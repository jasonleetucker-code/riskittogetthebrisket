"""BALLDONTLIE live NFL game state — a provider adapter, not an owner.

What this is
------------
An owner-approved CANDIDATE (2026-09-27) for the live game-state role ESPN's
public scoreboard can no longer fill (ESPN refuses our User-Agent with 403;
that block is not worked around).  It emits the SAME
:class:`~src.nfl_data.live_game_state.ObservedGameState` /
:class:`~src.nfl_data.live_game_state.ScoreboardSnapshot` shapes in the same
:data:`~src.nfl_data.live_game_state.PHASES` vocabulary, reached through
``live_game_state.fetch_live_game_state(provider="balldontlie", …)``.

ROLE TODAY: SHADOW ONLY.  The Game Day collector (``src/ros/game_day_live.py``
``collect_shadow_live_state``) records each observation and compares it with
the provider the collector actually selected; it is never selected, never
enters lineage or a forecast.  Promotion into the selector is a separate,
evidence-gated change (docs/game-day/BALLDONTLIE_LIVE_STATE_EVALUATION.md).

Endpoint and plan (docs: https://nfl.balldontlie.io/, read 2026-09-27)
---------------------------------------------------------------------
``GET https://api.balldontlie.io/nfl/v1/games?seasons[]=Y&weeks[]=W
&season_types[]=T&per_page=100`` — available on the FREE tier (5 requests /
minute).  Auth: the key in the ``Authorization`` header (no prefix).  Without
a key the API answers ``401 Unauthorized`` (measured 2026-09-27).

What the Games endpoint does NOT publish, and this adapter therefore never
states: the current quarter/period and the game clock.  Both exist only on
``/nfl/v1/plays`` (GOAT tier, $39.99/month), and there they are the clock AT
THE LAST PLAY, not a running clock.  So every in-progress state from this
adapter carries ``period=None`` / ``clock_seconds=None``, and
:func:`~src.nfl_data.live_game_state.regulation_fraction_remaining` answers
``None`` (``period_missing``) for it — remaining time is never inferred from
wall time since kickoff.  This is a PARTIAL live-state provider.

Mapping (documented ``status_state`` → phase)
---------------------------------------------
* ``scheduled`` → SCHEDULED (lifecycle ``pre``)
* ``in_progress`` → IN_PROGRESS (lifecycle ``in``; period / clock unknown)
* ``final`` → FINAL (lifecycle ``post``, completed)
* ``delayed`` / ``suspended`` → DELAYED
* ``postponed`` → POSTPONED;  ``canceled`` → CANCELED
* ``abandoned``, ``unknown``, a missing or unseen value → UNKNOWN (reason named)

Halftime has no documented representation (``status_state`` has no halftime
value; ``status`` is free text with only ``"Final"`` documented).  The raw
``status`` text is kept in ``status_name`` / ``status_detail`` so live shadow
evidence can show what the provider actually says; it is NOT mapped to
HALFTIME until that evidence exists.  ``overtime`` is ``True`` only when the
provider published an overtime line score (``*_ot`` not null), else unknown.

Keys, logging, missing values
-----------------------------
The key is read through :mod:`src.utils.secret_credentials` and is never
stored, logged, put in a URL or an error string.  No key → an explicit
``credential_missing:BALLDONTLIE_API_KEY`` refusal with NO request.  A missing
score is ``None``, never 0; an empty ``data`` array is an error, never an
empty slate; a paginated answer (a week has at most 16 games, we ask for 100)
is refused rather than read partially.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.api import feature_flags
from src.nfl_data import live_game_state as lgs
from src.playerctx.normalize import normalize_team_code
from src.utils.name_clean import NFL_TEAM_CODES
from src.utils.secret_credentials import SecretCredential, read_credential, redact

_LOGGER = logging.getLogger(__name__)

FLAG_NAME = "balldontlie_live_game_state"
CREDENTIAL_ENV_VAR = "BALLDONTLIE_API_KEY"
CREDENTIAL_HEADER = "Authorization"
API_BASE = "https://api.balldontlie.io/nfl/v1"
ENDPOINT = "games"
PER_PAGE = 100
#: Free-tier limit (docs, 2026-09-27).  The shared collector makes at most one
#: request per tick (>= 60 s apart), i.e. at most 1 request/minute.
FREE_TIER_REQUESTS_PER_MINUTE = 5
_UA = "riskit-live-game-state/1.0"
_TIMEOUT_SEC = 8.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

#: Documented ``status_state`` values → phase.  Unlisted → UNKNOWN.
STATUS_STATE_TO_PHASE: Mapping[str, str] = {
    "scheduled": lgs.PHASE_SCHEDULED,
    "in_progress": lgs.PHASE_IN_PROGRESS,
    "final": lgs.PHASE_FINAL,
    "delayed": lgs.PHASE_DELAYED,
    "suspended": lgs.PHASE_DELAYED,
    "postponed": lgs.PHASE_POSTPONED,
    "canceled": lgs.PHASE_CANCELED,
}
_LIFECYCLE: Mapping[str, str] = {"scheduled": "pre", "in_progress": "in", "final": "post"}


# ── Parsing ──────────────────────────────────────────────────────────


def _opt_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _opt_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_time(raw: Any) -> datetime | None:
    text = _opt_str(raw)
    if text is None:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _team_code(team: Any) -> tuple[str | None, str | None]:
    """``(canonical code, raw code)``; canonical is ``None`` for an unknown team."""
    raw = _opt_str(team.get("abbreviation")) if isinstance(team, Mapping) else None
    if raw is None:
        return None, None
    code = normalize_team_code(raw)
    return (code if code in NFL_TEAM_CODES else None), raw.upper()


def _resolve_phase(status_state: str | None) -> tuple[str, str | None]:
    if status_state is None:
        return lgs.PHASE_UNKNOWN, "status_state_missing"
    phase = STATUS_STATE_TO_PHASE.get(status_state)
    if phase is None:
        return lgs.PHASE_UNKNOWN, f"unmapped_status_state:{status_state}"
    return phase, None


def _parse_row(row: Any, *, observed_at: datetime) -> lgs.ObservedGameState | None:
    if not isinstance(row, Mapping):
        return None
    game_id = _opt_str(row.get("id"))
    home, home_raw = _team_code(row.get("home_team"))
    away, away_raw = _team_code(row.get("visitor_team"))
    if game_id is None or home is None or away is None or home == away:
        return None
    status_state = (_opt_str(row.get("status_state")) or "").lower() or None
    status = _opt_str(row.get("status"))
    phase, reason = _resolve_phase(status_state)
    home_ot, away_ot = row.get("home_team_ot"), row.get("visitor_team_ot")
    overtime = True if (home_ot is not None or away_ot is not None) else None
    completed = {"final": True, "scheduled": False, "in_progress": False}.get(status_state or "")
    return lgs.ObservedGameState(
        espn_event_id=None,
        home_team=home,
        away_team=away,
        home_team_raw=home_raw or home,
        away_team_raw=away_raw or away,
        kickoff=_parse_time(row.get("date")),
        espn_state=None,
        status_name=status,
        phase=phase,
        phase_reason=reason,
        # NOT PUBLISHED on the Games endpoint: missing stays missing.
        period=None,
        clock_seconds=None,
        display_clock=None,
        status_detail=status,
        completed=completed,
        home_score=_opt_int(row.get("home_team_score")),
        away_score=_opt_int(row.get("visitor_team_score")),
        observed_at=observed_at,
        provider=lgs.PROVIDER_BALLDONTLIE,
        provider_game_id=game_id,
        provider_state=_LIFECYCLE.get(status_state or ""),
        overtime=overtime,
    )


def parse_games(
    payload: Any,
    *,
    observed_at: datetime,
    season: int | None,
    week: int | None,
    season_type: int | None,
    source_url: str | None = None,
    http_status: int | None = None,
) -> lgs.ScoreboardSnapshot:
    """A ``{"data": [...], "meta": {...}}`` payload → snapshot.  Never raises.

    Rows that state a different season/week than each other fail the whole
    snapshot (``mixed_season_week_in_payload``); the snapshot carries what the
    rows state so a payload for another week is refused downstream.
    """
    base = dict(
        observed_at=observed_at,
        enabled=True,
        source_url=source_url,
        http_status=http_status,
        provider=lgs.PROVIDER_BALLDONTLIE,
    )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        error = "missing_payload" if payload is None else "unrecognized_payload_shape"
        return lgs.ScoreboardSnapshot(error=error, **base)
    rows = payload["data"]
    meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
    if meta.get("next_cursor") is not None:
        return lgs.ScoreboardSnapshot(
            error="unexpected_pagination", season=season, week=week, **base
        )
    if not rows:
        return lgs.ScoreboardSnapshot(error="empty_slate", season=season, week=week, **base)

    stated: set[tuple[int | None, int | None, int | None]] = set()
    games: list[lgs.ObservedGameState] = []
    skipped = 0
    for row in rows:
        try:
            game = _parse_row(row, observed_at=observed_at)
        except Exception as exc:  # noqa: BLE001 — one bad row must not sink the slate
            _LOGGER.warning(
                "balldontlie_live_game_state.row_parse_failed err=%s", type(exc).__name__
            )
            game = None
        if game is None:
            skipped += 1
            continue
        games.append(game)
        post = row.get("postseason")
        stated.add(
            (
                _opt_int(row.get("season")),
                _opt_int(row.get("week")),
                3 if post is True else (season_type if post is False else None),
            )
        )
    if len(stated) > 1:
        return lgs.ScoreboardSnapshot(
            error="mixed_season_week_in_payload",
            season=season,
            week=week,
            season_type=season_type,
            event_count=len(rows),
            skipped_events=skipped,
            **base,
        )
    row_season, row_week, row_type = next(iter(stated), (None, None, None))
    return lgs.ScoreboardSnapshot(
        error=None if games else "no_parseable_games",
        season=row_season if row_season is not None else season,
        week=row_week if row_week is not None else week,
        season_type=row_type if row_type is not None else season_type,
        games=tuple(games),
        event_count=len(rows),
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


def games_url(season: int, week: int, season_type: int = 2) -> str:
    """The request URL (carries no credential).  Raises ``ValueError``."""
    if isinstance(season, bool) or not isinstance(season, int) or not 2000 <= season <= 2100:
        raise ValueError(f"season out of range: {season!r}")
    if isinstance(week, bool) or not isinstance(week, int) or not 0 <= week <= 25:
        raise ValueError(f"week out of range: {week!r}")
    if season_type not in (1, 2, 3):
        raise ValueError(f"season_type must be 1, 2 or 3, got {season_type!r}")
    query = urllib.parse.urlencode(
        [
            ("seasons[]", season),
            ("weeks[]", week),
            ("season_types[]", season_type),
            ("per_page", PER_PAGE),
        ]
    )
    return f"{API_BASE}/{ENDPOINT}?{query}"


def _disabled(observed_at: datetime, flag: str) -> lgs.ScoreboardSnapshot:
    return lgs.ScoreboardSnapshot(
        observed_at=observed_at,
        enabled=False,
        source_url=None,
        http_status=None,
        error=f"flag_disabled:{flag}",
        provider=lgs.PROVIDER_BALLDONTLIE,
    )


def fetch_games_by_week(
    *,
    season: int | None,
    week: int | None,
    season_type: int = 2,
    now: Callable[[], datetime] | None = None,
    http_get: HttpGet | None = None,
    env: Mapping[str, str] | None = None,
) -> lgs.ScoreboardSnapshot:
    """One uncached BALLDONTLIE ``games`` read for one week.  Never raises.

    Refusals, in order, none of which makes a request: Game Day master flag
    off / this provider's flag off → ``enabled=False``; a malformed query →
    ``invalid_query:…``; no ``BALLDONTLIE_API_KEY`` →
    ``credential_missing:BALLDONTLIE_API_KEY``; breaker open →
    ``circuit_open``.  HTTP errors (401 no key / tier, 429 rate limited, 5xx)
    → ``http_error:<code>``.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    observed_at = clock()
    # Literals, not constants: the flag-reachability scan reads call sites
    # statically (tests/api/test_feature_flag_reachability.py).
    if not feature_flags.is_enabled("game_day_live_game_state"):
        return _disabled(observed_at, "game_day_live_game_state")
    if not feature_flags.is_enabled("balldontlie_live_game_state"):
        return _disabled(observed_at, "balldontlie_live_game_state")
    base = dict(observed_at=observed_at, enabled=True, provider=lgs.PROVIDER_BALLDONTLIE)
    try:
        url = games_url(season, week, season_type)  # type: ignore[arg-type]
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
            "balldontlie_games",
            failure_threshold=3,
            failure_window_sec=120.0,
            open_duration_sec=180.0,
        )
        if not breaker.can_call():
            _LOGGER.warning("balldontlie_live_game_state: breaker OPEN, fast-fail")
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
        _LOGGER.warning("balldontlie_live_game_state: http error %s", exc.code)
        if breaker is not None:
            breaker.report_failure(exc)
        return lgs.ScoreboardSnapshot(
            source_url=url, http_status=exc.code, error=f"http_error:{exc.code}", **base
        )
    except Exception as exc:  # noqa: BLE001 — network, timeout, JSON
        _LOGGER.warning(
            "balldontlie_live_game_state: fetch/parse error: %s",
            redact(type(exc).__name__, [credential]),
        )
        if breaker is not None:
            breaker.report_failure(exc)
        return lgs.ScoreboardSnapshot(
            source_url=url, http_status=None, error=f"fetch_failed:{type(exc).__name__}", **base
        )
    if breaker is not None:
        breaker.report_success()
    return parse_games(
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
    """``eligible``: may be ATTEMPTED (both flags on, key present)."""

    provider: str
    eligible: bool
    flag_on: bool
    credential_present: bool
    reasons: tuple[str, ...]


def capability(env: Mapping[str, str] | None = None) -> ProviderCapability:
    master = feature_flags.is_enabled("game_day_live_game_state")
    flag_on = feature_flags.is_enabled("balldontlie_live_game_state")
    credential_present = read_credential(CREDENTIAL_ENV_VAR, env) is not None
    reasons: list[str] = []
    if not master:
        reasons.append("feature_disabled:game_day_live_game_state")
    if not flag_on:
        reasons.append(f"feature_disabled:{FLAG_NAME}")
    if not credential_present:
        reasons.append(f"credential_missing:{CREDENTIAL_ENV_VAR}")
    return ProviderCapability(
        provider=lgs.PROVIDER_BALLDONTLIE,
        eligible=master and flag_on and credential_present,
        flag_on=flag_on,
        credential_present=credential_present,
        reasons=tuple(reasons),
    )


__all__ = [
    "API_BASE",
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_HEADER",
    "ENDPOINT",
    "FLAG_NAME",
    "FREE_TIER_REQUESTS_PER_MINUTE",
    "STATUS_STATE_TO_PHASE",
    "HttpResponse",
    "HttpStatusError",
    "ProviderCapability",
    "capability",
    "fetch_games_by_week",
    "games_url",
    "parse_games",
]
