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

**Owner methodology decision (2026-09-09) — in-progress remaining
production is TIME-PRORATED.**  For a player whose game is evidenced
``in_progress``, remaining production is the pregame per-game estimate
scaled by the fraction of the game clock not yet elapsed:
``remaining = projected_remaining * max(0, 1 - elapsed / ASSUMED_GAME_SECONDS)``,
where ``elapsed`` is wall time since the evidenced ``kickoff_at`` and
``ASSUMED_GAME_SECONDS`` is a single fixed constant approximating an NFL
game's kickoff-to-final-whistle duration (see
``_ASSUMED_GAME_DURATION_SECONDS``).  This is deliberately the simplest
correct estimator — a future revision may use snaps, drives, possession or
game script, but may not silently change today's methodology without the
same owner authority.  Option B ("remaining = 0 for every in-progress
player") was explicitly rejected: it is not a defensible default, it is a
different and unapproved forecast.

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
`Out` is unavailable; less certain injury labels remain projections.
Proration uses a single fixed assumed game duration rather than a real
per-game clock/quarter feed (none is wired), so it is a simple estimator by
design, not a precise one — see the owner decision above.
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
) -> tuple[TeamWeek, tuple[str, ...], tuple[str, ...], int]:
    """One roster -> ``(TeamWeek, unpriced ids, ineligible ids, active count)``."""
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
        if has_estimates:
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

    has_estimates = bool(estimate_source) and bool(estimates)
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
    """

    state: str
    source: str
    observed_at: float | None
    kickoff_at: float | None = None

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
        for team in (home, away):
            if team:
                result[team] = GameEvidence(state, "nflverse:schedules", observed_at, stamp)
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


# Owner decision, 2026-09-09: simple game-progress/time proration is the
# canonical initial estimator for in-progress remaining production (see the
# module docstring). ~3h15m approximates NFL kickoff-to-final-whistle
# duration across a broadcast window; it is a single fixed constant by
# design, not a per-game measurement, because no live game-clock/quarter
# feed is wired. A future estimator may replace this constant's role, but
# only through the same owner authority that set it.
_ASSUMED_GAME_DURATION_SECONDS = 3.25 * 3600.0


def _prorated_remaining(
    projected_remaining: float | None,
    kickoff_at: float | None,
    now: float,
) -> tuple[float | None, bool]:
    """Time-prorate one in-progress player's remaining production.

    Returns ``(remaining, progress_unavailable)``. ``progress_unavailable``
    is True only when a real projection exists but cannot be prorated for
    lack of reliable game-progress evidence (no/invalid ``kickoff_at``) —
    never when ``projected_remaining`` itself is missing, which is a
    separate "unpriced player" concern this function is not responsible
    for reporting.
    """
    if projected_remaining is None:
        return None, False
    if kickoff_at is None or now < kickoff_at:
        return None, True
    elapsed = now - kickoff_at
    fraction_remaining = max(
        0.0, 1.0 - min(elapsed, _ASSUMED_GAME_DURATION_SECONDS) / _ASSUMED_GAME_DURATION_SECONDS
    )
    return projected_remaining * fraction_remaining, False


@dataclass(frozen=True)
class ScoringWeekResolution:
    week: WeekResolution
    mode: str
    host_scores: dict[str, float | None]
    progress_unavailable_player_ids: tuple[str, ...]
    game_evidence: Mapping[str, GameEvidence]


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
) -> ScoringWeekResolution:
    """Factual scheduled/live/final state, in-progress remaining TIME-PRORATED.

    Owner-approved 2026-09-09 (see module docstring): an in-progress
    player's remaining production is his pregame estimate scaled by the
    fraction of an assumed game duration not yet elapsed since evidenced
    kickoff. When that evidence is missing or unusable, remaining stays
    ``None`` and ``progress_unavailable_player_ids`` reports it as a
    missing-evidence state, never a methodology-undecided one. A
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
    )
    by_id = {str(m.get("roster_id")): m for m in matchups or ()}
    opponents = opponents_from_matchups(matchups)
    teams = []
    progress_unavailable = []
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
            meta = players_meta.get(p.player_id) or {}
            game = evidence.get(str(meta.get("team") or "").upper())
            state = game.state if game else ("unknown" if begun else "not_started")
            actual = _finite_points(score_map.get(p.player_id)) if begun else 0.0
            if state == "not_started":
                actual = 0.0
            # Out is host-declared unavailability, unlike Doubtful or
            # Questionable. Do not override a recorded completed score.
            if meta.get("injury_status") == "Out" and state != "completed":
                state = "inactive"
                if actual is None:
                    actual = 0.0
            if state == "not_started":
                remaining = p.projected_remaining
            elif state == "in_progress":
                remaining, unavailable = _prorated_remaining(
                    p.projected_remaining, game.kickoff_at if game else None, current
                )
                if unavailable:
                    progress_unavailable.append(p.player_id)
            elif state in ("completed", "inactive"):
                # Definitive evidence nothing further is coming this week
                # (owner decision 2026-09-09) — 0.0 is the evidenced fact.
                remaining = 0.0
            else:
                # "unknown" — genuinely no evidence either way.
                remaining = None
            if state == "unknown" and begun:
                # An explicit game-state feed is also required here.
                # A nonzero score alone cannot tell live from completed.
                final = False
            if state == "completed" and actual is None:
                final = False
            players.append(
                replace(p, state=state, points_scored=actual, projected_remaining=remaining)
            )
        starters = tuple(str(pid) for pid in matchup.get("starters", ()) if pid and str(pid) != "0")
        teams.append(replace(team, players=tuple(players), declared_starters=starters))
        opponents.setdefault(team.team_id, None)
        unpriced[team.team_id] = tuple(
            p.player_id
            for p in players
            if p.state == "not_started" and p.projected_remaining is None
        )
    notes = list(base.notes) if not begun else []
    if progress_unavailable:
        notes.append(
            "GAME_PROGRESS_UNAVAILABLE: in-progress remaining production could not be "
            "time-prorated — no reliable kickoff/game-progress evidence"
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
    )


def actual_lineup(team: TeamWeek, rules: LeagueWeekRules, players_meta) -> dict[str, Any]:
    """Current best-ball assignment from observed points, never roster sum.

    Unobserved players are named and total is null when coverage is partial;
    knownSubtotal is explicitly partial evidence, not a projected/final score.
    """
    from src.ros.lineup import RosterPlayer, solve_optimal_assignment

    missing = [p.player_id for p in team.players if p.points_scored is None]
    pool = [
        RosterPlayer(
            player_id=p.player_id,
            canonical_name=_display_name(players_meta.get(p.player_id), p.player_id),
            position=p.position,
            fantasy_positions=p.fantasy_positions,
            ros_value=p.points_scored,
        )
        for p in team.players
        if p.points_scored is not None
    ]
    if rules.best_ball:
        assignment = solve_optimal_assignment(pool, list(rules.starter_slots)) if pool else {}
    else:
        by_id = {p.player_id: p for p in pool}
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
    return {
        "slots": slots,
        "total": total if not missing else None,
        "knownSubtotal": total,
        "missingPlayerIds": missing,
        "complete": not missing,
        "owner": "src/ros/lineup.py",
    }
