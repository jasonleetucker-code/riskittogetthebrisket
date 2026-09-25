"""SportsDataIO live NFL game state — a provider adapter, not an owner.

What this is
------------
The owner-authorized alternative to ESPN's public scoreboard for OBSERVED
live game state (status, quarter, clock, overtime, delays, postponements,
cancellations, finals).  It emits the SAME
:class:`~src.nfl_data.live_game_state.ObservedGameState` /
:class:`~src.nfl_data.live_game_state.ScoreboardSnapshot` shapes, in the
same :data:`~src.nfl_data.live_game_state.PHASES` vocabulary, so
:func:`~src.nfl_data.live_game_state.regulation_fraction_remaining` and
every consumer work unchanged.  Reach it through
``live_game_state.fetch_live_game_state(provider="sportsdataio", …)``;
choosing a provider per poll is the collector's job
(``src/ros/game_day_live.py``).

Access: owner-attested (docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md
names SportsDataIO for live game state).  Credentials are separate from
permission — the owner installs ``SPORTSDATAIO_API_KEY``.

Endpoint
--------
NFL v3 Scores, ``Games - by Week [Live & Final]``::

    GET https://api.sportsdata.io/v3/nfl/scores/json/ScoresByWeek/{season}/{week}
        season = "<year><REG|PRE|POST>"  (e.g. 2026REG),  week = 1..18

Returns ``Score[]``.  SportsDataIO's own coverage note calls ScoresByWeek
"the most efficient endpoint for pulling live scores and live game state".
The lighter ``ScoresBasic`` (``ScoreBasic[]``) was rejected: it carries no
``HasStarted`` / ``IsInProgress`` / ``IsOver`` / ``IsOvertime``, which this
adapter uses to cross-check ``Status`` the way the ESPN parser cross-checks
its ``state``.  Field names and meanings are from SportsDataIO's published
OpenAPI (``nfl-v3-scores``, schema ``Score``) and data dictionary
(https://sportsdata.io/developers/data-dictionary/nfl), retrieved
2026-09-25; status values from the SportsDataIO FAQ ("What are all of the
game statuses used across sports?").  No live response has been captured
in this repository — the fixtures are synthetic, shaped from those docs.

Key handling
------------
The key goes in the ``Ocp-Apim-Subscription-Key`` HEADER (SportsDataIO's
documented ``apiKeyHeader`` scheme), so it never appears in a URL.  It is
read through :mod:`src.utils.secret_credentials` (the one credential owner)
and is never stored on a result, logged, or placed in an error string.  A
missing key is an explicit ``credential_missing:SPORTSDATAIO_API_KEY``
refusal with NO request — never an empty slate, never zero.

Mapping (``Status`` × ``Quarter`` → phase)
------------------------------------------
* ``Scheduled`` → SCHEDULED
* ``InProgress`` + Quarter ``1``..``4`` → IN_PROGRESS (period = quarter),
  or END_PERIOD when ``TimeRemaining`` is ``0:00`` (the quarter's clock has
  expired; SportsDataIO has no separate end-of-quarter status)
* ``InProgress`` + ``HALF`` → HALFTIME (period 2)
* ``InProgress`` + ``OT`` → IN_PROGRESS, period 5 (an overtime period)
* ``InProgress`` + ``F`` / ``F/OT`` → UNKNOWN (status/quarter conflict)
* ``Final`` / ``F/OT`` → FINAL
* ``Delayed`` / ``Suspended`` → DELAYED (a suspended game is halted with
  intent to resume; either way no remaining time can be stated)
* ``Postponed`` → POSTPONED;  ``Canceled`` (or ``Canceled: true``) → CANCELED
* anything else (``Forfeit``, ``NotNecessary``, unseen values) → UNKNOWN

A mapped status contradicted by the provider's own booleans (``Scheduled``
with ``HasStarted: true``, ``Final`` with ``IsOver: false``, a live status
with ``IsOver: true`` …) is UNKNOWN with the conflict named, never trusted.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.api import feature_flags
from src.nfl_data import live_game_state as lgs
from src.playerctx.normalize import normalize_team_code
from src.utils.secret_credentials import SecretCredential, read_credential, redact

_LOGGER = logging.getLogger(__name__)

FLAG_NAME = "sportsdataio_live_game_state"
#: Canonical secret (shared with the SportsDataIO weekly projections feed).
CREDENTIAL_ENV_VAR = "SPORTSDATAIO_API_KEY"
CREDENTIAL_HEADER = "Ocp-Apim-Subscription-Key"
API_BASE = "https://api.sportsdata.io/v3/nfl/scores/json"
ENDPOINT = "ScoresByWeek"
_UA = "riskit-live-game-state/1.0"
_TIMEOUT_SEC = 8.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: SportsDataIO timestamps without an offset are US Eastern (data dictionary:
#: "All dates & times are in US Eastern Time"; ``DateTimeUTC`` is UTC).
_EASTERN = ZoneInfo("America/New_York")

#: Snapshot ``season_type`` (ESPN/nflverse convention) → SportsDataIO season suffix.
_SEASON_SUFFIX: Mapping[int, str] = {1: "PRE", 2: "REG", 3: "POST"}
#: SportsDataIO ``SeasonType`` (1 regular, 2 pre, 3 post) → snapshot convention.
_SDIO_SEASON_TYPE_TO_SNAPSHOT: Mapping[int, int] = {1: 2, 2: 1, 3: 3}

#: ``Status`` → phase before the ``Quarter`` refinement.  Unlisted → UNKNOWN.
STATUS_TO_PHASE: Mapping[str, str] = {
    "Scheduled": lgs.PHASE_SCHEDULED,
    "InProgress": lgs.PHASE_IN_PROGRESS,
    "Final": lgs.PHASE_FINAL,
    "F/OT": lgs.PHASE_FINAL,
    "Delayed": lgs.PHASE_DELAYED,
    "Suspended": lgs.PHASE_DELAYED,
    "Postponed": lgs.PHASE_POSTPONED,
    "Canceled": lgs.PHASE_CANCELED,
}

_LIVE_QUARTERS: Mapping[str, int] = {"1": 1, "2": 2, "3": 3, "4": 4, "OT": 5}
_FINAL_QUARTERS = frozenset({"F", "F/OT"})
_HALF = "HALF"
_CLOCK_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\.\d+)?\s*$")

PROVIDER_TIMESTAMP_SOURCE = "sportsdataio_last_updated"
SNAPSHOT_TIMESTAMP_SOURCE = "sportsdataio_last_updated_max"


# ── Parsing ──────────────────────────────────────────────────────────


def _opt_bool(raw: Any) -> bool | None:
    return raw if isinstance(raw, bool) else None


def _opt_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _opt_str(raw: Any) -> str | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    return text or None


def _parse_time(raw: Any, *, naive_zone: Any) -> datetime | None:
    text = _opt_str(raw)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_zone)
    return parsed.astimezone(timezone.utc)


def _clock_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    match = _CLOCK_RE.match(raw)
    if not match:
        return None
    return float(int(match.group(1)) * 60 + int(match.group(2)))


def _lifecycle(
    has_started: bool | None, in_progress: bool | None, is_over: bool | None
) -> str | None:
    if is_over is True:
        return "post"
    if in_progress is True or has_started is True:
        return "in"
    if has_started is False:
        return "pre"
    return None


def _resolve_phase(
    status: str | None,
    quarter: str | None,
    clock: float | None,
    *,
    has_started: bool | None,
    in_progress: bool | None,
    is_over: bool | None,
    canceled: bool | None,
) -> tuple[str, str | None]:
    """``(phase, reason)``; reason is set only when the phase is UNKNOWN."""
    if status is None:
        return lgs.PHASE_UNKNOWN, "status_name_missing"
    phase = STATUS_TO_PHASE.get(status)
    if phase is None:
        return lgs.PHASE_UNKNOWN, f"unmapped_status_name:{status}"
    if canceled is True and phase != lgs.PHASE_CANCELED:
        return lgs.PHASE_UNKNOWN, f"status_flag_conflict:{status}/Canceled=true"

    if phase == lgs.PHASE_IN_PROGRESS:
        q = (quarter or "").upper()
        if q == _HALF:
            phase = lgs.PHASE_HALFTIME
        elif q in _FINAL_QUARTERS:
            return lgs.PHASE_UNKNOWN, f"status_quarter_conflict:{status}/{quarter}"
        elif q in _LIVE_QUARTERS:
            if clock == 0.0 and _LIVE_QUARTERS[q] <= 4:
                phase = lgs.PHASE_END_PERIOD
        elif q:
            return lgs.PHASE_UNKNOWN, f"unmapped_quarter:{quarter}"

    if phase == lgs.PHASE_SCHEDULED:
        for flag, value in (
            ("HasStarted", has_started),
            ("IsInProgress", in_progress),
            ("IsOver", is_over),
        ):
            if value is True:
                return lgs.PHASE_UNKNOWN, f"status_flag_conflict:{status}/{flag}=true"
    elif phase in (lgs.PHASE_IN_PROGRESS, lgs.PHASE_END_PERIOD, lgs.PHASE_HALFTIME):
        if is_over is True:
            return lgs.PHASE_UNKNOWN, f"status_flag_conflict:{status}/IsOver=true"
        if has_started is False:
            return lgs.PHASE_UNKNOWN, f"status_flag_conflict:{status}/HasStarted=false"
    elif phase == lgs.PHASE_FINAL and is_over is False:
        return lgs.PHASE_UNKNOWN, f"status_flag_conflict:{status}/IsOver=false"
    return phase, None


def _period(quarter: str | None) -> int | None:
    q = (quarter or "").upper()
    if q == _HALF:
        return 2
    return _LIVE_QUARTERS.get(q)


def _parse_row(row: Any, *, observed_at: datetime) -> lgs.ObservedGameState | None:
    if not isinstance(row, Mapping):
        return None
    home_raw = _opt_str(row.get("HomeTeam"))
    away_raw = _opt_str(row.get("AwayTeam"))
    game_id = next(
        (
            str(v)
            for v in (row.get("GameID"), row.get("ScoreID"), row.get("GameKey"))
            if _opt_str(v) is not None
        ),
        None,
    )
    if home_raw is None or away_raw is None or game_id is None:
        return None

    status = _opt_str(row.get("Status"))
    quarter = _opt_str(row.get("Quarter"))
    time_remaining = _opt_str(row.get("TimeRemaining"))
    has_started = _opt_bool(row.get("HasStarted"))
    in_progress = _opt_bool(row.get("IsInProgress"))
    is_over = _opt_bool(row.get("IsOver"))
    canceled = _opt_bool(row.get("Canceled"))
    period = _period(quarter)
    # A clock is only a statement about a quarter being played.
    clock = _clock_seconds(time_remaining) if (quarter or "").upper() in _LIVE_QUARTERS else None
    phase, reason = _resolve_phase(
        status,
        quarter,
        clock,
        has_started=has_started,
        in_progress=in_progress,
        is_over=is_over,
        canceled=canceled,
    )
    overtime = _opt_bool(row.get("IsOvertime"))
    if overtime is None and (status == "F/OT" or (quarter or "").upper() in ("OT", "F/OT")):
        overtime = True

    kickoff = _parse_time(row.get("DateTimeUTC"), naive_zone=timezone.utc) or _parse_time(
        row.get("DateTime"), naive_zone=_EASTERN
    )
    last_updated = _parse_time(row.get("LastUpdated"), naive_zone=_EASTERN)
    return lgs.ObservedGameState(
        espn_event_id=None,
        home_team=normalize_team_code(home_raw),
        away_team=normalize_team_code(away_raw),
        home_team_raw=home_raw.upper(),
        away_team_raw=away_raw.upper(),
        kickoff=kickoff,
        espn_state=None,
        status_name=status,
        phase=phase,
        phase_reason=reason,
        period=period,
        clock_seconds=clock,
        display_clock=time_remaining,
        status_detail=_opt_str(row.get("QuarterDescription")) or status,
        completed=is_over,
        home_score=_opt_int(row.get("HomeScore")),
        away_score=_opt_int(row.get("AwayScore")),
        observed_at=observed_at,
        provider_timestamp=last_updated,
        provider_timestamp_source=PROVIDER_TIMESTAMP_SOURCE if last_updated else None,
        provider=lgs.PROVIDER_SPORTSDATAIO,
        provider_game_id=game_id,
        provider_state=_lifecycle(has_started, in_progress, is_over),
        overtime=overtime,
    )


def parse_scores(
    payload: Any,
    *,
    observed_at: datetime,
    season: int | None,
    week: int | None,
    season_type: int | None,
    source_url: str | None = None,
    http_status: int | None = None,
) -> lgs.ScoreboardSnapshot:
    """A ``Score[]`` payload → snapshot.  Never raises.

    ``season`` / ``week`` / ``season_type`` are the REQUEST (snapshot
    convention: 2 = regular).  The snapshot carries what the ROWS say when
    they state it, so a payload for another week is refused downstream
    (``week_mismatch``) rather than silently used; rows that disagree with
    each other fail the whole snapshot.  An empty array is an error: a
    regular-season week always has games, so "no rows" is missing
    evidence, never an empty slate.
    """
    base = dict(
        observed_at=observed_at,
        enabled=True,
        source_url=source_url,
        http_status=http_status,
        provider=lgs.PROVIDER_SPORTSDATAIO,
    )
    if not isinstance(payload, list):
        error = "missing_payload" if payload is None else "unrecognized_payload_shape"
        return lgs.ScoreboardSnapshot(error=error, **base)
    if not payload:
        return lgs.ScoreboardSnapshot(error="empty_slate", season=season, week=week, **base)

    stated: set[tuple[int | None, int | None, int | None]] = set()
    games: list[lgs.ObservedGameState] = []
    skipped = 0
    for row in payload:
        try:
            game = _parse_row(row, observed_at=observed_at)
        except Exception as exc:  # noqa: BLE001 — one bad row must not sink the slate
            _LOGGER.warning(
                "sportsdataio_live_game_state.row_parse_failed err=%s", type(exc).__name__
            )
            game = None
        if game is None:
            skipped += 1
            continue
        games.append(game)
        sdio_type = _opt_int(row.get("SeasonType"))
        stated.add(
            (
                _opt_int(row.get("Season")),
                _opt_int(row.get("Week")),
                _SDIO_SEASON_TYPE_TO_SNAPSHOT.get(sdio_type) if sdio_type is not None else None,
            )
        )

    if len(stated) > 1:
        return lgs.ScoreboardSnapshot(
            error="mixed_season_week_in_payload",
            season=season,
            week=week,
            season_type=season_type,
            event_count=len(payload),
            skipped_events=skipped,
            **base,
        )
    row_season, row_week, row_type = next(iter(stated), (None, None, None))
    stamps = [g.provider_timestamp for g in games if g.provider_timestamp is not None]
    newest = max(stamps) if stamps else None
    return lgs.ScoreboardSnapshot(
        error=None if games else "no_parseable_games",
        season=row_season if row_season is not None else season,
        week=row_week if row_week is not None else week,
        season_type=row_type if row_type is not None else season_type,
        provider_timestamp=newest,
        provider_timestamp_source=SNAPSHOT_TIMESTAMP_SOURCE if newest else None,
        games=tuple(games),
        event_count=len(payload),
        skipped_events=skipped,
        **base,
    )


# ── Transport ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HttpResponse:
    status: int | None
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class HttpStatusError(Exception):
    """An HTTP error status with NOTHING else attached (no URL, no headers)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {int(code)}")
        self.code = int(code)


#: ``(url, headers, timeout) -> HttpResponse``; raises :class:`HttpStatusError`
#: for an error status.  Injected in every test.
HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]


def _default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(MAX_RESPONSE_BYTES + 1)
            status = getattr(resp, "status", None)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        # HTTPError holds the Request (and so the key header); keep the code only.
        raise HttpStatusError(exc.code) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError: {type(exc.reason).__name__}") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    return HttpResponse(status=status, body=body, headers=resp_headers)


def scores_by_week_url(season: int, week: int, season_type: int = 2) -> str:
    """The request URL (carries no credential).  Raises ``ValueError``."""
    if isinstance(season, bool) or not isinstance(season, int) or not 2000 <= season <= 2100:
        raise ValueError(f"season out of range: {season!r}")
    if isinstance(week, bool) or not isinstance(week, int) or not 0 <= week <= 25:
        raise ValueError(f"week out of range: {week!r}")
    suffix = _SEASON_SUFFIX.get(season_type)
    if suffix is None:
        raise ValueError(f"season_type must be 1, 2 or 3, got {season_type!r}")
    return f"{API_BASE}/{ENDPOINT}/{season}{suffix}/{week}"


def _disabled(observed_at: datetime, flag: str) -> lgs.ScoreboardSnapshot:
    return lgs.ScoreboardSnapshot(
        observed_at=observed_at,
        enabled=False,
        source_url=None,
        http_status=None,
        error=f"flag_disabled:{flag}",
        provider=lgs.PROVIDER_SPORTSDATAIO,
    )


def fetch_scores_by_week(
    *,
    season: int | None,
    week: int | None,
    season_type: int = 2,
    now: Callable[[], datetime] | None = None,
    http_get: HttpGet | None = None,
    env: Mapping[str, str] | None = None,
) -> lgs.ScoreboardSnapshot:
    """One uncached SportsDataIO ``ScoresByWeek`` read.  Never raises.

    Refusals, in order, none of which makes a request:
    Game Day master flag off / this provider's flag off → ``enabled=False``
    (``flag_disabled:<flag>``); a malformed query → ``invalid_query:…``;
    no ``SPORTSDATAIO_API_KEY`` → ``credential_missing:SPORTSDATAIO_API_KEY``;
    breaker open → ``circuit_open``.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    observed_at = clock()
    # Literals, not constants: the flag-reachability scan reads call sites
    # statically (tests/api/test_feature_flag_reachability.py).
    if not feature_flags.is_enabled("game_day_live_game_state"):
        return _disabled(observed_at, "game_day_live_game_state")
    if not feature_flags.is_enabled("sportsdataio_live_game_state"):
        return _disabled(observed_at, "sportsdataio_live_game_state")
    base = dict(observed_at=observed_at, enabled=True, provider=lgs.PROVIDER_SPORTSDATAIO)
    try:
        url = scores_by_week_url(season, week, season_type)  # type: ignore[arg-type]
    except ValueError as exc:
        return lgs.ScoreboardSnapshot(
            source_url=None, http_status=None, error=f"invalid_query:{exc}", **base
        )
    credential: SecretCredential | None = read_credential(CREDENTIAL_ENV_VAR, env)
    if credential is None:
        return lgs.ScoreboardSnapshot(
            source_url=url,
            http_status=None,
            error=f"credential_missing:{CREDENTIAL_ENV_VAR}",
            season=season,
            week=week,
            season_type=season_type,
            **base,
        )

    breaker = None
    try:
        from src.utils import circuit_breaker as _cb

        breaker = _cb.get_or_create(
            "sportsdataio_scores",
            failure_threshold=3,
            failure_window_sec=120.0,
            open_duration_sec=180.0,
        )
        if not breaker.can_call():
            _LOGGER.warning("sportsdataio_live_game_state: breaker OPEN, fast-fail")
            return lgs.ScoreboardSnapshot(
                source_url=url, http_status=None, error="circuit_open", **base
            )
    except Exception:  # noqa: BLE001
        breaker = None

    getter = http_get or _default_http_get
    try:
        response = getter(url, {CREDENTIAL_HEADER: credential.reveal()}, _TIMEOUT_SEC)
        payload = json.loads(response.body)
    except HttpStatusError as exc:
        _LOGGER.warning("sportsdataio_live_game_state: http error %s", exc.code)
        if breaker is not None:
            breaker.report_failure(exc)
        return lgs.ScoreboardSnapshot(
            source_url=url, http_status=exc.code, error=f"http_error:{exc.code}", **base
        )
    except Exception as exc:  # noqa: BLE001 — network, timeout, JSON
        _LOGGER.warning(
            "sportsdataio_live_game_state: fetch/parse error: %s",
            redact(type(exc).__name__, [credential]),
        )
        if breaker is not None:
            breaker.report_failure(exc)
        return lgs.ScoreboardSnapshot(
            source_url=url,
            http_status=None,
            error=f"fetch_failed:{type(exc).__name__}",
            **base,
        )
    if breaker is not None:
        breaker.report_success()
    return parse_scores(
        payload,
        observed_at=observed_at,
        season=season,
        week=week,
        season_type=season_type,
        source_url=url,
        http_status=getattr(response, "status", None),
    )


# ── Capability ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderCapability:
    """``eligible``: may be ATTEMPTED (both flags on, key present).
    ``available``: eligible AND the last fetch was assessed healthy —
    missing health evidence is ``unknown``, which is not available."""

    provider: str
    eligible: bool
    available: bool
    flag_on: bool
    credential_present: bool
    health_state: str
    reasons: tuple[str, ...]


def capability(
    *, last_healthy: bool | None, env: Mapping[str, str] | None = None
) -> ProviderCapability:
    master = feature_flags.is_enabled("game_day_live_game_state")
    flag_on = feature_flags.is_enabled("sportsdataio_live_game_state")
    credential_present = read_credential(CREDENTIAL_ENV_VAR, env) is not None
    reasons: list[str] = []
    if not master:
        reasons.append("feature_disabled:game_day_live_game_state")
    if not flag_on:
        reasons.append(f"feature_disabled:{FLAG_NAME}")
    if not credential_present:
        reasons.append(f"credential_missing:{CREDENTIAL_ENV_VAR}")
    health_state = (
        "unknown" if last_healthy is None else ("healthy" if last_healthy else "unhealthy")
    )
    if health_state != "healthy":
        reasons.append(f"health_{health_state}")
    eligible = master and flag_on and credential_present
    return ProviderCapability(
        provider=lgs.PROVIDER_SPORTSDATAIO,
        eligible=eligible,
        available=eligible and health_state == "healthy",
        flag_on=flag_on,
        credential_present=credential_present,
        health_state=health_state,
        reasons=tuple(reasons),
    )


__all__ = [
    "API_BASE",
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_HEADER",
    "ENDPOINT",
    "FLAG_NAME",
    "STATUS_TO_PHASE",
    "HttpResponse",
    "HttpStatusError",
    "ProviderCapability",
    "capability",
    "fetch_scores_by_week",
    "parse_scores",
    "scores_by_week_url",
]
