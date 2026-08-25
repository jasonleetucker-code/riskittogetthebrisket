"""Simple in-memory token-bucket rate limiter for public endpoints.

Protects endpoints under the public allowlist — /api/public/league,
/api/leagues, /api/health, /api/auth/status — from scraper abuse
without needing redis or a separate service.

Rules
-----
* 60 requests/minute per IP (default; configurable per-endpoint).
* 1000 requests/hour per IP (burst cap).
* Bypass for allowlisted IPs (the uptime monitor, Jason's home).

Internal
--------
Per-IP bucket stores (tokens, last_refill_epoch).  O(1) per-request.
A background LRU-ish evict runs when the bucket dict exceeds
_MAX_TRACKED_IPS — keeps memory bounded.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_MAX_TRACKED_IPS = 5000


@dataclass
class _Bucket:
    tokens_minute: float
    last_refill_minute: float
    tokens_hour: float
    last_refill_hour: float


_buckets: dict[str, _Bucket] = {}
_lock = threading.Lock()

# Env overrides so Jason can bump limits without a code deploy.
_RATE_PER_MIN = float(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
_RATE_PER_HOUR = float(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

# IPs that bypass rate limiting (uptime monitors, operator IPs, etc.).
# Comma-separated in env.
_BYPASS_IPS = frozenset(
    s.strip() for s in (os.getenv("RATE_LIMIT_BYPASS_IPS") or "").split(",") if s.strip()
)


def _refill(bucket: _Bucket, now: float) -> None:
    """Token-bucket refill.  Minute-rate refills one token every
    ``60/RATE_PER_MIN`` seconds; hour-rate refills one every
    ``3600/RATE_PER_HOUR`` seconds."""
    # Minute bucket.
    elapsed_min = now - bucket.last_refill_minute
    if elapsed_min > 0:
        bucket.tokens_minute = min(
            _RATE_PER_MIN,
            bucket.tokens_minute + elapsed_min * (_RATE_PER_MIN / 60.0),
        )
        bucket.last_refill_minute = now
    # Hour bucket.
    elapsed_hour = now - bucket.last_refill_hour
    if elapsed_hour > 0:
        bucket.tokens_hour = min(
            _RATE_PER_HOUR,
            bucket.tokens_hour + elapsed_hour * (_RATE_PER_HOUR / 3600.0),
        )
        bucket.last_refill_hour = now


def should_rate_limit(ip: str) -> tuple[bool, int]:
    """Return ``(is_limited, retry_after_seconds)``.

    Thread-safe.  Refills + decrements atomically.  Never blocks.
    """
    if not ip or ip in _BYPASS_IPS:
        return (False, 0)
    now = time.time()
    with _lock:
        bucket = _buckets.get(ip)
        if bucket is None:
            # Brand-new IP — full buckets.
            bucket = _Bucket(
                tokens_minute=_RATE_PER_MIN - 1,
                last_refill_minute=now,
                tokens_hour=_RATE_PER_HOUR - 1,
                last_refill_hour=now,
            )
            _buckets[ip] = bucket
            _maybe_evict()
            return (False, 0)
        _refill(bucket, now)
        if bucket.tokens_minute < 1:
            # Retry-After = seconds until next token.
            retry = int(60.0 / _RATE_PER_MIN) + 1
            return (True, retry)
        if bucket.tokens_hour < 1:
            retry = int(3600.0 / _RATE_PER_HOUR) + 1
            return (True, retry)
        bucket.tokens_minute -= 1
        bucket.tokens_hour -= 1
        return (False, 0)


def _maybe_evict() -> None:
    """Drop oldest buckets when we hit the tracked-IP cap.  Called
    under _lock."""
    if len(_buckets) <= _MAX_TRACKED_IPS:
        return
    # Evict the 10% least-recently-refilled.
    target = max(1, _MAX_TRACKED_IPS // 10)
    sorted_ips = sorted(
        _buckets.items(),
        key=lambda kv: min(kv[1].last_refill_minute, kv[1].last_refill_hour),
    )[:target]
    for ip, _ in sorted_ips:
        _buckets.pop(ip, None)


def snapshot() -> dict[str, Any]:
    """Return summary stats for /api/status observability."""
    with _lock:
        return {
            "trackedIps": len(_buckets),
            "perMinuteLimit": _RATE_PER_MIN,
            "perHourLimit": _RATE_PER_HOUR,
            "bypassIps": sorted(_BYPASS_IPS),
        }


def reset_for_tests() -> None:
    with _lock:
        _buckets.clear()
    login_reset_for_tests()


# ── Login failure throttle (W22-F003) ────────────────────────────────
#
# ``POST /api/auth/login`` had no throttle of its own, no lockout and
# no failure backoff — 200 wrong-password attempts landed at 223 req/s
# with zero 429.  This is a dedicated FAILURE throttle, separate from
# the public token buckets above: it counts failed credential checks
# and imposes an exponential delay once the free attempts are spent.
#
# Keying — INVARIANT: a lockout is NEVER keyed on username alone.  An
# attacker must not be able to lock the real owner out remotely by
# spraying failures at the owner's username from anywhere on the
# internet; the per-username component is therefore always scoped
# WITHIN the client IP.  Each failure is charged to two keys:
#
#   * ``ip:<ip>``             — throttles username rotation from one host
#   * ``ipuser:<ip>|<user>``  — throttles password guessing on one account
#
# Failures from IP A never throttle IP B (test-pinned in
# tests/api/test_login_throttle.py).  With no usable client IP nothing
# is keyed at all — falling back to the bare username would break the
# invariant.
#
# All constants live here, once:
_LOGIN_FREE_ATTEMPTS = 5  # failures per window before the backoff starts
_LOGIN_BACKOFF_BASE_SECONDS = 1.0  # first delay; then 2s, 4s, ... doubling
_LOGIN_BACKOFF_CAP_SECONDS = 60.0  # the doubling caps here
_LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60  # cool-off: state expires after this
#                                          long with no new failure
_MAX_TRACKED_LOGIN_KEYS = 5000


@dataclass
class _LoginFailureState:
    failures: int
    last_failure_at: float
    blocked_until: float


_login_failures: dict[str, _LoginFailureState] = {}
_login_lock = threading.Lock()


def _login_now() -> float:
    """The login throttle's single clock read — a seam so tests can
    drive the backoff without sleeping."""
    return time.time()


def _login_keys(ip: str, username: str) -> list[str]:
    """The keys one attempt is charged to.  Never the bare username —
    see the invariant in the section comment above."""
    keys: list[str] = []
    ip = (ip or "").strip()
    if not ip:
        return keys
    keys.append(f"ip:{ip}")
    user = (username or "").strip().lower()
    if user:
        keys.append(f"ipuser:{ip}|{user}")
    return keys


def _login_state_expired(state: _LoginFailureState, now: float) -> bool:
    return now - state.last_failure_at >= _LOGIN_FAILURE_WINDOW_SECONDS


def login_throttle_check(ip: str, username: str) -> tuple[bool, int]:
    """``(is_blocked, retry_after_seconds)`` for one login attempt.

    Call BEFORE any credential comparison, so a blocked caller learns
    nothing about validity.  Never blocks a first attempt (no recorded
    failures → no state → not blocked).
    """
    now = _login_now()
    worst = 0.0
    with _login_lock:
        for key in _login_keys(ip, username):
            state = _login_failures.get(key)
            if state is None:
                continue
            if _login_state_expired(state, now):
                # Cool-off elapsed — the window resets.
                _login_failures.pop(key, None)
                continue
            worst = max(worst, state.blocked_until - now)
    if worst > 0:
        return (True, max(1, math.ceil(worst)))
    return (False, 0)


def login_record_failure(ip: str, username: str) -> None:
    """Record one FAILED credential check against both keys.

    The first ``_LOGIN_FREE_ATTEMPTS`` failures in a window carry no
    delay; from then on the next attempt is pushed out exponentially
    (1s, 2s, 4s, ... capped at ``_LOGIN_BACKOFF_CAP_SECONDS``).
    """
    now = _login_now()
    with _login_lock:
        for key in _login_keys(ip, username):
            state = _login_failures.get(key)
            if state is None or _login_state_expired(state, now):
                state = _LoginFailureState(failures=0, last_failure_at=now, blocked_until=0.0)
                _login_failures[key] = state
            state.failures += 1
            state.last_failure_at = now
            if state.failures >= _LOGIN_FREE_ATTEMPTS:
                delay = min(
                    _LOGIN_BACKOFF_CAP_SECONDS,
                    _LOGIN_BACKOFF_BASE_SECONDS * (2.0 ** (state.failures - _LOGIN_FREE_ATTEMPTS)),
                )
                state.blocked_until = max(state.blocked_until, now + delay)
        _maybe_evict_login_keys()


def login_record_success(ip: str, username: str) -> None:
    """A successful login clears the ``(ip, username)`` failure state.

    Deliberately NOT the bare-IP key: an attacker holding one valid
    credential (e.g. a guest pass) must not be able to reset the
    IP-wide counter between guessing bursts.  The IP key expires on its
    own via the cool-off window.
    """
    ip = (ip or "").strip()
    user = (username or "").strip().lower()
    if not ip or not user:
        return
    with _login_lock:
        _login_failures.pop(f"ipuser:{ip}|{user}", None)


def _maybe_evict_login_keys() -> None:
    """Bound memory: drop the oldest 10% when the cap is hit.  Called
    under ``_login_lock``."""
    if len(_login_failures) <= _MAX_TRACKED_LOGIN_KEYS:
        return
    target = max(1, _MAX_TRACKED_LOGIN_KEYS // 10)
    oldest = sorted(
        _login_failures.items(),
        key=lambda kv: kv[1].last_failure_at,
    )[:target]
    for key, _ in oldest:
        _login_failures.pop(key, None)


def login_throttle_snapshot() -> dict[str, Any]:
    """Summary stats for observability."""
    with _login_lock:
        return {
            "trackedKeys": len(_login_failures),
            "freeAttempts": _LOGIN_FREE_ATTEMPTS,
            "backoffBaseSeconds": _LOGIN_BACKOFF_BASE_SECONDS,
            "backoffCapSeconds": _LOGIN_BACKOFF_CAP_SECONDS,
            "failureWindowSeconds": _LOGIN_FAILURE_WINDOW_SECONDS,
        }


def login_reset_for_tests() -> None:
    with _login_lock:
        _login_failures.clear()
