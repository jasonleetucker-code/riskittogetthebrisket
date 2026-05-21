"""Blend sportsbook odds + consensus into per-game betting recommendations.

This is the betting analogue of the dynasty rankings blend: take many
independent signals (sportsbook moneylines, and any free consensus we
can layer on) and produce one consensus recommendation per game.

Input is the normalized odds snapshot written by
``scripts/fetch_betting_odds.py`` (decoupled from any one vendor's wire
format).  Snapshot shape::

    {
      "generated_at": "2026-05-21T18:00:00Z",
      "source": "the-odds-api",
      "games": [
        {
          "game_id": "...",
          "sport": "basketball_nba",
          "commence_time": "2026-05-21T23:30:00Z",
          "home_team": "San Antonio Spurs",
          "away_team": "New York Knicks",
          "books": [
            {"book": "draftkings",
             "outcomes": [
               {"team": "New York Knicks", "price": -150},
               {"team": "San Antonio Spurs", "price": 130}
             ]}
          ]
        }
      ]
    }

Only two-way moneyline (head-to-head) markets are blended in v1 — they
map cleanly onto Kalshi "team to win" Yes/No contracts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def american_to_prob(odds: Any) -> float | None:
    """Convert American moneyline odds to implied probability (with vig)."""
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    # Reject NaN/inf: float("nan") parses without error but would
    # silently poison the de-vig math downstream.
    if not math.isfinite(o) or o == 0:
        return None
    if o > 0:
        return 100.0 / (o + 100.0)
    return -o / (-o + 100.0)


def _devig_two_way(p_a: float, p_b: float) -> tuple[float, float]:
    """Remove the bookmaker margin from a two-way market (normalize to 1)."""
    total = p_a + p_b
    if total <= 0:
        return 0.0, 0.0
    return p_a / total, p_b / total


def _blend_game(game: dict[str, Any]) -> dict[str, Any] | None:
    """Produce one recommendation for a single game, or None if unusable."""
    home = str(game.get("home_team") or "").strip()
    away = str(game.get("away_team") or "").strip()
    if not home or not away:
        return None
    books = game.get("books")
    if not isinstance(books, list) or not books:
        return None

    # Accumulate de-vigged probabilities per team across books.
    sums: dict[str, float] = {home: 0.0, away: 0.0}
    counts: dict[str, int] = {home: 0, away: 0}
    book_count = 0
    for book in books:
        if not isinstance(book, dict):
            continue
        outcomes = book.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        raw: dict[str, float] = {}
        for oc in outcomes:
            if not isinstance(oc, dict):
                continue
            team = str(oc.get("team") or "").strip()
            prob = american_to_prob(oc.get("price"))
            if team in sums and prob is not None:
                raw[team] = prob
        if home in raw and away in raw:
            ph, pa = _devig_two_way(raw[home], raw[away])
            sums[home] += ph
            counts[home] += 1
            sums[away] += pa
            counts[away] += 1
            book_count += 1

    if book_count == 0:
        return None

    avg_home = sums[home] / counts[home] if counts[home] else 0.0
    avg_away = sums[away] / counts[away] if counts[away] else 0.0
    if avg_home >= avg_away:
        side_team, fair_prob = home, avg_home
    else:
        side_team, fair_prob = away, avg_away

    fair_price_cents = max(1, min(99, round(fair_prob * 100)))
    # Confidence: blend of how strong the favorite is and how many books
    # agree.  0..1.  A near-coinflip with one book is low confidence; a
    # heavy favorite priced across many books is high.
    edge = abs(avg_home - avg_away)  # 0 (coinflip) .. ~1 (lock)
    book_factor = min(1.0, book_count / 5.0)
    confidence = round(min(1.0, 0.5 * edge * 2 + 0.5 * book_factor), 3)

    return {
        "game_id": str(game.get("game_id") or f"{away}@{home}"),
        "sport": str(game.get("sport") or ""),
        "commence_time": str(game.get("commence_time") or ""),
        "game": f"{away} @ {home}",
        "side_team": side_team,
        "side_label": f"{side_team} ML",
        "fair_prob": round(fair_prob, 4),
        "fair_price_cents": fair_price_cents,
        "consensus_pct": round(fair_prob * 100, 1),
        "book_count": book_count,
        "confidence": confidence,
    }


def build_recommendations(
    snapshot: dict[str, Any],
    *,
    min_books: int = 1,
) -> list[dict[str, Any]]:
    """Blend a normalized odds snapshot into per-game recommendations.

    Sorted by confidence descending.  Games with fewer than ``min_books``
    contributing books are dropped.
    """
    if not isinstance(snapshot, dict):
        return []
    games = snapshot.get("games")
    if not isinstance(games, list):
        return []
    out: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        rec = _blend_game(game)
        if rec and rec["book_count"] >= min_books:
            out.append(rec)
    out.sort(key=lambda r: r["confidence"], reverse=True)
    return out


def load_snapshot(path: Path) -> dict[str, Any]:
    """Read a normalized odds snapshot JSON file.  Returns {} if missing/bad."""
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def latest_snapshot_path(betting_dir: Path) -> Path | None:
    """Return the newest ``odds_*.json`` in ``betting_dir`` or None."""
    try:
        candidates = sorted(Path(betting_dir).glob("odds_*.json"))
    except OSError:
        return None
    return candidates[-1] if candidates else None
