"""Per-request correlation context.

Every request gets a short, URL-safe request ID generated in the
middleware and stashed in a ContextVar.  Any log line emitted while
handling that request can pick it up via ``current_request_id()``
without having to thread it through every function call.

This is the observability foundation — request ID lets ops grep a
single request's full lifecycle across ingestion → auth → handler
→ external-call → response in the log stream.

Also exposes ``current_user()`` so signal + audit logs can say WHO
triggered an action without the endpoint re-reading the session.

All getters return sane defaults when called outside a request
context (tests, scripts, startup) — never raise.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
from typing import Any

# Generated per-request; available from any point during request
# handling.  "" outside request scope (startup / shutdown / tests).
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="",
)
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="")
_parent_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "parent_span_id", default=None
)
_trace_flags: contextvars.ContextVar[str] = contextvars.ContextVar("trace_flags", default="01")
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Opaque user context.  Handlers that have a session set this; logs
# pick it up.  Cleared by the middleware at response time.
_user_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "user_ctx",
    default={},
)


def new_request_id() -> str:
    """12-char URL-safe token — short enough to eyeball, long
    enough to not collide across a day's traffic."""
    return secrets.token_urlsafe(9)  # 9 bytes → 12 base64 chars


def valid_request_id(value: str) -> bool:
    return _REQUEST_ID.fullmatch(value) is not None


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: str | None) -> tuple[str, str, str] | None:
    match = _TRACEPARENT.fullmatch(value or "")
    if not match or int(match[1], 16) == 0 or int(match[2], 16) == 0:
        return None
    return match[1], match[2], match[3]


def set_trace_context(
    trace_id: str, span_id: str, parent_span_id: str | None, flags: str = "01"
) -> tuple[contextvars.Token, ...]:
    return (
        _trace_id.set(trace_id),
        _span_id.set(span_id),
        _parent_span_id.set(parent_span_id),
        _trace_flags.set(flags),
    )


def reset_trace_context(tokens: tuple[contextvars.Token, ...]) -> None:
    for variable, token in zip(
        (_trace_id, _span_id, _parent_span_id, _trace_flags), tokens, strict=True
    ):
        variable.reset(token)


def current_trace_id() -> str:
    return _trace_id.get()


def current_span_id() -> str:
    return _span_id.get()


def current_traceparent() -> str:
    if not _trace_id.get() or not _span_id.get():
        return ""
    return f"00-{_trace_id.get()}-{_span_id.get()}-{_trace_flags.get()}"


def emit_http_span(
    *, method: str, route: str, status_code: int, duration_ms: float, failure_class: str | None
) -> None:
    """Emit bounded, privacy-safe JSON to the existing application log stream."""
    try:
        from src.api.build_identity import PROCESS_BUILD, PROCESS_RELEASE

        event = {
            "event": "http.server.request",
            "trace_id": current_trace_id() or None,
            "span_id": current_span_id() or None,
            "parent_span_id": _parent_span_id.get(),
            "request_id": current_request_id() or None,
            "http_method": method,
            "http_route": route,
            "http_status_code": status_code,
            "duration_ms": max(0.0, duration_ms),
            "failure_class": failure_class,
            "deployment_commit": PROCESS_BUILD["commit"],
            "frontend_artifact_id": PROCESS_RELEASE["frontend_artifact_id"],
        }
        logging.getLogger("calculator.trace").info(json.dumps(event, separators=(",", ":")))
    except Exception:  # noqa: BLE001 — telemetry must never break a request
        return


def set_request_id(rid: str) -> contextvars.Token:
    """Set the current request ID; returns the reset token."""
    return _request_id.set(rid or "")


def current_request_id() -> str:
    try:
        return _request_id.get()
    except LookupError:
        return ""


def set_user(user: dict[str, Any] | None) -> contextvars.Token:
    return _user_ctx.set(user or {})


def current_user() -> dict[str, Any]:
    try:
        return _user_ctx.get() or {}
    except LookupError:
        return {}


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


def reset_user(token: contextvars.Token) -> None:
    _user_ctx.reset(token)
