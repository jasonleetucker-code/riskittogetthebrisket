from __future__ import annotations

import math
from typing import Dict, Optional

from .types import PlayerScoringAdjustment


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def compute_sample_size_score(total_games: int, recency_games: int) -> float:
    total = clamp(float(total_games) / 34.0, 0.0, 1.0)
    recent = clamp(float(recency_games) / 12.0, 0.0, 1.0)
    return clamp((total * 0.7) + (recent * 0.3), 0.0, 1.0)


def compute_shrunk_ratio(
    raw_ratio: float,
    *,
    sample_size_score: float,
    role_stability_score: float,
    archetype_prior_ratio: float,
    projection_weight: float,
) -> float:
    # Empirical-Bayes style shrinkage toward archetype + neutral.
    ss = clamp(sample_size_score, 0.0, 1.0)
    rs = clamp(role_stability_score, 0.0, 1.0)
    pw = clamp(projection_weight, 0.0, 1.0)
    prior = clamp(archetype_prior_ratio, 0.75, 1.25)
    player_weight = clamp((ss * 0.55) + (rs * 0.25) + ((1.0 - pw) * 0.20), 0.05, 0.95)
    neutral_prior = 1.0
    blended_prior = (prior * 0.65) + (neutral_prior * 0.35)
    shrunk = (float(raw_ratio) * player_weight) + (blended_prior * (1.0 - player_weight))
    return clamp(shrunk, 0.75, 1.25)


def ratio_to_multiplier(
    shrunk_ratio: float,
    *,
    alpha: float = 0.60,
    lower_log_bound: float = -0.12,
    upper_log_bound: float = 0.12,
    multiplier_min: float = 0.90,
    multiplier_max: float = 1.12,
) -> float:
    # m_score = exp(alpha * clamp(log(r_shrunk), lo, hi))
    ratio = max(0.01, float(shrunk_ratio))
    z = math.log(ratio)
    z_bounded = clamp(z, lower_log_bound, upper_log_bound)
    m = math.exp(alpha * z_bounded)
    return clamp(m, multiplier_min, multiplier_max)


def build_player_scoring_adjustment(
    *,
    baseline_scoring_version: str,
    league_scoring_version: str,
    league_id: str,
    baseline_ppg: float,
    league_ppg: float,
    position_bucket: str,
    archetype: str,
    confidence: float,
    sample_size_score: float,
    projection_weight: float,
    data_quality_flag: str,
    scoring_tags: list[str],
    rule_contributions: Dict[str, float],
    archetype_prior_ratio: float = 1.0,
    value_anchor: float = 1000.0,
    source: str = "scoring_translation_hybrid",
) -> PlayerScoringAdjustment:
    p_base = max(0.0, float(baseline_ppg or 0.0))
    p_league = max(0.0, float(league_ppg or 0.0))
    raw_ratio = p_league / max(p_base, 1.0) if (p_base > 0.0 or p_league > 0.0) else 1.0
    raw_ratio = clamp(raw_ratio, 0.70, 1.40)
    shrunk_ratio = compute_shrunk_ratio(
        raw_ratio,
        sample_size_score=sample_size_score,
        role_stability_score=confidence,
        archetype_prior_ratio=archetype_prior_ratio,
        projection_weight=projection_weight,
    )
    mult = ratio_to_multiplier(shrunk_ratio)
    delta_points = p_league - p_base
    delta_value = float(value_anchor) * (mult - 1.0)
    return PlayerScoringAdjustment(
        baseline_scoring_version=str(baseline_scoring_version or ""),
        league_scoring_version=str(league_scoring_version or ""),
        league_id=str(league_id or ""),
        baseline_points_per_game=round(p_base, 6),
        league_points_per_game=round(p_league, 6),
        raw_scoring_ratio=round(raw_ratio, 6),
        shrunk_scoring_ratio=round(shrunk_ratio, 6),
        final_scoring_multiplier=round(mult, 6),
        final_scoring_delta_points=round(delta_points, 6),
        final_scoring_delta_value=round(delta_value, 6),
        position_bucket=str(position_bucket or ""),
        archetype=str(archetype or ""),
        confidence=round(clamp(confidence, 0.20, 1.00), 6),
        sample_size_score=round(clamp(sample_size_score, 0.0, 1.0), 6),
        projection_weight=round(clamp(projection_weight, 0.0, 1.0), 6),
        data_quality_flag=str(data_quality_flag or ""),
        scoring_tags=list(scoring_tags or []),
        source=str(source or "scoring_translation_hybrid"),
        rule_contributions={k: round(float(v), 6) for k, v in (rule_contributions or {}).items()},
    )


def choose_final_multiplier(
    *,
    scoring_adjustment: PlayerScoringAdjustment,
    production_share: float,
    hard_cap: float,
    explicit_fit_final: Optional[float] = None,
    explicit_fit_blend: float = 0.0,
) -> float:
    # Apply scoring fit only to production-sensitive slice to avoid overpowering market value.
    prod = clamp(float(production_share), 0.0, 1.0)
    score_mult = float(scoring_adjustment.final_scoring_multiplier)
    output = 1.0 + ((score_mult - 1.0) * prod)
    if isinstance(explicit_fit_final, (int, float)) and explicit_fit_final > 0 and explicit_fit_blend > 0:
        w = clamp(float(explicit_fit_blend), 0.0, 0.50)
        output = (output * (1.0 - w)) + (float(explicit_fit_final) * w)
    return clamp(output, 1.0 - float(hard_cap), 1.0 + float(hard_cap))

