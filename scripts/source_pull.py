#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_folder_name(source: str) -> str:
    return source.strip().lower().replace(" ", "_")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _build_snapshot_id(source: str, season: str, run_id: str) -> str:
    return f"{source.lower()}_{season}_{run_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Source ingest scaffold with provenance + manifest output")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--config",
        default="config/sources/dlf_sources.template.json",
        help="Source config JSON (relative to repo root)",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.adapters import DlfCsvAdapter, KtcStubAdapter, ManualCsvAdapter
    from src.data_models import RawAssetRecord, RawSourceSnapshot, SourceManifest, utc_now_iso
    from src.identity import build_identity_resolution
    from src.utils import load_json, normalize_player_name

    cfg_path = (repo / args.config).resolve()
    cfg = load_json(cfg_path, default={"sources": []}) or {"sources": []}
    season_default = str(cfg.get("season_default", "unknown"))
    format_default = str(cfg.get("format_key_default", "dynasty_sf"))

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    raw_root = repo / "data" / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_summary_dir = repo / "data" / "raw_sources"
    raw_summary_dir.mkdir(parents=True, exist_ok=True)
    identity_dir = repo / "data" / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)

    run_payload: dict = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "config_file": str(cfg_path),
        "snapshots": [],
        "warnings": [],
    }
    all_records: list[RawAssetRecord] = []

    for src_cfg in cfg.get("sources", []):
        enabled = bool(src_cfg.get("enabled", True))
        if not enabled:
            continue

        source = str(src_cfg.get("source", src_cfg.get("source_id", ""))).strip()
        season = str(src_cfg.get("season", season_default)).strip() or season_default
        universe = str(src_cfg.get("universe", src_cfg.get("source_bucket", ""))).strip()
        format_key = str(src_cfg.get("format_key", format_default)).strip() or format_default
        ingest_type = str(src_cfg.get("ingest_type", "manual_csv")).strip()
        ingest_method = str(src_cfg.get("ingest_method", ingest_type)).strip()
        source_url = str(src_cfg.get("source_url", "")).strip()
        scoring_context = str(src_cfg.get("scoring_context", "")).strip()
        adapter_kind = str(src_cfg.get("adapter", "dlf_csv")).strip().lower()
        adapter_version = str(src_cfg.get("adapter_version", "1.0.0")).strip()
        notes = str(src_cfg.get("notes", "")).strip()
        rel_file = str(src_cfg.get("file", "")).strip()

        if not source:
            run_payload["warnings"].append(f"Skipping invalid source config (missing source): {src_cfg}")
            continue

        snapshot_id = _build_snapshot_id(source, season, run_id)
        snapshot_dir = raw_root / _source_folder_name(source) / season / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        raw_input_path = (repo / rel_file).resolve() if rel_file else None
        stored_raw_path = Path("")
        file_hash = ""
        parse_warnings: list[str] = []
        if raw_input_path and raw_input_path.exists():
            stored_raw_path = snapshot_dir / raw_input_path.name
            shutil.copy2(raw_input_path, stored_raw_path)
            file_hash = _sha256(stored_raw_path)
        else:
            parse_warnings.append(f"Raw input file missing: {raw_input_path if raw_input_path else '<not provided>'}")

        if adapter_kind in {"dlf_csv", "dlf"}:
            adapter = DlfCsvAdapter(source_id=source, source_bucket=universe, format_key=format_key)
        elif adapter_kind in {"ktc_stub", "ktc"}:
            adapter = KtcStubAdapter(source_id=source, source_bucket=universe, format_key=format_key)
        elif adapter_kind in {"manual_csv", "manual"}:
            adapter = ManualCsvAdapter(source_id=source, source_bucket=universe)
        else:
            run_payload["warnings"].append(f"Unknown adapter '{adapter_kind}' for source {source}")
            continue

        adapter_input = stored_raw_path if stored_raw_path and stored_raw_path.exists() else Path("")
        result = adapter.load(adapter_input)
        parse_warnings.extend(result.warnings)

        normalized_records: list[RawAssetRecord] = []
        for rec in result.records:
            rec.source = source
            rec.snapshot_id = snapshot_id
            rec.universe = universe or rec.universe
            rec.format_key = format_key or rec.format_key
            rec.source_notes = rec.source_notes or notes

            if not rec.asset_key:
                if rec.asset_type == "player":
                    nm = rec.name_normalized_guess or normalize_player_name(rec.display_name)
                    rec.asset_key = f"player::{nm}" if nm else f"player::{rec.display_name.lower()}"
                else:
                    rec.asset_key = rec.external_asset_id or rec.display_name
            normalized_records.append(rec)
            all_records.append(rec)

        normalized_rows = [r.to_dict() for r in normalized_records]
        normalized_path = snapshot_dir / "assets.normalized.jsonl"
        _write_jsonl(normalized_path, normalized_rows)

        manifest = SourceManifest(
            source=source,
            snapshot_id=snapshot_id,
            pulled_at_utc=utc_now_iso(),
            season=season,
            scoring_context=scoring_context,
            universe=universe,
            ingest_method=ingest_method,
            ingest_type=ingest_type,
            source_url=source_url,
            format_key=format_key,
            raw_file_path=str(raw_input_path) if raw_input_path else "",
            raw_storage_path=str(snapshot_dir),
            record_count=len(normalized_rows),
            hash=file_hash,
            notes=notes,
            adapter_version=adapter_version,
            inserted_by="codex_pipeline",
        )
        manifest_path = snapshot_dir / "manifest.json"
        _write_json(manifest_path, manifest.to_dict())

        parse_log_payload = {
            "source": source,
            "snapshot_id": snapshot_id,
            "adapter": adapter_kind,
            "record_count": len(normalized_rows),
            "warnings": parse_warnings,
        }
        parse_log_path = snapshot_dir / "parse_log.json"
        _write_json(parse_log_path, parse_log_payload)

        snapshot = RawSourceSnapshot(
            source=source,
            snapshot_id=snapshot_id,
            pulled_at_utc=utc_now_iso(),
            season=season,
            format_key=format_key,
            universe=universe,
            ingest_type=ingest_type,
            source_url=source_url,
            raw_storage_path=str(snapshot_dir),
            record_count=len(normalized_rows),
            adapter_version=adapter_version,
            scoring_context=scoring_context,
            ingest_method=ingest_method,
            raw_file_path=str(raw_input_path) if raw_input_path else "",
            hash=file_hash,
            notes=notes,
            parse_log_path=str(parse_log_path),
            manifest_path=str(manifest_path),
            records=normalized_records,
            warnings=parse_warnings,
        )
        run_payload["snapshots"].append(snapshot.to_dict())

    identity_resolution = build_identity_resolution(all_records)
    identity_resolution["run_id"] = run_id
    identity_resolution["created_at"] = utc_now_iso()
    identity_file = identity_dir / f"identity_report_{run_id}.json"
    _write_json(identity_file, identity_resolution)

    out_file = raw_summary_dir / f"raw_source_snapshot_{run_id}.json"
    _write_json(out_file, run_payload)

    total_records = sum(len(s.get("records", [])) for s in run_payload["snapshots"])
    total_sources = len(run_payload["snapshots"])
    print(f"[source_pull] wrote {out_file}")
    print(f"[source_pull] sources={total_sources} records={total_records}")
    print(
        "[source_pull] identity "
        f"master={identity_resolution.get('master_player_count', 0)} "
        f"single_source={identity_resolution.get('single_source_count', 0)} "
        f"conflicts={identity_resolution.get('conflict_count', 0)} "
        f"low_conf={identity_resolution.get('low_confidence_count', 0)} "
        f"-> {identity_file}"
    )
    if run_payload["warnings"]:
        print(f"[source_pull] warnings={len(run_payload['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
