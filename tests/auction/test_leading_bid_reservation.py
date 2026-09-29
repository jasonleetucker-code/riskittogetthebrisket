"""Owner clarification 2026-09-29 — LEADING BIDS RESERVE MONEY.

"If a manager has $50 unspent and is the current leading bidder at $45, only
$5 is available for other auctions."  Every test here is that example or a
direct consequence of it, enforced server-side by the engine and the store.
"""

from __future__ import annotations

import threading

from src.auction import engine
from src.auction.store import open_store
from tests.auction.helpers import NOON, make_room


def _start(budgets):
    s = make_room(budgets, preset="fast")
    s, _, _ = engine.apply_command(s, {"kind": "start", "actor": {"role": "commissioner"}}, NOON)
    return s


def _do(s, kind, seat, now=NOON, **kw):
    return engine.apply_command(
        s, {"kind": kind, "actor": {"role": "manager", "seat": seat}, **kw}, now
    )


def _leading_at_45():
    """S1 has $50 and leads auction A1 at $45 (S2's maximum was $44)."""
    s = _start([50] + [100] * 11)
    s, r, _ = _do(s, "nominate", "S3", player="P1")
    a1 = r["auction"]
    s, _, _ = _do(s, "bid", "S1", auction=a1, max=50)
    s, _, _ = _do(s, "bid", "S2", auction=a1, max=44)
    assert (s["auctions"][a1]["leader"], s["auctions"][a1]["price"]) == ("S1", 45)
    return s, a1


def test_owner_example_only_five_dollars_available_elsewhere():
    s, a1 = _leading_at_45()
    assert engine.balance(s, "S1") == 50
    assert engine.committed(s, "S1") == 45
    assert engine.spendable(s, "S1") == 5
    view = engine.seat_private_view(s, "S1", NOON)
    assert (view["balance"], view["committed"], view["spendable"]) == (50, 45, 5)


def test_private_maximum_elsewhere_executes_only_to_five():
    s, a1 = _leading_at_45()
    s, r, _ = _do(s, "nominate", "S4", player="P2")
    a2 = r["auction"]
    s, res, _ = _do(s, "bid", "S1", auction=a2, max=30)  # stored $30, affordable $5
    assert res["capped"] and res["effective_max"] == 5
    s, _, _ = _do(s, "bid", "S5", auction=a2, max=20)
    # S1's $30 instruction cannot execute past $5: S5 leads at $6, not $21/$31.
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == ("S5", 6)
    assert engine.committed(s, "S1") == 45


def test_reservation_released_when_genuinely_outbid():
    s, a1 = _leading_at_45()
    s, r, _ = _do(s, "nominate", "S4", player="P2")
    a2 = r["auction"]
    s, _, _ = _do(s, "bid", "S1", auction=a2, max=30)
    s, _, _ = _do(s, "bid", "S5", auction=a2, max=20)  # S5 leads a2 @6 (S1 capped at 5)
    s, _, _ = _do(s, "bid", "S6", auction=a1, max=60)  # S1 genuinely outbid on a1
    assert s["auctions"][a1]["leader"] == "S6"
    # $45 released → S1's stored $30 on a2 is affordable again and responds.
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == ("S1", 21)
    assert engine.committed(s, "S1") == 21 and engine.spendable(s, "S1") == 29


def test_winning_converts_reservation_without_double_charge():
    s, a1 = _leading_at_45()
    s, _, _ = engine.apply_command(
        s, {"kind": "advance", "actor": {"role": "system"}}, s["auctions"][a1]["deadline"]
    )
    assert s["auctions"][a1]["status"] == "closed" and s["auctions"][a1]["winner"] == "S1"
    assert engine.balance(s, "S1") == 5  # 50 - 45, charged once
    assert engine.committed(s, "S1") == 0
    assert engine.spendable(s, "S1") == 5


def test_zero_dollar_bids_remain_legal_with_five_or_zero_left():
    s, a1 = _leading_at_45()
    s, r, _ = _do(s, "nominate", "S4", player="P2")  # opens at $0 (S4's nomination)
    a2 = r["auction"]
    s, res, _ = _do(s, "bid", "S1", auction=a2, max=0)  # legal $0 bid, loses the tie
    assert not res["leading"]
    # Spend the last $5 by winning a1 at $50 instead of $45.
    s, _, _ = _do(s, "bid", "S2", auction=a1, max=49)
    assert (s["auctions"][a1]["leader"], s["auctions"][a1]["price"]) == ("S1", 50)
    assert engine.spendable(s, "S1") == 0
    # With $0 available a $0 bid is still accepted; a $1 bid is refused by capacity.
    s, r3, _ = _do(s, "nominate", "S1", player="P3")  # nominating is a binding $0 bid
    assert s["auctions"][r3["auction"]]["leader"] == "S1"
    assert engine.committed(s, "S1") == 50


def test_two_simultaneous_requests_cannot_spend_the_same_dollars(tmp_path):
    """Two threads race to make S1 lead two different auctions with money it
    only has once.  The store serialises them; the second sees the first's
    reservation and executes only to what is left."""
    st = open_store(tmp_path / "auction" / "auction.sqlite")
    s = make_room([50] + [100] * 11, preset="fast")
    with st.write() as conn:
        conn.execute(
            "INSERT INTO users (id, handle, display_name, created_at) VALUES (1, 'owner', 'Owner', 0)"
        )
    st.create_room(s, created_by=1, now_real=NOON)
    st.execute(
        s["room_id"],
        {"kind": "start", "actor": {"role": "commissioner"}},
        user_id=None,
        now_real=NOON,
    )
    for seat, pid in (("S2", "P1"), ("S3", "P2")):
        st.execute(
            s["room_id"],
            {"kind": "nominate", "actor": {"role": "manager", "seat": seat}, "player": pid},
            user_id=None,
            now_real=NOON,
        )
    # Rivals already hold $40 maxima on both lots.
    for seat, aid in (("S4", "A1"), ("S5", "A2")):
        st.execute(
            s["room_id"],
            {"kind": "bid", "actor": {"role": "manager", "seat": seat}, "auction": aid, "max": 40},
            user_id=None,
            now_real=NOON,
        )
    barrier = threading.Barrier(2)
    errors = []

    def go(aid, key):
        barrier.wait()
        try:
            st.execute(
                s["room_id"],
                {
                    "kind": "bid",
                    "actor": {"role": "manager", "seat": "S1"},
                    "auction": aid,
                    "max": 50,
                },
                user_id=7,
                now_real=NOON + 1,
                idem_key=key,
            )
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=go, args=("A1", "race-key-A1")),
        threading.Thread(target=go, args=("A2", "race-key-A2")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final, _, _ = st.load(s["room_id"])
    lead = [a for a in final["auctions"].values() if a["leader"] == "S1"]
    assert len(lead) == 1 and lead[0]["price"] == 41  # S1 can beat $40 once, not twice
    assert engine.committed(final, "S1") <= engine.balance(final, "S1") == 50
    # Preserved across a restart: a fresh store over the same file agrees.
    again, _, _ = open_store(st.path).load(s["room_id"])
    assert engine.committed(again, "S1") == 41 and engine.spendable(again, "S1") == 9
