#!/usr/bin/env python3
"""Grow the Sharp Tracker manager-discovery graph.

Walks outward from the seed leagues/users in
``config/sharp/discovery_seeds.json``:

    league -> members -> their leagues -> those leagues' members -> ...

Sleeper has no global user or league directory, so this outward walk is
the only way to build a cohort. Each run is budgeted and idempotent, so
running it repeatedly compounds coverage instead of redoing work.

    python scripts/discover_sharp_graph.py                  # one budgeted run
    python scripts/discover_sharp_graph.py --budget 5000
    python scripts/discover_sharp_graph.py --generations 3
    python scripts/discover_sharp_graph.py --stats          # report only
    python scripts/discover_sharp_graph.py --add-league 123 # register a league you joined

NOTE ON SEEDS: a seed league does NOT need to be a dynasty league. Seeds
exist to find MANAGERS. Only dynasty/keeper leagues ever feed the
transaction signal — a large redraft tournament is among the best seeds
available precisely because it puts many unrelated managers in one place.

Exit codes: 0 success, 1 failure, 2 partial (budget exhausted).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import discovery  # noqa: E402

log = logging.getLogger("discover_sharp_graph")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=None, help="Max Sleeper API calls this run.")
    parser.add_argument("--generations", type=int, default=None, help="Max BFS depth.")
    parser.add_argument("--stats", action="store_true", help="Print graph coverage and exit.")
    parser.add_argument(
        "--add-league",
        action="append",
        dest="add_leagues",
        help="Register a Sleeper league id as a new seed (repeatable), then exit.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.add_leagues:
            added = discovery.add_seed_leagues(args.add_leagues)
            print(json.dumps({"seedLeaguesAdded": added}, indent=2))
            return 0

        if args.stats:
            print(json.dumps(discovery.graph_stats(), indent=2))
            return 0

        result = discovery.discover(budget=args.budget, max_generations=args.generations)
        payload = result.to_dict()
        payload["graph"] = discovery.graph_stats()
        print(json.dumps(payload, indent=2))

        # Partial is a normal outcome on a large graph, not a failure —
        # the frontier is resumable and the next run continues it.
        return 2 if result.budget_exhausted else 0
    except Exception:  # noqa: BLE001
        log.exception("discovery failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
