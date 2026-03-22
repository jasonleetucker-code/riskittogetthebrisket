"""League context engine — scoring, scarcity, and replacement baselines.

This module provides league-specific adjustments to canonical values.
The first component is the replacement baseline calculator, which determines
the value threshold at each position below which a player is "replacement level."

Future components:
- Scarcity multipliers (positional value adjustment based on starter demand)
- Pick curve and time discount application
- Contender vs rebuilder adjustments

Usage:
    from src.league import ReplacementCalculator, LeagueSettings
    settings = LeagueSettings.from_json("config/leagues/default_superflex_idp.template.json")
    calc = ReplacementCalculator(settings)
    baselines = calc.compute_baselines(canonical_assets)
"""

from src.league.settings import LeagueSettings
from src.league.replacement import ReplacementCalculator

__all__ = ["LeagueSettings", "ReplacementCalculator"]
