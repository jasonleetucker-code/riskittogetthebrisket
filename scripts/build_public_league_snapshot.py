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
       1. The registry's default league (``config/leagues/registry.json``)
       2. ``SLEEPER_LEAGUE_ID`` env var (no registry file — fresh dev
          box / CI without config)
       3. Empty string (caller must pass --league-id)

    Registry-first is the platform-wide pattern (CLAUDE.md: "never
    read ``os.getenv('SLEEPER_LEAGUE_ID')`` in new code").  This CLI
    used to read the env var FIRST, which inverted the precedence
    every other consumer uses: on a multi-league host that still has
    the legacy single-league env var exported, the snapshot would be
    built for whatever that var points at rather than the registry's
    default league.

    ``get_sleeper_league_id()`` already synthesises a one-league
    registry from the env var when no registry file exists, so step 2
    is only reachable if that synthesis failed (e.g. the registry
    import raised).  It stays as a belt-and-braces fallback.

    Removes the hardcoded Sleeper ID that used to live here; the
    registry is now the source of truth per the multi-league audit.
    """
    reg = league_registry.get_sleeper_league_id()
    if reg:
        return reg
    return os.getenv("SLEEPER_LEAGUE_ID", "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league-id",
        default=_default_league_id(),
        help=(
            "Sleeper league id to start the chain walk from.  Defaults "
            "to the registry default → SLEEPER_LEAGUE_ID env var → empty."
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
