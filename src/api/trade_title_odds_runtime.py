"""Request runtime for ``POST /api/trade/title-odds`` — admit, bound, share, cache.

DYN10 #4 activation lane (owner directive 2026-11-21; the activation packet in
``docs/audits/DYNASTY_TOP10_AUDIT_2026-11-21.md`` row 4 and
``docs/EXECUTION_PLAN.md``): Analyze Trade's season-odds lens costs about
5.5 s, so ``/api/trade/analyze`` no longer computes it and the War Room asks
this route afterwards.  Transport only — nothing here computes odds; the lens is
``src.trade.title_odds_lens`` and its computation is unchanged.

Four properties, each pinned by ``tests/api/test_trade_title_odds_runtime.py``:

* **Admitted.**  Each COMPUTATION takes a slot of the route's admission bound
  (``src.api.compute_admission``, route ``trade_title_odds``).  When every slot
  is busy a further distinct trade is answered at once with the busy envelope
  (``title_odds_busy``, retryable) and nothing is started.  The slot is taken
  by the leader only, inside the single flight, so a request that joins a
  running computation never takes one.
* **Bounded.**  The caller waits at most the route's admission deadline
  (``ComputeAdmission.within_deadline``).  Past it, the request answers
  ``state: "unavailable"`` / ``title_odds_timeout`` — never a zero delta.  The
  computation cannot be interrupted (it runs in a worker thread), so it keeps
  its slot until it really finishes (the bound is on real work, not on waiting
  callers), and its result is cached for the next identical request (the War
  Room's Retry) instead of a retry starting a second simulation.
* **Shared, per user.**  An identical request from the SAME user that arrives
  while the computation runs joins it rather than starting another.
* **Cached, briefly, per user.**  A SUCCESSFUL payload (``state: "ok"``) is kept
  for :data:`CACHE_TTL_SECONDS` under :func:`cache_key` — (user, league, board
  generation, ``title_odds_lens.trade_signature``).  A refusal, an error, a busy
  answer or a timeout is never cached, and a request without a provable key (no
  user identity — e.g. a guest session whose id is unknown — or no board
  generation stamp) is computed every time and shared with nobody.  The board
  generation moves with every published board; the league snapshot (schedule,
  standings) and the team-strength rows the lens also reads are bounded by the
  TTL instead, because reading them to build the key would put their cost back
  outside the deadline.

  The user is in the key on purpose.  The payload itself is league-level, but
  sharing it across users is not harmless: the response's ``computation``
  (``source`` and ``ms``) — and the ~5.5 s timing gap alone — would tell one
  user that another had just asked about the same trade.  So the user is
  ``trade_analyze_runtime.session_owner`` (the identity Analyze Trade's own
  in-flight key uses: a guest pass is keyed per session, never pooled), and an
  unknown owner is never shared, exactly as ``trade_analyze_runtime.dedup_key``
  refuses one.
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

from src.api import compute_admission

LOG = logging.getLogger(__name__)

#: How long a successful payload is reused.
CACHE_TTL_SECONDS = 300.0
#: How many successful payloads are kept (least recently used evicted first).
CACHE_MAX_ENTRIES = 64

SOURCE_COMPUTED = "computed"
SOURCE_CACHE = "cache"
SOURCE_JOINED = "joined"
SOURCE_TIMEOUT = "timeout"
SOURCE_BUSY = "busy"


def cache_key(
    *,
    owner: str | None,
    league_key: str | None,
    board_generation: str | None,
    trade_signature: str | None,
) -> tuple[str, ...] | None:
    """The cache and in-flight identity of one user's lens question, or
    ``None`` when it cannot be proven: no user identity (never pooled with
    anyone) or an unstamped board (never assumed to be the same board)."""
    if not owner or not league_key or not board_generation or not trade_signature:
        return None
    return (
        "trade_title_odds",
        str(owner),
        str(league_key),
        str(board_generation),
        str(trade_signature),
    )


def _cacheable(payload: Any) -> bool:
    return isinstance(payload, Mapping) and payload.get("state") == "ok"


class TitleOddsRuntime:
    """One admitted, bounded, shared, briefly cached lens computation per key."""

    def __init__(
        self,
        *,
        admission: compute_admission.ComputeAdmission | None = None,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # ``None``: the process-wide instance, resolved per call so a config
        # change (or ``compute_admission.reset_for_tests``) applies at once.
        self._admission = admission
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[Hashable, tuple[float, dict[str, Any]]] = OrderedDict()
        # Keyed by (event loop, key): a task belongs to the loop that made it.
        self._inflight: dict[tuple[int, Hashable], asyncio.Future] = {}

    @property
    def admission(self) -> compute_admission.ComputeAdmission:
        if self._admission is not None:
            return self._admission
        return compute_admission.admission_for(compute_admission.ROUTE_TRADE_TITLE_ODDS)

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
        busy_payload: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        """``(payload, source)`` — ``source`` is one of ``computed`` /
        ``cache`` / ``joined`` / ``timeout`` / ``busy``.

        ``compute`` is synchronous and runs in the threadpool, in an admission
        slot.  ``timeout_payload`` / ``error_payload`` / ``busy_payload`` build
        the unavailable envelopes (the lens owns their wording); a raised
        exception is ``error_payload``.  None of the three is ever cached."""
        hit = self.cached(key)
        if hit is not None:
            return hit, SOURCE_CACHE

        from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

        admission = self.admission
        loop = asyncio.get_running_loop()
        slot = (id(loop), key) if key is not None else None
        task = self._inflight.get(slot) if slot is not None else None
        if task is not None and task.done():
            # Finished, but its done-callback (which caches it and clears the
            # slot) has not run yet: a success is as good as a cache hit.
            settled = self._settled_success(task)
            if settled is not None:
                return settled, SOURCE_CACHE
            task = None
        joined = task is not None
        if task is None:
            # The leader: the ONLY place a slot is taken.  A full route raises
            # ``AdmissionRejected("busy")`` from the task without starting the
            # computation; a joiner that caught that instant inherits it, which
            # is right — the slots were full for it too.
            task = asyncio.ensure_future(admission.admit(lambda: run_in_threadpool(compute)))
            if slot is not None:
                self._inflight[slot] = task
            task.add_done_callback(lambda t: self._finish(slot, key, t))
        shared = task
        source = SOURCE_JOINED if joined else SOURCE_COMPUTED
        try:
            # Shielded by ``within_deadline``: the deadline (or a caller that
            # goes away) cancels the wait, never the computation or its slot.
            payload = await admission.within_deadline(lambda: shared)
        except compute_admission.AdmissionRejected as exc:
            if exc.reason == "busy":
                return busy_payload(), SOURCE_BUSY
            return timeout_payload(), SOURCE_TIMEOUT
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — context only; reported, never cached
            return error_payload(), source
        return copy.deepcopy(payload), source

    @staticmethod
    def _settled_success(task: asyncio.Future) -> dict[str, Any] | None:
        if task.cancelled() or task.exception() is not None:
            return None
        payload = task.result()
        return copy.deepcopy(payload) if _cacheable(payload) else None

    def _finish(self, slot: tuple[int, Hashable] | None, key: Hashable | None, task) -> None:
        if slot is not None and self._inflight.get(slot) is task:
            del self._inflight[slot]
        if task.cancelled():
            return
        exc = task.exception()
        if isinstance(exc, compute_admission.AdmissionRejected):
            return  # a full route is load, not a failure
        if exc is not None:
            LOG.warning("trade title odds computation failed: %s", type(exc).__name__)
            return
        payload = task.result()
        if key is not None and _cacheable(payload):
            self._store(key, payload)
