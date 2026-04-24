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
    s.strip() for s in (os.getenv("RATE_LIMIT_BYPASS_IPS") or "").split(",")
    if s.strip()
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
