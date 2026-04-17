"""Section: Weekly Recap.

Per-week scoreboard + narrative highlights for every regular-season /
playoff week across the dynasty chain.  Attribution is by owner_id.

Keeps payload compact by listing only (matchup, score, owner_id,
team_name, margin) — no roster composition, no private signals.
"""
from __future__ import annotations

from typing import Any

from .history import _team_name_for
from .rivalries import _matchup_pairs
from .snapshot import PublicLeagueSnapshot


def _week_entry(snapshot, season, week, m):
    try:
        rid = int(m.get("roster_id"))
    except (TypeError, ValueError):
        return None
    pts = float(m.get("points") or 0.0)
    owner_id = snapshot.managers.owner_for_roster(season.league_id, rid)
    if not owner_id:
        return None
    return {
        "rosterId": rid,
        "ownerId": owner_id,
        "teamName": _team_name_for(snapshot, season.league_id, rid),
        "points": round(pts, 2),
    }


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    weeks: list[dict[str, Any]] = []

    for season in snapshot.seasons:
        for week in sorted(season.matchups_by_week.keys()):
            entries = season.matchups_by_week[week]
            pairs = _matchup_pairs(entries)
            if not pairs:
                continue
            matchups_out: list[dict[str, Any]] = []
            weekly_high: dict[str, Any] | None = None
            weekly_low: dict[str, Any] | None = None
            biggest_margin: dict[str, Any] | None = None
            closest_margin: dict[str, Any] | None = None

            for a, b in pairs:
                left = _week_entry(snapshot, season, week, a)
                right = _week_entry(snapshot, season, week, b)
                if not left or not right:
                    continue
                if left["points"] == 0 and right["points"] == 0:
                    continue
                winner = left if left["points"] > right["points"] else (
                    right if right["points"] > left["points"] else None
                )
                margin = round(abs(left["points"] - right["points"]), 2)
                matchup_row = {
                    "home": left,
                    "away": right,
                    "margin": margin,
                    "winnerOwnerId": winner["ownerId"] if winner else None,
                }
                matchups_out.append(matchup_row)

                for entry in (left, right):
                    if weekly_high is None or entry["points"] > weekly_high["points"]:
                        weekly_high = entry
                    if weekly_low is None or entry["points"] < weekly_low["points"]:
                        weekly_low = entry
                if biggest_margin is None or margin > biggest_margin["margin"]:
                    biggest_margin = matchup_row
                if closest_margin is None or margin < closest_margin["margin"]:
                    closest_margin = matchup_row

            if not matchups_out:
                continue
            weeks.append({
                "season": season.season,
                "leagueId": season.league_id,
                "week": week,
                "matchups": matchups_out,
                "highlights": {
                    "highestScore": weekly_high,
                    "lowestScore": weekly_low,
                    "biggestBlowout": biggest_margin,
                    "closestGame": closest_margin,
                },
            })

    weeks.sort(key=lambda w: (w["season"], w["week"]), reverse=True)
    return {"weeks": weeks}
