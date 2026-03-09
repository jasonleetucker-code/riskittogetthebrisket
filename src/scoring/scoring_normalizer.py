from __future__ import annotations

from typing import Dict, Iterable, Optional

from .sleeper_ingest import normalize_scoring_settings
from .types import ScoringConfig


def normalize_scoring_map(
    raw_scoring_settings: Dict[str, float],
    roster_positions: Optional[Iterable[str]] = None,
    *,
    league_id: str = "",
    season: Optional[int] = None,
) -> ScoringConfig:
    """Compatibility wrapper for scoring normalization module boundary.

    Downstream callers should consume ScoringConfig and avoid direct dependence
    on raw Sleeper key naming.
    """
    return normalize_scoring_settings(
        raw_scoring_settings=raw_scoring_settings,
        roster_positions=roster_positions,
        league_id=league_id,
        season=season,
    )

