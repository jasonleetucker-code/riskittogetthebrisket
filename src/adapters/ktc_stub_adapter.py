from __future__ import annotations

import csv
from pathlib import Path

from src.adapters.base import AdapterResult
from src.data_models import RawAssetRecord
from src.utils import normalize_player_name, normalize_position_family, normalize_team


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class KtcStubAdapter:
    """
    KTC adapter scaffold.
    - Contract-compatible now
    - Does not perform live scraping in this phase
    - Can optionally read a local seed CSV if provided
    """

    def __init__(self, source_id: str, source_bucket: str) -> None:
        self.source_id = source_id
        self.source_bucket = source_bucket

    def load(self, file_path: Path) -> AdapterResult:
        result = AdapterResult(
            source_id=self.source_id,
            source_bucket=self.source_bucket,
            file_path=str(file_path) if str(file_path) else "",
        )
        if not file_path or not str(file_path) or not file_path.exists():
            result.warnings.append(
                "KTC stub active: no seed file found. Supply local seed CSV or replace with live adapter."
            )
            return result

        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Accepted columns:
                # name/player, pos/position, team, rank, value
                name = str(
                    row.get("name")
                    or row.get("player")
                    or row.get("player_name")
                    or ""
                ).strip()
                if not name:
                    continue

                norm = normalize_player_name(name)
                if not norm:
                    continue

                rank = _safe_float(row.get("rank"))
                value = _safe_float(row.get("value"))
                if rank is None and value is None:
                    # Keep rows contract-safe; at least one signal expected.
                    continue

                pos = normalize_position_family(str(row.get("pos") or row.get("position") or ""))
                team = normalize_team(str(row.get("team") or ""))

                result.records.append(
                    RawAssetRecord(
                        asset_key=f"player::{norm}",
                        display_name=name,
                        asset_type="player",
                        source_id=self.source_id,
                        source_bucket=self.source_bucket,
                        rank=rank,
                        raw_value=value,
                        position=pos,
                        team=team,
                        rookie_flag=False,
                        metadata={
                            "profile_source": file_path.name,
                            "adapter": "ktc_stub",
                        },
                    )
                )

        if not result.records:
            result.warnings.append(f"KTC stub seed file loaded but produced no usable rows: {file_path.name}")
        return result

