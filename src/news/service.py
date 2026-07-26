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
   don't hammer upstream feeds.  The cache stores the UNFILTERED
   aggregate — request-level filters never participate in the
   cache key (see ``aggregate``), so a public caller can't bust
   the warm cache by varying query params.
5. Optionally filter by a team-roster name list (query param on
   the route) so the response only contains items that mention
   at least one of those names.  Applied per request on the way
   out of the cache, never baked into the cached payload.

No network I/O happens in this module directly — everything runs
through the injected providers.  That keeps the cache + dedupe
logic testable without stubbing HTTP.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from .base import NewsItem, NewsProvider
from .digest import build_player_digests
from .providers import available_provider_names, build_provider

log = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_S = 180  # 3 minutes — rate-limit-safe for all providers
# Hard freshness cutoff: every surface (news tab, popups, chips)
# must only show news from the last week, so the drop happens HERE
# at aggregation — not per consumer.  Items whose timestamp cannot
# be parsed are dropped too: they can't prove freshness.
MAX_ITEM_AGE_DAYS = 7
# All-failed aggregates get a much shorter cache life: caching an
# outage for the full TTL would keep the client's 15/30/60s retries
# hitting the stale failure for minutes after upstreams recover.
# Mirrors the client's FAILURE_TTL_MS rationale
# (frontend/components/useNews.js).  Partial successes keep the
# normal TTL.
FAILURE_CACHE_TTL_S = 15.0
# How long a follower thread waits on an in-flight refresh before
# re-checking the world.  Generous enough to cover a full cold
# sequential provider run (~11 registered providers × 5s soft cap);
# the wait sits in a loop, so a timeout just re-evaluates rather
# than stampeding.
_REFRESH_WAIT_TIMEOUT_S = 60.0
DEFAULT_LIMIT_PER_PROVIDER = 25
# Matches the route's ``?limit=`` hard ceiling so the route's limit
# contract isn't silently capped by the service before reaching the
# slicing step (Codex P2).
DEFAULT_TOTAL_LIMIT = 100


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
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "providersUsed": list(self.providers_used),
            "providerRuns": [r.to_dict() for r in self.provider_runs],
            "generatedAt": self.generated_at,
            "cacheHit": self.cache_hit,
            "count": len(self.items),
            # One combined entry per player with multiple recent
            # stories (see src/news/digest.py — including the LLM
            # synthesis seam).  Computed from the already-filtered
            # item list so every surface inherits the age cutoff.
            "playerDigests": build_player_digests(self.items),
        }


def _drop_stale_items(
    items: Sequence[NewsItem],
    *,
    now_epoch: float,
    max_age_days: int = MAX_ITEM_AGE_DAYS,
) -> List[NewsItem]:
    """Drop every item older than the hard freshness cutoff.

    ``now_epoch`` comes from the service clock so tests with a fake
    clock stay deterministic.  Unparseable timestamps are dropped —
    an item that can't prove it is under a week old doesn't ship.
    """
    cutoff = now_epoch - max_age_days * 86400.0
    out: List[NewsItem] = []
    for it in items:
        try:
            ts = datetime.fromisoformat(str(it.ts).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            out.append(it)
    return out


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


def _enrich_player_mentions(
    items: Sequence[NewsItem],
    player_meta: Optional[Mapping[str, Mapping[str, Any]]],
) -> List[NewsItem]:
    """Stamp position/team from the live contract onto mentions.

    ``player_meta`` maps EXACT contract display names to
    ``{"position": ..., "team": ...}``.  Mentions are tagged from
    those same display names (every provider matches against the
    known-names list the route derives from the contract), so an
    exact-name lookup attributes each mention to the specific row
    that produced it — including name-collision pairs whose display
    strings differ ("CJ Allen" the LB vs "C.J. Allen" the WR).

    One central pass covers every provider (RSS, Sleeper, PFK)
    without touching their taggers.  Mentions that already carry
    position/team (a provider whose upstream knows) are left alone;
    unknown names and null metadata stay name-only.  ``team`` is
    sparsely populated in the contract until the next scrape cycle —
    stamp what's available, null otherwise.
    """
    if not player_meta:
        return list(items)
    out: List[NewsItem] = []
    for item in items:
        if not item.players:
            out.append(item)
            continue
        changed = False
        mentions: List[Any] = []
        for m in item.players:
            # Never stamp an ambiguous mention — the tagger couldn't
            # tell which player the text meant, and stamping either
            # candidate's identity would make the guess look
            # authoritative to every downstream disambiguation guard.
            if m.ambiguous or m.position or m.team:
                mentions.append(m)
                continue
            meta = player_meta.get(m.name)
            if not isinstance(meta, Mapping):
                mentions.append(m)
                continue
            position = meta.get("position") or None
            team = meta.get("team") or None
            if position or team:
                mentions.append(replace(m, position=position, team=team))
                changed = True
            else:
                mentions.append(m)
        out.append(replace(item, players=mentions) if changed else item)
    return out


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
        # Cache keyed by the known-names universe ONLY (the sorted
        # ``player_names`` tuple the route derives from the live
        # contract).  Request-level filters (``team_names``) are
        # deliberately NOT part of the key — each entry stores the
        # unfiltered aggregate and filters are projected per request.
        # Values are ``(expires_at, aggregate)`` so all-failed
        # entries can carry a shorter life than successes.
        self._cache: dict[tuple, tuple[float, AggregatedNews]] = {}
        # Per-key single-flight: while one thread refreshes a cold
        # key, concurrent callers wait on its Event instead of each
        # launching their own sequential provider run.
        self._refreshing: dict[tuple, threading.Event] = {}

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
        player_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> AggregatedNews:
        """Aggregate all providers.

        ``player_meta`` (optional) maps exact contract display names
        to ``{"position", "team"}`` for mention enrichment — it is
        derived from the same live contract as ``player_names``, so
        it deliberately does NOT participate in the cache key.
        """
        known_names = sorted({n for n in (player_names or []) if n})
        team_filter = tuple(sorted({n for n in (team_names or []) if n}))
        # The cache key deliberately EXCLUDES request-level filters.
        # ``/api/news`` is public and the repeatable ``?team=`` param
        # is caller-controlled: keying the cache on it (the previous
        # behaviour) let any stranger bypass the warm cache — and
        # re-run every sequential upstream provider — just by varying
        # the param.  Instead the unfiltered aggregate is cached once
        # per known-names universe and filters are projected onto a
        # copy on the way out.
        cache_key = tuple(known_names)

        # Cold-cache single-flight: exactly one thread (the "leader")
        # refreshes a given key; concurrent callers wait on the
        # leader's Event and then re-check the cache instead of each
        # stampeding the sequential upstream providers.
        while True:
            now = self._clock()
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached and now < cached[0]:
                    return self._project(cached[1], team_filter, cache_hit=True)
                refresh = self._refreshing.get(cache_key)
                if refresh is None:
                    refresh = threading.Event()
                    self._refreshing[cache_key] = refresh
                    break  # this thread is the leader
            # Follower: wait for the in-flight refresh, then loop to
            # re-check.  The timeout only guards against a wedged
            # leader — on timeout the loop re-evaluates and this
            # thread can take over leadership if the entry is gone.
            refresh.wait(timeout=_REFRESH_WAIT_TIMEOUT_S)

        try:
            items, runs = self._fetch_all(known_names)
            # Hard 7-day freshness cutoff — applied at aggregation so
            # every downstream surface inherits it.  The cache TTL
            # (≤180s) is far below the cutoff granularity, so cached
            # entries can't meaningfully age past it between misses.
            items = _drop_stale_items(items, now_epoch=self._clock())
            items = _dedupe(items)
            items = _sort_items(items)
            # Stamp position/team identity discriminators onto
            # mentions before caching, so every consumer of the
            # cached aggregate (route + terminal) sees enriched
            # payloads regardless of which caller warmed the cache.
            items = _enrich_player_mentions(items, player_meta)

            providers_used = [r.name for r in runs if r.ok and r.count > 0]
            base = AggregatedNews(
                items=items,
                providers_used=providers_used,
                provider_runs=runs,
                generated_at=datetime.now(timezone.utc).isoformat(),
                cache_hit=False,
            )

            # All-failed aggregates get the short failure TTL so
            # client retries reach recovered upstreams promptly;
            # anything with at least one healthy provider (including
            # a legit empty feed from zero configured providers)
            # keeps the normal TTL.
            all_failed = bool(runs) and not any(r.ok for r in runs)
            ttl = min(self._ttl, FAILURE_CACHE_TTL_S) if all_failed else self._ttl

            now = self._clock()
            with self._lock:
                self._cache[cache_key] = (now + ttl, base)
                # Evict expired entries on every miss (Codex P2).
                # With filters out of the key the entry count is
                # bounded by the number of distinct known-names
                # universes (one in production), but the sweep stays
                # as cheap insurance.  Doing it at write time (not on
                # every read) keeps the hot path lock-free-ish and
                # bounds the work by miss rate, which is itself
                # rate-limited by the TTL.
                expired = [k for k, (exp, _v) in self._cache.items() if now >= exp]
                for k in expired:
                    self._cache.pop(k, None)
        finally:
            # Release followers even if the refresh itself raised —
            # they loop back, see no in-flight entry, and can take
            # over leadership.
            with self._lock:
                self._refreshing.pop(cache_key, None)
            refresh.set()

        return self._project(base, team_filter, cache_hit=False)

    def _project(
        self,
        base: AggregatedNews,
        team_filter: tuple[str, ...],
        *,
        cache_hit: bool,
    ) -> AggregatedNews:
        """Apply request-level filters + the total cap to a cached
        aggregate, returning a shallow copy so the cached entry is
        never mutated.  The cap runs AFTER the filter (matching the
        pre-cache-restructure order) so a narrow team filter can
        still surface items beyond the unfiltered top slice."""
        items = list(base.items)
        if team_filter:
            items = _filter_by_team_names(items, team_filter)
        return AggregatedNews(
            items=items[: self._total_limit],
            providers_used=base.providers_used,
            provider_runs=base.provider_runs,
            generated_at=base.generated_at,
            cache_hit=cache_hit,
        )

    # ── provider dispatch ───────────────────────────────────────
    def _fetch_all(self, known_names: list[str]) -> tuple[List[NewsItem], List[ProviderRunResult]]:
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
                log.warning("news provider %s raised: %s", provider.name, exc)
                run.ok = False
                run.error = f"{type(exc).__name__}: {exc}"
            finally:
                run.elapsed_ms = int((time.monotonic() - started) * 1000)
            runs.append(run)
        return all_items, runs


# ── factory helpers ─────────────────────────────────────────────
# Enabled-by-default providers.  All public, no licence required.
# Rotowire stays registered but OFF until its paid API is wired.
# ``pfk`` is the Play For Keeps articles provider — one polite
# sitemap request per cache refresh, isolated like every other
# provider.
_DEFAULT_ENABLED = ("sleeper", "espn", "espn_player", "fantasypros", "cbs", "pfk")


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
    "FAILURE_CACHE_TTL_S",
    "MAX_ITEM_AGE_DAYS",
    "NewsService",
    "ProviderRunResult",
    "build_default_service",
]
