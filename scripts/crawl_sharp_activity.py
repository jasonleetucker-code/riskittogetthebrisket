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
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.intel import platform_ledger  # noqa: E402
from src.intel import service as intel_service  # noqa: E402
from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import score as sharp_score  # noqa: E402

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
        return {
            "status": "cohort_building",
            "message": "No Sleeper manager has cleared Sharp Score v2 yet; no activity crawl ran.",
            "cohort": cohort,
            "selectedManagers": 0,
            "coverageBefore": before,
            "coverageAfter": before,
        }

    refresh = intel_service.refresh_intel(
        member_ids=selected,
        league_key=league_key,
        budget=max(1, int(budget)),
        sleep_s=max(0.0, float(sleep_seconds)),
    )
    after = platform_ledger.platform_coverage().get("sleeper") or {}
    return {
        "status": "success",
        "cohort": cohort,
        "selectedManagers": len(selected),
        "selectedManagerLimit": int(max_managers),
        "coverageBefore": before,
        "coverageAfter": after,
        "refresh": refresh,
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
