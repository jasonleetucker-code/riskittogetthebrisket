#!/usr/bin/env python3
"""Populate the unified Sharp market with Sleeper trades.

Discovery and season-record collection identify and score managers. This
third pass crawls only managers who actually cleared Sharp Score v2, then
feeds their public Sleeper transactions through the existing intel crawler
and normalized ledger. It is intentionally separate from discovery: finding
thousands of managers must not multiply the recurring transaction budget.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.intel import platform_ledger  # noqa: E402
from src.intel import service as intel_service  # noqa: E402
from src.intel import store as intel_store  # noqa: E402
from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import pass_coverage  # noqa: E402
from src.sharp import score as sharp_score  # noqa: E402

log = logging.getLogger("crawl_sharp_activity")

DEFAULT_LEAGUE_KEY = "sharp-tracker"
DEFAULT_BUDGET = 2_500
DEFAULT_MAX_MANAGERS = 250
DEFAULT_SLEEP_SECONDS = 0.12


def qualified_sleeper_ids() -> tuple[list[str], dict[str, Any]]:
    """Source Sleeper IDs of the automated-qualified sharp cohort.

    Resolved through ``src/sharp/cohort.py::cohort_members`` — the same
    call the Buy/Sell Tracker and the Roster Percentage board make.  It
    used to re-derive the pool here (``build_manager_records`` →
    ``score_managers`` → filter on ``qualified``), which was a second
    copy of the selection rules living in a script: a change to
    qualification moved the two boards and left the crawl that FEEDS
    them selecting a different set of managers.

    ``qualification="automated"`` is the deliberate slice.  Curated and
    provisional members are FFPC-only, and this pass crawls Sleeper.
    """
    members, coverage = sharp_cohort.cohort_members(qualification="automated")
    qualified = sorted(
        {
            member.manager_key.split(":", 1)[1]
            for member in members
            if member.manager_key.startswith("sleeper:")
        }
    )
    summary = {
        "methodologyVersion": sharp_score.methodology_version(),
        "evidenceManagers": coverage.get("evidenceManagers", 0),
        "qualifiedManagers": len(members),
        "qualifiedSleeperManagers": len(qualified),
    }
    return qualified, summary


def run_activity_crawl(
    *,
    budget: int = DEFAULT_BUDGET,
    max_managers: int = DEFAULT_MAX_MANAGERS,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    league_key: str = DEFAULT_LEAGUE_KEY,
) -> dict[str, Any]:
    manager_ids, cohort = qualified_sleeper_ids()
    selected = manager_ids[: max(1, int(max_managers))]
    before = platform_ledger.platform_coverage().get("sleeper") or {}

    if not selected:
        # Nothing eligible: a measured zero, reported through the same block as
        # every other run so an empty cohort is not a missing report.
        try:
            empty = pass_coverage.build_activity_coverage(
                eligible_managers=0,
                selected_managers=0,
                call_budget=max(1, int(budget)),
                refresh=None,
                state=None,
                breaker_refused_calls=None,
            )
            pass_coverage.log_pass_summary(log, empty)
        except Exception:  # noqa: BLE001 -- reporting must never fail the crawl
            log.warning("activity crawl: could not build pass coverage", exc_info=True)
            empty = None
        return {
            "status": "cohort_building",
            "message": "No Sleeper manager has cleared Sharp Score v2 yet; no activity crawl ran.",
            "cohort": cohort,
            "selectedManagers": 0,
            "coverageBefore": before,
            "coverageAfter": before,
            "stoppedReason": None if empty is None else empty["stoppedReason"],
            "passCoverage": empty,
        }

    call_budget = max(1, int(budget))
    breaker_before = pass_coverage.sleeper_breaker_fast_fails()
    refresh = intel_service.refresh_intel(
        member_ids=selected,
        league_key=league_key,
        budget=call_budget,
        sleep_s=max(0.0, float(sleep_seconds)),
    )
    breaker_refused = pass_coverage.breaker_refusals(
        breaker_before, pass_coverage.sleeper_breaker_fast_fails()
    )
    after = platform_ledger.platform_coverage().get("sleeper") or {}

    # Reporting only: where the crawl stands, read back from the snapshot the
    # refresh just persisted.  A snapshot that cannot be read leaves the
    # figures that need it ``null`` rather than guessed.
    try:
        state = intel_store.load_state(league_key)
    except Exception:  # noqa: BLE001 -- reporting must never fail the crawl
        log.warning("activity crawl: could not read the intel snapshot", exc_info=True)
        state = None
    try:
        coverage = pass_coverage.build_activity_coverage(
            eligible_managers=len(manager_ids),
            selected_managers=len(selected),
            call_budget=call_budget,
            refresh=refresh,
            state=state,
            breaker_refused_calls=breaker_refused,
        )
        pass_coverage.log_pass_summary(log, coverage)
    except Exception:  # noqa: BLE001 -- reporting must never fail the crawl
        # The refresh already ran and persisted; the coverage fields stay ``null``.
        log.warning("activity crawl: could not build pass coverage", exc_info=True)
        coverage = None
    return {
        "status": "success",
        "cohort": cohort,
        "selectedManagers": len(selected),
        "selectedManagerLimit": int(max_managers),
        "coverageBefore": before,
        "coverageAfter": after,
        "refresh": refresh,
        "stoppedReason": None if coverage is None else coverage["stoppedReason"],
        "passCoverage": coverage,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--max-managers", type=int, default=DEFAULT_MAX_MANAGERS)
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--league-key", default=DEFAULT_LEAGUE_KEY)
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print qualification and current Sleeper coverage without crawling.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Same logging setup as the other three passes, so the one-line coverage
    # summary (WARNING when the run stopped short) reaches the journal.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.stats:
        _ids, cohort = qualified_sleeper_ids()
        payload = {
            "status": "stats",
            "cohort": cohort,
            "coverage": platform_ledger.platform_coverage().get("sleeper") or {},
        }
    else:
        payload = run_activity_crawl(
            budget=args.budget,
            max_managers=args.max_managers,
            sleep_seconds=args.sleep_seconds,
            league_key=str(args.league_key or DEFAULT_LEAGUE_KEY),
        )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
