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
it does not prove a game is live or estimate its remaining production. An
in-progress source can enter through the typed :class:`GameEvidence` seam,
while the unresolved remaining-production policy stays explicit and blocks
probability rather than being guessed.

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
`Out` is unavailable; less certain injury labels remain projections. With no
evidenced live game-status feed, elapsed kickoff time remains `unknown`.
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


def schedule_game_evidence(rows, *, season, week, observed_at, now):
    """Shape the canonical nflverse schedule; do not create a downloader.

    The schedule dictionary describes scores as results for played games.
    Both scores + result constitute completed-game evidence. A past kickoff
    without a result stays unknown (not a fabricated in-progress status).
    Explicit live game states can enter through GameEvidence when a source
    capable of observing them is wired. Source age is carried unchanged.
    """
    from src.ros.game_day_capture import first_kickoff_utc

    result = {}
    for row in rows:
        try:
            if int(row.get("season")) != season or int(row.get("week")) != week:
                continue
        except (TypeError, ValueError):
            continue
        if row.get("game_type") != "REG":
            continue
        kickoff = first_kickoff_utc([row], season=season, week=week)
        stamp = kickoff.timestamp() if kickoff else None
        scores = [_finite_points(row.get(k)) for k in ("home_score", "away_score", "result")]
        if all(s is not None for s in scores) and stamp is not None and stamp <= now:
            state = "completed"
        elif stamp is not None and stamp > now:
            state = "not_started"
        else:
            state = "unknown"
        for key in ("home_team", "away_team"):
            team = str(row.get(key) or "").upper()
            if team:
                # nflverse LA is Sleeper LAR; no player identity guessing.
                team = "LAR" if team == "LA" else team
                result[team] = GameEvidence(state, "nflverse:schedules", observed_at, stamp)
    return result


@dataclass(frozen=True)
class ScoringWeekResolution:
    week: WeekResolution
    mode: str
    host_scores: dict[str, float | None]
    policy_required_player_ids: tuple[str, ...]
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
    """Factual scheduled/live/final state around an UNRESOLVED policy seam.

    No rate model, zero remainder or exclusion policy is selected for a
    mid-game player. Their actual points survive, their remainder is None,
    and policy_required_player_ids prevents the serving path from claiming
    an operational probability policy has been approved.
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
    required = []
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
            remaining = p.projected_remaining if state == "not_started" else None
            if state == "in_progress":
                required.append(p.player_id)
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
    if required:
        notes.append(
            "OWNER_POLICY_REQUIRED: in-progress remaining production has no approved policy"
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
        tuple(required),
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
