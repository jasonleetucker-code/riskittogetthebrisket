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
from datetime import date, datetime, timedelta, timezone
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

#: The two PRE-EVENT capture kinds, each gated on its own kickoff.
PREGAME_KIND = "pregame"
PREGAME_LATE_KIND = "pregame_late"
PREGAME_KINDS: tuple[str, ...] = (PREGAME_KIND, PREGAME_LATE_KIND)

#: How long before the week's first SUNDAY kickoff the ``pregame_late``
#: capture window opens (owner directive 2026-11-07, Part 7).
#:
#: ``pregame`` is taken inside 30h of the week's FIRST kickoff -- in practice
#: Wednesday evening before Thursday Night Football -- so Sunday and Monday
#: games were only ever archived against inputs four days stale: before the
#: Friday injury report, Saturday's IR moves and the weekend's waiver and
#: free-agent roster changes.  ``pregame_late`` re-observes the same state
#: before Sunday's first game.
#:
#: 12 hours, against a timer that fires at 00/04/08/12/16/20 UTC: a
#: half-open 12h window always contains EXACTLY three firings whatever the
#: kickoff minute (pinned against the installed timer's own ``OnCalendar``
#: in ``tests/ros/test_game_day_pregame_late_capture.py``), so the capture
#: survives two consecutive failed runs.  For a 1pm ET Sunday it lands Sunday 06:00-10:00
#: UTC, after Saturday's final designations; for a 9:30am ET international
#: game, 02:30-06:30 UTC.  Saturday games (late season) are NOT "before"
#: this snapshot -- the kickoff it precedes is recorded on every snapshot
#: (``provenance.precedesKickoffUtc``) so no reader has to infer it.
LATE_CAPTURE_WINDOW_HOURS: float = 12.0

#: ``(season, week)`` from which ``pregame_late`` is collected.  Earlier weeks
#: never had the capture kind; a closed window there is "never collected",
#: not a lost observation, and must not page.  The same posture as
#: ``src.history.store.HISTORY_FLOOR``: the floor is a fact about when
#: collection started, nothing is backfilled before it.
PREGAME_LATE_FIRST_WEEK: tuple[int, int] = (2026, 10)

#: ``date.weekday()`` of Sunday.
_SUNDAY = 6


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
    kickoffs = _week_kickoffs(schedule_rows, season=season, week=week)
    return min((utc for utc, _local in kickoffs), default=None)


def _week_kickoffs(
    schedule_rows: Sequence[Mapping[str, Any]] | None,
    *,
    season: int,
    week: int,
) -> list[tuple[datetime, datetime]]:
    """``(kickoff UTC, kickoff US-Eastern)`` for every usable row of one week.

    Rows of another season/week, or with an absent or unparseable date/time,
    are skipped -- never guessed.  A caller that must know whether a skipped
    row could have been the answer reads :func:`_week_schedule` instead.
    """
    return _week_schedule(schedule_rows, season=season, week=week)[0]


def _week_schedule(
    schedule_rows: Sequence[Mapping[str, Any]] | None,
    *,
    season: int,
    week: int,
) -> tuple[list[tuple[datetime, datetime]], list[date | None]]:
    """``(kickoffs, untimed)`` for one week -- the single parser of nflverse
    ``gameday`` + ``gametime`` for this module.

    ``kickoffs`` is ``(UTC, US-Eastern)`` per row with a parseable date AND
    time.  ``untimed`` holds, per row of THIS week without a usable kickoff,
    its calendar date -- or ``None`` when even the date is absent or
    unparseable.  Kept rather than dropped: a Sunday-dated game whose time is
    blank or "TBD" is still a Sunday game, and it may be the earliest one.
    """
    out: list[tuple[datetime, datetime]] = []
    untimed: list[date | None] = []
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
        day_text = str(row.get("gameday") or "").strip()
        clock = str(row.get("gametime") or "").strip()
        try:
            day = datetime.strptime(day_text, "%Y-%m-%d").date()
        except ValueError:
            untimed.append(None)
            continue
        try:
            naive = datetime.strptime(f"{day_text} {clock}", "%Y-%m-%d %H:%M")
        except ValueError:
            untimed.append(day)
            continue
        local = naive.replace(tzinfo=_NFL_CLOCK)
        out.append((local.astimezone(timezone.utc), local))
    return out, untimed


def first_sunday_kickoff_utc(
    schedule_rows: Sequence[Mapping[str, Any]] | None,
    *,
    season: int,
    week: int,
) -> tuple[datetime | None, str | None]:
    """``(earliest kickoff on the week's SUNDAY, None)``, or ``(None, reason)``.

    "Sunday" is the US-Eastern calendar date nflverse publishes the game on,
    never an assumed weekday offset from the first kickoff: Thursday and
    Saturday games (and Friday international openers) are skipped, a 9:30am
    ET London game IS the Sunday kickoff, and a Wednesday opener changes
    nothing.

    Reasons, kept apart because they mean opposite things:

    * ``no_schedule_rows_for_week`` -- UNKNOWN; the caller must not treat it
      as "no Sunday game".
    * ``sunday_game_without_kickoff_time`` / ``game_without_parseable_date``
      -- UNKNOWN: a Sunday-dated row with a blank or "TBD" time (or a row of
      the week with no readable date at all, which may be a Sunday game) could
      be the EARLIEST Sunday kickoff, so neither "no Sunday game" nor "the
      earliest timed Sunday game" can be proven.
    * ``no_sunday_game`` -- the slate was read, every row of the week is
      dated, and none is on a Sunday; the late capture does not apply.
    """
    kickoffs, untimed = _week_schedule(schedule_rows, season=season, week=week)
    if None in untimed:
        return None, "game_without_parseable_date"
    if any(day.weekday() == _SUNDAY for day in untimed if day is not None):
        return None, "sunday_game_without_kickoff_time"
    if not kickoffs:
        return None, "no_schedule_rows_for_week"
    sundays = [utc for utc, local in kickoffs if local.date().weekday() == _SUNDAY]
    if not sundays:
        return None, "no_sunday_game"
    return min(sundays), None


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


def pregame_capture_gaps(
    *,
    expected_team_ids: Sequence[Any],
    snapshots: Sequence[Any],
    first_kickoff: datetime | None,
    capture_kind: str = PREGAME_KIND,
) -> list[str]:
    """Team ids of one league-week that have NO ``capture_kind`` snapshot
    captured before ``first_kickoff`` -- sorted, empty when the week is fully
    captured.  For ``pregame_late`` the caller passes the first SUNDAY
    kickoff: that is the instant the late snapshot claims to precede.

    This is the question a closed window actually asks.  "Kickoff has passed"
    alone is not a lost observation: the timer keeps firing every four hours
    until Sleeper rolls the week, so a week captured on Tuesday evening would
    otherwise be REFUSED (exit 3, "unrecoverable") on every run from Thursday
    night to the next Tuesday while the evidence sits in the archive.

    A snapshot counts only if its ``captured_at`` is a real instant strictly
    before the first kickoff (with no kickoff to compare against, any
    pregame snapshot counts -- the archive's own write path refuses a
    post-kickoff pregame capture).  An expected team with nothing qualifying
    is a gap; an empty ``expected_team_ids`` proves nothing and is the
    caller's to refuse.
    """
    captured: set[str] = set()
    for snap in snapshots:
        if getattr(snap, "capture_kind", None) != capture_kind:
            continue
        if first_kickoff is not None:
            try:
                at = datetime.fromisoformat(str(getattr(snap, "captured_at", "")))
            except ValueError:
                continue
            if at.tzinfo is None or at >= first_kickoff:
                continue
        captured.add(str(getattr(snap, "team_id", "")))
    return sorted({str(t) for t in expected_team_ids} - captured)


def week_one_waiver_guard(
    *,
    season: int,
    week: int,
    transactions: Sequence[Mapping[str, Any]],
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Owner-authorized 2026 Week 1 exception, never a generic waiver model.

    Execute only on Wednesday after the observed owner-league waiver batch.
    The caller must ALSO pass the independent pre-kickoff and scoring gates.
    An empty/unavailable transaction feed cannot prove completion.
    """
    if (season, week) != (2026, 1):
        return True, "Wednesday exception not applicable"
    et = ZoneInfo("America/New_York")
    current = (now or datetime.now(timezone.utc)).astimezone(et)
    if current.date().isoformat() != "2026-09-09":
        return False, "2026 Week 1 capture requires Wednesday 2026-09-09 after waivers"
    if any(t.get("status") == "pending" for t in transactions):
        return False, "pending claims remain in the observed transaction batch"
    waivers = [t for t in transactions if t.get("type") == "waiver"]
    if not waivers:
        return False, "no observed waiver batch; completion is unproven"
    try:
        newest = max(float(t["status_updated"]) for t in waivers)
        batch = datetime.fromtimestamp(newest / 1000, et)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False, "waiver timestamps unavailable or invalid"
    if batch.date() != current.date() or batch.hour < 3 or batch > current:
        return False, "newest waiver batch is not this Wednesday after 03:00 ET"
    newest_rows = [t for t in waivers if float(t["status_updated"]) == newest]
    if any(t.get("status") not in {"complete", "failed"} for t in newest_rows):
        return False, "newest waiver batch is not terminal"
    return True, f"observed Wednesday waiver batch {batch.isoformat()}; no pending claims"


def late_pregame_window_state(
    *,
    season: int,
    week: int,
    sunday_kickoff: datetime | None,
    kickoff_reason: str | None,
    now: datetime | None = None,
    window_hours: float = LATE_CAPTURE_WINDOW_HOURS,
) -> tuple[str, str]:
    """``(state, explanation)`` for the ``pregame_late`` window.

    The states of :func:`pregame_window_state`, plus ``not_applicable`` (a
    week before :data:`PREGAME_LATE_FIRST_WEEK`, or a slate with no Sunday
    game).  ``unknown`` here is NOT "proceed" the way it is for ``pregame``:
    that capture still has the score gate behind it (no score can precede
    the first game), but by Sunday the Thursday game HAS scored, so nothing
    but the schedule can prove a late capture is pre-Sunday.  The caller
    refuses it.
    """
    if (int(season), int(week)) < PREGAME_LATE_FIRST_WEEK:
        floor_season, floor_week = PREGAME_LATE_FIRST_WEEK
        return (
            "not_applicable",
            f"pregame_late collection starts {floor_season} week {floor_week}; "
            f"{season} week {week} was never collected",
        )
    if sunday_kickoff is None:
        if kickoff_reason == "no_sunday_game":
            return "not_applicable", "the slate has no Sunday game this week"
        return "unknown", f"no Sunday kickoff could be resolved ({kickoff_reason})"
    return pregame_window_state(first_kickoff=sunday_kickoff, now=now, window_hours=window_hours)


def combine_exit_codes(codes: Sequence[int]) -> int:
    """One process exit code for several capture kinds run together.

    Same precedence the single-kind run already uses (``refusals`` are
    reported ahead of ``failures``): 3 (an observation lost) > 1 (a hard
    error) > 0 (captured, or already was) > 2 (nothing to do).  So a quiet
    "too early" for one kind can never mask another kind's loss or error.
    """
    seen = set(codes)
    for code in (3, 1, 0):
        if code in seen:
            return code
    return 2


# ── per-snapshot provenance ──────────────────────────────────────────
#
# The injury / board context BLOCKS are built in
# ``src/ros/game_day_capture_context.py`` (script-only; its docstring says
# why they must stay off this request-path module).  This section only
# summarises blocks it is handed.


def _context_summary(block: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    if block.get("state") != "known":
        return {"state": block.get("state"), "reason": block.get("reason")}
    return {"state": "known", **{k: block.get(k) for k in keys}}


def snapshot_provenance(
    build: CaptureBuild,
    *,
    precedes_kickoff: datetime | None,
    precedes_basis: str,
    injuries: Mapping[str, Any],
    canonical_board: Mapping[str, Any],
    capture_context: Mapping[str, Any],
    code_revision: Mapping[str, Any],
) -> dict[str, Any]:
    """The small per-team provenance block every new snapshot carries.

    Full injury entries live once per run in the capture-context file
    (``captureContext.path`` + its ``sha256``); each snapshot carries the
    identifying hashes so it can be checked against that file without
    duplicating ~300 injury rows into every team.
    """
    return {
        "schema": "game-day-snapshot-provenance/v1",
        "precedesKickoffUtc": precedes_kickoff.isoformat() if precedes_kickoff else None,
        "precedesKickoffBasis": precedes_basis,
        "codeRevision": dict(code_revision),
        "projectionInputs": {
            "estimateSourceLabel": build.estimate_source_label,
            "sourcesLoaded": list(build.sources_loaded),
            "sourcesUnavailable": list(build.sources_unavailable),
            "starterSlotSource": build.starter_slot_source,
        },
        "injuries": _context_summary(
            injuries, ("contentSha256", "snapshotFetchedAt", "lastObservedAt", "entryCount")
        ),
        "canonicalBoardAtCapture": _context_summary(
            canonical_board, ("payloadSha256", "scrapeTimestamp", "source", "usedByEstimates")
        ),
        "captureContext": dict(capture_context),
    }
