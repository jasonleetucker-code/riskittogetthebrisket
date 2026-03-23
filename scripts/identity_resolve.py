#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


from scripts._shared import _latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve identity for latest raw snapshot")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--quarantine-threshold", type=float, default=0.90)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.data_models import RawAssetRecord
    from src.identity import build_identity_resolution
    from src.utils import load_json, save_json

    raw_file = _latest(repo / "data" / "raw_sources", "raw_source_snapshot_*.json")
    if raw_file is None:
        print("[identity_resolve] No raw snapshot found. Run source_pull first.")
        return 0

    raw_payload = load_json(raw_file, default={}) or {}
    snapshots = raw_payload.get("snapshots", [])
    all_records: list[RawAssetRecord] = []
    for snap in snapshots:
        for r in snap.get("records", []):
            all_records.append(
                RawAssetRecord(
                    source=r.get("source", ""),
                    snapshot_id=r.get("snapshot_id", ""),
                    asset_type=r.get("asset_type", "player"),
                    external_asset_id=r.get("external_asset_id", ""),
                    external_name=r.get("external_name", ""),
                    display_name=r.get("display_name", ""),
                    team_raw=r.get("team_raw", ""),
                    position_raw=r.get("position_raw", ""),
                    age_raw=r.get("age_raw", ""),
                    rookie_flag_raw=r.get("rookie_flag_raw", ""),
                    rank_raw=r.get("rank_raw"),
                    value_raw=r.get("value_raw"),
                    tier_raw=r.get("tier_raw", ""),
                    universe=r.get("universe", ""),
                    format_key=r.get("format_key", ""),
                    is_idp=bool(r.get("is_idp", False)),
                    is_offense=bool(r.get("is_offense", False)),
                    source_notes=r.get("source_notes", ""),
                    metadata_json=dict(r.get("metadata_json", {})),
                    name_normalized_guess=r.get("name_normalized_guess", ""),
                    team_normalized_guess=r.get("team_normalized_guess", ""),
                    position_normalized_guess=r.get("position_normalized_guess", ""),
                    pick_round_guess=r.get("pick_round_guess"),
                    pick_slot_guess=r.get("pick_slot_guess", ""),
                    pick_year_guess=r.get("pick_year_guess"),
                    asset_key=r.get("asset_key", ""),
                )
            )

    identity = build_identity_resolution(all_records, quarantine_threshold=args.quarantine_threshold)
    identity["input_snapshot"] = raw_file.name
    identity["run_id"] = str(raw_payload.get("run_id", ""))
    identity["generated_at"] = datetime.now(timezone.utc).isoformat()

    out_dir = repo / "data" / "identity"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"identity_resolution_{identity.get('run_id') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    save_json(out_file, identity)

    print(
        "[identity_resolve] "
        f"players={identity.get('master_player_count', 0)} "
        f"unresolved={identity.get('unresolved_count', 0)} "
        f"low_conf={identity.get('low_confidence_count', 0)} "
        f"dup_alias={identity.get('duplicate_alias_count', 0)}"
    )
    print(f"[identity_resolve] wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

