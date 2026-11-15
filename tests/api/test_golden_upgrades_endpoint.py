"""POST /api/trade/golden-upgrades — private, league-scoped, recommend-only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.league_intel.cross_market import MARKET_IDPTC
from tests.api.test_trade_protections_endpoint import env  # noqa: F401 — fixture


def _contract():
    rows = [
        ("Our LB", "LB", 3000, 4000, "CIN"),
        ("Their LB", "LB", 3600, 3500, "BUF"),
    ]
    players_array = [
        {
            "displayName": n,
            "canonicalName": n,
            "position": p,
            "team": t,
            "rankDerivedValue": b,
            "canonicalSiteValues": {MARKET_IDPTC: m},
            "assetClass": "player",
        }
        for n, p, b, m, t in rows
    ]
    return {
        "meta": {"leagueKey": "main"},
        "playersArray": players_array,
        "players": {
            r["displayName"]: {
                "_canonicalSiteValues": dict(r["canonicalSiteValues"]),
                "position": r["position"],
                "_sites": 8,
            }
            for r in players_array
        },
        "sleeper": {
            "teams": [
                {"name": "Us", "ownerId": "1", "players": ["Our LB"]},
                {"name": "Them", "ownerId": "2", "players": ["Their LB"]},
            ]
        },
    }


URL = "/api/trade/golden-upgrades"


def test_anonymous_is_401():
    res = TestClient(server.app).post(URL, json={"myTeam": "Us"})
    assert res.status_code == 401


@pytest.fixture()
def authed(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    return env


def test_upgrades_are_recommend_only_and_never_cached(authed):
    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "recommend_only"
    assert body["leagueKey"] == "main"
    assert res.headers["cache-control"] == "no-store"
    assert [(u["owned"]["name"], u["target"]["name"]) for u in body["upgrades"]] == [
        ("Our LB", "Their LB")
    ]


def test_a_saved_protection_removes_the_owned_player(authed):
    put = authed.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": ["Our LB"], "nflTeams": []},
        headers={"x-test-user": "jason"},
    )
    assert put.status_code == 200, put.text
    body = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    ).json()
    assert body["upgrades"] == []
    assert body["noResultReason"] == "all_outgoing_assets_constrained"


def test_bad_requests_are_400(authed):
    h = {"x-test-user": "jason"}
    assert (
        authed.client.post(
            URL, json={"myTeam": "Nobody", "leagueKey": "main"}, headers=h
        ).status_code
        == 400
    )
    res = authed.client.post(
        URL,
        json={
            "myTeam": "Us",
            "leagueKey": "main",
            "refinement": {"lock": ["Our LB"], "exclude": ["our lb"]},
        },
        headers=h,
    )
    assert res.status_code == 400 and res.json()["error"] == "invalid_refinement"
