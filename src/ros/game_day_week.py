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

**PREGAME ONLY, and it says so rather than guessing.**  Distinguishing
`completed` from `in_progress` requires knowing whether each player's NFL
game has ended, and no live game-state feed is wired in this repo.  Rather
than collapse those two states — which is precisely the double-projection
spec §6 forbids — :func:`resolve_pregame_week` REFUSES once the week has
begun, using `game_day_capture.week_has_begun`, the same host-evidence gate
the archive uses.  Live resolution is a different unit and needs a schedule
or game-state source it can name.

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

**Known limitation, named rather than papered over.**  Sleeper's
`injury_status` is NOT read, so a player the host has already declared
`Out` is resolved as `not_started` with his full estimate rather than as a
known zero.  Reading it is a judgment about which statuses are certain
(`Out` yes, `Doubtful` no) and it belongs with the live-state unit that
already has to make per-player game-state calls.  The effect is bounded and
in one direction: it can only overstate a team's projection.
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
