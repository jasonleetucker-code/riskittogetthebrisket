#!/usr/bin/env python3
"""Replay a stored draft-class generation as of a past time and compare bytes.

Read-only (``src/draft/rookie_auction/replay.py``): selects only the stored
record, completed-class snapshots, rookie inputs and promotion pointers that
existed at ``--as-of``, recomputes the class's allocation with the canonical
calculation and compares it byte for byte with the stored record.
dynasty_main is the only configured league (owner scope 2026-10-18).

Usage::

    python scripts/draft_valuation_replay.py --year 2028 --as-of 2026-10-18T12:00:00+00:00

Exit codes: 0 reproduced byte for byte; 1 recomputed and differs;
3 unavailable or refused (the reason is printed); 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.replay import (  # noqa: E402
    STATE_DIFFERS,
    STATE_REPRODUCED,
    replay_generation,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--as-of", required=True, help="ISO-8601 time with a time zone")
    ap.add_argument("--league", default="dynasty_main")
    args = ap.parse_args(argv)
    out = replay_generation(args.league, args.year, args.as_of)
    print(json.dumps(out.to_dict(), indent=1))
    if out.state == STATE_REPRODUCED:
        return 0
    if out.state == STATE_DIFFERS:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
