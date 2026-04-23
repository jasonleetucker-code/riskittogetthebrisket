"""Sleeper trending-players provider.

Sleeper exposes an unauthenticated, rate-limit-safe endpoint that
lists the most-added / most-dropped players across the platform
over a lookback window:

    GET https://api.sleeper.app/v1/players/nfl/trending/add?limit=25&lookback_hours=24
    GET https://api.sleeper.app/v1/players/nfl/trending/drop?limit=25&lookback_hours=24

Responses are tiny — a list of ``{"player_id": str, "count": int}``
rows — so we can poll this every few minutes without burning the
Sleeper rate budget.  The player-id → full name mapping comes from
``GET /v1/players/nfl`` which is ~5 MB; Sleeper explicitly asks
callers to fetch it "once per day max" in their docs, so we cache
it with a 24h TTL.

Trending data maps to our news vocabulary as:

* ``kind = "trending"``
* ``severity = "watch"`` for adds, ``"info"`` for drops
* ``impact = "positive"`` for adds, ``"negative"`` for drops
* ``tags = ["trending", "add"|"drop"]``
* ``confidence`` = log-scaled share of top-trending count

No headline lives upstream, so we synthesize one:
    "Jayden Reed added in 18,432 leagues (last 24h)"
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

import requests

from ..base import NewsItem, NewsProvider, PlayerMention, stable_id, to_iso_utc

log = logging.getLogger(__name__)

SLEEPER_API_ROOT = "https://api.sleeper.app/v1"

# Sleeper's docs: "do not call this endpoint more than once per day".
# We cache the full player map for 24h.  24h × 3600 s = 86400.
_PLAYER_MAP_TTL_S = 86_400
_TRENDING_PATH_ADD = "/players/nfl/trending/add"
_TRENDING_PATH_DROP = "/players/nfl/trending/drop"
_PLAYERS_PATH = "/players/nfl"


class _PlayerMapCache:
    """Thread-safe, TTL'd cache for the Sleeper player-id → name map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at: float = 0.0
        self._map: dict[str, dict[str, Any]] = {}

    def get(
        self,
        *,
        fetcher,
        ttl_s: float = _PLAYER_MAP_TTL_S,
    ) -> dict[str, dict[str, Any]]:
        now = time.time()
        with self._lock:
            if self._map and now < self._expires_at:
                return self._map
        # Fetch outside the lock so concurrent callers don't pile
        # up on a single slow request.  Worst case we issue two
        # fetches on a cold start — benign, the second one just
        # overwrites the first.
        try:
            fresh = fetcher()
        except Exception as exc:
            log.warning("sleeper player-map fetch failed: %s", exc)
            # Return whatever we have (possibly stale, possibly
            # empty) rather than erroring out — trending data is
            # still useful with opaque player_ids.
            return self._map
        if isinstance(fresh, dict) and fresh:
            with self._lock:
                self._map = fresh
                self._expires_at = now + ttl_s
        return self._map

    def invalidate(self) -> None:
        with self._lock:
            self._map = {}
            self._expires_at = 0.0


# Module-level singleton — the player map is identical across every
# SleeperTrendingProvider instance, and it's big (5 MB) so we do not
# want one copy per instance.
_PLAYER_MAP = _PlayerMapCache()


def _reset_player_map_for_tests() -> None:
    """Test hook — purge the module-level player-map cache."""
    _PLAYER_MAP.invalidate()


def _display_name(entry: dict[str, Any]) -> Optional[str]:
    full = entry.get("full_name")
    if isinstance(full, str) and full.strip():
        return full.strip()
    first = (entry.get("first_name") or "").strip()
    last = (entry.get("last_name") or "").strip()
    combined = f"{first} {last}".strip()
    return combined or None


class SleeperTrendingProvider(NewsProvider):
    """Provider backed by Sleeper's trending-adds / trending-drops feeds."""

    name = "sleeper"
    label = "Sleeper"
    timeout_s = 5.0

    def __init__(
        self,
        *,
        lookback_hours: int = 24,
        limit_per_feed: int = 20,
        session: Optional[requests.Session] = None,
        api_root: str = SLEEPER_API_ROOT,
    ) -> None:
        super().__init__(
            lookback_hours=lookback_hours,
            limit_per_feed=limit_per_feed,
            api_root=api_root,
        )
        self._session = session or requests.Session()
        self._api_root = api_root.rstrip("/")
        self._lookback = max(1, int(lookback_hours))
        self._limit = max(1, int(limit_per_feed))

    # ── HTTP helpers ────────────────────────────────────────────
    def _get_json(self, path: str) -> Any:
        url = f"{self._api_root}{path}"
        resp = self._session.get(
            url,
            timeout=self.timeout_s,
            headers={"User-Agent": "brisket-news-sleeper/1.0"},
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_player_map(self) -> dict[str, dict[str, Any]]:
        return _PLAYER_MAP.get(fetcher=lambda: self._get_json(_PLAYERS_PATH))

    def _fetch_trending_safe(
        self, path: str
    ) -> tuple[bool, List[dict[str, Any]]]:
        """Fetch one trending endpoint, tolerating a single-endpoint outage.

        Returns ``(ok, rows)``.  ``ok=False`` means the upstream
        call failed — the caller uses that to decide whether
        total-failure propagation is warranted (both endpoints
        down) versus a partial-signal return (only one endpoint
        down, still useful).
        """
        params = f"?lookback_hours={self._lookback}&limit={self._limit}"
        try:
            data = self._get_json(f"{path}{params}")
        except Exception as exc:
            log.warning("sleeper trending fetch (%s) failed: %s", path, exc)
            return False, []
        if not isinstance(data, list):
            return True, []
        return True, [row for row in data if isinstance(row, dict)]

    # ── normalization ───────────────────────────────────────────
    def _row_to_item(
        self,
        row: dict[str, Any],
        *,
        direction: str,
        player_map: dict[str, dict[str, Any]],
        top_count: int,
        now: datetime,
    ) -> Optional[NewsItem]:
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            return None
        count = int(row.get("count") or 0)
        if count <= 0:
            return None

        entry = player_map.get(player_id) or {}
        name = _display_name(entry)
        if not name:
            return None

        position = (entry.get("position") or "").strip() or None
        team = (entry.get("team") or "").strip() or None

        impact = "positive" if direction == "add" else "negative"
        severity = "watch" if direction == "add" else "info"
        verb = "added in" if direction == "add" else "dropped in"
        headline = f"{name} {verb} {count:,} leagues (last {self._lookback}h)"
        tail_bits: list[str] = []
        if position:
            tail_bits.append(position)
        if team:
            tail_bits.append(team)
        suffix = f" ({'/'.join(tail_bits)})" if tail_bits else ""
        body = (
            f"Sleeper trending {direction}s — roster churn signal{suffix}. "
            f"Top {direction} leader this window: {top_count:,} adds."
            if direction == "add"
            else (
                f"Sleeper trending {direction}s — players owners are moving off{suffix}. "
                f"Top {direction} leader this window: {top_count:,} drops."
            )
        )

        # Confidence = share of the top trending count this window.
        # Log-scaled so the #1 item is ~1.0 and the tail still gets
        # a non-trivial score (avoids a cliff between rank 1 and 2).
        if top_count > 0:
            share = max(0.0, min(1.0, count / top_count))
            confidence = round(math.log1p(share * (math.e - 1)), 3)
        else:
            confidence = None

        # Bucket the timestamp to an hour so refetches within the
        # same window return stable ids — the frontend's cache +
        # dedupe logic keys off ``id``.
        bucket = now.replace(minute=0, second=0, microsecond=0)
        ident = stable_id(self.name, f"{direction}:{player_id}:{bucket.isoformat()}")

        return NewsItem(
            id=ident,
            ts=to_iso_utc(now),
            provider=self.name,
            provider_label=self.label,
            severity=severity,
            kind="trending",
            headline=headline,
            body=body,
            players=[PlayerMention(name=name, impact=impact)],
            url=f"https://sleeper.com/players/{player_id}",
            tags=["trending", direction],
            confidence=confidence,
        )

    # ── public entry point ──────────────────────────────────────
    def fetch(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> List[NewsItem]:
        adds_ok, adds = self._fetch_trending_safe(_TRENDING_PATH_ADD)
        drops_ok, drops = self._fetch_trending_safe(_TRENDING_PATH_DROP)
        # Both endpoints down → propagate so the service marks this
        # provider ``ok=False`` and the all-providers-failed check
        # can trigger 503 / DEMO fallback.  Partial failure (one
        # endpoint OK) stays silent — we still have usable signal.
        if not adds_ok and not drops_ok:
            raise RuntimeError("sleeper trending endpoints unavailable")
        if not adds and not drops:
            return []

        try:
            player_map = self._fetch_player_map()
        except Exception as exc:
            log.warning("sleeper player map fetch failed: %s", exc)
            player_map = {}

        now = datetime.now(timezone.utc)
        top_add = adds[0]["count"] if adds and adds[0].get("count") else 0
        top_drop = drops[0]["count"] if drops and drops[0].get("count") else 0

        out: List[NewsItem] = []
        for row in adds:
            item = self._row_to_item(
                row,
                direction="add",
                player_map=player_map,
                top_count=int(top_add or 0),
                now=now,
            )
            if item is not None:
                out.append(item)
        for row in drops:
            item = self._row_to_item(
                row,
                direction="drop",
                player_map=player_map,
                top_count=int(top_drop or 0),
                now=now,
            )
            if item is not None:
                out.append(item)

        # Sort by count-derived confidence (highest first), then
        # truncate to ``limit`` so a caller asking for 50 doesn't
        # get 40 adds + 40 drops back.
        out.sort(
            key=lambda it: (it.confidence or 0.0, it.severity == "watch"),
            reverse=True,
        )
        return out[: max(1, int(limit))]


__all__ = ["SleeperTrendingProvider"]
