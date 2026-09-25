"""Observed live NFL game state from ESPN's public scoreboard — read-only.

Source
------
The undocumented public endpoint already used by
:mod:`src.nfl_data.injury_feed` and :mod:`src.nfl_data.depth_charts`::

    https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
        [?dates=YYYYMMDD]  or  [?week=N&seasontype=2]

No key, no paid feed.  Same conventions as its siblings: urllib with an
explicit user agent, a bounded timeout, the shared circuit breaker, and a
feature flag (``game_day_live_game_state``, default OFF) that returns an
explicit disabled observation rather than data.

What this module answers
------------------------
Per game: ESPN event id, home/away team codes normalised to the codes
Sleeper and nflverse use (via :func:`src.playerctx.normalize.normalize_team_code`,
the existing owner — ESPN's ``WSH`` becomes ``WAS``), kickoff, ESPN state
(``pre``/``in``/``post``), the raw ESPN status name mapped onto an explicit
:data:`PHASES` value, period, clock seconds, the completed flag, scores,
and when WE observed it.  ESPN's scoreboard body carries no update
timestamp of its own (measured on a 2026 week-3 capture); the only
provider-side time is the HTTP ``Last-Modified`` / ``Date`` header, which
is recorded with its source named.

It also answers ONE derived question, :func:`regulation_fraction_remaining`,
from the OBSERVED quarter and clock — not from wall time since kickoff.
Overtime, delays, postponements and unknown states return ``None`` with a
reason: this module does not invent remaining time the provider did not
state.  Deciding what to do with that ``None`` belongs to the caller.

Status names
------------
Only the names in :data:`STATUS_NAME_TO_PHASE` are mapped.  Anything else
— including plausible ESPN names that have not been observed and verified
here — becomes :data:`PHASE_UNKNOWN`.  A mapped name whose ESPN ``state``
contradicts it (e.g. ``STATUS_FINAL`` with state ``in``) is also
``UNKNOWN``, with the conflict recorded, rather than trusting either half.

Not wired: nothing in ``server.py`` imports this yet.  Polling cadence and
caching belong to the future shared background collector; this module
performs exactly one uncached request per call.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src.api import feature_flags
from src.playerctx.normalize import normalize_team_code

_LOGGER = logging.getLogger(__name__)

FLAG_NAME = "game_day_live_game_state"

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
_UA = "riskit-live-game-state/1.0"
_TIMEOUT_SEC = 8.0

# ── Phases ───────────────────────────────────────────────────────────

PHASE_SCHEDULED = "SCHEDULED"
PHASE_IN_PROGRESS = "IN_PROGRESS"
PHASE_END_PERIOD = "END_PERIOD"
PHASE_HALFTIME = "HALFTIME"
PHASE_FINAL = "FINAL"
PHASE_DELAYED = "DELAYED"
PHASE_POSTPONED = "POSTPONED"
PHASE_CANCELED = "CANCELED"
PHASE_UNKNOWN = "UNKNOWN"

PHASES: frozenset[str] = frozenset(
    {
        PHASE_SCHEDULED,
        PHASE_IN_PROGRESS,
        PHASE_END_PERIOD,
        PHASE_HALFTIME,
        PHASE_FINAL,
        PHASE_DELAYED,
        PHASE_POSTPONED,
        PHASE_CANCELED,
        PHASE_UNKNOWN,
    }
)

#: ESPN ``status.type.name`` → phase.  Unlisted names map to UNKNOWN.
#: Observed in a real 2026 capture: STATUS_SCHEDULED, STATUS_END_PERIOD.
#: The rest are ESPN's published status vocabulary as named by the owner
#: contract; they are exercised by synthetic fixtures only.
STATUS_NAME_TO_PHASE: Mapping[str, str] = {
    "STATUS_SCHEDULED": PHASE_SCHEDULED,
    "STATUS_IN_PROGRESS": PHASE_IN_PROGRESS,
    "STATUS_END_PERIOD": PHASE_END_PERIOD,
    "STATUS_HALFTIME": PHASE_HALFTIME,
    "STATUS_FINAL": PHASE_FINAL,
    "STATUS_FINAL_OVERTIME": PHASE_FINAL,
    "STATUS_DELAYED": PHASE_DELAYED,
    "STATUS_RAIN_DELAY": PHASE_DELAYED,
    "STATUS_POSTPONED": PHASE_POSTPONED,
    "STATUS_CANCELED": PHASE_CANCELED,
}

#: ESPN ``state`` values each core phase is consistent with.  Phases not
#: listed (delays, postponements, cancellations) are accepted in any state
#: because ESPN uses them both before and during a game.
_EXPECTED_STATE: Mapping[str, frozenset[str]] = {
    PHASE_SCHEDULED: frozenset({"pre"}),
    PHASE_IN_PROGRESS: frozenset({"in"}),
    PHASE_END_PERIOD: frozenset({"in"}),
    PHASE_HALFTIME: frozenset({"in"}),
    PHASE_FINAL: frozenset({"post"}),
}

_PERIOD_SECONDS = 900.0
_REGULATION_PERIODS = 4
_REGULATION_SECONDS = _PERIOD_SECONDS * _REGULATION_PERIODS

_DISPLAY_CLOCK_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\.\d+)?\s*$")


@dataclass(frozen=True)
class ObservedGameState:
    """One game as ESPN reported it at ``observed_at``."""

    espn_event_id: str
    home_team: str
    away_team: str
    home_team_raw: str
    away_team_raw: str
    kickoff: datetime | None
    espn_state: str | None
    status_name: str | None
    phase: str
    #: Why ``phase`` is UNKNOWN (unmapped name, missing name, state conflict).
    phase_reason: str | None
    period: int | None
    clock_seconds: float | None
    display_clock: str | None
    status_detail: str | None
    completed: bool | None
    home_score: int | None
    away_score: int | None
    observed_at: datetime
    provider_timestamp: datetime | None = None
    provider_timestamp_source: str | None = None

    @property
    def is_overtime(self) -> bool:
        return self.period is not None and self.period > _REGULATION_PERIODS


@dataclass(frozen=True)
class ScoreboardSnapshot:
    """One observation of the scoreboard plus how it was obtained."""

    observed_at: datetime
    enabled: bool
    source_url: str | None
    http_status: int | None
    error: str | None
    provider_timestamp: datetime | None = None
    provider_timestamp_source: str | None = None
    season: int | None = None
    season_type: int | None = None
    week: int | None = None
    games: tuple[ObservedGameState, ...] = field(default_factory=tuple)
    #: Events present in the payload, before skipping.
    event_count: int = 0
    #: Events skipped as malformed (no id, no competitors, no team codes …).
    skipped_events: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RegulationRemaining:
    """``fraction`` of regulation left, or ``None`` with ``reason``."""

    fraction: float | None
    reason: str | None


# ── Parsing helpers ──────────────────────────────────────────────────


def _opt_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        try:
            as_float = float(raw)
        except (TypeError, ValueError):
            return None
        return int(as_float) if as_float.is_integer() else None


def _opt_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _opt_str(raw: Any) -> str | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    return text or None


def _parse_iso(raw: Any) -> datetime | None:
    text = _opt_str(raw)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clock_seconds(status: Mapping[str, Any]) -> float | None:
    clock = _opt_float(status.get("clock"))
    if clock is not None:
        return clock
    match = _DISPLAY_CLOCK_RE.match(str(status.get("displayClock") or ""))
    if match:
        return float(int(match.group(1)) * 60 + int(match.group(2)))
    return None


def _resolve_phase(status_name: str | None, espn_state: str | None) -> tuple[str, str | None]:
    if status_name is None:
        return PHASE_UNKNOWN, "status_name_missing"
    phase = STATUS_NAME_TO_PHASE.get(status_name)
    if phase is None:
        return PHASE_UNKNOWN, f"unmapped_status_name:{status_name}"
    expected = _EXPECTED_STATE.get(phase)
    if expected is not None and espn_state is not None and espn_state not in expected:
        return PHASE_UNKNOWN, f"status_state_conflict:{status_name}/{espn_state}"
    return phase, None


def _parse_event(
    event: Any,
    *,
    observed_at: datetime,
    provider_timestamp: datetime | None,
    provider_timestamp_source: str | None,
) -> ObservedGameState | None:
    if not isinstance(event, Mapping):
        return None
    event_id = _opt_str(event.get("id"))
    competitions = event.get("competitions")
    if event_id is None or not isinstance(competitions, list) or not competitions:
        return None
    comp = competitions[0]
    if not isinstance(comp, Mapping):
        return None

    teams: dict[str, tuple[str, int | None]] = {}
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return None
    for competitor in competitors:
        if not isinstance(competitor, Mapping):
            continue
        side = _opt_str(competitor.get("homeAway"))
        team = competitor.get("team")
        abbr = _opt_str(team.get("abbreviation")) if isinstance(team, Mapping) else None
        if side in ("home", "away") and abbr is not None:
            teams[side] = (abbr.upper(), _opt_int(competitor.get("score")))
    if "home" not in teams or "away" not in teams:
        return None

    status = comp.get("status")
    if not isinstance(status, Mapping):
        status = event.get("status")
    if not isinstance(status, Mapping):
        status = {}
    status_type = status.get("type")
    if not isinstance(status_type, Mapping):
        status_type = {}

    status_name = _opt_str(status_type.get("name"))
    espn_state = _opt_str(status_type.get("state"))
    espn_state = espn_state.lower() if espn_state else None
    phase, phase_reason = _resolve_phase(status_name, espn_state)
    completed_raw = status_type.get("completed")

    home_raw, home_score = teams["home"]
    away_raw, away_score = teams["away"]
    return ObservedGameState(
        espn_event_id=event_id,
        home_team=normalize_team_code(home_raw),
        away_team=normalize_team_code(away_raw),
        home_team_raw=home_raw,
        away_team_raw=away_raw,
        kickoff=_parse_iso(comp.get("date") or event.get("date")),
        espn_state=espn_state,
        status_name=status_name,
        phase=phase,
        phase_reason=phase_reason,
        period=_opt_int(status.get("period")),
        clock_seconds=_clock_seconds(status),
        display_clock=_opt_str(status.get("displayClock")),
        status_detail=_opt_str(status_type.get("shortDetail") or status_type.get("detail")),
        completed=completed_raw if isinstance(completed_raw, bool) else None,
        home_score=home_score,
        away_score=away_score,
        observed_at=observed_at,
        provider_timestamp=provider_timestamp,
        provider_timestamp_source=provider_timestamp_source,
    )


def parse_scoreboard(
    payload: Any,
    *,
    observed_at: datetime,
    source_url: str | None = None,
    http_status: int | None = None,
    error: str | None = None,
    provider_timestamp: datetime | None = None,
    provider_timestamp_source: str | None = None,
    enabled: bool = True,
) -> ScoreboardSnapshot:
    """Parse a scoreboard payload into a snapshot.  Never raises."""
    games: list[ObservedGameState] = []
    event_count = 0
    skipped = 0
    season = season_type = week = None
    if isinstance(payload, Mapping):
        season_block = payload.get("season")
        if isinstance(season_block, Mapping):
            season = _opt_int(season_block.get("year"))
            season_type = _opt_int(season_block.get("type"))
        week_block = payload.get("week")
        if isinstance(week_block, Mapping):
            week = _opt_int(week_block.get("number"))
        events = payload.get("events")
        if isinstance(events, list):
            for event in events:
                event_count += 1
                try:
                    game = _parse_event(
                        event,
                        observed_at=observed_at,
                        provider_timestamp=provider_timestamp,
                        provider_timestamp_source=provider_timestamp_source,
                    )
                except Exception as exc:  # noqa: BLE001 — one bad event must not sink the slate
                    _LOGGER.warning("live_game_state.event_parse_failed err=%r", exc)
                    game = None
                if game is None:
                    skipped += 1
                else:
                    games.append(game)
        elif error is None:
            error = "events_missing"
    elif error is None:
        error = "missing_payload" if payload is None else "unrecognized_payload_shape"

    return ScoreboardSnapshot(
        observed_at=observed_at,
        enabled=enabled,
        source_url=source_url,
        http_status=http_status,
        error=error,
        provider_timestamp=provider_timestamp,
        provider_timestamp_source=provider_timestamp_source,
        season=season,
        season_type=season_type,
        week=week,
        games=tuple(games),
        event_count=event_count,
        skipped_events=skipped,
    )


# ── Fetch ────────────────────────────────────────────────────────────


def scoreboard_url(
    *, dates: str | None = None, week: int | None = None, season_type: int | None = None
) -> str:
    """Build the scoreboard URL.  Raises ``ValueError`` on a malformed query."""
    params: dict[str, str] = {}
    if dates is not None:
        if not re.fullmatch(r"\d{8}", str(dates)):
            raise ValueError(f"dates must be YYYYMMDD, got {dates!r}")
        params["dates"] = str(dates)
    if week is not None:
        if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 25:
            raise ValueError(f"week out of range: {week!r}")
        params["week"] = str(week)
    if season_type is not None:
        if season_type not in (1, 2, 3):
            raise ValueError(f"season_type must be 1, 2 or 3, got {season_type!r}")
        params["seasontype"] = str(season_type)
    if not params:
        return ESPN_SCOREBOARD_URL
    return f"{ESPN_SCOREBOARD_URL}?{urllib.parse.urlencode(params)}"


def _provider_time(headers: Any) -> tuple[datetime | None, str | None]:
    if headers is None:
        return None, None
    for header, source in (("Last-Modified", "http_last_modified"), ("Date", "http_date")):
        try:
            raw = headers.get(header)
        except Exception:  # noqa: BLE001
            raw = None
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError, IndexError):
            continue
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed, source
    return None, None


def fetch_live_game_state(
    *,
    dates: str | None = None,
    week: int | None = None,
    season_type: int | None = None,
    now: Callable[[], datetime] | None = None,
    _url_opener: Callable[..., Any] | None = None,
) -> ScoreboardSnapshot:
    """One uncached read of the ESPN scoreboard.  Never raises.

    Flag off → an ``enabled=False`` snapshot with no games and
    ``error="flag_disabled"`` — distinguishable from an empty slate.
    ``now`` and ``_url_opener`` are test hooks.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    observed_at = clock()
    # Literal, not FLAG_NAME: the flag-reachability scan reads call sites
    # statically (tests/api/test_feature_flag_reachability.py).
    if not feature_flags.is_enabled("game_day_live_game_state"):
        return ScoreboardSnapshot(
            observed_at=observed_at,
            enabled=False,
            source_url=None,
            http_status=None,
            error="flag_disabled",
        )
    try:
        url = scoreboard_url(dates=dates, week=week, season_type=season_type)
    except ValueError as exc:
        return ScoreboardSnapshot(
            observed_at=observed_at,
            enabled=True,
            source_url=None,
            http_status=None,
            error=f"invalid_query:{exc}",
        )

    breaker = None
    try:
        from src.utils import circuit_breaker as _cb

        breaker = _cb.get_or_create(
            "espn_scoreboard",
            failure_threshold=3,
            failure_window_sec=120.0,
            open_duration_sec=180.0,
        )
        if not breaker.can_call():
            _LOGGER.warning("live_game_state: breaker OPEN, fast-fail")
            return ScoreboardSnapshot(
                observed_at=observed_at,
                enabled=True,
                source_url=url,
                http_status=None,
                error="circuit_open",
            )
    except Exception:  # noqa: BLE001
        breaker = None

    status: int | None = None
    headers: Any = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        opener = _url_opener or urllib.request.urlopen
        with opener(req, timeout=_TIMEOUT_SEC) as resp:
            status = getattr(resp, "status", None)
            headers = getattr(resp, "headers", None)
            body = resp.read()
        payload = json.loads(body)
    except urllib.error.HTTPError as exc:
        _LOGGER.warning("live_game_state: http error %s", exc.code)
        if breaker is not None:
            breaker.report_failure(exc)
        return ScoreboardSnapshot(
            observed_at=observed_at,
            enabled=True,
            source_url=url,
            http_status=exc.code,
            error=f"http_error:{exc.code}",
        )
    except Exception as exc:  # noqa: BLE001 — network, timeout, JSON
        _LOGGER.warning("live_game_state: fetch/parse error: %r", exc)
        if breaker is not None:
            breaker.report_failure(exc)
        return ScoreboardSnapshot(
            observed_at=observed_at,
            enabled=True,
            source_url=url,
            http_status=status,
            error=f"fetch_failed:{type(exc).__name__}",
        )

    if breaker is not None:
        breaker.report_success()
    provider_ts, provider_src = _provider_time(headers)
    return parse_scoreboard(
        payload,
        observed_at=observed_at,
        source_url=url,
        http_status=status,
        provider_timestamp=provider_ts,
        provider_timestamp_source=provider_src,
    )


# ── Derived: regulation remaining ────────────────────────────────────


def regulation_fraction_remaining(state: ObservedGameState) -> RegulationRemaining:
    """Fraction of REGULATION game time left, from the observed clock.

    * scheduled → 1.0;  final → 0.0;  halftime → 0.5
    * in progress, period p in 1..4 → ((4 − p)·900 + clock) / 3600
    * end of period p in 1..4 → (4 − p)·900 / 3600
    * overtime (period > 4), delayed, postponed, canceled, unknown, or a
      missing/out-of-range period or clock → ``None`` with a reason.

    An out-of-range clock (outside 0..900 s) is refused rather than
    clamped into a neighbouring quarter; the final value is clamped to
    [0, 1] only against float noise.  End of the 4th quarter is 0.0 —
    regulation IS over — even though the game may still go to overtime;
    that is the caller's question, answered from ``phase`` / ``period``.
    """
    phase = state.phase
    if phase == PHASE_SCHEDULED:
        return RegulationRemaining(1.0, None)
    if phase == PHASE_FINAL:
        return RegulationRemaining(0.0, None)
    if phase == PHASE_HALFTIME:
        return RegulationRemaining(0.5, None)
    if phase == PHASE_DELAYED:
        return RegulationRemaining(None, "delayed")
    if phase == PHASE_POSTPONED:
        return RegulationRemaining(None, "postponed")
    if phase == PHASE_CANCELED:
        return RegulationRemaining(None, "canceled")
    if phase not in (PHASE_IN_PROGRESS, PHASE_END_PERIOD):
        return RegulationRemaining(None, f"unknown_status:{state.phase_reason or phase}")

    period = state.period
    if period is None or period < 1:
        return RegulationRemaining(None, "period_missing")
    if period > _REGULATION_PERIODS:
        return RegulationRemaining(None, "overtime")
    periods_after = _REGULATION_PERIODS - period
    if phase == PHASE_END_PERIOD:
        seconds = periods_after * _PERIOD_SECONDS
    else:
        clock = state.clock_seconds
        if clock is None:
            return RegulationRemaining(None, "clock_missing")
        if clock < 0 or clock > _PERIOD_SECONDS:
            return RegulationRemaining(None, "clock_out_of_range")
        seconds = periods_after * _PERIOD_SECONDS + clock
    return RegulationRemaining(min(1.0, max(0.0, seconds / _REGULATION_SECONDS)), None)


__all__ = [
    "ESPN_SCOREBOARD_URL",
    "FLAG_NAME",
    "PHASES",
    "PHASE_CANCELED",
    "PHASE_DELAYED",
    "PHASE_END_PERIOD",
    "PHASE_FINAL",
    "PHASE_HALFTIME",
    "PHASE_IN_PROGRESS",
    "PHASE_POSTPONED",
    "PHASE_SCHEDULED",
    "PHASE_UNKNOWN",
    "STATUS_NAME_TO_PHASE",
    "ObservedGameState",
    "RegulationRemaining",
    "ScoreboardSnapshot",
    "fetch_live_game_state",
    "parse_scoreboard",
    "regulation_fraction_remaining",
    "scoreboard_url",
]
