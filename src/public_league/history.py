"""Section: League History / Hall of Fame.

Computes per-season:
    * Champion (winners_bracket p=1 winner, fallback placement 1,
      final fallback league.metadata.latest_league_winner_roster_id)
    * Runner-up (placement 2, fallback = loser of p=1 matchup)
    * Top seed (best regular-season win%, tiebreak PF desc, PA asc,
      sleeperRank asc)
    * Regular-season points leader
    * Best regular-season record
    * Playoff teams (every roster_id that appears in the winners
      bracket)
    * Final standings

Across the 2-season window:
    * Title count, finals appearances, playoff appearances, reg-season
      first-place finishes per owner_id.

Everything attributes to ``owner_id`` at the time of the season so
an orphaned roster that changed hands between seasons stays split.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _best_record_owner(standings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not standings:
        return None
    # ``standings`` is already sorted by win%.
    return standings[0]


def _points_leader_owner(standings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not standings:
        return None
    return sorted(standings, key=lambda r: -r["pointsFor"])[0]


def _season_block(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> dict[str, Any]:
    standings = metrics.season_standings(season, snapshot.managers)
    placement = metrics.playoff_placement(season.winners_bracket)
    playoff_rids = set(metrics.playoff_teams(season.winners_bracket))

    champion_rid = metrics.season_champion(season)
    runner_up_rid = metrics.season_runner_up(season)
    top_seed_row = metrics.top_seed(standings)
    best_record = _best_record_owner(standings)
    points_leader = _points_leader_owner(standings)

    # Merge placement + team-name enrichment onto standings rows.
    for row in standings:
        row["finalPlace"] = placement.get(row["rosterId"])
        row["madePlayoffs"] = row["rosterId"] in playoff_rids
        row["teamName"] = metrics.team_name(snapshot, season.league_id, row["rosterId"])

    def _wrap(rid: int | None) -> dict[str, Any] | None:
        if rid is None:
            return None
        owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        if not owner_id:
            return None
        return {
            "ownerId": owner_id,
            "rosterId": rid,
            "teamName": metrics.team_name(snapshot, season.league_id, rid),
            "displayName": metrics.display_name_for(snapshot, owner_id),
        }

    return {
        "season": season.season,
        "leagueId": season.league_id,
        "seasonStatus": str(season.league.get("status") or ""),
        "isComplete": season.is_complete,
        "numTeams": season.num_teams,
        "playoffWeekStart": season.playoff_week_start,
        "champion": _wrap(champion_rid),
        "runnerUp": _wrap(runner_up_rid),
        "topSeed": _wrap(top_seed_row["rosterId"]) if top_seed_row else None,
        "regularSeasonPointsLeader": _wrap(points_leader["rosterId"]) if points_leader else None,
        "bestRegularSeasonRecord": _wrap(best_record["rosterId"]) if best_record else None,
        "playoffTeams": [
            _wrap(rid) for rid in sorted(playoff_rids) if _wrap(rid) is not None
        ],
        "standings": standings,
    }


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    seasons_out: list[dict[str, Any]] = []
    champions_by_season: list[dict[str, Any]] = []
    manager_totals: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in manager_totals:
            mgr = snapshot.managers.by_owner_id.get(owner_id)
            manager_totals[owner_id] = {
                "ownerId": owner_id,
                "displayName": mgr.display_name if mgr else "",
                "currentTeamName": mgr.current_team_name if mgr else "",
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
                "seasonsPlayed": 0,
                "championships": 0,
                "finalsAppearances": 0,
                "playoffAppearances": 0,
                "regularSeasonFirstPlace": 0,
                "toiletBowls": 0,
                "bestFinish": None,
                "worstFinish": None,
            }
        return manager_totals[owner_id]

    for season in snapshot.seasons:
        block = _season_block(snapshot, season)
        seasons_out.append(block)

        if block["champion"]:
            champions_by_season.append({
                "season": season.season,
                "leagueId": season.league_id,
                **block["champion"],
            })

        for row in block["standings"]:
            totals = _ensure(row["ownerId"])
            totals["wins"] += row["wins"]
            totals["losses"] += row["losses"]
            totals["ties"] += row["ties"]
            totals["pointsFor"] += row["pointsFor"]
            totals["pointsAgainst"] += row["pointsAgainst"]
            totals["seasonsPlayed"] += 1
            if row["madePlayoffs"]:
                totals["playoffAppearances"] += 1
            if row["finalPlace"] == 1:
                totals["championships"] += 1
            if row["finalPlace"] in (1, 2):
                totals["finalsAppearances"] += 1
            if row["standing"] == 1:
                totals["regularSeasonFirstPlace"] += 1

            # Toilet bowl: worst final place across the league.
            max_place = max(
                (r["finalPlace"] for r in block["standings"] if r["finalPlace"] is not None),
                default=None,
            )
            if max_place is not None and row["finalPlace"] == max_place:
                totals["toiletBowls"] += 1

            # Best / worst finish (by final placement when available,
            # otherwise by regular-season standing).
            effective = row["finalPlace"] or row["standing"]
            if totals["bestFinish"] is None or effective < totals["bestFinish"]:
                totals["bestFinish"] = effective
            if totals["worstFinish"] is None or effective > totals["worstFinish"]:
                totals["worstFinish"] = effective

    hall_of_fame = sorted(
        manager_totals.values(),
        key=lambda m: (
            -m["championships"],
            -m["finalsAppearances"],
            -m["playoffAppearances"],
            -(m["wins"] + m["ties"] * 0.5),
            -m["pointsFor"],
        ),
    )
    for row in hall_of_fame:
        row["pointsFor"] = round(row["pointsFor"], 2)
        row["pointsAgainst"] = round(row["pointsAgainst"], 2)

    return {
        "seasons": seasons_out,
        "championsBySeason": champions_by_season,
        "hallOfFame": hall_of_fame,
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
