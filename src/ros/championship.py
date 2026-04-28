"""ROS-driven championship Monte Carlo.

Extends ``src.ros.playoff_sim`` through the playoff bracket + finals.
Outputs per-team championship odds, finals odds, semifinal odds, and
expected-finish.

For PR3 the bracket model is intentionally simple:

  * Single-elimination 6-team bracket (2 byes + 4 wild-card matchups
    in round 1; 4 in semis; finals).  Configurable per league.
  * Each playoff matchup uses the same per-team weekly score
    distribution as the regular-season simulator (mean from blended
    ROS strength, sd bumped for best-ball variance).
  * The full sim runs ``n_simulations`` times; for each run we
    simulate the regular season → seed → bracket → champion.

The frontend can render this directly as a "ROS Championship Odds"
section.  PR4 wires it into the buyer/seller direction logic.

Returns:
    {
        "championshipOdds": [{ownerId, displayName,
                              championshipOdds, finalsOdds,
                              semifinalOdds, expectedFinish,
                              contenderTier}],
        "n_simulations": int,
        "playoffSeeds": int,
        "byeSeeds": int,
        "rosStrengthAvailable": bool,
    }
"""
from __future__ import annotations

import json
import logging
import random
import statistics
from typing import Any

from src.public_league import metrics, playoff_odds
from src.public_league.snapshot import PublicLeagueSnapshot
from src.ros import ROS_DATA_DIR, playoff_sim

LOG = logging.getLogger("ros.championship")


# Contender-tier thresholds (per spec).
def _contender_tier(championship_odds: float, playoff_odds_pct: float) -> str:
    """Map odds to a contender label."""
    if championship_odds >= 0.20:
        return "Favorite"
    if championship_odds >= 0.10:
        return "Serious Contender"
    if championship_odds >= 0.05 or playoff_odds_pct >= 0.50:
        return "Dangerous Playoff Team"
    if playoff_odds_pct >= 0.30:
        return "Fringe Playoff Team"
    if playoff_odds_pct >= 0.10:
        return "Long Shot"
    return "Rebuilder / Seller"


def _simulate_bracket(
    seeded_owners: list[str],
    distributions: dict[str, playoff_sim._TeamDist],
    *,
    bye_seeds: int,
    rng: random.Random,
) -> dict[str, int]:
    """Simulate one playoff bracket.  Returns finish placement per
    owner: 1 (champion), 2 (runner-up), 3-4 (semifinal exits), 5-N
    (early/missed playoffs).
    """
    finishes: dict[str, int] = {}
    if not seeded_owners:
        return finishes

    # Mark anyone outside the playoff field with a finish equal to
    # their seed (they're "out" in seeding order).
    playoff_field_size = len([s for s in seeded_owners if seeded_owners.index(s) < 6]) or 6
    for i, owner in enumerate(seeded_owners):
        if i >= playoff_field_size:
            finishes[owner] = i + 1

    field = seeded_owners[:playoff_field_size]
    if len(field) < 4:
        # Tiny league fallback: champion is the top seed by record.
        if field:
            finishes[field[0]] = 1
            for i, owner in enumerate(field[1:], start=2):
                finishes[owner] = i
        return finishes

    bye_set = set(field[:bye_seeds])

    # Round 1: byes auto-advance; remaining seeds play in
    # higher-seed-vs-lower-seed pairs.
    advancing_to_semis: list[str] = list(field[:bye_seeds])
    wildcard = [s for s in field[bye_seeds:]]
    # Pair top remaining vs bottom remaining.
    while len(wildcard) >= 2:
        high = wildcard.pop(0)
        low = wildcard.pop(-1)
        winner = _simulate_matchup(high, low, distributions, rng)
        advancing_to_semis.append(winner)
        # The loser is eliminated at this round.
        loser = low if winner == high else high
        finishes.setdefault(loser, 5 + len(finishes) - (len(seeded_owners) - playoff_field_size))

    # Semifinals: pair higher seed vs lower seed in advancing list.
    semis_advance: list[str] = []
    while len(advancing_to_semis) >= 2:
        high = advancing_to_semis.pop(0)
        low = advancing_to_semis.pop(-1)
        winner = _simulate_matchup(high, low, distributions, rng)
        semis_advance.append(winner)
        loser = low if winner == high else high
        finishes.setdefault(loser, 3)

    # Finals.
    if len(semis_advance) >= 2:
        high = semis_advance[0]
        low = semis_advance[1]
        champion = _simulate_matchup(high, low, distributions, rng)
        runner_up = low if champion == high else high
        finishes[champion] = 1
        finishes[runner_up] = 2

    # Anyone unplaced gets the next available finish (defensive).
    placed_finishes = set(finishes.values())
    next_finish = 1
    for owner in seeded_owners:
        if owner in finishes:
            continue
        while next_finish in placed_finishes:
            next_finish += 1
        finishes[owner] = next_finish
        placed_finishes.add(next_finish)

    return finishes


def _simulate_matchup(
    owner_a: str,
    owner_b: str,
    distributions: dict[str, playoff_sim._TeamDist],
    rng: random.Random,
) -> str:
    """Single-week head-to-head from per-team distributions."""
    a = distributions.get(owner_a)
    b = distributions.get(owner_b)
    if a is None or b is None:
        return owner_a if rng.random() < 0.5 else owner_b
    score_a = max(0.0, rng.gauss(a.mean, a.sd))
    score_b = max(0.0, rng.gauss(b.mean, b.sd))
    if score_a > score_b:
        return owner_a
    if score_b > score_a:
        return owner_b
    return owner_a if rng.random() < 0.5 else owner_b


def simulate_championship_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    n_simulations: int = playoff_sim.DEFAULT_SIMULATIONS,
    playoff_seeds: int = 6,
    bye_seeds: int = 2,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Run the full regular-season + bracket simulation.

    Pulls per-team distributions through ``playoff_sim`` so the
    ROS-blended means + best-ball variance bump are reused.
    """
    rng = rng or random.Random()
    ros_map = playoff_sim._load_ros_strength_map()
    distributions, pf_by_owner = playoff_sim._build_team_distributions(snapshot, ros_map)
    if not distributions:
        return {
            "championshipOdds": [],
            "n_simulations": n_simulations,
            "playoffSeeds": playoff_seeds,
            "byeSeeds": bye_seeds,
            "rosStrengthAvailable": bool(ros_map),
        }

    record = playoff_sim._current_record(snapshot)
    schedule = playoff_sim._remaining_schedule(snapshot)
    owners = sorted(distributions.keys())

    champion_count: dict[str, int] = {o: 0 for o in owners}
    finals_count: dict[str, int] = {o: 0 for o in owners}
    semifinal_count: dict[str, int] = {o: 0 for o in owners}
    finish_total: dict[str, float] = {o: 0.0 for o in owners}
    playoff_count: dict[str, int] = {o: 0 for o in owners}

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

        seeded = sorted(
            owners,
            key=lambda o: (-sim_wins.get(o, 0.0), -sim_pf.get(o, 0.0)),
        )
        finishes = _simulate_bracket(
            seeded,
            distributions,
            bye_seeds=bye_seeds,
            rng=rng,
        )
        for owner, finish in finishes.items():
            finish_total[owner] += finish
            if finish == 1:
                champion_count[owner] += 1
            if finish <= 2:
                finals_count[owner] += 1
            if finish <= 4:
                semifinal_count[owner] += 1
            if finish <= playoff_seeds:
                playoff_count[owner] += 1

    out: list[dict[str, Any]] = []
    n_safe = max(1, n_simulations)
    for owner in owners:
        championship_odds = champion_count[owner] / n_safe
        playoff_odds_pct = playoff_count[owner] / n_safe
        out.append(
            {
                "ownerId": owner,
                "displayName": metrics.display_name_for(snapshot, owner),
                "championshipOdds": round(championship_odds, 4),
                "finalsOdds": round(finals_count[owner] / n_safe, 4),
                "semifinalOdds": round(semifinal_count[owner] / n_safe, 4),
                "playoffOdds": round(playoff_odds_pct, 4),
                "expectedFinish": round(finish_total[owner] / n_safe, 2),
                "contenderTier": _contender_tier(championship_odds, playoff_odds_pct),
            }
        )
    out.sort(key=lambda r: -r["championshipOdds"])
    return {
        "championshipOdds": out,
        "n_simulations": n_simulations,
        "playoffSeeds": playoff_seeds,
        "byeSeeds": bye_seeds,
        "rosStrengthAvailable": bool(ros_map),
    }


_SIM_CACHE_TTL_SEC = 6 * 3600


def _load_cached_payload() -> dict[str, Any] | None:
    """Read ``data/ros/sims/latest_championship.json`` if fresh; else None."""
    import os
    import time
    path = ROS_DATA_DIR / "sims" / "latest_championship.json"
    if not path.exists():
        return None
    try:
        if (time.time() - os.path.getmtime(path)) > _SIM_CACHE_TTL_SEC:
            return None
    except OSError:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        LOG.warning("[ros] championship cache unreadable (%s); rerunning sim", exc)
        return None


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosChampionship.

    Prefers the cached output written by the scheduled scrape; falls
    back to a live Monte Carlo when the cache is missing or stale.
    """
    cached = _load_cached_payload()
    if cached is not None:
        cached["cached"] = True
        return cached
    payload = simulate_championship_odds(snapshot)
    payload["cached"] = False
    return payload
