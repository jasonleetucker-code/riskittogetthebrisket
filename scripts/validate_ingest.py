#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), reverse=True)
    return files[0] if files else None


def _second_latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), reverse=True)
    return files[1] if len(files) > 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate raw ingest outputs")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.utils import load_json, save_json

    raw_dir = repo / "data" / "raw_sources"
    raw_file = _latest(raw_dir, "raw_source_snapshot_*.json")
    if raw_file is None:
        print("[validate_ingest] No raw snapshot found. Run source_pull first.")
        return 0
    prev_raw_file = _second_latest(raw_dir, "raw_source_snapshot_*.json")

    payload = load_json(raw_file, default={}) or {}
    snapshots = payload.get("snapshots", [])

    required_snapshot_fields = [
        "source",
        "snapshot_id",
        "pulled_at_utc",
        "season",
        "format_key",
        "universe",
        "ingest_type",
        "source_url",
        "raw_storage_path",
        "record_count",
        "adapter_version",
    ]
    required_asset_fields = [
        "source",
        "snapshot_id",
        "asset_type",
        "external_asset_id",
        "external_name",
        "display_name",
        "team_raw",
        "position_raw",
        "age_raw",
        "rookie_flag_raw",
        "rank_raw",
        "value_raw",
        "tier_raw",
        "universe",
        "format_key",
        "is_idp",
        "is_offense",
        "source_notes",
        "metadata_json",
    ]

    missing_snapshot_fields: list[dict] = []
    missing_asset_fields: list[dict] = []
    duplicate_external_ids: list[dict] = []
    universe_sanity_issues: list[dict] = []
    rookie_universe_warnings: list[dict] = []
    suspicious_rank_value_jumps: list[dict] = []

    # source + external id should be unique within snapshot
    ext_seen: dict[tuple[str, str, str], str] = {}
    current_metrics: dict[tuple[str, str], dict] = {}

    for snap in snapshots:
        for field in required_snapshot_fields:
            if field not in snap:
                missing_snapshot_fields.append(
                    {"snapshot_id": snap.get("snapshot_id", ""), "missing_field": field}
                )

        source = str(snap.get("source", ""))
        sid = str(snap.get("snapshot_id", ""))
        universe = str(snap.get("universe", "")).lower()
        records = snap.get("records", []) or []

        rec_count = len(records)
        if "rookie" in universe and rec_count > 250:
            rookie_universe_warnings.append(
                {
                    "snapshot_id": sid,
                    "source": source,
                    "warning": "rookie_universe_has_large_record_count",
                    "record_count": rec_count,
                }
            )
        if "rookie" not in universe and rec_count < 60:
            rookie_universe_warnings.append(
                {
                    "snapshot_id": sid,
                    "source": source,
                    "warning": "non_rookie_universe_has_small_record_count",
                    "record_count": rec_count,
                }
            )

        for idx, rec in enumerate(records, start=1):
            for field in required_asset_fields:
                if field not in rec:
                    missing_asset_fields.append(
                        {"snapshot_id": sid, "row": idx, "missing_field": field}
                    )

            ext_id = str(rec.get("external_asset_id", "")).strip()
            key_asset = str(rec.get("asset_key", "")).strip() or str(rec.get("name_normalized_guess", "")).strip()
            if key_asset:
                current_metrics[(source, key_asset)] = {
                    "rank_raw": rec.get("rank_raw"),
                    "value_raw": rec.get("value_raw"),
                    "display_name": rec.get("display_name", ""),
                    "snapshot_id": sid,
                }
            if ext_id:
                key = (source, sid, ext_id)
                owner = ext_seen.get(key)
                this_name = str(rec.get("display_name", ""))
                if owner is None:
                    ext_seen[key] = this_name
                elif owner != this_name:
                    duplicate_external_ids.append(
                        {
                            "snapshot_id": sid,
                            "source": source,
                            "external_asset_id": ext_id,
                            "first_name": owner,
                            "second_name": this_name,
                        }
                    )

            is_idp = bool(rec.get("is_idp", False))
            is_offense = bool(rec.get("is_offense", False))
            if "idp" in universe and not is_idp:
                universe_sanity_issues.append(
                    {
                        "snapshot_id": sid,
                        "source": source,
                        "display_name": rec.get("display_name", ""),
                        "issue": "idp_universe_but_is_idp_false",
                    }
                )
            if "offense" in universe and not is_offense:
                universe_sanity_issues.append(
                    {
                        "snapshot_id": sid,
                        "source": source,
                        "display_name": rec.get("display_name", ""),
                        "issue": "offense_universe_but_is_offense_false",
                    }
                )

    if prev_raw_file and prev_raw_file.exists():
        prev_payload = load_json(prev_raw_file, default={}) or {}
        prev_metrics: dict[tuple[str, str], dict] = {}
        for snap in prev_payload.get("snapshots", []):
            psource = str(snap.get("source", ""))
            for rec in snap.get("records", []):
                pkey = str(rec.get("asset_key", "")).strip() or str(rec.get("name_normalized_guess", "")).strip()
                if not pkey:
                    continue
                prev_metrics[(psource, pkey)] = {
                    "rank_raw": rec.get("rank_raw"),
                    "value_raw": rec.get("value_raw"),
                    "display_name": rec.get("display_name", ""),
                }
        for k, cur in current_metrics.items():
            prev = prev_metrics.get(k)
            if not prev:
                continue
            cur_rank = cur.get("rank_raw")
            prev_rank = prev.get("rank_raw")
            cur_val = cur.get("value_raw")
            prev_val = prev.get("value_raw")
            rank_jump = None
            value_jump = None
            if isinstance(cur_rank, (int, float)) and isinstance(prev_rank, (int, float)):
                rank_jump = float(cur_rank) - float(prev_rank)
            if isinstance(cur_val, (int, float)) and isinstance(prev_val, (int, float)):
                value_jump = float(cur_val) - float(prev_val)

            if (rank_jump is not None and abs(rank_jump) >= 100) or (value_jump is not None and abs(value_jump) >= 1500):
                suspicious_rank_value_jumps.append(
                    {
                        "source": k[0],
                        "asset_key": k[1],
                        "display_name": cur.get("display_name", ""),
                        "rank_jump": rank_jump,
                        "value_jump": value_jump,
                    }
                )

    status = "pass"
    if missing_snapshot_fields or missing_asset_fields:
        status = "fail"
    elif duplicate_external_ids or universe_sanity_issues or suspicious_rank_value_jumps:
        status = "warn"

    run_id = str(payload.get("run_id", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    out_dir = repo / "data" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"ingest_validation_{run_id}.json"

    report = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_snapshot": raw_file.name,
        "snapshot_count": len(snapshots),
        "missing_snapshot_field_count": len(missing_snapshot_fields),
        "missing_asset_field_count": len(missing_asset_fields),
        "duplicate_external_id_count": len(duplicate_external_ids),
        "universe_sanity_issue_count": len(universe_sanity_issues),
        "rookie_universe_warning_count": len(rookie_universe_warnings),
        "suspicious_rank_value_jump_count": len(suspicious_rank_value_jumps),
        "missing_snapshot_fields": missing_snapshot_fields,
        "missing_asset_fields": missing_asset_fields,
        "duplicate_external_ids": duplicate_external_ids,
        "universe_sanity_issues": universe_sanity_issues,
        "rookie_universe_warnings": rookie_universe_warnings,
        "suspicious_rank_value_jumps": suspicious_rank_value_jumps,
    }
    save_json(out_file, report)

    print(
        "[validate_ingest] "
        f"status={status} "
        f"missing_snapshot={len(missing_snapshot_fields)} "
        f"missing_asset={len(missing_asset_fields)} "
        f"dup_ext={len(duplicate_external_ids)} "
        f"universe={len(universe_sanity_issues)} "
        f"rookie_warn={len(rookie_universe_warnings)} "
        f"jump_warn={len(suspicious_rank_value_jumps)}"
    )
    print(f"[validate_ingest] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
