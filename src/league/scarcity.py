"""Scarcity adjustment layer for canonical values.

Converts raw blended canonical values into league-context-aware values
using replacement baselines. The key output is Value Above Replacement
(VAR), which measures how much better a player is than a freely
available replacement at their position.

The adjustment works as follows:
1. Compute replacement baselines per position (from replacement.py)
2. For each player: VAR = blended_value - replacement_value
3. Scale VAR back to the canonical 0-9999 range using a configurable
   scaling approach

This is the first concrete use of the league context engine and is
designed to make canonical values reflect positional scarcity rather
than just raw source consensus.

Future evolution:
- Position-specific scarcity multipliers (QB scarcity vs WR depth)
- Contender vs rebuilder adjustments
- Pick curve integration
"""
from __future__ import annotations

from typing import Any

from src.league.replacement import ReplacementCalculator, PositionBaseline
from src.league.settings import LeagueSettings


# The canonical scale maximum
CANONICAL_SCALE = 9999


def compute_scarcity_adjusted_values(
    canonical_assets: list[dict[str, Any]],
    baselines: dict[str, PositionBaseline],
    *,
    floor_value: int = 100,
    scale_to: int = CANONICAL_SCALE,
) -> list[dict[str, Any]]:
    """Apply scarcity adjustment to canonical assets using replacement baselines.

    For each asset with a known position:
    - Compute VAR = blended_value - replacement_baseline
    - Rescale to 0-{scale_to} range based on the maximum VAR observed

    Assets without position data retain their raw blended value.

    Args:
        canonical_assets: List of asset dicts from canonical snapshot.
        baselines: Position → PositionBaseline from ReplacementCalculator.
        floor_value: Minimum adjusted value for players at or below replacement.
        scale_to: Target scale maximum (default 9999).

    Returns:
        List of asset dicts with added fields:
        - scarcity_adjusted_value: the adjusted value
        - var_raw: raw value above replacement (before scaling)
        - replacement_baseline: the baseline used
        - scarcity_position: the position used for adjustment
    """
    # Compute raw VAR for each asset
    enriched: list[dict[str, Any]] = []
    max_var = 0

    for asset in canonical_assets:
        entry = dict(asset)
        blended = int(asset.get("blended_value", 0))
        pos = _infer_position_for_scarcity(asset)

        if pos and pos in baselines:
            baseline = baselines[pos]
            rep_val = baseline.replacement_value
            if rep_val is not None:
                var = max(0, blended - rep_val)
                entry["var_raw"] = var
                entry["replacement_baseline"] = rep_val
                entry["scarcity_position"] = pos
                max_var = max(max_var, var)
            else:
                entry["var_raw"] = None
                entry["replacement_baseline"] = None
                entry["scarcity_position"] = pos
        else:
            entry["var_raw"] = None
            entry["replacement_baseline"] = None
            entry["scarcity_position"] = None

        enriched.append(entry)

    # Scale VAR to target range
    if max_var <= 0:
        max_var = 1  # Avoid division by zero

    for entry in enriched:
        var = entry.get("var_raw")
        if var is not None:
            # Linear scale: VAR / max_VAR * scale_to
            scaled = int(round((var / max_var) * scale_to))
            entry["scarcity_adjusted_value"] = max(floor_value if var > 0 else 0, scaled)
        else:
            # No position data — use raw blended value as fallback
            entry["scarcity_adjusted_value"] = int(entry.get("blended_value", 0))

    return enriched


def _infer_position_for_scarcity(asset: dict[str, Any]) -> str | None:
    """Infer league position from canonical asset metadata.

    Uses the same position resolution as ReplacementCalculator but
    operates on the enriched canonical asset dict format.
    """
    from src.league.replacement import POSITION_ALIASES
    import re

    # Check metadata first (populated by _collect_asset_metadata in transform.py)
    meta = asset.get("metadata", {})
    if isinstance(meta, dict):
        raw_pos = str(meta.get("position", "")).strip().upper()
        if raw_pos:
            if raw_pos in POSITION_ALIASES:
                return POSITION_ALIASES[raw_pos]
            stripped = re.sub(r'\d+$', '', raw_pos)
            if stripped in POSITION_ALIASES:
                return POSITION_ALIASES[stripped]

    return None


def build_scarcity_summary(
    enriched_assets: list[dict[str, Any]],
    baselines: dict[str, PositionBaseline],
) -> dict[str, Any]:
    """Build a JSON-serializable summary of scarcity adjustments."""
    by_pos: dict[str, list] = {}
    for a in enriched_assets:
        pos = a.get("scarcity_position")
        if not pos:
            continue
        by_pos.setdefault(pos, []).append(a)

    positions = {}
    for pos, assets in sorted(by_pos.items()):
        bl = baselines.get(pos)
        vars_list = [a["var_raw"] for a in assets if a.get("var_raw") is not None]
        adjusted = [a["scarcity_adjusted_value"] for a in assets if a.get("scarcity_adjusted_value") is not None]

        positions[pos] = {
            "player_count": len(assets),
            "replacement_value": bl.replacement_value if bl else None,
            "replacement_rank": bl.replacement_rank if bl else None,
            "above_replacement": sum(1 for v in vars_list if v > 0),
            "below_replacement": sum(1 for v in vars_list if v == 0),
            "avg_var": int(round(sum(vars_list) / len(vars_list))) if vars_list else 0,
            "max_adjusted": max(adjusted) if adjusted else 0,
            "min_adjusted": min(adjusted) if adjusted else 0,
        }

    no_position = sum(1 for a in enriched_assets if a.get("scarcity_position") is None)

    return {
        "total_assets": len(enriched_assets),
        "with_position": len(enriched_assets) - no_position,
        "without_position": no_position,
        "positions": positions,
    }
