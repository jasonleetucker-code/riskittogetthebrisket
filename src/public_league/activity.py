"""Section: Trade Activity Center.

Public-safe trade feed + counts.  Each trade lists the players and
picks that moved, keyed to the owner who held the roster AT the time
of the trade (via the ``roster_to_owner`` map built by identity.py).

NO private "edge signals", NO "winner/loser" verdicts, NO internal
valuation output.  This is a pure log of what moved + when.
"""
from __future__ import annotations

from typing import Any

from .history import _team_name_for
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _format_pick_asset(pick: dict[str, Any]) -> dict[str, Any]:
    season = pick.get("season")
    round_ = pick.get("round")
    try:
        season_int = int(season)
    except (TypeError, ValueError):
        season_int = None
    try:
        round_int = int(round_)
    except (TypeError, ValueError):
        round_int = None
    return {
        "kind": "pick",
        "season": str(season) if season is not None else "",
        "round": round_int,
        "fromRosterId": pick.get("roster_id"),
        "label": (
            f"{season_int} R{round_int}" if season_int and round_int else f"{season} R{round_}"
        ),
    }


def _trade_side(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, rid: int, adds: list[str], drops: list[str], draft_picks: list[dict[str, Any]]) -> dict[str, Any]:
    owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
    return {
        "rosterId": rid,
        "ownerId": owner_id,
        "teamName": _team_name_for(snapshot, season.league_id, rid) if owner_id else f"Team {rid}",
        "receivedPlayerIds": list(adds),
        "sentPlayerIds": list(drops),
        "receivedPicks": [_format_pick_asset(p) for p in draft_picks],
    }


def _normalize_trade(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, tx: dict[str, Any]) -> dict[str, Any] | None:
    if str(tx.get("type") or "").lower() != "trade":
        return None
    if str(tx.get("status") or "").lower() != "complete":
        return None

    roster_ids = [int(rid) for rid in (tx.get("roster_ids") or []) if isinstance(rid, (int, str)) and str(rid).lstrip("-").isdigit()]
    if len(roster_ids) < 2:
        return None

    adds_map = tx.get("adds") or {}
    drops_map = tx.get("drops") or {}
    picks_by_owner: dict[int, list[dict[str, Any]]] = {}
    for pk in tx.get("draft_picks") or []:
        try:
            owner_rid = int(pk.get("owner_id"))
        except (TypeError, ValueError):
            continue
        picks_by_owner.setdefault(owner_rid, []).append(pk)

    sides = []
    for rid in roster_ids:
        adds = [pid for pid, r in adds_map.items() if int(r) == rid]
        drops = [pid for pid, r in drops_map.items() if int(r) == rid]
        picks = picks_by_owner.get(rid, [])
        if not adds and not drops and not picks:
            continue
        sides.append(_trade_side(snapshot, season, rid, adds, drops, picks))

    if not sides:
        return None

    return {
        "transactionId": str(tx.get("transaction_id") or ""),
        "season": season.season,
        "leagueId": season.league_id,
        "week": tx.get("leg"),
        "createdAt": tx.get("created") or tx.get("status_updated"),
        "sides": sides,
    }


def build_section(snapshot: PublicLeagueSnapshot, limit: int = 100) -> dict[str, Any]:
    feed: list[dict[str, Any]] = []
    per_season_counts: list[dict[str, Any]] = []

    for season in snapshot.seasons:
        season_count = 0
        for week_tx in season.transactions_by_week.values():
            for tx in week_tx:
                normalized = _normalize_trade(snapshot, season, tx)
                if normalized:
                    feed.append(normalized)
                    season_count += 1
        per_season_counts.append({
            "season": season.season,
            "leagueId": season.league_id,
            "tradeCount": season_count,
        })

    feed.sort(key=lambda t: -int(t.get("createdAt") or 0))
    return {
        "feed": feed[:limit],
        "totalCount": len(feed),
        "perSeasonCounts": per_season_counts,
    }
