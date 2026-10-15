"""Route tests for ``GET /api/market/trades/comparable`` (TC-09) and
``GET /api/market/trades/database`` (TC-08).

The logic is pinned in ``tests/trade/test_comparable_trades.py`` and
``tests/trade/test_market_trade_database.py``; these pin the routes: the
private API gate, league resolution, per-side CSV parsing, filter parsing
(400 on a bad value), the unavailable state and board names.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

import server
from src.trade import comparable_trades as ct
from src.trade import market_trade_database as db
from tests.api.test_market_trade_reference_endpoint import (  # noqa: F401
    LEAGUE,
    _build,
    env,
)

TODAY = date(2026, 10, 8)


def _pin_today(monkeypatch):
    real_c, real_d = ct.comparable_trades, db.browse_trades
    monkeypatch.setattr(
        ct, "comparable_trades", lambda *a, **k: real_c(*a, **{**k, "today": TODAY})
    )
    monkeypatch.setattr(db, "browse_trades", lambda *a, **k: real_d(*a, **{**k, "today": TODAY}))


def test_both_routes_are_private(env):  # noqa: F811
    _build(env)
    with TestClient(server.app) as c:
        assert c.get("/api/market/trades/comparable?aPlayers=6794").status_code == 401
        assert c.get("/api/market/trades/database").status_code == 401


def test_unavailable_without_a_ledger(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app) as c:
        for path in ("/api/market/trades/comparable?aPlayers=6794", "/api/market/trades/database"):
            resp = c.get(path)
            assert resp.status_code == 503
            assert resp.json()["error"] == "trade_ledger_unavailable"


def test_comparable_parses_sides_and_names(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    _pin_today(monkeypatch)
    _build(env)
    with TestClient(server.app) as c:
        resp = c.get(
            "/api/market/trades/comparable",
            params={"aPlayers": "6794", "bPlayers": "7564", "bPicks": "nope", "limit": "3"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["leagueKey"] == LEAGUE and body["state"] == "ok"
    assert body["query"]["sideA"]["players"] == ["6794"]
    assert body["query"]["sideB"]["players"] == ["7564"]
    assert body["query"]["sideB"]["unresolved"] == [
        {"ref": "nope", "reason": "unparseable_pick_name"}
    ]
    top = body["trades"][0]
    assert top["comparability"]["components"]["assetOverlap"]["score"] == 1.0
    assert top["comparability"]["reasons"][0]["text"].startswith("Same asset: Justin Jefferson")
    assert body["methodology"]["status"] == "PRIOR_UNVALIDATED"


def test_comparable_bad_limit_and_unknown_league(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app) as c:
        assert c.get("/api/market/trades/comparable?aPlayers=1&limit=x").status_code == 400
        resp = c.get("/api/market/trades/comparable?leagueKey=nope&aPlayers=1")
        assert resp.status_code == 400 and resp.json()["error"] == "unknown_league"


def test_database_filters(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    _pin_today(monkeypatch)
    _build(env)
    with TestClient(server.app) as c:
        resp = c.get(
            "/api/market/trades/database",
            params={"teams": "12", "shape": "1x1", "limit": "5"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["filters"]["teams"] == 12 and body["filters"]["shape"] == "1x1"
        assert body["trades"][0]["sides"][0][0]["label"] == "Justin Jefferson"
        assert resp.headers["cache-control"].startswith("private")
        # The fixture's KTC settings state no lineup: superflex is unknown, so a
        # superflex filter excludes the row and counts it.
        body = c.get("/api/market/trades/database?superflex=true").json()
        assert body["trades"] == [] and body["excludedUnknown"] == {"superflex": 1}


def test_database_bad_filters_are_400(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    _build(env)
    with TestClient(server.app) as c:
        for qs in (
            "teams=twelve",
            "superflex=maybe",
            "shape=2by1",
            "since=yesterday",
            "source=espn",
            "since=2026-10-05&until=2026-10-01",
            "beforeDate=soon",
            "skip=x",
        ):
            resp = c.get(f"/api/market/trades/database?{qs}")
            assert resp.status_code == 400, qs
            assert resp.json()["error"] == "bad_request"
