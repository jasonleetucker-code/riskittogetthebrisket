"""THE playoff / title probability engine (C5-PLAY-01 / V1-51).

ONE canonical owner.  Every surface that publishes a playoff, bye, seed,
championship, finals or semifinal probability reads :func:`canonical_forecast`
(or, for a hypothetical such as a trade arm, :func:`simulate_playoff_odds`):

* ``/api/public/league/rosPlayoffOdds`` — this payload as-is;
* ``/api/public/league/playoffOdds`` — the same forecast in the public
  section's historical shape (``src.public_league.playoff_odds``, now an
  adapter with no simulation of its own);
* ``/api/public/league/rosChampionship`` — the same forecast reshaped
  (``src.ros.championship``, likewise an adapter).

Until C5-PLAY-01 the public section ran its own empirical-resampling Monte
Carlo and ``championship.py`` ran a third loop with its own bracket; on the
2026-10-07 week-5 state the public engine said 99.0% for a team this engine
put at 77.2%.  Why THIS engine is the canonical one (model identity and
point-in-time capture via ``src.ros.forecast_archive`` / AL-P6 sidecars,
``draftSlotDistribution`` for the pick projector, adaptive convergence with
Wilson intervals, the league's exact lineup solve) is recorded in
``tests/ros/test_one_playoff_engine.py``.

Methodology is UNCHANGED by that consolidation, including the open owner
decision every surface now inherits: D2 (the ``× (1 + ROS_BLEND·z)`` mean
multiplier on top of a ROS-drawn best-ball pre-sim) —
``docs/OWNER_REQUESTED_TODO.md``.

D3 (TODO-2026-09-26-D3) is CLOSED as an exact-league-rule fact, not a
methodology change: when the league counts a weekly median game
(``league_average_match``), the record to date includes it
(``playoff_odds.regular_season_standings_to_date``) and every simulated week
awards each team a median W/L/T from that week's own drawn scores, decided by
Game Day's host-verified threshold (``game_day_sim.median_threshold``: the
average of the middle two scores; exactly on it is a TIE, half a win).  Seeding,
the bracket and expected wins read that record.  DRAFT ORDER does not: the
owner's draft-order rule does not say whether median results count, so it keeps
the head-to-head record (``DRAFT_ORDER_RECORD_BASIS``, stamped as
``draftOrderRecordBasis``) until the owner decides.  The rule travels on every
payload as ``standingsRule``; a league whose median rule cannot be verified —
including an unstated setting — is refused, never silently scored head-to-head
only.

This engine uses ROS team-strength as the per-team weekly score MEAN,
blended with the team's empirical scoring distribution from the season
snapshot — a forward-looking signal that pure history can't capture
(rosters that just got stronger via trades, breakout players, etc.).

Inputs:
    snapshot         : PublicLeagueSnapshot
    n_simulations    : int (default 10000; configurable via settings)
    ros_strength_map : {ownerId: ros_strength_score} from
                       data/ros/team_strength/latest.json — when
                       absent, the sim degrades cleanly to v1-style
                       empirical-only behavior.

Implementation overview:

  1. Per owner: collect regular-season weekly scores → (mean, sd).
  2. Blend ROS strength: shifted_mean = empirical_mean
        * (1 + ROS_BLEND * (ros_strength_z - 1)).
     ROS_BLEND defaults to 0.20 — small enough that empirical history
     dominates today's standings, large enough that current-roster
     differences register.
  3. Best-ball variance bump: sd *= 1.10 to account for spike-week
     contributions that the empirical distribution under-represents.
  4. For each remaining matchup, draw both teams' scores, record W/L.
  5. Apply tiebreaker (PF descending) and rank teams 1..N.
  6. Aggregate playoff appearance + bye + top-seed odds.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import random
import statistics
import threading
from dataclasses import dataclass
from typing import Any

from src.league_intel.sim_calibration import (
    DEFAULT_POINTS_MODEL,
    PointsModel,
    load_points_model,
)
from src.ros import ROS_DATA_DIR
from src.ros.game_day_sim import median_threshold
from src.ros.lineup import (
    RosterPlayer,
    load_league_starter_slots,
    solve_optimal_assignment,
)
from src.public_league import luck, metrics, playoff_odds
from src.public_league.playoff_structure import SEED_TYPE_RESEED, resolve_playoff_structure
from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.playoff_sim")


#: The record the rookie-draft order ranks on in a simulated season: the
#: head-to-head results plus half a win per tied game — the pre-D3 record.
#: Deliberately NOT the host's official standings when the league counts a
#: weekly median game: the owner's draft-order rule does not say whether those
#: count, and the league's draft history does not settle it
#: (docs/picks/DRAFT_ORDER_RULE.md).  Changing it is an owner decision.
DRAFT_ORDER_RECORD_BASIS = "head_to_head_with_half_win_ties"

# Magnitude of ROS-strength influence on per-team weekly mean.  Chosen
# small so empirical history still dominates; tunable via settings.
ROS_BLEND = 0.20

# Best-ball weekly variance bump — the optimal-lineup picks add
# spike-week upside that empirical scoring distributions under-sample.
# Used as the *base* multiplier; per-team depth lift is added on top
# (see ``_team_variance_multiplier``).
BEST_BALL_VARIANCE_BUMP = 1.10

# Maximum additional variance lift per team, on top of the base bump,
# proportional to the team's bench-to-starter score ratio.  A team
# with a deep bench (50% of starting-lineup value) gets ~+5% on top
# of the 10% base; a thin team gets ~+1%.  Capped to keep tail
# behavior physically plausible.
DEPTH_VARIANCE_LIFT_MAX = 0.15

# Simulation counts are now CONVERGENCE-DRIVEN (LI-8): these are the
# bounds of an adaptive loop, not a fixed budget.  A fixed count is
# either wasteful (a settled league keeps drawing) or wrong (a tight
# playoff race stops before the odds resolve) — and it cannot tell you
# which, because it reports no error bar.
DEFAULT_SIMULATIONS = 10000
MIN_SIMULATIONS = 2000
MAX_SIMULATIONS = 60000

# Stop when every team's playoff-odds standard error is under this.
# 0.005 ⇒ ±1pp at ~95% confidence, which is finer than the product ever
# displays (odds render to whole percents).
ODDS_SE_TOLERANCE = 0.005
SIM_CHECK_EVERY = 1000

# Best-ball per-week presim.  For each team we draw weekly per-player
# scores, solve the EXACT lineup on each draw, and take the empirical
# (mean, sd).  Adaptive between these bounds; the previous fixed 200
# claimed "~3% of the asymptotic value" with no check that it got there.
BEST_BALL_PRESIM_MIN_WEEKS = 120
BEST_BALL_PRESIM_MAX_WEEKS = 1200
PRESIM_CHECK_EVERY = 40
# Relative standard error of the mean: stop once the mean is pinned to
# 1% of itself.
PRESIM_MEAN_TOLERANCE = 0.01

# The rosValue -> weekly-points conversion and its per-position CV table
# belong to ``src/league_intel/sim_calibration.py``, which owns the
# ``PointsModel`` this module already draws through
# (``model.draw(ros, pos, rng)``).  This module used to restate that
# table verbatim — byte-identical to
# ``sim_calibration.FALLBACK_CV_BY_POSITION`` — and read it nowhere; its
# only consumer was a second ``draw()`` implementation in the dormant
# ``league_intel/sim.py``.  Three copies of three numbers.
#
# The comment that stood here also described arithmetic this module has
# not performed for some time: "mean = rosValue/17 x game-mean scale".
# The model divides by ``ros_value_per_point`` (2.7 as the documented
# fallback, or whatever a calibrated ``sim_points_model.json`` supplies)
# — a points-per-rosValue-unit conversion, not a season total spread
# over 17 games.  A stale formula in a comment is worse than none: it is
# the number a reader will quote.


def _mean_is_converged(samples: list[float], rel_tolerance: float) -> bool:
    """True when the sample mean's relative standard error is within
    ``rel_tolerance``.

    SE(mean) = sd / sqrt(n); "relative" divides by the mean so the
    tolerance is scale-free (a 12-point team and a 140-point team
    converge on the same criterion).  A zero/near-zero mean can never
    satisfy a relative test, so it converges on the absolute SE instead
    — otherwise an all-zero roster would spin to the cap.
    """
    n = len(samples)
    if n < 4:
        return False
    mean = statistics.fmean(samples)
    sd = statistics.pstdev(samples)
    if sd <= 0.0:
        return True
    se = sd / math.sqrt(n)
    if abs(mean) < 1e-9:
        return se < rel_tolerance
    return (se / abs(mean)) < rel_tolerance


def _proportion_se(p: float, n: int) -> float:
    """Standard error of a Bernoulli proportion — the error bar on an
    odds figure.  ``p`` at exactly 0 or 1 yields 0, which is an
    UNDERSTATEMENT of the true uncertainty from a finite sample; callers
    that report intervals use the Wilson bound instead (see
    ``_wilson_interval``), which stays honest at the boundaries.
    """
    if n <= 0:
        return 0.0
    p = min(1.0, max(0.0, p))
    return math.sqrt(p * (1.0 - p) / n)


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Chosen over the normal approximation because playoff odds live near
    0 and 1 for most of a season, exactly where the normal interval
    breaks (it produces bounds outside [0,1] and collapses to zero width
    at p=0/1, claiming certainty a finite sample cannot support).
    """
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2 * n)) / denom
    margin = (z / denom) * math.sqrt((p * (1 - p) / n) + (z * z) / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def _load_team_depth_ratios(league_key: str | None = None) -> dict[str, float]:
    """Per-owner bench/starter score ratio from team-strength snapshot.

    Returns {} when the snapshot is missing — caller falls back to the
    flat ``BEST_BALL_VARIANCE_BUMP`` for every team.  Capped at 1.0
    (a bench worth more than the starting lineup is anomalous; clamp
    to keep the lift bounded).
    """
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    rows = load_or_compute_team_strength(league_key)
    out: dict[str, float] = {}
    for r in rows or []:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue
        starter = float(r.get("startingLineupScore") or 0.0)
        bench = float(r.get("benchDepthScore") or 0.0)
        if starter <= 0:
            continue
        out[oid] = max(0.0, min(1.0, bench / starter))
    return out


def _team_variance_multiplier(
    owner_id: str,
    depth_ratios: dict[str, float],
    best_ball: bool,
) -> float:
    """Per-team weekly variance multiplier.

    For best-ball leagues, depth materially increases week-to-week
    ceiling — a richer bench produces more spike weeks via the
    optimal-lineup picker.  For start/sit leagues, depth doesn't
    feed weekly scoring, so the bump stays at 1.0 (no lift).
    """
    if not best_ball:
        return 1.0
    base = BEST_BALL_VARIANCE_BUMP
    ratio = depth_ratios.get(owner_id, 0.0)
    return base + DEPTH_VARIANCE_LIFT_MAX * ratio


@dataclass
class _TeamDist:
    owner_id: str
    mean: float
    sd: float
    pf_to_date: float
    #: Where this team's (mean, sd) came from: ``"presim"`` (its own roster,
    #: best-ball pre-sim), ``"empirical"`` (its own scored weeks), or
    #: ``"pool"`` (the LEAGUE-WIDE distribution, i.e. nothing about this
    #: team at all).  ``"unspecified"`` for distributions built by a caller
    #: rather than ``_build_team_distributions``.  Read by
    #: ``team_evidence_refusal`` — see there for why it matters.
    basis: str = "unspecified"


def _load_team_rosters(league_key: str | None = None) -> dict[str, dict[str, Any]]:
    """Per-owner roster from the team-strength snapshot.

    Returns ``{ownerId: {"starters": [...], "bench": [...]}}``.  Each
    player entry carries
    ``{playerId, canonicalName, position, rosValue, fantasyPositions}``.
    Empty dict when no snapshot — caller skips best-ball presim.

    **Two things this function must get right, and both were wrong.**

    1. *Prefers ``fullRoster``.*  Reading ``startingLineup +
       benchDepth`` yields 29 of a 44-58 man roster, because
       ``benchDepth`` is capped at ``lineup.DEPTH_BENCH_LIMIT`` for
       depth *scoring* rather than roster enumeration.  Best ball is
       the format that pays for the tail, so that truncation is simply
       the wrong input.  Measured on the 12 real rosters (400 weeks,
       seed 7): it understates the weekly mean by +1.1 to +9.4 points,
       varying ~8x by team, deep rosters penalised most.

       Said plainly rather than sold: at today's roster construction it
       reorders NO team.  This is a correctness fix to the input, not a
       repair of visibly wrong playoff odds.  But adaptive convergence
       and Wilson intervals computed over 29 of 44-58 players is a
       better-calibrated answer about the wrong team, which is why it
       is worth fixing underneath them rather than after.

    2. *Carries ``fantasyPositions``.*  ``_bestball_weekly_score``
       reads this key to build ``RosterPlayer.fantasy_positions``, and
       ``solve_optimal_assignment`` uses it for multi-position
       eligibility.  When the loader omitted it, ``fpos`` was always
       ``()``, ``eligible_positions()`` fell back to ``(position,)``,
       and every DL/LB hybrid was matched position-only — so routing
       the sim through the exact optimizer fixed the *algorithm* while
       the *data* still expressed the original bug.  The exact solve is
       only as good as the eligibility it is handed.

    Older snapshots without ``fullRoster`` fall back to the truncated
    read so the sim still runs.
    """
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    rows = load_or_compute_team_strength(league_key)
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        oid = str(r.get("ownerId") or "")
        if not oid:
            continue

        def _pluck(player_list: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
            return [
                {
                    "playerId": str(p.get("playerId") or ""),
                    "canonicalName": str(p.get("canonicalName") or ""),
                    "position": str(p.get("position") or "").upper(),
                    "rosValue": float(p.get("rosValue") or 0.0),
                    "fantasyPositions": [
                        str(fp).upper() for fp in (p.get("fantasyPositions") or [])
                    ],
                }
                for p in (player_list or [])
                if p.get("playerId")
            ]

        full = _pluck(r.get("fullRoster"))
        if full:
            # Whole roster available: put it all in "starters" so the
            # presim draws from every player.  The split only ever
            # existed because the snapshot stored two truncated lists.
            out[oid] = {"starters": full, "bench": []}
        else:
            out[oid] = {
                "starters": _pluck(r.get("startingLineup")),
                "bench": _pluck(r.get("benchDepth")),
            }
    return out


# ``_load_starter_slots`` and a private ``_eligible_for_slot`` used to
# live here — the third and fourth copies of logic that belongs to
# ``src.ros.lineup``.  Both are now imported (LI-8): one flattener, one
# eligibility definition, and the sim inherits the ``fantasy_positions``
# fix from LI-3 for free.
_load_starter_slots = load_league_starter_slots


def _bestball_weekly_score(
    roster_players: list[dict[str, Any]],
    starter_slots: list[str],
    rng: random.Random,
    points_model: PointsModel | None = None,
) -> float:
    """One simulated best-ball week.

    1. Draw a per-player weekly point total from the calibrated points
       model (see ``src.league_intel.sim_calibration``).
    2. Solve the EXACT maximum-weight player→slot assignment.
    3. Sum the assigned scores.

    Step 2 was a slot-ordered greedy until LI-8.  Two defects came with
    it, both silent:

    * The greedy is optimal only for a *laminar* slot-eligibility family
      (ADR-007).  It held for this league's slots, so it was correct by
      an unenforced precondition — one non-laminar slot would have
      quietly produced sub-optimal lineups and therefore understated
      every team's best-ball ceiling.
    * It matched on ``position`` alone, so hybrid IDPs (``position="DL"``
      with ``fantasy_positions=["DL","LB"]``) were locked out of half
      their legal slots — the exact bug LI-3 fixed in ``lineup.py`` and
      measured at up to +13.75 starting-lineup points on real rosters.

    Routing through ``solve_optimal_assignment`` fixes both, and the sim
    now shares ONE eligibility definition with team-strength.
    """
    if not roster_players or not starter_slots:
        return 0.0

    model = points_model or DEFAULT_POINTS_MODEL

    # Step 1: draw this week's points for every priced player.  Build
    # RosterPlayer rows whose ``ros_value`` IS the drawn score, so the
    # optimizer maximizes realized weekly points rather than season
    # value.  health penalties are already folded into the draw.
    pool: list[RosterPlayer] = []
    for p in roster_players:
        ros = float(p.get("rosValue") or 0.0)
        if ros <= 0:
            continue
        pos = str(p.get("position") or "").upper()
        score = model.draw(ros, pos, rng)
        fpos = p.get("fantasyPositions") or ()
        pool.append(
            RosterPlayer(
                player_id=str(p.get("playerId") or ""),
                canonical_name=str(p.get("canonicalName") or ""),
                position=pos,
                ros_value=score,
                fantasy_positions=tuple(fpos),
            )
        )

    # Step 2: exact assignment.
    assignment = solve_optimal_assignment(pool, starter_slots)
    return float(sum(player.ros_value for player in assignment.values()))


def _bestball_presim(
    rosters: dict[str, dict[str, Any]],
    starter_slots: list[str],
    rng: random.Random,
    points_model: PointsModel | None = None,
) -> dict[str, tuple[float, float]]:
    """Run best-ball weeks per team, return ``{ownerId: (mean, sd)}``.

    Week count is adaptive (LI-8): draws continue until the running mean
    is resolved to ``PRESIM_MEAN_TOLERANCE`` of a standard error, capped
    at ``BEST_BALL_PRESIM_MAX_WEEKS``.  The old fixed 200 was a guess
    that under-sampled high-variance rosters and wasted draws on stable
    ones.
    """
    if not rosters or not starter_slots:
        return {}
    model = points_model or DEFAULT_POINTS_MODEL
    out: dict[str, tuple[float, float]] = {}
    for owner, blob in rosters.items():
        roster = (blob.get("starters") or []) + (blob.get("bench") or [])
        if not roster:
            continue
        weekly: list[float] = []
        for i in range(BEST_BALL_PRESIM_MAX_WEEKS):
            weekly.append(_bestball_weekly_score(roster, starter_slots, rng, model))
            # Check convergence on a cadence, never before a usable floor.
            if i + 1 >= BEST_BALL_PRESIM_MIN_WEEKS and (i + 1) % PRESIM_CHECK_EVERY == 0:
                if _mean_is_converged(weekly, PRESIM_MEAN_TOLERANCE):
                    break
        if len(weekly) >= 4:
            out[owner] = (statistics.fmean(weekly), statistics.pstdev(weekly))
    return out


def _load_ros_strength_map(league_key: str | None = None) -> dict[str, float]:
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    rows = load_or_compute_team_strength(league_key)
    return {
        str(r.get("ownerId") or ""): float(r.get("teamRosStrength") or 0.0)
        for r in rows or []
        if r.get("ownerId")
    }


def ros_strength_available(ros_strength_map: dict[str, float]) -> bool:
    """Whether a ROS team-strength map carries REAL evidence.

    At least one team must have a positive strength.  A map that exists
    but is all zeros is what a failed NFL player download produces
    (refresh run 36220954196: every rostered player fell back to a raw
    Sleeper id, failed the ROS join, and scored 0), and it used to be
    stamped ``rosStrengthAvailable: true`` because the check was
    ``bool(ros_map)`` — non-empty, not evidential.  An all-zero map gives
    every team z = 0, i.e. no ROS signal at all, so reporting it as
    "ROS roster strength blended in" was false.

    No coverage threshold is applied: none exists in the codebase to reuse,
    and inventing one is a methodology decision.  This predicate answers
    only "is there any ROS evidence", which is the question the published
    flag asks.
    """
    for value in ros_strength_map.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return True
    return False


#: Stated once so both engines (and every refusal branch) name the state
#: identically — the V1-51 rule that two engines must not invent different
#: words for one state.
TEAM_STRENGTH_UNAVAILABLE = "team_strength_unavailable"


def team_evidence_refusal(
    distributions: dict[str, _TeamDist],
    ros_strength_map: dict[str, float],
) -> dict[str, Any] | None:
    """The ``unsimulable`` block when odds would carry no team evidence.

    Returns ``None`` when the simulation may run.  Refuses when BOTH:

    * ROS team strength is unavailable (``ros_strength_available`` is
      False), and
    * at least one team's distribution is the league-wide ``"pool"`` —
      nothing about that team, neither its roster nor its own history.

    That is exactly the degraded state that published flat 13/12/10%
    championship odds as real on 2026-09-26: with fewer than four
    finished weeks every team falls back to the pool, and with no ROS
    signal nothing distinguishes one team's weekly score from another's,
    so the "odds" are coin flips weighted only by the current record.

    Deliberately NOT a refusal of empirical-only mode.  When every team
    has its own scored history (``"empirical"``) the simulation is real
    evidence without ROS, which the frontend already labels as
    "Empirical-only mode"; that path is unchanged.
    """
    if ros_strength_available(ros_strength_map):
        return None
    pooled = sorted(o for o, d in distributions.items() if d.basis == "pool")
    if not pooled:
        return None
    return {
        "reason": TEAM_STRENGTH_UNAVAILABLE,
        "detail": (
            "ROS team strength is unavailable (the last roster refresh could not "
            "price any team), and "
            f"{len(pooled)} of {len(distributions)} teams have too few finished "
            "weeks for a distribution of their own. Simulating anyway would give "
            "those teams identical league-average scoring, i.e. coin flips. "
            "This is not an equal chance for everyone."
        ),
        "teamsWithoutEvidence": len(pooled),
        "teamCount": len(distributions),
    }


def _empirical_distribution(scores: list[float]) -> tuple[float, float]:
    """Mean + sd over a per-team weekly-score list.  Falls back to
    league-wide pool stats when the per-team list is too short.
    """
    if len(scores) >= 4:
        return statistics.fmean(scores), statistics.pstdev(scores)
    return 0.0, 0.0


def _build_team_distributions(
    snapshot: PublicLeagueSnapshot,
    ros_strength_map: dict[str, float],
    *,
    league_key: str | None = None,
    best_ball: bool = False,
    points_model: PointsModel | None = None,
) -> tuple[dict[str, _TeamDist], dict[str, float]]:
    """Build per-team weekly score distributions blended with ROS.

    Returns (distributions, current_records) where current_records is
    {ownerId: actual_wins_to_date}.

    ``best_ball`` toggles the depth-aware variance lift: in best-ball
    leagues a deeper bench produces more spike weeks via the optimal-
    lineup picker, so per-team variance scales with bench/starter
    ratio.  In start/sit leagues the bench doesn't feed weekly
    scoring, so the bump is 1.0 (no lift).
    """
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    if not seasons_sorted:
        return {}, {}
    current_season = seasons_sorted[-1]
    per_owner, pool = playoff_odds._season_weekly_scores(current_season, snapshot.managers)
    pool_mean, pool_sd = _empirical_distribution(pool)

    # ROS strength scores are 0-100ish; convert to a per-owner z-score
    # so the blend term is centered.  When the snapshot is empty, fall
    # through with all-zero z (no ROS influence).
    ros_values = list(ros_strength_map.values())
    ros_mean = statistics.fmean(ros_values) if ros_values else 0.0
    ros_sd = statistics.pstdev(ros_values) if len(ros_values) > 1 else 1.0
    if ros_sd <= 0:
        ros_sd = 1.0

    depth_ratios = _load_team_depth_ratios(league_key)

    # Best-ball pre-sim: when enabled, draw per-player weekly scores +
    # run greedy lineup optimization K=200 times per team to derive a
    # forward-looking weekly distribution that captures spike-week
    # upside the empirical history can't (bench depth, position
    # rotation, optimal start-sit decisions made for you).  The
    # resulting (mean, sd) replace the empirical distribution in the
    # matchup loop below.  When best_ball=False, this dict is empty
    # and the empirical/blended path runs unchanged.
    bestball_dists: dict[str, tuple[float, float]] = {}
    if best_ball:
        rosters = _load_team_rosters(league_key)
        # The league's OWN slots (D5): ``_load_starter_slots()`` with no key
        # resolves the DEFAULT league, so a non-default league's rosters were
        # solved against another league's lineup rules.
        starter_slots = _load_starter_slots(league_key)
        if rosters and starter_slots:
            presim_rng = random.Random(20260428)  # deterministic per league
            bestball_dists = _bestball_presim(rosters, starter_slots, presim_rng, points_model)
            LOG.info(
                "[ros] best-ball presim: %d teams, adaptive %d-%d weeks (points model: %s)",
                len(bestball_dists),
                BEST_BALL_PRESIM_MIN_WEEKS,
                BEST_BALL_PRESIM_MAX_WEEKS,
                (points_model or DEFAULT_POINTS_MODEL).source,
            )

    distributions: dict[str, _TeamDist] = {}
    pf_by_owner: dict[str, float] = {}
    for owner_id, scores in per_owner.items():
        emp_mean, emp_sd = _empirical_distribution(scores)
        basis = "empirical"
        if emp_mean <= 0:
            emp_mean, emp_sd = pool_mean, pool_sd
            basis = "pool"
        # Best-ball override: replace the empirical (mean, sd) with the
        # presim's per-player optimal-lineup distribution.  Falls back
        # to empirical when the presim couldn't run for this owner
        # (e.g. roster snapshot missing, no rosValues).
        if owner_id in bestball_dists:
            bb_mean, bb_sd = bestball_dists[owner_id]
            if bb_mean > 0:
                emp_mean, emp_sd = bb_mean, bb_sd
                basis = "presim"
        # Blend ROS strength as a multiplicative shift on the mean.
        ros_score = ros_strength_map.get(owner_id)
        if ros_score is not None and ros_sd > 0:
            ros_z = (ros_score - ros_mean) / ros_sd
            blended_mean = emp_mean * (1 + ROS_BLEND * ros_z)
        else:
            blended_mean = emp_mean
        variance_mult = _team_variance_multiplier(owner_id, depth_ratios, best_ball)
        sd = emp_sd * variance_mult if emp_sd > 0 else pool_sd * variance_mult
        distributions[owner_id] = _TeamDist(
            owner_id=owner_id,
            mean=max(0.0, blended_mean),
            sd=max(1.0, sd),
            pf_to_date=sum(scores),
            basis=basis,
        )
        pf_by_owner[owner_id] = sum(scores)
    return distributions, pf_by_owner


def _remaining_schedule(snapshot: PublicLeagueSnapshot) -> list[tuple[int, str, str]]:
    """Return (week, ownerA, ownerB) for every unplayed regular-season
    matchup in the current season.  Reuses the v1 helpers so this PR
    doesn't duplicate the schedule-inference logic.

    The v1 helper returns ``{week: [(ownerA, ownerB), ...]}``; flatten
    to the triple form the simulator iterates.
    """
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    if not seasons_sorted:
        return []
    season = seasons_sorted[-1]
    posted = playoff_odds._posted_future_matchups(season, snapshot.managers)
    out: list[tuple[int, str, str]] = []
    for week, pairs in posted.items():
        for owner_a, owner_b in pairs:
            out.append((int(week), owner_a, owner_b))
    return out


#: Public name for the posted-remaining-schedule reader both simulators use, so
#: a consumer outside this module (``src/ros/pick_forecast_snapshot.py``) does
#: not depend on a private helper. The private name stays for existing callers.
remaining_schedule = _remaining_schedule


def _current_record(
    snapshot: PublicLeagueSnapshot,
) -> dict[str, dict[str, float]]:
    """Wins/losses to date per owner — the HOST's record, median games
    included when the league counts them (D3)."""
    return _current_standings(snapshot)[0]


def _current_standings(
    snapshot: PublicLeagueSnapshot,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """``(record, standingsRule)`` for the simulated season — see
    :func:`src.public_league.playoff_odds.regular_season_standings_to_date`."""
    season = _simulated_season(snapshot)
    if season is None:
        return {}, playoff_odds.median_game_rule(None)
    return playoff_odds.regular_season_standings_to_date(season, snapshot.managers)


def _median_week_refusal(
    snapshot: PublicLeagueSnapshot,
    rule: dict[str, Any],
    schedule: list[tuple[int, str, str]],
    owners: list[str],
) -> dict[str, Any] | None:
    """Why the league's median game cannot be counted as the host counts it,
    or ``None`` when it can (or does not apply).

    A median game is a statistic of the WHOLE league's week, so it needs every
    team's score.  Three ways that fails, each named:

    * the median is ON but its threshold is unverified for this league's size
      (the host documents even-sized leagues only);
    * a FINISHED week lacks a score for some team (``unresolvedWeeks``);
    * a REMAINING posted week does not pair every team in the league with a
      score distribution, so its simulated median would be taken over a subset.

    Seeding without the median would publish a record the host does not keep
    (half the games), so each is a refusal — never a silent H2H-only answer.

    An UNKNOWN setting (``medianGame: None``) is refused too (#1712 review B):
    whether each week is one game or two is the record's definition, so
    seeding, playoff, title and draft-slot odds computed on either guess are
    unverified.  The record to date still publishes, labelled unverified, on
    the public section (``playoff_odds.compute_playoff_odds``).
    """
    if rule.get("medianGame") is None:
        return {
            "reason": rule.get("reason") or "median_setting_unknown",
            "detail": (
                "this league's settings do not say whether a weekly median game "
                "counts in the standings (league_average_match), so the record "
                "seeding and draft order rank on is undefined. Playoff, seed, "
                "title and draft-slot odds are not published. This is not a 0% "
                "chance for anyone."
            ),
        }
    if rule.get("medianGame") is not True:
        return None
    if rule.get("state") != playoff_odds.MEDIAN_COUNTED:
        return {"reason": rule.get("reason"), "detail": rule.get("detail")}
    if rule.get("unresolvedWeeks"):
        return {
            "reason": "median_game_week_unresolved",
            "weeks": list(rule["unresolvedWeeks"]),
            "detail": (
                "this league counts a weekly median game, but a finished week does "
                "not carry a score for every team, so that week's median result "
                "cannot be decided the way the host decided it. This is not a 0% "
                "chance for anyone."
            ),
        }
    season = _simulated_season(snapshot)
    team_count = playoff_odds._league_team_count(season)
    owner_set = set(owners)
    by_week: dict[int, set[str]] = {}
    for week, owner_a, owner_b in schedule:
        by_week.setdefault(week, set()).update((owner_a, owner_b))
    short = sorted(
        wk
        for wk, teams in by_week.items()
        if not teams <= owner_set or (team_count is not None and len(teams) != team_count)
    )
    if short:
        return {
            "reason": "median_game_week_unsimulable",
            "weeks": short,
            "detail": (
                "this league counts a weekly median game, but a remaining week does "
                "not pair every team with a score distribution, so its median "
                "cannot be simulated over the whole league. This is not a 0% "
                "chance for anyone."
            ),
        }
    return None


def _completed_games(row: Any) -> float:
    """Games this owner has actually played, from a record row.

    Written out rather than ``row.get("wins", 0) or 0`` because the
    distinction it is measuring IS the audit finding: a missing key
    means the season has not been observed, and collapsing that into a
    zero here would put us back where N-1 started.  A row with no usable
    numbers contributes nothing, which is the honest reading of it.
    """
    if not isinstance(row, dict):
        return 0.0
    total = 0.0
    for key in ("wins", "losses"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    return total


def _league_best_ball(league_key: str | None = None) -> bool:
    """Read a league's best_ball flag without forcing a
    PublicLeagueSnapshot dependency on caller side.  Lazy import so
    test fixtures that mock league_registry still work.

    ``league_key`` selects the league; ``None`` is the default league.
    It used to read the default league unconditionally, so a lazy
    rebuild for a non-default league inherited the default's format.
    """
    try:
        from src.api.league_registry import get_default_league, get_league_by_key  # noqa: PLC0415

        cfg = get_league_by_key(league_key) if league_key else get_default_league()
        return bool(cfg and cfg.best_ball)
    except Exception:  # noqa: BLE001
        return False


def _simulated_season(snapshot: Any) -> Any:
    """The season the simulator reads — the SAME selector as
    :func:`_current_record` and :func:`_remaining_schedule`."""
    seasons = list(getattr(snapshot, "seasons", None) or [])
    if not seasons:
        return None
    return sorted(seasons, key=lambda s: luck._season_sort_key(s.season))[-1]


def _season_year(snapshot: Any) -> int | None:
    """The simulated NFL season as a year."""
    season = _simulated_season(snapshot)
    try:
        return int(getattr(season, "season", None))
    except (TypeError, ValueError):
        return None


def _regular_season_progress(snapshot: Any, structure: Any) -> dict[str, Any]:
    """How much of the regular season is FINISHED, in the league's own weeks.

    Counted in weeks, not games: the regular season is weeks
    ``1 .. playoff_week_start - 1`` (the league's own settings), and a week
    counts only when it is in the canonical finished-week set
    (``playoff_odds._final_week_set``) — the same gate the record uses.  It is
    deliberately NOT inferred from an empty remaining schedule: future
    matchups that failed to post (or whose owners did not resolve) also leave
    the schedule empty, and that is not a finished season.  An unknown
    ``playoff_week_start`` answers ``None`` throughout — unknown, not zero.
    """
    week_start = getattr(structure, "week_start", None)
    season = _simulated_season(snapshot)
    if not isinstance(week_start, int) or week_start < 2 or season is None:
        return {"weeksTotal": None, "weeksFinal": None, "complete": None}
    total = week_start - 1
    final_weeks = playoff_odds._final_week_set(season)
    done = sum(1 for wk in range(1, total + 1) if wk in final_weeks)
    return {"weeksTotal": total, "weeksFinal": done, "complete": done >= total}


def _summary(samples: list[float]) -> dict[str, float] | None:
    """Mean and 10th/50th/90th percentiles of a simulated quantity."""
    if not samples:
        return None
    xs = sorted(samples)
    n = len(xs)

    def pct(q: float) -> float:
        return xs[min(n - 1, max(0, int(round(q * (n - 1)))))]

    return {
        "mean": round(sum(xs) / n, 2),
        "p10": round(pct(0.10), 2),
        "p50": round(pct(0.50), 2),
        "p90": round(pct(0.90), 2),
    }


#: Placement given to every loser of the round that leaves two teams standing
#: (the semifinal), and the size of the field from which a team counts as a
#: semifinalist / finalist.  These are the definitions the retired second
#: championship loop (``src/ros/championship.py`` before C5-PLAY-01) published
#: ``semifinalOdds`` / ``finalsOdds`` / ``expectedFinish`` under; they are
#: RECORDED here off this engine's own bracket so the surfaces that show those
#: columns keep their meaning while reading the one canonical simulation.
_SEMIFINAL_TEAMS_LEFT = 4
_FINAL_TEAMS_LEFT = 2
_SEMIFINAL_LOSER_PLACEMENT = 3


def _record_round(
    placements: dict[str, dict[str, int]],
    entrants: list[str],
    losers: list[str],
    survivors_after: int,
) -> None:
    """Record one bracket round into ``placements`` (no randomness).

    ``entrants`` reached a round of ``len(entrants)`` teams; ``losers`` (in
    game order) went out in it.  Placement convention, unchanged from the
    retired championship loop: the final's loser is 2nd, BOTH semifinal losers
    are 3rd, and losers of any earlier round take the next places in game order
    (round-one losers of a 7-team bracket are 5th, 6th, 7th).
    """
    size = len(entrants)
    for owner in entrants:
        slot = placements.setdefault(owner, {})
        slot["field"] = min(slot.get("field", size), size)
    for k, owner in enumerate(losers):
        if survivors_after == 1:
            place = 2
        elif survivors_after == _FINAL_TEAMS_LEFT:
            place = _SEMIFINAL_LOSER_PLACEMENT
        else:
            place = survivors_after + 1 + k
        placements[owner]["place"] = place


def _bracket_order(slots: int) -> list[int]:
    """Seeds 1..``slots`` in standard single-elimination bracket order.

    ``[1, 4, 2, 3]`` for four, ``[1, 8, 4, 5, 2, 7, 3, 6]`` for eight:
    adjacent entries meet, and the winners keep the order.  This is the
    fixed bracket Sleeper generates when ``playoff_seed_type`` is ``0``
    (see ``src/public_league/playoff_structure.py``).  ``slots`` must be a
    power of two — a fixed bracket is padded to one by its byes.
    """
    if slots < 1 or slots & (slots - 1):
        raise ValueError(f"a fixed bracket needs a power-of-two field, got {slots}")
    order = [1]
    while len(order) < slots:
        size = len(order) * 2
        order = [x for s in order for x in (s, size + 1 - s)]
    return order


def _fixed_bracket_refusal(field: int, byes: int | None) -> dict[str, Any] | None:
    """Why a FIXED bracket of ``field`` teams with ``byes`` byes cannot be
    played as the host plays it, or ``None`` when it can.

    After round one a fixed bracket must hold a power-of-two field
    (:func:`_bracket_order`).  A host-valid bracket always does; one that does
    not is missing teams (fewer seeded teams have a score distribution than
    the bracket has slots — #1699 review F1: four owners in a six-team, two-bye
    bracket) or is a shape the host does not generate.  Either way the answer
    is a named refusal, never an exception from inside the Monte Carlo.
    """
    if field <= 1:
        return None
    if byes is None:
        # Without the league's bye count there is no bracket to fill.
        return {
            "reason": "fixed_bracket_byes_unknown",
            "fieldTeams": field,
            "byeSeeds": None,
            "detail": (
                "this league's playoff bracket is fixed, but its settings do not say "
                "how many seeds get a bye, so the bracket cannot be played as the "
                "host plays it. This is not a 0% chance for anyone."
            ),
        }
    byes = max(0, min(byes, field))
    after_round_one = byes + (field - byes + 1) // 2
    if after_round_one & (after_round_one - 1) == 0:
        return None
    return {
        "reason": "fixed_bracket_field_unplayable",
        "fieldTeams": field,
        "byeSeeds": byes,
        "detail": (
            f"this league's playoff bracket is fixed (it does not re-seed), and "
            f"{field} seeded team(s) with {byes} bye(s) do not fill it the way the "
            "host builds it, so the bracket cannot be played as the host plays it. "
            "Playoff, bye and seed odds are unaffected; championship, finals and "
            "semifinal odds are not published. This is not a 0% chance for anyone."
        ),
    }


def _simulate_bracket(
    seeded: list[str],
    distributions: dict[str, _TeamDist],
    bye_seeds: int,
    rng: random.Random,
    placements: dict[str, dict[str, int]] | None = None,
    *,
    reseed: bool = True,
) -> str | None:
    """Play a seeded single-elimination bracket; return the champion.

    Standard fantasy structure: the top ``bye_seeds`` teams sit out
    round one and the rest play highest-vs-lowest.  After round one the
    league's own ``playoff_seed_type`` decides the pairings (C5-PLAY-01
    review B2): ``reseed=True`` — the surviving top seed always faces the
    surviving bottom seed, every round; ``reseed=False`` — a FIXED bracket
    (:func:`_bracket_order`), where a round-one winner takes its higher
    seed's slot and pairings are never redrawn (six teams: 1 vs
    winner(4/5), 2 vs winner(3/6)).  Each game is one draw from each team's weekly
    distribution — the same distribution the regular-season loop uses,
    so a team's playoff strength and its regular-season strength cannot
    disagree.

    Ties re-draw rather than coin-flip: a fantasy playoff tie is broken
    by the host's own tiebreakers, and a coin flip would inject variance
    the seeding already resolved.  Capped to avoid a pathological loop
    on degenerate (zero-variance) distributions.

    ``placements`` (optional) is filled with each bracket team's smallest
    field reached (``"field"``) and final placement (``"place"``) — see
    :func:`_record_round`.  Recording draws NOTHING from ``rng``: the champion
    and every game are identical with or without it (pinned by
    ``tests/ros/test_one_playoff_engine.py``).
    """
    alive = [o for o in seeded if o in distributions]
    if not alive:
        return None
    if len(alive) == 1:
        if placements is not None:
            placements[alive[0]] = {"field": 1, "place": 1}
        return alive[0]
    if not reseed and _fixed_bracket_refusal(len(alive), bye_seeds) is not None:
        # #1699 review F1: an unfillable fixed bracket is not playable as the
        # host plays it.  ``simulate_playoff_odds`` checks this BEFORE drawing
        # and publishes the named refusal; a direct caller gets no champion
        # (and no draws) rather than a ``ValueError`` from ``_bracket_order``.
        return None

    def _play(a: str, b: str) -> str:
        da, db = distributions[a], distributions[b]
        for _ in range(8):
            sa = max(0.0, rng.gauss(da.mean, da.sd))
            sb = max(0.0, rng.gauss(db.mean, db.sd))
            if sa > sb:
                return a
            if sb > sa:
                return b
        # Degenerate: identical deterministic distributions. The better
        # seed advances, which is what every host does.
        return a

    # Round one: byes advance automatically.
    byes = alive[:bye_seeds]
    contenders = alive[bye_seeds:]
    survivors = list(byes)
    losers: list[str] = []
    while len(contenders) >= 2:
        winner = _play(contenders[0], contenders[-1])
        survivors.append(winner)
        losers.append(contenders[-1] if winner == contenders[0] else contenders[0])
        contenders = contenders[1:-1]
    survivors.extend(contenders)  # odd bracket: the middle team advances
    if placements is not None:
        _record_round(placements, alive, losers, len(survivors))

    if not reseed:
        # Fixed bracket.  ``survivors`` is in slot order already: the byes
        # (slots 1..bye_seeds), then each round-one winner in the slot of
        # the higher seed it played (game k of round one is seed
        # bye_seeds + 1 + k).  Every later round pairs bracket neighbours
        # and the winner keeps the smaller slot.
        slotted = {i + 1: o for i, o in enumerate(survivors)}
        while len(slotted) > 1:
            order = _bracket_order(len(slotted))
            entrants = [slotted[s] for s in order]
            nxt_slots: dict[int, str] = {}
            losers = []
            for k in range(0, len(order), 2):
                a, b = slotted[order[k]], slotted[order[k + 1]]
                winner = _play(a, b)
                nxt_slots[min(order[k], order[k + 1])] = winner
                losers.append(b if winner == a else a)
            slotted = nxt_slots
            if placements is not None:
                _record_round(placements, entrants, losers, len(slotted))
        champion = next(iter(slotted.values()), None)
        if placements is not None and champion is not None:
            placements[champion] = {"field": 1, "place": 1}
        return champion

    # Re-seed and play down to one.
    seed_rank = {o: i for i, o in enumerate(alive)}
    while len(survivors) > 1:
        survivors.sort(key=lambda o: seed_rank.get(o, len(alive)))
        entrants = list(survivors)
        nxt: list[str] = []
        losers = []
        while len(survivors) >= 2:
            winner = _play(survivors[0], survivors[-1])
            nxt.append(winner)
            losers.append(survivors[-1] if winner == survivors[0] else survivors[0])
            survivors = survivors[1:-1]
        nxt.extend(survivors)
        survivors = nxt
        if placements is not None:
            _record_round(placements, entrants, losers, len(survivors))
    champion = survivors[0] if survivors else None
    if placements is not None and champion is not None:
        placements[champion] = {"field": 1, "place": 1}
    return champion


def simulate_playoff_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    n_simulations: int | None = None,
    playoff_seeds: int | None = None,
    bye_seeds: int | None = None,
    best_ball: bool | None = None,
    rng: random.Random | None = None,
    reseed: bool | None = None,
    min_simulations: int = MIN_SIMULATIONS,
    max_simulations: int = MAX_SIMULATIONS,
    odds_se_tolerance: float = ODDS_SE_TOLERANCE,
    points_model: PointsModel | None = None,
    distributions: dict[str, _TeamDist] | None = None,
) -> dict[str, Any]:
    """Run the Monte Carlo and return playoff/championship-relevant odds.

    Returns:
        {
          "playoffOdds": [{ownerId, displayName, playoffOdds, byeOdds,
                           topSeedOdds, expectedWins, medianFinalSeed,
                           mostLikelySeed, missPlayoffsOdds}],
          "n_simulations": int,
          "playoffSeeds": int,
          "byeSeeds": int,
          "rosStrengthAvailable": bool,
        }

    ``playoff_seeds`` / ``bye_seeds`` default to **the league's own
    bracket**, resolved by
    :func:`src.public_league.playoff_structure.resolve_playoff_structure`.
    They were hardcoded ``6`` and ``2`` until 2026-08-19 and no caller
    overrode them, so this engine simulated a six-seed bracket for a
    league that takes seven (V1-51).  An explicit value still wins —
    ``simulate_trade_impact`` pins both arms to the same bracket so the
    A/B is a comparison rather than two different leagues.

    A league that does not publish its bracket yields NO odds and an
    ``unsimulable`` block naming the reason, rather than odds computed
    under an assumed format.
    """
    rng = rng or random.Random()
    structure = resolve_playoff_structure(getattr(snapshot, "current_season", None))
    if playoff_seeds is None:
        playoff_seeds = structure.teams
    if bye_seeds is None:
        bye_seeds = structure.byes if structure.known else None
    # How the bracket is paired after round one is the LEAGUE'S rule
    # (``playoff_seed_type``, C5-PLAY-01 review B2).  Unknown fails closed:
    # qualifying, byes and seeds are still simulated (pairings do not affect
    # them); title / finals / semifinal / finish odds are not published.
    # An explicit ``reseed`` wins, exactly as an explicit ``playoff_seeds``
    # does — for hypotheticals that state their own bracket.
    if reseed is None and structure.seed_type is not None:
        reseed = structure.seed_type == SEED_TYPE_RESEED
    bracket_playable = reseed is not None
    model = points_model or load_points_model()
    # Team-strength rows are roster-derived and therefore leagueKey-scoped
    # (see team_strength.resolve_snapshot_league_key's docstring); without
    # this, every league's playoff sim read/wrote the SAME persisted
    # `team_strength/latest.json` regardless of which league was being
    # simulated.
    from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

    league_key = resolve_snapshot_league_key(snapshot)
    if best_ball is None:
        best_ball = _league_best_ball(league_key)

    # ``n_simulations`` pins an exact count (used by the trade-delta path
    # so both arms draw identically); otherwise the loop is adaptive.
    if n_simulations is not None:
        min_simulations = max_simulations = int(n_simulations)

    if playoff_seeds is None:
        # The league did not publish its bracket, so "made the playoffs"
        # has no definition here.  Refusing is the honest answer: the
        # retired default silently answered a question about a six-seed
        # league that this one is not.
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": None,
            "byeSeeds": None,
            "rosStrengthAvailable": ros_strength_available(_load_ros_strength_map(league_key)),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
            "playoffStructure": structure.to_dict(),
            "unsimulable": {
                "reason": structure.reason or "playoff_bracket_unknown",
                "detail": (
                    "this league's settings do not say how many teams make the "
                    "playoffs, so qualifying has no definition to simulate "
                    "against. This is not a 0% chance for anyone, and it is not "
                    "a six-team bracket."
                ),
            },
        }

    ros_map = _load_ros_strength_map(league_key)
    pf_by_owner: dict[str, float]
    if distributions is None:
        distributions, pf_by_owner = _build_team_distributions(
            snapshot, ros_map, league_key=league_key, best_ball=best_ball, points_model=model
        )
    else:
        _, pf_by_owner = _build_team_distributions(
            snapshot, ros_map, league_key=league_key, best_ball=best_ball, points_model=model
        )
    if not distributions:
        # No scored weeks exist for this league yet, so there is no
        # evidence to build a team score distribution from — the same
        # state `src.public_league.playoff_odds` and
        # `src.ros.championship` detect off the identical
        # `playoff_odds._season_weekly_scores` signal and both name
        # `no_scored_weeks_in_league` (V1-51: two engines must not
        # invent different words for one state). This branch used to
        # publish that state silently — n_simulations: 0 with no
        # unsimulable block — distinguishable from the two OTHER
        # refusal branches in this function only by the absence of a
        # name, not by any signal a caller could act on.
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "playoffStructure": structure.to_dict(),
            "rosStrengthAvailable": ros_strength_available(ros_map),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
            "unsimulable": {
                "reason": "no_scored_weeks_in_league",
                "detail": (
                    "no scored weeks exist for this league yet, so there is no "
                    "evidence to build a team score distribution from. This is "
                    "not a 0% chance for anyone."
                ),
            },
        }

    refusal = team_evidence_refusal(distributions, ros_map)
    if refusal is not None:
        # D1 (2026-09-26): no ROS evidence and teams with no distribution of
        # their own.  Publishing would present league-average coin flips as
        # each team's odds — see ``team_evidence_refusal``.
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "playoffStructure": structure.to_dict(),
            "rosStrengthAvailable": False,
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
            "unsimulable": refusal,
        }

    # The record as the HOST keeps it — median games included when the league
    # counts them (D3) — and the rule that says so, which every payload carries.
    record, standings_rule = _current_standings(snapshot)
    schedule = _remaining_schedule(snapshot)
    owners = sorted(distributions.keys())
    median_counted = standings_rule.get("state") == playoff_odds.MEDIAN_COUNTED

    median_refusal = _median_week_refusal(snapshot, standings_rule, schedule, owners)
    if median_refusal is not None:
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "playoffStructure": structure.to_dict(),
            "standingsRule": standings_rule,
            "rosStrengthAvailable": ros_strength_available(ros_map),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
            "unsimulable": median_refusal,
        }

    # #1699 review F1: a FIXED bracket the seeded field cannot fill is not
    # played (named reason), rather than raising inside the Monte Carlo.
    fixed_refusal = (
        _fixed_bracket_refusal(min(playoff_seeds, len(owners)), bye_seeds)
        if bracket_playable and not reseed
        else None
    )
    if fixed_refusal is not None:
        bracket_playable = False

    # AUDIT N-1 — with no remaining schedule the loop below draws no
    # games, so every "simulation" replays the current standings and
    # each team lands on exactly 1.0 or 0.0. Measured on the live cache:
    # playoffOdds were [1.0 x6, 0.0 x2], stamped ``converged: true`` on
    # 2000 simulations, in AUGUST, before a single 2026 game.
    #
    # There are two ways to have no games left, and they are opposites:
    #   * the season FINISHED — the outcome is known, and 1.0/0.0 is a
    #     fact rather than a projection;
    #   * no season has STARTED (or none is loaded) — nothing has been
    #     played and nothing is scheduled, so there is no evidence at
    #     all, and 1.0/0.0 is fabricated certainty.
    # Only the second is a defect, so they are distinguished by whether
    # any games have actually been played rather than by refusing both.
    games_played = sum(_completed_games(r) for r in record.values())
    if not schedule and games_played <= 0:
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "playoffStructure": structure.to_dict(),
            "rosStrengthAvailable": ros_strength_available(ros_map),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
            # Not ``converged``. Nothing was simulated, so there is
            # nothing for a consumer to be confident about — and the
            # trade-deadline classifier reads the empty list and reports
            # every team as "Insufficient evidence" rather than turning
            # a 0.0 into "Seller" (audit N-2).
            "unsimulable": {
                "reason": "no_games_played_and_none_scheduled",
                "detail": (
                    "no regular-season games have been played and none remain "
                    "on the schedule, so playoff odds cannot be projected. This "
                    "is not a 0% chance."
                ),
            },
        }

    seed_counts: dict[str, list[int]] = {o: [0] * len(owners) for o in owners}
    playoff_count: dict[str, int] = {o: 0 for o in owners}
    bye_count: dict[str, int] = {o: 0 for o in owners}
    top_seed_count: dict[str, int] = {o: 0 for o in owners}
    miss_count: dict[str, int] = {o: 0 for o in owners}
    wins_total: dict[str, float] = {o: 0.0 for o in owners}

    champ_count: dict[str, int] = {o: 0 for o in owners}
    finals_count: dict[str, int] = {o: 0 for o in owners}
    semis_count: dict[str, int] = {o: 0 for o in owners}
    finish_total: dict[str, float] = {o: 0.0 for o in owners}
    completed = 0

    # Rookie-draft slot distribution under the league's CANONICAL draft-order
    # rule (src/public_league/draft_order.py), applied to each simulation's
    # final regular-season wins and Points For.  A league with no recorded
    # rule gets none — never an assumed order.
    from src.public_league.draft_order import (  # noqa: PLC0415
        draft_order,
        league_draft_order_rule,
    )

    draft_rule = league_draft_order_rule(league_key)
    # Its own stream, cloned from the main rng's state without consuming it,
    # so publishing slots leaves every playoff/championship draw unchanged.
    draft_rng = random.Random()
    draft_rng.setstate(rng.getstate())
    # A recorded tie is half a win — the ``wins + 0.5 * ties`` key
    # ``_regular_season_record_to_date`` documents and the host's standings
    # use (C5-PLAY-01 review B3; spec §5 lists ties as an input).  It now
    # starts ``sim_wins``, so SEEDING, the bracket and the draft order all
    # read one record.  Until this review it was added only on the
    # draft-order path, so a 3-0-1 team was seeded as 3-1 — and the draft
    # order's separate add-back is removed with it, or the tie would count
    # twice there.
    tie_credit: dict[str, float] = {}
    for o in owners:
        ties = (record.get(o) or {}).get("ties")
        tie_credit[o] = (
            0.5 * float(ties)
            if isinstance(ties, (int, float)) and not isinstance(ties, bool)
            else 0.0
        )
    draft_slot_counts: dict[str, list[int]] = {o: [0] * len(owners) for o in owners}
    final_wins_samples: dict[str, list[float]] = {o: [] for o in owners}
    final_pf_samples: dict[str, list[float]] = {o: [] for o in owners}

    # DRAFT ORDER keeps its own record basis (#1712 review A).  The owner's
    # rule (docs/picks/DRAFT_ORDER_RULE.md) is "reverse final regular-season
    # record, ties half a win"; it does not say whether median-game results
    # count, and the league's own draft history does not settle it (the 2025
    # rookie draft matches reverse record neither with nor without them — see
    # that document).  So seeding and the published record use the host's
    # official standings (median included), while draft order stays on the
    # pre-D3 basis — head-to-head results with half-win ties — and says so in
    # ``draftOrderRecordBasis``.  With the median off the two are identical.
    draft_base: dict[str, float] = {}
    for o in owners:
        row = record.get(o) or {}
        median_w = row.get("medianWins", 0)
        median_t = row.get("medianTies", 0)
        draft_base[o] = (
            float(row.get("wins", 0)) - float(median_w) + tie_credit[o] - 0.5 * float(median_t)
        )

    # The schedule grouped by week, weeks and pairs in their own order, so the
    # draws happen in exactly the sequence they always have: with the median
    # game off the RNG stream — and therefore every published number — is
    # unchanged.
    schedule_by_week: dict[int, list[tuple[str, str]]] = {}
    for week, owner_a, owner_b in schedule:
        schedule_by_week.setdefault(week, []).append((owner_a, owner_b))

    for sim_i in range(max_simulations):
        completed = sim_i + 1
        sim_wins: dict[str, float] = {
            o: float(record.get(o, {}).get("wins", 0)) + tie_credit[o] for o in owners
        }
        draft_wins: dict[str, float] = dict(draft_base)
        sim_pf: dict[str, float] = {o: float(pf_by_owner.get(o, 0.0)) for o in owners}
        for _week, pairs in schedule_by_week.items():
            week_scores: dict[str, float] = {}
            for owner_a, owner_b in pairs:
                dist_a = distributions.get(owner_a)
                dist_b = distributions.get(owner_b)
                if dist_a is None or dist_b is None:
                    continue
                score_a = max(0.0, rng.gauss(dist_a.mean, dist_a.sd))
                score_b = max(0.0, rng.gauss(dist_b.mean, dist_b.sd))
                sim_pf[owner_a] = sim_pf.get(owner_a, 0.0) + score_a
                sim_pf[owner_b] = sim_pf.get(owner_b, 0.0) + score_b
                if score_a > score_b:
                    sim_wins[owner_a] = sim_wins.get(owner_a, 0.0) + 1
                    draft_wins[owner_a] = draft_wins.get(owner_a, 0.0) + 1
                elif score_b > score_a:
                    sim_wins[owner_b] = sim_wins.get(owner_b, 0.0) + 1
                    draft_wins[owner_b] = draft_wins.get(owner_b, 0.0) + 1
                else:
                    sim_wins[owner_a] = sim_wins.get(owner_a, 0.0) + 0.5
                    sim_wins[owner_b] = sim_wins.get(owner_b, 0.0) + 0.5
                    draft_wins[owner_a] = draft_wins.get(owner_a, 0.0) + 0.5
                    draft_wins[owner_b] = draft_wins.get(owner_b, 0.0) + 0.5
                week_scores[owner_a] = score_a
                week_scores[owner_b] = score_b
            if median_counted and week_scores:
                # D3: the week's second game, against the league median of THIS
                # draw's scores — Game Day's host-verified threshold, no extra
                # randomness.  Exactly on the median is a tie (half a win).
                threshold = median_threshold(list(week_scores.values()))
                for owner, score in week_scores.items():
                    if score > threshold:
                        sim_wins[owner] = sim_wins.get(owner, 0.0) + 1
                    elif score == threshold:
                        sim_wins[owner] = sim_wins.get(owner, 0.0) + 0.5

        # Standings order comes from the CANONICAL owner, not a local sort.
        # This used to be a two-key ``sorted(owners, key=(-wins, -pf))``, and
        # the third key was implicit: Python's sort is stable and ``owners``
        # is ``sorted(distributions.keys())``, so exact ties resolved in
        # ALPHABETICAL ownerId order.  Renaming an owner is not a football
        # event.  ``rng`` is passed explicitly per W19-F008 — see the guard in
        # tests/ros/test_standings_tiebreak.py.
        ranked = playoff_odds.standings_from_sim(sim_wins, sim_pf, owners, rng=rng)
        if draft_rule is not None:
            # ``draft_wins`` carries the recorded half-wins (B3) and the
            # head-to-head results only — ``draftOrderRecordBasis`` (#1712 A).
            record_wins = draft_wins
            for slot_i, owner in enumerate(
                draft_order(record_wins, sim_pf, owners, rng=draft_rng).order
            ):
                draft_slot_counts[owner][slot_i] += 1
            for owner in owners:
                final_wins_samples[owner].append(record_wins[owner])
                final_pf_samples[owner].append(sim_pf.get(owner, 0.0))
        for i, owner in enumerate(ranked):
            seed_counts[owner][i] += 1
            wins_total[owner] += sim_wins.get(owner, 0.0)
            if i < playoff_seeds:
                playoff_count[owner] += 1
            else:
                miss_count[owner] += 1
            if i < bye_seeds:
                bye_count[owner] += 1
            if i == 0:
                top_seed_count[owner] += 1

        # Championship: play the seeded bracket out on THIS sim's team
        # distributions.  Previously the module reported seeding odds
        # only and no championship probability existed anywhere — the
        # trade-delta contract (§17.3) requires one.
        # An unknown host seeding rule (B2) plays no bracket: no title /
        # finals / semifinal / finish odds exist for this run.
        placements: dict[str, dict[str, int]] = {}
        champion = (
            _simulate_bracket(
                ranked[:playoff_seeds],
                distributions,
                bye_seeds,
                rng,
                placements,
                reseed=bool(reseed),
            )
            if bracket_playable
            else None
        )
        if champion:
            champ_count[champion] += 1
        # Bracket depth + final placement, recorded off THIS draw's bracket
        # (C5-PLAY-01): the /league Championship tab's finals / semifinal /
        # expected-finish columns used to come from a second, independent
        # Monte Carlo in ``championship.py``.  A team outside the bracket
        # finishes at its regular-season seed.
        for i, owner in enumerate(ranked):
            slot = placements.get(owner)
            if slot is None:
                finish_total[owner] += i + 1
                continue
            finish_total[owner] += slot["place"]
            if slot["field"] <= _FINAL_TEAMS_LEFT:
                finals_count[owner] += 1
            if slot["field"] <= _SEMIFINAL_TEAMS_LEFT:
                semis_count[owner] += 1

        # Convergence: stop once every team's playoff-odds standard
        # error is inside tolerance.  Checked on a cadence and never
        # before the floor, so a lopsided league cannot exit early on a
        # handful of draws.
        if completed >= min_simulations and completed % SIM_CHECK_EVERY == 0:
            worst_se = max(_proportion_se(playoff_count[o] / completed, completed) for o in owners)
            if worst_se <= odds_se_tolerance:
                break

    out: list[dict[str, Any]] = []
    for owner in owners:
        seed_dist = seed_counts[owner]
        n_safe = max(1, completed)
        # Median final seed: cumulative threshold at half the sims.
        cumulative = 0
        median_seed = len(owners)
        for i, count in enumerate(seed_dist):
            cumulative += count
            if cumulative >= n_safe / 2:
                median_seed = i + 1
                break
        most_likely_seed = seed_dist.index(max(seed_dist)) + 1
        po_lo, po_hi = _wilson_interval(playoff_count[owner], n_safe)
        ch_lo, ch_hi = _wilson_interval(champ_count[owner], n_safe)
        bracket_fields: dict[str, Any] = (
            {
                "championshipOdds": round(champ_count[owner] / n_safe, 4),
                "championshipOddsCi": [round(ch_lo, 4), round(ch_hi, 4)],
                "finalsOdds": round(finals_count[owner] / n_safe, 4),
                "semifinalOdds": round(semis_count[owner] / n_safe, 4),
                "expectedFinish": round(finish_total[owner] / n_safe, 2),
            }
            if bracket_playable
            # Missing, never 0: no bracket was played (see
            # ``championshipUnavailable`` on the payload).
            else dict.fromkeys(
                (
                    "championshipOdds",
                    "championshipOddsCi",
                    "finalsOdds",
                    "semifinalOdds",
                    "expectedFinish",
                )
            )
        )
        out.append(
            {
                "ownerId": owner,
                "displayName": metrics.display_name_for(snapshot, owner),
                "playoffOdds": round(playoff_count[owner] / n_safe, 4),
                "playoffOddsCi": [round(po_lo, 4), round(po_hi, 4)],
                **bracket_fields,
                "byeOdds": round(bye_count[owner] / n_safe, 4),
                "topSeedOdds": round(top_seed_count[owner] / n_safe, 4),
                "missPlayoffsOdds": round(miss_count[owner] / n_safe, 4),
                "expectedWins": round(wins_total[owner] / n_safe, 2),
                "medianFinalSeed": median_seed,
                "mostLikelySeed": most_likely_seed,
                "seedDistribution": [c / n_safe for c in seed_dist],
                **(
                    {
                        "draftSlotDistribution": [c / n_safe for c in draft_slot_counts[owner]],
                        "finalWins": _summary(final_wins_samples[owner]),
                        "finalPointsFor": _summary(final_pf_samples[owner]),
                    }
                    if draft_rule is not None
                    else {}
                ),
            }
        )
    out.sort(key=lambda r: -r["playoffOdds"])
    worst_se = (
        max(_proportion_se(playoff_count[o] / max(1, completed), max(1, completed)) for o in owners)
        if owners
        else 0.0
    )
    unavailable_bracket: dict[str, Any] = {}
    if fixed_refusal is not None:
        unavailable_bracket = {"championshipUnavailable": fixed_refusal}
    elif not bracket_playable:
        unavailable_bracket = {
            "championshipUnavailable": {
                "reason": structure.seed_type_reason or "playoff_seed_type_unknown",
                "detail": (
                    "this league's settings do not say whether its playoff bracket "
                    "re-seeds each round or is fixed, so the bracket cannot be played "
                    "as the host plays it. Playoff, bye and seed odds are unaffected; "
                    "championship, finals and semifinal odds are not published. This "
                    "is not a 0% chance for anyone."
                ),
            }
        }
    return {
        "playoffOdds": out,
        **unavailable_bracket,
        "n_simulations": completed,
        "converged": worst_se <= odds_se_tolerance,
        "worstPlayoffOddsSe": round(worst_se, 5),
        "oddsSeTolerance": odds_se_tolerance,
        "playoffSeeds": playoff_seeds,
        "byeSeeds": bye_seeds,
        "playoffStructure": structure.to_dict(),
        # Whether the record, every simulated week, seeding and draft order
        # count the league's weekly median game (D3) — and why not, when not.
        "standingsRule": standings_rule,
        "rosStrengthAvailable": ros_strength_available(ros_map),
        "rosBlend": ROS_BLEND,
        "bestBallVarianceBump": BEST_BALL_VARIANCE_BUMP,
        "bestBallVarianceMode": "depth_aware" if best_ball else "off",
        "pointsModelSource": model.source,
        "pointsModelGeneratedAt": model.generated_at,
        # Which draft-order rule produced ``draftSlotDistribution`` (None =
        # the league has no recorded rule, so no slot distribution exists).
        "draftOrderRule": draft_rule,
        # Which record ``draftSlotDistribution`` / ``finalWins`` rank on
        # (#1712 review A): head-to-head results with half-win ties, never the
        # median game, until the owner says the draft rule counts it.
        "draftOrderRecordBasis": DRAFT_ORDER_RECORD_BASIS if draft_rule is not None else None,
        "season": _season_year(snapshot),
        # Season progress in the league's own regular-season WEEKS — see
        # ``_regular_season_progress``.  ``None`` = unknown, never zero.
        "regularSeasonProgress": _regular_season_progress(snapshot, structure),
    }


# Cache TTL (seconds) for the on-disk sim output written by
# ``src.ros.scrape``.  Past this age the lazy builder falls back to a
# live re-run so a stale GitHub Actions schedule doesn't pin clients to
# week-old odds.  Default 6h aligns with the every-2h scrape cadence
# (3x headroom).
_SIM_CACHE_TTL_SEC = 6 * 3600


def _cached_payload_path(league_key: str | None) -> Any:
    """This league's playoff-sim cache file.

    File names are owned by the writer, ``src.ros.scrape._sim_paths``; the
    directory is this module's ``ROS_DATA_DIR`` so tests that relocate it
    keep reader and fixture in agreement.  Mirrors
    ``championship._cached_payload_path``.
    """
    from src.api.league_registry import default_league_key  # noqa: PLC0415
    from src.ros.scrape import _sim_paths  # noqa: PLC0415

    try:
        default_key = default_league_key()
    except Exception:  # noqa: BLE001 — registry trouble reads the default file
        default_key = None
    playoff_path, _ = _sim_paths(league_key, default_key)
    return ROS_DATA_DIR / "sims" / playoff_path.name


def _load_cached_payload(league_key: str | None = None) -> dict[str, Any] | None:
    """Read this league's cached playoff sim if fresh; else None.

    Used to read ``latest_playoff.json`` for every league (D5)."""
    import os

    path = _cached_payload_path(league_key)
    if not path.exists():
        return None
    try:
        age = os.path.getmtime(path)
    except OSError:
        return None
    import time

    if (time.time() - age) > _SIM_CACHE_TTL_SEC:
        LOG.info("[ros] playoff cache stale (>%ds); rerunning sim", _SIM_CACHE_TTL_SEC)
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        LOG.warning("[ros] playoff cache unreadable (%s); rerunning sim", exc)
        return None


# ── Trade impact on shared seeds (spec §17.3) ──────────────────────


@dataclass(frozen=True)
class OddsDelta:
    """One team's before/after odds movement, with an honest error bar."""

    owner_id: str
    display_name: str
    before: float
    after: float
    delta: float
    delta_ci: tuple[float, float]
    significant: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "displayName": self.display_name,
            "before": round(self.before, 4),
            "after": round(self.after, 4),
            "delta": round(self.delta, 4),
            "deltaCi": [round(self.delta_ci[0], 4), round(self.delta_ci[1], 4)],
            "significant": self.significant,
        }


def _paired_delta_ci(
    before_hits: int,
    after_hits: int,
    n: int,
    z: float = 1.96,
) -> tuple[float, float]:
    """Interval for a paired proportion difference on SHARED seeds.

    Both arms are driven by the same RNG stream, so their sampling
    errors are strongly positively correlated and an unpaired interval
    (which adds the variances) would be far too wide — it would call a
    real trade effect "not significant" simply because each arm's
    absolute odds are noisy.

    We do not observe the per-simulation discordance counts here, so we
    take the CONSERVATIVE paired bound: treat the number of discordant
    pairs as at most ``before_hits + after_hits − 2·min(...)``, i.e. the
    largest discordance consistent with the observed marginals.  That
    over-states the interval slightly, which is the correct direction to
    err — this function exists to stop us calling noise a result.
    """
    if n <= 0:
        return (0.0, 0.0)
    # Max possible discordant pairs given the marginals.
    b_plus_c = min(n, abs(after_hits - before_hits) + 2 * min(before_hits, n - after_hits))
    b_plus_c = max(abs(after_hits - before_hits), min(b_plus_c, n))
    if b_plus_c <= 0:
        return (0.0, 0.0)
    d = (after_hits - before_hits) / n
    # McNemar-style SE on the discordant pairs.
    se = math.sqrt(b_plus_c) / n
    return (d - z * se, d + z * se)


#: Stated once so every return path — including the refusals — carries
#: the same explanation.
_TRADE_IMPACT_METHODOLOGY = (
    "Both arms run on one shared RNG seed and an identical simulation "
    "count, so the reported delta is the trade's effect rather than the "
    "difference between two independent Monte Carlo runs. Intervals are "
    "paired (McNemar-style, conservative on the discordant-pair count). "
    "A delta whose interval spans zero is flagged significant=false and "
    "must not be presented as a result."
)


def simulate_trade_impact(
    snapshot: PublicLeagueSnapshot,
    *,
    strength_delta: dict[str, float],
    n_simulations: int = DEFAULT_SIMULATIONS,
    playoff_seeds: int | None = None,
    bye_seeds: int | None = None,
    best_ball: bool | None = None,
    seed: int = 20260726,
    points_model: PointsModel | None = None,
    reseed: bool | None = None,
) -> dict[str, Any]:
    """Playoff/championship odds movement from a proposed trade.

    ``strength_delta`` maps ownerId → change in that team's weekly
    scoring MEAN (in the same units the distributions use).  A trade is
    zero-sum across its participants; this function does not enforce
    that, because a three-way trade or a waiver add legitimately is not.

    **Shared seeds (§17.3).**  Both arms run on the SAME RNG seed and
    the SAME number of simulations, so every simulated week draws the
    same underlying randomness before and after.  The difference is
    therefore the trade's effect, not the difference between two
    independent Monte Carlo runs.  Running the arms independently at
    10k sims each would put roughly ±1pp of pure noise on every delta —
    the same order as the effect being measured, which is how you end up
    confidently reporting a sign that flips on re-run.

    **Refusing to over-claim.**  Every delta carries a paired confidence
    interval, and ``significant`` is False whenever that interval spans
    zero.  Callers that render a delta MUST respect the flag: the spec
    is explicit that a delta smaller than simulation error is not a
    result.  ``meaningfulDeltas`` pre-filters for exactly that.

    Returns::

        {
          "playoff":      [OddsDelta...],   # sorted by |delta| desc
          "championship": [OddsDelta...],
          "meaningfulDeltas": int,          # count across both metrics
          "nSimulations": int,
          "sharedSeed": int,
          "pointsModelSource": str,
        }
    """
    model = points_model or load_points_model()
    # Team-strength rows are roster-derived and therefore leagueKey-scoped
    # (see team_strength.resolve_snapshot_league_key's docstring).
    from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

    league_key = resolve_snapshot_league_key(snapshot)
    if best_ball is None:
        best_ball = _league_best_ball(league_key)
    ros_map = _load_ros_strength_map(league_key)

    # Resolve ONCE and pass to both arms explicitly (V1-51).  Letting each
    # arm resolve independently would be equivalent today and is exactly
    # the seam a future league-aware change could split — and two arms on
    # different brackets would measure the bracket, not the trade.  The
    # shared-seed argument above applies to the league's rules as much as
    # to the RNG.
    structure = resolve_playoff_structure(getattr(snapshot, "current_season", None))
    if playoff_seeds is None:
        playoff_seeds = structure.teams
    if bye_seeds is None:
        bye_seeds = structure.byes if structure.known else None
    if playoff_seeds is None:
        return {
            "playoff": [],
            "championship": [],
            "meaningfulDeltas": 0,
            "nSimulations": 0,
            "sharedSeed": seed,
            "pointsModelSource": model.source,
            "playoffStructure": structure.to_dict(),
            # The full envelope, not a stub.  A refusal that drops keys the
            # normal return carries makes every consumer branch on shape
            # before it can read anything — and ``methodology`` is exactly
            # the field a caller reads to explain why there is no result.
            "note": "playoff bracket unknown",
            "methodology": _TRADE_IMPACT_METHODOLOGY,
            "unsimulable": {
                "reason": structure.reason or "playoff_bracket_unknown",
                "detail": (
                    "this league's settings do not say how many teams make the "
                    "playoffs, so a trade's effect on qualifying has nothing to "
                    "be measured against. This is not a zero-impact trade."
                ),
            },
        }

    base_dists, _ = _build_team_distributions(
        snapshot, ros_map, league_key=league_key, best_ball=best_ball, points_model=model
    )
    if not base_dists:
        return {
            "playoff": [],
            "championship": [],
            "meaningfulDeltas": 0,
            "nSimulations": 0,
            "sharedSeed": seed,
            "pointsModelSource": model.source,
            "note": "no team distributions available",
            "methodology": _TRADE_IMPACT_METHODOLOGY,
        }

    after_dists = {
        owner: _TeamDist(
            owner_id=d.owner_id,
            mean=max(0.0, d.mean + float(strength_delta.get(owner, 0.0))),
            sd=d.sd,
            pf_to_date=d.pf_to_date,
            # Carried so both arms answer ``team_evidence_refusal`` alike;
            # a trade does not create evidence about a team.
            basis=d.basis,
        )
        for owner, d in base_dists.items()
    }

    # Identical seeds, identical counts — this is the whole point.
    before = simulate_playoff_odds(
        snapshot,
        n_simulations=n_simulations,
        playoff_seeds=playoff_seeds,
        bye_seeds=bye_seeds,
        best_ball=best_ball,
        rng=random.Random(seed),
        points_model=model,
        distributions=base_dists,
        reseed=reseed,
    )
    after = simulate_playoff_odds(
        snapshot,
        n_simulations=n_simulations,
        playoff_seeds=playoff_seeds,
        bye_seeds=bye_seeds,
        best_ball=best_ball,
        rng=random.Random(seed),
        points_model=model,
        distributions=after_dists,
        reseed=reseed,
    )

    before_by_owner = {r["ownerId"]: r for r in before.get("playoffOdds") or []}
    after_by_owner = {r["ownerId"]: r for r in after.get("playoffOdds") or []}
    n = int(after.get("n_simulations") or n_simulations)

    def _deltas(metric: str) -> list[OddsDelta]:
        rows: list[OddsDelta] = []
        for owner, b_row in before_by_owner.items():
            a_row = after_by_owner.get(owner)
            if a_row is None:
                continue
            b = float(b_row.get(metric) or 0.0)
            a = float(a_row.get(metric) or 0.0)
            lo, hi = _paired_delta_ci(round(b * n), round(a * n), n)
            rows.append(
                OddsDelta(
                    owner_id=owner,
                    display_name=b_row.get("displayName") or owner,
                    before=b,
                    after=a,
                    delta=a - b,
                    delta_ci=(lo, hi),
                    # Significant only when the interval excludes zero.
                    significant=(lo > 0.0) or (hi < 0.0),
                )
            )
        rows.sort(key=lambda r: -abs(r.delta))
        return rows

    playoff_rows = _deltas("playoffOdds")
    # No bracket was played when the league's seeding rule is unknown (B2):
    # there is no championship delta to report, and a missing title odd must
    # not enter ``_deltas`` as 0.
    champ_unavailable = before.get("championshipUnavailable")
    champ_rows = [] if champ_unavailable else _deltas("championshipOdds")
    meaningful = sum(1 for r in playoff_rows + champ_rows if r.significant)

    return {
        "playoff": [r.to_dict() for r in playoff_rows],
        "championship": [r.to_dict() for r in champ_rows],
        **({"championshipUnavailable": champ_unavailable} if champ_unavailable else {}),
        "meaningfulDeltas": meaningful,
        "nSimulations": n,
        "sharedSeed": seed,
        "pointsModelSource": model.source,
        "methodology": _TRADE_IMPACT_METHODOLOGY,
    }


#: Reason published beside ``n_simulations: None`` when the canonical
#: forecast carries no usable simulation count.  Shared by both adapter
#: surfaces (``championship``, public ``playoffOdds``) so one state has one word.
SIM_COUNT_MISSING = "canonical_forecast_simulation_count_missing"


def simulation_count(forecast: dict[str, Any]) -> int | None:
    """The canonical forecast's simulation count, or ``None`` when it does not
    carry a real non-negative integer.  Never coerced to ``0``: a count is a
    claim about work done (#943), and "no count was reported" is not
    "nothing was simulated"."""
    value = forecast.get("n_simulations")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


#: Row fields every current forecast carries for the Championship surface.
_BRACKET_ROW_FIELDS = ("championshipOdds", "finalsOdds", "semifinalOdds", "expectedFinish")


def cached_forecast_matches_snapshot(cached: dict[str, Any], snapshot: Any) -> bool:
    """Does a fresh-by-mtime cached forecast describe THIS snapshot's state?

    Fetched recently is not content fresh: the file's age says when it was
    written, not which finished week it simulated.  Every surface reads one
    forecast and lays the snapshot's own record beside it, so a forecast taken
    before the latest week finalised would sit next to a record that already
    counts that week.  Compared on the fields the forecast itself carries —
    season, finished regular-season weeks, bracket — each only when present
    (a refusal payload carries none of them and is accepted as before).
    """
    rows = cached.get("playoffOdds")
    if isinstance(rows, list) and any(
        not isinstance(r, dict) or any(f not in r for f in _BRACKET_ROW_FIELDS) for r in rows
    ):
        # Written before this engine recorded bracket depth: the
        # Championship surface would have to publish those columns as
        # missing, so the file is not this engine's current output.
        return False
    if isinstance(rows, list) and rows:
        # D3: a forecast that does not state its standings rule was simulated
        # before median games counted, and one whose rule differs from the
        # league's current settings describes a different record.  Either way
        # its odds would sit beside a record they were not computed from.
        cached_rule = cached.get("standingsRule")
        if not isinstance(cached_rule, dict):
            return False
        live_rule = playoff_odds.median_game_rule(_simulated_season(snapshot))
        if {k: v for k, v in cached_rule.items() if k != "unresolvedWeeks"} != live_rule:
            return False
    season = cached.get("season")
    if season is not None and season != _season_year(snapshot):
        return False
    structure = resolve_playoff_structure(getattr(snapshot, "current_season", None))
    cached_structure = cached.get("playoffStructure")
    if isinstance(cached_structure, dict) and cached_structure != structure.to_dict():
        return False
    progress = cached.get("regularSeasonProgress")
    if isinstance(progress, dict) and "weeksFinal" in progress:
        live = _regular_season_progress(snapshot, structure)
        if progress.get("weeksFinal") != live.get("weeksFinal"):
            return False
    return True


#: Live-run memo shared by every surface: ``(leagueKey, root id, snapshot
#: generated_at) -> payload``.  Without it, two sections asked about the same
#: snapshot on a cache miss would each draw their own Monte Carlo and publish
#: two different sets of numbers for one league and week — the defect this
#: module's consolidation exists to remove.  Bounded: one entry per league.
_LIVE_MEMO: dict[str | None, tuple[tuple[Any, Any], dict[str, Any]]] = {}
_LIVE_LOCKS: dict[str | None, threading.Lock] = {}
_LIVE_LOCKS_GUARD = threading.Lock()


def _live_lock(league_key: str | None) -> threading.Lock:
    """One lock per league, so one league's live run never queues another's."""
    with _LIVE_LOCKS_GUARD:
        return _LIVE_LOCKS.setdefault(league_key, threading.Lock())


def canonical_forecast(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """The ONE published playoff/title forecast for ``snapshot``'s league.

    The scheduled scrape's file when it is fresh AND describes this
    snapshot's state (:func:`cached_forecast_matches_snapshot`); otherwise a
    live :func:`simulate_playoff_odds` run, computed once per snapshot and
    shared by every caller (single-flight).  Always returns a private copy, so
    a surface reshaping it cannot alter what another surface reads.
    """
    from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

    league_key = resolve_snapshot_league_key(snapshot)
    cached = _load_cached_payload(league_key)
    if cached is not None and cached_forecast_matches_snapshot(cached, snapshot):
        cached["cached"] = True
        return cached
    identity = (
        getattr(snapshot, "root_league_id", None),
        getattr(snapshot, "generated_at", None),
    )
    if not identity[1]:
        # No snapshot identity, nothing to key a shared result on: a memo
        # here could hand one snapshot's forecast to another.
        payload = simulate_playoff_odds(snapshot)
        payload["cached"] = False
        return payload
    with _live_lock(league_key):
        hit = _LIVE_MEMO.get(league_key)
        if hit is None or hit[0] != identity:
            payload = simulate_playoff_odds(snapshot)
            payload["cached"] = False
            hit = (identity, payload)
            _LIVE_MEMO[league_key] = hit
    return copy.deepcopy(hit[1])


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosPlayoffOdds.

    The canonical forecast as-is — see :func:`canonical_forecast`.
    """
    return canonical_forecast(snapshot)
