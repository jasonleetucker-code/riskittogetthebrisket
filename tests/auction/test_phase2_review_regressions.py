"""Regressions for the independent review of the Phase 2 fixes themselves."""

from __future__ import annotations

import asyncio
import threading

import httpx

from src.auction import engine, notify
from src.auction.store import _READ_POOL_MAX
from tests.auction.helpers import et
from tests.auction.test_api_store import (  # noqa: F401 - fixture import
    ORIGIN,
    _owner_client,
    _ready_room,
    env,
    idem,
)
from tests.auction.test_independent_recovery_audit import (
    NOON,
    FakePush,
    M,
    _capped_state,
    _comm,
    _device,
    _mkroom,
    _new_store,
    _outbox,
    nworld,  # noqa: F401 - fixture import
)


def test_reader_connections_are_pooled_not_leaked_per_thread(tmp_path):
    st, _ = _new_store(tmp_path)

    def use():
        with st.read() as conn:
            conn.execute("SELECT 1").fetchone()

    threads = [threading.Thread(target=use) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert st._pool.qsize() <= _READ_POOL_MAX
    st.close()
    assert st._pool.qsize() == 0


def test_concurrent_duplicate_admin_request_acts_once(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    before = float(st.room_row(room)["clock_offset"])
    headers = {**ORIGIN, "Idempotency-Key": "same-key-00000001"}

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", cookies=owner.cookies
        ) as c:
            return await asyncio.gather(
                *[
                    c.post(
                        f"/api/auction/rooms/{room}/clock",
                        json={"advanceSeconds": 3600},
                        headers=headers,
                    )
                    for _ in range(4)
                ]
            )

    results = asyncio.run(go())
    assert all(r.status_code in (200, 409) for r in results), [r.text for r in results]
    assert float(st.room_row(room)["clock_offset"]) - before == 3600


def test_link_tokens_are_never_stored_in_receipts(env):  # noqa: F811
    st, app = env
    owner = _owner_client(app)
    room = _ready_room(owner)
    h = idem()
    r = owner.post(f"/api/auction/rooms/{room}/invites", json={"seat": "S2"}, headers=h)
    assert r.status_code == 200
    token = r.json()["joinPath"].split("token=")[1]
    with st.read() as conn:
        bodies = [row[0] for row in conn.execute("SELECT body_json FROM route_receipts")]
    assert bodies and not any(token in b for b in bodies)
    again = owner.post(f"/api/auction/rooms/{room}/invites", json={"seat": "S2"}, headers=h)
    assert again.status_code == 409 and again.json()["error"] == "already_issued"


def test_a_delivered_push_is_never_resent_after_bookkeeping_fails(nworld, monkeypatch):  # noqa: F811
    st, room, tokens = nworld
    _device(st, 1, tokens[1])
    a = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 5, auction=a, max=9)  # S1 outbid → one push
    push = FakePush()
    real_write = st.write
    calls = {"n": 0}

    def flaky_write():
        calls["n"] += 1
        cm = real_write()
        if push.calls and calls["n"] == 3:  # the device-status update after the send
            raise RuntimeError("database is locked")
        return cm

    monkeypatch.setattr(st, "write", flaky_write)
    notify.dispatch_once(st, NOON + 6, sender=push)
    monkeypatch.setattr(st, "write", real_write)
    notify.dispatch_once(st, NOON + 400, sender=push)
    notify.dispatch_once(st, NOON + 4000, sender=push)
    assert len(push.calls) == 1
    assert [r["status"] for r in _outbox(st, 1)] == ["sent"]


def test_morning_reresolution_reports_the_displaced_leader():
    s, a1 = _capped_state()
    s, _, _ = _comm(s, "adjust_budget", et(2026, 10, 5, 22, 0), seat="S2", amount=100, reason="x")
    s, _, events = engine.apply_command(
        s, {"kind": "advance", "actor": {"role": "system"}}, et(2026, 10, 6, 8, 5)
    )
    kinds = {(e["type"], e["vis"]) for e in events}
    assert ("outbid", "seat:S1") in kinds
    assert ("proxy_leading", "seat:S2") in kinds or ("leading_again", "seat:S2") in kinds


def test_revision_announcements_never_go_backwards(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    rev = int(st.room_row(room)["revision"])
    st._notify(room, rev)
    st._notify(room, rev - 1)  # a slower thread's stale announcement
    assert st.cached_revision(room) == rev


def test_rooms_from_before_engine_rev_2_keep_their_played_behaviour():
    """A room without ``engine_rev`` replays exactly as it was played: its
    max history truncates at 50 and a paused-time credit is not deferred."""
    s, a1 = _capped_state()
    s = {k: v for k, v in s.items() if k != "engine_rev"}
    p, _, _ = _comm(s, "pause", NOON + 10, reason="hold")
    p, _, _ = _comm(p, "adjust_budget", NOON + 11, seat="S2", amount=100, reason="fix")
    assert "deferred_reresolve" not in p
    s2 = s
    for i in range(60):
        s2, _, _ = engine.apply_command(
            s2,
            {
                "kind": "bid",
                "actor": {"role": "manager", "seat": "S1"},
                "auction": a1,
                "max": 30 + i,
            },
            NOON + 30 + i,
        )
    assert len(s2["auctions"][a1]["bids"]["S1"]["hist"]) == 50
