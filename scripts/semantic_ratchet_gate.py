from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLDS = {
    "blankNonPickPositionCount": 61,
    "sourceCountWithoutPositiveCanonicalSites": 0,
    # Baseline pinned to the checked-in 2026-03-20 semantic validation snapshot.
    "lowConfidenceActionableCount": 420,
    "scoringFallbackRatio": 0.02,
    "scarcityFallbackRatio": 0.02,
}


def _to_num(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number:  # NaN
        return None
    return number


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail CI when semantic integrity metrics regress above ratchet thresholds.",
    )
    parser.add_argument("--repo", default=".", help="Repository root path.")
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Use existing data/validation/api_contract_validation_latest.json without rerunning validation.",
    )
    parser.add_argument(
        "--max-blank-non-pick",
        type=int,
        default=DEFAULT_THRESHOLDS["blankNonPickPositionCount"],
    )
    parser.add_argument(
        "--max-source-mismatch",
        type=int,
        default=DEFAULT_THRESHOLDS["sourceCountWithoutPositiveCanonicalSites"],
    )
    parser.add_argument(
        "--max-low-confidence-actionable",
        type=int,
        default=DEFAULT_THRESHOLDS["lowConfidenceActionableCount"],
    )
    parser.add_argument(
        "--max-scoring-fallback-ratio",
        type=float,
        default=DEFAULT_THRESHOLDS["scoringFallbackRatio"],
    )
    parser.add_argument(
        "--max-scarcity-fallback-ratio",
        type=float,
        default=DEFAULT_THRESHOLDS["scarcityFallbackRatio"],
    )
    return parser.parse_args()


def _run_semantic_validation(repo_root: Path) -> None:
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "validate_api_contract.py"),
        "--repo",
        str(repo_root),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _load_semantic_metrics(repo_root: Path) -> dict[str, Any]:
    report_path = repo_root / "data" / "validation" / "api_contract_validation_latest.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Missing semantic validation report: {report_path}")
    with report_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    semantic = payload.get("semanticReport")
    if not isinstance(semantic, dict):
        raise ValueError("semanticReport block missing from validation output")
    metrics = semantic.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("semanticReport.metrics block missing from validation output")
    return metrics


def main() -> int:
    args = _args()
    repo_root = Path(args.repo).resolve()

    if not args.skip_refresh:
        _run_semantic_validation(repo_root)

    metrics = _load_semantic_metrics(repo_root)
    checks: list[tuple[str, float, float]] = [
        ("blankNonPickPositionCount", float(args.max_blank_non_pick), float(metrics.get("blankNonPickPositionCount") or 0)),
        (
            "sourceCountWithoutPositiveCanonicalSites",
            float(args.max_source_mismatch),
            float(metrics.get("sourceCountWithoutPositiveCanonicalSites") or 0),
        ),
        (
            "lowConfidenceActionableCount",
            float(args.max_low_confidence_actionable),
            float(metrics.get("lowConfidenceActionableCount") or 0),
        ),
        ("scoringFallbackRatio", float(args.max_scoring_fallback_ratio), float(_to_num(metrics.get("scoringFallbackRatio")) or 0.0)),
        ("scarcityFallbackRatio", float(args.max_scarcity_fallback_ratio), float(_to_num(metrics.get("scarcityFallbackRatio")) or 0.0)),
    ]

    failures: list[str] = []
    print("[semantic-ratchet] current metrics:")
    for metric, threshold, actual in checks:
        print(f"  - {metric}: actual={actual} max={threshold}")
        if actual > threshold:
            failures.append(f"{metric} regressed: actual={actual} > max={threshold}")

    if failures:
        for failure in failures:
            print(f"[semantic-ratchet][fail] {failure}")
        return 1

    print("[semantic-ratchet] pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
