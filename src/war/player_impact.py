"""`C5-WAR-01` deterministic core — Realized Lineup VORP, Actual WAR, Wins
Above Bench, Game Changer Points.

Per `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`. Four of the spec's five metrics
live here; the fifth, **xWAR**, is deliberately excluded — §4 requires
"the same archived no-lookahead league-week scoring distribution /
simulation" that Game Day (`docs/GAME_DAY_PROBABILITY_SPEC.md`) also needs
and which does not exist yet in this codebase. Building a standalone
simulation just for xWAR would be exactly the "second matchup model" the
Game Day spec forbids. Callers needing xWAR must report it unavailable —
never approximate it from these deterministic metrics — until the joint
weekly simulation lands and this module gains a companion.

This module is pure computation over already-extracted primitives (real
per-player weekly points, a league's replacement baseline, a roster pool
for a given week). It does not fetch Sleeper data, does not know about
`PublicLeagueSnapshot`, and does not write anywhere — wiring it to a real
league's history is deliberately left to a consumer-migration follow-up,
the same staged-delivery shape `C5-PROJ-A` used for source acquisition.

Replacement-level consumption: **`src.scoring.replacement_level` is THE
owner** (`scripts/replacement_census.py`'s declared row `B`). This module
never computes its own replacement baseline from raw rows — every function
here takes an already-resolved ``replacement_expectation`` (or accepts
``None`` for "unavailable") so there is exactly one place a replacement
number is derived.

Missing is never zero, everywhere in this module: a ``None`` input for
score/replacement/lineup evidence propagates to a ``None`` (or an explicit
``available: False``) output rather than silently defaulting to 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from src.ros.lineup import LineupAssignment, RosterPlayer, assign_lineup
from src.war.standings import standings_credit


# ── 1. Realized Lineup VORP (spec §2) ───────────────────────────────────


def realized_lineup_vorp(
    actual_points: float | None,
    replacement_expectation: float | None,
) -> float | None:
    """One player-week's VORP.

    ``weeklyVORP = actualCountedPoints - leagueReplacementExpectation``.
    Negative is a valid, real answer per spec §2/§11 — never floored at
    zero. Returns ``None`` (unavailable) only when either input is
    ``None``; a genuinely zero replacement baseline or a genuinely zero
    score are real numbers, not missing evidence.
    """
    if actual_points is None or replacement_expectation is None:
        return None
    return actual_points - replacement_expectation


def non_counted_week_vorp() -> float:
    """A best-ball-non-counted player-week contributes exactly 0.0 realized
    lineup impact (spec §2, §11) — a KNOWN fact, not missing evidence.
    Named so a caller never has to remember which of the two "0" cases
    this is; contrast with :func:`realized_lineup_vorp` returning ``None``
    for genuinely missing evidence.
    """
    return 0.0


@dataclass(frozen=True)
class SeasonTotal:
    """A summed metric across a season's weeks, with its own coverage
    state carried alongside the number — a season total computed from 12
    of 14 known weeks is a different claim than one computed from 14 of
    14, and this type keeps that claim from being silently discarded.
    """

    total: float
    weeks_known: int
    weeks_missing: int

    @property
    def complete(self) -> bool:
        return self.weeks_missing == 0


def season_total(weekly_values: Iterable[float | None]) -> SeasonTotal:
    """Sum a season's worth of weekly VORP/WAR/WAB values, tracking how
    many weeks actually had evidence. ``None`` weeks are excluded from
    the sum (never coerced to 0.0) and counted in ``weeks_missing``.
    """
    known = 0
    missing = 0
    running = 0.0
    for value in weekly_values:
        if value is None:
            missing += 1
            continue
        known += 1
        running += value
    return SeasonTotal(total=running, weeks_known=known, weeks_missing=missing)


# ── 2. Actual WAR (spec §3) ──────────────────────────────────────────────


@dataclass(frozen=True)
class ActualWarResult:
    """One player-week's Actual WAR, with the intermediate counterfactual
    values preserved — §10's historical contract asks for the actual and
    counterfactual states, not only the final delta, so callers building
    that record do not have to recompute what this function already knew.
    """

    counterfactual_team_score: float
    actual_credit: float
    counterfactual_credit: float
    weekly_war: float


def actual_war_for_week(
    *,
    actual_team_score: float,
    player_points: float,
    replacement_expectation: float | None,
    opponent_score: float,
    all_scores_this_week: Sequence[float],
    median_enabled: bool,
) -> ActualWarResult | None:
    """One player-week's Actual WAR.

    ``counterfactualTeamScore = actualTeamScore - playerActualPoints +
    leagueReplacementExpectation`` (spec §3), then both the actual and
    counterfactual scores are run through the SAME standings-credit rule
    so the delta is leverage-sensitive rather than a raw point swing.

    **The median is recalculated from the counterfactual score set**
    (spec §3's own "Mandatory" instruction) — this function replaces this
    team's entry in ``all_scores_this_week`` with the counterfactual
    total before computing the counterfactual credit; it does NOT reuse
    the actual week's median. ``all_scores_this_week`` must include
    ``actual_team_score`` among its entries (the caller's own score,
    exactly once) — this function locates and replaces it in the
    counterfactual pass; if it cannot be found, the counterfactual median
    would silently omit the team, which would be worse than refusing, so
    this returns ``None`` for the whole week's result instead.

    Returns ``None`` (unavailable) when ``replacement_expectation`` is
    ``None`` or ``actual_team_score`` cannot be located in
    ``all_scores_this_week`` — this is a whole-week refusal, not a
    zero-WAR week, per "missing is never zero."
    """
    if replacement_expectation is None:
        return None
    if actual_team_score not in all_scores_this_week:
        return None

    counterfactual_team_score = actual_team_score - player_points + replacement_expectation

    actual_credit = standings_credit(
        actual_team_score,
        opponent_score,
        all_scores_this_week,
        median_enabled=median_enabled,
    )

    counterfactual_scores = list(all_scores_this_week)
    counterfactual_scores[counterfactual_scores.index(actual_team_score)] = (
        counterfactual_team_score
    )
    counterfactual_credit = standings_credit(
        counterfactual_team_score,
        opponent_score,
        counterfactual_scores,
        median_enabled=median_enabled,
    )

    return ActualWarResult(
        counterfactual_team_score=counterfactual_team_score,
        actual_credit=actual_credit,
        counterfactual_credit=counterfactual_credit,
        weekly_war=actual_credit - counterfactual_credit,
    )


# ── 3. Wins Above Bench + Game Changer Points (spec §5, §6) ─────────────


@dataclass(frozen=True)
class RemoveAndResolveResult:
    """The shared remove-and-re-solve primitive both WAB and Game Changer
    Points are built from (spec §6: "must reuse the exact same
    remove-and-re-solve primitive... do not implement separate Game
    Changer math"). One solve produces everything both metrics need.
    """

    with_player_assignment: LineupAssignment
    with_player_score: float
    without_player_assignment: LineupAssignment
    without_player_score: float
    game_changer_points: float


def _team_score_for_assignment(
    assignment: LineupAssignment, points_by_id: Mapping[str, float]
) -> float:
    """Sum of REAL points for the players an assignment started.

    Deliberately not ``assignment.score`` — that property runs the
    solver's own health-penalty objective (``max(0.0, ros_value)`` for a
    non-injured player), which would silently floor a legitimately
    negative historical score. A team's actual weekly total must be the
    real sum, floor or no floor.
    """
    return sum(points_by_id[p.player_id] for p in assignment.assignments.values())


def remove_and_resolve(
    *,
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    remove_player_id: str,
    points_by_id: Mapping[str, float],
    slot_eligibility: Mapping[str, "Sequence[str]"] | None = None,
) -> RemoveAndResolveResult:
    """Re-solve the exact best-ball lineup with and without one player.

    ``pool`` must already carry each player's REAL score for the week as
    ``ros_value`` — this function does not know about projections, only
    about the objective it is handed. ``injured``/``bye`` on every
    ``RosterPlayer`` in ``pool`` must already be ``False`` for a
    historical week (the caller's responsibility): the solver applies a
    live-state health penalty to those flags, which is the wrong
    adjustment for a week that has already been played.

    Spec §5/§9: flex/superflex/IDP assignments can change when one
    player is removed, so this genuinely re-solves rather than
    substituting "the next player at that position."
    """
    with_assignment = assign_lineup(pool, slots, slot_eligibility=slot_eligibility)
    without_pool = [p for p in pool if p.player_id != remove_player_id]
    without_assignment = assign_lineup(without_pool, slots, slot_eligibility=slot_eligibility)

    with_score = _team_score_for_assignment(with_assignment, points_by_id)
    without_score = _team_score_for_assignment(without_assignment, points_by_id)

    return RemoveAndResolveResult(
        with_player_assignment=with_assignment,
        with_player_score=with_score,
        without_player_assignment=without_assignment,
        without_player_score=without_score,
        game_changer_points=with_score - without_score,
    )


@dataclass(frozen=True)
class WabResult:
    with_player_score: float
    without_player_score: float
    game_changer_points: float
    with_player_credit: float
    without_player_credit: float
    weekly_wab: float


def wins_above_bench_for_week(
    *,
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    remove_player_id: str,
    points_by_id: Mapping[str, float],
    opponent_score: float,
    all_scores_this_week: Sequence[float],
    median_enabled: bool,
    slot_eligibility: Mapping[str, "Sequence[str]"] | None = None,
) -> WabResult | None:
    """One player-week's Wins Above Bench.

    "If this fantasy team did not have this player, what would actually
    have happened?" (spec §1) — remove the player, re-solve the whole
    legal lineup with everyone else's REAL scores, recompute standings
    credit (including the median, recalculated the same way Actual WAR
    recalculates it), and take the delta.

    Same not-found refusal as :func:`actual_war_for_week`: if the
    team's WITH-player score cannot be located in
    ``all_scores_this_week`` for the median recalculation, this returns
    ``None`` for the whole week rather than silently using a stale
    median.
    """
    solved = remove_and_resolve(
        pool=pool,
        slots=slots,
        remove_player_id=remove_player_id,
        points_by_id=points_by_id,
        slot_eligibility=slot_eligibility,
    )
    if solved.with_player_score not in all_scores_this_week:
        return None

    with_credit = standings_credit(
        solved.with_player_score,
        opponent_score,
        all_scores_this_week,
        median_enabled=median_enabled,
    )

    without_scores = list(all_scores_this_week)
    without_scores[without_scores.index(solved.with_player_score)] = solved.without_player_score
    without_credit = standings_credit(
        solved.without_player_score,
        opponent_score,
        without_scores,
        median_enabled=median_enabled,
    )

    return WabResult(
        with_player_score=solved.with_player_score,
        without_player_score=solved.without_player_score,
        game_changer_points=solved.game_changer_points,
        with_player_credit=with_credit,
        without_player_credit=without_credit,
        weekly_wab=with_credit - without_credit,
    )
