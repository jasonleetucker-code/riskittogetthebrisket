"""Section: Public searchable archives / databases.

A slim searchable index of public-safe facts: trades, drafts, weekly
results, and manager aliases.  The frontend uses this as a fallback
search corpus so the public /league page doesn't need to hit any
private endpoint.

Every record carries ``ownerId`` + ``season`` + ``leagueId`` so
results can deep-link back to franchise pages.
"""
from __future__ import annotations

from typing import Any

from .activity import build_section as build_activity
from .draft import build_section as build_draft
from .history import _team_name_for
from .snapshot import PublicLeagueSnapshot


def _index_managers(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
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


def _index_trades(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    # Reuse the activity feed — it already has public-safe fields.
    activity = build_activity(snapshot, limit=500)
    rows: list[dict[str, Any]] = []
    for t in activity["feed"]:
        rows.append({
            "kind": "trade",
            "transactionId": t["transactionId"],
            "season": t["season"],
            "leagueId": t["leagueId"],
            "ownerIds": [s["ownerId"] for s in t["sides"] if s.get("ownerId")],
            "week": t.get("week"),
            "createdAt": t.get("createdAt"),
        })
    return rows


def _index_draft_picks(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    draft = build_draft(snapshot)
    rows: list[dict[str, Any]] = []
    for d in draft["drafts"]:
        for p in d["picks"]:
            if not p.get("playerName"):
                continue
            rows.append({
                "kind": "draft_pick",
                "draftId": d["draftId"],
                "season": d["season"],
                "leagueId": d["leagueId"],
                "round": p["round"],
                "pickNo": p["pickNo"],
                "ownerId": p["ownerId"],
                "teamName": p["teamName"],
                "playerName": p["playerName"],
                "position": p.get("position"),
                "nflTeam": p.get("nflTeam"),
            })
    return rows


def _index_weeks(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for week, entries in season.matchups_by_week.items():
            for m in entries:
                try:
                    rid = int(m.get("roster_id"))
                except (TypeError, ValueError):
                    continue
                owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                if not owner_id:
                    continue
                pts = float(m.get("points") or 0.0)
                if pts <= 0:
                    continue
                rows.append({
                    "kind": "week_score",
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": week,
                    "ownerId": owner_id,
                    "teamName": _team_name_for(snapshot, season.league_id, rid),
                    "points": round(pts, 2),
                })
    return rows


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    return {
        "managers": _index_managers(snapshot),
        "trades": _index_trades(snapshot),
        "draftPicks": _index_draft_picks(snapshot),
        "weekScores": _index_weeks(snapshot),
    }
