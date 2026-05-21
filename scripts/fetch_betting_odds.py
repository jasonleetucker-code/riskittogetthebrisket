#!/usr/bin/env python3
"""Fetch sportsbook moneyline odds and write a normalized snapshot.

Pulls head-to-head (moneyline) odds for the major US sports from The
Odds API (https://the-odds-api.com), a clean, ToS-permitted feed with a
free tier.  No paywall bypass or scraping — a plain ``requests.get``
with an API key returns JSON.

The vendor response is normalized into the snapshot shape consumed by
``src/betting/recommendations.py`` so the blend logic never depends on
any one vendor's wire format.

Auth
────
Set ``ODDS_API_KEY`` in the environment (``.env`` locally; GitHub
Actions secret for the scheduled fetch).

Output
──────
``data/betting/odds_<YYYYMMDDTHHMMSSZ>.json`` (+ a freshness stamp at
``data/scrape_state/betting_odds_last_success``).

Run::

    python3 scripts/fetch_betting_odds.py [--sports nba,nfl] [--dry-run]

Exit codes:
    0  - success (snapshot written, even if zero games today)
    1  - soft failure (missing key, fetch/parse error)
    2  - schema regression (response not a JSON array for any sport)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_betting_odds] requests is not installed", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
BETTING_DIR = REPO_ROOT / "data" / "betting"
STAMP_PATH = REPO_ROOT / "data" / "scrape_state" / "betting_odds_last_success"

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"

# Friendly alias → The Odds API sport key.
SPORT_KEYS = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
}


class OddsSchemaError(RuntimeError):
    """Raised when a sport's response shape is not the expected JSON array."""


def _fetch_sport(sport_key: str, api_key: str, *, timeout: int = 30) -> list[dict[str, Any]]:
    url = f"{ODDS_API_BASE}/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise OddsSchemaError(f"{sport_key}: expected JSON array, got {type(data).__name__}")
    return data


def _normalize_game(raw: dict[str, Any], sport_key: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    home = str(raw.get("home_team") or "").strip()
    away = str(raw.get("away_team") or "").strip()
    if not home or not away:
        return None
    books_out: list[dict[str, Any]] = []
    for bm in raw.get("bookmakers") or []:
        if not isinstance(bm, dict):
            continue
        h2h = None
        for mkt in bm.get("markets") or []:
            if isinstance(mkt, dict) and mkt.get("key") == "h2h":
                h2h = mkt
                break
        if not h2h:
            continue
        outcomes = [
            {"team": str(oc.get("name") or "").strip(), "price": oc.get("price")}
            for oc in (h2h.get("outcomes") or [])
            if isinstance(oc, dict) and oc.get("name")
        ]
        if outcomes:
            books_out.append({"book": str(bm.get("key") or ""), "outcomes": outcomes})
    return {
        "game_id": str(raw.get("id") or f"{away}@{home}"),
        "sport": sport_key,
        "commence_time": str(raw.get("commence_time") or ""),
        "home_team": home,
        "away_team": away,
        "books": books_out,
    }


def _write_snapshot(snapshot: dict[str, Any]) -> Path:
    BETTING_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = BETTING_DIR / f"odds_{ts}.json"
    with dst.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, separators=(",", ":"), ensure_ascii=False)
    return dst


def _write_stamp() -> None:
    STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAMP_PATH.write_text(str(int(time.time())), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sports",
        default="nba,nfl,mlb,nhl",
        help="Comma list of sports to fetch (nba,nfl,mlb,nhl).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write the snapshot.")
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Read a pre-fetched normalized snapshot JSON instead of calling the API.",
    )
    args = parser.parse_args(argv)

    if args.from_file:
        try:
            snapshot = json.loads(args.from_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch_betting_odds] read failed: {exc}", file=sys.stderr)
            return 1
        games = snapshot.get("games", []) if isinstance(snapshot, dict) else []
        print(f"[fetch_betting_odds] loaded {len(games)} games from file")
        if not args.dry_run:
            dst = _write_snapshot(snapshot)
            _write_stamp()
            print(f"[fetch_betting_odds] wrote -> {dst}")
        return 0

    api_key = (os.getenv("ODDS_API_KEY") or "").strip()
    if not api_key:
        print("[fetch_betting_odds] ODDS_API_KEY is not set", file=sys.stderr)
        return 1

    requested = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    all_games: list[dict[str, Any]] = []
    for alias in requested:
        sport_key = SPORT_KEYS.get(alias)
        if not sport_key:
            print(f"[fetch_betting_odds] unknown sport '{alias}', skipping", file=sys.stderr)
            continue
        try:
            raw_games = _fetch_sport(sport_key, api_key)
        except OddsSchemaError as exc:
            print(f"[fetch_betting_odds] schema regression: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch_betting_odds] fetch failed for {sport_key}: {exc}", file=sys.stderr)
            return 1
        for raw in raw_games:
            game = _normalize_game(raw, sport_key)
            if game:
                all_games.append(game)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "the-odds-api",
        "sports": requested,
        "games": all_games,
    }
    print(f"[fetch_betting_odds] normalized {len(all_games)} games across {len(requested)} sports")

    if args.dry_run:
        print("[fetch_betting_odds] --dry-run; not writing snapshot")
        for g in all_games[:3]:
            print("  ", g["game"] if "game" in g else f"{g['away_team']} @ {g['home_team']}")
        return 0

    dst = _write_snapshot(snapshot)
    _write_stamp()
    print(f"[fetch_betting_odds] wrote {len(all_games)} games -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
