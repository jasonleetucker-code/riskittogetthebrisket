"""Section: Records.

League record book — single-game highs, season highs, all-time bests
across the dynasty chain.  Attribution is by owner_id.

All records are computed from Sleeper public data.  No private
valuation input is ever read.
"""
from __future__ import annotations

from typing import Any

from .history import _team_name_for
from .snapshot import PublicLeagueSnapshot


def _walk_weekly_scores(snapshot: PublicLeagueSnapshot):
    """Yield (season, league_id, week, rid, owner_id, points) for every
    roster-week with a non-zero score."""
    for season in snapshot.seasons:
        for week, entries in season.matchups_by_week.items():
            for m in entries:
                try:
                    rid = int(m.get("roster_id"))
                except (TypeError, ValueError):
                    continue
                pts = float(m.get("points") or 0.0)
                if pts <= 0:
                    continue
                owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
                if not owner_id:
                    continue
                yield season.season, season.league_id, week, rid, owner_id, pts


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    all_weeks = list(_walk_weekly_scores(snapshot))

    highest: list[dict[str, Any]] = []
    lowest: list[dict[str, Any]] = []

    sorted_high = sorted(all_weeks, key=lambda t: -t[5])[:10]
    sorted_low = sorted(all_weeks, key=lambda t: t[5])[:10]

    for season, league_id, week, rid, owner_id, pts in sorted_high:
        highest.append({
            "season": season,
            "leagueId": league_id,
            "week": week,
            "ownerId": owner_id,
            "teamName": _team_name_for(snapshot, league_id, rid),
            "points": round(pts, 2),
        })
    for season, league_id, week, rid, owner_id, pts in sorted_low:
        lowest.append({
            "season": season,
            "leagueId": league_id,
            "week": week,
            "ownerId": owner_id,
            "teamName": _team_name_for(snapshot, league_id, rid),
            "points": round(pts, 2),
        })

    # Per-owner season totals
    by_owner_season: dict[tuple[str, str], dict[str, Any]] = {}
    for season, _league_id, _week, _rid, owner_id, pts in all_weeks:
        key = (owner_id, season)
        rec = by_owner_season.setdefault(key, {
            "ownerId": owner_id,
            "season": season,
            "weeksPlayed": 0,
            "totalPoints": 0.0,
        })
        rec["weeksPlayed"] += 1
        rec["totalPoints"] += pts

    season_totals = sorted(
        (
            {
                **rec,
                "totalPoints": round(rec["totalPoints"], 2),
                "avgPoints": round(rec["totalPoints"] / rec["weeksPlayed"], 2) if rec["weeksPlayed"] else 0.0,
            }
            for rec in by_owner_season.values()
        ),
        key=lambda r: -r["totalPoints"],
    )

    return {
        "singleWeekHighest": highest,
        "singleWeekLowest": lowest,
        "seasonScoringTotals": season_totals[:20],
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
