from __future__ import annotations

from pathlib import Path

from src.adapters.base import AdapterResult


class ManualCsvAdapter:
    """
    Placeholder adapter for generic CSV imports.
    Intentionally lightweight for Phase 1 scaffolding.
    """

    def __init__(self, source_id: str, source_bucket: str) -> None:
        self.source_id = source_id
        self.source_bucket = source_bucket

    def load(self, file_path: Path) -> AdapterResult:
        return AdapterResult(
            source_id=self.source_id,
            source_bucket=self.source_bucket,
            file_path=str(file_path),
            records=[],
            warnings=[f"ManualCsvAdapter not yet implemented for {file_path.name}"],
        )

