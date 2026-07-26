"""Sleeper trending-adds adapter — live waiver-heat signal.

Fetches ``GET https://api.sleeper.app/v1/players/nfl/trending/add``
(a tiny unauthenticated list of ``{"player_id": str, "count": int}``
rows) and exposes a ``player_id → count`` map for the FAAB
recommender's trending kicker.

Before this adapter existed the recommender read
``latest_contract_data["sleeperTrending"]`` — a key NO producer ever
wrote, so the trending input was permanently "missing" and every
recommendation shipped with a lowered confidence.  This adapter is
the primary source now; the contract key remains as a fallback for
deployments that backfill it out-of-band.

Caching mirrors the ``_PlayerMapCache`` pattern from
``src/news/providers/sleeper.py``: a thread-safe module-level
singleton with a TTL, fetch-outside-the-lock, and stale-on-failure
degradation.  One deliberate difference: a COLD-cache fetch failure
returns ``None`` instead of raising — trending is an optional,
confidence-only signal for the recommender, so an outage must never
break the endpoint (the recommender already treats a missing
trending input as "degrade confidence, keep going").
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger(__name__)

TRENDING_ADD_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"

# 15-minute TTL — same window the Sleeper roster overlay uses
# (``src/api/sleeper_overlay.py::_CACHE_TTL_SEC``), so both live
# Sleeper signals converge on the same freshness ceiling.
TRENDING_TTL_S = 15 * 60

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_S = 5.0


class _TrendingCache:
    """Thread-safe, TTL'd cache for the trending-adds snapshot.

    Mirrors ``_PlayerMapCache`` (src/news/providers/sleeper.py):
    the cached value is returned while fresh, the fetcher runs
    outside the lock, and a warm-cache fetch failure degrades to
    the stale snapshot.  Unlike the player-map cache, a cold-cache
    failure returns ``None`` rather than raising — see module
    docstring.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at: float = 0.0
        self._snapshot: dict[str, Any] | None = None

    def get(
        self,
        *,
        fetcher,
        ttl_s: float = TRENDING_TTL_S,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            if not force_refresh and self._snapshot is not None and now < self._expires_at:
                return self._snapshot
            stale = self._snapshot
        # Fetch outside the lock so concurrent callers don't pile up
        # behind a single slow request.  Worst case two fetches race
        # on a cold start — benign, the second overwrites the first.
        try:
            fresh = fetcher()
        except Exception as exc:  # noqa: BLE001 — optional signal, never break callers
            log.warning("sleeper trending fetch failed: %s", exc)
            return stale
        if not isinstance(fresh, dict):
            return stale
        with self._lock:
            self._snapshot = fresh
            self._expires_at = time.time() + ttl_s
        return fresh

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None
            self._expires_at = 0.0


# Module-level singleton — the trending board is global (not
# per-league), so every caller shares one snapshot.
_CACHE = _TrendingCache()


def _reset_cache_for_tests() -> None:
    """Test hook — purge the module-level trending cache."""
    _CACHE.invalidate()


def _fetch_snapshot(
    *,
    lookback_hours: int,
    limit: int,
    session: requests.Session | None,
) -> dict[str, Any]:
    """One live round-trip to the trending-adds endpoint.

    Returns ``{"fetchedAt": iso-str, "lookbackHours": int,
    "counts": {player_id: count}}``.  Raises on transport errors —
    the cache layer decides how to degrade.
    """
    http = session or requests
    resp = http.get(
        TRENDING_ADD_URL,
        params={"lookback_hours": int(lookback_hours), "limit": int(limit)},
        timeout=_HTTP_TIMEOUT_S,
        headers={"User-Agent": "brisket-faab-trending/1.0"},
    )
    resp.raise_for_status()
    data = resp.json()
    counts: dict[str, int] = {}
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            pid = str(row.get("player_id") or "").strip()
            try:
                count = int(row.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if pid and count > 0:
                counts[pid] = count
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "lookbackHours": int(lookback_hours),
        "counts": counts,
    }


def get_trending_adds(
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    limit: int = DEFAULT_LIMIT,
    session: requests.Session | None = None,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Return the cached trending-adds snapshot, fetching if stale.

    ``None`` means no snapshot is available at all (cold cache and
    the live fetch failed) — callers degrade to their fallback
    (the contract's ``sleeperTrending`` key, then "missing input").
    """
    return _CACHE.get(
        fetcher=lambda: _fetch_snapshot(
            lookback_hours=lookback_hours,
            limit=limit,
            session=session,
        ),
        force_refresh=force_refresh,
    )


def warm(*, session: requests.Session | None = None) -> bool:
    """Force-refresh the cache (background warm hook).

    Returns True when a snapshot is available afterwards (fresh or
    stale).  Never raises — this runs on the server's post-scrape
    overlay-warm daemon thread.
    """
    try:
        return get_trending_adds(session=session, force_refresh=True) is not None
    except Exception as exc:  # noqa: BLE001 — warm must never propagate
        log.warning("sleeper trending warm failed: %s", exc)
        return False
