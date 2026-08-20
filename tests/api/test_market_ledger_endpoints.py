"""Endpoint tests for ``GET /api/market/waivers`` and ``GET /api/market/trades``.

Both are thin read-only projections over the canonical acquisition ledger
(``src.trade.waiver_ledger`` / ``src.trade.market_trade_ledger``) — no live
contract, no Sleeper fetch, no auth gate (matching the established pattern
of ``/api/draft/roster-context`` and ``/api/waiver/faab-recommend``, which
carry the same posture). These tests pin the response shape, league
resolution, and the recent-window cap.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.api import league_registry

LEAGUE = "main"
T1 = 1_760_000_000_000


@pytest.fixture
def market_env(tmp_path, monkeypatch):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": LEAGUE,
                "leagues": [
                    {
                        "key": LEAGUE,
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry_path))
    league_registry.reload_registry()

    store_mod._reset_setup_cache_for_tests()
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "retention" / "acquisition.sqlite")

    # These are private endpoints behind server.py's global _private_api_gate
    # middleware (every /api/* path except the public allowlist 401s without
    # a session) — bypass the same way tests/api/test_faab_recommend_endpoint.py
    # does, rather than standing up a real session cookie.
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    yield

    league_registry.reload_registry()
    store_mod._reset_setup_cache_for_tests()


def _waiver_tx(tx_id, *, bid=15, ts=T1, added=("4034",), rid=1):
    return {
        "transaction_id": tx_id,
        "type": "waiver",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "settings": {"waiver_bid": bid},
        "adds": {pid: rid for pid in added},
        "drops": {},
        "draft_picks": [],
    }


def _trade_tx(tx_id, *, ts=T1, adds=None, drops=None):
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "adds": adds or {},
        "drops": drops or {},
        "draft_picks": [],
    }


def _seed(txs, league_key=LEAGUE):
    events = []
    for tx in txs:
        events.extend(events_from_transaction(tx, league_key=league_key))
    store_mod.write_events(events)


# ── /api/market/waivers ─────────────────────────────────────────────


def test_waivers_endpoint_defaults_to_the_default_league(market_env):
    with TestClient(server.app) as c:
        resp = c.get("/api/market/waivers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["leagueKey"] == LEAGUE
    assert body["summary"]["totalClaims"] == 0
    assert body["recentClaims"] == []
    assert body["recentClaimsTruncated"] is False


def test_waivers_endpoint_reports_seeded_claims_newest_first(market_env):
    _seed(
        [
            _waiver_tx("t1", bid=10, ts=T1),
            _waiver_tx("t2", bid=0, ts=T1 + 1000),
        ]
    )
    with TestClient(server.app) as c:
        resp = c.get("/api/market/waivers", params={"leagueKey": LEAGUE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["totalClaims"] == 2
    assert body["summary"]["zeroBidClaims"] == 1
    assert [claim["sourceRef"] for claim in body["recentClaims"]] == ["tx:t2", "tx:t1"]


def test_waivers_endpoint_unknown_league_400s(market_env):
    with TestClient(server.app) as c:
        resp = c.get("/api/market/waivers", params={"leagueKey": "no_such_league"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_league"


def test_waivers_endpoint_truncates_the_recent_window(market_env, monkeypatch):
    monkeypatch.setattr(server, "_MARKET_LEDGER_RECENT_LIMIT", 1)
    _seed([_waiver_tx("t1", ts=T1), _waiver_tx("t2", ts=T1 + 1000)])
    with TestClient(server.app) as c:
        resp = c.get("/api/market/waivers", params={"leagueKey": LEAGUE})
    body = resp.json()
    assert body["summary"]["totalClaims"] == 2
    assert len(body["recentClaims"]) == 1
    assert body["recentClaims"][0]["sourceRef"] == "tx:t2"
    assert body["recentClaimsTruncated"] is True


# ── /api/market/trades ───────────────────────────────────────────────


def test_trades_endpoint_defaults_to_the_default_league(market_env):
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades")
    assert resp.status_code == 200
    body = resp.json()
    assert body["leagueKey"] == LEAGUE
    assert body["summary"]["totalTrades"] == 0
    assert body["recentTrades"] == []


def test_trades_endpoint_reports_seeded_trades_with_format_metadata(market_env):
    _seed([_trade_tx("t1", adds={"4034": 1}, drops={"4034": 2})])
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades", params={"leagueKey": LEAGUE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["totalTrades"] == 1
    trade = body["recentTrades"][0]
    assert trade["sourceRef"] == "tx:t1"
    assert set(trade["format"].keys()) == {"teams", "superflex", "tep", "tepLevel", "is2Te", "idp"}
    assert trade["format"]["teams"] == 12


def test_trades_endpoint_unknown_league_400s(market_env):
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades", params={"leagueKey": "no_such_league"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_league"


def test_market_endpoints_are_league_isolated(market_env):
    _seed([_waiver_tx("t1")], league_key=LEAGUE)
    # A second league isn't in the registry fixture, but the acquisition
    # ledger itself is keyed purely by league_key string — seed it directly
    # to prove the endpoint's own scoping doesn't leak across keys.
    _seed([_waiver_tx("t2")], league_key="other_league")

    with TestClient(server.app) as c:
        resp = c.get("/api/market/waivers", params={"leagueKey": LEAGUE})
    assert resp.json()["summary"]["totalClaims"] == 1
