"""Current-season realized weekly points — the in-season evidence feed.

Turns nflverse's in-progress ``stats_player_week_<season>.csv`` into
per-player weekly fantasy-point samples under THIS league's exact
scoring, via the same production loop the reconstructed baseline uses
(``normalize_weekly_row`` + ``compute_weekly_points`` — ADR-005: one
scoring engine, never two).

Which season?  The CALENDAR one, never ``currentDraftYear``.  The
contract's draft year is the *upcoming rookie draft* and rolls to
year+1 mid-summer — during the entire Sept–Jan regular season it
points one season ahead, whose weekly file doesn't exist yet.  Keying
the fetch on it would make the posterior structurally unreachable in
production.  ``current_nfl_season`` derives the season being played
from today's date instead, and returns ``None`` outside the Sept–Jan
window so offseason boards stay forward-looking (no completed-season
actuals blended into next year's projections).

Preseason honesty: before the season starts the file simply doesn't
exist upstream (the fetch returns nothing) and this module returns
``(None, {})`` — callers degrade to the preseason projection with an
explicit meta stamp, never a fabricated update.  An empty result is
"no evidence yet", NOT "zero production".
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

from src.bdvm.baseline import normalize_weekly_row
from src.bdvm.context import TRUE_POSITION_MAP
from src.nfl_data.realized_points import compute_weekly_points


def current_nfl_season(today: date | None = None) -> int | None:
    """NFL season whose REG weeks are being played right now, else None.

    Sept–Dec → this year; Jan → last year (week 18 spills into early
    January); Feb–Aug → None.  The None window is deliberate: after the
    season completes, blending a finished season's actuals into the
    NEXT season's projection set would be §8.4 applied across a season
    boundary — dynasty boards go back to forward-looking preseason
    semantics instead.
    """
    d = today or datetime.now(timezone.utc).date()
    if d.month >= 9:
        return d.year
    if d.month == 1:
        return d.year - 1
    return None


def nfl_projection_season(today: date | None = None) -> int:
    """The NFL season a projection snapshot / valuation describes.

    Jan → last year (the season still being played); every other month →
    the calendar year (Feb–Aug the season about to be played, Sept–Dec
    the one in progress).  So this AGREES with ``current_nfl_season`` by
    construction wherever that returns a season, and simply keeps
    answering outside the in-season window instead of returning None.

    That agreement is the point.  The §8.4 posterior blends realized
    weekly points into a projection, so the projection season and the
    actuals season have to be the same season; keying the projection on
    the contract's ``currentDraftYear`` — the upcoming ROOKIE-DRAFT year,
    which rolls to calendar+1 in May — would blend one season's results
    into another season's prior for the whole Sept–Jan window.  The two
    concepts are separate and are stamped separately (``meta.season``
    vs. ``meta.rookieDraftYear``).
    """
    d = today or datetime.now(timezone.utc).date()
    return d.year - 1 if d.month == 1 else d.year


def weekly_points_from_rows(
    weekly_rows: list[Mapping[str, Any]],
    scoring_settings: Mapping[str, Any],
    *,
    season: int,
    name_normalizer: Callable[[str], str],
) -> tuple[int | None, dict[str, list[tuple[int, float]]]]:
    """(current_week, player_key → [(week, points), ...]) from raw rows.

    Regular-season rows of ``season`` only.  ``current_week`` is the
    next unplayed week (max observed + 1 — deliberately UNCAPPED: after
    the week-18 slate it becomes 19 so ROS correctly sums zero
    remaining weeks instead of double-counting the banked final week);
    ``None`` when no rows exist — the preseason no-op signal.

    Distinct players colliding on a normalized name (real precedent:
    Byron Murphy / Byron Murphy II, both active) are DROPPED, mirroring
    the projection side's same-side collision policy — a per-week max
    over two different players is a chimera biased high by
    construction, and moving a player's µ on production that isn't his
    is worse than leaving him on the preseason prior.
    """
    samples: dict[str, dict[int, float]] = {}
    ids_by_key: dict[str, set[str]] = {}
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
        pid = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        if pid:
            ids_by_key.setdefault(key, set()).add(pid)
        # The same player can appear once per week; if a source ever
        # duplicates that row, keep the larger line rather than
        # double-counting.  (Cross-PLAYER merges are handled by the
        # collision drop below, not by this max.)
        bucket = samples.setdefault(key, {})
        bucket[week] = max(bucket.get(week, float("-inf")), float(rp.fantasy_points))
        max_week = max(max_week, week)
    if max_week <= 0:
        return None, {}
    for key, ids in ids_by_key.items():
        if len(ids) > 1:
            samples.pop(key, None)
    current_week = max_week + 1
    return current_week, {key: sorted(by_week.items()) for key, by_week in samples.items()}


def fetch_current_season_actuals(
    scoring_settings: Mapping[str, Any],
    *,
    name_normalizer: Callable[[str], str],
    season: int | None = None,
    today: date | None = None,
) -> tuple[int | None, dict[str, list[tuple[int, float]]]]:
    """Fetch + score the in-progress season's weekly rows.

    ``season`` defaults to ``current_nfl_season(today)``; outside the
    Sept–Jan window that is None and the result is the preseason
    signal without any fetch.  Fetches ``[season]`` ALONE so the
    current season gets its own 24h-TTL disk-cache entry (the ingest
    cache keys on the whole year list — bundling years would refetch
    history weekly).

    Fetch/network errors RAISE so the caller can decide not to
    memoize them — a transient blip must not pin the whole board to
    preseason values for the rest of the day.
    """
    if season is None:
        season = current_nfl_season(today)
    if season is None:
        return None, {}
    from src.nfl_data import ingest  # noqa: PLC0415

    rows = ingest.fetch_weekly_stats([int(season)]) or []
    return weekly_points_from_rows(
        rows, scoring_settings, season=season, name_normalizer=name_normalizer
    )
