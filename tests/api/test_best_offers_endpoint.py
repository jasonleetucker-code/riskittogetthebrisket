"""POST /api/trade/best-offers — private, league-scoped, recommend-only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from tests.api.test_trade_protections_endpoint import env  # noqa: F401 — fixture
from tests.trade.test_best_offers import KTC, IDPTC


def _contract():
    def row(name, pos, board, ktc, idptc, team):
        return {
            "displayName": name,
            "canonicalName": name,
            "position": pos,
            "team": team,
            "rankDerivedValue": board,
            "canonicalSiteValues": {KTC: ktc, IDPTC: idptc},
            "assetClass": "player",
        }

    rows = [
        row("Our WR", "WR", 4000, 5000, 5100, "CIN"),
        row("Their RB", "RB", 5000, 4800, 4900, "BUF"),
    ]
    return {
        "meta": {"leagueKey": "main"},
        "playersArray": rows,
        "players": {
            r["displayName"]: {
                "_canonicalSiteValues": dict(r["canonicalSiteValues"]),
                "position": r["position"],
                "_sites": 8,
            }
            for r in rows
        },
        "sleeper": {
            "teams": [
                {"name": "Us", "ownerId": "1", "players": ["Our WR"]},
                {"name": "Them", "ownerId": "2", "players": ["Their RB"]},
            ]
        },
    }


URL = "/api/trade/best-offers"


def test_anonymous_is_401():
    client = TestClient(server.app)
    res = client.post(URL, json={"myTeam": "Us"})
    assert res.status_code == 401


@pytest.fixture()
def authed(env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    from src.trade import best_offers as bo

    monkeypatch.setattr(bo, "BEST_OFFERS_RUN_LOG_DIR", tmp_path / "runs")
    return env


def test_one_card_per_opponent_recommend_only_and_no_store(authed):
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
    assert [o["team"] for o in body["opponents"]] == ["Them"]
    assert body["opponents"][0]["status"] == "qualified"
    assert body["runId"]


def test_a_contradictory_card_refinement_is_a_400(authed):
    res = authed.client.post(
        URL,
        json={
            "myTeam": "Us",
            "leagueKey": "main",
            "refinementByOpponent": {"Them": {"lock": ["Our WR"], "exclude": ["our wr"]}},
        },
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_refinement"


def test_a_card_lock_conflicting_with_a_saved_protection_is_explained(authed):
    put = authed.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": ["Our WR"], "nflTeams": []},
        headers={"x-test-user": "jason"},
    )
    assert put.status_code == 200, put.text
    res = authed.client.post(
        URL,
        json={
            "myTeam": "Us",
            "leagueKey": "main",
            "useTeamContext": False,
            "refinementByOpponent": {"Them": {"lock": ["Our WR"], "exclude": []}},
        },
        headers={"x-test-user": "jason"},
    )
    card = res.json()["opponents"][0]
    assert card["status"] == "no_result"
    assert card["noResultReason"] in (
        "lock_conflicts_with_protection",
        "all_outgoing_assets_constrained",
    )


def test_unknown_team_is_a_400(authed):
    res = authed.client.post(
        URL, json={"myTeam": "Nobody", "leagueKey": "main"}, headers={"x-test-user": "jason"}
    )
    assert res.status_code == 400
