"""Why did a V1 authenticated-verification run fail?  One owner, closed answers.

``v1-authenticated-verification.yml`` reduces a run to red/green.  Between
2026-10-19 and 2026-10-21 fifteen of its runs were red for at least six
unrelated reasons (spec drift, a hydration race, a stale selector, a session
lost to a backend restart, a backend stall, an unattributed public-League
failure), and the log could not tell a reader which -- the sanitized reporter
publishes an ``errorClass`` and nothing else, and ``errorClass`` calls "the UI
never showed up in 60 s" an *assertion*.  This module turns the sanitized
evidence a run already produces into one of nine categories, each with a
confidence and the fixed evidence codes that justify it.

It is a REPORTER.  It never changes a verdict, never retries, never hides a
failure: the job is still decided by "Fail the job on API/lane4/browser
verdicts" and the security acceptance step.  A classification that says
``unknown`` is the correct output when the evidence does not discriminate.

Categories
----------
``product_assertion``               the page/endpoint answered and the answer
                                     was wrong (or the spec is stale -- the two
                                     are not separable from outside)
``auth_session``                    the guest session was refused or died
``backend_timeout``                 the API / server side did not answer in time
``frontend_timeout``                the UI did not react in time while the
                                     backend looked healthy
``browser_infra``                   Chromium / Playwright / npm could not run
``deployment_revision_mismatch``    the spec's revision is not the revision
                                     production served, so no verdict about
                                     the revision under test exists
``resource_exhaustion``             memory / disk, runner or production
``cancellation``                    the run never produced a verdict
``unknown``                         the evidence does not discriminate

Posture -- the same as ``scripts/public_verification_report.py``: this repo,
its logs and its artifacts are PUBLIC, so the output is built from closed
vocabularies, counts, booleans, git SHAs and ISO instants only.  No message,
no URL, no response body, no cookie or token.  Any string that contains a
supplied secret, or looks like a ``jason_session=`` header, is dropped.

Do NOT attribute a failure to a backend restart because a restart happened
somewhere in the run.  A restart explains a test only when its observed
instant falls inside that test's own interval; a restart AFTER a failure is
a consequence candidate, not a cause, and is reported as such (run 39561535837:
three failures preceded the 07:53:55 restart by 3-6 minutes).

Stdlib only -- the GitHub runner installs nothing for this script.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "v1-failure-classification/v1"

PRODUCT_ASSERTION = "product_assertion"
AUTH_SESSION = "auth_session"
BACKEND_TIMEOUT = "backend_timeout"
FRONTEND_TIMEOUT = "frontend_timeout"
BROWSER_INFRA = "browser_infra"
DEPLOYMENT_REVISION_MISMATCH = "deployment_revision_mismatch"
RESOURCE_EXHAUSTION = "resource_exhaustion"
CANCELLATION = "cancellation"
UNKNOWN = "unknown"

CATEGORIES: tuple[str, ...] = (
    PRODUCT_ASSERTION,
    AUTH_SESSION,
    BACKEND_TIMEOUT,
    FRONTEND_TIMEOUT,
    BROWSER_INFRA,
    DEPLOYMENT_REVISION_MISMATCH,
    RESOURCE_EXHAUSTION,
    CANCELLATION,
    UNKNOWN,
)

CONFIDENCES = ("high", "medium", "low")

#: Mirrors ``SIGNAL_NAMES`` in tests/e2e/prod-auth-safe-reporter.js (parity test).
FAILURE_SIGNALS = frozenset(
    {
        "out_of_memory",
        "browser_launch_failed",
        "browser_closed",
        "network_error",
        "navigation_timeout",
        "api_request_timeout",
        "http_401_403",
        "http_5xx",
        "expect_timeout",
        "strict_mode_violation",
        "none",
    }
)

#: Signals that mean "a clock ran out", whatever ``errorClass`` says.
TIMEOUT_SIGNALS = frozenset({"navigation_timeout", "api_request_timeout", "expect_timeout"})

#: ``expect.timeout`` in tests/e2e/prod-auth.config.js (parity test).  A failure
#: that is an "assertion" yet lasted at least this long, with no signal to say
#: otherwise, ran out a web-first assertion's budget -- a wrong value fails at
#: once.  Used ONLY for logs published before ``failureSignal`` existed.
EXPECT_BUDGET_MS = 20_000
_EXPECT_BUDGET_SLACK_MS = 1_000

#: A failure faster than this, in a run of several, is a dead-session or
#: dead-browser signature rather than a slow page.
FAST_FAIL_MS = 2_000
FAST_FAIL_BURST = 3

#: A timeout cluster: failures this close to an API-contract timeout share its
#: dependency (same project, within this many tests, or within this window).
CLUSTER_TEST_DISTANCE = 3
CLUSTER_WINDOW_SECONDS = 600

#: A test that STARTED this soon after a restart ran against a cold backend
#: (``v1-authenticated-verification.yml`` measures 28-35 s cold /api/status
#: while the startup scrape runs).  Reported at LOW confidence, never above.
COLD_BACKEND_SECONDS = 240

#: Backend "healthy afterwards" thresholds -- the repo's own warm-wait rule.
HEALTHY_SECONDS = 10.0

_FAILED_STATUSES = frozenset({"failed", "timedOut", "interrupted"})
_STATUSES = frozenset({"passed", "failed", "timedOut", "interrupted", "skipped"})
_ERROR_CLASSES = frozenset({"assertion", "timeout", "error"})
_API_CONTRACT = re.compile(r"\b(?:GET|POST|PUT|DELETE)\s+/api/", re.IGNORECASE)
_SHA = re.compile(r"[0-9a-f]{7,40}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,120}")
_COOKIE_TEXT = re.compile(r"jason_session\s*=[^;\s\"']*", re.IGNORECASE)
_SECRET_MIN_LEN = 8

CANCELLATION_REASONS = frozenset(
    {
        "superseded_by_pending_concurrency",
        "job_timeout",
        "cancelled_in_flight",
        "cancelled_before_start",
        "unattributed",
    }
)


# ---------------------------------------------------------------------------
# Small validators: kinds, not trust.  A value of the wrong kind is dropped.
# ---------------------------------------------------------------------------


def _iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_out(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _sha(value: Any) -> str | None:
    if isinstance(value, str) and _SHA.fullmatch(value.strip().lower()):
        return value.strip().lower()
    return None


def _same_commit(a: str | None, b: str | None) -> bool | None:
    """True / False when both are known, None when either is not (unknown != false)."""
    if not a or not b:
        return None
    short = min(len(a), len(b))
    return a[:short] == b[:short]


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if math.isfinite(value) and value >= 0 else None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _enum(value: Any, allowed: Iterable[str]) -> str | None:
    return value if isinstance(value, str) and value in set(allowed) else None


# ---------------------------------------------------------------------------
# Normalised per-test record
# ---------------------------------------------------------------------------


def _normalise_test(raw: Mapping[str, Any], secrets: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    status = _enum(raw.get("status"), _STATUSES)
    if status is None:
        return None
    project = str(raw.get("project") or "").replace("prod-", "")
    project = project if project in {"desktop", "mobile"} else "other"
    file = str(raw.get("file") or "")
    file = file if _SAFE_NAME.fullmatch(file) else "unknown.spec.js"
    title = _scrub(str(raw.get("title") or ""), secrets)[:300]
    error_class = _enum(raw.get("errorClass"), _ERROR_CLASSES)
    signal = _enum(raw.get("failureSignal"), FAILURE_SIGNALS)
    started = _iso(raw.get("startedAt"))
    duration = _int(raw.get("durationMs"))
    return {
        "project": project,
        "file": file,
        "title": title,
        "status": status,
        "durationMs": duration,
        "errorClass": error_class,
        # None == the producer predates the signal; distinct from "none".
        "failureSignal": signal,
        "startedAt": started,
        "endedAt": (started + timedelta(milliseconds=duration))
        if started and duration is not None
        else None,
    }


def _scrub(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if len(secret) >= _SECRET_MIN_LEN:
            text = text.replace(secret, "[REDACTED]")
    return _COOKIE_TEXT.sub("jason_session=[REDACTED]", text)


def _is_timeout_like(t: Mapping[str, Any]) -> bool:
    """A clock ran out -- by status, by signal, or (legacy logs) by duration."""
    if t["status"] == "timedOut" or t["errorClass"] == "timeout":
        return True
    signal = t["failureSignal"]
    if signal in TIMEOUT_SIGNALS:
        return True
    if signal in (None, "none") and t["errorClass"] == "assertion":
        return _legacy_budget_exhausted(t)
    return False


def _legacy_budget_exhausted(t: Mapping[str, Any]) -> bool:
    duration = t["durationMs"]
    return duration is not None and duration >= EXPECT_BUDGET_MS - _EXPECT_BUDGET_SLACK_MS


def _is_api_contract(t: Mapping[str, Any]) -> bool:
    return bool(_API_CONTRACT.search(t["title"]))


# ---------------------------------------------------------------------------
# Run-level context
# ---------------------------------------------------------------------------


class _Context:
    """Facts about the whole run that individual failures are read against."""

    def __init__(self, evidence: Mapping[str, Any]) -> None:
        deployment = evidence.get("deployment") or {}
        self.expected = _sha(deployment.get("expectedCommit"))
        self.before = _sha(deployment.get("observedCommitBefore"))
        self.after = _sha(deployment.get("observedCommitAfter"))
        before_ok = _same_commit(self.expected, self.before)
        after_ok = _same_commit(self.expected, self.after)
        self.mismatch_before = before_ok is False
        self.mismatch_after = after_ok is False
        if self.mismatch_before or self.mismatch_after:
            self.revision = "mismatch"
        elif before_ok and after_ok is not False:
            self.revision = "match"
        elif after_ok and before_ok is not False:
            self.revision = "match"
        else:
            self.revision = "unknown"

        self.started_before = _iso(deployment.get("processStartedBefore"))
        self.started_after = _iso(deployment.get("processStartedAfter"))
        self.restart_at: datetime | None = None
        if self.started_before and self.started_after:
            if self.started_before == self.started_after:
                self.restart = "none"
            else:
                self.restart = "during_run"
                self.restart_at = self.started_after
        else:
            self.restart = "unknown"

        auth = evidence.get("auth") or {}
        self.login_exit = _int(auth.get("loginExit"))
        self.login_http = _int(auth.get("loginHttp"))
        self.pre_revoke_authenticated = _bool(auth.get("preRevokeAuthenticated"))
        self.login_control_authenticated = _bool(auth.get("loginControlAuthenticated"))

        backend = evidence.get("backend") or {}
        self.warm = _bool(backend.get("warm"))
        self.health_http = _int(backend.get("healthAfterHttp"))
        self.health_seconds = _float(backend.get("healthAfterSeconds"))

        browser = evidence.get("browser") or {}
        self.browser_step_outcome = _enum(
            browser.get("stepOutcome"), {"success", "failure", "cancelled", "skipped"}
        )
        self.report_present = _bool(browser.get("reportPresent"))

        resources = evidence.get("resources") or {}
        self.runner_oom = bool(_bool(resources.get("runnerOutOfMemory")))
        self.runner_disk_full = bool(_bool(resources.get("runnerDiskFull")))

        run = evidence.get("run") or {}
        self.conclusion = _enum(
            run.get("conclusion"), {"success", "failure", "cancelled", "skipped", "timed_out"}
        )
        self.cancellation_reason = _enum(run.get("cancellationReason"), CANCELLATION_REASONS)
        self.queue_wait_seconds = _int(run.get("queueWaitSeconds"))
        self.deploy_run_id = _int(run.get("deployRunId"))

    @property
    def backend_healthy_after(self) -> bool | None:
        if self.health_http is None or self.health_seconds is None:
            return None
        return self.health_http == 200 and self.health_seconds < HEALTHY_SECONDS


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _verdict(category: str, confidence: str, *evidence: str) -> dict[str, Any]:
    return {"category": category, "confidence": confidence, "evidence": list(evidence)}


def _fast_fail_burst_indexes(tests: Sequence[Mapping[str, Any]]) -> set[int]:
    """Indexes of failures inside a run of >= FAST_FAIL_BURST consecutive,
    same-project, sub-FAST_FAIL_MS thrown errors (ignoring skips between)."""
    flagged: set[int] = set()
    by_project: dict[str, list[int]] = {}
    for i, t in enumerate(tests):
        by_project.setdefault(t["project"], []).append(i)
    for indexes in by_project.values():
        run: list[int] = []
        for i in indexes + [None]:  # type: ignore[list-item]
            t = tests[i] if i is not None else None
            if t is not None and t["status"] == "skipped":
                continue
            fast = (
                t is not None
                and t["status"] in _FAILED_STATUSES
                and t["errorClass"] == "error"
                and t["durationMs"] is not None
                and t["durationMs"] < FAST_FAIL_MS
            )
            if fast:
                run.append(i)  # type: ignore[arg-type]
                continue
            if len(run) >= FAST_FAIL_BURST:
                flagged.update(run)
            run = []
    return flagged


def _co_timeout_with_api(index: int, tests: Sequence[Mapping[str, Any]]) -> bool:
    t = tests[index]
    for j, other in enumerate(tests):
        if j == index or other["status"] not in _FAILED_STATUSES:
            continue
        if not (_is_api_contract(other) and _is_timeout_like(other)):
            continue
        if t["startedAt"] and other["startedAt"]:
            if abs((t["startedAt"] - other["startedAt"]).total_seconds()) <= CLUSTER_WINDOW_SECONDS:
                return True
        elif t["project"] == other["project"] and abs(index - j) <= CLUSTER_TEST_DISTANCE:
            return True
    return False


def _overlaps_restart(t: Mapping[str, Any], ctx: _Context) -> bool:
    """DIRECT evidence only: the restart instant lies inside this test."""
    if ctx.restart_at is None or t["startedAt"] is None or t["endedAt"] is None:
        return False
    return (
        t["startedAt"] - timedelta(seconds=1)
        <= ctx.restart_at
        <= t["endedAt"] + timedelta(seconds=2)
    )


def _started_shortly_after_restart(t: Mapping[str, Any], ctx: _Context) -> bool:
    if ctx.restart_at is None or t["startedAt"] is None:
        return False
    delta = (t["startedAt"] - ctx.restart_at).total_seconds()
    return 0 <= delta <= COLD_BACKEND_SECONDS


def _classify_failure(
    index: int,
    tests: Sequence[Mapping[str, Any]],
    ctx: _Context,
    burst: set[int],
    previous: set[tuple[str, str, str]],
) -> dict[str, Any]:
    t = tests[index]
    signal = t["failureSignal"] or "none"
    legacy = t["failureSignal"] is None
    evidence: list[str] = []

    # 1. A verdict about the wrong revision is not a verdict about this one.
    if ctx.revision == "mismatch":
        return _verdict(
            DEPLOYMENT_REVISION_MISMATCH,
            "high" if ctx.mismatch_before else "medium",
            "production_commit_differs_from_spec_commit_before_suite"
            if ctx.mismatch_before
            else "production_commit_differs_from_spec_commit_after_suite",
        )

    # 2. The machine, not the product.
    if signal == "out_of_memory":
        return _verdict(RESOURCE_EXHAUSTION, "high", "signal_out_of_memory")
    if signal in {"browser_launch_failed", "browser_closed"}:
        return _verdict(BROWSER_INFRA, "high", f"signal_{signal}")
    if (ctx.runner_oom or ctx.runner_disk_full) and t["errorClass"] != "assertion":
        return _verdict(RESOURCE_EXHAUSTION, "medium", "runner_oom_or_disk_full_reported")

    # 3. A restart explains a test only if it happened INSIDE that test.
    if _overlaps_restart(t, ctx):
        return _verdict(BACKEND_TIMEOUT, "high", "backend_restart_instant_inside_test")
    if ctx.restart == "during_run":
        evidence.append("restart_in_run_but_not_inside_this_test")
        if t["endedAt"] and ctx.restart_at and ctx.restart_at > t["endedAt"]:
            evidence.append("restart_followed_this_failure")

    # 4. Session.
    if signal == "http_401_403":
        return _verdict(AUTH_SESSION, "high", "signal_http_401_403")
    if index in burst:
        if ctx.pre_revoke_authenticated is False:
            return _verdict(
                AUTH_SESSION,
                "medium",
                "fast_fail_burst",
                "session_unauthenticated_at_pre_revoke_probe",
            )
        evidence.append("fast_fail_burst")

    # 5. Server side said so.
    if signal == "http_5xx":
        return _verdict(BACKEND_TIMEOUT, "high", "signal_http_5xx", *evidence)
    if signal == "network_error":
        return _verdict(BACKEND_TIMEOUT, "medium", "signal_network_error", *evidence)
    if signal == "api_request_timeout":
        return _verdict(BACKEND_TIMEOUT, "high", "signal_api_request_timeout", *evidence)

    # 6. A clock ran out.
    if _is_timeout_like(t):
        if legacy and t["errorClass"] == "assertion":
            evidence.append("duration_at_or_above_expect_budget")
        if _is_api_contract(t):
            return _verdict(BACKEND_TIMEOUT, "medium", "api_contract_test_timed_out", *evidence)
        if _co_timeout_with_api(index, tests):
            return _verdict(
                BACKEND_TIMEOUT, "medium", "timed_out_alongside_api_contract_timeout", *evidence
            )
        if _started_shortly_after_restart(t, ctx):
            return _verdict(
                BACKEND_TIMEOUT,
                "low",
                "started_within_cold_backend_window_after_restart",
                *evidence,
            )
        if ctx.backend_healthy_after is False:
            return _verdict(BACKEND_TIMEOUT, "low", "backend_unhealthy_after_suite", *evidence)
        if ctx.backend_healthy_after is True and ctx.warm is not False:
            return _verdict(
                FRONTEND_TIMEOUT,
                "low",
                "backend_healthy_after_suite",
                "no_api_timeout_in_run",
                *evidence,
            )
        return _verdict(UNKNOWN, "low", "timeout_surface_ambiguous", *evidence)

    # 7. The page answered; the answer was wrong (or the spec is stale).
    if t["errorClass"] == "assertion" or signal == "strict_mode_violation":
        key = (t["project"], t["file"], t["title"])
        if key in previous:
            return _verdict(PRODUCT_ASSERTION, "high", "same_test_failed_previous_run", *evidence)
        return _verdict(PRODUCT_ASSERTION, "medium", "assertion_without_timeout_signal", *evidence)

    return _verdict(UNKNOWN, "low", "thrown_error_without_signal", *evidence)


def _classify_run_stages(ctx: _Context, tests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Failures that happen before / outside any test."""
    stages: list[dict[str, Any]] = []
    if ctx.login_exit not in (None, 0):
        if ctx.login_http in (401, 403):
            verdict = _verdict(AUTH_SESSION, "high", "login_refused_http_401_403")
        elif ctx.login_http is not None and ctx.login_http >= 500:
            verdict = _verdict(BACKEND_TIMEOUT, "high", "login_answered_http_5xx")
        elif ctx.login_http == 0:
            verdict = _verdict(BACKEND_TIMEOUT, "medium", "login_unreachable_or_timed_out")
        elif ctx.login_http is None:
            # The login step does not yet record its HTTP status: unknown is
            # not "unreachable", and guessing would invent a backend fault.
            verdict = _verdict(UNKNOWN, "low", "login_failed_status_not_captured")
        else:
            verdict = _verdict(UNKNOWN, "low", "login_failed_unclassified")
        stages.append({"stage": "login", **verdict})
    if ctx.browser_step_outcome == "failure" and not tests and ctx.report_present is not True:
        stages.append(
            {
                "stage": "browser_setup",
                **_verdict(BROWSER_INFRA, "medium", "browser_step_failed_before_any_test_reported"),
            }
        )
    return stages


def _dominant(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    # Most frequent; ties resolved by the order of CATEGORIES (stable, reviewable).
    return max(CATEGORIES, key=lambda c: (counts.get(c, 0), -CATEGORIES.index(c)))


def classify(evidence: Mapping[str, Any], *, secrets: Sequence[str] = ()) -> dict[str, Any]:
    """Classify one run.  ``evidence`` is the sanitized bundle described in the
    module docstring; unknown keys are ignored and wrong-kind values dropped."""
    ctx = _Context(evidence)
    tests = [t for t in (_normalise_test(r, secrets) for r in evidence.get("tests") or []) if t]
    previous = {
        (
            str(p.get("project", "")).replace("prod-", ""),
            str(p.get("file", "")),
            _scrub(str(p.get("title", "")), secrets)[:300],
        )
        for p in (evidence.get("previousFailures") or [])
        if isinstance(p, Mapping)
    }

    burst = _fast_fail_burst_indexes(tests)
    failures: list[dict[str, Any]] = []
    for i, t in enumerate(tests):
        if t["status"] not in _FAILED_STATUSES:
            continue
        verdict = _classify_failure(i, tests, ctx, burst, previous)
        failures.append(
            {
                "project": t["project"],
                "file": t["file"],
                "title": t["title"],
                "status": t["status"],
                "durationMs": t["durationMs"],
                "errorClass": t["errorClass"],
                "failureSignal": t["failureSignal"],
                "startedAt": _iso_out(t["startedAt"]),
                **verdict,
            }
        )

    stages = _classify_run_stages(ctx, tests)
    counts: Counter[str] = Counter(f["category"] for f in failures)
    counts.update(s["category"] for s in stages)

    cancelled = ctx.conclusion == "cancelled"
    if cancelled:
        reason = ctx.cancellation_reason or "unattributed"
        stages.append(
            {
                "stage": "run",
                **_verdict(
                    CANCELLATION,
                    "high" if reason != "unattributed" else "medium",
                    f"cancelled_{reason}",
                ),
            }
        )
        counts[CANCELLATION] += 1

    passed = sum(1 for t in tests if t["status"] == "passed")
    skipped = sum(1 for t in tests if t["status"] == "skipped")
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "sanitized": True,
        "gateEffect": "none: report-only; the job verdict is decided by the existing verdict and security steps",
        "run": {
            "conclusion": ctx.conclusion,
            "deployRunId": ctx.deploy_run_id,
            "queueWaitSeconds": ctx.queue_wait_seconds,
            "cancellationReason": ctx.cancellation_reason if cancelled else None,
        },
        "deployment": {
            "revision": ctx.revision,
            "expectedCommit": ctx.expected,
            "observedCommitBefore": ctx.before,
            "observedCommitAfter": ctx.after,
            "restart": {
                "status": ctx.restart,
                "processStartedBefore": _iso_out(ctx.started_before),
                "processStartedAfter": _iso_out(ctx.started_after),
                # Restart is only ever ATTRIBUTED through per-failure
                # `backend_restart_instant_inside_test` evidence.
                "failuresInsideRestart": sum(
                    1 for f in failures if "backend_restart_instant_inside_test" in f["evidence"]
                ),
                "failuresBeforeRestart": sum(
                    1 for f in failures if "restart_followed_this_failure" in f["evidence"]
                ),
            },
        },
        "tests": {
            "total": len(tests),
            "passed": passed,
            "skipped": skipped,
            "failed": len(failures),
        },
        "counts": {c: counts[c] for c in CATEGORIES if counts.get(c)},
        "runCategory": _dominant(counts) if counts else "none",
        "stages": stages,
        "failures": failures,
        "authenticatedVerification": _authenticated_verification(ctx, tests, failures, stages),
    }
    return _assert_public(report, secrets)


def _authenticated_verification(
    ctx: _Context,
    tests: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    stages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """What THIS run can honestly claim -- never more (see docs/ops/V1_VERIFICATION_TAXONOMY.md).

    ``authenticated_verification_passed`` needs a green run on the revision
    that was meant to be verified, with the process unrestarted for the whole
    run.  A green run whose revision or restart state cannot be established is
    NOT upgraded: ``authenticated_checks_passed_unattributed`` says the checks
    passed but cannot be pinned to the intended revision.
    """
    blockers: list[str] = []
    if ctx.conclusion != "success":
        blockers.append(f"run_conclusion_{ctx.conclusion or 'unknown'}")
    if failures or stages:
        blockers.append("failures_present")
    if not any(t["status"] == "passed" for t in tests):
        blockers.append("no_test_passed")
    if ctx.revision == "mismatch":
        blockers.append("revision_mismatch")
    if ctx.restart == "during_run":
        blockers.append("backend_restarted_during_run")
    if blockers:
        return {"level": "not_established", "blockers": blockers}
    unproven: list[str] = []
    if ctx.revision == "unknown":
        unproven.append("revision_unproven")
    if ctx.restart == "unknown":
        unproven.append("restart_state_unknown")
    if unproven:
        return {"level": "authenticated_checks_passed_unattributed", "blockers": unproven}
    return {"level": "authenticated_verification_passed", "blockers": []}


# ---------------------------------------------------------------------------
# Public-output guard
# ---------------------------------------------------------------------------


def _assert_public(report: dict[str, Any], secrets: Sequence[str]) -> dict[str, Any]:
    """Defence in depth: nothing secret-shaped leaves, whatever produced it."""
    live = [s for s in secrets if len(s) >= _SECRET_MIN_LEN]

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            if any(s in value for s in live) or _COOKIE_TEXT.search(value):
                return "[REDACTED]"
            return value
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(report)


# ---------------------------------------------------------------------------
# Inputs: the sanitized report, historic console logs, GitHub run records
# ---------------------------------------------------------------------------


def tests_from_safe_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    tests = report.get("tests") if isinstance(report, Mapping) else None
    return [t for t in tests or [] if isinstance(t, Mapping)]  # type: ignore[misc]


_LOG_LINE = re.compile(
    r"(?:(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z\s+)?"
    r"(?P<tag>ok|skip|FAIL|TIMEOUT|INTERRUPTED) \[prod-(?P<project>\w+)\] "
    r"(?P<file>[\w.\-]+) \S+ (?P<title>.*?) \((?P<ms>[\d*]+)ms\)"
    r"(?: \[(?P<cls>assertion|timeout|error)\])?"
    r"(?: signal=(?P<signal>\w+))?\s*$"
)
_TAG_STATUS = {
    "ok": "passed",
    "skip": "skipped",
    "FAIL": "failed",
    "TIMEOUT": "timedOut",
    "INTERRUPTED": "interrupted",
}


def tests_from_console_log(text: str) -> list[dict[str, Any]]:
    """Reconstruct per-test records from the sanitized reporter's console lines
    (``gh run view --log`` output included).  The line timestamp is the test's
    END, so ``startedAt`` is derived; a masked duration (GitHub replaces digit
    runs that equal a secret fragment with ``***``) stays unknown, never 0."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _LOG_LINE.search(line)
        if not m:
            continue
        ms_text = m.group("ms")
        duration = int(ms_text) if ms_text.isdigit() else None
        ended = _iso(m.group("ts") + "Z") if m.group("ts") else None
        started = (
            ended - timedelta(milliseconds=duration) if ended and duration is not None else None
        )
        out.append(
            {
                "project": m.group("project"),
                "file": m.group("file"),
                "title": m.group("title"),
                "status": _TAG_STATUS[m.group("tag")],
                "durationMs": duration,
                "errorClass": m.group("cls"),
                "failureSignal": m.group("signal"),
                "startedAt": _iso_out(started),
            }
        )
    return out


def classify_run_record(
    *,
    conclusion: str | None,
    annotation_messages: Sequence[str] = (),
    steps_ran: bool | None = None,
) -> dict[str, Any]:
    """Cancellation attribution from GitHub's own run/job record (read-only).

    A job that GitHub cancels while it is still *pending* in a concurrency
    group has no log at all; the only direct evidence is the job annotation
    GitHub attaches.  ``steps_ran`` is False when no step started.
    """
    if conclusion == "skipped":
        return {"conclusion": "skipped", "category": None, "reason": "not_a_verification_run"}
    if conclusion != "cancelled":
        return {"conclusion": conclusion, "category": None, "reason": None}
    text = " ".join(annotation_messages).lower()
    if "higher priority waiting request" in text:
        reason = "superseded_by_pending_concurrency"
    elif "maximum execution time" in text or "exceeded the maximum" in text:
        reason = "job_timeout"
    elif steps_ran is False:
        reason = "cancelled_before_start"
    elif steps_ran is True:
        reason = "cancelled_in_flight"
    else:
        reason = "unattributed"
    return {"conclusion": "cancelled", "category": CANCELLATION, "reason": reason}


# ---------------------------------------------------------------------------
# Step summary + CLI
# ---------------------------------------------------------------------------


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = ["### V1 failure classification (report-only)", ""]
    dep = report["deployment"]
    lines.append(
        f"Run category: `{report['runCategory']}` - revision `{dep['revision']}` - "
        f"backend restart `{dep['restart']['status']}`"
    )
    level = report["authenticatedVerification"]["level"]
    lines.append(f"Authenticated verification established by this run: `{level}`")
    if report["counts"]:
        lines += ["", "| category | count |", "|---|---|"]
        lines += [f"| `{c}` | {n} |" for c, n in report["counts"].items()]
    for stage in report["stages"]:
        lines.append(
            f"- stage `{stage['stage']}`: `{stage['category']}` ({stage['confidence']}) {stage['evidence']}"
        )
    shown = report["failures"][:40]
    if shown:
        lines += [
            "",
            "| project | spec | category | confidence | evidence |",
            "|---|---|---|---|---|",
        ]
        for f in shown:
            lines.append(
                f"| {f['project']} | {f['file']} | `{f['category']}` | {f['confidence']} | {', '.join(f['evidence'])} |"
            )
        if len(report["failures"]) > len(shown):
            lines.append(f"\n... {len(report['failures']) - len(shown)} more in the artifact")
    return "\n".join(lines) + "\n"


def _read_json(path: str | None) -> Any:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_secrets(paths: Sequence[str]) -> list[str]:
    secrets: list[str] = []
    for path in paths:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            secrets.append(value)
    return secrets


def _probe_authenticated(probe: Any) -> bool | None:
    if isinstance(probe, Mapping):
        if probe.get("probeError") is True:
            return None
        return _bool(probe.get("authenticated"))
    return None


def evidence_from_environment(
    env: Mapping[str, str],
    *,
    safe_report: Any,
    probe_login: Any,
    probe_pre_revoke: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the sanitized evidence bundle from workflow-provided values.

    Every field is a kind-checked scalar; nothing is copied through verbatim.
    """

    def e(name: str) -> str:
        return (env.get(name) or "").strip()

    now = now or datetime.now(timezone.utc)
    started = _iso(e("V1_JOB_STARTED_AT"))
    deploy_done = _iso(e("V1_DEPLOY_COMPLETED_AT"))
    queue_wait = int((started - deploy_done).total_seconds()) if started and deploy_done else None
    browser_outcome = e("V1_BROWSER_OUTCOME") or None
    tests = tests_from_safe_report(safe_report) if safe_report else []
    conclusion = e("V1_JOB_STATUS") or None
    # The Playwright step records its exit code instead of failing, so
    # ``job.status`` is still "success" when this runs even though the verdict
    # step that follows will fail the job.  Report what that step will decide.
    if conclusion == "success" and any(t.get("status") in _FAILED_STATUSES for t in tests):
        conclusion = "failure"
    return {
        "run": {
            "conclusion": conclusion,
            "deployRunId": _int(int(e("V1_DEPLOY_RUN_ID")))
            if e("V1_DEPLOY_RUN_ID").isdigit()
            else None,
            "queueWaitSeconds": queue_wait if queue_wait is None or queue_wait >= 0 else None,
        },
        "deployment": {
            "expectedCommit": e("V1_EXPECTED_SHA") or None,
            "observedCommitBefore": e("V1_COMMIT_BEFORE") or None,
            "observedCommitAfter": e("V1_COMMIT_AFTER") or None,
            "processStartedBefore": e("V1_STARTED_BEFORE") or None,
            "processStartedAfter": e("V1_STARTED_AFTER") or None,
        },
        "auth": {
            "loginExit": 0
            if e("V1_LOGIN_OUTCOME") == "success"
            else (1 if e("V1_LOGIN_OUTCOME") == "failure" else None),
            "loginControlAuthenticated": _probe_authenticated(probe_login),
            "preRevokeAuthenticated": _probe_authenticated(probe_pre_revoke),
        },
        "backend": {"warm": {"true": True, "false": False}.get(e("V1_BACKEND_WARM"))},
        "browser": {"stepOutcome": browser_outcome, "reportPresent": bool(tests)},
        "tests": tests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "classify", help="classify the current run from workflow-provided values (env V1_*)"
    )
    run.add_argument("--safe-report", default="tests/e2e/prod-auth-results.json")
    run.add_argument("--probe-login")
    run.add_argument("--probe-pre-revoke")
    run.add_argument("--secret-file", action="append", default=[])
    run.add_argument("--out", required=True)
    run.add_argument("--step-summary")

    log = sub.add_parser(
        "from-log", help="classify a saved console log / `gh run view --log` (offline analysis)"
    )
    log.add_argument("--log", required=True)
    log.add_argument(
        "--evidence", help="optional JSON evidence bundle (deployment/auth/backend/run)"
    )
    log.add_argument("--previous-log", help="previous run's log, to mark recurring failures")
    log.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "classify":
        secrets = _read_secrets(args.secret_file)
        evidence = evidence_from_environment(
            os.environ,
            safe_report=_read_json(args.safe_report),
            probe_login=_read_json(args.probe_login),
            probe_pre_revoke=_read_json(args.probe_pre_revoke),
        )
        report = classify(evidence, secrets=secrets)
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        if args.step_summary:
            with open(args.step_summary, "a", encoding="utf-8") as handle:
                handle.write(render_markdown(report))
        print(f"V1 failure classification: run={report['runCategory']} counts={report['counts']}")
        return 0

    text = Path(args.log).read_text(encoding="utf-8", errors="replace")
    evidence = _read_json(args.evidence) or {}
    evidence["tests"] = tests_from_console_log(text)
    if args.previous_log:
        prev = tests_from_console_log(
            Path(args.previous_log).read_text(encoding="utf-8", errors="replace")
        )
        evidence["previousFailures"] = [t for t in prev if t["status"] in _FAILED_STATUSES]
    report = classify(evidence)
    payload = json.dumps(report, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
