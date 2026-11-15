from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.auction import engine
from src.auction.rules import default_rules

NY = ZoneInfo("America/New_York")


def et(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=NY).timestamp()


NOON = et(2026, 10, 5, 12)


def make_pool(n: int = 40) -> dict:
    return {
        "version": "test-pool-v1",
        "label": "synthetic test fixture",
        "is_official_class": False,
        "players": {
            f"P{i}": {"name": f"Rookie {i}", "pos": "WR", "value": 1000 - i * 10}
            for i in range(1, n + 1)
        },
    }


def make_room(budgets=None, *, preset="official", seats=12, rules_patch=None, room_type="mock"):
    budgets = budgets if budgets is not None else [100] * seats
    rules = default_rules(preset)
    rules["seat_count"] = seats
    if rules_patch:
        rules.update(rules_patch)
    seat_list = [
        {"id": f"S{i + 1}", "name": f"Team {i + 1}", "opening_budget": b}
        for i, b in enumerate(budgets)
    ]
    return engine.new_room_state(
        room_id="R1",
        name="test",
        room_type=room_type,
        rules=rules,
        seats=seat_list,
        order=None,
        pool=make_pool(),
        created_at=NOON - 60,
    )


def cmd(state, kind, now, seat=None, role=None, **kw):
    role = role or ("manager" if seat else "commissioner")
    c = {"kind": kind, "actor": {"role": role, "seat": seat}, **kw}
    return engine.apply_command(state, c, now)


def started(budgets=None, **kw):
    s = make_room(budgets, **kw)
    s, _, _ = cmd(s, "start", NOON)
    return s


def nominate(s, seat, player, now=NOON):
    s, r, _ = cmd(s, "nominate", now, seat=seat, player=player)
    return s, r["auction"]


def bid(s, seat, aid, mx, now=NOON):
    s, r, ev = cmd(s, "bid", now, seat=seat, auction=aid, max=mx)
    return s, r
