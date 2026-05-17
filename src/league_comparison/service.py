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
from . import sleeper_scoring as _sleeper
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
    scores = compute_player_season_scores(rows, scoring, season=season)
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
) -> dict[str, Any]:
    """Compute per-season per-position metrics for one league across
    every available season.

    Returns a structured block:
    ``{"perSeason": {season: {"positions":{...}, "flex":{...},
        "topPlayers":[...]}},
       "combined": {"positions":{...}, "flex":{...}}}``
    """
    per_season: dict[int, dict[str, Any]] = {}
    for season, rows in seasons_map.items():
        if not rows:
            per_season[season] = {
                "positions": {
                    pos: _m.PositionMetrics(0, 0, 0, 0, 0, 0, 0, 0).to_dict()
                    for pos in _m.OFFENSE_POSITIONS
                },
                "flex": _m.PositionMetrics(0, 0, 0, 0, 0, 0, 0, 0).to_dict(),
                "topPlayers": [],
                "available": False,
            }
            continue
        per_pos, flex_metrics, sample_union = _per_season_metrics_for_league(
            rows,
            league_info.scoring_settings,
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

    # Pre-flag any scoring keys present in either league but not handled
    # by the scoring engine — surfaces in the methodology / warnings UI.
    from src.nfl_data.realized_points import _SIMPLE_KEYS, _IDP_KEYS  # noqa: PLC0415

    handled = (
        set(_SIMPLE_KEYS.keys())
        | set(_IDP_KEYS.keys())
        | {
            "bonus_rec_te",
            "bonus_pass_yd_300",
            "bonus_pass_yd_400",
            "bonus_rush_yd_100",
            "bonus_rush_yd_200",
            "bonus_rec_yd_100",
            "bonus_rec_yd_200",
            "pass_2pt",
            "rush_2pt",
            "rec_2pt",
            "idp_tkl_5p",
            "idp_tkl_10p",
        }
    )
    unsupported_my = sorted(set(my_info.scoring_settings.keys()) - handled)
    unsupported_base = sorted(set(base_info.scoring_settings.keys()) - handled)
    if unsupported_my or unsupported_base:
        keys = sorted(set(unsupported_my) | set(unsupported_base))
        # Only warn about keys with non-zero values — many leagues
        # have dozens of zeroed keys for unused categories.
        nonzero = [
            k
            for k in keys
            if my_info.scoring_settings.get(k, 0) or base_info.scoring_settings.get(k, 0)
        ]
        if nonzero:
            warnings.append(
                "Some scoring categories are present but not modeled by the engine "
                f"(zeroed in calculations): {', '.join(nonzero)}."
            )

    my_block = _build_league_block(my_info, seasons_map, sample_sizes)
    base_block = _build_league_block(base_info, seasons_map, sample_sizes)

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
