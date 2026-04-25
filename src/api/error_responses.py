"""Standardized error-response shape + global exception handler.

Every error response from the app — whether from a handler's own
``JSONResponse(status_code=N, content={...})`` or from an
unhandled exception caught by the global handler — emits the same
envelope::

    {
      "error": "<short_code_or_message>",
      "message": "<human-readable>",
      "context": {"endpoint": "...", "requestId": "...", ...},
      "timestamp": "2026-04-25T00:00:00+00:00"
    }

Handlers that want to enrich context (leagueKey, user, etc.) call
``error_payload(...)``.  The global ``install_exception_handler``
wraps FastAPI's app so ANY raised exception is caught, logged
with full context (traceback + request-id + path + method +
client IP), and returned as a 500 with the standard shape — no
more "stack trace leaked to browser" surprises.

Backward compat
---------------
Existing endpoints use different error field combinations
(``{"error": "..."}`` alone, ``{"ok": False, "error": "..."}``, etc.).
This module ADDS the envelope for unhandled paths and offers the
``error_payload()`` helper as an opt-in for new handlers.  We do
NOT rewrite every existing handler to conform — that would risk
breaking client parsers.  New code should use ``error_payload``.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.utils.request_context import current_request_id, current_user

_LOGGER = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def error_payload(
    error: str,
    *,
    message: str | None = None,
    context: dict[str, Any] | None = None,
    status_code: int = 400,
) -> tuple[int, dict[str, Any]]:
    """Return a ``(status_code, body)`` tuple with the standard
    envelope.  Handlers use this to emit structured errors::

        status, body = error_payload(
            "unknown_league",
            message="League 'ghost' is not configured",
            context={"leagueKey": "ghost"},
            status_code=400,
        )
        return JSONResponse(status_code=status, content=body)
    """
    ctx = dict(context or {})
    rid = current_request_id()
    if rid:
        ctx.setdefault("requestId", rid)
    user = current_user()
    if user:
        # Include username only — never session ID or Sleeper ID
        # in error payloads.
        if user.get("username"):
            ctx.setdefault("user", user.get("username"))
    return status_code, {
        "error": error,
        "message": message or error,
        "context": ctx,
        "timestamp": _utc_now_iso(),
    }


def install_exception_handler(app: FastAPI) -> None:
    """Register a global handler that catches every unhandled
    exception and returns a safe 500 in the standard envelope.

    Critical: this runs OUTSIDE any middleware, so a crash in a
    middleware (auth gate, rate limiter) is also caught.
    """

    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        # Never let a handler crash silently; always log with full
        # context that correlates to the request.
        rid = current_request_id()
        client_ip = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else ""
        )
        tb = traceback.format_exc()
        _LOGGER.error(
            "unhandled_exception requestId=%s method=%s path=%s ip=%s error=%s\n%s",
            rid or "-",
            request.method,
            request.url.path,
            client_ip,
            type(exc).__name__,
            tb,
        )
        status, body = error_payload(
            "internal_error",
            message="An internal error occurred.  The team has been notified.",
            context={
                "endpoint": request.url.path,
                "method": request.method,
                # NEVER expose the traceback or raw exception message
                # in a production response — just the type.  Logs
                # have the full trace.
                "errorType": type(exc).__name__,
            },
            status_code=500,
        )
        # Stamp X-Request-Id on the exception response — the
        # request-context middleware's response-mutation step
        # doesn't run when an exception propagates past call_next.
        headers = {"X-Request-Id": rid} if rid else {}
        return JSONResponse(status_code=status, content=body, headers=headers)
