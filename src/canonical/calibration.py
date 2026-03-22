"""Post-blend calibration layer for canonical values.

The raw canonical pipeline uses a percentile power curve (9999 * p^0.65)
which produces a top-heavy distribution compared to legacy Z-score values.
This calibration step remaps canonical values to a distribution that better
matches the legacy system's value range and tier boundaries.

The calibration is universe-aware:
- offense_vet/offense_rookie: calibrated to 8500 max (matching legacy offense)
- idp_vet/idp_rookie: calibrated to 5000 max (legacy IDP caps ~4900)
- Assets detected as picks: capped at 7500 (legacy picks max ~7300)

This produces values that more accurately reflect the cross-universe
relative value that users expect from the legacy system.

The calibration parameters are empirically chosen to maximize tier
agreement with the legacy system based on comparison batch data.
"""
from __future__ import annotations

import re
from typing import Any


# Default calibration parameters
CALIBRATION_EXPONENT = 2.0  # Steeper than raw 0.65 — spreads values more evenly

# Per-universe scale: empirically derived from legacy value distribution
# Legacy offense max ~8231, IDP max ~4882, picks max ~7311
UNIVERSE_SCALES: dict[str, int] = {
    "offense_vet": 8500,
    "offense_rookie": 8500,
    "idp_vet": 5000,
    "idp_rookie": 5000,
}
DEFAULT_SCALE = 8500

# Pick ceiling: picks should not exceed this even if ranked highly
PICK_CEILING = 7500


def _is_pick(asset: dict[str, Any]) -> bool:
    """Check if asset is a draft pick rather than a player."""
    name = str(asset.get("display_name", "")).lower().strip()
    patterns = [
        r"^\d{4}\s+(pick|early|mid|late)",
        r"^(early|mid|late)\s+\d",
        r"^\d{4}\s+\d+\.\d+",
        r"pick\s+\d+\.\d+",
        r"^\d{4}\s+\d+(st|nd|rd|th)$",  # "2026 1st", "2027 2nd"
    ]
    return any(re.search(p, name) for p in patterns)


# Non-fantasy positions that should be calibrated very low
NON_FANTASY_POSITIONS = {"K", "P", "OL"}
NON_FANTASY_CEILING = 600  # Legacy kickers max at ~568


def calibrate_canonical_values(
    assets: list[dict[str, Any]],
    *,
    universe_scales: dict[str, int] | None = None,
    exponent: float = CALIBRATION_EXPONENT,
    pick_ceiling: int = PICK_CEILING,
) -> list[dict[str, Any]]:
    """Apply universe-aware distribution calibration to canonical asset values.

    For each universe, re-ranks assets and applies a calibrated power curve
    using universe-specific scale and shared exponent.

    Pick assets are additionally capped at pick_ceiling.

    The raw blended_value is preserved. A new 'calibrated_value' field is added.

    Args:
        assets: List of canonical asset dicts (must have blended_value, universe).
        universe_scales: Optional override for per-universe max scales.
        exponent: Power curve exponent (default 2.0, steeper = more spread).
        pick_ceiling: Maximum calibrated value for draft pick assets.

    Returns:
        Same list with 'calibrated_value' added to each asset.
    """
    scales = universe_scales or UNIVERSE_SCALES

    # Group by universe and rank within each
    by_universe: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        universe = str(asset.get("universe", "unknown"))
        by_universe.setdefault(universe, []).append(asset)

    for universe, group in by_universe.items():
        scale = scales.get(universe, DEFAULT_SCALE)

        # Separate picks from players — calibrate independently
        players = [a for a in group if not _is_pick(a)]
        picks = [a for a in group if _is_pick(a)]

        # Calibrate players
        sort_key = "scarcity_adjusted_value" if players and players[0].get("scarcity_adjusted_value") is not None else "blended_value"
        players.sort(key=lambda a: -(a.get(sort_key) or 0))

        for rank_idx, asset in enumerate(players):
            depth = len(players)
            if depth == 0:
                break
            rank = rank_idx + 1
            percentile = (depth - (rank - 1)) / depth
            calibrated = int(round(scale * (percentile ** exponent)))
            calibrated = max(0, min(scale, calibrated))

            # Cap non-fantasy positions (kickers, punters)
            pos = str(asset.get("metadata", {}).get("position", "")).upper()
            if pos in NON_FANTASY_POSITIONS and calibrated > NON_FANTASY_CEILING:
                calibrated = NON_FANTASY_CEILING

            asset["calibrated_value"] = calibrated

        # Calibrate picks separately with pick_ceiling as their scale
        sort_key_p = "scarcity_adjusted_value" if picks and picks[0].get("scarcity_adjusted_value") is not None else "blended_value"
        picks.sort(key=lambda a: -(a.get(sort_key_p) or 0))

        for rank_idx, asset in enumerate(picks):
            depth = len(picks)
            if depth == 0:
                break
            rank = rank_idx + 1
            percentile = (depth - (rank - 1)) / depth
            calibrated = int(round(pick_ceiling * (percentile ** exponent)))
            asset["calibrated_value"] = max(0, min(pick_ceiling, calibrated))

    return assets


def get_calibration_params() -> dict[str, Any]:
    """Return current calibration parameters for documentation/inspection."""
    return {
        "exponent": CALIBRATION_EXPONENT,
        "universe_scales": dict(UNIVERSE_SCALES),
        "default_scale": DEFAULT_SCALE,
        "pick_ceiling": PICK_CEILING,
        "non_fantasy_ceiling": NON_FANTASY_CEILING,
        "non_fantasy_positions": sorted(NON_FANTASY_POSITIONS),
        "description": (
            f"Universe-aware power curve: scale * percentile^{CALIBRATION_EXPONENT}. "
            f"Offense universes use {UNIVERSE_SCALES.get('offense_vet')} max, "
            f"IDP universes use {UNIVERSE_SCALES.get('idp_vet')} max, "
            f"picks calibrated separately at {PICK_CEILING} max, "
            f"kickers/punters capped at {NON_FANTASY_CEILING}."
        ),
        "tier_thresholds": {
            "elite": ">= 7000",
            "star": ">= 5000",
            "starter": ">= 3000",
            "bench": ">= 1500",
            "depth": "< 1500",
        },
    }
