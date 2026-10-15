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


def test_refinement_keys_must_be_other_teams_in_the_league(authed):
    """Review nit: each key costs a constraint-store read, so the map is
    bounded to real opponents (never the requester, never a stranger)."""
    for key in ("Nobody", "Us"):
        res = authed.client.post(
            URL,
            json={
                "myTeam": "Us",
                "leagueKey": "main",
                "refinementByOpponent": {key: {"lock": [], "exclude": []}},
            },
            headers={"x-test-user": "jason"},
        )
        assert res.status_code == 400, key
        assert res.json()["error"] == "invalid_refinement"


def test_each_offer_carries_descriptive_manager_evidence(authed, monkeypatch):
    from src.intel import manager_scout as ms

    seen = {}

    def fake_scout(league_key, **kw):
        seen["league"] = league_key
        return {
            "managers": [
                {
                    "ownerId": "2",
                    "tradeTendencies": {
                        "state": "measured",
                        "tradeCount": 3,
                        "received": {
                            "assets": 4,
                            "players": 4,
                            "picks": 0,
                            "byPosition": {"WR": 2},
                        },
                        "packageShape": {"even": 3},
                        "partners": [{"ownerId": "1", "trades": 1}],
                    },
                }
            ]
        }

    monkeypatch.setattr(ms, "cached_manager_scout", fake_scout)
    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 200, res.text
    ev = res.json()["opponents"][0]["offer"]["managerEvidence"]
    assert seen["league"] == "main"
    assert ev["state"] == "measured"
    assert ev["positionsTheyWouldReceive"] == [
        {"position": "WR", "receivedBefore": 2, "ofPlayersReceived": 4}
    ]
    assert ev["tradesWithRequester"] == 1


def test_a_scout_fault_leaves_an_unavailable_block_not_a_500(authed, monkeypatch):
    from src.intel import manager_scout as ms

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(ms, "cached_manager_scout", boom)
    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 200, res.text
    ev = res.json()["opponents"][0]["offer"]["managerEvidence"]
    assert (ev["state"], ev["reason"]) == ("unavailable", "manager_scout_unavailable")


def test_one_cards_evidence_fault_is_contained_to_that_card(authed, monkeypatch):
    from src.intel import manager_scout as ms

    monkeypatch.setattr(ms, "cached_manager_scout", lambda *a, **k: {"managers": []})

    def boom(*a, **k):
        raise ValueError("odd profile")

    monkeypatch.setattr(ms, "offer_evidence", boom)
    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 200, res.text
    ev = res.json()["opponents"][0]["offer"]["managerEvidence"]
    assert (ev["state"], ev["reason"]) == ("unavailable", "offer_evidence_failed")


def test_manager_evidence_is_never_written_to_the_run_log(authed, monkeypatch, tmp_path):
    import json as _json

    from src.trade import best_offers as bo

    res = authed.client.post(
        URL,
        json={"myTeam": "Us", "leagueKey": "main", "useTeamContext": False},
        headers={"x-test-user": "jason"},
    )
    assert res.status_code == 200, res.text
    assert "managerEvidence" in res.json()["opponents"][0]["offer"]
    lines = [
        line
        for f in bo.BEST_OFFERS_RUN_LOG_DIR.glob("runs-*.jsonl")
        for line in f.read_text().splitlines()
    ]
    assert lines and all(
        "managerEvidence" not in _json.loads(line)["opponents"][0]["offer"] for line in lines
    )
