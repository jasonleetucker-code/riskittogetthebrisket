#!/usr/bin/env python3
"""Daily curated-sharp refresh using only public or explicitly verified data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import curated  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, default=curated.DEFAULT_SNAPSHOT_PATH)
    p.add_argument("--ledger", type=Path, default=None)
    p.add_argument("--sleeper-budget", type=int, default=75)
    p.add_argument("--skip-candidate-inspection", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path("data/intel/sharp_curated"))
    args = p.parse_args()

    result: dict[str, object] = {}
    result["import"] = curated.import_snapshot(
        snapshot_path=args.snapshot,
        ledger_path=args.ledger,
    )
    result["verifiedSleeper"] = curated.resolve_verified_sleeper_accounts(ledger_path=args.ledger)
    if not args.skip_candidate_inspection and args.sleeper_budget > 0:
        result["sleeperCandidates"] = curated.inspect_sleeper_candidates(
            ledger_path=args.ledger,
            budget=args.sleeper_budget,
        )
    result["ffpcCandidates"] = curated.match_ffpc_candidates(ledger_path=args.ledger)
    result["membership"] = curated.refresh_memberships(ledger_path=args.ledger)
    result["exports"] = curated.export_reconciliation(
        args.output_dir,
        ledger_path=args.ledger,
    )
    result["reconciliation"] = curated.reconciliation_report(ledger_path=args.ledger)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
