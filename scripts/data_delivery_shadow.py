#!/usr/bin/env python3
"""Shadow-mode bookkeeping for the data-only delivery experiment.

SHADOW MODE ONLY (audit-remediation Task 3, owner directive 2026-11-18).  Every
subcommand READS: GitHub run metadata through the REST API (``resolve``), local
receipts (``compare``, ``aggregate``) or local git history (``backtest``).  None
deploys, dispatches, gates or writes to GitHub.  Activation of a data-only path
is BLOCKED on an owner decision (``docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md``).

Subcommands
-----------
``resolve``    For one Deploy Production run: the commit it deployed (its
               TARGET), the last successful Deploy Production run created
               before it (the BASE: the last fully validated deployed commit),
               and that run's jobs (the full gate's verdict).
``compare``    Join the classification receipt, the data-gate receipt and the
               full verdict into one shadow verdict (+ a job-summary table).
``aggregate``  Fold many shadow verdicts into the activation metrics.
``backtest``   Replay the classifier over a ``deploy.yml`` run listing (offline).

WHICH COMMIT A RUN DEPLOYED
---------------------------
A ``push`` run deploys its ``head_sha``: ``deploy_ref`` exists only on
``workflow_dispatch``, so ``scripts/resolve_deploy_ref.py`` falls back to the
workflow commit.  A ``workflow_dispatch`` run may name another ref, so its
target is read from the "Resolve Deploy Target" job log
(``resolved deploy target: <sha> (<kind>; ...)``, printed by that script).  A
dispatch run whose log cannot be read has NO known target -- never a guessed
``head_sha`` -- and the classifier answers CODE for it.

THE BASE
--------
Deploy Production runs are serialised by the ``production-deploy`` concurrency
group, so once a run has completed, every run created before it has finished
too; the newest SUCCESSFUL one created before it is what production ran while
it deployed.  In shadow every successful run is a full-gate run.  An activated
data path would have to read the base from a box-side record that only
full-gate deploys write (the design document, "Activation design").

Exit codes: 0 done; 1 a fact could not be established (the receipt says
which); 2 usage error.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_deploy_delta as cdd  # noqa: E402  (the one owner of the DATA_ONLY rule)

SCHEMA = "data-delivery-shadow/v1"
DEPLOY_WORKFLOW_PATH = ".github/workflows/deploy.yml"
RESOLVE_JOB = "Resolve Deploy Target"
VALIDATE_JOB = "Validate Build Inputs"
PLAN_JOB = "Plan the hard gate"
COMPLETE_JOB = "Hard gate complete"
DEPLOY_JOB = "Deploy To Production"
SHARD_PREFIX = "Hard gate ("

#: ``scripts/resolve_deploy_ref.py`` prints exactly this line (pinned by test).
RESOLVED_LINE = re.compile(r"resolved deploy target: ([0-9a-f]{40}) \((default|commit|branch|tag);")

_FAILED = frozenset({"failure", "timed_out", "startup_failure"})

#: Outcomes of one shadow comparison.
AGREE_SHIP = "AGREE_SHIP"
AGREE_REFUSE = "AGREE_REFUSE"
UNSAFE_DISAGREEMENT = "UNSAFE_DISAGREEMENT"
CONSERVATIVE_DISAGREEMENT = "CONSERVATIVE_DISAGREEMENT"
NO_FULL_VERDICT = "NO_FULL_VERDICT"
FAST_PATH_NOT_RUN = "FAST_PATH_NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"

#: Activation evidence floor (design document, "Shadow plan").  These decide
#: only what ``aggregate`` reports; the owner decides activation.
MIN_COMPARED_DATA_ONLY = 30
MIN_WINDOW_DAYS = 14

Fetch = Callable[[str], object]


# ── GitHub REST (read-only) ────────────────────────────────────────────────


class GitHubReader:
    """Minimal read-only REST client.  The token never follows a redirect."""

    def __init__(self, repo_slug: str, token: str, api: str = "https://api.github.com"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_slug or ""):
            raise ValueError(f"repository slug {repo_slug!r} is not owner/name")
        if not token:
            raise ValueError("no GitHub token (GITHUB_TOKEN / GH_TOKEN) is set")
        self.repo = repo_slug
        self.token = token
        self.api = api.rstrip("/")

    def _request(self, url: str) -> bytes:
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "data-delivery-shadow")
        # Unredirected: a log download is a 302 to a signed blob URL.
        request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        last: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise
                last = exc
            except urllib.error.URLError as exc:
                last = exc
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GitHub API unreachable: {last}")

    def json(self, path: str) -> object:
        return json.loads(self._request(f"{self.api}/repos/{self.repo}/{path}").decode("utf-8"))

    def text(self, path: str) -> str:
        return self._request(f"{self.api}/repos/{self.repo}/{path}").decode("utf-8", "replace")


def run_jobs(get_json: Fetch, run_id: int) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, 6):
        payload = get_json(f"actions/runs/{run_id}/jobs?per_page=100&page={page}")
        batch = list((payload or {}).get("jobs") or [])  # type: ignore[union-attr]
        jobs.extend(batch)
        if len(batch) < 100:
            break
    return jobs


def deployed_target(run: dict, jobs: list[dict], get_text: Fetch) -> tuple[str | None, str]:
    """``(sha, source)`` a Deploy Production run deployed, or ``(None, reason)``."""
    resolve = next((j for j in jobs if j.get("name") == RESOLVE_JOB), None)
    if resolve is not None and resolve.get("conclusion") == "success":
        try:
            log = str(get_text(f"actions/jobs/{resolve['id']}/logs"))
        except Exception as exc:  # noqa: BLE001 — any read failure is "unknown"
            log, error = "", f"{type(exc).__name__}"
        else:
            error = ""
        match = RESOLVED_LINE.search(log)
        if match:
            return match.group(1), f"resolve_job_log:{match.group(2)}"
        if run.get("event") == "push":
            return str(run.get("head_sha")), "push_head_sha"
        return None, f"dispatch_target_unreadable{':' + error if error else ''}"
    if run.get("event") == "push" and cdd._FULL_SHA.fullmatch(str(run.get("head_sha") or "")):
        return str(run["head_sha"]), "push_head_sha"
    return None, "resolve_job_did_not_succeed"


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_base_run(get_json: Fetch, observed: dict, max_pages: int = 5) -> dict | None:
    """The newest successful Deploy Production run created before ``observed``."""
    created = _ts(observed.get("created_at"))
    best: dict | None = None
    for page in range(1, max_pages + 1):
        payload = get_json(
            f"actions/workflows/deploy.yml/runs?status=success&per_page=100&page={page}"
        )
        runs = list((payload or {}).get("workflow_runs") or [])  # type: ignore[union-attr]
        for run in runs:
            if run.get("id") == observed.get("id") or run.get("conclusion") != "success":
                continue
            run_created = _ts(run.get("created_at"))
            if created is None or run_created is None or run_created >= created:
                continue
            if best is None or run_created > _ts(best.get("created_at")):  # type: ignore[operator]
                best = run
        if best is not None or len(runs) < 100:
            break
    return best


def _run_brief(run: dict) -> dict:
    keys = (
        "id",
        "event",
        "status",
        "conclusion",
        "head_sha",
        "created_at",
        "run_started_at",
        "updated_at",
        "html_url",
    )
    return {key: run.get(key) for key in keys}


def _job_brief(job: dict) -> dict:
    return {
        "name": job.get("name"),
        "conclusion": job.get("conclusion"),
        "startedAt": job.get("started_at"),
        "completedAt": job.get("completed_at"),
        "failedSteps": [
            s.get("name") for s in (job.get("steps") or []) if s.get("conclusion") in _FAILED
        ],
    }


def resolve_inputs(get_json: Fetch, get_text: Fetch, deploy_run_id: int) -> dict:
    """Everything the shadow needs from GitHub, as one receipt."""
    out: dict = {
        "schema": SCHEMA + "#inputs",
        "deployRunId": deploy_run_id,
        "observedRun": None,
        "observedJobs": [],
        "target": {"sha": None, "source": None},
        "base": {"sha": None, "source": None, "runId": None, "createdAt": None},
        "errors": [],
    }
    run = get_json(f"actions/runs/{deploy_run_id}")
    if not isinstance(run, dict) or run.get("path") != DEPLOY_WORKFLOW_PATH:
        out["errors"].append("not_a_deploy_production_run")
        return out
    out["observedRun"] = _run_brief(run)
    jobs = run_jobs(get_json, deploy_run_id)
    out["observedJobs"] = [_job_brief(j) for j in jobs]
    sha, source = deployed_target(run, jobs, get_text)
    out["target"] = {"sha": sha, "source": source}
    if sha is None:
        out["errors"].append(f"target_unknown:{source}")
    base_run = find_base_run(get_json, run)
    if base_run is None:
        out["errors"].append("base_run_not_found")
        return out
    base_sha, base_source = deployed_target(
        base_run, run_jobs(get_json, int(base_run["id"])), get_text
    )
    out["base"] = {
        "sha": base_sha,
        "source": f"deploy_run:{base_run['id']}:{base_source}",
        "runId": base_run["id"],
        "createdAt": base_run.get("created_at"),
    }
    if base_sha is None:
        out["errors"].append(f"base_unknown:{base_source}")
    return out


# ── the full gate's verdict ────────────────────────────────────────────────


#: A failed step whose name starts with one of these prepares a runner; it
#: says nothing about the code or the data (measured: 2 of the 9 data-only
#: deltas that failed the full gate, 2026-11-03..18, failed only at
#: "Install tesseract-ocr").  Any other failed step -- including one nobody
#: listed -- is a gate verdict (fail closed: it counts as a full refusal).
_INFRA_STEP_PREFIXES = (
    "Set up ",
    "Install ",
    "Checkout",
    "Download ",
    "Upload ",
    "Post ",
    "Complete job",
)


def _is_infra_step(name: str) -> bool:
    return name.startswith(_INFRA_STEP_PREFIXES)


def full_verdict(jobs: list[dict]) -> dict:
    """``pass`` / ``fail`` / ``unknown`` for the PRE-DEPLOY gates of one run.

    Pre-deploy gates are what a data-only path would replace: validate, the
    hard-gate plan, every shard and the completeness proof.  The deploy job
    (box-side deploy + post-deploy verification) is reported separately; an
    activated data path keeps its own box-side verification.  A run whose
    only failed steps prepared a runner is ``unknown`` (``infrastructure``):
    it judged neither the code nor the data.
    """
    by_name = {j.get("name"): j for j in jobs}
    gate_jobs = [
        j
        for j in jobs
        if j.get("name") in (VALIDATE_JOB, PLAN_JOB, COMPLETE_JOB)
        or str(j.get("name") or "").startswith(SHARD_PREFIX)
    ]
    failed = [j for j in gate_jobs if j.get("conclusion") in _FAILED]
    failed_steps = [
        (str(j.get("name")), str(step)) for j in failed for step in (j.get("failedSteps") or [])
    ]
    validate = (by_name.get(VALIDATE_JOB) or {}).get("conclusion")
    complete = (by_name.get(COMPLETE_JOB) or {}).get("conclusion")
    failure_kind = None
    if failed:
        # A failed job with no failed step recorded (a timeout, a runner loss)
        # is not provably infrastructure, so it stays a gate failure.
        named_all = all(j.get("failedSteps") for j in failed)
        if named_all and all(_is_infra_step(step) for _, step in failed_steps):
            verdict, failure_kind = "unknown", "infrastructure"
        else:
            verdict, failure_kind = "fail", "gate"
    elif validate == "success" and complete == "success":
        verdict = "pass"
    else:
        verdict = "unknown"
    return {
        "preDeploy": verdict,
        "failureKind": failure_kind,
        "failedJobs": [j.get("name") for j in failed],
        "failedSteps": [f"{job}::{step}" for job, step in failed_steps],
        "deployJob": (by_name.get(DEPLOY_JOB) or {}).get("conclusion"),
    }


def full_timing(run: dict, jobs: list[dict]) -> dict:
    gate_jobs = [j for j in jobs if j.get("name") != DEPLOY_JOB]
    runner_seconds = 0.0
    last_gate_end: datetime | None = None
    for job in gate_jobs:
        start, end = _ts(job.get("startedAt")), _ts(job.get("completedAt"))
        if start and end and end >= start:
            runner_seconds += (end - start).total_seconds()
            last_gate_end = end if last_gate_end is None or end > last_gate_end else last_gate_end
    run_start = _ts(run.get("run_started_at") or run.get("created_at"))
    wall = (last_gate_end - run_start).total_seconds() if last_gate_end and run_start else None
    return {
        "preDeployRunnerMinutes": round(runner_seconds / 60, 1),
        "preDeployWallMinutes": round(wall / 60, 1) if wall is not None else None,
    }


def compare(
    inputs: dict, classification: dict, gates: dict | None, started_at: float | None
) -> dict:
    jobs = inputs.get("observedJobs") or []
    run = inputs.get("observedRun") or {}
    full = full_verdict(jobs)
    applicable = classification.get("classification") == cdd.DATA_ONLY
    would_ship = gates.get("wouldShip") if isinstance(gates, dict) else None
    if not applicable:
        outcome = NOT_APPLICABLE
    elif would_ship is None:
        outcome = FAST_PATH_NOT_RUN
    elif full["preDeploy"] == "unknown":
        outcome = NO_FULL_VERDICT
    elif would_ship and full["preDeploy"] == "pass":
        outcome = AGREE_SHIP
    elif not would_ship and full["preDeploy"] == "fail":
        outcome = AGREE_REFUSE
    elif would_ship:
        outcome = UNSAFE_DISAGREEMENT
    else:
        outcome = CONSERVATIVE_DISAGREEMENT
    shadow_wall = round(time.time() - started_at, 1) if started_at else None
    timing = full_timing(run, jobs)
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deployRunId": inputs.get("deployRunId"),
        "deployEvent": run.get("event"),
        "deployCreatedAt": run.get("created_at"),
        "deployConclusion": run.get("conclusion"),
        "target": classification.get("target", {}).get("sha"),
        "base": classification.get("base", {}).get("sha"),
        "baseSource": classification.get("base", {}).get("source"),
        "classification": classification.get("classification"),
        "classificationReasons": classification.get("reasons"),
        "codePathGroups": classification.get("codePathGroups"),
        "rulesDigest": classification.get("rulesDigest"),
        "inputErrors": inputs.get("errors") or [],
        "fullVerdict": full,
        "fastPath": None
        if not isinstance(gates, dict)
        else {
            "wouldShip": gates.get("wouldShip"),
            "blockingFailures": gates.get("blockingFailures"),
            "advisoryFailures": gates.get("advisoryFailures"),
            "gateSeconds": gates.get("seconds"),
            "gates": {g["name"]: g["status"] for g in gates.get("gates") or []},
        },
        "outcome": outcome,
        "timing": {
            **timing,
            "shadowJobWallMinutes": round(shadow_wall / 60, 1) if shadow_wall else None,
        },
        "decidesNothing": True,
    }


def render_summary(verdict: dict) -> str:
    fast = verdict.get("fastPath") or {}
    full = verdict["fullVerdict"]
    timing = verdict["timing"]
    rows = [
        (
            "Deploy run",
            f"{verdict['deployRunId']} ({verdict['deployEvent']}, {verdict['deployConclusion']})",
        ),
        ("Target", f"`{verdict['target']}`"),
        ("Base (last fully validated deploy)", f"`{verdict['base']}` — {verdict['baseSource']}"),
        (
            "Classification",
            f"**{verdict['classification']}** ({', '.join(verdict['classificationReasons'] or [])})",
        ),
        (
            "Full gate (pre-deploy)",
            f"{full['preDeploy']} {full['failedSteps'] or full['failedJobs'] or ''}",
        ),
        (
            "Fast path would ship",
            "not run" if not fast else f"{fast['wouldShip']} {fast['blockingFailures'] or ''}",
        ),
        ("Outcome", f"**{verdict['outcome']}**"),
        (
            "Full pre-deploy runner minutes / wall",
            f"{timing['preDeployRunnerMinutes']} / {timing['preDeployWallMinutes']}",
        ),
        ("Shadow job wall minutes", f"{timing['shadowJobWallMinutes']}"),
    ]
    groups = verdict.get("codePathGroups") or {}
    lines = [
        "## Data delivery shadow (decides nothing)",
        "",
        "| | |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rows],
    ]
    if groups:
        top = ", ".join(f"`{g}` {n}" for g, n in list(groups.items())[:8])
        lines += ["", f"Code paths that made it CODE: {top}"]
    lines += [
        "",
        "Shadow mode only: nothing here deploys, gates or blocks. Activation is BLOCKED — "
        "owner decision (docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md).",
        "",
    ]
    return "\n".join(lines)


# ── aggregate ──────────────────────────────────────────────────────────────


def aggregate(verdicts: list[dict]) -> dict:
    by_class: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for v in verdicts:
        by_class[v.get("classification") or "?"] = (
            by_class.get(v.get("classification") or "?", 0) + 1
        )
        by_outcome[v.get("outcome") or "?"] = by_outcome.get(v.get("outcome") or "?", 0) + 1
    compared = [
        v
        for v in verdicts
        if v.get("outcome")
        in (AGREE_SHIP, AGREE_REFUSE, UNSAFE_DISAGREEMENT, CONSERVATIVE_DISAGREEMENT)
    ]
    shipped = [v for v in compared if v.get("outcome") == AGREE_SHIP]
    saved = [
        (v["timing"].get("preDeployRunnerMinutes") or 0)
        - (v["timing"].get("shadowJobWallMinutes") or 0)
        for v in shipped
        if v.get("timing")
    ]
    created = sorted(_ts(v.get("deployCreatedAt")) for v in compared if v.get("deployCreatedAt"))
    window_days = (
        round((created[-1] - created[0]).total_seconds() / 86400, 1) if len(created) > 1 else 0.0
    )
    rules = sorted({v.get("rulesDigest") for v in verdicts if v.get("rulesDigest")})
    unsafe = [v for v in verdicts if v.get("outcome") == UNSAFE_DISAGREEMENT]
    criteria = {
        "zeroUnsafeDisagreements": not unsafe,
        f"atLeast{MIN_COMPARED_DATA_ONLY}ComparedDataOnly": len(compared) >= MIN_COMPARED_DATA_ONLY,
        f"windowAtLeast{MIN_WINDOW_DAYS}Days": window_days >= MIN_WINDOW_DAYS,
        "zeroFastPathNotRun": not by_outcome.get(FAST_PATH_NOT_RUN),
        "oneRuleSetThroughout": len(rules) <= 1,
    }
    return {
        "schema": SCHEMA + "#aggregate",
        "verdicts": len(verdicts),
        "byClassification": dict(sorted(by_class.items())),
        "byOutcome": dict(sorted(by_outcome.items())),
        "comparedDataOnly": len(compared),
        "windowDays": window_days,
        "unsafeDisagreements": [
            {
                "deployRunId": v.get("deployRunId"),
                "failedSteps": v["fullVerdict"].get("failedSteps"),
            }
            for v in unsafe
        ],
        "conservativeDisagreements": [
            {"deployRunId": v.get("deployRunId"), "fastPath": v.get("fastPath")}
            for v in verdicts
            if v.get("outcome") == CONSERVATIVE_DISAGREEMENT
        ],
        "runnerMinutesSavedOnAgreedShips": round(sum(saved), 1),
        "medianRunnerMinutesSavedPerShip": round(statistics.median(saved), 1) if saved else None,
        "rulesDigests": rules,
        "activationEvidenceCriteria": criteria,
        "activationEvidenceMet": all(criteria.values()),
        "activationDecision": "BLOCKED — OWNER DECISION (evidence alone never activates)",
    }


def _load_verdicts(directory: Path) -> list[dict]:
    verdicts = []
    for path in sorted(directory.rglob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
            verdicts.append(doc)
    return verdicts


# ── backtest ───────────────────────────────────────────────────────────────


def backtest(repo: Path, runs: list[dict]) -> dict:
    """Replay the classifier over a ``deploy.yml`` run listing.

    Offline: a run's target is its ``head_sha``.  That is exact for ``push``
    and an ASSUMPTION for ``workflow_dispatch`` (true for the scheduled
    refresh's dispatches, which pass no ``deploy_ref``); the report counts how
    many rows rest on it.
    """
    ordered = sorted(runs, key=lambda r: r.get("created_at") or "")
    rows = []
    for index, run in enumerate(ordered):
        if run.get("conclusion") in (None, "", "cancelled", "skipped"):
            continue
        base = next(
            (r for r in reversed(ordered[:index]) if r.get("conclusion") == "success"), None
        )
        if base is None:
            continue
        receipt = cdd.classify(
            repo, str(base.get("head_sha")), str(run.get("head_sha")), base_source="backtest"
        )
        rows.append(
            {
                "runId": run.get("id"),
                "event": run.get("event"),
                "conclusion": run.get("conclusion"),
                "classification": receipt["classification"],
                "reasons": receipt["reasons"],
                "codePathGroups": receipt["codePathGroups"],
                "assumedDispatchTarget": run.get("event") == "workflow_dispatch",
            }
        )
    data_only = [r for r in rows if r["classification"] == cdd.DATA_ONLY]
    code = [r for r in rows if r["classification"] == cdd.CODE]
    group_counts: dict[str, int] = {}
    for row in code:
        for group in row["codePathGroups"]:
            group_counts[group] = group_counts.get(group, 0) + 1

    def _by(rows_: list[dict], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows_:
            out[str(row[key])] = out.get(str(row[key]), 0) + 1
        return dict(sorted(out.items()))

    return {
        "schema": SCHEMA + "#backtest",
        "runsClassified": len(rows),
        "dataOnly": len(data_only),
        "code": len(code),
        "dataOnlyByConclusion": _by(data_only, "conclusion"),
        "dataOnlyByEvent": _by(data_only, "event"),
        "codeByConclusion": _by(code, "conclusion"),
        "codeReasons": _by([{"r": ",".join(r["reasons"])} for r in code], "r"),
        "codeDeltasTouchingGroup": dict(
            sorted(group_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "rowsOnAssumedDispatchTarget": sum(1 for r in rows if r["assumedDispatchTarget"]),
        "rows": rows,
    }


# ── CLI ────────────────────────────────────────────────────────────────────


def _read_json(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    return doc if isinstance(doc, dict) else None


def _write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _github_output(pairs: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="target, base and full verdict of one deploy run")
    p_resolve.add_argument("--deploy-run-id", type=int, required=True)
    p_resolve.add_argument("--repo-slug", required=True, help="owner/name")
    p_resolve.add_argument("--out", type=Path, required=True)

    p_compare = sub.add_parser("compare", help="one shadow verdict from the three receipts")
    p_compare.add_argument("--inputs", type=Path, required=True)
    p_compare.add_argument("--classification", type=Path, required=True)
    p_compare.add_argument("--gates", type=Path, help="absent when the fast path did not run")
    p_compare.add_argument("--started-at", type=float, help="shadow job start, unix seconds")
    p_compare.add_argument("--out", type=Path, required=True)
    p_compare.add_argument("--summary", type=Path, help="append a markdown table here")

    p_agg = sub.add_parser("aggregate", help="activation metrics over many shadow verdicts")
    p_agg.add_argument(
        "--receipts", type=Path, required=True, help="directory searched recursively"
    )

    p_back = sub.add_parser("backtest", help="replay the classifier over a deploy.yml run listing")
    p_back.add_argument(
        "--runs-json", type=Path, required=True, help="REST workflow-runs payload or a list"
    )
    p_back.add_argument("--repo", type=Path, default=Path.cwd())
    p_back.add_argument("--rows", action="store_true", help="include every row")

    args = parser.parse_args(argv)

    if args.command == "resolve":
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        try:
            reader = GitHubReader(
                args.repo_slug, token, os.environ.get("GITHUB_API_URL", "https://api.github.com")
            )
            inputs = resolve_inputs(reader.json, reader.text, args.deploy_run_id)
        except (ValueError, RuntimeError, urllib.error.HTTPError) as exc:
            print(f"::error title=Data delivery shadow::could not read the deploy run: {exc}")
            return 1
        _write_json(args.out, inputs)
        _github_output(
            {
                "target": inputs["target"]["sha"] or "",
                "base": inputs["base"]["sha"] or "",
                "base_source": inputs["base"]["source"] or "",
            }
        )
        print(json.dumps({k: inputs[k] for k in ("target", "base", "errors")}, indent=2))
        # An unknown base or target is a RESULT (the classifier answers CODE),
        # not a failure of the shadow; only "this is not a deploy run" is.
        return 1 if "not_a_deploy_production_run" in inputs["errors"] else 0

    if args.command == "compare":
        inputs = _read_json(args.inputs)
        classification = _read_json(args.classification)
        if inputs is None or classification is None:
            print("::error title=Data delivery shadow::inputs or classification receipt missing")
            return 1
        verdict = compare(inputs, classification, _read_json(args.gates), args.started_at)
        _write_json(args.out, verdict)
        summary = render_summary(verdict)
        if args.summary:
            with args.summary.open("a", encoding="utf-8") as handle:
                handle.write(summary)
        print(summary)
        return 0

    if args.command == "aggregate":
        print(json.dumps(aggregate(_load_verdicts(args.receipts)), indent=2))
        return 0

    with args.runs_json.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else payload
    report = backtest(args.repo, list(runs))
    if not args.rows:
        report.pop("rows")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
