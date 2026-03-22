#!/usr/bin/env python3
"""Check whether the canonical pipeline meets promotion thresholds.

Evaluates the current state against the machine-readable promotion
thresholds in config/promotion/promotion_thresholds.json.

Usage:
    python scripts/check_promotion_readiness.py [--target shadow|internal_primary|public_primary]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _latest_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern), reverse=True)
    return files[0] if files else None


def _load_thresholds(repo: Path, mode: str) -> dict:
    """Load promotion thresholds for *mode* from config, with hard-coded fallbacks.

    The config file is the intended source of truth.  If it is missing or
    malformed the function returns safe hard-coded defaults so the script
    never crashes on a missing config.
    """
    cfg_path = repo / "config" / "promotion" / "promotion_thresholds.json"
    try:
        cfg = json.loads(cfg_path.read_text())
        reqs = cfg.get("modes", {}).get(mode, {}).get("requirements_to_enter", {})
        if isinstance(reqs, dict) and reqs:
            return reqs
    except Exception:
        pass

    # Hard-coded fallbacks — keep in sync with config file.
    fallbacks = {
        "shadow": {
            "canonical_snapshot_exists": True,
            "canonical_asset_count_min": 500,
            "source_count_min": 2,
            "tests_pass": True,
        },
        "internal_primary": {
            "source_count_min": 4,
            "top50_overlap_min_pct": 70,
            "top100_overlap_min_pct": 65,
            "verdict_tier_agreement_min_pct": 50,
            "avg_abs_delta_max": 1500,
            "comparison_batch_sample_min": 500,
            "multi_source_blend_pct_min": 40,
            "idp_source_count_min": 2,
            "source_weights_tuned": True,
            "all_tests_pass": True,
        },
        "public_primary": {
            "source_count_min": 6,
            "top50_overlap_min_pct": 80,
            "top100_overlap_min_pct": 75,
            "verdict_tier_agreement_min_pct": 65,
            "avg_abs_delta_max": 800,
            "comparison_batch_sample_min": 600,
            "multi_source_blend_pct_min": 60,
            "idp_source_count_min": 2,
            "league_context_engine_active": True,
            "source_weights_tuned": True,
            "all_tests_pass": True,
            "founder_approval": True,
        },
    }
    return fallbacks.get(mode, {})


def check_shadow_readiness(repo: Path) -> list[dict]:
    """Check requirements to enter shadow mode."""
    thresholds = _load_thresholds(repo, "shadow")
    results = []

    # Canonical snapshot exists
    snap_path = _latest_file(repo / "data" / "canonical", "canonical_snapshot_*.json")
    results.append({
        "check": "canonical_snapshot_exists",
        "required": True,
        "actual": snap_path is not None and snap_path.exists(),
        "pass": snap_path is not None and snap_path.exists(),
    })

    asset_min = thresholds.get("canonical_asset_count_min", 500)
    source_min = thresholds.get("source_count_min", 2)

    if snap_path and snap_path.exists():
        snap = json.loads(snap_path.read_text())
        asset_count = snap.get("asset_count", 0)
        source_count = snap.get("source_count", 0)

        results.append({
            "check": "canonical_asset_count_min",
            "required": asset_min,
            "actual": asset_count,
            "pass": asset_count >= asset_min,
        })
        results.append({
            "check": "source_count_min",
            "required": source_min,
            "actual": source_count,
            "pass": source_count >= source_min,
        })
    else:
        results.append({"check": "canonical_asset_count_min", "required": asset_min, "actual": 0, "pass": False})
        results.append({"check": "source_count_min", "required": source_min, "actual": 0, "pass": False})

    # Tests pass (check by importing pytest if available)
    results.append({
        "check": "tests_pass",
        "required": True,
        "actual": "manual_verification_needed",
        "pass": None,
        "note": "Run: python -m pytest tests/ --ignore=tests/e2e -q",
    })

    return results


def check_internal_primary_readiness(repo: Path) -> list[dict]:
    """Check requirements to enter internal_primary mode."""
    thresholds = _load_thresholds(repo, "internal_primary")
    results = []

    # Load latest comparison batch
    comp_path = _latest_file(repo / "data" / "comparison", "comparison_batch_*.json")
    if comp_path and comp_path.exists():
        comp = json.loads(comp_path.read_text())
        stats = comp.get("stats", {})
        # Use offense_players_only when available (most decision-useful), fall back to offense_combined
        uni_stats = comp.get("universe_stats", {})
        offense_stats = uni_stats.get("offense_players_only") or uni_stats.get("offense_combined", {})
    else:
        stats = {}
        offense_stats = {}
        results.append({
            "check": "comparison_batch_exists",
            "required": True,
            "actual": False,
            "pass": False,
            "note": "Run: python scripts/run_comparison_batch.py",
        })
        return results

    # Load canonical snapshot
    snap_path = _latest_file(repo / "data" / "canonical", "canonical_snapshot_*.json")
    snap = json.loads(snap_path.read_text()) if snap_path else {}

    src_min = thresholds.get("source_count_min", 4)
    source_count = snap.get("source_count", 0)
    results.append({"check": "source_count_min", "required": src_min, "actual": source_count, "pass": source_count >= src_min})

    # Use offense_players_only overlap/tier when available, fall back to overall
    t50_min = thresholds.get("top50_overlap_min_pct", 70)
    t50 = offense_stats.get("top_n_overlap_pct", stats.get("top50_overlap_pct", 0))
    t50_note = "offense_players_only" if offense_stats.get("top_n_overlap_pct") is not None else "overall"
    results.append({"check": "top50_overlap_min_pct", "required": t50_min, "actual": t50, "pass": t50 >= t50_min,
                    "note": f"Using {t50_note} view"})

    t100_min = thresholds.get("top100_overlap_min_pct", 65)
    t100 = offense_stats.get("top100_overlap_pct", stats.get("top100_overlap_pct", 0)) or 0
    t100_note = "offense_players_only" if offense_stats.get("top100_overlap_pct") is not None else "overall"
    results.append({"check": "top100_overlap_min_pct", "required": t100_min, "actual": t100, "pass": t100 >= t100_min,
                    "note": f"Using {t100_note} view"})

    tier_min = thresholds.get("verdict_tier_agreement_min_pct", 50)
    tier_pct = offense_stats.get("tier_agreement_pct", stats.get("verdict_tier_agreement_pct", 0))
    tier_note = "offense_players_only" if offense_stats.get("tier_agreement_pct") is not None else "overall"
    results.append({"check": "verdict_tier_agreement_min_pct", "required": tier_min, "actual": tier_pct, "pass": tier_pct >= tier_min,
                    "note": f"Using {tier_note} view"})

    delta_max = thresholds.get("avg_abs_delta_max", 1500)
    avg_delta = offense_stats.get("avg_abs_delta", stats.get("avg_abs_delta", 9999))
    delta_note = "offense_players_only" if offense_stats.get("avg_abs_delta") is not None else "overall"
    results.append({"check": "avg_abs_delta_max", "required": delta_max, "actual": avg_delta, "pass": avg_delta <= delta_max,
                    "note": f"Using {delta_note} view"})

    sample_min = thresholds.get("comparison_batch_sample_min", 500)
    sample = stats.get("count", 0)
    results.append({"check": "comparison_batch_sample_min", "required": sample_min, "actual": sample, "pass": sample >= sample_min})

    # Multi-source blend percentage — compute from snapshot directly
    blend_min = thresholds.get("multi_source_blend_pct_min", 40)
    assets = snap.get("assets", [])
    total_assets = len(assets)
    multi = sum(1 for a in assets if len(a.get("source_values", {})) > 1)
    blend_pct = round(multi / total_assets * 100) if total_assets else 0
    results.append({"check": "multi_source_blend_pct_min", "required": blend_min, "actual": blend_pct, "pass": blend_pct >= blend_min})

    # IDP source count
    idp_min = thresholds.get("idp_source_count_min", 2)
    idp_sources = set()
    for a in assets:
        if "idp" in str(a.get("universe", "")).lower():
            for src in (a.get("source_values") or {}).keys():
                idp_sources.add(src)
    results.append({"check": "idp_source_count_min", "required": idp_min, "actual": len(idp_sources), "pass": len(idp_sources) >= idp_min})

    # Source weights tuned (check if any weight != 1.0)
    weights_path = repo / "config" / "weights" / "default_weights.json"
    weights = json.loads(weights_path.read_text()) if weights_path.exists() else {}
    source_weights = weights.get("sources", {})
    any_tuned = any(v != 1.0 for v in source_weights.values())
    tuned_count = sum(1 for v in source_weights.values() if v != 1.0)
    results.append({
        "check": "source_weights_tuned",
        "required": True,
        "actual": any_tuned,
        "pass": any_tuned,
        "note": f"{tuned_count}/{len(source_weights)} weights differ from 1.0" if any_tuned else "All weights are 1.0 — founder needs to set relative source weights",
    })

    results.append({
        "check": "all_tests_pass",
        "required": True,
        "actual": "manual_verification_needed",
        "pass": None,
        "note": "Run: python -m pytest tests/ --ignore=tests/e2e -q",
    })

    return results


def check_public_primary_readiness(repo: Path) -> list[dict]:
    """Check requirements for public_primary (superset of internal)."""
    results = check_internal_primary_readiness(repo)
    pub_thresholds = _load_thresholds(repo, "public_primary")

    # Override with public_primary thresholds (stricter than internal)
    _override_map = {
        "source_count_min": (">=", pub_thresholds.get("source_count_min", 6)),
        "top50_overlap_min_pct": (">=", pub_thresholds.get("top50_overlap_min_pct", 80)),
        "top100_overlap_min_pct": (">=", pub_thresholds.get("top100_overlap_min_pct", 75)),
        "verdict_tier_agreement_min_pct": (">=", pub_thresholds.get("verdict_tier_agreement_min_pct", 65)),
        "avg_abs_delta_max": ("<=", pub_thresholds.get("avg_abs_delta_max", 800)),
        "multi_source_blend_pct_min": (">=", pub_thresholds.get("multi_source_blend_pct_min", 60)),
        "comparison_batch_sample_min": (">=", pub_thresholds.get("comparison_batch_sample_min", 600)),
    }
    for r in results:
        override = _override_map.get(r["check"])
        if override is None:
            continue
        op, threshold = override
        r["required"] = threshold
        actual = r.get("actual") or (9999 if op == "<=" else 0)
        r["pass"] = actual <= threshold if op == "<=" else actual >= threshold

    # League context engine
    league_dir = repo / "src" / "league"
    league_files = list(league_dir.glob("*.py"))
    league_active = any(f.name != "__init__.py" and f.stat().st_size > 100 for f in league_files)
    results.append({
        "check": "league_context_engine_active",
        "required": True,
        "actual": league_active,
        "pass": league_active,
        "note": "src/league/ must have real implementation code",
    })

    results.append({
        "check": "founder_approval",
        "required": True,
        "actual": False,
        "pass": False,
        "note": "Founder must explicitly approve public cutover",
    })

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check promotion readiness")
    parser.add_argument(
        "--target",
        choices=["shadow", "internal_primary", "public_primary", "all"],
        default="all",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    repo = _repo_root()
    targets = (
        ["shadow", "internal_primary", "public_primary"]
        if args.target == "all"
        else [args.target]
    )

    all_results = {}
    for target in targets:
        if target == "shadow":
            checks = check_shadow_readiness(repo)
        elif target == "internal_primary":
            checks = check_internal_primary_readiness(repo)
        elif target == "public_primary":
            checks = check_public_primary_readiness(repo)
        else:
            continue

        passed = sum(1 for c in checks if c.get("pass") is True)
        failed = sum(1 for c in checks if c.get("pass") is False)
        manual = sum(1 for c in checks if c.get("pass") is None)
        ready = failed == 0 and manual == 0

        all_results[target] = {
            "ready": ready,
            "passed": passed,
            "failed": failed,
            "manual_verification": manual,
            "checks": checks,
        }

    if args.json:
        print(json.dumps(all_results, indent=2, default=str))
    else:
        for target, result in all_results.items():
            status = "READY" if result["ready"] else "NOT READY"
            print(f"\n{'='*60}")
            print(f"  {target.upper()}: {status}")
            print(f"  Passed: {result['passed']}  Failed: {result['failed']}  Manual: {result['manual_verification']}")
            print(f"{'='*60}")
            for c in result["checks"]:
                icon = "PASS" if c.get("pass") is True else ("FAIL" if c.get("pass") is False else "????")
                line = f"  [{icon}] {c['check']}: required={c['required']}, actual={c['actual']}"
                if c.get("note"):
                    line += f"  ({c['note']})"
                print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
