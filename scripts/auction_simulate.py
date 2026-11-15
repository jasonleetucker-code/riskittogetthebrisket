"""Simulate full rookie auctions to estimate how long a real one takes.

The owner wants "roughly one month", explicitly not promised.  This plays
complete rooms through the REAL engine (``src/auction/engine.py``) with
seeded bots in every seat and a virtual clock, under a timing preset, and
reports the calendar duration, how the room ended, and how many players sold.

It is a model, and says so: bots nominate and bid on their own seeded
schedule, while real managers are slower (turn timeouts) or faster.  Use it
to see the SHAPE — what drives duration — not as a completion date.

    python scripts/auction_simulate.py --rooms 20 --preset official
    python scripts/auction_simulate.py --rooms 5 --preset official --nominate-delay-hours 6

Exit 0 always (it measures; it gates nothing).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auction import engine, schedule  # noqa: E402
from src.auction.engine import AuctionError  # noqa: E402
from src.auction.rules import default_rules  # noqa: E402
from src.auction.sources import synthetic_pool  # noqa: E402

NY = ZoneInfo("America/New_York")


def _start_time() -> float:
    # A Monday 08:00 ET, so every run starts at the same point in the week.
    return datetime(2027, 4, 5, 8, 0, tzinfo=NY).timestamp()


def simulate(
    seed: int, preset: str, budgets: list[int], step_minutes: int, nominate_delay_hours: float
) -> dict:
    rules = default_rules(preset)
    rng = random.Random(seed)
    seats = [
        {
            "id": f"S{i + 1}",
            "name": f"Team {i + 1}",
            "opening_budget": budgets[i],
            "is_bot": True,
            "bot_seed": seed * 100 + i,
        }
        for i in range(12)
    ]
    order = [s["id"] for s in seats]
    rng.shuffle(order)
    t0 = _start_time()
    s = engine.new_room_state(
        room_id=f"sim{seed}",
        name="sim",
        room_type="mock",
        rules=rules,
        seats=seats,
        order=order,
        pool=synthetic_pool(96),
        created_at=t0,
    )
    s, _, _ = engine.apply_command(s, {"kind": "start", "actor": {"role": "commissioner"}}, t0)
    now = t0
    step = step_minutes * 60
    win = engine._window(s)
    last_nom: dict[str, float] = {}
    guard = 0
    while s["status"] != "complete" and guard < 200_000:
        guard += 1
        now = schedule.next_active_start(win, now + step)
        s, _, _ = engine.apply_command(s, {"kind": "advance", "actor": {"role": "system"}}, now)
        for cmd in engine.bot_commands(s, now):
            if cmd["kind"] == "nominate" and nominate_delay_hours:
                # Model human latency on the nomination clock.
                started = next(
                    (
                        c["since"]
                        for c in engine.public_view(s, now)["on_clock"]
                        if c["seat"] == cmd["actor"]["seat"]
                    ),
                    now,
                )
                if schedule.active_between(
                    win, started, now
                ) < nominate_delay_hours * 3600 * rng.uniform(0.2, 1.0):
                    continue
                last_nom[cmd["actor"]["seat"]] = now
            try:
                s, _, _ = engine.apply_command(s, cmd, now)
            except AuctionError:
                continue
    sold = [a for a in s["auctions"].values() if a["status"] == "closed"]
    return {
        "seed": seed,
        "days": round((s["completed_at"] - t0) / 86400, 1) if s["completed_at"] else None,
        "reason": s["drain_reason"],
        "sold": len(sold),
        "zero_dollar_sales": sum(1 for a in sold if a["price"] == 0),
        "passed_turns": sum(1 for r in s["rights"] if r["status"] == "passed"),
        "spent": sum(a["price"] for a in sold),
        "unspent": sum(engine.balance(s, x["id"]) for x in s["seats"]),
        "extensions": sum(a["extensions"] for a in sold),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rooms", type=int, default=10)
    ap.add_argument("--preset", default="official", choices=["official", "rehearsal", "fast"])
    ap.add_argument("--step-minutes", type=int, default=15)
    ap.add_argument(
        "--nominate-delay-hours",
        type=float,
        default=0.0,
        help="model human latency on the nomination clock",
    )
    ap.add_argument(
        "--budget",
        type=int,
        default=100,
        help="equal opening budget per seat (league pool is ~$1,200)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    budgets = [args.budget] * 12
    runs = [
        simulate(seed, args.preset, budgets, args.step_minutes, args.nominate_delay_hours)
        for seed in range(args.rooms)
    ]
    days = [r["days"] for r in runs if r["days"] is not None]
    summary = {
        "preset": args.preset,
        "rooms": args.rooms,
        "nominate_delay_hours": args.nominate_delay_hours,
        "days_median": statistics.median(days) if days else None,
        "days_min": min(days) if days else None,
        "days_max": max(days) if days else None,
        "end_reasons": {
            k: sum(1 for r in runs if r["reason"] == k) for k in {r["reason"] for r in runs}
        },
        "sold_median": statistics.median(r["sold"] for r in runs),
        "passed_turns_median": statistics.median(r["passed_turns"] for r in runs),
        "caveat": "Seeded bots, not people. Real duration depends on how fast managers nominate and how often the money runs out.",
    }
    if args.json:
        print(json.dumps({"summary": summary, "runs": runs}, indent=2))
    else:
        for r in runs:
            print(r)
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
