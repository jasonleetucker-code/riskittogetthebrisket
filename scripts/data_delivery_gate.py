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
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCHEMA = "data-delivery-gates/v1"

#: The environment the full pipeline gives these commands (deploy.yml validate).
_PIPELINE_ENV = {"ALLOW_DEFAULT_LOGIN_DEV": "1", "UPTIME_CHECK_ENABLED": "0"}

_TAIL_LINES = 40


@dataclass(frozen=True)
class Gate:
    name: str
    blocking: bool
    argv: tuple[str, ...]
    mirrors: str
    timeout_seconds: int
    env: dict[str, str] = field(default_factory=dict)


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
            argv=(python, "scripts/check_source_health.py", "--repo", "."),
            mirrors="pr-validation.yml / release-candidate.yml source-health lane (advisory)",
            timeout_seconds=600,
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
        ),
    )


def _tail(text: str) -> list[str]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-_TAIL_LINES:]


def run_gate(gate: Gate, repo: Path) -> dict:
    env = {**os.environ, **gate.env}
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
            timeout=gate.timeout_seconds,
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


def run_gates(gates: tuple[Gate, ...], repo: Path) -> dict:
    """Run every gate (a blocking failure does not stop the others) and judge."""
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = [run_gate(gate, repo) for gate in gates]
    blocking_failed = [r["name"] for r in results if r["blocking"] and r["status"] != "pass"]
    advisory_failed = [r["name"] for r in results if not r["blocking"] and r["status"] != "pass"]
    return {
        "schema": SCHEMA,
        "startedAt": started_at,
        "repo": str(repo),
        "headSha": _head_sha(repo),
        "gates": results,
        # Vacuous truth is not a verdict: no blocking gate ran, nothing ships.
        "wouldShip": bool([r for r in results if r["blocking"]]) and not blocking_failed,
        "blockingFailures": blocking_failed,
        "advisoryFailures": advisory_failed,
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
    receipt = run_gates(gates, repo)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.receipt.open("w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(render_text(receipt))
    return 0 if receipt["wouldShip"] else 1


if __name__ == "__main__":
    sys.exit(main())
