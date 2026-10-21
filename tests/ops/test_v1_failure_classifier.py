"""V1 failure classifier (scripts/v1_failure_classifier.py).

Every scenario below is a shape that actually occurred in V1 runs between
2026-10-19 and 2026-10-21 (run ids in the docstrings), reduced to the sanitized
evidence the workflow produces.  The classifier is a REPORTER: nothing here
asserts anything about a gate, and ``unknown`` is a legitimate answer.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "v1_failure_classifier", REPO_ROOT / "scripts" / "v1_failure_classifier.py"
)
vfc = importlib.util.module_from_spec(_SPEC)
sys.modules["v1_failure_classifier"] = vfc
_SPEC.loader.exec_module(vfc)

COOKIE = "c0ffee0123456789abcdef0123456789"
TOKEN = "tok_9f8e7d6c5b4a39281706f5e4d3c2b1a0"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _t(
    title="t",
    *,
    status="failed",
    cls="assertion",
    signal=None,
    ms=5000,
    started="2026-10-21T07:50:00Z",
    project="prod-desktop",
    file="x.spec.js",
):
    return {
        "project": project,
        "file": file,
        "title": title,
        "status": status,
        "errorClass": cls,
        "failureSignal": signal,
        "durationMs": ms,
        "startedAt": started,
    }


def _run(tests, **overrides):
    evidence = {"run": {"conclusion": "failure"}, "tests": tests}
    evidence.update(overrides)
    return vfc.classify(evidence, secrets=[COOKIE, TOKEN])


def _only(report):
    assert len(report["failures"]) == 1
    return report["failures"][0]


# ---------------------------------------------------------------------------
# The taxonomy itself
# ---------------------------------------------------------------------------


def test_the_nine_categories_are_exactly_the_ones_the_owner_asked_for():
    assert set(vfc.CATEGORIES) == {
        "product_assertion",
        "auth_session",
        "backend_timeout",
        "frontend_timeout",
        "browser_infra",
        "deployment_revision_mismatch",
        "resource_exhaustion",
        "cancellation",
        "unknown",
    }
    assert len(vfc.CATEGORIES) == len(set(vfc.CATEGORIES))


def test_every_verdict_uses_a_declared_category_and_confidence():
    scenarios = [
        _run([_t(signal="http_5xx")]),
        _run([_t(signal="browser_closed", cls="error")]),
        _run([_t(signal="out_of_memory", cls="error")]),
        _run([_t(signal="http_401_403")]),
        _run([_t(cls="error")]),
        _run([_t()]),
    ]
    for report in scenarios:
        for failure in report["failures"]:
            assert failure["category"] in vfc.CATEGORIES
            assert failure["confidence"] in vfc.CONFIDENCES


# ---------------------------------------------------------------------------
# Product assertion
# ---------------------------------------------------------------------------


def test_a_repeated_assertion_is_high_confidence_a_first_one_is_medium():
    """Runs 39235281344 .. 39311556615: the same 12 specs, six deploys running."""
    # 31.5 s is a web-first assertion that ran out its budget, not a wrong value.
    first = _only(_run([_t("arbitrage", ms=31500)]))
    assert first["category"] != "product_assertion"

    quick = _t("draft capital", ms=900)
    medium = _only(_run([quick]))
    assert (medium["category"], medium["confidence"]) == ("product_assertion", "medium")

    previous = [{"project": "prod-desktop", "file": "x.spec.js", "title": "draft capital"}]
    high = _only(_run([quick], previousFailures=previous))
    assert (high["category"], high["confidence"]) == ("product_assertion", "high")
    assert "same_test_failed_previous_run" in high["evidence"]


def test_a_wrong_value_is_not_laundered_into_a_timeout():
    only = _only(_run([_t(signal="none", ms=1200)]))
    assert only["category"] == "product_assertion"


# ---------------------------------------------------------------------------
# Timeouts: backend vs frontend, and the legacy "assertion that lasted 64 s"
# ---------------------------------------------------------------------------


def test_an_assertion_that_ran_out_a_ui_budget_is_a_timeout_not_a_wrong_value():
    """Run 39561535837 published three ~64 s ``[assertion]`` failures."""
    report = _run([_t("previews", ms=64109, signal="expect_timeout")])
    only = _only(report)
    assert only["errorClass"] == "assertion"
    assert only["category"] != "product_assertion"


def test_legacy_logs_without_a_signal_use_the_declared_expect_budget():
    legacy = _only(_run([_t(ms=vfc.EXPECT_BUDGET_MS + 11000, signal=None)]))
    assert "duration_at_or_above_expect_budget" in legacy["evidence"]
    assert legacy["category"] != "product_assertion"
    fast = _only(_run([_t(ms=vfc.EXPECT_BUDGET_MS - 5000, signal=None)]))
    assert fast["category"] == "product_assertion"


def test_an_api_contract_timeout_is_backend_and_drags_its_cluster_with_it():
    """Run 39561535837: Sharp Tracker (GET /api/sharp/market) 91 s, then the public previews."""
    tests = [
        _t(
            "Sharp Tracker matches GET /api/sharp/market field-for-field",
            status="failed",
            cls="timeout",
            ms=91418,
            started="2026-10-21T07:48:35Z",
        ),
        _t(
            "previews tab renders",
            ms=64109,
            signal="expect_timeout",
            started="2026-10-21T07:50:07Z",
        ),
        _t("older slate", status="passed", cls=None, ms=2000, started="2026-10-21T07:56:00Z"),
    ]
    report = _run(tests)
    first, second = report["failures"]
    assert (first["category"], first["confidence"]) == ("backend_timeout", "medium")
    assert "api_contract_test_timed_out" in first["evidence"]
    assert second["category"] == "backend_timeout"
    assert "timed_out_alongside_api_contract_timeout" in second["evidence"]


def test_a_lone_ui_timeout_with_a_healthy_backend_is_frontend_low_confidence():
    report = _run(
        [_t("tab renders", ms=65000, signal="expect_timeout")],
        backend={"warm": True, "healthAfterHttp": 200, "healthAfterSeconds": 0.3},
    )
    only = _only(report)
    assert (only["category"], only["confidence"]) == ("frontend_timeout", "low")


def test_a_lone_ui_timeout_with_no_backend_evidence_stays_unknown():
    only = _only(_run([_t("tab renders", ms=65000, signal="expect_timeout")]))
    assert only["category"] == "unknown"
    assert "timeout_surface_ambiguous" in only["evidence"]


def test_server_side_signals_are_backend():
    assert _only(_run([_t(signal="http_5xx", ms=300)]))["category"] == "backend_timeout"
    assert (
        _only(_run([_t(signal="network_error", cls="error", ms=300)]))["category"]
        == "backend_timeout"
    )
    assert (
        _only(_run([_t(signal="api_request_timeout", cls="timeout", ms=30000)]))["category"]
        == "backend_timeout"
    )


# ---------------------------------------------------------------------------
# Restart attribution: direct evidence only
# ---------------------------------------------------------------------------

_RESTART = {
    "processStartedBefore": "2026-10-21T07:17:42.799216+00:00",
    "processStartedAfter": "2026-10-21T07:53:55.856458+00:00",
}


def test_a_restart_inside_a_test_is_attributed_to_that_test_only():
    """Run 39561535837: restart at 07:53:55 -- inside the 07:52:17..07:55:17 test."""
    tests = [
        _t("before", cls="error", ms=1500, started="2026-10-21T07:50:00Z"),
        _t(
            "straddles", status="timedOut", cls="timeout", ms=180029, started="2026-10-21T07:52:17Z"
        ),
    ]
    report = _run(tests, deployment=_RESTART)
    before, straddles = report["failures"]
    assert straddles["category"] == "backend_timeout"
    assert straddles["evidence"] == ["backend_restart_instant_inside_test"]
    assert "backend_restart_instant_inside_test" not in before["evidence"]
    assert "restart_followed_this_failure" in before["evidence"]
    restart = report["deployment"]["restart"]
    assert restart["status"] == "during_run"
    assert restart["failuresInsideRestart"] == 1
    assert restart["failuresBeforeRestart"] == 1


def test_a_restart_somewhere_in_the_run_does_not_taint_an_unrelated_failure():
    report = _run([_t("wrong value", ms=900, started="2026-10-21T07:40:00Z")], deployment=_RESTART)
    only = _only(report)
    assert only["category"] == "product_assertion"
    assert "restart_followed_this_failure" in only["evidence"]


def test_without_test_timing_a_restart_is_not_attributable_at_all():
    test = _t("x", status="timedOut", cls="timeout", ms=180000, started=None)
    only = _only(_run([test], deployment=_RESTART))
    assert "backend_restart_instant_inside_test" not in only["evidence"]
    assert only["category"] == "unknown"  # a 180 s timeout with nothing to discriminate it


def test_a_test_that_started_just_after_a_restart_is_flagged_low_confidence_only():
    test = _t("cold", status="timedOut", cls="timeout", ms=180000, started="2026-10-21T07:54:30Z")
    only = _only(_run([test], deployment=_RESTART))
    assert (only["category"], only["confidence"]) == ("backend_timeout", "low")
    assert "started_within_cold_backend_window_after_restart" in only["evidence"]


def test_unknown_restart_state_is_not_reported_as_no_restart():
    unknown = _run([_t()], deployment={"processStartedBefore": "2026-10-21T07:17:42Z"})
    assert unknown["deployment"]["restart"]["status"] == "unknown"
    same = _run(
        [_t()],
        deployment={
            "processStartedBefore": "2026-10-21T07:17:42Z",
            "processStartedAfter": "2026-10-21T07:17:42Z",
        },
    )
    assert same["deployment"]["restart"]["status"] == "none"


# ---------------------------------------------------------------------------
# Auth / session
# ---------------------------------------------------------------------------


def _burst(n=5, ms=500):
    return [
        _t(f"private {i}", cls="error", ms=ms, started=f"2026-10-19T08:4{i}:00Z") for i in range(n)
    ]


def test_a_dead_session_burst_needs_the_pre_revoke_control_to_be_called_auth():
    """Run 39221318435: after ~27.6 min every private spec failed in ~0.5 s."""
    with_control = _run(_burst(), auth={"preRevokeAuthenticated": False})
    assert {f["category"] for f in with_control["failures"]} == {"auth_session"}
    assert all(f["confidence"] == "medium" for f in with_control["failures"])

    without_control = _run(_burst())
    assert {f["category"] for f in without_control["failures"]} == {"unknown"}
    assert all("fast_fail_burst" in f["evidence"] for f in without_control["failures"])

    still_authenticated = _run(_burst(), auth={"preRevokeAuthenticated": True})
    assert {f["category"] for f in still_authenticated["failures"]} == {"unknown"}


def test_two_fast_failures_are_not_a_burst():
    report = _run(_burst(2), auth={"preRevokeAuthenticated": False})
    assert {f["category"] for f in report["failures"]} == {"unknown"}


def test_a_received_401_or_403_is_auth_and_needs_no_burst():
    only = _only(_run([_t(signal="http_401_403", ms=300)]))
    assert (only["category"], only["confidence"]) == ("auth_session", "high")


def test_login_failure_is_classified_by_its_status_and_unknown_status_stays_unknown():
    refused = _run([], auth={"loginExit": 1, "loginHttp": 403})
    assert refused["stages"][0]["category"] == "auth_session"
    server = _run([], auth={"loginExit": 1, "loginHttp": 502})
    assert server["stages"][0]["category"] == "backend_timeout"
    unreachable = _run([], auth={"loginExit": 1, "loginHttp": 0})
    assert unreachable["stages"][0]["category"] == "backend_timeout"
    uncaptured = _run([], auth={"loginExit": 1})
    assert uncaptured["stages"][0]["category"] == "unknown"
    assert "login_failed_status_not_captured" in uncaptured["stages"][0]["evidence"]


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


def test_browser_and_memory_signals_map_to_their_categories():
    assert (
        _only(_run([_t(signal="browser_closed", cls="error", ms=50)]))["category"]
        == "browser_infra"
    )
    assert (
        _only(_run([_t(signal="browser_launch_failed", cls="error", ms=50)]))["category"]
        == "browser_infra"
    )
    assert (
        _only(_run([_t(signal="out_of_memory", cls="error", ms=50)]))["category"]
        == "resource_exhaustion"
    )


def test_runner_disk_or_memory_pressure_only_claims_non_assertion_failures():
    pressured = {"runnerOutOfMemory": True}
    assert (
        _only(_run([_t(cls="error", ms=80)], resources=pressured))["category"]
        == "resource_exhaustion"
    )
    assert (
        _only(_run([_t(cls="assertion", ms=900)], resources=pressured))["category"]
        == "product_assertion"
    )


def test_a_browser_step_that_died_before_reporting_is_browser_infra():
    report = _run([], browser={"stepOutcome": "failure", "reportPresent": False})
    assert report["stages"][0]["category"] == "browser_infra"
    ran = _run([_t()], browser={"stepOutcome": "failure", "reportPresent": True})
    assert all(s["stage"] != "browser_setup" for s in ran["stages"])


# ---------------------------------------------------------------------------
# Deployment revision
# ---------------------------------------------------------------------------


def test_a_revision_mismatch_means_no_verdict_about_the_revision_under_test():
    """Run 39552411042: spec ref 85ee0562, production serving a later deploy after a 86 min queue."""
    dep = {"expectedCommit": SHA_A, "observedCommitBefore": SHA_B, "observedCommitAfter": SHA_B}
    report = _run([_t(ms=900), _t("other", cls="error", ms=80)], deployment=dep)
    assert {f["category"] for f in report["failures"]} == {"deployment_revision_mismatch"}
    assert all(f["confidence"] == "high" for f in report["failures"])
    assert report["deployment"]["revision"] == "mismatch"

    late = _run(
        [_t()],
        deployment={
            "expectedCommit": SHA_A,
            "observedCommitBefore": SHA_A,
            "observedCommitAfter": SHA_B,
        },
    )
    assert _only(late)["confidence"] == "medium"


def test_short_and_full_shas_compare_by_prefix_and_unknown_is_not_a_mismatch():
    assert vfc._same_commit("85ee0562", SHA_A.replace("a" * 8, "85ee0562", 1)) is True
    assert vfc._same_commit("85ee0562", "9e3c52fd") is False
    assert vfc._same_commit(None, SHA_A) is None
    report = _run([_t(ms=900)], deployment={"expectedCommit": SHA_A})
    assert report["deployment"]["revision"] == "unknown"
    assert _only(report)["category"] == "product_assertion"


def test_a_malformed_commit_is_dropped_not_compared():
    report = _run(
        [_t(ms=900)], deployment={"expectedCommit": "not-a-sha", "observedCommitBefore": SHA_A}
    )
    assert report["deployment"]["expectedCommit"] is None
    assert report["deployment"]["revision"] == "unknown"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_displacement_by_a_pending_concurrency_request_is_named_from_githubs_own_annotation():
    """Runs 39592500560 / 39545078157 / 39433335744 / 39401129952."""
    msg = "Canceling since a higher priority waiting request for production-deploy exists"
    got = vfc.classify_run_record(
        conclusion="cancelled", annotation_messages=[msg], steps_ran=False
    )
    assert got == {
        "conclusion": "cancelled",
        "category": "cancellation",
        "reason": "superseded_by_pending_concurrency",
    }


def test_other_cancellations_are_not_guessed_to_be_displacement():
    assert (
        vfc.classify_run_record(conclusion="cancelled", steps_ran=False)["reason"]
        == "cancelled_before_start"
    )
    assert (
        vfc.classify_run_record(conclusion="cancelled", steps_ran=True)["reason"]
        == "cancelled_in_flight"
    )
    assert vfc.classify_run_record(conclusion="cancelled")["reason"] == "unattributed"
    timeout = vfc.classify_run_record(
        conclusion="cancelled",
        annotation_messages=["The job has exceeded the maximum execution time of 50m0s"],
    )
    assert timeout["reason"] == "job_timeout"


def test_a_skipped_v1_run_is_not_a_failure_and_a_pass_has_no_category():
    assert vfc.classify_run_record(conclusion="skipped")["category"] is None
    assert vfc.classify_run_record(conclusion="success")["category"] is None


def test_a_cancelled_run_report_carries_the_cancellation_category():
    report = vfc.classify(
        {
            "run": {
                "conclusion": "cancelled",
                "cancellationReason": "superseded_by_pending_concurrency",
            }
        }
    )
    assert report["runCategory"] == "cancellation"
    assert report["authenticatedVerification"]["level"] == "not_established"


# ---------------------------------------------------------------------------
# What a run may claim (docs/ops/V1_VERIFICATION_TAXONOMY.md)
# ---------------------------------------------------------------------------


def _green(**overrides):
    base = {
        "run": {"conclusion": "success"},
        "deployment": {
            "expectedCommit": SHA_A,
            "observedCommitBefore": SHA_A,
            "observedCommitAfter": SHA_A,
            "processStartedBefore": "2026-10-21T07:17:42Z",
            "processStartedAfter": "2026-10-21T07:17:42Z",
        },
        "tests": [_t(status="passed", cls=None, ms=100)],
    }
    base.update(overrides)
    return vfc.classify(base)


def test_only_a_green_attributed_unrestarted_run_claims_authenticated_verification():
    assert _green()["authenticatedVerification"] == {
        "level": "authenticated_verification_passed",
        "blockers": [],
    }


def test_a_green_run_that_cannot_prove_its_revision_is_not_upgraded():
    """Run 39472497541 went green 66 min after its deploy, against a newer process."""
    report = _green(deployment={"expectedCommit": SHA_A})
    assert (
        report["authenticatedVerification"]["level"] == "authenticated_checks_passed_unattributed"
    )
    assert "revision_unproven" in report["authenticatedVerification"]["blockers"]


def test_a_green_run_with_a_mismatch_or_restart_is_not_established():
    mismatch = _green(deployment={"expectedCommit": SHA_A, "observedCommitBefore": SHA_B})
    assert mismatch["authenticatedVerification"]["level"] == "not_established"
    restarted = _green(
        deployment={
            "expectedCommit": SHA_A,
            "observedCommitBefore": SHA_A,
            "observedCommitAfter": SHA_A,
            "processStartedBefore": "2026-10-21T07:17:42Z",
            "processStartedAfter": "2026-10-21T07:53:55Z",
        }
    )
    assert restarted["authenticatedVerification"]["level"] == "not_established"
    assert "backend_restarted_during_run" in restarted["authenticatedVerification"]["blockers"]


def test_a_run_with_no_passing_test_proves_nothing():
    report = _green(tests=[_t(status="skipped", cls=None, ms=1)])
    assert report["authenticatedVerification"]["level"] == "not_established"


# ---------------------------------------------------------------------------
# Redaction: this repo, its logs and its artifacts are public
# ---------------------------------------------------------------------------


def test_secrets_and_cookie_text_never_survive_into_the_report():
    hostile_title = f"title {COOKIE} jason_session={COOKIE} and {TOKEN}"
    report = _run([_t(hostile_title)])
    blob = json.dumps(report)
    assert COOKIE not in blob
    assert TOKEN not in blob
    assert "jason_session=" not in blob.replace("jason_session=[REDACTED]", "")


def test_unknown_keys_and_wrong_kinds_are_dropped_not_passed_through():
    evidence = {
        "run": {"conclusion": "failure", "debug": f"cookie={COOKIE}"},
        "responseBody": {"owner": "998877665544332211", "players": ["Josh Allen"]},
        "tests": [
            {
                **_t(),
                "message": f"Received: {COOKIE}",
                "url": f"https://chaseupside.com/api/x?token={TOKEN}",
                "file": "../../etc/passwd",
                "failureSignal": "Received: Josh Allen",
                "errorClass": f"leak {COOKIE}",
                "durationMs": "5000; DROP TABLE",
            }
        ],
    }
    blob = json.dumps(vfc.classify(evidence, secrets=[COOKIE, TOKEN]))
    for leak in (
        COOKIE,
        TOKEN,
        "998877665544332211",
        "Josh Allen",
        "etc/passwd",
        "DROP TABLE",
        "chaseupside.com",
    ):
        assert leak not in blob, leak


def test_an_unclassifiable_enum_value_is_dropped_to_none_not_echoed():
    only = _only(_run([_t(signal="made_up_signal")]))
    assert only["failureSignal"] is None


def test_the_report_is_valid_json_with_only_the_declared_top_level_keys():
    report = _run([_t()])
    assert set(report) == {
        "schema",
        "sanitized",
        "gateEffect",
        "run",
        "deployment",
        "tests",
        "counts",
        "runCategory",
        "stages",
        "failures",
        "authenticatedVerification",
    }
    assert report["schema"] == vfc.SCHEMA
    assert report["gateEffect"].startswith("none")
    json.dumps(report)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

_LOG = "\n".join(
    [
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T07:48:35.5277960Z ok [prod-desktop] v1-56-waivers-faab-strip.spec.js › the strip equals the payload (5143ms)",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T07:50:07.0019282Z FAIL [prod-desktop] v1-62-sharp-tracker.spec.js › Sharp Tracker matches GET /api/sharp/market field-for-field (91418ms) [timeout]",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T07:51:11.6943466Z FAIL [prod-desktop] w1-12-public-pregame.spec.js › the previews tab (64109ms) [assertion] signal=expect_timeout",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T07:55:17.1124792Z TIMEOUT [prod-desktop] w1-12-public-pregame.spec.js › Home card link (180029ms) [timeout]",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T08:00:00.0000000Z FAIL [prod-mobile] train2-private-surfaces.spec.js › Why it moved (817***ms) [timeout]",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T08:00:01.0000000Z skip [prod-mobile] a.spec.js › skipped (1ms)",
        "V1 authenticated verification\tUNKNOWN STEP\t2026-10-21T08:00:02.0000000Z 103 passed, 26 skipped — run failed",
    ]
)


def test_console_log_lines_are_parsed_with_derived_start_and_masked_duration_unknown():
    tests = vfc.tests_from_console_log(_LOG)
    assert [t["status"] for t in tests] == [
        "passed",
        "failed",
        "failed",
        "timedOut",
        "failed",
        "skipped",
    ]
    sharp = tests[1]
    assert sharp["durationMs"] == 91418
    assert sharp["startedAt"].startswith("2026-10-21T07:48:35")
    assert tests[2]["failureSignal"] == "expect_timeout"
    masked = tests[4]
    assert masked["durationMs"] is None  # GitHub masked digits: unknown, never 0
    assert masked["startedAt"] is None


def test_the_log_to_report_path_reproduces_the_restart_attribution():
    evidence = {
        "run": {"conclusion": "failure"},
        "deployment": _RESTART,
        "tests": vfc.tests_from_console_log(_LOG),
    }
    report = vfc.classify(evidence)
    by_file = {(f["file"], f["durationMs"]): f for f in report["failures"]}
    assert (
        "backend_restart_instant_inside_test"
        in by_file[("w1-12-public-pregame.spec.js", 180029)]["evidence"]
    )
    assert (
        "backend_restart_instant_inside_test"
        not in by_file[("v1-62-sharp-tracker.spec.js", 91418)]["evidence"]
    )


def test_environment_assembly_computes_queue_wait_and_drops_hostile_values():
    env = {
        "V1_JOB_STARTED_AT": "2026-10-21T07:22:38Z",
        "V1_DEPLOY_COMPLETED_AT": "2026-10-21T05:56:23Z",
        "V1_DEPLOY_RUN_ID": "39540158948",
        "V1_EXPECTED_SHA": "85ee0562",
        "V1_COMMIT_BEFORE": f"9e3c52fd; echo {COOKIE}",
        "V1_STARTED_BEFORE": "2026-10-21T07:17:42.799216+00:00",
        "V1_STARTED_AFTER": "2026-10-21T07:17:42.799216+00:00",
        "V1_LOGIN_OUTCOME": "success",
        "V1_BACKEND_WARM": "true",
        "V1_BROWSER_OUTCOME": "failure",
    }
    evidence = vfc.evidence_from_environment(
        env,
        safe_report={"tests": [_t()]},
        probe_login=None,
        probe_pre_revoke={"authenticated": False, "probeError": False},
    )
    assert evidence["run"]["queueWaitSeconds"] == 86 * 60 + 15
    assert evidence["run"]["deployRunId"] == 39540158948
    assert evidence["auth"]["preRevokeAuthenticated"] is False
    report = vfc.classify(evidence, secrets=[COOKIE])
    assert COOKIE not in json.dumps(report)
    assert report["deployment"]["observedCommitBefore"] is None  # malformed -> dropped
    assert report["run"]["queueWaitSeconds"] == 5175


def test_a_probe_that_errored_does_not_count_as_unauthenticated():
    assert vfc._probe_authenticated({"authenticated": False, "probeError": True}) is None
    assert vfc._probe_authenticated({"authenticated": False, "probeError": False}) is False
    assert vfc._probe_authenticated(None) is None


# ---------------------------------------------------------------------------
# CLI end to end
# ---------------------------------------------------------------------------


def test_cli_classify_writes_a_public_safe_report_and_summary(tmp_path, monkeypatch):
    cookie_file = tmp_path / "cookie"
    cookie_file.write_text(COOKIE)
    safe = tmp_path / "safe.json"
    safe.write_text(
        json.dumps(
            {"tests": [_t(f"Private {COOKIE}", ms=900), _t("ok", status="passed", cls=None, ms=10)]}
        )
    )
    out = tmp_path / "out.json"
    summary = tmp_path / "summary.md"
    for key, value in {
        "V1_EXPECTED_SHA": SHA_A,
        "V1_COMMIT_BEFORE": SHA_A,
        "V1_COMMIT_AFTER": SHA_A,
        "V1_STARTED_BEFORE": "2026-10-21T07:00:00Z",
        "V1_STARTED_AFTER": "2026-10-21T07:00:00Z",
        "V1_JOB_STATUS": "failure",
    }.items():
        monkeypatch.setenv(key, value)
    rc = vfc.main(
        [
            "classify",
            "--safe-report",
            str(safe),
            "--secret-file",
            str(cookie_file),
            "--out",
            str(out),
            "--step-summary",
            str(summary),
        ]
    )
    assert rc == 0
    blob = out.read_text() + summary.read_text()
    assert COOKIE not in blob
    report = json.loads(out.read_text())
    assert report["deployment"]["revision"] == "match"
    assert report["counts"] == {"product_assertion": 1}
    assert "V1 failure classification" in summary.read_text()


def test_cli_classify_survives_a_missing_report_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("V1_JOB_STATUS", "failure")
    out = tmp_path / "out.json"
    rc = vfc.main(["classify", "--safe-report", str(tmp_path / "nope.json"), "--out", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["tests"]["total"] == 0


# ---------------------------------------------------------------------------
# Parity with the things this module mirrors
# ---------------------------------------------------------------------------


def test_failure_signals_match_the_reporters_vocabulary():
    src = (REPO_ROOT / "tests" / "e2e" / "prod-auth-safe-reporter.js").read_text(encoding="utf-8")
    block = re.search(r"const SIGNAL_NAMES = \[(.*?)\];", src, re.S)
    assert block, "SIGNAL_NAMES not found in the reporter"
    names = set(re.findall(r'"([a-z_0-9]+)"', block.group(1)))
    assert names == set(vfc.FAILURE_SIGNALS)


def test_expect_budget_matches_the_prod_auth_config():
    config = (REPO_ROOT / "tests" / "e2e" / "prod-auth.config.js").read_text(encoding="utf-8")
    match = re.search(r"expect:\s*\{\s*timeout:\s*([\d_]+)", config)
    assert match, "expect.timeout not found in prod-auth.config.js"
    assert int(match.group(1).replace("_", "")) == vfc.EXPECT_BUDGET_MS


@pytest.mark.parametrize("path", ["scripts/v1_failure_classifier.py"])
def test_the_module_is_stdlib_only(path):
    src = (REPO_ROOT / path).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import)\s+([A-Za-z_][\w]*)", src, re.M))
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    assert imported <= stdlib, imported - stdlib
