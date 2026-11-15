#!/usr/bin/env python3
"""Capture each own registered league's per-season format, point in time.

Walks every ACTIVE registry league's Sleeper ``previous_league_id`` chain with
the public ``GET /v1/league/{id}`` and records each season-league's roster
slots, scoring card and format settings, dated and append-only, into the
own-league format store (``src/trade/own_league_format_capture.py``).  The
completed-trade ledger reads it to classify each own-league trade in its OWN
season's format instead of today's.

Normally unnecessary: the Sharp transaction-crawl timer
(``scripts/crawl_sharp_transactions.py``) runs the same refresh as its third
pass.  Run it by hand on a fresh deploy (to seed the completed seasons before
the next timer run) or after adding a league — not while a Sharp timer is
running (shared public IP).  Completed
seasons are fetched once and then frozen, so re-running costs one request per
league.

    python scripts/capture_own_league_formats.py
    python scripts/capture_own_league_formats.py --league dynasty_main
    python scripts/capture_own_league_formats.py --path /tmp/own_formats.sqlite

Exit codes: 0 every league walked to the end of its chain · 1 a walk stopped
early (fetch failure / 429) · 2 nothing to do.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import league_registry  # noqa: E402
from src.trade import own_league_format_capture as olfc  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", action="append", default=[], metavar="KEY")
    parser.add_argument("--path", type=Path, default=None, help="store path (default: box store)")
    args = parser.parse_args(argv)

    if args.league:
        configs = [league_registry.get_league_by_key(k) for k in args.league]
        configs = [c for c in configs if c is not None]
    else:
        configs = list(league_registry.active_leagues())
    if not configs:
        print("no leagues to capture", file=sys.stderr)
        return 2

    stopped = 0
    for cfg in configs:
        result = olfc.refresh_own_league_formats(
            cfg.key, root_league_id=cfg.sleeper_league_id, path=args.path, sleep_s=0.12
        )
        print(json.dumps(result.to_dict(), sort_keys=True))
        if result.stopped_reason:
            stopped += 1
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
