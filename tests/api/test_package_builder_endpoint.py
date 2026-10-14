"""POST /api/trade/package-builder — private, league-scoped, recommend-only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from tests.api.test_trade_protections_endpoint import env  # noqa: F401 — fixture


def _contract():
    rows = [
        ("Our WR", "WR", 4200, 4600, "CIN", "Us"),
        ("Our RB", "RB", 3000, 3300, "MIN", "Us"),
        ("Their QB", "QB", 4400, 4300, "KC", "Them"),
        ("Their WR", "WR", 4100, 4000, "BUF", "Them"),
    ]
    arr = [
        {
            "displayName": n,
            "canonicalName": n,
            "position": p,
            "team": t,
            "rankDerivedValue": b,
            "canonicalSiteValues": {MARKET_KTC: m, MARKET_IDPTC: m},
            "assetClass": "player",
        }
        for n, p, b, m, t, _o in rows
    ]
    return {
        "meta": {"leagueKey": "main"},
        "playersArray": arr,
        "players": {
            r["displayName"]: {
                "_canonicalSiteValues": dict(r["canonicalSiteValues"]),
                "position": r["position"],
                "team": r["team"],
                "_sites": 8,
            }
            for r in arr
        },
        "sleeper": {
            "teams": [
                {"name": "Us", "ownerId": "1", "players": ["Our WR", "Our RB"]},
                {"name": "Them", "ownerId": "2", "players": ["Their QB", "Their WR"]},
            ]
        },
    }


URL = "/api/trade/package-builder"
H = {"x-test-user": "jason"}


def test_anonymous_is_401():
    assert TestClient(server.app).post(URL, json={"myTeam": "Us"}).status_code == 401


@pytest.fixture()
def authed(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    return env


def test_a_target_build_is_recommend_only_and_never_cached(authed):
    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "target": "Their QB", "useTeamContext": False},
        headers=H,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "recommend_only"
    assert res.headers["cache-control"] == "no-store"
    assert body["request"]["opponent"] == "Them"
    assert body["packages"]
    assert all("Their QB" in {a["name"] for a in p["receive"]} for p in body["packages"])


@pytest.mark.parametrize(
    "extra,error",
    [
        ({"returnPositions": ["K"]}, "invalid_return_positions"),
        ({"maxAssetsPerSide": 4}, "invalid_numbers"),
        ({"evidence": "vibes"}, "invalid_evidence"),
        ({"opponent": "Us"}, "unknown_opponent"),
        ({"outgoing": "Our WR"}, "invalid_outgoing"),
        ({"refinement": {"lock": ["Our WR"], "exclude": ["our wr"]}}, "invalid_refinement"),
    ],
)
def test_bad_requests_are_400(authed, extra, error):
    res = authed.client.post(URL, json={"myTeam": "Us", "leagueKey": "main", **extra}, headers=H)
    assert res.status_code == 400
    assert res.json()["error"] == error
