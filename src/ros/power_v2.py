"""Canonical league Power Rankings.

The league-facing score has one forward-looking input and four observed
results targets:

    0.40 team ROS strength
    0.20 season-to-date all-play
    0.15 recent four-game form
    0.15 canonical weekly realized VORP/PAR (currently unavailable)
    0.10 official current-season record

Observed-results evidence enters smoothly as games are scored. Missing
inputs stay missing and the available weights renormalize without inventing
zeroes. The ``results_only`` lens is diagnostic; the legacy
``forward_looking`` query string is only a compatibility alias for the
canonical blend.

Current Sleeper roster membership is authoritative for the current Power
table. Team-strength/history are fallbacks only when current roster membership
is unavailable, so stale or historical owners cannot expand a 12-team league
view.

This is the only Power Ranking engine. Official week-to-week movement is
materialized separately by ``src.ros.power_snapshots``.
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

# Compatibility/diagnostic names retained for historical tests and payload
# readers. They are NOT weighted by the canonical score.
_HISTORICAL_RESULTS_COMPONENTS: tuple[str, ...] = (
    "ppg",
    "recent",
    "wl_record",
    "all_play",
    "streak",
    "luck_regression",
)
# The old cliff-based eligibility system is retired. Keeping an empty mapping
# makes old monkeypatch-based tests harmless while the smooth blend owns sample
# reliability.
_MIN_SCORED_GAMES: dict[str, int] = {}

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
        results_raw = (
            sum(WEIGHTS[k] for k in RESULT_COMPONENTS) * evidence if result_base > 0 else 0.0
        )
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

    * CANONICAL — prior-season results do not project the upcoming year,
      so preseason score mass remains on current ROS strength.
    * RESULTS-ONLY — the finished year IS the answer.  Nothing is
      dropped, or the lens would have nothing to say for the whole
      offseason.

    Legacy roster-health, schedule, streak and luck terms remain display or
    historical diagnostics only; none is a canonical weighted input.
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
      2. If no registry-valid current roster membership is available,
         owners present in the live team-strength snapshot are the first
         fallback.
      3. Prior-season career history is the final fallback. It never unions
         departed owners into a populated current-season league table.

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

    # A populated current-season roster is authoritative membership for this
    # CURRENT league ranking. Team-strength/history are fallbacks for an
    # incomplete snapshot, not unions that can resurrect departed owners.
    if not ordered:
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
        outcomes = (state.get("outcomes") or {}).get(oid, [])
        streak = _streak_score_from_outcomes(outcomes)
        expected_total = float((state.get("expected") or {}).get(oid, 0.0))
        luck_delta = (float(s.get("wins") or 0.0) - expected_total) / games if games else 0.0
        luck_score = max(0.0, min(1.0, 0.5 - luck_delta))
        inputs[oid] = {
            "ppg": ppg,
            "recent": recent,
            "wl_record": wl,
            "all_play": all_play,
            "streak": streak,
            "luck_regression": luck_score,
            # Deliberately unmeasured until a canonical weekly VORP/PAR owner
            # exists. The season-aggregate awards approximation is not a
            # substitute for the quantity the Power spec names.
            "team_vorp": None,
        }

    ppg_values = [inputs[o]["ppg"] for o in owner_ids]
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
            # Display-only diagnostics. None of these keys appears in WEIGHTS.
            "ppg": (None if i["ppg"] is None else _percentile(ppg_values, i["ppg"])),
            "streak": None if suppressed_results else i["streak"],
            "luck_regression": None if suppressed_results else i["luck_regression"],
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
            key: weight for key, weight in active_weights.items() if components.get(key) is not None
        }
        owner_weight_total = sum(owner_weights.values())
        score = None
        if owner_weight_total:
            score_unit = (
                sum(owner_weights[key] * float(components[key]) for key in owner_weights)
                / owner_weight_total
            )
            score = round(score_unit * 100.0, 2)

        rankings.append(
            {
                "ownerId": oid,
                "displayName": _metrics.display_name_for(snapshot, oid),
                "powerScore": score,
                "components": {
                    k: (None if v is None else round(float(v), 4)) for k, v in components.items()
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
    lens: str = LENS_CANONICAL,
) -> dict[str, Any]:
    """Build the single canonical Power ranking or its results-only diagnostic.

    Canonical answers "what has this team earned, and how strong is it now?"
    with a season-aware blend. Results-only is retained for inspection, not as
    a competing headline product. The legacy forward_looking query value is
    accepted as a compatibility alias for canonical.
    """
    if lens not in {LENS_CANONICAL, LENS_FORWARD_LOOKING, LENS_RESULTS_ONLY}:
        raise ValueError(f"unknown Power lens: {lens!r}")
    requested_lens = lens
    results_only = lens == LENS_RESULTS_ONLY
    public_lens = LENS_RESULTS_ONLY if results_only else LENS_CANONICAL

    registry = snapshot.managers
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    team_strength_rows = [] if results_only else _load_team_strength_rows(snapshot)
    preseason = _is_preseason(snapshot)

    if (
        not seasons_sorted
        and not team_strength_rows
        and (snapshot.current_season is None or not (snapshot.current_season.rosters or []))
    ):
        return {
            "currentRanking": [],
            "lens": public_lens,
            "requestedLens": requested_lens,
            "methodologyVersion": METHODOLOGY_VERSION,
            "weights": dict(WEIGHTS),
            "effectiveWeights": {},
            "blend": {
                "forwardWeight": 0.0,
                "resultsWeight": 0.0,
                "resultsEvidence": 0.0,
                "scoredGames": 0,
                "targetForwardWeight": WEIGHTS["team_ros_strength"],
                "targetResultsWeight": sum(WEIGHTS[k] for k in RESULT_COMPONENTS),
            },
            "missingInputs": ["snapshot empty"],
            "rosTeamStrengthAvailable": False,
            "preseason": preseason,
            "asOfSeason": None,
            "asOfWeek": 0,
            "officialSnapshot": None,
        }

    # Historical presence remains separate from the season-scoped scoring
    # state. A manager who rejoined after missing a season must not disappear.
    career_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )
    season_state: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0}
    )
    last_season_recent: dict[str, list[float]] = defaultdict(list)
    last_season_allplay_share: dict[str, float] = {}
    allplay_share_total: dict[str, float] = defaultdict(float)
    season_outcomes: dict[str, list[float]] = defaultdict(list)
    expected_share_total: dict[str, float] = defaultdict(float)
    week_states: list[tuple[str, int, dict[str, Any]]] = []
    scored_week_by_season: dict[str, int] = {}

    for season in seasons_sorted:
        week_scores = luck._season_weekly_scores(season, registry)
        if not week_scores:
            continue

        season_state = defaultdict(lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0})
        last_season_recent = defaultdict(list)
        last_season_allplay_share = {}
        allplay_share_total = defaultdict(float)
        season_outcomes = defaultdict(list)
        expected_share_total = defaultdict(float)
        recent_buffer: dict[str, list[float]] = defaultdict(list)

        for wk in sorted(week_scores.keys()):
            scores = week_scores[wk]
            actuals, _ = luck._actual_week_results(season, wk, registry)
            all_play = luck._all_play_week(scores)
            scored_week_by_season[str(season.season)] = int(wk)

            for oid, pts in scores:
                actual_share = actuals.get(oid, 0.0)

                career = career_state[oid]
                career["points"] += pts
                career["games"] += 1
                career["wins"] += actual_share
                career["losses"] += 1.0 - actual_share

                current = season_state[oid]
                current["points"] += pts
                current["games"] += 1
                current["wins"] += actual_share
                current["losses"] += 1.0 - actual_share
                season_outcomes[oid].append(actual_share)

                recent = recent_buffer[oid]
                recent.append(pts)
                if len(recent) > _RECENT_WINDOW:
                    recent.pop(0)
                last_season_recent[oid] = list(recent)

                expected_share = float((all_play.get(oid) or {}).get("expectedShare", 0.0))
                allplay_share_total[oid] += expected_share
                expected_share_total[oid] += expected_share
                # Season-to-date all-play, not "last week" wearing a broad
                # label. This is the schedule-independent earned-performance
                # signal named by the canonical spec.
                last_season_allplay_share[oid] = (
                    allplay_share_total[oid] / int(current["games"]) if current["games"] else 0.0
                )

            week_states.append(
                (
                    str(season.season),
                    int(wk),
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
            "lens": public_lens,
            "requestedLens": requested_lens,
            "methodologyVersion": METHODOLOGY_VERSION,
            "weights": dict(WEIGHTS),
            "effectiveWeights": {},
            "missingInputs": ["no owners found"],
            "rosTeamStrengthAvailable": False,
            "preseason": preseason,
            "asOfSeason": None,
            "asOfWeek": 0,
            "officialSnapshot": None,
        }

    # Sleeper's roster settings are the authoritative current competitive
    # record for the headline. Trend points cannot use today's roster settings
    # retroactively, so they fall back to matchup-derived as-of records.
    official_record_scores: dict[str, float] = {}
    official_record_strings: dict[str, str] = {}
    current_season = snapshot.current_season
    if current_season is not None:
        for roster in current_season.rosters or []:
            rid = _metrics.roster_id_of(roster)
            if rid is None:
                continue
            oid = _metrics.resolve_owner(registry, current_season.league_id, rid)
            if not oid:
                continue
            rec = _metrics.regular_season_settings_record(roster)
            games = int(rec["wins"]) + int(rec["losses"]) + int(rec["ties"])
            if games:
                official_record_scores[oid] = (
                    float(rec["wins"]) + 0.5 * float(rec["ties"])
                ) / games
                official_record_strings[oid] = (
                    f"{rec['wins']}-{rec['losses']}-{rec['ties']}"
                    if rec["ties"]
                    else f"{rec['wins']}-{rec['losses']}"
                )

    ros_pct = {} if results_only else _load_team_strength_percentiles(snapshot)
    ros_available = bool(ros_pct)
    final_state = {
        "career": season_state,
        "recent": last_season_recent,
        "allplay": last_season_allplay_share,
        "expected": expected_share_total,
        "outcomes": season_outcomes,
        "official_record": official_record_scores,
    }
    rankings, missing_inputs, active_weights, blend = _score_state(
        owner_ids,
        final_state,
        snapshot=snapshot,
        ros_pct=ros_pct,
        preseason=preseason,
        results_only=results_only,
    )

    current_league_id = (
        current_season.league_id
        if current_season is not None
        else (seasons_sorted[-1].league_id if seasons_sorted else None)
    )
    for row in rankings:
        rid = (
            luck._roster_id_for_owner(registry, current_league_id, row["ownerId"])
            if current_league_id
            else None
        )
        row["teamName"] = (
            _metrics.team_name(snapshot, current_league_id, rid) if current_league_id else None
        )
        if row["ownerId"] in official_record_strings:
            row["record"] = official_record_strings[row["ownerId"]]
            row["recordSource"] = "sleeper"
        else:
            current = season_state.get(row["ownerId"], _EMPTY_CAREER)
            wins = round(float(current.get("wins") or 0.0))
            games = int(current.get("games") or 0)
            row["record"] = f"{wins}-{games - wins}" if games else "0-0"
            row["recordSource"] = "matchups"

    current_season_label = (
        str(current_season.season)
        if current_season is not None
        else (str(seasons_sorted[-1].season) if seasons_sorted else None)
    )
    as_of_week = (
        int(scored_week_by_season.get(current_season_label, 0))
        if current_season_label is not None and not preseason
        else 0
    )
    as_of_season = current_season_label

    # Canonical week-over-week movement is compared only with exactly Week
    # N-1's immutable official publication. It never diffs two recalculations
    # from the same week.
    official_snapshot = None
    share_snapshot = None
    league_key = None
    if not results_only and as_of_season:
        try:
            from src.api.league_registry import league_key_for_sleeper_id  # noqa: PLC0415
            from src.ros import power_snapshots  # noqa: PLC0415

            league_key = league_key_for_sleeper_id(snapshot.root_league_id)
            if league_key:
                # The detailed table may be live, but its comparison anchor is
                # always a published week — never another same-week recalculation.
                if as_of_week > 0:
                    movement = power_snapshots.movement_against_previous(
                        league_key=league_key,
                        season=as_of_season,
                        week=as_of_week,
                        rankings=rankings,
                    )
                    for row in rankings:
                        row.update(movement.get(str(row.get("ownerId") or "")) or {})
                    official_snapshot = power_snapshots.load_snapshot(
                        league_key, as_of_season, as_of_week
                    )
                # Screenshot/share is stricter: use the latest immutable
                # official publication in this season. If the live engine has
                # already begun accumulating an incomplete next week, never
                # expose that partial recalculation as a weekly share card.
                share_snapshot = power_snapshots.latest_snapshot(
                    league_key,
                    season=as_of_season,
                )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[power_v2] weekly movement unavailable: %s", exc)

    # Historical chart remains results-only because no historical ROS value is
    # reconstructed after the fact. The immutable official snapshots above are
    # the canonical history from this methodology forward.
    trend_weeks: list[dict[str, Any]] = []
    series_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for season_label, wk, wk_state in week_states:
        wk_rankings, wk_missing, wk_weights, wk_blend = _score_state(
            owner_ids,
            wk_state,
            snapshot=snapshot,
            ros_pct={},
            preseason=False,
            results_only=True,
        )
        trend_weeks.append(
            {
                "season": season_label,
                "week": wk,
                "rankings": wk_rankings,
                "effectiveWeights": dict(wk_weights),
                "missingInputs": list(wk_missing),
                "blend": dict(wk_blend),
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

    unrankable: dict[str, Any] | None = None
    if not active_weights:
        unrankable = {
            "reason": (
                "preseason_and_no_forward_looking_input"
                if preseason and not results_only
                else "no_scoring_component_available"
            ),
            "missingInputs": sorted(missing_inputs),
            "explanation": (
                "No legitimate weighted component is available for this view, "
                "so Power withholds the score and rank instead of inventing an order."
            ),
        }

    scoring_fingerprint = None
    try:
        from src.ros import power_snapshots  # noqa: PLC0415

        scoring_fingerprint = power_snapshots.scoring_config_fingerprint(snapshot)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[power_v2] scoring fingerprint unavailable: %s", exc)

    return {
        "currentRanking": rankings,
        "lens": public_lens,
        "requestedLens": requested_lens,
        "methodologyVersion": METHODOLOGY_VERSION,
        "unrankable": unrankable,
        "trend": {
            "lens": LENS_RESULTS_ONLY,
            "weeks": trend_weeks,
            "seriesByOwner": {k: v for k, v in series_by_owner.items()},
            "note": (
                "Diagnostic results-only history. Canonical ROS strength was not "
                "snapshotted for old weeks, so it is never back-filled. Official "
                "canonical movement comes from immutable weekly publications."
            ),
        },
        "weights": dict(WEIGHTS),
        "effectiveWeights": dict(active_weights),
        "blend": dict(blend),
        "missingInputs": sorted(missing_inputs),
        "rosTeamStrengthAvailable": ros_available,
        "preseason": preseason,
        "asOfSeason": as_of_season,
        "asOfWeek": as_of_week,
        "leagueKey": league_key,
        "scoringConfigFingerprint": scoring_fingerprint,
        "officialSnapshot": official_snapshot,
        "shareSnapshot": share_snapshot,
    }
