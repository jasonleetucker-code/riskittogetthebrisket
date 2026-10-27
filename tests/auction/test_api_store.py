"""Store + HTTP integration for the auction room (no live server import)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.auction import accounts, api, runtime
from src.auction import store as store_mod
from src.auction.store import StoreUnavailable, open_store

ORIGIN = {"Origin": "http://testserver"}


def _contract():
    teams = [
        {"name": f"Owner{i}", "sleeperTeamName": f"Team {i}", "ownerId": f"u{i}", "roster_id": i}
        for i in range(1, 13)
    ]
    rows = [
        {
            "playerId": f"99{i}",
            "canonicalName": f"Rookie {i}",
            "position": "WR",
            "rookie": True,
            "rankDerivedValue": 5000 - i * 30,
        }
        for i in range(1, 60)
    ]
    rows.append(
        {
            "playerId": "1",
            "canonicalName": "Veteran",
            "position": "QB",
            "rookie": False,
            "rankDerivedValue": 9000,
        }
    )
    return {"sleeper": {"teams": teams}, "playersArray": rows, "meta": {}}


def _draft_capital():
    totals = [{"team": f"Team {i}", "auctionDollars": 100} for i in range(1, 12)]
    totals.append({"team": "Renamed Team", "auctionDollars": 100})  # Team 12 cannot be joined
    return {"season": 2027, "totalBudget": 1200, "numTeams": 12, "teamTotals": totals}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JASON_AUTH_COOKIE_SECURE", "0")  # TestClient speaks plain http
    st = open_store(tmp_path / "auction" / "auction.sqlite")
    store_mod.reset_store_for_tests(st)
    fake = types.ModuleType("server")
    fake.PRIVATE_APP_ALLOWED_USERNAMES = frozenset({"owner"})
    fake._get_auth_session = lambda req: (
        {"username": "owner", "displayName": "Owner"}
        if req.cookies.get("jason_session") == "site-admin"
        else None
    )
    fake.latest_contract_data = _contract()

    async def get_draft_capital(request):
        return _draft_capital()

    fake.get_draft_capital = get_draft_capital
    monkeypatch.setitem(sys.modules, "server", fake)
    app = FastAPI()
    app.include_router(api.router)
    yield st, app
    store_mod.reset_store_for_tests(None)


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


def _owner_client(app):
    c = TestClient(app)
    c.cookies.set("jason_session", "site-admin")
    r = c.post("/api/auction/auth/site-owner", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return c


_k = iter(range(10**6))
_ik = iter(range(10**6))


def idem() -> dict:
    """Same-origin headers plus a fresh Idempotency-Key (room-changing routes require one)."""
    return {**ORIGIN, "Idempotency-Key": f"route-{next(_ik):08d}"}


def _cmd(c, room, body, key=None):
    key = key or f"key-{next(_k):08d}"
    return c.post(
        f"/api/auction/rooms/{room}/commands", json=body, headers={**ORIGIN, "Idempotency-Key": key}
    )


def _make_room(c, **kw):
    body = {
        "name": "Mock",
        "preset": "fast",
        "seatSource": "league",
        "budgetSource": "draft_capital",
        "bots": False,
        **kw,
    }
    r = c.post("/api/auction/rooms", json=body, headers=idem())
    assert r.status_code == 200, r.text
    return r.json()


def test_origin_required_for_mutations(env):
    st, app = env
    c = TestClient(app)
    c.cookies.set("jason_session", "site-admin")
    assert c.post("/api/auction/auth/site-owner").status_code == 403
    assert (
        c.post(
            "/api/auction/auth/site-owner", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_league_budget_join_reports_missing_and_blocks_start(env):
    st, app = env
    c = _owner_client(app)
    out = _make_room(c)
    prov = out["budgetProvenance"]
    assert prov["unmatchedSeats"] == ["Team 12"]
    assert prov["unmatchedBudgetRows"] == ["renamed team"]
    room = out["roomId"]
    r = _cmd(c, room, {"kind": "start"})
    assert r.status_code == 409 and r.json()["error"] == "missing_budgets"
    r = _cmd(
        c,
        room,
        {
            "kind": "set_seat",
            "seat": "S12",
            "patch": {"opening_budget": 100},
            "reason": "renamed team",
        },
    )
    assert r.status_code == 200
    view = c.get(f"/api/auction/rooms/{room}/view").json()
    s12 = [s for s in view["public"]["seats"] if s["id"] == "S12"][0]
    assert s12["budget_source"] == "commissioner_override"
    # the veteran is excluded from the frozen pool
    pool = c.get(f"/api/auction/rooms/{room}/pool").json()
    assert "1" not in pool["players"] and not pool["isOfficialClass"]


def test_official_rooms_are_launch_gated(env):
    st, app = env
    c = _owner_client(app)
    r = c.post("/api/auction/rooms", json={"roomType": "official"}, headers=idem())
    assert r.status_code == 403 and r.json()["error"] == "official_launch_gated"


def test_non_admin_cannot_create_rooms(env):
    st, app = env
    c = TestClient(app)
    r = c.post("/api/auction/rooms", json={}, headers=idem())
    assert r.status_code == 401


def _ready_room(c, time_now=None):
    room = _make_room(c, budgetSource="equal", equalAmount=100)["roomId"]
    assert _cmd(c, room, {"kind": "start"}).status_code == 200
    return room


def test_invite_claim_bid_and_seat_isolation(env, monkeypatch):
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    inv = owner.post(
        f"/api/auction/rooms/{room}/invites",
        json={"seat": "S2", "intendedHandle": "alice"},
        headers=idem(),
    ).json()
    token = inv["joinPath"].split("token=")[1]
    peek = TestClient(app).get(f"/api/auction/invites/peek?token={token}").json()
    assert peek["seat"]["id"] == "S2"
    # A stranger who knows the public username still needs the token AND matching handle.
    stranger = TestClient(app)
    r = stranger.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": "mallory", "password": "x" * 12},
        headers=ORIGIN,
    )
    assert r.status_code == 403
    alice = TestClient(app)
    r = alice.post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": "alice", "password": "correct horse"},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    # single use
    r = TestClient(app).post(
        "/api/auction/invites/claim",
        json={"token": token, "handle": "alice2", "password": "y" * 12},
        headers=ORIGIN,
    )
    assert r.status_code == 404
    # owner (S1) nominates, alice bids from S2
    r = _cmd(owner, room, {"kind": "nominate", "player": "991"})
    assert r.status_code == 200, r.text
    aid = r.json()["auction"]
    r = _cmd(alice, room, {"kind": "bid", "auction": aid, "max": 37})
    assert r.status_code == 200 and r.json()["leading"]
    # alice cannot smuggle an actor/seat
    r = _cmd(
        alice,
        room,
        {"kind": "bid", "auction": aid, "max": 38, "actor": {"role": "commissioner", "seat": "S1"}},
    )
    view_owner = owner.get(f"/api/auction/rooms/{room}/view").json()
    assert _keys(view_owner["public"]).isdisjoint({"max", "bids", "bid_log", "queues"})
    assert all(not str(e["vis"]).startswith("seat:S2") for e in view_owner["events"])
    assert view_owner["me"]["private"]["my_bids"][0]["max"] == 0  # owner's own nomination bid only
    view_alice = alice.get(f"/api/auction/rooms/{room}/view").json()
    assert (
        view_alice["me"]["seat"] == "S2" and view_alice["me"]["private"]["my_bids"][0]["max"] == 38
    )
    # alice is not a commissioner
    assert _cmd(alice, room, {"kind": "pause", "reason": "x"}).status_code == 403
    # login round trip with the new password
    fresh = TestClient(app)
    assert (
        fresh.post(
            "/api/auction/auth/login",
            json={"handle": "alice", "password": "nope-nope-nope"},
            headers=ORIGIN,
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/api/auction/auth/login",
            json={"handle": "alice", "password": "correct horse"},
            headers=ORIGIN,
        ).status_code
        == 200
    )
    assert fresh.get(f"/api/auction/rooms/{room}/view").status_code == 200
    # non-member is refused
    other = TestClient(app)
    other.post(
        "/api/auction/invites/claim",
        json={"token": "bogus", "handle": "bob", "password": "z" * 12},
        headers=ORIGIN,
    )
    assert other.get(f"/api/auction/rooms/{room}/view").status_code == 401


def test_idempotency_replay_conflict_and_receipt(env):
    st, app = env
    c = _owner_client(app)
    room = _ready_room(c)
    r1 = _cmd(c, room, {"kind": "nominate", "player": "991"}, key="same-key-0001")
    r2 = _cmd(c, room, {"kind": "nominate", "player": "991"}, key="same-key-0001")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["replayed"] and r1.json()["auction"] == r2.json()["auction"]
    state, _, _ = st.load(room)
    assert len(state["auctions"]) == 1
    r3 = _cmd(c, room, {"kind": "nominate", "player": "992"}, key="same-key-0001")
    assert r3.status_code == 409 and r3.json()["error"] == "idempotency_conflict"
    rec = c.get(f"/api/auction/rooms/{room}/receipts/same-key-0001").json()
    assert rec["status"] == 200 and rec["result"]["auction"] == r1.json()["auction"]
    assert c.get(f"/api/auction/rooms/{room}/receipts/never-sent-000").status_code == 404
    # a rejected command's receipt is also durable
    r = _cmd(c, room, {"kind": "bid", "auction": "A1", "max": 10**9}, key="bad-amount-01")
    assert r.status_code == 400
    assert c.get(f"/api/auction/rooms/{room}/receipts/bad-amount-01").json()["status"] == 400
    assert _cmd(c, room, {"kind": "bid"}, key="x").status_code == 400  # key too short


def test_long_poll_wakes_on_commit(env):
    st, app = env
    c = _owner_client(app)
    room = _ready_room(c)
    rev = c.get(f"/api/auction/rooms/{room}/view").json()["revision"]
    t0 = time.monotonic()
    r = c.get(f"/api/auction/rooms/{room}/view?after={rev}&wait=0.6")
    assert r.json()["revision"] == rev and time.monotonic() - t0 >= 0.5
    _cmd(c, room, {"kind": "nominate", "player": "991"})
    r = c.get(f"/api/auction/rooms/{room}/view?after={rev}&wait=10")
    assert r.json()["revision"] > rev


def test_restart_recovery_replay_and_awards(env):
    st, app = env
    c = _owner_client(app)
    room = _ready_room(c)
    aid = _cmd(c, room, {"kind": "nominate", "player": "991"}).json()["auction"]
    _cmd(c, room, {"kind": "bid", "auction": aid, "max": 12})
    # jump the mock clock past the close
    assert (
        c.post(
            f"/api/auction/rooms/{room}/clock", json={"advanceSeconds": 3600}, headers=idem()
        ).status_code
        == 200
    )
    # "restart": a brand-new Store object over the same file
    st2 = open_store(st.path)
    state, revision, _ = st2.load(room)
    assert state["auctions"][aid]["status"] == "closed"
    report = st2.verify_room(room)
    assert report["replay_matches"] and report["awards_match"]
    with sqlite3.connect(st.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO awards VALUES (?,?,?,?,?,?)", (room, "991", "A9", "S3", 1, 0.0)
            )
    csv_text = c.get(f"/api/auction/rooms/{room}/export?format=csv").text
    assert "Rookie 1" in csv_text


def test_fail_closed_when_store_vanishes(env, tmp_path):
    st, app = env
    st.path.unlink()
    for suffix in ("-wal", "-shm"):
        p = st.path.with_name(st.path.name + suffix)
        if p.exists():
            p.unlink()
    with pytest.raises(StoreUnavailable):
        open_store(st.path)


def test_outage_check_pauses_instead_of_awarding(env):
    st, app = env
    c = _owner_client(app)
    room = _ready_room(c)
    aid = _cmd(c, room, {"kind": "nominate", "player": "991"}).json()["auction"]
    state, _, _ = st.load(room)
    deadline = state["auctions"][aid]["deadline"]
    # Pretend the process was down from 1 min after nomination until well past the deadline.
    hb = time.time() + 60
    with st.write() as conn:
        conn.execute("UPDATE rooms SET last_heartbeat=? WHERE id=?", (hb, room))
    paused = runtime.outage_check(deadline + 3600)
    assert paused == [room]
    state, _, _ = st.load(room)
    assert state["paused"]["kind"] == "outage"
    assert state["auctions"][aid]["status"] == "open"


def test_password_hashing_and_sessions(env):
    st, app = env
    h = accounts.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert accounts.verify_password("correct horse battery", h)
    assert not accounts.verify_password("wrong", h)
    assert not accounts.verify_password("anything", None)
    with st.read() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
    assert "token_hash" in cols and "token" not in cols


def test_bots_play_a_fast_mock_to_completion(env):
    st, app = env
    c = _owner_client(app)
    room = _make_room(c, budgetSource="equal", equalAmount=100, bots=True, preset="fast")["roomId"]
    with st.write() as conn:
        # smaller room so the test is quick: 1 round
        state = json.loads(
            conn.execute("SELECT state_json FROM rooms WHERE id=?", (room,)).fetchone()[0]
        )
        state["rules"]["rounds"] = 1
        conn.execute(
            "UPDATE rooms SET state_json=?, initial_state_json=? WHERE id=?",
            (json.dumps(state), json.dumps(state), room),
        )
    assert _cmd(c, room, {"kind": "start"}).status_code == 200
    # the owner (S1, human) nominates; bots act through the runtime path
    _cmd(c, room, {"kind": "nominate", "player": "991"})
    now = time.time()
    for step in range(200):
        runtime._run_bots(now)
        runtime._advance_due(now)
        state, _, off = st.load(room)
        if state["status"] == "complete":
            break
        now += 30  # real seconds; clock_offset stays 0
        with st.write() as conn:
            conn.execute("UPDATE rooms SET clock_offset=clock_offset+30 WHERE id=?", (room,))
        now -= 30
    state, _, _ = st.load(room)
    assert state["status"] == "complete"
    assert len([a for a in state["auctions"].values() if a["status"] == "closed"]) == 12
    assert st.verify_room(room)["replay_matches"]


def test_online_backup_restores_onto_a_fresh_environment(env, tmp_path):
    """The nightly jobs use sqlite3's online backup API (WAL-safe).  Restore
    that copy into an empty environment and re-verify everything."""
    st, app = env
    c = _owner_client(app)
    room = _ready_room(c)
    aid = _cmd(c, room, {"kind": "nominate", "player": "991"}).json()["auction"]
    _cmd(c, room, {"kind": "bid", "auction": aid, "max": 30})
    c.post(f"/api/auction/rooms/{room}/clock", json={"advanceSeconds": 3600}, headers=idem())
    _cmd(c, room, {"kind": "nominate", "player": "992"})  # an open lot with private state
    restored = tmp_path / "restored" / "auction" / "auction.sqlite"
    restored.parent.mkdir(parents=True)
    src = sqlite3.connect(st.path)
    dst = sqlite3.connect(restored)
    src.backup(dst)
    dst.close()
    src.close()
    st2 = open_store(restored)
    report = st2.verify_room(room)
    assert report == {**report, "replay_matches": True, "awards_match": True, "invariants_ok": True}
    before, rev_a, _ = st.load(room)
    after, rev_b, _ = st2.load(room)
    assert before == after and rev_a == rev_b
    # accounts and sessions travel with the backup (the owner can still act)
    with st2.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
