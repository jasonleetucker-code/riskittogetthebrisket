"""League settings model.

Loads league configuration from JSON and provides structured access to
roster requirements, scoring format, and positional structure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LeagueSettings:
    """Immutable league configuration."""

    league_name: str
    teams: int
    superflex: bool
    te_premium: float
    ppr: float
    starters: dict[str, int]
    roster_size: int
    taxi_size: int
    flex_eligible: list[str]
    sflex_eligible: list[str]
    idp_flex_eligible: list[str]
    pick_model: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> LeagueSettings:
        """Load settings from a league config JSON file."""
        data = json.loads(Path(path).read_text())
        fmt = data.get("format", {})
        return cls(
            league_name=str(data.get("league_name", "Unknown")),
            teams=int(data.get("teams", 12)),
            superflex=bool(fmt.get("superflex", False)),
            te_premium=float(fmt.get("te_premium", 1.0)),
            ppr=float(fmt.get("ppr", 1.0)),
            starters=dict(data.get("starters", {})),
            roster_size=int(data.get("roster_size", 25)),
            taxi_size=int(data.get("taxi_size", 0)),
            flex_eligible=list(data.get("flex_eligible", ["RB", "WR", "TE"])),
            sflex_eligible=list(data.get("sflex_eligible", ["QB", "RB", "WR", "TE"])),
            idp_flex_eligible=list(data.get("idp_flex_eligible", ["DL", "LB", "DB"])),
            pick_model=dict(data.get("pick_model", {})),
        )

    @property
    def offense_positions(self) -> list[str]:
        """Positions considered offensive."""
        return ["QB", "RB", "WR", "TE"]

    @property
    def idp_positions(self) -> list[str]:
        """Positions considered IDP."""
        return ["DL", "LB", "DB"]

    @property
    def all_positions(self) -> list[str]:
        """All startable positions."""
        return self.offense_positions + self.idp_positions

    def starter_demand(self, position: str) -> int:
        """Total starter slots that a given position can fill across all teams.

        For a 12-team league with 1 QB + 1 SFLEX:
        - QB demand = 12 * (1 QB + 1 SFLEX) = 24 (QBs are SF-eligible)
        - RB demand = 12 * (2 RB + 2 FLEX) = 48 (RBs fill FLEX)
        - WR demand = 12 * (3 WR + 2 FLEX) = 60 (WRs fill FLEX)
        - TE demand = 12 * (1 TE + 2 FLEX) = 36 (TEs fill FLEX)

        Note: FLEX/SFLEX slots are shared, so this represents maximum demand,
        not guaranteed demand. The actual replacement level depends on how
        teams allocate these shared slots.
        """
        pos = position.upper()
        direct = self.starters.get(pos, 0)

        # Add flex eligibility
        flex_count = 0
        if pos in self.flex_eligible:
            flex_count += self.starters.get("FLEX", 0)
        if pos in self.sflex_eligible:
            flex_count += self.starters.get("SFLEX", 0)
        if pos in self.idp_flex_eligible:
            flex_count += self.starters.get("IDP_FLEX", 0)

        return self.teams * (direct + flex_count)

    def direct_starter_demand(self, position: str) -> int:
        """Starter slots that ONLY this position can fill (no flex sharing).

        This represents the minimum guaranteed demand — the floor of how
        many players of this position must start league-wide.
        """
        pos = position.upper()
        direct = self.starters.get(pos, 0)
        return self.teams * direct
