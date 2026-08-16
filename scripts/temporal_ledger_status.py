#!/usr/bin/env python3
"""Temporal-ledger status probe — coverage plus real as-of queries.

The production observability answer for C1-U4: what the canonical
ledger actually holds, and whether the as-of contract answers real
queries correctly, measured on the box rather than assumed.

Exit codes (playerctx style):
    0 — ledger present, has rows, and the probe queries behaved
    1 — probe error
    2 — no ledger / empty (not recording yet)

Usage:
    python scripts/temporal_ledger_status.py
    python scripts/temporal_ledger_status.py --asset "mpick:2026:r1:s1" --date 2026-08-15
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.history import asof, store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--asset", action="append", default=[], help="asset key to probe")
    parser.add_argument("--date", default=None, help="as-of date for probes (YYYY-MM-DD)")
    parser.add_argument("--lane", default=store.LANE_CANONICAL)
    parser.add_argument("--source-key", default="")
    args = parser.parse_args(argv)

    cov = store.coverage(args.ledger)
    print(json.dumps(cov, indent=1, sort_keys=True))
    if not cov.get("exists") or not cov.get("rows"):
        print("STATUS: no temporal ledger content on this host", file=sys.stderr)
        return 2

    # Structural probe: a pre-boundary query must answer
    # before_history_boundary regardless of ledger content.
    probe = asof.value_as_of("mpick:2026:r1:s1", "2026-07-01", lane=args.lane, path=args.ledger)
    if probe["fidelity"] != asof.FIDELITY_UNAVAILABLE or (
        probe["missingReason"] != asof.REASON_BEFORE_BOUNDARY
    ):
        print("STATUS: pre-boundary probe FAILED — investigate", file=sys.stderr)
        return 1
    print("pre-boundary probe: ok (before_history_boundary)")

    for asset in args.asset:
        when = args.date or cov.get("lastDate")
        result = asof.value_as_of(
            asset, when, lane=args.lane, source_key=args.source_key, path=args.ledger
        )
        print(f"--- {asset} @ {when}")
        print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
