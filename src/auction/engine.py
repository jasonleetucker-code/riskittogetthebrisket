"""Deterministic rules engine for the rookie auction room.

Pure: no network, no database, no clock.  Every function takes the room
``state`` (a JSON-serialisable dict), a command, and the server-owned ``now``
(epoch seconds) and returns a NEW state plus a result and a list of events.
The store serialises commands per room and persists the returned state, so
this module is the single owner of every auction rule; the API, the ticker,
the bots and the tests all go through ``apply_command``.

Money and the multi-auction problem
-----------------------------------
Dollars are integers.  Per seat:

    balance     = opening + adjustments + transfers_in - transfers_out - settled purchases
    committed   = sum of CURRENT public prices on open auctions the seat leads
    spendable   = balance - committed

A seat's stored maximum on auction ``a`` is a CONDITIONAL instruction.  Its
EFFECTIVE ceiling there is

    effective(s, a) = min(max(s, a), balance(s) - committed(s, excluding a))

— this auction's own current commitment is replaced, not charged twice, and
money leading elsewhere is not available.  An unaffordable maximum therefore
never sets a phantom price.  Because every price a seat is charged is bounded
by that capacity, ``committed <= balance`` holds for every seat after every
transition (asserted in ``check_invariants``).

Resolving one auction (fixed effective ceilings):

* candidates: every active bid whose effective ceiling is at least the
  current public price (the current leader always is — see invariants);
* winner: highest effective ceiling, ties to the EARLIEST accepted sequence
  at that level;
* price: unchanged with no rival; the tie value on an exact tie; otherwise
  ``min(winner, runner_up + 1)``; never below the existing public price.

Cross-auction resolution is a deterministic worklist.  When a seat is
displaced as leader its commitment is released, so its other open auctions
where it holds an active maximum above the current price are re-resolved
(lowest auction number first).  Public prices never decrease; a leader change
at an unchanged price moves leadership to a strictly earlier sequence; so the
cascade terminates.  It is additionally bounded and fails the whole command
(nothing is persisted) rather than ever writing a half-resolved room.

Prices move only when a competitive action moves them.  A leader that won a
TIE while budget-capped keeps that price when its money is later freed
elsewhere — the runner-up's instruction could not go higher, so nothing
happened on that auction.  The next competitive action there re-resolves it
with the leader's full current capacity.
"""

from __future__ import annotations

import hashlib
import random
from copy import deepcopy
from typing import Any, Iterable

from src.auction import schedule
from src.auction.rules import MAX_DOLLARS, unconfirmed_rules, validate_rules, window_of

STATE_SCHEMA = 1
_CASCADE_BOUND = 100_000

SEAT_KINDS = frozenset(
    {
        "nominate",
        "bid",
        "withdraw",
        "pass_nomination",
        "set_queue",
        "offer_trade",
        "respond_trade",
        "cancel_trade",
    }
)
COMMISSIONER_KINDS = frozenset(
    {
        "configure",
        "set_seat",
        "set_order",
        "start",
        "pause",
        "resume",
        "adjust_budget",
        "confirm_rules",
        "verify_trade",
        # Server-issued only (not in the HTTP command allow-list): announces
        # that the commissioner changed WHO holds a seat.  Moves no money.
        "note_member_change",
    }
)
SYSTEM_KINDS = frozenset({"advance"})


class AuctionError(Exception):
    """A rejected command.  ``status`` maps onto HTTP."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def new_room_state(
    *,
    room_id: str,
    name: str,
    room_type: str,
    rules: dict[str, Any],
    seats: list[dict[str, Any]],
    order: list[str] | None,
    pool: dict[str, Any],
    created_at: float,
) -> dict[str, Any]:
    if room_type not in ("mock", "official"):
        raise AuctionError("bad_room_type", "room_type must be mock or official")
    try:
        validate_rules(rules)
    except ValueError as exc:
        raise AuctionError("bad_rules", str(exc)) from exc
    if len(seats) != rules["seat_count"]:
        raise AuctionError("bad_seats", f"expected {rules['seat_count']} seats, got {len(seats)}")
    seat_ids = [str(s["id"]) for s in seats]
    if len(set(seat_ids)) != len(seat_ids):
        raise AuctionError("bad_seats", "duplicate seat ids")
    norm_seats = []
    for s in seats:
        budget = s.get("opening_budget")
        if budget is not None:
            budget = _require_dollars(budget, "opening_budget")
        norm_seats.append(
            {
                "id": str(s["id"]),
                "name": str(s.get("name") or s["id"])[:80],
                "team": str(s.get("team") or "")[:80],
                "sleeper_user_id": s.get("sleeper_user_id"),
                "roster_id": s.get("roster_id"),
                "opening_budget": budget,
                "budget_source": s.get("budget_source")
                or ("missing" if budget is None else "manual"),
                "is_bot": bool(s.get("is_bot")),
                "bot_seed": int(s.get("bot_seed") or 0),
            }
        )
    order = list(order) if order else list(seat_ids)
    _validate_order(order, seat_ids)
    players = pool.get("players") or {}
    if not isinstance(players, dict) or not players:
        raise AuctionError("bad_pool", "rookie pool is empty")
    state = {
        "schema": STATE_SCHEMA,
        "room_id": room_id,
        "name": str(name)[:120],
        "room_type": room_type,
        "rules": deepcopy(rules),
        "status": "setup",
        "drain_reason": None,
        "paused": None,
        "seq": 0,
        "seats": norm_seats,
        "order": order,
        "pool": {
            "version": str(pool.get("version") or "unversioned"),
            "label": str(pool.get("label") or ""),
            "is_official_class": bool(pool.get("is_official_class")),
            "players": deepcopy(players),
        },
        "rights": [],
        "auctions": {},
        "auction_order": [],
        "next_auction": 1,
        "ledger": [],
        "queues": {},
        "bid_log": [],
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "last_event_at": created_at,
    }
    return state


def _validate_order(order: list[str], seat_ids: list[str]) -> None:
    if sorted(order) != sorted(seat_ids) or len(order) != len(seat_ids):
        raise AuctionError("bad_order", "nomination order must list every seat exactly once")


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def _require_dollars(value: Any, field: str) -> int:
    # bool is an int subclass — reject it explicitly.  Floats, strings,
    # NaN/inf and negatives are all rejected; there is no rounding.
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuctionError("bad_amount", f"{field} must be a whole-dollar integer")
    if value < 0 or value > MAX_DOLLARS:
        raise AuctionError("bad_amount", f"{field} must be between 0 and {MAX_DOLLARS}")
    return value


def _seat(state: dict, seat_id: str) -> dict:
    for s in state["seats"]:
        if s["id"] == seat_id:
            return s
    raise AuctionError("unknown_seat", f"unknown seat {seat_id}", 404)


def balance(state: dict, seat_id: str) -> int:
    seat = _seat(state, seat_id)
    total = int(seat["opening_budget"] or 0)
    for entry in state["ledger"]:
        if entry["seat"] == seat_id:
            total += int(entry["amount"])
    for a in _auctions(state):
        if a["status"] == "closed" and a["winner"] == seat_id:
            total -= int(a["price"])
    return total


def committed(state: dict, seat_id: str, exclude: str | None = None) -> int:
    return sum(
        int(a["price"])
        for a in _auctions(state)
        if a["status"] == "open" and a["leader"] == seat_id and a["id"] != exclude
    )


def spendable(state: dict, seat_id: str) -> int:
    return balance(state, seat_id) - committed(state, seat_id)


def capacity(state: dict, seat_id: str, auction_id: str) -> int:
    return balance(state, seat_id) - committed(state, seat_id, exclude=auction_id)


def total_opening_pool(state: dict) -> int:
    return sum(int(s["opening_budget"] or 0) for s in state["seats"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auctions(state: dict) -> Iterable[dict]:
    for aid in state["auction_order"]:
        yield state["auctions"][aid]


def open_auctions(state: dict) -> list[dict]:
    return [a for a in _auctions(state) if a["status"] == "open"]


def _next_seq(state: dict) -> int:
    state["seq"] += 1
    return state["seq"]


def _ev(events: list, etype: str, vis: str, **data: Any) -> None:
    events.append({"type": etype, "vis": vis, "data": data})


def _window(state: dict) -> schedule.ActiveWindow:
    return window_of(state["rules"])


def _require_running(state: dict, now: float, *, binding: bool = True) -> None:
    if state["status"] not in ("running", "draining"):
        raise AuctionError("not_running", "the room is not running", 409)
    if state["paused"]:
        raise AuctionError(
            "paused", "the room is paused — no binding actions until it resumes", 409
        )
    if binding and not schedule.is_active(_window(state), now):
        raise AuctionError(
            "quiet_hours",
            "binding actions are closed during the nightly pause (9 PM–8 AM Eastern)",
            409,
        )


def _awarded_or_open_players(state: dict) -> set[str]:
    return {a["player"] for a in _auctions(state)}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def priority_at(bid: dict, level: int) -> int:
    """Tie priority of ``bid`` at ``level``: the EARLIEST accepted bid since
    which this seat has continuously held a maximum >= ``level``.

    A raise therefore earns new priority only for the NEW, higher levels
    ("not retroactively from an earlier low bid"), while a seat that already
    stood at a level keeps its priority there through later raises and
    reductions.  A withdrawal breaks continuity (history restarts).
    """
    hist = bid.get("hist") or [[int(bid["max"]), int(bid["seq"])]]
    best = None
    for mx, seq in reversed(hist):
        if int(mx) < level:
            break
        best = int(seq)
    return best if best is not None else int(bid["seq"])


def _set_max(a: dict, seat_id: str, new_max: int, seq: int, now: float) -> None:
    old = a["bids"].get(seat_id)
    hist = (
        list(old.get("hist") or [[int(old["max"]), int(old["seq"])]])
        if old and old["active"]
        else []
    )
    hist.append([new_max, seq])
    a["bids"][seat_id] = {"max": new_max, "seq": seq, "active": True, "at": now, "hist": hist[-50:]}


def _resolve_one(state: dict, auction: dict) -> tuple[str, int]:
    """Winner/price for one auction under CURRENT capacities."""
    price = int(auction["price"])
    leader = auction["leader"]
    cands: list[tuple[int, int, str]] = []
    for seat_id, bid in auction["bids"].items():
        if not bid["active"] and seat_id != leader:
            continue
        eff = min(int(bid["max"]), capacity(state, seat_id, auction["id"]))
        if seat_id == leader:
            if eff < price:  # invariant — a leader can always cover its own price
                raise AssertionError(
                    f"leader {seat_id} effective {eff} < price {price} on {auction['id']}"
                )
        elif eff < price:
            continue
        cands.append((eff, priority_at(bid, eff), seat_id))
    cands.sort(key=lambda c: (-c[0], c[1]))
    win_eff, _, winner = cands[0]
    if len(cands) == 1:
        new_price = price
    else:
        second = cands[1][0]
        new_price = win_eff if second == win_eff else min(win_eff, second + 1)
    new_price = max(new_price, price)
    return winner, new_price


def _cascade(state: dict, start: Iterable[str], now: float, events: list) -> set[str]:
    """Re-resolve auctions until stable.  Returns ids whose public state changed."""
    pending = set(start)
    changed: set[str] = set()
    steps = 0
    order_index = {aid: i for i, aid in enumerate(state["auction_order"])}
    while pending:
        steps += 1
        if steps > _CASCADE_BOUND:
            raise AuctionError("resolution_bound", "proxy resolution did not converge", 500)
        aid = min(pending, key=lambda x: order_index[x])
        pending.discard(aid)
        a = state["auctions"][aid]
        if a["status"] != "open":
            continue
        old_leader, old_price = a["leader"], int(a["price"])
        winner, price = _resolve_one(state, a)
        if winner == old_leader and price == old_price:
            continue
        a["leader"], a["price"] = winner, price
        changed.add(aid)
        if winner != old_leader:
            # Displaced seat's money is free again: its other conditional
            # maxima may now be affordable.
            for other in open_auctions(state):
                if other["id"] == aid or other["leader"] == old_leader:
                    continue
                b = other["bids"].get(old_leader)
                if b and b["active"] and int(b["max"]) >= int(other["price"]):
                    pending.add(other["id"])
    return changed


def _publish_changes(state: dict, changed: set[str], now: float, events: list) -> None:
    win = _window(state)
    ext = int(state["rules"]["extension_active_seconds"])
    for aid in sorted(changed, key=state["auction_order"].index):
        a = state["auctions"][aid]
        extended = False
        if ext > 0 and not state["paused"]:
            candidate = schedule.add_active(win, now, ext)
            if candidate > a["deadline"]:
                a["deadline"] = candidate
                a["extensions"] += 1
                extended = True
        _ev(
            events,
            "price",
            "public",
            auction=aid,
            player=a["player"],
            price=a["price"],
            leader=a["leader"],
            deadline=a["deadline"],
            extended=extended,
        )


# ---------------------------------------------------------------------------
# Nomination rights
# ---------------------------------------------------------------------------


def _build_rights(state: dict) -> None:
    rights = []
    for rnd in range(1, int(state["rules"]["rounds"]) + 1):
        for idx, seat_id in enumerate(state["order"]):
            rights.append(
                {
                    "id": f"R{rnd}.{idx + 1}",
                    "round": rnd,
                    "index": idx,
                    "seat": seat_id,
                    "status": "pending",
                    "window_at": None,
                    "deadline": None,
                    "remaining": None,
                    "auction": None,
                }
            )
    state["rights"] = rights


def _window_rights(state: dict) -> list[dict]:
    """Rights currently on the nomination clock.

    The first ``free slots`` pending rights in (round, order) sequence, each
    seat at most once (its earliest pending right).  A right only enters this
    window when a slot exists, so a full board never runs anyone's clock.
    """
    if state["status"] != "running":
        return []
    free = int(state["rules"]["max_open"]) - len(open_auctions(state))
    if free <= 0:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for r in state["rights"]:
        if r["status"] != "pending":
            continue
        if r["seat"] in seen:
            continue
        seen.add(r["seat"])
        out.append(r)
        if len(out) >= free:
            break
    return out


def _refresh_window(state: dict, at: float, events: list) -> None:
    """Stamp newly-on-the-clock rights with their start and timeout."""
    win = _window(state)
    timeout = state["rules"].get("nomination_timeout_active_seconds")
    for r in _window_rights(state):
        if r["window_at"] is None:
            r["window_at"] = at
            r["deadline"] = schedule.add_active(win, at, timeout) if timeout else None
            _ev(
                events,
                "nomination_turn",
                "public",
                right=r["id"],
                seat=r["seat"],
                round=r["round"],
                deadline=r["deadline"],
            )


def _current_right_for(state: dict, seat_id: str) -> dict | None:
    for r in _window_rights(state):
        if r["seat"] == seat_id:
            return r
    return None


def _open_auction(
    state: dict, right: dict, player_id: str, now: float, events: list, *, via: str
) -> dict:
    win = _window(state)
    aid = f"A{state['next_auction']}"
    state["next_auction"] += 1
    seq = _next_seq(state)
    auction = {
        "id": aid,
        "player": player_id,
        "nominator": right["seat"],
        "round": right["round"],
        "right": right["id"],
        "opened_at": now,
        "nom_seq": seq,
        "status": "open",
        "price": 0,
        "leader": right["seat"],
        "deadline": schedule.add_active(win, now, int(state["rules"]["auction_active_seconds"])),
        "remaining": None,
        # The nomination itself is a binding $0 bid by the nominator.
        "bids": {
            right["seat"]: {"max": 0, "seq": seq, "active": True, "at": now, "hist": [[0, seq]]}
        },
        "closed_at": None,
        "winner": None,
        "extensions": 0,
        # Every seat that has held the lead at the END of a committed
        # transaction (drives the net "leading again" alert).
        "led_by": [right["seat"]],
    }
    state["auctions"][aid] = auction
    state["auction_order"].append(aid)
    right["status"] = "used"
    right["auction"] = aid
    state["bid_log"].append(
        {
            "seq": seq,
            "at": now,
            "seat": right["seat"],
            "auction": aid,
            "max": 0,
            "kind": "nomination",
        }
    )
    p = state["pool"]["players"][player_id]
    _ev(
        events,
        "nominated",
        "public",
        auction=aid,
        player=player_id,
        player_name=p.get("name"),
        seat=right["seat"],
        round=right["round"],
        deadline=auction["deadline"],
        via=via,
    )
    return auction


def _validate_nominee(state: dict, player_id: Any) -> str:
    if not isinstance(player_id, str) or not player_id or len(player_id) > 64:
        raise AuctionError("bad_player", "invalid player id")
    if player_id not in state["pool"]["players"]:
        raise AuctionError("not_eligible", "player is not in this room's frozen rookie pool")
    if player_id in _awarded_or_open_players(state):
        raise AuctionError("already_nominated", "player is already open or awarded", 409)
    return player_id


# ---------------------------------------------------------------------------
# Time advancement
# ---------------------------------------------------------------------------


def _due_events(state: dict) -> list[tuple[float, int, str, str]]:
    """(time, priority, kind, id) for every scheduled transition."""
    if state["status"] not in ("running", "draining") or state["paused"]:
        return []
    due: list[tuple[float, int, str, str]] = []
    win = _window(state)
    deferred = state.get("deferred_reresolve") or []
    if deferred:
        # Priority -1: re-resolve before a close due at the same instant.
        at = max(float(i["at"]) for i in deferred)
        due.append((schedule.next_active_start(win, at), -1, "reresolve", ""))
    for a in open_auctions(state):
        due.append((a["deadline"], 0, "close", a["id"]))
    if state["status"] == "running":
        for r in _window_rights(state):
            if r["window_at"] is None:
                continue
            q = state["queues"].get(r["seat"]) or {}
            if state["rules"].get("auto_nomination_queue") and q.get("auto") and q.get("players"):
                due.append((schedule.next_active_start(win, r["window_at"]), 1, "autonom", r["id"]))
            if r["deadline"] is not None:
                due.append((r["deadline"], 2, "timeout", r["id"]))
    due.sort(key=lambda d: (d[0], d[1], _id_order(state, d)))
    return due


def _id_order(state: dict, d: tuple) -> int:
    if d[2] == "reresolve":
        return 0
    if d[2] == "close":
        return state["auction_order"].index(d[3])
    return [r["id"] for r in state["rights"]].index(d[3])


def next_due_time(state: dict) -> float | None:
    due = _due_events(state)
    return due[0][0] if due else None


def _advance(state: dict, now: float, events: list) -> bool:
    progressed = False
    for _ in range(10_000):
        due = _due_events(state)
        if not due or due[0][0] > now:
            break
        t, _, kind, ident = due[0]
        progressed = True
        if kind == "reresolve":
            _run_deferred_reresolve(state, t, events)
        elif kind == "close":
            _close_auction(state, state["auctions"][ident], t, events)
        elif kind == "timeout":
            r = _right(state, ident)
            r["status"] = "passed"
            _ev(
                events,
                "nomination_passed",
                "public",
                right=r["id"],
                seat=r["seat"],
                reason="timeout",
                at=t,
            )
        elif kind == "autonom":
            r = _right(state, ident)
            _try_auto_nominate(state, r, t, events)
        _refresh_window(state, t, events)
        _check_completion(state, t, events)
    return progressed


def _right(state: dict, right_id: str) -> dict:
    for r in state["rights"]:
        if r["id"] == right_id:
            return r
    raise AuctionError("unknown_right", right_id, 404)


def _try_auto_nominate(state: dict, right: dict, t: float, events: list) -> None:
    q = state["queues"].get(right["seat"]) or {}
    players = list(q.get("players") or [])
    chosen = None
    while players:
        pid = players.pop(0)
        try:
            chosen = _validate_nominee(state, pid)
            break
        except AuctionError:
            _ev(
                events,
                "queue_skipped",
                f"seat:{right['seat']}",
                player=pid,
                reason="no_longer_eligible",
            )
            continue
    q["players"] = players
    if chosen is None:
        # Nothing valid left: stop auto-nominating; the normal turn clock
        # continues.  Never a substitute pick.
        q["auto"] = False
        _ev(events, "queue_exhausted", f"seat:{right['seat']}")
        return
    _open_auction(state, right, chosen, t, events, via="queue")


def _close_auction(state: dict, a: dict, t: float, events: list) -> None:
    a["status"] = "closed"
    a["closed_at"] = t
    a["winner"] = a["leader"]
    _ev(
        events,
        "sold",
        "public",
        auction=a["id"],
        player=a["player"],
        player_name=state["pool"]["players"][a["player"]].get("name"),
        seat=a["winner"],
        price=a["price"],
        at=t,
    )


def _check_completion(state: dict, t: float, events: list) -> None:
    if state["status"] == "running":
        pool = total_opening_pool(state)
        money_spent = (
            bool(state["rules"].get("end_when_money_spent"))
            and pool > 0  # an all-$0 room never "spends all its money"
            and all(balance(state, s["id"]) == 0 for s in state["seats"])
        )
        rights_left = any(r["status"] == "pending" for r in state["rights"])
        if money_spent:
            for r in state["rights"]:
                if r["status"] == "pending":
                    r["status"] = "void"
            state["status"] = "draining"
            state["drain_reason"] = "money_spent"
            _ev(events, "draining", "public", reason="money_spent", at=t)
        elif not rights_left:
            state["status"] = "draining"
            state["drain_reason"] = "rights_exhausted"
            _ev(events, "draining", "public", reason="rights_exhausted", at=t)
    if state["status"] == "draining" and not open_auctions(state):
        state["status"] = "complete"
        state["completed_at"] = t
        _ev(
            events,
            "complete",
            "public",
            reason=state["drain_reason"],
            unspent={s["id"]: balance(state, s["id"]) for s in state["seats"]},
            at=t,
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def apply_command(state: dict, cmd: dict, now: float) -> tuple[dict, dict, list[dict]]:
    """Apply one command.  Returns ``(new_state, result, events)``.

    The input state is never mutated.  On ``AuctionError`` nothing changes.
    Time-driven transitions due at or before ``now`` are applied FIRST, so a
    delayed close worker can never open a late-bidding window: an auction
    whose deadline has passed is closed before the bid is even looked at.
    """
    s = deepcopy(state)
    events: list[dict] = []
    kind = cmd.get("kind")
    actor = cmd.get("actor") or {}
    role = actor.get("role")
    seat_id = actor.get("seat")

    if kind in COMMISSIONER_KINDS:
        if role != "commissioner":
            raise AuctionError("forbidden", "commissioner only", 403)
    elif kind in SEAT_KINDS:
        if role not in ("manager", "commissioner", "bot") or not seat_id:
            raise AuctionError("forbidden", "a seat is required for this action", 403)
        _seat(s, seat_id)
    elif kind in SYSTEM_KINDS:
        if role != "system":
            raise AuctionError("forbidden", "system only", 403)
    else:
        raise AuctionError("unknown_command", f"unknown command {kind!r}")

    # An outage pause is stamped at the last moment the service was known to
    # be reachable; nothing due AFTER that moment may settle first.
    advance_to = now
    if kind == "pause" and cmd.get("at") is not None:
        advance_to = min(now, float(cmd["at"]))
    _advance(s, advance_to, events)
    # Leadership is reported NET per committed transaction: an intermediate
    # proxy-cascade step that displaces and then restores a seat is not an
    # "outbid" (owner rule, AUC-002).
    leaders_before = {a["id"]: a["leader"] for a in open_auctions(s)}
    handler = _HANDLERS[kind]
    result = handler(s, cmd, now, events) or {}
    _emit_net_leadership(s, leaders_before, now, events)
    if kind != "advance":
        _refresh_window(s, now, events)
        _check_completion(s, now, events)
    check_invariants(s)
    if events:
        s["last_event_at"] = now
    return s, result, events


def _emit_net_leadership(s: dict, leaders_before: dict, now: float, events: list) -> None:
    for aid, before in leaders_before.items():
        a = s["auctions"][aid]
        if a["status"] != "open" or a["leader"] == before:
            continue
        after = a["leader"]
        led_by = a.setdefault("led_by", [a["nominator"]])
        _ev(events, "outbid", f"seat:{before}", auction=aid, player=a["player"], price=a["price"])
        if after in led_by:
            _ev(
                events,
                "leading_again",
                f"seat:{after}",
                auction=aid,
                player=a["player"],
                price=a["price"],
            )
        else:
            # First time this seat leads the lot through the resolver (its own
            # bid, or its standing maximum after money freed).  The notifier
            # tells the seat only when someone ELSE's action caused it.
            _ev(
                events,
                "proxy_leading",
                f"seat:{after}",
                auction=aid,
                player=a["player"],
                price=a["price"],
            )
            led_by.append(after)


def _cmd_advance(s: dict, cmd: dict, now: float, events: list) -> dict:
    return {"ok": True}


def _cmd_configure(s: dict, cmd: dict, now: float, events: list) -> dict:
    if s["status"] != "setup":
        raise AuctionError("frozen", "rules are frozen once the room starts", 409)
    patch = cmd.get("rules") or {}
    allowed = {
        "auction_active_seconds",
        "extension_active_seconds",
        "nomination_timeout_active_seconds",
        "window",
        "end_when_money_spent",
        "outage_threshold_seconds",
        "resume_min_active_seconds",
        "auto_nomination_queue",
        "rounds",
        "max_open",
    }
    bad = set(patch) - allowed
    if bad:
        raise AuctionError("bad_rules", f"not configurable: {sorted(bad)}")
    merged = deepcopy(s["rules"])
    merged.update(deepcopy(patch))
    merged["timing_preset"] = "custom" if patch else merged.get("timing_preset")
    merged["confirmations"] = {}  # any rule change voids prior confirmations
    try:
        validate_rules(merged)
    except ValueError as exc:
        raise AuctionError("bad_rules", str(exc)) from exc
    s["rules"] = merged
    _ev(events, "rules_changed", "public", keys=sorted(patch))
    return {"ok": True}


def _cmd_confirm_rules(s: dict, cmd: dict, now: float, events: list) -> dict:
    if s["status"] != "setup":
        raise AuctionError("frozen", "rules are frozen once the room starts", 409)
    keys = cmd.get("keys") or []
    from src.auction.rules import PROPOSED_RULE_KEYS

    for k in keys:
        if k not in PROPOSED_RULE_KEYS:
            raise AuctionError("bad_rules", f"unknown rule key {k}")
        s["rules"].setdefault("confirmations", {})[k] = {
            "at": now,
            "by": (cmd.get("actor") or {}).get("user"),
        }
    _ev(events, "rules_confirmed", "commissioner", keys=list(keys))
    return {"ok": True, "unconfirmed": unconfirmed_rules(s["rules"])}


def _cmd_set_seat(s: dict, cmd: dict, now: float, events: list) -> dict:
    seat = _seat(s, str(cmd.get("seat")))
    patch = cmd.get("patch") or {}
    if not isinstance(patch, dict):
        raise AuctionError("bad_request", "patch must be an object")
    if s["status"] == "setup":
        allowed = {"name", "team", "opening_budget", "budget_source", "is_bot", "bot_seed"}
    elif s["room_type"] == "mock":
        # Mock rooms may hand a bot seat to a person mid-run (or back).
        allowed = {"name", "is_bot"}
    else:
        allowed = {"name"}
    bad = set(patch) - allowed
    if bad:
        raise AuctionError("frozen", f"cannot change {sorted(bad)} now", 409)
    before = {k: seat.get(k) for k in patch}
    for k, v in patch.items():
        if k == "opening_budget":
            v = None if v is None else _require_dollars(v, "opening_budget")
            if "budget_source" not in patch:
                seat["budget_source"] = "commissioner_override"
        elif k in ("name", "team", "budget_source"):
            v = str(v)[:80]
        elif k == "is_bot":
            v = bool(v)
        elif k == "bot_seed":
            if isinstance(v, bool) or not isinstance(v, int):
                raise AuctionError("bad_request", "bot_seed must be an integer")
        seat[k] = v
    _ev(
        events,
        "seat_changed",
        "commissioner",
        seat=seat["id"],
        before=before,
        after={k: seat.get(k) for k in patch},
        reason=str(cmd.get("reason") or "")[:200],
    )
    return {"ok": True}


def _cmd_set_order(s: dict, cmd: dict, now: float, events: list) -> dict:
    if s["status"] != "setup":
        raise AuctionError("frozen", "nomination order is frozen once the room starts", 409)
    order = [str(x) for x in (cmd.get("order") or [])]
    _validate_order(order, [x["id"] for x in s["seats"]])
    s["order"] = order
    _ev(
        events,
        "order_changed",
        "public",
        order=order,
        basis=str(cmd.get("basis") or "manual")[:120],
    )
    return {"ok": True}


def _cmd_start(s: dict, cmd: dict, now: float, events: list) -> dict:
    if s["status"] != "setup":
        raise AuctionError("already_started", "room already started", 409)
    missing = [x["id"] for x in s["seats"] if x["opening_budget"] is None]
    if missing:
        raise AuctionError(
            "missing_budgets", f"budgets missing for {missing}; correct them before starting", 409
        )
    if s["room_type"] == "official":
        _require_binding_shape(s)
        unconfirmed = unconfirmed_rules(s["rules"])
        if unconfirmed:
            raise AuctionError("rules_unconfirmed", f"confirm rules first: {unconfirmed}", 409)
        if not s["pool"]["is_official_class"]:
            raise AuctionError(
                "pool_unapproved", "an official room needs an approved eligible rookie pool", 409
            )
    if not schedule.is_active(_window(s), now):
        raise AuctionError("quiet_hours", "a room can only start inside the active window", 409)
    s["status"] = "running"
    s["started_at"] = now
    _build_rights(s)
    _ev(
        events,
        "started",
        "public",
        at=now,
        opening={x["id"]: x["opening_budget"] for x in s["seats"]},
        pool_version=s["pool"]["version"],
        rule_version=s["rules"].get("rule_version"),
    )
    return {"ok": True}


def _require_binding_shape(s: dict) -> None:
    """An OFFICIAL room must match the owner's binding rules exactly."""
    r = s["rules"]
    w = window_of(r)
    problems = []
    if len(s["seats"]) != 12:
        problems.append("12 seats")
    if int(r["rounds"]) != 6:
        problems.append("6 rounds")
    if int(r["max_open"]) != 12:
        problems.append("12 open lots")
    if not (
        w.enabled
        and w.tz == "America/New_York"
        and w.start_seconds == 8 * 3600
        and w.end_seconds == 21 * 3600
    ):
        problems.append("activity 8 AM-9 PM America/New_York")
    if problems:
        raise AuctionError(
            "binding_rules",
            f"an official room must use the owner's rules: {', '.join(problems)}",
            409,
        )


def _cmd_nominate(s: dict, cmd: dict, now: float, events: list) -> dict:
    _require_running(s, now)
    if s["status"] != "running":
        raise AuctionError("draining", "no new nominations — the room is draining", 409)
    seat_id = cmd["actor"]["seat"]
    right = _current_right_for(s, seat_id)
    if right is None:
        if len(open_auctions(s)) >= int(s["rules"]["max_open"]):
            raise AuctionError("board_full", "all nomination slots are open — wait for a sale", 409)
        raise AuctionError("not_your_turn", "you are not on the nomination clock", 409)
    player_id = _validate_nominee(s, cmd.get("player"))
    a = _open_auction(s, right, player_id, now, events, via="manual")
    return {"ok": True, "auction": a["id"]}


def _cmd_pass(s: dict, cmd: dict, now: float, events: list) -> dict:
    _require_running(s, now)
    seat_id = cmd["actor"]["seat"]
    right = _current_right_for(s, seat_id)
    if right is None:
        raise AuctionError("not_your_turn", "you are not on the nomination clock", 409)
    right["status"] = "passed"
    _ev(
        events,
        "nomination_passed",
        "public",
        right=right["id"],
        seat=seat_id,
        reason="manager_pass",
        at=now,
    )
    return {"ok": True}


def _cmd_set_queue(s: dict, cmd: dict, now: float, events: list) -> dict:
    # Private and non-binding: allowed any time, including quiet hours.
    seat_id = cmd["actor"]["seat"]
    players = cmd.get("players") or []
    if not isinstance(players, list) or len(players) > 200:
        raise AuctionError("bad_queue", "queue must be a list of at most 200 player ids")
    clean = []
    for p in players:
        if not isinstance(p, str) or p not in s["pool"]["players"]:
            raise AuctionError("not_eligible", f"{p!r} is not in the rookie pool")
        if p not in clean:
            clean.append(p)
    auto = bool(cmd.get("auto"))
    s["queues"][seat_id] = {"players": clean, "auto": auto, "authorized_at": now if auto else None}
    _ev(events, "queue_set", f"seat:{seat_id}", count=len(clean), auto=auto)
    return {"ok": True}


def _cmd_bid(s: dict, cmd: dict, now: float, events: list) -> dict:
    seat_id = cmd["actor"]["seat"]
    aid = str(cmd.get("auction") or "")
    a = s["auctions"].get(aid)
    if a is None:
        raise AuctionError("unknown_auction", "no such auction", 404)
    if a["status"] != "open":
        raise AuctionError("closed", "this auction has closed", 409)
    _require_running(s, now)
    new_max = _require_dollars(cmd.get("max"), "max")
    bal = balance(s, seat_id)
    if new_max > bal:
        raise AuctionError(
            "over_balance",
            f"a maximum of ${new_max} exceeds your balance of ${bal}",
            409,
        )
    price = int(a["price"])
    existing = a["bids"].get(seat_id)
    is_leader = a["leader"] == seat_id
    if new_max < price:
        if is_leader:
            raise AuctionError(
                "below_binding", f"you lead at ${price}; your maximum cannot go below it", 409
            )
        raise AuctionError("below_price", f"the current price is ${price}", 409)
    if existing and existing["active"] and int(existing["max"]) == new_max:
        return {"ok": True, "noop": True, **_my_status(s, seat_id, a)}
    if is_leader:
        # The current leader changing their OWN private maximum is not a
        # competitive action: it never re-resolves the lot, never moves the
        # public price, never extends the clock ("bidding against your own
        # earlier maximum never raises your price").  Tie priority per level
        # is kept by ``priority_at``.
        seq = _next_seq(s)
        _set_max(a, seat_id, new_max, seq, now)
        s["bid_log"].append(
            {
                "seq": seq,
                "at": now,
                "seat": seat_id,
                "auction": aid,
                "max": new_max,
                "kind": "leader_max",
            }
        )
    else:
        seq = _next_seq(s)
        _set_max(a, seat_id, new_max, seq, now)
        s["bid_log"].append(
            {"seq": seq, "at": now, "seat": seat_id, "auction": aid, "max": new_max, "kind": "max"}
        )
        changed = _cascade(s, [aid], now, events)
        _publish_changes(s, changed, now, events)
    status = _my_status(s, seat_id, a)
    _ev(events, "bid_accepted", f"seat:{seat_id}", auction=aid, max=new_max, **status)
    return {"ok": True, **status}


def _my_status(s: dict, seat_id: str, a: dict) -> dict:
    b = a["bids"].get(seat_id)
    cap = capacity(s, seat_id, a["id"])
    mx = int(b["max"]) if b else None
    return {
        "leading": a["leader"] == seat_id,
        "price": int(a["price"]),
        "effective_max": None if mx is None else min(mx, cap),
        "capped": mx is not None and cap < mx,
        "capacity": cap,
    }


def _cmd_withdraw(s: dict, cmd: dict, now: float, events: list) -> dict:
    seat_id = cmd["actor"]["seat"]
    a = s["auctions"].get(str(cmd.get("auction") or ""))
    if a is None:
        raise AuctionError("unknown_auction", "no such auction", 404)
    if a["status"] != "open":
        raise AuctionError("closed", "this auction has closed", 409)
    _require_running(s, now)
    if a["leader"] == seat_id:
        raise AuctionError(
            "leader_cannot_withdraw", "the current leader cannot withdraw a binding price", 409
        )
    b = a["bids"].get(seat_id)
    if not b or not b["active"]:
        return {"ok": True, "noop": True}
    b["active"] = False
    s["bid_log"].append(
        {
            "seq": _next_seq(s),
            "at": now,
            "seat": seat_id,
            "auction": a["id"],
            "max": None,
            "kind": "withdraw",
        }
    )
    _ev(events, "proxy_disabled", f"seat:{seat_id}", auction=a["id"])
    return {"ok": True}


def _cmd_note_member_change(s: dict, cmd: dict, now: float, events: list) -> dict:
    seat = cmd.get("seat")
    if seat is not None:
        _seat(s, seat)
    change = str(cmd.get("change") or "removed")
    if change not in ("removed",):
        raise AuctionError("bad_change", "unknown membership change")
    # Public and reason-free: the audit log keeps the reason.
    _ev(events, "member_changed", "public", seat=seat, change=change)
    return {"ok": True}


def _cmd_pause(s: dict, cmd: dict, now: float, events: list) -> dict:
    if s["status"] not in ("running", "draining"):
        raise AuctionError("not_running", "the room is not running", 409)
    if s["paused"]:
        return {"ok": True, "noop": True}
    at = float(cmd.get("at", now))
    if at > now:
        raise AuctionError("bad_time", "pause cannot start in the future")
    win = _window(s)
    for a in open_auctions(s):
        a["remaining"] = schedule.active_between(win, at, a["deadline"])
    for r in s["rights"]:
        if r["status"] == "pending" and r["deadline"] is not None:
            r["remaining"] = schedule.active_between(win, at, r["deadline"])
    kind = str(cmd.get("pause_kind") or "commissioner")
    s["paused"] = {"at": at, "reason": str(cmd.get("reason") or "")[:300], "kind": kind}
    _ev(events, "paused", "public", at=at, reason=s["paused"]["reason"], kind=kind)
    return {"ok": True}


def _cmd_resume(s: dict, cmd: dict, now: float, events: list) -> dict:
    if not s["paused"]:
        return {"ok": True, "noop": True}
    win = _window(s)
    floor = cmd.get("min_remaining_active_seconds")
    if floor is None:
        floor = (
            int(s["rules"]["resume_min_active_seconds"]) if s["paused"]["kind"] == "outage" else 0
        )
    if isinstance(floor, bool) or not isinstance(floor, int) or not (0 <= floor <= 10 * 24 * 3600):
        raise AuctionError(
            "bad_time", "min remaining must be a whole number of seconds, 0 to 10 days"
        )
    start = now
    for a in open_auctions(s):
        rem = max(float(a["remaining"] or 0.0), float(floor))
        a["deadline"] = schedule.add_active(win, start, rem)
        a["remaining"] = None
    for r in s["rights"]:
        if r["status"] == "pending" and r["remaining"] is not None:
            rem = max(float(r["remaining"]), float(floor))
            r["deadline"] = schedule.add_active(win, start, rem)
            r["remaining"] = None
    was = s["paused"]
    s["paused"] = None
    _ev(
        events,
        "resumed",
        "public",
        at=now,
        reason=str(cmd.get("reason") or "")[:300],
        paused_kind=was["kind"],
        min_remaining_active_seconds=floor,
    )
    # Corrections credited during the pause take effect now (or at the next
    # active moment, via the "reresolve" due event, if resumed in quiet hours).
    if schedule.is_active(win, now):
        _run_deferred_reresolve(s, now, events)
    else:
        for item in s.get("deferred_reresolve") or []:
            item["at"] = max(float(item["at"]), now)
    return {"ok": True}


def _cmd_adjust_budget(s: dict, cmd: dict, now: float, events: list) -> dict:
    seat_id = str(cmd.get("seat"))
    _seat(s, seat_id)
    amount = cmd.get("amount")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, int)
        or abs(amount) > MAX_DOLLARS
        or amount == 0
    ):
        raise AuctionError("bad_amount", "adjustment must be a non-zero whole-dollar integer")
    reason = str(cmd.get("reason") or "").strip()
    if not reason:
        raise AuctionError("reason_required", "a reason is required for a budget adjustment")
    if s["status"] == "complete":
        raise AuctionError("complete", "the room is complete", 409)
    before = balance(s, seat_id)
    after = before + amount
    if after < committed(s, seat_id):
        raise AuctionError(
            "below_obligations",
            f"balance would fall to ${after}, below binding leading commitments of ${committed(s, seat_id)}",
            409,
        )
    s["ledger"].append(
        {
            "seq": _next_seq(s),
            "seat": seat_id,
            "kind": "adjustment",
            "amount": amount,
            "reason": reason[:300],
            "at": now,
        }
    )
    _ev(
        events,
        "budget_adjusted",
        "public",
        seat=seat_id,
        amount=amount,
        before=before,
        after=after,
        reason=reason[:300],
    )
    if amount > 0 and s["status"] in ("running", "draining"):
        if s["paused"] or not schedule.is_active(_window(s), now):
            # Nothing binding moves while the room is paused or inside quiet
            # hours: the money is credited now, and the seat's capped proxies
            # re-resolve at the next active moment (on resume, or 08:00 ET),
            # ahead of any close due at that same instant.
            s.setdefault("deferred_reresolve", []).append({"seat": seat_id, "at": now})
        else:
            _reresolve_seat(s, seat_id, now, events)
    return {"ok": True, "balance": after}


def _reresolve_seat(s: dict, seat_id: str, now: float, events: list) -> None:
    """Money freed or credited for ``seat_id``: its capped proxies respond."""
    start = [a["id"] for a in open_auctions(s) if a["leader"] != seat_id and seat_id in a["bids"]]
    changed = _cascade(s, start, now, events)
    _publish_changes(s, changed, now, events)


def _run_deferred_reresolve(s: dict, now: float, events: list) -> None:
    items = s.get("deferred_reresolve") or []
    if not items:
        return
    s["deferred_reresolve"] = []
    for seat_id in dict.fromkeys(i["seat"] for i in items):
        _reresolve_seat(s, seat_id, now, events)


# ---------------------------------------------------------------------------
# In-room auction-dollar trades (milestone C)
# ---------------------------------------------------------------------------
#
# Rules (proposed, visible in the room):
# * Both parties agree to the SAME immutable terms: an offer has an id and a
#   version; acceptance must name both.  Changing terms means a new offer.
# * Open offers do NOT reserve money.  Affordability and ownership are
#   re-checked atomically at settlement; a trade that no longer fits fails.
# * Only SPENDABLE money moves — dollars reserved by a current lead cannot be
#   sent (AUC-001).
# * Room assets (players won in this room) can move with the dollars in the
#   same transition.  EXTERNAL assets (Sleeper veterans, future picks) are a
#   note only: such a trade waits for the commissioner to verify the external
#   side, and only then do in-room dollars move.  This is not a two-system
#   atomic trade and never claims to be.
# * Binding like a bid: no acceptance during the nightly pause or a room pause.

TRADE_MAX_HOURS = 7 * 24


def _trades(s: dict) -> dict:
    return s.setdefault("trades", {})


def lot_owner(a: dict) -> str | None:
    return a.get("owner") or a.get("winner")


def _check_lots(s: dict, seat: str, lots: list) -> list[str]:
    if not isinstance(lots, list) or len(lots) > 20:
        raise AuctionError("bad_trade", "lots must be a list of at most 20 won lots")
    clean = []
    for aid in lots:
        a = s["auctions"].get(str(aid))
        if not a or a["status"] != "closed" or lot_owner(a) != seat:
            raise AuctionError("bad_trade", f"{aid} is not a won player owned by {seat}", 409)
        if str(aid) not in clean:
            clean.append(str(aid))
    return clean


def _cmd_offer_trade(s: dict, cmd: dict, now: float, events: list) -> dict:
    _require_running(s, now)
    me = cmd["actor"]["seat"]
    to = str(cmd.get("to") or "")
    _seat(s, to)
    if to == me:
        raise AuctionError("bad_trade", "you cannot trade with yourself")
    give = _require_dollars(cmd.get("give_dollars", 0), "give_dollars")
    get = _require_dollars(cmd.get("get_dollars", 0), "get_dollars")
    give_lots = _check_lots(s, me, cmd.get("give_lots") or [])
    get_lots = _check_lots(s, to, cmd.get("get_lots") or [])
    note = str(cmd.get("external_note") or "").strip()[:300]
    if not (give or get or give_lots or get_lots or note):
        raise AuctionError("bad_trade", "an offer must move something")
    hours = cmd.get("expires_hours", 24)
    if (
        isinstance(hours, bool)
        or not isinstance(hours, (int, float))
        or not (1 <= hours <= TRADE_MAX_HOURS)
    ):
        raise AuctionError("bad_trade", f"expiry must be 1-{TRADE_MAX_HOURS} hours")
    tid = f"T{s.get('next_trade', 1)}"
    s["next_trade"] = s.get("next_trade", 1) + 1
    _trades(s)[tid] = {
        "id": tid,
        "version": 1,
        "from": me,
        "to": to,
        "give_dollars": give,
        "get_dollars": get,
        "give_lots": give_lots,
        "get_lots": get_lots,
        "external_note": note,
        "status": "open",
        "created_at": now,
        "expires_at": now + float(hours) * 3600,
        "resolved_at": None,
        "reason": None,
    }
    _ev(events, "trade_offered", f"seat:{to}", trade=tid, **{"from": me})
    _ev(events, "trade_offered_by_you", f"seat:{me}", trade=tid, to=to)
    return {"ok": True, "trade": tid}


def _open_trade(s: dict, tid: str, now: float) -> dict:
    t = _trades(s).get(str(tid))
    if t is None:
        raise AuctionError("unknown_trade", "no such trade", 404)
    if t["status"] == "open" and now >= t["expires_at"]:
        t["status"] = "expired"
        t["resolved_at"] = t["expires_at"]
    return t


def _settle_trade(s: dict, t: dict, now: float, events: list) -> None:
    a, b = t["from"], t["to"]
    # Re-check EVERYTHING against the room as it is now.
    if spendable(s, a) < t["give_dollars"]:
        raise AuctionError(
            "trade_unaffordable", f"{a} no longer has ${t['give_dollars']} spendable", 409
        )
    if spendable(s, b) < t["get_dollars"]:
        raise AuctionError(
            "trade_unaffordable", f"{b} no longer has ${t['get_dollars']} spendable", 409
        )
    _check_lots(s, a, t["give_lots"])
    _check_lots(s, b, t["get_lots"])
    net_a = t["get_dollars"] - t["give_dollars"]
    if net_a:
        s["ledger"].append(
            {
                "seq": _next_seq(s),
                "seat": a,
                "kind": "transfer",
                "amount": net_a,
                "reason": f"trade {t['id']}",
                "at": now,
            }
        )
        s["ledger"].append(
            {
                "seq": _next_seq(s),
                "seat": b,
                "kind": "transfer",
                "amount": -net_a,
                "reason": f"trade {t['id']}",
                "at": now,
            }
        )
    for aid in t["give_lots"]:
        s["auctions"][aid]["owner"] = b
    for aid in t["get_lots"]:
        s["auctions"][aid]["owner"] = a
    t["status"] = "completed"
    t["resolved_at"] = now
    _ev(
        events,
        "trade_completed",
        "public",
        trade=t["id"],
        seats=[a, b],
        dollars={a: -t["give_dollars"] + t["get_dollars"], b: t["give_dollars"] - t["get_dollars"]},
        lots={a: t["get_lots"], b: t["give_lots"]},
        external=bool(t["external_note"]),
    )
    # Money received can reactivate that seat's capped proxies.
    gainer = a if net_a > 0 else b if net_a < 0 else None
    if gainer and s["status"] in ("running", "draining") and not s["paused"]:
        start = [x["id"] for x in open_auctions(s) if x["leader"] != gainer and gainer in x["bids"]]
        changed = _cascade(s, start, now, events)
        _publish_changes(s, changed, now, events)


def _cmd_respond_trade(s: dict, cmd: dict, now: float, events: list) -> dict:
    me = cmd["actor"]["seat"]
    t = _open_trade(s, cmd.get("trade"), now)
    if t["to"] != me:
        raise AuctionError("forbidden", "only the receiving manager can answer this offer", 403)
    if t["status"] != "open":
        raise AuctionError("trade_closed", f"this offer is {t['status']}", 409)
    if cmd.get("version") != t["version"]:
        raise AuctionError("trade_changed", "the terms changed — review the current offer", 409)
    if not cmd.get("accept"):
        t["status"] = "declined"
        t["resolved_at"] = now
        _ev(events, "trade_declined", f"seat:{t['from']}", trade=t["id"])
        return {"ok": True, "status": "declined"}
    _require_running(s, now)
    if t["external_note"]:
        # Affordability is still checked now so an impossible trade is not queued.
        if spendable(s, t["from"]) < t["give_dollars"] or spendable(s, t["to"]) < t["get_dollars"]:
            raise AuctionError(
                "trade_unaffordable", "not enough spendable money for these terms", 409
            )
        t["status"] = "awaiting_verification"
        _ev(
            events,
            "trade_awaiting_verification",
            "commissioner",
            trade=t["id"],
            note=t["external_note"],
        )
        _ev(events, "trade_awaiting_verification", f"seat:{t['from']}", trade=t["id"])
        return {"ok": True, "status": "awaiting_verification"}
    _settle_trade(s, t, now, events)
    return {"ok": True, "status": "completed"}


def _cmd_cancel_trade(s: dict, cmd: dict, now: float, events: list) -> dict:
    me = cmd["actor"]["seat"]
    t = _open_trade(s, cmd.get("trade"), now)
    if t["from"] != me:
        raise AuctionError("forbidden", "only the offering manager can withdraw this offer", 403)
    if t["status"] not in ("open", "awaiting_verification"):
        raise AuctionError("trade_closed", f"this offer is {t['status']}", 409)
    t["status"] = "cancelled"
    t["resolved_at"] = now
    _ev(events, "trade_cancelled", f"seat:{t['to']}", trade=t["id"])
    return {"ok": True}


def _cmd_verify_trade(s: dict, cmd: dict, now: float, events: list) -> dict:
    t = _open_trade(s, cmd.get("trade"), now)
    if t["status"] != "awaiting_verification":
        raise AuctionError("trade_closed", f"this trade is {t['status']}", 409)
    reason = str(cmd.get("reason") or "").strip()
    if not reason:
        raise AuctionError("reason_required", "record how the external side was verified")
    if not cmd.get("approve"):
        t["status"] = "rejected"
        t["resolved_at"] = now
        t["reason"] = reason[:300]
        _ev(events, "trade_rejected", "public", trade=t["id"], reason=t["reason"])
        return {"ok": True, "status": "rejected"}
    _require_running(s, now)
    t["reason"] = reason[:300]
    _settle_trade(s, t, now, events)
    return {"ok": True, "status": "completed"}


def trades_for_seat(s: dict, seat: str, now: float) -> list[dict]:
    out = []
    for t in _trades(s).values():
        if seat in (t["from"], t["to"]):
            view = dict(t)
            if view["status"] == "open" and now >= view["expires_at"]:
                view["status"] = "expired"
            out.append(view)
    return sorted(out, key=lambda t: -t["created_at"])


_HANDLERS = {
    "advance": _cmd_advance,
    "configure": _cmd_configure,
    "confirm_rules": _cmd_confirm_rules,
    "set_seat": _cmd_set_seat,
    "set_order": _cmd_set_order,
    "start": _cmd_start,
    "nominate": _cmd_nominate,
    "pass_nomination": _cmd_pass,
    "set_queue": _cmd_set_queue,
    "bid": _cmd_bid,
    "withdraw": _cmd_withdraw,
    "pause": _cmd_pause,
    "note_member_change": _cmd_note_member_change,
    "resume": _cmd_resume,
    "adjust_budget": _cmd_adjust_budget,
    "offer_trade": _cmd_offer_trade,
    "respond_trade": _cmd_respond_trade,
    "cancel_trade": _cmd_cancel_trade,
    "verify_trade": _cmd_verify_trade,
}


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def check_invariants(s: dict) -> None:
    """Raise AssertionError if the room is in an impossible state."""
    open_count = 0
    players_seen: set[str] = set()
    for a in _auctions(s):
        if a["player"] in players_seen:
            raise AssertionError(f"player {a['player']} nominated twice")
        players_seen.add(a["player"])
        if a["status"] == "open":
            open_count += 1
            if a["leader"] not in a["bids"]:
                raise AssertionError(f"{a['id']} leader has no bid")
            if int(a["price"]) > int(a["bids"][a["leader"]]["max"]):
                raise AssertionError(f"{a['id']} price above leader maximum")
        elif a["winner"] is None:
            raise AssertionError(f"{a['id']} closed without a winner")
        elif lot_owner(a) not in {x["id"] for x in s["seats"]}:
            raise AssertionError(f"{a['id']} owned by an unknown seat")
        if int(a["price"]) < 0:
            raise AssertionError("negative price")
    if open_count > int(s["rules"]["max_open"]):
        raise AssertionError("too many open auctions")
    if s["status"] != "setup":
        for seat in s["seats"]:
            bal = balance(s, seat["id"])
            if bal < 0:
                raise AssertionError(f"{seat['id']} overspent: balance {bal}")
            if committed(s, seat["id"]) > bal:
                raise AssertionError(f"{seat['id']} overcommitted")


# ---------------------------------------------------------------------------
# Projections — what each audience may see
# ---------------------------------------------------------------------------


def public_view(s: dict, now: float) -> dict:
    """Everything any room member may see.  NEVER includes a maximum bid."""
    win = _window(s)
    auctions = []
    for a in _auctions(s):
        remaining = (
            a["remaining"]
            if s["paused"] and a["status"] == "open"
            else (schedule.active_between(win, now, a["deadline"]) if a["status"] == "open" else 0)
        )
        auctions.append(
            {
                "id": a["id"],
                "player": a["player"],
                "nominator": a["nominator"],
                "round": a["round"],
                "status": a["status"],
                "price": a["price"],
                "leader": a["leader"] if a["status"] == "open" else None,
                "winner": a["winner"],
                "owner": lot_owner(a) if a["status"] == "closed" else None,
                "deadline": a["deadline"],
                "remaining_active_seconds": remaining,
                "opened_at": a["opened_at"],
                "closed_at": a["closed_at"],
                "extensions": a["extensions"],
            }
        )
    seats = []
    for seat in s["seats"]:
        bal = balance(s, seat["id"]) if seat["opening_budget"] is not None else None
        seats.append(
            {
                "id": seat["id"],
                "name": seat["name"],
                "team": seat["team"],
                "is_bot": seat["is_bot"],
                "opening_budget": seat["opening_budget"],
                "budget_source": seat["budget_source"],
                "balance": bal,
                "committed": committed(s, seat["id"]) if bal is not None else None,
                "spendable": (bal - committed(s, seat["id"])) if bal is not None else None,
                "won": sum(
                    1 for a in _auctions(s) if a["status"] == "closed" and a["winner"] == seat["id"]
                ),
                "rights_left": sum(
                    1 for r in s["rights"] if r["seat"] == seat["id"] and r["status"] == "pending"
                ),
            }
        )
    on_clock = [
        {
            "right": r["id"],
            "seat": r["seat"],
            "round": r["round"],
            "deadline": r["deadline"],
            "since": r["window_at"],
        }
        for r in _window_rights(s)
        if r["window_at"] is not None
    ]
    return {
        "room_id": s["room_id"],
        "name": s["name"],
        "room_type": s["room_type"],
        "status": s["status"],
        "drain_reason": s["drain_reason"],
        "paused": s["paused"],
        "active_now": schedule.is_active(win, now),
        "next_active_start": schedule.next_active_start(win, now),
        "window": win.to_dict(),
        "window_text": schedule.describe(win),
        "rules": _public_rules(s["rules"]),
        "unconfirmed_rules": unconfirmed_rules(s["rules"]),
        "seats": seats,
        "order": s["order"],
        "pool": {
            "version": s["pool"]["version"],
            "label": s["pool"]["label"],
            "is_official_class": s["pool"]["is_official_class"],
            "size": len(s["pool"]["players"]),
        },
        "auctions": auctions,
        "on_clock": on_clock,
        "open_count": len(open_auctions(s)),
        "rights": [
            {
                "id": r["id"],
                "round": r["round"],
                "seat": r["seat"],
                "status": r["status"],
                "auction": r["auction"],
            }
            for r in s["rights"]
        ],
        "total_opening_pool": total_opening_pool(s),
        "completed_trades": [
            {
                k: t[k]
                for k in (
                    "id",
                    "from",
                    "to",
                    "give_dollars",
                    "get_dollars",
                    "give_lots",
                    "get_lots",
                    "resolved_at",
                )
            }
            | {"external": bool(t["external_note"])}
            for t in (s.get("trades") or {}).values()
            if t["status"] == "completed"
        ],
        "started_at": s["started_at"],
        "completed_at": s["completed_at"],
        "now": now,
    }


def _public_rules(rules: dict) -> dict:
    keys = (
        "rule_version",
        "timing_preset",
        "seat_count",
        "rounds",
        "max_open",
        "auction_active_seconds",
        "extension_active_seconds",
        "nomination_timeout_active_seconds",
        "end_when_money_spent",
        "tie_rule",
        "withdraw_policy",
        "resume_min_active_seconds",
        "auto_nomination_queue",
    )
    return {k: rules.get(k) for k in keys}


def seat_private_view(s: dict, seat_id: str, now: float) -> dict:
    """ONE seat's private state: its own maxima, caps and queue.  Never a rival's."""
    _seat(s, seat_id)
    mine = []
    for a in open_auctions(s):
        b = a["bids"].get(seat_id)
        if not b:
            continue
        st = _my_status(s, seat_id, a)
        mine.append({"auction": a["id"], "max": int(b["max"]), "active": b["active"], **st})
    q = s["queues"].get(seat_id) or {"players": [], "auto": False}
    right = _current_right_for(s, seat_id)
    return {
        "seat": seat_id,
        "balance": balance(s, seat_id) if _seat(s, seat_id)["opening_budget"] is not None else None,
        "committed": committed(s, seat_id),
        "spendable": spendable(s, seat_id)
        if _seat(s, seat_id)["opening_budget"] is not None
        else None,
        "conditional_exposure": sum(
            max(0, min(m["max"], m["capacity"]) - (m["price"] if m["leading"] else 0))
            for m in mine
            if m["active"]
        ),
        "my_bids": mine,
        "queue": q,
        "trades": trades_for_seat(s, seat_id, now),
        "on_clock": None
        if right is None or right["window_at"] is None
        else {
            "right": right["id"],
            "round": right["round"],
            "deadline": right["deadline"],
        },
    }


# ---------------------------------------------------------------------------
# Bots — seeded, public-information-only, same command path
# ---------------------------------------------------------------------------


def _bot_rng(seat: dict, salt: str) -> random.Random:
    h = hashlib.sha256(f"{seat['bot_seed']}:{seat['id']}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def bot_commands(s: dict, now: float) -> list[dict]:
    """Commands each bot seat wants to issue right now.

    Bots see ONLY the public view plus their own seeded preferences.  They
    never read a rival's maximum or anyone's Perfect Draft strategy.
    """
    if s["status"] not in ("running", "draining") or s["paused"]:
        return []
    if not schedule.is_active(_window(s), now):
        return []
    pub = public_view(s, now)
    players = s["pool"]["players"]
    # A bot prices a lot as its share of the ROOM's money across the players
    # the room can realistically sell (rounds x seats), not the whole pool.
    sellable = int(s["rules"]["rounds"]) * len(s["seats"])
    top_values = sorted((float(p.get("value") or 0) for p in players.values()), reverse=True)[
        :sellable
    ]
    pool_total = max(1.0, sum(top_values))
    room_money = max(0, total_opening_pool(s))
    out: list[dict] = []
    bids: list[dict] = []
    taken = {a["player"] for a in pub["auctions"]}
    for seat in s["seats"]:
        if not seat["is_bot"]:
            continue
        sid = seat["id"]
        # Nominate: best remaining player by the bot's own noisy preference.
        clock = next((c for c in pub["on_clock"] if c["seat"] == sid), None)
        if pub["status"] == "running" and clock is not None:
            rng = _bot_rng(seat, f"nom:{len(taken)}")
            waited = schedule.active_between(_window(s), clock["since"], now)
            ready = waited >= rng.uniform(0.0, 0.1) * float(s["rules"]["auction_active_seconds"])
            avail = [pid for pid in players if pid not in taken]
            if ready and avail:
                avail.sort(
                    key=lambda pid: -(float(players[pid].get("value") or 0) * rng.uniform(0.7, 1.3))
                )
                out.append(
                    {"kind": "nominate", "actor": {"role": "bot", "seat": sid}, "player": avail[0]}
                )
                taken.add(avail[0])
        # Bid: one private maximum per auction, from own seeded valuation.
        bal = balance(s, sid)
        for a in pub["auctions"]:
            if a["status"] != "open" or a["leader"] == sid:
                continue
            existing = s["auctions"][a["id"]]["bids"].get(sid)
            if existing:
                continue
            rng = _bot_rng(seat, f"bid:{a['player']}")
            # Humanlike pacing: each bot looks at a lot after its own seeded
            # share of the auction's active clock has passed.
            waited = schedule.active_between(_window(s), a["opened_at"], now)
            if waited < rng.uniform(0.01, 0.25) * float(s["rules"]["auction_active_seconds"]):
                continue
            value = float(players[a["player"]].get("value") or 0)
            want = int(round(room_money * (value / pool_total) * rng.uniform(0.5, 1.4)))
            want = max(0, min(want, bal))
            if want > int(a["price"]) and rng.random() < 0.8:
                bids.append(
                    {
                        "kind": "bid",
                        "actor": {"role": "bot", "seat": sid},
                        "auction": a["id"],
                        "max": want,
                    }
                )
    # Nominations first: a backlog of bids must never cost a bot its turn.
    return out + bids
