"""Request runtime for ``POST /api/trade/analyze`` — timing, progress, dedup.

Transport-level support only.  Nothing here computes, caches or changes an
analysis: the route still runs the one simulation (``trade_simulator``) and the
one decision owner (``src.trade.analyze_trade``).  Three things live here
because they are about the REQUEST, not the trade:

* :class:`StageClock` — wall time per server stage of THIS request, published
  as ``analysisTiming`` and as a standard ``Server-Timing`` header.  Measured,
  never estimated.
* :data:`PROGRESS` — the phase an in-flight analysis is in, readable by the
  same signed-in user through ``GET /api/trade/analyze/status`` when the
  client tags its request with ``X-Analysis-Request-Id``.  It reports the
  phase the server is actually executing; it never forecasts a remaining
  time.  Entries are scoped to the session owner, so one user can never read
  another's (the request id alone is not a capability).
* :class:`AsyncSingleFlight` + :func:`dedup_key` — two IDENTICAL analyze
  requests from the same user, against the same loaded board, while the first
  is still running (a retry after a client timeout, an edit undone before the
  answer arrived) share one computation instead of running it twice.  Nothing
  is retained after it finishes, so this is not a response cache, and the key
  carries the user, so two users never share one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

T = TypeVar("T")

TIMING_VERSION = 1

#: The phases a progress entry moves through, in order.  ``resolve`` covers
#: auth, league / team resolution and any cross-league overlay splice;
#: ``posture`` the league's competitive-posture bundle (a cold build is the
#: slow case); ``simulation`` the trade simulation including the best-ball
#: roster utility; ``comparables`` comparable real trades; ``decision`` the
#: decision synthesis; ``receipt`` the decision-log line.
PHASES: tuple[str, ...] = (
    "received",
    "resolve",
    "posture",
    "simulation",
    "exposure",
    "comparables",
    "decision",
    "receipt",
    "complete",
)
#: Terminal states besides ``complete``.
FAILED = "failed"
#: A request that joined an identical in-flight request reports this phase
#: until that computation finishes.
JOINED = "joined_identical_request"

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def request_id_from(raw: str | None) -> str | None:
    """A client-supplied analysis request id, or ``None`` when absent/invalid."""
    value = (raw or "").strip()
    return value if _REQUEST_ID.match(value) else None


def session_owner(session: Mapping[str, Any] | None, session_id: str | None = None) -> str | None:
    """The identity a progress entry / dedup key is scoped to.

    Guest-pass sessions all carry the username ``"guest"``, so they are keyed
    by their pass AND their own session (hashed — the raw session id is a
    credential), never pooled: two holders of one pass are two people.  A
    guest session whose id is unknown gets ``None`` (no progress entry, no
    sharing) rather than a shared bucket.
    """
    if not isinstance(session, Mapping):
        return None
    if str(session.get("auth_method") or "") == "guest_pass":
        sid = str(session_id or "").strip()
        if not sid:
            return None
        digest = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:24]
        return f"guest_pass:{session.get('guest_pass_id')}:{digest}"
    for key in ("username", "sleeper_user_id"):
        value = str(session.get(key) or "").strip().lower()
        if value:
            return value
    return None


class ProgressRegistry:
    """Bounded, TTL'd, owner-scoped phase registry (process-local)."""

    def __init__(
        self, *, ttl_seconds: float = 300.0, max_entries: int = 512, max_per_owner: int = 16
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._max_per_owner = max_per_owner
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._entries:
            key, entry = next(iter(self._entries.items()))
            if now - entry["updatedAt"] <= self._ttl and len(self._entries) <= self._max:
                break
            self._entries.pop(key, None)

    def begin(self, owner: str, request_id: str) -> "ProgressHandle":
        now = time.monotonic()
        with self._lock:
            # One user cannot churn everyone else's entries out: past the
            # per-owner cap, that owner's own oldest entry goes first.
            mine = [k for k in self._entries if k[0] == owner and k != (owner, request_id)]
            for key in mine[: max(0, len(mine) - self._max_per_owner + 1)]:
                self._entries.pop(key, None)
            self._entries[(owner, request_id)] = {
                "phase": "received",
                "state": "running",
                "startedAt": now,
                "updatedAt": now,
                "stages": [],
            }
            self._entries.move_to_end((owner, request_id))
            self._prune(now)
        return ProgressHandle(self, owner, request_id)

    def _update(self, owner: str, request_id: str, **fields: Any) -> None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get((owner, request_id))
            if entry is None:
                return
            stage = fields.pop("completed_stage", None)
            if stage is not None:
                entry["stages"].append(stage)
            entry.update(fields)
            entry["updatedAt"] = now
            self._entries.move_to_end((owner, request_id))

    def snapshot(self, owner: str | None, request_id: str | None) -> dict[str, Any] | None:
        if not owner or not request_id:
            return None
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            entry = self._entries.get((owner, request_id))
            if entry is None:
                return None
            phase = entry["phase"]
            return {
                "requestId": request_id,
                "state": entry["state"],
                "phase": phase,
                "phaseIndex": PHASES.index(phase) if phase in PHASES else None,
                "phases": list(PHASES),
                "elapsedMs": round((now - entry["startedAt"]) * 1000.0, 1),
                "completedStages": [dict(s) for s in entry["stages"]],
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ProgressHandle:
    def __init__(self, registry: ProgressRegistry, owner: str, request_id: str) -> None:
        self._registry = registry
        self._owner = owner
        self._request_id = request_id

    def phase(self, name: str) -> None:
        self._registry._update(self._owner, self._request_id, phase=name)

    def stage_done(self, name: str, ms: float) -> None:
        self._registry._update(
            self._owner, self._request_id, completed_stage={"stage": name, "ms": ms}
        )

    def finish(self, state: str) -> None:
        phase = "complete" if state == "complete" else FAILED
        self._registry._update(self._owner, self._request_id, phase=phase, state=state)


PROGRESS = ProgressRegistry()


class StageClock:
    """Wall time per server stage of one request."""

    def __init__(self, progress: ProgressHandle | None = None) -> None:
        self._t0 = time.perf_counter()
        self._stages: list[tuple[str, float]] = []
        self.progress = progress

    @contextmanager
    def stage(self, name: str):
        if self.progress is not None:
            self.progress.phase(name)
        t0 = time.perf_counter()
        try:
            yield
        finally:
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            self._stages.append((name, ms))
            if self.progress is not None:
                self.progress.stage_done(name, ms)

    def stages(self) -> list[tuple[str, float]]:
        return list(self._stages)

    def to_dict(self, *, shared_with: "StageClock | None" = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": TIMING_VERSION,
            "unit": "ms",
            "totalMs": round((time.perf_counter() - self._t0) * 1000.0, 1),
            "stages": [{"stage": n, "ms": ms} for n, ms in self._stages],
            "sharedComputation": shared_with is not None,
            "note": (
                "server wall time for this request, by stage; excludes network "
                "transfer and browser rendering"
            ),
        }
        if shared_with is not None:
            out["sharedStages"] = [{"stage": n, "ms": ms} for n, ms in shared_with.stages()]
        return out

    def server_timing(self) -> str:
        parts = [f"{n};dur={ms}" for n, ms in self._stages]
        parts.append(f"total;dur={round((time.perf_counter() - self._t0) * 1000.0, 1)}")
        return ", ".join(parts)


def dedup_key(
    owner: str | None,
    session: Mapping[str, Any] | None,
    body: Any,
    contract: Mapping[str, Any] | None,
    *,
    league_key: str | None,
    query_items: Sequence[tuple[str, str]] = (),
) -> tuple[Hashable, ...] | None:
    """Identity of an analyze request for in-flight sharing, or ``None``.

    Everything that can decide the answer for this user: the owner and the
    session's Sleeper id (the default team), the RESOLVED league (which can
    come from the query string, the body, or the user's saved active league —
    so it is resolved before this key is taken, and the computation is handed
    that same league), the whole query string (``leagueKey``,
    ``valuationMode`` …) and body in canonical form, and the identity of the
    loaded board.  An unauthenticated, malformed or unresolvable request is
    never shared; it takes the normal path and gets its normal error.
    """
    if owner is None or not league_key or not isinstance(body, dict):
        return None
    try:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None
    meta = (contract or {}).get("meta") if isinstance(contract, Mapping) else None
    return (
        "trade_analyze",
        owner,
        str((session or {}).get("sleeper_user_id") or ""),
        str(league_key),
        tuple(sorted((str(k), str(v)) for k, v in query_items)),
        canonical,
        id(contract),
        str((meta or {}).get("generatedAt") or "") if isinstance(meta, Mapping) else "",
    )


class AsyncSingleFlight:
    """One in-flight coroutine per key on one event loop; nothing retained.

    The shared computation runs as its own task, so a caller that is cancelled
    (client gone) does not cancel it for the others.  An exception reaches
    every caller.
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[int, Hashable], asyncio.Task] = {}

    def in_flight(self) -> int:
        return sum(1 for t in self._pending.values() if not t.done())

    async def run(
        self,
        key: Hashable,
        factory: Callable[[], Awaitable[T]],
        *,
        on_join: Callable[[], None] | None = None,
    ) -> tuple[T, bool]:
        """``(result, joined)``.  ``on_join`` runs the moment a caller joins an
        in-flight computation (before waiting on it)."""
        loop = asyncio.get_running_loop()
        slot = (id(loop), key)
        task = self._pending.get(slot)
        if task is not None and not task.done():
            if on_join is not None:
                on_join()
            return await asyncio.shield(task), True
        task = asyncio.ensure_future(factory())
        self._pending[slot] = task

        def _done(t: asyncio.Task, slot: tuple[int, Hashable] = slot) -> None:
            if self._pending.get(slot) is t:
                del self._pending[slot]
            if not t.cancelled():
                t.exception()  # retrieved: never "exception was never retrieved"

        task.add_done_callback(_done)
        return await asyncio.shield(task), False
