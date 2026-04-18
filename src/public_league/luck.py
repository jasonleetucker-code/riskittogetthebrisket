"""Luck Score section: expected wins vs actual wins.

For each completed regular-season week, compute each owner's "all-play"
record — how many of the other teams they would have beaten if
everyone played everyone that week.  Convert that to an expected win
share, sum across the season, and compare to actual wins.

    expected_wins(owner) = Σ_week (beats + ties * 0.5) / (rivals)
    actual_wins(owner)   = Σ_week actual_w + actual_t * 0.5
    luck_delta           = actual_wins − expected_wins

A positive delta means the owner has won more than their weekly score
profile alone would predict — lucky matchup draw or timely ceiling
games.  A negative delta means the owner has lost more than the
scores warrant — close losses, schedule grind, or peak weeks wasted
on an opponent who happened to peak higher.

We restrict luck accounting to **regular season** only.  Playoffs
conflate bracket position with scoring skill and muddy the metric.

Output shape
────────────
``byOwnerCareer``      — one row per owner aggregated across every
                         scored regular-season week in every season.
``byOwnerSeason``      — one row per (owner, season) pair.
``currentSeasonRanked``— ``byOwnerSeason`` filtered to the current
                         season, ranked luckiest → unluckiest, for a
                         quick Home-tab card.
``weeklyTrail``        — chronological per-owner timeline of weekly
                         and cumulative luck deltas.  Drives the
                         sparkline.
``seasonsCovered``     — list of season ids included.
``methodology``        — human-readable formula so the UI can render
                         the "how this is computed" footnote.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .identity import ManagerRegistry
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── All-play primitive ───────────────────────────────────────────────────
def _all_play_week(
    scores: list[tuple[str, float]],
) -> dict[str, dict[str, float | int]]:
    """Compute per-owner all-play stats for a single week's scored roster-weeks.

    Returns ``{owner_id: {"beats": int, "ties": int, "rivals": int,
    "expectedShare": float}}``.  ``expectedShare`` is ``(beats + ties*0.5) / rivals``.
    """
    n = len(scores)
    if n < 2:
        return {}
    rivals = n - 1
    out: dict[str, dict[str, float | int]] = {}
    for i, (oid_i, pts_i) in enumerate(scores):
        beats = 0
        ties = 0
        for j, (_oid_j, pts_j) in enumerate(scores):
            if i == j:
                continue
            if pts_i > pts_j:
                beats += 1
            elif pts_i == pts_j:
                ties += 1
        out[oid_i] = {
            "beats": beats,
            "ties": ties,
            "rivals": rivals,
            "expectedShare": (beats + ties * 0.5) / rivals,
        }
    return out


def _season_weekly_scores(
    season: SeasonSnapshot,
    registry: ManagerRegistry,
) -> dict[int, list[tuple[str, float]]]:
    """Return ``{week: [(owner_id, points), ...]}`` for every scored
    regular-season week.  Entries that can't be resolved to an owner are skipped.
    """
    out: dict[int, list[tuple[str, float]]] = {}
    for wk in season.regular_season_weeks:
        rows: list[tuple[str, float]] = []
        for entry in season.matchups_by_week.get(wk) or []:
            if not metrics.is_scored(entry):
                continue
            owner_id = metrics.resolve_owner(registry, season.league_id, entry.get("roster_id"))
            if not owner_id:
                continue
            rows.append((owner_id, metrics.matchup_points(entry)))
        if rows:
            out[wk] = rows
    return out


def _actual_week_results(
    season: SeasonSnapshot,
    week: int,
    registry: ManagerRegistry,
) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    """Return (actual_share, pair_points) for the given week.

    * ``actual_share[owner_id]`` — 1.0 / 0.5 / 0.0 for W / T / L.
    * ``pair_points[owner_id]`` — ``(pointsFor, pointsAgainst)`` for the
      owner's matchup (0/0 if Sleeper didn't pair them).
    """
    pairs = metrics.matchup_pairs(season.matchups_by_week.get(week) or [])
    actual: dict[str, float] = {}
    pair_pts: dict[str, tuple[float, float]] = {}
    for a, b in pairs:
        if not metrics.is_scored(a) and not metrics.is_scored(b):
            continue
        pa, pb = metrics.matchup_points(a), metrics.matchup_points(b)
        oa = metrics.resolve_owner(registry, season.league_id, a.get("roster_id"))
        ob = metrics.resolve_owner(registry, season.league_id, b.get("roster_id"))
        if oa:
            pair_pts[oa] = (pa, pb)
        if ob:
            pair_pts[ob] = (pb, pa)
        if pa > pb:
            if oa:
                actual[oa] = 1.0
            if ob:
                actual[ob] = 0.0
        elif pb > pa:
            if oa:
                actual[oa] = 0.0
            if ob:
                actual[ob] = 1.0
        else:
            if oa:
                actual[oa] = 0.5
            if ob:
                actual[ob] = 0.5
    return actual, pair_pts


def _roster_id_for_owner(
    registry: ManagerRegistry, league_id: str, owner_id: str
) -> int | None:
    for (lid, rid), oid in registry.roster_to_owner.items():
        if lid == league_id and oid == owner_id:
            return rid
    return None


def _season_sort_key(season: str) -> int:
    try:
        return int(season)
    except (TypeError, ValueError):
        return 0


# ── Build section ────────────────────────────────────────────────────────
def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Assemble the luck-score section payload."""
    registry = snapshot.managers

    def _blank_career() -> dict[str, Any]:
        return {
            "ownerId": "",
            "displayName": "",
            "teamName": "",
            "gamesPlayed": 0,
            "actualWins": 0.0,
            "expectedWins": 0.0,
            "pointsFor": 0.0,
            "pointsAgainst": 0.0,
            "allPlayBeats": 0,
            "allPlayTies": 0,
            "allPlayRivals": 0,
        }

    by_owner_career: dict[str, dict[str, Any]] = defaultdict(_blank_career)
    by_owner_season: dict[tuple[str, str], dict[str, Any]] = {}
    weekly_trail: list[dict[str, Any]] = []

    # Owner → running cumulative totals for the trail (across seasons).
    trail_state: dict[str, dict[str, float]] = defaultdict(
        lambda: {"expected": 0.0, "actual": 0.0, "games": 0}
    )

    current_season_year = (
        snapshot.current_season.season if snapshot.current_season else None
    )

    # Iterate oldest → newest so ``trail_state`` cumulative counters
    # match the final chronological sort of ``weekly_trail``.  If we
    # walked most-recent-first (the snapshot's natural order), cumGames
    # would decrease in the sorted output.
    for season in sorted(snapshot.seasons, key=lambda s: _season_sort_key(s.season)):
        week_scores = _season_weekly_scores(season, registry)
        for wk in sorted(week_scores.keys()):
            scores = week_scores[wk]
            all_play = _all_play_week(scores)
            actual, pair_pts = _actual_week_results(season, wk, registry)

            for oid, ap in all_play.items():
                pts_for, pts_against = pair_pts.get(oid, (0.0, 0.0))
                expected_share = float(ap["expectedShare"])
                actual_share = actual.get(oid, 0.0)

                # Career aggregate.
                career = by_owner_career[oid]
                if not career["ownerId"]:
                    career["ownerId"] = oid
                    career["displayName"] = metrics.display_name_for(snapshot, oid)
                    current = snapshot.current_season
                    if current:
                        rid_current = _roster_id_for_owner(registry, current.league_id, oid)
                        career["teamName"] = metrics.team_name(snapshot, current.league_id, rid_current)
                career["gamesPlayed"] += 1
                career["expectedWins"] += expected_share
                career["actualWins"] += actual_share
                career["pointsFor"] += pts_for
                career["pointsAgainst"] += pts_against
                career["allPlayBeats"] += int(ap["beats"])
                career["allPlayTies"] += int(ap["ties"])
                career["allPlayRivals"] += int(ap["rivals"])

                # Season aggregate.
                key = (oid, season.season)
                if key not in by_owner_season:
                    rid = _roster_id_for_owner(registry, season.league_id, oid)
                    by_owner_season[key] = {
                        "ownerId": oid,
                        "season": season.season,
                        "leagueId": season.league_id,
                        "displayName": metrics.display_name_for(snapshot, oid),
                        "teamName": metrics.team_name(snapshot, season.league_id, rid),
                        "gamesPlayed": 0,
                        "actualWins": 0.0,
                        "expectedWins": 0.0,
                        "pointsFor": 0.0,
                        "pointsAgainst": 0.0,
                        "allPlayBeats": 0,
                        "allPlayTies": 0,
                        "allPlayRivals": 0,
                    }
                s = by_owner_season[key]
                s["gamesPlayed"] += 1
                s["actualWins"] += actual_share
                s["expectedWins"] += expected_share
                s["pointsFor"] += pts_for
                s["pointsAgainst"] += pts_against
                s["allPlayBeats"] += int(ap["beats"])
                s["allPlayTies"] += int(ap["ties"])
                s["allPlayRivals"] += int(ap["rivals"])

                # Trail (owner-scoped cumulative).
                t = trail_state[oid]
                t["expected"] += expected_share
                t["actual"] += actual_share
                t["games"] += 1
                weekly_trail.append({
                    "ownerId": oid,
                    "season": season.season,
                    "week": wk,
                    "weekExpected": round(expected_share, 4),
                    "weekActual": round(actual_share, 4),
                    "weekLuckDelta": round(actual_share - expected_share, 4),
                    "weekPoints": round(pts_for, 2),
                    "cumExpected": round(t["expected"], 4),
                    "cumActual": round(t["actual"], 4),
                    "cumLuckDelta": round(t["actual"] - t["expected"], 4),
                    "cumGames": int(t["games"]),
                })

    # Finalize career rows.
    career_rows: list[dict[str, Any]] = []
    for oid, row in by_owner_career.items():
        games = row["gamesPlayed"]
        actual = row["actualWins"]
        expected = row["expectedWins"]
        rivals = row["allPlayRivals"]
        career_rows.append({
            "ownerId": oid,
            "displayName": row["displayName"],
            "teamName": row["teamName"],
            "gamesPlayed": games,
            "actualWins": round(actual, 2),
            "expectedWins": round(expected, 2),
            "luckDelta": round(actual - expected, 2),
            "luckPerGame": round((actual - expected) / games, 4) if games else 0.0,
            "actualWinPct": round(actual / games, 4) if games else 0.0,
            "expectedWinPct": round(expected / games, 4) if games else 0.0,
            "allPlayWinPct": round(
                (row["allPlayBeats"] + row["allPlayTies"] * 0.5) / rivals, 4
            ) if rivals else 0.0,
            "allPlayBeats": row["allPlayBeats"],
            "allPlayTies": row["allPlayTies"],
            "allPlayLosses": rivals - row["allPlayBeats"] - row["allPlayTies"],
            "pointsFor": round(row["pointsFor"], 2),
            "pointsAgainst": round(row["pointsAgainst"], 2),
        })
    career_rows.sort(key=lambda r: -r["luckDelta"])

    # Finalize season rows.
    season_rows: list[dict[str, Any]] = []
    for row in by_owner_season.values():
        games = row["gamesPlayed"]
        actual = row["actualWins"]
        expected = row["expectedWins"]
        rivals = row["allPlayRivals"]
        season_rows.append({
            "ownerId": row["ownerId"],
            "season": row["season"],
            "leagueId": row["leagueId"],
            "displayName": row["displayName"],
            "teamName": row["teamName"],
            "gamesPlayed": games,
            "actualWins": round(actual, 2),
            "expectedWins": round(expected, 2),
            "luckDelta": round(actual - expected, 2),
            "luckPerGame": round((actual - expected) / games, 4) if games else 0.0,
            "actualWinPct": round(actual / games, 4) if games else 0.0,
            "expectedWinPct": round(expected / games, 4) if games else 0.0,
            "allPlayWinPct": round(
                (row["allPlayBeats"] + row["allPlayTies"] * 0.5) / rivals, 4
            ) if rivals else 0.0,
            "pointsFor": round(row["pointsFor"], 2),
            "pointsAgainst": round(row["pointsAgainst"], 2),
        })
    # Most recent season first; within a season, luckiest first.
    season_rows.sort(key=lambda r: (-_season_sort_key(r["season"]), -r["luckDelta"]))

    weekly_trail.sort(
        key=lambda t: (_season_sort_key(t["season"]), t["week"], t["ownerId"])
    )

    current_season_rows = [r for r in season_rows if r["season"] == current_season_year]
    current_season_rows.sort(key=lambda r: -r["luckDelta"])

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "currentSeason": current_season_year,
        "byOwnerCareer": career_rows,
        "byOwnerSeason": season_rows,
        "currentSeasonRanked": current_season_rows,
        "weeklyTrail": weekly_trail,
        "luckiestCareer": career_rows[0] if career_rows else None,
        "unluckiestCareer": career_rows[-1] if career_rows else None,
        "luckiestCurrent": current_season_rows[0] if current_season_rows else None,
        "unluckiestCurrent": current_season_rows[-1] if current_season_rows else None,
        "methodology": (
            "Expected wins = sum of weekly all-play win share "
            "((beats + ties*0.5) / (teams-1)). Luck delta = actual wins "
            "minus expected wins. Regular season only."
        ),
    }
