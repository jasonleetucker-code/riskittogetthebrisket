"""Resolve a live league-week into the inputs `game_day_sim` simulates.

`src/ros/game_day_sim.py` is the canonical current-week simulation and is
deliberately pure: it takes `LeagueWeekRules`, `TeamWeek`s and an opponent
map and knows nothing about Sleeper.  It shipped with **zero callers** — a
grep for `game_day_sim` across `src/`, `scripts/` and `server.py` returned
nothing — which is the same shape `game_day_archive` was in before
`game_day_capture` became its resolver.  This module is that missing half:
already-fetched Sleeper payloads plus an estimate index in, simulation
inputs out.

**It is not a third owner of the roster.**  Player enumeration, position
resolution and the non-active (IR / taxi) subtraction all come from
`src/ros/game_day_capture.py`, which already owns them for the archive;
slot rules and eligibility come from `src/ros/lineup.py`.  What is genuinely
new here — and the only reason a module is needed rather than a function —
is the **per-player state axis** the archive has no use for, because the
archive is pregame-only by construction while the simulation is not.

**Scheduled, live and final stay evidence-bounded.**  The pregame adapter
still refuses a begun week. :func:`resolve_scoring_week` adds actual host
scores and explicit game evidence around that canonical roster/lineup input.
The existing nflverse schedule cache proves scheduled and completed games;
it does not by itself prove a game is live. An in-progress source enters
through the typed :class:`GameEvidence` seam, which now also carries
``kickoff_at`` evidence used for the OWNER-APPROVED remaining-production
methodology below.

**In-progress remaining production — OBSERVED CLOCK first (owner contract
2026-09-24, reconciling the 2026-09-09 decision).**  The 2026-09-09 owner
decision chose a PRORATED remaining (option B, "remaining = 0 for every
in-progress player", was rejected) and, with no live clock wired, measured
progress as wall time since kickoff over a fixed assumed duration.  The
2026-09-24 contract ("observe actual quarter/clock/status; elapsed wall
time since kickoff is not sufficient") keeps the proration and changes what
it is prorated BY:

* **primary — ``remainingBasis = "observed_clock"``:**
  ``remaining = pregame provider baseline x regulation_fraction_remaining``
  where the fraction comes from the OBSERVED quarter and clock
  (:func:`src.nfl_data.live_game_state.regulation_fraction_remaining`,
  reached through :func:`observed_game_evidence`).  Overtime, a possible
  overtime (tied at the end of regulation), delays, postponements,
  cancellations, unknown statuses and a stale observation give NO fraction:
  the player's remaining is ``None`` and the reason is published — overtime
  time is never invented.  This is a simple observed-clock baseline, not a
  usage / injury / game-script model, and is labelled as such.
* **degraded fallback — ``remainingBasis = "wall_time_fallback"``:** only
  for ``in_progress`` evidence that carries NO observed phase (the legacy
  :class:`GameEvidence` seam).  Wall time since ``kickoff_at`` over
  ``_ASSUMED_GAME_DURATION_SECONDS``; it is never presented as observed and
  it can never finish a game by itself — once the assumed duration has
  elapsed without an observed final, remaining is ``None``
  (``wall_time_exhausted_without_observed_final``), not 0.0.  The nflverse
  schedule cache never asserts ``in_progress``, so with the live feed off
  this branch is unreachable from the matchup endpoint: a passed kickoff
  stays ``unknown`` and probability is withheld.

The baseline is never reduced by actual points already scored (that would
count them twice); banked points and remaining production are separate
terms.

**Missing/stale game-progress evidence degrades honestly; it is never
guessed.**  When a player is evidenced ``in_progress`` but has a
``projected_remaining`` and no usable ``kickoff_at`` (or ``now`` precedes
it), remaining stays ``None`` and the player is reported in
``progress_unavailable_player_ids`` — this is a *missing-evidence* state,
never a *methodology-undecided* state (that seam is now closed; see the
2026-09-09 decision above).  A `completed` game or a host-declared `Out`
(definitively finished) is a DIFFERENT case: remaining is `0.0`, not
`None`, because the game being over IS positive evidence nothing further
is coming — that is not a guess, and coercing it to `None` would hide a
fact behind the same spelling used for genuine absence of evidence.

**Missing is never zero, and the three ways a player can be absent stay
distinct:**

* **ineligible** — in the roster's `reserve` / `taxi` buckets.  He cannot
  legally start, so he is not part of the week at all and is reported in
  `ineligible_player_ids`.  Leaving him in the pool at a 0.0 draw would let
  him occupy a slot on a thin roster, which is a lineup the host would not
  award.
* **unpriced** — active, startable, but no projection source covers him.
  He enters as `state="unknown"`, which `game_day_sim._drawable` excludes
  and `unsimulable_player_ids` reports.  He is never drawn as zero.
* **priced** — `state="not_started"` with `projected_remaining` set to the
  per-game estimate.  Nothing is banked pregame, which is an observation
  (the games have not kicked off), not a gap.

**Known limitation, named rather than papered over.**  A host-declared
`Out` is unavailable; less certain injury labels remain projections.  The
observed-clock baseline scales a pregame projection by regulation time
left; it knows nothing about possession, score, injuries or usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.ros.game_day_capture import (
    _display_name,
    _player_positions,
    non_active_player_ids,
    week_has_begun,
)
from src.ros.game_day_sim import (
    LeagueWeekRules,
    PlayerWeek,
    TeamWeek,
    rules_from_league,
)
from src.ros.lineup import lineup_position
from src.utils.name_clean import normalize_player_name


class GameDayWeekRefusal(RuntimeError):
    """The week cannot be resolved as asked, and saying so beats guessing."""


@dataclass(frozen=True)
class WeekResolution:
    """Everything `simulate_league_week` needs, plus what was lost getting here."""

    rules: LeagueWeekRules
    teams: tuple[TeamWeek, ...]
    #: team_id -> opponent team_id, or ``None`` for a team with no
    #: scheduled opponent. Team ids are Sleeper roster ids as strings.
    opponents: dict[str, str | None]
    #: ``(players with an estimate, active players)`` across the league.
    #: Two numbers rather than a ratio so "no projections at all" and
    #: "thin coverage" cannot read the same.
    estimate_coverage: tuple[int, int]
    #: Per team: active players no source priced. These are simulable
    #: by nothing, and the simulation reports them again itself.
    unpriced_player_ids: dict[str, tuple[str, ...]]
    #: Per team: players the roster's own buckets exclude from starting.
    ineligible_player_ids: dict[str, tuple[str, ...]]
    estimate_source: str | None
    notes: list[str] = field(default_factory=list)


def opponents_from_matchups(
    matchups: Sequence[Mapping[str, Any]] | None,
) -> dict[str, str | None]:
    """roster_id -> opponent roster_id from one week's matchup rows.

    A `matchup_id` that does not hold exactly two rosters yields ``None``
    for each of its members rather than an arbitrary pairing: a bye, a
    partial payload and a three-way row are all "no opponent I can name",
    and `game_day_sim` turns that into `UNSIMULABLE`, never 50%.
    """
    groups: dict[Any, list[str]] = {}
    loose: list[str] = []
    for row in matchups or ():
        if not isinstance(row, Mapping):
            continue
        rid = row.get("roster_id")
        if rid is None:
            continue
        mid = row.get("matchup_id")
        if mid is None:
            loose.append(str(rid))
            continue
        groups.setdefault(mid, []).append(str(rid))

    out: dict[str, str | None] = {rid: None for rid in loose}
    for members in groups.values():
        if len(members) == 2:
            a, b = members
            out[a] = b
            out[b] = a
        else:
            for rid in members:
                out[rid] = None
    return out


def _team_week(
    *,
    roster: Mapping[str, Any],
    players_meta: Mapping[str, Any],
    estimates: Mapping[str, float],
    has_estimates: bool,
    estimates_by_player_id: Mapping[str, float] | None = None,
) -> tuple[TeamWeek, tuple[str, ...], tuple[str, ...], int]:
    """One roster -> ``(TeamWeek, unpriced ids, ineligible ids, active count)``.

    ``estimates_by_player_id`` (Sleeper player id -> points) is the join
    of record when supplied; the legacy normalized-name ``estimates`` map
    is consulted only when it is not.
    """
    team_id = str(roster.get("roster_id"))
    ineligible = non_active_player_ids(roster)

    players: list[PlayerWeek] = []
    unpriced: list[str] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for raw in roster.get("players") or ():
        if not raw:
            continue
        pid = str(raw)
        if pid in seen:
            # Same host artifact `build_team_roster` collapses: a roster
            # listing one player twice is not two roster spots.
            continue
        seen.add(pid)
        if pid in ineligible:
            excluded.append(pid)
            continue

        meta = players_meta.get(pid) if isinstance(players_meta, Mapping) else None
        primary, fantasy = _player_positions(meta)
        estimate: float | None = None
        if has_estimates and estimates_by_player_id is not None:
            found = estimates_by_player_id.get(pid)
            if found is not None:
                estimate = float(found)
        elif has_estimates:
            name_key = normalize_player_name(_display_name(meta, pid))
            if name_key:
                found = estimates.get(name_key)
                if found is not None:
                    estimate = float(found)

        if estimate is None:
            unpriced.append(pid)

        players.append(
            PlayerWeek(
                player_id=pid,
                # The lineup vocabulary, because `_team_score` hands this
                # straight to the canonical slot solver.
                position=lineup_position(primary) if primary else "",
                state="not_started" if estimate is not None else "unknown",
                # Pregame: nothing is banked. That is an observation, not
                # a gap — the games have not kicked off.
                points_scored=0.0,
                projected_remaining=estimate,
                fantasy_positions=tuple(fantasy),
            )
        )

    return (
        TeamWeek(team_id=team_id, players=tuple(players)),
        tuple(unpriced),
        tuple(excluded),
        len(players),
    )


def resolve_pregame_week(
    *,
    league_key: str,
    league_payload: Mapping[str, Any],
    rosters: Sequence[Mapping[str, Any]],
    matchups: Sequence[Mapping[str, Any]] | None,
    players_meta: Mapping[str, Any],
    starter_slots: Sequence[str],
    estimates: Mapping[str, float] | None = None,
    estimate_source: str | None = None,
    estimates_by_player_id: Mapping[str, float] | None = None,
) -> WeekResolution:
    """Resolve one UNPLAYED league-week into simulation inputs.

    Raises :class:`GameDayWeekRefusal` once the week has begun — see the
    module docstring for why that is a refusal and not a degraded answer —
    and for the two states that make the result meaningless rather than
    merely thin: no rosters, and no starter slots (a lineup filled from an
    empty slot list is a fiction, which `LeagueWeekRules` also refuses).

    A league with NO projection snapshot still resolves: every player comes
    back `unknown`, the simulation reports them all unsimulable, and the
    caller can say "we cannot price this week" instead of publishing a
    number built on nothing.
    """
    if week_has_begun(matchups):
        raise GameDayWeekRefusal(
            f"{league_key}: the week has already begun (the host reports a nonzero "
            "score). Resolving it as pregame would treat banked points as still "
            "uncertain; distinguishing completed from in-progress needs a live "
            "game-state source this repo does not wire."
        )
    if not rosters:
        raise GameDayWeekRefusal(f"{league_key}: no rosters to resolve")
    if not starter_slots:
        raise GameDayWeekRefusal(
            f"{league_key}: no starter slots resolved — lineup eligibility would be "
            "a fiction and defaulting a slot list would simulate a different league."
        )

    rules = rules_from_league(
        league_key=league_key,
        league_payload=league_payload,
        starter_slots=starter_slots,
    )

    has_estimates = bool(estimate_source) and bool(estimates or estimates_by_player_id)
    est: Mapping[str, float] = estimates or {}

    teams: list[TeamWeek] = []
    unpriced: dict[str, tuple[str, ...]] = {}
    ineligible: dict[str, tuple[str, ...]] = {}
    priced_total = 0
    active_total = 0
    for roster in rosters:
        team, team_unpriced, team_ineligible, active = _team_week(
            roster=roster,
            players_meta=players_meta,
            estimates=est,
            has_estimates=has_estimates,
            estimates_by_player_id=estimates_by_player_id,
        )
        teams.append(team)
        unpriced[team.team_id] = team_unpriced
        ineligible[team.team_id] = team_ineligible
        active_total += active
        priced_total += active - len(team_unpriced)

    opponents = opponents_from_matchups(matchups)
    # Every resolved team needs an entry, including one the matchup payload
    # never mentions: an ABSENT key and a key holding ``None`` must not be
    # left to the simulator to tell apart.
    for team in teams:
        opponents.setdefault(team.team_id, None)

    notes: list[str] = []
    if not has_estimates:
        notes.append(
            "no projection snapshot: every player is unsimulable, so no probability "
            "is derivable for this week"
        )
    elif priced_total < active_total:
        notes.append(
            f"{active_total - priced_total} of {active_total} active players are "
            "unpriced and are excluded from every draw rather than drawn as zero"
        )
    unscheduled = [tid for tid, opp in opponents.items() if opp is None]
    if unscheduled:
        notes.append(f"no scheduled opponent for roster(s) {', '.join(sorted(unscheduled))}")

    return WeekResolution(
        rules=rules,
        teams=tuple(teams),
        opponents=opponents,
        estimate_coverage=(priced_total, active_total),
        unpriced_player_ids=unpriced,
        ineligible_player_ids=ineligible,
        estimate_source=estimate_source if has_estimates else None,
        notes=notes,
    )


@dataclass(frozen=True)
class GameEvidence:
    """An observed NFL state, never an estimate of remaining production.

    `unknown` includes a scheduled kickoff which has passed without a live
    status feed: elapsed wall time does not prove a game actually started.

    ``phase`` is set only when a LIVE feed observed the game (a
    :data:`src.nfl_data.live_game_state.PHASES` value).  Then
    ``remaining_fraction`` is the observed share of regulation left, or
    ``None`` with ``remaining_reason`` naming why it cannot be stated
    (``overtime``, ``delayed``, ``stale_live_state`` …).  ``phase is None``
    marks evidence with no observed clock — schedule/result evidence, or a
    caller asserting a state without one.
    """

    state: str
    source: str
    observed_at: float | None
    kickoff_at: float | None = None
    game_id: str | None = None
    phase: str | None = None
    period: int | None = None
    clock_seconds: float | None = None
    remaining_fraction: float | None = None
    remaining_reason: str | None = None
    status_detail: str | None = None

    def __post_init__(self):
        if self.state not in {"not_started", "in_progress", "completed", "unknown"}:
            raise GameDayWeekRefusal(f"unsupported game evidence state: {self.state}")
        if not self.source:
            raise GameDayWeekRefusal("game evidence requires a source")


def _finite_points(value: Any) -> float | None:
    import math

    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _normalize_nfl_team(code: Any) -> str:
    """nflverse LA is Sleeper LAR; no player identity guessing."""
    team = str(code or "").upper()
    return "LAR" if team == "LA" else team


def _row_game_state(
    row: Mapping[str, Any], *, season: int, week: int, now: float
) -> tuple[str, str, str, float | None, float | None, float | None] | None:
    """One nflverse schedule row -> ``(home, away, state, kickoff_at, home_score, away_score)``.

    Returns ``None`` for a row outside this season/week or not a regular-season
    game. Shared by :func:`schedule_game_evidence` (per-team) and
    :func:`schedule_games` (per-game) so the two never derive state/kickoff
    differently for the same row.
    """
    from src.ros.game_day_capture import first_kickoff_utc

    try:
        if int(row.get("season")) != season or int(row.get("week")) != week:
            return None
    except (TypeError, ValueError):
        return None
    if row.get("game_type") != "REG":
        return None
    kickoff = first_kickoff_utc([row], season=season, week=week)
    stamp = kickoff.timestamp() if kickoff else None
    home_score = _finite_points(row.get("home_score"))
    away_score = _finite_points(row.get("away_score"))
    result_score = _finite_points(row.get("result"))
    scores = (home_score, away_score, result_score)
    if all(s is not None for s in scores) and stamp is not None and stamp <= now:
        state = "completed"
    elif stamp is not None and stamp > now:
        state = "not_started"
    else:
        state = "unknown"
    home = _normalize_nfl_team(row.get("home_team"))
    away = _normalize_nfl_team(row.get("away_team"))
    return home, away, state, stamp, home_score, away_score


def schedule_game_evidence(rows, *, season, week, observed_at, now):
    """Shape the canonical nflverse schedule; do not create a downloader.

    The schedule dictionary describes scores as results for played games.
    Both scores + result constitute completed-game evidence. A past kickoff
    without a result stays unknown (not a fabricated in-progress status).
    Explicit live game states can enter through GameEvidence when a source
    capable of observing them is wired. Source age is carried unchanged.
    """
    result = {}
    for row in rows:
        derived = _row_game_state(row, season=season, week=week, now=now)
        if derived is None:
            continue
        home, away, state, stamp, _home_score, _away_score = derived
        game_id = f"{season}_{week}_{away}_{home}" if home and away else None
        for team in (home, away):
            if team:
                result[team] = GameEvidence(
                    state, "nflverse:schedules", observed_at, stamp, game_id=game_id
                )
    return result


@dataclass(frozen=True)
class NflGame:
    """One real NFL game for a week — a first-class object, unlike `GameEvidence`.

    `GameEvidence` is per-TEAM (the same evidence written under both the home
    and away team codes, with no pairing between them). This is the missing
    per-game shape: a chronologically-orderable list of real games, each with
    both teams and a single kickoff, for surfaces that need to render "the
    week's NFL slate" rather than answer "is this one team's game live yet".
    """

    game_id: str
    home_team: str
    away_team: str
    kickoff_at: float | None
    state: str
    home_score: float | None = None
    away_score: float | None = None

    def __post_init__(self):
        if self.state not in {"not_started", "in_progress", "completed", "unknown"}:
            raise GameDayWeekRefusal(f"unsupported game evidence state: {self.state}")


def schedule_games(rows, *, season: int, week: int, now: float) -> list[NflGame]:
    """The complete real NFL schedule for one week, as first-class per-game objects.

    Ordered by `kickoff_at` ascending; a row with no resolvable kickoff sorts
    LAST, never first — an unknown kickoff must never read as "the earliest
    game", which is a fact this data does not support. Reuses the exact same
    per-row state/kickoff derivation `schedule_game_evidence` uses, so the two
    can never disagree about what one row means.
    """
    games: list[NflGame] = []
    for row in rows:
        derived = _row_game_state(row, season=season, week=week, now=now)
        if derived is None:
            continue
        home, away, state, stamp, home_score, away_score = derived
        if not home or not away:
            # No player identity to guess here either: a row missing a team
            # code names no real game and is dropped rather than fabricated.
            continue
        games.append(
            NflGame(
                game_id=f"{season}_{week}_{away}_{home}",
                home_team=home,
                away_team=away,
                kickoff_at=stamp,
                state=state,
                home_score=home_score,
                away_score=away_score,
            )
        )
    games.sort(key=lambda g: (g.kickoff_at is None, g.kickoff_at))
    return games


# The DEGRADED wall-time fallback's assumed kickoff-to-final duration (see
# the module docstring). A single fixed constant by design, never a
# per-game measurement; used only when no observed clock exists.
_ASSUMED_GAME_DURATION_SECONDS = 3.25 * 3600.0

#: ``remainingBasis`` vocabulary — how a player's remaining production was
#: derived.  Published per player so a consumer never has to guess.
REMAINING_BASIS_PREGAME = "pregame_full_baseline"
REMAINING_BASIS_OBSERVED_CLOCK = "observed_clock"
REMAINING_BASIS_WALL_TIME_FALLBACK = "wall_time_fallback"
REMAINING_BASIS_GAME_OVER = "game_over"

#: How old an observed live game state may be before it stops counting as
#: current: 3x the Game Day panel's 60 s poll cadence — the repo's existing
#: "three missed cadences" staleness rule (``SCRAPE_INTERVAL_HOURS * 3``)
#: applied to the live cadence, not a tuned number.
LIVE_STATE_MAX_AGE_SECONDS = 180.0


def _wall_time_fallback_remaining(
    projected_remaining: float,
    kickoff_at: float | None,
    now: float,
) -> tuple[float | None, str | None]:
    """DEGRADED fallback: ``(remaining, reason_unavailable)`` from wall time.

    Never reaches 0.0 on elapsed time alone: a wall-clock timer cannot
    prove a game ended (overtime, delays), so once the assumed duration
    has passed without an observed final the answer is ``None``.
    """
    if kickoff_at is None or now < kickoff_at:
        return None, "no_kickoff_evidence"
    elapsed = now - kickoff_at
    if elapsed >= _ASSUMED_GAME_DURATION_SECONDS:
        return None, "wall_time_exhausted_without_observed_final"
    return projected_remaining * (1.0 - elapsed / _ASSUMED_GAME_DURATION_SECONDS), None


def _remaining_for(
    baseline: float | None,
    state: str,
    game: GameEvidence | None,
    now: float,
) -> tuple[float | None, str | None, str | None]:
    """``(remaining, remainingBasis, reason_unavailable)`` for one player.

    ``baseline`` is the PREGAME provider baseline (never reduced by points
    already scored).  ``reason_unavailable`` is set only when a real
    baseline exists but the game's progress cannot be stated — an unpriced
    player (``baseline is None``) is a different, separately reported gap.
    """
    if state in ("completed", "inactive"):
        return 0.0, REMAINING_BASIS_GAME_OVER, None
    if state not in ("not_started", "in_progress") or baseline is None:
        return None, None, None
    observed = game is not None and game.phase is not None
    if observed:
        if game.remaining_fraction is None:
            return None, None, game.remaining_reason or "live_progress_unknown"
        basis = (
            REMAINING_BASIS_PREGAME if state == "not_started" else REMAINING_BASIS_OBSERVED_CLOCK
        )
        return baseline * game.remaining_fraction, basis, None
    if state == "not_started":
        return baseline, REMAINING_BASIS_PREGAME, None
    remaining, reason = _wall_time_fallback_remaining(
        baseline, game.kickoff_at if game else None, now
    )
    return remaining, (REMAINING_BASIS_WALL_TIME_FALLBACK if reason is None else None), reason


@dataclass(frozen=True)
class ObservedSlate:
    """Live game evidence from one scoreboard observation, per NFL team.

    ``state`` is ``observed`` | ``disabled`` | ``unavailable`` |
    ``week_mismatch``; only ``observed`` carries evidence.  ``stale`` is
    True when the observation is older than ``LIVE_STATE_MAX_AGE_SECONDS``
    (its non-final in-game states then carry ``stale_live_state``).
    """

    evidence: dict[str, GameEvidence]
    state: str
    reason: str | None
    observed_at: float | None
    stale: bool = False
    unmatched_game_ids: tuple[str, ...] = ()
    #: Which provider's scoreboard this slate was read from
    #: (``espn:scoreboard`` / ``sportsdataio:scores``); ``None`` when no
    #: provider was read at all (no observation, or the feed is disabled).
    source: str | None = None


def _observed_state(obs: Any) -> tuple[str, float | None, str | None]:
    """``(evidence state, remaining fraction, reason)`` for one observed game."""
    from src.nfl_data import live_game_state as lgs

    phase = obs.phase
    rr = lgs.regulation_fraction_remaining(obs)
    if phase == lgs.PHASE_SCHEDULED:
        return "not_started", rr.fraction, rr.reason
    if phase == lgs.PHASE_FINAL:
        return "completed", 0.0, None
    if phase in (lgs.PHASE_IN_PROGRESS, lgs.PHASE_END_PERIOD, lgs.PHASE_HALFTIME):
        fraction, reason = rr.fraction, rr.reason
        # End of regulation is 0.0 regulation time left, but a TIED game
        # (or one whose score was not stated) may still go to overtime.
        # Not invented either way: withheld until a final is observed.
        at_end = fraction == 0.0 and (obs.period or 0) >= 4
        tied = obs.home_score is None or obs.away_score is None or obs.home_score == obs.away_score
        if at_end and tied:
            fraction, reason = None, "overtime_possible"
        return "in_progress", fraction, reason
    if phase in (lgs.PHASE_DELAYED, lgs.PHASE_POSTPONED, lgs.PHASE_CANCELED):
        state = "in_progress" if obs.lifecycle_state == "in" else "not_started"
        return state, None, rr.reason or phase.lower()
    return "unknown", None, rr.reason or f"unknown_status:{obs.phase_reason}"


def observed_game_evidence(
    snapshot: Any,
    *,
    schedule_rows: Sequence[Mapping[str, Any]] | None,
    season: int,
    week: int,
    now: float,
    max_age_seconds: float = LIVE_STATE_MAX_AGE_SECONDS,
) -> ObservedSlate:
    """Per-team :class:`GameEvidence` from an ESPN scoreboard observation.

    Joins each observed game to our schedule by normalized team codes plus
    a kickoff within 36 hours (ESPN ``WSH`` and nflverse ``LA`` are both
    normalized first), taking the schedule's ``game_id`` when it matches;
    an observed game with no schedule row keeps an id built the same way
    and is listed in ``unmatched_game_ids`` — the observation is still
    evidence about those two teams.  A scoreboard for a different season /
    week / season type is refused outright rather than half-used.
    """
    if snapshot is None:
        return ObservedSlate({}, "unavailable", "no_observation", None)
    if not getattr(snapshot, "enabled", True):
        return ObservedSlate({}, "disabled", snapshot.error or "flag_disabled", None)
    observed_at = snapshot.observed_at.timestamp() if snapshot.observed_at else None
    label = getattr(snapshot, "source_label", "espn:scoreboard")
    if not snapshot.ok:
        return ObservedSlate({}, "unavailable", snapshot.error, observed_at, source=label)
    if (snapshot.season not in (None, season)) or (snapshot.week not in (None, week)):
        return ObservedSlate(
            {},
            "week_mismatch",
            f"scoreboard is {snapshot.season}/{snapshot.week}, asked {season}/{week}",
            observed_at,
            source=label,
        )
    if snapshot.season_type not in (None, 2):
        return ObservedSlate(
            {},
            "week_mismatch",
            f"season_type {snapshot.season_type} is not regular",
            observed_at,
            source=label,
        )

    scheduled: dict[frozenset[str], list[NflGame]] = {}
    for g in schedule_games(schedule_rows or (), season=season, week=week, now=now):
        scheduled.setdefault(frozenset((g.home_team, g.away_team)), []).append(g)

    evidence: dict[str, GameEvidence] = {}
    unmatched: list[str] = []
    stale_any = False
    for obs in snapshot.games:
        home = _normalize_nfl_team(obs.home_team)
        away = _normalize_nfl_team(obs.away_team)
        if not home or not away:
            continue
        kickoff = obs.kickoff.timestamp() if obs.kickoff else None
        match = None
        for cand in scheduled.get(frozenset((home, away)), ()):
            if kickoff is None or cand.kickoff_at is None:
                continue
            if abs(cand.kickoff_at - kickoff) <= 36 * 3600:
                match = cand
                break
        game_id = match.game_id if match else f"{season}_{week}_{away}_{home}"
        if match is None:
            unmatched.append(game_id)
        state, fraction, reason = _observed_state(obs)
        obs_at = obs.observed_at.timestamp() if obs.observed_at else observed_at
        age = (now - obs_at) if obs_at is not None else None
        if age is None or age > max_age_seconds:
            from src.nfl_data import live_game_state as lgs

            future_kickoff = kickoff is not None and kickoff > now
            if obs.phase == lgs.PHASE_FINAL or (state == "not_started" and future_kickoff):
                pass  # a final is terminal; an unplayed future game cannot have begun
            else:
                stale_any = True
                if state == "not_started":
                    state = "unknown"
                fraction, reason = None, "stale_live_state"
        ev = GameEvidence(
            state=state,
            source=obs.source_label,
            observed_at=obs_at,
            kickoff_at=kickoff if kickoff is not None else (match.kickoff_at if match else None),
            game_id=game_id,
            phase=obs.phase,
            period=obs.period,
            clock_seconds=obs.clock_seconds,
            remaining_fraction=fraction,
            remaining_reason=reason,
            status_detail=obs.status_detail,
        )
        evidence[home] = ev
        evidence[away] = ev
    return ObservedSlate(
        evidence, "observed", None, observed_at, stale_any, tuple(sorted(unmatched)), source=label
    )


def merge_game_evidence(
    schedule: Mapping[str, GameEvidence], observed: ObservedSlate | None
) -> dict[str, GameEvidence]:
    """Observed evidence wins per team; schedule evidence fills the rest.

    A team the live feed did not report keeps its schedule/result evidence,
    which never asserts ``in_progress`` — so a gap in the live feed degrades
    to ``unknown`` for a begun game, never to a wall-clock guess.
    """
    merged = dict(schedule)
    if observed is not None:
        merged.update(observed.evidence)
    return merged


@dataclass(frozen=True)
class ScoringWeekResolution:
    week: WeekResolution
    mode: str
    host_scores: dict[str, float | None]
    progress_unavailable_player_ids: tuple[str, ...]
    game_evidence: Mapping[str, GameEvidence]
    #: player_id -> why his remaining production cannot be stated
    #: (``overtime``, ``delayed``, ``stale_live_state``, ``no_kickoff_evidence`` …).
    progress_unavailable_reasons: Mapping[str, str] = field(default_factory=dict)
    #: player_id -> ``remainingBasis`` for every player with a remaining value.
    remaining_basis: Mapping[str, str] = field(default_factory=dict)


def resolve_scoring_week(
    *,
    league_key,
    league_payload,
    rosters,
    matchups,
    players_meta,
    starter_slots,
    estimates=None,
    estimate_source=None,
    game_evidence: Mapping[str, GameEvidence] | None = None,
    now: float | None = None,
    estimates_by_player_id: Mapping[str, float] | None = None,
) -> ScoringWeekResolution:
    """Factual scheduled/live/final state; in-progress remaining PRORATED.

    See the module docstring: the pregame baseline is scaled by the
    OBSERVED share of regulation left when a live feed observed the game,
    by the labelled wall-time fallback only for evidence with no observed
    clock, and is withheld (``None`` + reason in
    ``progress_unavailable_reasons``) when neither can state it. A
    ``completed`` or definitively-``inactive`` (host-declared ``Out``)
    player's remaining is ``0.0`` — real evidence nothing further is
    coming, not a guess.
    """
    import time
    from dataclasses import replace

    evidence = game_evidence or {}
    current = time.time() if now is None else now
    begun = week_has_begun(matchups) or any(
        g.state in {"in_progress", "completed"}
        or (g.kickoff_at is not None and g.kickoff_at <= current)
        for g in evidence.values()
    )
    # Reuse the pregame owner for roster enumeration, projection joining,
    # IR/taxi exclusion, positions and rules. Only state is adapted below.
    base = resolve_pregame_week(
        league_key=league_key,
        league_payload=league_payload,
        rosters=rosters,
        matchups=None if begun else matchups,
        players_meta=players_meta,
        starter_slots=starter_slots,
        estimates=estimates,
        estimate_source=estimate_source,
        estimates_by_player_id=estimates_by_player_id,
    )
    by_id = {str(m.get("roster_id")): m for m in matchups or ()}
    opponents = opponents_from_matchups(matchups)
    teams = []
    progress_unavailable = []
    unavailable_reasons: dict[str, str] = {}
    basis_by_player: dict[str, str] = {}
    host_scores = {}
    unpriced = {}
    final = bool(evidence) and all(g.state == "completed" for g in evidence.values())
    for team in base.teams:
        matchup = by_id.get(team.team_id, {})
        score_map = matchup.get("players_points")
        score_map = score_map if isinstance(score_map, Mapping) else {}
        host_scores[team.team_id] = _finite_points(matchup.get("points")) if begun else None
        players = []
        for p in team.players:
            meta_record = (
                players_meta.get(p.player_id) if isinstance(players_meta, Mapping) else None
            )
            metadata_present = isinstance(meta_record, Mapping)
            meta = meta_record if metadata_present else {}
            raw_team = str(meta.get("team") or "").upper()
            # A player with a PRESENT metadata record but NO team on file
            # (a true free agent/unrostered dynasty stash) is a definitive
            # fact he has no game this week. A completely missing metadata
            # row is different: it is unknown evidence and must never be
            # coerced to inactive/zero merely because other schedule
            # evidence exists.
            #
            # Gated on `evidence` itself being non-empty: when the schedule
            # feed produced NOTHING, an absent team means "we cannot resolve
            # anyone right now", not "he is definitely out" — the same
            # conservative default every other player gets.
            no_team_on_file = metadata_present and not raw_team and bool(evidence)
            game = evidence.get(raw_team) if raw_team else None
            if no_team_on_file:
                state = "inactive" if begun else "not_started"
            else:
                state = game.state if game else ("unknown" if begun else "not_started")
            actual = _finite_points(score_map.get(p.player_id)) if begun else 0.0
            if state == "not_started" or no_team_on_file:
                actual = 0.0
            # Out is host-declared unavailability, unlike Doubtful or
            # Questionable. Do not override a recorded completed score.
            if meta.get("injury_status") == "Out" and state != "completed":
                state = "inactive"
                if actual is None:
                    actual = 0.0
            # `p.projected_remaining` is the PREGAME baseline from the
            # pregame owner; completed/inactive -> 0.0 (definitive), unknown
            # -> None, in-game -> baseline x observed fraction (or the
            # labelled fallback / withheld).  See `_remaining_for`.
            remaining, basis, unavailable_reason = _remaining_for(
                p.projected_remaining, state, None if no_team_on_file else game, current
            )
            if unavailable_reason is not None:
                progress_unavailable.append(p.player_id)
                unavailable_reasons[p.player_id] = unavailable_reason
            if basis is not None:
                basis_by_player[p.player_id] = basis
            if state == "unknown" and begun:
                # An explicit game-state feed is also required here.
                # A nonzero score alone cannot tell live from completed.
                final = False
            if state == "completed" and actual is None:
                # Sleeper's per-player score map omits an entry for a
                # player it attributed no stats to, rather than stamping
                # an explicit 0.0 — but his roster's own `points` total
                # (read above from the host directly) already includes
                # that zero contribution. 0.0 here is the evidenced fact
                # this now-finished game produced, not a guess standing
                # in for missing evidence.
                actual = 0.0
            players.append(
                replace(
                    p,
                    state=state,
                    points_scored=actual,
                    projected_remaining=remaining,
                    nfl_game_id=game.game_id if game is not None else None,
                )
            )
        # `.get(..., ())` only guards a MISSING key — Sleeper's live matchup
        # payload can carry an explicit `"starters": null` (observed on a
        # best-ball league, where declared starters do not apply), which
        # `.get` still hands back verbatim and crashes the iteration below.
        starters = tuple(
            str(pid) for pid in (matchup.get("starters") or ()) if pid and str(pid) != "0"
        )
        teams.append(replace(team, players=tuple(players), declared_starters=starters))
        opponents.setdefault(team.team_id, None)
        unpriced[team.team_id] = tuple(
            p.player_id
            for p in players
            if p.state == "not_started"
            and p.projected_remaining is None
            and p.player_id not in unavailable_reasons
        )
    notes = list(base.notes) if not begun else []
    if progress_unavailable:
        reasons = sorted(set(unavailable_reasons.values()))
        notes.append(
            "GAME_PROGRESS_UNAVAILABLE: remaining production could not be stated for "
            f"{len(progress_unavailable)} player(s) ({', '.join(reasons)}); their "
            "probability inputs are withheld rather than guessed"
        )
    if begun and any(p.state == "unknown" for t in teams for p in t.players):
        notes.append(
            "game-state coverage incomplete: a past kickoff is not an observed live/final status"
        )
    resolved = replace(
        base, teams=tuple(teams), opponents=opponents, notes=notes, unpriced_player_ids=unpriced
    )
    return ScoringWeekResolution(
        resolved,
        "final" if final and begun else "live" if begun else "pregame",
        host_scores,
        tuple(progress_unavailable),
        evidence,
        progress_unavailable_reasons=dict(unavailable_reasons),
        remaining_basis=dict(basis_by_player),
    )


def actual_lineup(team: TeamWeek, rules: LeagueWeekRules, players_meta) -> dict[str, Any]:
    """CURRENT scoring lineup: best-ball assignment over points already scored.

    Only players whose game has begun (``in_progress`` / ``completed``) are
    candidates; a definitively-out (``inactive``) player's certain 0.0 is not
    shown as a scoring seat either (listed in ``inactivePlayerIds``).

    **Banked points are fact whatever we know about the game's state.**  A
    player whose game state is ``unknown`` (live feed down, unmatched game)
    but whom the host credits with NONZERO points is seated like any other
    scorer — unknown state only withholds his REMAINING production.  An
    ``unknown`` player with 0.0 or no points is not seated (0.0 cannot tell
    "has not played" from "played, scored nothing") and is listed in
    ``unknownStatePlayerIds``, never silently dropped; his presence makes
    ``lineupState`` ``partial``.  A player whose
    game has not kicked off has scored nothing, but seating him at 0.0 would
    turn a pregame roster into an arbitrary all-zero tie-break presented as
    a lineup; he is listed in ``notStartedPlayerIds`` instead, and before any
    game begins ``lineupState`` is ``not_started`` with no slots.  Choice
    and sum use the same raw points (``OBJECTIVE_REALIZED_POINTS``), so a
    negative score is never seated over a 0.0.  Unobserved players are named
    and total is null when coverage is partial; knownSubtotal is partial
    evidence, never a projected or final score.
    """
    from src.ros.lineup import OBJECTIVE_REALIZED_POINTS, RosterPlayer, solve_optimal_assignment

    begun_states = {"in_progress", "completed"}

    def _seated(p) -> bool:
        if p.points_scored is None:
            return False
        if p.state in begun_states:
            return True
        return p.state == "unknown" and p.points_scored != 0.0

    not_started = [p.player_id for p in team.players if p.state == "not_started"]
    inactive = [p.player_id for p in team.players if p.state == "inactive"]
    unknown_state = [p.player_id for p in team.players if p.state == "unknown" and not _seated(p)]
    missing = [
        p.player_id for p in team.players if p.points_scored is None and p.state in begun_states
    ]
    pool = [
        RosterPlayer(
            player_id=p.player_id,
            canonical_name=_display_name(players_meta.get(p.player_id), p.player_id),
            position=p.position,
            fantasy_positions=p.fantasy_positions,
            ros_value=p.points_scored,
        )
        for p in team.players
        if _seated(p)
    ]
    if rules.best_ball:
        assignment = (
            solve_optimal_assignment(
                pool, list(rules.starter_slots), objective=OBJECTIVE_REALIZED_POINTS
            )
            if pool
            else {}
        )
    else:
        # MANAGED: the lineup is the one the manager submitted, so a declared
        # starter whose game has not begun IS in it (at his real 0.0 so far)
        # — there is no tie-break to fake.
        by_id = {
            p.player_id: RosterPlayer(
                player_id=p.player_id,
                canonical_name=_display_name(players_meta.get(p.player_id), p.player_id),
                position=p.position,
                fantasy_positions=p.fantasy_positions,
                ros_value=p.points_scored,
            )
            for p in team.players
            if p.points_scored is not None
        }
        assignment = {
            i: by_id[pid]
            for i, pid in enumerate(team.declared_starters)
            if pid in by_id and i < len(rules.starter_slots)
        }
        missing = [pid for pid in team.declared_starters if pid not in by_id]
    slots = [
        {
            "slot": rules.starter_slots[i],
            "slotIndex": i,
            "playerId": p.player_id,
            "name": p.canonical_name,
            "points": p.ros_value,
        }
        for i, p in sorted(assignment.items())
    ]
    total = sum(p.ros_value for p in assignment.values()) if assignment else None
    if not pool and not missing and not unknown_state:
        lineup_state = "not_started"
    elif missing or unknown_state:
        lineup_state = "partial"
    elif not_started:
        lineup_state = "in_progress"
    else:
        lineup_state = "complete"
    if lineup_state == "not_started":
        # Nobody has played: the score now is a real 0.0, but there is no
        # scoring lineup to show — not an all-zero tie-break.
        total = 0.0
    return {
        "slots": slots,
        "total": total if not missing else None,
        "knownSubtotal": total,
        "missingPlayerIds": missing,
        "notStartedPlayerIds": not_started,
        "inactivePlayerIds": inactive,
        # State unknown AND no nonzero banked points: not seated, named.
        "unknownStatePlayerIds": unknown_state,
        "lineupState": lineup_state,
        "complete": not missing,
        "owner": "src/ros/lineup.py",
    }
