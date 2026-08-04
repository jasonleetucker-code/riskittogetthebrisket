#!/usr/bin/env python3
"""Accumulate cross-league FAAB bids from KTC's public waiver database.

KTC publishes real waiver claims from other people's dynasty leagues,
each row carrying the winning bid, the league's ORIGINAL budget, and
the league's format.  That is a second, independent read on what a
waiver claim actually costs — our own Sleeper history says what THIS
league pays, and this says what comparable leagues pay for the same
player right now.

    python scripts/fetch_crowd_faab.py
    python scripts/fetch_crowd_faab.py --league dynasty_main --dry-run

Exit codes: 0 ok · 1 error · 2 nothing fetched.

WHY THIS ACCUMULATES
────────────────────
The feed is a ROLLING WINDOW — measured 2026-08-04 it served 200 rows
spanning five days across 83 leagues.  A single fetch is a snapshot,
not a history, so each run merges into
``data/faab/crowd_history_<leagueKey>.json``, deduped by the KTC row
id (stable across fetches).  Run it on the scrape cadence and a real
sample builds over a season.

WHAT THIS IS NOT
────────────────
It is an anonymous crowd of MyFantasyLeague managers, NOT a panel of
experts, and no expert or ranking source in our pipeline is attached
to a league at all.  It is also used only to price the MARKET — how
contested a claim will be — never to price the PLAYER.  Our board owns
player value; letting a hype cycle bid up our own valuation is exactly
the double-count the FAAB engine exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade.faab_history import (  # noqa: E402
    crowd_bid_index,
    load_crowd_history,
    merge_crowd_rows,
    save_crowd_history,
)

WAIVER_DB_URL = "https://keeptradecut.com/dynasty/waiver-database"
_TIMEOUT = 30
_UA = "Mozilla/5.0 (compatible; riskittogetthebrisket/1.0)"


def fetch_rows() -> list[dict[str, Any]]:
    """Pull and parse the inline ``var waivers`` array.

    The rows are embedded in the page HTML, not served over an XHR —
    which is why the Playwright scraper's response-interception path
    always timed out and shipped an empty crowd block.  A plain HTTP
    GET is enough and needs no browser.

    The ``sf`` / ``tep`` query params are deliberately omitted: measured
    2026-08-04, they do not filter this payload (``sf=0&tep=0`` and
    ``sf=1&tep=2`` return byte-identical rows).  They drive the rendered
    DOM only, so format filtering happens below.
    """
    req = urllib.request.Request(WAIVER_DB_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        html = resp.read().decode("utf-8", errors="replace")

    waivers = re.search(r"var\s+waivers\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not waivers:
        return []
    rows = json.loads(waivers.group(1))

    names: dict[str, str] = {}
    players = re.search(r"var\s+playersArray\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if players:
        try:
            for p in json.loads(players.group(1)):
                pid, nm = p.get("playerID"), p.get("playerName")
                if pid is not None and nm:
                    names[str(pid)] = nm
        except (ValueError, TypeError):
            pass

    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        settings = row.get("settings") or {}
        try:
            budget = float(settings.get("totalBlindBidWaiverAmount") or 0)
            bid = float(row.get("blindBid") or 0)
        except (TypeError, ValueError):
            continue
        if budget <= 0 or bid < 0:
            continue

        added = names.get(str(row.get("pickedUpPlayer")))
        if not added:
            continue  # unresolvable id — cannot join our board by name

        dropped_id = str(row.get("droppedPlayer") or "")
        # KTC uses -1 for "no drop"; ~half of all claims are no-drop.
        dropped = names.get(dropped_id) if dropped_id not in ("-1", "0", "") else None

        out.append(
            {
                "id": row.get("id"),
                "date": row.get("date"),
                "added": added,
                "dropped": dropped,
                "bid": bid,
                "budget": budget,
                "bidPct": round(100.0 * bid / budget, 3),
                "settings": {
                    "leagueId": str(settings.get("id") or ""),
                    "teams": settings.get("teams"),
                    "superflex": (settings.get("qBs") or 0) >= 2,
                    "tep": settings.get("tep"),
                    "ppr": settings.get("ppr"),
                    "platform": settings.get("dynastyPlatformType"),
                },
            }
        )
    return out


def comparable(row: dict[str, Any], *, teams: int, superflex: bool, tep: bool) -> bool:
    """Keep only leagues whose FORMAT makes their prices meaningful here.

    A 10-team 1QB league's waiver wire is a different market from a
    12-team superflex TEP league's — deeper starting requirements make
    the same player scarcer and dearer.  Team count is allowed +/-2
    because exact-match alone discards most of an already small feed.
    """
    s = row.get("settings") or {}
    if bool(s.get("superflex")) != bool(superflex):
        return False
    if bool(s.get("tep")) != bool(tep):
        return False
    try:
        n = int(s.get("teams") or 0)
    except (TypeError, ValueError):
        return False
    return abs(n - int(teams)) <= 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default=None, help="only this league key")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    try:
        from src.api import league_registry

        leagues = [
            cfg
            for cfg in league_registry.active_leagues()
            if not args.league or cfg.key == args.league
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"error: league registry unreadable: {exc}", file=sys.stderr)
        return 1
    if not leagues:
        print("error: no matching active leagues", file=sys.stderr)
        return 2

    try:
        rows = fetch_rows()
    except Exception as exc:  # noqa: BLE001
        print(f"error: crowd fetch failed: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("error: no rows parsed from the waiver database", file=sys.stderr)
        return 2
    print(f"fetched {len(rows)} crowd claims")

    now_iso = datetime.now(timezone.utc).isoformat()
    for cfg in leagues:
        settings = league_registry.get_league_roster_settings(cfg.key) or {}
        starters = settings.get("starters") or {}
        teams = int(settings.get("teamCount") or 12)
        superflex = bool(starters.get("SFLEX") or starters.get("SUPER_FLEX"))
        tep = bool(int(starters.get("TE") or 0) >= 2) or "tep" in str(
            getattr(cfg, "scoring_profile", "")
        )

        keep = [r for r in rows if comparable(r, teams=teams, superflex=superflex, tep=tep)]
        print(
            f"→ {cfg.key}: {len(keep)} of {len(rows)} comparable "
            f"({teams}tm superflex={superflex} tep={tep})"
        )
        if not keep:
            continue

        merged = merge_crowd_rows(load_crowd_history(cfg.key), keep, now_iso=now_iso)
        index = crowd_bid_index(merged)
        print(
            f"   +{merged['addedLastRun']} new · {len(merged['rows'])} total rows · "
            f"{len(index)} players priced"
        )
        if args.dry_run:
            top = sorted(index.items(), key=lambda kv: -kv[1]["medianPct"])[:8]
            for key, v in top:
                print(f"     {key:24s} median {v['medianPct']:>5.1f}%  ({v['claims']} claims)")
            continue
        print(f"   wrote {save_crowd_history(cfg.key, merged)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
