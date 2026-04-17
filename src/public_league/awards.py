"""Section: Awards.

Per-season narrative awards derived from Sleeper standings + matchup
data.  Every award attributes to an owner_id, never a team name, so
renames don't split awards across the same manager.

Awards computed today:
    * Champion
    * Runner-Up
    * Regular-Season Crown (best reg-season record)
    * Points King (most points scored)
    * Points Black Hole (most points allowed)
    * Toilet Bowl (worst final place)
    * Highest Single-Week Score
    * Lowest Single-Week Score

Additional narrative awards (Biggest Riser, Best Trade, etc.) can be
added without changing the public contract shape.
"""
from __future__ import annotations

from typing import Any

from .history import _final_standing_from_bracket, _regular_season_records, _team_name_for
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _award(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, rid: int | None, key: str, label: str, value: Any = None) -> dict[str, Any] | None:
    if rid is None:
        return None
    owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
    if not owner_id:
        return None
    return {
        "key": key,
        "label": label,
        "ownerId": owner_id,
        "teamName": _team_name_for(snapshot, season.league_id, rid),
        "value": value,
    }


def _awards_for_season(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    awards: list[dict[str, Any]] = []
    regular = _regular_season_records(season)
    placement = _final_standing_from_bracket(season.winners_bracket)

    if not regular:
        return awards

    champion_rid = next((rid for rid, p in placement.items() if p == 1), None)
    runner_up_rid = next((rid for rid, p in placement.items() if p == 2), None)
    worst_place = max(placement.values(), default=None)
    toilet_rid = next((rid for rid, p in placement.items() if p == worst_place), None) if worst_place else None

    best_record_rid = max(
        regular,
        key=lambda rid: (regular[rid]["wins"] + regular[rid]["ties"] * 0.5, regular[rid]["pointsFor"]),
        default=None,
    )
    pf_leader_rid = max(regular, key=lambda rid: regular[rid]["pointsFor"], default=None)
    pa_leader_rid = max(regular, key=lambda rid: regular[rid]["pointsAgainst"], default=None)

    # Single-week highs/lows
    high_week: tuple[float, int, int] | None = None  # (points, rid, week)
    low_week: tuple[float, int, int] | None = None
    for week, entries in season.matchups_by_week.items():
        for m in entries:
            pts = float(m.get("points") or 0.0)
            try:
                rid = int(m.get("roster_id"))
            except (TypeError, ValueError):
                continue
            if pts <= 0:
                continue
            if high_week is None or pts > high_week[0]:
                high_week = (pts, rid, week)
            if low_week is None or pts < low_week[0]:
                low_week = (pts, rid, week)

    candidates = [
        _award(snapshot, season, champion_rid, "champion", "Champion"),
        _award(snapshot, season, runner_up_rid, "runner_up", "Runner-Up"),
        _award(snapshot, season, best_record_rid, "regular_season_crown", "Regular-Season Crown",
               value={"record": f'{regular[best_record_rid]["wins"]}-{regular[best_record_rid]["losses"]}'} if best_record_rid is not None else None),
        _award(snapshot, season, pf_leader_rid, "points_king", "Points King",
               value={"pointsFor": regular[pf_leader_rid]["pointsFor"]} if pf_leader_rid is not None else None),
        _award(snapshot, season, pa_leader_rid, "points_black_hole", "Points Black Hole",
               value={"pointsAgainst": regular[pa_leader_rid]["pointsAgainst"]} if pa_leader_rid is not None else None),
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
