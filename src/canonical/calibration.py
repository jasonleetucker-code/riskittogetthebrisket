"""Post-blend calibration layer for canonical values.

The raw canonical pipeline uses a percentile power curve (9999 * p^0.65)
which produces a top-heavy distribution compared to legacy Z-score values.
This calibration step remaps canonical values to a distribution that better
matches the legacy system's value range and tier boundaries.

Calibration is universe-aware:
- offense_vet/offense_rookie: calibrated to 8500 max (matching legacy offense)
- idp_vet/idp_rookie: calibrated to 5000 max (legacy IDP caps ~4900)
- Picks: calibrated using legacy pick value curve (direct name match or
  round-based median fallback), replacing the generic power curve

The calibration parameters are empirically chosen to maximize tier
agreement with the legacy system based on comparison batch data.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any


# Default calibration parameters
# Piecewise power curve chosen via empirical sweep (calibration_sweep.py):
#   - Above the knee (percentile >= KNEE): standard power curve scale * p^exp
#   - Below the knee: linear ramp from 0 to the curve value at the knee
# This lifts the bottom of the distribution (bench/depth players) without
# changing the top, fixing systematic bench→depth deflation.
#
# IDP uses a higher knee (0.80) because IDP has more bench/depth players
# with fewer sources (avg 2.2 vs ~5 for offense), making the bottom-half
# compression more damaging. Scale raised from 5000 to 5500 to allow
# top IDP players to approach star tier (legacy IDP tops ~6000).
#
# Sweep history:
#   v1: exp=2.0, scale=8500             → off tier=45.5%, delta=1101
#   v2: exp=2.5, scale=7800             → off tier=61.5%, delta=879
#   v3: exp=2.5, scale=7800, knee=0.65  → off tier=69.7%, delta=646
#   v4: IDP knee=0.80, scale=5500       → IDP tier=36.8%→51.9%, off unchanged
CALIBRATION_EXPONENT = 2.5
CALIBRATION_KNEE = 0.65  # default knee (offense)

# Per-universe scale: empirically derived from legacy value distribution
UNIVERSE_SCALES: dict[str, int] = {
    "offense_vet": 7800,
    "offense_rookie": 7000,
    "idp_vet": 5500,
    "idp_rookie": 5000,
}
DEFAULT_SCALE = 7800

# Per-universe knee: IDP needs a higher knee to avoid crushing bench/depth players
UNIVERSE_KNEES: dict[str, float] = {
    "offense_vet": 0.65,
    "offense_rookie": 0.65,
    "idp_vet": 0.80,
    "idp_rookie": 0.80,
}

# Pick ceiling for fallback power curve
PICK_CEILING = 7500

# ── Display Scale ──
# Public-facing 1–9999 scale. Pure presentation remap of internal calibrated values.
# Linear: display = max(1, round(calibrated * 9999 / INTERNAL_SCALE_MAX))
# INTERNAL_SCALE_MAX = offense_vet scale (the highest possible calibrated value).
DISPLAY_SCALE_MAX = 9999
INTERNAL_SCALE_MAX = 7800  # must equal UNIVERSE_SCALES["offense_vet"]


def to_display_value(calibrated_value: int | float) -> int:
    """Convert internal calibrated value (0–7800) to display scale (1–9999).

    Linear proportional remap with fixed denominator. Monotonic, deterministic,
    and preserves relative spacing. Does not affect internal model logic.
    """
    if calibrated_value <= 0:
        return 1
    return max(1, min(DISPLAY_SCALE_MAX, round(calibrated_value * DISPLAY_SCALE_MAX / INTERNAL_SCALE_MAX)))


# Non-fantasy positions that should be calibrated very low
NON_FANTASY_POSITIONS = {"K", "P", "OL"}
NON_FANTASY_CEILING = 600  # Legacy kickers max at ~568

# Legacy pick value curve by round (median values from legacy data)
# Used as fallback when a pick can't be matched by name
LEGACY_PICK_ROUND_CURVE: dict[int, int] = {
    1: 6124,  # median 1st round pick
    2: 5251,  # median 2nd round pick
    3: 4367,  # median 3rd round pick
    4: 3425,  # median 4th round pick
    5: 3146,  # median 5th round pick
    6: 2600,  # median 6th round pick
}

# Year discount: future year picks are worth less
# Relative to the current calendar year. Each year out reduces by this factor.
PICK_YEAR_DISCOUNT = 0.70


def _is_pick(asset: dict[str, Any]) -> bool:
    """Check if asset is a draft pick rather than a player."""
    name = str(asset.get("display_name", "")).lower().strip()
    patterns = [
        r"^\d{4}\s+(pick|early|mid|late)",
        r"^(early|mid|late)\s+\d",
        r"^\d{4}\s+\d+\.\d+",
        r"pick\s+\d+\.\d+",
        r"^\d{4}\s+\d+(st|nd|rd|th)$",
    ]
    return any(re.search(p, name) for p in patterns)


def _parse_pick_info(name: str) -> dict[str, Any]:
    """Extract structured info from a pick name for curve-based calibration."""
    n = name.lower().strip()
    info: dict[str, Any] = {"year": None, "round": None, "slot": None, "tier": None}

    # "2026 Pick 1.01" format
    m = re.match(r"(\d{4})\s+pick\s+(\d+)\.(\d+)", n)
    if m:
        info["year"] = int(m.group(1))
        info["round"] = int(m.group(2))
        info["slot"] = int(m.group(3))
        return info

    # "2026 Early 1st" format
    m = re.match(r"(\d{4})\s+(early|mid|late)\s+(\d+)", n)
    if m:
        info["year"] = int(m.group(1))
        info["tier"] = m.group(2)
        info["round"] = int(m.group(3))
        return info

    # "2026 1st" format (no tier)
    m = re.match(r"(\d{4})\s+(\d+)(st|nd|rd|th)$", n)
    if m:
        info["year"] = int(m.group(1))
        info["round"] = int(m.group(2))
        return info

    # "Early 1st" format (no year)
    m = re.match(r"(early|mid|late)\s+(\d+)", n)
    if m:
        info["tier"] = m.group(1)
        info["round"] = int(m.group(2))
        return info

    return info


def _pick_curve_value(info: dict[str, Any], current_year: int | None = None) -> int:
    """Compute a pick value from the legacy round curve with tier/year adjustments."""
    if current_year is None:
        current_year = datetime.date.today().year
    rnd = info.get("round")
    if rnd is None or rnd not in LEGACY_PICK_ROUND_CURVE:
        rnd = min(LEGACY_PICK_ROUND_CURVE.keys(), default=1)

    base = LEGACY_PICK_ROUND_CURVE.get(rnd, 2000)

    # Tier adjustment: early +15%, mid 0%, late -15%
    tier = info.get("tier")
    if tier == "early":
        base = int(base * 1.15)
    elif tier == "late":
        base = int(base * 0.85)

    # Slot adjustment: specific slots get interpolated
    slot = info.get("slot")
    if slot is not None and rnd in LEGACY_PICK_ROUND_CURVE:
        # Interpolate between early/late within the round
        early_val = int(LEGACY_PICK_ROUND_CURVE[rnd] * 1.15)
        late_val = int(LEGACY_PICK_ROUND_CURVE[rnd] * 0.85)
        # 12-team league: slot 1-4 = early, 5-8 = mid, 9-12 = late
        if slot <= 4:
            frac = (4 - slot) / 4
            base = int(early_val * (1 - frac) + (early_val + 200) * frac)
        elif slot >= 9:
            frac = (slot - 8) / 4
            base = int(LEGACY_PICK_ROUND_CURVE[rnd] * (1 - frac) + late_val * frac)

    # Year discount: future years are worth less
    year = info.get("year")
    if year is not None and year > current_year:
        years_out = year - current_year
        discount = PICK_YEAR_DISCOUNT ** years_out
        base = int(base * discount)

    return max(100, min(PICK_CEILING, base))


def _build_legacy_pick_lookup(legacy_path: Path | None) -> dict[str, int]:
    """Build a name-normalized lookup of legacy pick values."""
    if legacy_path is None or not legacy_path.exists():
        return {}

    try:
        data = json.loads(legacy_path.read_text())
    except Exception:
        return {}

    players = data.get("players", {})
    lookup: dict[str, int] = {}

    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        # Legacy data may store position under "POS" or the old "_lamBucket" key
        pos = str(pdata.get("position", pdata.get("POS", pdata.get("_lamBucket", "")))).strip().upper()
        if pos != "PICK":
            continue
        val = pdata.get("_composite", 0)
        if val > 0:
            norm = name.lower().strip()
            lookup[norm] = int(val)

    return lookup


def calibrate_canonical_values(
    assets: list[dict[str, Any]],
    *,
    universe_scales: dict[str, int] | None = None,
    universe_knees: dict[str, float] | None = None,
    exponent: float = CALIBRATION_EXPONENT,
    knee: float = CALIBRATION_KNEE,
    pick_ceiling: int = PICK_CEILING,
    legacy_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Apply universe-aware distribution calibration to canonical asset values.

    For each universe, re-ranks players and applies a piecewise power curve.
    The knee can vary per universe (IDP uses a higher knee than offense).
    Picks are calibrated separately using the legacy pick value curve.

    Args:
        assets: List of canonical asset dicts.
        universe_scales: Optional override for per-universe max scales.
        universe_knees: Optional override for per-universe knee values.
        exponent: Power curve exponent for players.
        knee: Default knee if not specified per-universe.
        pick_ceiling: Maximum calibrated value for picks.
        legacy_path: Path to legacy data JSON for pick value lookup.

    Returns:
        Same list with 'calibrated_value' added to each asset.
    """
    scales = universe_scales or UNIVERSE_SCALES
    knees = universe_knees or UNIVERSE_KNEES
    legacy_pick_lookup = _build_legacy_pick_lookup(legacy_path)

    by_universe: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        universe = str(asset.get("universe", "unknown"))
        by_universe.setdefault(universe, []).append(asset)

    for universe, group in by_universe.items():
        scale = scales.get(universe, DEFAULT_SCALE)
        uni_knee = knees.get(universe, knee)

        players = [a for a in group if not _is_pick(a)]
        picks = [a for a in group if _is_pick(a)]

        # Calibrate players with piecewise power curve (knee varies per universe)
        sort_key = "blended_value"
        players.sort(key=lambda a: -(a.get(sort_key) or 0))

        for rank_idx, asset in enumerate(players):
            depth = len(players)
            if depth == 0:
                break
            rank = rank_idx + 1
            percentile = (depth - (rank - 1)) / depth
            if percentile >= uni_knee:
                calibrated = int(round(scale * (percentile ** exponent)))
            else:
                # Linear ramp from 0 to the curve value at the knee
                knee_val = scale * (uni_knee ** exponent)
                calibrated = int(round(knee_val * (percentile / uni_knee)))
            calibrated = max(0, min(scale, calibrated))

            pos = str(asset.get("metadata", {}).get("position", "")).upper()
            if pos in NON_FANTASY_POSITIONS and calibrated > NON_FANTASY_CEILING:
                calibrated = NON_FANTASY_CEILING

            asset["calibrated_value"] = calibrated

        # Calibrate picks using legacy curve
        for asset in picks:
            name = str(asset.get("display_name", "")).strip()
            norm_name = name.lower().strip()

            # Strategy 1: Direct legacy value lookup
            legacy_val = legacy_pick_lookup.get(norm_name)
            if legacy_val is not None:
                asset["calibrated_value"] = legacy_val
                asset["_pick_calibration_source"] = "legacy_direct"
                continue

            # Strategy 2: Parse pick info and use round curve
            info = _parse_pick_info(name)
            if info.get("round") is not None:
                curve_val = _pick_curve_value(info)
                asset["calibrated_value"] = curve_val
                asset["_pick_calibration_source"] = "round_curve"
                continue

            # Strategy 3: Fallback power curve
            # Sort picks by blended value and use generic curve
            asset["calibrated_value"] = min(pick_ceiling, int(asset.get("blended_value", 0) * 0.5))
            asset["_pick_calibration_source"] = "fallback"

    # Apply display-scale values to all assets (players + picks)
    for asset in assets:
        cv = asset.get("calibrated_value")
        if cv is not None:
            asset["display_value"] = to_display_value(cv)

    return assets


def get_calibration_params() -> dict[str, Any]:
    """Return current calibration parameters for documentation/inspection."""
    return {
        "exponent": CALIBRATION_EXPONENT,
        "knee": CALIBRATION_KNEE,
        "universe_scales": dict(UNIVERSE_SCALES),
        "universe_knees": dict(UNIVERSE_KNEES),
        "default_scale": DEFAULT_SCALE,
        "pick_ceiling": PICK_CEILING,
        "non_fantasy_ceiling": NON_FANTASY_CEILING,
        "non_fantasy_positions": sorted(NON_FANTASY_POSITIONS),
        "pick_calibration": "Legacy curve: direct name match → round/tier/year curve → fallback",
        "pick_round_curve": dict(LEGACY_PICK_ROUND_CURVE),
        "pick_year_discount": PICK_YEAR_DISCOUNT,
        "description": (
            f"Piecewise power curve: scale * percentile^{CALIBRATION_EXPONENT}, "
            f"offense knee={UNIVERSE_KNEES.get('offense_vet')}, IDP knee={UNIVERSE_KNEES.get('idp_vet')}. "
            f"Offense scale={UNIVERSE_SCALES.get('offense_vet')}, IDP scale={UNIVERSE_SCALES.get('idp_vet')}. "
            f"Picks use legacy curve, kickers/punters capped at {NON_FANTASY_CEILING}."
        ),
        "tier_thresholds": {
            "elite": ">= 7000",
            "star": ">= 5000",
            "starter": ">= 3000",
            "bench": ">= 1500",
            "depth": "< 1500",
        },
        "display_scale": {
            "max": DISPLAY_SCALE_MAX,
            "internal_max": INTERNAL_SCALE_MAX,
            "formula": f"max(1, round(calibrated_value * {DISPLAY_SCALE_MAX} / {INTERNAL_SCALE_MAX}))",
            "description": "Linear remap of internal calibrated values to 1–9999 public display scale.",
        },
    }
