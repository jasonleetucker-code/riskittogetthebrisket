#!/usr/bin/env python3
"""Crawl multi-season manager records for the Sharp Score.

Discovery finds MANAGERS; this finds their RECORDS — completed seasons,
W/L, playoff appearances, championships, finishes — by walking each
sharp-eligible league's ``previous_league_id`` chain. Without it no
manager can be scored and /market/sharp-tracker stays "cohort building".

    python scripts/crawl_sharp_records.py             # budgeted pass
    python scripts/crawl_sharp_records.py --budget 3000
    python scripts/crawl_sharp_records.py --league 12345  # one chain
    python scripts/crawl_sharp_records.py --stats      # coverage only
    python scripts/crawl_sharp_records.py --score      # score + report

Costs 4 Sleeper calls per league-season (league, rosters,
winners_bracket for completed seasons, plus the chain hop). Idempotent:
rows upsert on (league_id, season, user_id).

The default league order is persistent and fair: leagues with no stored
season rows are crawled first, then previously crawled leagues from oldest
to newest. That makes repeated budgeted runs advance through the full graph
instead of restarting at the same insertion-ordered prefix every day.

Exit codes: 0 success, 1 failure, 2 budget exhausted with work left.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import discovery, record_queue, records  # noqa: E402
from src.sharp import score as sharp_score  # noqa: E402

log = logging.getLogger("crawl_sharp_records")


def _stats_payload() -> dict:
    payload = records.records_coverage()
    payload["queue"] = record_queue.queue_stats()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=None, help="Max Sleeper API calls.")
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="Crawl only this league id's chain (repeatable).",
    )
    parser.add_argument("--max-seasons", type=int, default=None)
    parser.add_argument("--stats", action="store_true", help="Print coverage and exit.")
    parser.add_argument(
        "--score", action="store_true", help="Score the cohort from stored records and report."
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.stats:
            print(json.dumps(_stats_payload(), indent=2))
            return 0

        if args.score:
            recs = records.build_manager_records()
            scored = sharp_score.score_managers(recs)
            payload = {
                "tiers": sharp_score.cohort_tiers(scored),
                "qualified": [
                    s.to_dict()
                    for s in sorted(
                        (x for x in scored if x.qualified),
                        key=lambda x: -(x.score or 0),
                    )[:25]
                ],
            }
            print(json.dumps(payload, indent=2))
            return 0

        kwargs = {}
        if args.budget is not None:
            kwargs["budget"] = args.budget
        if args.max_seasons is not None:
            kwargs["max_seasons"] = args.max_seasons

        league_ids = args.leagues
        if league_ids is None:
            league_ids = record_queue.prioritized_league_ids()
        result = records.crawl_records(league_ids=league_ids, **kwargs)

        payload = result.to_dict()
        payload["coverage"] = records.records_coverage()
        payload["queue"] = record_queue.queue_stats()
        payload["sharpEligibleLeagues"] = len(discovery.sharp_eligible_league_ids())
        print(json.dumps(payload, indent=2))
        # Partial is normal on a large graph — the next run continues.
        return 2 if result.budget_exhausted else 0
    except Exception:  # noqa: BLE001
        log.exception("records crawl failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
