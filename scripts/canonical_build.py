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

from scripts._shared import _latest


def _bootstrap_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _second_latest(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), reverse=True)
    return files[1] if len(files) > 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical build scaffold (universe-aware)")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--exponent", type=float, default=0.65)
    parser.add_argument("--jump-threshold", type=int, default=1800)
    parser.add_argument(
        "--engine", choices=["legacy", "canonical"], default="legacy",
        help="Valuation engine: 'legacy' (percentile blend + calibration) or "
             "'canonical' (6-step rank-based pipeline from player_valuation.py)",
    )
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
    from src.data_models import CanonicalAssetValue, RawAssetRecord
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

    # ── Value engine selection ──
    use_canonical_engine = args.engine == "canonical"

    if use_canonical_engine:
        from src.canonical.player_valuation import (
            build_player_inputs_from_record_objects,
            run_valuation,
            valuation_result_to_asset_dicts,
        )
        from src.canonical.transform import split_by_universe as _split

        grouped = _split(all_records)
        asset_dicts: list[dict] = []
        valuation_summaries: dict[str, dict] = {}

        for universe, universe_records in grouped.items():
            player_inputs = build_player_inputs_from_record_objects(universe_records)
            if not player_inputs:
                continue
            result = run_valuation(player_inputs)
            universe_assets = valuation_result_to_asset_dicts(result, universe)
            asset_dicts.extend(universe_assets)
            valuation_summaries[universe] = {
                "player_count": len(result.players),
                "tier_count": result.tier_count,
                "monotonic_clamp_count": result.monotonic_clamp_count,
                "hyperparameters": result.hyperparameters,
            }

        asset_dicts.sort(key=lambda a: a.get("blended_value", 0), reverse=True)
        # Build a lightweight all_assets list for jump detection
        all_assets = [
            CanonicalAssetValue(
                asset_key=a["asset_key"], display_name=a["display_name"],
                universe=a["universe"], source_values=a.get("source_values", {}),
                blended_value=a.get("blended_value", 0),
            )
            for a in asset_dicts
        ]
        canonical_by_universe = {}
        for a in all_assets:
            canonical_by_universe.setdefault(a.universe, []).append(a)
        print(f"[canonical_build] engine=canonical, {len(asset_dicts)} assets across {len(valuation_summaries)} universes")
        for u, s in sorted(valuation_summaries.items()):
            print(f"  {u}: {s['player_count']} players, {s['tier_count']} tiers, {s['monotonic_clamp_count']} clamps")
    else:
        canonical_by_universe = build_canonical_by_universe(all_records, source_weights=source_weights, exponent=args.exponent)
        all_assets = flatten_canonical(canonical_by_universe)
        asset_dicts = [a.to_dict() for a in all_assets]
        valuation_summaries = None

    out_dir = repo / "data" / "canonical"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(raw_payload.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out_file = out_dir / f"canonical_snapshot_{run_id}.json"

    # Position enrichment from legacy player data
    enrichment_summary = None
    legacy_file = _latest(repo / "data", "legacy_data_*.json")
    if legacy_file:
        try:
            from src.canonical.enrich import (
                build_legacy_position_lookup,
                build_player_map_lookup,
                enrich_positions,
            )
            legacy_lookup = build_legacy_position_lookup(legacy_file)

            # Load nickname lookup from exported player map if available
            player_map_path = repo / "data" / "player_map" / "player_position_map.json"
            nickname_lookup = {}
            if player_map_path.exists():
                _, nickname_lookup = build_player_map_lookup(player_map_path)

            supplemental_path = repo / "data" / "player_map" / "supplemental_positions.json"
            asset_dicts, enrichment_summary = enrich_positions(
                asset_dicts, legacy_lookup, nickname_lookup,
                infer_idp=True,
                supplemental_path=supplemental_path if supplemental_path.exists() else None,
            )
            print(
                f"[canonical_build] enrichment: {enrichment_summary['enriched_from_legacy']} legacy, "
                f"{enrichment_summary['enriched_from_nickname']} nickname, "
                f"{enrichment_summary.get('enriched_from_supplemental', 0)} supplemental, "
                f"{enrichment_summary['enriched_from_universe_infer']} IDP inferred, "
                f"{enrichment_summary['already_had_position']} adapter, "
                f"{enrichment_summary['skipped_picks']} picks, "
                f"{enrichment_summary['unmatched']} unmatched → "
                f"{enrichment_summary['position_coverage_pct']}% coverage"
            )
        except Exception as e:
            print(f"[canonical_build] enrichment skipped: {e}")

    # Distribution calibration: remap values to match legacy-like distribution
    # Skipped when using the canonical engine — values are already display-scaled.
    calibration_params = None
    if not use_canonical_engine:
        try:
            from src.canonical.calibration import calibrate_canonical_values, get_calibration_params
            asset_dicts = calibrate_canonical_values(asset_dicts, legacy_path=legacy_file)
            calibration_params = get_calibration_params()
            cal_vals = [a.get("calibrated_value", 0) for a in asset_dicts if a.get("calibrated_value") is not None]
            if cal_vals:
                uni_scales = calibration_params.get('universe_scales', {})
                scales_str = ", ".join(f"{k}={v}" for k, v in sorted(uni_scales.items()))
                print(
                    f"[canonical_build] calibration: {len(cal_vals)} assets, "
                    f"range {min(cal_vals)}-{max(cal_vals)}, "
                    f"exponent={calibration_params['exponent']}, "
                    f"pick_ceiling={calibration_params.get('pick_ceiling', 'n/a')}, "
                    f"scales=[{scales_str}]"
                )
        except Exception as e:
            print(f"[canonical_build] calibration skipped: {e}")

    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_id": raw_payload.get("run_id", ""),
        "input_snapshot": raw_file.name,
        "transform_version": TRANSFORM_VERSION,
        "valuation_engine": "canonical" if use_canonical_engine else "legacy",
        "canonical_scale": 9999,
        "known_universes": sorted(KNOWN_UNIVERSES),
        "source_count": len({r.source for r in all_records}),
        "asset_count": len(all_assets),
        "asset_count_by_universe": {u: len(v) for u, v in canonical_by_universe.items()},
        "assets_by_universe": {
            u: [a.to_dict() for a in rows] for u, rows in canonical_by_universe.items()
        } if not use_canonical_engine else {},
        "assets": asset_dicts,
        "enrichment_summary": enrichment_summary,
        "calibration": calibration_params,
        "valuation_summaries": valuation_summaries,
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

    # Per-source contribution summary for operator visibility.
    from collections import Counter
    source_record_counts = Counter(r.source for r in all_records)
    source_asset_counts: dict[str, int] = {}
    for asset_dict in asset_dicts:
        for src in asset_dict.get("source_values", {}):
            source_asset_counts[src] = source_asset_counts.get(src, 0) + 1
    contrib_parts = []
    for src in sorted(source_record_counts):
        records = source_record_counts[src]
        assets = source_asset_counts.get(src, 0)
        contrib_parts.append(f"{src}={records}r/{assets}a")
    print(f"[canonical_build] sources: {', '.join(contrib_parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

