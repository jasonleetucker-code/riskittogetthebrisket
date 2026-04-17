"""Section: Trade Activity Center.

Public-safe trade feed + rollups.  No private valuation columns.
Computes:
    * trades by season
    * trades by manager
    * most active trader
    * most frequent trade partner pair
    * biggest blockbuster by total assets moved (players + picks)
    * trade timeline by week
    * position mix moved in trades
    * picks moved count / players moved count

Blockbuster tiebreaks (prompt spec):
    1. Most total moved assets
    2. Most distinct starters / notable players moved (approx: count
       of moved assets whose Sleeper position is in the offensive
       core of {QB, RB, WR, TE})
    3. Combined end-of-season internal values — server-side only,
       NEVER exposed on the public payload.  We use it as a silent
       deterministic tiebreaker and drop the raw number from the
       response.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


OFFENSIVE_CORE = {"QB", "RB", "WR", "TE"}
# Any position we consider "notable" enough for the tiebreak.
NOTABLE_POSITIONS = OFFENSIVE_CORE | {"DL", "LB", "DB", "EDGE"}


def _pick_asset(pick: dict[str, Any], snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
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


def _player_asset(player_id: str, snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    return {
        "kind": "player",
        "playerId": str(player_id),
        "playerName": snapshot.player_display(player_id),
        "position": snapshot.player_position(player_id),
    }


def _normalize_trade(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, tx: dict[str, Any]) -> dict[str, Any] | None:
    roster_ids = []
    for rid in tx.get("roster_ids") or []:
        try:
            roster_ids.append(int(rid))
        except (TypeError, ValueError):
            continue
    if len(roster_ids) < 2:
        return None

    adds_map = tx.get("adds") or {}
    drops_map = tx.get("drops") or {}
    picks_by_owner: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for pk in tx.get("draft_picks") or []:
        try:
            owner_rid = int(pk.get("owner_id"))
        except (TypeError, ValueError):
            continue
        picks_by_owner[owner_rid].append(pk)

    sides = []
    total_assets = 0
    total_notable = 0
    for rid in roster_ids:
        owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        received_player_ids = [pid for pid, r in adds_map.items() if int(r) == rid]
        sent_player_ids = [pid for pid, r in drops_map.items() if int(r) == rid]
        received_picks = picks_by_owner.get(rid, [])
        received_assets = [_player_asset(pid, snapshot) for pid in received_player_ids] + [
            _pick_asset(p, snapshot) for p in received_picks
        ]
        if not received_assets and not sent_player_ids:
            continue
        side_note_count = sum(1 for a in received_assets if a.get("position") in NOTABLE_POSITIONS)
        total_assets += len(received_assets)
        total_notable += side_note_count
        sides.append({
            "rosterId": rid,
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
            "teamName": metrics.team_name(snapshot, season.league_id, rid) if owner_id else f"Team {rid}",
            "receivedAssets": received_assets,
            "sentPlayerIds": list(sent_player_ids),
            "receivedPlayerCount": len(received_player_ids),
            "receivedPickCount": len(received_picks),
            "notableAssetCount": side_note_count,
        })

    if not sides:
        return None

    return {
        "transactionId": str(tx.get("transaction_id") or ""),
        "season": season.season,
        "leagueId": season.league_id,
        "week": tx.get("leg") or tx.get("_leg"),
        "createdAt": tx.get("created") or tx.get("status_updated"),
        "sides": sides,
        "totalAssets": total_assets,
        "notableAssetCount": total_notable,
    }


def _position_mix(feed: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter = Counter()
    for trade in feed:
        for side in trade["sides"]:
            for asset in side["receivedAssets"]:
                if asset["kind"] != "player":
                    continue
                pos = asset.get("position") or "UNK"
                counter[pos] += 1
    return dict(counter)


def _by_manager_counts(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_counts: Counter = Counter()
    for t in feed:
        seen_owners = {side["ownerId"] for side in t["sides"] if side.get("ownerId")}
        for owner in seen_owners:
            trade_counts[owner] += 1
    rows = [{"ownerId": owner, "trades": n} for owner, n in trade_counts.items()]
    rows.sort(key=lambda r: -r["trades"])
    return rows


def _partner_pairs(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pair_counts: Counter = Counter()
    for t in feed:
        owners = sorted({side["ownerId"] for side in t["sides"] if side.get("ownerId")})
        if len(owners) < 2:
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                pair_counts[(owners[i], owners[j])] += 1
    rows = [{"ownerIds": list(pair), "trades": n} for pair, n in pair_counts.items()]
    rows.sort(key=lambda r: -r["trades"])
    return rows


def _server_side_tiebreak_score(trade: dict[str, Any]) -> float:
    """Internal tiebreak — NEVER exposed on the public payload.

    Approximates "combined end-of-season internal values" using a
    simple proxy: sum of notable-asset counts per side times the
    count of received picks (earlier rounds carry more weight).
    The raw number is intentionally opaque.
    """
    score = 0.0
    for side in trade["sides"]:
        score += side["notableAssetCount"] * 1.5
        for asset in side["receivedAssets"]:
            if asset["kind"] == "pick":
                r = asset.get("round") or 5
                score += max(0.0, 5.0 - r)
    return score


def _biggest_blockbusters(feed: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    ordered = sorted(
        feed,
        key=lambda t: (
            -t["totalAssets"],
            -t["notableAssetCount"],
            -_server_side_tiebreak_score(t),
        ),
    )
    top = []
    for t in ordered[:n]:
        # Strip internal tiebreaker output — it was only used for
        # ordering, never returned.
        row = {k: v for k, v in t.items() if k != "_tiebreak"}
        top.append(row)
    return top


def _timeline_by_week(feed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], int] = defaultdict(int)
    for t in feed:
        wk = t.get("week") or 0
        grouped[(t["season"], int(wk))] += 1
    rows = [
        {"season": season, "week": week, "trades": n}
        for (season, week), n in grouped.items()
    ]
    rows.sort(key=lambda r: (r["season"], r["week"]))
    return rows


def build_section(snapshot: PublicLeagueSnapshot, limit: int = 200) -> dict[str, Any]:
    feed: list[dict[str, Any]] = []
    per_season_counts: list[dict[str, Any]] = []
    picks_moved = 0
    players_moved = 0

    for season in snapshot.seasons:
        season_trades = 0
        for tx in season.trades():
            normalized = _normalize_trade(snapshot, season, tx)
            if normalized:
                feed.append(normalized)
                season_trades += 1
                for side in normalized["sides"]:
                    picks_moved += side["receivedPickCount"]
                    players_moved += side["receivedPlayerCount"]
        per_season_counts.append({
            "season": season.season,
            "leagueId": season.league_id,
            "tradeCount": season_trades,
        })

    feed.sort(key=lambda t: -int(t.get("createdAt") or 0))
    by_manager = _by_manager_counts(feed)
    partner_pairs = _partner_pairs(feed)
    blockbusters = _biggest_blockbusters(feed)
    timeline = _timeline_by_week(feed)
    position_mix = _position_mix(feed)

    most_active = by_manager[0] if by_manager else None
    if most_active:
        most_active = {
            **most_active,
            "displayName": metrics.display_name_for(snapshot, most_active["ownerId"]),
        }
    partner_display = None
    if partner_pairs:
        top_pair = partner_pairs[0]
        partner_display = {
            "ownerIds": top_pair["ownerIds"],
            "trades": top_pair["trades"],
            "displayNames": [
                metrics.display_name_for(snapshot, oid) for oid in top_pair["ownerIds"]
            ],
        }

    return {
        "feed": feed[:limit],
        "totalCount": len(feed),
        "perSeasonCounts": per_season_counts,
        "byManager": by_manager,
        "partnerPairs": partner_pairs,
        "mostActiveTrader": most_active,
        "mostFrequentPartnerPair": partner_display,
        "biggestBlockbusters": blockbusters,
        "timelineByWeek": timeline,
        "positionMixMoved": position_mix,
        "picksMovedCount": picks_moved,
        "playersMovedCount": players_moved,
    }
