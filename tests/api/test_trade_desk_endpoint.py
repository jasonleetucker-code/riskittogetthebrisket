"""/api/user/trade-desk — private, per (user, leagueKey), user-entered statuses."""

from __future__ import annotations

import pytest

import server
from src.api import user_kv
from tests.api.test_trade_protections_endpoint import env  # noqa: F401 — fixture

URL = "/api/user/trade-desk"


def _as(user):
    return {"x-test-user": user}


@pytest.fixture()
def desk_env(env, monkeypatch):  # noqa: F811
    contract = {
        "meta": {"leagueKey": "main"},
        "playersArray": [],
        "sleeper": {
            "teams": [
                {"name": "Us", "ownerId": "1", "players": ["Our WR"]},
                {"name": "Them", "ownerId": "2", "players": ["Their RB"]},
            ]
        },
    }
    monkeypatch.setattr(server, "latest_contract_data", contract)
    return env


def _save(e, user="alice", **over):
    body = {
        "leagueKey": "main",
        "myTeam": "Us",
        "opponent": "Them",
        "send": [{"name": "Our WR"}],
        "receive": [{"name": "Their RB"}],
        "source": "package_builder",
    }
    body.update(over)
    return e.client.post(URL, json=body, headers=_as(user))


def test_anonymous_is_401_everywhere(desk_env):
    c = desk_env.client
    assert c.get(URL, params={"leagueKey": "main"}).status_code == 401
    assert c.post(URL, json={}).status_code == 401
    assert c.patch(f"{URL}/0123456789abcdef", json={}).status_code == 401
    assert c.delete(f"{URL}/0123456789abcdef?leagueKey=main").status_code == 401


def test_league_must_be_named(desk_env):
    res = desk_env.client.get(URL, headers=_as("alice"))
    assert res.status_code == 400 and res.json()["error"] == "league_key_required"


def test_save_list_mark_and_remove_round_trip(desk_env):
    res = _save(desk_env)
    assert res.status_code == 201, res.text
    body = res.json()
    assert res.headers["cache-control"] == "no-store"
    assert body["count"] == 1 and body["action"] == "recommend_only"
    item = body["items"][0]
    assert item["status"] == "candidate"
    assert item["rosterCheck"]["state"] == "current"

    res = desk_env.client.patch(
        f"{URL}/{item['id']}",
        json={"leagueKey": "main", "status": "accepted", "note": "they said yes"},
        headers=_as("alice"),
    )
    assert res.status_code == 200, res.text
    got = res.json()["items"][0]
    assert got["status"] == "accepted" and got["note"] == "they said yes"
    assert got["statusHistory"][-1]["setBy"] == "user"

    listed = desk_env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice")).json()
    assert listed["items"][0]["status"] == "accepted"

    res = desk_env.client.delete(f"{URL}/{item['id']}?leagueKey=main", headers=_as("alice"))
    assert res.status_code == 200 and res.json()["count"] == 0


def test_desks_are_per_user_and_per_league(desk_env):
    assert _save(desk_env, "alice").status_code == 201
    bob = desk_env.client.get(URL, params={"leagueKey": "main"}, headers=_as("bob")).json()
    assert bob["count"] == 0
    other = desk_env.client.get(URL, params={"leagueKey": "backup"}, headers=_as("alice")).json()
    assert other["count"] == 0
    state = user_kv.get_user_state("alice")
    assert list(state["tradeDeskByLeague"]) == ["main"]


def test_duplicate_is_409_with_the_existing_id(desk_env):
    first = _save(desk_env).json()["items"][0]["id"]
    res = _save(desk_env)
    assert res.status_code == 409
    assert res.json() == {"error": "duplicate", "detail": {"id": first}}


def test_a_league_whose_teams_are_not_loaded_saves_nothing(desk_env):
    res = _save(desk_env, leagueKey="backup")
    assert res.status_code == 503 and res.json()["error"] == "data_not_ready"
    assert "tradeDeskByLeague" not in user_kv.get_user_state("alice")


def test_unknown_fields_and_bad_status_are_400(desk_env):
    res = _save(desk_env, execute=True)
    assert res.status_code == 400 and res.json()["unknownFields"] == ["execute"]
    item = _save(desk_env).json()["items"][0]
    res = desk_env.client.patch(
        f"{URL}/{item['id']}",
        json={"leagueKey": "main", "status": "sent_by_app"},
        headers=_as("alice"),
    )
    assert res.status_code == 400 and res.json()["error"] == "invalid_status"


def test_missing_item_is_404(desk_env):
    res = desk_env.client.patch(
        f"{URL}/0123456789abcdef",
        json={"leagueKey": "main", "status": "saved"},
        headers=_as("alice"),
    )
    assert res.status_code == 404


def test_guest_pass_cannot_write(desk_env, monkeypatch):
    monkeypatch.setattr(
        server, "_get_auth_session", lambda r: {"username": "guest", "auth_method": "guest_pass"}
    )
    assert _save(desk_env).status_code == 403
    res = desk_env.client.get(URL, params={"leagueKey": "main"})
    assert res.status_code == 200


def test_roster_check_flags_a_moved_player_without_touching_status(desk_env, monkeypatch):
    item = _save(desk_env).json()["items"][0]
    server.latest_contract_data["sleeper"]["teams"][1]["players"] = ["Someone Else"]
    got = desk_env.client.get(URL, params={"leagueKey": "main"}, headers=_as("alice")).json()
    check = got["items"][0]["rosterCheck"]
    assert check["state"] == "changed" and check["noLongerInPlace"] == ["Their RB"]
    assert got["items"][0]["status"] == item["status"]
