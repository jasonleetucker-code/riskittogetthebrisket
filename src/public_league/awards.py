"""Section: Awards.

Per-season narrative awards derived from Sleeper standings + matchup
data.  Every award attributes to an owner_id so renames / orphan
handoffs never split the recipient across seasons.

Awards computed:
    * Champion
    * Runner-Up
    * Top Seed
    * Regular-Season Crown (best regular-season record)
    * Points King (most points scored, regular season)
    * Points Black Hole (most points allowed)
    * Toilet Bowl (worst final placement)
    * Highest Single-Week Score
    * Lowest Single-Week Score
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _award(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, rid: int | None, key: str, label: str, value: Any = None) -> dict[str, Any] | None:
    if rid is None:
        return None
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    if not owner_id:
        return None
    return {
        "key": key,
        "label": label,
        "ownerId": owner_id,
        "displayName": metrics.display_name_for(snapshot, owner_id),
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "value": value,
    }


def _awards_for_season(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    standings = metrics.season_standings(season, snapshot.managers)
    placement = metrics.playoff_placement(season.winners_bracket)
    if not standings:
        return []

    champion_rid = metrics.season_champion(season)
    runner_up_rid = metrics.season_runner_up(season)
    top_seed = metrics.top_seed(standings)
    best_record_rid = standings[0]["rosterId"] if standings else None
    pf_leader = max(standings, key=lambda r: r["pointsFor"], default=None)
    pa_leader = max(standings, key=lambda r: r["pointsAgainst"], default=None)

    worst_place = max((p for p in placement.values()), default=None)
    toilet_rid: int | None = None
    if worst_place is not None:
        toilet_rid = next((rid for rid, p in placement.items() if p == worst_place), None)

    # Single-week highs/lows across regular + playoffs.
    high_week: tuple[float, int, int] | None = None
    low_week: tuple[float, int, int] | None = None
    for week, entries in season.matchups_by_week.items():
        for m in entries:
            rid = metrics.roster_id_of(m)
            if rid is None:
                continue
            pts = metrics.matchup_points(m)
            if pts <= 0:
                continue
            if high_week is None or pts > high_week[0]:
                high_week = (pts, rid, week)
            if low_week is None or pts < low_week[0]:
                low_week = (pts, rid, week)

    candidates = [
        _award(snapshot, season, champion_rid, "champion", "Champion"),
        _award(snapshot, season, runner_up_rid, "runner_up", "Runner-Up"),
        _award(snapshot, season, top_seed["rosterId"] if top_seed else None, "top_seed", "Top Seed",
               value={"winPct": top_seed["winPct"]} if top_seed else None),
        _award(snapshot, season, best_record_rid, "regular_season_crown", "Regular-Season Crown",
               value={"record": f'{standings[0]["wins"]}-{standings[0]["losses"]}'} if standings else None),
        _award(snapshot, season, pf_leader["rosterId"] if pf_leader else None, "points_king", "Points King",
               value={"pointsFor": pf_leader["pointsFor"]} if pf_leader else None),
        _award(snapshot, season, pa_leader["rosterId"] if pa_leader else None, "points_black_hole", "Points Black Hole",
               value={"pointsAgainst": pa_leader["pointsAgainst"]} if pa_leader else None),
        _award(snapshot, season, toilet_rid, "toilet_bowl", "Toilet Bowl"),
        _award(snapshot, season, high_week[1] if high_week else None, "highest_single_week", "Highest Single-Week Score",
               value={"points": round(high_week[0], 2), "week": high_week[2]} if high_week else None),
        _award(snapshot, season, low_week[1] if low_week else None, "lowest_single_week", "Lowest Single-Week Score",
               value={"points": round(low_week[0], 2), "week": low_week[2]} if low_week else None),
    ]
    return [a for a in candidates if a is not None]


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    by_season: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        by_season.append({
            "season": season.season,
            "leagueId": season.league_id,
            "seasonStatus": str(season.league.get("status") or ""),
            "awards": _awards_for_season(snapshot, season),
        })
    return {"bySeason": by_season}
