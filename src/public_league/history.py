"""Section: League History / Hall of Fame.

Aggregates per-season finishes, champions, and cumulative records
across the dynasty chain.  Attribution is by owner_id, so renames
and orphaned-roster handoffs never split or merge managers.
"""
from __future__ import annotations

from typing import Any

from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _final_standing_from_bracket(bracket: list[dict[str, Any]]) -> dict[int, int]:
    """Return roster_id -> final playoff place (1 = champion).

    Sleeper's bracket array has ``p`` (place) annotations only on the
    last round of each bracket.  We walk the bracket and record the
    place of each winner / loser so this also handles 3rd place games
    and consolation brackets.
    """
    placement: dict[int, int] = {}
    for matchup in bracket:
        if not isinstance(matchup, dict):
            continue
        p = matchup.get("p")
        if p is None:
            continue
        winner = matchup.get("w")
        loser = matchup.get("l")
        try:
            place = int(p)
        except (TypeError, ValueError):
            continue
        if winner is not None:
            try:
                placement.setdefault(int(winner), place)
            except (TypeError, ValueError):
                pass
        if loser is not None:
            try:
                placement.setdefault(int(loser), place + 1)
            except (TypeError, ValueError):
                pass
    return placement


def _regular_season_records(season: SeasonSnapshot) -> dict[int, dict[str, Any]]:
    """Return roster_id -> {wins, losses, ties, points_for, points_against}
    from Sleeper roster settings.
    """
    out: dict[int, dict[str, Any]] = {}
    for roster in season.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        settings = roster.get("settings") or {}

        def _num(key: str) -> float:
            val = settings.get(key)
            try:
                return float(val or 0)
            except (TypeError, ValueError):
                return 0.0

        points_for = _num("fpts") + (_num("fpts_decimal") / 100.0)
        points_against = _num("fpts_against") + (_num("fpts_against_decimal") / 100.0)
        out[rid] = {
            "wins": int(_num("wins")),
            "losses": int(_num("losses")),
            "ties": int(_num("ties")),
            "pointsFor": round(points_for, 2),
            "pointsAgainst": round(points_against, 2),
        }
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Build the League History / Hall of Fame block."""
    seasons_out: list[dict[str, Any]] = []
    manager_totals: dict[str, dict[str, Any]] = {}
    champions_by_season: list[dict[str, Any]] = []

    for season in snapshot.seasons:
        regular = _regular_season_records(season)
        placement = _final_standing_from_bracket(season.winners_bracket)

        standings: list[dict[str, Any]] = []
        for rid, rec in regular.items():
            owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
            if not owner_id:
                continue
            row = {
                "ownerId": owner_id,
                "rosterId": rid,
                "teamName": _team_name_for(snapshot, season.league_id, rid),
                "wins": rec["wins"],
                "losses": rec["losses"],
                "ties": rec["ties"],
                "pointsFor": rec["pointsFor"],
                "pointsAgainst": rec["pointsAgainst"],
                "finalPlace": placement.get(rid),
            }
            standings.append(row)

            totals = manager_totals.setdefault(owner_id, {
                "ownerId": owner_id,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
                "seasonsPlayed": 0,
                "championships": 0,
                "runnerUps": 0,
                "toiletBowls": 0,
            })
            totals["wins"] += row["wins"]
            totals["losses"] += row["losses"]
            totals["ties"] += row["ties"]
            totals["pointsFor"] += row["pointsFor"]
            totals["pointsAgainst"] += row["pointsAgainst"]
            totals["seasonsPlayed"] += 1
            if placement.get(rid) == 1:
                totals["championships"] += 1
            elif placement.get(rid) == 2:
                totals["runnerUps"] += 1
            if placement.get(rid) == max(placement.values(), default=0):
                totals["toiletBowls"] += 1

        standings.sort(
            key=lambda r: (-(r["wins"] + r["ties"] * 0.5), -r["pointsFor"])
        )

        champion = next((r for r in standings if r.get("finalPlace") == 1), None)
        runner_up = next((r for r in standings if r.get("finalPlace") == 2), None)
        if champion:
            champions_by_season.append({
                "season": season.season,
                "leagueId": season.league_id,
                "ownerId": champion["ownerId"],
                "teamName": champion["teamName"],
            })

        seasons_out.append({
            "season": season.season,
            "leagueId": season.league_id,
            "seasonStatus": str(season.league.get("status") or ""),
            "isComplete": season.is_complete,
            "numTeams": season.num_teams,
            "standings": standings,
            "champion": {
                "ownerId": champion["ownerId"],
                "teamName": champion["teamName"],
            } if champion else None,
            "runnerUp": {
                "ownerId": runner_up["ownerId"],
                "teamName": runner_up["teamName"],
            } if runner_up else None,
        })

    hall_of_fame = sorted(
        manager_totals.values(),
        key=lambda m: (-m["championships"], -(m["wins"] + m["ties"] * 0.5), -m["pointsFor"]),
    )
    for row in hall_of_fame:
        row["pointsFor"] = round(row["pointsFor"], 2)
        row["pointsAgainst"] = round(row["pointsAgainst"], 2)
        mgr = snapshot.managers.by_owner_id.get(row["ownerId"])
        row["displayName"] = mgr.display_name if mgr else ""
        row["currentTeamName"] = mgr.current_team_name if mgr else ""

    return {
        "seasons": seasons_out,
        "championsBySeason": champions_by_season,
        "hallOfFame": hall_of_fame,
    }


def _team_name_for(snapshot: PublicLeagueSnapshot, league_id: str, rid: int) -> str:
    """Return the historical team name for a roster in a league."""
    owner_id = snapshot.managers.owner_for_roster(league_id, rid)
    manager = snapshot.managers.by_owner_id.get(owner_id)
    if not manager:
        return f"Team {rid}"
    for alias in manager.aliases:
        if alias.league_id == league_id and alias.roster_id == rid:
            return alias.team_name
    return manager.current_team_name or manager.display_name or f"Team {rid}"
