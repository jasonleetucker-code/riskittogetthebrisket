"""Thin, side-effect-free Sleeper HTTP client for the public pipeline.

The public league snapshot pulls exclusively from the documented
Sleeper v1 endpoints.  No internal scraper state, no CSV, no cached
private payload.  Every call degrades gracefully — a network failure
returns ``None`` / ``[]`` rather than raising, so the snapshot can
still render with partial sections instead of failing the whole
page.

History depth: the WHOLE ``previous_league_id`` chain.  The walk stops at
Sleeper's terminator (``"0"`` / empty), at a link it cannot read, at a
loop, or at a 25-season SAFETY cap -- and it says which
(:func:`walk_league_chain_status`), so a truncated history can never pass
for a complete one (C9-HIST-02).

Network layer:
    Uses a module-level ``requests.Session`` with a pooled
    ``HTTPAdapter``.  Across a 12-thread snapshot build that's one
    TLS handshake amortized over ~85 GETs instead of 85 separate
    handshakes.  Drops cold-fetch from ~0.65s to ~0.25s against the
    live Sleeper chain.
"""

from __future__ import annotations

import logging
import os as _os
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

# SAFETY cap on the dynasty seasons the public pipeline walks -- not a
# retention window.  "All-time" records, archives, Hall of Fame and every
# other section iterate ``snapshot.seasons``, so this constant decides how
# much league history exists for them.  It used to be 3, which made
# "all-time" a rolling 3-season window that was correct only by coincidence
# (dynasty_main's chain was exactly 3 seasons long) and would have silently
# dropped 2024 at the 2027 rollover (C9-HIST-02 / W19-F017).  25 is a guard
# against a malformed or cyclic chain, far past any real league's age; if a
# chain ever reaches it the walk reports ``truncated`` instead of passing
# the partial history off as complete.  Env override retained for ops.
DEFAULT_PUBLIC_MAX_SEASONS = 25
try:
    PUBLIC_MAX_SEASONS = max(
        1, int(_os.getenv("PUBLIC_MAX_SEASONS", str(DEFAULT_PUBLIC_MAX_SEASONS)))
    )
except ValueError:
    PUBLIC_MAX_SEASONS = DEFAULT_PUBLIC_MAX_SEASONS

#: Sleeper's ``previous_league_id`` for a league with no predecessor.
_CHAIN_TERMINATORS = frozenset({"", "0"})

#: :func:`walk_league_chain_status` outcomes.
CHAIN_COMPLETE = "complete"  # reached the first season of the league
CHAIN_TRUNCATED = "truncated"  # hit the safety cap with history still pending
CHAIN_UNVERIFIED = "unverified"  # a link could not be read, looped, or has no type
# The predecessor is a real league but not a DYNASTY one (Sleeper
# ``settings.type`` != 2): a redraft/keeper season is not this dynasty's
# history, so the walk stops there rather than mixing it in.
CHAIN_NON_DYNASTY = "non_dynasty_predecessor"

#: Sleeper ``league.settings.type``: 0 redraft, 1 keeper, 2 dynasty.
SLEEPER_DYNASTY_TYPE = 2

_DEFAULT_TIMEOUT = 8.0

# Connection-pool size has to match the snapshot fetcher's thread cap
# (see snapshot.py::_FETCH_CONCURRENCY).  Being under-provisioned would
# force threads to queue on the pool and negate the parallelism win.
_POOL_SIZE = 16

# In-process TTL cache for Sleeper GETs.  The snapshot builder makes
# ~85 calls per build with mostly-unique URLs, so dedup-within-build
# benefit is modest — the real win is across-build dedup when:
#   1. Multiple clients hit /api/public/league in close succession
#      (pre-snapshot-cache-expiry, when the higher-level
#      _public_league_cache happens to miss),
#   2. The 20-min warm-up cron and a synchronous user request race
#      to rebuild the same snapshot,
#   3. ROS scrape's fetch_nfl_players (already module-cached) and
#      another caller hit Sleeper inside the same minute.
#
# 60s TTL = under the 20-min warm-up cadence, so cron rebuilds always
# get fresh data, but bursts of user traffic between cron runs share
# one upstream request.  Tunable via env without a code change.
try:
    _CACHE_TTL_SECONDS = max(0, float(_os.getenv("PUBLIC_LEAGUE_HTTP_CACHE_TTL_SEC", "60")))
except ValueError:
    _CACHE_TTL_SECONDS = 60.0

_session_lock = threading.Lock()
_session: requests.Session | None = None

_request_cache_lock = threading.Lock()
_request_cache: dict[str, tuple[float, Any]] = {}


def _get_session() -> requests.Session:
    """Lazily-created pooled session shared across the public pipeline."""
    global _session
    with _session_lock:
        if _session is None:
            sess = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=_POOL_SIZE,
                pool_maxsize=_POOL_SIZE,
                max_retries=0,
            )
            sess.mount("https://", adapter)
            sess.mount("http://", adapter)
            sess.headers.update({"User-Agent": "brisket-public-league/1.0"})
            _session = sess
    return _session


def reset_session() -> None:
    """Test hook — closes the pooled session so the next call reopens it."""
    global _session
    with _session_lock:
        if _session is not None:
            try:
                _session.close()
            except Exception:  # noqa: BLE001
                pass
        _session = None


def _cache_get(url: str) -> Any | None:
    """Return cached payload for ``url`` if still under TTL, else None."""
    if _CACHE_TTL_SECONDS <= 0:
        return None
    import time as _time

    now = _time.time()
    with _request_cache_lock:
        entry = _request_cache.get(url)
        if entry is None:
            return None
        ts, payload = entry
        if (now - ts) > _CACHE_TTL_SECONDS:
            # Expired; drop so the next miss doesn't keep growing the
            # dict with stale entries.
            _request_cache.pop(url, None)
            return None
        return payload


def _cache_put(url: str, payload: Any) -> None:
    if _CACHE_TTL_SECONDS <= 0 or payload is None:
        # Don't cache failures — we want the next call to retry.
        return
    import time as _time

    with _request_cache_lock:
        _request_cache[url] = (_time.time(), payload)


def reset_request_cache() -> None:
    """Test hook — drop every cached HTTP response."""
    with _request_cache_lock:
        _request_cache.clear()


def _request_json(url: str, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    """GET ``url`` and return parsed JSON, or ``None`` on any failure.

    Cached for ``_CACHE_TTL_SECONDS`` (default 60s).  Failures are
    NOT cached — a transient network error must let the next caller
    retry.  Set ``PUBLIC_LEAGUE_HTTP_CACHE_TTL_SEC=0`` to disable
    the cache (e.g. for tests).
    """
    cached = _cache_get(url)
    if cached is not None:
        return cached
    try:
        resp = _get_session().get(url, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("sleeper_client GET failed for %s: %s", url, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders
        log.warning("sleeper_client GET unexpected error for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        log.warning("sleeper_client GET %s returned status %d", url, resp.status_code)
        return None
    try:
        payload = resp.json()
    except ValueError as exc:
        log.warning("sleeper_client JSON decode failed for %s: %s", url, exc)
        return None
    _cache_put(url, payload)
    return payload


#: Outcome kinds of :func:`request_json_classified`.
FETCH_OK = "ok"
FETCH_NOT_FOUND = "not_found"
FETCH_RATE_LIMITED = "rate_limited"
FETCH_ERROR = "error"


def request_json_classified(url: str, timeout: float = _DEFAULT_TIMEOUT) -> tuple[str, Any]:
    """``(kind, payload)`` for one GET — the variant for paced batch crawls
    that must tell "Sleeper refused us" apart from "this object is gone".

    :func:`_request_json` maps every non-200 to ``None``, so a 429 reads
    exactly like a deleted league; its other callers rely on that and are left
    alone.  Here:

    * ``ok`` — 200 with a non-null JSON body;
    * ``not_found`` — 200 with a JSON ``null`` body (Sleeper's answer for a
      league id that does not exist) or a 404;
    * ``rate_limited`` — HTTP 429;
    * ``error`` — transport failure, any other status, or an undecodable body.

    Shares the response cache with :func:`_request_json` for ``ok`` answers only.
    """
    cached = _cache_get(url)
    if cached is not None:
        return FETCH_OK, cached
    try:
        resp = _get_session().get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — every transport failure is an error
        log.warning("sleeper_client GET failed for %s: %s", url, exc)
        return FETCH_ERROR, None
    if resp.status_code == 429:
        log.warning("sleeper_client GET %s rate limited (429)", url)
        return FETCH_RATE_LIMITED, None
    if resp.status_code == 404:
        return FETCH_NOT_FOUND, None
    if resp.status_code != 200:
        log.warning("sleeper_client GET %s returned status %d", url, resp.status_code)
        return FETCH_ERROR, None
    try:
        payload = resp.json()
    except ValueError as exc:
        log.warning("sleeper_client JSON decode failed for %s: %s", url, exc)
        return FETCH_ERROR, None
    if payload is None:
        return FETCH_NOT_FOUND, None
    _cache_put(url, payload)
    return FETCH_OK, payload


def fetch_nfl_state() -> dict[str, Any] | None:
    """Sleeper's own ``/state/nfl``: the host's answer to "what season and
    week is it right now".

    Preferred over any calendar derivation for anything that must agree
    with the league it is describing — Sleeper numbers its own weeks, and
    a snapshot filed under a week the host disagrees with is filed under
    the wrong week.  ``None`` on any failure, so a caller can refuse
    rather than fall back to a guess.
    """
    data = _request_json(f"{SLEEPER_BASE}/state/nfl")
    return data if isinstance(data, dict) else None


def fetch_league(league_id: str) -> dict[str, Any] | None:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}")
    return data if isinstance(data, dict) else None


def fetch_users(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/users")
    return data if isinstance(data, list) else []


def fetch_rosters(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/rosters")
    return data if isinstance(data, list) else []


def fetch_matchups(league_id: str, week: int) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/matchups/{week}")
    return data if isinstance(data, list) else []


def fetch_transactions(league_id: str, week: int) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}")
    return data if isinstance(data, list) else []


def fetch_drafts(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/drafts")
    return data if isinstance(data, list) else []


def fetch_draft_detail(draft_id: str) -> dict[str, Any] | None:
    data = _request_json(f"{SLEEPER_BASE}/draft/{draft_id}")
    return data if isinstance(data, dict) else None


def fetch_draft_picks(draft_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks")
    return data if isinstance(data, list) else []


def fetch_traded_picks(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/traded_picks")
    return data if isinstance(data, list) else []


def fetch_winners_bracket(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/winners_bracket")
    return data if isinstance(data, list) else []


def fetch_losers_bracket(league_id: str) -> list[dict[str, Any]]:
    data = _request_json(f"{SLEEPER_BASE}/league/{league_id}/losers_bracket")
    return data if isinstance(data, list) else []


# Module-level cache for the (large) NFL players dump.  Fetched lazily
# the first time a section needs player position data and shared across
# every subsequent snapshot build.  ~5 MB from Sleeper — we cache it
# for the life of the process.
_nfl_players_cache: dict[str, Any] | None = None


def fetch_nfl_players() -> dict[str, Any]:
    """Return Sleeper's ``players/nfl`` dump keyed by player_id.

    Graceful fallback: empty dict on any network or parse error so the
    public pipeline can still render without position breakdowns.

    **An empty dict is a FAILURE, and it is not cached.**  Only a
    non-empty dump is memoized, matching ``_request_json``'s own rule
    ("failures are NOT cached").  This used to memoize ``{}`` for the
    life of the process, so one ``ConnectionResetError`` (refresh run
    36220954196) answered every later caller in that run with an empty
    universe too — and the ROS team-strength refresh then scored every
    rostered player at zero.  Callers that need names must treat ``{}``
    as unavailable, never as "the NFL has no players".
    """
    global _nfl_players_cache
    if _nfl_players_cache is not None:
        return _nfl_players_cache
    data = _request_json(f"{SLEEPER_BASE}/players/nfl", timeout=30.0)
    if isinstance(data, dict) and data:
        _nfl_players_cache = data
        return data
    return {}


def reset_nfl_players_cache() -> None:
    """Test hook — clear the cached NFL players dump."""
    global _nfl_players_cache
    _nfl_players_cache = None


def walk_league_chain_status(
    start_league_id: str, max_seasons: int = PUBLIC_MAX_SEASONS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Follow ``previous_league_id`` links to the league's first DYNASTY season.

    Returns ``(chain, coverage)``: league objects ordered current -> oldest,
    and how the walk ended, so a consumer can tell full history from a
    partial one:

    * ``complete`` -- reached Sleeper's terminator (``"0"`` / empty): every
      season of the league is in ``chain``;
    * ``truncated`` -- stopped at ``max_seasons`` while an older season was
      still linked.  Logged as a warning; never silent;
    * ``non_dynasty_predecessor`` -- the next older league is not a dynasty
      league (``settings.type`` != 2), so it is not this dynasty's history
      and is left out;
    * ``unverified`` -- a linked league could not be fetched
      (``predecessor_fetch_failed``), the chain looped (``chain_loop``), or a
      predecessor carries no league type (``predecessor_type_unknown`` --
      unknown is not dynasty, so it fails closed).

    ``coverage`` = ``{"state", "reason", "seasonsWalked", "cap",
    "stoppedAtLeagueId"}``; ``stoppedAtLeagueId`` is the league the walk did
    NOT include (``None`` when it reached the terminator).  The starting
    league is the current season and is included whatever its type; the
    dynasty gate applies to predecessors.  Network failures never raise.
    """
    chain: list[dict[str, Any]] = []

    def _cov(state: str, reason: str | None, stopped: str | None) -> dict[str, Any]:
        return {
            "state": state,
            "reason": reason,
            "seasonsWalked": len(chain),
            "cap": max_seasons,
            "stoppedAtLeagueId": stopped,
        }

    cur = str(start_league_id or "").strip()
    if max_seasons <= 0:
        return chain, _cov(CHAIN_TRUNCATED, "safety_cap", cur or None)
    if cur in _CHAIN_TERMINATORS:
        # No start id at all: nothing was walked, so nothing is proven complete.
        return chain, _cov(CHAIN_UNVERIFIED, "no_start_league", None)
    seen: set[str] = set()
    while cur not in _CHAIN_TERMINATORS:
        if cur in seen:
            log.warning("sleeper_client: previous_league_id chain loops at %s", cur)
            return chain, _cov(CHAIN_UNVERIFIED, "chain_loop", cur)
        if len(chain) >= max_seasons:
            log.warning(
                "sleeper_client: league history TRUNCATED at the %d-season safety cap "
                "(older season %s still linked)",
                max_seasons,
                cur,
            )
            return chain, _cov(CHAIN_TRUNCATED, "safety_cap", cur)
        seen.add(cur)
        league = fetch_league(cur)
        if not league:
            reason = "predecessor_fetch_failed" if chain else "start_fetch_failed"
            return chain, _cov(CHAIN_UNVERIFIED, reason, cur)
        if chain:
            raw_type = (league.get("settings") or {}).get("type")
            try:
                league_type = int(raw_type)
            except (TypeError, ValueError):
                league_type = None
            if league_type is None:
                log.warning("sleeper_client: predecessor league %s has no league type", cur)
                return chain, _cov(CHAIN_UNVERIFIED, "predecessor_type_unknown", cur)
            if league_type != SLEEPER_DYNASTY_TYPE:
                log.warning(
                    "sleeper_client: predecessor league %s is type %s, not dynasty; "
                    "history stops before it",
                    cur,
                    league_type,
                )
                return chain, _cov(CHAIN_NON_DYNASTY, f"league_type_{league_type}", cur)
        chain.append(league)
        nxt = league.get("previous_league_id") or league.get("previous_league") or ""
        cur = str(nxt or "").strip()
    return chain, _cov(CHAIN_COMPLETE, None, None)


def walk_league_chain(
    start_league_id: str, max_seasons: int = PUBLIC_MAX_SEASONS
) -> list[dict[str, Any]]:
    """The chain alone, current -> oldest; see :func:`walk_league_chain_status`
    for how the walk ended (complete / truncated / unverified).

    Graceful fallback: any missing league object or broken link ends the
    walk without raising -- callers must handle the short case.
    """
    return walk_league_chain_status(start_league_id, max_seasons)[0]
