"""Load historical NFL weekly stat rows for the seasons we want to
compare.

Primary source is :func:`src.nfl_data.ingest.fetch_weekly_stats`,
which wraps nflverse.  When nflverse hasn't published a season yet
(typical for the most recent season), we fall back to Sleeper via
:mod:`.sleeper_stats`.  Both sources emit nflverse-shaped rows so the
downstream scoring engine doesn't care which fed it.

Both sources are filtered to **regular-season weeks 1-17 only**
before they leave this module — week 18 is the starter-rest week for
most playoff-bound teams and would distort the multi-year sample.
"""

from __future__ import annotations

import logging
from typing import Any

from src.nfl_data import ingest as _ingest

from . import sleeper_stats as _sleeper_stats

_LOGGER = logging.getLogger(__name__)

# Inclusive upper bound on regular-season week.  The 2021+ NFL season
# is 18 weeks, but we drop week 18 to align with pre-2021 17-game
# seasons and to skip the starter-rest distortion at the top of the
# rankings.  nflverse postseason rows (week >= 19) are also excluded
# by this filter as a side benefit.
_MAX_REGULAR_WEEK = 17

# Which source produced each season's rows in the most recent call.
# Surfaces through :func:`summarize_availability` so the API meta
# block can tell the UI which seasons came from where.
_LAST_SOURCE: dict[int, str] = {}


def _set_source(season: int, source: str) -> None:
    _LAST_SOURCE[int(season)] = source


def get_source_for(season: int) -> str | None:
    return _LAST_SOURCE.get(int(season))


def _filter_to_regular_season(
    rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Drop rows past week 17 (and any malformed-week row).

    Applied to BOTH nflverse and Sleeper output so the comparison
    samples a consistent week range regardless of source.  Postseason
    rows (week >= 19 in nflverse) and week 18 starter-rest games drop
    cleanly; rows with a missing/non-numeric week field also drop.
    """
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            week = int(row.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= week <= _MAX_REGULAR_WEEK:
            out.append(row)
    return out


def load_season_rows(season: int) -> list[dict[str, Any]] | None:
    """Return weekly stat rows for ``season``, or ``None`` if unavailable.

    Resolution order:

    1. nflverse via :func:`fetch_weekly_stats` — canonical, used for
       any season the project already has.
    2. Sleeper via :func:`fetch_sleeper_weekly_stats` — fallback used
       when nflverse returns empty (typical for the most-recent season
       before nflverse finalises its dataset).

    A season is considered unavailable when both sources return empty.
    Returns ``None`` (not ``[]``) so the orchestrator can distinguish
    "no data" from "zero players scored" in its availability summary.
    """
    season = int(season)
    # Primary: nflverse.
    try:
        rows = _ingest.fetch_weekly_stats([season])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "league_compare.nflverse_fetch_failed season=%s err=%r",
            season,
            exc,
        )
        rows = []
    rows = _filter_to_regular_season(rows)
    if rows:
        _set_source(season, "nflverse")
        return rows

    # Fallback: Sleeper.
    _LOGGER.info(
        "league_compare.season_nflverse_empty season=%d falling_back_to=sleeper",
        season,
    )
    try:
        sleeper_rows = _sleeper_stats.fetch_sleeper_weekly_stats(season)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "league_compare.sleeper_fetch_failed season=%s err=%r",
            season,
            exc,
        )
        sleeper_rows = []
    sleeper_rows = _filter_to_regular_season(sleeper_rows)
    if sleeper_rows:
        _set_source(season, "sleeper")
        return sleeper_rows

    _LOGGER.info("league_compare.season_unavailable_from_all_sources season=%d", season)
    _LAST_SOURCE.pop(season, None)
    return None


def load_all_seasons(seasons: list[int]) -> dict[int, list[dict[str, Any]] | None]:
    """Fan out to load every requested season; preserve order.

    Returns a dict ``{season: rows | None}`` so the orchestrator can
    report which seasons were included and which were unavailable.
    """
    out: dict[int, list[dict[str, Any]] | None] = {}
    for season in sorted({int(s) for s in seasons}):
        out[season] = load_season_rows(season)
    return out


def summarize_availability(seasons_map: dict[int, Any]) -> dict[str, Any]:
    """Split a seasons_map into available/unavailable lists for the
    response metadata block, plus a per-season source map (only the
    sources that actually produced data this run).
    """
    available = sorted(s for s, rows in seasons_map.items() if rows)
    unavailable = sorted(s for s, rows in seasons_map.items() if not rows)
    sources = {s: _LAST_SOURCE.get(s) for s in available if _LAST_SOURCE.get(s)}
    return {"available": available, "unavailable": unavailable, "sources": sources}
