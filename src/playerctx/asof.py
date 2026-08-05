"""What was observable on a given date.

:func:`observable_as_of` turns a plain date into the
:class:`~src.playerctx.service.AsOf` window a replay should use — which
season's snap counts, and how many weeks of them had actually been
played by then.

**Why this needs a schedule at all.**  ``snap_counts_{season}.csv``
carries ``season``, ``game_type`` and ``week``, but no date: nothing in
the file says when week 8 was played.  The file is also the CURRENT
publication, so on 1 December it contains every week through the current
one.  Reading it unbounded for a replay of 9 November would hand the
replay three weeks of games that had not happened yet — a look-ahead
that produces a better-looking backtest for exactly the wrong reason.
The date → week map has to come from a schedule, and nflverse publishes
one with a ``gameday`` per game.

The fetch is injectable and the builder is pure, so the week arithmetic
is tested against fixtures rather than the network.

**This reproduces the offseason's frozen constant rather than hiding
it.**  Asked for a date in June, this returns the previous season's
final week — the same window it returns for every other June date,
because that is genuinely what was observable.  A caller replaying an
all-offseason panel therefore gets one identical window on every fold,
and can detect that and refuse instead of reporting the resampling of a
single observation as a multi-fold result.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.playerctx.service import AsOf

log = logging.getLogger(__name__)

# Regular season plus the four postseason rounds nflverse numbers 19-22.
MAX_WEEK = 22


def completed_week_on(rows: Iterable[Mapping[str, Any]], as_of: str) -> int | None:
    """Highest week whose games had ALL finished before ``as_of``.

    ``as_of`` is an ISO date (``"2025-11-09"``); comparison is on the
    date part alone and is strict, because a game played on ``as_of``
    has no published snap counts on ``as_of`` — nflverse posts them
    after the game.  Counting the same day's games would leak a few
    hours of the future into every Sunday replay.

    A week counts only when every one of its games is done, so a Monday
    replay does not see a Sunday-complete week as final while its MNF
    game is still to come.  Returns None when no week had completed —
    the honest answer for a preseason date, and the one that stops a
    caller replaying week 1 with an empty file and calling it a fold.
    """
    bound = str(as_of).strip()[:10]
    if not bound:
        return None

    last_gameday: dict[int, str] = {}
    for row in rows:
        try:
            week = int(float(row.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if week < 1 or week > MAX_WEEK:
            continue
        gameday = str(row.get("gameday") or "").strip()[:10]
        if not gameday:
            # A scheduled-but-undated game means the week's completion
            # is unknown; treat it as not complete rather than guessing.
            last_gameday[week] = "9999-99-99"
            continue
        if gameday > last_gameday.get(week, ""):
            last_gameday[week] = gameday

    if not last_gameday:
        return None

    best: int | None = None
    for week in sorted(last_gameday):
        if last_gameday[week] >= bound:
            break  # this week is not done, so nothing after it is either
        best = week
    return best


def observable_as_of(
    as_of: str,
    *,
    fetch_rows: Callable[[int], Sequence[Mapping[str, Any]]] | None = None,
    seasons: Sequence[int] | None = None,
) -> AsOf | None:
    """The playerctx window observable on ``as_of``, or None.

    Tries the calendar year of ``as_of`` first and falls back to the
    year before it, which is what makes January and February resolve to
    the previous season's playoffs rather than to an unplayed one.
    Returns None when neither season had a completed week — a date
    before any football, where the only honest replay is no replay.

    ``depth_as_of`` is set to the date itself: the depth-chart file
    carries its own timestamps, so it needs no schedule to bound.
    """
    bound = str(as_of).strip()[:10]
    if len(bound) != 10:
        return None

    if seasons is None:
        year = int(bound[:4])
        candidates = (year, year - 1)
    else:
        candidates = tuple(seasons)

    getter = fetch_rows or _default_fetch_rows
    for season in candidates:
        try:
            rows = getter(season)
        except Exception as exc:  # noqa: BLE001 — degrade soft, same as the fetchers
            log.warning("playerctx asof: schedule fetch failed for %s: %s", season, exc)
            continue
        week = completed_week_on(rows or [], bound)
        if week is not None:
            return AsOf(season=season, through_week=week, depth_as_of=bound)
    return None


def _default_fetch_rows(season: int) -> Sequence[Mapping[str, Any]]:
    """nflverse schedules, via the fetcher already wired for BDVM's ROS.

    Imported lazily and behind the injectable seam above so this module
    stays importable (and testable) without pulling BDVM in.  Reusing it
    beats a second copy of the same nflverse release URL and its
    per-season-file-404 fallback.
    """
    from src.bdvm.schedule import fetch_schedule_rows  # noqa: PLC0415

    return fetch_schedule_rows(season)
