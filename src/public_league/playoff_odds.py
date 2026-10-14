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
including the open owner decision D2 (the ROS multiplier on top of a ROS-drawn
best-ball pre-sim, ``docs/OWNER_REQUESTED_TODO.md``).  D3 is CLOSED as a
factual defect (TODO-2026-09-26-D3): when the league counts a weekly median
game (``league_average_match``), the record to date, every simulated week and
seeding count it exactly as the host does (:func:`median_game_rule`,
:func:`regular_season_standings_to_date`).  The draft-slot forecast keeps the
head-to-head record until the owner says the draft rule counts median games
(``playoff_sim.DRAFT_ORDER_RECORD_BASIS``).

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


#: ``standingsRule.state`` values — whether the league's weekly median game
#: (``settings.league_average_match``) is part of the record.
MEDIAN_COUNTED = "counted"
MEDIAN_NOT_APPLICABLE = "not_applicable"
MEDIAN_UNVERIFIED = "unverified"

#: Primary host evidence for the median game's semantics (threshold = the
#: average of the two middle scores; an exact-median score is a TIE), recorded
#: in ``docs/game-day/MEDIAN_SEMANTICS_VERIFICATION.md``.  The RECORD rule was
#: re-verified against Sleeper's own roster records on 2026-10-08: dynasty_main
#: (median on), four finished weeks, host W-L-T == H2H + median for 12 of 12
#: rosters; dynasty_new (median off), host == H2H for 10 of 10.
MEDIAN_RULE_SOURCE = (
    "https://support.sleeper.com/en/articles/3971690-extra-game-each-week-against-league-median"
)


def _league_team_count(season: Any) -> int | None:
    """The league's team count, or ``None`` when the host states none."""
    stated = getattr(season, "num_teams", None)
    if isinstance(stated, int) and not isinstance(stated, bool) and stated > 0:
        return stated
    rosters = getattr(season, "rosters", None)
    n = len(rosters) if isinstance(rosters, (list, tuple)) else 0
    return n if n > 0 else None


def median_game_rule(season: Any) -> dict[str, Any]:
    """Does this league's official record count a weekly median game, and is
    the host's rule for it verified?  (TODO-2026-09-26-D3.)

    The setting is the league's OWN ``settings.league_average_match``, read
    through the one reader (``metrics.median_game_enabled``) — never assumed.
    The threshold and tie semantics are Game Day's canonical, host-verified
    ones (``game_day_sim.median_threshold`` /
    ``THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES``), so a realized record,
    a simulated week and a live Game Day median decide the median game one way.

    * ``counted``        — median on, even-sized league: every finished week is
                           two games (H2H + median), exactly as the host records.
    * ``not_applicable`` — the league states the median game is off.
    * ``unverified``     — the setting is absent or unparseable
                           (``median_setting_unknown``), or the median is on in
                           a league whose size the host's documentation does
                           not cover (``median_threshold_unverified_for_league_size``).
                           The median is NOT counted in the record, which is
                           labelled with the reason; the canonical engine
                           refuses every standings-dependent forecast.
    """
    from src.ros.game_day_sim import (  # noqa: PLC0415
        THRESHOLD_SEMANTICS,
        THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES,
    )

    enabled = metrics.median_game_enabled(season) if season is not None else None
    if enabled is False:
        return {"medianGame": False, "state": MEDIAN_NOT_APPLICABLE}
    if enabled is None:
        return {
            "medianGame": None,
            "state": MEDIAN_UNVERIFIED,
            "reason": "median_setting_unknown",
            "detail": (
                "this league's settings do not say whether a weekly median game "
                "counts in the standings (league_average_match), so this record "
                "counts head-to-head games only and may not match the host's "
                "standings; seeding, playoff and draft-slot odds are withheld."
            ),
        }
    teams = _league_team_count(season)
    if teams is None or teams % 2 or not THRESHOLD_SEMANTICS_VERIFIED_FOR_EVEN_LEAGUES:
        return {
            "medianGame": True,
            "state": MEDIAN_UNVERIFIED,
            "reason": "median_threshold_unverified_for_league_size",
            "teams": teams,
            "detail": (
                "this league counts a weekly median game, but the host documents "
                "the median threshold only for leagues with an even number of "
                "teams, so the median game cannot be decided the way the host "
                "decides it."
            ),
        }
    return {
        "medianGame": True,
        "state": MEDIAN_COUNTED,
        "threshold": THRESHOLD_SEMANTICS,
        "tieRule": "exact_median_is_tie",
        "source": MEDIAN_RULE_SOURCE,
    }


def _week_median_threshold(
    entries: list[dict[str, Any]],
    team_count: int | None,
) -> float | None:
    """The league median of one FINISHED week's scores, or ``None`` when the
    week does not carry a score for every team: the threshold is a statistic
    of the whole league's week, and a partial week cannot decide it."""
    from src.ros.game_day_sim import median_threshold  # noqa: PLC0415

    scores: dict[int, float] = {}
    for e in entries:
        rid = metrics.roster_id_of(e)
        pts = e.get("points")
        if rid is None or pts is None or isinstance(pts, bool):
            return None
        try:
            scores[rid] = float(pts)
        except (TypeError, ValueError):
            return None
    if not scores or (team_count is not None and len(scores) != team_count):
        return None
    return median_threshold(list(scores.values()))


def regular_season_standings_to_date(
    season: SeasonSnapshot,
    registry,
) -> tuple[dict[str, dict[str, float | int]], dict[str, Any]]:
    """``(records, rule)`` — the record to date as the HOST counts it.

    ``records`` has :func:`_regular_season_record_to_date`'s shape.  When the
    league's median game is ``counted`` (:func:`median_game_rule`), each
    finished week adds one median result per team — a win above the league
    median, a loss below it, a TIE exactly on it — into ``wins`` / ``losses``
    / ``ties``, and the median half is also published on its own
    (``medianWins`` / ``medianLosses`` / ``medianTies``).  ``rule`` is the
    median rule, plus ``unresolvedWeeks`` when a finished week could not
    decide its median (a team without a score): that week's median game is
    not counted, and the canonical engine refuses rather than seed on it.
    """
    rule = median_game_rule(season)
    final_weeks = _final_week_set(season)
    count_median = rule["state"] == MEDIAN_COUNTED
    team_count = _league_team_count(season)
    unresolved: list[int] = []
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
        if not (count_median and week_is_final and entries):
            continue
        threshold = _week_median_threshold(entries, team_count)
        if threshold is None:
            unresolved.append(wk)
            continue
        for e in entries:
            owner_id = metrics.resolve_owner(registry, season.league_id, metrics.roster_id_of(e))
            if not owner_id:
                continue
            pts = float(e["points"])
            rec = out.setdefault(owner_id, {"wins": 0, "losses": 0, "ties": 0, "pointsFor": 0.0})
            outcome = "wins" if pts > threshold else "losses" if pts < threshold else "ties"
            rec[outcome] += 1
            median_key = "median" + outcome.capitalize()
            rec[median_key] = rec.get(median_key, 0) + 1
    if count_median:
        for rec in out.values():
            for key in ("medianWins", "medianLosses", "medianTies"):
                rec.setdefault(key, 0)
    if unresolved:
        rule = {**rule, "unresolvedWeeks": unresolved}
    return out, rule


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

    MEDIAN GAMES (TODO-2026-09-26-D3): when the league counts a weekly
    median game the record includes it, exactly as the host's standings do —
    see :func:`regular_season_standings_to_date`, which also returns the rule.
    """
    return regular_season_standings_to_date(season, registry)[0]


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


def _simulation_count(forecast: dict[str, Any]) -> int | None:
    """The canonical forecast's simulation count, or ``None`` — the engine's
    own reader, so both adapter surfaces agree on it."""
    from src.ros.playoff_sim import simulation_count  # noqa: PLC0415

    return simulation_count(forecast)


def _why_not_simulated(n_sims: int | None, by_owner: dict[str, Any]) -> dict[str, str]:
    """The exact reason a forecast with no ``unsimulable`` block still yields
    no published probability — each state named, none folded into another."""
    from src.ros.playoff_sim import SIM_COUNT_MISSING  # noqa: PLC0415

    if n_sims is None:
        return {
            "reason": SIM_COUNT_MISSING,
            "detail": (
                "the playoff forecast does not say how many simulations it ran, so "
                "its odds cannot be presented as a measurement. This is not a 0% "
                "chance for anyone."
            ),
        }
    if n_sims == 0:
        return {
            "reason": "canonical_forecast_ran_no_simulations",
            "detail": (
                "the playoff forecast reports zero simulations, so there are no "
                "odds to publish. This is not a 0% chance for anyone."
            ),
        }
    return {
        "reason": "canonical_forecast_has_no_team_rows",
        "detail": (
            f"the playoff forecast reports {n_sims} simulations but no team rows, "
            "so no team's odds can be published. This is not a 0% chance for anyone."
        ),
    }


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

    current_record, standings_rule = regular_season_standings_to_date(season, registry)

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
    n_sims = _simulation_count(forecast)
    simulated = bool(by_owner) and not unsimulable and bool(n_sims)

    owners: list[dict[str, Any]] = []
    for o in owners_in_league:
        probability = _probability(by_owner.get(o)) if simulated else None
        row = _row(o, probability)
        if simulated and probability is None:
            row["unavailableReason"] = "owner_absent_from_canonical_forecast"
        owners.append(row)

    out: dict[str, Any] = {
        "season": season.season,
        # The canonical run's own count: a real 0 when it refused, ``None``
        # (reason in ``unsimulable``) when the forecast reported none.
        "numSims": n_sims if (simulated or n_sims == 0) else None,
        "playoffSpots": spots,
        "weeksPlayed": len(played_weeks),
        "weeksRemaining": len(remaining_weeks),
        "scheduleCertainty": certainty,
        # Stamped on every return path that reaches the engine: absent and
        # False must not read the same.
        "simulated": simulated,
        "engine": ENGINE,
        "playoffStructure": structure.to_dict(),
        # Whether ``currentWins`` counts the weekly median game (D3), and, when
        # the rule is unverified, why — beside the record it describes.
        "standingsRule": standings_rule,
        "owners": owners,
    }
    if unposted:
        out["unpostedWeeks"] = unposted
    if unsimulable:
        out["unsimulable"] = unsimulable
    elif not simulated:
        out["unsimulable"] = _why_not_simulated(n_sims, by_owner)
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
