#!/usr/bin/env python3
"""The data gate set: the minimum validation a DATA_ONLY delivery needs.

SHADOW MODE ONLY (audit-remediation Task 3, owner directive 2026-11-18).  In
the shadow (``.github/workflows/data-delivery-shadow.yml``) this runs against
the deploy target tree and its verdict is RECORDED beside the full Deploy
Production verdict; it gates, ships and blocks nothing.  Activation is BLOCKED
on an owner decision (``docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md``).

WHAT IT RUNS, AND WHY THESE
---------------------------
Only a delta that ``scripts/classify_deploy_delta.py`` calls DATA_ONLY reaches
this: the code tree is byte-identical to a commit that passed the full gate, so
every check whose verdict is a function of the code alone has already passed on
exactly this code.  What remains are the checks a data change CAN move.  Each
gate below mirrors a step the full pipeline already runs, with the same command
and environment; none is new methodology.

==================== ========= ===============================================
gate                 blocking  mirrors
==================== ========= ===============================================
runtime_import       yes       deploy.yml validate "Python runtime import gate"
contract_full_lane   yes       deploy.yml validate "API data contract check
                               (FULL lane — blocking)": builds the canonical
                               contract from exports/latest + CSVs/site_raw
                               with this code and validates it (schema, rank
                               invariants, the 1..9999 scale, blend integrity,
                               pick census, row floors, source health)
tracked_data_privacy yes       the hard-gate tests whose SUBJECT is the tracked
                               data itself (no per-manager intelligence in a
                               tracked file; the trade ledger store is never
                               tracked)
source_health        no        pr-validation / release-candidate "source
                               health" (advisory there too)
livedata_tests       no        deploy.yml validate "Run live-data tests
                               (advisory — non-blocking)"
==================== ========= ===============================================

WHAT THE TWO ADVISORY GATES ACTUALLY SAY
----------------------------------------
Both were red on every shadow run (17 of 17 by 2026-11-20), for the same few
known conditions, so a NEW condition could not be told from the old ones.
Each now has a judge (advisory gates only; a blocking gate's verdict is never
re-read): a condition already DECLARED, with a review date still ahead, is
reported on its own named line (``advisoryDeclared``) instead of failing the
gate, and anything else -- including a report the judge cannot read -- still
fails it.

* ``source_health``: a source whose ``config/sources/rehabilitation.json``
  entry (in the TARGET tree) is in a state that explains the condition --
  ``auth_blocked`` (an owner-held credential lapsed, e.g. a private source in
  ``reconnect_required``: nothing can be fetched) explains a stale fetch and
  stale content; ``upstream_inactive`` and ``degraded`` (the vendor is not
  publishing) explain stale content only.  Voting-policy states
  (``policy_held``, ``shadow``, ...) explain no collection failure.
* ``livedata_tests``: a failing test listed in ``DECLARED_LIVEDATA_FAILURES``.

What the data gate does NOT re-run is listed, with the reason, in the design
document's coverage comparison.  The one class a data change can still move --
hard-gate tests that evaluate code over refreshable data -- is exactly what the
shadow measures (``UNSAFE_DISAGREEMENT``) and what the activation precondition
(a hard gate hermetic to the data roots) removes.

Exit codes: 0 every blocking gate passed (would ship); 1 a blocking gate failed
or could not run (would refuse); 2 usage error.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCHEMA = "data-delivery-gates/v1"

#: Which declared rehabilitation state explains which source-health condition
#: (module docstring).  Read from the target tree's
#: ``config/sources/rehabilitation.json``; an entry past its ``reviewBy``
#: explains nothing (its plan is overdue, so the condition is news again).
DECLARED_STATE_EXPLAINS: dict[str, frozenset[str]] = {
    "auth_blocked": frozenset({"fetch_stale", "content_stale"}),
    "upstream_inactive": frozenset({"content_stale"}),
    "degraded": frozenset({"content_stale"}),
}
_REHABILITATION_REGISTRY = Path("config") / "sources" / "rehabilitation.json"

#: Live-data tests known to fail for a reason that is not a data defect, each
#: with the reason and a review date (after which it fails the gate again).
DECLARED_LIVEDATA_FAILURES: dict[str, dict[str, str]] = {
    "tests/trade/test_faab_calibration.py::TestAllInRegion::"
    "test_every_human_anchor_reaches_a_full_ceiling": {
        "reason": (
            "bands named players' board values measured on 2026-08-04 at +/-35%; its own "
            "comment says a normal market move fails it with no code defect.  It failed on "
            "all 17 shadow runs to 2026-11-20 (e.g. Jaylen Warren 4214 and 4413 against 2938)"
        ),
        "reviewBy": "2026-12-31",
    },
}

_PYTEST_FAILURE_LINE = re.compile(r"^(FAILED|ERROR) (\S+)", re.MULTILINE)

#: The environment the full pipeline gives these commands (deploy.yml validate).
_PIPELINE_ENV = {"ALLOW_DEFAULT_LOGIN_DEV": "1", "UPTIME_CHECK_ENABLED": "0"}

_TAIL_LINES = 40

#: Wall-clock budget for the WHOLE gate set.  The per-gate timeouts sum to 75
#: minutes, which cannot fit the shadow job's limit, so the set carries its own
#: deadline: each gate's timeout is capped to what is left, and a gate that
#: finds no time left is recorded ``skipped_budget`` (a non-pass, so a blocking
#: gate skipped this way refuses -- it never reads as green).  The workflow's
#: ``timeout-minutes`` must leave margin above this (pinned by test).
GATE_SET_BUDGET_SECONDS = 2700

#: A gate is not started with less than this left; it could only time out.
_MIN_GATE_SECONDS = 30


@dataclass(frozen=True)
class Gate:
    name: str
    blocking: bool
    argv: tuple[str, ...]
    mirrors: str
    timeout_seconds: int
    env: dict[str, str] = field(default_factory=dict)
    #: Key into ``JUDGES``: reads an ADVISORY gate's output instead of its exit
    #: code alone.  Ignored on a blocking gate (never re-read a blocker).
    judge: str | None = None


def default_gates(python: str = sys.executable) -> tuple[Gate, ...]:
    return (
        Gate(
            name="runtime_import",
            blocking=True,
            argv=(python, "-c", "import server  # noqa: F401\nprint('runtime import ok')"),
            mirrors="deploy.yml::validate::Python runtime import gate",
            timeout_seconds=300,
            env=dict(_PIPELINE_ENV),
        ),
        Gate(
            name="contract_full_lane",
            blocking=True,
            argv=(python, "scripts/validate_api_contract.py", "--repo", ".", "--lane", "full"),
            mirrors="deploy.yml::validate::API data contract check (FULL lane — blocking)",
            timeout_seconds=900,
        ),
        Gate(
            name="tracked_data_privacy",
            blocking=True,
            argv=(
                python,
                "-m",
                "pytest",
                "tests/api/test_tracked_artifacts_privacy.py",
                "tests/trade/test_market_trade_privacy.py",
                "-q",
                "--tb=short",
                "-m",
                "not livedata",
                "-p",
                "no:cacheprovider",
            ),
            mirrors="deploy.yml::hard-gate (the tracked-data privacy subset)",
            timeout_seconds=900,
            env=dict(_PIPELINE_ENV),
        ),
        Gate(
            name="source_health",
            blocking=False,
            # --json: the same checks and exit code, as a report the judge reads.
            argv=(python, "scripts/check_source_health.py", "--repo", ".", "--json"),
            mirrors="pr-validation.yml / release-candidate.yml source-health lane (advisory)",
            timeout_seconds=600,
            judge="source_health",
        ),
        Gate(
            name="livedata_tests",
            blocking=False,
            argv=(
                python,
                "-m",
                "pytest",
                "tests/",
                "-q",
                "--tb=short",
                "-m",
                "livedata",
                "-p",
                "no:cacheprovider",
            ),
            mirrors="deploy.yml::validate::Run live-data tests (advisory — non-blocking)",
            timeout_seconds=1800,
            env=dict(_PIPELINE_ENV),
            judge="livedata",
        ),
    )


def _tail(text: str) -> list[str]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-_TAIL_LINES:]


# ── judges: what an always-red advisory gate actually says ─────────────────


def _review_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _declared(reason: str, state: str | None, review_by: object, today: date) -> dict | None:
    """The declaration, if it is still current on ``today``; else ``None``."""
    due = _review_date(review_by)
    if due is None or due < today:
        return None
    return {"declaredState": state, "declaredReason": reason, "reviewBy": due.isoformat()}


def source_health_conditions(report: dict) -> list[dict]:
    """Every condition that makes ``check_source_health.py`` exit 1, one per row."""
    out: list[dict] = []
    for msg in report.get("contractSourceHealthErrors") or []:
        out.append({"kind": "contract", "source": None, "detail": str(msg)})
    for row in report.get("hardStale") or []:
        out.append(
            {
                "kind": "fetch_stale",
                "source": row.get("source"),
                "detail": f"last fetch {row.get('ageHours')}h ago > {row.get('thresholdHours')}h",
            }
        )
    for row in report.get("contentStale") or []:
        label = str(row.get("source") or "")
        out.append(
            {
                "kind": "content_stale",
                "source": label.split(" ", 1)[0] or None,
                "detail": f"{label} unchanged {row.get('daysSinceChange')}d "
                f"(budget {row.get('budgetDays')}d)",
            }
        )
    for key, item in sorted((report.get("registeredSourceIntegrity") or {}).items()):
        for msg in (item or {}).get("errors") or []:
            out.append({"kind": "integrity", "source": key, "detail": str(msg)})
    ktc = (report.get("semanticIntegrity") or {}).get("ktc") or {}
    if ktc and (
        ktc.get("measurable") is False
        or ktc.get("errors")
        or ktc.get("coverageErrors")
        or ktc.get("parserErrors")
    ):
        out.append({"kind": "ktc_semantic", "source": "ktc", "detail": str(ktc.get("state"))})
    return out


def _rehabilitation_entries(repo: Path) -> dict:
    try:
        doc = json.loads((repo / _REHABILITATION_REGISTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # nothing is declared: every condition stays a failure
    entries = doc.get("entries") if isinstance(doc, dict) else None
    return entries if isinstance(entries, dict) else {}


def judge_source_health(
    stdout: str, returncode: int | None, repo: Path, today: date
) -> tuple[str, dict]:
    """``(status, conditions)``: ``pass`` when every condition is declared."""
    if returncode == 0:
        return "pass", {"declared": [], "undeclared": []}
    if returncode != 1:
        return "fail", {"reason": f"the check could not run (exit {returncode})"}
    try:
        report = json.loads(stdout)
    except ValueError:
        return "fail", {"reason": "report_unparseable"}
    if not isinstance(report, dict):
        return "fail", {"reason": "report_unparseable"}
    conditions = source_health_conditions(report)
    if not conditions:
        # exit 1 for a reason this judge does not model: never a pass
        return "fail", {"reason": "unmodelled_condition"}
    entries = _rehabilitation_entries(repo)
    declared, undeclared = [], []
    for cond in conditions:
        entry = entries.get(cond["source"]) if cond["source"] else None
        state = (entry or {}).get("state")
        why = None
        if entry and cond["kind"] in DECLARED_STATE_EXPLAINS.get(str(state), frozenset()):
            why = _declared(str(entry.get("reason") or ""), state, entry.get("reviewBy"), today)
        if why:
            declared.append({**cond, **why})
        else:
            undeclared.append(cond)
    return ("fail" if undeclared else "pass"), {"declared": declared, "undeclared": undeclared}


def judge_livedata(
    stdout: str, returncode: int | None, repo: Path, today: date
) -> tuple[str, dict]:
    """``(status, conditions)``: ``pass`` when every failing test is declared."""
    del repo
    if returncode == 0:
        return "pass", {"declared": [], "undeclared": []}
    if returncode != 1:
        return "fail", {"reason": f"pytest did not complete (exit {returncode})"}
    failures = [(kind, node) for kind, node in _PYTEST_FAILURE_LINE.findall(stdout or "")]
    if not failures:
        return "fail", {"reason": "unmodelled_condition"}
    declared, undeclared = [], []
    for kind, node in failures:
        cond = {"kind": kind.lower(), "source": None, "detail": node}
        entry = DECLARED_LIVEDATA_FAILURES.get(node) if kind == "FAILED" else None
        why = _declared(entry["reason"], None, entry["reviewBy"], today) if entry else None
        if why:
            declared.append({**cond, **why})
        else:
            undeclared.append(cond)
    return ("fail" if undeclared else "pass"), {"declared": declared, "undeclared": undeclared}


JUDGES = {"source_health": judge_source_health, "livedata": judge_livedata}


def _condition_line(cond: dict) -> str:
    who = f" {cond['source']}" if cond.get("source") else ""
    line = f"{cond['kind']}{who}: {cond['detail']}"
    if cond.get("reviewBy"):
        state = f" {cond['declaredState']}" if cond.get("declaredState") else ""
        line += f" [declared{state}, review by {cond['reviewBy']}]"
    return line


def run_gate(gate: Gate, repo: Path, timeout_seconds: float | None = None) -> dict:
    env = {**os.environ, **gate.env}
    limit = gate.timeout_seconds if timeout_seconds is None else timeout_seconds
    started = time.monotonic()
    record: dict = {
        "name": gate.name,
        "blocking": gate.blocking,
        "mirrors": gate.mirrors,
        "argv": list(gate.argv),
        "status": "error",
        "returnCode": None,
        "seconds": None,
        "outputTail": [],
    }
    try:
        proc = subprocess.run(
            list(gate.argv),
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limit,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        record["status"] = "timeout"
        out = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout or b"").decode("utf-8", "replace")
        )
        record["outputTail"] = _tail(out)
    except OSError as exc:
        record["status"] = "error"
        record["outputTail"] = [f"{type(exc).__name__}: {exc}"]
    else:
        record["returnCode"] = proc.returncode
        record["status"] = "pass" if proc.returncode == 0 else "fail"
        record["outputTail"] = _tail(f"{proc.stdout}\n{proc.stderr}")
        judge = JUDGES.get(gate.judge or "") if not gate.blocking else None
        if judge is not None:
            status, conditions = judge(
                proc.stdout, proc.returncode, repo, datetime.now(timezone.utc).date()
            )
            record["status"] = status
            record["conditions"] = conditions
            if gate.judge == "source_health":
                # its stdout is the JSON report: keep stderr and the conditions
                record["outputTail"] = _tail(
                    "\n".join(
                        [proc.stderr or "", conditions.get("reason") or ""]
                        + [
                            f"declared: {_condition_line(c)}"
                            for c in conditions.get("declared", [])
                        ]
                        + [
                            f"undeclared: {_condition_line(c)}"
                            for c in conditions.get("undeclared", [])
                        ]
                    )
                )
    record["seconds"] = round(time.monotonic() - started, 2)
    return record


def _head_sha(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and len(value) == 40 else None


def _skipped_budget(gate: Gate) -> dict:
    return {
        "name": gate.name,
        "blocking": gate.blocking,
        "mirrors": gate.mirrors,
        "argv": list(gate.argv),
        "status": "skipped_budget",
        "returnCode": None,
        "seconds": 0.0,
        "outputTail": ["gate-set wall-clock budget exhausted before this gate could start"],
    }


def _write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def run_gates(
    gates: tuple[Gate, ...],
    repo: Path,
    receipt_path: Path | None = None,
    budget_seconds: float = GATE_SET_BUDGET_SECONDS,
) -> dict:
    """Run every gate (a blocking failure does not stop the others) and judge.

    With ``receipt_path`` the receipt is rewritten after EVERY gate, marked
    ``complete: false`` and ``wouldShip: false`` until the last one finishes, so
    a job killed mid-set leaves the evidence so far and never a ship verdict.
    """
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    deadline = time.monotonic() + budget_seconds
    results: list[dict] = []
    for gate in gates:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_GATE_SECONDS:
            results.append(_skipped_budget(gate))
        else:
            results.append(run_gate(gate, repo, min(gate.timeout_seconds, remaining)))
        if receipt_path is not None:
            _write_receipt(
                receipt_path,
                _assemble(started_at, repo, results, complete=len(results) == len(gates)),
            )
    return _assemble(started_at, repo, results, complete=True)


def _assemble(started_at: str, repo: Path, results: list[dict], complete: bool) -> dict:
    blocking_failed = [r["name"] for r in results if r["blocking"] and r["status"] != "pass"]
    advisory_failed = [r["name"] for r in results if not r["blocking"] and r["status"] != "pass"]
    # Known conditions an advisory gate's judge set aside, on their own line.
    advisory_declared = {
        r["name"]: [_condition_line(c) for c in r["conditions"]["declared"]]
        for r in results
        if not r["blocking"] and (r.get("conditions") or {}).get("declared")
    }
    return {
        "schema": SCHEMA,
        "startedAt": started_at,
        "repo": str(repo),
        "headSha": _head_sha(repo),
        "gates": results,
        # Vacuous truth is not a verdict: no blocking gate ran, nothing ships.
        "complete": complete,
        "wouldShip": complete
        and bool([r for r in results if r["blocking"]])
        and not blocking_failed,
        "blockingFailures": blocking_failed,
        "advisoryFailures": advisory_failed,
        "advisoryDeclared": advisory_declared,
        "seconds": {
            "blocking": round(sum(r["seconds"] or 0 for r in results if r["blocking"]), 2),
            "total": round(sum(r["seconds"] or 0 for r in results), 2),
        },
    }


def render_text(receipt: dict) -> str:
    lines = [f"data gate set on {receipt['repo']} @ {receipt['headSha'] or 'unknown'}"]
    for gate in receipt["gates"]:
        kind = "blocking" if gate["blocking"] else "advisory"
        lines.append(f"  {gate['status']:7s} {kind:8s} {gate['seconds']:8.1f}s  {gate['name']}")
    for name, conditions in (receipt.get("advisoryDeclared") or {}).items():
        for line in conditions:
            lines.append(f"  declared advisory  {name}: {line}")
    lines.append(
        f"would ship: {receipt['wouldShip']}  "
        f"(blocking {receipt['seconds']['blocking']}s, total {receipt['seconds']['total']}s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the data gate set against a repository tree")
    run.add_argument("--repo", type=Path, default=Path.cwd(), help="the deploy target tree")
    run.add_argument("--receipt", type=Path, help="write the JSON receipt here")
    run.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only the named gate(s); repeatable (diagnostics, never the shadow)",
    )
    sub.add_parser("list", help="print the gate table")
    args = parser.parse_args(argv)

    gates = default_gates()
    if args.command == "list":
        for gate in gates:
            kind = "blocking" if gate.blocking else "advisory"
            print(f"{gate.name:22s} {kind:8s} {gate.mirrors}")
        return 0

    if args.only:
        unknown = sorted(set(args.only) - {g.name for g in gates})
        if unknown:
            parser.error(f"unknown gate(s): {', '.join(unknown)}")
        gates = tuple(g for g in gates if g.name in set(args.only))
    repo = args.repo.resolve()
    if not repo.is_dir():
        parser.error(f"--repo {repo} is not a directory")
    receipt = run_gates(gates, repo, receipt_path=args.receipt)
    if args.receipt:
        _write_receipt(args.receipt, receipt)
    print(render_text(receipt))
    return 0 if receipt["wouldShip"] else 1


if __name__ == "__main__":
    sys.exit(main())
