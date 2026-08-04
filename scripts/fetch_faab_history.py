#!/usr/bin/env python3
"""Fetch and persist a league's historical FAAB bid history.

Walks the Sleeper league chain backwards through ``previous_league_id``
and stores every completed waiver / free-agent add with its winning
bid under ``data/faab/bid_history_<leagueKey>.json``.

The FAAB engine's market model reads the persisted file; it never
makes network calls itself.  Run this on a cadence (or by hand after
a busy waiver week) to keep the priors current.

    python scripts/fetch_faab_history.py                # every active league
    python scripts/fetch_faab_history.py --league dynasty_main
    python scripts/fetch_faab_history.py --summary-only # print, don't write

Exit codes: 0 ok · 1 error · 2 nothing fetched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade.faab_history import (  # noqa: E402
    fetch_bid_history,
    save_bid_history,
    summarize_bid_history,
)


def _leagues(only: str | None) -> list[tuple[str, str]]:
    """``(leagueKey, sleeperLeagueId)`` for each active league."""
    from src.api import league_registry  # noqa: PLC0415

    out: list[tuple[str, str]] = []
    for cfg in league_registry.active_leagues():
        key = getattr(cfg, "key", None) or ""
        sleeper_id = getattr(cfg, "sleeper_league_id", None) or ""
        if not key or not sleeper_id:
            continue
        if only and key != only:
            continue
        out.append((key, str(sleeper_id)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="only this league key")
    parser.add_argument("--max-seasons", type=int, default=10)
    parser.add_argument("--summary-only", action="store_true", help="print without writing")
    args = parser.parse_args()

    try:
        targets = _leagues(args.league)
    except Exception as exc:  # noqa: BLE001
        print(f"error: could not read league registry: {exc}", file=sys.stderr)
        return 1

    if not targets:
        print("error: no matching active leagues", file=sys.stderr)
        return 2

    fetched_any = False
    for key, sleeper_id in targets:
        print(f"→ {key} (sleeper {sleeper_id})")
        try:
            payload = fetch_bid_history(sleeper_id, max_seasons=args.max_seasons)
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}", file=sys.stderr)
            continue

        total = payload.get("totalAdds") or 0
        if not total:
            print("  no completed adds with a bid found")
            continue
        fetched_any = True

        priors = summarize_bid_history(payload)
        print(
            f"  {total} adds across {len(payload.get('seasons') or [])} season(s): "
            f"median {priors.median_pct:.2f}% of budget, "
            f"p90 {priors.p90_pct:.2f}%, max {priors.max_pct:.2f}%, "
            f"{priors.zero_bid_share:.0%} at $0"
        )
        if args.summary_only:
            print(json.dumps(priors.to_dict(), indent=2))
            continue
        path = save_bid_history(key, payload)
        print(f"  wrote {path}")

    return 0 if fetched_any else 2


if __name__ == "__main__":
    raise SystemExit(main())
