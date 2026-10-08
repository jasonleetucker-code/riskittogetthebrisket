"""Player Impact — the C5-WAR-01 deterministic core.

Realized Lineup VORP, Actual WAR, Wins Above Bench (WAB) and Game Changer
Points per player-week, attributed per ``(player, franchise, week)``, per
``docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`` (§1-§6, §10-§12).  xWAR (§4) is NOT
computed here: it needs an archived no-lookahead league-week distribution
that does not exist for historical weeks, and the spec makes it
unavailable by default rather than reconstructed.  Every payload says so.

This module is the ONE owner of the player-impact calculation.  It owns no
second copy of anything it needs:

==========================  ==============================================
concept                     canonical owner consumed
==========================  ==============================================
"which weeks are finished"  ``metrics.final_weeks`` (in-progress weeks are
                            absent, never partially counted)
median game on/off          ``metrics.median_game_enabled`` (tri-state)
median threshold + its      ``ros.game_day_sim.median_threshold`` /
host-verification status    ``THRESHOLD_SEMANTICS`` /
                            ``THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES``
H2H credit / tie credit     ``schedule_impact.comparison_credit``
who played whom / byes      ``schedule_impact.week_matchup_structure``
starter slots               ``ros.lineup.resolve_starter_slots``
best-ball re-solve          ``ros.lineup.solve_optimal_assignment`` with
                            ``OBJECTIVE_REALIZED_POINTS`` (exact; negative
                            realized points are never floored)
positional demand           ``league_intel.replacement.measure_endogenous_starters``
                            run on each finished week's REAL scores
replacement points/game     ``scoring.replacement_level.replacement_per_game``
                            (``require_full_band=True``: a thin band is
                            UNAVAILABLE, never a self-referential number)
==========================  ==============================================

Definitions (spec wording, made executable)
───────────────────────────────────────────
* **counted** — the player is in the host's final counted lineup that week
  (Sleeper ``starters``; in a best-ball league that IS the optimal lineup,
  and the WAB path re-proves it by reproducing the host score exactly).
* ``weeklyVORP = countedPoints - R(position)``; non-counted weeks are a
  KNOWN 0, never missing.  Negative is valid.
* ``weeklyWAR = credits(actual) - credits(counterfactual)`` where
  ``counterfactual = teamScore - playerPoints + R(position)`` — a
  league-replacement substitution, never the owner's bench (spec §1).  The
  league median is RECOMPUTED with this team's score replaced, located by
  roster id, never by matching a score value (§3, §12).
* ``weeklyWAB`` — remove the player, re-solve the complete legal best-ball
  lineup from every other rostered player's real score, recompute
  H2H + median (§5).  ``GameChangerPoints = teamScore - scoreWithout``
  (§6) comes from the same solve.
* credits = H2H credit (when the team had a game) + median credit (when the
  league runs one).  Ties are the canonical half credit.

Settings that contradict the matchups fail closed.  Sleeper keeps one
league object per season with its FINAL settings; a week whose starters
count or lineups contradict it (``detect_contradictions``) is withheld
entirely and the season is stamped ``contradicted_settings``.

Missing is never zero.  Every unknowable quantity is ``None`` with a named
reason; a season total sums only KNOWN weeks and publishes its coverage.

Labelled PRIORS (definitional choices the spec leaves open; see
``PRIORS`` — surfaced in every payload):

* replacement is a SEASON-TO-DATE level per position over the window's
  finished regular-season weeks (stamped ``asOfWeek``), not a per-week one
  -- it therefore uses LATER weeks (``replacementTemporalScope``);
* the starter cutoff is the MEASURED league demand (players started per
  week, from the exact solver over real weekly scores); the band is the
  owner's default 5 just below it;
* scope is regular-season weeks (standings credits); playoffs are excluded;
* a 0.00 week is not a game in the replacement pace (the host does not
  distinguish a bye/inactive week from a scoreless game);
* positions/eligibility come from the host's current player directory;
* odd-team median threshold semantics are unverified upstream (the
  canonical Game Day flag) and are stamped, not hidden.

Attribution limits (spec §11): leave-one-out impacts are not additive
shares of team wins; two players can each be necessary to one win.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.league_intel.replacement import measure_endogenous_starters
from src.ros.game_day_sim import (
    THRESHOLD_SEMANTICS,
    THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES,
    median_threshold,
)
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    precompute_slot_eligibility,
    resolve_starter_slots,
    solve_optimal_assignment,
)
from src.scoring.replacement_level import replacement_per_game

from . import metrics
from .schedule_impact import comparison_credit, week_matchup_structure
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

CALC_VERSION = "player-impact-2026.10-c5war01-core-v1"
CONTRACT_VERSION = "player-impact/2026-10-07.v1"

#: Owner default band below the cutoff (``replacement_per_game``'s default).
REPLACEMENT_BAND_SIZE = 5

#: Host scores are hundredths; comparisons are made on thousandths so a
#: median of two hundredths (which can end in 5) compares exactly.
_QUANTUM = 1000

# ── unavailable reasons ────────────────────────────────────────────────
R_TEAM_SCORE_MISSING = "team_score_missing"
R_LINEUP_MISSING = "counted_lineup_missing"
R_COUNTED_SCORE_MISSING = "counted_player_score_missing"
R_TEAM_SCORE_MISMATCH = "team_score_does_not_match_counted_players"
R_POSITION_UNKNOWN = "player_position_unknown"
R_REPLACEMENT_UNAVAILABLE = "replacement_unavailable"
R_OPPONENT_SCORE_MISSING = "opponent_score_missing"
R_MEDIAN_RULE_UNVERIFIED = "median_rule_unverified"
R_LEAGUE_WEEK_INCOMPLETE = "league_week_scores_incomplete"
R_NOT_BEST_BALL = "wab_requires_best_ball"
R_BEST_BALL_UNVERIFIED = "best_ball_rule_unverified"
R_SLOTS_UNKNOWN = "starter_slots_unknown"
R_ROSTER_SCORES_INCOMPLETE = "roster_scores_incomplete"
R_LINEUP_NOT_REPRODUCED = "host_lineup_not_reproduced"
R_COUNTERFACTUAL_INFEASIBLE = "counterfactual_lineup_infeasible"
R_INVARIANT_VIOLATED = "remove_and_reoptimize_invariant_violated"
R_MATCHUP_STRUCTURE = "matchup_structure_unresolved"
R_CONTRADICTED_SETTINGS = "contradicted_settings"

#: Week-level contradictions between the season's league object (Sleeper
#: stores the season's FINAL settings) and what its matchups actually show.
CONTRA_SLOT_COUNT = "starter_count_differs_from_configured_slots"
CONTRA_BEST_BALL = "best_ball_flag_contradicted_by_host_lineups"
SETTINGS_CONSISTENT = "consistent"
SETTINGS_CONTRADICTED = "contradicted_settings"

_METRICS = ("vorp", "war", "wab", "gameChangerPoints")

#: Replacement-level reasons (per position).
REPL_INSUFFICIENT_BAND = "insufficient_replacement_band"
REPL_NO_DEMAND = "position_not_started"
REPL_NO_SLOTS = "starter_slots_unknown"
REPL_NO_WEEKS = "no_finished_weeks"
REPL_CONTRADICTED = "contradicted_settings"

PRIORS: tuple[dict[str, str], ...] = (
    {
        "id": "replacement_season_to_date",
        "choice": "One replacement level per position over the window's finished "
        "regular-season weeks (asOfWeek stamped), not a per-week level.",
        "why": "Spec §1 allows 'the relevant week/season context'; a one-week band is "
        "dominated by noise.",
        "temporalScope": "Uses LATER finished weeks of the same season: not a "
        "no-lookahead value (spec §10/§12 temporal-leakage item stays open).",
    },
    {
        "id": "zero_week_not_a_game",
        "choice": "A 0.00 week is not counted as a game in the replacement pace.",
        "why": "The host records NFL byes and inactive weeks as 0.0, indistinguishable "
        "from a scoreless game; the owner defines pace per game played.",
    },
    {
        "id": "replacement_cutoff_measured_demand",
        "choice": "Cutoff = league players started per week at the position, measured "
        "by the exact solver over each finished week's real scores; band = owner "
        "default (5) just below it.",
        "why": "Spec §1: robust marginal band around the league-demand cutoff, from "
        "actual scoring, lineup rules, size and flex/superflex/IDP demand.",
    },
    {
        "id": "regular_season_scope",
        "choice": "Only finished regular-season weeks; playoff weeks are excluded.",
        "why": "WAR/WAB are standings-win credits; playoff games award none.",
    },
    {
        "id": "current_player_directory",
        "choice": "Position and slot eligibility come from the host's current player "
        "directory, not an as-of copy.",
        "why": "No as-of eligibility archive exists; a reproduced host score guards WAB.",
    },
    {
        "id": "median_threshold_semantics",
        "choice": "League-median threshold = canonical Game Day semantics; verified for "
        "even-sized leagues only, stamped per payload.",
        "why": "Host documentation covers the middle-two average; odd sizes unverified.",
    },
)


# ── inputs ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlayerInfo:
    """What the solver and the replacement owner need about one player.

    ``position`` is the replacement bucket (base family, e.g. ``DL``);
    ``host_position`` / ``fantasy_positions`` are slot eligibility.
    """

    position: str
    host_position: str = ""
    fantasy_positions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamWeek:
    """One franchise's finished week, exactly as the host recorded it."""

    roster_id: int
    owner_id: str
    #: The host's official team score; ``None`` = unknown (never 0).
    score: float | None
    #: The host's counted lineup (player ids, empty slots removed).
    counted: tuple[str, ...]
    #: Every rostered player's realized points that week.
    points: Mapping[str, float]
    #: Every rostered player id that week (counted or not).
    roster: tuple[str, ...]
    #: H2H opponent's roster id; ``None`` = no head-to-head game.
    opponent: int | None
    #: Why the H2H game could not be established (``unpaired`` /
    #: ``group_size`` / ``unscored``); ``None`` = a real game or a real bye.
    matchup_issue: str | None = None
    #: Length of the host's raw ``starters`` array (empty slots included);
    #: ``None`` = not reported.  Compared with the configured slot count.
    lineup_size: int | None = None


@dataclass(frozen=True)
class WeekRules:
    starter_slots: tuple[str, ...]
    best_ball: bool | None
    median_enabled: bool | None


# ── standings credits ──────────────────────────────────────────────────
def _q(value: float) -> int:
    return int(round(float(value) * _QUANTUM))


def _r2(value: float) -> float:
    return round(float(value) + 0.0, 2)


@dataclass(frozen=True)
class Outcome:
    """Standings credits for one team-week under one team score."""

    score: float
    h2h: float | None
    median: float | None
    median_threshold: float | None


def team_outcome(
    roster_id: int,
    score: float,
    league_scores: Mapping[int, float],
    opponent: int | None,
    median_enabled: bool | None,
) -> Outcome:
    """Credits for ``roster_id`` posting ``score``, every other team fixed.

    The median is computed from ``league_scores`` with THIS team's entry
    replaced by ``score`` — located by roster id, never by score value —
    so a counterfactual can move the median (spec §3 "Mandatory").
    ``median_enabled`` must be ``True`` for a median credit; ``False`` and
    ``None`` both yield no median credit, and the caller distinguishes them.
    """
    h2h: float | None = None
    if opponent is not None and opponent in league_scores:
        h2h = comparison_credit(_q(score), _q(league_scores[opponent]))
    median: float | None = None
    threshold: float | None = None
    if median_enabled is True:
        pool = dict(league_scores)
        pool[roster_id] = score
        threshold = float(median_threshold([_q(v) for v in pool.values()]))
        median = comparison_credit(_q(score), threshold)
        threshold = threshold / _QUANTUM
    return Outcome(score=_r2(score), h2h=h2h, median=median, median_threshold=threshold)


@dataclass(frozen=True)
class CreditDelta:
    """``actual - counterfactual`` standings credits, by component."""

    actual: Outcome
    counterfactual: Outcome
    h2h_delta: float | None
    median_delta: float | None
    total: float | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "actualScore": self.actual.score,
            "counterfactualScore": self.counterfactual.score,
            "h2h": {"actual": self.actual.h2h, "counterfactual": self.counterfactual.h2h},
            "median": {
                "actual": self.actual.median,
                "counterfactual": self.counterfactual.median,
                "actualThreshold": self.actual.median_threshold,
                "counterfactualThreshold": self.counterfactual.median_threshold,
            },
            "h2hDelta": self.h2h_delta,
            "medianDelta": self.median_delta,
            "total": self.total,
            "reason": self.reason,
        }


def credit_delta(
    team: TeamWeek,
    counterfactual_score: float,
    league_scores: Mapping[int, float],
    *,
    median_enabled: bool | None,
    league_week_complete: bool,
) -> CreditDelta:
    actual_score = float(team.score)  # caller guarantees known
    actual = team_outcome(
        team.roster_id, actual_score, league_scores, team.opponent, median_enabled
    )
    cf = team_outcome(
        team.roster_id, counterfactual_score, league_scores, team.opponent, median_enabled
    )
    reason: str | None = None
    h2h_delta: float | None
    if team.matchup_issue is not None:
        h2h_delta = None  # a broken matchup group is unknown, never a bye
        reason = R_MATCHUP_STRUCTURE
    elif team.opponent is None:
        h2h_delta = 0.0  # no game -> no H2H credit in either world (a bye)
    elif actual.h2h is None:
        h2h_delta = None
        reason = R_OPPONENT_SCORE_MISSING
    else:
        h2h_delta = float(actual.h2h) - float(cf.h2h)
    median_delta: float | None
    if median_enabled is False:
        median_delta = 0.0
    elif median_enabled is None:
        median_delta = None
        reason = reason or R_MEDIAN_RULE_UNVERIFIED
    elif not league_week_complete:
        median_delta = None
        reason = reason or R_LEAGUE_WEEK_INCOMPLETE
    else:
        median_delta = float(actual.median) - float(cf.median)
    total = None if h2h_delta is None or median_delta is None else h2h_delta + median_delta
    return CreditDelta(
        actual=actual,
        counterfactual=cf,
        h2h_delta=h2h_delta,
        median_delta=median_delta,
        total=total,
        reason=reason,
    )


# ── the remove-and-re-solve primitive (WAB + Game Changer) ─────────────
def _pool(team: TeamWeek, players: Mapping[str, PlayerInfo]) -> list[RosterPlayer]:
    out = []
    for pid in sorted(set(team.roster) | set(team.counted)):
        info = players.get(pid) or PlayerInfo(position="")
        out.append(
            RosterPlayer(
                player_id=pid,
                canonical_name="",
                position=info.host_position or info.position,
                ros_value=team.points.get(pid),
                fantasy_positions=info.fantasy_positions,
            )
        )
    return out


def _solve(pool: list[RosterPlayer], slots: list[str], elig) -> tuple[float, int]:
    assignment = solve_optimal_assignment(
        pool, slots, precomputed_eligibility=elig, objective=OBJECTIVE_REALIZED_POINTS
    )
    score = sum(float(p.ros_value) for p in assignment.values())
    return _r2(score), len(slots) - len(assignment)


# ── one league-week ────────────────────────────────────────────────────
def _unavailable(reason: str) -> dict[str, Any]:
    return {"value": None, "reason": reason}


def evaluate_league_week(
    week: int,
    teams: Sequence[TeamWeek],
    rules: WeekRules,
    players: Mapping[str, PlayerInfo],
    replacement: Mapping[str, float | None],
    *,
    expected_team_count: int | None,
    contradictions: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Every rostered player-week's impact for one finished league-week.

    ``expected_team_count`` is the league's size from the host (``None`` when
    the host states none).  The week counts as a COMPLETE league-week — the
    precondition for recomputing the median — only when every expected team
    has a row AND a known score.  Counting only the rows that happen to be
    present would quietly take the median over a partial league; an unknown
    size withholds the median rather than trusting the rows.

    Returns one record per ``(player, roster)`` rostered that week.  Pure:
    same inputs, same output, in a deterministic order.

    ``contradictions`` (from :func:`detect_contradictions`) FAILS THE WEEK
    CLOSED: when the league object's settings disagree with what the week's
    matchups show, no slot layout or lineup rule can be trusted, so every
    metric is unavailable with ``contradicted_settings`` — never computed
    on the wrong layout and never stamped complete.
    """
    if contradictions:
        return [
            {
                "week": week,
                "playerId": pid,
                "rosterId": team.roster_id,
                "ownerId": team.owner_id,
                "position": players[pid].position if pid in players else "",
                "counted": pid in set(team.counted),
                "points": team.points.get(pid),
                "teamScore": team.score,
                "opponentRosterId": team.opponent,
                "contradictions": list(contradictions),
                **{key: _unavailable(R_CONTRADICTED_SETTINGS) for key in _METRICS},
            }
            for team in sorted(teams, key=lambda t: t.roster_id)
            for pid in sorted(set(team.roster) | set(team.counted))
        ]
    league_scores = {t.roster_id: float(t.score) for t in teams if t.score is not None}
    league_week_complete = (
        expected_team_count is not None
        and len(teams) == expected_team_count
        and len(league_scores) == len(teams)
    )
    slots = list(rules.starter_slots)
    out: list[dict[str, Any]] = []

    for team in sorted(teams, key=lambda t: t.roster_id):
        team_reason: str | None = None
        if team.score is None:
            team_reason = R_TEAM_SCORE_MISSING
        elif not team.counted:
            team_reason = R_LINEUP_MISSING
        elif any(pid not in team.points for pid in team.counted):
            team_reason = R_COUNTED_SCORE_MISSING
        elif abs(sum(team.points[pid] for pid in team.counted) - float(team.score)) > 0.011:
            team_reason = R_TEAM_SCORE_MISMATCH

        # WAB / Game Changer: one with-player solve per team-week.
        wab_reason: str | None = team_reason
        pool: list[RosterPlayer] = []
        elig = None
        with_unfilled = 0
        if wab_reason is None:
            if rules.best_ball is None:
                wab_reason = R_BEST_BALL_UNVERIFIED
            elif rules.best_ball is False:
                wab_reason = R_NOT_BEST_BALL
            elif not slots:
                wab_reason = R_SLOTS_UNKNOWN
            elif any(pid not in team.points for pid in team.roster):
                wab_reason = R_ROSTER_SCORES_INCOMPLETE
        if wab_reason is None:
            pool = _pool(team, players)
            elig = precompute_slot_eligibility(pool, slots)
            with_score, with_unfilled = _solve(pool, slots, elig)
            if abs(with_score - float(team.score)) > 0.011:
                wab_reason = R_LINEUP_NOT_REPRODUCED

        counted = set(team.counted)
        for pid in sorted(set(team.roster) | counted):
            info = players.get(pid)
            rec: dict[str, Any] = {
                "week": week,
                "playerId": pid,
                "rosterId": team.roster_id,
                "ownerId": team.owner_id,
                "position": info.position if info else "",
                "counted": pid in counted,
                "points": team.points.get(pid),
                "teamScore": team.score,
                "opponentRosterId": team.opponent,
            }
            if team_reason is not None and (
                pid in counted or not team.counted or team_reason == R_TEAM_SCORE_MISMATCH
            ):
                # This player's counted contribution cannot be established.
                # A score mismatch also makes the counted lineup itself
                # unproven, so a bench player is not a KNOWN zero either.
                for key in _METRICS:
                    rec[key] = _unavailable(team_reason)
                out.append(rec)
                continue
            if pid not in counted:
                # Spec §2/§11: a non-counted week is a KNOWN zero impact
                # whenever the counted lineup itself is known.  WAB keeps
                # the team-week's own state so a team-week is never half
                # known (an unsupported format reads unavailable, not 0).
                zero = {"value": 0.0, "reason": None}
                rec["vorp"] = dict(zero)
                rec["war"] = dict(zero)
                rec["wab"] = dict(zero) if wab_reason is None else _unavailable(wab_reason)
                rec["gameChangerPoints"] = (
                    dict(zero) if wab_reason is None else _unavailable(wab_reason)
                )
                out.append(rec)
                continue

            pts = float(team.points[pid])
            repl = replacement.get(info.position) if info and info.position else None
            if not info or not info.position:
                rec["vorp"] = _unavailable(R_POSITION_UNKNOWN)
                rec["war"] = _unavailable(R_POSITION_UNKNOWN)
            elif repl is None:
                rec["vorp"] = _unavailable(R_REPLACEMENT_UNAVAILABLE)
                rec["war"] = _unavailable(R_REPLACEMENT_UNAVAILABLE)
            else:
                rec["replacementPerGame"] = round(float(repl), 4)
                rec["vorp"] = {"value": _r2(pts - float(repl)), "reason": None}
                delta = credit_delta(
                    team,
                    _r2(float(team.score) - pts + float(repl)),
                    league_scores,
                    median_enabled=rules.median_enabled,
                    league_week_complete=league_week_complete,
                )
                rec["war"] = {"value": delta.total, "reason": delta.reason, **delta.to_dict()}

            if wab_reason is not None:
                rec["wab"] = _unavailable(wab_reason)
                rec["gameChangerPoints"] = _unavailable(wab_reason)
            else:
                without = [p for p in pool if p.player_id != pid]
                without_score, without_unfilled = _solve(without, slots, elig)
                gc = _r2(float(team.score) - without_score)
                if without_unfilled > with_unfilled:
                    rec["wab"] = _unavailable(R_COUNTERFACTUAL_INFEASIBLE)
                    rec["gameChangerPoints"] = _unavailable(R_COUNTERFACTUAL_INFEASIBLE)
                elif gc < -0.005:
                    # Removing an available player cannot raise the optimum
                    # (spec §11): investigate, never clamp.
                    rec["wab"] = _unavailable(R_INVARIANT_VIOLATED)
                    rec["gameChangerPoints"] = _unavailable(R_INVARIANT_VIOLATED)
                else:
                    delta = credit_delta(
                        team,
                        without_score,
                        league_scores,
                        median_enabled=rules.median_enabled,
                        league_week_complete=league_week_complete,
                    )
                    rec["gameChangerPoints"] = {"value": gc, "reason": None}
                    rec["wab"] = {"value": delta.total, "reason": delta.reason, **delta.to_dict()}
            out.append(rec)
    return out


# ── settings contradictions (fail closed) ──────────────────────────────
def detect_contradictions(
    weeks: Mapping[int, Sequence[TeamWeek]],
    rules: WeekRules,
    players: Mapping[str, PlayerInfo],
) -> dict[int, list[str]]:
    """Weeks whose matchups contradict the season's league object.

    Sleeper keeps ONE league object per season carrying its FINAL settings,
    so a mid-season or off-season change makes it lie about earlier weeks.
    Two observable contradictions, each enough to fail the week closed:

    * ``starter_count_differs_from_configured_slots`` — a team's raw
      ``starters`` array is not the configured slot count (measured on the
      2025 ``dynasty_main`` season: 22 starters per team against a
      17-slot league object);
    * ``best_ball_flag_contradicted_by_host_lineups`` — the league says
      best ball but a team's recorded lineup (whose points sum to its
      score) is not the exact optimum of its own roster (2024: best_ball=1
      with managed-looking lineups on every team-week).

    Strict by design: one contradicting team-week marks the week, because
    replacement demand, the slot layout and the median all span the whole
    league-week.  A false positive costs availability, never correctness.
    """
    slots = list(rules.starter_slots)
    out: dict[int, list[str]] = {}
    for wk in sorted(weeks):
        reasons: set[str] = set()
        for team in sorted(weeks[wk], key=lambda t: t.roster_id):
            if slots and team.lineup_size is not None and team.lineup_size != len(slots):
                reasons.add(CONTRA_SLOT_COUNT)
                continue
            if rules.best_ball is not True or not slots or team.score is None:
                continue
            if not team.counted or any(pid not in team.points for pid in team.counted):
                continue
            if abs(sum(team.points[pid] for pid in team.counted) - float(team.score)) > 0.011:
                continue
            if any(pid not in team.points for pid in team.roster):
                continue  # cannot prove the optimum without every score
            pool = _pool(team, players)
            score, _unfilled = _solve(pool, slots, precompute_slot_eligibility(pool, slots))
            if abs(score - float(team.score)) > 0.011:
                reasons.add(CONTRA_BEST_BALL)
        if reasons:
            out[wk] = sorted(reasons)
    return out


# ── replacement level (consumes the two replacement owners) ────────────
def measure_replacement(
    weeks: Mapping[int, Sequence[TeamWeek]],
    players: Mapping[str, PlayerInfo],
    starter_slots: Sequence[str],
    *,
    band_size: int = REPLACEMENT_BAND_SIZE,
) -> dict[str, dict[str, Any]]:
    """League-level replacement points-per-game per position.

    Demand: ``measure_endogenous_starters`` on each finished week's REAL
    scores (its docstring: "given per-week actuals it reports the real
    allocation"), averaged over weeks -> league starters per week at the
    position = the cutoff.  Level: ``replacement_per_game`` over every
    rostered player's season-to-date pace, ``require_full_band=True``.

    Pace is PER GAME PLAYED, as the owner's docstring defines it ("80
    points in 6 games").  The host records an NFL bye or an inactive week
    as a literal ``0.0`` it does not distinguish from a scoreless game, so
    a ``0.0`` week is not counted as a game (labelled PRIOR
    ``zero_week_not_a_game``); counting it would deflate every pace, most
    of all for the injured starters the band exists to look past.
    """
    positions = sorted({info.position for info in players.values() if info.position})
    if not weeks:
        return {p: {"replacementPerGame": None, "reason": REPL_NO_WEEKS} for p in positions}
    if not starter_slots:
        return {p: {"replacementPerGame": None, "reason": REPL_NO_SLOTS} for p in positions}

    started: dict[str, float] = defaultdict(float)
    totals: dict[str, dict[str, Any]] = {}
    for wk in sorted(weeks):
        week_teams = []
        for team in sorted(weeks[wk], key=lambda t: t.roster_id):
            rows = []
            for pid in sorted(set(team.roster) | set(team.counted)):
                info = players.get(pid)
                pts = team.points.get(pid)
                if pts is None or not info or not info.position:
                    continue
                rows.append(
                    {
                        "playerId": pid,
                        "position": info.position,
                        "rosValue": float(pts),
                        "fantasyPositions": list(info.fantasy_positions),
                    }
                )
                rec = totals.setdefault(pid, {"position": info.position, "points": 0.0, "games": 0})
                rec["points"] += float(pts)
                if float(pts) != 0.0:
                    rec["games"] += 1
            week_teams.append({"players": rows})
        measured = measure_endogenous_starters(week_teams, list(starter_slots))
        for pos, per_team in measured.starters_per_team.items():
            started[pos] += per_team * measured.team_count

    n_weeks = len(weeks)
    by_pos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in totals.values():
        by_pos[rec["position"]].append(rec)

    out: dict[str, dict[str, Any]] = {}
    for pos in positions:
        per_week = started.get(pos, 0.0) / n_weeks
        cutoff = int(math.floor(per_week + 0.5))
        rows = by_pos.get(pos) or []
        base = {
            "leagueStartersPerWeek": round(per_week, 3),
            "starterCutoff": cutoff,
            "poolSize": len(rows),
            "bandSize": band_size,
        }
        if cutoff <= 0:
            out[pos] = {"replacementPerGame": None, "reason": REPL_NO_DEMAND, **base}
            continue
        level = replacement_per_game(rows, cutoff, band_size=band_size, require_full_band=True)
        out[pos] = {
            "replacementPerGame": None if level is None else round(float(level), 4),
            "reason": None if level is not None else REPL_INSUFFICIENT_BAND,
            **base,
        }
    return out


# ── season aggregation ─────────────────────────────────────────────────
def aggregate(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Season rows per ``(player, franchise)``; only KNOWN weeks are summed.

    A traded player gets one row per franchise that actually rostered him,
    each carrying only that franchise's weeks (spec §11: a late trade never
    transfers earlier impact).
    """
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        groups[(rec["playerId"], rec["rosterId"])].append(rec)

    rows: list[dict[str, Any]] = []
    for (pid, rid), recs in sorted(groups.items()):
        recs.sort(key=lambda r: r["week"])
        row: dict[str, Any] = {
            "playerId": pid,
            "rosterId": rid,
            "ownerId": recs[-1]["ownerId"],
            "position": next((r["position"] for r in recs if r["position"]), ""),
            "weeks": [r["week"] for r in recs],
            "weeksRostered": len(recs),
            "weeksCounted": sum(1 for r in recs if r["counted"]),
        }
        for key in _METRICS:
            known = [r[key]["value"] for r in recs if r[key]["value"] is not None]
            reasons: dict[str, int] = defaultdict(int)
            for r in recs:
                if r[key]["value"] is None:
                    reasons[r[key]["reason"] or "unknown"] += 1
            missing = len(recs) - len(known)
            block: dict[str, Any] = {
                "total": _r2(sum(known)) if known else None,
                "weeksKnown": len(known),
                "weeksUnavailable": missing,
                "coverage": "complete" if missing == 0 else ("partial" if known else "unavailable"),
                "unavailableReasons": dict(sorted(reasons.items())),
            }
            if key in ("war", "wab"):
                h2h = [r[key].get("h2hDelta") for r in recs if r["counted"]]
                med = [r[key].get("medianDelta") for r in recs if r["counted"]]
                block["h2hResultsChanged"] = sum(1 for v in h2h if v)
                block["medianResultsChanged"] = sum(1 for v in med if v)
            row[key] = block
        rows.append(row)
    rows.sort(
        key=lambda r: (
            r["vorp"]["total"] is None,
            -(r["vorp"]["total"] if r["vorp"]["total"] is not None else 0.0),
            r["playerId"],
            r["rosterId"],
        )
    )
    return rows


# ── snapshot adapter ───────────────────────────────────────────────────
def _parse_points(entry: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    pp = entry.get("players_points")
    if not isinstance(pp, dict):
        return out
    for pid, raw in pp.items():
        if raw is None or isinstance(raw, bool):
            continue
        try:
            out[str(pid)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _score(entry: Mapping[str, Any]) -> float | None:
    raw = entry.get("points")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _best_ball(season: SeasonSnapshot) -> bool | None:
    """Tri-state, like ``game_day_sim.rules_from_league``: an absent or
    unparseable flag is UNVERIFIED (``None``), never "managed"."""
    raw = (season.league.get("settings") or {}).get("best_ball")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    try:
        return bool(int(raw))
    except (TypeError, ValueError):
        return None


def season_team_weeks(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> tuple[dict[int, list[TeamWeek]], list[int]]:
    """``({finished regular week: [TeamWeek]}, excluded regular weeks)``.

    Finished = ``metrics.final_weeks`` (the one owner); an in-progress or
    unproven week is excluded and reported, never partially counted.
    """
    final = set(metrics.final_weeks(season))
    regular = season.regular_season_weeks
    included = [w for w in regular if w in final]
    excluded = [w for w in regular if w not in final]
    out: dict[int, list[TeamWeek]] = {}
    for wk in included:
        entries = season.matchups_by_week.get(wk) or []
        # THE grouping rule (schedule_impact): a malformed group is a named
        # structural issue, never silently a bye.
        pairs, _byes, structural = week_matchup_structure(entries, metrics.roster_id_of)
        opponent: dict[int, int] = {}
        for ra, rb in pairs:
            opponent[ra] = rb
            opponent[rb] = ra
        issue_of: dict[int, str] = {}
        for issue in structural:
            kind, _sep, rest = issue.partition(":")
            members = rest.split(":", 1)[1] if kind == "group_size" else rest
            for member in members.split(","):
                if member.strip().lstrip("-").isdigit():
                    issue_of[int(member)] = kind
        teams: list[TeamWeek] = []
        seen: set[int] = set()
        for entry in entries:
            rid = metrics.roster_id_of(entry)
            if rid is None or rid in seen:
                continue
            seen.add(rid)
            points = _parse_points(entry)
            counted = tuple(str(s) for s in (entry.get("starters") or []) if s and str(s) != "0")
            roster = tuple(str(p) for p in (entry.get("players") or []) if p) or tuple(points)
            raw_starters = entry.get("starters")
            teams.append(
                TeamWeek(
                    roster_id=rid,
                    owner_id=metrics.resolve_owner(snapshot.managers, season.league_id, rid),
                    score=_score(entry),
                    counted=counted,
                    points=points,
                    roster=roster,
                    opponent=opponent.get(rid),
                    matchup_issue=issue_of.get(rid),
                    lineup_size=len(raw_starters) if isinstance(raw_starters, list) else None,
                )
            )
        out[wk] = teams
    return out, excluded


def _player_info(snapshot: PublicLeagueSnapshot, pid: str) -> PlayerInfo:
    raw = snapshot.nfl_players.get(str(pid))
    raw = raw if isinstance(raw, dict) else {}
    fps = tuple(str(p).upper() for p in (raw.get("fantasy_positions") or []) if p)
    return PlayerInfo(
        position=snapshot.player_position(pid),
        host_position=str(raw.get("position") or "").upper(),
        fantasy_positions=fps,
    )


def compute_season(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> dict[str, Any]:
    """The full deterministic player-impact contract for one season."""
    weeks, excluded = season_team_weeks(snapshot, season)
    slots, slots_source = resolve_starter_slots(
        roster_positions=season.league.get("roster_positions")
    )
    rules = WeekRules(
        starter_slots=tuple(slots),
        best_ball=_best_ball(season),
        median_enabled=metrics.median_game_enabled(season),
    )
    pids = sorted({p for teams in weeks.values() for t in teams for p in (*t.roster, *t.counted)})
    players = {pid: _player_info(snapshot, pid) for pid in pids}
    contradicted = detect_contradictions(weeks, rules, players)
    # Replacement demand is measured ONLY over weeks whose matchups agree
    # with the configured slots and lineup rule; a contradicted week would
    # feed the wrong layout into the cutoff.
    consistent = {wk: teams for wk, teams in weeks.items() if wk not in contradicted}
    if weeks and not consistent:
        positions = sorted({info.position for info in players.values() if info.position})
        replacement = {
            pos: {"replacementPerGame": None, "reason": REPL_CONTRADICTED} for pos in positions
        }
    else:
        replacement = measure_replacement(consistent, players, rules.starter_slots)
    level = {pos: r["replacementPerGame"] for pos, r in replacement.items()}

    records: list[dict[str, Any]] = []
    for wk in sorted(weeks):
        records.extend(
            evaluate_league_week(
                wk,
                weeks[wk],
                rules,
                players,
                level,
                expected_team_count=season.num_teams if season.num_teams > 0 else None,
                contradictions=contradicted.get(wk, ()),
            )
        )

    rows = aggregate(records)
    # League-wide coverage over COUNTED player-weeks, so "this season's WAB
    # is unavailable because the host lineups are not best-ball optima" is
    # one readable line rather than thousands of per-row reasons.
    coverage: dict[str, dict[str, Any]] = {}
    counted_recs = [r for r in records if r["counted"]]
    for key in _METRICS:
        reasons: dict[str, int] = defaultdict(int)
        for r in counted_recs:
            if r[key]["value"] is None:
                reasons[r[key]["reason"] or "unknown"] += 1
        coverage[key] = {
            "countedPlayerWeeks": len(counted_recs),
            "known": len(counted_recs) - sum(reasons.values()),
            "unavailableReasons": dict(sorted(reasons.items())),
        }
    for row in rows:
        row["playerName"] = snapshot.player_display(row["playerId"])
        row["displayName"] = (
            metrics.display_name_for(snapshot, row["ownerId"]) if row["ownerId"] else ""
        )
    # ``num_teams`` reads 0 when the host states no size: that is UNKNOWN,
    # and an unknown size can be neither verified nor refuted.
    team_count: int | None = season.num_teams if season.num_teams > 0 else None
    host_verified: bool | None = (
        None
        if team_count is None
        else bool(THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES and team_count % 2 == 0)
    )
    return {
        "contractVersion": CONTRACT_VERSION,
        "calcVersion": CALC_VERSION,
        "season": season.season,
        "leagueId": season.league_id,
        "scope": {
            "kind": "regular_season_finished_weeks",
            "weeks": sorted(weeks),
            "excludedRegularSeasonWeeks": excluded,
            "asOfWeek": max(weeks) if weeks else None,
            "playoffsIncluded": False,
        },
        "rules": {
            "bestBall": rules.best_ball,
            "medianGame": rules.median_enabled,
            "medianThreshold": {
                "semantics": THRESHOLD_SEMANTICS,
                "hostVerified": host_verified,
            },
            "starterSlots": list(rules.starter_slots),
            "starterSlotsSource": slots_source,
            "tieCredit": comparison_credit(0, 0),
        },
        "settings": {
            "state": SETTINGS_CONTRADICTED if contradicted else SETTINGS_CONSISTENT,
            "configuredStarterSlotCount": len(rules.starter_slots),
            "contradictedWeeks": [
                {"week": wk, "reasons": reasons} for wk, reasons in sorted(contradicted.items())
            ],
            "note": "Sleeper stores one league object per season with its FINAL settings; "
            "weeks whose matchups contradict it are withheld, never computed on the "
            "wrong layout.",
        },
        "replacement": replacement,
        "replacementTemporalScope": {
            "kind": "season_to_date",
            "weeks": sorted(consistent) if weeks else [],
            "usesLaterWeeks": True,
            "prior": "replacement_season_to_date",
            "note": "One level per position over every consistent finished week, so a "
            "week's VORP/WAR reads replacement evidence from LATER weeks too.  Not a "
            "no-lookahead (as-of) value; a published value is reproducible only with "
            "this asOfWeek and calcVersion (spec §10/§12).",
        },
        "coverage": coverage,
        "xWar": {"state": "unavailable", "reason": "no_archived_no_lookahead_distribution"},
        "priors": [dict(p) for p in PRIORS],
        "attribution": "per (player, franchise, week); leave-one-out impacts are not "
        "additive shares of team wins",
        "players": rows,
        "_records": records,
    }


def build_payload(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    player_id: str | None = None,
    computed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public shape of :func:`compute_season`: season rows always; weekly
    records only for one requested player (they are ~3.5k per season)."""
    full = computed if computed is not None else compute_season(snapshot, season)
    payload = {k: v for k, v in full.items() if k != "_records"}
    if player_id is not None:
        pid = str(player_id)
        payload["players"] = [r for r in full["players"] if r["playerId"] == pid]
        payload["playerWeeks"] = [
            r for r in full["_records"] if r["playerId"] == pid and r["counted"]
        ]
    return payload
