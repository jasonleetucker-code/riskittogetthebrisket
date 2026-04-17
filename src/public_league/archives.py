"""Section: Public searchable archives / databases.

Normalized, filterable record sets:
    * trades      — {season, leagueId, week, ownerIds, playerNames,
                     positions, assetTypes, award tags}
    * waivers     — {season, week, ownerId, playerName, position, bid}
    * weeklyMatchups — {season, week, matchupId, homeOwnerId, awayOwnerId,
                       points, result}
    * rookieDrafts — {season, round, pickNo, ownerId, playerName, position}
    * seasonResults — {season, ownerId, wins, losses, pointsFor,
                       finalPlace, award tags}

Every record exposes the fields the UI needs to filter by:
season, week (where applicable), manager (ownerId), player, trade
partner (ownerIds), position, asset type, and a ``tags`` list with
award labels when relevant.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .activity import build_section as build_activity
from .awards import build_section as build_awards
from .draft import build_section as build_draft
from .history import build_section as build_history
from .player_journey import list_players_with_activity
from .snapshot import PublicLeagueSnapshot


def _award_tags_by_owner(awards_section: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """Return (season, ownerId) -> [award labels]."""
    out: dict[tuple[str, str], list[str]] = {}
    for season_row in awards_section.get("bySeason", []):
        season = season_row["season"]
        for award in season_row.get("awards", []):
            out.setdefault((season, award["ownerId"]), []).append(award["label"])
    return out


def _trade_archives(snapshot: PublicLeagueSnapshot, activity: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in activity.get("feed", []):
        owners = [s["ownerId"] for s in trade["sides"] if s.get("ownerId")]
        player_names: list[str] = []
        positions: list[str] = []
        asset_types: set[str] = set()
        for side in trade["sides"]:
            for asset in side.get("receivedAssets", []):
                asset_types.add(asset["kind"])
                if asset["kind"] == "player":
                    if asset.get("playerName"):
                        player_names.append(asset["playerName"])
                    if asset.get("position"):
                        positions.append(asset["position"])
        rows.append({
            "kind": "trade",
            "transactionId": trade["transactionId"],
            "season": trade["season"],
            "leagueId": trade["leagueId"],
            "week": trade.get("week"),
            "createdAt": trade.get("createdAt"),
            "ownerIds": owners,
            "playerNames": player_names,
            "positions": positions,
            "assetTypes": sorted(asset_types),
            "totalAssets": trade["totalAssets"],
            "tags": [],
        })
    return rows


def _waiver_archives(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for tx in season.waivers():
            settings = tx.get("settings") or {}
            bid = settings.get("waiver_bid")
            try:
                bid_n = int(bid) if bid is not None else None
            except (TypeError, ValueError):
                bid_n = None
            adds = tx.get("adds") or {}
            drops = tx.get("drops") or {}
            roster_ids = tx.get("roster_ids") or []
            primary_rid = int(roster_ids[0]) if roster_ids else None
            owner_id = (
                metrics.resolve_owner(snapshot.managers, season.league_id, primary_rid)
                if primary_rid is not None
                else ""
            )
            added_players = [
                {
                    "playerId": pid,
                    "playerName": snapshot.player_display(pid),
                    "position": snapshot.player_position(pid),
                }
                for pid in adds.keys()
            ]
            dropped_players = [
                {
                    "playerId": pid,
                    "playerName": snapshot.player_display(pid),
                    "position": snapshot.player_position(pid),
                }
                for pid in drops.keys()
            ]
            rows.append({
                "kind": "waiver",
                "transactionId": str(tx.get("transaction_id") or ""),
                "season": season.season,
                "leagueId": season.league_id,
                "week": tx.get("_leg"),
                "createdAt": tx.get("created") or tx.get("status_updated"),
                "ownerId": owner_id,
                "rosterId": primary_rid,
                "bid": bid_n,
                "added": added_players,
                "dropped": dropped_players,
                "type": str(tx.get("type") or "").lower(),
                "tags": [],
            })
    rows.sort(key=lambda r: -(int(r.get("createdAt") or 0)))
    return rows


def _weekly_matchup_archives(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        is_playoff_threshold = season.playoff_week_start
        for week in sorted(season.matchups_by_week.keys()):
            is_playoff = week >= is_playoff_threshold
            for a, b in metrics.matchup_pairs(season.matchups_by_week[week]):
                if not metrics.is_scored(a) and not metrics.is_scored(b):
                    continue
                rid_a = metrics.roster_id_of(a)
                rid_b = metrics.roster_id_of(b)
                owner_a = metrics.resolve_owner(snapshot.managers, season.league_id, rid_a)
                owner_b = metrics.resolve_owner(snapshot.managers, season.league_id, rid_b)
                pa = metrics.matchup_points(a)
                pb = metrics.matchup_points(b)
                if pa > pb:
                    winner = owner_a
                elif pb > pa:
                    winner = owner_b
                else:
                    winner = ""
                rows.append({
                    "kind": "weekly_matchup",
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": week,
                    "isPlayoff": is_playoff,
                    "matchupId": a.get("matchup_id"),
                    "homeOwnerId": owner_a,
                    "awayOwnerId": owner_b,
                    "homeRosterId": rid_a,
                    "awayRosterId": rid_b,
                    "homePoints": round(pa, 2),
                    "awayPoints": round(pb, 2),
                    "winnerOwnerId": winner,
                    "margin": round(abs(pa - pb), 2),
                    "tags": ["playoff"] if is_playoff else [],
                })
    return rows


def _rookie_draft_archives(snapshot: PublicLeagueSnapshot, draft_section: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for draft in draft_section.get("drafts", []):
        if str(draft.get("type") or "").lower() not in {"rookie", "rookie_draft"}:
            # Include any draft marked as rookie; also include first-round
            # entries from other dynasty drafts for completeness.
            pass
        for pick in draft.get("picks", []):
            if not pick.get("playerName"):
                continue
            rows.append({
                "kind": "rookie_draft",
                "draftId": draft["draftId"],
                "season": draft["season"],
                "leagueId": draft["leagueId"],
                "round": pick["round"],
                "pickNo": pick["pickNo"],
                "ownerId": pick["ownerId"],
                "rosterId": pick["rosterId"],
                "teamName": pick["teamName"],
                "playerId": pick["playerId"],
                "playerName": pick["playerName"],
                "position": pick.get("position"),
                "nflTeam": pick.get("nflTeam"),
                "tags": [],
            })
    return rows


def _season_result_archives(snapshot: PublicLeagueSnapshot, history_section: dict[str, Any], award_tags: dict[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season_row in history_section.get("seasons", []):
        season = season_row["season"]
        league_id = season_row["leagueId"]
        for standing in season_row.get("standings", []):
            owner_id = standing["ownerId"]
            tags = list(award_tags.get((season, owner_id), []))
            if standing.get("finalPlace") == 1:
                tags.append("champion")
            rows.append({
                "kind": "season_result",
                "season": season,
                "leagueId": league_id,
                "ownerId": owner_id,
                "rosterId": standing["rosterId"],
                "teamName": standing["teamName"],
                "wins": standing["wins"],
                "losses": standing["losses"],
                "ties": standing["ties"],
                "pointsFor": standing["pointsFor"],
                "pointsAgainst": standing["pointsAgainst"],
                "finalPlace": standing.get("finalPlace"),
                "madePlayoffs": standing["madePlayoffs"],
                "standing": standing["standing"],
                "tags": sorted(set(tags)),
            })
    return rows


def _manager_index(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manager in snapshot.managers.ordered_managers():
        rows.append({
            "kind": "manager",
            "ownerId": manager.owner_id,
            "displayName": manager.display_name,
            "currentTeamName": manager.current_team_name,
            "aliases": [a.team_name for a in manager.aliases],
        })
    return rows


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    history_section = build_history(snapshot)
    activity_section = build_activity(snapshot, limit=500)
    draft_section = build_draft(snapshot)
    awards_section = build_awards(snapshot)
    award_tags = _award_tags_by_owner(awards_section)

    trades_archive = _trade_archives(snapshot, activity_section)
    for trade in trades_archive:
        tags = award_tags.get((trade["season"], ""), [])
        trade["tags"] = sorted(set(tags))

    # Named players who appear in any roster/transaction — each row
    # links to the player-journey page.  Only players with a resolved
    # display name make the cut so we don't ship IDs for stale/orphan
    # player records.
    players_archive = [
        {"kind": "player", **p}
        for p in list_players_with_activity(snapshot)
        if p.get("playerName")
    ]

    return {
        "managers": _manager_index(snapshot),
        "trades": trades_archive,
        "waivers": _waiver_archives(snapshot),
        "weeklyMatchups": _weekly_matchup_archives(snapshot),
        "rookieDrafts": _rookie_draft_archives(snapshot, draft_section),
        "seasonResults": _season_result_archives(snapshot, history_section, award_tags),
        "players": players_archive,
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
