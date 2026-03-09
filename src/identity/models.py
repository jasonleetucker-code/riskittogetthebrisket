from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class PlayerRow:
    player_id: str
    sleeper_id: str
    full_name: str
    search_name: str
    team: str
    position: str
    position_group: str
    rookie_class_year: int | None
    age: float | None
    is_active: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlayerAliasRow:
    alias_id: str
    player_id: str
    source: str
    external_asset_id: str
    external_name: str
    name_normalized: str
    team_raw: str
    position_raw: str
    match_confidence: float
    match_method: str
    first_seen_snapshot_id: str
    last_seen_snapshot_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PickRow:
    pick_id: str
    season: int
    round: int
    slot_known: bool
    slot_number: int | None
    bucket: str
    league_id: str
    description: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PickAliasRow:
    pick_alias_id: str
    pick_id: str
    source: str
    external_asset_id: str
    external_name: str
    year_guess: int | None
    round_guess: int | None
    bucket_guess: str
    match_confidence: float
    match_method: str

    def to_dict(self) -> dict:
        return asdict(self)

