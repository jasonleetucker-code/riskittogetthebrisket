#!/usr/bin/env python3
"""Export model people, identities, review queues, Super Sharps, and evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import curated  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, default=None)
    p.add_argument("--output-dir", type=Path, default=Path("data/intel/sharp_curated"))
    args = p.parse_args()
    result = curated.export_reconciliation(args.output_dir, ledger_path=args.ledger)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
