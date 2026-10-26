"""Refresh the automatic DFS slates (DFS-AUTO-07 / DFS-AUTO-19) — the timer's entry point.

Every automatic sport (NFL weekly; NBA and NHL daily) decides for itself whether
it is due.  Exit codes: 0 at least one sport refreshed and none failed, 1 a
source failed for some sport (its last good slates are kept, labelled
SOURCE_ERROR), 2 nothing was due or there was nothing to build (offseason, an
off day, a page listing no slate yet).  ``--force`` ignores the cadence;
``--sport`` limits the tick to one sport.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAILED = {"source_error", "partial"}
REFRESHED = {"ok"}


def exit_code(results: dict[str, dict]) -> int:
    outcomes = {r.get("outcome") for r in results.values()}
    if outcomes & FAILED:
        return 1
    return 0 if outcomes & REFRESHED else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="refresh even when nothing is due")
    ap.add_argument(
        "--sport", choices=("all", "nfl", "nba", "nhl"), default="all", help="limit to one sport"
    )
    args = ap.parse_args(argv)
    from src.dfs.auto import live

    if args.sport == "all":
        results = live.refresh_all_live(force=args.force)
    else:
        results = {args.sport: live.refresh_live(args.sport, force=args.force)}
    for sport, result in results.items():
        head = {k: v for k, v in result.items() if k != "platforms"}
        print(sport, json.dumps(head, default=str))
        for platform, detail in (result.get("platforms") or {}).items():
            print(
                f"  {platform}",
                json.dumps(
                    {k: v for k, v in detail.items() if k not in ("pool", "report")}, default=str
                ),
            )
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
