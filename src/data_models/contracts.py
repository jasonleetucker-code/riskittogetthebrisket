from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawAssetRecord:
    # Required adapter output contract fields
    source: str
    snapshot_id: str
    asset_type: str  # player|pick
    external_asset_id: str
    external_name: str
    display_name: str
    team_raw: str
    position_raw: str
    age_raw: str
    rookie_flag_raw: str
    rank_raw: float | None
    value_raw: float | None
    tier_raw: str
    universe: str
    format_key: str
    is_idp: bool
    is_offense: bool
    source_notes: str
    metadata_json: dict[str, Any] = field(default_factory=dict)

    # Strongly recommended normalized helper fields
    name_normalized_guess: str = ""
    team_normalized_guess: str = ""
    position_normalized_guess: str = ""
    pick_round_guess: int | None = None
    pick_slot_guess: str = ""
    pick_year_guess: int | None = None

    # Internal convenience field for deterministic joins/blends
    asset_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def source_id(self) -> str:
        return self.source

    @property
    def source_bucket(self) -> str:
        return self.universe

    @property
    def rank(self) -> float | None:
        return self.rank_raw

    @property
    def raw_value(self) -> float | None:
        return self.value_raw

    @property
    def position(self) -> str:
        return self.position_normalized_guess or self.position_raw

    @property
    def team(self) -> str:
        return self.team_normalized_guess or self.team_raw

    @property
    def rookie_flag(self) -> bool:
        return str(self.rookie_flag_raw).strip().lower() in {"1", "true", "yes", "y", "rookie"}


@dataclass
class RawSourceSnapshot:
    # Required snapshot-level contract fields
    source: str
    snapshot_id: str
    pulled_at_utc: str
    season: str
    format_key: str
    universe: str
    ingest_type: str
    source_url: str
    raw_storage_path: str
    record_count: int
    adapter_version: str

    # Additional provenance required by project rules
    scoring_context: str = ""
    ingest_method: str = ""
    raw_file_path: str = ""
    hash: str = ""
    notes: str = ""
    parse_log_path: str = ""
    manifest_path: str = ""

    records: list[RawAssetRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["record_count"] = len(self.records)
        payload["records"] = [r.to_dict() for r in self.records]
        return payload


@dataclass
class SourceManifest:
    source: str
    snapshot_id: str
    pulled_at_utc: str
    season: str
    scoring_context: str
    universe: str
    ingest_method: str
    ingest_type: str
    source_url: str
    format_key: str
    raw_file_path: str
    raw_storage_path: str
    record_count: int
    hash: str
    notes: str
    adapter_version: str
    inserted_by: str = "codex_pipeline"

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
        }


@dataclass
class CanonicalAssetValue:
    asset_key: str
    display_name: str
    universe: str
    source_values: dict[str, int]
    blended_value: int
    source_weights_used: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
