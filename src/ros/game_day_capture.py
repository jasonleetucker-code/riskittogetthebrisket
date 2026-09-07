"""C5-GD-02b — the scheduled caller for the Game Day prediction archive.

`src/ros/game_day_archive.py` is a pure, append-only store that
deliberately does not resolve anything: "a caller resolves point
estimates ... and passes them in already-built."  It shipped 2026-08-20
with **no caller at all** — a `grep` for it across `.github/workflows/`
and `scripts/` returned zero matches — so the perishable observation it
exists to protect was being lost every week regardless.  This module is
that missing caller's resolution half; `scripts/capture_game_day_predictions.py`
is its CLI and `.github/workflows/game-day-capture.yml` its schedule.

**Split this way on purpose.**  Everything here is a pure function of
already-fetched Sleeper payloads plus an already-built estimate index,
so the whole resolution path — the pregame gate, slot eligibility,
estimate joining, the missing-estimate semantics — is testable with no
network and no live league.  The script owns fetching and the archive
owns writing; neither is re-implemented here.

**The pregame gate is the load-bearing part.**  The directive governing
this unit is explicit that a snapshot reconstructed after games have
begun must never be labelled `pregame`, and the archive itself cannot
enforce that: `record_snapshot` takes `capture_kind` from its caller and
stamps a truthful `captured_at`, which proves *when* a capture ran but
not that the week was still unplayed when it did.  :func:`week_has_begun`
answers that from the host's own evidence — any nonzero team or player
score in the week's matchups — and :func:`build_capture` REFUSES a
`pregame` capture once it is true.  A missed pregame window is missing
evidence, permanently, and that is the correct outcome: the alternative
is a snapshot that lies about what was knowable when it was taken.

**Missing is never zero, twice over.**  A player no projection source
covers is recorded with `point_estimate=None` (the archive's own
contract forbids a fabricated 0.0), and a league whose projection
snapshot is absent entirely produces a capture whose rosters are fully
real and whose estimates are uniformly absent — still worth capturing,
because roster composition on the morning of Week 1 is itself perishable
and is not recoverable later.  `CaptureBuild.estimate_coverage` reports
which of those two states a capture is in rather than leaving a reader
to infer it from the row count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.ros.game_day_archive import PlayerPointEstimate
from src.ros.lineup import (
    RosterPlayer,
    lineup_position,
    player_eligible_for_slot,
    resolve_starter_slots,
)
from src.utils.name_clean import normalize_player_name

#: Roster buckets whose occupants cannot fill a starting slot this week,
#: read from the roster payload itself rather than assumed.  Sleeper
#: lists IR and taxi players inside ``players`` alongside everyone else,
#: so without subtracting them a stashed rookie reads as an available
#: starter.  Note this is roster-payload evidence, NOT the bracketed
#: taxi-occupancy guess `src/trade/roster_capacity.py` has to make: there
#: the membership is genuinely invisible, here the host hands it over.
_NON_ACTIVE_ROSTER_BUCKETS: tuple[str, ...] = ("reserve", "taxi")


def non_active_player_ids(roster: Mapping[str, Any]) -> set[str]:
    """Rostered players who cannot fill a starting slot this week.

    Exported so the Game Day WEEK resolver (`src/ros/game_day_week.py`)
    subtracts exactly the same set this module does, from exactly the
    same roster-payload evidence.  Two answers to "is this player
    available" would be two definitions of the roster.
    """
    out: set[str] = set()
    for bucket in _NON_ACTIVE_ROSTER_BUCKETS:
        for pid in roster.get(bucket) or ():
            if pid:
                out.add(str(pid))
    return out


#: nflverse publishes `gametime` in US Eastern. Converting with a fixed
#: offset would be wrong for exactly the games that matter here — the
#: season spans the DST boundary — so the zone does the work.
_NFL_CLOCK = ZoneInfo("America/New_York")

#: How long before the week's first kickoff a pregame capture is taken.
#:
#: A WINDOW, not a weekday. The original timer assumed a Thursday-night
#: opener and fired Thursday 13:00 UTC. Week 1 of 2026 opens on a
#: WEDNESDAY (NE @ SEA, 2026-09-09 20:20 ET = 2026-09-10 00:20 UTC), so
#: that timer would have run roughly thirteen hours AFTER kickoff, been
#: correctly refused by `week_has_begun`, and lost the observation
#: permanently. A weekday is a guess about the schedule; the schedule is
#: a fact, and this reads it.
#:
#: 30 hours is chosen to clear a full waiver cycle: claims process
#: Wednesday morning, and the roster that starts the week is the one
#: that should be captured. It is wide enough that a timer firing a few
#: times a day cannot miss it, and narrow enough that the capture is not
#: taken days early against a roster that will still change.
CAPTURE_WINDOW_HOURS: float = 30.0


class GameDayCaptureRefusal(RuntimeError):
    """A capture that must not be written as asked.

    Distinct from an error: nothing failed, the capture is simply not
    honest to take.  The only current cause is a `pregame` capture
    requested after the week has begun.
    """


@dataclass(frozen=True)
class TeamCapture:
    """One team's fully-resolved snapshot arguments, ready for
    :func:`src.ros.game_day_archive.record_snapshot`."""

    team_id: str
    roster: tuple[PlayerPointEstimate, ...]

    @property
    def estimated_count(self) -> int:
        return sum(1 for p in self.roster if p.point_estimate is not None)


@dataclass
class CaptureBuild:
    """Everything one league-week capture needs, plus the provenance a
    later calibration consumer will need to judge it."""

    league_key: str
    season: int
    week: int
    capture_kind: str
    scoring_config_id: str
    starter_slots: tuple[str, ...]
    starter_slot_source: str | None
    teams: tuple[TeamCapture, ...]
    estimate_source_label: str | None
    sources_loaded: tuple[str, ...] = ()
    sources_unavailable: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def estimate_coverage(self) -> tuple[int, int]:
        """``(players with an estimate, players total)`` across every team.

        Reported rather than derived by the reader so "no source covered
        this league" (0 of N) and "a source covered part of it" (k of N)
        are distinguishable at a glance — they are different evidence
        states, not degrees of the same one.
        """
        total = sum(len(t.roster) for t in self.teams)
        have = sum(t.estimated_count for t in self.teams)
        return have, total


def _is_positive_score(raw: Any) -> bool:
    """Is this a real, positive score?

    An ABSENT value is not a zero. Both answer "no football has been
    played" here, so the practical result is the same — but they are
    written as the different statements they are, rather than coerced
    together with an ``or 0.0`` that a reader (and the repo's
    decision-path coercion gate) would have to take on trust.
    """
    if raw is None:
        return False
    try:
        return float(raw) > 0.0
    except (TypeError, ValueError):
        return False


def week_has_begun(matchups: Sequence[Mapping[str, Any]] | None) -> bool:
    """Has any football counting toward this league-week been played?

    Decided on the host's own scoring evidence — a nonzero team total or
    any nonzero per-player score — never on a clock or a calendar
    derivation.  Before kickoff Sleeper reports every team at 0.0 with an
    empty (or all-zero) ``players_points`` map; the first score to land
    flips this and it never flips back.

    A genuinely all-zero week after kickoff is not a practical concern
    across a full slate of teams, and the failure direction is the safe
    one anyway: this returning ``False`` late would let a slightly-late
    capture be labelled pregame, so the caller ALSO has the schedule-
    independent option of simply not running after kickoff.  Returning
    ``True`` early is impossible — a score cannot precede the game.

    An absent or empty matchup list returns ``False``: a week Sleeper has
    not published matchups for has certainly not been played.
    """
    for row in matchups or ():
        if not isinstance(row, Mapping):
            continue
        if _is_positive_score(row.get("points")):
            return True
        points_map = row.get("players_points")
        if isinstance(points_map, Mapping):
            if any(_is_positive_score(v) for v in points_map.values()):
                return True
    return False


def estimate_index_from_ensemble(ensemble: Sequence[Any]) -> dict[str, float]:
    """Normalized-name → per-game point estimate.

    The ensemble keys players by ``player_key``, which is already a
    normalized canonical name (`src/bdvm/projections.py`), so this is a
    re-key rather than a re-normalization — the join key is the one the
    projection lane already decided on.
    """
    out: dict[str, float] = {}
    for obs in ensemble or ():
        key = getattr(obs, "player_key", None)
        value = getattr(obs, "combined_league_scored_fpg", None)
        if not key or value is None:
            continue
        out[str(key)] = float(value)
    return out


def _player_positions(meta: Mapping[str, Any] | None) -> tuple[str, list[str]]:
    """``(primary position, fantasy positions)`` from a Sleeper player row."""
    if not isinstance(meta, Mapping):
        return "", []
    primary = str(meta.get("position") or "").strip().upper()
    raw = meta.get("fantasy_positions")
    fantasy = [str(p).strip().upper() for p in raw if p] if isinstance(raw, list) else []
    if primary and primary not in fantasy:
        fantasy = [primary, *fantasy]
    return primary, fantasy


def _display_name(meta: Mapping[str, Any] | None, player_id: str) -> str:
    if not isinstance(meta, Mapping):
        return ""
    full = meta.get("full_name")
    if full:
        return str(full)
    first = str(meta.get("first_name") or "").strip()
    last = str(meta.get("last_name") or "").strip()
    joined = f"{first} {last}".strip()
    return joined or str(meta.get("last_name") or "")


def build_team_roster(
    *,
    roster: Mapping[str, Any],
    players_meta: Mapping[str, Any],
    starter_slots: Sequence[str],
    estimates: Mapping[str, float],
    estimate_source_label: str | None,
) -> tuple[PlayerPointEstimate, ...]:
    """Resolve one Sleeper roster into archive rows.

    Every rostered player is captured, including ones no slot can hold
    and ones no source prices — `is_lineup_eligible` and
    `point_estimate` carry those facts as data.  Dropping either class
    would silently narrow what a future replay can see, in the direction
    that hides coverage gaps.
    """
    player_ids = [str(p) for p in (roster.get("players") or []) if p]
    inactive = non_active_player_ids(roster)

    rows: list[PlayerPointEstimate] = []
    seen: set[str] = set()
    for pid in player_ids:
        if pid in seen:
            # The archive refuses a duplicate player_id outright; a
            # Sleeper roster listing one twice is a host artifact, not
            # two roster spots, so collapse it here rather than failing
            # the whole league's capture.
            continue
        seen.add(pid)
        meta = players_meta.get(pid) if isinstance(players_meta, Mapping) else None
        primary, fantasy = _player_positions(meta)
        candidate = RosterPlayer(
            player_id=pid,
            canonical_name=_display_name(meta, pid),
            position=primary,
            ros_value=None,
            fantasy_positions=tuple(fantasy),
        )
        eligible = pid not in inactive and any(
            player_eligible_for_slot(slot, candidate) for slot in starter_slots
        )

        estimate: float | None = None
        if estimate_source_label:
            name_key = normalize_player_name(candidate.canonical_name)
            if name_key:
                found = estimates.get(name_key)
                if found is not None:
                    estimate = float(found)

        rows.append(
            PlayerPointEstimate(
                player_id=pid,
                # The lineup vocabulary, so a stored position means the
                # same thing as the slots stored beside it.  An unknown
                # position stays empty rather than becoming a guess.
                position=lineup_position(primary) if primary else "",
                is_lineup_eligible=eligible,
                point_estimate=estimate,
                estimate_source=estimate_source_label if estimate is not None else None,
            )
        )
    return tuple(rows)


def build_capture(
    *,
    league_key: str,
    season: int,
    week: int,
    capture_kind: str,
    league_payload: Mapping[str, Any],
    rosters: Sequence[Mapping[str, Any]],
    matchups: Sequence[Mapping[str, Any]] | None,
    players_meta: Mapping[str, Any],
    roster_settings: Mapping[str, Any] | None = None,
    estimates: Mapping[str, float] | None = None,
    estimate_source_label: str | None = None,
    sources_loaded: Sequence[str] = (),
    sources_unavailable: Sequence[str] = (),
) -> CaptureBuild:
    """Resolve one league-week into a :class:`CaptureBuild`.

    Raises :class:`GameDayCaptureRefusal` for a `pregame` capture of a
    week that has already begun, and ``ValueError`` for the two states
    that make a capture meaningless rather than merely degraded: no
    starter slots resolved (so lineup eligibility would be a fiction)
    and no scoring card (so the snapshot could not say what rules it was
    taken under).  Both fail closed rather than substituting a default —
    a snapshot filed under the wrong league's scoring is worse than no
    snapshot, because a future consumer cannot tell.
    """
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    if capture_kind == "pregame" and week_has_begun(matchups):
        raise GameDayCaptureRefusal(
            f"{league_key}/{season}/w{week}: the week has already begun (Sleeper is "
            "reporting scores), so a 'pregame' capture would be a reconstruction "
            "labelled as a prediction. This window is closed permanently; capture "
            "'in_game' or 'postgame' instead. Missing pregame evidence stays missing."
        )

    scoring = league_payload.get("scoring_settings")
    fingerprint = scoring_fingerprint(scoring)
    if not fingerprint:
        raise ValueError(
            f"{league_key}: no usable scoring card from the host — a snapshot that "
            "cannot name the rules it was taken under is not evidence."
        )

    slots, slot_source = resolve_starter_slots(
        roster_positions=league_payload.get("roster_positions"),
        roster_settings=dict(roster_settings) if roster_settings else None,
    )
    if not slots:
        raise ValueError(
            f"{league_key}: no starter slots resolved from the host or the registry — "
            "lineup eligibility would be invented, so nothing is captured."
        )

    estimates = estimates or {}
    teams: list[TeamCapture] = []
    notes: list[str] = []
    for roster in rosters or ():
        team_id = roster.get("roster_id")
        if team_id is None:
            notes.append("skipped a roster with no roster_id")
            continue
        rows = build_team_roster(
            roster=roster,
            players_meta=players_meta,
            starter_slots=slots,
            estimates=estimates,
            estimate_source_label=estimate_source_label,
        )
        if not rows:
            # The archive refuses an empty roster ("not evidence, a
            # caller bug"). An genuinely empty Sleeper roster is a real
            # state though, so report it instead of raising.
            notes.append(f"roster {team_id} has no players; not captured")
            continue
        teams.append(TeamCapture(team_id=str(team_id), roster=rows))

    return CaptureBuild(
        league_key=league_key,
        season=season,
        week=week,
        capture_kind=capture_kind,
        scoring_config_id=fingerprint,
        starter_slots=tuple(slots),
        starter_slot_source=slot_source,
        teams=tuple(teams),
        estimate_source_label=estimate_source_label,
        sources_loaded=tuple(sources_loaded),
        sources_unavailable=tuple(sources_unavailable),
        notes=notes,
    )


def first_kickoff_utc(
    schedule_rows: Sequence[Mapping[str, Any]] | None,
    *,
    season: int,
    week: int,
) -> datetime | None:
    """The earliest kickoff of one league-week, in UTC.

    Reads `gameday` + `gametime` from nflverse schedule rows. Returns
    ``None`` when the week has no usable rows — an UNKNOWN kickoff, which
    the caller must not treat as "no kickoff yet".

    The times are US Eastern and the season crosses the DST boundary, so
    they are localised through a real zone rather than a fixed offset.
    """
    best: datetime | None = None
    for row in schedule_rows or ():
        if not isinstance(row, Mapping):
            continue
        try:
            if int(float(row.get("season"))) != int(season):
                continue
            if int(float(row.get("week"))) != int(week):
                continue
        except (TypeError, ValueError):
            continue
        day = str(row.get("gameday") or "").strip()
        clock = str(row.get("gametime") or "").strip()
        if not day or not clock:
            continue
        try:
            naive = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        when = naive.replace(tzinfo=_NFL_CLOCK).astimezone(timezone.utc)
        if best is None or when < best:
            best = when
    return best


def pregame_window_state(
    *,
    first_kickoff: datetime | None,
    now: datetime | None = None,
    window_hours: float = CAPTURE_WINDOW_HOURS,
) -> tuple[str, str]:
    """``(state, human explanation)`` for the pregame capture window.

    States:

    * ``open``    — inside the window; capture now.
    * ``early``   — kickoff is further away than the window. Capturing
      would consume the append-only pregame slot with a roster that
      waivers will still change, and the slot cannot be reused.
    * ``closed``  — kickoff has passed. The observation is gone; this is
      the same conclusion `week_has_begun` reaches from scores, derived
      here from the schedule so it can be known BEFORE any score posts.
    * ``unknown`` — no kickoff could be resolved. Deliberately NOT
      treated as ``open`` or ``closed``: the caller decides, and the
      script's choice is to proceed (a capture with an unverifiable
      window still beats no capture, and the score-based gate is still
      in front of it).
    """
    if first_kickoff is None:
        return "unknown", "no kickoff time could be resolved for this week"
    current = now or datetime.now(timezone.utc)
    if current >= first_kickoff:
        return (
            "closed",
            f"first kickoff was {first_kickoff.isoformat()} — the pregame window "
            "has passed and that observation cannot be recovered",
        )
    opens_at = first_kickoff - timedelta(hours=window_hours)
    if current < opens_at:
        return (
            "early",
            f"first kickoff is {first_kickoff.isoformat()}; the capture window "
            f"opens {window_hours:g}h before it, at {opens_at.isoformat()}",
        )
    return (
        "open",
        f"first kickoff is {first_kickoff.isoformat()}; inside the "
        f"{window_hours:g}h capture window",
    )
