#!/usr/bin/env python3
"""Collect the CURRENT rosters of the sharp cohort, on both platforms.

Discovery finds MANAGERS, ``crawl_sharp_records.py`` finds their
RECORDS — this finds what they currently OWN, which is what
``/market/sharp-roster-percentage`` is made of.  Without it that page
reports ``cohort_building`` and an empty board, exactly as the Buy/Sell
Tracker does before a records crawl.

    python scripts/crawl_sharp_rosters.py                 # budgeted pass
    python scripts/crawl_sharp_rosters.py --budget 2000
    python scripts/crawl_sharp_rosters.py --ffpc-only     # zero API calls
    python scripts/crawl_sharp_rosters.py --stats         # coverage only
    python scripts/crawl_sharp_rosters.py --audit 4046    # one player

Costs 2 Sleeper calls per league (``/league/{id}`` for format + status,
``/league/{id}/rosters`` for the holdings), regardless of how many
cohort members play in it.  FFPC costs ZERO calls — its roster contents
already arrive with the public-page crawl and are only lifted into the
queryable store here.

Idempotent: rosters upsert on ``roster_key`` and holdings upsert on
``(roster_key, canonical_asset_id)``, so a re-run overwrites rather than
inflating any count.

Exit codes: 0 success, 1 failure, 2 budget exhausted with work left.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import roster_collect, roster_percentage, roster_store  # noqa: E402

log = logging.getLogger("crawl_sharp_rosters")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=roster_collect.DEFAULT_BUDGET)
    parser.add_argument("--sleep", type=float, default=roster_collect.DEFAULT_SLEEP_S)
    parser.add_argument(
        "--qualification",
        default="all",
        choices=list(roster_percentage.sharp_cohort.ALLOWED_QUALIFICATION),
        help="Which slice of the sharp cohort to collect for.",
    )
    parser.add_argument("--sleeper-only", action="store_true")
    parser.add_argument("--ffpc-only", action="store_true")
    parser.add_argument("--stats", action="store_true", help="Print coverage and exit.")
    parser.add_argument("--audit", metavar="ASSET_ID", help="Audit one player and exit.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.stats:
        print(
            json.dumps(
                {
                    "store": roster_store.coverage(),
                    "exclusionReasons": roster_store.exclusion_reason_counts(),
                },
                indent=2,
            )
        )
        return 0

    if args.audit:
        print(json.dumps(roster_percentage.audit_player(args.audit), indent=2))
        return 0

    run_id = f"sharp-rosters-{uuid.uuid4().hex[:12]}"
    started = int(time.time() * 1000)
    try:
        summary = roster_collect.collect_all(
            qualification=args.qualification,
            budget=args.budget,
            sleep_s=args.sleep,
            run_id=run_id,
            skip_sleeper=args.ffpc_only,
            skip_ffpc=args.sleeper_only,
        )
    except Exception:  # noqa: BLE001 — the script's job is an exit code
        log.exception("sharp roster crawl failed")
        return 1
    finished = int(time.time() * 1000)

    try:
        roster_collect.record_collection_run(
            summary, started_ms=started, finished_ms=finished, run_id=run_id
        )
    except Exception:  # noqa: BLE001 — bookkeeping must not fail the crawl
        log.exception("sharp roster crawl: run bookkeeping failed")

    print(json.dumps(summary, indent=2))
    if summary.get("sleeper", {}).get("budgetExhausted"):
        log.warning("budget exhausted with leagues still uncollected — re-run to continue")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
