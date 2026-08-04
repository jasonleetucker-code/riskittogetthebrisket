#!/usr/bin/env python3
"""Crawl transactions from the sharp-eligible leagues.

Discovery finds MANAGERS, records finds their RESULTS — this finds
their TRADES, which is what /market/sharp-tracker's board is made of.

Until this existed, ``ledger.ingest_events`` had exactly one caller
(Insider Trading's snapshot migration), so the ledger held only the
user's own league-mates and a sharp board would have rendered empty.

    python scripts/crawl_sharp_transactions.py              # budgeted pass
    python scripts/crawl_sharp_transactions.py --budget 2000
    python scripts/crawl_sharp_transactions.py --league 12345   # one league
    python scripts/crawl_sharp_transactions.py --stats          # coverage only

Costs 1 call per league for rosters plus one per transaction week —
three weeks on a league's first pass (the backfill walks to week 0,
where Sleeper files preseason trades), one per run after that.
Idempotent: movements dedupe on the roster-slot key, so a re-run or an
interrupted pass re-ingests nothing.

Both sides of every trade are recorded; the board filters to the
QUALIFIED cohort at read time. See src/sharp/transactions.py for why
that ordering is deliberate.

Exit codes: 0 success, 1 failure, 2 budget exhausted with leagues left.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import transactions  # noqa: E402

log = logging.getLogger("crawl_sharp_transactions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=None, help="Max Sleeper API calls.")
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="Crawl only this league id (repeatable). Default: every sharp-eligible league.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Report crawl coverage and exit without fetching anything.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        if args.stats:
            print(json.dumps(transactions.crawl_coverage(), indent=2))
            return 0

        kwargs = {}
        if args.budget is not None:
            kwargs["budget"] = args.budget
        result = transactions.crawl_transactions(league_ids=args.leagues, **kwargs)

        payload = result.to_dict()
        payload["coverage"] = transactions.crawl_coverage()
        print(json.dumps(payload, indent=2))
        # Partial is normal on a large graph — the next run continues
        # from the cursor, uncrawled leagues first.
        return 2 if result.leagues_pending else 0
    except Exception:  # noqa: BLE001
        log.exception("sharp transaction crawl failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
