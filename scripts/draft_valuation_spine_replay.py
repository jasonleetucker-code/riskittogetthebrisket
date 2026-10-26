#!/usr/bin/env python3
"""Replay which completed classes form a target class's spine, as of a time.

Read-only view of the draft-valuation rollover ledger
(``config/draft_valuation/historical_curves/<league>/``).  dynasty_main is the
only configured league (owner scope 2026-10-18).

Usage::

    python scripts/draft_valuation_spine_replay.py --target 2027 [--as-of 2027-06-01T00:00:00+00:00]

Exit codes: 0 printed (``spineUnavailable`` names a missing spine); 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.ledger import LedgerRefusal, replay_spine  # noqa: E402
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--league", default="dynasty_main")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args(argv)
    try:
        out = replay_spine(args.target, league_key=args.league, as_of=args.as_of)
    except (LedgerRefusal, LeagueNotConfiguredError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
