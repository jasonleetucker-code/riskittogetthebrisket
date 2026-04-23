"""News aggregation service.

The service layer is the single entry point for the ``/api/news``
route.  Responsibilities:

1. Own the enabled-providers list (loaded once from config at
   build time, or passed in explicitly for testing).
2. Dispatch each provider with per-provider isolation — one
   provider raising or timing out does NOT poison the response.
3. Dedupe items by ``id`` across providers (stable ids make this
   cheap).
4. Cache the aggregated response for a short TTL so repeated
   ``/api/news`` hits from the landing-page cache-warm cycle
   don't hammer upstream feeds.
5. Optionally filter by a team-roster name list (query param on
   the route) so the response only contains items that mention
   at least one of those names.

No network I/O happens in this module directly — everything runs
through the injected providers.  That keeps the cache + dedupe
logic testable without stubbing HTTP.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Sequence

from .base import NewsItem, NewsProvider
from .providers import available_provider_names, build_provider

log = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_S = 180  # 3 minutes — rate-limit-safe for all providers
DEFAULT_LIMIT_PER_PROVIDER = 25
DEFAULT_TOTAL_LIMIT = 60


@dataclass
class ProviderRunResult:
    """Per-provider diagnostics attached to the aggregated response."""

    name: str
    label: str
    count: int = 0
    ok: bool = True
    error: Optional[str] = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        out = {
            "name": self.name,
            "label": self.label,
            "count": self.count,
            "ok": self.ok,
            "elapsedMs": self.elapsed_ms,
        }
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class AggregatedNews:
    """Service-layer response object — the route serializes this."""

    items: List[NewsItem]
    providers_used: List[str]
    provider_runs: List[ProviderRunResult] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "providersUsed": list(self.providers_used),
            "providerRuns": [r.to_dict() for r in self.provider_runs],
            "generatedAt": self.generated_at,
            "cacheHit": self.cache_hit,
            "count": len(self.items),
        }


def _dedupe(items: Sequence[NewsItem]) -> List[NewsItem]:
    seen: set[str] = set()
    out: List[NewsItem] = []
    for it in items:
        if it.id in seen:
            continue
        seen.add(it.id)
        out.append(it)
    return out


def _sort_items(items: List[NewsItem]) -> List[NewsItem]:
    """Sort by (severity rank desc, timestamp desc).

    Alerts float to the top regardless of age, then watch, then
    info — matches how the frontend ticker prioritizes.
    """
    severity_rank = {"alert": 3, "watch": 2, "info": 1}

    def key(it: NewsItem) -> tuple[int, float]:
        r = severity_rank.get(it.severity, 0)
        try:
            ts = datetime.fromisoformat(it.ts.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            ts = 0.0
        return (r, ts)

    return sorted(items, key=key, reverse=True)


def _filter_by_team_names(
    items: Sequence[NewsItem],
    team_names: Iterable[str],
) -> List[NewsItem]:
    wanted = {n.strip().lower() for n in team_names if n and n.strip()}
    if not wanted:
        return list(items)
    out: List[NewsItem] = []
    for it in items:
        names = {p.name.strip().lower() for p in it.players if p.name}
        if names & wanted:
            out.append(it)
    return out


class NewsService:
    """Aggregator with TTL cache and per-provider fault isolation."""

    def __init__(
        self,
        providers: Sequence[NewsProvider],
        *,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        limit_per_provider: int = DEFAULT_LIMIT_PER_PROVIDER,
        total_limit: int = DEFAULT_TOTAL_LIMIT,
        clock=time.time,
    ) -> None:
        self._providers = list(providers)
        self._ttl = max(0.0, float(cache_ttl_s))
        self._limit_per_provider = max(1, int(limit_per_provider))
        self._total_limit = max(1, int(total_limit))
        self._clock = clock
        self._lock = threading.Lock()
        # Single-entry cache keyed by the (frozenset of) player
        # names the caller passed in — the aggregated payload is
        # different per roster when a team filter is in play.
        self._cache: dict[tuple, tuple[float, AggregatedNews]] = {}

    @property
    def provider_names(self) -> List[str]:
        return [p.name for p in self._providers]

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    # ── main entry point ────────────────────────────────────────
    def aggregate(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        team_names: Optional[Iterable[str]] = None,
    ) -> AggregatedNews:
        known_names = sorted({n for n in (player_names or []) if n})
        team_filter = tuple(sorted({n for n in (team_names or []) if n}))
        cache_key = (tuple(known_names), team_filter)

        now = self._clock()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < self._ttl:
                # Return a shallow copy with the cache flag flipped
                # so the caller can tell live vs cached apart.
                payload = cached[1]
                return AggregatedNews(
                    items=payload.items,
                    providers_used=payload.providers_used,
                    provider_runs=payload.provider_runs,
                    generated_at=payload.generated_at,
                    cache_hit=True,
                )

        items, runs = self._fetch_all(known_names)
        items = _dedupe(items)
        items = _sort_items(items)
        if team_filter:
            items = _filter_by_team_names(items, team_filter)
        items = items[: self._total_limit]

        providers_used = [r.name for r in runs if r.ok and r.count > 0]
        result = AggregatedNews(
            items=items,
            providers_used=providers_used,
            provider_runs=runs,
            generated_at=datetime.now(timezone.utc).isoformat(),
            cache_hit=False,
        )

        with self._lock:
            self._cache[cache_key] = (now, result)

        return result

    # ── provider dispatch ───────────────────────────────────────
    def _fetch_all(
        self, known_names: list[str]
    ) -> tuple[List[NewsItem], List[ProviderRunResult]]:
        """Run every enabled provider and collect their items.

        Each provider is fully isolated — any exception is logged
        and converted into a ``ProviderRunResult(ok=False)`` so
        the aggregate response can still succeed on the survivors.

        Run order follows registration order (priority).  We do
        this sequentially rather than in a thread pool because
        the worst-case total latency is small (2 providers × 5s
        timeout = 10s cap, but realistic steady state is
        sub-second) and keeping it sequential avoids another
        dependency on a shared thread pool.
        """
        all_items: List[NewsItem] = []
        runs: List[ProviderRunResult] = []
        for provider in self._providers:
            run = ProviderRunResult(name=provider.name, label=provider.label)
            started = time.monotonic()
            try:
                items = provider.fetch(
                    player_names=known_names,
                    limit=self._limit_per_provider,
                )
                if not isinstance(items, list):
                    items = list(items or [])
                run.count = len(items)
                all_items.extend(items)
            except Exception as exc:  # defensive — providers
                # shouldn't raise, but if they do we isolate the
                # failure here rather than 500-ing the route.
                log.warning(
                    "news provider %s raised: %s", provider.name, exc
                )
                run.ok = False
                run.error = f"{type(exc).__name__}: {exc}"
            finally:
                run.elapsed_ms = int((time.monotonic() - started) * 1000)
            runs.append(run)
        return all_items, runs


# ── factory helpers ─────────────────────────────────────────────
# Enabled-by-default providers.  All public, no licence required.
# Rotowire stays registered but OFF until its paid API is wired.
_DEFAULT_ENABLED = ("sleeper", "espn", "fantasypros", "cbs")


def build_default_service(
    *,
    enabled: Optional[Sequence[str]] = None,
    cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
    provider_config: Optional[dict[str, dict[str, Any]]] = None,
) -> NewsService:
    """Construct a ``NewsService`` with the production provider set.

    ``enabled`` defaults to Sleeper + ESPN.  Rotowire stays
    registered (``available_provider_names`` includes it) but is
    OFF until explicitly enabled and licensed.

    ``provider_config`` lets callers pass per-provider kwargs,
    e.g. ``{"sleeper": {"lookback_hours": 48}}``.
    """
    if enabled is None:
        enabled = _DEFAULT_ENABLED
    cfg = provider_config or {}
    known = set(available_provider_names())
    instances: List[NewsProvider] = []
    for name in enabled:
        key = name.lower()
        if key not in known:
            log.warning("news provider %r not registered — skipping", name)
            continue
        try:
            instances.append(build_provider(key, **cfg.get(key, {})))
        except Exception as exc:
            log.warning("news provider %r failed to build: %s", name, exc)
    return NewsService(instances, cache_ttl_s=cache_ttl_s)


__all__ = [
    "AggregatedNews",
    "DEFAULT_CACHE_TTL_S",
    "DEFAULT_LIMIT_PER_PROVIDER",
    "DEFAULT_TOTAL_LIMIT",
    "NewsService",
    "ProviderRunResult",
    "build_default_service",
]
