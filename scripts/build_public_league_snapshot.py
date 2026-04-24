"""Build + persist the public league snapshot from the command line.

    python scripts/build_public_league_snapshot.py [--league-id <id>] [--no-players]

The resulting files live under ``data/public_league/``.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import league_registry  # noqa: E402
from src.public_league import build_public_contract, build_public_snapshot  # noqa: E402
from src.public_league import snapshot_store  # noqa: E402


def _default_league_id() -> str:
    """Pick the default --league-id for the CLI:
       1. ``SLEEPER_LEAGUE_ID`` env var (explicit operator override)
       2. The registry's default league
       3. Empty string (caller must pass --league-id)

    Removes the hardcoded Sleeper ID that used to live here; the
    registry is now the source of truth per the multi-league audit.
    """
    env = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
    if env:
        return env
    reg = league_registry.get_sleeper_league_id()
    return reg or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league-id",
        default=_default_league_id(),
        help=(
            "Sleeper league id to start the chain walk from.  Defaults "
            "to SLEEPER_LEAGUE_ID env var → registry default → empty."
        ),
    )
    parser.add_argument(
        "--max-seasons",
        type=int,
        default=2,
        help="Max dynasty seasons to ingest (default 2).",
    )
    parser.add_argument(
        "--no-players",
        action="store_true",
        help="Skip the ~5 MB players/nfl fetch (position breakdowns will be empty).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    snapshot = build_public_snapshot(
        args.league_id,
        max_seasons=args.max_seasons,
        include_nfl_players=not args.no_players,
    )
    if not snapshot.seasons:
        logging.error("No seasons ingested — check league id %s", args.league_id)
        return 2
    contract = build_public_contract(snapshot)
    snapshot_store.persist_snapshot(snapshot, contract=contract)
    logging.info(
        "Persisted snapshot for league %s (%d seasons, %d managers) to %s",
        snapshot.root_league_id,
        len(snapshot.seasons),
        len(snapshot.managers.by_owner_id),
        snapshot_store.DATA_DIR,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
