#!/usr/bin/env python3
"""Build the BDVM reconstructed-baseline projection snapshot.

Fetches the last N completed seasons of nflverse weekly stats, scores
them under the league's exact Sleeper scoring settings (read from the
latest committed contract export by default), builds the BDVM §8.3
proxy projections, and writes an immutable snapshot under
``data/bdvm/projections/<season>/``.

Usage::

    python scripts/bdvm_build_baseline.py --season 2026
    python scripts/bdvm_build_baseline.py --season 2026 \
        --contract exports/latest/dynasty_data_2026-07-27.json \
        --seasons-back 3 --label baseline

Exit codes: 0 success, 1 nothing built, 2 error.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.bdvm.baseline import fetch_and_build_baseline  # noqa: E402
from src.bdvm.projections import write_snapshot  # noqa: E402


def _default_contract_path() -> Path | None:
    candidates = sorted(glob.glob(str(REPO_ROOT / "exports" / "latest" / "dynasty_data_*.json")))
    return Path(candidates[-1]) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True, help="target (upcoming) season")
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="contract export with sleeper.scoringSettings "
        "(default: newest exports/latest/dynasty_data_*.json)",
    )
    parser.add_argument("--seasons-back", type=int, default=3)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--dry-run", action="store_true", help="build but do not write")
    args = parser.parse_args()

    contract_path = args.contract or _default_contract_path()
    if contract_path is None or not contract_path.exists():
        print("ERROR: no contract export found for scoring settings", file=sys.stderr)
        return 2
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
    if not scoring:
        print(f"ERROR: {contract_path} has no sleeper.scoringSettings", file=sys.stderr)
        return 2

    as_of = datetime.now(timezone.utc).date().isoformat()
    try:
        records, summary = fetch_and_build_baseline(
            season=args.season,
            as_of=as_of,
            scoring_settings=scoring,
            seasons_back=args.seasons_back,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: baseline build failed: {exc}", file=sys.stderr)
        return 2

    print(f"scoring settings: {len(scoring)} keys from {contract_path.name}")
    for k, v in summary.items():
        print(f"{k}: {v}")
    if not records:
        print("nothing built (no realized history?)", file=sys.stderr)
        return 1
    if args.dry_run:
        print("dry run — snapshot not written")
        return 0
    path = write_snapshot(records, season=args.season, as_of=as_of, label=args.label)
    print(f"snapshot written: {path} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
