"""ROS-driven power rankings (v2).

Spec formula:

    power_score =
        0.38 * team_ros_strength_percentile
        + 0.18 * season_points_scored_percentile
        + 0.12 * recent_points_scored_percentile
        + 0.10 * win_loss_record_percentile
        + 0.08 * all_play_record_percentile
        + 0.05 * winning_streak_score
        + 0.04 * schedule_adjusted_performance
        + 0.03 * roster_health_score
        + 0.02 * luck_regression_score

Inputs come from two places:

    * ``data/ros/team_strength/latest.json`` — written by
      ``src.ros.team_strength``.  Provides ``team_ros_strength_percentile``.
    * ``PublicLeagueSnapshot`` — already feeds the existing
      ``power.py``.  Provides PPG, recent form, W/L, all-play, streak,
      and luck-regression inputs.

PR2 leaves ``schedule_adjusted_performance`` and ``roster_health_score``
at 0 (well-documented config-gated TODOs) — the spec calls these out as
"implement what is reasonable and leave clean TODOs/config flags for the
rest" because they need data this app doesn't currently surface
(opponent-strength SOS + injury-aware roster scoring).  The current
formula renormalises the populated weights so missing terms don't
deflate the result against teams with full coverage.

Render-side, this section is gated by ``settings.useRosPowerRankings``:
when False, the existing ``power.py`` v1 still drives /league → Power.
When True, /league → ROS Power renders this version side-by-side as
the new "ROS Power" tab.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict
from typing import Any

from src.ros import ROS_DATA_DIR
from src.public_league import luck
from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.power_v2")


# ── Formula weights (spec) ────────────────────────────────────────────
WEIGHTS: dict[str, float] = {
    "team_ros_strength": 0.38,
    "ppg": 0.18,
    "recent": 0.12,
    "wl_record": 0.10,
    "all_play": 0.08,
    "streak": 0.05,
    "schedule_adjusted": 0.04,
    "roster_health": 0.03,
    "luck_regression": 0.02,
}

_RECENT_WINDOW = 3  # matches power.py


def _percentile(values: list[float], target: float) -> float:
    """Inclusive percentile rank in [0, 1]."""
    if not values:
        return 0.0
    eligible = [v for v in values if v is not None]
    if not eligible:
        return 0.0
    below = sum(1 for v in eligible if v < target)
    same = sum(1 for v in eligible if v == target)
    return (below + 0.5 * same) / len(eligible)


def _load_team_strength_rows() -> list[dict[str, Any]]:
    """Read raw rows from `data/ros/team_strength/latest.json`.
    Returns [] when the snapshot is missing or unparsable.
    """
    path = ROS_DATA_DIR / "team_strength" / "latest.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return rows or []


def _load_team_strength_percentiles() -> dict[str, float]:
    """Convert team-strength composite to a percentile per ownerId.
    Empty dict when no snapshot — caller renormalises weights.
    """
    rows = _load_team_strength_rows()
    scores: list[tuple[str, float]] = []
    for r in rows:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue
        score = float(r.get("teamRosStrength") or 0.0)
        scores.append((oid, score))
    score_values = [s for _, s in scores]
    return {oid: _percentile(score_values, score) for oid, score in scores}


def _load_roster_health_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Per-owner roster_health in [0, 1] from team-strength snapshot.

    The team-strength file stores ``healthAvailabilityScore`` already
    in [0, 100] (share of starting lineup not flagged injured/bye).
    Divide by 100 so it slots into the unit-scaled formula directly.
    """
    out: dict[str, float] = {}
    for r in rows:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue
        out[oid] = max(
            0.0,
            min(1.0, float(r.get("healthAvailabilityScore") or 0.0) / 100.0),
        )
    return out


def _schedule_adjusted_scores(
    snapshot: PublicLeagueSnapshot,
    team_strength_pcts: dict[str, float],
) -> dict[str, float]:
    """Per-owner schedule difficulty score in [0, 1].

    For each team, look up every remaining regular-season opponent
    and average their team-strength percentile.  Easier schedules
    average *low* opponent strength, so the score is the inverse:
    ``1 - mean(opponent_strength_percentiles)``.

    Empty dict when team-strength is absent or no remaining matchups
    can be inferred — the caller's missing_inputs renormalisation
    keeps absent metrics from deflating scores.
    """
    if not team_strength_pcts:
        return {}
    # Lazy import keeps this module's import path acyclic.
    from src.ros import playoff_sim  # noqa: PLC0415

    schedule = playoff_sim._remaining_schedule(snapshot)
    opponents: dict[str, list[float]] = defaultdict(list)
    for _week, owner_a, owner_b in schedule:
        if owner_b in team_strength_pcts:
            opponents[owner_a].append(team_strength_pcts[owner_b])
        if owner_a in team_strength_pcts:
            opponents[owner_b].append(team_strength_pcts[owner_a])
    out: dict[str, float] = {}
    for oid, op_pcts in opponents.items():
        if not op_pcts:
            continue
        out[oid] = max(0.0, min(1.0, 1.0 - statistics.mean(op_pcts)))
    return out


def _streak_score_from_outcomes(outcomes: list[float]) -> float:
    """Convert a chronological list of W/L outcomes (1.0 = W, 0.0 = L,
    0.5 = T) into a 0-1 streak score.  Reads the trailing run only;
    saturates at 5 wins (1.0) and bottoms at 5+ losses (0.0).
    """
    if not outcomes:
        return 0.5
    run = 0
    last = outcomes[-1]
    for o in reversed(outcomes):
        if o == last:
            run += 1
        else:
            break
    if last >= 0.75:  # winning streak
        return min(1.0, 0.5 + run * 0.10)
    if last <= 0.25:  # losing streak
        return max(0.0, 0.5 - run * 0.10)
    return 0.5  # tie or mixed


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Build the ROS power section for the public contract.

    Output mirrors the existing ``power.py::build_section`` shape so
    the frontend can render it side-by-side with no schema fork:

        {
            "currentRanking": [...],
            "weights": { ... },
            "missingInputs": [...]
        }

    The historical week-by-week series is intentionally NOT computed
    here in PR2 — the v1 power section already exposes that, and the
    ROS-team-strength input only has a single "now" snapshot.  PR3
    adds historical playoff-odds; the chart on the new tab will hook
    into that data instead.
    """
    registry = snapshot.managers
    seasons_sorted = sorted(snapshot.seasons, key=luck._season_sort_key)
    if not seasons_sorted:
        return {
            "currentRanking": [],
            "weights": dict(WEIGHTS),
            "missingInputs": ["snapshot empty"],
            "rosTeamStrengthAvailable": False,
        }

    # Career totals across all seasons (matches power.py's accumulator
    # semantics).  Recent buffer is per-season; the "recent form"
    # metric is the trailing 3-game average within the current season.
    career_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )
    season_outcomes: dict[str, list[float]] = defaultdict(list)
    last_season_recent: dict[str, list[float]] = defaultdict(list)
    last_season_allplay_share: dict[str, float] = {}

    for season in seasons_sorted:
        week_scores = luck._season_weekly_scores(season, registry)
        if not week_scores:
            continue
        if season is seasons_sorted[-1]:
            recent_buffer: dict[str, list[float]] = defaultdict(list)
        for wk in sorted(week_scores.keys()):
            scores = week_scores[wk]
            actuals, _ = luck._actual_week_results(season, wk, registry)
            all_play = luck._all_play_week(scores)
            for oid, pts in scores:
                s = career_state[oid]
                s["points"] += pts
                s["games"] += 1
                actual_share = actuals.get(oid, 0.0)
                s["wins"] += actual_share
                s["losses"] += 1.0 - actual_share
                season_outcomes[oid].append(actual_share)
                if season is seasons_sorted[-1]:
                    rb = recent_buffer[oid]
                    rb.append(pts)
                    if len(rb) > _RECENT_WINDOW:
                        rb.pop(0)
                    last_season_recent[oid] = list(rb)
                # Capture the last week's all-play expected share so
                # the all-play-record percentile reflects current
                # standings rather than a season-wide average that
                # would lag mid-season trades.
                ap = all_play.get(oid) or {}
                last_season_allplay_share[oid] = float(ap.get("expectedShare", 0.0))

    owner_ids = sorted(career_state.keys())
    if not owner_ids:
        return {
            "currentRanking": [],
            "weights": dict(WEIGHTS),
            "missingInputs": ["no owners played"],
            "rosTeamStrengthAvailable": False,
        }

    team_strength_rows = _load_team_strength_rows()
    ros_pct = _load_team_strength_percentiles()
    ros_available = bool(ros_pct)
    roster_health_by_owner = _load_roster_health_scores(team_strength_rows)
    schedule_by_owner = _schedule_adjusted_scores(snapshot, ros_pct)
    schedule_available = bool(schedule_by_owner)
    health_available = bool(roster_health_by_owner)

    # Compute per-owner inputs.
    inputs: dict[str, dict[str, float]] = {}
    for oid in owner_ids:
        s = career_state[oid]
        ppg = s["points"] / s["games"] if s["games"] else 0.0
        rb = last_season_recent.get(oid, [])
        recent = sum(rb) / len(rb) if rb else 0.0
        wins = s["wins"]
        games = s["games"] or 1
        wl = wins / games  # already in [0, 1]
        all_play = last_season_allplay_share.get(oid, 0.0)
        streak = _streak_score_from_outcomes(season_outcomes.get(oid, []))
        # Luck regression: a team whose actualWins lag expectedWins
        # gets a small boost (regression toward expected).  Clamp to
        # [-0.5, 0.5] then map to [0, 1].
        career_row = career_state[oid]
        # Re-walk the seasons to compute expectedWins (luck.py exposes
        # this via build_section but at PR-2 budget we'd rather not
        # invoke the whole section).  Re-use the same all_play share
        # iteration (cheap; same data already in scope).
        expected_share_running = 0.0
        for season in seasons_sorted:
            week_scores = luck._season_weekly_scores(season, registry)
            for wk in sorted(week_scores.keys()):
                scores = week_scores[wk]
                ap_week = luck._all_play_week(scores)
                if oid in {o for o, _ in scores}:
                    ap = ap_week.get(oid) or {}
                    expected_share_running += float(ap.get("expectedShare", 0.0))
        luck_delta = (wins - expected_share_running) / games if games else 0.0
        luck_score = max(0.0, min(1.0, 0.5 - luck_delta))  # underperformers get higher score (regression boost)

        inputs[oid] = {
            "ppg": ppg,
            "recent": recent,
            "wl_record": wl,
            "all_play": all_play,
            "streak": streak,
            "luck_regression": luck_score,
            "schedule_adjusted": schedule_by_owner.get(oid, 0.5),
            "roster_health": roster_health_by_owner.get(oid, 0.0),
        }

    # Convert raw inputs to percentiles (ppg, recent only — the others
    # are already 0-1 scores).
    ppg_values = [inputs[o]["ppg"] for o in owner_ids]
    recent_values = [inputs[o]["recent"] for o in owner_ids]

    # Renormalise weights when missing inputs are present so the score
    # stays in [0, 100] instead of being deflated by the unfilled
    # 0.04 + 0.03 = 0.07 budget.
    missing_inputs: list[str] = []
    if not ros_available:
        missing_inputs.append("team_ros_strength")
    if not schedule_available:
        missing_inputs.append("schedule_adjusted")
    if not health_available:
        missing_inputs.append("roster_health")
    active_weights = {
        k: v for k, v in WEIGHTS.items() if k not in missing_inputs
    }
    weight_total = sum(active_weights.values()) or 1.0

    rankings: list[dict[str, Any]] = []
    for oid in owner_ids:
        i = inputs[oid]
        components: dict[str, float] = {
            "ppg": _percentile(ppg_values, i["ppg"]),
            "recent": _percentile(recent_values, i["recent"]),
            "wl_record": i["wl_record"],
            "all_play": i["all_play"],
            "streak": i["streak"],
            "luck_regression": i["luck_regression"],
        }
        if ros_available:
            components["team_ros_strength"] = ros_pct.get(oid, 0.0)
        components["schedule_adjusted"] = (
            i["schedule_adjusted"] if schedule_available else 0.0
        )
        components["roster_health"] = (
            i["roster_health"] if health_available else 0.0
        )

        # Active weighted score in [0, 1], then scale to 100.
        score_unit = sum(
            active_weights.get(k, 0.0) * components.get(k, 0.0)
            for k in active_weights
        ) / weight_total
        score = round(score_unit * 100, 2)

        ros_strength_pct = ros_pct.get(oid, None) if ros_available else None
        rankings.append(
            {
                "ownerId": oid,
                "displayName": registry.display_name_for(oid)
                if hasattr(registry, "display_name_for")
                else oid,
                "powerScore": score,
                "components": {k: round(v, 4) for k, v in components.items()},
                "rosStrengthPercentile": (
                    round(ros_strength_pct, 4) if ros_strength_pct is not None else None
                ),
                "weightsApplied": dict(active_weights),
            }
        )

    rankings.sort(key=lambda r: -r["powerScore"])
    for rank, row in enumerate(rankings, start=1):
        row["rank"] = rank

    return {
        "currentRanking": rankings,
        "weights": dict(WEIGHTS),
        "missingInputs": sorted(missing_inputs),
        "rosTeamStrengthAvailable": ros_available,
    }
