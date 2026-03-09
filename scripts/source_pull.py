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
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.adapters import DlfCsvAdapter
    from src.data_models import RawSourceSnapshot, utc_now_iso
    from src.utils import load_json, save_json

    cfg_path = repo / "config" / "sources" / "dlf_sources.template.json"
    cfg = load_json(cfg_path, default={"sources": []}) or {"sources": []}

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo / "data" / "raw_sources"
    out_dir.mkdir(parents=True, exist_ok=True)

    run_payload: dict = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "snapshots": [],
        "warnings": [],
    }

    for src_cfg in cfg.get("sources", []):
        source_id = str(src_cfg.get("source_id", "")).strip()
        source_bucket = str(src_cfg.get("source_bucket", "")).strip()
        rel_file = str(src_cfg.get("file", "")).strip()
        if not source_id or not rel_file:
            run_payload["warnings"].append(f"Skipping invalid source config: {src_cfg}")
            continue

        adapter = DlfCsvAdapter(source_id=source_id, source_bucket=source_bucket)
        file_path = repo / rel_file
        result = adapter.load(file_path)
        snapshot = RawSourceSnapshot(
            snapshot_id=f"{source_id}:{run_id}",
            created_at=utc_now_iso(),
            source_id=source_id,
            source_bucket=source_bucket,
            records=result.records,
            warnings=result.warnings,
        )
        run_payload["snapshots"].append(snapshot.to_dict())

    out_file = out_dir / f"raw_source_snapshot_{run_id}.json"
    save_json(out_file, run_payload)

    total_records = sum(len(s.get("records", [])) for s in run_payload["snapshots"])
    total_sources = len(run_payload["snapshots"])
    print(f"[source_pull] wrote {out_file}")
    print(f"[source_pull] sources={total_sources} records={total_records}")
    if run_payload["warnings"]:
        print(f"[source_pull] warnings={len(run_payload['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

