"""INDEPENDENT adversarial audit of rookie-auction money and proxy correctness.

Written against the owner rules (``docs/auction/ROOKIE_AUCTION_ROOM.md`` §2 and
the AUC-001 clarification "LEADING BIDS RESERVE MONEY"), NOT against the
implementation's own tests.  Nothing here imports an engine internal to decide
what the right answer is: ``RefRoom`` below is a separate, deliberately small
model of the rules, and the engine/store are driven only through their public
command path (``engine.apply_command`` and ``Store.execute``).

Contents
--------
1. ``RefRoom`` — the reference model (money ledger, proxy resolution, freed-money
   reactivation, trades, adjustments).
2. A randomized differential fuzz: engine vs reference after EVERY accepted
   command, plus rule properties checked from scratch (committed <= balance,
   spendable >= 0, prices never fall, one award per player, no maximum in any
   public projection or public event, identical resubmission is a no-op,
   deterministic replay incl. a JSON round trip).
3. The same fuzz through the real SQLite ``Store`` (idempotency-key repeats,
   store reopen mid-room, ``verify_room`` replay + awards).
4. Every named owner scenario pinned as its own test.
5. Real-thread races against the real SQLite store.
6. Restart persistence.
7. Audit findings: ``xfail(strict=True)`` reproductions of real defects, and
   ``test_ambiguity_*`` tests that pin CURRENT behaviour where the owner rules
   do not decide the question (flagged for an owner decision, not endorsed).

Findings (2026-09-29 audit):

* DEFECT — a positive ``adjust_budget`` while the room is paused never
  reactivates that seat's capped proxies, and ``resume`` does not re-resolve,
  so a lot can close to a lower affordable maximum.
* DEFECT — ``_set_max`` keeps only ``hist[-50:]``; after 50+ edits a seat
  loses tie priority it has held continuously.
* AMBIGUITY — freed money reactivates maxima lowest lot first; a price set by
  that money on one lot can rest, after commit, on a maximum the same money
  then spent elsewhere in the same transaction (lot-number dependent).
* AMBIGUITY — a reactivated capped proxy keeps its original acceptance time
  for tie priority and can retake a lot at an unchanged price.
* CONSISTENT — the documented "+$1 tie while budget-capped" nuance.
* Minor — ``engine.seat_private_view`` mutates its input (adds ``trades``).
"""

from __future__ import annotations

import copy
import json
import os
import random
import threading
from collections import Counter

import pytest

from src.auction import engine
from src.auction.engine import AuctionError
from src.auction.rules import default_rules
from src.auction.store import open_store

# The "fast" preset has no nightly pause, so any epoch is inside the window.
T0 = 1_791_000_000.0
COMM = {"role": "commissioner"}
SYS = {"role": "system"}
MONEY_CODES = frozenset(
    {
        "over_balance",
        "below_price",
        "below_binding",
        "closed",
        "leader_cannot_withdraw",
        "below_obligations",
        "trade_unaffordable",
    }
)
SECRET_KEYS = frozenset({"max", "effective_max", "capacity", "hist", "bids"})


def mgr(seat: str) -> dict:
    return {"role": "manager", "seat": seat}


def build_room(budgets: list[int], room_id: str = "AUD", **rule_patch) -> dict:
    rules = default_rules("fast")
    rules["seat_count"] = len(budgets)
    rules.update(rule_patch)
    seats = [
        {"id": f"S{i + 1}", "name": f"Seat {i + 1}", "opening_budget": b}
        for i, b in enumerate(budgets)
    ]
    pool = {
        "version": "audit-v1",
        "label": "independent audit fixture",
        "is_official_class": False,
        "players": {
            f"P{i}": {"name": f"Rookie {i}", "pos": "WR", "value": 500 - i} for i in range(1, 91)
        },
    }
    return engine.new_room_state(
        room_id=room_id,
        name="audit",
        room_type="mock",
        rules=rules,
        seats=seats,
        order=None,
        pool=pool,
        created_at=T0 - 60,
    )


# ---------------------------------------------------------------------------
# 1. Reference model
# ---------------------------------------------------------------------------


def run_start_priority(hist: list[tuple[int, int]], level: int) -> int | None:
    """Tie priority at ``level``: the sequence number at which the seat's
    CURRENT unbroken run of maxima >= level began (earliest accepted max wins
    an exact tie; a raise earns priority only for new levels)."""
    start = None
    for mx, sq in hist:
        if mx >= level:
            if start is None:
                start = sq
        else:
            start = None
    return start


class RefRoom:
    """Small reference implementation of the owner money/proxy rules."""

    def __init__(self, budgets: dict[str, int]):
        self.opening = dict(budgets)
        self.delta = {s: 0 for s in budgets}  # adjustments + trade transfers
        self.lots: dict[str, dict] = {}
        self.order: list[str] = []
        self.seq = 0
        self.trades: dict[str, dict] = {}

    def clone(self) -> RefRoom:
        return copy.deepcopy(self)

    # -- money -----------------------------------------------------------
    def balance(self, seat: str) -> int:
        spent = sum(
            lot["price"]
            for lot in self.lots.values()
            if lot["status"] == "closed" and lot["winner"] == seat
        )
        return self.opening[seat] + self.delta[seat] - spent

    def committed(self, seat: str, exclude: str | None = None) -> int:
        return sum(
            lot["price"]
            for lid, lot in self.lots.items()
            if lot["status"] == "open" and lot["leader"] == seat and lid != exclude
        )

    def spendable(self, seat: str) -> int:
        return self.balance(seat) - self.committed(seat)

    def eff(self, seat: str, lid: str) -> int:
        bid = self.lots[lid]["bids"][seat]
        return min(bid["max"], self.balance(seat) - self.committed(seat, exclude=lid))

    # -- proxy resolution -----------------------------------------------
    def resolve(self, lid: str) -> tuple[str, int]:
        lot = self.lots[lid]
        leader, price = lot["leader"], lot["price"]
        field = []
        for seat, bid in lot["bids"].items():
            if seat != leader and not bid["active"]:
                continue
            e = self.eff(seat, lid)
            if seat == leader:
                assert e >= price, f"ref: leader {seat} cannot cover {price} on {lid}"
            elif e < price:
                continue
            field.append((seat, e))
        top = max(e for _, e in field)
        tied = [s for s, e in field if e == top]
        winner = min(tied, key=lambda s: run_start_priority(lot["bids"][s]["hist"], top))
        rest = [e for s, e in field if s != winner]
        if not rest:
            new_price = price
        else:
            second = max(rest)
            new_price = top if second == top else min(top, second + 1)
        return winner, max(price, new_price)

    def react(self, start: list[str]) -> None:
        """Re-resolve until stable, lowest lot first; a displaced seat's other
        conditional maxima respond to its released money."""
        pending = set(start)
        guard = 0
        while pending:
            guard += 1
            assert guard < 100_000, "ref cascade did not converge"
            lid = min(pending, key=self.order.index)
            pending.discard(lid)
            lot = self.lots[lid]
            if lot["status"] != "open":
                continue
            before = lot["leader"]
            lot["leader"], lot["price"] = self.resolve(lid)
            if lot["leader"] != before:
                for other in self.order:
                    o = self.lots[other]
                    b = o["bids"].get(before)
                    if (
                        other != lid
                        and o["status"] == "open"
                        and o["leader"] != before
                        and b
                        and b["active"]
                        and b["max"] >= o["price"]
                    ):
                        pending.add(other)

    # -- commands ----------------------------------------------------------
    def nominate(self, lid: str, seat: str, player: str) -> None:
        self.seq += 1
        self.lots[lid] = {
            "player": player,
            "status": "open",
            "price": 0,
            "leader": seat,
            "winner": None,
            "bids": {seat: {"max": 0, "active": True, "hist": [(0, self.seq)]}},
        }
        self.order.append(lid)

    def close(self, lid: str) -> None:
        lot = self.lots[lid]
        lot["status"] = "closed"
        lot["winner"] = lot["leader"]

    def bid(self, seat: str, lid: str, mx: int) -> str:
        lot = self.lots.get(lid)
        if lot is None or lot["status"] != "open":
            return "closed"
        if mx > self.balance(seat):
            return "over_balance"
        if mx < lot["price"]:
            return "below_binding" if lot["leader"] == seat else "below_price"
        cur = lot["bids"].get(seat)
        if cur and cur["active"] and cur["max"] == mx:
            return "noop"
        self.seq += 1
        hist = list(cur["hist"]) if cur and cur["active"] else []
        hist.append((mx, self.seq))
        lot["bids"][seat] = {"max": mx, "active": True, "hist": hist}
        if lot["leader"] != seat:
            self.react([lid])
        return "accept"

    def withdraw(self, seat: str, lid: str) -> str:
        lot = self.lots.get(lid)
        if lot is None or lot["status"] != "open":
            return "closed"
        if lot["leader"] == seat:
            return "leader_cannot_withdraw"
        cur = lot["bids"].get(seat)
        if not cur or not cur["active"]:
            return "noop"
        cur["active"] = False
        return "accept"

    def _money_in(self, seat: str) -> None:
        """Money received: that seat's capped conditional maxima may respond."""
        self.react(
            [
                lid
                for lid in self.order
                if self.lots[lid]["status"] == "open"
                and self.lots[lid]["leader"] != seat
                and seat in self.lots[lid]["bids"]
            ]
        )

    def adjust(self, seat: str, amount: int) -> str:
        if self.balance(seat) + amount < self.committed(seat):
            return "below_obligations"
        self.delta[seat] += amount
        if amount > 0:
            self._money_in(seat)
        return "accept"

    def settle_trade(self, tid: str) -> str:
        t = self.trades[tid]
        if self.spendable(t["from"]) < t["give"] or self.spendable(t["to"]) < t["get"]:
            return "trade_unaffordable"
        net_from = t["get"] - t["give"]
        self.delta[t["from"]] += net_from
        self.delta[t["to"]] -= net_from
        t["status"] = "completed"
        if net_from > 0:
            self._money_in(t["from"])
        elif net_from < 0:
            self._money_in(t["to"])
        return "accept"


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def _scan_keys(obj, path="") -> list[str]:
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SECRET_KEYS:
                bad.append(f"{path}.{k}")
            bad.extend(_scan_keys(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_scan_keys(v, f"{path}[{i}]"))
    return bad


def check_no_leak(s: dict, events: list[dict], now: float, actor_seat: str | None) -> None:
    # NOTE: engine.seat_private_view mutates its input (trades_for_seat ->
    # _trades() setdefault adds an empty "trades" key); undo that afterwards so
    # the audit never perturbs the state it is checking.
    had_trades = "trades" in s
    assert _scan_keys(engine.public_view(s, now)) == [], "public view exposes a maximum"
    for e in events:
        leaked = _scan_keys(e["data"])
        if not leaked:
            continue
        # Only the acting seat's own private receipt may carry its own maximum.
        assert actor_seat is not None and e["vis"] == f"seat:{actor_seat}", (e["type"], e["vis"])
    seats = [x["id"] for x in s["seats"]]
    for seat in seats:
        view = engine.seat_private_view(s, seat, now)
        for mine in view["my_bids"]:
            assert int(s["auctions"][mine["auction"]]["bids"][seat]["max"]) == mine["max"]
    if not had_trades:
        s.pop("trades", None)


def check_money(s: dict) -> None:
    for seat in (x["id"] for x in s["seats"]):
        bal = engine.balance(s, seat)
        com = engine.committed(s, seat)
        assert bal >= 0, f"{seat} balance {bal}"
        assert com <= bal, f"{seat} committed {com} > balance {bal}"
        assert engine.spendable(s, seat) >= 0
    pub = engine.public_view(s, 0)
    for row in pub["seats"]:
        assert row["spendable"] >= 0 and row["committed"] <= row["balance"]
    players = [a["player"] for a in s["auctions"].values()]
    assert len(players) == len(set(players)), "a player was nominated/awarded twice"
    for a in s["auctions"].values():
        if a["status"] == "closed":
            assert a["winner"] is not None


def compare(ref: RefRoom, s: dict) -> None:
    for lid, lot in ref.lots.items():
        a = s["auctions"][lid]
        assert a["status"] == lot["status"], lid
        if lot["status"] == "open":
            assert (a["leader"], a["price"]) == (lot["leader"], lot["price"]), (
                lid,
                (a["leader"], a["price"]),
                (lot["leader"], lot["price"]),
            )
        else:
            assert (a["winner"], a["price"]) == (lot["winner"], lot["price"]), lid
    assert set(ref.lots) == set(s["auctions"])
    for seat in ref.opening:
        assert engine.balance(s, seat) == ref.balance(seat), seat
        assert engine.committed(s, seat) == ref.committed(seat), seat


def scratch_analysis(ref: RefRoom, stats: Counter) -> None:
    """From-scratch view of every open lot under the reference model."""
    for lid in ref.order:
        lot = ref.lots[lid]
        if lot["status"] != "open":
            continue
        leader, price = lot["leader"], lot["price"]
        lead_bid = lot["bids"][leader]
        assert price <= lead_bid["max"], "price above the leader's own maximum"
        assert ref.eff(leader, lid) >= price, "leader cannot afford its own price"
        winner, scratch = ref.resolve(lid)
        assert winner == leader, f"{lid}: from-scratch leader {winner} != {leader}"
        for seat, bid in lot["bids"].items():
            if seat == leader or not bid["active"]:
                continue
            assert ref.eff(seat, lid) <= price, f"{lid}: live rival {seat} above price"
        if scratch != price:
            # Only the documented "+$1 tie" case: a rival sits exactly at the
            # price while the leader could now afford more.
            assert scratch == price + 1, (lid, price, scratch)
            assert ref.eff(leader, lid) > price
            assert any(
                s != leader and b["active"] and ref.eff(s, lid) == price
                for s, b in lot["bids"].items()
            )
            stats["plus_one_tie_state"] += 1


def phantom_analysis(ref: RefRoom, before_prices: dict[str, int], stats: Counter) -> None:
    """Count lots whose price ROSE in this command although no remaining
    rival can, after the command commits, afford price - 1."""
    for lid, old in before_prices.items():
        lot = ref.lots[lid]
        if lot["status"] != "open" or lot["price"] <= old:
            continue
        best = max(
            (ref.eff(s, lid) for s, b in lot["bids"].items() if s != lot["leader"] and b["active"]),
            default=-1,
        )
        if lot["price"] > best + 1:
            stats["price_above_post_commit_rival_capacity"] += 1


# ---------------------------------------------------------------------------
# 2/3. Randomized differential fuzz
# ---------------------------------------------------------------------------


class EngineExec:
    """Drive the pure engine."""

    def __init__(self, s0: dict):
        self.s = s0
        self.log: list[tuple[dict, float]] = []

    def apply(self, cmd: dict, now: float, key: str | None = None):
        s2, res, ev = engine.apply_command(self.s, cmd, now)
        self.s = s2
        self.log.append((cmd, now))
        return res, ev


class StoreExec:
    """Drive the real SQLite store through ``Store.execute`` with idempotency
    keys, exactly as the HTTP route does."""

    def __init__(self, path, s0: dict, now: float):
        self.path = path
        self.st = open_store(path)
        with self.st.write() as conn:
            conn.execute(
                "INSERT INTO users (id, handle, display_name, created_at) VALUES (1,'own','Own',0)"
            )
        self.room = s0["room_id"]
        self.st.create_room(s0, created_by=1, now_real=now)
        self.s = s0
        self.last: tuple | None = None
        self.idem_repeats = 0

    def reopen(self, now: float) -> None:
        before = self.st.load(self.room)
        self.st = open_store(self.path)  # a fresh process over the same file
        self.st.heartbeat([self.room], now)
        assert self.st.load(self.room) == before

    def apply(self, cmd: dict, now: float, key: str):
        user = 1 if (cmd.get("actor") or {}).get("role") != "manager" else 100
        self.st.heartbeat([self.room], now)
        out = self.st.execute(self.room, cmd, user_id=user, now_real=now, idem_key=key)
        assert out["replayed"] is False
        self.last = (cmd, now, key, user, out)
        if out["status"] != 200:
            err = out["result"]
            raise AuctionError(err["error"], err["message"], out["status"])
        self.s, _, _ = self.st.load(self.room)
        return out["result"], []

    def repeat_last(self) -> None:
        """Re-send the previous request with the same Idempotency-Key."""
        if self.last is None:
            return
        cmd, now, key, user, out = self.last
        rev_before = self.st.load(self.room)[1]
        state_before = self.st.load(self.room)[0]
        again = self.st.execute(self.room, cmd, user_id=user, now_real=now + 1, idem_key=key)
        assert again["replayed"] is True
        assert (again["status"], again["result"]) == (out["status"], out["result"])
        assert self.st.load(self.room)[1] == rev_before
        assert self.st.load(self.room)[0] == state_before
        self.idem_repeats += 1


def _gen_command(
    rng: random.Random, s: dict, ref: RefRoom, now: float, seats: list[str], stress: bool
):
    opens = [a for a in engine.open_auctions(s)]
    roll = rng.random()
    # Stress mode keeps ~8-12 lots open and piles bids onto them.
    nominate_p = (0.3 if len(opens) < 12 else 0.02) if stress else 0.20
    if roll < nominate_p:
        on_clock = [c["seat"] for c in engine.public_view(s, now)["on_clock"]]
        seat = rng.choice(on_clock) if on_clock and rng.random() < 0.9 else rng.choice(seats)
        taken = {a["player"] for a in s["auctions"].values()}
        free = [p for p in s["pool"]["players"] if p not in taken]
        player = rng.choice(free) if free and rng.random() < 0.95 else "P1"
        return {"kind": "nominate", "actor": mgr(seat), "player": player}
    if roll < 0.66 and opens:
        a = rng.choice(opens) if rng.random() < 0.97 else rng.choice(list(s["auctions"].values()))
        seat = rng.choice(seats)
        lot = ref.lots.get(a["id"])
        price = a["price"]
        bal = ref.balance(seat)
        spend = ref.spendable(seat)
        own = lot["bids"].get(seat) if lot else None
        lead_max = lot["bids"][lot["leader"]]["max"] if lot else 0
        choices = [
            0,
            price,
            price + 1,
            spend,
            spend + 1,
            bal,
            bal + 1,
            lead_max,
            lead_max + 1,
            rng.randint(0, max(0, bal)),
            rng.randint(price, price + 15),
        ]
        if own and own["active"]:
            choices += [own["max"]] * 3  # identical resubmissions
        if stress:
            # Whole-balance conditional ceilings on many lots at once: the
            # cross-lot reservation / release / reactivation paths.
            part = rng.randint(max(0, bal // 4), max(0, bal))
            choices = [bal, part, part, price + 1, price + 2, lead_max + 1, lead_max]
        mx = max(0, rng.choice(choices))
        return {"kind": "bid", "actor": mgr(seat), "auction": a["id"], "max": mx}
    if roll < 0.72 and opens:
        a = rng.choice(opens)
        lot = ref.lots[a["id"]]
        seat = lot["leader"]
        mx = rng.randint(a["price"], max(a["price"], ref.balance(seat)))
        return {"kind": "bid", "actor": mgr(seat), "auction": a["id"], "max": mx}
    if roll < 0.77 and opens:
        a = rng.choice(opens)
        return {"kind": "withdraw", "actor": mgr(rng.choice(seats)), "auction": a["id"]}
    if roll < 0.87:
        open_trades = [t for t in (s.get("trades") or {}).values() if t["status"] == "open"]
        if open_trades and rng.random() < 0.6:
            t = rng.choice(open_trades)
            return {
                "kind": "respond_trade",
                "actor": mgr(t["to"]),
                "trade": t["id"],
                "version": 1,
                "accept": rng.random() < 0.85,
            }
        a_, b_ = rng.sample(seats, 2)
        return {
            "kind": "offer_trade",
            "actor": mgr(a_),
            "to": b_,
            "give_dollars": rng.choice([0, 1, 3, 5, 10, 25, ref.spendable(a_), ref.balance(a_)]),
            "get_dollars": rng.choice([0, 0, 1, 2, 5]),
        }
    if roll < 0.92:
        return {
            "kind": "adjust_budget",
            "actor": COMM,
            "seat": rng.choice(seats),
            "amount": rng.choice([-20, -5, -1, 1, 4, 15, 40]),
            "reason": "audit",
        }
    return {"kind": "advance", "actor": SYS}


def _predict(ref: RefRoom, cmd: dict, now: float, engine_state: dict) -> str | None:
    """Mutates ``ref``; returns the predicted outcome or None (not modelled)."""
    kind = cmd["kind"]
    seat = (cmd.get("actor") or {}).get("seat")
    if kind == "bid":
        return ref.bid(seat, cmd["auction"], cmd["max"])
    if kind == "withdraw":
        return ref.withdraw(seat, cmd["auction"])
    if kind == "adjust_budget":
        if engine_state["status"] == "complete":
            return None
        return ref.adjust(cmd["seat"], cmd["amount"])
    if kind == "respond_trade":
        t = (engine_state.get("trades") or {}).get(cmd["trade"])
        if not t or t["status"] != "open" or now >= t["expires_at"] or not cmd["accept"]:
            return None
        if engine_state["status"] not in ("running", "draining"):
            return None
        return ref.settle_trade(cmd["trade"])
    return None


def fuzz_room(
    seed: int,
    n_ops: int,
    make_exec,
    stats: Counter,
    reopen_at: int | None = None,
    stress: bool = False,
):
    rng = random.Random(seed)
    menu = [10, 20, 25, 30, 40, 50] if stress else [0, 1, 5, 10, 20, 35, 50, 100]
    budgets = [rng.choice(menu) for _ in range(12)]
    # Long lots and no nomination timeout keep up to 12 lots open and the room
    # alive for the whole run; lots still close via explicit deadline jumps.
    s0 = build_room(
        budgets,
        room_id=f"AUD{seed}",
        # stress: lots stay open for (almost) the whole run so conditional
        # ceilings on up to 12 lots interact; they all close near the end.
        auction_active_seconds=30 * 86400 if stress else rng.choice([900, 1800, 3600]),
        nomination_timeout_active_seconds=None,
    )
    now = T0
    ex = make_exec(s0, now)
    ex.apply({"kind": "start", "actor": COMM}, now, key=f"{seed}-start")
    ref = RefRoom({f"S{i + 1}": b for i, b in enumerate(budgets)})
    seats = list(ref.opening)
    last_price: dict[str, int] = {}
    for step in range(n_ops):
        if reopen_at is not None and step == reopen_at:
            ex.reopen(now)
        s = ex.s
        opens = engine.open_auctions(s)
        jump_p = (0.0 if step < n_ops * 0.85 else 0.25) if stress else 0.035
        if opens and rng.random() < jump_p:
            now = max(now, min(a["deadline"] for a in opens))
        else:
            now += rng.choice([0, 1, 1, 2, 5, 20, 60, 150])
        cmd = _gen_command(rng, s, ref, now, seats, stress)
        # Time settles first: lots due at ``now`` close before the command.
        due = sorted(
            (a for a in opens if a["deadline"] <= now),
            key=lambda a: (a["deadline"], s["auction_order"].index(a["id"])),
        )
        ref2 = ref.clone()
        for a in due:
            ref2.close(a["id"])
        before_prices = {lid: lot["price"] for lid, lot in ref2.lots.items()}
        predicted = _predict(ref2, cmd, now, s)
        identical = predicted == "noop" and not due
        try:
            res, events = ex.apply(cmd, now, key=f"{seed}-{step}")
        except AuctionError as exc:
            stats["rejected"] += 1
            if predicted is not None and predicted in ("accept", "noop"):
                assert exc.code not in MONEY_CODES, (seed, step, cmd, exc.code)
            if predicted in MONEY_CODES:
                assert exc.code == predicted, (seed, step, cmd, predicted, exc.code)
            if hasattr(ex, "repeat_last") and rng.random() < 0.3:
                ex.repeat_last()
            continue
        stats["accepted"] += 1
        stats[f"accepted_{cmd['kind']}"] += 1
        # Cross-lot proxy reactions (freed / received money), from the engine's
        # own public price events (only available on the pure-engine path).
        stats["cross_lot_reactions"] += sum(
            1 for e in events if e["type"] == "price" and e["data"]["auction"] != cmd.get("auction")
        )
        assert predicted not in MONEY_CODES, (seed, step, cmd, predicted)
        if cmd["kind"] == "nominate":
            ref2.nominate(res["auction"], cmd["actor"]["seat"], cmd["player"])
        if cmd["kind"] == "offer_trade":
            ref2.trades[res["trade"]] = {
                "from": cmd["actor"]["seat"],
                "to": cmd["to"],
                "give": cmd["give_dollars"],
                "get": cmd["get_dollars"],
                "status": "open",
            }
        s2 = ex.s
        if identical:
            stats["identical_resubmission"] += 1
            assert res.get("noop") is True
            assert s2 == s, "identical resubmission changed the room"
        compare(ref2, s2)
        check_money(s2)
        check_no_leak(s2, events, now, (cmd.get("actor") or {}).get("seat"))
        for a in s2["auctions"].values():
            if a["status"] == "open":
                assert a["price"] >= last_price.get(a["id"], 0), "public price fell"
                last_price[a["id"]] = a["price"]
        scratch_analysis(ref2, stats)
        phantom_analysis(ref2, before_prices, stats)
        ref = ref2
        stats["max_open_seen"] = max(stats["max_open_seen"], len(engine.open_auctions(s2)))
        if hasattr(ex, "repeat_last") and rng.random() < 0.3:
            ex.repeat_last()
    stats["lots"] += len(ex.s["auctions"])
    return ex, s0


# 20 seeds x 2 modes by default (~40 s); widen for a deep run with
# AUCTION_AUDIT_SEEDS=<n>.
ENGINE_SEEDS = range(int(os.getenv("AUCTION_AUDIT_SEEDS", "20")))


@pytest.mark.parametrize("stress", [False, True], ids=["mixed", "cascade"])
@pytest.mark.parametrize("seed", ENGINE_SEEDS)
def test_differential_fuzz_engine_vs_reference(seed, stress):
    stats: Counter = Counter()
    ex, s0 = fuzz_room(seed, 220, lambda s0, now: EngineExec(s0), stats, stress=stress)
    assert stats["accepted"] > 50
    # Deterministic replay, including through a JSON round trip (the store's form).
    r = json.loads(json.dumps(s0))
    for c, t in ex.log:
        r, _, _ = engine.apply_command(r, json.loads(json.dumps(c)), t)
    assert r == json.loads(json.dumps(ex.s))
    r2 = s0
    for c, t in ex.log:
        r2, _, _ = engine.apply_command(r2, c, t)
    assert r2 == ex.s


@pytest.mark.parametrize("seed", range(1000, 1006))
def test_differential_fuzz_through_sqlite_store(seed, tmp_path):
    stats: Counter = Counter()
    path = tmp_path / "auction" / "auction.sqlite"
    ex, _ = fuzz_room(
        seed,
        140,
        lambda s0, now: StoreExec(path, s0, now),
        stats,
        reopen_at=70,
        stress=seed % 2 == 1,
    )
    assert ex.idem_repeats > 5
    room = ex.room
    report = ex.st.verify_room(room)
    assert report["replay_matches"] and report["awards_match"], report
    with ex.st.read() as conn:
        rows = conn.execute(
            "SELECT player_id, COUNT(*) c FROM awards WHERE room_id=? GROUP BY player_id", (room,)
        ).fetchall()
    assert all(r["c"] == 1 for r in rows)
    for ev in ex.st.events_for(room, vis={"public", "commissioner"}, limit=100_000):
        assert _scan_keys(ev["data"]) == [], ev
    # A completely fresh store over the file agrees with the live one.
    again = open_store(path)
    assert again.load(room)[0] == ex.st.load(room)[0]
    assert again.replay(room) == ex.st.load(room)[0]


# ---------------------------------------------------------------------------
# 4. Named owner scenarios
# ---------------------------------------------------------------------------


class Room:
    def __init__(self, budgets: list[int] | None = None):
        self.s = build_room(budgets if budgets is not None else [100] * 12)
        self.now = T0
        self.events: list = []
        self.cmd({"kind": "start", "actor": COMM})

    def cmd(self, c: dict, dt: float = 1.0) -> dict:
        self.now += dt
        self.s, res, self.events = engine.apply_command(self.s, c, self.now)
        return res

    def nominate(self, seat: str, player: str) -> str:
        return self.cmd({"kind": "nominate", "actor": mgr(seat), "player": player})["auction"]

    def bid(self, seat: str, lid: str, mx: int, dt: float = 1.0) -> dict:
        return self.cmd({"kind": "bid", "actor": mgr(seat), "auction": lid, "max": mx}, dt)

    def lot(self, lid: str) -> tuple[str, int]:
        a = self.s["auctions"][lid]
        return a["leader"] if a["status"] == "open" else a["winner"], a["price"]

    def money(self, seat: str) -> tuple[int, int, int]:
        return (
            engine.balance(self.s, seat),
            engine.committed(self.s, seat),
            engine.spendable(self.s, seat),
        )

    def close(self, lid: str) -> None:
        self.now = max(self.now, self.s["auctions"][lid]["deadline"])
        self.s, _, self.events = engine.apply_command(
            self.s, {"kind": "advance", "actor": SYS}, self.now
        )
        assert self.s["auctions"][lid]["status"] == "closed"


def test_zero_dollar_opening_and_zero_dollar_win():
    r = Room()
    a = r.nominate("S1", "P1")
    assert r.lot(a) == ("S1", 0)
    r.close(a)
    assert r.lot(a) == ("S1", 0)
    assert r.money("S1") == (100, 0, 100)


def test_manager_with_zero_spendable_may_bid_zero():
    r = Room([0] + [100] * 11)
    a = r.nominate("S2", "P1")
    res = r.bid("S1", a, 0)  # $0 balance, legal $0 bid
    assert res["ok"] and not res["leading"]
    b = r.nominate("S1", "P2")  # a $0-budget manager may nominate
    r.close(b)
    assert r.lot(b) == ("S1", 0) and r.money("S1") == (0, 0, 0)
    # Fully-committed (spendable $0) manager may also bid $0.
    r2 = Room([10] + [100] * 11)
    x = r2.nominate("S2", "P1")
    r2.bid("S1", x, 10)
    r2.bid("S3", x, 9)
    assert r2.lot(x) == ("S1", 10) and r2.money("S1")[2] == 0
    y = r2.nominate("S4", "P2")
    assert r2.bid("S1", y, 0)["ok"]
    with pytest.raises(AuctionError) as e:
        r2.bid("S1", y, 11)
    assert e.value.code == "over_balance"


def test_positive_bids_are_whole_dollars():
    r = Room()
    a = r.nominate("S1", "P1")
    for bad in (1.5, "3", True, -1, float("nan")):
        with pytest.raises(AuctionError):
            r.bid("S2", a, bad)


def test_owner_example_50_vs_39_leads_at_40():
    r = Room()
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 50)
    r.bid("S2", a, 39)
    assert r.lot(a) == ("S1", 40)


def test_equal_50_earliest_wins_at_50_then_51_takes_it():
    r = Room()
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 50)
    r.bid("S2", a, 50)
    assert r.lot(a) == ("S1", 50)
    r.bid("S2", a, 51)
    assert r.lot(a) == ("S2", 51)


def test_two_zero_maxima_earlier_keeps_priority():
    r = Room()
    a = r.nominate("S1", "P1")
    r.bid("S2", a, 0)
    r.bid("S3", a, 0)
    assert r.lot(a) == ("S1", 0)
    r.close(a)
    assert r.lot(a) == ("S1", 0)


def test_leader_alone_raising_to_50_keeps_price_zero_and_no_extension():
    r = Room()
    a = r.nominate("S1", "P1")
    deadline = r.s["auctions"][a]["deadline"]
    r.bid("S1", a, 50, dt=deadline - r.now - 5)  # inside the extension window
    assert r.lot(a) == ("S1", 0)
    assert r.s["auctions"][a]["deadline"] == deadline
    assert r.money("S1") == (100, 0, 100)


def test_raising_own_max_without_competition_never_moves_price():
    r = Room()
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 50)
    r.bid("S2", a, 39)
    assert r.lot(a) == ("S1", 40)
    deadline = r.s["auctions"][a]["deadline"]
    r.bid("S1", a, 90, dt=deadline - r.now - 5)
    assert r.lot(a) == ("S1", 40) and r.s["auctions"][a]["deadline"] == deadline


def test_identical_resubmission_is_a_noop_no_priority_no_extension():
    r = Room()
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 50)
    r.bid("S2", a, 50)  # loses the tie
    deadline = r.s["auctions"][a]["deadline"]
    before = copy.deepcopy(r.s)
    res = r.bid("S2", a, 50, dt=deadline - r.now - 5)  # late, identical
    assert res.get("noop") is True
    # no new seq, no priority, no extension (nomination clocks elsewhere may
    # have timed out during the time jump; the lot and the sequence may not move)
    assert r.s["auctions"][a] == before["auctions"][a]
    assert r.s["seq"] == before["seq"] and r.s["bid_log"] == before["bid_log"]
    before = copy.deepcopy(r.s)
    res = r.bid("S1", a, 50, dt=0)  # leader identical resubmission
    assert res.get("noop") is True and r.s == before
    r.bid("S4", a, 50)  # a third equal max still loses to the earliest
    assert r.lot(a) == ("S1", 50)


def _auc001_base() -> tuple[Room, str]:
    """S1 has $50 and leads lot A at $45 (S2's max $44)."""
    r = Room([50] + [100] * 11)
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 50)
    r.bid("S2", a, 44)
    assert r.lot(a) == ("S1", 45)
    return r, a


def test_auc001_leading_45_of_50_leaves_5():
    r, _ = _auc001_base()
    assert r.money("S1") == (50, 45, 5)
    pv = engine.seat_private_view(r.s, "S1", r.now)
    assert (pv["balance"], pv["committed"], pv["spendable"]) == (50, 45, 5)


def test_auc001_bid_5_elsewhere_is_legal_and_6_is_only_conditional():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 5)
    r.bid("S5", b, 4)
    assert r.lot(b) == ("S1", 5) and r.money("S1") == (50, 50, 0)
    # $6 stored as a ceiling: accepted, but it executes only to $5.
    res = r.bid("S1", b, 6)
    assert res["ok"] and res["effective_max"] == 5 and res["capped"]
    assert r.lot(b) == ("S1", 5) and r.money("S1") == (50, 50, 0)
    r.bid("S6", b, 6)
    assert r.lot(b) == ("S6", 6)  # S1's $6 could not be paid → no overspend
    assert r.money("S1") == (50, 45, 5)


def test_auc001_six_dollar_max_first_never_overspends():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    res = r.bid("S1", b, 6)
    assert res["effective_max"] == 5
    r.bid("S5", b, 5)
    # tie at the affordable $5 → earlier-accepted S1 leads at $5, not $6
    assert r.lot(b) == ("S1", 5) and r.money("S1") == (50, 50, 0)
    r.bid("S5", b, 6)
    assert r.lot(b) == ("S5", 6) and r.money("S1") == (50, 45, 5)


def test_auc001_outbid_releases_45_immediately():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 30)
    r.bid("S5", b, 20)
    assert r.lot(b) == ("S5", 6)  # S1 capped at $5: no phantom $21
    r.bid("S7", a, 60)
    assert r.lot(a) == ("S7", 51)
    # same transaction: $45 released, S1's $30 on B now responds
    assert r.lot(b) == ("S1", 21)
    assert r.money("S1") == (50, 21, 29)


def test_auc001_close_converts_reservation_exactly_once():
    r, a = _auc001_base()
    r.close(a)
    assert r.money("S1") == (5, 0, 5)
    r.cmd({"kind": "advance", "actor": SYS}, dt=3600)
    assert r.money("S1") == (5, 0, 5)
    assert sum(1 for x in r.s["auctions"].values() if x["winner"] == "S1") == 1


def test_auc001_spend_last_5_then_proxy_on_a_never_exceeds_affordable():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 5)
    r.bid("S5", b, 4)
    assert r.money("S1") == (50, 50, 0)
    r.bid("S2", a, 48)  # S1's stored $50 on A can now pay only $45
    assert r.lot(a) == ("S2", 46)
    assert r.money("S1") == (50, 5, 45)
    for x in r.s["auctions"].values():
        if x["status"] == "open" and x["leader"] == "S1":
            assert x["price"] <= 50


def test_auc001_unaffordable_max_never_sets_a_rivals_price():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 40)  # stored $40, affordable $5
    r.bid("S5", b, 3)
    assert r.lot(b) == ("S1", 4)
    r.bid("S6", b, 30)
    assert r.lot(b) == ("S6", 6)  # not $31 — S1 could never pay $30


def test_multiple_leads_commit_90_leave_10():
    r = Room([100] * 12)
    lots = []
    for seat, p, price in (("S2", "P1", 40), ("S3", "P2", 30), ("S4", "P3", 20)):
        lid = r.nominate(seat, p)
        r.bid("S1", lid, 100)
        r.bid("S9", lid, price - 1)
        assert r.lot(lid) == ("S1", price)
        lots.append(lid)
    assert r.money("S1") == (100, 90, 10)
    d = r.nominate("S5", "P4")
    r.bid("S10", d, 30)
    res = r.bid("S1", d, 50)
    assert res["effective_max"] == 10 and not res["leading"]
    assert r.lot(d) == ("S10", 11)
    assert r.money("S1") == (100, 90, 10)


def test_trade_cannot_move_reserved_money_and_open_offer_reserves_nothing():
    r, a = _auc001_base()
    t = r.cmd({"kind": "offer_trade", "actor": mgr("S1"), "to": "S2", "give_dollars": 6})["trade"]
    with pytest.raises(AuctionError) as e:
        r.cmd(
            {"kind": "respond_trade", "actor": mgr("S2"), "trade": t, "version": 1, "accept": True}
        )
    assert e.value.code == "trade_unaffordable"
    # An open offer does not reserve: S1 can still spend the $5 on a bid.
    t2 = r.cmd({"kind": "offer_trade", "actor": mgr("S1"), "to": "S2", "give_dollars": 5})["trade"]
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 5)
    r.bid("S5", b, 4)
    assert r.money("S1") == (50, 50, 0)
    with pytest.raises(AuctionError) as e:  # settlement re-checks
        r.cmd(
            {"kind": "respond_trade", "actor": mgr("S2"), "trade": t2, "version": 1, "accept": True}
        )
    assert e.value.code == "trade_unaffordable"
    assert r.money("S1") == (50, 50, 0) and r.money("S2")[0] == 100


# ---------------------------------------------------------------------------
# 5. Real-thread races against the real SQLite store
# ---------------------------------------------------------------------------


def _store_room(path, budgets, room_id):
    st = open_store(path)
    with st.write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, handle, display_name, created_at) VALUES (1,'own','Own',0)"
        )
    s0 = build_room(budgets, room_id=room_id)
    st.create_room(s0, created_by=1, now_real=T0)
    return st


def _x(st, room, cmd, now, key=None, user=None):
    return st.execute(room, cmd, user_id=user, now_real=now, idem_key=key)


def _race(fns):
    barrier = threading.Barrier(len(fns))
    out: list = [None] * len(fns)
    errs: list = []

    def run(i, fn):
        barrier.wait()
        try:
            out[i] = fn()
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errs.append(exc)

    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs, errs
    return out


@pytest.mark.parametrize("separate_processes", [False, True])
def test_race_for_the_last_ten_dollars_across_two_lots(tmp_path, separate_processes):
    path = tmp_path / "auction" / "auction.sqlite"
    for it in range(4):
        room = f"RACE{it}"
        st = _store_room(path, [100] * 12, room)
        _x(st, room, {"kind": "start", "actor": COMM}, T0)
        # S1 leads A $40, B $30, C $20 → $10 free
        for seat, p, price in (("S2", "P1", 40), ("S3", "P2", 30), ("S4", "P3", 20)):
            lid = _x(st, room, {"kind": "nominate", "actor": mgr(seat), "player": p}, T0)["result"][
                "auction"
            ]
            _x(st, room, {"kind": "bid", "actor": mgr("S1"), "auction": lid, "max": 100}, T0)
            _x(st, room, {"kind": "bid", "actor": mgr("S9"), "auction": lid, "max": price - 1}, T0)
        d = _x(st, room, {"kind": "nominate", "actor": mgr("S5"), "player": "P4"}, T0)["result"][
            "auction"
        ]
        e = _x(st, room, {"kind": "nominate", "actor": mgr("S6"), "player": "P5"}, T0)["result"][
            "auction"
        ]
        for lid, rival in ((d, "S10"), (e, "S11")):
            _x(st, room, {"kind": "bid", "actor": mgr(rival), "auction": lid, "max": 9}, T0)
        pre, _, _ = st.load(room)
        assert engine.spendable(pre, "S1") == 10
        st2 = open_store(path) if separate_processes else st
        bid_d = {"kind": "bid", "actor": mgr("S1"), "auction": d, "max": 10}
        bid_e = {"kind": "bid", "actor": mgr("S1"), "auction": e, "max": 10}
        _race(
            [
                lambda: _x(st, room, bid_d, T0 + 1, key=f"d{it}", user=7),
                lambda: _x(st2, room, bid_e, T0 + 1, key=f"e{it}", user=7),
            ]
        )
        final, _, _ = st.load(room)
        # Only a serial order may survive.
        s_de = engine.apply_command(engine.apply_command(pre, bid_d, T0 + 1)[0], bid_e, T0 + 1)[0]
        s_ed = engine.apply_command(engine.apply_command(pre, bid_e, T0 + 1)[0], bid_d, T0 + 1)[0]
        assert final in (s_de, s_ed)
        led = [
            a["id"]
            for a in final["auctions"].values()
            if a["status"] == "open" and a["leader"] == "S1" and a["id"] in (d, e)
        ]
        assert len(led) == 1 and final["auctions"][led[0]]["price"] == 10
        assert engine.committed(final, "S1") == 100 and engine.spendable(final, "S1") == 0
        assert st.verify_room(room)["replay_matches"]


def test_race_trade_accept_vs_bid_cannot_spend_same_money_twice(tmp_path):
    path = tmp_path / "auction" / "auction.sqlite"
    orders = Counter()
    for it in range(6):
        room = f"TR{it}"
        st = _store_room(path, [50] + [100] * 11, room)
        _x(st, room, {"kind": "start", "actor": COMM}, T0)
        lid = _x(st, room, {"kind": "nominate", "actor": mgr("S2"), "player": "P1"}, T0)["result"][
            "auction"
        ]
        _x(st, room, {"kind": "bid", "actor": mgr("S4"), "auction": lid, "max": 40}, T0)
        tid = _x(
            st,
            room,
            {"kind": "offer_trade", "actor": mgr("S1"), "to": "S3", "give_dollars": 30},
            T0,
        )["result"]["trade"]
        pre, _, _ = st.load(room)
        accept = {
            "kind": "respond_trade",
            "actor": mgr("S3"),
            "trade": tid,
            "version": 1,
            "accept": True,
        }
        bid = {"kind": "bid", "actor": mgr("S1"), "auction": lid, "max": 50}
        other = open_store(path)
        res_accept, res_bid = _race(
            [
                lambda: _x(st, room, accept, T0 + 1, key=f"acc{it}", user=3),
                lambda: _x(other, room, bid, T0 + 1, key=f"bid{it}", user=1),
            ]
        )
        ok = [r["status"] == 200 for r in (res_accept, res_bid)]
        assert ok.count(True) == 1, (res_accept, res_bid)
        final, _, _ = st.load(room)

        def serial(first, second):
            s1 = engine.apply_command(pre, first, T0 + 1)[0]
            try:
                return engine.apply_command(s1, second, T0 + 1)[0]
            except AuctionError:
                return s1

        assert final in (serial(accept, bid), serial(bid, accept))
        bal, com = engine.balance(final, "S1"), engine.committed(final, "S1")
        assert com <= bal
        # Never both: $30 sent AND leading at $41 on a $50 balance.
        assert not (bal == 20 and com > 0)
        orders["trade_first" if ok[0] else "bid_first"] += 1
        assert st.verify_room(room)["replay_matches"]
    assert sum(orders.values()) == 6


def test_race_duplicate_idempotency_key_applies_once(tmp_path):
    path = tmp_path / "auction" / "auction.sqlite"
    st = _store_room(path, [100] * 12, "IDEM")
    _x(st, "IDEM", {"kind": "start", "actor": COMM}, T0)
    lid = _x(st, "IDEM", {"kind": "nominate", "actor": mgr("S2"), "player": "P1"}, T0)["result"][
        "auction"
    ]
    rev0 = st.load("IDEM")[1]
    c = {"kind": "bid", "actor": mgr("S1"), "auction": lid, "max": 30}
    other = open_store(path)
    outs = _race(
        [
            lambda: _x(st, "IDEM", c, T0 + 1, key="same-key", user=1),
            lambda: _x(other, "IDEM", c, T0 + 1, key="same-key", user=1),
        ]
    )
    assert sorted(o["replayed"] for o in outs) == [False, True]
    assert st.load("IDEM")[1] == rev0 + 1
    with pytest.raises(AuctionError) as e:
        _x(st, "IDEM", {**c, "max": 31}, T0 + 2, key="same-key", user=1)
    assert e.value.code == "idempotency_conflict"


# ---------------------------------------------------------------------------
# 6. Restart
# ---------------------------------------------------------------------------


def test_restart_mid_room_preserves_reservations_and_replays(tmp_path):
    path = tmp_path / "auction" / "auction.sqlite"
    st = _store_room(path, [50, 100, 100, 100, 100, 100, 0, 100, 100, 100, 100, 100], "RS")
    _x(st, "RS", {"kind": "start", "actor": COMM}, T0)
    a = _x(st, "RS", {"kind": "nominate", "actor": mgr("S3"), "player": "P1"}, T0)["result"][
        "auction"
    ]
    b = _x(st, "RS", {"kind": "nominate", "actor": mgr("S4"), "player": "P2"}, T0)["result"][
        "auction"
    ]
    for seat, lid, mx, t in (
        ("S1", a, 50, 1),
        ("S2", a, 44, 2),
        ("S1", b, 30, 3),
        ("S5", b, 20, 4),
    ):
        _x(st, "RS", {"kind": "bid", "actor": mgr(seat), "auction": lid, "max": mx}, T0 + t)
    state, rev, _ = st.load("RS")
    views = {
        seat: engine.seat_private_view(copy.deepcopy(state), seat, T0 + 10)
        for seat in ("S1", "S2", "S5", "S7")
    }
    del st  # "process exit"
    st2 = open_store(path)
    st2.heartbeat(["RS"], T0 + 10)
    state2, rev2, _ = st2.load("RS")
    assert (state2, rev2) == (state, rev)
    assert st2.replay("RS") == state
    assert {s: engine.seat_private_view(copy.deepcopy(state2), s, T0 + 10) for s in views} == views
    assert (engine.balance(state2, "S1"), engine.committed(state2, "S1")) == (50, 45)
    rep = st2.verify_room("RS")
    assert rep["replay_matches"] and rep["awards_match"]
    # Continue after restart: an outbid still releases, a close converts once.
    _x(st2, "RS", {"kind": "bid", "actor": mgr("S6"), "auction": a, "max": 60}, T0 + 20)
    s3, _, _ = st2.load("RS")
    assert s3["auctions"][b]["leader"] == "S1" and engine.committed(s3, "S1") == 21
    deadline = max(x["deadline"] for x in s3["auctions"].values())
    st2.heartbeat(["RS"], deadline)
    _x(st2, "RS", {"kind": "advance", "actor": SYS}, deadline)
    st3 = open_store(path)
    s4, _, _ = st3.load("RS")
    assert engine.balance(s4, "S1") == 29 and engine.committed(s4, "S1") == 0
    with st3.read() as conn:
        n = conn.execute("SELECT COUNT(*) FROM awards WHERE room_id='RS'").fetchone()[0]
    assert n == 2
    rep = st3.verify_room("RS")
    assert rep["replay_matches"] and rep["awards_match"]


# ---------------------------------------------------------------------------
# 7. Audit findings
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT: a positive commissioner budget adjustment made while the room is PAUSED "
        "never reactivates the seat's capped proxies (engine._cmd_adjust_budget skips the cascade "
        "when paused and _cmd_resume never re-resolves), so after resume a lot can close to a "
        "lower maximum than a rival's now-affordable one."
    ),
)
def test_defect_adjust_during_pause_leaves_capped_proxy_dead():
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 50)  # stored $50, affordable $5
    r.bid("S5", b, 20)
    assert r.lot(b) == ("S5", 6)
    r.cmd({"kind": "pause", "actor": COMM, "reason": "audit"})
    r.cmd({"kind": "adjust_budget", "actor": COMM, "seat": "S1", "amount": 100, "reason": "audit"})
    r.cmd({"kind": "resume", "actor": COMM})
    assert engine.capacity(r.s, "S1", b) == 105  # S1 can now pay its $50
    r.close(b)
    # Owner proxy rule: S1's affordable $50 beats S5's $20 → S1 at $21.
    assert r.lot(b) == ("S1", 21)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AUDIT DEFECT: engine._set_max truncates a bid's priority history to hist[-50:], so a "
        "seat that has held a maximum >= $40 continuously since BEFORE a rival's $40 loses the "
        "exact tie at $40 after 50+ max edits (earliest accepted max must win)."
    ),
)
def test_defect_priority_history_truncation_flips_an_exact_tie():
    r = Room([200] * 12)
    a = r.nominate("S3", "P1")
    r.bid("S1", a, 40)
    r.bid("S2", a, 40)
    assert r.lot(a) == ("S1", 40)
    for m in range(41, 92):  # the leader edits its private maximum 51 times, never below $40
        r.bid("S1", a, m)
    r.bid("S1", a, 40)
    assert r.lot(a) == ("S1", 40)
    r.bid("S4", a, 40)  # an unrelated third $40 re-resolves the lot
    assert r.lot(a) == ("S1", 40)


def test_ambiguity_plus_one_tie_while_capped_is_rule_consistent():
    """Documented nuance: a leader that won a tie while budget-capped keeps
    the tie price when its money frees; the next competitive action re-prices.
    Evaluated against the owner rules this is CONSISTENT: the tie was decided
    correctly at the moment it happened (earliest accepted max at the
    affordable level), and freed money is not a competitive action ("raising
    your own max without competition never raises the price")."""
    r = Room([50] + [100] * 11)
    x = r.nominate("S2", "P1")
    y = r.nominate("S3", "P2")
    r.bid("S1", x, 40)
    r.bid("S1", y, 40)
    r.bid("S7", x, 30)  # S1 leads x @31 → $19 free for y
    r.bid("S8", y, 19)  # tie at S1's affordable $19; S1's max is earlier
    assert r.lot(y) == ("S1", 19)
    r.bid("S9", x, 45)  # S1 displaced on x, money freed
    assert r.lot(y) == ("S1", 19)  # nobody acted on y
    r.bid("S10", y, 19)  # a competitive action on y re-prices with full capacity
    assert r.lot(y) == ("S1", 20)


def test_ambiguity_reactivated_capped_proxy_keeps_original_tie_priority():
    """OWNER DECISION NEEDED.  S1's $6 was accepted (as a conditional ceiling,
    affordable $5) BEFORE S6's $6.  S6 took the lead at $6.  When S1 is outbid
    elsewhere, S1's reactivated $6 ties S6 at $6 and wins on its earlier
    acceptance time — S6 loses the lead at an unchanged public price without
    anyone offering more than $6.  Literal reading of "earliest accepted max
    wins" supports this; a reading that dates priority from when the max
    became AFFORDABLE would keep S6.  Current behaviour pinned, not endorsed."""
    r, a = _auc001_base()
    b = r.nominate("S4", "P2")
    r.bid("S1", b, 6)
    r.bid("S5", b, 5)
    r.bid("S6", b, 6)
    assert r.lot(b) == ("S6", 6)
    r.bid("S7", a, 60)
    assert r.lot(b) == ("S1", 6)


def test_ambiguity_freed_money_pressure_is_lot_order_dependent():
    """OWNER DECISION NEEDED.  When D's money frees, D's conditional maxima
    respond lowest lot first.  D's $50 first pushes lot X's leader to $51,
    then the same $50 wins lot Y at $21 in the same atomic transaction, so
    after commit X's price rests on a maximum D can afford only $29 of.  Had
    Y been numbered lower, X would sit at $30.  Each step is affordable when
    it happens (sequential semantics), but the committed state prices X as if
    D could still pay $50.  Current behaviour pinned, not endorsed."""
    r = Room([100, 100, 100, 100, 100, 100, 100, 100, 50, 100, 100, 100])
    x = r.nominate("S1", "P1")  # L = S1
    y = r.nominate("S2", "P2")  # M = S2
    z = r.nominate("S3", "P3")
    r.bid("S1", x, 70)  # leader raise, price stays 0
    r.bid("S2", y, 20)
    r.bid("S9", z, 50)  # D = S9 ($50)
    r.bid("S4", z, 49)
    assert r.lot(z) == ("S9", 50) and engine.spendable(r.s, "S9") == 0
    r.bid("S9", x, 50)
    r.bid("S9", y, 50)
    assert r.lot(x) == ("S1", 1) and r.lot(y) == ("S2", 1)
    r.bid("S5", z, 60)  # D displaced → $50 freed
    assert r.lot(x) == ("S1", 51)
    assert r.lot(y) == ("S9", 21)
    assert engine.capacity(r.s, "S9", x) == 29  # post-commit, D cannot pay $50 on X
