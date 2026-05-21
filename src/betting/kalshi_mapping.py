"""Map a betting recommendation onto a concrete Kalshi market + side.

A recommendation says "take the Knicks ML".  To place an order we need
a Kalshi market ticker and whether to buy ``yes`` or ``no``.  Kalshi
sports markets are typically framed as "Will <TEAM> win?" so taking a
team usually means buying ``yes`` on that team's market.

The matching here is best-effort and string-based: Kalshi's exact
ticker/title schema varies by sport and evolves, so we score candidate
markets by team-name and date overlap and return the best match.  The
pure scorer (``score_market``) is unit-testable without the network;
``resolve_market`` wraps it with a live Kalshi query.

If auto-matching fails, the UI lets the user paste a ticker manually —
so a schema drift degrades to a manual step, never a hard failure.
"""

from __future__ import annotations

import re
from typing import Any

_STOPWORDS = frozenset(
    {"will", "win", "the", "vs", "at", "game", "to", "beat", "match", "yes", "no"}
)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _team_tokens(team: str) -> set[str]:
    """Tokens for a team, biased toward the distinctive last word (nickname).

    "New York Knicks" → {"new", "york", "knicks"}; the nickname "knicks"
    is the most reliable match key against Kalshi titles.
    """
    return _tokens(team)


def score_market(market: dict[str, Any], *, team: str, opponent: str) -> float:
    """Score how well a Kalshi market matches "<team> beats <opponent>".

    Looks at the market's ``title``/``subtitle``/``yes_sub_title`` and
    ``ticker``.  Returns a float; higher is better.  0 means no match.
    """
    if not isinstance(market, dict):
        return 0.0
    haystack = " ".join(
        str(market.get(k) or "")
        for k in ("title", "subtitle", "yes_sub_title", "ticker", "event_ticker")
    )
    hay = _tokens(haystack)
    if not hay:
        return 0.0
    team_tok = _team_tokens(team)
    opp_tok = _team_tokens(opponent)
    team_hits = len(team_tok & hay)
    opp_hits = len(opp_tok & hay)
    if team_hits == 0:
        return 0.0
    # Reward presence of both teams (correct game) and the target team
    # being the market's subject.
    score = team_hits * 2.0 + opp_hits * 1.0
    # Bonus when the target team appears in the yes-side subtitle —
    # that's the contract that pays if the team wins.
    yes_sub = _tokens(market.get("yes_sub_title") or market.get("title") or "")
    if team_tok & yes_sub:
        score += 1.5
    return score


def select_market(
    markets: list[dict[str, Any]],
    *,
    team: str,
    opponent: str,
    min_score: float = 2.0,
) -> dict[str, Any] | None:
    """Pick the best-matching market for taking ``team`` over ``opponent``.

    Returns ``{"ticker", "side", "score", "market"}`` or None.  ``side``
    is ``"yes"`` (the team's market resolves yes if they win).
    """
    best: dict[str, Any] | None = None
    best_score = 0.0
    for m in markets or []:
        s = score_market(m, team=team, opponent=opponent)
        if s > best_score:
            best_score = s
            best = m
    if best is None or best_score < min_score:
        return None
    ticker = str(best.get("ticker") or "").strip()
    if not ticker:
        return None
    return {"ticker": ticker, "side": "yes", "score": best_score, "market": best}


# ── sport → Kalshi series ticker prefixes ────────────────────────────────
# Used to narrow the markets query.  These are the public game-winner
# series prefixes; confirm/extend against live Kalshi data at integration.
_SPORT_SERIES = {
    "basketball_nba": "KXNBAGAME",
    "americanfootball_nfl": "KXNFLGAME",
    "baseball_mlb": "KXMLBGAME",
    "icehockey_nhl": "KXNHLGAME",
}


def series_for_sport(sport: str) -> str | None:
    return _SPORT_SERIES.get(str(sport).strip().lower())


def resolve_market(client: Any, recommendation: dict[str, Any]) -> dict[str, Any] | None:
    """Query Kalshi and return the best market match for a recommendation.

    Best-effort: returns None when no confident match is found, leaving
    the UI to fall back to manual ticker entry.  ``client`` is a
    ``KalshiClient``; passed in so this stays testable with a fake.
    """
    side_team = str(recommendation.get("side_team") or "")
    game = str(recommendation.get("game") or "")
    # Derive opponent from the "AWAY @ HOME" label.
    opponent = ""
    if "@" in game:
        away, home = (p.strip() for p in game.split("@", 1))
        opponent = home if side_team == away else away
    if not side_team:
        return None

    params: dict[str, Any] = {"status": "open", "limit": 200}
    series = series_for_sport(recommendation.get("sport", ""))
    if series:
        params["series_ticker"] = series
    try:
        resp = client.get_markets(**params)
    except Exception:
        return None
    markets = resp.get("markets") if isinstance(resp, dict) else None
    if not isinstance(markets, list):
        return None
    return select_market(markets, team=side_team, opponent=opponent)
