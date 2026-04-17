"""Section: Weekly Recap.

For every completed scoring week across the 2-season window:
    * Game of the Week  — closest margin
    * Blowout of the Week — largest margin
    * Highest Scorer
    * Lowest Scorer
    * Upset of the Week — worse pre-week record beats better pre-week
      record.  Tiebreak 1: largest record gap; Tiebreak 2: loser
      entered the week with higher PF; Tiebreak 3: larger score delta.
    * Rivalry Result — if the week contains a matchup from the top
      featured rivalry pair.
    * Standings Mover — owner with the largest absolute change in
      standings rank from start-of-week to end-of-week.

Pre-week standings: built using only games completed strictly before
the week in question.
"""
from __future__ import annotations

from typing import Any

from . import metrics
from .rivalries import build_section as build_rivalries
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _side_entry(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, entry: dict[str, Any]) -> dict[str, Any] | None:
    rid = metrics.roster_id_of(entry)
    if rid is None:
        return None
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    if not owner_id:
        return None
    return {
        "rosterId": rid,
        "ownerId": owner_id,
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "displayName": metrics.display_name_for(snapshot, owner_id),
        "points": round(metrics.matchup_points(entry), 2),
    }


def _standing_lookup(standings: list[dict[str, Any]]) -> dict[str, int]:
    return {r["ownerId"]: r["standing"] for r in standings}


def _record_lookup(standings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["ownerId"]: r for r in standings}


def _upset(snapshot, season, matchups, pre_lookup) -> dict[str, Any] | None:
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for m in matchups:
        winner = m["winner"]
        loser = m["loser"]
        if winner is None or loser is None:
            continue
        win_rec = pre_lookup.get(winner["ownerId"])
        lose_rec = pre_lookup.get(loser["ownerId"])
        if not win_rec or not lose_rec:
            continue
        # An upset requires the winner had a worse record going in.
        if win_rec["winPct"] < lose_rec["winPct"]:
            candidates.append((m, {
                "gap": lose_rec["winPct"] - win_rec["winPct"],
                "winnerPF": win_rec["pointsFor"],
                "margin": m["margin"],
            }))
    if not candidates:
        return None
    # Tiebreaks (per spec):
    #   1. largest record-gap first (biggest upset)
    #   2. lower WINNER pre-week PF (more of an underdog)
    #   3. larger margin of victory
    candidates.sort(
        key=lambda p: (
            -p[1]["gap"],
            p[1]["winnerPF"],
            -p[1]["margin"],
        )
    )
    return candidates[0][0]


def _featured_rivalry_pair(snapshot) -> set[str] | None:
    rivalries = build_rivalries(snapshot).get("rivalries") or []
    if not rivalries:
        return None
    return set(rivalries[0]["ownerIds"])


def _rivalry_result(matchups: list[dict[str, Any]], pair: set[str] | None) -> dict[str, Any] | None:
    if not pair:
        return None
    for m in matchups:
        owners = {m["home"]["ownerId"], m["away"]["ownerId"]}
        if owners == pair:
            return m
    return None


def _standings_mover(pre: dict[str, int], post: dict[str, int]) -> dict[str, Any] | None:
    best_owner: str | None = None
    best_delta = 0
    for owner_id, post_rank in post.items():
        pre_rank = pre.get(owner_id)
        if pre_rank is None:
            continue
        delta = pre_rank - post_rank  # positive = moved up
        if abs(delta) > abs(best_delta):
            best_delta = delta
            best_owner = owner_id
    if best_owner is None or best_delta == 0:
        return None
    return {
        "ownerId": best_owner,
        "preRank": pre[best_owner],
        "postRank": post[best_owner],
        "delta": best_delta,
    }


def _incremental_standings(
    season: SeasonSnapshot,
    snapshot: PublicLeagueSnapshot,
    up_to_week_inclusive: int,
) -> list[dict[str, Any]]:
    """Standings after games through ``up_to_week_inclusive`` (inclusive)
    have been completed.  Same semantics as metrics.pre_week_standings
    but with `week = up_to_week_inclusive + 1`.
    """
    return metrics.pre_week_standings(season, snapshot.managers, up_to_week_inclusive + 1)


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    featured_pair = _featured_rivalry_pair(snapshot)
    weeks_out: list[dict[str, Any]] = []

    for season in snapshot.seasons:
        # Pre-compute per-week standings incrementally so we don't
        # re-walk the full season for every week.
        sorted_weeks = season.regular_season_weeks
        standings_at = {0: []}
        for wk in sorted_weeks:
            standings_at[wk] = _incremental_standings(season, snapshot, wk)

        for wk in sorted(season.matchups_by_week.keys()):
            entries = season.matchups_by_week[wk]
            pairs = metrics.matchup_pairs(entries)
            if not pairs:
                continue

            is_playoff = wk >= season.playoff_week_start
            pre_week = wk - 1
            pre_standings = standings_at.get(pre_week, [])
            pre_ranks = _standing_lookup(pre_standings)
            pre_records = _record_lookup(pre_standings)

            matchup_rows: list[dict[str, Any]] = []
            highest: dict[str, Any] | None = None
            lowest: dict[str, Any] | None = None
            biggest: dict[str, Any] | None = None
            closest: dict[str, Any] | None = None

            for a, b in pairs:
                left = _side_entry(snapshot, season, a)
                right = _side_entry(snapshot, season, b)
                if not left or not right:
                    continue
                if left["points"] == 0 and right["points"] == 0:
                    continue
                winner = left if left["points"] > right["points"] else (
                    right if right["points"] > left["points"] else None
                )
                loser = None
                if winner is left:
                    loser = right
                elif winner is right:
                    loser = left
                margin = round(abs(left["points"] - right["points"]), 2)
                try:
                    mid = int(a.get("matchup_id"))
                except (TypeError, ValueError):
                    mid = None
                row = {
                    "home": left,
                    "away": right,
                    "margin": margin,
                    "winner": winner,
                    "loser": loser,
                    "winnerOwnerId": winner["ownerId"] if winner else None,
                    "matchupId": mid,
                }
                matchup_rows.append(row)

                for entry in (left, right):
                    if highest is None or entry["points"] > highest["points"]:
                        highest = entry
                    if lowest is None or entry["points"] < lowest["points"]:
                        lowest = entry
                if biggest is None or margin > biggest["margin"]:
                    biggest = row
                if closest is None or margin < closest["margin"]:
                    closest = row

            if not matchup_rows:
                continue

            # Post-week standings (games through wk inclusive).
            if is_playoff:
                post_standings = pre_standings  # playoffs don't move
                # regular-season standings.
            else:
                post_standings = standings_at.get(wk, pre_standings)
            post_ranks = _standing_lookup(post_standings)

            weeks_out.append({
                "season": season.season,
                "leagueId": season.league_id,
                "week": wk,
                "isPlayoff": is_playoff,
                "matchups": [
                    {k: v for k, v in r.items() if k in {"home", "away", "margin", "winnerOwnerId", "matchupId"}}
                    for r in matchup_rows
                ],
                "highlights": {
                    "gameOfTheWeek": _pack_highlight(closest),
                    "blowoutOfTheWeek": _pack_highlight(biggest),
                    "highestScorer": highest,
                    "lowestScorer": lowest,
                    "upsetOfTheWeek": _pack_highlight(
                        _upset(snapshot, season, matchup_rows, pre_records)
                    ),
                    "rivalryResult": _pack_highlight(
                        _rivalry_result(matchup_rows, featured_pair)
                    ),
                    "standingsMover": _standings_mover(pre_ranks, post_ranks),
                },
            })

    weeks_out.sort(key=lambda w: (w["season"], w["week"]), reverse=True)
    return {
        "weeks": weeks_out,
        "featuredRivalryPair": list(featured_pair or ()),
        "seasonsCovered": [s.season for s in snapshot.seasons],
    }


def _pack_highlight(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {k: v for k, v in row.items() if k in {"home", "away", "margin", "winnerOwnerId", "matchupId"}}
