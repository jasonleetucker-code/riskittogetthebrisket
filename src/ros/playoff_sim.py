"""ROS-driven playoff Monte Carlo.

Coexists with ``src.public_league.playoff_odds``; this version uses
ROS team-strength as the per-team weekly score MEAN, blended with the
team's empirical scoring distribution from the season snapshot.  The
v1 module uses purely empirical distributions — when ROS data is
available it provides a forward-looking signal that pure history
can't capture (rosters that just got stronger via trades, breakout
players, etc.).

Outputs match the v1 schema so the frontend can swap data sources
without a contract fork.

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

import json
import logging
import math
import random
import statistics
from dataclasses import dataclass
from typing import Any

from src.league_intel.sim_calibration import (
    DEFAULT_POINTS_MODEL,
    PointsModel,
    load_points_model,
)
from src.ros import ROS_DATA_DIR
from src.ros.lineup import (
    RosterPlayer,
    load_league_starter_slots,
    solve_optimal_assignment,
)
from src.public_league import luck, metrics, playoff_odds
from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.playoff_sim")


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

# Coefficient of variation per position for per-player weekly scores.
# Calibrated from public weekly-scoring datasets — high-variance
# positions (RB workload swings, WR target volatility) get larger
# CVs, while QBs are tighter week-to-week.  These coefficients
# combine with each player's rosValue to produce a per-player
# Gaussian (mean = rosValue/17 × game-mean scale, sd = mean × cv).
_PLAYER_CV_BY_POSITION: dict[str, float] = {
    "QB": 0.32,
    "RB": 0.55,
    "WR": 0.60,
    "TE": 0.65,
    "DL": 0.55,
    "DE": 0.55,
    "DT": 0.55,
    "EDGE": 0.55,
    "LB": 0.45,
    "DB": 0.50,
    "S": 0.50,
    "CB": 0.55,
}
_DEFAULT_PLAYER_CV = 0.55


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


def _load_team_depth_ratios() -> dict[str, float]:
    """Per-owner bench/starter score ratio from team-strength snapshot.

    Returns {} when the snapshot is missing — caller falls back to the
    flat ``BEST_BALL_VARIANCE_BUMP`` for every team.  Capped at 1.0
    (a bench worth more than the starting lineup is anomalous; clamp
    to keep the lift bounded).
    """
    path = ROS_DATA_DIR / "team_strength" / "latest.json"
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
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


def _load_team_rosters() -> dict[str, dict[str, Any]]:
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
    path = ROS_DATA_DIR / "team_strength" / "latest.json"
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
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


def _load_ros_strength_map() -> dict[str, float]:
    path = ROS_DATA_DIR / "team_strength" / "latest.json"
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(r.get("ownerId") or ""): float(r.get("teamRosStrength") or 0.0)
        for r in rows or []
        if r.get("ownerId")
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

    depth_ratios = _load_team_depth_ratios()

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
        rosters = _load_team_rosters()
        starter_slots = _load_starter_slots()
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
        if emp_mean <= 0:
            emp_mean, emp_sd = pool_mean, pool_sd
        # Best-ball override: replace the empirical (mean, sd) with the
        # presim's per-player optimal-lineup distribution.  Falls back
        # to empirical when the presim couldn't run for this owner
        # (e.g. roster snapshot missing, no rosValues).
        if owner_id in bestball_dists:
            bb_mean, bb_sd = bestball_dists[owner_id]
            if bb_mean > 0:
                emp_mean, emp_sd = bb_mean, bb_sd
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


def _current_record(
    snapshot: PublicLeagueSnapshot,
) -> dict[str, dict[str, float]]:
    """Wins/losses to date per owner."""
    seasons_sorted = sorted(snapshot.seasons, key=lambda s: luck._season_sort_key(s.season))
    if not seasons_sorted:
        return {}
    current = seasons_sorted[-1]
    return playoff_odds._regular_season_record_to_date(current, snapshot.managers)


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


def _league_best_ball() -> bool:
    """Read the default league's best_ball flag without forcing a
    PublicLeagueSnapshot dependency on caller side.  Lazy import so
    test fixtures that mock league_registry still work.
    """
    try:
        from src.api.league_registry import get_default_league  # noqa: PLC0415

        cfg = get_default_league()
        return bool(cfg and cfg.best_ball)
    except Exception:  # noqa: BLE001
        return False


def _simulate_bracket(
    seeded: list[str],
    distributions: dict[str, _TeamDist],
    bye_seeds: int,
    rng: random.Random,
) -> str | None:
    """Play a seeded single-elimination bracket; return the champion.

    Standard fantasy structure: the top ``bye_seeds`` teams sit out
    round one, the rest play highest-vs-lowest, and re-seeding applies
    each round (the surviving top seed always faces the surviving
    bottom seed).  Each game is one draw from each team's weekly
    distribution — the same distribution the regular-season loop uses,
    so a team's playoff strength and its regular-season strength cannot
    disagree.

    Ties re-draw rather than coin-flip: a fantasy playoff tie is broken
    by the host's own tiebreakers, and a coin flip would inject variance
    the seeding already resolved.  Capped to avoid a pathological loop
    on degenerate (zero-variance) distributions.
    """
    alive = [o for o in seeded if o in distributions]
    if not alive:
        return None
    if len(alive) == 1:
        return alive[0]

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
    while len(contenders) >= 2:
        survivors.append(_play(contenders[0], contenders[-1]))
        contenders = contenders[1:-1]
    survivors.extend(contenders)  # odd bracket: the middle team advances

    # Re-seed and play down to one.
    seed_rank = {o: i for i, o in enumerate(alive)}
    while len(survivors) > 1:
        survivors.sort(key=lambda o: seed_rank.get(o, len(alive)))
        nxt: list[str] = []
        while len(survivors) >= 2:
            nxt.append(_play(survivors[0], survivors[-1]))
            survivors = survivors[1:-1]
        nxt.extend(survivors)
        survivors = nxt
    return survivors[0] if survivors else None


def simulate_playoff_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    n_simulations: int | None = None,
    playoff_seeds: int = 6,
    bye_seeds: int = 2,
    best_ball: bool | None = None,
    rng: random.Random | None = None,
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
    """
    rng = rng or random.Random()
    if best_ball is None:
        best_ball = _league_best_ball()
    model = points_model or load_points_model()

    # ``n_simulations`` pins an exact count (used by the trade-delta path
    # so both arms draw identically); otherwise the loop is adaptive.
    if n_simulations is not None:
        min_simulations = max_simulations = int(n_simulations)

    ros_map = _load_ros_strength_map()
    pf_by_owner: dict[str, float]
    if distributions is None:
        distributions, pf_by_owner = _build_team_distributions(
            snapshot, ros_map, best_ball=best_ball, points_model=model
        )
    else:
        _, pf_by_owner = _build_team_distributions(
            snapshot, ros_map, best_ball=best_ball, points_model=model
        )
    if not distributions:
        return {
            "playoffOdds": [],
            "n_simulations": 0,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "rosStrengthAvailable": bool(ros_map),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
            "pointsModelSource": model.source,
        }

    record = _current_record(snapshot)
    schedule = _remaining_schedule(snapshot)
    owners = sorted(distributions.keys())

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
            "rosStrengthAvailable": bool(ros_map),
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
    completed = 0

    for sim_i in range(max_simulations):
        completed = sim_i + 1
        sim_wins: dict[str, float] = {o: float(record.get(o, {}).get("wins", 0)) for o in owners}
        sim_pf: dict[str, float] = {o: float(pf_by_owner.get(o, 0.0)) for o in owners}
        for week, owner_a, owner_b in schedule:
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
            elif score_b > score_a:
                sim_wins[owner_b] = sim_wins.get(owner_b, 0.0) + 1
            else:
                sim_wins[owner_a] = sim_wins.get(owner_a, 0.0) + 0.5
                sim_wins[owner_b] = sim_wins.get(owner_b, 0.0) + 0.5

        # Sort: wins desc, PF tiebreak desc.
        ranked = sorted(
            owners,
            key=lambda o: (-sim_wins.get(o, 0.0), -sim_pf.get(o, 0.0)),
        )
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
        champion = _simulate_bracket(ranked[:playoff_seeds], distributions, bye_seeds, rng)
        if champion:
            champ_count[champion] += 1

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
        out.append(
            {
                "ownerId": owner,
                "displayName": metrics.display_name_for(snapshot, owner),
                "playoffOdds": round(playoff_count[owner] / n_safe, 4),
                "playoffOddsCi": [round(po_lo, 4), round(po_hi, 4)],
                "championshipOdds": round(champ_count[owner] / n_safe, 4),
                "championshipOddsCi": [round(ch_lo, 4), round(ch_hi, 4)],
                "byeOdds": round(bye_count[owner] / n_safe, 4),
                "topSeedOdds": round(top_seed_count[owner] / n_safe, 4),
                "missPlayoffsOdds": round(miss_count[owner] / n_safe, 4),
                "expectedWins": round(wins_total[owner] / n_safe, 2),
                "medianFinalSeed": median_seed,
                "mostLikelySeed": most_likely_seed,
                "seedDistribution": [c / n_safe for c in seed_dist],
            }
        )
    out.sort(key=lambda r: -r["playoffOdds"])
    worst_se = (
        max(_proportion_se(playoff_count[o] / max(1, completed), max(1, completed)) for o in owners)
        if owners
        else 0.0
    )
    return {
        "playoffOdds": out,
        "n_simulations": completed,
        "converged": worst_se <= odds_se_tolerance,
        "worstPlayoffOddsSe": round(worst_se, 5),
        "oddsSeTolerance": odds_se_tolerance,
        "playoffSeeds": playoff_seeds,
        "byeSeeds": bye_seeds,
        "rosStrengthAvailable": bool(ros_map),
        "rosBlend": ROS_BLEND,
        "bestBallVarianceBump": BEST_BALL_VARIANCE_BUMP,
        "bestBallVarianceMode": "depth_aware" if best_ball else "off",
        "pointsModelSource": model.source,
        "pointsModelGeneratedAt": model.generated_at,
    }


# Cache TTL (seconds) for the on-disk sim output written by
# ``src.ros.scrape``.  Past this age the lazy builder falls back to a
# live re-run so a stale GitHub Actions schedule doesn't pin clients to
# week-old odds.  Default 6h aligns with the every-2h scrape cadence
# (3x headroom).
_SIM_CACHE_TTL_SEC = 6 * 3600


def _load_cached_payload() -> dict[str, Any] | None:
    """Read ``data/ros/sims/latest_playoff.json`` if fresh; else None."""
    import os

    path = ROS_DATA_DIR / "sims" / "latest_playoff.json"
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


def simulate_trade_impact(
    snapshot: PublicLeagueSnapshot,
    *,
    strength_delta: dict[str, float],
    n_simulations: int = DEFAULT_SIMULATIONS,
    playoff_seeds: int = 6,
    bye_seeds: int = 2,
    best_ball: bool | None = None,
    seed: int = 20260726,
    points_model: PointsModel | None = None,
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
    if best_ball is None:
        best_ball = _league_best_ball()
    model = points_model or load_points_model()
    ros_map = _load_ros_strength_map()

    base_dists, _ = _build_team_distributions(
        snapshot, ros_map, best_ball=best_ball, points_model=model
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
        }

    after_dists = {
        owner: _TeamDist(
            owner_id=d.owner_id,
            mean=max(0.0, d.mean + float(strength_delta.get(owner, 0.0))),
            sd=d.sd,
            pf_to_date=d.pf_to_date,
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
    champ_rows = _deltas("championshipOdds")
    meaningful = sum(1 for r in playoff_rows + champ_rows if r.significant)

    return {
        "playoff": [r.to_dict() for r in playoff_rows],
        "championship": [r.to_dict() for r in champ_rows],
        "meaningfulDeltas": meaningful,
        "nSimulations": n,
        "sharedSeed": seed,
        "pointsModelSource": model.source,
        "methodology": (
            "Both arms run on one shared RNG seed and an identical simulation "
            "count, so the reported delta is the trade's effect rather than the "
            "difference between two independent Monte Carlo runs. Intervals are "
            "paired (McNemar-style, conservative on the discordant-pair count). "
            "A delta whose interval spans zero is flagged significant=false and "
            "must not be presented as a result."
        ),
    }


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosPlayoffOdds.

    Prefers the cached output written by the scheduled scrape; falls
    back to a live Monte Carlo when the cache is missing or stale.
    """
    cached = _load_cached_payload()
    if cached is not None:
        cached["cached"] = True
        return cached
    payload = simulate_playoff_odds(snapshot)
    payload["cached"] = False
    return payload
