"""Canonical league Power Rankings.

The league-facing score has one forward-looking input and four observed
results targets:

    0.30 team ROS strength
    0.30 season-to-date all-play
    0.15 recent four-game form
    0.15 canonical weekly realized VORP/PAR (currently unavailable)
    0.10 official current-season record

Rebalanced 2026-09-22, owner directive: the prior 0.40/0.20/0.15/0.15/0.10
target gave the forward-looking ROS input too much influence relative to
demonstrated performance, especially early in the season -- at 2 games
played it split roughly 63% forward / 37% results, the INVERSE of the
owner's stated ~60-65% demonstrated / ~35-40% forward-looking target for
that point in the season. Two changes, kept separate on purpose:

  * the TARGET split itself moved 40/60 -> 30/70 (``WEIGHTS`` below), and
    the evidence time constant sped up 4 -> 2 games
    (``_RESULTS_EVIDENCE_TAU_GAMES``), so results earn their target share
    faster. Together these land the g=2 forward/results split at
    approximately 40/60 -- at the boundary of, not deep inside, the
    stated band, by design: the constants are round and independently
    explainable rather than curve-fit to hit an exact percentage the
    owner themselves called approximate.
  * ``all_play`` rose 0.20 -> 0.30 (now tied with ``team_ros_strength`` as
    the largest individual weight) because it is the one genuinely
    schedule-independent, season-long measure of scoring quality this
    formula has -- see ``docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md``
    §6 for why a SEPARATE raw-PPG weight was rejected instead (it would
    double-count the same scoring evidence ``all_play`` already prices
    in). ``recent`` and ``wl_record`` were deliberately left at their
    prior ABSOLUTE weights: growing the results bucket around them
    already shrinks their RELATIVE share (record's share of the results
    bucket falls from 16.7% to 14.3%), which is the "should matter but
    not dominate" the owner asked for, without a second lever.

``recent`` also gets a new, separate correction: while ``games_played <=
_RECENT_WINDOW`` its trailing window IS the entire season-to-date sample
(see ``_recent_distinctness``), so it is definitionally redundant with
``all_play`` over that stretch and contributes no weight of its own until
the window genuinely diverges from the full season past week 4. This is
an internal reallocation within the results bucket only; it does not
change the forward/results split itself.

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
from src.public_league.snapshot import PublicLeagueSnapshot, current_season_membership_error

LOG = logging.getLogger("ros.power_v2")


# ── Canonical formula targets ─────────────────────────────────────────
# Owner-approved starting point from docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md.
# These are TARGET masses, not a claim that every component is always
# available. The canonical scorer preserves the forward-vs-results split
# first, then renormalises within the results bucket when (today) canonical
# weekly VORP/PAR is not yet available.
WEIGHTS: dict[str, float] = {
    "team_ros_strength": 0.30,
    "all_play": 0.30,
    "recent": 0.15,
    "team_vorp": 0.15,
    "wl_record": 0.10,
}

FORWARD_COMPONENTS: tuple[str, ...] = ("team_ros_strength",)
RESULT_COMPONENTS: tuple[str, ...] = ("all_play", "recent", "team_vorp", "wl_record")

#: How fast the forward/results MASS split shifts toward its target as games
#: are played.  results_evidence = 1 - exp(-games / tau), smooth and
#: monotone instead of arbitrary Week-1/2/4 cliffs.  Deliberately DECOUPLED
#: from ``_RECENT_WINDOW`` (2026-09-22 rebalance) -- the two constants used
#: to share one value (4) "by coincidence of sharing the same number," not
#: because the two questions are the same one.  This one answers "how many
#: games before the blend has mostly shifted from projection to results";
#: ``_RECENT_WINDOW`` answers "how many trailing games count as recent
#: form" and is unrelated to that.  2 games matches the owner-stated target
#: of the blend already reading roughly 60/40 toward demonstrated
#: performance by the second week of the season.
_RESULTS_EVIDENCE_TAU_GAMES = 2.0
#: Trailing-form window for the ``recent`` component and its display
#: diagnostic.  Unchanged by the 2026-09-22 rebalance.
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

#: Bumped to v2 with the 2026-09-22 rebalance (30/70 target, tau 2, recent
#: redundancy discount). That commit changed the formula but kept v1, so the
#: Week 2 publication (old formula, 05:29Z) and the live table (new formula,
#: 10:59Z onward) carried the same version string and a reader could not tell
#: a methodology change from a data change. Publications stay keyed by
#: (league, season, week) only, so a version change can never orphan history:
#: movement still compares against exactly week N-1, and names that week's
#: version in ``movementBaseline``.
METHODOLOGY_VERSION = "canonical-power-2026.09-v2"

#: Zero state for ONE season. Named for what it holds: this and the
#: ``state["season"]`` key it backs were called ``_EMPTY_CAREER`` /
#: ``state["career"]`` while holding season-scoped state, and that name has
#: already cost one shipped defect — see
#: ``tests/ros/test_power_v2_headline_fields.py``, where ``record`` read the
#: key believing it was the cross-season accumulator. The genuine
#: cross-season accumulator is ``career_state``, which is used only for
#: owner enumeration and never reaches ``_score_state``.
_EMPTY_SEASON_STATE: dict[str, float | int] = {
    "points": 0.0,
    "games": 0,
    "wins": 0.0,
    "losses": 0.0,
}


def _scored_game_span(state: dict[str, Any]) -> tuple[int, int]:
    """``(shared, maximum)`` current-season games across scored owners.

    Owners with no rows at all are excluded rather than dragging the shared
    count to zero — they have not played, which is a different statement
    from the league having no evidence.
    """
    season_state = state.get("season") or {}
    counts = [int(v.get("games", 0)) for v in season_state.values()]
    counts = [c for c in counts if c > 0]
    if not counts:
        return 0, 0
    return min(counts), max(counts)


def _scored_game_count(state: dict[str, Any]) -> int:
    """Games EVERY scored owner has played — the league's SHARED evidence.

    Deliberately the minimum, not the maximum.  The results-evidence ramp
    asks "how much has this league actually played", and the maximum
    answers it with the luckiest team's total: when denominators diverged
    it claimed more evidence than any shared week supported.  With the
    completed-week gate in ``metrics.final_regular_season_weeks`` they no
    longer diverge, so this is an identity on healthy data and an honest
    floor on unhealthy data.
    """
    return _scored_game_span(state)[0]


def _results_evidence(scored_games: int) -> float:
    """Reliability multiplier for observed results, smoothly in [0, 1)."""
    if scored_games <= 0:
        return 0.0
    return 1.0 - math.exp(-float(scored_games) / _RESULTS_EVIDENCE_TAU_GAMES)


def _recent_distinctness(games_played: int, window: int = _RECENT_WINDOW) -> float:
    """How much of ``recent`` is information NOT already in season-to-date.

    While ``games_played <= window`` the trailing-form buffer holds EVERY
    game the team has played -- it is not a subset of the season-to-date
    sample, it IS the season-to-date sample, just run through a different
    aggregation (a percentile of raw average PPG, vs all_play's average of
    weekly rank-shares).  Two different transforms of the identical game
    set are highly correlated, not independent evidence, so crediting both
    in full double-counts the same one or two games -- precisely what the
    owner flagged for early season.

    Returns 0.0 (fully redundant, contributes nothing distinct) while
    ``games_played <= window``, then ramps linearly in the FRACTION of
    played games that sit outside the trailing window: at
    ``games_played = 2*window`` half the window is games season-to-date
    doesn't otherwise emphasize on its own, at ``games_played = 4*window``
    three-quarters is.  Never reaches exactly 1.0 in a finite regular
    season, which is correct -- the two measures never become fully
    unrelated, only decreasingly redundant.

    This is a within-results-bucket reallocation only (see
    ``_effective_weight_vector``): it does not touch how much weight the
    results bucket gets relative to ``team_ros_strength``, only how that
    weight splits internally once earned.
    """
    if games_played <= 0:
        return 0.0
    return max(0.0, 1.0 - float(window) / float(games_played))


def _effective_weight_vector(
    *,
    scored_games: int,
    ros_available: bool,
    available_results: set[str],
    preseason: bool,
    results_only: bool,
    scored_games_max: int | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return the actual component weights plus blend metadata.

    Canonical mode preserves the spec's 30/70 forward/results TARGET while
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
        # ``recent`` is discounted toward the OTHER active results
        # components while its trailing window is redundant with the
        # season-to-date sample it is drawn from (see
        # ``_recent_distinctness``). This is a reallocation WITHIN the
        # results bucket only -- ``results_mass`` itself, and therefore
        # the forward/results split, is untouched by it.
        distinctness = _recent_distinctness(scored_games)
        effective_weight = {
            key: (WEIGHTS[key] * distinctness if key == "recent" else WEIGHTS[key])
            for key in result_keys
        }
        effective_base = sum(effective_weight.values())
        if not effective_base:
            # Only reachable when ``recent`` is the SOLE active result
            # component and fully redundant (games_played <= window) --
            # every other league surface has at least all_play/wl_record
            # too. Fall back to the undiscounted split rather than
            # silently dropping the entire results bucket: a discount
            # that zeroes ALL available evidence is not what "recent is
            # redundant with the other results components" means when
            # there ARE no other results components.
            effective_weight = {key: WEIGHTS[key] for key in result_keys}
            effective_base = result_base
        for key in result_keys:
            applied[key] = results_mass * (effective_weight[key] / effective_base)

    # Preseason suppresses observed results, so publishing last season's
    # game count beside ``resultsEvidence: 0.0`` states a number that is not
    # true of the season being described.
    suppressed = preseason and not results_only
    games_shared = 0 if suppressed else int(scored_games)
    games_max = games_shared if scored_games_max is None or suppressed else int(scored_games_max)

    blend = {
        "forwardWeight": round(forward_mass, 6),
        "resultsWeight": round(results_mass, 6),
        "resultsEvidence": round(evidence, 6),
        "scoredGames": games_shared,
        # A denominator that diverges across teams is the defect this whole
        # gate exists to prevent. Publish it rather than let it be silent.
        "scoredGamesMax": games_max,
        "scoredGamesDiverged": bool(games_max != games_shared),
        "targetForwardWeight": WEIGHTS["team_ros_strength"],
        "targetResultsWeight": sum(WEIGHTS[k] for k in RESULT_COMPONENTS),
    }
    return applied, blend


def _largest_remainder_percents(
    weights: dict[str, float], order: tuple[str, ...]
) -> dict[str, int]:
    """Whole-number percentages that sum to EXACTLY 100.

    Rounding each weight on its own does not: three equal thirds display as
    33 + 33 + 33 = 99, and a methodology line that does not add up reads as
    an error. Floors every share, then hands the leftover points to the
    largest fractional parts (ties broken by ``order``, so it is
    deterministic). ``{}`` when nothing carries weight.
    """
    total = sum(w for w in weights.values() if w > 0)
    if total <= 0:
        return {}
    exact = {k: 100.0 * w / total for k, w in weights.items() if w > 0}
    floors = {k: math.floor(v) for k, v in exact.items()}
    leftover = 100 - sum(floors.values())
    rank = sorted(exact, key=lambda k: (-(exact[k] - floors[k]), order.index(k)))
    for k in rank[:leftover]:
        floors[k] += 1
    return floors


def _methodology(
    active_weights: dict[str, float],
    *,
    preseason: bool,
    results_only: bool,
) -> dict[str, Any]:
    """The methodology a reader is shown, derived from the weights USED.

    ``active_weights`` is the exact vector ``_score_state`` scored with, so
    the displayed formula cannot drift from the calculation: early in the
    season the blend is ROS-heavy and ``recent`` carries no weight, late in
    the season it approaches the 30/70 target, and neither is hard-coded here.
    Every canonical component is listed with a status, so a 0% component is
    explained ("activates after N games") rather than silently omitted.
    ``displayPct`` is the largest-remainder rounding of ``weight`` and always
    sums to 100 when anything is weighted; the page renders it verbatim.
    """
    order = FORWARD_COMPONENTS + RESULT_COMPONENTS
    display = _largest_remainder_percents(
        {k: float(active_weights.get(k, 0.0)) for k in order}, order
    )
    components: list[dict[str, Any]] = []
    for key in order:
        weight = float(active_weights.get(key, 0.0))
        entry: dict[str, Any] = {
            "key": key,
            "group": "forward" if key in FORWARD_COMPONENTS else "results",
            "weight": round(weight, 6),
            "displayPct": display.get(key, 0),
            "status": "active",
            "reason": None,
            "activatesAfterGames": None,
        }
        if weight > 0:
            pass
        elif key in _UNAVAILABLE_CANONICAL_COMPONENTS:
            entry["status"] = "unavailable"
            entry["reason"] = "canonical weekly realized VORP/PAR not yet available"
        elif key == "team_ros_strength" and results_only:
            entry["status"] = "excluded_by_lens"
            entry["reason"] = "results-only lens"
        elif key in RESULT_COMPONENTS and preseason and not results_only:
            entry["status"] = "suppressed"
            entry["reason"] = "no games scored this season yet"
        elif key == "recent" and key in active_weights:
            # Measured, but its trailing window is still the whole season
            # (``_recent_distinctness``): it earns weight once more than
            # ``_RECENT_WINDOW`` games exist.
            entry["status"] = "inactive"
            entry["reason"] = "redundant with season-to-date results until the window diverges"
            entry["activatesAfterGames"] = _RECENT_WINDOW
        else:
            entry["status"] = "unavailable"
            entry["reason"] = "input unavailable"
        components.append(entry)
    forward_pct = sum(c["displayPct"] for c in components if c["group"] == "forward")
    results_pct = sum(c["displayPct"] for c in components if c["group"] == "results")
    return {
        "components": components,
        "forwardDisplayPct": forward_pct,
        "resultsDisplayPct": results_pct,
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


def _load_team_strength_rows(
    snapshot: PublicLeagueSnapshot | None = None,
    league_key: str | None = None,
) -> list[dict[str, Any]]:
    """Team-strength rows for the current league.

    Delegates to ``team_strength.load_or_compute_team_strength``, which
    reads the persisted ``data/ros/team_strength/<leagueKey>.json`` when
    present and fresh, and otherwise computes it LIVE from ``snapshot``
    (no network) or, failing that, from a cached Sleeper overlay fetch —
    closing the single point of failure where this component went dark
    for a full refresh cycle whenever the scheduled scrape's write step
    hadn't run.  Returns [] only when every tier is genuinely unable to
    answer.

    ``league_key`` is required for correctness on a non-default league:
    without it, every league collapses onto the SAME persisted snapshot
    file (``_team_strength_path(None)``), so a caller with a snapshot in
    scope must resolve and pass its own key rather than rely on this
    function to guess one.
    """
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    return load_or_compute_team_strength(league_key, snapshot=snapshot) or []


def _load_team_strength_percentiles(
    snapshot: PublicLeagueSnapshot | None = None,
    league_key: str | None = None,
) -> dict[str, float]:
    """Convert team-strength composite to a percentile per ownerId.
    Empty dict when no snapshot — caller renormalises weights.
    """
    rows = _load_team_strength_rows(snapshot, league_key)
    scores: list[tuple[str, float]] = []
    for r in rows:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue
        # MISSING IS NEVER ZERO: a row with no strength is left out, so the
        # owner's ROS component is ``None`` and ``_score_state`` renormalises
        # over what IS measured -- never the league's bottom percentile.
        raw = r.get("teamRosStrength")
        if raw is None:
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
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
      2. Only if there is no current roster list at all, owners present in
         the live team-strength snapshot are the first fallback.
      3. Prior-season career history is the final fallback. It never unions
         departed owners into a current-season league table. In production
         ``build_section`` refuses an in-season snapshot whose current roster
         list is empty or short before enumeration, so 2 and 3 are reachable
         only for a snapshot with no current season.

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

    # A current-season roster list is authoritative membership for this
    # CURRENT league ranking -- even when every owner on it is filtered out
    # (orphaned or retired), which is an answer, not an absence.
    # Team-strength/history are fallbacks ONLY when there is no current roster
    # list at all, and ``build_section`` refuses a current season whose roster
    # list is empty or short (``current_season_membership_error``) before it
    # gets here: filtered through a registry built from those same missing
    # rosters, the fallback silently dropped every owner new this season
    # (2026-09-23: 10 of 12, the two 2026 joiners gone).
    if not ordered and (current is None or not (current.rosters or [])):
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
        s = state["season"].get(oid, _EMPTY_SEASON_STATE)
        games = int(s.get("games", 0))
        points = float(s.get("points", 0.0))
        ppg = points / games if games else None
        rb = state["recent"].get(oid, [])
        recent = sum(rb) / len(rb) if rb else None
        computed_wl = float(s.get("wins", 0.0)) / games if games else None
        wl = official_record.get(oid, computed_wl)
        all_play = state["allplay"].get(oid)
        outcomes = (state.get("outcomes") or {}).get(oid, [])
        streak = _streak_score_from_outcomes(outcomes)
        expected_total = float((state.get("expected") or {}).get(oid, 0.0))
        luck_delta = (float(s.get("wins", 0.0)) - expected_total) / games if games else 0.0
        luck_score = max(0.0, min(1.0, 0.5 - luck_delta))
        inputs[oid] = {
            "games_used": games,
            "recent_games_used": len(rb),
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
    else:
        ros_missing = sorted(o for o in owner_ids if o not in ros_pct)
        if ros_missing:
            # Measured for the league but not for these owners: their ROS
            # component is ``None`` and their score renormalises over what
            # IS measured. Named, so it can never pass for a full table.
            missing_inputs.append(
                f"team_ros_strength (unavailable for {len(ros_missing)} owner(s): "
                f"{', '.join(ros_missing)})"
            )
    if not all_play_available:
        missing_inputs.append("all_play")
    if not recent_available:
        missing_inputs.append("recent")
    if not wl_available:
        missing_inputs.append("wl_record")
    missing_inputs.append(
        "team_vorp (canonical weekly realized VORP/PAR unavailable; not substituted)"
    )

    scored_games, scored_games_max = _scored_game_span(state)
    if scored_games_max != scored_games:
        LOG.warning(
            "[power_v2] scored-game denominators diverge across owners "
            "(shared=%s, max=%s) — averages are not comparable across rows",
            scored_games,
            scored_games_max,
        )
    active_weights, blend = _effective_weight_vector(
        scored_games=scored_games,
        scored_games_max=scored_games_max,
        ros_available=ros_available,
        available_results=available_results,
        preseason=preseason,
        results_only=results_only,
    )

    # Canonical preseason intentionally suppresses the previous season's
    # results. Results-only keeps them because retrospective performance is
    # the explicit subject of that diagnostic lens.
    suppressed_results = preseason and not results_only

    def _row_denominators(oid: str) -> dict[str, int]:
        """Per-row game counts, so an average can never hide its divisor.

        ``i["games_used"]`` and ``i["recent_games_used"]`` are already
        guaranteed real, non-None ints at their source (``int(s.get(...,
        0))`` and ``len(rb)`` respectively in the loop above) -- 0 there
        means "genuinely no games", never "missing". An ``or 0`` here would
        not be a fallback for anything that can actually happen; it would
        only be a decision-coercion pattern with nothing behind it
        (`scripts/check_decision_coercions.py`), so it is not written.
        """
        if suppressed_results:
            return {"gamesUsed": 0, "recentGamesUsed": 0}
        i = inputs[oid]
        return {
            "gamesUsed": int(i["games_used"]),
            "recentGamesUsed": int(i["recent_games_used"]),
        }

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
            # TODO(power-vorp): the canonical weekly realized VORP/PAR feed
            # does not exist yet, so this component is unavailable rather than
            # zero. `_effective_weight_vector` redistributes its 15% across the
            # components that ARE measurable — deliberate interim behavior, not
            # a bug: scoring a team at 0 for a quantity nobody measured would
            # punish every team equally and still be a fabricated number. This
            # is the one open dependency of the Power blend. When the feed
            # lands, populate this key; the weighting needs no change.
            "team_vorp": None,
            "wl_record": None if suppressed_results else i["wl_record"],
            # Display-only diagnostics. None of these keys appears in WEIGHTS.
            "ppg": (
                None
                if suppressed_results or i["ppg"] is None
                else _percentile(ppg_values, i["ppg"])
            ),
            "streak": None if suppressed_results else i["streak"],
            "luck_regression": None if suppressed_results else i["luck_regression"],
            # These three carried no suppression guard, unlike their
            # neighbours above. The ``continue`` in the state builder fires
            # BEFORE the per-season resets, so in a true preseason the state
            # still holds the last season that had data — and last season's
            # PPG was published in a column labelled neither "last season"
            # nor anything else.
            "pointsPerGame": None if suppressed_results else i["ppg"],
            "recentAvg": None if suppressed_results else recent_value,
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
                    **_row_denominators(oid),
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
                **_row_denominators(oid),
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

    _attach_component_ranks(scored_rows + refused, active_weights)

    return scored_rows + refused, missing_inputs, active_weights, blend


def _attach_component_ranks(
    rows: list[dict[str, Any]],
    active_weights: dict[str, float],
) -> None:
    """Stamp each row's per-component rank across the league, in place.

    The reader's question about a Power rank is "which of these five things put
    me here?", and a raw percentile does not answer it — #1 of 12 and #9 of 12
    can sit a few points apart. So publish the sub-rank alongside.

    Derived in the BACKEND on purpose. These are ordinals over a population,
    which is the thing ``CLAUDE.md`` forbids the frontend to compute; the page
    stays a materializer. Only keys that carry weight are ranked — a display
    diagnostic like ``ppg`` is not part of "what put me here".

    A ``None`` component is UNRANKED (absent from the map), never sorted to
    last: a team with no measurement is not the worst team at it.
    """
    for key in active_weights:
        measured = [
            (row, float(row["components"][key]))
            for row in rows
            if (row.get("components") or {}).get(key) is not None
        ]
        if not measured:
            continue
        # Higher component percentile is better, so descending. Same standard
        # competition ranking the overall rank uses (1, 1, 3), with ownerId as
        # the deterministic in-group tiebreak only.
        measured.sort(key=lambda item: (-item[1], str(item[0].get("ownerId"))))
        prior_value: float | None = None
        prior_rank: int | None = None
        for position, (row, value) in enumerate(measured, start=1):
            if prior_value is not None and value == prior_value:
                rank = prior_rank
            else:
                rank = position
                prior_rank = position
                prior_value = value
            row.setdefault("componentRanks", {})[key] = rank


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


def _refused_section(
    *,
    lens: str,
    requested_lens: str,
    preseason: bool,
    as_of_season: str | None,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    """The section shape for "the inputs cannot support a ranking".

    ``currentRanking`` is empty and ``unrankable`` names why, so the page
    renders an explicit refusal instead of a partial table, the publisher
    (``src/ros/scrape.py``) skips it, and nothing downstream can mistake it
    for a real week. ``asOfWeek`` is ``None`` -- unknown -- never 0, which
    would claim "preseason" and turn every movement into NEW.
    """
    return {
        "currentRanking": [],
        "lens": lens,
        "requestedLens": requested_lens,
        "methodologyVersion": METHODOLOGY_VERSION,
        "unrankable": {
            "reason": reason,
            "missingInputs": [detail],
            "explanation": (
                "The league snapshot is incomplete for the current season, so Power "
                "withholds the ranking instead of publishing a partial or "
                "prior-season table."
            ),
        },
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
        "missingInputs": [detail],
        "rosTeamStrengthAvailable": False,
        "preseason": preseason,
        "asOfSeason": as_of_season,
        "asOfWeek": None,
        "expectedTeamCount": None,
        "rankingComplete": False,
        "officialSnapshot": None,
    }


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
    # Resolved independently of the LATER `league_key` resolution below
    # (which is gated on `not results_only and as_of_season` for the
    # movement/snapshot-history lookup and must keep that exact gating
    # untouched): team-strength rows are roster-derived and therefore
    # leagueKey-scoped by this platform's own invariant, and this needs
    # the key unconditionally whenever `results_only` is False, before
    # `as_of_season` even exists.  Resolving no key here silently
    # collapsed every league's Power Rankings onto ONE shared
    # `team_strength/latest.json` file.
    team_strength_league_key = None
    if not results_only:
        from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

        team_strength_league_key = resolve_snapshot_league_key(snapshot)
    team_strength_rows = (
        [] if results_only else _load_team_strength_rows(snapshot, team_strength_league_key)
    )
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
    recent_window: dict[str, list[float]] = defaultdict(list)
    last_season_allplay_share: dict[str, float] = {}
    allplay_share_total: dict[str, float] = defaultdict(float)
    season_outcomes: dict[str, list[float]] = defaultdict(list)
    expected_share_total: dict[str, float] = defaultdict(float)
    week_states: list[tuple[str, int, dict[str, Any]]] = []
    scored_week_by_season: dict[str, int] = {}
    # Reassigned per scored season, so these end up describing the newest
    # season that produced scores — the same one ``final_state`` describes.
    counted_weeks: list[int] = []
    partial_weeks: list[dict[str, Any]] = []
    # Which season the accumulators above currently describe. A season with
    # no resolvable scores ``continue``s BEFORE the reset below, so without
    # this the "current" state silently stays the previous season's -- see
    # the prior-season guard after this loop.
    state_season_label: str | None = None

    for season in seasons_sorted:
        week_scores = luck._season_weekly_scores(season, registry)
        if not week_scores:
            continue

        counted_weeks = sorted(week_scores.keys())
        partial_weeks = []
        state_season_label = str(season.season)

        season_state = defaultdict(lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0})
        recent_window = defaultdict(list)
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

            # The completed-week gate cannot close an odd/bye/unresolved-owner
            # shortfall inside a week it admitted. Say so out loud instead of
            # letting one short week quietly shrink somebody's denominator.
            # ``season.num_teams`` is typed -> int and already falls back to
            # ``len(rosters)`` internally (SeasonSnapshot.num_teams) -- an
            # ``or 0`` here would coerce nothing real, so it is not written.
            expected_rosters = season.num_teams
            if expected_rosters and len(scores) != expected_rosters:
                partial_weeks.append(
                    {
                        "week": int(wk),
                        "observed": len(scores),
                        "expected": expected_rosters,
                    }
                )
                LOG.warning(
                    "[power_v2] %s week %s counted %s scored owners, expected %s",
                    season.season,
                    wk,
                    len(scores),
                    expected_rosters,
                )

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
                recent_window[oid] = list(recent)

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
                        "season": {o: dict(v) for o, v in season_state.items()},
                        "recent": {o: list(v) for o, v in recent_window.items()},
                        "allplay": dict(last_season_allplay_share),
                        "expected": dict(expected_share_total),
                        "outcomes": {o: list(v) for o, v in season_outcomes.items()},
                    },
                )
            )

    current_season = snapshot.current_season
    current_label = str(current_season.season) if current_season is not None else None

    # ── Current-season integrity: refuse rather than publish a wrong table ──
    # Both gates exist because the alternative was measured on 2026-09-23: a
    # snapshot whose 2026 rosters failed to fetch ranked the 2025 season's
    # results for 10 of 12 owners, labelled the table "Preseason" and marked
    # every team NEW. A refusal is a true statement about a table we cannot
    # build; a plausible-looking wrong ranking is not.
    membership_error = current_season_membership_error(snapshot)
    if membership_error is not None:
        LOG.warning("[power_v2] refusing to rank: %s", membership_error)
        return _refused_section(
            lens=public_lens,
            requested_lens=requested_lens,
            preseason=preseason,
            as_of_season=current_label,
            reason="current_league_membership_incomplete",
            detail=membership_error,
        )
    host_scored_through = (
        _metrics.last_scored_week(current_season) if current_season is not None else None
    )
    if (
        current_season is not None
        and not current_season.is_complete
        and current_label not in scored_week_by_season
        and (
            (host_scored_through is not None and host_scored_through >= 1)
            or bool(_metrics.final_regular_season_weeks(current_season))
        )
    ):
        detail = f"host reports scored week(s) for {current_label} but none resolved to an owner"
        LOG.warning("[power_v2] refusing to rank: %s", detail)
        return _refused_section(
            lens=public_lens,
            requested_lens=requested_lens,
            preseason=preseason,
            as_of_season=current_label,
            reason="current_season_scores_unresolvable",
            detail=detail,
        )

    # ── No prior-season results in the canonical in-season answer ──
    # In-season with no FINAL week yet (Week 1 in progress: live points make
    # ``_is_preseason`` False, but ``_season_weekly_scores`` admits nothing),
    # the accumulators still hold last season's complete results. Canonical
    # Power answers "what has this team earned THIS season"; the honest
    # answer before any final week is "nothing yet", so results carry no
    # evidence and ROS strength stands alone. Results-only keeps its
    # documented offseason view of the finished year.
    if (
        not results_only
        and not preseason
        and current_label is not None
        and state_season_label != current_label
    ):
        season_state = defaultdict(lambda: {"points": 0.0, "games": 0, "wins": 0.0, "losses": 0.0})
        recent_window = defaultdict(list)
        last_season_allplay_share = {}
        season_outcomes = defaultdict(list)
        expected_share_total = defaultdict(float)
        counted_weeks = []
        partial_weeks = []

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

    ros_pct = (
        {} if results_only else _load_team_strength_percentiles(snapshot, team_strength_league_key)
    )
    ros_available = bool(ros_pct)
    final_state = {
        "season": season_state,
        "recent": recent_window,
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
            current = season_state.get(row["ownerId"], _EMPTY_SEASON_STATE)
            wins = round(float(current.get("wins", 0.0)))
            games = int(current.get("games", 0))
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
    median_game_enabled = (
        _metrics.median_game_enabled(current_season) if current_season is not None else None
    )

    # Canonical week-over-week movement is compared only with exactly Week
    # N-1's immutable official publication. It never diffs two recalculations
    # from the same week.
    official_snapshot = None
    share_snapshot = None
    official_history: list[dict[str, Any]] = []
    league_key = None
    # What the movement arrows were measured against. The frontend keys NEW on
    # it: "no prior publication exists" and "the lookup failed" must not both
    # render as NEW on every row, which is what a swallowed exception or a
    # mis-stamped week 0 used to produce.
    movement_baseline: dict[str, Any] = {
        "status": "unavailable",
        "reason": "results_only lens" if results_only else "no current season",
    }
    if not results_only and as_of_season:
        movement_baseline = {"status": "unavailable", "reason": "league key not resolved"}
        try:
            from src.api.league_registry import league_key_for_sleeper_id  # noqa: PLC0415
            from src.ros import power_snapshots  # noqa: PLC0415

            league_key = league_key_for_sleeper_id(snapshot.root_league_id)
            if league_key:
                # The detailed table may be live, but its comparison anchor is
                # always a published week — never another same-week recalculation.
                # ``>= 0`` so a published PRESEASON (week 0) ranking is found
                # and served like any other official week. Movement itself is
                # still correctly ``None`` there — week 0 has no predecessor,
                # which ``movement_against_previous`` decides, not this guard.
                if as_of_week == 0:
                    movement_baseline = {
                        "status": "not_applicable",
                        "reason": "week 0 (preseason) has no earlier publication",
                    }
                else:
                    baseline = power_snapshots.load_snapshot(
                        league_key, as_of_season, as_of_week - 1
                    )
                    movement_baseline = (
                        {
                            "status": "compared",
                            "week": as_of_week - 1,
                            "preseason": bool(baseline.get("preseason")),
                            "methodologyVersion": baseline.get("methodologyVersion"),
                            "rankSource": power_snapshots.rank_source(baseline),
                            "sameMethodology": (
                                baseline.get("methodologyVersion") == METHODOLOGY_VERSION
                            ),
                        }
                        if baseline is not None
                        else {"status": "no_prior_publication", "week": as_of_week - 1}
                    )
                if as_of_week >= 0:
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
                # Published weeks only, and only this season's. This is the
                # canonical rank history: every point is a week that was
                # actually published, so the chart cannot disagree with the
                # arrows on the share card. Nothing is reconstructed.
                official_history = [
                    {
                        "week": snap.get("week"),
                        "preseason": bool(snap.get("preseason")),
                        "rankSource": power_snapshots.rank_source(snap),
                        "methodologyVersion": snap.get("methodologyVersion"),
                        "ranking": [
                            {
                                "ownerId": r.get("ownerId"),
                                "rank": r.get("rank"),
                                "powerScore": r.get("powerScore"),
                            }
                            for r in (snap.get("ranking") or [])
                        ],
                    }
                    for snap in power_snapshots.season_snapshots(league_key, as_of_season)
                ]
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[power_v2] weekly movement unavailable: %s", exc)
            movement_baseline = {"status": "unavailable", "reason": str(exc)}

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

    # Completeness is stamped, not assumed: the table and the share card both
    # render ``currentRanking``, and a reader must be able to tell "all twelve"
    # from "the ten we could resolve" without counting rows. Expected is the
    # current season's active (non-retired) roster owners; an orphaned or
    # retired-owner roster is counted separately rather than silently.
    expected_team_count: int | None = None
    ranking_complete: bool | None = None
    unowned_rosters: int | None = None
    if current_season is not None:
        active_ids = {m.owner_id for m in registry.ordered_managers()}
        roster_owners = [
            str(r.get("owner_id") or "").strip() for r in (current_season.rosters or [])
        ]
        expected_ids = {oid for oid in roster_owners if oid in active_ids}
        expected_team_count = len(expected_ids)
        unowned_rosters = sum(1 for oid in roster_owners if oid not in active_ids)
        ranked_ids = {str(r.get("ownerId")) for r in rankings if r.get("rank") is not None}
        ranking_complete = (
            unrankable is None
            and len(rankings) == expected_team_count
            and ranked_ids == expected_ids
        )

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
        "methodology": _methodology(active_weights, preseason=preseason, results_only=results_only),
        "blend": dict(blend),
        # Tri-state: whether RECORD reflects a league-average ("median")
        # game alongside real H2H, which is why it can differ from
        # countedWeeks/gamesUsed by design rather than by defect. None
        # means unverified -- never coerced to "off".
        "medianGameEnabled": median_game_enabled,
        # The exact weeks behind every average on this payload.
        "countedWeeks": list(counted_weeks),
        "partialWeeks": [dict(w) for w in partial_weeks],
        "missingInputs": sorted(missing_inputs),
        "rosTeamStrengthAvailable": ros_available,
        "preseason": preseason,
        "asOfSeason": as_of_season,
        "asOfWeek": as_of_week,
        "leagueKey": league_key,
        "scoringConfigFingerprint": scoring_fingerprint,
        "officialSnapshot": official_snapshot,
        "shareSnapshot": share_snapshot,
        "officialHistory": official_history,
        "movementBaseline": movement_baseline,
        "expectedTeamCount": expected_team_count,
        "rankingComplete": ranking_complete,
        "unownedRosters": unowned_rosters,
    }
