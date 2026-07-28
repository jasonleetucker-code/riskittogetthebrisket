"""Current-season realized weekly points — the in-season evidence feed.

Turns nflverse's in-progress ``stats_player_week_<season>.csv`` into
per-player weekly fantasy-point samples under THIS league's exact
scoring, via the same production loop the reconstructed baseline uses
(``normalize_weekly_row`` + ``compute_weekly_points`` — ADR-005: one
scoring engine, never two).

Preseason honesty: before the season starts the file simply doesn't
exist upstream (the fetch returns nothing) and this module returns
``(None, {})`` — callers degrade to the preseason projection with an
explicit meta stamp, never a fabricated update.  An empty result is
"no evidence yet", NOT "zero production".
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.bdvm.baseline import normalize_weekly_row
from src.bdvm.context import TRUE_POSITION_MAP
from src.nfl_data.realized_points import compute_weekly_points


def weekly_points_from_rows(
    weekly_rows: list[Mapping[str, Any]],
    scoring_settings: Mapping[str, Any],
    *,
    season: int,
    name_normalizer: Callable[[str], str],
) -> tuple[int | None, dict[str, list[tuple[int, float]]]]:
    """(current_week, player_key → [(week, points), ...]) from raw rows.

    Regular-season rows of ``season`` only.  ``current_week`` is the
    next unplayed week (max observed + 1, capped at 18); ``None`` when
    no rows exist — the preseason no-op signal.
    """
    samples: dict[str, dict[int, float]] = {}
    max_week = 0
    for raw in weekly_rows or []:
        try:
            if int(raw.get("season") or 0) != int(season):
                continue
        except (TypeError, ValueError):
            continue
        if str(raw.get("season_type") or "REG").upper() != "REG":
            continue
        name = str(raw.get("player_display_name") or raw.get("player_name") or "").strip()
        if not name:
            continue
        listing = str(raw.get("position") or "").upper()
        position = TRUE_POSITION_MAP.get(listing, listing)
        row = normalize_weekly_row(raw)
        rp = compute_weekly_points(row, dict(scoring_settings), position=position)
        if rp is None:
            continue
        try:
            week = int(raw.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if week <= 0:
            continue
        key = name_normalizer(name)
        # A player appears once per week; if a source ever duplicates,
        # keep the larger line rather than double-counting.
        bucket = samples.setdefault(key, {})
        bucket[week] = max(bucket.get(week, float("-inf")), float(rp.fantasy_points))
        max_week = max(max_week, week)
    if max_week <= 0:
        return None, {}
    current_week = min(18, max_week + 1)
    return current_week, {key: sorted(by_week.items()) for key, by_week in samples.items()}


def fetch_current_season_actuals(
    season: int,
    scoring_settings: Mapping[str, Any],
    *,
    name_normalizer: Callable[[str], str],
) -> tuple[int | None, dict[str, list[tuple[int, float]]]]:
    """Fetch + score this season's weekly rows.

    Fetches ``[season]`` ALONE so the current season gets its own
    24h-TTL disk-cache entry (the ingest cache keys on the whole year
    list — bundling years would refetch history weekly).  Any fetch
    problem degrades to ``(None, {})``.
    """
    try:
        from src.nfl_data import ingest  # noqa: PLC0415

        rows = ingest.fetch_weekly_stats([int(season)]) or []
    except Exception:  # noqa: BLE001
        return None, {}
    return weekly_points_from_rows(
        rows, scoring_settings, season=season, name_normalizer=name_normalizer
    )
