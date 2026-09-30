"""Commissioner recovery tools, preflight and the points-for order preview."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.public_league import sleeper_client
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _cmd,
    _make_room,
    _owner_client,
    _ready_room,
    env,
)


def _invite_and_claim(app, owner, room, seat, handle):
    inv = owner.post(
        f"/api/auction/rooms/{room}/invites", json={"seat": seat}, headers=ORIGIN
    ).json()
    token = inv["joinPath"].split("token=")[1]
    c = TestClient(app)
    r = c.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": handle, "password": "first password 1"},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["id"]
    return c, uid


def test_reset_link_flow_revokes_old_sessions(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, uid = _invite_and_claim(app, owner, room, "S2", "alice")
    assert alice.get(f"/api/auction/rooms/{room}/view").status_code == 200
    # a manager cannot issue resets
    assert (
        alice.post(
            f"/api/auction/rooms/{room}/members/{uid}/reset-link", headers=ORIGIN
        ).status_code
        == 403
    )
    link = owner.post(f"/api/auction/rooms/{room}/members/{uid}/reset-link", headers=ORIGIN).json()[
        "resetPath"
    ]
    token = link.split("token=")[1]
    # the member's inbox says a reset was issued
    inbox = alice.get("/api/auction/notify/inbox").json()["items"]
    assert any("reset" in i["title"].lower() for i in inbox)
    fresh = TestClient(app)
    assert (
        fresh.post(
            "/api/auction/auth/reset", json={"token": token, "password": "short"}, headers=ORIGIN
        ).status_code
        == 400
    )
    r = fresh.post(
        "/api/auction/auth/reset",
        json={"token": token, "password": "a new password 2"},
        headers=ORIGIN,
    )
    assert r.status_code == 200
    assert alice.get(f"/api/auction/rooms/{room}/view").status_code == 401  # old session revoked
    assert fresh.get(f"/api/auction/rooms/{room}/view").status_code == 200
    again = TestClient(app).post(
        "/api/auction/auth/reset",
        json={"token": token, "password": "another pass 3"},
        headers=ORIGIN,
    )
    assert again.status_code == 404  # single use
    login = TestClient(app).post(
        "/api/auction/auth/login",
        json={"handle": "alice", "password": "a new password 2"},
        headers=ORIGIN,
    )
    assert login.status_code == 200


def test_site_owner_account_has_no_password_reset(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    me = owner.get("/api/auction/auth/me").json()["user"]["id"]
    r = owner.post(f"/api/auction/rooms/{room}/members/{me}/reset-link", headers=ORIGIN)
    assert r.status_code == 409


def test_replacing_a_lost_account_keeps_the_seats_money_and_bids(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, uid = _invite_and_claim(app, owner, room, "S2", "alice")
    aid = _cmd(owner, room, {"kind": "nominate", "player": "991"}).json()["auction"]
    assert _cmd(alice, room, {"kind": "bid", "auction": aid, "max": 30}).status_code == 200
    before, _, _ = st.load(room)
    assert (
        owner.post(
            f"/api/auction/rooms/{room}/members/{uid}/remove", json={}, headers=ORIGIN
        ).status_code
        == 400
    )
    r = owner.post(
        f"/api/auction/rooms/{room}/members/{uid}/remove",
        json={"reason": "lost phone + email"},
        headers=ORIGIN,
    )
    assert r.status_code == 200 and r.json()["seat"] == "S2"
    assert alice.get(f"/api/auction/rooms/{room}/view").status_code == 403
    after, _, _ = st.load(room)
    assert after == before  # the seat's money, bids and lead are untouched
    bob, _ = _invite_and_claim(app, owner, room, "S2", "bob")
    view = bob.get(f"/api/auction/rooms/{room}/view").json()
    assert view["me"]["seat"] == "S2" and view["me"]["private"]["my_bids"][0]["max"] == 30
    with st.read() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM audit WHERE action='member_removed'").fetchone()[0]
            == 1
        )


def test_preflight_reports_without_deciding(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _make_room(owner, budgetSource="equal", equalAmount=100, bots=True)["roomId"]
    out = owner.get(f"/api/auction/rooms/{room}/preflight").json()
    keys = {i["key"]: i for i in out["items"]}
    assert keys["budgets"]["status"] == "ok" and keys["room_type"]["status"] == "ok"
    assert keys["rules"]["status"] == "warn"  # mock: proposed rules unconfirmed is fine
    assert out["status"] in ("warn", "ok")


def test_points_for_preview_is_labelled_and_flags_ties(env, monkeypatch):  # noqa: F811
    st, app = env
    import sys

    sys.modules["server"].latest_contract_data["meta"] = {"leagueKey": "dynasty_main"}
    owner = _owner_client(app)
    room = _make_room(owner, budgetSource="equal", equalAmount=100)["roomId"]
    from src.api import league_registry

    monkeypatch.setattr(league_registry, "get_sleeper_league_id", lambda key=None: "L123")
    monkeypatch.setattr(
        sleeper_client, "fetch_league", lambda lid: {"season": "2026", "status": "in_season"}
    )
    rosters = [
        {
            "roster_id": i,
            "owner_id": f"u{i}",
            "settings": {"fpts": 100 + (i % 11) * 10, "fpts_decimal": 0},
        }
        for i in range(1, 13)
    ]
    monkeypatch.setattr(sleeper_client, "fetch_rosters", lambda lid: rosters)
    out = owner.get(f"/api/auction/rooms/{room}/points-for-preview").json()
    assert out["final"] is False and "PREVIEW ONLY" in out["note"]
    assert out["seatOrder"][0] in ("S11", "S1") and len(out["seatOrder"]) == 12
    assert out["ties"]  # rosters 1 and 12 tie at 110 → flagged, not silently broken
    assert all("owner_id" not in r for r in out["order"])
    # previewing changes nothing
    state, _, _ = st.load(room)
    assert state["order"] == [f"S{i}" for i in range(1, 13)]
