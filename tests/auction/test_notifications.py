"""AUC-002 — draft notifications (inbox + outbox + Web Push), fake transport only."""

from __future__ import annotations

import json

import pytest

from src.auction import accounts, engine, notify
from src.auction.engine import AuctionError
from src.auction.store import open_store
from tests.auction.helpers import NOON, et, make_room

FCM = "https://fcm.googleapis.com/fcm/send/"


class FakePush:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, sub, payload, *, ttl, urgency="normal", topic=None):
        self.calls.append(
            {"endpoint": sub["endpoint"], "payload": payload, "ttl": ttl, "urgency": urgency}
        )
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "gone": False, "status": 201, "retry_after": None, "error": None}


@pytest.fixture()
def world(tmp_path):
    st = open_store(tmp_path / "auction" / "auction.sqlite")
    users, tokens = {}, {}
    with st.write() as conn:
        for i in range(1, 5):
            conn.execute(
                "INSERT INTO users (id, handle, display_name, created_at) VALUES (?,?,?,0)",
                (i, f"u{i}", f"User {i}"),
            )
    for i in range(1, 5):
        users[f"S{i}"] = i
        tokens[i] = accounts.issue_session(st, i, NOON - 10)
    return st, users, tokens


def _room(
    st, *, budgets=None, room_type="official", preset="official", seats_to_users=None, room_id="R1"
):
    s = make_room(budgets, preset=preset)
    s["room_id"] = room_id
    # The ENGINE state stays a mock (an official engine room refuses to start
    # without confirmed rules + an approved pool); notification behaviour keys
    # off the STORE row's room_type, which is flipped to 'official' below.
    st.create_room(s, created_by=1, now_real=NOON - 60)
    with st.write() as conn:
        if room_type == "official":
            conn.execute("UPDATE rooms SET room_type='official' WHERE id=?", (room_id,))
        for seat, uid in (seats_to_users or {}).items():
            accounts.add_member(
                st, conn, room_id=room_id, user_id=uid, role="manager", seat_id=seat, now=NOON - 60
            )
    st.execute(
        room_id, {"kind": "start", "actor": {"role": "commissioner"}}, user_id=None, now_real=NOON
    )
    return room_id


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


def _cmd(st, room, seat, kind, now=NOON, **kw):
    return st.execute(
        room,
        {"kind": kind, "actor": {"role": "manager", "seat": seat}, **kw},
        user_id=None,
        now_real=now,
    )


def _inbox(st, uid, typ=None):
    with st.read() as conn:
        rows = notify.inbox(conn, uid)
    return [r for r in rows if typ is None or r["type"] == typ]


def _all_text(st):
    with st.read() as conn:
        return " ".join(
            r["title"] + " " + r["body"]
            for r in conn.execute("SELECT title, body FROM notif_inbox")
        )


# ---------------------------------------------------------------------------
# Proxy truth
# ---------------------------------------------------------------------------


def test_owner_example_50_vs_39_sends_no_outbid_leading_pair(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=50)
    _cmd(st, room, "S2", "bid", auction=aid, max=39)
    state, _, _ = st.load(room)
    assert (state["auctions"][aid]["leader"], state["auctions"][aid]["price"]) == ("S1", 40)
    assert _inbox(st, 1, "outbid") == [] and _inbox(st, 1, "leading_again") == []
    assert _inbox(st, 2, "outbid") == []  # B never led
    # the nominator S3 did lead at $0 and was genuinely displaced
    assert len(_inbox(st, 3, "outbid")) == 1


def test_genuine_outbid_then_restored_by_a_separate_event(world):
    st, users, tokens = world
    room = _room(st, budgets=[30, 100, 100, 100] + [100] * 8, seats_to_users=users)
    a1 = _cmd(st, room, "S2", "nominate", player="P1")["result"]["auction"]
    a2 = _cmd(st, room, "S3", "nominate", player="P2")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=a1, max=25)
    _cmd(st, room, "S4", "bid", auction=a1, max=20)  # S1 leads a1 @21
    _cmd(st, room, "S1", "bid", auction=a2, max=30)  # S1 leads a2 @1 (capacity 9)
    _cmd(st, room, "S4", "bid", auction=a2, max=15)  # S4 takes a2 @10: S1 outbid (capped)
    out = _inbox(st, 1, "outbid")
    assert len(out) == 1 and "limited your bid" in out[0]["body"]
    # A separate event (S2 outbids S1 on a1) frees S1's money → S1's capped
    # a2 maximum reactivates and restores the lead: genuine leading-again.
    _cmd(st, room, "S2", "bid", auction=a1, max=40)
    state, _, _ = st.load(room)
    assert state["auctions"][a2]["leader"] == "S1"
    assert len(_inbox(st, 1, "leading_again")) == 1
    assert len(_inbox(st, 1, "outbid")) == 2  # a1 as well — both true


def test_self_caused_retake_is_not_notified(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=10)
    _cmd(st, room, "S2", "bid", auction=aid, max=20)  # S1 outbid
    _cmd(st, room, "S1", "bid", auction=aid, max=30)  # S1 retakes by own action
    assert len(_inbox(st, 1, "outbid")) == 1
    assert _inbox(st, 1, "leading_again") == []


def test_zero_dollar_win_is_notified(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S1", "nominate", player="P1")["result"]["auction"]
    state, _, _ = st.load(room)
    st.execute(
        room,
        {"kind": "advance", "actor": {"role": "system"}},
        user_id=None,
        now_real=state["auctions"][aid]["deadline"],
    )
    won = _inbox(st, 1, "won")
    assert len(won) == 1 and "$0" in won[0]["body"]


def test_notifications_never_contain_private_maxima(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=87)
    _cmd(st, room, "S2", "bid", auction=aid, max=93)
    text = _all_text(st)
    assert "$87" not in text and "$93" not in text and "maximum of" not in text


def test_your_turn_only_when_you_can_nominate(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    # start put all 12 round-1 rights on the clock → each human seat told once
    assert all(len(_inbox(st, uid, "your_turn")) == 1 for uid in users.values())
    for i, seat in enumerate(
        ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
    ):
        _cmd(st, room, seat, "nominate", player=f"P{i + 1}")
    # board is full: no new turn notifications while nobody can nominate
    assert all(len(_inbox(st, uid, "your_turn")) == 1 for uid in users.values())


# ---------------------------------------------------------------------------
# Delivery worker
# ---------------------------------------------------------------------------


def test_dispatch_sends_after_commit_with_short_ttl_and_tag(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    room = _room(st, seats_to_users=users)
    push = FakePush()
    stats = notify.dispatch_once(st, NOON + 1, sender=push)
    assert stats["sent"] == 1
    call = push.calls[0]
    assert call["payload"]["url"] == f"/auction/{room}" and call["urgency"] == "high"
    assert 0 < call["ttl"] <= notify.TTL_SECONDS["your_turn"]
    assert notify.dispatch_once(st, NOON + 2, sender=push)["sent"] == 0  # no duplicate


def test_gone_subscription_is_disabled_and_retry_after_is_honoured(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    _device(st, 2, tokens[2])
    _room(st, seats_to_users={"S1": 1, "S2": 2})
    push = FakePush(
        [
            {"ok": False, "gone": True, "status": 410, "retry_after": None, "error": "gone"},
            {"ok": False, "gone": False, "status": 429, "retry_after": 120, "error": "slow down"},
        ]
    )
    stats = notify.dispatch_once(st, NOON + 1, sender=push)
    assert stats["gone"] == 1 and stats["retry"] == 1
    with st.read() as conn:
        devs = {d["user_id"]: d for d in conn.execute("SELECT * FROM notif_devices")}
        pending = conn.execute(
            "SELECT next_attempt_at FROM notif_outbox WHERE status='pending'"
        ).fetchall()
    assert devs[1]["disabled_reason"] == "expired_subscription"
    assert pending and pending[0]["next_attempt_at"] == pytest.approx(NOON + 1 + 120)
    assert notify.dispatch_once(st, NOON + 60, sender=push)["sent"] == 0  # not before Retry-After
    assert notify.dispatch_once(st, NOON + 125, sender=push)["sent"] == 1


def test_stale_outbid_is_not_sent(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    room = _room(st, seats_to_users=users)
    notify.dispatch_once(st, NOON + 1, sender=FakePush())  # flush turn alert
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=10)
    _cmd(st, room, "S2", "bid", auction=aid, max=20)  # S1 outbid
    _cmd(st, room, "S1", "bid", auction=aid, max=40)  # S1 leads again before dispatch
    push = FakePush()
    stats = notify.dispatch_once(st, NOON + 5, sender=push)
    assert stats["stale"] >= 1 and not any("Outbid" in c["payload"]["title"] for c in push.calls)


def test_quiet_hours_hold_until_0800_and_recheck(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    room = _room(st, seats_to_users=users)
    notify.dispatch_once(st, NOON + 1, sender=FakePush())
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=10)
    night = et(2026, 10, 5, 22)
    st.execute(
        room,
        {"kind": "pause", "actor": {"role": "commissioner"}, "reason": "test"},
        user_id=None,
        now_real=night,
    )
    with st.read() as conn:
        row = conn.execute(
            "SELECT o.next_attempt_at FROM notif_outbox o JOIN notif_inbox i ON i.id=o.inbox_id WHERE i.type='room_status'"
        ).fetchone()
    assert row["next_attempt_at"] == pytest.approx(et(2026, 10, 6, 8))
    assert notify.dispatch_once(st, night + 60, sender=FakePush())["sent"] == 0
    assert notify.dispatch_once(st, et(2026, 10, 6, 8, 0, 1), sender=FakePush())["sent"] == 1


def test_last_hour_reminder_keyed_to_deadline_and_bounded(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]
    _cmd(st, room, "S1", "bid", auction=aid, max=10)
    state, _, _ = st.load(room)
    d0 = state["auctions"][aid]["deadline"]
    t = d0 - 1800  # 30 active minutes left (deadline is within an active window)
    assert notify.run_reminder_scan(st, t) >= 1
    assert notify.run_reminder_scan(st, t + 10) == 0  # same deadline → deduped
    body = _inbox(st, 1, "last_hour")[0]["body"]
    assert "closes" in body and "9 PM–8 AM" in body
    # Extension → new deadline → old reminder becomes stale at dispatch.
    _cmd(st, room, "S2", "bid", auction=aid, max=20, now=t + 20)
    push = FakePush()
    notify.dispatch_once(st, t + 21, sender=push)
    assert not any("active hour left" in c["payload"]["title"] for c in push.calls)
    # at most MAX_LAST_HOUR_PER_LOT across repeated extensions
    for k in range(5):
        _cmd(st, room, "S1" if k % 2 else "S4", "bid", auction=aid, max=30 + k * 5, now=t + 30 + k)
        notify.run_reminder_scan(st, t + 31 + k)
    assert len(_inbox(st, 1, "last_hour")) <= notify.MAX_LAST_HOUR_PER_LOT


def test_notification_fault_never_rejects_a_bid(world, monkeypatch):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    aid = _cmd(st, room, "S3", "nominate", player="P1")["result"]["auction"]

    def boom(*a, **k):
        raise RuntimeError("notification bug")

    monkeypatch.setattr(notify, "record_transition", boom)
    out = _cmd(st, room, "S1", "bid", auction=aid, max=10)
    assert out["status"] == 200
    state, _, _ = st.load(room)
    assert state["auctions"][aid]["leader"] == "S1"
    with st.read() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit WHERE action='notification_record_failed'"
            ).fetchone()[0]
            == 1
        )


def test_mock_rooms_suppress_external_push_unless_opted_in(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    _device(st, 2, tokens[2])
    with st.write() as conn:
        notify.set_prefs(conn, 2, {"mock_push": True}, NOON)
    _room(st, room_type="mock", seats_to_users={"S1": 1, "S2": 2})
    push = FakePush()
    stats = notify.dispatch_once(st, NOON + 1, sender=push)
    assert stats["sent"] == 1 and push.calls[0]["endpoint"].endswith("dev2-1")
    assert push.calls[0]["payload"]["title"].startswith("[MOCK]")
    assert all(r["title"].startswith("[MOCK]") for r in _inbox(st, 1))  # inbox still records


def test_generic_previews_hide_details(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    with st.write() as conn:
        notify.set_prefs(conn, 1, {"generic_previews": True}, NOON)
    _room(st, seats_to_users={"S1": 1})
    push = FakePush()
    notify.dispatch_once(st, NOON + 1, sender=push)
    assert push.calls[0]["payload"]["title"] == "Chase Upside auction"


# ---------------------------------------------------------------------------
# Identity, devices, isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://169.254.169.254/latest",
        "https://evil.example.com/push",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com:8443/x",
        "https://fcm.googleapis.com.evil.com/x",
    ],
)
def test_arbitrary_endpoints_are_refused(world, endpoint):
    st, users, tokens = world
    with st.write() as conn, pytest.raises(AuctionError):
        notify.register_device(
            conn,
            user_id=1,
            session_token=tokens[1],
            sub={"endpoint": endpoint, "keys": {"p256dh": "p" * 20, "auth": "a" * 16}},
            label="",
            platform="",
            now=NOON,
        )


def test_apple_and_mozilla_endpoints_accepted(world):
    st, users, tokens = world
    for ep in (
        "https://web.push.apple.com/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
    ):
        notify.validate_subscription(
            {"endpoint": ep, "keys": {"p256dh": "p" * 20, "auth": "a" * 16}}
        )


def test_account_switch_moves_the_device_and_logout_silences_it(world):
    st, users, tokens = world
    _device(st, 1, tokens[1], n=7)
    with st.write() as conn:  # user 2 signs in on the SAME phone and subscribes
        notify.register_device(
            conn,
            user_id=2,
            session_token=tokens[2],
            sub={"endpoint": f"{FCM}dev1-7", "keys": {"p256dh": "p" * 20, "auth": "a" * 16}},
            label="",
            platform="",
            now=NOON,
        )
        assert notify._live_devices(conn, 1, NOON) == []
        assert len(notify._live_devices(conn, 2, NOON)) == 1
        notify.disable_devices_for_session(conn, tokens[2], NOON + 1)
        assert notify._live_devices(conn, 2, NOON + 2) == []


def test_revoked_session_silences_its_devices(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    accounts.revoke_all_sessions(st, 1, NOON)
    with st.read() as conn:
        assert notify._live_devices(conn, 1, NOON + 1) == []


def test_seat_reassignment_makes_queued_alerts_stale(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    room = _room(st, seats_to_users={"S1": 1})
    with st.write() as conn:
        conn.execute("UPDATE members SET removed_at=? WHERE room_id=? AND user_id=1", (NOON, room))
    stats = notify.dispatch_once(st, NOON + 1, sender=FakePush())
    assert stats["sent"] == 0 and stats["stale"] == 1


def test_cross_room_isolation(world):
    st, users, tokens = world
    _room(st, seats_to_users={"S1": 1}, room_id="RA")
    _room(st, seats_to_users={"S1": 2}, room_id="RB")
    assert {r["room_id"] for r in _inbox(st, 1)} == {"RA"}
    assert {r["room_id"] for r in _inbox(st, 2)} == {"RB"}


def test_test_notification_flow_records_confirmation(world):
    st, users, tokens = world
    _device(st, 1, tokens[1])
    ids = notify.queue_test(st, user_id=1, device_id=None, now_real=NOON)
    push = FakePush()
    assert notify.dispatch_once(st, NOON + 1, sender=push)["sent"] == 1
    with st.read() as conn:
        status = notify.delivery_status(conn, 1)
    assert status[0]["status"] == "sent" and status[0]["id"] == ids[0]  # accepted, not "displayed"


def test_email_backup_requires_verification(world):
    st, users, tokens = world
    with st.write() as conn:
        with pytest.raises(AuctionError):
            notify.set_prefs(conn, 1, {"email_backup": True}, NOON)
        token = notify.start_email_verification(conn, 1, "u1@example.com", NOON)
        assert not notify.verify_email(conn, 1, "wrong", NOON)
        assert notify.verify_email(conn, 1, token, NOON + 5)
        assert notify.set_prefs(conn, 1, {"email_backup": True}, NOON)["email_backup"]


def test_email_channel_sends_only_when_opted_in(world):
    st, users, tokens = world
    with st.write() as conn:
        token = notify.start_email_verification(conn, 1, "u1@example.com", NOON)
        notify.verify_email(conn, 1, token, NOON)
        notify.set_prefs(conn, 1, {"email_backup": True}, NOON)
    _room(st, seats_to_users={"S1": 1, "S2": 2})
    sent = []
    stats = notify.dispatch_once(
        st,
        NOON + 1,
        sender=FakePush(),
        email_sender=lambda to, s, b: (sent.append(to) or True, None),
    )
    assert sent == ["u1@example.com"] and stats["sent"] == 1  # user 2 never opted in


def test_inbox_rows_are_json_safe_and_engine_state_unchanged(world):
    st, users, tokens = world
    room = _room(st, seats_to_users=users)
    before, _, _ = st.load(room)
    notify.run_reminder_scan(st, NOON + 1)
    after, _, _ = st.load(room)
    assert before == after  # reminders never mutate the auction
    json.dumps(_inbox(st, 1))
    assert engine.check_invariants(after) is None
