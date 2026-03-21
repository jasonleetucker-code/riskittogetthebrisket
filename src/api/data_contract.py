from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re
from typing import Any

from src.utils import normalize_player_name

from src.offseason.mike_clay.integration import (
    apply_mike_clay_overlay,
    get_mike_clay_runtime_context,
)

CONTRACT_VERSION = "2026-03-20.v6"

REQUIRED_TOP_LEVEL_KEYS = {
    "contractVersion",
    "generatedAt",
    "players",
    "playersArray",
    "runtimeAuthority",
    "valueAuthority",
    "valueResolverDiagnostics",
    "sites",
    "maxValues",
}

REQUIRED_PLAYER_KEYS = {
    "playerId",
    "canonicalName",
    "displayName",
    "position",
    "team",
    "rookie",
    "values",
    "valueBundle",
    "confidence",
    "sourceCoverage",
    "adjustmentTags",
    "canonicalSiteValues",
    "sourceCount",
}

REQUIRED_VALUE_BUNDLE_KEYS = {
    "rawValue",
    "scoringAdjustedValue",
    "scarcityAdjustedValue",
    "bestBallAdjustedValue",
    "fullValue",
    "confidence",
    "sourceCoverage",
    "adjustmentTags",
    "layers",
}


BEST_BALL_REPLACEMENT_FLOOR = {
    "QB": 1800.0,
    "RB": 1200.0,
    "WR": 1200.0,
    "TE": 1050.0,
    "DL": 900.0,
    "LB": 900.0,
    "DB": 880.0,
    "PICK": 1300.0,
}

BEST_BALL_REPLACEMENT_CEILING = {
    "QB": 9300.0,
    "RB": 9000.0,
    "WR": 9100.0,
    "TE": 8600.0,
    "DL": 7600.0,
    "LB": 7300.0,
    "DB": 7000.0,
    "PICK": 6200.0,
}

BEST_BALL_POSITION_LEVERAGE = {
    "QB": 0.78,
    "RB": 0.95,
    "WR": 1.08,
    "TE": 1.02,
    "DL": 0.94,
    "LB": 0.86,
    "DB": 0.84,
    "PICK": 0.70,
}

BEST_BALL_DEPTH_POSITION_WEIGHT = {
    "QB": 0.46,
    "RB": 0.88,
    "WR": 1.00,
    "TE": 0.84,
    "DL": 0.78,
    "LB": 0.65,
    "DB": 0.62,
    "PICK": 0.50,
}

BEST_BALL_ARCHETYPE_CEILING_BONUS = {
    "field_stretcher_wr": 0.24,
    "td_te": 0.22,
    "goal_line_rb": 0.20,
    "sack_dl": 0.21,
    "ballhawk_db": 0.18,
    "dual_threat_qb": 0.16,
    "receiving_rb": 0.12,
    "development_qb": 0.08,
    "ascending_receiver": 0.10,
    "target_earner": 0.06,
    "workhorse_back": 0.05,
    "franchise_qb": 0.04,
    "volume_te": 0.02,
    "possession_wr": -0.06,
    "tackle_lb": -0.04,
    "tackle_db": -0.05,
    "tackle_dl": -0.04,
}

BEST_BALL_ARCHETYPE_SPIKE_BONUS = {
    "field_stretcher_wr": 0.25,
    "td_te": 0.24,
    "goal_line_rb": 0.22,
    "sack_dl": 0.24,
    "ballhawk_db": 0.20,
    "dual_threat_qb": 0.15,
    "ascending_receiver": 0.10,
    "target_earner": 0.07,
    "workhorse_back": 0.05,
    "possession_wr": -0.07,
    "tackle_lb": -0.05,
    "tackle_db": -0.06,
}

BEST_BALL_TAG_BONUS = {
    "td_sensitive": 0.14,
    "first_down_heavy": 0.09,
    "idp_splash": 0.15,
    "reception_sensitive": 0.03,
    "carry_sensitive": 0.02,
    "te_premium_sensitive": 0.05,
    "balanced_profile": -0.06,
}

# Fields that are useful for deeper diagnostics/explanations but are not required
# for initial first-paint startup rendering in the Static runtime.
STARTUP_HEAVY_PLAYER_FIELD_PREFIXES = ("_formatFit",)
STARTUP_HEAVY_PLAYER_FIELDS = {
    "_scoringAdjustment",
}
STARTUP_DROP_TOP_LEVEL_KEYS = {
    # Large secondary blocks not required for first-screen calculator/rankings usability.
    "coverageAudit",
    "ktcCrowd",
    # Runtime/startup views intentionally avoid the duplicated contract array.
    "playersArray",
}

IDP_POSITIONS = {"DL", "LB", "DB"}
PICK_POSITION = "PICK"

IDP_MARKET_SITE_KEYS = {
    "idpTradeCalc",
    "pffIdp",
    "fantasyProsIdp",
    "dlfIdp",
    "dlfRidp",
}
OFFENSE_MARKET_SITE_KEYS = {
    "ktc",
    "fantasyCalc",
    "dynastyDaddy",
    "fantasyPros",
    "draftSharks",
    "yahoo",
    "dynastyNerds",
    "dlfSf",
    "dlfRsf",
}
PICK_MARKET_SITE_KEYS = {"ktc", "fantasyCalc", "dynastyDaddy", "yahoo", "idpTradeCalc"}
IDP_SIGNAL_SITE_KEYS = {"dlfIdp", "dlfRidp", "pffIdp", "fantasyProsIdp", "idpTradeCalc"}

# Trust-first final-authority guardrail thresholds.
LOW_CONFIDENCE_CAP_THRESHOLD = 0.55
ULTRA_LOW_CONFIDENCE_QUARANTINE_THRESHOLD = 0.32
SINGLE_SOURCE_COUNT_THRESHOLD = 1
EXTREME_DISPERSION_CV_THRESHOLD = 0.60
LOW_COVERAGE_RATIO_THRESHOLD = 0.22


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except Exception:
        return None
    if not math.isfinite(n):
        return None
    return n


def _to_int_or_none(v: Any) -> int | None:
    n = _safe_num(v)
    if n is None:
        return None
    return int(round(n))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize_value_int(v: Any) -> int | None:
    n = _to_int_or_none(v)
    if n is None or n <= 0:
        return None
    return int(_clamp(n, 1, 9999))


def _normalize_pos(pos: Any) -> str:
    p = str(pos or "").strip().upper()
    if p in {"DE", "DT", "EDGE", "NT"}:
        return "DL"
    if p in {"CB", "S", "FS", "SS"}:
        return "DB"
    if p in {"OLB", "ILB"}:
        return "LB"
    return p


def _is_pick_name(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    if re.search(r"\b(20\d{2})\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)\b", n, re.I):
        return True
    if re.search(r"\b(20\d{2})\s+[1-6]\.(0?[1-9]|1[0-2])\b", n, re.I):
        return True
    if re.search(r"\b(20\d{2})\s+(PICK|ROUND)\b", n, re.I):
        return True
    return False


def _canonical_site_values(
    p_data: dict[str, Any],
    site_keys: list[str],
) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    explicit = p_data.get("_canonicalSiteValues")
    if isinstance(explicit, dict):
        for key in site_keys:
            out[key] = _to_int_or_none(explicit.get(key))
        for key, val in explicit.items():
            if key not in out:
                out[str(key)] = _to_int_or_none(val)
        return out

    for key in site_keys:
        out[key] = _to_int_or_none(p_data.get(key))
    return out


def _positive_site_count(canonical_sites: dict[str, int | None]) -> int:
    count = 0
    for value in (canonical_sites or {}).values():
        if value is not None and value > 0:
            count += 1
    return int(count)


def _source_count(p_data: dict[str, Any], canonical_sites: dict[str, int | None]) -> int:
    positive_sites = _positive_site_count(canonical_sites)
    if positive_sites <= 0:
        return 0

    explicit_sites = _to_int_or_none(p_data.get("_sites"))
    if explicit_sites is None or explicit_sites < 0:
        return positive_sites
    if explicit_sites == 0:
        return positive_sites
    return int(max(1, min(int(explicit_sites), positive_sites)))


def _clean_adjustment_tags(raw_tags: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    if isinstance(raw_tags, str):
        candidates = re.split(r"[,;\s]+", raw_tags.strip())
    elif isinstance(raw_tags, list):
        candidates = raw_tags
    else:
        candidates = []

    for item in candidates:
        tag = str(item or "").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _parse_scoring_tags(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, list):
        return _clean_adjustment_tags(raw_tags)
    if isinstance(raw_tags, str):
        return _clean_adjustment_tags(
            [x for x in re.split(r"[|,;/\s]+", raw_tags.strip()) if x]
        )
    return []


def _resolve_confidence(
    p_data: dict[str, Any],
    source_coverage: dict[str, Any],
    source_count: int,
    *,
    pos: str,
    canonical_sites: dict[str, int | None],
) -> float:
    explicit_confidence = _safe_num(
        p_data.get("_marketReliabilityScore", p_data.get("_marketConfidence"))
    )
    coverage_ratio = _safe_num(source_coverage.get("ratio"))
    coverage_score = (
        _clamp(0.30 + (0.60 * coverage_ratio), 0.20, 1.00)
        if coverage_ratio is not None
        else (0.55 if source_count >= 3 else 0.35)
    )
    dispersion_cv = _safe_num(p_data.get("_marketDispersionCV"))
    dispersion_score = (
        _clamp(1.0 - (abs(float(dispersion_cv)) / 0.55), 0.20, 1.00)
        if dispersion_cv is not None
        else 0.60
    )

    if explicit_confidence is None:
        confidence = (0.55 * coverage_score) + (0.45 * dispersion_score)
    else:
        confidence = (
            (0.72 * explicit_confidence)
            + (0.20 * coverage_score)
            + (0.08 * dispersion_score)
        )

    is_pick = pos == PICK_POSITION
    if is_pick and source_count >= 2:
        confidence = max(confidence, 0.56)

    if pos in IDP_POSITIONS and source_count >= 3:
        has_idp_market = any(
            (_to_int_or_none(canonical_sites.get(key)) or 0) > 0
            for key in IDP_MARKET_SITE_KEYS
        )
        if has_idp_market:
            confidence = max(confidence, 0.50)

    if bool(p_data.get("_fallbackValue")) and source_count == 0:
        confidence = min(confidence, 0.34)

    return round(_clamp(float(confidence), 0.0, 1.0), 4)


def _best_ball_metrics_from_profile(
    *,
    scarcity_value: int,
    pos: str,
    p_data: dict[str, Any],
    source_count: int,
    source_coverage: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    coverage_ratio = _safe_num(source_coverage.get("ratio"))
    if coverage_ratio is None:
        coverage_ratio = _clamp(source_count / 8.0, 0.0, 1.0)

    fmt_confidence = _safe_num(p_data.get("_formatFitConfidence"))
    if fmt_confidence is None:
        fmt_confidence = confidence
    fmt_confidence = _clamp(fmt_confidence, 0.0, 1.0)

    projection_weight = _safe_num(p_data.get("_formatFitProjectionWeight"))
    if projection_weight is None:
        projection_weight = 0.42
    projection_weight = _clamp(projection_weight, 0.0, 1.0)

    role_stability = _safe_num(p_data.get("_formatFitRRoleStabilityScore"))
    if role_stability is None:
        role_stability = _clamp(1.0 - (projection_weight * 0.65), 0.0, 1.0)
    role_stability = _clamp(role_stability, 0.0, 1.0)

    recency_score = _safe_num(p_data.get("_formatFitRRecencyScore"))
    if recency_score is None:
        recency_score = 0.65
    recency_score = _clamp(recency_score, 0.0, 1.0)

    archetype = str(p_data.get("_formatFitArchetype") or "").strip().lower()
    tags = _parse_scoring_tags(p_data.get("_formatFitScoringTags"))

    rule_contrib = p_data.get("_formatFitRuleContributions")
    abs_rule_values: list[float] = []
    td_dependency = 0.0
    if isinstance(rule_contrib, dict):
        for k, v in rule_contrib.items():
            n = abs(_safe_num(v) or 0.0)
            if n <= 0:
                continue
            abs_rule_values.append(n)
            key = str(k or "").lower()
            if "td" in key or "splash" in key or "bonus" in key:
                td_dependency += n
    total_abs_rule = sum(abs_rule_values)
    rule_concentration = (
        max(abs_rule_values) / total_abs_rule if total_abs_rule > 0 else 0.0
    )
    td_dependency = (
        _clamp(td_dependency / max(total_abs_rule, 1e-9), 0.0, 1.0)
        if total_abs_rule > 0
        else 0.0
    )

    tier_score = _clamp((scarcity_value - 300.0) / 9000.0, 0.0, 1.0)
    rep_floor = BEST_BALL_REPLACEMENT_FLOOR.get(pos, 1000.0)
    rep_ceiling = BEST_BALL_REPLACEMENT_CEILING.get(pos, 8500.0)
    replacement_beating_share = _clamp(
        (scarcity_value - rep_floor) / max(1.0, rep_ceiling - rep_floor),
        0.0,
        1.0,
    )

    format_fit_raw = _safe_num(p_data.get("_formatFitRaw"))
    format_fit_raw_norm = 0.0
    if format_fit_raw is not None:
        format_fit_raw_norm = _clamp((format_fit_raw - 1.0) / 0.25, 0.0, 1.0)

    weekly_ceiling = (
        0.34
        + (0.36 * tier_score)
        + BEST_BALL_ARCHETYPE_CEILING_BONUS.get(archetype, 0.0)
        + sum(BEST_BALL_TAG_BONUS.get(t, 0.0) for t in tags)
        + (0.10 * format_fit_raw_norm)
        + (0.08 * td_dependency)
    )
    weekly_ceiling = _clamp(weekly_ceiling, 0.0, 1.0)

    volatility_flag = bool(p_data.get("_formatFitVolatilityFlag"))
    spike_week_frequency = (
        0.24
        + (0.32 * weekly_ceiling)
        + BEST_BALL_ARCHETYPE_SPIKE_BONUS.get(archetype, 0.0)
        + (0.16 * rule_concentration)
        + (0.08 * td_dependency)
        + (0.10 if volatility_flag else 0.0)
    )
    if "balanced_profile" in tags:
        spike_week_frequency -= 0.05
    spike_week_frequency = _clamp(spike_week_frequency, 0.0, 1.0)

    stable_conf = (0.65 * confidence) + (0.35 * fmt_confidence)
    startable_week_rate = (
        0.12
        + (0.34 * replacement_beating_share)
        + (0.30 * stable_conf)
        + (0.16 * role_stability)
        + (0.04 * coverage_ratio)
        + (0.04 * recency_score)
        - (0.08 * projection_weight)
    )
    startable_week_rate = _clamp(startable_week_rate, 0.0, 1.0)

    volatility_utility = (
        (0.58 * spike_week_frequency) + (0.42 * weekly_ceiling)
    ) * (0.45 + (0.55 * startable_week_rate))
    volatility_utility = _clamp(volatility_utility, 0.0, 1.0)
    if confidence < 0.50 or coverage_ratio < 0.35:
        volatility_utility = _clamp(volatility_utility * 0.62, 0.0, 1.0)

    rookie = bool(p_data.get("_formatFitRookie") or p_data.get("_isRookie"))
    low_sample = bool(p_data.get("_formatFitLowSample"))
    role_change = bool(p_data.get("_formatFitRoleChange"))
    contingent_upside = (
        0.10
        + (0.20 if rookie else 0.0)
        + (0.12 if low_sample else 0.0)
        + (0.11 if role_change else 0.0)
        + (0.18 * projection_weight)
        + (0.10 * max(0.0, 1.0 - role_stability))
        + (0.08 * spike_week_frequency)
    )
    contingent_upside = _clamp(contingent_upside, 0.0, 1.0)
    contingent_upside *= 0.45 + (0.55 * max(confidence, 0.35))
    contingent_upside = _clamp(contingent_upside, 0.0, 1.0)

    depth_band = _clamp((4700.0 - scarcity_value) / 3400.0, 0.0, 1.0)
    depth_weight = BEST_BALL_DEPTH_POSITION_WEIGHT.get(pos, 0.70)
    depth_utility = depth_weight * depth_band * (0.35 + (0.65 * startable_week_rate))
    depth_utility = _clamp(depth_utility, 0.0, 1.0)

    position_leverage = BEST_BALL_POSITION_LEVERAGE.get(pos, 0.90)

    raw_signal = (
        0.24 * (weekly_ceiling - 0.44)
        + 0.20 * (spike_week_frequency - 0.40)
        + 0.18 * (startable_week_rate - 0.50)
        + 0.14 * (replacement_beating_share - 0.42)
        + 0.10 * (volatility_utility - 0.36)
        + 0.08 * (contingent_upside - 0.28)
        + 0.06 * (depth_utility - 0.25)
    ) * position_leverage
    delta_pct_raw = raw_signal * 0.28

    confidence_gate = _clamp(
        0.24 + (0.52 * confidence) + (0.24 * coverage_ratio),
        0.24,
        1.0,
    )
    positive_gate = confidence_gate
    if confidence < 0.50:
        positive_gate *= 0.72
    if source_count <= 1:
        positive_gate *= 0.80
    negative_gate = 0.60 + (0.40 * confidence_gate)

    if delta_pct_raw >= 0:
        delta_pct_effective = delta_pct_raw * positive_gate
    else:
        delta_pct_effective = delta_pct_raw * negative_gate

    max_up = 0.12
    if confidence < 0.45:
        max_up *= 0.45
    if source_count <= 1:
        max_up *= 0.65
    delta_pct_effective = _clamp(delta_pct_effective, -0.09, max_up)

    return {
        "weeklyCeiling": round(weekly_ceiling, 4),
        "spikeWeekFrequency": round(spike_week_frequency, 4),
        "startableWeekRate": round(startable_week_rate, 4),
        "replacementBeatingShare": round(replacement_beating_share, 4),
        "volatilityUtility": round(volatility_utility, 4),
        "contingentUpside": round(contingent_upside, 4),
        "depthUtility": round(depth_utility, 4),
        "positionLeverage": round(position_leverage, 4),
        "confidenceGate": round(confidence_gate, 4),
        "positiveGate": round(positive_gate, 4),
        "negativeGate": round(negative_gate, 4),
        "ruleConcentration": round(rule_concentration, 4),
        "tdDependency": round(td_dependency, 4),
        "rawSignal": round(raw_signal, 6),
        "deltaPctRaw": round(delta_pct_raw, 6),
        "deltaPctEffective": round(delta_pct_effective, 6),
        "volatilityFlag": volatility_flag,
        "archetype": archetype,
        "scoringTags": tags,
    }


def _resolve_best_ball_layer(
    scarcity_value: int,
    p_data: dict[str, Any],
    *,
    pos: str,
    source_count: int,
    source_coverage: dict[str, Any],
    confidence: float,
) -> tuple[int, str, dict[str, Any]]:
    explicit = _normalize_value_int(
        p_data.get(
            "_bestBallAdjusted",
            p_data.get("_bestBallAdjustedValue", p_data.get("_bestBallValue")),
        )
    )
    if explicit is not None:
        delta = int(explicit - scarcity_value)
        return (
            explicit,
            "backend_best_ball_explicit",
            {
                "deltaFromScarcity": delta,
                "deltaPctEffective": round(delta / max(1, scarcity_value), 6),
                "multiplierRaw": round(explicit / max(1, scarcity_value), 6),
                "multiplierEffective": round(explicit / max(1, scarcity_value), 6),
                "guards": {"mode": "explicit"},
                "metrics": {},
            },
        )

    boost = _safe_num(p_data.get("_bestBallBoost"))
    if boost is not None:
        # Accept either multiplier-style boosts (1.08), percentage deltas (0.08),
        # or additive deltas (e.g. +180) from legacy payloads.
        source = "best_ball_value_delta"
        if 0.5 <= boost <= 2.0:
            resolved = _normalize_value_int(scarcity_value * boost)
            source = "best_ball_multiplier"
        elif -0.5 <= boost <= 0.5:
            resolved = _normalize_value_int(scarcity_value * (1.0 + boost))
            source = "best_ball_pct_delta"
        else:
            resolved = _normalize_value_int(scarcity_value + boost)
        best_ball = resolved or scarcity_value
        delta = int(best_ball - scarcity_value)
        return (
            best_ball,
            source,
            {
                "deltaFromScarcity": delta,
                "deltaPctEffective": round(delta / max(1, scarcity_value), 6),
                "multiplierRaw": round(best_ball / max(1, scarcity_value), 6),
                "multiplierEffective": round(best_ball / max(1, scarcity_value), 6),
                "guards": {"mode": "legacy_boost"},
                "metrics": {},
            },
        )

    if pos == "PICK":
        return (
            scarcity_value,
            "pick_passthrough",
            {
                "deltaFromScarcity": 0,
                "deltaPctEffective": 0.0,
                "multiplierRaw": 1.0,
                "multiplierEffective": 1.0,
                "guards": {"mode": "pick_passthrough"},
                "metrics": {},
            },
        )

    if pos == "K":
        return (
            scarcity_value,
            "kicker_passthrough",
            {
                "deltaFromScarcity": 0,
                "deltaPctEffective": 0.0,
                "multiplierRaw": 1.0,
                "multiplierEffective": 1.0,
                "guards": {"mode": "kicker_passthrough"},
                "metrics": {},
            },
        )

    metrics = _best_ball_metrics_from_profile(
        scarcity_value=scarcity_value,
        pos=pos,
        p_data=p_data,
        source_count=source_count,
        source_coverage=source_coverage,
        confidence=confidence,
    )
    delta_pct_effective = _safe_num(metrics.get("deltaPctEffective")) or 0.0
    model_value = _normalize_value_int(scarcity_value * (1.0 + delta_pct_effective))
    best_ball = model_value or scarcity_value
    delta = int(best_ball - scarcity_value)
    source = "best_ball_component_model" if delta != 0 else "best_ball_component_neutral"
    return (
        best_ball,
        source,
        {
            "deltaFromScarcity": delta,
            "deltaPctEffective": round(delta / max(1, scarcity_value), 6),
            "multiplierRaw": round(1.0 + (_safe_num(metrics.get("deltaPctRaw")) or 0.0), 6),
            "multiplierEffective": round(best_ball / max(1, scarcity_value), 6),
            "guards": {
                "maxUp": round(0.12 * (0.45 if confidence < 0.45 else 1.0) * (0.65 if source_count <= 1 else 1.0), 6),
                "maxDown": 0.09,
                "confidence": round(confidence, 4),
                "sourceCount": int(max(0, source_count)),
                "sourceCoverageRatio": source_coverage.get("ratio"),
            },
            "metrics": metrics,
        },
    )


def _expected_sites_for_pos(pos: str, site_keys: list[str]) -> int:
    configured_site_keys = {
        str(k).strip()
        for k in (site_keys or [])
        if str(k or "").strip()
    }
    if not configured_site_keys:
        return 0

    pos_norm = _normalize_pos(pos)
    if pos_norm == PICK_POSITION:
        expected_keys = PICK_MARKET_SITE_KEYS
    elif pos_norm in IDP_POSITIONS:
        expected_keys = IDP_MARKET_SITE_KEYS
    else:
        expected_keys = OFFENSE_MARKET_SITE_KEYS

    expected_configured = configured_site_keys.intersection(expected_keys)
    if expected_configured:
        return int(len(expected_configured))
    return int(len(configured_site_keys))


def _build_source_coverage(
    source_count: int,
    site_keys: list[str],
    p_data: dict[str, Any],
    *,
    pos: str,
) -> dict[str, Any]:
    total_sites = _expected_sites_for_pos(pos, site_keys)
    explicit_ratio = _safe_num(
        p_data.get("_sourceCoverageRatio", p_data.get("_marketCoverageRatio"))
    )
    ratio: float | None = None
    if explicit_ratio is not None:
        ratio = _clamp(explicit_ratio, 0.0, 1.0)
    elif total_sites > 0:
        ratio = _clamp(source_count / max(1, total_sites), 0.0, 1.0)

    return {
        "count": int(max(0, source_count)),
        "totalSites": int(total_sites),
        "ratio": (round(ratio, 4) if ratio is not None else None),
    }


def _legacy_values_from_bundle(value_bundle: dict[str, Any]) -> dict[str, int | None]:
    raw = _normalize_value_int(value_bundle.get("rawValue"))
    scoring = _normalize_value_int(value_bundle.get("scoringAdjustedValue")) or raw
    scarcity = _normalize_value_int(value_bundle.get("scarcityAdjustedValue")) or scoring
    best_ball = _normalize_value_int(value_bundle.get("bestBallAdjustedValue")) or scarcity

    guardrails = value_bundle.get("guardrails")
    guardrails = guardrails if isinstance(guardrails, dict) else {}
    quarantined = bool(guardrails.get("quarantined"))

    full = _normalize_value_int(value_bundle.get("fullValue"))
    if full is None and not quarantined:
        full = best_ball or raw

    return {
        "overall": (full if full is not None else (None if quarantined else best_ball)),
        "rawComposite": raw,
        "scoringAdjusted": scoring,
        "scarcityAdjusted": scarcity,
        "bestBallAdjusted": best_ball,
        "finalAdjusted": full,
    }


def _apply_full_value_guardrails(
    *,
    pos: str,
    p_data: dict[str, Any],
    source_count: int,
    source_coverage: dict[str, Any],
    confidence: float,
    scarcity: int,
    best_ball: int,
    full_value: int,
    full_authority_status: str,
) -> tuple[int | None, dict[str, Any], list[str]]:
    cap_reasons: list[str] = []
    quarantine_reasons: list[str] = []
    tags: list[str] = []

    is_pick = pos == PICK_POSITION
    is_idp = pos in IDP_POSITIONS
    rookie = bool(p_data.get("_formatFitRookie") or p_data.get("_isRookie"))

    coverage_ratio = _safe_num(source_coverage.get("ratio"))
    dispersion_cv = _safe_num(p_data.get("_marketDispersionCV"))
    full_pre_guardrails = int(full_value)
    guardrailed_full = int(full_value)

    if not is_pick and not str(pos or "").strip():
        quarantine_reasons.append("position_unresolved")
        tags.append("position_unresolved")

    if (
        not is_pick
        and source_count <= SINGLE_SOURCE_COUNT_THRESHOLD
        and confidence < ULTRA_LOW_CONFIDENCE_QUARANTINE_THRESHOLD
    ):
        quarantine_reasons.append("ultra_low_confidence_single_source")

    if (
        not is_pick
        and dispersion_cv is not None
        and dispersion_cv >= EXTREME_DISPERSION_CV_THRESHOLD
        and source_count <= SINGLE_SOURCE_COUNT_THRESHOLD
        and confidence < 0.45
    ):
        quarantine_reasons.append("extreme_disagreement_single_source")

    if not quarantine_reasons:
        if (
            not is_pick
            and source_count <= SINGLE_SOURCE_COUNT_THRESHOLD
            and confidence < LOW_CONFIDENCE_CAP_THRESHOLD
        ):
            cap_value = int(round(scarcity * 1.03))
            if guardrailed_full > cap_value:
                guardrailed_full = cap_value
                cap_reasons.append("single_source_low_confidence_cap")

        if (
            not is_pick
            and coverage_ratio is not None
            and coverage_ratio < LOW_COVERAGE_RATIO_THRESHOLD
            and confidence < 0.50
        ):
            cap_value = int(round(scarcity * 1.02))
            if guardrailed_full > cap_value:
                guardrailed_full = cap_value
                cap_reasons.append("low_coverage_ratio_cap")

        if (
            not is_pick
            and dispersion_cv is not None
            and dispersion_cv >= EXTREME_DISPERSION_CV_THRESHOLD
            and source_count <= 2
        ):
            cap_value = int(round(scarcity * 1.06))
            if guardrailed_full > cap_value:
                guardrailed_full = cap_value
                cap_reasons.append("extreme_source_disagreement_cap")

        if (
            not is_pick
            and is_idp
            and rookie
            and source_count <= SINGLE_SOURCE_COUNT_THRESHOLD
            and confidence < 0.55
        ):
            cap_value = int(round(best_ball * 1.01))
            if guardrailed_full > cap_value:
                guardrailed_full = cap_value
                cap_reasons.append("idp_rookie_low_confidence_cap")

        if (
            not is_pick
            and full_authority_status != "final_adjusted_authoritative"
            and source_count <= SINGLE_SOURCE_COUNT_THRESHOLD
            and confidence < 0.50
        ):
            cap_value = int(round(scarcity))
            if guardrailed_full > cap_value:
                guardrailed_full = cap_value
                cap_reasons.append("derived_full_value_single_source_cap")

    if full_authority_status != "final_adjusted_authoritative":
        tags.append("full_authority_derived_without_final_adjusted")

    if cap_reasons:
        tags.append("final_authority_guardrail_capped")
    if quarantine_reasons:
        tags.append("quarantined_from_final_authority")
        if "position_unresolved" in quarantine_reasons:
            tags.append("unresolved_position_quarantine")

    final_status = "quarantined" if quarantine_reasons else full_authority_status
    full_out = None if quarantine_reasons else (_normalize_value_int(guardrailed_full) or 1)

    guardrail_meta = {
        "finalAuthorityStatus": final_status,
        "quarantined": bool(quarantine_reasons),
        "quarantineReasons": quarantine_reasons,
        "capped": bool(cap_reasons),
        "capReasons": cap_reasons,
        "fullValueBeforeGuardrails": full_pre_guardrails,
        "fullValueAfterGuardrails": full_out,
        "confidence": round(confidence, 4),
        "sourceCount": int(max(0, source_count)),
        "sourceCoverageRatio": (
            round(float(coverage_ratio), 4) if coverage_ratio is not None else None
        ),
        "dispersionCV": round(float(dispersion_cv), 4) if dispersion_cv is not None else None,
        "positionResolved": bool(str(pos or "").strip()),
    }
    return full_out, guardrail_meta, tags


def _authoritative_value_bundle(
    *,
    name: str,
    p_data: dict[str, Any],
    pos: str,
    source_count: int,
    canonical_sites: dict[str, int | None],
    site_keys: list[str],
    clay_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    raw = _normalize_value_int(
        p_data.get("_rawComposite", p_data.get("_rawMarketValue", p_data.get("_composite")))
    )
    if raw is None:
        raw = 1
    raw_source = (
        "backend_raw_composite"
        if _normalize_value_int(p_data.get("_rawComposite")) is not None
        else (
            "backend_raw_market_value"
            if _normalize_value_int(p_data.get("_rawMarketValue")) is not None
            else "backend_legacy_composite"
        )
    )

    scoring = _normalize_value_int(p_data.get("_scoringAdjusted"))
    scoring_source = "backend_scoring_adjusted"
    if scoring is None:
        scoring = _normalize_value_int(p_data.get("_leagueAdjusted")) or raw
        scoring_source = (
            "fallback_league_adjusted"
            if _normalize_value_int(p_data.get("_leagueAdjusted")) is not None
            else "fallback_raw_passthrough"
        )

    scarcity = _normalize_value_int(p_data.get("_scarcityAdjusted"))
    scarcity_source = "backend_scarcity_adjusted"
    if scarcity is None:
        scarcity = scoring
        scarcity_source = "fallback_scoring_passthrough"

    source_coverage = _build_source_coverage(source_count, site_keys, p_data, pos=pos)
    confidence = _resolve_confidence(
        p_data,
        source_coverage,
        source_count,
        pos=pos,
        canonical_sites=canonical_sites,
    )
    best_ball, best_ball_source, best_ball_detail = _resolve_best_ball_layer(
        scarcity,
        p_data,
        pos=pos,
        source_count=source_count,
        source_coverage=source_coverage,
        confidence=confidence,
    )

    backend_final = _normalize_value_int(p_data.get("_finalAdjusted"))
    if backend_final is not None:
        full = backend_final
        full_source = "backend_final_adjusted"
        full_authority_status = "final_adjusted_authoritative"
    else:
        # Avoid quietly aliasing full/final authority to league-adjusted scoring output.
        full = best_ball
        full_source = "derived_best_ball_final"
        league_anchor = _normalize_value_int(p_data.get("_leagueAdjusted"))
        if league_anchor is not None:
            anchored_cap = int(league_anchor)
            if full > anchored_cap:
                full = anchored_cap
                full_source = "derived_best_ball_league_anchor_cap"
        full_authority_status = "derived_without_final_adjusted"

    full_before_clay = int(full)
    base_full_source = str(full_source)
    full, clay_layer = apply_mike_clay_overlay(
        runtime=clay_runtime,
        canonical_name=name,
        player_id=str(p_data.get("_sleeperId") or "").strip(),
        pos=pos,
        base_value=full_before_clay,
        source_count=source_count,
    )
    if clay_layer.get("active") and bool(clay_layer.get("applied")):
        full_source = str(clay_layer.get("source") or "offseason_clay_overlay_applied")

    full_before_guardrails = int(_normalize_value_int(full) or full_before_clay)
    full, guardrails, guardrail_tags = _apply_full_value_guardrails(
        pos=pos,
        p_data=p_data,
        source_count=source_count,
        source_coverage=source_coverage,
        confidence=confidence,
        scarcity=scarcity,
        best_ball=best_ball,
        full_value=full_before_guardrails,
        full_authority_status=full_authority_status,
    )
    guardrails["fullBaseSource"] = base_full_source
    guardrails["fullEffectiveSource"] = (
        "quarantined_no_final_value" if full is None else str(full_source)
    )
    guardrails["fullValueBeforeClay"] = full_before_clay
    guardrails["fullValueBeforeQuarantine"] = full_before_guardrails

    tags = _clean_adjustment_tags(p_data.get("_adjustmentTags"))
    if not tags:
        tags = []
    if scoring_source.startswith("fallback_"):
        tags.append("scoring_layer_fallback")
    if scarcity_source.startswith("fallback_"):
        tags.append("scarcity_layer_fallback")
    if best_ball_source.endswith("passthrough"):
        tags.append("best_ball_layer_passthrough")
    bb_delta = int(best_ball - scarcity)
    bb_metrics = (
        best_ball_detail.get("metrics")
        if isinstance(best_ball_detail, dict)
        else None
    )
    spike = _safe_num((bb_metrics or {}).get("spikeWeekFrequency"))
    depth_utility = _safe_num((bb_metrics or {}).get("depthUtility"))
    if bb_delta > 0:
        tags.append("best_ball_boosted")
    elif bb_delta < 0:
        tags.append("best_ball_discounted")
    if spike is not None and spike >= 0.68:
        tags.append("spike_week_profile")
    if depth_utility is not None and depth_utility >= 0.55:
        tags.append("depth_utility_profile")
    bb_delta_pct = bb_delta / max(1, scarcity)
    if abs(bb_delta_pct) >= 0.08:
        tags.append("best_ball_high_impact")
    if bb_delta > 0 and confidence < 0.45:
        tags.append("best_ball_confidence_capped")
    if full_source.startswith("fallback_") or full_authority_status != "final_adjusted_authoritative":
        tags.append("full_layer_fallback")
    if clay_layer.get("active"):
        tags.append("offseason_clay_considered")
        if clay_layer.get("applied"):
            tags.append("offseason_clay_applied")
        if str(clay_layer.get("supportTier") or "") == "strong":
            tags.append("offseason_clay_strong_support")
        if str(clay_layer.get("excludedReason") or ""):
            tags.append("offseason_clay_excluded")
    if source_count <= 1:
        tags.append("single_source_market")
    if confidence < 0.50:
        tags.append("low_confidence")
    if pos in IDP_POSITIONS:
        tags.append("idp_asset")
    if pos == PICK_POSITION:
        tags.append("pick_asset")
    tags.extend(guardrail_tags)
    tags = _clean_adjustment_tags(tags)

    full_layer_source = (
        "quarantined_no_final_value" if full is None else str(full_source)
    )

    return {
        "rawValue": raw,
        "scoringAdjustedValue": scoring,
        "scarcityAdjustedValue": scarcity,
        "bestBallAdjustedValue": best_ball,
        "fullValue": full,
        "confidence": confidence,
        "sourceCoverage": source_coverage,
        "sourceCoverageRatio": source_coverage.get("ratio"),
        "sourceCount": source_count,
        "adjustmentTags": tags,
        "guardrails": guardrails,
        "layers": {
            "rawMarket": {
                "value": raw,
                "source": raw_source,
                "deltaFromRaw": 0,
            },
            "scoring": {
                "value": scoring,
                "source": scoring_source,
                "deltaFromRaw": int(scoring - raw),
            },
            "scarcity": {
                "value": scarcity,
                "source": scarcity_source,
                "deltaFromRaw": int(scarcity - raw),
            },
            "bestBall": {
                "value": best_ball,
                "source": best_ball_source,
                "deltaFromRaw": int(best_ball - raw),
                "deltaFromScarcity": int(best_ball - scarcity),
                "deltaPctFromScarcity": round((best_ball - scarcity) / max(1, scarcity), 6),
                "multiplierRaw": (
                    best_ball_detail.get("multiplierRaw")
                    if isinstance(best_ball_detail, dict)
                    else None
                ),
                "multiplierEffective": (
                    best_ball_detail.get("multiplierEffective")
                    if isinstance(best_ball_detail, dict)
                    else None
                ),
                "metrics": (
                    best_ball_detail.get("metrics")
                    if isinstance(best_ball_detail, dict)
                    else {}
                ),
                "guards": (
                    best_ball_detail.get("guards")
                    if isinstance(best_ball_detail, dict)
                    else {}
                ),
            },
            "full": {
                "value": full,
                "source": full_layer_source,
                "baseSource": base_full_source,
                "deltaFromRaw": (int(full - raw) if full is not None else None),
                "fullValueBeforeGuardrails": full_before_guardrails,
            },
            "offseasonClay": clay_layer,
        },
        "resolver": {
            "authority": "backend",
            "resolverVersion": CONTRACT_VERSION,
            "assetRef": str(name or "").strip(),
        },
    }


def _apply_bundle_compatibility_fields(
    p_data: dict[str, Any],
    value_bundle: dict[str, Any],
    *,
    source_count: int,
) -> None:
    if not isinstance(p_data, dict):
        return
    values = _legacy_values_from_bundle(value_bundle)
    guardrails = value_bundle.get("guardrails")
    guardrails = guardrails if isinstance(guardrails, dict) else {}
    final_status = str(guardrails.get("finalAuthorityStatus") or "")
    quarantined = bool(guardrails.get("quarantined"))

    p_data["valueBundle"] = deepcopy(value_bundle)
    p_data["_rawComposite"] = values.get("rawComposite")
    p_data["_rawMarketValue"] = values.get("rawComposite")
    p_data["_scoringAdjusted"] = values.get("scoringAdjusted")
    p_data["_scarcityAdjusted"] = values.get("scarcityAdjusted")
    p_data["_bestBallAdjusted"] = values.get("bestBallAdjusted")
    p_data["_finalAdjusted"] = (
        values.get("finalAdjusted")
        if final_status == "final_adjusted_authoritative" and not quarantined
        else None
    )
    p_data["_leagueAdjusted"] = (
        None
        if quarantined
        else (
            values.get("finalAdjusted")
            if final_status == "final_adjusted_authoritative"
            else values.get("scoringAdjusted")
        )
    )
    p_data["_marketReliabilityScore"] = value_bundle.get("confidence")
    p_data["_marketConfidence"] = value_bundle.get("confidence")
    p_data["_sourceCoverageRatio"] = value_bundle.get("sourceCoverageRatio")
    p_data["_sites"] = int(max(0, source_count))
    p_data["_adjustmentTags"] = list(value_bundle.get("adjustmentTags") or [])
    p_data["_valueAuthorityGuardrails"] = deepcopy(guardrails)
    p_data["_valueResolver"] = {
        "authority": "backend",
        "resolverVersion": CONTRACT_VERSION,
    }


def _derive_player_row(
    name: str,
    p_data: dict[str, Any],
    pos_map: dict[str, Any],
    site_keys: list[str],
    clay_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    canonical_name = str(name or "").strip()
    canonical_norm = normalize_player_name(canonical_name)
    pos = _normalize_pos(
        pos_map.get(canonical_name)
        or pos_map.get(canonical_norm)
        or p_data.get("position")
    )
    is_pick = _is_pick_name(canonical_name)
    if is_pick:
        pos = PICK_POSITION

    canonical_sites = _canonical_site_values(p_data, site_keys)
    if not pos and not is_pick:
        hinted_pos = _normalize_pos(
            p_data.get("_positionHint")
            or p_data.get("_mustHaveRookiePos")
            or p_data.get("_lamBucket")
        )
        if hinted_pos:
            pos = hinted_pos

    if not pos and not is_pick:
        has_idp_signal = any(
            (_to_int_or_none(canonical_sites.get(key)) or 0) > 0
            for key in IDP_SIGNAL_SITE_KEYS
        )
        has_offense_signal = any(
            (_to_int_or_none(canonical_sites.get(key)) or 0) > 0
            for key in OFFENSE_MARKET_SITE_KEYS
        )
        is_idp_asset_hint = str(p_data.get("_assetClass") or "").strip().lower() == "idp"
        if has_idp_signal and (is_idp_asset_hint or not has_offense_signal):
            # Conservative fallback to keep IDP-signal assets out of blank-position quarantine.
            pos = "LB"

    source_count = _source_count(p_data, canonical_sites)
    value_bundle = _authoritative_value_bundle(
        name=canonical_name,
        p_data=p_data,
        pos=pos or "",
        source_count=source_count,
        canonical_sites=canonical_sites,
        site_keys=site_keys,
        clay_runtime=clay_runtime,
    )
    values = _legacy_values_from_bundle(value_bundle)

    # Maintain legacy map fields consumed by older runtime modules while making
    # valueBundle the backend-authoritative source of truth.
    _apply_bundle_compatibility_fields(
        p_data,
        value_bundle,
        source_count=source_count,
    )

    return {
        "playerId": str(p_data.get("_sleeperId") or "").strip() or None,
        "canonicalName": canonical_name,
        "displayName": canonical_name,
        "position": pos or None,
        "team": p_data.get("team") if isinstance(p_data.get("team"), str) else None,
        "rookie": bool(p_data.get("_formatFitRookie", False)),
        "assetClass": "pick" if is_pick else ("idp" if pos in IDP_POSITIONS else "offense"),
        "values": values,
        "valueBundle": value_bundle,
        "valueGuardrails": value_bundle.get("guardrails"),
        "quarantinedFromFinalAuthority": bool(
            (value_bundle.get("guardrails") or {}).get("quarantined")
            if isinstance(value_bundle.get("guardrails"), dict)
            else False
        ),
        "rawValue": values.get("rawComposite"),
        "scoringAdjustedValue": values.get("scoringAdjusted"),
        "scarcityAdjustedValue": values.get("scarcityAdjusted"),
        "bestBallAdjustedValue": values.get("bestBallAdjusted"),
        "fullValue": values.get("finalAdjusted"),
        "confidence": value_bundle.get("confidence"),
        "sourceCoverage": value_bundle.get("sourceCoverage"),
        "adjustmentTags": list(value_bundle.get("adjustmentTags") or []),
        "canonicalSiteValues": canonical_sites,
        "sourceCount": source_count,
        "sourcePresence": {k: (v is not None and v > 0) for k, v in canonical_sites.items()},
        "marketConfidence": value_bundle.get("confidence"),
        "marketDispersionCV": _safe_num(p_data.get("_marketDispersionCV")),
        "legacyRef": canonical_name,
    }


def _build_value_authority_summary(
    players_array: list[dict[str, Any]],
    *,
    clay_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(players_array or [])
    raw_present = 0
    scoring_present = 0
    scarcity_present = 0
    best_ball_present = 0
    final_present = 0
    confidence_present = 0
    source_coverage_present = 0
    fallback_layer_assets = 0
    canonical_map_present = 0
    canonical_points = 0
    full_derived_without_final = 0
    final_quarantined_assets = 0
    final_capped_assets = 0

    for row in players_array or []:
        if not isinstance(row, dict):
            continue
        bundle = row.get("valueBundle")
        if isinstance(bundle, dict):
            raw_v = _normalize_value_int(bundle.get("rawValue"))
            scoring_v = _normalize_value_int(bundle.get("scoringAdjustedValue"))
            scarcity_v = _normalize_value_int(bundle.get("scarcityAdjustedValue"))
            best_ball_v = _normalize_value_int(bundle.get("bestBallAdjustedValue"))
            final_v = _normalize_value_int(bundle.get("fullValue"))

            if raw_v is not None:
                raw_present += 1
            if scoring_v is not None:
                scoring_present += 1
            if scarcity_v is not None:
                scarcity_present += 1
            if best_ball_v is not None:
                best_ball_present += 1
            if final_v is not None:
                final_present += 1

            confidence_v = _safe_num(bundle.get("confidence"))
            if confidence_v is not None:
                confidence_present += 1

            source_cov = bundle.get("sourceCoverage")
            if isinstance(source_cov, dict):
                ratio = _safe_num(source_cov.get("ratio"))
                if ratio is not None:
                    source_coverage_present += 1

            layer_sources = bundle.get("layers")
            if isinstance(layer_sources, dict):
                layer_used_fallback = False
                for layer_data in layer_sources.values():
                    if not isinstance(layer_data, dict):
                        continue
                    source_name = str(layer_data.get("source") or "")
                    if (
                        source_name.startswith("fallback_")
                        or source_name.startswith("derived_")
                        or source_name.startswith("quarantined_")
                        or source_name.endswith("_passthrough")
                    ):
                        layer_used_fallback = True
                        break
                if layer_used_fallback:
                    fallback_layer_assets += 1

            guardrails = bundle.get("guardrails")
            if isinstance(guardrails, dict):
                status = str(guardrails.get("finalAuthorityStatus") or "")
                if status == "derived_without_final_adjusted":
                    full_derived_without_final += 1
                elif status == "quarantined":
                    final_quarantined_assets += 1
                if bool(guardrails.get("capped")):
                    final_capped_assets += 1

        canonical_sites = row.get("canonicalSiteValues")
        if isinstance(canonical_sites, dict):
            non_null = 0
            for val in canonical_sites.values():
                n = _to_int_or_none(val)
                if n is not None and n > 0:
                    non_null += 1
            if non_null > 0:
                canonical_map_present += 1
                canonical_points += non_null

    clay_runtime = clay_runtime or {}
    return {
        "mode": "backend_authoritative_value_bundle",
        "fallbackPolicy": "frontend_recompute_only_for_manual_or_missing_assets",
        "offseasonClay": {
            "enabled": bool(clay_runtime.get("enabled")),
            "active": bool(clay_runtime.get("active")),
            "importDataReady": bool(clay_runtime.get("importDataReady")),
            "datasetLoaded": bool(clay_runtime.get("datasetLoaded")),
            "seasonPhase": str(clay_runtime.get("seasonPhase") or ""),
            "weight": float(clay_runtime.get("phaseWeight") or 0.0),
            "seasonalGatingActive": bool(clay_runtime.get("seasonalGatingActive")),
            "seasonalGatingConfigured": bool(clay_runtime.get("seasonalGatingConfigured")),
            "seasonalGatingReason": str(clay_runtime.get("seasonalGatingReason") or ""),
            "seasonalGatingErrors": list(clay_runtime.get("seasonalGatingErrors") or []),
            "configPath": str(clay_runtime.get("configPath") or ""),
            "guideYear": clay_runtime.get("guideYear"),
            "guideVersion": clay_runtime.get("guideVersion"),
            "importTimestamp": clay_runtime.get("importTimestamp"),
            "runId": clay_runtime.get("runId"),
            "unresolvedCount": int(clay_runtime.get("unresolvedCount") or 0),
            "ambiguousCount": int(clay_runtime.get("ambiguousCount") or 0),
            "lowConfidenceCount": int(clay_runtime.get("lowConfidenceCount") or 0),
            "readyForFormulaIntegration": bool(clay_runtime.get("readyForFormulaIntegration")),
            "readinessReasons": list(clay_runtime.get("readinessReasons") or []),
            "cutoverWindow": clay_runtime.get("cutoverWindow"),
            "lastValidationRun": clay_runtime.get("lastValidationRun"),
        },
        "coverage": {
            "playersTotal": total,
            "rawValuePresent": raw_present,
            "scoringAdjustedPresent": scoring_present,
            "scarcityAdjustedPresent": scarcity_present,
            "bestBallAdjustedPresent": best_ball_present,
            "fullValuePresent": final_present,
            "confidencePresent": confidence_present,
            "sourceCoveragePresent": source_coverage_present,
            "fallbackLayerAssets": fallback_layer_assets,
            "fullDerivedWithoutFinalAdjusted": full_derived_without_final,
            "finalQuarantinedAssets": final_quarantined_assets,
            "finalCappedAssets": final_capped_assets,
            "canonicalSiteMapPresent": canonical_map_present,
            "canonicalSiteValuePoints": canonical_points,
        },
    }


def _build_value_resolver_diagnostics(
    players_array: list[dict[str, Any]],
    *,
    clay_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback_counts: dict[str, int] = {
        "scoringFallback": 0,
        "scarcityFallback": 0,
        "bestBallPassthrough": 0,
        "fullFallback": 0,
    }
    low_confidence_assets = 0
    single_source_assets = 0
    quarantined_assets = 0
    capped_assets = 0
    fallback_samples: list[dict[str, Any]] = []
    guardrail_samples: list[dict[str, Any]] = []
    best_ball_rows: list[dict[str, Any]] = []
    clay_rows: list[dict[str, Any]] = []

    for row in players_array or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("canonicalName") or "")
        bundle = row.get("valueBundle")
        if not isinstance(bundle, dict):
            continue

        layers = bundle.get("layers")
        if isinstance(layers, dict):
            scoring_src = str((layers.get("scoring") or {}).get("source") or "")
            scarcity_src = str((layers.get("scarcity") or {}).get("source") or "")
            best_ball_src = str((layers.get("bestBall") or {}).get("source") or "")
            full_src = str((layers.get("full") or {}).get("source") or "")
            full_non_authoritative = (
                full_src.startswith("fallback_")
                or full_src.startswith("derived_")
                or full_src.startswith("quarantined_")
            )

            if scoring_src.startswith("fallback_"):
                fallback_counts["scoringFallback"] += 1
            if scarcity_src.startswith("fallback_"):
                fallback_counts["scarcityFallback"] += 1
            if best_ball_src.endswith("_passthrough"):
                fallback_counts["bestBallPassthrough"] += 1
            if full_non_authoritative:
                fallback_counts["fullFallback"] += 1

            if len(fallback_samples) < 120 and (
                scoring_src.startswith("fallback_")
                or scarcity_src.startswith("fallback_")
                or best_ball_src.endswith("_passthrough")
                or full_non_authoritative
            ):
                fallback_samples.append(
                    {
                        "asset": name,
                        "assetClass": row.get("assetClass"),
                        "scoringSource": scoring_src,
                        "scarcitySource": scarcity_src,
                        "bestBallSource": best_ball_src,
                        "fullSource": full_src,
                    }
                )

            best_ball_layer = layers.get("bestBall")
            if isinstance(best_ball_layer, dict):
                scarcity_layer = layers.get("scarcity")
                bb_val = _normalize_value_int(best_ball_layer.get("value"))
                scarcity_val = _normalize_value_int(
                    (scarcity_layer or {}).get("value")
                    if isinstance(scarcity_layer, dict)
                    else bundle.get("scarcityAdjustedValue")
                )
                if bb_val is None:
                    bb_val = _normalize_value_int(bundle.get("bestBallAdjustedValue"))
                if scarcity_val is None:
                    scarcity_val = _normalize_value_int(bundle.get("scarcityAdjustedValue"))

                if bb_val is not None and scarcity_val is not None:
                    bb_delta = int(bb_val - scarcity_val)
                    bb_delta_pct = bb_delta / max(1, scarcity_val)
                    bb_metrics = best_ball_layer.get("metrics")
                    if not isinstance(bb_metrics, dict):
                        bb_metrics = {}
                    spike = _safe_num(bb_metrics.get("spikeWeekFrequency")) or 0.0
                    depth = _safe_num(bb_metrics.get("depthUtility")) or 0.0
                    contingent = _safe_num(bb_metrics.get("contingentUpside")) or 0.0
                    confidence = _safe_num(bundle.get("confidence")) or 0.0
                    source_cov = bundle.get("sourceCoverage")
                    source_cov_count = 0
                    source_cov_ratio = None
                    if isinstance(source_cov, dict):
                        source_cov_count = int(source_cov.get("count") or 0)
                        source_cov_ratio = _safe_num(source_cov.get("ratio"))
                    best_ball_rows.append(
                        {
                            "asset": name,
                            "position": row.get("position"),
                            "assetClass": row.get("assetClass"),
                            "scarcityValue": scarcity_val,
                            "bestBallValue": bb_val,
                            "bestBallDelta": bb_delta,
                            "bestBallDeltaPct": round(bb_delta_pct, 6),
                            "bestBallSource": str(best_ball_layer.get("source") or ""),
                            "confidence": round(confidence, 4),
                            "sourceCoverageCount": int(max(0, source_cov_count)),
                            "sourceCoverageRatio": (
                                round(source_cov_ratio, 4)
                                if source_cov_ratio is not None
                                else None
                            ),
                            "spikeWeekFrequency": round(spike, 4),
                            "depthUtility": round(depth, 4),
                            "contingentUpside": round(contingent, 4),
                        }
                    )

            clay_layer = layers.get("offseasonClay")
            if isinstance(clay_layer, dict):
                base_val = _normalize_value_int(clay_layer.get("baseValue"))
                clay_val = _normalize_value_int(clay_layer.get("value"))
                if base_val is None:
                    base_val = _normalize_value_int(bundle.get("fullValue"))
                if clay_val is None:
                    clay_val = _normalize_value_int(bundle.get("fullValue"))
                if base_val is not None and clay_val is not None:
                    delta = int(clay_val - base_val)
                    delta_pct = delta / max(1, base_val)
                    signals = clay_layer.get("signals")
                    if not isinstance(signals, dict):
                        signals = {}
                    clay_rows.append(
                        {
                            "asset": name,
                            "position": row.get("position"),
                            "assetClass": row.get("assetClass"),
                            "baseValue": base_val,
                            "clayValue": clay_val,
                            "delta": delta,
                            "deltaPct": round(delta_pct, 6),
                            "seasonPhase": str(clay_layer.get("seasonPhase") or ""),
                            "weightUsed": _safe_num(clay_layer.get("weightUsed")) or 0.0,
                            "source": str(clay_layer.get("source") or ""),
                            "applied": bool(clay_layer.get("applied")),
                            "excludedReason": str(clay_layer.get("excludedReason") or ""),
                            "supportTier": str(clay_layer.get("supportTier") or ""),
                            "projectedProductionScore": _safe_num(signals.get("projectedProductionScore")) or 0.0,
                            "workloadOpportunityScore": _safe_num(signals.get("workloadOpportunityScore")) or 0.0,
                            "durabilityGamesScore": _safe_num(signals.get("durabilityGamesScore")) or 0.0,
                            "touchdownExpectationScore": _safe_num(signals.get("touchdownExpectationScore")) or 0.0,
                            "teamEnvironmentScore": _safe_num(signals.get("teamEnvironmentScore")) or 0.0,
                            "scheduleScore": _safe_num(signals.get("scheduleScore")) or 0.0,
                            "roleCertaintyScore": _safe_num(signals.get("roleCertaintyScore")) or 0.0,
                            "starterConfidenceScore": _safe_num(signals.get("starterConfidenceScore")) or 0.0,
                            "idpProductionScore": _safe_num(signals.get("idpProductionScore")) or 0.0,
                            "idpOpportunityScore": _safe_num(signals.get("idpOpportunityScore")) or 0.0,
                            "overallSignal": _safe_num(signals.get("overallSignal")) or 0.0,
                        }
                    )

        guardrails = bundle.get("guardrails")
        if isinstance(guardrails, dict):
            quarantined = bool(guardrails.get("quarantined"))
            capped = bool(guardrails.get("capped"))
            if quarantined:
                quarantined_assets += 1
            if capped:
                capped_assets += 1
            if len(guardrail_samples) < 120 and (quarantined or capped):
                guardrail_samples.append(
                    {
                        "asset": name,
                        "assetClass": row.get("assetClass"),
                        "position": row.get("position"),
                        "status": str(guardrails.get("finalAuthorityStatus") or ""),
                        "quarantined": quarantined,
                        "quarantineReasons": list(guardrails.get("quarantineReasons") or []),
                        "capped": capped,
                        "capReasons": list(guardrails.get("capReasons") or []),
                        "fullEffectiveSource": str(guardrails.get("fullEffectiveSource") or ""),
                    }
                )

        confidence = _safe_num(bundle.get("confidence"))
        if confidence is not None and confidence < 0.50:
            low_confidence_assets += 1

        source_cov = bundle.get("sourceCoverage")
        if isinstance(source_cov, dict):
            if int(source_cov.get("count") or 0) <= 1:
                single_source_assets += 1

    best_ball_rows.sort(
        key=lambda r: (
            float(r.get("bestBallDelta") or 0),
            float(r.get("bestBallDeltaPct") or 0),
            str(r.get("asset") or ""),
        ),
        reverse=True,
    )
    bb_risers = [r for r in best_ball_rows if float(r.get("bestBallDelta") or 0) > 0][:40]
    bb_fallers = sorted(
        [r for r in best_ball_rows if float(r.get("bestBallDelta") or 0) < 0],
        key=lambda r: (
            float(r.get("bestBallDelta") or 0),
            float(r.get("bestBallDeltaPct") or 0),
            str(r.get("asset") or ""),
        ),
    )[:40]
    spike_winners = sorted(
        [r for r in best_ball_rows if float(r.get("bestBallDelta") or 0) > 0],
        key=lambda r: (
            float(r.get("spikeWeekFrequency") or 0),
            float(r.get("bestBallDeltaPct") or 0),
            float(r.get("bestBallDelta") or 0),
        ),
        reverse=True,
    )[:40]
    depth_winners = sorted(
        [r for r in best_ball_rows if float(r.get("bestBallDelta") or 0) > 0],
        key=lambda r: (
            float(r.get("depthUtility") or 0),
            float(r.get("bestBallDeltaPct") or 0),
            float(r.get("bestBallDelta") or 0),
        ),
        reverse=True,
    )[:40]
    suspicious_extremes = []
    for r in best_ball_rows:
        delta_pct = abs(float(r.get("bestBallDeltaPct") or 0))
        delta_abs = abs(float(r.get("bestBallDelta") or 0))
        conf = float(r.get("confidence") or 0)
        cov = int(r.get("sourceCoverageCount") or 0)
        source_name = str(r.get("bestBallSource") or "")
        looks_extreme = delta_pct >= 0.085 or delta_abs >= 700
        low_trust = conf < 0.50 or cov <= 1
        if not looks_extreme:
            continue
        reasons: list[str] = []
        if delta_pct >= 0.085:
            reasons.append("delta_pct_ge_8_5")
        if delta_abs >= 700:
            reasons.append("delta_abs_ge_700")
        if low_trust:
            reasons.append("low_trust_signal")
        if source_name.endswith("passthrough") or source_name.endswith("neutral"):
            reasons.append("non_model_source")
        suspicious_extremes.append({**r, "reasons": reasons})
    suspicious_extremes = sorted(
        suspicious_extremes,
        key=lambda r: (
            abs(float(r.get("bestBallDeltaPct") or 0)),
            abs(float(r.get("bestBallDelta") or 0)),
        ),
        reverse=True,
    )[:60]

    clay_runtime = clay_runtime or {}
    clay_before_top50 = sorted(
        clay_rows,
        key=lambda r: (
            float(r.get("baseValue") or 0),
            str(r.get("asset") or ""),
        ),
        reverse=True,
    )[:50]
    clay_after_top50 = sorted(
        clay_rows,
        key=lambda r: (
            float(r.get("clayValue") or 0),
            str(r.get("asset") or ""),
        ),
        reverse=True,
    )[:50]
    clay_effective = [
        r
        for r in clay_rows
        if str(r.get("source") or "").startswith("offseason_clay_overlay")
    ]
    clay_risers = [r for r in sorted(clay_effective, key=lambda r: float(r.get("delta") or 0), reverse=True) if float(r.get("delta") or 0) > 0][:50]
    clay_fallers = [r for r in sorted(clay_effective, key=lambda r: float(r.get("delta") or 0)) if float(r.get("delta") or 0) < 0][:50]
    clay_disagreement = sorted(
        [r for r in clay_effective if abs(float(r.get("deltaPct") or 0.0)) > 0.0001],
        key=lambda r: (
            abs(float(r.get("deltaPct") or 0)),
            abs(float(r.get("delta") or 0)),
        ),
        reverse=True,
    )[:50]
    clay_offense_impact = sorted(
        [r for r in clay_effective if str(r.get("assetClass") or "") == "offense"],
        key=lambda r: abs(float(r.get("delta") or 0)),
        reverse=True,
    )[:50]
    clay_idp_impact = sorted(
        [r for r in clay_effective if str(r.get("assetClass") or "") == "idp"],
        key=lambda r: abs(float(r.get("delta") or 0)),
        reverse=True,
    )[:50]
    clay_strong_support_weak_current = sorted(
        [
            r
            for r in clay_effective
            if float(r.get("overallSignal") or 0.0) >= 0.70
            and float(r.get("baseValue") or 0.0) <= 4500
        ],
        key=lambda r: (
            float(r.get("overallSignal") or 0.0),
            float(r.get("delta") or 0.0),
        ),
        reverse=True,
    )[:40]
    clay_strong_current_weak_support = sorted(
        [
            r
            for r in clay_effective
            if float(r.get("baseValue") or 0.0) >= 7000
            and float(r.get("overallSignal") or 0.0) <= 0.40
        ],
        key=lambda r: (
            float(r.get("overallSignal") or 0.0),
            float(r.get("delta") or 0.0),
        ),
    )[:40]
    clay_games_role_penalties = sorted(
        [
            r
            for r in clay_effective
            if float(r.get("delta") or 0.0) < 0.0
            and (
                float(r.get("durabilityGamesScore") or 0.0) < 0.50
                or float(r.get("roleCertaintyScore") or 0.0) < 0.75
            )
        ],
        key=lambda r: (
            float(r.get("delta") or 0.0),
            float(r.get("durabilityGamesScore") or 1.0),
            float(r.get("roleCertaintyScore") or 1.0),
        ),
    )[:50]
    clay_excluded = [r for r in clay_rows if str(r.get("excludedReason") or "").strip()][:80]
    clay_top_impact_summary = {
        "topRiser": clay_risers[0] if clay_risers else None,
        "topFaller": clay_fallers[0] if clay_fallers else None,
        "largestAbsMove": clay_disagreement[0] if clay_disagreement else None,
    }

    return {
        "resolverVersion": CONTRACT_VERSION,
        "generatedAt": utc_now_iso(),
        "fallbackCounts": fallback_counts,
        "lowConfidenceAssets": low_confidence_assets,
        "singleSourceAssets": single_source_assets,
        "quarantinedAssets": quarantined_assets,
        "cappedAssets": capped_assets,
        "fallbackSamples": fallback_samples[:80],
        "guardrailSamples": guardrail_samples[:80],
        "bestBallDiagnostics": {
            "assetsAnalyzed": len(best_ball_rows),
            "biggestBestBallOnlyRisers": bb_risers,
            "biggestBestBallOnlyFallers": bb_fallers,
            "spikeWeekWinners": spike_winners,
            "depthUtilityWinners": depth_winners,
            "suspiciousExtremeBestBallMovers": suspicious_extremes,
        },
        "offseasonClayDiagnostics": {
            "enabled": bool(clay_runtime.get("enabled")),
            "active": bool(clay_runtime.get("active")),
            "importDataReady": bool(clay_runtime.get("importDataReady")),
            "datasetLoaded": bool(clay_runtime.get("datasetLoaded")),
            "seasonPhase": str(clay_runtime.get("seasonPhase") or ""),
            "weight": float(clay_runtime.get("phaseWeight") or 0.0),
            "seasonalGatingActive": bool(clay_runtime.get("seasonalGatingActive")),
            "seasonalGatingConfigured": bool(clay_runtime.get("seasonalGatingConfigured")),
            "seasonalGatingReason": str(clay_runtime.get("seasonalGatingReason") or ""),
            "seasonalGatingErrors": list(clay_runtime.get("seasonalGatingErrors") or []),
            "configPath": str(clay_runtime.get("configPath") or ""),
            "guideYear": clay_runtime.get("guideYear"),
            "guideVersion": clay_runtime.get("guideVersion"),
            "importTimestamp": clay_runtime.get("importTimestamp"),
            "unresolvedCount": int(clay_runtime.get("unresolvedCount") or 0),
            "ambiguousCount": int(clay_runtime.get("ambiguousCount") or 0),
            "lowConfidenceCount": int(clay_runtime.get("lowConfidenceCount") or 0),
            "lastValidationRun": clay_runtime.get("lastValidationRun"),
            "assetsAnalyzed": len(clay_rows),
            "top50BeforeClay": clay_before_top50,
            "top50AfterClay": clay_after_top50,
            "topRisers": clay_risers,
            "topFallers": clay_fallers,
            "biggestDisagreementCases": clay_disagreement,
            "biggestOffensiveImpactCases": clay_offense_impact,
            "biggestIDPImpactCases": clay_idp_impact,
            "strongClaySupportWeakCurrentValue": clay_strong_support_weak_current,
            "strongCurrentValueWeakClaySupport": clay_strong_current_weak_support,
            "gamesRolePenaltyCases": clay_games_role_penalties,
            "excludedOrUnresolvedSignals": {
                "excludedPlayerRows": clay_excluded,
                "importSummaryUnresolvedCount": int(clay_runtime.get("unresolvedCount") or 0),
                "importSummaryAmbiguousCount": int(clay_runtime.get("ambiguousCount") or 0),
            },
            "topImpactSummary": clay_top_impact_summary,
        },
    }


def build_api_data_contract(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = deepcopy(raw_payload or {})
    players_by_name = base.get("players")
    if not isinstance(players_by_name, dict):
        players_by_name = {}
        base["players"] = players_by_name

    sites = base.get("sites")
    if not isinstance(sites, list):
        sites = []
        base["sites"] = sites

    max_values = base.get("maxValues")
    if not isinstance(max_values, dict):
        max_values = {}
        base["maxValues"] = max_values

    sleeper = base.get("sleeper")
    if not isinstance(sleeper, dict):
        sleeper = {}
        base["sleeper"] = sleeper

    pos_map = sleeper.get("positions")
    if not isinstance(pos_map, dict):
        pos_map = {}
        sleeper["positions"] = pos_map

    site_keys = [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]
    clay_runtime = get_mike_clay_runtime_context()
    players_array: list[dict[str, Any]] = []
    for name in sorted(players_by_name.keys(), key=lambda x: str(x).lower()):
        p_data = players_by_name.get(name)
        if not isinstance(p_data, dict):
            continue
        players_array.append(_derive_player_row(str(name), p_data, pos_map, site_keys, clay_runtime))

    data_source = data_source or {}
    contract_payload: dict[str, Any] = {
        **base,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": utc_now_iso(),
        "playersArray": players_array,
        "playerCount": len(players_array),
        "runtimeAuthority": {
            "decision": "de_scope_src_pipeline_until_live",
            "authoritativePath": "Dynasty Scraper.py -> src.api.data_contract -> /api/data",
            "scaffoldPipelineAuthoritative": False,
            "scaffoldEndpointPrefix": "/api/scaffold",
        },
        "valueAuthority": _build_value_authority_summary(players_array, clay_runtime=clay_runtime),
        "valueResolverDiagnostics": _build_value_resolver_diagnostics(players_array, clay_runtime=clay_runtime),
        "offseasonClayStatus": {
            "enabled": bool(clay_runtime.get("enabled")),
            "active": bool(clay_runtime.get("active")),
            "importDataReady": bool(clay_runtime.get("importDataReady")),
            "datasetLoaded": bool(clay_runtime.get("datasetLoaded")),
            "seasonPhase": str(clay_runtime.get("seasonPhase") or ""),
            "weight": float(clay_runtime.get("phaseWeight") or 0.0),
            "seasonalGatingActive": bool(clay_runtime.get("seasonalGatingActive")),
            "seasonalGatingConfigured": bool(clay_runtime.get("seasonalGatingConfigured")),
            "seasonalGatingReason": str(clay_runtime.get("seasonalGatingReason") or ""),
            "seasonalGatingErrors": list(clay_runtime.get("seasonalGatingErrors") or []),
            "configPath": str(clay_runtime.get("configPath") or ""),
            "guideYear": clay_runtime.get("guideYear"),
            "guideVersion": clay_runtime.get("guideVersion"),
            "importTimestamp": clay_runtime.get("importTimestamp"),
            "runId": clay_runtime.get("runId"),
            "unresolvedCount": int(clay_runtime.get("unresolvedCount") or 0),
            "lowConfidenceCount": int(clay_runtime.get("lowConfidenceCount") or 0),
            "lastValidationRun": clay_runtime.get("lastValidationRun"),
            "cutoverWindow": clay_runtime.get("cutoverWindow"),
            "readyForFormulaIntegration": bool(clay_runtime.get("readyForFormulaIntegration")),
            "readinessReasons": list(clay_runtime.get("readinessReasons") or []),
        },
        "dataSource": {
            "type": str(data_source.get("type") or ""),
            "path": str(data_source.get("path") or ""),
            "loadedAt": str(data_source.get("loadedAt") or ""),
        },
    }
    return contract_payload


def _strip_startup_player_fields(player_row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (player_row or {}).items():
        key_s = str(key)
        if key_s in STARTUP_HEAVY_PLAYER_FIELDS:
            continue
        if any(key_s.startswith(prefix) for prefix in STARTUP_HEAVY_PLAYER_FIELD_PREFIXES):
            continue
        out[key_s] = value
    return out


def build_api_startup_payload(contract_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Build a startup-slim payload for first paint / early interaction.

    Keeps the same top-level contract shape expected by the live Static app,
    but strips heavyweight per-player debug fields and non-critical secondary
    top-level blobs so startup transfer/parse cost is lower.
    """
    base = deepcopy(contract_payload or {})

    for key in STARTUP_DROP_TOP_LEVEL_KEYS:
        base.pop(key, None)

    players_map = base.get("players")
    if isinstance(players_map, dict):
        slim_players: dict[str, Any] = {}
        for name, pdata in players_map.items():
            if isinstance(pdata, dict):
                slim_players[str(name)] = _strip_startup_player_fields(pdata)
            else:
                slim_players[str(name)] = pdata
        base["players"] = slim_players

    base["payloadView"] = "startup"
    return base


def validate_api_data_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": "invalid",
            "errors": ["payload is not an object"],
            "warnings": [],
            "errorCount": 1,
            "warningCount": 0,
            "checkedAt": utc_now_iso(),
            "contractVersion": CONTRACT_VERSION,
            "playerCount": 0,
        }

    for key in sorted(REQUIRED_TOP_LEVEL_KEYS):
        if key not in payload:
            errors.append(f"missing top-level key: {key}")

    runtime_authority = payload.get("runtimeAuthority")
    if not isinstance(runtime_authority, dict):
        errors.append("runtimeAuthority must be an object")

    value_authority = payload.get("valueAuthority")
    if not isinstance(value_authority, dict):
        errors.append("valueAuthority must be an object")
    else:
        coverage = value_authority.get("coverage")
        if not isinstance(coverage, dict):
            errors.append("valueAuthority.coverage must be an object")

    value_diag = payload.get("valueResolverDiagnostics")
    if not isinstance(value_diag, dict):
        errors.append("valueResolverDiagnostics must be an object")

    players_map = payload.get("players")
    if not isinstance(players_map, dict):
        errors.append("players must be an object map")

    players_array = payload.get("playersArray")
    if not isinstance(players_array, list):
        errors.append("playersArray must be a list")
        players_array = []

    sites = payload.get("sites")
    if not isinstance(sites, list):
        errors.append("sites must be a list")
        sites = []

    site_keys = [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]

    for idx, row in enumerate(players_array[:1000]):
        if not isinstance(row, dict):
            errors.append(f"playersArray[{idx}] must be object")
            continue
        for key in REQUIRED_PLAYER_KEYS:
            if key not in row:
                errors.append(f"playersArray[{idx}] missing key: {key}")

        values = row.get("values")
        if not isinstance(values, dict):
            errors.append(f"playersArray[{idx}].values must be object")
        else:
            for k in ("overall", "rawComposite", "scoringAdjusted", "scarcityAdjusted", "bestBallAdjusted", "finalAdjusted"):
                if k not in values:
                    errors.append(f"playersArray[{idx}].values missing key: {k}")

        value_bundle = row.get("valueBundle")
        if not isinstance(value_bundle, dict):
            errors.append(f"playersArray[{idx}].valueBundle must be object")
        else:
            for k in REQUIRED_VALUE_BUNDLE_KEYS:
                if k not in value_bundle:
                    errors.append(f"playersArray[{idx}].valueBundle missing key: {k}")
            conf = _safe_num(value_bundle.get("confidence"))
            if conf is None:
                errors.append(f"playersArray[{idx}].valueBundle.confidence must be numeric")
            elif conf < 0 or conf > 1:
                warnings.append(f"playersArray[{idx}].valueBundle.confidence outside [0,1]")
            source_cov = value_bundle.get("sourceCoverage")
            if not isinstance(source_cov, dict):
                errors.append(f"playersArray[{idx}].valueBundle.sourceCoverage must be object")
            tags = value_bundle.get("adjustmentTags")
            if not isinstance(tags, list):
                errors.append(f"playersArray[{idx}].valueBundle.adjustmentTags must be list")

        canonical_sites = row.get("canonicalSiteValues")
        if not isinstance(canonical_sites, dict):
            errors.append(f"playersArray[{idx}].canonicalSiteValues must be object")
        elif site_keys:
            missing_keys = [k for k in site_keys if k not in canonical_sites]
            if missing_keys:
                warnings.append(
                    f"playersArray[{idx}] canonicalSiteValues missing keys: {', '.join(missing_keys[:6])}"
                )

    if not players_array:
        warnings.append("playersArray is empty")
    if not site_keys:
        warnings.append("sites is empty or missing keys")

    if isinstance(players_map, dict):
        for idx, (name, p_data) in enumerate(players_map.items()):
            if idx >= 1000:
                break
            if not isinstance(p_data, dict):
                continue
            bundle = p_data.get("valueBundle")
            if not isinstance(bundle, dict):
                errors.append(f"players[{name}] missing valueBundle")
                continue
            for k in ("rawValue", "fullValue", "confidence", "sourceCoverage"):
                if k not in bundle:
                    errors.append(f"players[{name}].valueBundle missing key: {k}")

    ok = len(errors) == 0
    status = "healthy" if ok else "invalid"
    return {
        "ok": ok,
        "status": status,
        "errors": errors[:200],
        "warnings": warnings[:200],
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "checkedAt": utc_now_iso(),
        "contractVersion": str(payload.get("contractVersion") or CONTRACT_VERSION),
        "playerCount": len(players_array),
    }
