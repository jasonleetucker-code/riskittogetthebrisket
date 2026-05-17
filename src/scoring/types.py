from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class ScoringRule:
    key: str
    category: str
    baseline_value: float
    league_value: float
    delta: float
    relevant_buckets: List[str] = field(default_factory=list)
    rule_type: str = "linear"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class ScoringConfig:
    scoring_version: str
    league_id: str
    season: Optional[int]
    roster_positions: List[str]
    scoring_map: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class HistoricalScoringProfile:
    player_id: str
    player_name: str
    position_bucket: str
    seasons: List[int]
    games: int
    stats_per_game: Dict[str, float] = field(default_factory=dict)
    features: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class ArchetypeProfile:
    position_bucket: str
    archetype: str
    role_bucket: str
    scoring_profile_tags: List[str] = field(default_factory=list)
    feature_means: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class PlayerScoringAdjustment:
    baseline_scoring_version: str
    league_scoring_version: str
    league_id: str
    baseline_points_per_game: float
    league_points_per_game: float
    raw_scoring_ratio: float
    shrunk_scoring_ratio: float
    final_scoring_multiplier: float
    final_scoring_delta_points: float
    final_scoring_delta_value: float
    position_bucket: str
    archetype: str
    confidence: float
    sample_size_score: float
    projection_weight: float
    data_quality_flag: str
    scoring_tags: List[str] = field(default_factory=list)
    source: str = "scoring_translation_hybrid"
    rule_contributions: Dict[str, float] = field(default_factory=dict)
    # Per-rule-key contribution for selected rules where the
    # category-level aggregate is too coarse to be useful (e.g. the
    # ``first_downs`` category aggregates ``rec_fd``, ``rush_fd``,
    # and ``bonus_fd_te`` for TE rows; the TE Premium Lab needs to
    # isolate ``bonus_fd_te`` from the others).  Optional, additive,
    # populated only for the rules listed in
    # ``RULE_CONTRIBUTION_DETAIL_KEYS`` in ``scoring_delta.py``.
    # Older contracts simply won't carry this field.
    rule_contributions_detail: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class BacktestRow:
    player_name: str
    position_bucket: str
    baseline_ppg: float
    league_ppg: float
    ratio: float
    multiplier: float
    confidence: float
    delta_points: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)
