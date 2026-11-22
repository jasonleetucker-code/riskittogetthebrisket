"""Request runtime for ``POST /api/trade/title-odds`` — bound, share, cache.

DYN10 #4 activation lane (owner directive 2026-11-21; the activation packet in
``docs/audits/DYNASTY_TOP10_AUDIT_2026-11-21.md`` row 4 and
``docs/EXECUTION_PLAN.md``): Analyze Trade's season-odds lens costs about
5.5 s, so ``/api/trade/analyze`` no longer computes it and the War Room asks
this route afterwards.  Transport only — nothing here computes odds; the lens is
``src.trade.title_odds_lens`` and its computation is unchanged.

Three properties, each pinned by ``tests/api/test_trade_title_odds_runtime.py``:

* **Bounded.**  The computation runs in the threadpool as its own task and the
  request waits at most :data:`TIMEOUT_SECONDS` for it.  Past that, the request
  answers ``state: "unavailable"`` / ``title_odds_timeout`` — never a zero
  delta.  The task is not abandoned: a threadpool computation cannot be
  interrupted, so it finishes in the background and its result is cached for
  the next identical request (the War Room's Retry), instead of a retry
  starting a second simulation beside the first.
* **Shared.**  An identical request that arrives while the computation runs
  joins it rather than starting another.
* **Cached, briefly.**  A SUCCESSFUL payload (``state: "ok"``) is kept for
  :data:`CACHE_TTL_SECONDS` under :func:`cache_key` — (league, board
  generation, ``title_odds_lens.trade_signature``).  A refusal, an error or a
  timeout is never cached, and a request without a provable key (no board
  generation stamp) is computed every time.  The board generation moves with
  every published board; the league snapshot (schedule, standings) and the
  team-strength rows the lens also reads are bounded by the TTL instead,
  because reading them to build the key would put their cost back outside the
  timeout.  The payload is league-level (every team's row for that trade), so
  the key carries no user: two users asking the same question for the same
  team get the same answer either way.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping
from typing import Any

LOG = logging.getLogger(__name__)

#: How long a request waits for the computation.  The lens measured a median
#: 5.5 s on a 12-team best-ball fixture; a cold league snapshot or team-strength
#: build can add more.  Below nginx's 120 s ``/api/`` read timeout and the War
#: Room's own 60 s request ceiling.
TIMEOUT_SECONDS = 40.0
#: How long a successful payload is reused.
CACHE_TTL_SECONDS = 300.0
#: How many successful payloads are kept (least recently used evicted first).
CACHE_MAX_ENTRIES = 64

SOURCE_COMPUTED = "computed"
SOURCE_CACHE = "cache"
SOURCE_JOINED = "joined"
SOURCE_TIMEOUT = "timeout"


def cache_key(
    *,
    league_key: str | None,
    board_generation: str | None,
    trade_signature: str | None,
) -> tuple[str, ...] | None:
    """The cache identity of one lens question, or ``None`` when it cannot be
    proven (an unstamped board is never assumed to be the same board)."""
    if not league_key or not board_generation or not trade_signature:
        return None
    return ("trade_title_odds", str(league_key), str(board_generation), str(trade_signature))


def _cacheable(payload: Any) -> bool:
    return isinstance(payload, Mapping) and payload.get("state") == "ok"


class TitleOddsRuntime:
    """One bounded, shared, briefly cached lens computation per key."""

    def __init__(
        self,
        *,
        timeout_seconds: float = TIMEOUT_SECONDS,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[Hashable, tuple[float, dict[str, Any]]] = OrderedDict()
        # Keyed by (event loop, key): a task belongs to the loop that made it.
        self._inflight: dict[tuple[int, Hashable], asyncio.Future] = {}

    # ── cache ────────────────────────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def cached(self, key: Hashable | None) -> dict[str, Any] | None:
        """A deep copy of the live cached payload for ``key``, or ``None``."""
        if key is None:
            return None
        with self._lock:
            hit = self._cache.get(key)
            if hit is None:
                return None
            stored_at, payload = hit
            if self._clock() - stored_at >= self.ttl_seconds:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return copy.deepcopy(payload)

    def _store(self, key: Hashable, payload: dict[str, Any]) -> None:
        with self._lock:
            self._cache[key] = (self._clock(), copy.deepcopy(payload))
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    # ── computation ──────────────────────────────────────────────────────

    async def run(
        self,
        key: Hashable | None,
        compute: Callable[[], dict[str, Any]],
        *,
        timeout_payload: Callable[[], dict[str, Any]],
        error_payload: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        """``(payload, source)`` — ``source`` is one of ``computed`` /
        ``cache`` / ``joined`` / ``timeout``.

        ``compute`` is synchronous and runs in the threadpool.
        ``timeout_payload`` / ``error_payload`` build the unavailable envelopes
        (the lens owns their wording); a raised exception is ``error_payload``
        and is never cached."""
        hit = self.cached(key)
        if hit is not None:
            return hit, SOURCE_CACHE

        from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

        loop = asyncio.get_running_loop()
        slot = (id(loop), key) if key is not None else None
        task = self._inflight.get(slot) if slot is not None else None
        joined = task is not None and not task.done()
        if not joined:
            task = asyncio.ensure_future(run_in_threadpool(compute))
            if slot is not None:
                self._inflight[slot] = task
            task.add_done_callback(lambda t: self._finish(slot, key, t))
        try:
            # ``shield``: the timeout cancels the wait, never the computation.
            payload = await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            return timeout_payload(), SOURCE_TIMEOUT
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — context only; reported, never cached
            return error_payload(), (SOURCE_JOINED if joined else SOURCE_COMPUTED)
        return copy.deepcopy(payload), (SOURCE_JOINED if joined else SOURCE_COMPUTED)

    def _finish(self, slot: tuple[int, Hashable] | None, key: Hashable | None, task) -> None:
        if slot is not None and self._inflight.get(slot) is task:
            del self._inflight[slot]
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LOG.warning("trade title odds computation failed: %s", type(exc).__name__)
            return
        payload = task.result()
        if key is not None and _cacheable(payload):
            self._store(key, payload)
