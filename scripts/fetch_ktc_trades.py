#!/usr/bin/env python3
"""Accumulate KeepTradeCut's Trade Database into the append-only raw archive.

    python scripts/fetch_ktc_trades.py                      # one polite fetch
    python scripts/fetch_ktc_trades.py --min-interval-minutes 50
    python scripts/fetch_ktc_trades.py --stats              # archive coverage only
    python scripts/fetch_ktc_trades.py --clear-stop         # after resolving an access stop

The page serves a ROLLING WINDOW of the most recent 200 trades, so a single
fetch is a snapshot; runs accumulate into ``data/market_trades/archive.sqlite``
(gitignored, never committed).  Identical rows re-seen on later runs are
stored once; a changed row is kept as a revision.  Owner: src/sources/ktc_trades.py.

Exit codes: 0 archived / not modified / skipped · 1 fetch failed, quarantined
or stopped (401/403/challenge, or 3 consecutive quarantines, persists a stop
that only --clear-stop lifts; --force bypasses the min interval only) · 2 rate limited.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources import ktc_trades  # noqa: E402
from src.trade import market_trade_archive as archive  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--min-interval-minutes", type=float, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore the min interval only; a persisted stop is lifted by --clear-stop alone",
    )
    parser.add_argument("--stats", action="store_true", help="print archive coverage and exit")
    parser.add_argument(
        "--clear-stop", action="store_true", help="clear a persisted access stop and exit"
    )
    args = parser.parse_args()

    if args.stats:
        print(json.dumps(archive.coverage(ktc_trades.SOURCE_FAMILY), indent=2))
        return 0
    if args.clear_stop:
        cleared = ktc_trades.clear_stop()
        print("stop cleared" if cleared else "no stop was set")
        return 0

    out = ktc_trades.collect(min_interval_minutes=args.min_interval_minutes, force=args.force)
    out["coverage"] = archive.coverage(ktc_trades.SOURCE_FAMILY)
    print(json.dumps(out, indent=2, default=str))
    outcome = out.get("outcome")
    if outcome in ("archived", "not_modified", "skipped_recent"):
        return 0
    if outcome == "rate_limited":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
