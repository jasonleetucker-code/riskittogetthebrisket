"""Per-target circuit breaker for external services.

Pattern
-------
A circuit breaker wraps a call site that depends on an external
service (Sleeper, ESPN, KTC, SMTP, nflverse).  When the service
fails ``failure_threshold`` times in the ``failure_window``
seconds, the breaker OPENS and subsequent calls fail fast for
``open_duration_sec`` without touching the network.

States
------
    CLOSED   — normal.  Every call is attempted.
    OPEN     — tripped.  Every call fails fast with the last error.
    HALF_OPEN — probe.  One call is allowed through; success
               closes the breaker, failure re-opens it.

Goals for this codebase
-----------------------
1. **Prevent cascading failures** — if Sleeper is down for 10
   minutes, we don't queue up 2,000 timeouts.
2. **Preserve cached responses** — when breaker is open, callers
   fall back to their cache layer cleanly.
3. **Be observable** — every state transition logs a structured
   event and increments per-breaker metrics.

Design
------
Not a decorator, not a context manager — a tiny stateful class you
ask ``can_call()`` before the network call and ``report_success()``
/ ``report_failure(exc)`` after.  Keeps the breaker orthogonal to
whatever HTTP client / caching layer each call site already uses.

A global registry indexes breakers by name so ``/api/status`` can
report the state of every external dependency in one snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


# Breaker states.
CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


@dataclass
class _Counters:
    success: int = 0
    failure: int = 0
    fast_fail: int = 0  # call rejected because breaker open
    opens: int = 0
    closes: int = 0


@dataclass
class CircuitBreaker:
    """A single breaker.  Thread-safe.

    Configuration:
        failure_threshold — consecutive failures within
                            failure_window_sec that trip the breaker.
        failure_window_sec — rolling window (sliding) for counting
                             failures.  Failures older than this
                             don't count.
        open_duration_sec — how long the breaker stays OPEN before
                            moving to HALF_OPEN.
        name — human-readable label for logging.
    """

    name: str
    failure_threshold: int = 5
    failure_window_sec: float = 60.0
    open_duration_sec: float = 60.0

    _state: str = CLOSED
    _state_since: float = 0.0
    _failure_timestamps: list[float] = field(default_factory=list)
    _last_error: str = ""
    _counters: _Counters = field(default_factory=_Counters)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def can_call(self) -> bool:
        """Returns True if the call may proceed.  Transitions OPEN
        → HALF_OPEN when the open window expires."""
        now = time.time()
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                if now - self._state_since >= self.open_duration_sec:
                    self._transition(HALF_OPEN, now)
                    return True
                self._counters.fast_fail += 1
                return False
            if self._state == HALF_OPEN:
                return True
            return True

    def report_success(self) -> None:
        """Call after a successful external call."""
        now = time.time()
        with self._lock:
            self._counters.success += 1
            # Any success in HALF_OPEN closes the breaker.
            if self._state == HALF_OPEN:
                self._transition(CLOSED, now)
            # Successes don't clear the failure window — if 5 failures
            # are still within the window they may trip the breaker on
            # the next failure.  But a CLOSED breaker with trailing
            # successes is fine.

    def report_failure(self, exc: BaseException | str | None = None) -> None:
        """Call after a failed external call."""
        now = time.time()
        err = str(exc)[:120] if exc is not None else ""
        with self._lock:
            self._counters.failure += 1
            self._last_error = err
            # HALF_OPEN failure → re-open immediately.
            if self._state == HALF_OPEN:
                self._transition(OPEN, now)
                return
            # CLOSED: push failure into the sliding window.
            self._failure_timestamps.append(now)
            cutoff = now - self.failure_window_sec
            self._failure_timestamps = [
                t for t in self._failure_timestamps if t > cutoff
            ]
            if len(self._failure_timestamps) >= self.failure_threshold:
                self._transition(OPEN, now)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            age = round(now - self._state_since, 1) if self._state_since else None
            return {
                "name": self.name,
                "state": self._state,
                "stateAgeSec": age,
                "lastError": self._last_error,
                "counters": {
                    "success": self._counters.success,
                    "failure": self._counters.failure,
                    "fastFail": self._counters.fast_fail,
                    "opens": self._counters.opens,
                    "closes": self._counters.closes,
                },
                "failureWindowSec": self.failure_window_sec,
                "failureThreshold": self.failure_threshold,
                "openDurationSec": self.open_duration_sec,
                "recentFailuresInWindow": len(self._failure_timestamps),
            }

    def _transition(self, new_state: str, now: float) -> None:
        """Move to ``new_state``.  Must be called under _lock."""
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        self._state_since = now
        if new_state == OPEN:
            self._counters.opens += 1
            _LOGGER.warning(
                "circuit_breaker=open name=%s threshold=%d window=%.0fs "
                "last_error=%r",
                self.name, self.failure_threshold,
                self.failure_window_sec, self._last_error,
            )
        elif new_state == CLOSED:
            self._counters.closes += 1
            self._failure_timestamps.clear()
            _LOGGER.info(
                "circuit_breaker=closed name=%s from=%s",
                self.name, old_state,
            )
        elif new_state == HALF_OPEN:
            _LOGGER.info(
                "circuit_breaker=half_open name=%s probing after %.0fs",
                self.name, self.open_duration_sec,
            )

    def force_close(self) -> None:
        """Operator override — admin endpoint can reset the breaker."""
        with self._lock:
            self._transition(CLOSED, time.time())

    def reset_for_tests(self) -> None:
        with self._lock:
            self._state = CLOSED
            self._state_since = 0.0
            self._failure_timestamps.clear()
            self._last_error = ""
            self._counters = _Counters()


# ── Global registry ─────────────────────────────────────────────

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_or_create(
    name: str,
    *,
    failure_threshold: int = 5,
    failure_window_sec: float = 60.0,
    open_duration_sec: float = 60.0,
) -> CircuitBreaker:
    """Fetch the named breaker, creating it with the given defaults
    on first call.  Thread-safe."""
    with _registry_lock:
        bp = _registry.get(name)
        if bp is None:
            bp = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                failure_window_sec=failure_window_sec,
                open_duration_sec=open_duration_sec,
            )
            _registry[name] = bp
        return bp


def snapshot_all() -> list[dict[str, Any]]:
    """Return every registered breaker's snapshot.  Used by
    ``/api/status.circuitBreakers`` for ops observability."""
    with _registry_lock:
        names = list(_registry.keys())
    return [_registry[n].snapshot() for n in sorted(names)]


def reset_all_for_tests() -> None:
    with _registry_lock:
        for bp in _registry.values():
            bp.reset_for_tests()
        _registry.clear()
