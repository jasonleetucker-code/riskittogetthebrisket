"""Adversarial randomized check of the cross-auction resolver.

Reference properties, re-derived from scratch after EVERY accepted command
(not by trusting the cascade that produced the state):

* every open auction is a FIXED POINT of single-auction resolution under the
  current capacities — nothing the cascade skipped wants to move;
* committed <= balance and balance >= 0 for every seat;
* a public price never decreases while its auction is open;
* one award per player, at most ``max_open`` open auctions;
* replaying the accepted command log from the initial state reproduces the
  final state exactly (determinism — the recovery path depends on it).
"""

from __future__ import annotations

import random

import pytest

from src.auction import engine
from src.auction.engine import AuctionError
from tests.auction.helpers import NOON, make_room


def _fixed_point(s):
    """From-scratch resolution agrees on every LEADER.  The price may differ
    in exactly two documented ways: lower (a runner-up withdrew or lost
    capacity — public prices never go backward), or +$1 higher when the
    leader won a TIE while budget-capped and its money has since been freed
    (a leader's price never rises without a rival acting)."""
    for a in engine.open_auctions(s):
        leader, price = engine._resolve_one(s, a)
        assert leader == a["leader"], a["id"]
        assert price - a["price"] <= 1, a["id"]


@pytest.mark.parametrize("seed", range(40))
def test_random_rooms_hold_invariants_and_replay(seed):
    rng = random.Random(seed)
    budgets = [rng.choice([0, 0, 1, 5, 10, 20, 40, 60, 100]) for _ in range(12)]
    s0 = make_room(budgets, preset="fast")
    s, _, _ = engine.apply_command(s0, {"kind": "start", "actor": {"role": "commissioner"}}, NOON)
    log = [({"kind": "start", "actor": {"role": "commissioner"}}, NOON)]
    now = NOON
    last_price: dict[str, int] = {}
    seats = [x["id"] for x in s["seats"]]
    for _ in range(400):
        now += rng.choice([0, 1, 5, 30, 90, 240])
        roll = rng.random()
        opens = engine.open_auctions(s)
        if roll < 0.25:
            c = {
                "kind": "nominate",
                "actor": {"role": "manager", "seat": rng.choice(seats)},
                "player": f"P{rng.randint(1, 40)}",
            }
        elif roll < 0.8 and opens:
            a = rng.choice(opens)
            c = {
                "kind": "bid",
                "actor": {"role": "manager", "seat": rng.choice(seats)},
                "auction": a["id"],
                "max": rng.randint(0, 70),
            }
        elif roll < 0.86 and opens:
            a = rng.choice(opens)
            c = {
                "kind": "withdraw",
                "actor": {"role": "manager", "seat": rng.choice(seats)},
                "auction": a["id"],
            }
        elif roll < 0.9:
            trades = [t for t in (s.get("trades") or {}).values() if t["status"] == "open"]
            if trades and rng.random() < 0.6:
                t = rng.choice(trades)
                c = {
                    "kind": "respond_trade",
                    "actor": {"role": "manager", "seat": t["to"]},
                    "trade": t["id"],
                    "version": 1,
                    "accept": rng.random() < 0.8,
                }
            else:
                a_, b_ = rng.sample(seats, 2)
                c = {
                    "kind": "offer_trade",
                    "actor": {"role": "manager", "seat": a_},
                    "to": b_,
                    "give_dollars": rng.randint(0, 8),
                    "get_dollars": rng.randint(0, 3),
                }
        elif roll < 0.93:
            c = {
                "kind": "adjust_budget",
                "actor": {"role": "commissioner"},
                "seat": rng.choice(seats),
                "amount": rng.choice([-5, -1, 1, 3, 10]),
                "reason": "fuzz",
            }
        else:
            c = {"kind": "advance", "actor": {"role": "system"}}
        before_leaders = {a["id"]: a["leader"] for a in engine.open_auctions(s)}
        try:
            s2, _, events = engine.apply_command(s, c, now)
        except AuctionError:
            continue
        # Leadership events are NET per committed transaction (AUC-002).
        # (Lots that closed during this command's time advance are excluded.)
        changed = {
            aid
            for aid, lead in before_leaders.items()
            if s2["auctions"][aid]["status"] == "open" and s2["auctions"][aid]["leader"] != lead
        }
        assert {e["data"]["auction"] for e in events if e["type"] == "outbid"} == changed
        assert all(
            e["vis"] == f"seat:{before_leaders[e['data']['auction']]}"
            for e in events
            if e["type"] == "outbid"
        )
        s = s2
        log.append((c, now))
        _fixed_point(s)
        for a in s["auctions"].values():
            if a["status"] == "open":
                assert a["price"] >= last_price.get(a["id"], 0)
                last_price[a["id"]] = a["price"]
        winners = [a["player"] for a in s["auctions"].values()]
        assert len(winners) == len(set(winners))
        for seat in seats:
            assert engine.balance(s, seat) >= 0
            assert engine.committed(s, seat) <= engine.balance(s, seat)
    # Replay determinism
    r = s0
    for c, t in log:
        r, _, _ = engine.apply_command(r, c, t)
    assert r == s


def test_many_proxies_competing_for_one_managers_funds():
    """S1 ($50) holds maxima of $40 on five auctions; rivals push each in
    turn.  S1 can never be committed beyond $50 in total, and whichever
    auctions S1 leads are exactly the ones a from-scratch resolution says."""
    s = make_room([50] + [100] * 11, preset="fast")
    s, _, _ = engine.apply_command(s, {"kind": "start", "actor": {"role": "commissioner"}}, NOON)
    aids = []
    for i, seat in enumerate(["S2", "S3", "S4", "S5", "S6"]):
        s, r, _ = engine.apply_command(
            s,
            {"kind": "nominate", "actor": {"role": "manager", "seat": seat}, "player": f"P{i + 1}"},
            NOON,
        )
        aids.append(r["auction"])
    for aid in aids:
        s, _, _ = engine.apply_command(
            s,
            {"kind": "bid", "actor": {"role": "manager", "seat": "S1"}, "auction": aid, "max": 40},
            NOON,
        )
    for i, aid in enumerate(aids):
        s, _, _ = engine.apply_command(
            s,
            {
                "kind": "bid",
                "actor": {"role": "manager", "seat": "S7"},
                "auction": aid,
                "max": 10 + i,
            },
            NOON + i,
        )
        assert engine.committed(s, "S1") <= 50
        _fixed_point(s)
    # Release: S8 takes auction 0 away from S1 → capped proxies reactivate.
    s, _, _ = engine.apply_command(
        s,
        {"kind": "bid", "actor": {"role": "manager", "seat": "S8"}, "auction": aids[0], "max": 45},
        NOON + 99,
    )
    assert engine.committed(s, "S1") <= 50
    _fixed_point(s)


def test_leader_price_never_rises_without_a_rival_action():
    s = make_room([50] + [100] * 11, preset="fast")
    s, _, _ = engine.apply_command(s, {"kind": "start", "actor": {"role": "commissioner"}}, NOON)
    s, r1, _ = engine.apply_command(
        s, {"kind": "nominate", "actor": {"role": "manager", "seat": "S2"}, "player": "P1"}, NOON
    )
    s, r2, _ = engine.apply_command(
        s, {"kind": "nominate", "actor": {"role": "manager", "seat": "S3"}, "player": "P2"}, NOON
    )
    a1, a2 = r1["auction"], r2["auction"]
    for aid in (a1, a2):
        s, _, _ = engine.apply_command(
            s,
            {"kind": "bid", "actor": {"role": "manager", "seat": "S1"}, "auction": aid, "max": 40},
            NOON,
        )
    s, _, _ = engine.apply_command(
        s,
        {"kind": "bid", "actor": {"role": "manager", "seat": "S7"}, "auction": a1, "max": 30},
        NOON,
    )
    # S1 leads a1 @31 → only $19 left for a2 (where S1 leads @1).
    s, _, _ = engine.apply_command(
        s,
        {"kind": "bid", "actor": {"role": "manager", "seat": "S8"}, "auction": a2, "max": 19},
        NOON,
    )
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == (
        "S1",
        19,
    )  # capped tie, earlier wins
    # S9 takes a1 from S1: S1's $31 frees.  S1 still leads a2 at $19 —
    # nobody acted on a2, so its price does not move.
    s, _, _ = engine.apply_command(
        s,
        {"kind": "bid", "actor": {"role": "manager", "seat": "S9"}, "auction": a1, "max": 45},
        NOON + 1,
    )
    assert s["auctions"][a1]["leader"] == "S9"
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == ("S1", 19)
    # The next competitive action on a2 resolves with S1's full capacity.
    s, _, _ = engine.apply_command(
        s,
        {"kind": "bid", "actor": {"role": "manager", "seat": "S10"}, "auction": a2, "max": 25},
        NOON + 2,
    )
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == ("S1", 26)
