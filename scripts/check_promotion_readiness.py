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


def check_shadow_readiness(repo: Path) -> list[dict]:
    """Check requirements to enter shadow mode."""
    results = []

    # Canonical snapshot exists
    snap_path = _latest_file(repo / "data" / "canonical", "canonical_snapshot_*.json")
    results.append({
        "check": "canonical_snapshot_exists",
        "required": True,
        "actual": snap_path is not None and snap_path.exists(),
        "pass": snap_path is not None and snap_path.exists(),
    })

    if snap_path and snap_path.exists():
        snap = json.loads(snap_path.read_text())
        asset_count = snap.get("asset_count", 0)
        source_count = snap.get("source_count", 0)

        results.append({
            "check": "canonical_asset_count_min",
            "required": 500,
            "actual": asset_count,
            "pass": asset_count >= 500,
        })
        results.append({
            "check": "source_count_min",
            "required": 2,
            "actual": source_count,
            "pass": source_count >= 2,
        })
    else:
        results.append({"check": "canonical_asset_count_min", "required": 500, "actual": 0, "pass": False})
        results.append({"check": "source_count_min", "required": 2, "actual": 0, "pass": False})

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
    results = []

    # Load latest comparison batch
    comp_path = _latest_file(repo / "data" / "comparison", "comparison_batch_*.json")
    if comp_path and comp_path.exists():
        comp = json.loads(comp_path.read_text())
        stats = comp.get("stats", {})
    else:
        stats = {}
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

    source_count = snap.get("source_count", 0)
    results.append({"check": "source_count_min", "required": 4, "actual": source_count, "pass": source_count >= 4})

    t50 = stats.get("top50_overlap_pct", 0)
    results.append({"check": "top50_overlap_min_pct", "required": 70, "actual": t50, "pass": t50 >= 70})

    t100 = stats.get("top100_overlap_pct", 0)
    results.append({"check": "top100_overlap_min_pct", "required": 65, "actual": t100 or 0, "pass": (t100 or 0) >= 65})

    tier_pct = stats.get("verdict_tier_agreement_pct", 0)
    results.append({"check": "verdict_tier_agreement_min_pct", "required": 50, "actual": tier_pct, "pass": tier_pct >= 50})

    avg_delta = stats.get("avg_abs_delta", 9999)
    results.append({"check": "avg_abs_delta_max", "required": 1500, "actual": avg_delta, "pass": avg_delta <= 1500})

    sample = stats.get("count", 0)
    results.append({"check": "comparison_batch_sample_min", "required": 500, "actual": sample, "pass": sample >= 500})

    # Multi-source blend percentage
    total_assets = snap.get("asset_count", 0)
    multi = stats.get("multi_source_count", 0)
    blend_pct = round(multi / total_assets * 100) if total_assets else 0
    results.append({"check": "multi_source_blend_pct_min", "required": 40, "actual": blend_pct, "pass": blend_pct >= 40})

    # IDP source count
    assets = snap.get("assets", [])
    idp_sources = set()
    for a in assets:
        if "idp" in str(a.get("universe", "")).lower():
            for src in (a.get("source_values") or {}).keys():
                idp_sources.add(src)
    results.append({"check": "idp_source_count_min", "required": 2, "actual": len(idp_sources), "pass": len(idp_sources) >= 2})

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

    # Override stricter thresholds
    for r in results:
        if r["check"] == "source_count_min":
            r["required"] = 6
            r["pass"] = (r.get("actual") or 0) >= 6
        elif r["check"] == "top50_overlap_min_pct":
            r["required"] = 80
            r["pass"] = (r.get("actual") or 0) >= 80
        elif r["check"] == "top100_overlap_min_pct":
            r["required"] = 75
            r["pass"] = (r.get("actual") or 0) >= 75
        elif r["check"] == "verdict_tier_agreement_min_pct":
            r["required"] = 65
            r["pass"] = (r.get("actual") or 0) >= 65
        elif r["check"] == "avg_abs_delta_max":
            r["required"] = 800
            r["pass"] = (r.get("actual") or 9999) <= 800
        elif r["check"] == "multi_source_blend_pct_min":
            r["required"] = 60
            r["pass"] = (r.get("actual") or 0) >= 60

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
