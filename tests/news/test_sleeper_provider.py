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


def test_provider_swallows_network_errors():
    """The provider must return ``[]`` not raise on upstream errors."""
    class _ExplodingSession:
        calls = 0

        def get(self, *_a, **_kw):
            self.__class__.calls += 1
            raise RuntimeError("boom")

    _reset_player_map_for_tests()
    provider = SleeperTrendingProvider(session=_ExplodingSession())
    # The public fetch method logs + returns [], never raises.
    assert provider.fetch() == []


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
