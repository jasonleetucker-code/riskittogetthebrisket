#!/usr/bin/env python3
"""Create the additive curated Sharp schema and optionally import its snapshot."""

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
    p.add_argument("--schema-only", action="store_true")
    args = p.parse_args()
    conn = curated.ensure_schema(args.ledger)
    try:
        version = conn.execute(
            "SELECT value FROM meta WHERE key='curated_sharp_schema_version'"
        ).fetchone()
    finally:
        conn.close()
    result = {"schemaVersion": int(version[0]) if version else None}
    if not args.schema_only:
        result["import"] = curated.import_snapshot(ledger_path=args.ledger)
        result["membership"] = curated.refresh_memberships(ledger_path=args.ledger)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
