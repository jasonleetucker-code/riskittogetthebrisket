#!/usr/bin/env python3
"""Read-only stage profiler for V1-61 Sharp Roster Percentage.

This script does not implement a second roster-percentage engine and does not
change any product result. It calls the canonical
``src.sharp.roster_percentage.build_board`` function while temporarily
wrapping its existing stage owners with timers, then prints a JSON timing
report to stdout.

The purpose is narrow: production verification has repeatedly shown
``/api/sharp/roster-percentage`` exceeding the authenticated verifier's read
timeout even after connection reuse and batched historical holdings reads.
Before another optimization, measure which canonical stage actually owns the
remaining wall time.

Truthfulness rules:
- missing data remains missing; no values are substituted;
- no auth or feature flags are changed;
- no database writes are performed by this script itself;
- the canonical implementation is executed exactly once;
- a timeout/error is reported as such, never as an empty or healthy result.
"""

from __future__ import annotations

import argparse
import functools
import json
import signal
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

# When invoked as ``python scripts/profile_sharp_roster_percentage.py``, Python
# places ``scripts/`` rather than the repository root at sys.path[0].  The
# production Lane 4 runner executes the profiler in exactly that form, so make
# the repository root explicit before importing the canonical ``src`` package.
# This changes import plumbing only; it does not alter product inputs, outputs,
# auth, methodology, or missing-data semantics.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import roster_percentage as roster_percentage  # noqa: E402
from src.sharp import roster_store  # noqa: E402


class ProfileTimeout(RuntimeError):
    """Raised when the bounded profiler wall-clock budget is exhausted."""


class StageRecorder:
    def __init__(self) -> None:
        self._stats: OrderedDict[str, dict[str, float | int]] = OrderedDict()
        self._restores: list[tuple[Any, str, Callable[..., Any]]] = []

    def wrap(self, owner: Any, attr: str, label: str) -> None:
        original = getattr(owner, attr)
        stats = self._stats.setdefault(
            label,
            {"calls": 0, "totalMs": 0.0, "maxMs": 0.0},
        )

        @functools.wraps(original)
        def timed(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                stats["calls"] = int(stats["calls"]) + 1
                stats["totalMs"] = float(stats["totalMs"]) + elapsed_ms
                stats["maxMs"] = max(float(stats["maxMs"]), elapsed_ms)

        self._restores.append((owner, attr, original))
        setattr(owner, attr, timed)

    def restore(self) -> None:
        while self._restores:
            owner, attr, original = self._restores.pop()
            setattr(owner, attr, original)

    def report(self) -> dict[str, dict[str, float | int]]:
        return {
            label: {
                "calls": int(stats["calls"]),
                "totalMs": round(float(stats["totalMs"]), 3),
                "maxMs": round(float(stats["maxMs"]), 3),
            }
            for label, stats in self._stats.items()
        }


def _latest_contract_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates = sorted((root / "exports" / "latest").glob("dynasty_data_*.json"))
    if not candidates:
        raise FileNotFoundError("no exports/latest/dynasty_data_*.json contract found")
    return candidates[-1]


def _load_contract(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"contract file is not a JSON object: {path}")
    if isinstance(raw.get("playersArray"), list):
        return raw
    for key in ("contract", "data"):
        nested = raw.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("playersArray"), list):
            return nested
    raise ValueError(f"contract file has no playersArray payload: {path}")


def _install_stage_wrappers(recorder: StageRecorder) -> None:
    # These are the existing canonical calls made by build_board().  Wrapping
    # records wall time only; arguments, return values, exceptions and owners
    # remain untouched.
    recorder.wrap(sharp_cohort, "cohort_members", "cohort_members")
    recorder.wrap(roster_store, "ensure_roster_schema", "ensure_roster_schema")
    recorder.wrap(roster_store, "load_rosters", "load_rosters")
    recorder.wrap(roster_percentage, "eligible_rosters", "eligible_rosters")
    recorder.wrap(roster_percentage, "_tally", "tally")
    recorder.wrap(roster_percentage, "_denominators", "denominators")
    recorder.wrap(roster_percentage, "build_player_index", "build_player_index")
    recorder.wrap(roster_percentage, "_catalog_metadata", "catalog_metadata")
    recorder.wrap(roster_percentage, "_buy_sell_index", "buy_sell_index")
    recorder.wrap(roster_store, "holdings_as_of_multi", "holdings_as_of_multi")
    recorder.wrap(roster_percentage, "_market_ownership", "market_ownership")
    recorder.wrap(roster_percentage, "_fallback_metadata", "fallback_metadata")
    recorder.wrap(roster_percentage, "_transparency", "transparency")
    recorder.wrap(roster_percentage, "_sort_rows", "sort_rows")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="contract JSON; defaults to newest exports/latest/dynasty_data_*.json",
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="optional canonical ledger path; omit to use the product default",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="hard wall-clock budget; timeout is reported truthfully (default: 300)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be > 0")

    contract_path = args.contract or _latest_contract_path()
    contract = _load_contract(contract_path)
    recorder = StageRecorder()
    _install_stage_wrappers(recorder)

    started = time.perf_counter()
    status = "error"
    error: str | None = None
    payload: dict[str, Any] | None = None

    previous_handler = None
    if hasattr(signal, "SIGALRM"):
        previous_handler = signal.getsignal(signal.SIGALRM)

        def _alarm(_signum: int, _frame: Any) -> None:
            raise ProfileTimeout(
                f"canonical build exceeded {args.timeout_seconds}s profiler budget"
            )

        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, float(args.timeout_seconds))

    try:
        payload = roster_percentage.build_board(
            contract=contract,
            ledger_path=args.ledger_path,
        )
        status = "ok"
    except ProfileTimeout as exc:
        status = "timeout"
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - profiler must preserve/report the real failure
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.setitimer(signal.ITIMER_REAL, 0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)
        recorder.restore()

    wall_ms = (time.perf_counter() - started) * 1000.0
    report: dict[str, Any] = {
        "status": status,
        "wallMs": round(wall_ms, 3),
        "contractPath": str(contract_path),
        "contractPlayers": len(contract.get("playersArray") or []),
        "ledgerPath": str(args.ledger_path) if args.ledger_path else None,
        "stages": recorder.report(),
        "result": None,
        "error": error,
    }
    if payload is not None:
        report["result"] = {
            "status": payload.get("status"),
            "totalQualifyingPlayers": payload.get("totalQualifyingPlayers"),
            "returnedPlayers": len(payload.get("players") or []),
            "eligibleRosters": ((payload.get("sample") or {}).get("eligibleRosters")),
            "storedRosters": ((payload.get("exclusions") or {}).get("storedRosters")),
            "lastUpdated": payload.get("lastUpdated"),
        }

    print(json.dumps(report, indent=2, sort_keys=False))
    if status == "ok":
        return 0
    if status == "timeout":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
