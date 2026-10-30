"""GET /api/roster-construction — flag, auth, league routing and payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, league_registry, user_kv
from tests.roster_intel.rc_support import build_snapshot, league_of, make_contract, positions_of

URL = "/api/roster-construction"
AS = {"x-test-user": "alice"}


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
                        "sleeperLeagueId": "RCMAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "rosterSize": 58},
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "RCSIDE",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "rosterSize": 27},
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
    teams = league_of(4)
    main = build_snapshot(teams, league_id="RCMAIN")
    side = build_snapshot(teams, best_ball=0, league_id="RCSIDE")
    built: list[str] = []

    def _build(league_id, *a, **k):
        built.append(league_id)
        return side

    monkeypatch.setattr(server, "_get_public_snapshot", lambda *a, **k: main)
    monkeypatch.setattr(server, "build_public_snapshot", _build)
    pos = positions_of(teams)
    contract = make_contract(
        "main", {rid: list(t) for rid, t in teams.items()}, {p: 1000.0 for p in pos}, pos
    )
    monkeypatch.setattr(server, "latest_contract_data", contract)
    for cache in (
        server._roster_construction_cache,
        server._rc_league_cache,
        server._rc_snapshot_cache,
        server._player_impact_cache,
    ):
        cache.clear()
    real = feature_flags.is_enabled
    state = {"on": True}
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name, *a, **k: state["on"] if name == "roster_construction" else real(name, *a, **k),
    )
    client = TestClient(server.app, raise_server_exceptions=True)
    yield type("E", (), {"client": client, "state": state, "contract": contract, "built": built})
    league_registry.reload_registry()


def test_flag_off_is_503_before_anything(env):
    env.state["on"] = False
    res = env.client.get(URL, headers=AS)
    assert res.status_code == 503
    assert res.json() == {"error": "feature_disabled", "flag": "roster_construction"}


def test_requires_a_session(env):
    res = env.client.get(URL)
    assert res.status_code == 401


def test_not_a_public_api_path():
    assert not server._is_public_api_path(URL)


def test_league_overview_without_team(env):
    res = env.client.get(URL, params={"leagueKey": "main"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert body["schemaVersion"] == "roster_construction.v1"
    assert body["leagueKey"] == "main"
    assert "team" not in body and len(body["teams"]) == 4
    assert res.headers["cache-control"] == "private, no-store"


def test_selected_team_payload_and_value_is_read_only(env):
    before = json.dumps(env.contract, sort_keys=True)
    res = env.client.get(URL, params={"leagueKey": "main", "rosterId": "2"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert body["team"]["rosterId"] == 2
    assert body["lineupBasis"] == "host_best_ball_optimal"
    assert body["valueBlock"]["available"] is True
    assert body["rules"]["rosterLimit"] == 58
    assert json.dumps(env.contract, sort_keys=True) == before


def test_managed_league_is_served_labelled_not_refused(env):
    res = env.client.get(URL, params={"leagueKey": "side", "rosterId": "1"}, headers=AS)
    assert res.status_code == 200
    body = res.json()
    assert env.built == ["RCSIDE"]
    assert body["lineupBasis"] == "hypothetical_optimal"
    assert body["valueBlock"] == {
        "available": False,
        "reason": "contract_league_mismatch",
        "asOf": None,
    }
    row = body["players"][0]
    assert row["marginalPoints"]["value"] is None
    assert row["marginalPoints"]["unavailableWeeks"]


def test_errors_are_named(env):
    assert env.client.get(URL, params={"leagueKey": "nope"}, headers=AS).status_code == 400
    r = env.client.get(URL, params={"leagueKey": "main", "season": "1999"}, headers=AS)
    assert r.status_code == 404 and r.json()["error"] == "unknown_season"
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "77"}, headers=AS)
    assert r.status_code == 404 and r.json()["error"] == "unknown_team"
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "x"}, headers=AS)
    assert r.status_code == 400 and r.json()["error"] == "invalid_roster_id"


def test_include_playoffs_parameter(env):
    r = env.client.get(URL, params={"leagueKey": "main", "includePlayoffs": "1"}, headers=AS)
    assert r.status_code == 200 and r.json()["rules"]["includePlayoffs"] is True


def test_error_responses_are_not_cacheable(env):
    cases = [
        ({}, AS),  # flag off below
        ({"leagueKey": "nope"}, AS),
        ({"leagueKey": "main", "rosterId": "x"}, AS),
        ({"leagueKey": "main", "season": "1999"}, AS),
        ({"leagueKey": "main"}, {}),
    ]
    for params, headers in cases:
        r = env.client.get(URL, params=params, headers=headers)
        assert "no-store" in (r.headers.get("cache-control") or ""), (params, r.status_code)
    env.state["on"] = False
    r = env.client.get(URL, headers=AS)
    assert r.status_code == 503 and r.headers["cache-control"] == "private, no-store"


def test_posture_failure_is_a_stable_code(env, monkeypatch):
    from src.api import gameplan

    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(gameplan, "league_competitive_postures", boom)
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.status_code == 200
    assert r.json()["team"]["posture"] == {"label": None, "reason": "posture_lookup_failed"}
    assert "RuntimeError" not in r.text and "secret detail" not in r.text


def test_posture_unavailable_carries_the_owner_reason_code(env, monkeypatch):
    from src.api import gameplan

    def unavailable(*a, **k):
        raise gameplan.GameplanUnavailable("bundle_not_built", "long prose")

    monkeypatch.setattr(gameplan, "league_competitive_postures", unavailable)
    r = env.client.get(URL, params={"leagueKey": "main", "rosterId": "1"}, headers=AS)
    assert r.json()["team"]["posture"]["reason"] == "posture_unavailable:bundle_not_built"
    assert "GameplanUnavailable" not in r.text
