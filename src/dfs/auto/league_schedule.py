"""NBA / NHL game schedule for automated DFS slates (DFS-AUTO-05 for daily sports).

Source — ESPN's public scoreboard, the same provider and endpoint family the
Calculator already reads for NFL live game state, injuries and depth charts
(``src/nfl_data/live_game_state.py``; owner access attestation 2026-09-25,
``docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md``)::

    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
    https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD

Extending that integration from NFL to NBA/NHL schedules is recorded as an
EXPANSION (ADR-DFS-025, ``docs/dfs/SOURCES.md`` §9), as the access-evidence
record requires; it is not a new provider.  No key, no paid feed, no DraftKings
or FanDuel endpoint.

What this module answers, per game: canonical team codes (the identity owner's
per-sport table, ``src.identity.athletes.canonical_team``), the ``AWAY@HOME``
event id, the start time in UTC, the US-Eastern calendar date, ESPN's season
year/type and status.  A game whose start time ESPN marks invalid (``timeValid``
false), whose team code is unknown, which is preseason / all-star, or which is
postponed or cancelled is DROPPED with a reason — never given a guessed start
time, so a slate's lock is never guessed.

Fetching is paced like the DFF adapter: an on-disk cache (``MIN_REFETCH_S``),
a descriptive User-Agent, a bounded timeout and a size cap, the shared circuit
breaker, and no retry loop.  ``parse`` is pure, so a captured payload replays
deterministically in tests.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from src.dfs import store
from src.identity.athletes import canonical_team

ET = ZoneInfo("America/New_York")
SOURCE = "espn_scoreboard"
SPORT_PATHS = {"nba": "basketball/nba", "nhl": "hockey/nhl"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day}"
MIN_REFETCH_S = 30 * 60
TIMEOUT_S = 10
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "ChaseUpsideDFS/1.0 (owner research tool; contact via site)"
#: ESPN season types kept: 2 regular season, 3 postseason, 5 play-in.  1
#: (preseason) and 4 (all-star / off-season) are not classic DFS slates.
KEPT_SEASON_TYPES = frozenset({2, 3, 5})
DROPPED_STATUSES = frozenset(
    {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_FORFEIT"}
)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ScheduleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScheduledGame:
    sport: str
    event_id: str  # "AWAY@HOME" in canonical team codes
    away: str
    home: str
    start_utc: str
    date_et: str  # YYYY-MM-DD, US Eastern — the platforms' slate day
    season_year: int | None
    season_type: int | None
    status: str
    source_game_id: str


def scoreboard_url(sport: str, day: str) -> str:
    if sport not in SPORT_PATHS:
        raise ScheduleError("UNSUPPORTED_SPORT", f"No schedule source for {sport!r}.")
    if not _DAY.match(str(day or "")):
        raise ScheduleError("INVALID_DATE", f"Expected YYYY-MM-DD, got {day!r}.")
    return BASE.format(path=SPORT_PATHS[sport], day=day.replace("-", ""))


def _cache_path(sport: str, day: str):
    d = store._db_path().parent / "raw" / SOURCE
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sport}_{day}.json"


def fetch(
    sport: str,
    day: str,
    *,
    now: float | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """The scoreboard payload for one Eastern date (cached ``MIN_REFETCH_S``)."""
    url = scoreboard_url(sport, day)
    now = time.time() if now is None else now
    cache = _cache_path(sport, day)
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if now - cached["fetchedEpoch"] < MIN_REFETCH_S:
            return {**cached, "fromCache": True}
    breaker = None
    try:
        from src.utils import circuit_breaker as _cb

        breaker = _cb.get_or_create(
            f"{SOURCE}_{sport}", failure_threshold=3, failure_window_sec=120.0,
            open_duration_sec=300.0,
        )  # fmt: skip
    except Exception:  # noqa: BLE001 - the breaker is advisory
        breaker = None
    if breaker is not None and not breaker.can_call():
        raise ScheduleError("CIRCUIT_OPEN", f"{SOURCE} is failing; not called (breaker open).")
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if breaker is not None:
            breaker.report_failure(exc)
        raise ScheduleError("PROVIDER_UNAVAILABLE", f"{SOURCE} answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if breaker is not None:
            breaker.report_failure(exc)
        raise ScheduleError("PROVIDER_UNAVAILABLE", f"{SOURCE} could not be reached.") from exc
    if len(body) > MAX_BYTES:
        raise ScheduleError("SOURCE_TOO_LARGE", f"{SOURCE} payload exceeded the size cap.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if breaker is not None:
            breaker.report_failure(exc)
        raise ScheduleError("SOURCE_MALFORMED", f"{SOURCE} returned non-JSON.") from exc
    if breaker is not None:
        breaker.report_success()
    record = {
        "url": url,
        "status": status,
        "fetchedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "fetchedEpoch": now,
        "sha256": hashlib.sha256(body).hexdigest(),
        "payload": payload,
    }
    cache.write_text(json.dumps(record), encoding="utf-8")
    return {**record, "fromCache": False}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse(
    sport: str, payload: Mapping[str, Any]
) -> tuple[list[ScheduledGame], list[dict[str, Any]]]:
    """Scoreboard payload → (games, dropped).  Pure."""
    games: list[ScheduledGame] = []
    dropped: list[dict[str, Any]] = []

    def drop(event: Mapping[str, Any], reason: str) -> None:
        if len(dropped) < 100:
            dropped.append({"sourceGameId": str(event.get("id") or ""), "reason": reason})

    for ev in payload.get("events") or []:
        if not isinstance(ev, Mapping):
            continue
        comps = ev.get("competitions") or []
        comp = comps[0] if comps and isinstance(comps[0], Mapping) else {}
        season = ev.get("season") or {}
        season_type = _int(season.get("type"))
        if season_type not in KEPT_SEASON_TYPES:
            drop(ev, f"season_type_{season_type}")
            continue
        status = str(((ev.get("status") or {}).get("type") or {}).get("name") or "")
        if status in DROPPED_STATUSES:
            drop(ev, status.lower())
            continue
        if comp.get("timeValid") is False:
            drop(ev, "start_time_not_valid")
            continue
        try:
            start = datetime.fromisoformat(str(ev.get("date")).replace("Z", "+00:00"))
        except ValueError:
            drop(ev, "missing_start_time")
            continue
        if start.tzinfo is None:
            drop(ev, "start_time_without_zone")
            continue
        sides: dict[str, str | None] = {}
        for c in comp.get("competitors") or []:
            side = str(c.get("homeAway") or "")
            sides[side] = canonical_team(sport, (c.get("team") or {}).get("abbreviation"))
        away, home = sides.get("away"), sides.get("home")
        if not away or not home:
            drop(ev, "team_unknown_for_sport")
            continue
        start_utc = start.astimezone(timezone.utc)
        games.append(
            ScheduledGame(
                sport=sport,
                event_id=f"{away}@{home}",
                away=away,
                home=home,
                start_utc=start_utc.isoformat(),
                date_et=start_utc.astimezone(ET).date().isoformat(),
                season_year=_int(season.get("year")),
                season_type=season_type,
                status=status or "unknown",
                source_game_id=str(ev.get("id") or ""),
            )
        )
    return sorted(games, key=lambda g: (g.start_utc, g.event_id)), dropped
