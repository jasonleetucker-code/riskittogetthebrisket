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
    parser = argparse.ArgumentParser(description="Canonical build scaffold (universe-aware)")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--exponent", type=float, default=0.65)
    parser.add_argument("--jump-threshold", type=int, default=1800)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    _bootstrap_path(repo)

    from src.canonical import (
        KNOWN_UNIVERSES,
        TRANSFORM_VERSION,
        build_canonical_by_universe,
        detect_suspicious_value_jumps,
        flatten_canonical,
        rookie_universe_warnings,
    )
    from src.data_models import RawAssetRecord
    from src.utils import load_json, save_json

    raw_file = _latest(repo / "data" / "raw_sources", "raw_source_snapshot_*.json")
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

    weights_cfg = load_json(repo / "config" / "weights" / "default_weights.json", default={}) or {}
    source_weights = dict(weights_cfg.get("sources", {}))

    canonical_by_universe = build_canonical_by_universe(all_records, source_weights=source_weights, exponent=args.exponent)
    all_assets = flatten_canonical(canonical_by_universe)

    out_dir = repo / "data" / "canonical"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(raw_payload.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out_file = out_dir / f"canonical_snapshot_{run_id}.json"

    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_id": raw_payload.get("run_id", ""),
        "input_snapshot": raw_file.name,
        "transform_version": TRANSFORM_VERSION,
        "canonical_scale": 9999,
        "known_universes": sorted(KNOWN_UNIVERSES),
        "source_count": len({r.source for r in all_records}),
        "asset_count": len(all_assets),
        "asset_count_by_universe": {u: len(v) for u, v in canonical_by_universe.items()},
        "assets_by_universe": {
            u: [a.to_dict() for a in rows] for u, rows in canonical_by_universe.items()
        },
        "assets": [a.to_dict() for a in all_assets],
    }
    save_json(out_file, payload)

    # Validation outputs for this build
    validation_dir = repo / "data" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    validation_file = validation_dir / f"canonical_validation_{run_id}.json"

    prev_file = _second_latest(out_dir, "canonical_snapshot_*.json")
    prev_assets = []
    if prev_file and prev_file.exists():
        prev_payload = load_json(prev_file, default={}) or {}
        for row in prev_payload.get("assets", []):
            # Minimal structure for jump check
            from src.data_models import CanonicalAssetValue

            prev_assets.append(
                CanonicalAssetValue(
                    asset_key=row.get("asset_key", ""),
                    display_name=row.get("display_name", ""),
                    universe=row.get("universe", ""),
                    source_values=dict(row.get("source_values", {})),
                    blended_value=int(row.get("blended_value", 0)),
                    source_weights_used=dict(row.get("source_weights_used", {})),
                    metadata=dict(row.get("metadata", {})),
                )
            )

    suspicious_jumps = detect_suspicious_value_jumps(
        current_assets=all_assets,
        previous_assets=prev_assets,
        jump_threshold=args.jump_threshold,
    )
    rookie_warn = rookie_universe_warnings(all_records)

    identity_file = _latest(repo / "data" / "identity", "identity_resolution_*.json")
    if identity_file is None:
        identity_file = _latest(repo / "data" / "identity", "identity_report_*.json")
    identity_payload = load_json(identity_file, default={}) if identity_file else {}

    validation_payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_snapshot": raw_file.name,
        "previous_canonical_snapshot": prev_file.name if prev_file else None,
        "suspicious_jump_count": len(suspicious_jumps),
        "suspicious_jumps": suspicious_jumps,
        "rookie_universe_warning_count": len(rookie_warn),
        "rookie_universe_warnings": rookie_warn,
        "unmatched_asset_count": int(identity_payload.get("unresolved_count", 0)),
        "low_confidence_match_count": int(identity_payload.get("low_confidence_count", 0)),
        "duplicate_alias_count": int(identity_payload.get("duplicate_alias_count", 0)),
    }
    save_json(validation_file, validation_payload)

    print(f"[canonical_build] wrote {out_file}")
    print(f"[canonical_build] source_count={payload['source_count']} asset_count={payload['asset_count']}")
    print(
        f"[canonical_build] validation jumps={len(suspicious_jumps)} "
        f"rookie_warn={len(rookie_warn)} unmatched={validation_payload['unmatched_asset_count']} "
        f"low_conf={validation_payload['low_confidence_match_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

