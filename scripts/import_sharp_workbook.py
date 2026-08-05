#!/usr/bin/env python3
"""Import the researched Sharp workbook into the normalized Sharp Model.

The import is idempotent. It stores every candidate-pool person, promotes the
Final 100 into the curated population, retains near-misses for research, and
never verifies a platform identity from username resemblance alone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import curated  # noqa: E402
from src.sharp.workbook_import import build_snapshot, write_snapshot  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workbook", nargs="?", type=Path, help="Source .xlsx workbook")
    p.add_argument(
        "--snapshot",
        type=Path,
        default=curated.DEFAULT_SNAPSHOT_PATH,
        help="Normalized JSON snapshot to read/write",
    )
    p.add_argument("--ledger", type=Path, default=None, help="Override Sharp ledger path")
    p.add_argument("--dry-run", action="store_true", help="Parse and report without committing")
    p.add_argument("--resolve-verified-sleeper", action="store_true")
    p.add_argument("--inspect-sleeper-candidates", action="store_true")
    p.add_argument("--sleeper-budget", type=int, default=50)
    p.add_argument("--match-ffpc", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.workbook:
        if args.dry_run:
            snapshot = build_snapshot(args.workbook)
        else:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot = write_snapshot(args.workbook, args.snapshot)
    else:
        snapshot = curated.load_snapshot(args.snapshot)

    result: dict[str, object] = {
        "snapshot": str(args.snapshot),
        "snapshotCounts": snapshot.get("counts") or {},
        "import": curated.import_snapshot(
            snapshot,
            snapshot_path=args.snapshot,
            ledger_path=args.ledger,
            dry_run=args.dry_run,
        ),
    }
    if not args.dry_run:
        if args.resolve_verified_sleeper:
            result["verifiedSleeper"] = curated.resolve_verified_sleeper_accounts(
                ledger_path=args.ledger
            )
        if args.inspect_sleeper_candidates:
            result["sleeperCandidates"] = curated.inspect_sleeper_candidates(
                ledger_path=args.ledger,
                budget=max(0, args.sleeper_budget),
            )
        if args.match_ffpc:
            result["ffpcCandidates"] = curated.match_ffpc_candidates(ledger_path=args.ledger)
        result["membership"] = curated.refresh_memberships(ledger_path=args.ledger)
        result["reconciliation"] = curated.reconciliation_report(ledger_path=args.ledger)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
