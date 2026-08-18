#!/usr/bin/env python3
"""Build the per-player-week play-by-play stat artifact.

Ten rules on ``dynasty_main``'s card have no column on the nflverse
WEEKLY feed and are deterministic from play-by-play: the six reception
depth bands, ``st_tkl_solo``, ``st_ff``, ``st_fum_rec`` and
``pass_int_td``. :mod:`src.nfl_data.pbp_weekly` derives them; this script
is how the artifact gets built.

Without it those rules score nothing — measured against the league host's
own week-14 2025 dump, 451.53 points in one week, about two thirds of it
the reception bands. The realized-points engine reports them in
``unscored`` rather than silently zeroing them, so the shortfall is
visible either way; running this is what closes it.

Output: ``data/nfl_data/actuals/pbp_weekly_<season>.jsonl``, one line per
season, replaced wholesale on re-run. Streaming, not buffered — a season
is ~98 MB over 372 columns, and peak memory is the histogram.

Exit codes: 0 built, 1 nothing built (no season produced plays), 2 the
run failed outright.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.nfl_data.pbp_weekly import (  # noqa: E402
    PBP_WEEKLY_SCHEMA_VERSION,
    persist_pbp_weekly,
)
from src.nfl_data.realized_points import PBP_SUPPLEMENT_KEYS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        required=True,
        help="seasons to build, e.g. --seasons 2021 2022 2023 2024 2025",
    )
    parser.add_argument(
        "--season-types",
        nargs="+",
        default=["REG"],
        help="REG (default) and/or POST. Regular season only is what realized "
        "scoring uses, matching the rest of the pipeline.",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    print(f"schema {PBP_WEEKLY_SCHEMA_VERSION}; keys: {', '.join(sorted(PBP_SUPPLEMENT_KEYS))}")
    try:
        result = persist_pbp_weekly(
            args.seasons,
            out_dir=args.out_dir,
            season_types=args.season_types,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: pbp weekly build failed: {exc}", file=sys.stderr)
        return 2

    built = result.get("seasons") or []
    for path in result.get("paths") or []:
        print(f"written: {path}")
    print(
        f"seasons built: {built or 'none'}; "
        f"player-seasons {result.get('players', 0)}; events {result.get('events', 0):g}"
    )
    missing = [s for s in args.seasons if s not in built]
    if missing:
        # Named rather than swallowed: a season that produced nothing is a
        # season whose ten rules stay unavailable, and the operator has to
        # know which one.
        print(f"NOT built: {missing}", file=sys.stderr)
    if not built:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
