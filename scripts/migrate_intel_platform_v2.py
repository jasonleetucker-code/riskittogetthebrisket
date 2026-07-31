#!/usr/bin/env python3
"""Back up and migrate the Intel ledger to platform schema v2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intel import platform_ledger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--check", action="store_true", help="Report only after ensuring schema.")
    args = parser.parse_args()
    report = (
        platform_ledger.migration_report(args.ledger)
        if args.check
        else platform_ledger.backup_and_migrate(args.ledger, backup=not args.no_backup)
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") and report.get("rowCountsPreserved", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
