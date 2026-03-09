from __future__ import annotations

import csv
from pathlib import Path

from src.adapters.base import AdapterResult
from src.data_models import RawAssetRecord
from src.utils import normalize_player_name, normalize_position_family, normalize_team


def _first_present(row: dict[str, str], *keys: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        v = lowered.get(key.lower())
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_rank(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _safe_read_rows(file_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                rows.append({str(k): str(v or "") for k, v in row.items()})
        return rows, warnings
    except Exception as exc:  # noqa: BLE001 - fallback parser is intentional
        warnings.append(f"Normal CSV parse failed: {exc}; attempting tolerant parse.")

    # Tolerant fallback: split lines, re-parse each row individually.
    with file_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]

    if not lines:
        return rows, warnings

    try:
        header = next(csv.reader([lines[0]]))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Could not parse header row: {exc}")
        return rows, warnings

    bad_rows = 0
    for line in lines[1:]:
        try:
            parsed = next(csv.reader([line]))
            if len(parsed) < 2:
                bad_rows += 1
                continue
            # Normalize row length to header.
            if len(parsed) < len(header):
                parsed.extend([""] * (len(header) - len(parsed)))
            elif len(parsed) > len(header):
                parsed = parsed[: len(header)]
            rows.append(dict(zip(header, parsed)))
        except Exception:  # noqa: BLE001
            bad_rows += 1

    if bad_rows:
        warnings.append(f"Tolerant parse skipped {bad_rows} malformed row(s).")
    return rows, warnings


class DlfCsvAdapter:
    """Local DLF CSV adapter that uses Avg rank as the source signal."""

    def __init__(self, source_id: str, source_bucket: str, format_key: str = "dynasty_sf") -> None:
        self.source_id = source_id
        self.source_bucket = source_bucket
        self.format_key = format_key

    def load(self, file_path: Path) -> AdapterResult:
        result = AdapterResult(
            source_id=self.source_id,
            source_bucket=self.source_bucket,
            file_path=str(file_path),
        )
        if not file_path.exists():
            result.warnings.append(f"Missing file: {file_path}")
            return result

        rows, parse_warnings = _safe_read_rows(file_path)
        result.warnings.extend(parse_warnings)
        for row in rows:
            name = _first_present(row, "name", "player", "player_name")
            if not name:
                continue
            pos_raw = _first_present(row, "pos", "position")
            team_raw = _first_present(row, "team")
            avg_raw = _first_present(row, "avg", "average", "rank")
            avg_rank = _parse_rank(avg_raw)

            norm_name = normalize_player_name(name)
            if not norm_name:
                continue

            asset_key = f"player::{norm_name}"
            pos_guess = normalize_position_family(pos_raw)
            team_guess = normalize_team(team_raw)
            rec = RawAssetRecord(
                source=self.source_id,
                snapshot_id="",
                asset_type="player",
                external_asset_id=_first_present(row, "id", "player_id", "external_id"),
                external_name=name.strip(),
                display_name=name.strip(),
                team_raw=team_raw,
                position_raw=pos_raw,
                age_raw=_first_present(row, "age"),
                rookie_flag_raw=_first_present(row, "rookie", "rookie_flag"),
                rank_raw=avg_rank,
                value_raw=None,
                tier_raw=_first_present(row, "tier"),
                universe=self.source_bucket,
                format_key=self.format_key,
                is_idp="idp" in self.source_bucket.lower(),
                is_offense="offense" in self.source_bucket.lower(),
                source_notes="DLF Avg rank import",
                metadata_json={
                    "raw_avg": avg_raw,
                    "raw_pos": pos_raw,
                    "raw_team": team_raw,
                    "profile_source": file_path.name,
                },
                name_normalized_guess=norm_name,
                team_normalized_guess=team_guess,
                position_normalized_guess=pos_guess,
                asset_key=asset_key,
                pick_round_guess=None,
                pick_slot_guess="",
                pick_year_guess=None,
            )
            result.records.append(rec)
        return result
