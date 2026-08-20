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

Exit codes: 0 built, 1 a season that should exist produced no plays
(release path likely moved — the one worth investigating), 2 nothing to
do or the run was refused. 2 is the NORMAL state of the weekly timer once
every completed season is on disk, and is not a failure.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.nfl_data.pbp_weekly import (  # noqa: E402
    PBP_WEEKLY_SCHEMA_VERSION,
    load_pbp_weekly,
    persist_pbp_weekly,
)
from src.nfl_data.reception_depth import season_has_plausibly_started  # noqa: E402
from src.nfl_data.realized_points import PBP_SUPPLEMENT_KEYS  # noqa: E402


def _season_is_final(season: int, *, now: datetime | None = None) -> bool:
    """Has ``season`` finished, as far as the calendar can tell?

    Week 18 lands in the first days of January, so the February after a
    season is comfortably past its last snap. Coarse on purpose — the
    alternative is fetching a schedule to answer a question about whether
    to require a flag.
    """
    now = now or datetime.now(timezone.utc)
    return (now.year, now.month) >= (int(season) + 1, 2)


def _newest_final_season(*, now: datetime | None = None) -> int | None:
    """The most recent season whose slate has certainly finished."""
    now = now or datetime.now(timezone.utc)
    candidate = now.year
    while candidate > 1999:
        if _season_is_final(candidate, now=now):
            return candidate
        candidate -= 1
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        help="seasons to build, e.g. --seasons 2021 2022 2023 2024 2025",
    )
    parser.add_argument(
        "--completed-seasons-back",
        type=int,
        default=None,
        help="build the last N COMPLETED seasons instead of naming them. The "
        "scheduled build uses this: it can never select a season whose slate "
        "is still running, so it cannot record a not-yet-played game as a "
        "real zero. An in-season build stays an explicit operator action.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="leave a season alone if its artifact is already on disk at the "
        "current schema. Completed seasons do not change.",
    )
    parser.add_argument(
        "--season-types",
        nargs="+",
        default=["REG"],
        help="REG (default) and/or POST. Regular season only is what realized "
        "scoring uses, matching the rest of the pipeline.",
    )
    parser.add_argument(
        "--complete-through-week",
        type=int,
        default=None,
        help="last week whose slate has FINISHED. Weeks after it are recorded "
        "as partial and read back as unknown rather than as real zeroes. "
        "Required when building a season that is still in progress: a "
        "mid-week build otherwise fabricates a zero for every player whose "
        "game has not kicked off, and suppresses the flag that would say so.",
    )
    parser.add_argument(
        "--assume-complete",
        action="store_true",
        help="build an in-progress season asserting every streamed week is "
        "final. Use only when you know the slate is done.",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    if args.seasons and args.completed_seasons_back is not None:
        print("ERROR: pass --seasons or --completed-seasons-back, not both", file=sys.stderr)
        return 2
    if args.completed_seasons_back is not None:
        newest = _newest_final_season()
        if newest is None:
            print("ERROR: no completed season to build", file=sys.stderr)
            return 2
        args.seasons = list(range(newest - args.completed_seasons_back + 1, newest + 1))
        print(f"completed seasons: {args.seasons}")
    if not args.seasons:
        print("ERROR: --seasons or --completed-seasons-back is required", file=sys.stderr)
        return 2

    if args.skip_existing:
        keep = []
        for season in args.seasons:
            payload = load_pbp_weekly(season, out_dir=args.out_dir)
            if payload and payload.get("schemaVersion") == PBP_WEEKLY_SCHEMA_VERSION:
                print(f"season {season}: already on disk at current schema — skipping")
                continue
            keep.append(season)
        if not keep:
            # Nothing to do is not a failure: this is the normal state of a
            # weekly timer over immutable completed seasons.  Exit 2 so the
            # unit can report it distinctly from "built nothing because the
            # fetch broke".
            print("nothing to build — every requested season is current")
            return 2
        args.seasons = keep

    in_progress = [
        s for s in args.seasons if season_has_plausibly_started(s) and not _season_is_final(s)
    ]
    if in_progress and args.complete_through_week is None and not args.assume_complete:
        print(
            f"ERROR: {in_progress} is in progress. nflverse republishes the "
            "current season's play-by-play mid-week, so a build now would record "
            "every not-yet-played game as a real zero. Pass "
            "--complete-through-week N, or --assume-complete if the slate is done.",
            file=sys.stderr,
        )
        return 2

    print(f"schema {PBP_WEEKLY_SCHEMA_VERSION}; keys: {', '.join(sorted(PBP_SUPPLEMENT_KEYS))}")
    try:
        result = persist_pbp_weekly(
            args.seasons,
            out_dir=args.out_dir,
            season_types=args.season_types,
            complete_through_week=args.complete_through_week,
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
