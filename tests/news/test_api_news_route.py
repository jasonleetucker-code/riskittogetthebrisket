"""End-to-end test for the GET /api/news FastAPI route.

Uses an in-memory stub NewsService injected via
``server._reset_news_service_for_tests`` so no real providers
touch the network.  The route is otherwise exercised verbatim —
query-param parsing, response shape, 503 on all-failures.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.news.base import NewsItem, PlayerMention
from src.news.service import NewsService

# Starlette's TestClient-backed lifespan conflicts with this
# long-running app's background-thread startup.  We test the
# route by mounting just the app without triggering lifespan.


@pytest.fixture
def client():
    # Bypass lifespan — the startup hook spins up scrape threads
    # that are unrelated to /api/news and would slow the test down.
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c
    server._reset_news_service_for_tests(None)


class _FakeProvider:
    name = "fake"
    label = "Fake"
    timeout_s = 1.0

    def __init__(self, items=None, error=None):
        self._items = items or []
        self._error = error

    def fetch(self, *, player_names=None, limit=50):
        if self._error:
            raise self._error
        return self._items


def _make_item(id_, players=None):
    return NewsItem(
        id=id_,
        ts="2026-04-23T10:00:00+00:00",
        provider="fake",
        provider_label="Fake",
        severity="alert",
        kind="injury",
        headline=f"hi {id_}",
        body="body",
        players=players or [],
    )


def test_api_news_returns_normalized_items(client):
    svc = NewsService(
        [_FakeProvider(items=[_make_item("a"), _make_item("b")])],
        cache_ttl_s=0,
    )
    server._reset_news_service_for_tests(svc)

    resp = client.get("/api/news")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "backend"
    assert data["count"] == 2
    assert len(data["items"]) == 2
    first = data["items"][0]
    # legacy + enriched fields both present
    for key in (
        "id",
        "ts",
        "providerLabel",
        "severity",
        "headline",
        "publishedAt",
        "summary",
        "impactedPlayers",
        "tags",
    ):
        assert key in first
    assert data["providersUsed"] == ["fake"]


def test_api_news_team_filter(client):
    svc = NewsService(
        [
            _FakeProvider(
                items=[
                    _make_item("a", players=[PlayerMention(name="Bijan Robinson")]),
                    _make_item("b", players=[PlayerMention(name="Random Joe")]),
                ]
            )
        ],
        cache_ttl_s=0,
    )
    server._reset_news_service_for_tests(svc)

    resp = client.get("/api/news?team=Bijan+Robinson")
    assert resp.status_code == 200
    data = resp.json()
    assert [i["id"] for i in data["items"]] == ["a"]


def test_api_news_limit_caps_response(client):
    items = [_make_item(f"x-{i}") for i in range(10)]
    svc = NewsService([_FakeProvider(items=items)], cache_ttl_s=0)
    server._reset_news_service_for_tests(svc)

    resp = client.get("/api/news?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["count"] == 3
    assert data["limit"] == 3


def test_api_news_returns_503_when_all_providers_fail(client):
    svc = NewsService(
        [_FakeProvider(error=RuntimeError("boom"))],
        cache_ttl_s=0,
    )
    server._reset_news_service_for_tests(svc)

    resp = client.get("/api/news")
    assert resp.status_code == 503
    data = resp.json()
    assert data["items"] == []
    assert data["error"] == "all_providers_failed"


def test_api_news_200_with_empty_items_when_providers_return_nothing(client):
    """Provider OK but empty → 200 (no DEMO fallback on frontend)."""
    svc = NewsService([_FakeProvider(items=[])], cache_ttl_s=0)
    server._reset_news_service_for_tests(svc)

    resp = client.get("/api/news")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["source"] == "backend"
