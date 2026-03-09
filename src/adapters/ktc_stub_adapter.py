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

    def __init__(self, source_id: str, source_bucket: str, format_key: str = "dynasty_sf") -> None:
        self.source_id = source_id
        self.source_bucket = source_bucket
        self.format_key = format_key

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
                ext_id = str(row.get("id") or row.get("player_id") or row.get("external_id") or "").strip()

                result.records.append(
                    RawAssetRecord(
                        source=self.source_id,
                        snapshot_id="",
                        asset_type="player",
                        external_asset_id=ext_id,
                        external_name=name,
                        asset_key=f"player::{norm}",
                        display_name=name,
                        team_raw=str(row.get("team") or ""),
                        position_raw=str(row.get("pos") or row.get("position") or ""),
                        age_raw=str(row.get("age") or ""),
                        rookie_flag_raw=str(row.get("rookie") or ""),
                        rank_raw=rank,
                        value_raw=value,
                        tier_raw=str(row.get("tier") or ""),
                        universe=self.source_bucket,
                        format_key=self.format_key,
                        is_idp="idp" in self.source_bucket.lower(),
                        is_offense="offense" in self.source_bucket.lower(),
                        source_notes="KTC seed adapter (scaffold)",
                        metadata_json={
                            "profile_source": file_path.name,
                            "adapter": "ktc_stub",
                        },
                        name_normalized_guess=norm,
                        team_normalized_guess=team,
                        position_normalized_guess=pos,
                        pick_round_guess=None,
                        pick_slot_guess="",
                        pick_year_guess=None,
                    )
                )

        if not result.records:
            result.warnings.append(f"KTC stub seed file loaded but produced no usable rows: {file_path.name}")
        return result
