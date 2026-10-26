"""INDEPENDENT audit: persistence, crash recovery, restore, timers, notifications.

Written by an auditor who did not write the auction room, against
``docs/auction/ROOKIE_AUCTION_ROOM.md`` §2 (Time, Outage), §4, §5, §10, §12.
Temp directories only — nothing here touches ``data/auction``.

Areas
-----
A. process-crash fault injection (a real child process killed with
   ``os._exit`` at a chosen SQL statement or right after COMMIT);
B. restore drill through the real ``scripts/auction_backup_verify.py``;
C. quiet hours / extensions / outage pause on the real America/New_York
   calendar, including both DST boundaries;
D. notification semantics derived from final committed state;
E. long-poll / restart facts the server side owns (the client half is in
   ``frontend/__tests__/components/auction-room-revision.test.jsx``).

Every real defect found is pinned as ``xfail(strict=True)`` with a reason
starting ``AUDIT DEFECT`` — the xfail flips to a hard failure the moment the
defect is fixed, so the marker must then be removed.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import auction_backup_verify as abv
from src.auction import accounts, engine, notify, schedule
from src.auction.engine import AuctionError
from src.auction.store import open_store
from tests.auction.helpers import NOON, cmd, et, make_room

REPO = Path(__file__).resolve().parents[2]
H = 3600
FCM = "https://fcm.googleapis.com/fcm/send/"
OK_PUSH = {"ok": True, "gone": False, "status": 201, "retry_after": None, "error": None}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _new_store(tmp_path: Path, name: str = "live"):
    st = open_store(tmp_path / name / "auction" / "auction.sqlite")
    with st.write() as conn:
        for i in range(1, 7):
            conn.execute(
                "INSERT INTO users (id, handle, display_name, created_at) VALUES (?,?,?,0)",
                (i, f"u{i}", f"User {i}"),
            )
    tokens = {i: accounts.issue_session(st, i, NOON - 10 * 86400) for i in range(1, 7)}
    return st, tokens


SEAT_USERS = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}


def _mkroom(
    st,
    *,
    room_id="R1",
    budgets=None,
    seats=12,
    preset="official",
    rules_patch=None,
    start_at=NOON,
    row_type="official",
    seat_users=SEAT_USERS,
    commissioner=5,
):
    s = make_room(budgets, preset=preset, seats=seats, rules_patch=rules_patch)
    s["room_id"] = room_id
    st.create_room(s, created_by=1, now_real=start_at - 60)
    with st.write() as conn:
        # Engine state stays a mock (an official ENGINE room refuses to start
        # without confirmations); the store row type drives notifications.
        conn.execute("UPDATE rooms SET room_type=? WHERE id=?", (row_type, room_id))
        for seat, uid in (seat_users or {}).items():
            accounts.add_member(
                st, conn, room_id=room_id, user_id=uid, role="manager", seat_id=seat, now=start_at
            )
        if commissioner:
            accounts.add_member(
                st,
                conn,
                room_id=room_id,
                user_id=commissioner,
                role="commissioner",
                seat_id=None,
                now=start_at,
            )
    st.execute(
        room_id,
        {"kind": "start", "actor": {"role": "commissioner"}},
        user_id=None,
        now_real=start_at,
    )
    st.heartbeat([room_id], start_at)
    return room_id


def M(st, room, seat, kind, now, *, key=None, **kw):
    """A manager command, attributed to the seat's user when idempotent."""
    return st.execute(
        room,
        {"kind": kind, "actor": {"role": "manager", "seat": seat}, **kw},
        user_id=SEAT_USERS.get(seat) if key else None,
        now_real=now,
        idem_key=key,
    )


def C(st, room, kind, now, **kw):
    return st.execute(
        room,
        {"kind": kind, "actor": {"role": "commissioner", "user": 5}, **kw},
        user_id=None,
        now_real=now,
    )


def ADV(st, room, now):
    return st.execute(
        room, {"kind": "advance", "actor": {"role": "system"}}, user_id=None, now_real=now
    )


def _inbox(st, uid, typ=None):
    with st.read() as conn:
        rows = notify.inbox(conn, uid, limit=1000)
    return [r for r in rows if typ is None or r["type"] == typ]


def _device(st, uid, token, n=1):
    with st.write() as conn:
        return notify.register_device(
            conn,
            user_id=uid,
            session_token=token,
            sub={"endpoint": f"{FCM}dev{uid}-{n}", "keys": {"p256dh": "p" * 20, "auth": "a" * 16}},
            label=f"phone {uid}",
            platform="android",
            now=NOON - 5,
        )


def _outbox(st, uid=None):
    with st.read() as conn:
        rows = conn.execute(
            "SELECT o.*, i.type, i.logical_key FROM notif_outbox o JOIN notif_inbox i ON i.id=o.inbox_id"
            " ORDER BY o.id"
        ).fetchall()
    return [dict(r) for r in rows if uid is None or r["user_id"] == uid]


class FakePush:
    def __init__(self, fn=None):
        self.calls = []
        self.fn = fn

    def __call__(self, sub, payload, *, ttl, urgency="normal", topic=None):
        self.calls.append({"endpoint": sub["endpoint"], "payload": payload, "ttl": ttl})
        if self.fn:
            return self.fn(sub, payload)
        return dict(OK_PUSH)


def _snapshot(st, room):
    """Everything a crash could duplicate or lose."""
    state, rev, _ = st.load(room)
    with st.read() as conn:
        cmds = conn.execute("SELECT COUNT(*) FROM commands WHERE room_id=?", (room,)).fetchone()[0]
        awards = [
            tuple(r)
            for r in conn.execute(
                "SELECT player_id, seat_id, price FROM awards WHERE room_id=? ORDER BY player_id",
                (room,),
            )
        ]
        idem = conn.execute("SELECT COUNT(*) FROM idempotency WHERE room_id=?", (room,)).fetchone()[
            0
        ]
    return {
        "state": state,
        "revision": rev,
        "commands": cmds,
        "awards": awards,
        "idempotency": idem,
        "balances": {s["id"]: engine.balance(state, s["id"]) for s in state["seats"]},
    }


# -- the crash driver: a REAL child process that dies with os._exit ----------

_DRIVER = r"""
import json, os, sys
from pathlib import Path
spec = json.loads(sys.argv[1])
sys.path.insert(0, spec["repo"])
from src.auction import store as S
st = S.open_store(Path(spec["db"]))
trig = spec["trigger"]
if trig.startswith("sql:"):
    pat = trig[4:].upper()
    orig = S.Store.connect
    def connect(self):
        conn = orig(self)
        def cb(stmt):
            if " ".join(stmt.split()).upper().startswith(pat):
                os._exit(137)
        conn.set_trace_callback(cb)
        return conn
    S.Store.connect = connect
elif trig == "after_commit":
    def boom(self, room_id, revision):
        os._exit(137)
    S.Store._notify = boom
for step in spec["steps"]:
    op = step["op"]
    if op == "execute":
        st.execute(spec["room"], step["cmd"], user_id=step.get("user"),
                   now_real=step["now"], idem_key=step.get("key"))
    elif op == "runtime_advance":
        from src.auction import runtime
        S.reset_store_for_tests(st)
        runtime._advance_due(step["now"])
    elif op == "dispatch":
        from src.auction import notify
        ok = {"ok": True, "gone": False, "status": 201, "retry_after": None, "error": None}
        notify.dispatch_once(st, step["now"], sender=lambda *a, **k: dict(ok))
    elif op == "backup_crash_mid_gzip":
        sys.path.insert(0, str(Path(spec["repo"]) / "scripts"))
        from scripts import auction_backup_verify as abv
        def partial(fin, fout, *a, **k):
            fout.write(fin.read(4096))
            fout.flush()
            os._exit(137)
        abv.shutil.copyfileobj = partial
        abv.run(Path(spec["db"]), Path(step["dest"]), 48)
os._exit(0)
"""


def _crash(st, room, trigger, steps):
    spec = {"repo": str(REPO), "db": str(st.path), "room": room, "trigger": trigger, "steps": steps}
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER, json.dumps(spec)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert (
        proc.returncode == 137
    ), f"the fault was never injected (rc={proc.returncode}): {proc.stderr[-2000:]}"


def _bid_step(seat, auction, mx, now, key):
    return {
        "op": "execute",
        "cmd": {
            "kind": "bid",
            "actor": {"role": "manager", "seat": seat},
            "auction": auction,
            "max": mx,
        },
        "user": SEAT_USERS[seat],
        "now": now,
        "key": key,
    }


@pytest.fixture()
def crash_world(tmp_path):
    st, tokens = _new_store(tmp_path)
    room = _mkroom(st)
    aid = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 60, auction=aid, max=20)
    st.heartbeat([room], NOON + 60)
    return st, room, aid


# ===========================================================================
# A. Process-crash fault injection
# ===========================================================================


def test_A1_crash_just_before_commit_loses_nothing_acknowledged(crash_world):
    st, room, aid = crash_world
    before = _snapshot(st, room)
    _crash(st, room, "sql:COMMIT", [_bid_step("S3", aid, 30, NOON + 90, "key-crash-before-1")])
    st2 = open_store(st.path)  # "restart"
    after = _snapshot(st2, room)
    # Never acknowledged ⇒ never applied: no phantom bid, no receipt, no reset.
    assert after == before
    assert "S3" not in after["state"]["auctions"][aid]["bids"]
    assert st2.receipt(room, SEAT_USERS["S3"], "key-crash-before-1") is None
    # The client's retry with the SAME key applies exactly once.
    r1 = M(st2, room, "S3", "bid", NOON + 120, key="key-crash-before-1", auction=aid, max=30)
    r2 = M(st2, room, "S3", "bid", NOON + 130, key="key-crash-before-1", auction=aid, max=30)
    assert r1["status"] == 200 and not r1["replayed"]
    assert r2["replayed"] and r2["revision"] == r1["revision"] and r2["result"] == r1["result"]
    a = st2.load(room)[0]["auctions"][aid]
    assert (a["leader"], a["price"]) == ("S3", 21)
    assert st2.verify_room(room)["replay_matches"]


def test_A2_crash_after_commit_before_response_is_replayed_not_reapplied(crash_world):
    st, room, aid = crash_world
    before = _snapshot(st, room)
    _crash(st, room, "after_commit", [_bid_step("S3", aid, 30, NOON + 90, "key-crash-after-1")])
    st2 = open_store(st.path)
    after = _snapshot(st2, room)
    # Committed before the crash ⇒ durable (WAL + synchronous=FULL).
    assert after["revision"] == before["revision"] + 1
    assert after["commands"] == before["commands"] + 1
    receipt = st2.receipt(room, SEAT_USERS["S3"], "key-crash-after-1")
    assert receipt and receipt["status"] == 200 and receipt["result"]["leading"] is True
    bid_log_len = len(after["state"]["bid_log"])
    # The HTTP response was lost; the client retries with the same key.
    # (Restart inside the 5-min outage threshold; a longer gap would first
    # outage-pause the room — the replay is still the original result.)
    r = M(st2, room, "S3", "bid", NOON + 200, key="key-crash-after-1", auction=aid, max=30)
    assert (
        r["replayed"] and r["result"] == receipt["result"] and r["revision"] == receipt["revision"]
    )
    final = _snapshot(st2, room)
    assert final["revision"] == after["revision"]
    assert len(final["state"]["bid_log"]) == bid_log_len  # no duplicate bid
    # Same key, different payload: refused, never silently applied.
    with pytest.raises(AuctionError) as exc:
        M(st2, room, "S3", "bid", NOON + 410, key="key-crash-after-1", auction=aid, max=31)
    assert exc.value.code == "idempotency_conflict"


@pytest.mark.parametrize("gap_seconds", [70, 250])
def test_A3_crash_during_scheduler_settlement_then_quick_restart(crash_world, gap_seconds):
    """Runtime close dies mid-settlement (INSERT INTO awards).  A restart
    INSIDE the outage threshold must settle the lot exactly once at its own
    deadline and refuse the late bid that arrives first."""
    st, room, aid = crash_world
    D = st.load(room)[0]["auctions"][aid]["deadline"]
    st.heartbeat([room], D - 10)
    before = _snapshot(st, room)
    _crash(st, room, "sql:INSERT INTO awards", [{"op": "runtime_advance", "now": D + 1}])
    st2 = open_store(st.path)
    mid = _snapshot(st2, room)
    assert mid == before  # the half-done close rolled back entirely
    assert mid["state"]["auctions"][aid]["status"] == "open"
    # First thing after restart is a LATE bid (deadline passed during downtime).
    late = M(st2, room, "S3", "bid", D + gap_seconds, key="late-bid-0001", auction=aid, max=99)
    assert late["status"] == 409 and late["result"]["error"] == "closed"
    # Observation: a REJECTED command persists nothing, including the settlement
    # it computed first — the row stays 'open' (remaining 0) until the worker's
    # next advance.  Not a late-bid window: every command settles first.
    s = st2.load(room)[0]
    assert "S3" not in s["auctions"][aid]["bids"]
    ADV(st2, room, D + gap_seconds + 5)  # the worker catches up
    a = st2.load(room)[0]["auctions"][aid]
    assert (a["status"], a["winner"], a["price"], a["closed_at"]) == ("closed", "S2", 1, D)
    ADV(st2, room, D + gap_seconds + 10)  # and again: nothing new
    final = _snapshot(st2, room)
    assert final["awards"] == [("P1", "S2", 1)]  # one winner
    assert final["balances"]["S2"] == 99  # one debit
    assert st2.verify_room(room) == {
        **st2.verify_room(room),
        "replay_matches": True,
        "awards_match": True,
    }


def test_A3b_crash_during_settlement_then_long_outage_pauses_as_of_heartbeat(crash_world):
    st, room, aid = crash_world
    D = st.load(room)[0]["auctions"][aid]["deadline"]
    hb = D - 100
    st.heartbeat([room], hb)
    _crash(st, room, "sql:INSERT INTO awards", [{"op": "runtime_advance", "now": D + 1}])
    st2 = open_store(st.path)
    # Down for 10 minutes; a bid is the first request after restart.
    r = M(st2, room, "S3", "bid", D + 500, key="late-bid-0002", auction=aid, max=99)
    assert r["status"] == 409 and r["result"]["error"] == "paused"
    s = st2.load(room)[0]
    assert s["paused"]["kind"] == "outage" and s["paused"]["at"] == hb
    a = s["auctions"][aid]
    assert a["status"] == "open" and a["remaining"] == pytest.approx(100)
    assert _snapshot(st2, room)["awards"] == []  # nothing awarded through the gap
    # Commissioner resumes: outage floor gives at least one active hour.
    C(st2, room, "resume", D + 900)
    a = st2.load(room)[0]["auctions"][aid]
    win = schedule.ActiveWindow()
    assert schedule.active_between(win, D + 900, a["deadline"]) == pytest.approx(H)


def test_A4_crash_during_trade_settlement_is_all_or_nothing(crash_world):
    st, room, _ = crash_world
    t = M(st, room, "S1", "offer_trade", NOON + 100, to="S2", give_dollars=10)["result"]["trade"]
    st.heartbeat([room], NOON + 150)
    before = _snapshot(st, room)
    step = {
        "op": "execute",
        "cmd": {
            "kind": "respond_trade",
            "actor": {"role": "manager", "seat": "S2"},
            "trade": t,
            "version": 1,
            "accept": True,
        },
        "user": 2,
        "now": NOON + 160,
        "key": "trade-accept-01",
    }
    _crash(st, room, "sql:INSERT INTO events", [step])
    st2 = open_store(st.path)
    mid = _snapshot(st2, room)
    assert mid == before and mid["state"]["trades"][t]["status"] == "open"
    r = M(
        st2,
        room,
        "S2",
        "respond_trade",
        NOON + 200,
        key="trade-accept-01",
        trade=t,
        version=1,
        accept=True,
    )
    again = M(
        st2,
        room,
        "S2",
        "respond_trade",
        NOON + 210,
        key="trade-accept-01",
        trade=t,
        version=1,
        accept=True,
    )
    assert r["status"] == 200 and again["replayed"]
    final = _snapshot(st2, room)
    assert final["balances"]["S1"] == 90 and final["balances"]["S2"] == 110
    assert sum(final["balances"].values()) == sum(before["balances"].values())
    transfers = [e for e in final["state"]["ledger"] if e["kind"] == "transfer"]
    assert len(transfers) == 2  # exactly one settlement


def test_A5_crash_mid_outbox_claim_rolls_back_the_claim(crash_world, tmp_path):
    st, room, aid = crash_world
    tokens = {1: accounts.issue_session(st, 1, NOON)}
    _device(st, 1, tokens[1])
    M(st, room, "S3", "bid", NOON + 100, auction=aid, max=5)  # nominator S1 was outbid earlier
    M(st, room, "S1", "bid", NOON + 110, auction=aid, max=50)  # S1 retakes
    M(st, room, "S2", "bid", NOON + 120, auction=aid, max=60)  # S1 outbid again (device live)
    rows = _outbox(st, 1)
    assert rows and rows[-1]["status"] == "pending"
    _crash(
        st,
        room,
        "sql:UPDATE notif_outbox SET status='sending'",
        [{"op": "dispatch", "now": NOON + 125}],
    )
    st2 = open_store(st.path)
    row = _outbox(st2, 1)[-1]
    assert (row["status"], row["attempts"]) == ("pending", 0)


def test_A5b_crash_after_push_accepted_is_at_least_once_with_a_stable_tag(crash_world):
    st, room, aid = crash_world
    tok = accounts.issue_session(st, 1, NOON)
    _device(st, 1, tok)
    M(st, room, "S3", "bid", NOON + 100, auction=aid, max=5)
    M(st, room, "S1", "bid", NOON + 110, auction=aid, max=50)
    M(st, room, "S2", "bid", NOON + 120, auction=aid, max=60)
    state_before = st.load(room)

    class Crash(BaseException):
        pass

    def die(sub, payload):
        raise Crash()  # the push service accepted it; then the process died

    first = FakePush(die)
    with pytest.raises(Crash):
        notify.dispatch_once(st, NOON + 130, sender=first)
    st2 = open_store(st.path)
    assert st2.load(room) == state_before  # delivery never touches the bid
    second = FakePush()
    notify.dispatch_once(st2, NOON + 200, sender=second)  # < 120 s after claim
    assert second.calls == []
    notify.dispatch_once(st2, NOON + 260, sender=second)  # reclaimed
    assert len(second.calls) == 1
    assert second.calls[0]["payload"]["tag"] == first.calls[0]["payload"]["tag"]
    notify.dispatch_once(st2, NOON + 600, sender=second)
    assert len(second.calls) == 1  # delivered once more, then done
    assert _inbox(st2, 1, "outbid")  # the inbox stayed authoritative throughout


def test_A6_crash_during_backup_leaves_live_store_and_record_untouched(crash_world, tmp_path):
    st, room, _ = crash_world
    before = _snapshot(st, room)
    dest = tmp_path / "copies"
    _crash(st, room, "none", [{"op": "backup_crash_mid_gzip", "dest": str(dest)}])
    st2 = open_store(st.path)
    assert _snapshot(st2, room) == before
    with st2.read() as conn:
        assert (
            conn.execute("SELECT value FROM meta WHERE key='last_verified_backup'").fetchone()
            is None
        )
    # And the next scheduled run still works.
    assert abv.run(st2.path, dest, keep=48) == 0


def test_A6b_a_killed_backup_never_leaves_a_corrupt_archive_under_a_verified_name(
    crash_world, tmp_path
):
    st, room, _ = crash_world
    dest = tmp_path / "copies"
    _crash(st, room, "none", [{"op": "backup_crash_mid_gzip", "dest": str(dest)}])
    for gz in dest.glob("auction-*.sqlite.gz"):
        out = tmp_path / "probe.sqlite"
        with gzip.open(gz, "rb") as fin, open(out, "wb") as fout:
            shutil.copyfileobj(fin, fout)  # raises on a truncated stream
        with sqlite3.connect(out) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_A7_restart_never_resets_the_room(crash_world):
    st, room, aid = crash_world
    before = _snapshot(st, room)
    for _ in range(3):
        _crash(st, room, "sql:COMMIT", [_bid_step("S4", aid, 7, NOON + 90, "reset-probe-01")])
        st = open_store(st.path)
        assert _snapshot(st, room) == before
    with st.read() as conn:
        init = conn.execute("SELECT initial_state_json FROM rooms WHERE id=?", (room,)).fetchone()[
            0
        ]
    assert json.loads(init)["status"] == "setup" and before["state"]["status"] == "running"


# ===========================================================================
# B. Restore drill through the real backup script
# ===========================================================================


def _populated(tmp_path):
    """Bids, maxima, prices, money, awards, trades, rules, deadlines, pause
    state, identities, notification outbox/inbox — in one live store."""
    st, tokens = _new_store(tmp_path)
    accounts.set_password(st, 1, "correct horse battery staple", NOON - 100)
    for uid in (1, 2):
        _device(st, uid, tokens[uid])
    with st.write() as conn:
        notify.set_prefs(conn, 2, {"fifteen_min": True, "generic_previews": True}, NOON - 50)
    r1 = _mkroom(st, room_id="R1", budgets=[50, 100, 100, 100] + [100] * 8)
    r2 = _mkroom(st, room_id="R2", seat_users={}, commissioner=5)
    inv = accounts.create_invite(
        st, room_id=r1, seat_id="S5", role="manager", created_by=5, now=NOON
    )
    a1 = M(st, r1, "S4", "nominate", NOON + 10, player="P1")["result"]["auction"]
    a2 = M(st, r1, "S1", "nominate", NOON + 20, player="P2")["result"]["auction"]
    a3 = M(st, r1, "S3", "nominate", NOON + 30, player="P3")["result"]["auction"]
    M(st, r1, "S1", "bid", NOON + 40, key="k-s1-a2-45xx", auction=a2, max=45)
    M(st, r1, "S3", "bid", NOON + 50, key="k-s3-a2-40xx", auction=a2, max=40)
    M(st, r1, "S1", "bid", NOON + 60, key="k-s1-a1-30xx", auction=a1, max=30)  # capped
    M(st, r1, "S2", "bid", NOON + 70, key="k-s2-a1-20xx", auction=a1, max=20)
    M(st, r1, "S4", "set_queue", NOON + 80, players=["P9", "P10"], auto=True)
    C(st, r1, "adjust_budget", NOON + 90, seat="S4", amount=5, reason="audit correction")
    with st.write() as conn:
        conn.execute(
            "INSERT INTO notif_watch (room_id, user_id, auction_id, created_at) VALUES (?,?,?,?)",
            (r1, 2, a3, NOON + 95),
        )
    # Close every open lot (65 active hours later), then keep playing.
    D = st.load(r1)[0]["auctions"][a3]["deadline"]
    ADV(st, r1, D + 1)
    a4 = M(st, r1, "S2", "nominate", D + 10, player="P4")["result"]["auction"]
    M(st, r1, "S1", "bid", D + 20, key="k-s1-a4-11xx", auction=a4, max=5)
    M(st, r1, "S4", "bid", D + 30, key="k-s4-a4-09xx", auction=a4, max=3)
    t = M(st, r1, "S3", "offer_trade", D + 40, to="S4", give_lots=[a3], get_dollars=2)
    M(
        st,
        r1,
        "S4",
        "respond_trade",
        D + 50,
        key="k-s4-trade-1",
        trade=t["result"]["trade"],
        version=1,
        accept=True,
    )
    C(st, r2, "pause", NOON + 5, reason="commissioner hold")
    st.heartbeat([r1, r2], D + 60)
    return st, [r1, r2], inv, D + 60


def _table_dump(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        out = {}
        for t in tables:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            if t == "meta":
                rows = [r for r in rows if r[0] != "last_verified_backup"]
            out[t] = sorted(rows, key=repr)
        return out
    finally:
        conn.close()


def test_B_restore_drill_reproduces_every_field_and_measures_rto(tmp_path, capsys):
    st, rooms, invite_token, t_backup = _populated(tmp_path)
    dest = tmp_path / "copies"
    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "auction_backup_verify.py"),
            "--db",
            str(st.path),
            "--dest",
            str(dest),
            "--keep",
            "48",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
    )
    backup_s = time.perf_counter() - t0
    assert proc.returncode == 0, proc.stderr
    (archive,) = sorted(dest.glob("auction-*.sqlite.gz"))

    # --- restore onto a FRESH path, open it, replay, verify ---------------
    t1 = time.perf_counter()
    fresh = tmp_path / "restored-host" / "auction" / "auction.sqlite"
    fresh.parent.mkdir(parents=True)
    with gzip.open(archive, "rb") as fin, open(fresh, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    restored = open_store(fresh)
    reports = [restored.verify_room(r) for r in rooms]
    replays = {r: restored.replay(r) for r in rooms}
    rto_s = time.perf_counter() - t1

    assert all(rep["replay_matches"] and rep["awards_match"] for rep in reports)
    for r in rooms:
        assert replays[r] == st.load(r)[0]
    # Every row of every table — rooms, commands, events, idempotency receipts,
    # awards, audit, users (+pw hashes), sessions, members, invites, devices,
    # prefs, inbox, outbox, watch — is identical.
    src_dump, dst_dump = _table_dump(st.path), _table_dump(fresh)
    assert src_dump.keys() == dst_dump.keys()
    for table in src_dump:
        assert src_dump[table] == dst_dump[table], f"table {table} differs after restore"
    # Spot-check the money and private state through the engine.
    s_src, s_dst = st.load("R1")[0], restored.load("R1")[0]
    for seat in s_src["seats"]:
        sid = seat["id"]
        assert engine.spendable(s_src, sid) == engine.spendable(s_dst, sid)
        assert engine.seat_private_view(s_src, sid, t_backup) == engine.seat_private_view(
            s_dst, sid, t_backup
        )
    assert restored.load("R2")[0]["paused"]["reason"] == "commissioner hold"
    assert s_dst["rules"] == s_src["rules"] and s_dst["trades"] == s_src["trades"]
    assert accounts.authenticate(restored, "u1", "correct horse battery staple") is not None
    assert accounts.peek_invite(restored, invite_token, t_backup)  # identities travel
    with capsys.disabled():
        print(
            f"\n[AUDIT B] backup+self-verify {backup_s:.2f}s; restore(gunzip+open+verify+replay) "
            f"RTO {rto_s:.3f}s for {len(rooms)} rooms / {fresh.stat().st_size} bytes"
        )
    assert rto_s < 60


def test_B_rpo_is_pinned_by_the_hourly_timer():
    """RPO for a DATABASE fault (corruption, bad write) = time since the last
    VERIFIED hourly copy: at most 60 min + RandomizedDelaySec (2 min) + the
    backup's own runtime; longer whenever a run exits 1/2 (nothing alerts
    beyond the journal).  RPO for a PROCESS crash / power loss is 0 (WAL +
    synchronous=FULL — area A).  RPO for DISK/HOST loss is the last OFF-host
    copy (the nightly jobs, ~24 h per §4): the hourly copies live on the same
    disk."""
    timer = (REPO / "deploy/systemd/dynasty-auction-backup.timer.template").read_text()
    service = (REPO / "deploy/systemd/dynasty-auction-backup.service.template").read_text()
    assert "OnCalendar=*-*-* *:17:00 UTC" in timer
    assert "RandomizedDelaySec=120" in timer and "Persistent=true" in timer
    assert "TimeoutStartSec=600" in service
    rpo_db_fault_max = 3600 + 120 + 600
    assert rpo_db_fault_max == 4320  # 72 min worst case with a full-timeout run


def test_B_restored_copy_is_not_fenced_as_a_second_writer(tmp_path):
    """Documented finding (not code-enforced): a restored copy and the original
    can BOTH be opened and BOTH accept writes; they share one ``store_id`` and
    will mint the same revision numbers for different histories.  The only
    fence is operational (stop the service first) plus the outage guard: a
    copy restored >5 min after its last heartbeat comes up PAUSED."""
    st, rooms, _, t_backup = _populated(tmp_path)
    dest = tmp_path / "copies"
    assert abv.run(st.path, dest, keep=5) == 0
    (archive,) = sorted(dest.glob("*.gz"))
    fresh = tmp_path / "second" / "auction" / "auction.sqlite"
    fresh.parent.mkdir(parents=True)
    with gzip.open(archive, "rb") as fin, open(fresh, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    twin = open_store(fresh)
    with st.read() as a, twin.read() as b:
        sid_a = a.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]
        sid_b = b.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]
    assert sid_a == sid_b  # no identity/epoch distinguishes the copy
    s = st.load("R1")[0]
    open_lot = next(a["id"] for a in engine.open_auctions(s))
    # Restored promptly (inside the outage threshold): it takes bids too.
    r_live = M(st, "R1", "S2", "bid", t_backup + 30, auction=open_lot, max=50)
    r_twin = M(twin, "R1", "S3", "bid", t_backup + 30, auction=open_lot, max=50)
    assert r_live["status"] == r_twin["status"] == 200
    assert r_live["revision"] == r_twin["revision"]  # split brain: same rev, different history
    # Restored late: the outage guard pauses it instead of trading on stale state.
    late = open_store(fresh)
    with late.write() as conn:
        conn.execute("UPDATE rooms SET last_heartbeat=? WHERE id='R1'", (t_backup,))
    r = M(late, "R1", "S4", "bid", t_backup + 3600, key="late-twin-01", auction=open_lot, max=70)
    assert r["status"] == 409 and r["result"]["error"] == "paused"


# ===========================================================================
# C. Quiet hours and timers on the real calendar
# ===========================================================================

WIN = schedule.ActiveWindow()


def _hour_room(st, start_at, **kw):
    return _mkroom(st, rules_patch={"auction_active_seconds": H}, start_at=start_at, **kw)


def test_C1_one_active_hour_at_2030_closes_0830_next_day(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _hour_room(st, et(2026, 10, 5, 20, 0))
    aid = M(st, room, "S1", "nominate", et(2026, 10, 5, 20, 30), player="P1")["result"]["auction"]
    a = st.load(room)[0]["auctions"][aid]
    assert a["deadline"] == et(2026, 10, 6, 8, 30)
    for t in (et(2026, 10, 5, 23, 0), et(2026, 10, 6, 3, 0), et(2026, 10, 6, 8, 29, 59)):
        ADV(st, room, t)
        assert st.load(room)[0]["auctions"][aid]["status"] == "open"
    view = engine.public_view(st.load(room)[0], et(2026, 10, 6, 2, 0))
    assert view["auctions"][0]["remaining_active_seconds"] == 1800
    ADV(st, room, et(2026, 10, 6, 8, 30))
    a = st.load(room)[0]["auctions"][aid]
    assert (a["status"], a["closed_at"], a["winner"], a["price"]) == (
        "closed",
        et(2026, 10, 6, 8, 30),
        "S1",
        0,
    )


@pytest.mark.parametrize("hh,mm,ss", [(21, 0, 0), (21, 0, 1), (23, 30, 0), (3, 0, 0), (7, 59, 59)])
def test_C2_no_binding_action_between_2100_and_0800(tmp_path, hh, mm, ss):
    st, _ = _new_store(tmp_path)
    room = _hour_room(st, et(2026, 10, 5, 19, 0))
    aid = M(st, room, "S1", "nominate", et(2026, 10, 5, 20, 30), player="P1")["result"]["auction"]
    tr = M(st, room, "S1", "offer_trade", et(2026, 10, 5, 20, 40), to="S2", give_dollars=1)
    t = et(2026, 10, 5, hh, mm, ss) if hh >= 12 else et(2026, 10, 6, hh, mm, ss)
    rev = st.load(room)[1]
    for seat, kind, kw in (
        ("S2", "bid", {"auction": aid, "max": 5}),
        ("S2", "nominate", {"player": "P2"}),
        ("S3", "pass_nomination", {}),
        ("S3", "offer_trade", {"to": "S4", "give_dollars": 1}),
        ("S2", "respond_trade", {"trade": tr["result"]["trade"], "version": 1, "accept": True}),
    ):
        with pytest.raises(AuctionError) as exc:
            M(st, room, seat, kind, t, **kw)
        assert exc.value.code == "quiet_hours", (kind, exc.value.code)
    s, rev_after, _ = st.load(room)
    assert rev_after == rev and s["auctions"][aid]["price"] == 0
    # Edges of the window are open.
    assert M(st, room, "S2", "bid", et(2026, 10, 6, 8, 0), auction=aid, max=5)["status"] == 200


def test_C3_extension_is_max_of_deadline_and_now_plus_one_active_hour(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _hour_room(st, et(2026, 10, 5, 20, 0))
    aid = M(st, room, "S1", "nominate", et(2026, 10, 5, 20, 30), player="P1")["result"]["auction"]
    dl = lambda: st.load(room)[0]["auctions"][aid]  # noqa: E731
    M(st, room, "S2", "bid", et(2026, 10, 5, 20, 45), auction=aid, max=5)
    assert (dl()["leader"], dl()["deadline"]) == ("S2", et(2026, 10, 6, 8, 45))
    # A leader's private raise: no extension, no price change.
    M(st, room, "S2", "bid", et(2026, 10, 5, 20, 50), auction=aid, max=50)
    assert (dl()["deadline"], dl()["price"], dl()["extensions"]) == (et(2026, 10, 6, 8, 45), 1, 1)
    # A rival's competitive bid that only moves the price still extends.
    M(st, room, "S3", "bid", et(2026, 10, 5, 20, 55), auction=aid, max=3)
    assert (dl()["leader"], dl()["price"], dl()["deadline"]) == ("S2", 4, et(2026, 10, 6, 8, 55))
    # A competitive change far from the deadline never shortens it.
    st2, _ = _new_store(tmp_path, "far")
    room2 = _mkroom(st2)  # 65 active hours
    a2 = M(st2, room2, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    before = st2.load(room2)[0]["auctions"][a2]["deadline"]
    M(st2, room2, "S2", "bid", NOON + 60, auction=a2, max=5)
    after = st2.load(room2)[0]["auctions"][a2]
    assert after["deadline"] == before and after["extensions"] == 0


@pytest.mark.parametrize(
    "start,nominate,deadline,wall_hours",
    [
        # DST ends Sun 2026-11-01 02:00 EDT → 01:00 EST: the night is 1 h longer.
        ((2026, 10, 31, 20, 0), (2026, 10, 31, 20, 30), (2026, 11, 1, 8, 30), 13),
        # DST starts Sun 2027-03-14 02:00 EST → 03:00 EDT: the night is 1 h shorter.
        ((2027, 3, 13, 20, 0), (2027, 3, 13, 20, 30), (2027, 3, 14, 8, 30), 11),
    ],
)
def test_C4_dst_boundaries_keep_the_wall_clock_window(
    tmp_path, start, nominate, deadline, wall_hours
):
    st, _ = _new_store(tmp_path)
    room = _hour_room(st, et(*start))
    t = et(*nominate)
    aid = M(st, room, "S1", "nominate", t, player="P1")["result"]["auction"]
    d = st.load(room)[0]["auctions"][aid]["deadline"]
    assert d == et(*deadline) and d - t == wall_hours * H
    assert schedule.active_between(WIN, t, d) == H
    # Extension across the boundary is still one ACTIVE hour.
    t2 = t + 15 * 60
    M(st, room, "S2", "bid", t2, auction=aid, max=3)
    d2 = st.load(room)[0]["auctions"][aid]["deadline"]
    assert d2 == et(*deadline) + 15 * 60 and schedule.active_between(WIN, t2, d2) == H
    # No binding action in the shifted night.
    with pytest.raises(AuctionError) as exc:
        M(st, room, "S3", "bid", et(*deadline) - 2 * H, auction=aid, max=9)
    assert exc.value.code == "quiet_hours"


def _reminder_world(tmp_path):
    st, tokens = _new_store(tmp_path)
    room = _hour_room(st, et(2026, 10, 5, 20, 0))
    for uid in (1, 2, 3):
        _device(st, uid, tokens[uid])
    aid = M(st, room, "S1", "nominate", et(2026, 10, 5, 19 + 1, 29), player="P1")["result"][
        "auction"
    ]
    M(st, room, "S2", "bid", et(2026, 10, 5, 20, 29, 30), auction=aid, max=10)
    return st, room, aid


def _last_hour_rows(st):
    return [r for r in _outbox(st) if r["type"] == "last_hour"]


def test_C5_last_hour_reminder_is_never_delivered_stale_the_next_morning(tmp_path):
    st, room, aid = _reminder_world(tmp_path)
    # Scans in the quiet night generate nothing.
    for t in (et(2026, 10, 5, 21, 0), et(2026, 10, 6, 2, 0), et(2026, 10, 6, 7, 59)):
        assert notify.run_reminder_scan(st, t) == 0
    # (a) generated at 20:40 (rem 50 min), push service down until morning.
    assert notify.run_reminder_scan(st, et(2026, 10, 5, 20, 40)) >= 1
    down = FakePush(lambda sub, p: {"ok": False, "status": 503, "retry_after": None, "error": "x"})
    for t in (et(2026, 10, 5, 20, 41), et(2026, 10, 5, 20, 42), et(2026, 10, 5, 20, 45)):
        notify.dispatch_once(st, t, sender=down)
    morning = FakePush()
    notify.dispatch_once(st, et(2026, 10, 6, 8, 0), sender=morning)
    assert [c for c in morning.calls if "left" in c["payload"]["title"]] == []
    assert {r["status"] for r in _last_hour_rows(st)} <= {"failed", "expired_ttl", "sent"}


@pytest.mark.parametrize("change", ["extension", "settlement", "outbid"])
def test_C5b_pending_last_hour_reminder_is_dropped_after_state_change(tmp_path, change):
    st, room, aid = _reminder_world(tmp_path)
    notify.run_reminder_scan(st, et(2026, 10, 5, 20, 40))
    assert _last_hour_rows(st)
    if change == "extension":  # a rival bid on the leader's lot
        M(st, room, "S3", "bid", et(2026, 10, 5, 20, 50), auction=aid, max=5)
        t = et(2026, 10, 5, 20, 51)
    elif change == "outbid":  # the reminder told S2 "you are leading"
        M(st, room, "S3", "bid", et(2026, 10, 5, 20, 50), auction=aid, max=40)
        t = et(2026, 10, 5, 20, 51)
    else:  # sold at 08:30 before a delayed worker got to it
        ADV(st, room, et(2026, 10, 6, 8, 30))
        t = et(2026, 10, 6, 8, 31)
    push = FakePush()
    notify.dispatch_once(st, t, sender=push)
    stale_titles = [
        c["payload"]["title"] for c in push.calls if "1 active hour" in c["payload"]["title"]
    ]
    assert stale_titles == []


def test_C6_outage_pause_as_of_last_heartbeat_after_a_gap(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    aid = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    D = st.load(room)[0]["auctions"][aid]["deadline"]
    # 4-minute gap (< threshold): no pause; the lot settles at its own deadline.
    st.heartbeat([room], D - 60)
    st2 = open_store(st.path)
    ADV(st2, room, D + 180)
    s = st2.load(room)[0]
    assert s["paused"] is None and s["auctions"][aid]["closed_at"] == D

    # 6-minute gap: paused AS OF the heartbeat, not as of restart.
    st3, _ = _new_store(tmp_path, "b")
    room3 = _mkroom(st3)
    a3 = M(st3, room3, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    D3 = st3.load(room3)[0]["auctions"][a3]["deadline"]
    st3.heartbeat([room3], D3 - 30)
    st4 = open_store(st3.path)
    ADV(st4, room3, D3 - 30 + 360)
    s = st4.load(room3)[0]
    assert s["paused"]["kind"] == "outage" and s["paused"]["at"] == D3 - 30
    assert s["auctions"][a3]["status"] == "open" and s["auctions"][a3]["remaining"] == 30


def test_C6b_overnight_outage_pauses_the_room_and_preserves_every_second(tmp_path):
    """Observation: an outage wholly inside quiet hours (no clock could run)
    still pauses the room, which then stays paused through the morning until a
    commissioner resumes it (resume floors every lot to >=1 active hour)."""
    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    aid = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    hb = et(2026, 10, 5, 22, 0)
    st.heartbeat([room], hb)
    st2 = open_store(st.path)
    ADV(st2, room, et(2026, 10, 6, 7, 30))
    s = st2.load(room)[0]
    assert s["paused"]["kind"] == "outage"
    a = s["auctions"][aid]
    assert a["remaining"] == schedule.active_between(WIN, hb, a["deadline"])
    ADV(st2, room, et(2026, 10, 6, 10, 0))
    assert st2.load(room)[0]["paused"] is not None  # still frozen at 10 AM


def test_C6c_a_lagging_heartbeat_does_not_fake_an_outage_on_restart(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    aid = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    st.heartbeat([room], NOON)
    # The service is demonstrably reachable: bids keep committing for 7 min.
    for i, t in enumerate(range(60, 421, 60)):
        M(st, room, "S2" if i % 2 else "S3", "bid", NOON + t, auction=aid, max=10 + i)
    st2 = open_store(st.path)  # a 20-second deploy restart
    ADV(st2, room, NOON + 440)
    assert st2.load(room)[0]["paused"] is None


def _comm(s, kind, now, **kw):
    return engine.apply_command(s, {"kind": kind, "actor": {"role": "commissioner"}, **kw}, now)


def _capped_state():
    """S2 holds a $30 instruction on A1 but $25 of its $30 is reserved on A2."""
    s = make_room([100, 30, 100, 100], seats=4)
    s, _, _ = cmd(s, "start", NOON)
    s, r, _ = cmd(s, "nominate", NOON, seat="S2", player="P2")
    a2 = r["auction"]
    s, _, _ = cmd(s, "bid", NOON + 1, seat="S2", auction=a2, max=30)
    s, _, _ = cmd(s, "bid", NOON + 2, seat="S4", auction=a2, max=24)
    s, r, _ = cmd(s, "nominate", NOON + 3, seat="S3", player="P1")
    a1 = r["auction"]
    s, _, _ = cmd(s, "bid", NOON + 4, seat="S1", auction=a1, max=20)
    s, _, _ = cmd(s, "bid", NOON + 5, seat="S2", auction=a1, max=30)
    assert (s["auctions"][a1]["leader"], s["auctions"][a1]["price"]) == ("S1", 6)
    return s, a1


def test_C7_budget_correction_during_a_pause_reactivates_capped_proxies_on_resume():
    s, a1 = _capped_state()
    live, _, _ = _comm(s, "adjust_budget", NOON + 10, seat="S2", amount=100, reason="fix")
    assert (live["auctions"][a1]["leader"], live["auctions"][a1]["price"]) == ("S2", 21)
    p, _, _ = cmd(s, "pause", NOON + 10, reason="hold")
    p, _, _ = _comm(p, "adjust_budget", NOON + 11, seat="S2", amount=100, reason="fix")
    p, _, _ = cmd(p, "resume", NOON + 12)
    assert (p["auctions"][a1]["leader"], p["auctions"][a1]["price"]) == ("S2", 21)


def test_C7b_budget_correction_in_quiet_hours_does_not_move_leaders_overnight():
    s, a1 = _capped_state()
    night = et(2026, 10, 5, 22, 0)
    s2, _, events = _comm(s, "adjust_budget", night, seat="S2", amount=100, reason="fix")
    assert s2["auctions"][a1]["leader"] == "S1"
    assert not [e for e in events if e["type"] in ("price", "outbid")]


# ===========================================================================
# D. Notification semantics from final committed state
# ===========================================================================


@pytest.fixture()
def nworld(tmp_path):
    st, tokens = _new_store(tmp_path)
    room = _mkroom(st, budgets=[50] + [100] * 11)
    return st, room, tokens


def _rich_scenario(st, room):
    """Owner-shaped sequence exercising outbid / leading-again / capped."""
    a1 = M(st, room, "S4", "nominate", NOON + 1, player="P1")["result"]["auction"]
    a2 = M(st, room, "S1", "nominate", NOON + 2, player="P2")["result"]["auction"]
    M(st, room, "S1", "bid", NOON + 3, auction=a2, max=45)  # leader's private raise
    M(st, room, "S3", "bid", NOON + 4, auction=a2, max=40)  # S1 at 41 on a2
    M(st, room, "S1", "bid", NOON + 5, auction=a1, max=30)  # capped at 9 on a1
    M(st, room, "S2", "bid", NOON + 6, auction=a1, max=20)  # S1 outbid on a1 (capped)
    M(st, room, "S3", "bid", NOON + 7, auction=a2, max=60)  # S1 outbid a2 → retakes a1
    return a1, a2


def test_D_owner_example_50_vs_39_in_both_orders(nworld):
    st, room, _ = nworld
    a = M(st, room, "S3", "nominate", NOON + 1, player="P1")["result"]["auction"]
    M(st, room, "S1", "bid", NOON + 2, auction=a, max=50)
    M(st, room, "S2", "bid", NOON + 3, auction=a, max=39)
    x = st.load(room)[0]["auctions"][a]
    assert (x["leader"], x["price"]) == ("S1", 40)
    assert _inbox(st, 1, "outbid") == [] and _inbox(st, 1, "leading_again") == []
    assert _inbox(st, 2, "outbid") == []
    # Reverse order (B's $39 lands first) with two unencumbered $100 seats.
    b = M(st, room, "S5", "nominate", NOON + 4, player="P2")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 5, auction=b, max=39)  # B leads first
    M(st, room, "S4", "bid", NOON + 6, auction=b, max=50)  # A takes it at 40
    y = st.load(room)[0]["auctions"][b]
    assert (y["leader"], y["price"]) == ("S4", 40)
    assert _inbox(st, 4, "outbid") == [] and _inbox(st, 4, "leading_again") == []
    assert len(_inbox(st, 2, "outbid")) == 1  # B genuinely lost a lead


def test_D_types_turn_outbid_leading_again_capacity_won_and_zero_won(nworld):
    st, room, _ = nworld
    # 1. your nomination turn — every seated user is on the clock at start.
    for uid in (1, 2, 3, 4):
        assert len(_inbox(st, uid, "your_turn")) == 1
    a1, a2 = _rich_scenario(st, room)
    s = st.load(room)[0]
    assert (s["auctions"][a1]["leader"], s["auctions"][a1]["price"]) == ("S1", 21)
    # 3. genuinely outbid (twice: a1 capped, a2 plain) — 11. capacity condition.
    out = _inbox(st, 1, "outbid")
    assert len(out) == 2
    assert any("reserved on other lots" in r["body"] for r in out)
    # 4. genuinely leading again — restored by S3's action on a DIFFERENT lot.
    lead = _inbox(st, 1, "leading_again")
    assert len(lead) == 1 and "$21" in lead[0]["body"]
    assert len(_inbox(st, 2, "outbid")) == 1  # S2 lost a1
    # 5/6. won, including $0: close everything.
    a3 = M(st, room, "S2", "nominate", NOON + 8, player="P3")["result"]["auction"]
    D = s["auctions"][a2]["deadline"]
    ADV(st, room, D + 3600)
    won1 = _inbox(st, 1, "won")
    won2 = _inbox(st, 2, "won")
    assert any("$21" in r["body"] for r in won1)
    assert any("$0" in r["body"] and a3 for r in won2)


def test_D_types_turn_expiring_last_hour_trades_pause_resume(nworld):
    st, room, _ = nworld
    # 2. nomination deadline reminder: turns started Mon 12:00 pass Tue 12:00.
    assert notify.run_reminder_scan(st, et(2026, 10, 6, 11, 30)) > 0
    assert _inbox(st, 1, "turn_expiring")
    # 7. one active hour left.
    a = M(st, room, "S1", "nominate", et(2026, 10, 6, 11, 40), player="P1")["result"]["auction"]
    D = st.load(room)[0]["auctions"][a]["deadline"]
    notify.run_reminder_scan(st, D - 1800)
    lh = _inbox(st, 1, "last_hour")
    assert len(lh) == 1 and "closes" in lh[0]["body"]
    # 9/10. trade offer and dollar trade completed.
    t = M(st, room, "S2", "offer_trade", D - 1700, to="S3", give_dollars=7)["result"]["trade"]
    assert [r for r in _inbox(st, 3, "trade") if "offer" in r["title"].lower()]
    M(st, room, "S3", "respond_trade", D - 1600, trade=t, version=1, accept=True)
    assert [r for r in _inbox(st, 2, "trade") if r["title"] == "Trade completed"]
    assert [r for r in _inbox(st, 3, "trade") if "$7" in r["body"]]
    # 12/13. commissioner pause / resume.
    C(st, room, "pause", D - 1500, reason="dinner")
    C(st, room, "resume", D - 1400)
    kinds = {r["title"] for r in _inbox(st, 4, "room_status")}
    assert {"Auction paused", "Auction resumed"} <= kinds


def test_D_type_draft_completed(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _mkroom(
        st,
        seats=4,
        budgets=[10, 10, 10, 10],
        preset="fast",
        rules_patch={"rounds": 1},
        row_type="official",
    )
    for i, seat in enumerate(("S1", "S2", "S3", "S4")):
        M(st, room, seat, "nominate", NOON + i, player=f"P{i + 1}")
    ADV(st, room, NOON + 3600)
    assert st.load(room)[0]["status"] == "complete"
    for uid in (1, 2, 3, 4):
        assert [r for r in _inbox(st, uid, "room_status") if r["title"] == "Auction complete"]


def test_D_type_deadline_extended_is_notified(nworld):
    st, room, _ = nworld
    a = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 10, auction=a, max=5)  # S1 outbid, S2 leads
    D = st.load(room)[0]["auctions"][a]["deadline"]
    M(st, room, "S3", "bid", D - 600, auction=a, max=3)  # price moves → extends
    assert st.load(room)[0]["auctions"][a]["extensions"] == 1
    with st.read() as conn:
        types = {r[0] for r in conn.execute("SELECT DISTINCT type FROM notif_inbox")}
    assert types & {"deadline_extended", "extended", "extension"}


def test_D_capped_proxy_first_time_activation_is_notified(nworld):
    st, room, _ = nworld
    a2 = M(st, room, "S1", "nominate", NOON + 1, player="P2")["result"]["auction"]
    M(st, room, "S1", "bid", NOON + 2, auction=a2, max=45)
    M(st, room, "S3", "bid", NOON + 3, auction=a2, max=40)  # S1 leads a2 at 41 of $50
    a1 = M(st, room, "S4", "nominate", NOON + 4, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 5, auction=a1, max=20)  # S2 leads a1 at 1
    M(st, room, "S1", "bid", NOON + 6, auction=a1, max=30)  # S1 capped at 9 → S2 at 10
    assert st.load(room)[0]["auctions"][a1]["leader"] == "S2"
    n_before = len(_inbox(st, 1))
    M(st, room, "S3", "bid", NOON + 7, auction=a2, max=60)  # frees S1 → S1 takes a1 at 21
    assert st.load(room)[0]["auctions"][a1]["leader"] == "S1"
    new = _inbox(st, 1)[: len(_inbox(st, 1)) - n_before]
    assert any(r["type"] != "outbid" for r in new), [r["type"] for r in new]


def test_D_your_turn_that_starts_during_a_pause_is_sent_on_resume(tmp_path):
    st, _ = _new_store(tmp_path)
    room = _mkroom(st, seats=4, budgets=[100] * 4, rules_patch={"max_open": 1})
    a = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    D = st.load(room)[0]["auctions"][a]["deadline"]
    C(st, room, "pause", D + 5, reason="hold")  # worker had not settled the lot yet
    s = st.load(room)[0]
    assert s["auctions"][a]["status"] == "closed"
    assert any(r["seat"] == "S2" and r["window_at"] is not None for r in s["rights"])
    C(st, room, "resume", D + 60)
    assert _inbox(st, 2, "your_turn")


def test_D_no_text_contains_a_maximum_strategy_watchlist_or_credential(nworld):
    st, room, tokens = nworld
    with st.write() as conn:
        for uid in (1, 2, 3, 4):
            notify.set_prefs(conn, uid, {"new_nomination": True, "other_purchase": True}, NOON)
    a1, a2 = _rich_scenario(st, room)
    # A private, non-authorised queue must never surface anywhere.
    M(st, room, "S4", "set_queue", NOON + 8, players=["P33", "P34"], auto=False)
    with st.write() as conn:
        conn.execute(
            "INSERT INTO notif_watch (room_id, user_id, auction_id, created_at) VALUES (?,?,?,?)",
            (room, 3, a1, NOON),
        )
    a5 = M(st, room, "S2", "nominate", NOON + 9, player="P5")["result"]["auction"]
    M(st, room, "S1", "bid", NOON + 10, auction=a5, max=7)
    M(st, room, "S4", "bid", NOON + 11, auction=a5, max=6)  # price 7 = S1's max, allowed
    D = st.load(room)[0]["auctions"][a2]["deadline"]
    notify.run_reminder_scan(st, D - 1200)
    ADV(st, room, D + 3600)
    with st.read() as conn:
        rows = conn.execute("SELECT title, body, data_json FROM notif_inbox").fetchall()
        secrets_ = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        secrets_ += [
            r[0] for r in conn.execute("SELECT pw_hash FROM users WHERE pw_hash IS NOT NULL")
        ]
    text = " ".join(f"{r['title']} {r['body']} {r['data_json']}" for r in rows)
    assert rows
    for m in (45, 40, 30, 20, 60):  # every private maximum that never became a price
        assert f"${m}" not in text and f'"max": {m}' not in text
    for word in ("maximum", "proxy", "strategy", "watch", "queue", "Rookie 33", "Rookie 34"):
        assert word.lower() not in text.lower(), word
    for tok in list(tokens.values()) + secrets_:
        assert tok not in text


def test_D_push_transport_failure_never_rolls_back_a_bid(nworld):
    st, room, tokens = nworld
    _device(st, 1, tokens[1])
    a = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 5, auction=a, max=9)
    snap = _snapshot(st, room)
    bad = FakePush(lambda sub, p: {"ok": False, "status": 500, "retry_after": None, "error": "x"})
    notify.dispatch_once(st, NOON + 6, sender=bad)

    def explode(sub, p):
        raise RuntimeError("push library blew up")

    # The exception is contained per row (recorded as a retry), never raised
    # into the worker, and never touches the room.
    notify.dispatch_once(st, NOON + 400, sender=FakePush(explode))
    assert _snapshot(st, room) == snap
    assert len(_inbox(st, 1, "outbid")) == 1


def test_D_one_poisoned_outbox_row_does_not_block_other_users(nworld):
    st, room, tokens = nworld
    _device(st, 1, tokens[1])
    _device(st, 2, tokens[2])
    a = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 5, auction=a, max=9)  # S1 outbid (row first)
    M(st, room, "S3", "bid", NOON + 6, auction=a, max=19)  # S2 outbid
    first_uid = _outbox(st)[0]["user_id"]
    poison = f"{FCM}dev{first_uid}-1"

    def sender(sub, p):
        if sub["endpoint"] == poison:
            raise ValueError("malformed subscription")
        return dict(OK_PUSH)

    fp = FakePush(sender)
    for t in (NOON + 10, NOON + 140, NOON + 270, NOON + 400):
        try:
            notify.dispatch_once(st, t, sender=fp)
        except ValueError:
            pass
    other = [r for r in _outbox(st) if r["user_id"] != first_uid]
    assert other and all(r["status"] == "sent" for r in other)


# ===========================================================================
# E. Long-poll / restart facts owned by the server
# ===========================================================================


def test_E_restart_serves_the_persisted_revision_never_a_reset(crash_world):
    st, room, aid = crash_world
    rev = st.load(room)[1]
    assert st.cached_revision(room) == rev
    st2 = open_store(st.path)  # restart mid long-poll
    assert st2.cached_revision(room) is None  # the waiter falls back to the DB row
    assert int(st2.room_row(room)["revision"]) == rev
    M(st2, room, "S3", "bid", NOON + 100, auction=aid, max=30)
    assert st2.cached_revision(room) == rev + 1


def test_E_restore_rewinds_the_revision_clients_already_hold(tmp_path):
    """Server half of a client defect (see the vitest file): after a restore
    the room's revision goes BACKWARDS, and /view carries no store epoch, so a
    client holding a newer revision drops every post-restore snapshot as
    'stale' and keeps showing actions the restore lost."""
    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    aid = M(st, room, "S1", "nominate", NOON, player="P1")["result"]["auction"]
    dest = tmp_path / "copies"
    assert abv.run(st.path, dest, keep=5) == 0
    for i in range(3):  # acknowledged after the last hourly copy
        M(st, room, "S2", "bid", NOON + 10 + i, auction=aid, max=5 + i)
    client_rev = st.load(room)[1]
    (archive,) = sorted(dest.glob("*.gz"))
    fresh = tmp_path / "restored" / "auction" / "auction.sqlite"
    fresh.parent.mkdir(parents=True)
    with gzip.open(archive, "rb") as fin, open(fresh, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    restored_rev = open_store(fresh).load(room)[1]
    assert restored_rev < client_rev
