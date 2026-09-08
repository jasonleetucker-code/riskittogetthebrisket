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
    * ``PublicLeagueSnapshot`` — the same historical walk the retired
      ``power.py`` v1 engine read.  Provides PPG, recent form, W/L,
      all-play, streak, and luck-regression inputs.

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

This is the ONLY power-ranking engine.  ``src/public_league/power.py``
(the pre-V1-52 v1 engine) and its renderer are deleted; /league → Power
always renders this module's output.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Iterable

from src.public_league import luck, metrics as _metrics
from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.power_v2")


# ── Canonical formula targets ─────────────────────────────────────────
# Owner-approved starting point from docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md.
# These are TARGET masses, not a claim that every component is always
# available. The canonical scorer preserves the forward-vs-results split
# first, then renormalises within the results bucket when (today) canonical
# weekly VORP/PAR is not yet available.
WEIGHTS: dict[str, float] = {
    "team_ros_strength": 0.40,
    "all_play": 0.20,
    "recent": 0.15,
    "team_vorp": 0.15,
    "wl_record": 0.10,
}

FORWARD_COMPONENTS: tuple[str, ...] = ("team_ros_strength",)
RESULT_COMPONENTS: tuple[str, ...] = ("all_play", "recent", "team_vorp", "wl_record")

#: Four games is both the recent-form horizon in the canonical spec and the
#: evidence time constant.  results_evidence = 1 - exp(-games / 4) gives a
#: smooth, monotone transition instead of arbitrary Week-1/2/4 cliffs.
_RESULTS_EVIDENCE_TAU_GAMES = 4.0
_RECENT_WINDOW = 4

#: Canonical weekly/realized VORP is specified but not dependency-ready.
#: The existing awards approximation is season-aggregate and floors at zero;
#: consuming it here would silently substitute a different quantity.
_UNAVAILABLE_CANONICAL_COMPONENTS: frozenset[str] = frozenset({"team_vorp"})

METHODOLOGY_VERSION = "canonical-power-2026.09-v1"

_EMPTY_CAREER: dict[str, float | int] = {
    "points": 0.0,
    "games": 0,
    "wins": 0.0,
    "losses": 0.0,
}


def _scored_game_count(state: dict[str, Any]) -> int:
    """Maximum current-season games represented by an as-of state."""
    career = state.get("career") or {}
    return max((int(v.get("games", 0)) for v in career.values()), default=0)


def _results_evidence(scored_games: int) -> float:
    """Reliability multiplier for observed results, smoothly in [0, 1)."""
    if scored_games <= 0:
        return 0.0
    return 1.0 - math.exp(-float(scored_games) / _RESULTS_EVIDENCE_TAU_GAMES)


def _effective_weight_vector(
    *,
    scored_games: int,
    ros_available: bool,
    available_results: set[str],
    preseason: bool,
    results_only: bool,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return the actual component weights plus blend metadata.

    Canonical mode preserves the spec's 40/60 forward/results TARGET while
    allowing observed evidence to earn its way into the score. Missing result
    inputs are renormalised *inside* the results bucket so an unavailable VORP
    dependency cannot accidentally make the ranking more forward-looking than
    the methodology intends.

    Results-only is a diagnostic lens over the same result components; it never
    loads ROS and renormalises the available results to 100%.
    """
    result_keys = [k for k in RESULT_COMPONENTS if k in available_results]
    result_base = sum(WEIGHTS[k] for k in result_keys)

    if results_only:
        forward_mass = 0.0
        results_mass = 1.0 if result_base > 0 else 0.0
        evidence = 1.0 if results_mass else 0.0
    else:
        evidence = 0.0 if preseason else _results_evidence(scored_games)
        forward_raw = WEIGHTS["team_ros_strength"] if ros_available else 0.0
        results_raw = sum(WEIGHTS[k] for k in RESULT_COMPONENTS) * evidence if result_base > 0 else 0.0
        total = forward_raw + results_raw
        forward_mass = forward_raw / total if total else 0.0
        results_mass = results_raw / total if total else 0.0

    applied: dict[str, float] = {}
    if forward_mass and ros_available:
        applied["team_ros_strength"] = forward_mass
    if results_mass and result_base:
        for key in result_keys:
            applied[key] = results_mass * (WEIGHTS[key] / result_base)

    blend = {
        "forwardWeight": round(forward_mass, 6),
        "resultsWeight": round(results_mass, 6),
        "resultsEvidence": round(evidence, 6),
        "scoredGames": int(scored_games),
        "targetForwardWeight": WEIGHTS["team_ros_strength"],
        "targetResultsWeight": sum(WEIGHTS[k] for k in RESULT_COMPONENTS),
    }
    return applied, blend


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


def _load_team_strength_rows(
    snapshot: PublicLeagueSnapshot | None = None,
) -> list[dict[str, Any]]:
    """Team-strength rows for the current league.

    Delegates to ``team_strength.load_or_compute_team_strength``, which
    reads the persisted ``data/ros/team_strength/latest.json`` when
    present and otherwise computes it LIVE from ``snapshot`` (no network)
    or, failing that, from a cached Sleeper overlay fetch — closing the
    single point of failure where this component went dark for a full
    refresh cycle whenever the scheduled scrape's write step hadn't run.
    Returns [] only when every tier is genuinely unable to answer.
    """
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    return load_or_compute_team_strength(snapshot=snapshot) or []


def _load_team_strength_percentiles(
    snapshot: PublicLeagueSnapshot | None = None,
) -> dict[str, float]:
    """Convert team-strength composite to a percentile per ownerId.
    Empty dict when no snapshot — caller renormalises weights.
    """
    rows = _load_team_strength_rows(snapshot)
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

    This predicate answers only "is there an in-progress regular
    season".  What that IMPLIES depends on the lens, and conflating the
    two is what made this function's old docstring wrong:

    * FORWARD-LOOKING — the historical-results components describe a
      finished year and don't project the upcoming one, so the build
      drops them via ``missing_inputs`` and the score reflects only
      forward-looking inputs (ROS strength, SOS).
    * RESULTS-ONLY — the finished year IS the answer.  Nothing is
      dropped, or the lens would have nothing to say for the whole
      offseason.

    ``roster_health`` is not in that forward-looking list any more: it
    was double-counted against ``team_ros_strength`` and was folded into
    it (0.38 -> 0.41) earlier in V1-52.
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

    Every source is filtered through the registry's non-retired owner
    ids (``ManagerRegistry.ordered_managers()``, NOT the raw
    ``by_owner_id`` dict — that dict is keyed by ALL owners including
    retired ones since C9-HIST-01, because a retired owner's real past
    seasons stay real history for standings/archives/franchise pages;
    this table is a CURRENT view, so it is one of the call sites that
    still needs the retirement exclusion applied).  The registry gate
    matters at every step because each upstream source can carry a
    stale owner around the season-transition window:

      * the team-strength snapshot is written by a scheduled scrape
        and lags live rosters by a refresh cycle;
      * Sleeper itself sometimes leaves a departed owner attached to
        a roster slot until a new owner claims it, so even
        ``snapshot.current_season.rosters`` can still carry them;
      * historical participants who left the league have rows in past
        ``career_state`` keys but should not appear in current rankings.

    Order of precedence (for the dedup walk — rows are re-sorted by
    power score before render):

      1. Owners on the snapshot's current Sleeper season — this is what
         league membership actually means TODAY, and it is not
         hypothetical: this league expanded from 10 to 12 teams for the
         2026 season, so prior-season history is a SHRINKING set that
         cannot be trusted as a primary source without silently dropping
         every owner who joined after the expansion.
      2. Owners present in the live team-strength snapshot — union, not
         override, so an owner Sleeper hasn't attached to a roster slot
         yet (a mid-season rejoin) is still caught.
      3. Owners from prior-season career history — last-resort fallback,
         only meaningful when there is no current season loaded at all.

    Precedence was inverted 2026-09 (was: team-strength -> current season
    -> history). Team-strength first made history — the shrinking set —
    the effective backstop whenever the team-strength file happened to be
    empty AND the current-season branch failed to contribute (a stale or
    partial persisted snapshot): the union then silently bottomed out at
    exactly the pre-expansion owner count, dropping every newly-joined
    manager with no error and no warning.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    registry_ids = {m.owner_id for m in snapshot.managers.ordered_managers()}

    def _add(oid: str | None) -> None:
        if not oid:
            return
        oid = str(oid).strip()
        if not oid or oid in seen or oid not in registry_ids:
            return
        seen.add(oid)
        ordered.append(oid)

    current = snapshot.current_season
    if current is not None:
        for roster in current.rosters or []:
            _add(roster.get("owner_id"))

    for row in team_strength_rows:
        _add(row.get("ownerId"))

    for oid in historical_owner_ids:
        _add(oid)

    # Floor invariant, not a correction: every registry-passing owner who
    # holds a roster in the CURRENT season must appear in the result. This
    # is a warning, never a synthesized row -- it exists to make a future
    # regression in any upstream source loud instead of a silent manager
    # drop discovered only by someone counting rows on the page.
    if current is not None:
        current_owner_ids = {
            str(r.get("owner_id") or "").strip()
            for r in (current.rosters or [])
            if str(r.get("owner_id") or "").strip() in registry_ids
        }
        missing = current_owner_ids - seen
        if missing:
            LOG.warning(
                "[power_v2] _enumerate_owner_ids: %d current-season roster "
                "owner(s) failed to enumerate: %s",
                len(missing),
                sorted(missing),
            )

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


def _score_state(
    owner_ids: list[str],
    state: dict[str, Any],
    *,
    snapshot: PublicLeagueSnapshot,
    ros_pct: dict[str, float],
    preseason: bool,
    results_only: bool,
) -> tuple[list[dict[str, Any]], list[str], dict[str, float], dict[str, float]]:
    """Score one current-season/as-of state with the canonical methodology.

    Results-only is a diagnostic lens over the same observed components.
    The canonical lens adds current ROS strength and lets results influence
    grow smoothly as scored-game evidence accumulates.
    """
    ros_available = bool(ros_pct) and not results_only
    official_record = state.get("official_record") or {}

    inputs: dict[str, dict[str, float | None]] = {}
    for oid in owner_ids:
        s = state["career"].get(oid, _EMPTY_CAREER)
        games = int(s.get("games") or 0)
        points = float(s.get("points") or 0.0)
        ppg = points / games if games else None
        rb = state["recent"].get(oid, [])
        recent = sum(rb) / len(rb) if rb else None
        computed_wl = float(s.get("wins") or 0.0) / games if games else None
        wl = official_record.get(oid, computed_wl)
        all_play = state["allplay"].get(oid)
        inputs[oid] = {
            "ppg": ppg,
            "recent": recent,
            "wl_record": wl,
            "all_play": all_play,
            # Deliberately unmeasured until a canonical weekly VORP/PAR owner
            # exists. The season-aggregate awards approximation is not a
            # substitute for the quantity the Power spec names.
            "team_vorp": None,
        }

    recent_values = [inputs[o]["recent"] for o in owner_ids]
    recent_available = any(v is not None for v in recent_values)
    all_play_available = any(inputs[o]["all_play"] is not None for o in owner_ids)
    wl_available = any(inputs[o]["wl_record"] is not None for o in owner_ids)

    available_results: set[str] = set()
    if all_play_available:
        available_results.add("all_play")
    if recent_available:
        available_results.add("recent")
    if wl_available:
        available_results.add("wl_record")

    missing_inputs: list[str] = []
    if not ros_available:
        missing_inputs.append(_LENS_DROPPED_ROS if results_only else "team_ros_strength")
    if not all_play_available:
        missing_inputs.append("all_play")
    if not recent_available:
        missing_inputs.append("recent")
    if not wl_available:
        missing_inputs.append("wl_record")
    missing_inputs.append(
        "team_vorp (canonical weekly realized VORP/PAR unavailable; not substituted)"
    )

    scored_games = _scored_game_count(state)
    active_weights, blend = _effective_weight_vector(
        scored_games=scored_games,
        ros_available=ros_available,
        available_results=available_results,
        preseason=preseason,
        results_only=results_only,
    )

    # Canonical preseason intentionally suppresses the previous season's
    # results. Results-only keeps them because retrospective performance is
    # the explicit subject of that diagnostic lens.
    suppressed_results = preseason and not results_only

    def _component_map(oid: str) -> dict[str, float | None]:
        i = inputs[oid]
        recent_value = i["recent"]
        return {
            "team_ros_strength": ros_pct.get(oid) if ros_available else None,
            "all_play": None if suppressed_results else i["all_play"],
            "recent": (
                None
                if suppressed_results or recent_value is None
                else _percentile(recent_values, recent_value)
            ),
            "team_vorp": None,
            "wl_record": None if suppressed_results else i["wl_record"],
            # Display-only diagnostics. Neither key appears in WEIGHTS.
            "pointsPerGame": i["ppg"],
            "recentAvg": recent_value,
        }

    if not active_weights:
        rows: list[dict[str, Any]] = []
        for oid in owner_ids:
            components = _component_map(oid)
            rows.append(
                {
                    "ownerId": oid,
                    "displayName": _metrics.display_name_for(snapshot, oid),
                    "powerScore": None,
                    "rank": None,
                    "components": {
                        k: (None if v is None else round(float(v), 4))
                        for k, v in components.items()
                    },
                    "rosStrengthPercentile": None,
                    "weightsApplied": {},
                }
            )
        return rows, missing_inputs, active_weights, blend

    rankings: list[dict[str, Any]] = []
    for oid in owner_ids:
        components = _component_map(oid)
        owner_weights = {
            key: weight
            for key, weight in active_weights.items()
            if components.get(key) is not None
        }
        owner_weight_total = sum(owner_weights.values())
        score = None
        if owner_weight_total:
            score_unit = sum(
                owner_weights[key] * float(components[key]) for key in owner_weights
            ) / owner_weight_total
            score = round(score_unit * 100.0, 2)

        rankings.append(
            {
                "ownerId": oid,
                "displayName": _metrics.display_name_for(snapshot, oid),
                "powerScore": score,
                "components": {
                    k: (None if v is None else round(float(v), 4))
                    for k, v in components.items()
                },
                "rosStrengthPercentile": (
                    round(float(ros_pct[oid]), 4) if oid in ros_pct and ros_available else None
                ),
                "weightsApplied": dict(owner_weights),
            }
        )

    # Standard competition ranking for exact score ties (1, 1, 3). ownerId
    # is only a deterministic presentation tiebreak inside an equal-rank
    # group; it never changes the published rank.
    scored_rows = [r for r in rankings if r["powerScore"] is not None]
    refused = [r for r in rankings if r["powerScore"] is None]
    scored_rows.sort(key=lambda r: (-float(r["powerScore"]), str(r["ownerId"])))
    prior_score: float | None = None
    prior_rank: int | None = None
    for position, row in enumerate(scored_rows, start=1):
        score = float(row["powerScore"])
        if prior_score is not None and score == prior_score:
            row["rank"] = prior_rank
        else:
            row["rank"] = position
            prior_rank = position
            prior_score = score
    for row in refused:
        row["rank"] = None

    return scored_rows + refused, missing_inputs, active_weights, blend



#: One canonical public answer plus one diagnostic retrospective lens.
LENS_CANONICAL = "canonical"
#: Compatibility alias accepted by the HTTP route for old bookmarks/clients.
#: It executes the canonical blend; it is no longer a separate product label.
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

        {
            "currentRanking": [...],   # rank/powerScore None when unrankable
            "lens": "...",
            "unrankable": {...} | None,
            "trend": {"weeks": [...], "seriesByOwner": {...}},
            "weights": {...},          # the spec vector
            "effectiveWeights": {...}, # what actually applied, renormalised
            "missingInputs": [...],
            "preseason": bool,
        }

    Two fields carry the honesty of the thing and are easy to drop:

    * ``effectiveWeights`` is what the score was ACTUALLY computed from.
      It differs from ``weights`` whenever an input is unavailable, and
      a surface that renders the spec vector instead will describe a
      formula the number did not come from.
    * ``unrankable`` is non-None when NO component survived.  Then
      ``powerScore`` and ``rank`` are ``None`` — never ``0.0``, never
      ``1..N`` — because ranking on identically-zero scores publishes
      the ``owner_ids`` order as if it were a result.

    This docstring used to say the week-by-week series was "intentionally
    NOT computed here in PR2" and that the v1 power section exposes it
    instead.  Both halves are now false: ``trend`` is computed here (so
    the table and the chart beside it are one quantity rather than two
    formulas), and the v1 section (``src/public_league/power.py``) is
    deleted -- this is the only remaining power-ranking engine.

    ``components.pointsPerGame``/``components.recentAvg`` (both headline
    rows and every ``trend.weeks[].rankings`` row) are the raw magnitudes
    v1's renderer displayed beside its percentile transforms.  They are
    surfaced from the same locals ``components.ppg``/``components.recent``
    already derive their percentile from -- not a second computation, and
    excluded from ``active_weights`` by construction (display-only; see
    the comment at their assignment in ``_score_state``).
    """
    registry = snapshot.managers
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    team_strength_rows = _load_team_strength_rows(snapshot)
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
    #
    # career_state is CONSUMED for exactly one purpose past this loop:
    # _enumerate_owner_ids's historical-presence fallback (its keys, not
    # its values) — a manager who mid-rejoined and is missing from both
    # live sources this season still needs to appear via history. It is
    # deliberately NOT reset per season and deliberately NOT read by
    # _score_state.
    career_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )
    # SEASON-scoped mirror of career_state, feeding ppg / wl_record and
    # the trend series only (V1-52 / #1020).  Reset at the top of each
    # season below, so by loop-end it holds ONLY the final season's
    # totals — the same "last write wins across the season boundary"
    # contract last_season_recent / last_season_allplay_share already
    # use for recentAvg / all_play.  Before this fix, ppg and wl_record
    # read career_state directly: a CAREER average presented as the
    # current season's number, contaminated by every prior season a
    # manager played, including on the trend line for weeks that had not
    # happened yet in the contaminating season.
    season_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )
    season_outcomes: dict[str, list[float]] = defaultdict(list)
    last_season_recent: dict[str, list[float]] = defaultdict(list)
    last_season_allplay_share: dict[str, float] = {}
    expected_share_total: dict[str, float] = defaultdict(float)
    #: ``(season, week, state-as-of-that-week)`` for the trend series.
    week_states: list[tuple[str, int, dict[str, Any]]] = []

    for season in seasons_sorted:
        week_scores = luck._season_weekly_scores(season, registry)
        if not week_scores:
            continue
        # Reset at the top of each season's processing — V1-52.  By the
        # time this loop ends, season_state holds ONLY the final
        # season's totals.
        season_state = defaultdict(lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0})
        # Same reset, same reason (V1-52 follow-up): season_outcomes and
        # expected_share_total fed streak/luck_regression from a career
        # total the same way season_state's points/games fed ppg/wl_record
        # before the fix above. Neither has a second, career-scoped
        # consumer (unlike career_state, whose .keys() also backs
        # _enumerate_owner_ids's historical-presence fallback), so resetting
        # them here in place is sufficient -- no parallel accumulator
        # needed.
        season_outcomes = defaultdict(list)
        expected_share_total = defaultdict(float)
        # Same reset, same reason, third time (V1-52 follow-up 2):
        # last_season_recent / last_season_allplay_share feed recent and
        # all_play.  They were NOT reset here -- last_season_recent was
        # gated on ``season is seasons_sorted[-1]`` and
        # last_season_allplay_share on an unconditional overwrite.
        #
        # The gate was the defect.  This loop ``continue``s past a
        # scoreless season ABOVE, so when the newest season in the
        # snapshot has no scores yet -- every preseason, and the state
        # production is in right now -- ``seasons_sorted[-1]`` is that
        # scoreless season and the guard never fired for ANY season.
        # last_season_recent stayed empty for every owner, _score_state
        # read ``recent = 0.0`` for all of them, and a percentile over an
        # all-equal list is 0.5.  A 0.12-weight component (21.8% of the
        # results-only score, whose active weights sum to 0.55) was
        # published as a measurement with nothing measured behind it, and
        # the UI rendered "0.0" recentAvg as though it were an
        # observation.
        #
        # Resetting here instead makes "the last SCORED season wins"
        # structural for all six accumulators rather than a property of
        # which season happens to sit last in the list.  An owner absent
        # from that season now holds no stale prior-season value either
        # -- their recent/all_play go empty exactly as their
        # season_state does, so the three stay consistent.
        last_season_recent = defaultdict(list)
        last_season_allplay_share = {}
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
                ss = season_state[oid]
                ss["points"] += pts
                ss["games"] += 1
                ss["wins"] += actual_share
                ss["losses"] += 1.0 - actual_share
                season_outcomes[oid].append(actual_share)
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
                # Running sum, accumulated HERE rather than re-walked per
                # owner below.  The re-walk was O(owners x weeks) inside an
                # owner loop, and the per-week trend would have made it
                # O(weeks x owners x weeks) for a quantity that is a running
                # total by construction.
                expected_share_total[oid] += float(ap.get("expectedShare", 0.0))

            # Snapshot the state AS OF this week, for the trend series.
            # A copy, because the accumulators keep mutating: a reference
            # here would make every week's entry show the final standings,
            # which is a trend line that cannot go down.
            week_states.append(
                (
                    season.season,
                    wk,
                    {
                        "career": {o: dict(v) for o, v in season_state.items()},
                        "recent": {o: list(v) for o, v in last_season_recent.items()},
                        "allplay": dict(last_season_allplay_share),
                        "expected": dict(expected_share_total),
                        "outcomes": {o: list(v) for o, v in season_outcomes.items()},
                    },
                )
            )

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
    ros_pct = {} if results_only else _load_team_strength_percentiles(snapshot)
    ros_available = bool(ros_pct)
    schedule_by_owner = _schedule_adjusted_scores(snapshot, ros_pct)

    final_state = {
        "career": season_state,
        "recent": last_season_recent,
        "allplay": last_season_allplay_share,
        "expected": expected_share_total,
        "outcomes": season_outcomes,
    }
    rankings, missing_inputs, active_weights = _score_state(
        owner_ids,
        final_state,
        snapshot=snapshot,
        ros_pct=ros_pct,
        schedule_by_owner=schedule_by_owner,
        preseason=preseason,
        results_only=results_only,
    )

    # ``teamName`` and ``record`` only for the HEADLINE rows -- a lookup
    # (resp. career fact) per owner, once, not per trend week (56+ weeks
    # x 12 owners of unused work for fields the trend series has no use
    # for).  ``teamName``: same source power.py reads
    # (``_roster_id_for_owner`` -> ``_metrics.team_name``), because a team
    # name is not this engine's concept to redefine -- it is looked up,
    # never derived from anything power-ranking-specific.
    #
    # ``record`` is READ FROM ``career_state`` HERE, deliberately not
    # from ``final_state["career"]`` (== ``season_state``) inside
    # ``_score_state`` -- V1-52 / #1032 repointed the headline call's
    # ``state["career"]`` to the season-scoped accumulator so ppg/
    # wl_record stop reading a career average as the current season's
    # number.  ``record`` is a DIFFERENT field with the OPPOSITE
    # intent: a true career wins/losses tally, the same accumulator
    # ``power.py``'s own ``record`` field reads (an actual-share tally
    # across every historical week, not the current season's
    # Sleeper-stored W-L).  Reading it via ``state["career"]`` would
    # have silently reintroduced #1032's exact contamination bug for
    # this one field -- present here, not in ``_score_state``, is what
    # keeps it reading the real unreset accumulator regardless of which
    # state ``_score_state`` was called with (headline vs. any given
    # trend week).
    league_id = seasons_sorted[-1].league_id if seasons_sorted else None
    for row in rankings:
        rid = luck._roster_id_for_owner(registry, league_id, row["ownerId"]) if league_id else None
        row["teamName"] = _metrics.team_name(snapshot, league_id, rid) if league_id else None
        career = career_state.get(row["ownerId"], _EMPTY_CAREER)
        career_wins = round(career["wins"])
        career_games = career["games"]
        row["record"] = f"{career_wins}-{career_games - career_wins}"

    # ── The trend series ────────────────────────────────────────────
    #
    # RESULTS-ONLY at every week, INCLUDING the current one, and that is
    # deliberate.  ``team_ros_strength`` is a single current snapshot —
    # ``data/ros/team_strength/latest.json`` — never a per-week history,
    # so there is no observation of it for any past week.  Back-filling
    # today's value would be the as-of defect: a number that was not
    # known then, presented as if it had been.
    #
    # Splicing it into only the LAST point would be worse than either
    # extreme: the line would jump at the final week for a reason that
    # has nothing to do with how the team played, and no reader could
    # tell that from a real move.  So the trend is one internally
    # consistent quantity, and it is NAMED as a different one from the
    # headline ranking rather than left to be discovered.
    trend_weeks: list[dict[str, Any]] = []
    series_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for season_label, wk, wk_state in week_states:
        wk_rankings, _wk_missing, _wk_weights = _score_state(
            owner_ids,
            wk_state,
            snapshot=snapshot,
            ros_pct={},
            schedule_by_owner={},
            preseason=False,
            results_only=True,
        )
        trend_weeks.append(
            {
                "season": season_label,
                "week": wk,
                "rankings": wk_rankings,
                # Additive: early weeks now score on a narrower component
                # set than the headline (progressive per-component
                # eligibility -- see ``_MIN_SCORED_GAMES``), so the trend
                # payload names the basis each point was actually computed
                # on rather than leaving it implicit.
                "effectiveWeights": dict(_wk_weights),
                "missingInputs": list(_wk_missing),
            }
        )
        for row in wk_rankings:
            series_by_owner[row["ownerId"]].append(
                {
                    "season": season_label,
                    "week": wk,
                    "powerScore": row["powerScore"],
                    "rank": row["rank"],
                }
            )

    # The refusal, surfaced. ``_score_state`` returns rows whose score and
    # rank are None when no component survived; the section must SAY so
    # rather than leave a consumer to infer it from null fields, which is
    # how a refusal gets rendered as an empty table or a zero.
    unrankable: dict[str, Any] | None = None
    if not active_weights:
        unrankable = {
            "reason": (
                "no_scoring_component_available"
                if not preseason
                else "preseason_and_no_forward_looking_input"
            ),
            "missingInputs": sorted(missing_inputs),
            "explanation": (
                "Every weighted component is unavailable, so there is no "
                "quantity to rank on. The owners and their raw component "
                "values are listed; the score and the rank are withheld "
                "rather than published as zeros in identifier order."
            ),
        }

    return {
        "currentRanking": rankings,
        "lens": lens,
        "unrankable": unrankable,
        "trend": {
            "lens": LENS_RESULTS_ONLY,
            "weeks": trend_weeks,
            "seriesByOwner": {k: v for k, v in series_by_owner.items()},
            "note": (
                "Results only. Forward-looking roster strength is a current "
                "snapshot with no per-week history, so it is excluded from "
                "every point rather than back-filled into past weeks or "
                "spliced into the last one. The headline ranking includes it "
                "and will differ."
            ),
        },
        "weights": dict(WEIGHTS),
        "effectiveWeights": dict(active_weights),
        "missingInputs": sorted(missing_inputs),
        "rosTeamStrengthAvailable": ros_available,
        "preseason": preseason,
    }
