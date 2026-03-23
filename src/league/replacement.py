"""Replacement baseline calculator.

Determines the canonical value at which a player at each position becomes
"replacement level" — i.e., freely available on waivers or near-worthless
in trade.

The replacement level is the value of the Nth-best player at a position,
where N is determined by league starter demand. Players above replacement
level have positive trade value; players below are essentially free.

This is the foundation for future scarcity multipliers:
    scarcity_multiplier = f(player_value - replacement_baseline)

Usage:
    from src.league import ReplacementCalculator, LeagueSettings

    settings = LeagueSettings.from_json("config/leagues/default_superflex_idp.template.json")
    calc = ReplacementCalculator(settings)
    baselines = calc.compute_baselines(canonical_assets)
    # baselines = {"QB": {"replacement_value": 4200, "replacement_rank": 24, ...}, ...}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.league.settings import LeagueSettings


# Position mapping from canonical pipeline universes/positions to league positions
POSITION_ALIASES: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
}

# Injury buffer: extra roster spots beyond starters to account for
# injuries, byes, and roster churn. As a fraction of starter demand.
DEFAULT_INJURY_BUFFER = 0.25

# For positions with shared FLEX eligibility, we estimate what fraction
# of FLEX slots are typically occupied by each position.
# These are reasonable estimates for a Superflex dynasty league.
DEFAULT_FLEX_ALLOCATION: dict[str, float] = {
    "RB": 0.45,  # RBs take ~45% of FLEX slots
    "WR": 0.40,  # WRs take ~40% of FLEX slots
    "TE": 0.15,  # TEs take ~15% of FLEX slots
}

DEFAULT_SFLEX_ALLOCATION: dict[str, float] = {
    "QB": 0.85,  # QBs take ~85% of SFLEX slots in Superflex
    "RB": 0.05,
    "WR": 0.05,
    "TE": 0.05,
}

DEFAULT_IDP_FLEX_ALLOCATION: dict[str, float] = {
    "DL": 0.35,
    "LB": 0.40,
    "DB": 0.25,
}


@dataclass
class PositionBaseline:
    """Replacement baseline for a single position."""

    position: str
    direct_starter_demand: int
    effective_starter_demand: int
    replacement_rank: int
    replacement_value: int | None
    player_pool_size: int
    above_replacement_count: int
    injury_buffer_slots: int


class ReplacementCalculator:
    """Calculate replacement-level baselines for each position.

    The replacement level for a position is determined by:
    1. How many starters of that position the league needs (demand)
    2. How deep the player pool is at that position (supply)
    3. An injury/bye buffer to account for real roster management

    The "replacement player" is the one at the cutoff — the marginal
    starter across all teams.
    """

    def __init__(
        self,
        settings: LeagueSettings,
        injury_buffer: float = DEFAULT_INJURY_BUFFER,
        flex_allocation: dict[str, float] | None = None,
        sflex_allocation: dict[str, float] | None = None,
        idp_flex_allocation: dict[str, float] | None = None,
    ) -> None:
        self.settings = settings
        self.injury_buffer = injury_buffer
        self.flex_allocation = flex_allocation or DEFAULT_FLEX_ALLOCATION
        self.sflex_allocation = sflex_allocation or DEFAULT_SFLEX_ALLOCATION
        self.idp_flex_allocation = idp_flex_allocation or DEFAULT_IDP_FLEX_ALLOCATION

    def effective_demand(self, position: str) -> int:
        """Estimated real demand for a position, accounting for flex sharing.

        Instead of using maximum possible demand (which overstates positions
        that CAN fill FLEX but rarely do), we estimate the effective demand
        based on typical roster construction patterns.
        """
        pos = position.upper()
        teams = self.settings.teams
        direct = self.settings.starters.get(pos, 0) * teams

        # Add estimated share of FLEX slots
        flex_share = 0.0
        if pos in self.settings.flex_eligible:
            flex_total = self.settings.starters.get("FLEX", 0) * teams
            flex_share += flex_total * self.flex_allocation.get(pos, 0.0)

        if pos in self.settings.sflex_eligible:
            sflex_total = self.settings.starters.get("SFLEX", 0) * teams
            flex_share += sflex_total * self.sflex_allocation.get(pos, 0.0)

        if pos in self.settings.idp_flex_eligible:
            idp_flex_total = self.settings.starters.get("IDP_FLEX", 0) * teams
            flex_share += idp_flex_total * self.idp_flex_allocation.get(pos, 0.0)

        return int(round(direct + flex_share))

    def replacement_rank(self, position: str) -> int:
        """The rank at which a player becomes replacement level.

        replacement_rank = effective_demand + injury_buffer
        """
        demand = self.effective_demand(position)
        buffer = max(1, int(round(demand * self.injury_buffer)))
        return demand + buffer

    def compute_baselines(
        self,
        canonical_assets: list[dict[str, Any]],
    ) -> dict[str, PositionBaseline]:
        """Compute replacement baselines from canonical snapshot assets.

        Args:
            canonical_assets: List of asset dicts from a canonical snapshot.
                Each must have at least 'blended_value' and either 'display_name'
                or 'asset_key'. Position is inferred from universe or metadata.

        Returns:
            Dict mapping position → PositionBaseline.
        """
        # Group assets by position
        by_position: dict[str, list[int]] = {}
        for asset in canonical_assets:
            pos = self._infer_position(asset)
            if not pos:
                continue
            val = asset.get("blended_value")
            if val is None:
                continue
            by_position.setdefault(pos, []).append(int(val))

        # Sort each position's values descending
        for pos in by_position:
            by_position[pos].sort(reverse=True)

        # Compute baselines
        results: dict[str, PositionBaseline] = {}
        for pos in self.settings.all_positions:
            values = by_position.get(pos, [])
            demand = self.effective_demand(pos)
            rep_rank = self.replacement_rank(pos)
            buffer = rep_rank - demand

            # The replacement value is the value at the replacement rank
            if values and rep_rank <= len(values):
                rep_value = values[rep_rank - 1]  # 0-indexed
            elif values:
                # Pool is smaller than demand — use the lowest value
                rep_value = values[-1]
            else:
                rep_value = None

            above_rep = sum(1 for v in values if rep_value is not None and v > rep_value) if rep_value is not None else 0

            results[pos] = PositionBaseline(
                position=pos,
                direct_starter_demand=self.settings.direct_starter_demand(pos),
                effective_starter_demand=demand,
                replacement_rank=rep_rank,
                replacement_value=rep_value,
                player_pool_size=len(values),
                above_replacement_count=above_rep,
                injury_buffer_slots=buffer,
            )

        return results

    def _infer_position(self, asset: dict[str, Any]) -> str | None:
        """Infer the league position from a canonical asset dict.

        Tries multiple fields: position metadata, universe, display_name patterns.
        Handles DLF-style rank-suffixed positions like "LB1", "DB23", "DL70".
        """
        for field_source in self._position_field_sources(asset):
            pos = self._normalize_position(field_source)
            if pos:
                return pos
        return None

    @staticmethod
    def _position_field_sources(asset: dict[str, Any]) -> list[str]:
        """Collect raw position strings from all available fields."""
        candidates = []
        for field in ("position", "position_normalized_guess", "position_raw"):
            val = str(asset.get(field, "")).strip()
            if val:
                candidates.append(val)
        meta = asset.get("metadata", {})
        if isinstance(meta, dict):
            val = str(meta.get("position", "")).strip()
            if val:
                candidates.append(val)
        return candidates

    @staticmethod
    def _normalize_position(raw: str) -> str | None:
        """Normalize a position string to a league position.

        Handles:
        - Standard positions: QB, RB, WR, TE, DL, LB, DB
        - Sub-positions: DE, DT → DL; CB, S, SS, FS → DB; ILB, OLB → LB
        - DLF rank-suffixed: LB1, LB23, DL70, DB5 → strip trailing digits
        """
        import re
        pos = raw.strip().upper()
        if pos in POSITION_ALIASES:
            return POSITION_ALIASES[pos]
        # Strip trailing digits (e.g., LB1 → LB, DL70 → DL)
        stripped = re.sub(r'\d+$', '', pos)
        if stripped and stripped in POSITION_ALIASES:
            return POSITION_ALIASES[stripped]
        return None

    def baselines_summary(
        self, baselines: dict[str, PositionBaseline]
    ) -> dict[str, Any]:
        """Produce a JSON-serializable summary of baselines."""
        return {
            "league": self.settings.league_name,
            "teams": self.settings.teams,
            "superflex": self.settings.superflex,
            "te_premium": self.settings.te_premium,
            "positions": {
                pos: {
                    "direct_demand": bl.direct_starter_demand,
                    "effective_demand": bl.effective_starter_demand,
                    "replacement_rank": bl.replacement_rank,
                    "replacement_value": bl.replacement_value,
                    "pool_size": bl.player_pool_size,
                    "above_replacement": bl.above_replacement_count,
                    "buffer_slots": bl.injury_buffer_slots,
                }
                for pos, bl in baselines.items()
            },
        }
