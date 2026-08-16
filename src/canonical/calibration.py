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
    return max(
        1, min(DISPLAY_SCALE_MAX, round(calibrated_value * DISPLAY_SCALE_MAX / INTERNAL_SCALE_MAX))
    )


# Non-fantasy positions that should be calibrated very low
NON_FANTASY_POSITIONS = {"K", "P", "OL"}
NON_FANTASY_CEILING = 600  # Legacy kickers max at ~568

# RETIRED (C1-U6): this module's own pick pricer — LEGACY_PICK_ROUND_CURVE
# ({6124/5251/4367/3425/3146/2600}), PICK_YEAR_DISCOUNT (0.70**years_out),
# the ±15% tier adjustment and the slot interpolation — is DELETED.  It was
# a complete second future-pick valuation owner surviving in the tree
# (production-dormant since the CANONICAL_DATA_MODE retirement, exercised
# only by its own tests), and its constants contradicted the canonical
# pipeline's measured derivations.  Canonical pick values have exactly one
# owner: the data_contract pick pipeline (+ src/api/pick_value_resolution
# for reference-class lookup).  This layer now refuses to price picks.


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

    This function is for the LEGACY engine only.  The canonical 6-step
    Hill-curve engine produces display-scaled values in a single pass
    (see ``src/canonical/player_valuation.py``) and must not be
    re-calibrated here — doing so would stack a second curve on top of
    the Hill output.  Assets tagged by the canonical pipeline with
    ``_pick_calibration_source == "canonical_pipeline"`` are rejected.

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

    Raises:
        RuntimeError: If any input asset was produced by the canonical
            Hill-curve pipeline (would cause double-calibration).
    """
    canonical_tagged = [
        a for a in assets if a.get("_pick_calibration_source") == "canonical_pipeline"
    ]
    if canonical_tagged:
        sample = canonical_tagged[0].get("display_name", "<unknown>")
        raise RuntimeError(
            f"calibrate_canonical_values called on {len(canonical_tagged)} "
            f"asset(s) already produced by the canonical Hill-curve pipeline "
            f"(e.g. {sample!r}). The canonical engine emits display-scaled "
            f"values in a single pass; re-calibrating them here would stack "
            f"a second curve on top."
        )

    scales = universe_scales or UNIVERSE_SCALES
    knees = universe_knees or UNIVERSE_KNEES

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
                calibrated = int(round(scale * (percentile**exponent)))
            else:
                # Linear ramp from 0 to the curve value at the knee
                knee_val = scale * (uni_knee**exponent)
                calibrated = int(round(knee_val * (percentile / uni_knee)))
            calibrated = max(0, min(scale, calibrated))

            pos = str(asset.get("metadata", {}).get("position", "")).upper()
            if pos in NON_FANTASY_POSITIONS and calibrated > NON_FANTASY_CEILING:
                calibrated = NON_FANTASY_CEILING

            asset["calibrated_value"] = calibrated

        # Picks: this retired layer prices NO pick (C1-U6 — one owner).
        # Missing is never zero: calibrated_value stays None and the
        # source label says why, so a consumer cannot mistake refusal
        # for a real $0.
        for asset in picks:
            asset["calibrated_value"] = None
            asset["_pick_calibration_source"] = "retired_second_owner_c1u6"

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
        "pick_calibration": "RETIRED (C1-U6): this layer prices no pick; canonical owner is the data_contract pick pipeline",
        "description": (
            f"Piecewise power curve: scale * percentile^{CALIBRATION_EXPONENT}, "
            f"offense knee={UNIVERSE_KNEES.get('offense_vet')}, IDP knee={UNIVERSE_KNEES.get('idp_vet')}. "
            f"Offense scale={UNIVERSE_SCALES.get('offense_vet')}, IDP scale={UNIVERSE_SCALES.get('idp_vet')}. "
            f"Picks are not priced by this layer (C1-U6), kickers/punters capped at {NON_FANTASY_CEILING}."
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
