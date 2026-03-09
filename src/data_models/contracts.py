from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawAssetRecord:
    asset_key: str
    display_name: str
    asset_type: str  # player|pick
    source_id: str
    source_bucket: str
    rank: float | None = None
    raw_value: float | None = None
    position: str | None = None
    team: str | None = None
    rookie_flag: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawSourceSnapshot:
    snapshot_id: str
    created_at: str
    source_id: str
    source_bucket: str
    records: list[RawAssetRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "source_id": self.source_id,
            "source_bucket": self.source_bucket,
            "warnings": self.warnings,
            "records": [r.to_dict() for r in self.records],
        }


@dataclass
class CanonicalAssetValue:
    asset_key: str
    display_name: str
    source_values: dict[str, int]
    blended_value: int
    source_weights_used: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

