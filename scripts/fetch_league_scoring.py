#!/usr/bin/env python3
"""Snapshot each configured league's ACTUAL scoring card from Sleeper.

The cross-league ranking-compatibility gate (W18-F001) compares factual
scoring fingerprints, not the hand-typed ``scoringProfile`` label, and it
reads snapshots rather than fetching inside a request — an 8 s Sleeper
round-trip in the ``/api/data`` gate would trade a correctness bug for a
latency one.  This script writes those snapshots.

Normally unnecessary: ``server.py``'s post-scrape warm pass refreshes
every active league's card on the same cadence as the scrape.  Run it by
hand on a fresh deploy (before the first scrape), after adding a league
to ``config/leagues/registry.json``, or after a commissioner changes
scoring settings and you do not want to wait for the next refresh.

Exit codes
    0  every requested league now has a snapshot
    1  at least one league could not be snapshotted
    2  nothing to do — no leagues configured / none matched
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import league_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league",
        action="append",
        default=[],
        metavar="KEY",
        help="registry league key; repeatable.  Default: every ACTIVE league.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="include inactive leagues too.",
    )
    args = parser.parse_args()

    if args.league:
        configs = [league_registry.get_league_by_key(key) for key in args.league]
        missing = [key for key, cfg in zip(args.league, configs) if cfg is None]
        for key in missing:
            print(f"ERROR: unknown league key {key!r}", file=sys.stderr)
        configs = [cfg for cfg in configs if cfg is not None]
        if missing and not configs:
            return 2
    elif args.all:
        configs = list(league_registry.all_leagues())
    else:
        configs = list(league_registry.active_leagues())

    if not configs:
        print("no leagues configured — nothing to snapshot", file=sys.stderr)
        return 2

    failures = 0
    for cfg in configs:
        fingerprint = league_registry.refresh_scoring_snapshot(cfg)
        if fingerprint:
            path = league_registry.scoring_snapshot_path(cfg.sleeper_league_id)
            print(f"{cfg.key}: {fingerprint}  ->  {path}")
        else:
            failures += 1
            print(f"{cfg.key}: FAILED (previous snapshot, if any, left in place)", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
