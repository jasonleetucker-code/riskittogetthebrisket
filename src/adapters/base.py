from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from src.data_models import RawAssetRecord


@dataclass
class AdapterResult:
    source_id: str
    source_bucket: str
    file_path: str
    records: list[RawAssetRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(Protocol):
    source_id: str
    source_bucket: str

    def load(self, file_path: Path) -> AdapterResult: ...

