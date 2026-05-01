"""Load historical NFL weekly stat rows for the seasons we want to
compare.

Wraps :func:`src.nfl_data.ingest.fetch_weekly_stats` season-by-season
so we get clean per-season availability information — if 2025 hasn't
been published yet by nflverse, we want to gracefully degrade to the
three available seasons rather than corrupting the comparison.
"""
from __future__ import annotations

import logging
from typing import Any

from src.nfl_data import ingest as _ingest

_LOGGER = logging.getLogger(__name__)


def load_season_rows(season: int) -> list[dict[str, Any]] | None:
    """Return weekly stat rows for ``season``, or ``None`` if unavailable.

    A season is considered unavailable when the upstream fetcher returns
    an empty list — this happens when nflverse hasn't published the
    season yet, or when the feature flag is off.  We return None (not
    an empty list) so callers can distinguish "no data" from "zero
    players scored anything", which matters for the seasons-included
    metadata block.
    """
    try:
        rows = _ingest.fetch_weekly_stats([int(season)])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("league_compare.season_fetch_failed season=%s err=%r", season, exc)
        return None
    if not rows:
        _LOGGER.info("league_compare.season_unavailable season=%s", season)
        return None
    return rows


def load_all_seasons(seasons: list[int]) -> dict[int, list[dict[str, Any]] | None]:
    """Fan out to load every requested season; preserve order.

    Returns a dict ``{season: rows | None}`` so the orchestrator can
    report which seasons were included and which were unavailable.
    """
    out: dict[int, list[dict[str, Any]] | None] = {}
    for season in sorted({int(s) for s in seasons}):
        out[season] = load_season_rows(season)
    return out


def summarize_availability(seasons_map: dict[int, Any]) -> dict[str, list[int]]:
    """Split a seasons_map into available/unavailable lists for the
    response metadata block."""
    available = sorted(s for s, rows in seasons_map.items() if rows)
    unavailable = sorted(s for s, rows in seasons_map.items() if not rows)
    return {"available": available, "unavailable": unavailable}
