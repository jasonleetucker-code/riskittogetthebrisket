"""Public ``playoffOdds`` section — an ADAPTER over the one canonical engine.

C5-PLAY-01 / V1-51.  This module no longer simulates anything.  Every
probability it publishes is :func:`src.ros.playoff_sim.canonical_forecast`'s
``playoffOdds`` for the same league and snapshot — the number
``/api/public/league/rosPlayoffOdds`` and ``rosChampionship`` publish — laid
into this section's historical shape (``owners[].playoffProbability``) beside
facts read straight off the snapshot: each owner's record to date, finished
and remaining regular-season weeks, and whether the remaining schedule is
posted.

Why it had to stop simulating: until C5-PLAY-01 this module ran its own
empirical-resampling Monte Carlo, and two engines served the same league
different answers.  On the 2026-10-07 week-5 state it published 99.0% for a
``dynasty_main`` team the canonical engine put at 77.2%, and 85.1% for one it
put at 99.4% — on two tabs of the same /league page.  Bracket rules had
already been unified (``playoff_structure``) and both read finished weeks the
same way; what differed was the model itself.  The retired loop (empirical
score resampling, round-robin / cycle-inferred schedules for un-posted weeks,
``DEFAULT_SIMS``, ``MIN_SAMPLED_WEEKS``) is deleted rather than deprecated.

The section therefore INHERITS the canonical engine's methodology exactly,
including two open owner decisions recorded in
``docs/OWNER_REQUESTED_TODO.md``: D2 (the ROS multiplier on top of a
ROS-drawn best-ball pre-sim) and D3 (median games excluded from the record
and from seeding).

What stays here, because other owners import it and it is FACT rather than
model: the finished-week gate (``_final_week_set``), the record to date
(``_regular_season_record_to_date``), the posted remaining schedule
(``_posted_future_matchups``), the per-owner completed-score lists
(``_season_weekly_scores``) and the canonical standings order
(``standings_from_sim``).  The canonical engine itself reads all five.
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from . import luck, metrics
from .playoff_structure import PlayoffStructure, resolve_playoff_structure
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

#: Where every probability in this section comes from.
ENGINE = "src.ros.playoff_sim"

#: ``scheduleCertainty`` when some remaining regular-season week has no posted
#: matchups.  The canonical engine simulates POSTED weeks only — it does not
#: invent pairings — so the label says exactly that, rather than the retired
#: ``partial`` / ``inferred`` / ``inferred_from_posted`` values, which described
#: a round-robin this section no longer runs.
CERTAINTY_POSTED_WEEKS_ONLY = "posted_weeks_only"

# DELETED 2026-08-19 (V1-51): ``DEFAULT_PLAYOFF_SPOTS = 6``.
#
# It stood in for the league's own ``playoff_teams`` when the settings did
# not carry one, and the live league takes SEVEN — so the fallback was
# wrong for the league it served, and it published probabilities computed
# under a format nobody verified.  ``playoff_structure`` is the one owner
# now and an unpublished bracket is a refusal, not a number.  The constant
# is gone rather than deprecated: a plausible default in scope is how a
# guess gets re-adopted.


def _season_weekly_scores(
    season: SeasonSnapshot,
    registry,
) -> tuple[dict[str, list[float]], list[float]]:
    """Return (per-owner regular-season scores, league-wide pool).

    League-wide pool is the fallback distribution for owners who
    haven't played enough weeks yet to have a stable personal
    distribution.

    Which weeks and which entries count is NOT decided here: it is the
    canonical completed-score definition, ``luck._season_weekly_scores``
    (``metrics.final_regular_season_weeks`` + ``points is None`` is
    missing), shared with Luck and Power.  This used to keep its own
    per-entry ``metrics.is_scored`` (``points > 0``) over every
    regular-season week, which let an in-progress week's partial scores
    into the distributions and dropped a finished week's genuine ``0.0``.
    """
    per_owner: dict[str, list[float]] = {}
    pool: list[float] = []
    week_scores = luck._season_weekly_scores(season, registry)
    for wk in sorted(week_scores):
        for owner_id, pts in week_scores[wk]:
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


def _final_week_set(season: SeasonSnapshot) -> set[int]:
    """The regular-season weeks whose scoring is FINISHED.

    Not decided here: this is ``metrics.final_regular_season_weeks``, the
    canonical finished-week gate (host clock ``last_scored_leg``, or every
    roster reporting a real score) that Luck, Power and this module's own
    score distributions already use.  Record, "played weeks" and the
    remaining schedule must all use the SAME gate, or a week can be neither
    counted nor simulated (or both).
    """
    return set(metrics.final_regular_season_weeks(season))


def _matchup_is_final(a: dict, b: dict, week_is_final: bool) -> bool:
    """True when the A vs. B matchup should count toward current record.

    A matchup is final only inside a FINISHED week (``_final_week_set``),
    and only when both sides carry a score.  Inside a finished week ``0.0``
    is an observation — an exact 0-0 tie is a real final (Codex PR #215
    round 4) — and only an absent score (``points is None``) is missing.

    RETIRED (D4, 2026-09-26): the rule "both sides have ``points > 0``"
    during the current week.  In a best-ball league most rosters post
    points on Thursday night, so that rule froze live matchups as finals:
    measured on week 3, 3 of 6 ``dynasty_main`` matchups were counted as
    completed games on Thursday-only scores (e.g. 35.31 vs 25.44), and
    ``dynasty_new`` published a 3-0 record the host still showed as 2-0.
    Per-matchup scores cannot tell a finished game from a started one;
    only the week gate can.
    """
    if not week_is_final:
        return False
    return a.get("points") is not None and b.get("points") is not None


def _regular_season_record_to_date(
    season: SeasonSnapshot,
    registry,
) -> dict[str, dict[str, float | int]]:
    """Current wins / PF / ties per owner from already-played weeks.

    A matchup counts toward current record when ``_matchup_is_final``
    returns True: its week is in the canonical finished-week set and both
    sides carry a score (a genuine zero included — the Codex P2 review on
    PR #215).  A live week counts toward nobody's record; its matchups are
    simulated instead (``_posted_future_matchups``).

    Tie outcomes (both sides with identical non-zero points) are
    counted into the ``ties`` bucket so downstream standings sort
    with ``wins + 0.5 * ties`` as the primary key — matches Sleeper's
    default regular-season tiebreak and keeps 0-1-0 vs 0-0-1 teams
    ordered correctly in the simulator.
    """
    final_weeks = _final_week_set(season)
    out: dict[str, dict[str, float | int]] = {}
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        week_is_final = wk in final_weeks
        for a, b in metrics.matchup_pairs(entries):
            if not _matchup_is_final(a, b, week_is_final):
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
                rec = out.setdefault(
                    owner_id, {"wins": 0, "losses": 0, "ties": 0, "pointsFor": 0.0}
                )
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
    """Owner-id pairs for every matchup of every week that is not yet
    FINISHED.

    A live week (Thursday game complete, Sunday games pending) still has
    authoritative posted pairings, and every one of them is emitted: no
    matchup in an unfinished week counts toward the record
    (``_matchup_is_final``), so every one of them must be simulated —
    otherwise a Thursday-scored game would be neither counted nor played.

    Finished weeks are excluded wholesale; their results feed
    ``_regular_season_record_to_date``.  The finished-week set is the
    canonical ``metrics.final_regular_season_weeks`` gate, the same one the
    record uses, so the two partition the season with no gap and no
    overlap.

    Retired (D4, 2026-09-26): filtering per matchup on "both sides
    ``points > 0``", which in a best-ball league dropped Thursday-scored
    live matchups from the schedule while the record counted them.
    """
    final_weeks = _final_week_set(season)
    out: dict[int, list[tuple[str, str]]] = {}
    for wk in season.regular_season_weeks:
        if wk in final_weeks:
            continue
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


def standings_from_sim(
    wins: dict[str, float],
    points: dict[str, float],
    owners: Iterable[str],
    *,
    ties: dict[str, int] | None = None,
    rng: random.Random | None = None,
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

    THE THIRD KEY IS A RANDOM DRAW, NOT THE ownerId (2026-08-18, W19-F008).
    It used to be ``o`` — the ownerId string — and the argument above is why
    that looked safe: integrated over 10,000 varying draws, a crude final
    tiebreak washes out.  It stops washing out the moment the draws STOP
    varying, and a placeholder pool upstream made every draw identical.  The
    lexicographic key then decided every simulation the same way and published
    the alphabet as certainty (W19-F008, in this module's retired Monte
    Carlo, itself deleted by C5-PLAY-01).

    A per-simulation ``rng`` draw keeps the tiebreak deterministic under a
    seed and reproducible, while making it impossible for the ORDER OF THE IDS
    to become the answer: renaming an owner is not a football event and must
    not move anybody's odds.  When two teams are genuinely level on wins and
    points, a coin flip is the honest model of "we cannot separate these",
    and averaged over the simulation it yields the ~50/50 each deserves rather
    than 100/0 to whoever sorts first.

    ``rng`` is optional so existing callers and tests keep working; without it
    the tiebreak falls back to the ownerId for a stable, if arbitrary, order.
    Production always passes one.
    """
    ties = ties or {}
    if rng is None:
        return sorted(
            owners,
            key=lambda o: (
                -(wins.get(o, 0) + 0.5 * ties.get(o, 0)),
                -points.get(o, 0.0),
                o,
            ),
        )
    jitter = {o: rng.random() for o in owners}
    return sorted(
        owners,
        key=lambda o: (
            -(wins.get(o, 0) + 0.5 * ties.get(o, 0)),
            -points.get(o, 0.0),
            jitter[o],
        ),
    )


def _unknown_bracket(
    snapshot: PublicLeagueSnapshot,
    season: Any,
    structure: PlayoffStructure,
) -> dict[str, Any]:
    """The league did not publish how many teams make the playoffs.

    Qualifying therefore has no definition to simulate against, so every
    owner reports ``playoffProbability: None`` rather than a number
    computed under an assumed bracket. Same shape as the other refusals
    in this module: the rows are still there, the certainty is not.
    """
    owners_in_league = _owners_in_league(snapshot, season)
    return {
        "season": season.season,
        "numSims": 0,
        "playoffSpots": None,
        "weeksPlayed": 0,
        "weeksRemaining": 0,
        "scheduleCertainty": "unknown_bracket",
        "simulated": False,
        "playoffStructure": structure.to_dict(),
        "unsimulable": {
            "reason": structure.reason or "playoff_bracket_unknown",
            "detail": (
                "this league's settings do not say how many teams make the "
                "playoffs, so qualifying has no definition to simulate "
                "against. This is not a 0% chance for anyone."
            ),
        },
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


def _owners_in_league(snapshot: PublicLeagueSnapshot, season: Any) -> list[str]:
    """Every owner with a roster in ``season``, in roster order."""
    registry = snapshot.managers
    owners: list[str] = []
    for roster in season.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        oid = metrics.resolve_owner(registry, season.league_id, rid)
        if oid and oid not in owners:
            owners.append(oid)
    return owners


def _canonical_forecast(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """The one engine's forecast (lazy import: the engine imports this module)."""
    from src.ros import playoff_sim  # noqa: PLC0415

    return playoff_sim.canonical_forecast(snapshot)


def _probability(row: dict[str, Any] | None) -> float | None:
    value = (row or {}).get("playoffOdds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def compute_playoff_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    forecast: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The public section: canonical playoff odds in the historical shape.

    Returns::

        {
          "season": "2026",
          "numSims": 8000,                 # the canonical run's own count
          "playoffSpots": 7,
          "weeksPlayed": 4,
          "weeksRemaining": 10,
          "scheduleCertainty": "posted" | "posted_weeks_only" | "final"
                               | "preseason" | "unknown_bracket" | "none",
          "simulated": bool,
          "engine": "src.ros.playoff_sim",
          "playoffStructure": {...},
          "owners": [{ownerId, displayName, currentWins, currentPointsFor,
                      playoffProbability}],
          # only when they apply:
          "unsimulable": {...}, "unpostedWeeks": [...],
          "forecastComputedAt": "...", "forecastCached": bool,
        }

    ``forecast`` is the canonical engine's payload; ``None`` reads
    :func:`src.ros.playoff_sim.canonical_forecast`.  States decided by FACT
    alone (no current season, unknown bracket, no owners, preseason) answer
    without consulting the engine and publish no probability.  A canonical
    refusal passes through as ``unsimulable`` with every probability ``None``;
    an owner the forecast does not cover is ``None`` with ``unavailableReason``
    — never ``0``.
    """
    season = snapshot.current_season
    if season is None:
        return {
            "season": None,
            "numSims": 0,
            "playoffSpots": 0,
            "weeksPlayed": 0,
            "weeksRemaining": 0,
            "scheduleCertainty": "none",
            "simulated": False,
            "owners": [],
        }

    registry = snapshot.managers
    structure = resolve_playoff_structure(season)
    spots = structure.teams
    if spots is None:
        return _unknown_bracket(snapshot, season, structure)

    owners_in_league = _owners_in_league(snapshot, season)
    if not owners_in_league:
        return {
            "season": season.season,
            "numSims": 0,
            "playoffSpots": spots,
            "weeksPlayed": 0,
            "weeksRemaining": 0,
            "scheduleCertainty": "none",
            "simulated": False,
            "owners": [],
        }

    current_record = _regular_season_record_to_date(season, registry)

    # Played vs remaining regular-season weeks: the canonical finished-week
    # gate — the same one the record and the engine's schedule use — so a
    # live week is remaining (simulated by the engine), never counted.
    latest_played = _latest_played_week(season)
    final_weeks = _final_week_set(season)
    played_weeks = [
        wk
        for wk in season.regular_season_weeks
        if season.matchups_by_week.get(wk) and wk in final_weeks
    ]
    remaining_weeks = [wk for wk in season.regular_season_weeks if wk not in played_weeks]

    def _row(owner: str, probability: float | None) -> dict[str, Any]:
        rec = current_record.get(owner, {})
        return {
            "ownerId": owner,
            "displayName": metrics.display_name_for(snapshot, owner),
            "currentWins": int(rec.get("wins", 0)),
            "currentPointsFor": round(float(rec.get("pointsFor", 0.0)), 2),
            "playoffProbability": probability,
        }

    if not remaining_weeks and not played_weeks and latest_played is None:
        # Preseason: nothing posted, nothing played, nothing for any engine to
        # simulate.  Not a 0% or a 100% chance for anyone.
        return {
            "season": season.season,
            "numSims": 0,
            "playoffSpots": spots,
            "weeksPlayed": 0,
            "weeksRemaining": 0,
            "scheduleCertainty": "preseason",
            "simulated": False,
            "owners": [_row(o, None) for o in owners_in_league],
        }

    posted = _posted_future_matchups(season, registry)
    unposted = [wk for wk in remaining_weeks if wk not in posted]
    if not remaining_weeks:
        certainty = "final"
    elif unposted:
        certainty = CERTAINTY_POSTED_WEEKS_ONLY
    else:
        certainty = "posted"

    if forecast is None:
        forecast = _canonical_forecast(snapshot)
    unsimulable = forecast.get("unsimulable")
    by_owner = {
        str(r.get("ownerId")): r
        for r in forecast.get("playoffOdds") or []
        if isinstance(r, dict) and r.get("ownerId")
    }
    n_sims = forecast.get("n_simulations") or 0
    simulated = bool(by_owner) and not unsimulable and n_sims > 0

    owners: list[dict[str, Any]] = []
    for o in owners_in_league:
        probability = _probability(by_owner.get(o)) if simulated else None
        row = _row(o, probability)
        if simulated and probability is None:
            row["unavailableReason"] = "owner_absent_from_canonical_forecast"
        owners.append(row)

    out: dict[str, Any] = {
        "season": season.season,
        "numSims": n_sims if simulated else 0,
        "playoffSpots": spots,
        "weeksPlayed": len(played_weeks),
        "weeksRemaining": len(remaining_weeks),
        "scheduleCertainty": certainty,
        # Stamped on every return path that reaches the engine: absent and
        # False must not read the same.
        "simulated": simulated,
        "engine": ENGINE,
        "playoffStructure": structure.to_dict(),
        "owners": owners,
    }
    if unposted:
        out["unpostedWeeks"] = unposted
    if unsimulable:
        out["unsimulable"] = unsimulable
    elif not simulated:
        out["unsimulable"] = {
            "reason": "canonical_forecast_empty",
            "detail": (
                "the playoff engine returned no odds for this league, so none are "
                "published. This is not a 0% chance for anyone."
            ),
        }
    if forecast.get("computedAt") is not None:
        out["forecastComputedAt"] = forecast["computedAt"]
    if "cached" in forecast:
        out["forecastCached"] = bool(forecast["cached"])
    return out


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Public-league section builder — matches the shape the
    `/api/public/league/*` handlers expect from every other builder
    in this package (activity, awards, power, luck, …).
    """
    return compute_playoff_odds(snapshot)
