"""Background runtime for the auction room: closes, bots, heartbeat, outages.

Correctness never depends on this loop.  Every command applies all
time-driven transitions due at its own server time FIRST (``engine.apply_command``),
so a late or dead worker can delay a *visible* close but can never let a bid
land after a deadline.  The loop exists so rooms advance and bots act when
nobody is clicking.

* every ~1 s: rooms whose next scheduled transition is due get an ``advance``;
* every ~2 s: mock rooms with bot seats let each bot act through the same
  command path humans use;
* every ~15 s: a heartbeat on every running room.

Startup outage check: a running room whose heartbeat is older than its
``outage_threshold_seconds`` (the service was unreachable) is PAUSED as of
that last heartbeat — never advanced through the gap.  Players whose
wall-clock deadlines passed while nobody could reach the room are not
awarded; the commissioner resumes with an announced fair window.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from starlette.concurrency import run_in_threadpool

from src.auction import engine
from src.auction.engine import AuctionError
from src.auction.store import StoreUnavailable, get_store

log = logging.getLogger("auction.runtime")

TICK_SECONDS = 1.0
BOT_EVERY_TICKS = 2
HEARTBEAT_EVERY_TICKS = 15
MAX_BOT_COMMANDS_PER_ROOM = 6


def outage_check(now_real: float) -> list[str]:
    store = get_store()
    paused = []
    for row in store.active_rooms():
        state, _, _ = store.load(row["id"])
        if state.get("paused"):
            continue
        threshold = float(state["rules"].get("outage_threshold_seconds") or 300)
        hb = row["last_heartbeat"]
        if hb is None or now_real - float(hb) <= threshold:
            continue
        try:
            store.execute(
                row["id"],
                {
                    "kind": "pause",
                    "actor": {
                        "role": "commissioner",
                        "user": None,
                        "seat": None,
                        "system": "outage",
                    },
                    "pause_kind": "outage",
                    "reason": f"Service was unreachable for {int((now_real - float(hb)) // 60)} minutes; clocks frozen at the last confirmed moment.",
                },
                user_id=None,
                now_real=now_real,
                at_real=float(hb),
            )
            paused.append(row["id"])
            log.warning(
                "auction: outage pause applied to %s (heartbeat gap %.0fs)",
                row["id"],
                now_real - float(hb),
            )
        except AuctionError as exc:
            log.error("auction: outage pause failed for %s: %s", row["id"], exc.message)
    return paused


def _advance_due(now_real: float) -> None:
    store = get_store()
    for room_id in store.due_rooms(now_real):
        try:
            store.execute(
                room_id,
                {"kind": "advance", "actor": {"role": "system"}},
                user_id=None,
                now_real=now_real,
            )
        except AuctionError as exc:
            log.error("auction: advance failed for %s: %s", room_id, exc.message)


def _run_bots(now_real: float) -> None:
    store = get_store()
    for row in store.active_rooms():
        if row["room_type"] != "mock" or not row["has_bots"]:
            continue
        full = store.room_row(row["id"])
        state = json.loads(full["state_json"])
        room_now = store.room_now(full, now_real)
        for cmd in engine.bot_commands(state, room_now)[:MAX_BOT_COMMANDS_PER_ROOM]:
            try:
                store.execute(row["id"], cmd, user_id=None, now_real=now_real)
            except AuctionError:
                continue


def _heartbeat(now_real: float) -> None:
    store = get_store()
    store.heartbeat([r["id"] for r in store.active_rooms()], now_real)


async def _loop() -> None:
    try:
        await run_in_threadpool(get_store)
        await run_in_threadpool(outage_check, time.time())
    except StoreUnavailable as exc:
        log.error("auction runtime not started: %s", exc)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("auction runtime startup failed: %s", exc)
    tick = 0
    while True:
        tick += 1
        try:
            now = time.time()
            await run_in_threadpool(_advance_due, now)
            if tick % BOT_EVERY_TICKS == 0:
                await run_in_threadpool(_run_bots, now)
            if tick % HEARTBEAT_EVERY_TICKS == 0:
                await run_in_threadpool(_heartbeat, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must survive
            log.exception("auction runtime tick failed: %s", exc)
        await asyncio.sleep(TICK_SECONDS)


def start() -> asyncio.Task | None:
    try:
        from src.api import feature_flags

        if not feature_flags.is_enabled("rookie_auction"):
            return None
    except Exception:  # noqa: BLE001
        return None
    return asyncio.create_task(_loop(), name="auction-runtime")
