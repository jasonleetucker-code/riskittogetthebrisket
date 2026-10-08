"""C6-MGR-01 — ``GET /api/manager-scout`` route behaviour.

League resolution goes through ``server.py::_resolve_league_for_request`` with
``require_loaded_contract=True``; display names come only from a contract
loaded for the SAME league.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.api import league_registry
from src.intel import manager_scout as ms
from src.trade import faab_history

LEAGUE = "main"
OTHER = "second"
T1 = 1_760_000_000_000


@pytest.fixture
def scout_env(tmp_path, monkeypatch):
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
                        "bestBall": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                    {
                        "key": OTHER,
                        "displayName": "Second",
                        "sleeperLeagueId": "L-SECOND",
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry_path))
    league_registry.reload_registry()

    store_mod._reset_setup_cache_for_tests()
    ms._reset_memo_for_tests()
    retention = tmp_path / "retention"
    monkeypatch.setattr(store_mod, "DB_PATH", retention / "acquisition.sqlite")
    # The memo keys on the retention directory's files; point it at ours.
    monkeypatch.setattr("src.retention.evidence_store.RETENTION_DIR", retention)
    monkeypatch.setattr(faab_history, "HISTORY_DIR", tmp_path / "faab")
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    yield monkeypatch
    league_registry.reload_registry()
    store_mod._reset_setup_cache_for_tests()
    ms._reset_memo_for_tests()


_CONTRACT = {
    "meta": {"leagueKey": LEAGUE, "sleeperDataReady": True},
    "sleeper": {
        "teams": [
            {"ownerId": "U1", "name": "Team One", "roster_id": 1},
            {"ownerId": "U2", "name": "Team Two", "roster_id": 2},
        ]
    },
}


def _get(monkeypatch, **params):
    """GET after app startup — startup loads a contract from disk, so the
    test contract is installed only once the client is running."""
    with TestClient(server.app) as c:
        monkeypatch.setattr(server, "latest_contract_data", _CONTRACT)
        return c.get("/api/manager-scout", params=params or None)


def _seed_trade():
    tx = {
        "transaction_id": "t1",
        "type": "trade",
        "status": "complete",
        "leg": 3,
        "status_updated": T1,
        "adds": {"4034": 1, "1111": 2},
        "drops": {"4034": 2, "1111": 1},
        "draft_picks": [],
    }
    store_mod.write_events(
        events_from_transaction(
            tx, league_key=LEAGUE, season="2026", owner_by_roster={1: "U1", 2: "U2"}
        )
    )


def test_serves_the_resolved_leagues_profiles_with_current_names(scout_env):
    _seed_trade()
    res = _get(scout_env)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["leagueKey"] == LEAGUE
    assert body["privacyClass"] == "private"
    managers = {m["ownerId"]: m for m in body["managers"]}
    assert managers["U1"]["displayName"] == "Team One"
    assert managers["U1"]["tradeTendencies"]["tradeCount"] == 1
    assert managers["U1"]["lineupTendencies"]["state"] == "not_applicable"
    assert managers["U1"]["faabTendencies"]["state"] == "unavailable"


def test_a_league_mismatch_against_the_loaded_contract_is_503(scout_env):
    res = _get(scout_env, leagueKey=OTHER)
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_an_unknown_league_is_400(scout_env):
    res = _get(scout_env, leagueKey="nope")
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"


def test_a_missing_ledger_is_a_200_with_unavailable_states(scout_env):
    res = _get(scout_env)
    assert res.status_code == 200
    body = res.json()
    assert body["sources"]["trades"]["state"] == "acquisition_store_missing"
    for m in body["managers"]:
        assert m["tradeTendencies"]["state"] == "unavailable"
        assert m["tradeTendencies"]["sampleSize"] is None


def test_an_unwired_router_never_serves():
    from fastapi import FastAPI

    from src.intel import manager_scout_api as api

    saved = (api._league_resolver, api._contract_provider)
    try:
        api.configure(league_resolver=None, contract_provider=None)
        app = FastAPI()
        app.include_router(api.router)
        with TestClient(app) as c:
            assert c.get("/api/manager-scout").status_code == 401
    finally:
        api.configure(league_resolver=saved[0], contract_provider=saved[1])
