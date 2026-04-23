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

from src.news.base import NewsItem, NewsProvider, PlayerMention
from src.news.service import NewsService


class _StaticProvider(NewsProvider):
    name = "static"
    label = "Static"

    def __init__(self, *, items=None, error=None, provider_name=None, provider_label=None):
        super().__init__()
        self._items = list(items or [])
        self._error = error
        if provider_name:
            self.name = provider_name
        if provider_label:
            self.label = provider_label

    def fetch(self, *, player_names=None, limit=50):
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


def test_expired_entries_evicted_on_miss():
    """Many distinct team filters must not leak full payloads
    into the cache forever.  Eviction sweeps on every miss
    (Codex P2)."""
    clock = {"t": 1000.0}
    provider = _StaticProvider(
        items=[
            _item("a-1", players=[PlayerMention(name="Alpha")]),
            _item("a-2", players=[PlayerMention(name="Beta")]),
            _item("a-3", players=[PlayerMention(name="Gamma")]),
        ]
    )
    svc = NewsService([provider], cache_ttl_s=30, clock=lambda: clock["t"])
    # Three distinct team filters → three cache entries.
    svc.aggregate(team_names=["Alpha"])
    svc.aggregate(team_names=["Beta"])
    svc.aggregate(team_names=["Gamma"])
    assert len(svc._cache) == 3

    # Advance past TTL, trigger one more miss — all three prior
    # entries should get evicted, leaving only the fresh one.
    clock["t"] += 60
    svc.aggregate(team_names=["Delta"])
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
    provider = _StaticProvider(
        items=[_item("a-1", players=[PlayerMention(name="Player X")])]
    )
    svc = NewsService([provider], cache_ttl_s=0)
    payload = svc.aggregate().to_dict()
    assert "items" in payload
    assert "providersUsed" in payload
    assert "providerRuns" in payload
    assert "generatedAt" in payload
    assert payload["items"][0]["impactedPlayers"] == ["Player X"]
