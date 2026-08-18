"""Reconstructed-baseline projections from realized scoring history.

Implements the BDVM §8.3 documented proxy as a runnable pipeline:
nflverse weekly stats (offense + IDP in one dataset) → per-week fantasy
points under the league's EXACT scoring settings (via the production
``realized_points`` path) → per-season PPG history → shrunk
recency-weighted baseline (``projections.build_reconstructed_baseline``)
→ immutable projection snapshot.

Every record is flagged ``is_proxy``; this is explicitly a worse
projection than a real preseason consensus and downstream confidence
reflects that.  The moment real projection sources land as CSVs, they
blend beside (or replace) this baseline through the same consensus.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping

from src.bdvm.context import TRUE_POSITION_MAP
from src.bdvm.projections import ProjectionRecord, RealizedSeason, build_reconstructed_baseline
from src.nfl_data.pbp_weekly import attach_supplement
from src.nfl_data.realized_points import compute_weekly_points

_LOGGER = logging.getLogger(__name__)

# Raw nflverse-direct column → the vocabulary compute_weekly_points
# reads.  Only keys that differ are listed; identical names pass through.
# Defensive columns need NO aliases here: ``realized_points`` resolves
# them through candidate lists and ``_tackle_view`` (which rebuilds
# gamebook solo/assist/combined from the raw 2025-unified columns —
# never synthesize ``def_tackles`` yourself; a published value under
# that name is interpreted as the PRE-2025 gamebook SOLO total).
_RAW_ALIASES = {
    "interceptions": "passing_interceptions",
    "sacks": "sacks_suffered",
    "fumbles_lost": "fumbles_lost_total",
}

_MIN_PPG_FLOOR = 1.0  # ignore sub-1-PPG seasons when forming the mean pool


def normalize_weekly_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Map a raw nflverse weekly row onto the scoring vocabulary.

    Handles both the nflverse-direct raw columns and already-normalized
    rows (aliases only fill keys that are absent).
    """
    row = dict(raw)
    for canonical, source in _RAW_ALIASES.items():
        if canonical not in row and source in row:
            row[canonical] = row[source]
    return row


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def realized_ppg_history(
    weekly_rows: Iterable[Mapping[str, Any]],
    scoring_settings: Mapping[str, Any],
    *,
    name_normalizer,
    regular_season_only: bool = True,
    scoring_for_season: Callable[[int], Mapping[str, Any] | None] | None = None,
    pbp_for_season: Callable[[int], Any] | None = None,
) -> dict[str, tuple[str, list[RealizedSeason]]]:
    """player_key → (true position, [RealizedSeason...]) under league scoring.

    ``scoring_for_season`` resolves the card that season was actually played
    under — see ``src.league_comparison.season_scoring`` (#802 as-of
    correctness).  Without it this function applies ONE card to every season
    in ``weekly_rows``, which for a league that changed its rules rewrites
    each prior year under rules nobody played.  The reconstructed baseline
    spans several seasons, so that is not hypothetical here.

    When a resolver is supplied and returns ``None`` for a season, that
    season's rows are SKIPPED rather than scored under the fallback card: an
    unknown rule set is unknown, not "presumably the current one".  Callers
    that want the old single-card behaviour simply omit the resolver, which
    keeps it explicit at the call site instead of implicit in here.

    ``pbp_for_season`` resolves the play-by-play supplement for a season —
    see :class:`src.nfl_data.pbp_weekly.SeasonPbpIndex`.  Without it the ten
    rules only play-by-play can supply score at nothing, which on this
    league's card is roughly two thirds of every receiver's reception
    points; the per-week result reports them in ``unscored`` either way, so
    the shortfall is visible rather than silent.  A season the producer has
    not built is left alone rather than zeroed — unlike the card resolver,
    the season is NOT skipped, because a partial line is still a real lower
    bound while an unknown rule set makes the whole line meaningless.
    """
    totals: dict[tuple[str, int], float] = {}
    games: dict[tuple[str, int], int] = {}
    latest_pos: dict[str, tuple[int, str]] = {}

    for raw in weekly_rows:
        if regular_season_only and str(raw.get("season_type") or "REG").upper() != "REG":
            continue
        name = raw.get("player_display_name") or raw.get("player_name") or ""
        if not name:
            continue
        key = name_normalizer(str(name))
        season = int(_num(raw.get("season")))
        listing = str(raw.get("position") or "").upper()
        pos = TRUE_POSITION_MAP.get(listing, listing)
        if scoring_for_season is not None:
            card = scoring_for_season(season)
            if card is None:
                # This season's rules are unknown. Scoring it under another
                # season's card would manufacture a number, so the season is
                # dropped from the history instead.
                continue
        else:
            card = scoring_settings
        row = normalize_weekly_row(raw)
        if pbp_for_season is not None:
            row = attach_supplement(row, pbp_for_season(season))
        rp = compute_weekly_points(row, dict(card), position=pos)
        if rp is None:
            continue
        totals[(key, season)] = totals.get((key, season), 0.0) + rp.fantasy_points
        games[(key, season)] = games.get((key, season), 0) + 1
        prev = latest_pos.get(key)
        if prev is None or season >= prev[0]:
            latest_pos[key] = (season, pos)

    by_player: dict[str, list[RealizedSeason]] = {}
    for (key, season), pts in totals.items():
        g = games[(key, season)]
        if g <= 0:
            continue
        by_player.setdefault(key, []).append(
            RealizedSeason(season=season, ppg=pts / g, games=float(g))
        )
    return {
        key: (latest_pos[key][1], sorted(seasons, key=lambda s: s.season))
        for key, seasons in by_player.items()
        if key in latest_pos
    }


def positional_means(
    history: Mapping[str, tuple[str, list[RealizedSeason]]],
    *,
    min_games: float = 8.0,
) -> dict[str, float]:
    """Mean season-PPG per position among meaningful seasons.

    The shrink target for the baseline: player-seasons with at least
    ``min_games`` games and a non-trivial scoring rate.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for pos, seasons in history.values():
        for s in seasons:
            if s.games < min_games or s.ppg < _MIN_PPG_FLOOR:
                continue
            sums[pos] = sums.get(pos, 0.0) + s.ppg
            counts[pos] = counts.get(pos, 0) + 1
    return {pos: sums[pos] / counts[pos] for pos in sums if counts[pos] > 0}


def build_baseline_records(
    *,
    season: int,
    as_of: str,
    weekly_rows: Iterable[Mapping[str, Any]],
    scoring_settings: Mapping[str, Any],
    name_normalizer,
    scoring_for_season: Callable[[int], Mapping[str, Any] | None] | None = None,
    pbp_for_season: Callable[[int], Any] | None = None,
) -> tuple[list[ProjectionRecord], dict[str, Any]]:
    """weekly rows → proxy projection records + a build summary."""
    history = realized_ppg_history(
        weekly_rows,
        scoring_settings,
        name_normalizer=name_normalizer,
        scoring_for_season=scoring_for_season,
        pbp_for_season=pbp_for_season,
    )
    means = positional_means(history)
    records = build_reconstructed_baseline(
        history, season=season, as_of=as_of, positional_means=means
    )
    summary = {
        "playersWithHistory": len(history),
        "recordsBuilt": len(records),
        "positionalMeans": {k: round(v, 2) for k, v in sorted(means.items())},
        "seasonsSeen": sorted({s.season for _, seasons in history.values() for s in seasons}),
        "pbpSupplementJoined": pbp_for_season is not None,
        "seasonCardsResolved": scoring_for_season is not None,
    }
    return records, summary


# ---------------------------------------------------------------------------
# Rookie priors from draft slot (the §8.3 "rookie prior from draft slot")
# ---------------------------------------------------------------------------

_ROOKIE_BUCKETS = ("r1", "r2", "r3plus")
_ROOKIE_MIN_BUCKET_N = 5
_ROOKIE_PRIOR_GAMES = 15.0


def _draft_bucket(draft_overall: int | None) -> str | None:
    if draft_overall is None or draft_overall <= 0:
        return None
    rnd = (draft_overall - 1) // 32 + 1
    if rnd == 1:
        return "r1"
    if rnd == 2:
        return "r2"
    return "r3plus"


def build_rookie_prior_records(
    *,
    season: int,
    as_of: str,
    history: Mapping[str, tuple[str, list[RealizedSeason]]],
    context: Mapping[str, Any],
    source: str = "rookieDraftSlotPrior",
) -> tuple[list[ProjectionRecord], dict[str, Any]]:
    """Proxy µ(0) for incoming rookies from historical rookie-season PPG
    by (position, draft-round bucket).

    For every player in ``context`` whose ``rookie_season`` is a PAST
    season with realized history, their rookie-year PPG feeds the bucket
    means; every ``rookie_season == season`` player with known draft
    capital gets the bucket mean as a proxy projection.  Undrafted
    rookies get no prior — they stay honestly unpriced rather than
    receiving a fabricated role.
    """
    sums: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    pos_sums: dict[str, float] = {}
    pos_counts: dict[str, int] = {}

    for key, (pos, seasons) in history.items():
        ctx = context.get(key)
        if ctx is None or ctx.rookie_season is None:
            continue
        bucket = _draft_bucket(ctx.draft_overall)
        if bucket is None:
            continue
        rookie_rows = [s for s in seasons if s.season == ctx.rookie_season and s.games >= 4]
        if not rookie_rows:
            continue
        ppg = rookie_rows[0].ppg
        sums[(pos, bucket)] = sums.get((pos, bucket), 0.0) + ppg
        counts[(pos, bucket)] = counts.get((pos, bucket), 0) + 1
        pos_sums[pos] = pos_sums.get(pos, 0.0) + ppg
        pos_counts[pos] = pos_counts.get(pos, 0) + 1

    def _bucket_mean(pos: str, bucket: str) -> float | None:
        n = counts.get((pos, bucket), 0)
        if n >= _ROOKIE_MIN_BUCKET_N:
            return sums[(pos, bucket)] / n
        if pos_counts.get(pos, 0) >= _ROOKIE_MIN_BUCKET_N:
            return pos_sums[pos] / pos_counts[pos]
        return None

    records: list[ProjectionRecord] = []
    skipped_undrafted = 0
    for key, ctx in context.items():
        if ctx.rookie_season != season:
            continue
        bucket = _draft_bucket(ctx.draft_overall)
        if bucket is None:
            skipped_undrafted += 1
            continue
        pos = ctx.true_position
        if pos is None:
            continue
        mu = _bucket_mean(pos, bucket)
        if mu is None:
            continue
        records.append(
            ProjectionRecord(
                source=source,
                player_key=key,
                position=pos,
                season=season,
                as_of=as_of,
                games=_ROOKIE_PRIOR_GAMES,
                fpg=mu,
                scoring_native=True,
                is_proxy=True,
            )
        )
    summary = {
        "rookiePriorRecords": len(records),
        "rookieBucketSamples": {f"{p}:{b}": n for (p, b), n in sorted(counts.items())},
        "undraftedRookiesSkipped": skipped_undrafted,
    }
    return records, summary


def fetch_and_build_baseline(
    *,
    season: int,
    as_of: str,
    scoring_settings: Mapping[str, Any],
    seasons_back: int = 3,
    name_normalizer=None,
    include_rookie_priors: bool = True,
    scoring_for_season: Callable[[int], Mapping[str, Any] | None] | None = None,
    pbp_for_season: Callable[[int], Any] | None = None,
) -> tuple[list[ProjectionRecord], dict[str, Any]]:
    """Network variant: fetch the last ``seasons_back`` completed seasons.

    Rookie priors use the full context (id map) so incoming draftees get
    a draft-slot µ(0); veterans-with-history come from the realized
    baseline.  A player never gets both (rookies have no history).

    Both resolvers pass straight through to :func:`realized_ppg_history`;
    see it for what each one refuses to guess.
    """
    if name_normalizer is None:
        from src.utils.name_clean import normalize_player_name as name_normalizer  # noqa: PLC0415
    from src.nfl_data import ingest  # noqa: PLC0415

    years = [y for y in range(season - seasons_back, season)]
    weekly = ingest.fetch_weekly_stats(years)
    _LOGGER.info("bdvm baseline: fetched %d weekly rows for %s", len(weekly), years)
    records, summary = build_baseline_records(
        season=season,
        as_of=as_of,
        weekly_rows=weekly,
        scoring_settings=scoring_settings,
        name_normalizer=name_normalizer,
        scoring_for_season=scoring_for_season,
        pbp_for_season=pbp_for_season,
    )
    if include_rookie_priors:
        from src.bdvm.context import fetch_and_build_context  # noqa: PLC0415

        context = fetch_and_build_context(
            season, seasons_back=0, include_snaps=False, name_normalizer=name_normalizer
        )
        history = realized_ppg_history(
            weekly,
            scoring_settings,
            name_normalizer=name_normalizer,
            scoring_for_season=scoring_for_season,
            pbp_for_season=pbp_for_season,
        )
        rookie_records, rookie_summary = build_rookie_prior_records(
            season=season,
            as_of=as_of,
            history=history,
            context=context,
        )
        existing = {r.player_key for r in records}
        added = [r for r in rookie_records if r.player_key not in existing]
        records = records + added
        summary = {**summary, **rookie_summary, "rookiePriorsAdded": len(added)}
    return records, summary
