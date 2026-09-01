#!/usr/bin/env python3
"""Read-only stage profiler for V1-62 Sharp Tracker (``/api/sharp/market``).

This script does not implement a second market engine and does not change
any product result. It calls the canonical ``src.sharp.market.market_payload``
function exactly as the HTTP route (``src/sharp/service.py::get_market``)
calls it -- default ``ffpc_config=None`` -- while temporarily wrapping its
existing stage owners with timers, then prints a JSON timing report.

Purpose: V1-62's required L4 evidence has repeatedly shown
``/api/sharp/market`` timing out on the remote authenticated-verification
path while passing on-box, the same symptom class V1-61 had before its
``/api/sharp/roster-percentage`` fix.

Profiling with this script surfaced something more fundamental than the
``ffpc_config`` cache-key mismatch it was written to test (that mismatch is
real too, and both are now fixed): the W15-F017 cohort memo
(``src/sharp/cohort.py``) was silently self-poisoning on EVERY call,
including two calls made microseconds apart with an identical key.
``_compute_cohort_members`` calls ``curated_industry_members`` on every
build, which reaches ``curated.ensure_schema`` -- and that function
performed an UNCONDITIONAL ``INSERT OR REPLACE INTO meta(...)`` + commit
on every single call, writing to the exact ledger sqlite file whose
``(mtime_ns, size)`` is the memo's only freshness signal. So the very act
of building a cohort invalidated the cache entry it was about to store,
before the next caller could ever see a hit -- inside ``market_payload``
itself (two ``cohort_members`` calls per request, line 394-ish and
517-ish, never shared) as well as across requests and across endpoints.
Fixed in ``src/sharp/curated.py::ensure_schema`` by making the version
stamp write conditional on the value actually needing to change. With
that fixed, the ``ffpc_config`` key-mismatch fix in ``market.py`` (passing
the ORIGINAL argument to ``cohort_members`` instead of the pre-resolved
dict) lets ``market.py`` and ``roster_percentage.py`` share one cohort
build across endpoints, as W15-F017 originally intended.

``--simulate-shared-memo`` demonstrates both effects together: after the
fix, repeat ``market_payload`` calls in one process do ONE cohort compute
(previously N), and warming the memo under ``roster_percentage``'s own
call shape (no explicit ``ffpc_config``) is now visible to a subsequent
``market_payload`` call too.

Truthfulness rules (same as ``profile_sharp_roster_percentage.py``):
- missing data remains missing; no values are substituted;
- no auth or feature flags are changed;
- no database writes are performed by this script itself;
- the canonical implementation is executed exactly as production calls it;
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

# Same sys.path fix as profile_sharp_roster_percentage.py -- this script is
# invoked as ``python scripts/profile_sharp_market.py``, which puts
# ``scripts/`` rather than the repo root at sys.path[0].
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.intel import platform_ledger  # noqa: E402
from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import consensus as sharp_consensus  # noqa: E402
from src.sharp import market as sharp_market  # noqa: E402
from src.sharp import platform_records as sharp_platform_records  # noqa: E402
from src.sharp import score as sharp_score  # noqa: E402


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


def _install_stage_wrappers(recorder: StageRecorder) -> None:
    # ``market.py`` imports ``cohort_members`` (and the other cohort names)
    # by value -- ``from src.sharp.cohort import (..., cohort_members, ...)``
    # -- so ``market`` module's own attribute is the one ``market_payload``
    # actually calls, and it must be wrapped there to see real call counts.
    # ``_compute_cohort_members`` is only ever called from inside
    # ``cohort.py`` itself, so wrapping it on ``sharp_cohort`` is correct.
    recorder.wrap(sharp_market, "cohort_members", "market_cohort_members_call")
    recorder.wrap(sharp_cohort, "_compute_cohort_members", "cohort_compute")
    recorder.wrap(sharp_cohort, "load_ffpc_config", "cohort_load_ffpc_config")
    recorder.wrap(
        sharp_platform_records,
        "build_manager_records",
        "cohort_build_manager_records",
    )
    recorder.wrap(sharp_score, "score_managers", "cohort_score_managers")
    recorder.wrap(sharp_cohort, "curated_members", "cohort_curated_members")
    recorder.wrap(sharp_cohort, "provisional_members", "cohort_provisional_members")
    recorder.wrap(
        sharp_cohort,
        "curated_industry_members",
        "cohort_curated_industry_members",
    )
    recorder.wrap(platform_ledger, "query_movements", "query_movements")
    recorder.wrap(platform_ledger, "platform_coverage", "platform_coverage")
    recorder.wrap(sharp_market, "_aggregate_window", "aggregate_window")
    recorder.wrap(sharp_consensus, "aggregate_person_consensus", "aggregate_person_consensus")
    recorder.wrap(sharp_market, "_sort_rows", "sort_rows")


def _timed_call(
    label: str,
    fn: Callable[[], Any],
    *,
    timeout_seconds: int,
) -> tuple[str, float, Any, str | None]:
    previous_handler = None
    if hasattr(signal, "SIGALRM"):
        previous_handler = signal.getsignal(signal.SIGALRM)

        def _alarm(_signum: int, _frame: Any) -> None:
            raise ProfileTimeout(f"{label} exceeded {timeout_seconds}s profiler budget")

        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))

    started = time.perf_counter()
    status = "error"
    error: str | None = None
    result: Any = None
    try:
        result = fn()
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
    wall_ms = (time.perf_counter() - started) * 1000.0
    return status, round(wall_ms, 3), result, error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="optional canonical ledger path; omit to use the product default",
    )
    parser.add_argument(
        "--window",
        default="30d",
        help="window param, as the /api/sharp/market route would pass it (default: 30d)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="hard wall-clock budget per call; timeout is reported truthfully (default: 300)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=2,
        help=(
            "number of consecutive market_payload calls to make in this process, "
            "to separate first-call (cold cohort build) cost from same-key "
            "repeat-call (warm W15-F017 memo) cost (default: 2)"
        ),
    )
    parser.add_argument(
        "--simulate-shared-memo",
        action="store_true",
        help=(
            "additionally warm the cohort memo under roster_percentage's own "
            "call shape (qualification=all, no ffpc_config -> cache signal "
            "'file') immediately before a market_payload call, to measure "
            "whether the candidate fix (passing the original ffpc_config, "
            "None by default, instead of the resolved dict) would let the "
            "two endpoints share one cohort build. This does not change "
            "market.py; it calls cohort_members directly the way "
            "roster_percentage.py does, using the SAME cohort_members "
            "entrypoint market_payload itself calls."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be > 0")
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")

    recorder = StageRecorder()
    _install_stage_wrappers(recorder)

    report: dict[str, Any] = {
        "ledgerPath": str(args.ledger_path) if args.ledger_path else None,
        "window": args.window,
        "calls": [],
        "simulatedSharedMemoCall": None,
        "stages": None,
        "overallStatus": "error",
    }

    overall_status = "ok"
    try:
        for i in range(args.repeat):
            label = f"market_payload_call_{i + 1}"
            status, wall_ms, payload, error = _timed_call(
                label,
                lambda: sharp_market.market_payload(
                    window=args.window,
                    ledger_path=args.ledger_path,
                ),
                timeout_seconds=args.timeout_seconds,
            )
            call_report: dict[str, Any] = {
                "call": label,
                "status": status,
                "wallMs": wall_ms,
                "error": error,
            }
            if payload is not None:
                call_report["result"] = {
                    "status": payload.get("status"),
                    "assetCount": len(payload.get("assets") or []),
                    "selectedManagers": (payload.get("cohort") or {}).get("selectedManagers"),
                    "automatedQualifiedManagers": (payload.get("cohort") or {}).get(
                        "automatedQualifiedManagers"
                    ),
                }
            report["calls"].append(call_report)
            if status != "ok":
                overall_status = status

        if args.simulate_shared_memo and overall_status == "ok":
            # Warm the memo under roster_percentage's exact call shape
            # (no ffpc_config argument at all -- key signal "file").
            warm_status, warm_ms, _warm_result, warm_error = _timed_call(
                "roster_percentage_shaped_cohort_warm",
                lambda: sharp_cohort.cohort_members(
                    qualification="all", ledger_path=args.ledger_path
                ),
                timeout_seconds=args.timeout_seconds,
            )
            after_status, after_ms, after_payload, after_error = _timed_call(
                "market_payload_after_roster_percentage_shaped_warm",
                lambda: sharp_market.market_payload(
                    window=args.window,
                    ledger_path=args.ledger_path,
                ),
                timeout_seconds=args.timeout_seconds,
            )
            report["simulatedSharedMemoCall"] = {
                "warmStatus": warm_status,
                "warmMs": warm_ms,
                "warmError": warm_error,
                "marketAfterWarmStatus": after_status,
                "marketAfterWarmMs": after_ms,
                "marketAfterWarmError": after_error,
            }
            if after_status != "ok":
                overall_status = after_status
    finally:
        report["stages"] = recorder.report()
        recorder.restore()

    report["overallStatus"] = overall_status
    print(json.dumps(report, indent=2, sort_keys=False))
    if overall_status == "ok":
        return 0
    if overall_status == "timeout":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
