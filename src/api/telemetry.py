"""Bounded, privacy-safe serving measurements; no external collector required.

Metric labels are server route templates, never request paths or identifiers.
W3C trace context can be correlated with an OpenTelemetry collector later; the
local JSON records and counters remain usable when no exporter is installed.
"""

from __future__ import annotations

import contextvars
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger("riskit.performance")
_TRACE = contextvars.ContextVar("performance_trace", default=None)
_LOCK = threading.Lock()
_SERIES: OrderedDict[tuple, dict] = OrderedDict()
_MAX_SERIES = 512
_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 15000, 60000)
_CLS_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5, 1, 5)
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_PAGE_ROUTES = frozenset(
    {
        "/",
        "/rankings",
        "/trade",
        "/draft",
        "/waivers",
        "/rosters",
        "/bdvm",
        "/league",
        "/game-day",
        "/league-comparison",
        "/players/compare",
        "/players/[playerId]",
        "/league/player/[playerId]",
        "/settings",
        "/login",
        "/rankings/[position]",
        "/more",
        "/news",
        "/trending",
        "/edge",
        "/finder",
        "/angle",
        "/arbitrage",
        "/phases",
        "/intel",
        "/consensus-edge",
        "/trades",
        "/market/sharp-tracker",
        "/market/sharp-roster-percentage",
        "other",
    }
)


class WebVital(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["LCP", "INP", "CLS", "FCP", "TTFB", "route-useful"]
    value: float = Field(ge=0, le=3_600_000, allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    route: str
    navigationType: Literal[
        "navigate",
        "reload",
        "back-forward",
        "back_forward",
        "back-forward-cache",
        "restore",
        "prerender",
        "route",
        "unknown",
    ] = "unknown"
    device: Literal["desktop", "mobile", "unknown"] = "unknown"

    @field_validator("route")
    @classmethod
    def safe_route(cls, value: str) -> str:
        if value not in _PAGE_ROUTES:
            raise ValueError("expected an allowlisted route template")
        return value


def _observe(key: tuple, duration_ms: float, *, byte_count: int = 0) -> None:
    if not math.isfinite(duration_ms) or duration_ms < 0:
        return
    with _LOCK:
        bounds = _CLS_BUCKETS if key[0] == "browser" and key[2] == "CLS" else _BUCKETS
        entry = _SERIES.get(key)
        if entry is None:
            if len(_SERIES) >= _MAX_SERIES:
                _SERIES.popitem(last=False)
            entry = {
                "count": 0,
                "sum": 0.0,
                "max": 0.0,
                "bytes": 0,
                "buckets": [0] * (len(bounds) + 1),
                "bucketBounds": list(bounds),
                "unit": "score" if bounds is _CLS_BUCKETS else "milliseconds",
            }
            _SERIES[key] = entry
        entry["count"] += 1
        entry["sum"] += duration_ms
        entry["max"] = max(entry["max"], duration_ms)
        entry["bytes"] += max(0, byte_count)
        bucket = next((i for i, bound in enumerate(bounds) if duration_ms <= bound), len(bounds))
        entry["buckets"][bucket] += 1


def record_vital(metric: WebVital) -> None:
    # IDs are deliberately neither persisted nor labels. CLS uses its native
    # unit; the series names make that distinction explicit.
    _observe(("browser", metric.route, metric.name, metric.device), metric.value)


def snapshot() -> dict:
    with _LOCK:
        series = [
            {"labels": list(k), **v, "buckets": list(v["buckets"])} for k, v in _SERIES.items()
        ]
    return {"bucketBounds": list(_BUCKETS), "seriesLimit": _MAX_SERIES, "series": series}


def reset() -> None:
    with _LOCK:
        _SERIES.clear()


@contextmanager
def work_span(name: str, *, outcome: str = "ok"):
    """Use fixed call-site names only; never pass player/user/provider URLs."""
    started = time.perf_counter()
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        _observe(("work", name, outcome), elapsed)
        trace = _TRACE.get()
        if not trace or trace["sampled"]:
            log.info(
                json.dumps(
                    {
                        "event": "work",
                        "name": name,
                        "outcome": outcome,
                        "durationMs": round(elapsed, 3),
                        "traceId": trace["traceId"] if trace else None,
                        **_identity(),
                    }
                )
            )


def cache_event(name: str, hit: bool) -> None:
    _observe(("cache", name, "hit" if hit else "miss"), 0)


def _identity() -> dict:
    return {
        "deploySha": os.environ.get("RISKIT_DEPLOY_SHA") or None,
        "artifactDigest": os.environ.get("RISKIT_ARTIFACT_DIGEST") or None,
    }


class PerformanceMiddleware:
    """Measure streamed bodies without buffering or writing to a database."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        incoming = dict(scope.get("headers", [])).get(b"traceparent", b"").decode("ascii", "ignore")
        match = _TRACEPARENT.fullmatch(incoming)
        valid = match and int(match[1], 16) and int(match[2], 16)
        trace_id = match[1] if valid else secrets.token_hex(16)
        # Client-supplied sampling flags cannot force unbounded log volume.
        sampled = secrets.randbelow(10) == 0
        trace = {"traceId": trace_id, "spanId": secrets.token_hex(8), "sampled": sampled}
        token = _TRACE.set(trace)
        status = 500
        bytes_sent = 0
        state = scope.setdefault("state", {})
        state["performance_trace_id"] = trace_id

        async def measured_send(message):
            nonlocal status, bytes_sent
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                duration = (time.perf_counter() - started) * 1000
                headers.append((b"server-timing", f"app;dur={duration:.3f}".encode()))
                headers.append((b"x-trace-id", trace_id.encode()))
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body":
                bytes_sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope.get("method", "OTHER")
            method = (
                method
                if method in {"GET", "POST", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"}
                else "OTHER"
            )
            _observe(("http", route, method, str(status)), elapsed, byte_count=bytes_sent)
            if sampled or status >= 500:
                log.info(
                    json.dumps(
                        {
                            "event": "http",
                            "route": route,
                            "method": method,
                            "status": status,
                            "durationMs": round(elapsed, 3),
                            "bytes": bytes_sent,
                            "traceId": trace_id,
                            "requestId": state.get("performance_request_id"),
                            "dataGeneration": state.get("data_generation"),
                            **_identity(),
                        }
                    )
                )
            _TRACE.reset(token)
