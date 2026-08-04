from __future__ import annotations

import json
import os
from typing import Dict, List

from .types import ScoringConfig, ScoringRule


RULE_META: Dict[str, Dict[str, object]] = {
    "pass_yd": {"category": "passing", "buckets": ["QB"], "rule_type": "linear"},
    "pass_td": {"category": "passing", "buckets": ["QB"], "rule_type": "event"},
    "pass_int": {"category": "turnovers", "buckets": ["QB"], "rule_type": "event"},
    "pass_cmp": {"category": "passing", "buckets": ["QB"], "rule_type": "linear"},
    "pass_inc": {"category": "passing", "buckets": ["QB"], "rule_type": "linear"},
    "pass_fd": {"category": "first_downs", "buckets": ["QB"], "rule_type": "event"},
    "rush_yd": {"category": "rushing", "buckets": ["QB", "RB", "WR", "TE"], "rule_type": "linear"},
    "rush_td": {
        "category": "touchdowns",
        "buckets": ["QB", "RB", "WR", "TE"],
        "rule_type": "event",
    },
    "rush_fd": {
        "category": "first_downs",
        "buckets": ["QB", "RB", "WR", "TE"],
        "rule_type": "event",
    },
    "rec": {"category": "receptions", "buckets": ["RB", "WR", "TE"], "rule_type": "linear"},
    "rec_yd": {"category": "receiving", "buckets": ["RB", "WR", "TE"], "rule_type": "linear"},
    "rec_td": {"category": "touchdowns", "buckets": ["RB", "WR", "TE"], "rule_type": "event"},
    "rec_fd": {"category": "first_downs", "buckets": ["RB", "WR", "TE"], "rule_type": "event"},
    "bonus_rec_rb": {"category": "tiered_ppr", "buckets": ["RB"], "rule_type": "linear"},
    "bonus_rec_wr": {"category": "tiered_ppr", "buckets": ["WR"], "rule_type": "linear"},
    "bonus_rec_te": {"category": "te_premium", "buckets": ["TE"], "rule_type": "linear"},
    "bonus_fd_qb": {"category": "first_downs", "buckets": ["QB"], "rule_type": "event"},
    "bonus_fd_rb": {"category": "first_downs", "buckets": ["RB"], "rule_type": "event"},
    "bonus_fd_wr": {"category": "first_downs", "buckets": ["WR"], "rule_type": "event"},
    "bonus_fd_te": {"category": "first_downs", "buckets": ["TE"], "rule_type": "event"},
    "fum": {"category": "turnovers", "buckets": ["QB", "RB", "WR", "TE"], "rule_type": "event"},
    "fum_lost": {
        "category": "turnovers",
        "buckets": ["QB", "RB", "WR", "TE"],
        "rule_type": "event",
    },
    "bonus_pass_yd_300": {"category": "yardage_bonus", "buckets": ["QB"], "rule_type": "threshold"},
    "bonus_rush_yd_100": {
        "category": "yardage_bonus",
        "buckets": ["QB", "RB", "WR", "TE"],
        "rule_type": "threshold",
    },
    "bonus_rec_yd_100": {
        "category": "yardage_bonus",
        "buckets": ["RB", "WR", "TE"],
        "rule_type": "threshold",
    },
    "bonus_pass_td_50+": {
        "category": "long_play_bonus",
        "buckets": ["QB"],
        "rule_type": "threshold",
    },
    "bonus_rush_td_40+": {
        "category": "long_play_bonus",
        "buckets": ["QB", "RB", "WR", "TE"],
        "rule_type": "threshold",
    },
    "bonus_rec_td_40+": {
        "category": "long_play_bonus",
        "buckets": ["RB", "WR", "TE"],
        "rule_type": "threshold",
    },
    "kick_ret_td": {"category": "returns", "buckets": ["RB", "WR", "DB"], "rule_type": "event"},
    "punt_ret_td": {"category": "returns", "buckets": ["RB", "WR", "DB"], "rule_type": "event"},
    "idp_tkl_solo": {
        "category": "idp_tackles",
        "buckets": ["DL", "LB", "DB"],
        "rule_type": "linear",
    },
    "idp_tkl_ast": {
        "category": "idp_tackles",
        "buckets": ["DL", "LB", "DB"],
        "rule_type": "linear",
    },
    "idp_tkl_loss": {"category": "idp_tfl", "buckets": ["DL", "LB", "DB"], "rule_type": "event"},
    "idp_sack": {"category": "idp_splash", "buckets": ["DL", "LB"], "rule_type": "event"},
    "idp_hit": {"category": "idp_splash", "buckets": ["DL", "LB"], "rule_type": "event"},
    "idp_int": {"category": "idp_splash", "buckets": ["LB", "DB"], "rule_type": "event"},
    "idp_pd": {"category": "idp_splash", "buckets": ["LB", "DB"], "rule_type": "event"},
    "idp_ff": {"category": "idp_splash", "buckets": ["DL", "LB", "DB"], "rule_type": "event"},
    "idp_fum_rec": {"category": "idp_splash", "buckets": ["DL", "LB", "DB"], "rule_type": "event"},
    "idp_def_td": {"category": "idp_td", "buckets": ["DL", "LB", "DB"], "rule_type": "event"},
}


def compare_to_baseline(
    baseline_config: ScoringConfig, league_config: ScoringConfig
) -> List[ScoringRule]:
    baseline = baseline_config.scoring_map if isinstance(baseline_config, ScoringConfig) else {}
    league = league_config.scoring_map if isinstance(league_config, ScoringConfig) else {}
    keys = sorted(set(baseline.keys()) | set(league.keys()))
    out: List[ScoringRule] = []
    for key in keys:
        b = float(baseline.get(key, 0.0) or 0.0)
        league_val = float(league.get(key, 0.0) or 0.0)
        d = league_val - b
        if abs(d) < 1e-9:
            continue
        meta = RULE_META.get(key, {})
        out.append(
            ScoringRule(
                key=key,
                category=str(meta.get("category", "other")),
                baseline_value=b,
                league_value=league_val,
                delta=d,
                relevant_buckets=list(meta.get("buckets", [])),
                rule_type=str(meta.get("rule_type", "linear")),
            )
        )
    return out


# Rule keys whose per-rule contribution is preserved separately
# alongside the category aggregate.  Sandbox / research consumers (the
# TE Premium Lab) need to isolate these specific TE-bonus rules from
# the broader category buckets they share — e.g. ``bonus_fd_te`` is in
# the ``first_downs`` category, but the category aggregate also pools
# ``rec_fd`` and ``rush_fd``.  Removing the category-level aggregate
# when the operator only meant to remove the TE bonus would
# over-remove.  Keeping per-rule entries is additive — the existing
# category aggregate is unchanged.
RULE_CONTRIBUTION_DETAIL_KEYS: tuple[str, ...] = (
    "bonus_rec_te",
    "bonus_fd_te",
)


def bucket_rule_contributions(
    bucket: str,
    stats_per_game: Dict[str, float],
    delta_rules: List[ScoringRule],
) -> Dict[str, float]:
    """Aggregate per-bucket rule contributions by category.

    The aggregated map is what the live valuation pipeline has
    historically consumed.  For per-rule precision (e.g. isolating
    ``bonus_fd_te`` from the ``first_downs`` category), use
    ``bucket_rule_contributions_detail`` alongside this function.
    """
    if not isinstance(stats_per_game, dict):
        return {}
    out: Dict[str, float] = {}
    b = str(bucket or "").upper()
    for rule in delta_rules:
        if rule.relevant_buckets and b not in rule.relevant_buckets:
            continue
        stat_value = float(stats_per_game.get(rule.key, 0.0) or 0.0)
        contrib = stat_value * float(rule.delta)
        if abs(contrib) < 1e-8:
            continue
        out[rule.category] = out.get(rule.category, 0.0) + contrib
    return {k: round(float(v), 6) for k, v in out.items()}


def bucket_rule_contributions_detail(
    bucket: str,
    stats_per_game: Dict[str, float],
    delta_rules: List[ScoringRule],
    *,
    rule_keys: tuple[str, ...] = RULE_CONTRIBUTION_DETAIL_KEYS,
) -> Dict[str, float]:
    """Per-rule (rule.key) contributions for the selected rule keys.

    Same math as ``bucket_rule_contributions`` (stat × delta), but
    keyed by ``rule.key`` rather than ``rule.category`` so the
    operator can read each rule independently.  By default only the
    TE-bonus-specific rules in ``RULE_CONTRIBUTION_DETAIL_KEYS`` are
    emitted — keeping the surface area small for the contract.

    Every rule listed in ``rule_keys`` that's relevant to ``bucket``
    is included in the output, even when the contribution is zero,
    so a downstream consumer can deterministically tell "this rule
    has zero impact" apart from "this rule wasn't computed".  Rules
    irrelevant to the bucket (e.g. ``bonus_fd_te`` on a QB row) are
    skipped.
    """
    if not isinstance(stats_per_game, dict):
        return {}
    selected = set(rule_keys or ())
    if not selected:
        return {}
    b = str(bucket or "").upper()
    rule_by_key: Dict[str, ScoringRule] = {}
    for rule in delta_rules or []:
        if rule.key not in selected:
            continue
        if rule.relevant_buckets and b not in rule.relevant_buckets:
            continue
        rule_by_key[rule.key] = rule
    out: Dict[str, float] = {}
    for key, rule in rule_by_key.items():
        stat_value = float(stats_per_game.get(key, 0.0) or 0.0)
        out[key] = round(stat_value * float(rule.delta), 6)
    return out


def persist_scoring_delta_map(
    path: str,
    *,
    custom_league_id: str,
    baseline_league_id: str,
    baseline_scoring_version: str,
    league_scoring_version: str,
    rules: List[ScoringRule],
) -> None:
    if not path:
        return
    payload = []
    for rule in rules or []:
        try:
            payload.append(rule.to_dict() if hasattr(rule, "to_dict") else dict(rule))
        except Exception:
            continue
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "customLeagueId": str(custom_league_id or ""),
                "baselineLeagueId": str(baseline_league_id or ""),
                "baselineScoringVersion": str(baseline_scoring_version or ""),
                "leagueScoringVersion": str(league_scoring_version or ""),
                "rules": payload,
            },
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
