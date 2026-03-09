#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 source pull scaffold")
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
    from src.data_models import RawAssetRecord, RawSourceSnapshot, utc_now_iso
    from src.identity import build_identity_report
    from src.utils import load_json, save_json

    cfg_path = (repo / args.config).resolve()
    cfg = load_json(cfg_path, default={"sources": []}) or {"sources": []}

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo / "data" / "raw_sources"
    out_dir.mkdir(parents=True, exist_ok=True)
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
        source_id = str(src_cfg.get("source_id", "")).strip()
        source_bucket = str(src_cfg.get("source_bucket", "")).strip()
        adapter_kind = str(src_cfg.get("adapter", "dlf_csv")).strip().lower()
        rel_file = str(src_cfg.get("file", "")).strip()
        if not enabled:
            run_payload["warnings"].append(f"Skipping disabled source: {source_id or src_cfg}")
            continue
        if not source_id:
            run_payload["warnings"].append(f"Skipping invalid source config: {src_cfg}")
            continue

        if adapter_kind in {"dlf_csv", "dlf"}:
            adapter = DlfCsvAdapter(source_id=source_id, source_bucket=source_bucket)
        elif adapter_kind in {"ktc_stub", "ktc"}:
            adapter = KtcStubAdapter(source_id=source_id, source_bucket=source_bucket)
        elif adapter_kind in {"manual_csv", "manual"}:
            adapter = ManualCsvAdapter(source_id=source_id, source_bucket=source_bucket)
        else:
            run_payload["warnings"].append(f"Unknown adapter '{adapter_kind}' for source {source_id}")
            continue

        file_path = (repo / rel_file).resolve() if rel_file else Path("")
        result = adapter.load(file_path)
        all_records.extend(result.records)
        snapshot = RawSourceSnapshot(
            snapshot_id=f"{source_id}:{run_id}",
            created_at=utc_now_iso(),
            source_id=source_id,
            source_bucket=source_bucket,
            records=result.records,
            warnings=result.warnings,
        )
        run_payload["snapshots"].append(snapshot.to_dict())

    identity_report = build_identity_report(all_records)
    identity_report["run_id"] = run_id
    identity_report["created_at"] = utc_now_iso()
    identity_file = identity_dir / f"identity_report_{run_id}.json"
    save_json(identity_file, identity_report)

    out_file = out_dir / f"raw_source_snapshot_{run_id}.json"
    save_json(out_file, run_payload)

    total_records = sum(len(s.get("records", [])) for s in run_payload["snapshots"])
    total_sources = len(run_payload["snapshots"])
    print(f"[source_pull] wrote {out_file}")
    print(f"[source_pull] sources={total_sources} records={total_records}")
    print(
        "[source_pull] identity "
        f"master={identity_report.get('master_player_count', 0)} "
        f"single_source={identity_report.get('single_source_count', 0)} "
        f"conflicts={identity_report.get('conflict_count', 0)} "
        f"-> {identity_file}"
    )
    if run_payload["warnings"]:
        print(f"[source_pull] warnings={len(run_payload['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
