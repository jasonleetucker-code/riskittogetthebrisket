"""Adapter that reads per-site CSV exports from the legacy scraper.

The legacy scraper (``Dynasty Scraper.py``) writes per-site raw data to
``exports/latest/site_raw/{key}.csv`` in a uniform ``name,value`` format.
This adapter reads those CSVs and produces :class:`RawAssetRecord` objects
suitable for the canonical pipeline, without performing any live scraping.

Supports two signal types:

* ``value`` (default) — higher numbers are better (KTC, FantasyCalc, etc.)
* ``rank`` — lower numbers are better (DynastyNerds, PFF IDP, etc.)

When ``signal_type="value"``, the CSV's ``value`` column is stored as
``value_raw`` on the record.  When ``signal_type="rank"``, it is stored
as ``rank_raw`` instead.
"""
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


class ScraperBridgeAdapter:
    """Read a ``name,value`` CSV exported by the legacy scraper."""

    def __init__(
        self,
        source_id: str,
        source_bucket: str,
        format_key: str = "dynasty_sf",
        signal_type: str = "value",
    ) -> None:
        self.source_id = source_id
        self.source_bucket = source_bucket
        self.format_key = format_key
        if signal_type not in ("value", "rank"):
            raise ValueError(f"signal_type must be 'value' or 'rank', got {signal_type!r}")
        self.signal_type = signal_type

    def load(self, file_path: Path) -> AdapterResult:
        result = AdapterResult(
            source_id=self.source_id,
            source_bucket=self.source_bucket,
            file_path=str(file_path) if file_path else "",
        )
        if not file_path or not file_path.is_file():
            result.warnings.append(
                f"Scraper bridge: file not found — {file_path}. "
                "Run the legacy scraper to produce exports/latest/site_raw/ CSVs."
            )
            return result

        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
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

                raw_signal = _safe_float(row.get("value") or row.get("rank"))
                if raw_signal is None:
                    continue

                if self.signal_type == "rank":
                    rank_raw = raw_signal
                    value_raw = None
                else:
                    rank_raw = None
                    value_raw = raw_signal

                pos = normalize_position_family(str(row.get("pos") or row.get("position") or ""))
                team = normalize_team(str(row.get("team") or ""))

                result.records.append(
                    RawAssetRecord(
                        source=self.source_id,
                        snapshot_id="",
                        asset_type="player",
                        external_asset_id="",
                        external_name=name,
                        asset_key=f"player::{norm}",
                        display_name=name,
                        team_raw=str(row.get("team") or ""),
                        position_raw=str(row.get("pos") or row.get("position") or ""),
                        age_raw="",
                        rookie_flag_raw="",
                        rank_raw=rank_raw,
                        value_raw=value_raw,
                        tier_raw="",
                        universe=self.source_bucket,
                        format_key=self.format_key,
                        is_idp="idp" in self.source_bucket.lower(),
                        is_offense="offense" in self.source_bucket.lower(),
                        source_notes=f"Scraper bridge ({self.source_id}, signal={self.signal_type})",
                        metadata_json={
                            "profile_source": file_path.name,
                            "adapter": "scraper_bridge",
                            "signal_type": self.signal_type,
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
            result.warnings.append(
                f"Scraper bridge: file loaded but produced no usable rows — {file_path.name}"
            )
        return result
