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
   exact matchup pairs.  For further-out weeks we first try to infer
   the pairings from the observed posted-week pattern — detecting the
   cycle length by looking for pair-set repetition across posted
   weeks and propagating forward.  Only when fewer than 2 posted
   weeks are available (or the observed block leaves residues
   uncovered) do we fall back to a synthetic single round-robin
   rotation.

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


def _latest_played_week(season: SeasonSnapshot) -> int | None:
    """Return the highest regular-season week that has any scored entry.

    Used to disambiguate ``points == 0 and the week is past`` (e.g. a
    roster legitimately finished at zero) from ``points == 0 and the
    week hasn't been played yet``.  ``metrics.is_scored`` returns
    ``True`` only for ``points > 0``, so we need an out-of-band
    signal for finalization when a team genuinely scored zero.
    """
    latest: int | None = None
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        if any(metrics.is_scored(e) for e in entries):
            if latest is None or wk > latest:
                latest = wk
    return latest


def _matchup_is_final(a: dict, b: dict, is_past_week: bool) -> bool:
    """True when the A vs. B matchup should count toward current record.

    Two cases fall under "final":
      1. The week is strictly before the latest week with any scored
         entry.  We know the week is done because a later week has
         scored entries, so every matchup in it is a real final —
         including an exact 0-0 tie where neither roster scored a
         point (rare but valid in extreme injury-wipeout scenarios).
         Per Codex PR #215 round 4: the earlier "at least one side
         scored" gate incorrectly rejected these 0-0 ties and caused
         the simulator to re-simulate an already-finalised game.
      2. Both sides have ``points > 0`` — the standard current-week
         gate.  During a live week we require both sides to have
         posted scores before counting, otherwise a Thursday-only
         finish gets credited as a phantom win over an opponent still
         sitting at 0.
    """
    if is_past_week:
        return True
    if metrics.is_scored(a) and metrics.is_scored(b):
        return True
    return False


def _regular_season_record_to_date(
    season: SeasonSnapshot,
    registry,
) -> dict[str, dict[str, float | int]]:
    """Current wins / PF / ties per owner from already-played weeks.

    A matchup counts toward current record when ``_matchup_is_final``
    returns True.  That supports the two legitimate final states:
    both-sides-scored (normal) and one-side-zero-in-a-past-week (rare
    but real — addresses the Codex P2 review on PR #215).

    Tie outcomes (both sides with identical non-zero points) are
    counted into the ``ties`` bucket so downstream standings sort
    with ``wins + 0.5 * ties`` as the primary key — matches Sleeper's
    default regular-season tiebreak and keeps 0-1-0 vs 0-0-1 teams
    ordered correctly in the simulator.
    """
    latest_played = _latest_played_week(season)
    out: dict[str, dict[str, float | int]] = {}
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        is_past_week = latest_played is not None and wk < latest_played
        for a, b in metrics.matchup_pairs(entries):
            if not _matchup_is_final(a, b, is_past_week):
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


def _all_posted_pair_lists(
    season: SeasonSnapshot,
    registry,
) -> dict[int, list[tuple[str, str]]]:
    """Owner-id pairs for every regular-season week Sleeper has posted
    matchup assignments for — regardless of whether the games are
    already scored.

    Differs from ``_posted_future_matchups`` in that this helper does
    not filter out fully-scored matchups.  Cycle detection in
    ``_infer_schedule_from_posted`` needs the authoritative pairings
    from already-played weeks, not just the live/future un-played ones.
    """
    out: dict[int, list[tuple[str, str]]] = {}
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        pairs: list[tuple[str, str]] = []
        for a, b in metrics.matchup_pairs(entries):
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


def _detect_cycle_length(
    posted_weeks: list[int],
    canonical: dict[int, frozenset],
) -> int | None:
    """Return the smallest ``L ≥ 1`` such that every pair of posted
    weeks sharing a residue ``(w - anchor) mod L`` has the same
    canonical pair-set, AND at least one such overlap exists.

    Returns ``None`` when no cycle can be confirmed — e.g. all posted
    weeks carry distinct pair-sets and no ``L`` within the span lines
    two of them up.
    """
    if len(posted_weeks) < 2:
        return None
    anchor = posted_weeks[0]
    span = posted_weeks[-1] - anchor
    for L in range(1, span + 1):
        residues: dict[int, frozenset] = {}
        has_overlap = False
        ok = True
        for w in posted_weeks:
            r = (w - anchor) % L
            if r in residues:
                has_overlap = True
                if residues[r] != canonical[w]:
                    ok = False
                    break
            else:
                residues[r] = canonical[w]
        if ok and has_overlap:
            return L
    return None


def _infer_schedule_from_posted(
    season: SeasonSnapshot,
    registry,
) -> dict[int, list[tuple[str, str]]] | None:
    """Infer per-week owner pairs for every regular-season week from
    the pattern of posted weeks.

    Returns a full schedule dict when inference succeeds, or ``None``
    when fewer than 2 posted weeks are available (caller should fall
    back to ``_round_robin_schedule``) or when at least one regular-
    season week has no matching residue in the observed pattern.

    Algorithm:
      1. Gather all posted weeks with their canonical pair-sets.
      2. Detect the cycle length ``L`` via pair-set repetition across
         posted weeks.  If no cycle is confirmed, fall back to
         ``L = span + 1`` — treats the contiguous observed block as a
         single cycle and propagates it forward.
      3. For each regular-season week, reuse the posted pairs from the
         observed week with the same residue ``(wk - anchor) mod L``.
    """
    posted_pairs = _all_posted_pair_lists(season, registry)
    if len(posted_pairs) < 2:
        return None
    posted_weeks = sorted(posted_pairs.keys())
    canonical = {
        w: frozenset(frozenset(p) for p in posted_pairs[w]) for w in posted_weeks
    }
    anchor = posted_weeks[0]

    cycle_length = _detect_cycle_length(posted_weeks, canonical)
    if cycle_length is None:
        # No confirmed repetition — treat the posted block itself as
        # the cycle.  Works for the common case of weeks [1..k] posted
        # with distinct pairings: week k+1 inherits week 1's pairs.
        cycle_length = posted_weeks[-1] - anchor + 1

    residue_to_week: dict[int, int] = {}
    for w in posted_weeks:
        r = (w - anchor) % cycle_length
        residue_to_week.setdefault(r, w)

    schedule: dict[int, list[tuple[str, str]]] = {}
    for wk in season.regular_season_weeks:
        if wk in posted_pairs:
            schedule[wk] = posted_pairs[wk]
            continue
        residue = (wk - anchor) % cycle_length
        src_week = residue_to_week.get(residue)
        if src_week is None:
            # Posted block has a gap at this residue — inference
            # can't cover every missing week; caller falls back.
            return None
        schedule[wk] = posted_pairs[src_week]
    return schedule


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
    *,
    ties: dict[str, int] | None = None,
) -> list[str]:
    """Sort owners by (wins+0.5·ties desc, pointsFor desc).

    Matches the tiebreak rule ``season_standings`` applies across
    every Sleeper league we've observed: a tie counts as half a win
    in standings sort order, so a (0-0-1) team ranks above (0-1-0).
    Advanced tiebreakers (H2H, division records) are intentionally
    ignored — they don't matter for probability at
    ``num_sims >= 10_000`` when integrated over many draws.

    ``ties`` is optional for backward compatibility with callers that
    don't track ties (the default treats everyone as 0-tie).
    """
    ties = ties or {}
    return sorted(
        owners,
        key=lambda o: (
            -(wins.get(o, 0) + 0.5 * ties.get(o, 0)),
            -points.get(o, 0.0),
            o,
        ),
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
          "scheduleCertainty": "posted" | "inferred_from_posted" | "partial" | "inferred",
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
    latest_played = _latest_played_week(season)

    def _week_is_complete(wk: int) -> bool:
        entries = season.matchups_by_week.get(wk) or []
        if not entries:
            return False
        is_past_week = latest_played is not None and wk < latest_played
        for a, b in metrics.matchup_pairs(entries):
            if not _matchup_is_final(a, b, is_past_week):
                return False
        return True

    played_weeks = [wk for wk in season.regular_season_weeks if _week_is_complete(wk)]
    remaining_weeks = [wk for wk in season.regular_season_weeks if wk not in played_weeks]

    # Early exit: both played and remaining are empty.  Two very
    # different states collapse to this shape and must be handled
    # distinctly (per Codex PR #215 round 4):
    #
    #   * Preseason — ``regular_season_weeks`` is empty because the
    #     snapshot only stores weeks with real matchup rows and no
    #     week has been published yet.  Before: reported
    #     ``scheduleCertainty: "final"`` and handed out arbitrary 0/1
    #     probabilities from whatever owner order the loop produced.
    #     Now: emits a ``preseason`` state with all probabilities
    #     null so the frontend can render "season hasn't started".
    #
    #   * Finished — at least one week has been played AND nothing
    #     remains.  Everyone either made the playoffs (1.0) or didn't
    #     (0.0) based on their actual current record.
    if not remaining_weeks:
        is_preseason = len(played_weeks) == 0 and latest_played is None
        if is_preseason:
            return {
                "season": season.season,
                "numSims": 0,
                "playoffSpots": spots,
                "weeksPlayed": 0,
                "weeksRemaining": 0,
                "scheduleCertainty": "preseason",
                "owners": [
                    {
                        "ownerId": o,
                        "displayName": metrics.display_name_for(snapshot, o),
                        "currentWins": 0,
                        "currentPointsFor": 0.0,
                        "playoffProbability": None,
                    }
                    for o in owners_in_league
                ],
            }
        wins_snapshot = {o: int(current_record.get(o, {}).get("wins", 0)) for o in owners_in_league}
        ties_snapshot = {o: int(current_record.get(o, {}).get("ties", 0)) for o in owners_in_league}
        pf_snapshot = {o: float(current_record.get(o, {}).get("pointsFor", 0.0)) for o in owners_in_league}
        ordered = _standings_from_sim(
            wins_snapshot, pf_snapshot, owners_in_league, ties=ties_snapshot
        )
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
    missing_weeks = [wk for wk in remaining_weeks if wk not in posted]
    # For missing future weeks, prefer inference from the observed
    # posted-week pattern over a synthetic round-robin — the latter
    # ignores Sleeper's actual pairings and can invent opponents the
    # league will never face.  Fall back to round-robin only when
    # fewer than 2 posted weeks exist (helper returns ``None``) or
    # when the observed block has gaps that block inference.
    inferred_full = (
        _infer_schedule_from_posted(season, registry) if missing_weeks else None
    )
    if missing_weeks and inferred_full is not None:
        inferred = {wk: inferred_full.get(wk, []) for wk in missing_weeks}
        used_posted_inference = True
    else:
        inferred = _round_robin_schedule(owners_in_league, missing_weeks)
        used_posted_inference = False

    if not missing_weeks:
        schedule_certainty = "posted"
    elif used_posted_inference:
        schedule_certainty = "inferred_from_posted"
    elif any(wk in posted for wk in remaining_weeks):
        schedule_certainty = "partial"
    else:
        schedule_certainty = "inferred"
    full_schedule = {**inferred, **posted}

    owner_pool: dict[str, list[float]] = {}
    for o in owners_in_league:
        scores = per_owner_scores.get(o, [])
        owner_pool[o] = scores if len(scores) >= MIN_SAMPLED_WEEKS else (scores + league_pool)
        if not owner_pool[o]:
            # Nothing at all — use a flat 100-point placeholder so the
            # sim runs but the distribution is uninformative.
            owner_pool[o] = [100.0]

    # Pre-snapshot current state — wins, ties, PF all carry over.
    base_wins = {o: int(current_record.get(o, {}).get("wins", 0)) for o in owners_in_league}
    base_ties = {o: int(current_record.get(o, {}).get("ties", 0)) for o in owners_in_league}
    base_pf = {o: float(current_record.get(o, {}).get("pointsFor", 0.0)) for o in owners_in_league}

    made_counter: dict[str, int] = {o: 0 for o in owners_in_league}

    for _ in range(num_sims):
        sim_wins = dict(base_wins)
        sim_ties = dict(base_ties)
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
                else:
                    # Exact-tie simulation branch.  Both sides get a
                    # tie credited so downstream standings correctly
                    # rank (0-0-1) above (0-1-0) via the ``wins +
                    # 0.5 * ties`` key in ``_standings_from_sim``.
                    sim_ties[a] = sim_ties.get(a, 0) + 1
                    sim_ties[b] = sim_ties.get(b, 0) + 1
        ordered = _standings_from_sim(
            sim_wins, sim_pf, owners_in_league, ties=sim_ties
        )
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
