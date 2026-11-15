"""Per-route admission control for the N-team trade analyze routes (R2-5).

The ONE owner of "may this request start an engine computation, and how long
will its caller wait for it?" for:

* ``POST /api/public/league/trade-advisor/analyze`` (route key
  ``public_advisor_analyze``, ``src/api/public_trade_advisor_api.py``);
* ``POST /api/trade/analyze-multi`` (route key ``trade_analyze_multi``,
  ``server.py``).

Why it exists: the analyze work is pure Python and GIL-bound.  Measured
locally (Lane E-4), one process saturates at ~12-14 worst-case public analyses
per second, and past that point latency grows with concurrency and spills onto
EVERY route (``/api/health`` went from ~20 ms to 0.7-1.4 s at 32 concurrent
public requests, ~10 s at 32 private ones).  The rate limiters bound requests
per time window, not requests in flight, so neither route had a bound on
concurrent work or on how long a caller could be held.

Two independent controls, both fail closed with a RETRYABLE refusal:

* :meth:`ComputeAdmission.admit` — wraps ONE computation (inside the route's
  single-flight factory, so joined waiters never take a slot).  When
  ``maxConcurrent`` computations are already running the request is refused at
  once (``reason == "busy"``) rather than queued behind the GIL.
* :meth:`ComputeAdmission.within_deadline` — wraps the caller's wait.  After
  ``timeoutSeconds`` the caller is answered (``reason == "timeout"``).  The
  computation runs in a worker thread and cannot be interrupted, so it is NOT
  abandoned: it keeps its slot until it really finishes (the concurrency bound
  is therefore a bound on real work, not on waiting callers), and an identical
  retry joins it through the route's single-flight instead of starting another.

Sizes live in ``config/trade/analyze_admission.json`` and are PENDING OWNER
CONFIRMATION (directive 2026-10-20 §16 gate 7).  A missing, unreadable or
malformed entry falls back to :data:`DEFAULTS`; a non-positive or non-numeric
size is never read as "unlimited".
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

_LOG = logging.getLogger(__name__)

T = TypeVar("T")

ROUTE_PUBLIC_ADVISOR = "public_advisor_analyze"
ROUTE_ANALYZE_MULTI = "trade_analyze_multi"

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "analyze_admission.json"


@dataclass(frozen=True)
class AdmissionSpec:
    max_concurrent: int
    timeout_seconds: float


#: Conservative defaults, PENDING OWNER CONFIRMATION — identical to the
#: committed config so an unreadable file changes nothing.
DEFAULTS: dict[str, AdmissionSpec] = {
    ROUTE_PUBLIC_ADVISOR: AdmissionSpec(max_concurrent=2, timeout_seconds=5.0),
    ROUTE_ANALYZE_MULTI: AdmissionSpec(max_concurrent=2, timeout_seconds=30.0),
}

#: The ``Retry-After`` hint on a refusal.  A hint, not a limit: a busy slot
#: frees within a computation's lifetime (sub-second at p99 on the public
#: route), and a timed-out caller's identical retry joins its computation.
RETRY_AFTER_SECONDS = 1


class AdmissionRejected(Exception):
    """The route refused to start (``busy``) or stopped waiting for
    (``timeout``) a computation.  Always retryable."""

    def __init__(self, route: str, reason: str) -> None:
        super().__init__(f"{route}:{reason}")
        self.route = route
        self.reason = reason
        self.retry_after_seconds = RETRY_AFTER_SECONDS


def _positive_int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _positive_seconds(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) and f > 0 else None


def parse_spec(raw: Any, default: AdmissionSpec) -> AdmissionSpec:
    """One route's spec from its config entry; each field independently falls
    back to ``default`` when absent or malformed (never unlimited)."""
    entry = raw if isinstance(raw, dict) else {}
    mc = _positive_int(entry.get("maxConcurrent"))
    ts = _positive_seconds(entry.get("timeoutSeconds"))
    return AdmissionSpec(
        max_concurrent=mc if mc is not None else default.max_concurrent,
        timeout_seconds=ts if ts is not None else default.timeout_seconds,
    )


@lru_cache(maxsize=1)
def _config_routes() -> dict[str, Any]:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOG.error("analyze admission config unreadable; using the declared defaults")
        return {}
    routes = raw.get("routes") if isinstance(raw, dict) else None
    return routes if isinstance(routes, dict) else {}


def spec_for(route: str) -> AdmissionSpec:
    if route not in DEFAULTS:
        raise KeyError(f"unknown admission route {route!r}")
    return parse_spec(_config_routes().get(route), DEFAULTS[route])


def _retrieve_quietly(task: asyncio.Future) -> None:
    """Consume an abandoned wait's outcome so it is never "exception was never
    retrieved"; log the exception CLASS only (no request content)."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOG.warning(
            "analyze computation finished after its caller timed out: %s", type(exc).__name__
        )


class ComputeAdmission:
    """Concurrency slots and a caller deadline for ONE route (see module doc).

    The spec is resolved per call through ``spec_provider`` so a config change
    (or a test's override) applies without rebuilding the instance."""

    def __init__(
        self,
        route: str,
        *,
        spec_provider: Callable[[], AdmissionSpec] | None = None,
    ) -> None:
        if route not in DEFAULTS:
            raise KeyError(f"unknown admission route {route!r}")
        self.route = route
        self._spec_provider = spec_provider or (lambda: spec_for(route))
        self._lock = threading.Lock()
        self._active = 0

    def spec(self) -> AdmissionSpec:
        return self._spec_provider()

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def _try_acquire(self) -> bool:
        limit = self.spec().max_concurrent
        with self._lock:
            if self._active >= limit:
                return False
            self._active += 1
            return True

    def _release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    async def admit(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Run ONE computation in a slot, or raise ``AdmissionRejected("busy")``
        without starting it.  The slot is held until the computation's own
        awaitable completes."""
        if not self._try_acquire():
            raise AdmissionRejected(self.route, "busy")
        try:
            return await factory()
        finally:
            self._release()

    async def within_deadline(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Await ``factory()`` for at most ``timeoutSeconds``; past that raise
        ``AdmissionRejected("timeout")``.  The awaited work is shielded: it is
        never cancelled by the deadline or by a disconnected caller, so its
        slot is released only when it really finishes."""
        task = asyncio.ensure_future(factory())
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.spec().timeout_seconds)
        except TimeoutError:
            task.add_done_callback(_retrieve_quietly)
            raise AdmissionRejected(self.route, "timeout") from None
        except asyncio.CancelledError:
            task.add_done_callback(_retrieve_quietly)
            raise


_INSTANCES: dict[str, ComputeAdmission] = {}
_INSTANCES_LOCK = threading.Lock()


def admission_for(route: str) -> ComputeAdmission:
    """The process-wide :class:`ComputeAdmission` for ``route``."""
    with _INSTANCES_LOCK:
        inst = _INSTANCES.get(route)
        if inst is None:
            inst = ComputeAdmission(route)
            _INSTANCES[route] = inst
        return inst


def reset_for_tests() -> None:
    _config_routes.cache_clear()
    with _INSTANCES_LOCK:
        _INSTANCES.clear()
