#!/usr/bin/env python3
"""Run one Game Day live-collector tick (Game Day U5).

The systemd timer ``dynasty-game-day-live`` fires this every minute; the
tick itself decides whether it is due (``src/ros/game_day_live.py``'s
cadence: ~60 s while any game is live, a few minutes near a kickoff,
hourly otherwise).  A not-due run exits 2 BEFORE importing the heavy Game
Day modules, so the per-minute firing costs one small JSON read.

Each due tick fetches the ESPN scoreboard, Sleeper live stats, Sleeper
weekly projections (when due — at least one inside the final ten minutes
before every kickoff) and every active league's league / users / rosters /
matchups; persists every observation append-only under
``data/game_day/live/``; and publishes a new versioned generation per
league-week only when the input content changed.

Exit codes
    0  tick ran and every league-week is current
    1  tick ran and at least one league-week (or the tick itself) failed
    2  nothing to do: not due, another tick holds the lock, out of season,
       or the host stated no week
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="run now even if the cadence says not due"
    )
    parser.add_argument("--json", action="store_true", help="print the tick report as JSON")
    args = parser.parse_args(argv)

    # Cheap pre-check first: most per-minute firings stop here.
    from src.ros import game_day_live

    if not args.force and not game_day_live.tick_due(time.time()):
        if args.json:
            print(json.dumps({"outcome": "not_due", "exitCode": 2}))
        return 2

    report = game_day_live.run_tick(force=args.force)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        leagues = ", ".join(
            f"{k}={v.get('outcome')}" + (f"({v.get('error')})" if v.get("error") else "")
            for k, v in sorted(report.leagues.items())
        )
        print(
            f"game-day-live: outcome={report.outcome} exit={report.exit_code} "
            f"season={report.season} week={report.week} "
            f"phase={(report.cadence or {}).get('phase')} "
            f"nextDueAt={(report.cadence or {}).get('nextDueAt')} "
            f"requests={len(report.requests)} leagues=[{leagues}]"
            + (f" error={report.error}" if report.error else "")
        )
    return int(report.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
