"""Playoff-odds Monte Carlo simulator for the current season.

Emits, per franchise, a probability that they finish the regular
season inside the playoff cutoff (top-N by standings).  The simulator
is deliberately self-contained — no external modelling library, no
hidden state.  Every input is explicit so the caller can reproduce a
run.

Algorithm
─────────
For the *current* season only:

1. Walk every scored regular-season week in this season's snapshot to
   build an empirical per-owner weekly score distribution (points
   scored in each past week).  This is the sampling pool for future
   weeks — it's the owner's *actual* scoring history, so unusual
   roster construction / matchup luck is naturally encoded.

2. Determine the remaining schedule.  Sleeper exposes matchups only
   for weeks that have been posted (usually current + a couple of
   future weeks).  For posted-but-not-played weeks we honour the
   exact matchup pairs.  For further-out weeks we assume a standard
   single round-robin rotation over a week-0 reference pairing, which
   closely matches how most Sleeper leagues schedule.

3. Run N Monte Carlo simulations.  In each run, for every remaining
   week, sample each owner's score from their empirical distribution
   and award W/L based on the week's pairing.  At season end, compute
   final regular-season standings (wins, PF tiebreak) and check
   whether each owner sits inside the top ``playoff_spots``.

4. Return ``{owner_id: probability}`` plus structured diagnostics for
   the frontend (current wins, current PF, weeks remaining, schedule
   certainty flag).

The simulator degrades gracefully:

* ``remaining_weeks == 0`` → probabilities collapse to 0/1 (the
  season is over; the team either made it or didn't).
* An owner with <2 scored weeks in the current season → fall back
  to the league-wide empirical distribution so a hot streak from a
  handful of weeks doesn't get amplified.
* No schedule information at all → assume a random-opponent model
  (every remaining week each owner gets a random opponent).  The
  output includes ``scheduleCertainty = "inferred"`` so the
  frontend can warn.

Constants live at the top of the module so audits can see them in
one place.
"""
from __future__ import annotations

import random
from typing import Any, Iterable

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

# Number of MC runs per invocation.  10_000 is plenty for a 12-team
# league: standard error on each owner's probability is < 0.5%.
DEFAULT_SIMS: int = 10_000

# Minimum per-owner sampled weeks before we trust their empirical
# distribution.  Below this, fall back to the league-wide pool.
MIN_SAMPLED_WEEKS: int = 2

# Default playoff spot count when the league settings don't carry an
# explicit ``playoff_teams`` field.
DEFAULT_PLAYOFF_SPOTS: int = 6


def _season_weekly_scores(
    season: SeasonSnapshot,
    registry,
) -> tuple[dict[str, list[float]], list[float]]:
    """Return (per-owner regular-season scores, league-wide pool).

    League-wide pool is the fallback distribution for owners who
    haven't played enough weeks yet to have a stable personal
    distribution.
    """
    per_owner: dict[str, list[float]] = {}
    pool: list[float] = []
    for wk in season.regular_season_weeks:
        for entry in season.matchups_by_week.get(wk) or []:
            if not metrics.is_scored(entry):
                continue
            rid = metrics.roster_id_of(entry)
            if rid is None:
                continue
            owner_id = metrics.resolve_owner(registry, season.league_id, rid)
            if not owner_id:
                continue
            pts = metrics.matchup_points(entry)
            per_owner.setdefault(owner_id, []).append(pts)
            pool.append(pts)
    return per_owner, pool


def _regular_season_record_to_date(
    season: SeasonSnapshot,
    registry,
) -> dict[str, dict[str, float | int]]:
    """Current wins / PF per owner from already-played regular weeks."""
    out: dict[str, dict[str, float | int]] = {}
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        for a, b in metrics.matchup_pairs(entries):
            # Only count a matchup once BOTH sides have posted scores.
            # During a live week one side can be scored (e.g. Thursday
            # game already finished) while the other hasn't played yet
            # — if we counted that, the completed side would be
            # credited with a phantom win over an opponent sitting at
            # 0 points, and the playoff simulator would inherit that
            # wrong record.  Requiring both scored also covers the
            # "future week sits in matchups_by_week before it's
            # played" case that the earlier single-side check
            # intended to handle.
            if not (metrics.is_scored(a) and metrics.is_scored(b)):
                continue
            for side, opp in ((a, b), (b, a)):
                rid = metrics.roster_id_of(side)
                if rid is None:
                    continue
                owner_id = metrics.resolve_owner(registry, season.league_id, rid)
                if not owner_id:
                    continue
                pts_me = metrics.matchup_points(side)
                pts_opp = metrics.matchup_points(opp)
                rec = out.setdefault(owner_id, {"wins": 0, "losses": 0, "ties": 0, "pointsFor": 0.0})
                rec["pointsFor"] += pts_me
                if pts_me > pts_opp:
                    rec["wins"] += 1
                elif pts_me < pts_opp:
                    rec["losses"] += 1
                else:
                    rec["ties"] += 1
    return out


def _posted_future_matchups(
    season: SeasonSnapshot,
    registry,
) -> dict[int, list[tuple[str, str]]]:
    """Owner-id pairs for matchups within each week that haven't been
    fully scored yet.

    Key subtlety: a "partially played" live week (Thursday game
    complete, Sunday games pending) still has authoritative posted
    pairings for the unplayed matchups.  Early iterations of this
    helper skipped the whole week when *any* entry was scored, which
    let ``_round_robin_schedule`` re-generate pairings for the
    already-completed Thursday game — at best wasted simulator work,
    at worst wrong opponents for Sunday games.

    So we emit pairings per un-scored matchup within each week, not
    per whole week.  An already-complete matchup (both sides scored)
    is filtered out — its actual result feeds ``_regular_season_
    record_to_date`` via the week-completion check there, not the
    simulator.  A completely un-started week still yields every pair
    exactly as before.
    """
    out: dict[int, list[tuple[str, str]]] = {}
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        pairs: list[tuple[str, str]] = []
        for a, b in metrics.matchup_pairs(entries):
            # Filter completed matchups (both sides scored) — those
            # are already in the current-record snapshot and must not
            # be re-simulated.
            if metrics.is_scored(a) and metrics.is_scored(b):
                continue
            rid_a = metrics.roster_id_of(a)
            rid_b = metrics.roster_id_of(b)
            if rid_a is None or rid_b is None:
                continue
            oa = metrics.resolve_owner(registry, season.league_id, rid_a)
            ob = metrics.resolve_owner(registry, season.league_id, rid_b)
            if oa and ob:
                pairs.append((oa, ob))
        if pairs:
            out[wk] = pairs
    return out


def _round_robin_schedule(
    owners: list[str],
    weeks: list[int],
) -> dict[int, list[tuple[str, str]]]:
    """Standard circle-method round robin over ``owners`` for ``weeks``.

    Used as a fallback when Sleeper hasn't posted future matchups yet.
    If ``len(owners)`` is odd we add a bye placeholder; the owner paired
    with the bye gets a free week (no score generated).

    The pairing is deterministic for a given owners list + weeks range
    so two subsequent simulator runs on the same data produce the same
    schedule.
    """
    if not owners:
        return {week: [] for week in weeks}
    ring = list(owners)
    if len(ring) % 2 == 1:
        ring.append("__BYE__")
    n = len(ring)
    schedule: dict[int, list[tuple[str, str]]] = {}
    # Fix the first owner in place; rotate the rest.  Standard circle
    # method, identical to NFL-style round-robin generation.
    fixed = ring[0]
    rotators = ring[1:]
    for i, wk in enumerate(weeks):
        pairs: list[tuple[str, str]] = []
        rot = rotators[-i % len(rotators):] + rotators[: -i % len(rotators)]
        # Pair fixed vs rot[0]; then pair rot[1..] inward.
        half = [fixed] + rot
        for j in range(n // 2):
            a, b = half[j], half[n - 1 - j]
            if a == "__BYE__" or b == "__BYE__":
                continue
            pairs.append((a, b))
        schedule[wk] = pairs
    return schedule


def _standings_from_sim(
    wins: dict[str, int],
    points: dict[str, float],
    owners: Iterable[str],
) -> list[str]:
    """Sort owners by (wins desc, pointsFor desc).  Matches the tiebreak
    rule ``season_standings`` applies across every leage Sleeper hosts
    we've observed.  Advanced tiebreakers (H2H, division records) are
    intentionally ignored — they don't matter for probability at
    ``num_sims >= 10_000`` when integrated over many draws.
    """
    return sorted(
        owners,
        key=lambda o: (-wins.get(o, 0), -points.get(o, 0.0), o),
    )


def compute_playoff_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    num_sims: int = DEFAULT_SIMS,
    playoff_spots: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Simulate the current season's remaining weeks and return
    per-owner playoff probabilities.

    Returns a dict of shape::

        {
          "season": "2026",
          "numSims": 10000,
          "playoffSpots": 6,
          "weeksPlayed": 8,
          "weeksRemaining": 5,
          "scheduleCertainty": "posted" | "inferred" | "partial",
          "owners": [
            {
              "ownerId": "...",
              "displayName": "...",
              "currentWins": 5,
              "currentPointsFor": 1234.5,
              "playoffProbability": 0.82,
            },
            ...
          ],
        }
    """
    rng = rng or random.Random()
    season = snapshot.current_season
    if season is None:
        return {
            "season": None,
            "numSims": 0,
            "playoffSpots": 0,
            "weeksPlayed": 0,
            "weeksRemaining": 0,
            "scheduleCertainty": "none",
            "owners": [],
        }

    registry = snapshot.managers

    # Guard against non-positive simulation counts.  The remaining-
    # weeks code path divides probabilities by ``num_sims`` — a zero
    # value would raise ``ZeroDivisionError`` mid-response.  Callers
    # asking for "just tell me the current snapshot" (``num_sims=0``)
    # on a season with remaining weeks still get a well-formed reply:
    # every owner reports ``playoffProbability=None`` and the header
    # surfaces ``numSims=0`` so the frontend can render a "season in
    # progress, simulations disabled" state without crashing.
    try:
        num_sims = int(num_sims)
    except (TypeError, ValueError):
        num_sims = 0
    if num_sims < 0:
        num_sims = 0

    # Playoff spot count — honour league settings, else default.
    settings = season.league.get("settings") or {}
    cfg_spots = settings.get("playoff_teams") if isinstance(settings, dict) else None
    try:
        spots = int(playoff_spots if playoff_spots is not None else cfg_spots or DEFAULT_PLAYOFF_SPOTS)
    except (TypeError, ValueError):
        spots = DEFAULT_PLAYOFF_SPOTS
    spots = max(1, spots)

    owners_in_league: list[str] = []
    for roster in season.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        oid = metrics.resolve_owner(registry, season.league_id, rid)
        if oid and oid not in owners_in_league:
            owners_in_league.append(oid)
    if not owners_in_league:
        return {
            "season": season.season,
            "numSims": 0,
            "playoffSpots": spots,
            "weeksPlayed": 0,
            "weeksRemaining": 0,
            "scheduleCertainty": "none",
            "owners": [],
        }

    per_owner_scores, league_pool = _season_weekly_scores(season, registry)
    current_record = _regular_season_record_to_date(season, registry)

    # Determine played vs remaining regular-season weeks.  A week is
    # "played" only when *every* scored matchup in that week has both
    # sides posted — mirrors ``_regular_season_record_to_date``'s
    # requirement, so a live Thursday-only week still sits in
    # ``remaining_weeks`` and gets simulated rather than counted as
    # completed with half its games at zero.
    def _week_is_complete(wk: int) -> bool:
        entries = season.matchups_by_week.get(wk) or []
        if not entries:
            return False
        for a, b in metrics.matchup_pairs(entries):
            if not (metrics.is_scored(a) and metrics.is_scored(b)):
                return False
        return True

    played_weeks = [wk for wk in season.regular_season_weeks if _week_is_complete(wk)]
    remaining_weeks = [wk for wk in season.regular_season_weeks if wk not in played_weeks]

    # Early exit: season over → probabilities collapse to 0/1.
    if not remaining_weeks:
        wins_snapshot = {o: int(current_record.get(o, {}).get("wins", 0)) for o in owners_in_league}
        pf_snapshot = {o: float(current_record.get(o, {}).get("pointsFor", 0.0)) for o in owners_in_league}
        ordered = _standings_from_sim(wins_snapshot, pf_snapshot, owners_in_league)
        made = set(ordered[:spots])
        return {
            "season": season.season,
            "numSims": 0,
            "playoffSpots": spots,
            "weeksPlayed": len(played_weeks),
            "weeksRemaining": 0,
            "scheduleCertainty": "final",
            "owners": [
                {
                    "ownerId": o,
                    "displayName": metrics.display_name_for(snapshot, o),
                    "currentWins": wins_snapshot[o],
                    "currentPointsFor": round(pf_snapshot[o], 2),
                    "playoffProbability": 1.0 if o in made else 0.0,
                }
                for o in owners_in_league
            ],
        }

    posted = _posted_future_matchups(season, registry)
    schedule_certainty = "posted" if all(wk in posted for wk in remaining_weeks) else (
        "partial" if any(wk in posted for wk in remaining_weeks) else "inferred"
    )
    missing_weeks = [wk for wk in remaining_weeks if wk not in posted]
    inferred = _round_robin_schedule(owners_in_league, missing_weeks)
    full_schedule = {**inferred, **posted}

    owner_pool: dict[str, list[float]] = {}
    for o in owners_in_league:
        scores = per_owner_scores.get(o, [])
        owner_pool[o] = scores if len(scores) >= MIN_SAMPLED_WEEKS else (scores + league_pool)
        if not owner_pool[o]:
            # Nothing at all — use a flat 100-point placeholder so the
            # sim runs but the distribution is uninformative.
            owner_pool[o] = [100.0]

    # Pre-snapshot current state.
    base_wins = {o: int(current_record.get(o, {}).get("wins", 0)) for o in owners_in_league}
    base_pf = {o: float(current_record.get(o, {}).get("pointsFor", 0.0)) for o in owners_in_league}

    made_counter: dict[str, int] = {o: 0 for o in owners_in_league}

    for _ in range(num_sims):
        sim_wins = dict(base_wins)
        sim_pf = dict(base_pf)
        for wk in remaining_weeks:
            pairs = full_schedule.get(wk, [])
            for a, b in pairs:
                pa = rng.choice(owner_pool[a])
                pb = rng.choice(owner_pool[b])
                sim_pf[a] = sim_pf.get(a, 0.0) + pa
                sim_pf[b] = sim_pf.get(b, 0.0) + pb
                if pa > pb:
                    sim_wins[a] = sim_wins.get(a, 0) + 1
                elif pb > pa:
                    sim_wins[b] = sim_wins.get(b, 0) + 1
        ordered = _standings_from_sim(sim_wins, sim_pf, owners_in_league)
        for o in ordered[:spots]:
            made_counter[o] += 1

    def _probability(owner: str) -> float | None:
        if num_sims <= 0:
            return None
        return round(made_counter[owner] / num_sims, 4)

    return {
        "season": season.season,
        "numSims": num_sims,
        "playoffSpots": spots,
        "weeksPlayed": len(played_weeks),
        "weeksRemaining": len(remaining_weeks),
        "scheduleCertainty": schedule_certainty,
        "owners": [
            {
                "ownerId": o,
                "displayName": metrics.display_name_for(snapshot, o),
                "currentWins": base_wins[o],
                "currentPointsFor": round(base_pf[o], 2),
                "playoffProbability": _probability(o),
            }
            for o in owners_in_league
        ],
    }


def build_section(
    snapshot: PublicLeagueSnapshot,
    *,
    num_sims: int = DEFAULT_SIMS,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Public-league section builder — matches the shape the
    `/api/public/league/*` handlers expect from every other builder
    in this package (activity, awards, power, luck, …).
    """
    return compute_playoff_odds(snapshot, num_sims=num_sims, rng=rng)
