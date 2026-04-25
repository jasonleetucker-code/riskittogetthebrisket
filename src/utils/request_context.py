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
import secrets
from typing import Any

# Generated per-request; available from any point during request
# handling.  "" outside request scope (startup / shutdown / tests).
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="",
)

# Opaque user context.  Handlers that have a session set this; logs
# pick it up.  Cleared by the middleware at response time.
_user_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "user_ctx", default={},
)


def new_request_id() -> str:
    """12-char URL-safe token — short enough to eyeball, long
    enough to not collide across a day's traffic."""
    return secrets.token_urlsafe(9)  # 9 bytes → 12 base64 chars


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
