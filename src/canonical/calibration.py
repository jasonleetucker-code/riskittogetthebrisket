"""Post-blend calibration layer for canonical values.

The raw canonical pipeline uses a percentile power curve (9999 * p^0.65)
which produces a top-heavy distribution compared to legacy Z-score values.
This calibration step remaps canonical values to a distribution that better
matches the legacy system's value range and tier boundaries.

The calibration works at the percentile level:
1. Each asset's rank within its universe determines its percentile
2. The percentile is mapped through a calibrated curve with a steeper
   exponent and lower ceiling, producing values that distribute more
   naturally across the tier spectrum

This is a post-process step that preserves:
- Raw blended values (for comparison/debugging)
- Per-source contributions
- All metadata

The calibration parameters are empirically chosen to maximize tier
agreement with the legacy system based on comparison batch data.
"""
from __future__ import annotations

from typing import Any


# Calibration parameters — empirically tuned against legacy distribution.
# These produce ~75% tier agreement vs the legacy Z-score system.
CALIBRATION_SCALE = 8500   # Legacy values max around 8200-8500
CALIBRATION_EXPONENT = 2.0  # Steeper than raw 0.65 — spreads values more evenly


def calibrate_canonical_values(
    assets: list[dict[str, Any]],
    *,
    scale: int = CALIBRATION_SCALE,
    exponent: float = CALIBRATION_EXPONENT,
) -> list[dict[str, Any]]:
    """Apply distribution calibration to canonical asset values.

    For each universe, re-ranks assets and applies a calibrated power curve
    that produces values matching the legacy system's distribution more closely.

    The raw blended_value is preserved. A new 'calibrated_value' field is added.

    Args:
        assets: List of canonical asset dicts (must have blended_value, universe).
        scale: Maximum value of the calibrated range (default 8500).
        exponent: Power curve exponent (default 2.0, steeper = more spread).

    Returns:
        Same list with 'calibrated_value' added to each asset.
    """
    # Group by universe and rank within each
    by_universe: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        universe = str(asset.get("universe", "unknown"))
        by_universe.setdefault(universe, []).append(asset)

    for universe, group in by_universe.items():
        # Sort by blended_value descending (or scarcity_adjusted_value if present)
        sort_key = "scarcity_adjusted_value" if group[0].get("scarcity_adjusted_value") is not None else "blended_value"
        group.sort(key=lambda a: -(a.get(sort_key) or 0))

        depth = len(group)
        if depth == 0:
            continue

        for rank_idx, asset in enumerate(group):
            rank = rank_idx + 1
            percentile = (depth - (rank - 1)) / depth
            calibrated = int(round(scale * (percentile ** exponent)))
            calibrated = max(0, min(scale, calibrated))
            asset["calibrated_value"] = calibrated

    return assets


def get_calibration_params() -> dict[str, Any]:
    """Return current calibration parameters for documentation/inspection."""
    return {
        "scale": CALIBRATION_SCALE,
        "exponent": CALIBRATION_EXPONENT,
        "description": (
            f"Calibrated power curve: {CALIBRATION_SCALE} * percentile^{CALIBRATION_EXPONENT}. "
            f"Produces values in 0-{CALIBRATION_SCALE} range with distribution matching "
            f"legacy Z-score system (~75% tier agreement)."
        ),
        "tier_thresholds": {
            "elite": ">= 7000",
            "star": ">= 5000",
            "starter": ">= 3000",
            "bench": ">= 1500",
            "depth": "< 1500",
        },
    }
