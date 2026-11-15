"""Rehearsal problem reports: traceable, private to reporter + commissioner,
idempotent, and never a room mutation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.auction import feedback
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _cmd,
    _owner_client,
    _ready_room,
    env,
)
from tests.auction.test_recovery import _invite_and_claim


def _report(c, room, body, key="report-key-0001"):
    return c.post(
        f"/api/auction/rooms/{room}/reports",
        json=body,
        headers={**ORIGIN, "Idempotency-Key": key},
    )


def test_report_pins_room_revision_rules_pool_and_code(env, monkeypatch):  # noqa: F811
    st, app = env
    monkeypatch.setattr(feedback, "_SHA", "a" * 40)
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, uid = _invite_and_claim(app, owner, room, "S2", "alice")
    view = alice.get(f"/api/auction/rooms/{room}/view").json()
    rev_before = view["revision"]

    r = _report(
        alice,
        room,
        {
            "what_happened": "My $5 bid showed as $6",
            "expected": "$5",
            "observed_when": "about 7:40 PM",
            "client_revision": rev_before,
        },
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["roomId"] == room
    assert rep["revision"] == rev_before
    assert rep["clientRevision"] == rev_before
    assert rep["seat"] == "S2" and rep["role"] == "manager"
    assert rep["roomType"] == "mock"
    assert rep["ruleVersion"] and rep["poolVersion"]
    assert rep["codeSha"] == "a" * 40
    assert rep["replayed"] is False

    # Filing a report is not a room command: the revision does not move.
    assert alice.get(f"/api/auction/rooms/{room}/view").json()["revision"] == rev_before

    # Same key → same report, not a duplicate.
    again = _report(alice, room, {"what_happened": "My $5 bid showed as $6"})
    assert again.json()["id"] == rep["id"] and again.json()["replayed"] is True


def test_report_names_a_lot_and_validates_it(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    state, _, _ = st.load(room)
    player = next(iter(state["pool"]["players"]))
    nom = _cmd(owner, room, {"kind": "nominate", "player": player, "max_bid": 0})
    assert nom.status_code == 200, nom.text
    state, _, _ = st.load(room)
    aid = state["auction_order"][-1]
    ok = _report(owner, room, {"what_happened": "timer looked wrong", "auction": aid})
    assert ok.status_code == 200 and ok.json()["playerId"] == player
    bad = _report(owner, room, {"what_happened": "x", "auction": "nope"}, key="report-key-0002")
    assert bad.status_code == 404
    empty = _report(owner, room, {"what_happened": "  "}, key="report-key-0003")
    assert empty.status_code == 400


def test_reports_are_private_to_reporter_and_commissioner(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, _ = _invite_and_claim(app, owner, room, "S2", "alice")
    bob, _ = _invite_and_claim(app, owner, room, "S3", "bob")
    assert _report(alice, room, {"what_happened": "alice saw a thing"}).status_code == 200
    assert _report(bob, room, {"what_happened": "bob saw a thing"}).status_code == 200

    mine = alice.get(f"/api/auction/rooms/{room}/reports").json()["reports"]
    assert [r["whatHappened"] for r in mine] == ["alice saw a thing"]
    everyone = owner.get(f"/api/auction/rooms/{room}/reports").json()["reports"]
    assert {r["whatHappened"] for r in everyone} == {"alice saw a thing", "bob saw a thing"}
    # Outsiders get nothing.
    assert TestClient(app).get(f"/api/auction/rooms/{room}/reports").status_code == 401


def test_report_requires_origin_and_idempotency_key(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    no_key = owner.post(
        f"/api/auction/rooms/{room}/reports", json={"what_happened": "x"}, headers=ORIGIN
    )
    assert no_key.status_code == 400
    no_origin = owner.post(
        f"/api/auction/rooms/{room}/reports",
        json={"what_happened": "x"},
        headers={"Idempotency-Key": "report-key-0009"},
    )
    assert no_origin.status_code == 403


def test_meta_and_preflight_name_the_deployed_code(env, monkeypatch):  # noqa: F811
    st, app = env
    monkeypatch.setattr(feedback, "_SHA", "b" * 40)
    owner = _owner_client(app)
    room = _ready_room(owner)
    assert TestClient(app).get("/api/auction/meta").json()["codeSha"] == "b" * 40
    assert owner.get(f"/api/auction/rooms/{room}/preflight").json()["codeSha"] == "b" * 40
