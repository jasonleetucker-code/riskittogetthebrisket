#!/usr/bin/env python3
"""Refresh per-player reception-band histograms from nflverse play-by-play.

Keeps the current season current, and backfills the prior seasons the
shape projection blends with.

Why this needs a cadence at all
───────────────────────────────
Historical seasons never change, so a one-off build would do for them.
The current season does change — every week adds catches, and a player
whose role has changed (a checkdown back running deep routes, a rookie
taking over a slot) only shows up in the data as those catches
accumulate. Without an in-season refresh the board would price every
player on last year's shape all year.

Exit codes follow the playerctx convention:

    0  every requested season is up to date
    1  a season that should exist could not be fetched
    2  nothing to do (the current season has not kicked off)

The distinction between 1 and 2 is the point. nflverse publishes a
season's pbp only once that season starts, so a 404 in July is expected
and must not page anyone; a 404 in November means the release path
moved. ``reception_depth.season_has_plausibly_started`` draws that line.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.nfl_data.reception_depth import (  # noqa: E402
    RECEPTION_DEPTH_SCHEMA_VERSION,
    depth_path,
    load_reception_depth,
    persist_reception_depth,
    season_has_plausibly_started,
)

_LOGGER = logging.getLogger("refresh_reception_depth")

#: How many seasons back to keep. The shape projection blends seasons
#: with a one-season half-life, so the third season back already counts
#: for a quarter and the fourth would be noise with a filename.
DEFAULT_LOOKBACK_SEASONS: int = 3


def _current_season(now: datetime | None = None) -> int:
    """The season whose games are being played, or the one just ended.

    January and February belong to the PREVIOUS season's playoffs, so a
    naive ``now.year`` would ask for a season that has not started and
    report "nothing to do" through the entire postseason.
    """
    now = now or datetime.now(timezone.utc)
    return now.year - 1 if now.month <= 2 else now.year


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons", type=int, nargs="*", help="explicit seasons; default is recent"
    )
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_SEASONS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild seasons already on disk (historical seasons are immutable, "
        "so by default only the current one is refetched)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    current = _current_season()
    if args.seasons:
        seasons = sorted({int(s) for s in args.seasons})
    else:
        seasons = sorted(range(current - args.lookback + 1, current + 1))

    wanted: list[int] = []
    for season in seasons:
        if not season_has_plausibly_started(season):
            _LOGGER.info("season %d has not kicked off — skipping", season)
            continue
        # Completed seasons are immutable once written; only the season
        # in progress is worth re-fetching on a schedule.
        # "Already on disk" is not enough: a file written under an older
        # schema carries a DIFFERENT measurement under the same field
        # names (v2 moved lost-yardage catches out of rec_0_4), and
        # ``load_reception_depth`` now refuses it.  Checking the version
        # here is what turns that refusal into a rebuild instead of a
        # season that silently has no overlay forever.
        if not args.force and season != current and depth_path(season).exists():
            existing = load_reception_depth(season)
            if existing is not None:
                _LOGGER.info("season %d already on disk and complete — skipping", season)
                continue
            _LOGGER.info(
                "season %d is on disk but not readable at schema %s — rebuilding",
                season,
                RECEPTION_DEPTH_SCHEMA_VERSION,
            )
        wanted.append(season)

    if not wanted:
        _LOGGER.info("nothing to refresh")
        return 2

    result = persist_reception_depth(wanted)
    built = {int(s) for s in (result.get("seasons") or [])}
    missing = [s for s in wanted if s not in built]

    _LOGGER.info(
        "reception_depth refreshed seasons=%s players=%s receptions=%s",
        sorted(built),
        result.get("players"),
        result.get("receptions"),
    )
    if missing:
        _LOGGER.error(
            "seasons %s should exist but produced nothing — check the pbp "
            "release path and the logs above",
            missing,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
