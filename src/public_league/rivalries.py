"""Section: Rivalries.

For every owner-pair that met at least once across the 2-season window:
    * total meetings, regular-season meetings, playoff meetings
    * head-to-head record (wins/losses/ties, both sides)
    * points for / against per side
    * biggest blowout, closest game, last meeting (season, week, margin)
    * season-by-season splits

Rivalry index =
    5 * playoff_meetings
  + 3 * games_decided_by_5_or_less
  + 2 * games_decided_by_10_or_less
  + 2 * seasons_where_the_series_split
  + 1 * total_meetings
  + 2 * meetings_in_most_recent_season
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot


def _empty_record(owner_ids: tuple[str, str]) -> dict[str, Any]:
    return {
        "ownerIds": list(owner_ids),
        "totalMeetings": 0,
        "regularSeasonMeetings": 0,
        "playoffMeetings": 0,
        "winsA": 0,
        "winsB": 0,
        "ties": 0,
        "pointsA": 0.0,
        "pointsB": 0.0,
        "closestGame": None,
        "biggestBlowout": None,
        "lastMeeting": None,
        "seasonsWhereSeriesSplit": 0,
        "gamesDecidedByFive": 0,
        "gamesDecidedByTen": 0,
        "meetingsInMostRecentSeason": 0,
        "seasonSplits": {},
        "rivalryIndex": 0,
    }


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    if not snapshot.seasons:
        return {"rivalries": [], "seasonsCovered": [], "pairs": []}

    most_recent_season = snapshot.seasons[0].season
    head_to_head: dict[tuple[str, str], dict[str, Any]] = {}

    # Per-pair per-season wins/losses to compute "seasons split".
    per_season: dict[tuple[str, str], dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"winsA": 0, "winsB": 0, "ties": 0})
    )

    for season, week, a, b, is_playoff in metrics.walk_matchup_pairs(snapshot):
        owner_a = metrics.resolve_owner(snapshot.managers, season.league_id, a.get("roster_id"))
        owner_b = metrics.resolve_owner(snapshot.managers, season.league_id, b.get("roster_id"))
        if not owner_a or not owner_b or owner_a == owner_b:
            continue

        pts_a = metrics.matchup_points(a)
        pts_b = metrics.matchup_points(b)
        pk = _pair_key(owner_a, owner_b)

        rec = head_to_head.get(pk)
        if rec is None:
            rec = _empty_record(pk)
            head_to_head[pk] = rec

        # Orient the scores relative to the canonical pair ordering.
        if pk[0] == owner_a:
            pts_left, pts_right = pts_a, pts_b
        else:
            pts_left, pts_right = pts_b, pts_a

        rec["totalMeetings"] += 1
        if is_playoff:
            rec["playoffMeetings"] += 1
        else:
            rec["regularSeasonMeetings"] += 1

        rec["pointsA"] += pts_left
        rec["pointsB"] += pts_right

        margin_abs = abs(pts_left - pts_right)
        if pts_left > pts_right:
            rec["winsA"] += 1
            winner_side = "A"
        elif pts_right > pts_left:
            rec["winsB"] += 1
            winner_side = "B"
        else:
            rec["ties"] += 1
            winner_side = "T"

        # Season-split bookkeeping (by canonical pair ordering).
        ss = per_season[pk][season.season]
        if winner_side == "A":
            ss["winsA"] += 1
        elif winner_side == "B":
            ss["winsB"] += 1
        else:
            ss["ties"] += 1

        # Closeness bands.
        if margin_abs <= 5.0 + 1e-9:
            rec["gamesDecidedByFive"] += 1
        if margin_abs <= 10.0 + 1e-9:
            rec["gamesDecidedByTen"] += 1

        meeting = {
            "season": season.season,
            "leagueId": season.league_id,
            "week": week,
            "isPlayoff": is_playoff,
            "winnerSide": winner_side,
            "margin": round(margin_abs, 2),
            "pointsA": round(pts_left, 2),
            "pointsB": round(pts_right, 2),
        }
        if rec["closestGame"] is None or margin_abs < rec["closestGame"]["margin"]:
            rec["closestGame"] = meeting
        if rec["biggestBlowout"] is None or margin_abs > rec["biggestBlowout"]["margin"]:
            rec["biggestBlowout"] = meeting
        if rec["lastMeeting"] is None or (season.season, week) > (
            rec["lastMeeting"]["season"], rec["lastMeeting"]["week"],
        ):
            rec["lastMeeting"] = meeting

        if season.season == most_recent_season:
            rec["meetingsInMostRecentSeason"] += 1

    # Finalize per-pair aggregates.
    rivalries: list[dict[str, Any]] = []
    for pk, rec in head_to_head.items():
        # Season-split counting: a season splits if both sides won at
        # least one game in that season.
        splits = 0
        season_splits_out: dict[str, dict[str, int]] = {}
        for season_key, ss in per_season[pk].items():
            season_splits_out[season_key] = dict(ss)
            if ss["winsA"] > 0 and ss["winsB"] > 0:
                splits += 1
        rec["seasonsWhereSeriesSplit"] = splits
        rec["seasonSplits"] = season_splits_out

        rec["pointsA"] = round(rec["pointsA"], 2)
        rec["pointsB"] = round(rec["pointsB"], 2)

        rec["rivalryIndex"] = (
            5 * rec["playoffMeetings"]
            + 3 * rec["gamesDecidedByFive"]
            + 2 * rec["gamesDecidedByTen"]
            + 2 * rec["seasonsWhereSeriesSplit"]
            + 1 * rec["totalMeetings"]
            + 2 * rec["meetingsInMostRecentSeason"]
        )

        # Enrichment: display names for the pair.
        rec["displayNames"] = [
            metrics.display_name_for(snapshot, pk[0]),
            metrics.display_name_for(snapshot, pk[1]),
        ]
        rivalries.append(rec)

    rivalries.sort(
        key=lambda r: (
            -r["rivalryIndex"],
            -r["totalMeetings"],
            -r["playoffMeetings"],
        )
    )

    # ``pairs`` is a slim index consumers can use for filter dropdowns.
    pairs = [
        {
            "ownerIds": r["ownerIds"],
            "displayNames": r["displayNames"],
            "rivalryIndex": r["rivalryIndex"],
        }
        for r in rivalries
    ]

    return {
        "rivalries": rivalries,
        "pairs": pairs,
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "mostRecentSeason": most_recent_season,
    }
