"""Endpoint tests for ``POST /api/waiver/perfect`` (Perfect Waivers, C7-WAIV-01).

Pins the route posture the other league-scoped waiver/trade endpoints share:
private (401 anonymous), 503 with no contract, 503 ``data_not_ready`` on a
league mismatch through ``_resolve_league_for_request``, 400 when the team is
missing or unknown (never another team's plan), and the 200 shape — including
that a protection saved through ``PUT /api/user/trade-protections`` is honoured
(the protected player is never proposed as a drop) and that the plan is stamped
advisory.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry, user_kv

URL = "/api/waiver/perfect"


def _row(pid, name, pos, value, team="XX"):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": team,
        "rankDerivedValue": value,
        "sourceCount": 3,
        "assetClass": "offense",
    }


def _contract(league_key="main"):
    return {
        "meta": {"leagueKey": league_key},
        "playersArray": [
            _row("qb1", "Star QB", "QB", 8000, "BUF"),
            _row("te1", "Weak TE", "TE", 900, "MIN"),
            _row("wr1", "Bench WR", "WR", 3000, "CIN"),
            _row("wr2", "Deep WR", "WR", 400, "CIN"),
            _row("fa1", "Free TE", "TE", 2600, "DAL"),
            _row("fa2", "Free WR", "WR", 2500, "DAL"),
            _row("o1", "Other QB", "QB", 7000, "KC"),
        ],
        "sleeper": {
            "rosterPositions": ["QB", "TE", "BN", "BN", "BN"],
            "teams": [
                {
                    "ownerId": "me",
                    "name": "Mine",
                    "roster_id": 1,
                    "players": ["Star QB", "Weak TE", "Bench WR", "Deep WR"],
                    "playerIds": ["qb1", "te1", "wr1", "wr2"],
                    "faabBudget": 100,
                    "faabRemaining": 60,
                },
                {
                    "ownerId": "them",
                    "name": "Theirs",
                    "roster_id": 2,
                    "players": ["Other QB"],
                    "playerIds": ["o1"],
                    "faabBudget": 100,
                    "faabRemaining": 100,
                },
            ],
        },
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "111",
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "rosterSize": 4},
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "222",
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "rosterSize": 4},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    def _session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        return {"username": user, "auth_method": "password"} if user else None

    monkeypatch.setattr(server, "_get_auth_session", _session)
    # No live Sleeper: the plan runs on the contract's own rosters.
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **_kw: None)
    contract = _contract()
    monkeypatch.setattr(server, "latest_contract_data", contract)
    server._PERFECT_WAIVERS_CACHE.clear()
    # No ``with``: the lifespan would load the real board over this fixture.
    client = TestClient(server.app, raise_server_exceptions=True)
    yield SimpleNamespace(client=client, contract=contract)
    league_registry.reload_registry()


AS = {"x-test-user": "alice"}


def test_anonymous_is_401(env):
    res = env.client.post(URL, json={"teamOwnerId": "me"})
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"


def test_503_when_no_contract(env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", {})
    res = env.client.post(URL, json={"teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_503_data_not_ready_on_league_mismatch(env):
    res = env.client.post(URL, json={"leagueKey": "side", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_team_is_required_and_never_guessed(env):
    res = env.client.post(URL, json={"leagueKey": "main"}, headers=AS)
    assert res.status_code == 400
    assert res.json()["error"] == "team_required"
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "ghost"}, headers=AS)
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_team"


def test_200_plan_shape(env):
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["leagueKey"] == "main"
    assert body["advisoryOnly"] is True
    assert body["valuationMode"] == "market"
    assert body["rosterSource"] == "contract"
    assert body["solver"]["provenOptimal"] is True
    assert body["budget"]["state"] == "known" and body["budget"]["balance"] == 60
    assert body["capacity"]["rosterLimit"] == 4
    plan = body["plan"]
    assert plan["moves"], "a plan with clearly better free agents must move"
    # The market-aware engine priced these claims (two-team league, a flush
    # rival), and the plan spends no more than the balance.
    assert body["budget"]["bidMethodology"] == "market_aware"
    assert plan["totalRecommendedBid"] <= body["budget"]["balance"]
    assert all(m["standsAlone"] and m["material"] for m in plan["moves"])
    # Weak TE may only leave if a TE arrives in the same plan.
    released = {m["release"].get("name") for m in plan["moves"]}
    added = {m["add"]["name"] for m in plan["moves"]}
    assert "Weak TE" not in released or "Free TE" in added


def test_saved_protection_is_never_proposed_as_a_drop(env):
    put = env.client.put(
        "/api/user/trade-protections",
        json={"leagueKey": "main", "untouchables": ["Weak TE"], "nflTeams": []},
        headers=AS,
    )
    assert put.status_code == 200, put.text
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 200, res.text
    body = res.json()
    released = {m["release"].get("name") for m in body["plan"]["moves"]}
    assert "Weak TE" not in released
    assert {r["name"] for r in body["constraints"]["protectedOnRoster"]} == {"Weak TE"}
    # Another user is unaffected by alice's protection.
    res = env.client.post(
        URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers={"x-test-user": "bob"}
    )
    assert res.json()["constraints"]["protectedOnRoster"] == []


def test_missing_stop_band_config_refuses_with_json(env, monkeypatch, tmp_path):
    from src.trade import perfect_waivers

    monkeypatch.setattr(perfect_waivers, "_CONFIG_PATH", tmp_path / "absent.json")
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json()["error"] == "perfect_waivers_unavailable"


def test_identical_request_is_served_from_cache_and_roster_change_busts_it(env, monkeypatch):
    from src.trade import perfect_waivers

    calls = {"n": 0}
    real = perfect_waivers.build_perfect_waivers

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(perfect_waivers, "build_perfect_waivers", counting)
    body = {"leagueKey": "main", "teamOwnerId": "me"}
    first = env.client.post(URL, json=body, headers=AS).json()
    second = env.client.post(URL, json=body, headers=AS).json()
    assert calls["n"] == 1 and first == second
    env.contract["sleeper"]["teams"][0]["faabRemaining"] = 59
    env.client.post(URL, json=body, headers=AS)
    assert calls["n"] == 2


@pytest.mark.parametrize("bad", [{"teamCount": "twelve"}, {"starters": {"QB": "one"}}])
def test_malformed_registry_answers_json_on_both_waiver_routes(env, monkeypatch, bad):
    settings = {"teamCount": 2, "rosterSize": 4, **bad}
    monkeypatch.setattr(
        server._league_registry, "get_league_roster_settings", lambda _key: dict(settings)
    )
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json()["error"] == "perfect_waivers_unavailable"
    res = env.client.post(
        "/api/waiver/suggestions", json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS
    )
    assert res.status_code == 500
    assert res.json()["error"].startswith("failed:")
