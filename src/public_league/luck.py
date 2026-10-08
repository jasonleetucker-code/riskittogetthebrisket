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

import logging
from collections import defaultdict
from typing import Any

from . import metrics, schedule_impact
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
    """Return ``{week: [(owner_id, points), ...]}`` for every COMPLETED
    regular-season week.  Entries that can't be resolved to an owner are skipped.

    Two distinctions are load-bearing here, and getting either wrong is a
    measured defect rather than a hypothetical one.

    **An in-progress week contributes to nobody.**  The week gate is
    ``metrics.final_regular_season_weeks``, not ``season.regular_season_weeks``.
    This function feeds per-game aggregation in ``ros.power_v2`` and
    ``playoff_odds`` (it fed the Luck section too, until Luck moved onto the
    canonical schedule-impact owner -- see ``_season_team_weeks``), so
    admitting a live week made a Thursday-night sliver count as a completed
    game.  Measured on 2026-09-19: live week 2
    held 8 partial scores and 4 rosters at ``0.0``, so eight teams' PPG was
    divided by 2 and four by 1, inside one table (PRIOR-A03-F03).

    **Inside a counted week, ``0.0`` is an observation and an absent row is
    missing.**  The per-entry test is therefore ``points is None``, not
    ``is_scored`` (``points > 0``).  A roster that genuinely scored nothing in
    a finished week played that game; dropping it would shrink that one team's
    denominator again, in the direction that hides the defect.  MISSING IS
    NEVER ZERO must not become "zero is never real".

    ``_actual_week_results`` inherits the gate for free: its caller iterates
    only the weeks this function returned.

    Orphan rosters (no owner that season) are skipped HERE, while
    ``_actual_week_results`` credits the owner who played one -- the
    inconsistency #1530 finding A measured.  The Luck section no longer reads
    this pair; ``ros.power_v2`` still does, and changing its inputs is a Power
    methodology question, not a Luck one.
    """
    out: dict[int, list[tuple[str, float]]] = {}
    for wk in metrics.final_regular_season_weeks(season):
        rows: list[tuple[str, float]] = []
        for entry in season.matchups_by_week.get(wk) or []:
            if entry.get("points") is None:
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


def _season_team_weeks(
    season: SeasonSnapshot,
    registry: ManagerRegistry,
) -> tuple[list[tuple[int, str, dict[str, float | int], float, float, float]], dict[str, Any]]:
    """Every owner's evaluable regular-season game as
    ``(week, owner_id, all_play, actual_share, points_for, points_against)``,
    plus the season's luck STATE.

    The state is the canonical contract's own (``complete`` / ``partial`` /
    ``unavailable`` / ``unsupported``) with its reason and issue count.  A
    season that contributes no rows must say why: an ``unsupported`` format
    and a season with no finished weeks yet are different statements, and
    neither may read as a season silently absent from the tables.

    Consumed from the canonical schedule-impact owner
    (``schedule_impact.season_week_inputs`` + ``compute_schedule_impact``)
    rather than re-derived, so the EXPECTED and the ACTUAL halves of the luck
    delta are measured over one game set by construction (#1530 finding A).

    The defect this replaced: ``_season_weekly_scores`` dropped an ownerless
    (orphan) roster from every all-play rival set, while
    ``_actual_week_results`` still credited the owner who played it.  In
    ``dynasty_new`` 2024 (rosters 3 and 5 had no owner) expected and actual
    wins were therefore summed over different games.  The canonical owner keeps
    an orphan roster as a real participant (``roster:<id>``): a rival in every
    all-play comparison and a real opponent.  It is never published as a luck
    row of its own -- it has no manager to be lucky -- which is why ``roster:``
    keys are skipped here and only here.

    Two consequences of consuming the owner, both its documented rules:

    * a team that scored but played no head-to-head game (a bye) is not an
      eligible all-play rival that week (``equal_opponent_v1``), and has no
      luck row for it -- no game, so no actual result to compare against;
    * a game whose score is missing is excluded for BOTH teams, never scored
      as a 0-point loss (MISSING IS NEVER ZERO); a format the owner calls
      ``unsupported`` (a team in two games in one week) yields no luck rows
      rather than a plausible number from a simplified format.

    Week gate: the owner's own, ``metrics.final_regular_season_weeks``.
    """
    core = schedule_impact.compute_schedule_impact(
        schedule_impact.season_week_inputs(season, registry)
    )
    out: list[tuple[int, str, dict[str, float | int], float, float, float]] = []
    for row in core.get("weeks") or []:
        key = row["teamKey"]
        if key.startswith("roster:"):
            continue
        beats, ties = int(row["allPlayWins"]), int(row["allPlayTies"])
        rivals = beats + ties + int(row["allPlayLosses"])
        all_play = {
            "beats": beats,
            "ties": ties,
            "rivals": rivals,
            "expectedShare": float(row["allPlayRate"]),
        }
        out.append(
            (
                int(row["week"]),
                key,
                all_play,
                float(row["h2hCredit"]),
                float(row["score"]),
                float(row["opponentScore"]),
            )
        )
    out.sort(key=lambda r: (r[0], r[1]))
    issues = core.get("issues") or []
    state = {
        "season": season.season,
        "state": core.get("state"),
        "reason": core.get("reason"),
        "issueCount": len(issues),
        "teamWeeks": len(out),
    }
    return out, state


def _roster_id_for_owner(registry: ManagerRegistry, league_id: str, owner_id: str) -> int | None:
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

    current_season_year = snapshot.current_season.season if snapshot.current_season else None

    # Iterate oldest → newest so ``trail_state`` cumulative counters
    # match the final chronological sort of ``weekly_trail``.  If we
    # walked most-recent-first (the snapshot's natural order), cumGames
    # would decrease in the sorted output.
    season_states: list[dict[str, Any]] = []
    for season in sorted(snapshot.seasons, key=lambda s: _season_sort_key(s.season)):
        team_weeks, season_state = _season_team_weeks(season, registry)
        season_states.append(season_state)
        for wk, oid, ap, actual_share, pts_for, pts_against in team_weeks:
            expected_share = float(ap["expectedShare"])

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
            weekly_trail.append(
                {
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
                }
            )

    # Finalize career rows.
    career_rows: list[dict[str, Any]] = []
    for oid, row in by_owner_career.items():
        games = row["gamesPlayed"]
        actual = row["actualWins"]
        expected = row["expectedWins"]
        rivals = row["allPlayRivals"]
        career_rows.append(
            {
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
                "allPlayWinPct": round((row["allPlayBeats"] + row["allPlayTies"] * 0.5) / rivals, 4)
                if rivals
                else 0.0,
                "allPlayBeats": row["allPlayBeats"],
                "allPlayTies": row["allPlayTies"],
                "allPlayLosses": rivals - row["allPlayBeats"] - row["allPlayTies"],
                "pointsFor": round(row["pointsFor"], 2),
                "pointsAgainst": round(row["pointsAgainst"], 2),
            }
        )
    # ``ownerId`` is the tie-break on every luck sort below.  Deltas are
    # rounded to 2dp and cluster hard around 0, so ties are common; with
    # no tie-break the order fell out of the order Sleeper happened to
    # return that week's matchup rows in, and "luckiest manager" could
    # change between two identical requests.
    career_rows.sort(key=lambda r: (-r["luckDelta"], r["ownerId"]))

    # Finalize season rows.
    season_rows: list[dict[str, Any]] = []
    for row in by_owner_season.values():
        games = row["gamesPlayed"]
        actual = row["actualWins"]
        expected = row["expectedWins"]
        rivals = row["allPlayRivals"]
        season_rows.append(
            {
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
                "allPlayWinPct": round((row["allPlayBeats"] + row["allPlayTies"] * 0.5) / rivals, 4)
                if rivals
                else 0.0,
                "pointsFor": round(row["pointsFor"], 2),
                "pointsAgainst": round(row["pointsAgainst"], 2),
            }
        )
    # Most recent season first; within a season, luckiest first.
    season_rows.sort(key=lambda r: (-_season_sort_key(r["season"]), -r["luckDelta"], r["ownerId"]))

    weekly_trail.sort(key=lambda t: (_season_sort_key(t["season"]), t["week"], t["ownerId"]))

    current_season_rows = [r for r in season_rows if r["season"] == current_season_year]
    current_season_rows.sort(key=lambda r: (-r["luckDelta"], r["ownerId"]))

    # Schedule Intelligence (Milestone A): the canonical schedule-impact
    # contract rides on this public section rather than a new one.  A
    # failure there must not take the Luck section down with it.
    try:
        schedule_block = schedule_impact.build_block(snapshot)
    except Exception:  # noqa: BLE001 -- surfaced as an explicit state
        logging.getLogger(__name__).exception(
            "schedule impact failed; Luck section served without it"
        )
        schedule_block = {"currentSeason": None, "bySeason": {}, "state": "failed"}

    return {
        "scheduleImpact": schedule_block,
        "seasonsCovered": [s.season for s in snapshot.seasons],
        # Per-season luck state, newest first: a season with no luck rows
        # (``unsupported`` format, ``unavailable`` = no finished weeks) is
        # named here with its reason instead of silently missing.
        "seasonStates": sorted(season_states, key=lambda r: -_season_sort_key(r["season"])),
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
            "((beats + ties*0.5) / rivals, where rivals are every other team "
            "that played a head-to-head game that week, ownerless rosters "
            "included). Luck delta = actual wins minus expected wins, over the "
            "same games. Regular season only."
        ),
    }
