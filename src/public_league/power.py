"""Section: Weekly Power Ranking.

A composite per-week power score for each owner, drawn from three
signals:

    * Points per game (PPG) — overall scoring strength, season-to-date.
    * Recent form           — average PPG over the last 3 regular-season games.
    * All-play win %        — strength of score distribution irrespective
                              of schedule luck (mirrors ``luck.py``).

Each signal is converted to a percentile rank within that week's set of
owners (0 = worst in league, 1 = best), then combined into a 0-100
power score:

    power = 100 * (0.50 * PPG%ile + 0.25 * recent%ile + 0.25 * allPlayWin%)

We emit a per-week ranking + a flat time-series per owner so the UI can
render both a table and a line chart without re-computing.

Output shape
────────────
``seasonsCovered``    — passthrough.
``weeks``             — list of ``{season, week, rankings: [...]}`` sorted
                        chronologically.  Each ranking row carries:
                          - ``rank``, ``ownerId``, ``displayName``,
                            ``teamName``, ``power``, ``components``,
                            ``weekRankDelta`` (change vs prior week),
                            ``record`` (season-to-date W-L).
``seriesByOwner``     — flat time-series per owner: list of ``{season,
                        week, power, rank}`` ordered by (season, week).
``currentRanking``    — rankings of the most recently completed week.
``methodology``       — human-readable formula.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import luck, metrics
from .snapshot import PublicLeagueSnapshot


# Composite weights.  These sum to 1.0.
_W_PPG = 0.50
_W_RECENT = 0.25
_W_ALLPLAY = 0.25

_RECENT_WINDOW = 3


def _percentile_rank(values: list[float], target: float) -> float:
    """Fraction of ``values`` strictly less than ``target`` + half the
    count equal to ``target`` (midrank tiebreak).  Returns 0-1.
    """
    n = len(values)
    if n <= 1:
        return 0.5
    below = sum(1 for v in values if v < target)
    equal = sum(1 for v in values if v == target)
    return (below + (equal - 1) * 0.5) / (n - 1)


def _season_sort_key(season: str) -> int:
    try:
        return int(season)
    except (TypeError, ValueError):
        return 0


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    registry = snapshot.managers
    weeks_out: list[dict[str, Any]] = []
    # owner → list of {season, week, power, rank, pointsForThisWeek}
    series: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Track per-owner running totals across the ORDERED walk.  We iterate
    # oldest → newest so PPG accumulates chronologically.
    seasons_sorted = sorted(
        snapshot.seasons, key=lambda s: _season_sort_key(s.season)
    )

    # Cross-season continuous accumulators (career PPG-to-date).
    career_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )

    for season in seasons_sorted:
        week_scores = luck._season_weekly_scores(season, registry)

        # Per-owner rolling buffer for recent-form average.
        recent_buffer: dict[str, list[float]] = defaultdict(list)

        # Track prior-week rank per owner for delta computation.
        prior_rank: dict[str, int] = {}

        for wk in sorted(week_scores.keys()):
            scores = week_scores[wk]
            all_play = luck._all_play_week(scores)
            actuals, _pair = luck._actual_week_results(season, wk, registry)

            # Update running state for every owner that played.
            for oid, pts in scores:
                s = career_state[oid]
                s["points"] += pts
                s["games"] += 1
                # Recent buffer (FIFO of _RECENT_WINDOW size).
                rb = recent_buffer[oid]
                rb.append(pts)
                if len(rb) > _RECENT_WINDOW:
                    rb.pop(0)
                actual_share = actuals.get(oid, 0.0)
                s["wins"] += actual_share
                # Losses is 1.0 - actual_share per game.
                s["losses"] += 1.0 - actual_share

            # Compute this week's ranking.  Gather per-owner components.
            owners_this_week = sorted({oid for oid, _ in scores})
            ppg_vals: dict[str, float] = {}
            recent_vals: dict[str, float] = {}
            allplay_vals: dict[str, float] = {}
            for oid in owners_this_week:
                s = career_state[oid]
                ppg_vals[oid] = s["points"] / s["games"] if s["games"] else 0.0
                rb = recent_buffer[oid]
                recent_vals[oid] = sum(rb) / len(rb) if rb else 0.0
                ap = all_play.get(oid) or {}
                # All-play share uses up to this week's all-play record
                # aggregated (easier read: just use this week's share
                # since the full-season all-play matches career PPG
                # already).  We'd need cum state to get career all-play;
                # simpler + still useful is current-week all-play share.
                allplay_vals[oid] = float(ap.get("expectedShare", 0.0))

            ppg_list = [ppg_vals[o] for o in owners_this_week]
            recent_list = [recent_vals[o] for o in owners_this_week]

            rankings: list[dict[str, Any]] = []
            for oid in owners_this_week:
                ppg_pct = _percentile_rank(ppg_list, ppg_vals[oid])
                recent_pct = _percentile_rank(recent_list, recent_vals[oid])
                ap_pct = allplay_vals[oid]
                power = 100.0 * (_W_PPG * ppg_pct + _W_RECENT * recent_pct + _W_ALLPLAY * ap_pct)

                s = career_state[oid]
                wins = round(s["wins"])
                games = s["games"]
                losses = games - wins
                record = f"{wins}-{losses}"

                rid = luck._roster_id_for_owner(registry, season.league_id, oid)
                rankings.append({
                    "ownerId": oid,
                    "displayName": metrics.display_name_for(snapshot, oid),
                    "teamName": metrics.team_name(snapshot, season.league_id, rid),
                    "power": round(power, 2),
                    "components": {
                        "pointsPerGame": round(ppg_vals[oid], 2),
                        "pointsPerGamePct": round(ppg_pct, 4),
                        "recentAvg": round(recent_vals[oid], 2),
                        "recentAvgPct": round(recent_pct, 4),
                        "allPlayWinPctThisWeek": round(ap_pct, 4),
                    },
                    "record": record,
                    "games": games,
                })

            rankings.sort(key=lambda r: -r["power"])
            for i, r in enumerate(rankings):
                r["rank"] = i + 1
                prior = prior_rank.get(r["ownerId"])
                r["weekRankDelta"] = (prior - r["rank"]) if prior else 0

            for r in rankings:
                prior_rank[r["ownerId"]] = r["rank"]

            weeks_out.append({
                "season": season.season,
                "leagueId": season.league_id,
                "week": wk,
                "rankings": rankings,
            })

            for r in rankings:
                series[r["ownerId"]].append({
                    "season": season.season,
                    "week": wk,
                    "power": r["power"],
                    "rank": r["rank"],
                    "record": r["record"],
                })

    series_out = []
    for oid, pts in series.items():
        series_out.append({
            "ownerId": oid,
            "displayName": metrics.display_name_for(snapshot, oid),
            "points": pts,
        })

    current_ranking = weeks_out[-1]["rankings"] if weeks_out else []

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "weeks": weeks_out,
        "seriesByOwner": series_out,
        "currentRanking": current_ranking,
        "methodology": (
            f"Power = 100 × ({int(_W_PPG * 100)}% × PPG percentile "
            f"+ {int(_W_RECENT * 100)}% × last-{_RECENT_WINDOW}-game avg percentile "
            f"+ {int(_W_ALLPLAY * 100)}% × all-play win share). "
            "Computed weekly; percentiles normalized within each week's active owners."
        ),
        "weights": {
            "pointsPerGame": _W_PPG,
            "recentForm": _W_RECENT,
            "allPlayWinPct": _W_ALLPLAY,
            "recentWindow": _RECENT_WINDOW,
        },
    }
