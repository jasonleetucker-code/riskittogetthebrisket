"""Sleeper trending provider tests.

These exercise the normalization path — upstream HTTP is stubbed
via a fake ``requests.Session`` so the tests stay offline and
deterministic.
"""
from __future__ import annotations

from src.news.providers.sleeper import (
    SleeperTrendingProvider,
    _reset_player_map_for_tests,
)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeSession:
    """Stubs the two endpoints the provider hits.

    Routes are keyed by path substring so the test reads naturally.
    Each route can be either a static payload or a callable.
    """

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    def get(self, url, timeout=None, headers=None):
        self.calls.append(url)
        for key, payload in self._routes.items():
            if key in url:
                resolved = payload() if callable(payload) else payload
                return _FakeResponse(resolved)
        raise AssertionError(f"unexpected URL: {url}")


def _build_provider(routes):
    _reset_player_map_for_tests()
    session = _FakeSession(routes)
    provider = SleeperTrendingProvider(
        lookback_hours=24,
        limit_per_feed=5,
        session=session,
    )
    return provider, session


def test_trending_maps_to_normalized_items():
    routes = {
        "/players/nfl/trending/add": [
            {"player_id": "6797", "count": 18432},
            {"player_id": "9999", "count": 9021},
        ],
        "/players/nfl/trending/drop": [
            {"player_id": "1234", "count": 5502},
        ],
        "/players/nfl": {
            "6797": {
                "full_name": "Jayden Reed",
                "position": "WR",
                "team": "GB",
            },
            "9999": {
                "first_name": "Rookie",
                "last_name": "Breakout",
                "position": "RB",
            },
            "1234": {
                "full_name": "Fallen Star",
                "position": "WR",
            },
        },
    }
    provider, _ = _build_provider(routes)
    items = provider.fetch(limit=10)
    assert len(items) == 3

    # Spot-check the top add.
    top = items[0]
    assert "Jayden Reed" in top.headline
    assert top.provider == "sleeper"
    assert top.provider_label == "Sleeper"
    assert top.kind == "trending"
    assert top.severity == "watch"
    assert top.players[0].impact == "positive"
    assert top.url and top.url.endswith("/6797")
    assert "trending" in top.tags and "add" in top.tags

    # Dropped player should come through with negative impact.
    drops = [i for i in items if "drop" in i.tags]
    assert len(drops) == 1
    assert drops[0].players[0].impact == "negative"
    assert drops[0].severity == "info"


def test_missing_player_map_entry_is_dropped():
    routes = {
        "/players/nfl/trending/add": [
            {"player_id": "missing", "count": 100},
        ],
        "/players/nfl/trending/drop": [],
        "/players/nfl": {},  # empty map → name lookup returns None
    }
    provider, _ = _build_provider(routes)
    assert provider.fetch() == []


def test_cold_player_map_failure_propagates():
    """Player-map fetch failure on a cold cache must raise, so
    the service can mark the provider run ``ok=False``.  A warm
    cache (previous successful fetch) still degrades gracefully.
    Codex P1 #2."""
    import pytest

    class _TrendingOkMapFailSession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout=None, headers=None):
            self.calls.append(url)
            if "trending" in url:
                class _R:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return [{"player_id": "1", "count": 3}]

                return _R()
            # /players/nfl — simulate outage
            raise RuntimeError("player-map unavailable")

    _reset_player_map_for_tests()
    provider = SleeperTrendingProvider(session=_TrendingOkMapFailSession())
    with pytest.raises(RuntimeError):
        provider.fetch()


def test_warm_player_map_failure_degrades_gracefully():
    """If a prior fetch succeeded, a later fetch outage falls
    back to the stale map rather than raising — dynasty names
    don't change that often, and stale-but-usable > failure."""
    # First populate the cache via a successful fetch.
    routes_ok = {
        "/players/nfl/trending/add": [
            {"player_id": "42", "count": 10},
        ],
        "/players/nfl/trending/drop": [],
        "/players/nfl": {"42": {"full_name": "Cached Star"}},
    }
    provider_ok, _ = _build_provider(routes_ok)
    items_ok = provider_ok.fetch()
    assert len(items_ok) == 1

    # Now simulate a player-map outage on the next fetch.  The
    # trending endpoints still work, but /players/nfl errors out.
    class _WarmMapOutage:
        def get(self, url, timeout=None, headers=None):
            if "trending" in url:
                class _R:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return [{"player_id": "42", "count": 11}]

                return _R()
            raise RuntimeError("player-map down")

    # Force a player-map refetch by expiring the TTL — simulate by
    # invalidating then re-seeding trending but failing map.
    # The existing module-level cache has the "42" entry so the
    # warm-stale path should return it.
    provider_warm = SleeperTrendingProvider(session=_WarmMapOutage())
    items_warm = provider_warm.fetch()
    assert len(items_warm) >= 1
    assert any(p.name == "Cached Star" for i in items_warm for p in i.players)


def test_provider_propagates_when_both_endpoints_fail():
    """Total upstream outage → raise so the service can mark the
    run ``ok=False``.  Silently returning ``[]`` would hide a real
    outage from the all-providers-failed → 503 path (Codex P1)."""
    import pytest

    class _ExplodingSession:
        def get(self, *_a, **_kw):
            raise RuntimeError("boom")

    _reset_player_map_for_tests()
    provider = SleeperTrendingProvider(session=_ExplodingSession())
    with pytest.raises(RuntimeError):
        provider.fetch()


def test_provider_tolerates_one_endpoint_failing():
    """Partial outage (only one of add/drop down) still returns
    the usable items — no reason to throw away a working signal."""

    class _SplitSession:
        def __init__(self, ok_path: str):
            self._ok_path = ok_path
            self.calls = []

        def get(self, url, timeout=None, headers=None):
            self.calls.append(url)
            if self._ok_path in url:
                class _R:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return [{"player_id": "1", "count": 5}]

                return _R()
            if "/players/nfl" in url and "trending" not in url:
                class _R2:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"1": {"full_name": "Only Add"}}

                return _R2()
            raise RuntimeError("drops unavailable")

    _reset_player_map_for_tests()
    provider = SleeperTrendingProvider(
        session=_SplitSession("/trending/add")
    )
    items = provider.fetch()
    assert len(items) == 1
    assert items[0].players[0].name == "Only Add"


def test_stable_ids_across_bucket():
    """Two fetches in the same hour bucket should produce identical ids."""
    routes = {
        "/players/nfl/trending/add": [{"player_id": "6797", "count": 10}],
        "/players/nfl/trending/drop": [],
        "/players/nfl": {"6797": {"full_name": "Jayden Reed"}},
    }
    provider, _ = _build_provider(routes)
    a = provider.fetch()
    # Re-fetch — player map cache hit + same hour bucket → same id.
    b = provider.fetch()
    assert [i.id for i in a] == [i.id for i in b]
