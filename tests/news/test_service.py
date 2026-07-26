"""Service-layer tests for the news aggregator.

Verifies:
* per-provider fault isolation — a raising provider does not poison
  the response
* TTL caching — second call within TTL is a cache hit
* team-name filter drops items with no matching player
* ``providers_used`` tracks providers that actually produced items
* priority ordering — Sleeper items appear ahead of ESPN in the
  aggregator before the severity/time sort re-orders them
"""

from __future__ import annotations

import threading
import time

from src.news.base import NewsItem, NewsProvider, PlayerMention
from src.news.service import FAILURE_CACHE_TTL_S, NewsService


class _StaticProvider(NewsProvider):
    name = "static"
    label = "Static"

    def __init__(self, *, items=None, error=None, provider_name=None, provider_label=None):
        super().__init__()
        self._items = list(items or [])
        self._error = error
        self.fetch_calls = 0
        if provider_name:
            self.name = provider_name
        if provider_label:
            self.label = provider_label

    def fetch(self, *, player_names=None, limit=50):
        self.fetch_calls += 1
        if self._error is not None:
            raise self._error
        return self._items


def _item(id_, provider="static", severity="info", ts="2026-04-23T10:00:00+00:00", players=None):
    return NewsItem(
        id=id_,
        ts=ts,
        provider=provider,
        provider_label=provider.title(),
        severity=severity,
        kind="news",
        headline=f"headline {id_}",
        body="",
        players=players or [],
    )


def test_fault_isolation_one_provider_failing():
    good = _StaticProvider(
        items=[_item("a-1"), _item("a-2")],
        provider_name="good",
        provider_label="Good",
    )
    bad = _StaticProvider(
        error=RuntimeError("boom"),
        provider_name="bad",
        provider_label="Bad",
    )
    svc = NewsService([good, bad], cache_ttl_s=0)
    out = svc.aggregate()
    assert len(out.items) == 2
    assert out.providers_used == ["good"]
    runs_by_name = {r.name: r for r in out.provider_runs}
    assert runs_by_name["good"].ok is True
    assert runs_by_name["bad"].ok is False
    assert "RuntimeError" in runs_by_name["bad"].error


def test_all_providers_failing_returns_empty_with_runs():
    a = _StaticProvider(error=RuntimeError("x"), provider_name="a", provider_label="A")
    b = _StaticProvider(error=RuntimeError("y"), provider_name="b", provider_label="B")
    svc = NewsService([a, b], cache_ttl_s=0)
    out = svc.aggregate()
    assert out.items == []
    assert out.providers_used == []
    assert all(not r.ok for r in out.provider_runs)


def test_ttl_cache_hit():
    # Use a controllable clock so we're not racing wall time.
    clock = {"t": 1000.0}
    provider = _StaticProvider(items=[_item("a-1")])
    svc = NewsService([provider], cache_ttl_s=60, clock=lambda: clock["t"])
    first = svc.aggregate()
    assert first.cache_hit is False
    # Second call within TTL — should be a cache hit.
    clock["t"] += 30
    second = svc.aggregate()
    assert second.cache_hit is True
    assert [i.id for i in second.items] == [i.id for i in first.items]
    # Past TTL — refreshes.
    clock["t"] += 60
    third = svc.aggregate()
    assert third.cache_hit is False


def test_team_name_filter_drops_non_matching_items():
    provider = _StaticProvider(
        items=[
            _item("a-1", players=[PlayerMention(name="Bijan Robinson")]),
            _item("a-2", players=[PlayerMention(name="Random Joe")]),
            _item("a-3", players=[]),
        ]
    )
    svc = NewsService([provider], cache_ttl_s=0)
    out = svc.aggregate(team_names=["Bijan Robinson"])
    assert [i.id for i in out.items] == ["a-1"]


def test_dedup_by_id_across_providers():
    a = _StaticProvider(
        items=[_item("shared-1"), _item("only-a")],
        provider_name="a",
    )
    b = _StaticProvider(
        items=[_item("shared-1"), _item("only-b")],
        provider_name="b",
    )
    svc = NewsService([a, b], cache_ttl_s=0)
    out = svc.aggregate()
    ids = [i.id for i in out.items]
    assert len(ids) == 3
    assert sorted(ids) == ["only-a", "only-b", "shared-1"]


def test_sort_alerts_float_above_info():
    provider = _StaticProvider(
        items=[
            _item("a-info", severity="info", ts="2026-04-23T12:00:00+00:00"),
            _item("b-alert", severity="alert", ts="2026-04-23T09:00:00+00:00"),
            _item("c-watch", severity="watch", ts="2026-04-23T10:00:00+00:00"),
        ]
    )
    svc = NewsService([provider], cache_ttl_s=0)
    out = svc.aggregate()
    assert [i.id for i in out.items] == ["b-alert", "c-watch", "a-info"]


def test_team_filters_share_one_cached_fetch():
    """Public-endpoint hardening (Codex P2): the repeatable ``?team=``
    param is caller-controlled, so it must NOT participate in the
    cache key — otherwise any stranger could bypass the warm cache
    (and re-run every sequential upstream provider) just by varying
    the param.  Distinct team filters within TTL must be served from
    ONE cached provider fetch, with the filter applied per request."""
    clock = {"t": 1000.0}
    provider = _StaticProvider(
        items=[
            _item("a-1", players=[PlayerMention(name="Alpha")]),
            _item("a-2", players=[PlayerMention(name="Beta")]),
        ]
    )
    svc = NewsService([provider], cache_ttl_s=60, clock=lambda: clock["t"])

    first = svc.aggregate(team_names=["Alpha"])
    assert provider.fetch_calls == 1
    assert first.cache_hit is False
    assert [i.id for i in first.items] == ["a-1"]

    # Different team filter, same TTL window — must reuse the cached
    # fetch AND still filter correctly.
    second = svc.aggregate(team_names=["Beta"])
    assert provider.fetch_calls == 1, "varying ?team= busted the cache"
    assert second.cache_hit is True
    assert [i.id for i in second.items] == ["a-2"]

    # Unfiltered request shares the same entry too.
    third = svc.aggregate()
    assert provider.fetch_calls == 1
    assert third.cache_hit is True
    assert len(third.items) == 2

    # Only ONE cache entry exists regardless of filter variety.
    assert len(svc._cache) == 1

    # Filtering projects a copy — the cached unfiltered aggregate is
    # not mutated by narrower requests.
    assert len(svc.aggregate().items) == 2


def test_all_failed_aggregate_not_cached_for_full_ttl():
    """Server-side mirror of the client failure-TTL fix: an outage
    aggregate (every provider raised) must not squat in the cache for
    the full success TTL — the client's 15/30/60s retries need to
    reach recovered upstreams promptly."""
    clock = {"t": 1000.0}
    provider = _StaticProvider(items=[_item("a-1")], error=RuntimeError("down"))
    svc = NewsService([provider], cache_ttl_s=180, clock=lambda: clock["t"])

    first = svc.aggregate()
    assert first.items == []
    assert provider.fetch_calls == 1

    # Providers recover.  Just past the short failure TTL — but well
    # inside the 180s success TTL — the next call must refetch.
    provider._error = None
    clock["t"] += FAILURE_CACHE_TTL_S + 1
    second = svc.aggregate()
    assert provider.fetch_calls == 2, "all-failed aggregate enjoyed the success TTL"
    assert second.cache_hit is False
    assert [i.id for i in second.items] == ["a-1"]


def test_partial_success_keeps_normal_ttl():
    """One healthy provider is enough for the aggregate to cache for
    the full TTL — only total outages get the short failure life."""
    clock = {"t": 1000.0}
    good = _StaticProvider(items=[_item("a-1")], provider_name="good")
    bad = _StaticProvider(error=RuntimeError("down"), provider_name="bad")
    svc = NewsService([good, bad], cache_ttl_s=180, clock=lambda: clock["t"])

    svc.aggregate()
    assert good.fetch_calls == 1

    # Far beyond the failure TTL but inside the success TTL: still a
    # cache hit, no refetch.
    clock["t"] += 60
    again = svc.aggregate()
    assert again.cache_hit is True
    assert good.fetch_calls == 1
    assert bad.fetch_calls == 1


def test_cold_cache_single_flight():
    """Concurrent public requests on a cold cache must not stampede
    the sequential providers: one leader refreshes, followers wait on
    it and read the fresh entry (Codex P2)."""

    class _SlowProvider(NewsProvider):
        name = "slow"
        label = "Slow"

        def __init__(self):
            super().__init__()
            self.fetch_calls = 0

        def fetch(self, *, player_names=None, limit=50):
            self.fetch_calls += 1
            time.sleep(0.25)
            return [_item("s-1")]

    provider = _SlowProvider()
    svc = NewsService([provider], cache_ttl_s=60)

    results = []
    barrier = threading.Barrier(2)

    def call():
        barrier.wait()
        results.append(svc.aggregate())

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert provider.fetch_calls == 1, "cold-cache stampede: both threads fetched"
    assert len(results) == 2
    assert all([i.id for i in r.items] == ["s-1"] for r in results)
    # One leader (fresh fetch), one follower (served the new entry).
    assert sorted(r.cache_hit for r in results) == [False, True]


def test_expired_entries_evicted_on_miss():
    """Cache entries are keyed by the known-names universe (request
    filters are excluded — see test above); expired universes are
    swept on every miss so stale payloads don't accumulate."""
    clock = {"t": 1000.0}
    provider = _StaticProvider(items=[_item("a-1")])
    svc = NewsService([provider], cache_ttl_s=30, clock=lambda: clock["t"])
    # Two distinct known-names universes → two cache entries.
    svc.aggregate(player_names=["Alpha"])
    svc.aggregate(player_names=["Beta"])
    assert len(svc._cache) == 2

    # Advance past TTL, trigger one more miss — both prior entries
    # should get evicted, leaving only the fresh one.
    clock["t"] += 60
    svc.aggregate(player_names=["Gamma"])
    assert len(svc._cache) == 1


def test_total_limit_matches_route_cap():
    """Service cap must not silently truncate below the route's
    max limit (Codex P2).  Default total_limit should allow the
    route's documented ``?limit=100`` to return 100 items."""
    from src.news.service import DEFAULT_TOTAL_LIMIT

    assert DEFAULT_TOTAL_LIMIT >= 100

    many = [_item(f"x-{i}") for i in range(80)]
    svc = NewsService([_StaticProvider(items=many)], cache_ttl_s=0)
    out = svc.aggregate()
    # 80 items should survive; previously capped at 60.
    assert len(out.items) == 80


def test_serialize_to_dict_shape():
    provider = _StaticProvider(items=[_item("a-1", players=[PlayerMention(name="Player X")])])
    svc = NewsService([provider], cache_ttl_s=0)
    payload = svc.aggregate().to_dict()
    assert "items" in payload
    assert "providersUsed" in payload
    assert "providerRuns" in payload
    assert "generatedAt" in payload
    assert payload["items"][0]["impactedPlayers"] == ["Player X"]
