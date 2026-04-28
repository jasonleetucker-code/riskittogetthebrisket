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
import random
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from src.ros import ROS_DATA_DIR
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

DEFAULT_SIMULATIONS = 10000


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
    seasons_sorted = sorted(
        snapshot.seasons, key=luck._season_sort_key
    )
    if not seasons_sorted:
        return {}, {}
    current_season = seasons_sorted[-1]
    per_owner, pool = playoff_odds._season_weekly_scores(
        current_season, snapshot.managers
    )
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

    distributions: dict[str, _TeamDist] = {}
    pf_by_owner: dict[str, float] = {}
    for owner_id, scores in per_owner.items():
        emp_mean, emp_sd = _empirical_distribution(scores)
        if emp_mean <= 0:
            emp_mean, emp_sd = pool_mean, pool_sd
        # Blend ROS strength as a multiplicative shift on the mean.
        ros_score = ros_strength_map.get(owner_id)
        if ros_score is not None and ros_sd > 0:
            ros_z = (ros_score - ros_mean) / ros_sd
            blended_mean = emp_mean * (1 + ROS_BLEND * ros_z)
        else:
            blended_mean = emp_mean
        variance_mult = _team_variance_multiplier(
            owner_id, depth_ratios, best_ball
        )
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
    seasons_sorted = sorted(
        snapshot.seasons, key=luck._season_sort_key
    )
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
    seasons_sorted = sorted(
        snapshot.seasons, key=luck._season_sort_key
    )
    if not seasons_sorted:
        return {}
    current = seasons_sorted[-1]
    return playoff_odds._regular_season_record_to_date(
        current, snapshot.managers
    )


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


def simulate_playoff_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    n_simulations: int = DEFAULT_SIMULATIONS,
    playoff_seeds: int = 6,
    bye_seeds: int = 2,
    best_ball: bool | None = None,
    rng: random.Random | None = None,
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
    ros_map = _load_ros_strength_map()
    distributions, pf_by_owner = _build_team_distributions(
        snapshot, ros_map, best_ball=best_ball
    )
    if not distributions:
        return {
            "playoffOdds": [],
            "n_simulations": n_simulations,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "rosStrengthAvailable": bool(ros_map),
            "bestBallVarianceMode": "depth_aware" if best_ball else "off",
        }

    record = _current_record(snapshot)
    schedule = _remaining_schedule(snapshot)
    owners = sorted(distributions.keys())

    seed_counts: dict[str, list[int]] = {o: [0] * len(owners) for o in owners}
    playoff_count: dict[str, int] = {o: 0 for o in owners}
    bye_count: dict[str, int] = {o: 0 for o in owners}
    top_seed_count: dict[str, int] = {o: 0 for o in owners}
    miss_count: dict[str, int] = {o: 0 for o in owners}
    wins_total: dict[str, float] = {o: 0.0 for o in owners}

    for _ in range(n_simulations):
        sim_wins: dict[str, float] = {
            o: float(record.get(o, {}).get("wins", 0)) for o in owners
        }
        sim_pf: dict[str, float] = {
            o: float(pf_by_owner.get(o, 0.0)) for o in owners
        }
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

    out: list[dict[str, Any]] = []
    for owner in owners:
        seed_dist = seed_counts[owner]
        n_safe = max(1, n_simulations)
        # Median final seed: cumulative threshold at half the sims.
        cumulative = 0
        median_seed = len(owners)
        for i, count in enumerate(seed_dist):
            cumulative += count
            if cumulative >= n_safe / 2:
                median_seed = i + 1
                break
        most_likely_seed = seed_dist.index(max(seed_dist)) + 1
        out.append(
            {
                "ownerId": owner,
                "displayName": metrics.display_name_for(snapshot, owner),
                "playoffOdds": round(playoff_count[owner] / n_safe, 4),
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
    return {
        "playoffOdds": out,
        "n_simulations": n_simulations,
        "playoffSeeds": playoff_seeds,
        "byeSeeds": bye_seeds,
        "rosStrengthAvailable": bool(ros_map),
        "rosBlend": ROS_BLEND,
        "bestBallVarianceBump": BEST_BALL_VARIANCE_BUMP,
        "bestBallVarianceMode": "depth_aware" if best_ball else "off",
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
