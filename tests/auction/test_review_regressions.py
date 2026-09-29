"""Regression tests for the independent adversarial review (2026-09-29).

Each test reproduces a reviewer-confirmed defect and pins the fix.
"""

from __future__ import annotations

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from src.auction import engine
from src.auction.engine import AuctionError
from src.auction.store import StoreUnavailable, open_store
from tests.auction.helpers import NOON, cmd, make_room, nominate, started
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _cmd,
    _make_room,
    _owner_client,
    _ready_room,
    env,
)


def _claim(app, owner, room, seat, handle, role="manager"):
    body = {"seat": seat, "role": role} if seat else {"role": role}
    r = owner.post(f"/api/auction/rooms/{room}/invites", json=body, headers=ORIGIN)
    return r


# 1 — an observer can never hold a seat or read its maxima
def test_observer_invite_cannot_carry_a_seat(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    r = _claim(app, owner, room, "S3", "spy", role="observer")
    assert r.status_code == 400 and r.json()["error"] == "bad_role"
    ok = _claim(app, owner, room, None, "watcher", role="observer")
    token = ok.json()["joinPath"].split("token=")[1]
    obs = TestClient(app)
    obs.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": "watcher", "password": "watch pass 123"},
        headers=ORIGIN,
    )
    view = obs.get(f"/api/auction/rooms/{room}/view").json()
    assert (
        view["me"]["role"] == "observer"
        and view["me"]["seat"] is None
        and view["me"]["private"] is None
    )


# 2 — claiming an invite never moves an existing member (incl. the commissioner)
def test_existing_member_cannot_take_another_seat_via_invite(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    inv = _claim(app, owner, room, "S4", None).json()
    token = inv["joinPath"].split("token=")[1]
    r = owner.post("/api/auction/invites/claim", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "already_member"
    assert owner.get(f"/api/auction/rooms/{room}/view").json()["me"]["seat"] == "S1"


# 3 — a bot seat is not invitable; turning the bot off (mock) hands it over
def test_bot_seat_must_be_turned_off_before_inviting(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _make_room(owner, budgetSource="equal", equalAmount=100, bots=True)["roomId"]
    assert _cmd(owner, room, {"kind": "start"}).status_code == 200
    r = _claim(app, owner, room, "S2", None)
    assert r.status_code == 409 and r.json()["error"] == "bot_seat"
    assert (
        _cmd(
            owner,
            room,
            {"kind": "set_seat", "seat": "S2", "patch": {"is_bot": False}, "reason": "human joins"},
        ).status_code
        == 200
    )
    assert _claim(app, owner, room, "S2", None).status_code == 200
    state, _, _ = st.load(room)
    assert not any(
        c["actor"]["seat"] == "S2" for c in engine.bot_commands(state, time.time() + 3600)
    )


def test_official_rooms_cannot_flip_bots_after_start():
    s = started()
    s["room_type"] = "official"
    with pytest.raises(AuctionError):
        engine.apply_command(
            s,
            {
                "kind": "set_seat",
                "actor": {"role": "commissioner"},
                "seat": "S2",
                "patch": {"is_bot": True},
            },
            NOON,
        )


# 4 — a tie-winning leader's own raise never moves the price or the clock
def test_leader_private_raise_after_tie_changes_nothing_public():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = cmd(s, "bid", NOON, seat="S2", auction=aid, max=40)
    s, _, _ = cmd(s, "bid", NOON, seat="S3", auction=aid, max=40)
    a = s["auctions"][aid]
    assert (a["leader"], a["price"]) == ("S2", 40)
    late = a["deadline"] - 1800
    s2, _, ev = cmd(s, "bid", late, seat="S2", auction=aid, max=45)
    b = s2["auctions"][aid]
    assert (b["leader"], b["price"], b["extensions"], b["deadline"]) == ("S2", 40, 0, a["deadline"])
    assert not [e for e in ev if e["type"] == "price"]


def test_raise_then_reduce_keeps_the_original_tie_priority():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = cmd(s, "bid", NOON, seat="S2", auction=aid, max=40)  # S2 first at 40
    s, _, _ = cmd(s, "bid", NOON, seat="S3", auction=aid, max=40)  # tie → S2 @40
    s, _, _ = cmd(s, "bid", NOON, seat="S2", auction=aid, max=60)  # private raise
    s, _, _ = cmd(s, "bid", NOON, seat="S2", auction=aid, max=40)  # and back down
    s, _, _ = cmd(
        s, "bid", NOON, seat="S4", auction=aid, max=40
    )  # a competitive action re-resolves
    assert (s["auctions"][aid]["leader"], s["auctions"][aid]["price"]) == ("S2", 40)


def test_raise_earns_priority_only_for_new_levels():
    s = started()
    s, aid = nominate(s, "S5", "P1")
    s, _, _ = cmd(s, "bid", NOON, seat="S1", auction=aid, max=10)
    s, _, _ = cmd(s, "bid", NOON, seat="S2", auction=aid, max=30)
    s, _, _ = cmd(s, "bid", NOON, seat="S1", auction=aid, max=30)  # S1's 30 is newer than S2's
    assert (s["auctions"][aid]["leader"], s["auctions"][aid]["price"]) == ("S2", 30)


# 5 — losing the whole store directory fails closed
def test_whole_store_directory_loss_fails_closed(tmp_path):
    db = tmp_path / "data" / "auction" / "auction.sqlite"
    st = open_store(db)
    del st
    shutil.rmtree(db.parent)
    with pytest.raises(StoreUnavailable):
        open_store(db)


# 6 — the first command after an outage cannot settle across it
def test_first_command_after_restart_does_not_settle_the_outage(tmp_path):
    db = tmp_path / "auction" / "auction.sqlite"
    st = open_store(db)
    with st.write() as conn:
        conn.execute(
            "INSERT INTO users (id, handle, display_name, created_at) VALUES (1,'o','O',0)"
        )
    s = make_room(preset="fast")
    st.create_room(s, created_by=1, now_real=NOON)
    st.execute(
        s["room_id"],
        {"kind": "start", "actor": {"role": "commissioner"}},
        user_id=None,
        now_real=NOON,
    )
    r = st.execute(
        s["room_id"],
        {"kind": "nominate", "actor": {"role": "manager", "seat": "S1"}, "player": "P1"},
        user_id=None,
        now_real=NOON,
    )
    aid = r["result"]["auction"]
    # the process "dies"; two hours pass with no heartbeat; a new process starts
    later = NOON + 7200
    st2 = open_store(db)
    out = st2.execute(
        s["room_id"],
        {
            "kind": "set_queue",
            "actor": {"role": "manager", "seat": "S2"},
            "players": ["P2"],
            "auto": False,
        },
        user_id=None,
        now_real=later,
    )
    assert out["status"] == 200
    state, _, _ = st2.load(s["room_id"])
    assert state["paused"]["kind"] == "outage"
    assert state["auctions"][aid]["status"] == "open"  # not awarded across the outage


def test_commands_do_not_count_as_heartbeats(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    hb0 = st.room_row(room)["last_heartbeat"]
    _cmd(owner, room, {"kind": "nominate", "player": "991"})
    assert st.room_row(room)["last_heartbeat"] == hb0


# hardening
def test_bad_commissioner_inputs_are_400s_not_500s(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    _cmd(owner, room, {"kind": "pause", "reason": "x"})
    assert (
        _cmd(owner, room, {"kind": "resume", "min_remaining_active_seconds": "abc"}).status_code
        == 400
    )
    assert (
        _cmd(owner, room, {"kind": "resume", "min_remaining_active_seconds": 10**9}).status_code
        == 400
    )
    assert (
        _cmd(owner, room, {"kind": "set_seat", "seat": "S2", "patch": ["name"]}).status_code == 400
    )
    r = owner.post(
        f"/api/auction/rooms/{room}/invites", json={"seat": "S2", "ttlHours": "nan"}, headers=ORIGIN
    )
    assert r.status_code == 400


def test_official_room_must_match_binding_shape():
    s = make_room(room_type="official", rules_patch={"max_open": 6})
    s["rules"]["confirmations"] = {k: {"at": 0} for k in engine.unconfirmed_rules(s["rules"])}
    s["pool"]["is_official_class"] = True
    with pytest.raises(AuctionError) as e:
        engine.apply_command(s, {"kind": "start", "actor": {"role": "commissioner"}}, NOON)
    assert e.value.code == "binding_rules"


def test_more_than_twelve_open_lots_is_rejected():
    with pytest.raises(ValueError):
        from src.auction.rules import default_rules, validate_rules

        r = default_rules("fast")
        r["max_open"] = 13
        validate_rules(r)


def test_export_hides_sleeper_ids_from_managers(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    _cmd(owner, room, {"kind": "nominate", "player": "991"})
    owner.post(f"/api/auction/rooms/{room}/clock", json={"advanceSeconds": 3600}, headers=ORIGIN)
    inv = _claim(app, owner, room, "S2", None).json()
    token = inv["joinPath"].split("token=")[1]
    mgr = TestClient(app)
    mgr.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": "mgr", "password": "manager pass 1"},
        headers=ORIGIN,
    )
    rows = mgr.get(f"/api/auction/rooms/{room}/export").json()["results"]
    assert rows and "winnerSleeperUserId" not in rows[0]
    assert (
        "winnerSleeperUserId" in owner.get(f"/api/auction/rooms/{room}/export").json()["results"][0]
    )
