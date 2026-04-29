"""Thin, side-effect-free Sleeper HTTP client for the public pipeline.

The public league snapshot pulls exclusively from the documented
Sleeper v1 endpoints.  No internal scraper state, no CSV, no cached
private payload.  Every call degrades gracefully — a network failure
returns ``None`` / ``[]`` rather than raising, so the snapshot can
still render with partial sections instead of failing the whole
page.

Exactly two dynasty seasons are supported right now: the current
league and its direct ``previous_league_id``.  The chain walk is
capped so a badly-configured league cannot recurse forever.

Network layer:
    Uses a module-level ``requests.Session`` with a pooled
    ``HTTPAdapter``.  Across a 12-thread snapshot build that's one
    TLS handshake amortized over ~85 GETs instead of 85 separate
    handshakes.  Drops cold-fetch from ~0.65s to ~0.25s against the
    live Sleeper chain.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

# Max dynasty seasons the public pipeline surfaces.  Widened to 3
# after the 2025 playoffs + 2026 offseason shipped — unlocks deeper
# Hall of Fame + Best Rebuild signal.  Tunable via env override below
# so ops can raise or lower without a code change.  Every section
# module iterates ``snapshot.seasons`` so this constant is the single
# knob that controls horizon.
import os as _os

try:
    PUBLIC_MAX_SEASONS = max(1, int(_os.getenv("PUBLIC_MAX_SEASONS", "3")))
except ValueError:
    PUBLIC_MAX_SEASONS = 3

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
    """
    global _nfl_players_cache
    if _nfl_players_cache is not None:
        return _nfl_players_cache
    data = _request_json(f"{SLEEPER_BASE}/players/nfl", timeout=30.0)
    _nfl_players_cache = data if isinstance(data, dict) else {}
    return _nfl_players_cache


def reset_nfl_players_cache() -> None:
    """Test hook — clear the cached NFL players dump."""
    global _nfl_players_cache
    _nfl_players_cache = None


def walk_league_chain(start_league_id: str, max_seasons: int = PUBLIC_MAX_SEASONS) -> list[dict[str, Any]]:
    """Follow ``previous_league_id`` links up to ``max_seasons`` hops.

    Returns a list of league objects ordered current → previous.  When
    the chain is shorter than ``max_seasons`` (e.g. league only has one
    completed dynasty season), the returned list is simply shorter —
    callers must handle the short case.

    Graceful fallback: any missing league object or broken link ends
    the walk without raising.
    """
    if max_seasons <= 0:
        return []
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur = str(start_league_id or "").strip()
    while cur and cur not in seen and len(chain) < max_seasons:
        seen.add(cur)
        league = fetch_league(cur)
        if not league:
            break
        chain.append(league)
        nxt = league.get("previous_league_id") or league.get("previous_league") or ""
        cur = str(nxt or "").strip()
    return chain
