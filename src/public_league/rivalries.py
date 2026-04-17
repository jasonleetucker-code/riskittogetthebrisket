"""Section: Rivalries.

Builds head-to-head records between every pair of managers across the
dynasty chain.  Attribution is by owner_id at the time of each
matchup so orphaned-roster handoffs split correctly.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _matchup_pairs(week_matchups: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group a week's matchup entries into (team_a, team_b) pairs by matchup_id."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    for m in week_matchups:
        mid = m.get("matchup_id")
        if mid is None:
            continue
        groups.setdefault(mid, []).append(m)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for mid, entries in groups.items():
        if len(entries) == 2:
            pairs.append((entries[0], entries[1]))
    return pairs


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    head_to_head: dict[tuple[str, str], dict[str, Any]] = {}

    for season in snapshot.seasons:
        for week, entries in season.matchups_by_week.items():
            for a, b in _matchup_pairs(entries):
                owner_a = snapshot.managers.owner_for_roster(season.league_id, a.get("roster_id"))
                owner_b = snapshot.managers.owner_for_roster(season.league_id, b.get("roster_id"))
                if not owner_a or not owner_b or owner_a == owner_b:
                    continue
                pts_a = float(a.get("points") or 0.0)
                pts_b = float(b.get("points") or 0.0)
                if pts_a == 0 and pts_b == 0:
                    # Future-week placeholders from Sleeper — skip.
                    continue

                pk = _pair_key(owner_a, owner_b)
                rec = head_to_head.setdefault(pk, {
                    "ownerIds": list(pk),
                    "games": 0,
                    "winsA": 0,
                    "winsB": 0,
                    "ties": 0,
                    "pointsA": 0.0,
                    "pointsB": 0.0,
                    "biggestBlowout": None,
                    "lastMeeting": None,
                })
                rec["games"] += 1
                if pk[0] == owner_a:
                    rec["pointsA"] += pts_a
                    rec["pointsB"] += pts_b
                    winner_side = "A" if pts_a > pts_b else ("B" if pts_b > pts_a else "T")
                    margin = pts_a - pts_b
                else:
                    rec["pointsA"] += pts_b
                    rec["pointsB"] += pts_a
                    winner_side = "A" if pts_b > pts_a else ("B" if pts_a > pts_b else "T")
                    margin = pts_b - pts_a

                if winner_side == "A":
                    rec["winsA"] += 1
                elif winner_side == "B":
                    rec["winsB"] += 1
                else:
                    rec["ties"] += 1

                meeting = {
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": week,
                    "margin": round(margin, 2),
                    "winnerSide": winner_side,
                }
                if rec["biggestBlowout"] is None or abs(margin) > abs(rec["biggestBlowout"]["margin"]):
                    rec["biggestBlowout"] = meeting
                rec["lastMeeting"] = meeting

    rivalries: list[dict[str, Any]] = []
    for pk, rec in head_to_head.items():
        diff = rec["winsA"] - rec["winsB"]
        rec["competitivenessScore"] = round(
            1.0 / (1.0 + abs(diff) / max(1, rec["games"])), 3
        )
        rec["pointsA"] = round(rec["pointsA"], 2)
        rec["pointsB"] = round(rec["pointsB"], 2)
        rivalries.append(rec)

    rivalries.sort(
        key=lambda r: (-r["competitivenessScore"], -r["games"]),
    )

    return {
        "rivalries": rivalries,
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }
