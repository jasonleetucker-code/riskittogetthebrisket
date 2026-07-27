"""Persist nflverse player-week actuals to durable JSONL.

Writes ``data/nfl_data/actuals/player_week_{season}.jsonl`` from
``src.nfl_data.ingest.fetch_weekly_stats`` +
``fetch_weekly_defensive_stats``.  Idempotent: a week already on disk is
replaced by the fresh pull, never duplicated, and weeks absent from the
fetch are left alone.

Deliberately NOT the TTL cache under ``data/nfl_data_cache/`` — that one
evicts on a 24h timer, so nothing accumulates there.  See
``src/nfl_data/actuals_store.py``'s module docstring.

Run:
    python3 scripts/persist_nfl_actuals.py --seasons 2025
    python3 scripts/persist_nfl_actuals.py --seasons 2023 2024 2025
    python3 scripts/persist_nfl_actuals.py --coverage

Exit codes:
    0  wrote at least one week (or --coverage succeeded)
    1  fetch returned rows but none were persistable
    2  bad arguments, or the feature flag is off
    3  the fetch returned nothing at all (upstream problem)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import feature_flags  # noqa: E402
from src.nfl_data import actuals_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=None,
        help="Season years to fetch and persist, e.g. --seasons 2024 2025.",
    )
    parser.add_argument(
        "--dir",
        default=None,
        help=(
            "Override the output directory.  Defaults to "
            "data/nfl_data/actuals/ under the repo root."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Evict the 24h ingest TTL cache for these seasons first.  Without "
            "it a re-run inside the window is served the previous pull, so a "
            "box-score revision published hours after a game stays invisible."
        ),
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Print what is already on disk and exit without fetching.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log each provider rung and per-season write.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    actuals_dir = Path(args.dir) if args.dir else None

    if args.coverage:
        print(json.dumps(actuals_store.coverage(actuals_dir=actuals_dir), indent=2))
        return 0

    if not args.seasons:
        parser.error("--seasons is required unless --coverage is passed")

    if not feature_flags.is_enabled("nfl_data_ingest"):
        # Every fetch would silently return [] and this script would
        # report "no rows" as though nflverse were down.  Say which it
        # is — that distinction is the whole point of the exit codes.
        print(
            "[actuals] feature flag nfl_data_ingest is OFF; every fetch would "
            "return no rows.  Set RISKIT_FEATURE_NFL_DATA_INGEST=1 to run.",
            file=sys.stderr,
        )
        return 2

    print(f"[actuals] fetching seasons {args.seasons}")
    result = actuals_store.persist_weekly_actuals(
        args.seasons, actuals_dir=actuals_dir, refresh=args.refresh
    )
    print(json.dumps(result.to_dict(), indent=2))

    fetched = result.offensive_rows_fetched + result.defensive_rows_fetched
    if fetched == 0:
        print(
            "[actuals] the fetchers returned zero rows.  Check the nflverse "
            "release URLs in src/nfl_data/nflverse_direct.py — a rename 404s "
            "silently and looks exactly like a season with no data.",
            file=sys.stderr,
        )
        return 3
    if result.weeks_written == 0:
        print(
            f"[actuals] fetched {fetched} rows but persisted none — the column "
            "mapping in actuals_store may no longer match the release schema.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[actuals] wrote {result.weeks_written} week(s), "
        f"{result.player_weeks} player-weeks "
        f"({result.offense_records} offensive, {result.defense_records} defensive)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
