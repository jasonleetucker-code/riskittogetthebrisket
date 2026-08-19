"""ROS-driven power rankings (v2).

Spec formula (in-season):

    power_score =
        0.38 * team_ros_strength_percentile
        + 0.18 * season_points_scored_percentile
        + 0.12 * recent_points_scored_percentile
        + 0.10 * win_loss_record_percentile
        + 0.08 * all_play_record_percentile
        + 0.05 * winning_streak_score
        + 0.04 * schedule_adjusted_performance
        + 0.02 * luck_regression_score

Inputs come from two places:

    * ``data/ros/team_strength/latest.json`` — written by
      ``src.ros.team_strength``.  Provides ``team_ros_strength_percentile``.
    * ``PublicLeagueSnapshot`` — already feeds the existing
      ``power.py``.  Provides PPG, recent form, W/L, all-play, streak,
      and luck-regression inputs.

The owner list spans every team that owns a roster in the current
league, sourced from the team-strength snapshot (live Sleeper rosters)
unioned with the snapshot's current-season rosters.  Owners who joined
the league for the upcoming year and have no prior-season record still
appear with their ROS-based score — without this union the table
silently drops to the count of owners with historical participation.

Preseason / between-seasons handling: when no scored regular-season
matchups exist for the snapshot's current season (either because the
year hasn't kicked off yet or the prior year is complete and the new
schedule isn't loaded), the historical-results components — PPG,
recent form, W/L, all-play, streak, and luck regression — describe a
season that is over and don't project the upcoming year.  Those
components are routed through ``missing_inputs`` so the formula
renormalises onto the forward-looking metrics (team ROS strength,
roster health, and 2026 schedule SOS when available).  The same
``missing_inputs`` machinery that protects against an absent
team-strength file already handles renormalisation cleanly.

Render-side, this section is gated by ``settings.useRosPowerRankings``:
when False, the existing ``power.py`` v1 still drives /league → Power.
When True, /league → ROS Power renders this version side-by-side as
the new "ROS Power" tab.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import defaultdict
from typing import Any, Iterable

from src.ros import ROS_DATA_DIR
from src.public_league import luck, metrics as _metrics
from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.power_v2")


# ── Formula weights (spec) ────────────────────────────────────────────
# ``roster_health`` REMOVED 2026-08-18 and its 0.03 folded into
# ``team_ros_strength``.  Two independent reasons, either sufficient:
#
# 1. SIGNAL INDEPENDENCE (CLAUDE.md §3.3 — "a body of evidence affects a
#    conclusion once").  Health was counted TWICE: ``team_strength.py``
#    already folds ``healthAvailabilityScore`` into the composite at
#    ``WEIGHT_HEALTH = 0.05``, and this table then added it again on top of
#    ``0.38 × percentile(composite)``.  On the preseason weight set the
#    standalone term was 7.3% of the published score while the composite
#    retained 4.6% of health influence.
#
# 2. PRIVACY (CLAUDE.md §5).  ``components.roster_health`` was
#    ``healthAvailabilityScore / 100`` exactly — a field listed in
#    ``tests/api/test_public_league_privacy_boundary.py::PRIVATE_MARKERS``,
#    sourced from the AUTH-GATED ``rosTeamStrength`` section, republished on
#    the PUBLIC ``rosPower`` section of an unauthenticated page.  The privacy
#    guard scans for private field NAMES, so the rename+rescale passed it.
#    The disclosure was exact rather than fuzzy: the score is
#    ``healthy_starters / starting_slots``, so at 4dp over this league's 21
#    slots a public reader recovers a rival's precise count of flagged
#    starters.
#
# This is DE-DUPLICATION, not a weakening of the ranking, and not a
# declassification: health keeps its designed 0.05 share inside
# ``teamRosStrength``, whose inclusive PERCENTILE remains a public input by
# owner decision.  Publishing only that rank is what keeps it safe — the
# composite is ``0.72S + 0.18D + 0.05C + 0.05H`` and a rank over 12 owners is
# 11 ordering constraints against 36 unknowns.
WEIGHTS: dict[str, float] = {
    "team_ros_strength": 0.41,
    "ppg": 0.18,
    "recent": 0.12,
    "wl_record": 0.10,
    "all_play": 0.08,
    "streak": 0.05,
    "schedule_adjusted": 0.04,
    "luck_regression": 0.02,
}

_RECENT_WINDOW = 3  # matches power.py

# Components driven entirely by the most-recent-loaded season's results.
# Routed through ``missing_inputs`` when no scored games exist in the
# current season — see module docstring.
_HISTORICAL_RESULTS_COMPONENTS: tuple[str, ...] = (
    "ppg",
    "recent",
    "wl_record",
    "all_play",
    "streak",
    "luck_regression",
)

_EMPTY_CAREER: dict[str, float | int] = {
    "points": 0.0,
    "games": 0,
    "wins": 0.0,
    "losses": 0.0,
}


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


def _is_preseason(snapshot: PublicLeagueSnapshot) -> bool:
    """True when no in-progress regular season exists for the snapshot.

    Two conditions count as "going into a new season":
      * no current season at all (empty snapshot);
      * the snapshot's current season has zero scored regular-season
        matchups — covers both "Sleeper has the new year live but no
        games have been played yet" and "the prior year is complete
        and we're between seasons".

    In this state the historical-results components describe a finished
    season and don't project the upcoming year.  The build pipeline
    drops them via ``missing_inputs`` so the score reflects only
    forward-looking inputs (ROS strength, roster health, SOS).
    """
    current = snapshot.current_season
    if current is None:
        return True
    if current.is_complete:
        return True
    for wk in current.regular_season_weeks:
        for entry in current.matchups_by_week.get(wk) or []:
            pts = entry.get("points")
            try:
                if pts is not None and float(pts) > 0:
                    return False
            except (TypeError, ValueError):
                continue
    return True


def _enumerate_owner_ids(
    snapshot: PublicLeagueSnapshot,
    team_strength_rows: list[dict[str, Any]],
    historical_owner_ids: Iterable[str],
) -> list[str]:
    """Canonical owner list for the rankings table.

    Every source is filtered through ``snapshot.managers.by_owner_id``,
    which is the authoritative active-owner registry: it's built from
    the rosters the snapshot actually fetched and excludes the
    operator-maintained retirement list.  The registry gate matters at
    every step because each upstream source can carry a stale owner
    around the season-transition window:

      * the team-strength snapshot is written by a scheduled scrape
        and lags live rosters by a refresh cycle;
      * Sleeper itself sometimes leaves a departed owner attached to
        a roster slot until a new owner claims it, so even
        ``snapshot.current_season.rosters`` can still carry them;
      * historical participants who left the league have rows in past
        ``career_state`` keys but should not appear in current rankings.

    Order of precedence (for the dedup walk — rows are re-sorted by
    power score before render):

      1. Owners present in the live team-strength snapshot.
      2. Owners on the snapshot's current Sleeper season — fallback
         for an empty team-strength file.
      3. Owners from prior-season career history — defensive fallback
         so a registered manager who exists in history but is missing
         from both live sources (e.g. mid-rejoin) still appears.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    registry_ids = snapshot.managers.by_owner_id

    def _add(oid: str | None) -> None:
        if not oid:
            return
        oid = str(oid).strip()
        if not oid or oid in seen or oid not in registry_ids:
            return
        seen.add(oid)
        ordered.append(oid)

    for row in team_strength_rows:
        _add(row.get("ownerId"))

    current = snapshot.current_season
    if current is not None:
        for roster in current.rosters or []:
            _add(roster.get("owner_id"))

    for oid in historical_owner_ids:
        _add(oid)

    return ordered


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


#: The two lenses this engine publishes, and what separates them.
#:
#: They are NOT two formulas.  ``results_only`` is the same weight vector
#: with ``team_ros_strength`` declared missing, renormalised by the
#: machinery that already handles an absent team-strength file — so the
#: relative weighting of every retrospective component is identical in
#: both, and the only difference is whether the forward-looking input is
#: in the mix.  That is what makes them lenses rather than engines.
LENS_FORWARD_LOOKING = "forward_looking"
LENS_RESULTS_ONLY = "results_only"

#: Why a lens dropped ROS, distinguished from "the file was missing".
#: A reader must be able to tell a deliberate retrospective view from an
#: engine that wanted forward-looking strength and could not get it.
_LENS_DROPPED_ROS = "team_ros_strength (lens: results_only)"


def build_section(
    snapshot: PublicLeagueSnapshot,
    *,
    lens: str = LENS_FORWARD_LOOKING,
) -> dict[str, Any]:
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
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    team_strength_rows = _load_team_strength_rows()
    preseason = _is_preseason(snapshot)
    if (
        not seasons_sorted
        and not team_strength_rows
        and (snapshot.current_season is None or not (snapshot.current_season.rosters or []))
    ):
        return {
            "currentRanking": [],
            "lens": lens,
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

    owner_ids = _enumerate_owner_ids(snapshot, team_strength_rows, sorted(career_state.keys()))
    if not owner_ids:
        return {
            "currentRanking": [],
            "lens": lens,
            "weights": dict(WEIGHTS),
            "missingInputs": ["no owners found"],
            "rosTeamStrengthAvailable": False,
        }

    # The results-only lens does not consult team strength at all, rather
    # than loading it and discarding it — so a reader cannot mistake the
    # lens for a league whose team-strength file is missing, and so the
    # schedule-adjusted component (which is derived FROM team strength)
    # drops with it automatically rather than by a second rule.
    results_only = lens == LENS_RESULTS_ONLY
    ros_pct = {} if results_only else _load_team_strength_percentiles()
    ros_available = bool(ros_pct)
    schedule_by_owner = _schedule_adjusted_scores(snapshot, ros_pct)
    schedule_available = bool(schedule_by_owner)

    # Compute per-owner inputs.  ``career_state`` is a defaultdict but
    # we read via ``.get`` to avoid mutating it for owners (e.g. new
    # league members for the upcoming season) who never appeared in
    # historical play.  Their historical components default to zero;
    # in preseason mode those weights are renormalised away anyway.
    inputs: dict[str, dict[str, float]] = {}
    for oid in owner_ids:
        s = career_state.get(oid, _EMPTY_CAREER)
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
        luck_score = max(
            0.0, min(1.0, 0.5 - luck_delta)
        )  # underperformers get higher score (regression boost)

        inputs[oid] = {
            "ppg": ppg,
            "recent": recent,
            "wl_record": wl,
            "all_play": all_play,
            "streak": streak,
            "luck_regression": luck_score,
            "schedule_adjusted": schedule_by_owner.get(oid, 0.5),
        }

    # Convert raw inputs to percentiles (ppg, recent only — the others
    # are already 0-1 scores).
    ppg_values = [inputs[o]["ppg"] for o in owner_ids]
    recent_values = [inputs[o]["recent"] for o in owner_ids]

    # Renormalise weights when missing inputs are present so the score
    # stays in [0, 100] instead of being deflated by the unfilled
    # weight budget.  Preseason / between-seasons drops the historical
    # results components — they describe a finished year and don't
    # project the upcoming one (see ``_is_preseason``).
    missing_inputs: list[str] = []
    if not ros_available:
        missing_inputs.append(_LENS_DROPPED_ROS if results_only else "team_ros_strength")
    if not schedule_available:
        missing_inputs.append("schedule_adjusted")
    if preseason:
        for component in _HISTORICAL_RESULTS_COMPONENTS:
            if component not in missing_inputs:
                missing_inputs.append(component)
    # ``missing_inputs`` is a human-readable list; the weight lookup keys
    # on component NAMES, so the lens marker is normalised back before it
    # is used to drop a weight.  Without this the lens would leave
    # ``team_ros_strength`` weighted at 0.41 against a component of 0.0 —
    # a silent 41% deflation of every score rather than a renormalisation.
    dropped_components = {m.split(" (")[0] for m in missing_inputs}
    active_weights = {k: v for k, v in WEIGHTS.items() if k not in dropped_components}
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
        components["schedule_adjusted"] = i["schedule_adjusted"] if schedule_available else 0.0

        # Active weighted score in [0, 1], then scale to 100.
        score_unit = (
            sum(active_weights.get(k, 0.0) * components.get(k, 0.0) for k in active_weights)
            / weight_total
        )
        score = round(score_unit * 100, 2)

        ros_strength_pct = ros_pct.get(oid, None) if ros_available else None
        # Display name resolution: ``ManagerRegistry`` doesn't define
        # a ``display_name_for`` method (the original ``hasattr`` guard
        # always evaluated False), so this used to fall back to the
        # raw Sleeper owner_id and the /league Power table rendered
        # numeric IDs in the OWNER column.  The canonical helper lives
        # at module scope in ``src.public_league.metrics``; use it
        # consistently with the rest of the public-league pipeline.
        rankings.append(
            {
                "ownerId": oid,
                "displayName": _metrics.display_name_for(snapshot, oid),
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
        "lens": lens,
        "weights": dict(WEIGHTS),
        "effectiveWeights": dict(active_weights),
        "missingInputs": sorted(missing_inputs),
        "rosTeamStrengthAvailable": ros_available,
        "preseason": preseason,
    }
