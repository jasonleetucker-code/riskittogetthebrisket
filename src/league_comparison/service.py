"""Service orchestrator for the League Comparison endpoint.

Single public entry point: :func:`build_comparison`.  Everything else
in this module is a private helper.

Flow
----
1. Load ``config/league_comparison.json``.
2. Fetch ``scoring_settings`` for both leagues from Sleeper
   (:mod:`.sleeper_scoring`).
3. Compute a cache key from league IDs + scoring hashes + seasons +
   version.
4. If a fresh cached result exists and ``refresh=False``, return it
   directly (cache TTL: 7 days).
5. Otherwise: load weekly NFL stats per season
   (:mod:`.historical_stats`).  Track which seasons are
   available vs unavailable.
6. For each league × available season:
     * Compute per-player season totals under that league's scoring.
     * Sample top-N per position (sample sizes from config).
     * Compute :class:`PositionMetrics` per position.
     * Compute Top-96 flex metrics (RB ∪ WR ∪ TE).
7. Combine seasons equally across the available seasons.
8. Compute legacy + improved blended scores per position.
9. Compute positional shares per league.
10. Compute :class:`SimilarityResult`.
11. Build per-position recommendations.
12. Persist to disk cache and return.

Output shape
------------
Documented in :func:`build_comparison`'s docstring and pinned by
``tests/league_comparison/test_service.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.nfl_data import cache as _nfl_cache

from . import historical_stats as _stats
from . import idp as _idp
from . import metrics as _m
from . import season_scoring as _season_scoring
from . import sleeper_scoring as _sleeper
from src.nfl_data import pbp_weekly as _pbp_weekly

from .scoring_engine import PlayerSeasonScore, compute_player_season_scores

_LOGGER = logging.getLogger(__name__)

_CACHE_TTL_SEC = 7 * 24 * 3600
_CACHE_SUBDIR = "league_comparison_cache"


# ── Config loading ────────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return _repo_root() / "config" / "league_comparison.json"


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"missing config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Cache layer (disk) ────────────────────────────────────────────────


def _cache_dir() -> Path:
    return _repo_root() / "data" / _CACHE_SUBDIR


def _cache_key(
    *,
    my_id: str,
    baseline_id: str,
    my_hash: str,
    baseline_hash: str,
    seasons: Iterable[int],
    version: str,
) -> str:
    parts = [
        version,
        my_id,
        my_hash,
        baseline_id,
        baseline_hash,
        ",".join(str(s) for s in sorted(seasons)),
    ]
    return "league_compare:" + hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()


def _resolve_season_cards_or_none(
    league_id: str, seasons: list[int]
) -> _season_scoring.SeasonScoringChain | None:
    """Resolve the season -> card chain, or ``None`` if the walk failed.

    ``None`` and "resolved but with unresolved seasons" are different states
    and are reported differently upstream: the first means we never learned
    anything about this league's history, the second means we learned it and
    those particular seasons are genuinely absent.

    **A walk that resolved NOTHING counts as the first case.**  The chain
    walker degrades internally rather than raising — a dead network ends the
    walk and yields an empty map — so an empty result is indistinguishable
    from "this league has no history", and treating it as authoritative would
    mark every season unavailable and blank the whole comparison on a
    transient outage.  One or more resolved cards is what makes the chain
    trustworthy enough for its gaps to mean something.
    """
    try:
        chain = _season_scoring.resolve_season_cards(league_id, seasons)
    except Exception as exc:  # noqa: BLE001 — an optional refinement must not 500
        _LOGGER.warning(
            "league_compare.season_cards_unresolved league_id=%s err=%r", league_id, exc
        )
        return None
    if not chain.cards:
        _LOGGER.warning(
            "league_compare.season_chain_empty league_id=%s seasons=%s", league_id, seasons
        )
        return None
    return chain


# ── Per-position pipeline ─────────────────────────────────────────────


def _per_season_metrics_for_league(
    rows: list[dict[str, Any]],
    scoring: dict[str, float],
    sample_sizes: dict[str, int],
    season: int,
) -> tuple[dict[str, _m.PositionMetrics], _m.PositionMetrics, list[PlayerSeasonScore]]:
    """For one league × one season, compute per-position metrics + flex
    metrics.  Returns ``(per_pos, flex_metrics, top_player_pool)``.

    The third return is the union of all top-N samples (offense only)
    so callers can build a "top players used" breakdown for the
    year-by-year UI section without recomputing.
    """
    # Play-by-play supplies the six reception bands and the player
    # special-teams rules; both cards in a comparison are scored with it
    # or neither is (src/nfl_data/pbp_weekly.py).
    scores = compute_player_season_scores(
        rows, scoring, season=season, pbp_for_season=_pbp_weekly.SeasonPbpIndex().for_season
    )
    per_pos: dict[str, _m.PositionMetrics] = {}
    sample_union: list[PlayerSeasonScore] = []
    for pos in _m.OFFENSE_POSITIONS:
        n = int(sample_sizes.get(pos, 0))
        sample = _m.top_n_by_position(scores, pos, n)
        per_pos[pos] = _m.position_metrics(sample)
        sample_union.extend(sample)
    flex_n = int(sample_sizes.get("FLEX", 96))
    flex_sample = _m.flex_top_n(scores, n=flex_n)
    flex_metrics = _m.position_metrics(flex_sample)
    return per_pos, flex_metrics, sample_union


def _build_league_block(
    league_info: _sleeper.LeagueScoringInfo,
    seasons_map: dict[int, list[dict[str, Any]] | None],
    sample_sizes: dict[str, int],
    season_cards: _season_scoring.SeasonScoringChain | None = None,
) -> dict[str, Any]:
    """Compute per-season per-position metrics for one league across
    every available season.

    Returns a structured block:
    ``{"perSeason": {season: {"positions":{...}, "flex":{...},
        "topPlayers":[...]}},
       "combined": {"positions":{...}, "flex":{...}}}``

    **Each season is scored under ITS OWN card.**  This loop used to pass
    ``league_info.scoring_settings`` — today's card — into every season, so a
    league that changed its rules had every prior year rewritten under rules
    nobody played.  ``season_cards`` resolves the real card per season from
    the ``previous_league_id`` chain (see ``season_scoring``).

    A season whose card cannot be resolved is marked UNAVAILABLE rather than
    scored with today's card: substituting the current rules is the defect,
    and doing it silently is what let the defect survive.  Callers already
    handle an unavailable season — it is the same shape as "no stat rows".
    """
    per_season: dict[int, dict[str, Any]] = {}
    for season, rows in seasons_map.items():
        scoring_for_season: dict[str, float] | None
        if season_cards is None:
            # No chain resolved (offline, or a caller that predates this):
            # fall back to the league's current card, and SAY SO on the
            # season block rather than presenting it as the season's rules.
            scoring_for_season = league_info.scoring_settings
            card_basis = "current_card_unverified"
        else:
            scoring_for_season = season_cards.settings_for(season)
            card_basis = "season_card" if scoring_for_season is not None else "unresolved"
        if not rows or scoring_for_season is None:
            per_season[season] = {
                "positions": {
                    pos: _m.PositionMetrics(0, 0, 0, 0, 0, 0, 0, 0).to_dict()
                    for pos in _m.OFFENSE_POSITIONS
                },
                "flex": _m.PositionMetrics(0, 0, 0, 0, 0, 0, 0, 0).to_dict(),
                "topPlayers": [],
                "available": False,
                # "no stat rows" and "we do not know this season's rules" are
                # different reasons to show nothing, and a user deserves to
                # know which one they hit.
                "unavailableReason": ("no_stat_rows" if not rows else "scoring_card_unresolved"),
                "cardBasis": card_basis,
            }
            continue
        per_pos, flex_metrics, sample_union = _per_season_metrics_for_league(
            rows,
            scoring_for_season,
            sample_sizes,
            season,
        )
        # Top players sample for the UI year-by-year detail panel —
        # cap at 25 to keep payload light.  Sort by blended_score so
        # the displayed top matches what the ranking math actually used.
        top_players = sorted(
            sample_union,
            key=lambda s: -s.blended_score,
        )[:25]
        per_season[season] = {
            "positions": {pos: m.to_dict() for pos, m in per_pos.items()},
            "flex": flex_metrics.to_dict(),
            # Which card produced these numbers.  Stamped on EVERY season,
            # including the resolved ones: "scored under the season's own
            # rules" and "scored under whatever we had" must not read the
            # same, and only one of them supports an as-of claim.
            "cardBasis": card_basis,
            "topPlayers": [
                {
                    "playerId": s.player_id,
                    "name": s.player_name,
                    "position": s.position,
                    "rawPosition": s.raw_position,
                    "season": s.season,
                    "totalPoints": round(s.total_points, 2),
                    "gamesPlayed": s.games_played,
                    "pointsPerGame": round(s.points_per_game, 2),
                    "blendedScore": round(s.blended_score, 2),
                }
                for s in top_players
            ],
            "available": True,
        }

    # Build combined metrics by averaging available-season metrics
    # equally per position.
    combined_positions: dict[str, _m.PositionMetrics] = {}
    for pos in _m.OFFENSE_POSITIONS:
        per_year = {}
        for season, block in per_season.items():
            if not block.get("available"):
                continue
            d = block["positions"][pos]
            per_year[season] = _m.PositionMetrics(
                average=d["average"],
                median=d["median"],
                p25=d["p25"],
                p75=d["p75"],
                replacement_level=d["replacementLevel"],
                elite=d["elite"],
                replacement_adj=d["replacementAdj"],
                sample_size=d["sampleSize"],
            )
        combined_positions[pos] = _m.combine_metrics_equal_weight(per_year)
    flex_per_year = {}
    for season, block in per_season.items():
        if not block.get("available"):
            continue
        d = block["flex"]
        flex_per_year[season] = _m.PositionMetrics(
            average=d["average"],
            median=d["median"],
            p25=d["p25"],
            p75=d["p75"],
            replacement_level=d["replacementLevel"],
            elite=d["elite"],
            replacement_adj=d["replacementAdj"],
            sample_size=d["sampleSize"],
        )
    combined_flex = _m.combine_metrics_equal_weight(flex_per_year)

    return {
        "perSeason": {str(yr): block for yr, block in per_season.items()},
        "combined": {
            "positions": {pos: m.to_dict() for pos, m in combined_positions.items()},
            "flex": combined_flex.to_dict(),
        },
        "_combinedPositions": combined_positions,  # internal handle
        "_combinedFlex": combined_flex,  # internal handle
    }


def _build_position_comparisons(
    my_block: dict[str, Any],
    base_block: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
]:
    """Compute per-position comparisons and the four share dicts (legacy
    + improved × my + baseline)."""
    my_pos: dict[str, _m.PositionMetrics] = my_block["_combinedPositions"]
    base_pos: dict[str, _m.PositionMetrics] = base_block["_combinedPositions"]

    my_legacy = {pos: _m.legacy_blended(m) for pos, m in my_pos.items()}
    my_improved = {pos: _m.improved_blended(m) for pos, m in my_pos.items()}
    base_legacy = {pos: _m.legacy_blended(m) for pos, m in base_pos.items()}
    base_improved = {pos: _m.improved_blended(m) for pos, m in base_pos.items()}

    my_share_legacy = _m.position_shares(my_legacy)
    my_share_improved = _m.position_shares(my_improved)
    base_share_legacy = _m.position_shares(base_legacy)
    base_share_improved = _m.position_shares(base_improved)

    out: dict[str, dict[str, Any]] = {}
    for pos in _m.OFFENSE_POSITIONS:
        diff_pp_improved = my_share_improved[pos] - base_share_improved[pos]
        rec_text = _m.recommendation(
            pos,
            diff_pp_improved,
            my_share_improved[pos],
            base_share_improved[pos],
        )
        comp = _m.PositionComparison(
            position=pos,
            my_metrics=my_pos[pos],
            baseline_metrics=base_pos[pos],
            my_legacy_score=my_legacy[pos],
            baseline_legacy_score=base_legacy[pos],
            my_improved_score=my_improved[pos],
            baseline_improved_score=base_improved[pos],
        )
        out[pos] = comp.to_dict(
            my_share_legacy=my_share_legacy[pos],
            my_share_improved=my_share_improved[pos],
            base_share_legacy=base_share_legacy[pos],
            base_share_improved=base_share_improved[pos],
            recommendation_text=rec_text,
        )
    return out, my_share_legacy, my_share_improved, base_share_legacy, base_share_improved


def _flex_block(
    my_block: dict[str, Any],
    base_block: dict[str, Any],
) -> dict[str, Any]:
    my_flex: _m.PositionMetrics = my_block["_combinedFlex"]
    base_flex: _m.PositionMetrics = base_block["_combinedFlex"]
    my_legacy = _m.legacy_blended(my_flex)
    base_legacy = _m.legacy_blended(base_flex)
    my_improved = _m.improved_blended(my_flex)
    base_improved = _m.improved_blended(base_flex)
    diff = my_improved - base_improved
    rel = (diff / base_improved * 100.0) if base_improved > 0 else 0.0
    if abs(rel) <= 1:
        interp = "Top-96 flex value is essentially aligned with the baseline league."
    elif abs(rel) <= 5:
        interp = (
            f"Top-96 flex value is slightly "
            f"{'higher' if rel > 0 else 'lower'} than baseline ({rel:+.1f}%) — "
            f"minor adjustment may be worth considering."
        )
    else:
        interp = (
            f"Top-96 flex value is meaningfully "
            f"{'higher' if rel > 0 else 'lower'} than baseline ({rel:+.1f}%); "
            f"this can shift overall lineup-construction value relative to a normal league."
        )
    return {
        "my": {
            "metrics": my_flex.to_dict(),
            "legacyScore": round(my_legacy, 2),
            "improvedScore": round(my_improved, 2),
        },
        "baseline": {
            "metrics": base_flex.to_dict(),
            "legacyScore": round(base_legacy, 2),
            "improvedScore": round(base_improved, 2),
        },
        "diffLegacy": round(my_legacy - base_legacy, 2),
        "diffImproved": round(diff, 2),
        "relDiffPct": round(rel, 2),
        "interpretation": interp,
    }


def _summary_block(
    positions: dict[str, dict[str, Any]],
    flex: dict[str, Any],
    similarity: _m.SimilarityResult,
) -> dict[str, Any]:
    """Compute biggest-difference + closest-match for the summary cards."""
    diffs = [(pos, abs(comp["diffPpImproved"])) for pos, comp in positions.items()]
    diffs.sort(key=lambda x: -x[1])
    biggest = diffs[0][0] if diffs else None
    closest = diffs[-1][0] if diffs else None
    return {
        "score": similarity.score,
        "label": similarity.label,
        "distortionLabel": similarity.distortion_label,
        "totalShareDevPp": similarity.total_share_dev_pp,
        "flexDevPct": similarity.flex_dev_pct,
        "biggestDiffPosition": biggest,
        "closestMatchPosition": closest,
        "qbStatus": positions.get("QB", {}).get("status"),
        "rbStatus": positions.get("RB", {}).get("status"),
        "wrStatus": positions.get("WR", {}).get("status"),
        "teStatus": positions.get("TE", {}).get("status"),
        "flexInterpretation": flex.get("interpretation"),
    }


# ── Top-level entry ───────────────────────────────────────────────────


def build_comparison(*, refresh: bool = False) -> dict[str, Any]:
    """Build the full comparison payload (or load it from cache).

    Returns a dict ready to be JSON-serialized as the response body for
    ``GET /api/league-comparison``.

    Network failures fetching scoring settings raise — the API layer
    catches and returns 503.  Missing seasons degrade gracefully.
    """
    config = _load_config()
    version = str(config.get("version") or "v1.0")
    seasons_requested: list[int] = sorted({int(s) for s in config.get("seasons") or []})
    sample_sizes: dict[str, int] = {
        k: int(v) for k, v in (config.get("sample_sizes") or {}).items()
    }

    # Fail fast on a malformed config rather than silently producing
    # zeroed metrics when a position key is missing or non-positive.
    _required_sample_keys = ("QB", "RB", "WR", "TE", "FLEX")
    _missing = [k for k in _required_sample_keys if k not in sample_sizes]
    if _missing:
        raise ValueError(f"config/league_comparison.json missing sample_sizes keys: {_missing}")
    _bad = [k for k in _required_sample_keys if sample_sizes[k] <= 0]
    if _bad:
        raise ValueError(
            f"config/league_comparison.json sample_sizes must be positive, "
            f"got non-positive values for: {_bad}"
        )

    my_cfg = config["my_league"]
    base_cfg = config["baseline_league"]

    my_info = _sleeper.fetch_league_scoring(my_cfg["id"], refresh=refresh)
    base_info = _sleeper.fetch_league_scoring(base_cfg["id"], refresh=refresh)

    cache_key = _cache_key(
        my_id=my_info.league_id,
        baseline_id=base_info.league_id,
        my_hash=my_info.scoring_hash,
        baseline_hash=base_info.scoring_hash,
        seasons=seasons_requested,
        version=version,
    )
    cache_dir = _cache_dir()
    if not refresh:
        cached = _nfl_cache.get(cache_key, ttl_seconds=_CACHE_TTL_SEC, cache_dir=cache_dir)
        if cached is not None:
            cached["meta"]["cacheHit"] = True
            return cached

    t_start = time.time()
    seasons_map = _stats.load_all_seasons(seasons_requested)
    avail = _stats.summarize_availability(seasons_map)

    warnings: list[str] = []
    if avail["unavailable"]:
        missing = ", ".join(str(s) for s in avail["unavailable"])
        warnings.append(
            f"Seasons unavailable from upstream NFL stats source: {missing}. "
            f"Combined results use only the available seasons, equally weighted."
        )
    if len(avail["available"]) == 1:
        warnings.append(
            "Only one season of data is available — comparison is based on a "
            "limited sample and may be less reliable."
        )
    elif len(avail["available"]) == 0:
        warnings.append(
            "No NFL stats are available for any requested season.  "
            "Comparison cannot be computed."
        )

    # Pre-flag any scoring rules the engine does not score — surfaces in
    # the methodology / warnings UI.
    #
    # This used to compare against a HAND-MAINTAINED ``handled`` set, and
    # a hand-maintained mirror of behaviour drifts from it.  That set was
    # wrong in both directions: it omitted ``idp_tkl_solo`` /
    # ``idp_tkl_ast`` (the highest-volume IDP stats, which the engine
    # does score) and so warned about them falsely, while listing keys
    # under names the engine reaches only conditionally.  A warning
    # surface that mislabels its own subject is worse than none — it is
    # what let three separate silent-zero scoring bugs survive.
    #
    # ``scoring_coverage`` answers the question by PROBING the engine
    # instead, and separates two cases the old lump conflated:
    #   * NOT_APPLICABLE — DST / kicker / special-teams rules, correctly
    #     ignored because none of those is a tradeable asset here.
    #     Warning about them was pure noise, and noise gets suppressed.
    #   * GAP / UNSCORABLE — rules for players we DO value, which really
    #     do understate their realized points.
    from src.nfl_data.scoring_coverage import (  # noqa: PLC0415
        Coverage,
        audit_scoring_settings,
        describe_gaps,
    )

    for label, info in (("your league", my_info), ("the baseline league", base_info)):
        audit = audit_scoring_settings(info.scoring_settings)
        gaps = audit[Coverage.GAP]
        if gaps:
            warnings.append(
                f"Scoring rules in {label} that the engine can score but does not "
                f"({', '.join(sorted(gaps))}) — realized points are understated. "
                "This is a defect; please report it."
            )
        detail = describe_gaps(info.scoring_settings)
        unscorable = audit[Coverage.UNSCORABLE]
        if unscorable:
            warnings.append(
                f"Scoring rules in {label} that available data cannot reconstruct "
                f"({', '.join(sorted(unscorable))}) — realized points for affected "
                "players are understated. "
                + " ".join(d for d in detail if d.startswith(tuple(unscorable)))
            )

    # Resolve each league's ACTUAL card per season from its
    # ``previous_league_id`` chain, so a season is scored under the rules it
    # was played under rather than under today's (#802 as-of correctness).
    # Degrades rather than fails: a chain that cannot be walked leaves
    # ``season_cards`` None and every season is stamped
    # ``cardBasis: current_card_unverified``, which is an honest label on a
    # weaker number — not a silent claim that these are the season's rules.
    requested_seasons = sorted(seasons_map)
    my_cards = _resolve_season_cards_or_none(my_info.league_id, requested_seasons)
    base_cards = _resolve_season_cards_or_none(base_info.league_id, requested_seasons)
    for label, chain in (("your league", my_cards), ("the baseline league", base_cards)):
        if chain is None:
            warnings.append(
                f"Could not resolve historical scoring settings for {label}; "
                "seasons are scored under its CURRENT card, which may differ "
                "from the rules those seasons were played under."
            )
        elif chain.unresolved:
            warnings.append(
                f"No scoring card found for {label} in "
                f"{', '.join(str(s) for s in sorted(chain.unresolved))} — "
                "those seasons are excluded rather than scored under today's rules."
            )

    my_block = _build_league_block(my_info, seasons_map, sample_sizes, my_cards)
    base_block = _build_league_block(base_info, seasons_map, sample_sizes, base_cards)

    positions, my_sl, my_si, base_sl, base_si = _build_position_comparisons(
        my_block,
        base_block,
    )
    flex = _flex_block(my_block, base_block)

    similarity = _m.similarity_score(
        my_shares=my_si,
        baseline_shares=base_si,
        my_flex=flex["my"]["improvedScore"],
        baseline_flex=flex["baseline"]["improvedScore"],
    )

    summary = _summary_block(positions, flex, similarity)
    idp_block = _idp.compute_idp_block()

    by_season: dict[str, Any] = {}
    for season in avail["available"]:
        by_season[str(season)] = {
            "my": {
                "positions": my_block["perSeason"][str(season)]["positions"],
                "flex": my_block["perSeason"][str(season)]["flex"],
                "topPlayers": my_block["perSeason"][str(season)]["topPlayers"],
            },
            "baseline": {
                "positions": base_block["perSeason"][str(season)]["positions"],
                "flex": base_block["perSeason"][str(season)]["flex"],
                "topPlayers": base_block["perSeason"][str(season)]["topPlayers"],
            },
        }

    payload: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "myLeague": {
                "id": my_info.league_id,
                "label": my_cfg.get("label"),
                "name": my_info.name,
                "scoringHash": my_info.scoring_hash,
            },
            "baselineLeague": {
                "id": base_info.league_id,
                "label": base_cfg.get("label"),
                "name": base_info.name,
                "scoringHash": base_info.scoring_hash,
            },
            "seasonsRequested": seasons_requested,
            "seasonsAvailable": avail["available"],
            "seasonsUnavailable": avail["unavailable"],
            "seasonsSources": avail.get("sources") or {},
            "sampleSizes": sample_sizes,
            "computeMs": int((time.time() - t_start) * 1000),
            "cacheHit": False,
        },
        "summary": summary,
        "similarity": {
            "score": similarity.score,
            "label": similarity.label,
            "distortionLabel": similarity.distortion_label,
            "totalShareDevPp": similarity.total_share_dev_pp,
            "flexDevPct": similarity.flex_dev_pct,
        },
        "positions": positions,
        "flex": flex,
        "bySeason": by_season,
        "idp": idp_block,
        "warnings": warnings,
    }

    # Persist to disk cache (only if we successfully got at least one
    # season — don't poison the cache with an all-empty result).
    if avail["available"]:
        try:
            _nfl_cache.put(cache_key, payload, cache_dir=cache_dir)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("league_compare.cache_put_failed err=%r", exc)

    _LOGGER.info(
        "league_compare.built my=%s baseline=%s seasons=%s ms=%d",
        my_info.league_id,
        base_info.league_id,
        avail["available"],
        payload["meta"]["computeMs"],
    )
    return payload
