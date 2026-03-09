#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _latest_raw_snapshot(raw_dir: Path) -> Path | None:
    files = sorted(raw_dir.glob("raw_source_snapshot_*.json"), reverse=True)
    return files[0] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 canonical build scaffold")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.canonical import blend_source_values, bucket_and_canonicalize
    from src.data_models import RawAssetRecord
    from src.utils import load_json, save_json

    raw_dir = repo / "data" / "raw_sources"
    raw_file = _latest_raw_snapshot(raw_dir)
    if raw_file is None:
        print("[canonical_build] No raw source snapshot found. Run source_pull first.")
        return 0

    raw_payload = load_json(raw_file, default={}) or {}
    snapshots = raw_payload.get("snapshots", [])

    all_records: list[RawAssetRecord] = []
    for snap in snapshots:
        for r in snap.get("records", []):
            all_records.append(
                RawAssetRecord(
                    asset_key=r.get("asset_key", ""),
                    display_name=r.get("display_name", ""),
                    asset_type=r.get("asset_type", "player"),
                    source_id=r.get("source_id", ""),
                    source_bucket=r.get("source_bucket", ""),
                    rank=r.get("rank"),
                    raw_value=r.get("raw_value"),
                    position=r.get("position"),
                    team=r.get("team"),
                    rookie_flag=bool(r.get("rookie_flag", False)),
                    metadata=dict(r.get("metadata", {})),
                )
            )

    per_source_scores = bucket_and_canonicalize(all_records)
    weights_cfg = load_json(repo / "config" / "weights" / "default_weights.json", default={}) or {}
    source_weights = dict(weights_cfg.get("sources", {}))
    blended = blend_source_values(per_source_scores, source_weights=source_weights)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo / "data" / "canonical"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"canonical_snapshot_{run_id}.json"

    payload = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "input_snapshot": raw_file.name,
        "source_count": len(per_source_scores),
        "asset_count": len(blended),
        "assets": [a.to_dict() for a in blended],
    }
    save_json(out_file, payload)

    print(f"[canonical_build] wrote {out_file}")
    print(f"[canonical_build] source_count={payload['source_count']} asset_count={payload['asset_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

