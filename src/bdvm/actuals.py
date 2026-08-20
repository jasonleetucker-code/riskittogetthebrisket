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

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

from src.bdvm.baseline import normalize_weekly_row
from src.bdvm.context import TRUE_POSITION_MAP
from src.nfl_data.pbp_weekly import attach_supplement
from src.nfl_data.realized_points import compute_weekly_points

_LOGGER = logging.getLogger(__name__)


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
    pbp_stats: Any | None = None,
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

    ``pbp_stats`` is this season's
    :class:`src.nfl_data.pbp_weekly.PbpWeeklyStats`, supplying the ten
    rules the weekly feed does not publish.  ``None`` leaves them
    unavailable rather than zero — the per-week result says so in
    ``unscored`` — which matters most here, because the in-season blend
    moves a player's posterior toward whatever these weeks measured.
    """
    samples: dict[str, dict[int, float]] = {}
    ids_by_key: dict[str, set[str]] = {}
    unscored_rules: dict[str, float] = {}
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
        if pbp_stats is not None and str(raw.get("source") or "nflverse") == "nflverse":
            row = attach_supplement(row, pbp_stats)
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
        if rp.unscored:
            # A week whose play-by-play rules had no source is a LOWER
            # BOUND, and this feeds the in-season posterior blend — a
            # low-but-plausible week pulls a player's mean down exactly as
            # convincingly as a real one.
            #
            # It is KEPT rather than dropped: without the artifact every
            # week would qualify, and refusing all of them would silently
            # switch the whole in-season update off, which is a bigger
            # untruth than an understated week.  What must not happen is
            # that the understatement is invisible, hence the warning
            # below.
            for unscored_key, rate in rp.unscored:
                unscored_rules[unscored_key] = rate
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
    if unscored_rules:
        # Loud, because the number this returns feeds the in-season
        # posterior blend and is a LOWER BOUND whenever this fires.
        _LOGGER.warning(
            "bdvm actuals: season %s scored WITHOUT %s — at least one week "
            "had no play-by-play evidence for these rules (no artifact, or a "
            "week it marks unfinished), so weekly points are understated. "
            "Build or extend it with scripts/build_pbp_weekly.py --seasons %s.",
            season,
            ", ".join(sorted(unscored_rules)),
            season,
        )
    current_week = max_week + 1
    return current_week, {key: sorted(by_week.items()) for key, by_week in samples.items()}


def fetch_current_season_actuals(
    scoring_settings: Mapping[str, Any],
    *,
    name_normalizer: Callable[[str], str],
    season: int | None = None,
    today: date | None = None,
    cache_only: bool = False,
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

    ``cache_only=True`` is the REQUEST-PATH mode and never fetches; it
    scores whatever weekly rows the refresh owner has already
    materialised.  With nothing materialised this returns the ordinary
    ``(None, {})`` no-evidence signal — the SAME value the preseason
    window returns — so the posterior simply does not update.  It is not
    zero production, and this function's stricter rules are untouched by
    the mode: the calendar NFL season (never the rookie draft year), REG
    weeks only, and the caller's deliberate refusal to memoize failures.
    """
    if season is None:
        season = current_nfl_season(today)
    if season is None:
        return None, {}
    from src.nfl_data import ingest  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import default_pbp_stats  # noqa: PLC0415

    rows = ingest.fetch_weekly_stats([int(season)], cache_only=cache_only) or []
    return weekly_points_from_rows(
        rows,
        scoring_settings,
        season=season,
        name_normalizer=name_normalizer,
        # Joined by default: without it the six reception bands and the
        # player special-teams rules score nothing, and this is the path
        # that moves a player's posterior toward what the season measured.
        # An absent artifact resolves to None and is warned about, not
        # silently zeroed.
        pbp_stats=default_pbp_stats(int(season)),
    )
