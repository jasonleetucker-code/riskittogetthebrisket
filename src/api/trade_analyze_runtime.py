"""Request runtime for ``POST /api/trade/analyze`` — timing, progress, dedup.

Transport-level support only.  Nothing here computes, caches or changes an
analysis: the route still runs the one simulation (``trade_simulator``) and the
one decision owner (``src.trade.analyze_trade``).  Three things live here
because they are about the REQUEST, not the trade:

* :class:`StageClock` — wall time per server stage of THIS request, published
  as ``analysisTiming`` and as a standard ``Server-Timing`` header.  Measured,
  never estimated.  Guest-pass sessions get the total only: a per-stage time
  can reveal whether a shared cache was warm.
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
  carries the user, so two users never share one.  Only a SUCCESS (or a
  refusal that is a fact about the request: 400 / 404) is shared.  When the
  leader raised or got a 5xx, its joiners make ONE retry between them (itself
  shared) and all get its outcome — at most two computations, never a storm.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

T = TypeVar("T")

LOG = logging.getLogger(__name__)

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
CANCELLED = "cancelled"
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


def owner_group(owner: str) -> str:
    """The bucket a progress cap is counted in: one guest PASS (every session
    it minted), else the owner itself — so one pass cannot mint sessions to
    churn other users' entries out."""
    if owner.startswith("guest_pass:"):
        return owner.rsplit(":", 1)[0]
    return owner


def is_guest(session: Mapping[str, Any] | None) -> bool:
    return isinstance(session, Mapping) and str(session.get("auth_method") or "") == "guest_pass"


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
        self._seq = 0

    def _prune(self, now: float) -> None:
        while self._entries:
            key, entry = next(iter(self._entries.items()))
            if now - entry["updatedAt"] <= self._ttl and len(self._entries) <= self._max:
                break
            self._entries.pop(key, None)

    def begin(self, owner: str, request_id: str, *, detail: bool = True) -> "ProgressHandle":
        now = time.monotonic()
        group = owner_group(owner)
        with self._lock:
            # One user (or one guest pass, whatever sessions it mints) cannot
            # churn everyone else's entries out: past the cap, that group's
            # own oldest entry goes first.
            mine = [
                k
                for k, e in self._entries.items()
                if e["group"] == group and k != (owner, request_id)
            ]
            for key in mine[: max(0, len(mine) - self._max_per_owner + 1)]:
                self._entries.pop(key, None)
            self._seq += 1
            token = self._seq
            self._entries[(owner, request_id)] = {
                "token": token,
                "phase": "received",
                "state": "running",
                "startedAt": now,
                "updatedAt": now,
                "stages": [],
                "group": group,
                "detail": detail,
            }
            self._entries.move_to_end((owner, request_id))
            self._prune(now)
        return ProgressHandle(self, owner, request_id, token)

    def _update(self, owner: str, request_id: str, token: int, **fields: Any) -> None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get((owner, request_id))
            # A finished entry is final: a cancelled request's computation may
            # still be running (it is shielded for its joiners) and must not
            # move a status the client was already told is terminal.  An entry
            # REPLACED by a reused request id belongs to the new request: the
            # old handle's token no longer matches, so it moves nothing.
            if entry is None or entry["token"] != token or entry["state"] != "running":
                return
            if fields.get("state") not in (None, "running"):
                entry["finishedAt"] = now
            stage = fields.pop("completed_stage", None)
            if stage is not None:
                # A stage timed in two parts (``resolve``) reports its total.
                for existing in entry["stages"]:
                    if existing["stage"] == stage["stage"]:
                        existing["ms"] = stage["ms"]
                        break
                else:
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
            if not entry["detail"]:
                # Guests: the state and current phase name only — what a
                # progress indicator needs.  No elapsed time and no stage list,
                # which would hand over the per-stage times outright.  This is
                # not a full defence: a guest polling the phase name can still
                # time stage boundaries to within its own poll interval — the
                # residual, low-sensitivity side channel the PR documents
                # (with total latency, which the per-team shared cache makes
                # observable by design).
                return {"requestId": request_id, "state": entry["state"], "phase": phase}
            end = entry.get("finishedAt") or now
            return {
                "requestId": request_id,
                "state": entry["state"],
                "phase": phase,
                "phaseIndex": PHASES.index(phase) if phase in PHASES else None,
                "phases": list(PHASES),
                # Frozen at finish: the request's own duration, not its age.
                "elapsedMs": round((end - entry["startedAt"]) * 1000.0, 1),
                "completedStages": [dict(s) for s in entry["stages"]],
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ProgressHandle:
    def __init__(self, registry: ProgressRegistry, owner: str, request_id: str, token: int) -> None:
        self._registry = registry
        self._owner = owner
        self._request_id = request_id
        self._token = token

    def phase(self, name: str) -> None:
        self._registry._update(self._owner, self._request_id, self._token, phase=name)

    def stage_done(self, name: str, ms: float) -> None:
        self._registry._update(
            self._owner,
            self._request_id,
            self._token,
            completed_stage={"stage": name, "ms": ms},
        )

    def finish(self, state: str) -> None:
        """``complete``, ``failed`` or ``cancelled`` (client went away)."""
        phase = "complete" if state == "complete" else FAILED
        self._registry._update(self._owner, self._request_id, self._token, phase=phase, state=state)


PROGRESS = ProgressRegistry()


class StageClock:
    """Wall time per server stage of one request."""

    def __init__(self, progress: ProgressHandle | None = None) -> None:
        self._t0 = time.perf_counter()
        self._stages: list[tuple[str, float]] = []
        self.progress = progress

    @contextmanager
    def stage(self, name: str):
        """Time one stage.  A name timed twice (``resolve``: its route part and
        its simulation part) accumulates into ONE entry."""
        if self.progress is not None:
            self.progress.phase(name)
        t0 = time.perf_counter()
        try:
            yield
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            for i, (existing, prior) in enumerate(self._stages):
                if existing == name:
                    ms += prior
                    self._stages[i] = (name, ms)
                    break
            else:
                self._stages.append((name, ms))
            if self.progress is not None:
                self.progress.stage_done(name, round(ms, 1))

    def stages(self) -> list[tuple[str, float]]:
        """A snapshot (a copy), so a reader never sees stages recorded later."""
        return list(self._stages)

    def _total_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000.0, 1)

    def to_dict(
        self,
        *,
        shared_stages: list[tuple[str, float]] | None = None,
        detail: bool = True,
    ) -> dict[str, Any]:
        """``detail=False`` (guest sessions) publishes the total only: per-stage
        times can reveal whether a shared cache was warm."""
        out: dict[str, Any] = {
            "version": TIMING_VERSION,
            "unit": "ms",
            "totalMs": self._total_ms(),
            "note": (
                "server wall time for this request, by stage; excludes network "
                "transfer and browser rendering"
            ),
        }
        if not detail:
            out["detail"] = "total_only"
            out["note"] = (
                "server wall time for this request; excludes network transfer and "
                "browser rendering"
            )
            return out
        out["stages"] = [{"stage": n, "ms": round(ms, 1)} for n, ms in self._stages]
        out["sharedComputation"] = shared_stages is not None
        if shared_stages is not None:
            out["sharedStages"] = [{"stage": n, "ms": round(ms, 1)} for n, ms in shared_stages]
        return out

    def server_timing(self, *, detail: bool = True) -> str:
        parts = [f"{n};dur={round(ms, 1)}" for n, ms in self._stages] if detail else []
        parts.append(f"total;dur={self._total_ms()}")
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
        # In order, never sorted: a repeated parameter is read last-wins
        # (``valuationMode=a&valuationMode=b`` != the reverse).
        tuple((str(k), str(v)) for k, v in query_items),
        canonical,
        id(contract),
        str((meta or {}).get("generatedAt") or "") if isinstance(meta, Mapping) else "",
    )


class _AsyncFlight:
    """One shared computation and its single retry wave."""

    __slots__ = ("task", "retry")

    def __init__(self, task: asyncio.Future) -> None:
        self.task = task
        self.retry: asyncio.Future | None = None


def _start(factory: Callable[[], Awaitable[T]]) -> asyncio.Future:
    """Run ``factory`` as a task.  A factory that raises SYNCHRONOUSLY becomes
    a failed future — that failure is the attempt's outcome — instead of
    escaping before the flight records its attempt."""
    try:
        return asyncio.ensure_future(factory())
    except Exception as exc:  # noqa: BLE001 — becomes the attempt's outcome
        failed = asyncio.get_running_loop().create_future()
        failed.set_exception(exc)
        return failed


def _retrieve(task: asyncio.Future, *, kind: str, label: str | None) -> None:
    """Retrieve a finished attempt's exception (never "exception was never
    retrieved") and log it, so an orphaned attempt's failure is not silent.
    Logs the request id and the exception CLASS only — no user or league data."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        LOG.warning(
            "trade analysis shared %s failed (request %s): %s",
            kind,
            label or "-",
            type(exc).__name__,
        )


class AsyncSingleFlight:
    """One in-flight coroutine per key on one event loop; nothing retained.

    The shared computation runs as its own task, so a caller that is cancelled
    (client gone) does not cancel it for the others.  Only SUCCESS fans out:
    when the shared computation fails, its joiners make ONE retry between
    them (itself shared), and every joiner gets that retry's outcome, success
    or failure — at most two computations per wave, however many joined.
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[int, Hashable], _AsyncFlight] = {}

    def in_flight(self) -> int:
        return sum(1 for f in self._pending.values() if not f.task.done())

    async def run(
        self,
        key: Hashable,
        factory: Callable[[], Awaitable[T]],
        *,
        on_join: Callable[[], None] | None = None,
        share_if: Callable[[T], bool] | None = None,
        personal_if: Callable[[T], bool] | None = None,
        label: str | None = None,
    ) -> tuple[T, bool]:
        """``(result, joined)``.  ``on_join`` runs the moment a caller joins an
        in-flight computation (before waiting on it).

        A joiner whose leader raised, was cancelled, or returned a result
        ``share_if`` rejects (a transient 5xx) does not inherit that failure:
        the first such joiner starts the wave's one retry with its own
        ``factory`` and the rest join it, getting its outcome — success, 5xx or
        exception — except an outcome ``personal_if`` marks as about the retry
        leader's own caller (a 401 / 403 of ITS session), which a joiner never
        inherits: it computes for itself.  A joiner whose OWN request was
        cancelled re-raises, even when the leader was cancelled in the same
        tick.  ``label`` (a request id) only names failures in the log."""
        loop = asyncio.get_running_loop()
        slot = (id(loop), key)
        flight = self._pending.get(slot)
        if flight is not None and not flight.task.done():
            if on_join is not None:
                on_join()
            ok = False
            try:
                result = await asyncio.shield(flight.task)
                ok = share_if is None or share_if(result)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise  # this joiner itself was cancelled
            except Exception:  # noqa: BLE001 — the leader's failure is not ours (yet)
                ok = False
            if ok:
                return result, True
            retry_leader = flight.retry is None
            if retry_leader:
                flight.retry = _start(factory)
                flight.retry.add_done_callback(lambda t: _retrieve(t, kind="retry", label=label))
            outcome = await asyncio.shield(flight.retry)
            if not retry_leader and personal_if is not None and personal_if(outcome):
                return await factory(), False  # another session's refusal is not ours
            return outcome, not retry_leader
        task = _start(factory)
        flight = _AsyncFlight(task)
        self._pending[slot] = flight

        def _done(t: asyncio.Future, slot: tuple[int, Hashable] = slot) -> None:
            if (current := self._pending.get(slot)) is not None and current.task is t:
                del self._pending[slot]
            _retrieve(t, kind="computation", label=label)

        task.add_done_callback(_done)
        return await asyncio.shield(task), False
