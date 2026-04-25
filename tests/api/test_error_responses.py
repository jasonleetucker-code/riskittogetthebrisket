"""Tests for the standardized error-response envelope + global
exception handler."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import error_responses as er
from src.utils import request_context as rc


def test_error_payload_has_required_fields():
    status, body = er.error_payload(
        "unknown_league",
        message="League 'ghost' not configured",
        context={"leagueKey": "ghost"},
        status_code=400,
    )
    assert status == 400
    assert body["error"] == "unknown_league"
    assert body["message"] == "League 'ghost' not configured"
    assert body["context"]["leagueKey"] == "ghost"
    assert "timestamp" in body
    # ISO 8601 with timezone.
    assert "T" in body["timestamp"]
    assert body["timestamp"].endswith("+00:00")


def test_error_payload_picks_up_request_id():
    tok = rc.set_request_id("req-test-123")
    try:
        _status, body = er.error_payload("bad_request")
    finally:
        rc.reset_request_id(tok)
    assert body["context"]["requestId"] == "req-test-123"


def test_error_payload_picks_up_username_from_context():
    # Use a sleeper_user_id pattern that can't appear in a timestamp
    # microsecond suffix, so the leak check stays unambiguous.
    sleeper_id = "leak-canary-zzz"
    tok1 = rc.set_request_id("req-1")
    tok2 = rc.set_user({"username": "alice", "sleeper_user_id": sleeper_id})
    try:
        _, body = er.error_payload("x")
    finally:
        rc.reset_request_id(tok1)
        rc.reset_user(tok2)
    # Username exposed, but NOT sleeper_user_id.
    assert body["context"]["user"] == "alice"
    assert "sleeper_user_id" not in body["context"]
    assert sleeper_id not in str(body)


def test_error_payload_default_message_equals_error_code():
    _, body = er.error_payload("some_code")
    assert body["message"] == "some_code"


def test_global_handler_catches_handler_exception():
    """Any unhandled handler exception returns the standard
    500 envelope — no stack trace leaked to the client."""
    app = FastAPI()
    er.install_exception_handler(app)

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("simulated internal failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body["error"] == "internal_error"
    # Message does NOT leak the raw exception text.
    assert "simulated internal failure" not in body["message"]
    assert "traceback" not in str(body).lower()
    # But DOES surface the exception TYPE for triage.
    assert body["context"]["errorType"] == "RuntimeError"
    assert body["context"]["endpoint"] == "/boom"
    assert body["context"]["method"] == "GET"


def test_global_handler_logs_full_trace(caplog):
    """The log line includes the traceback even though the
    response does not."""
    app = FastAPI()
    er.install_exception_handler(app)

    @app.get("/boom")
    async def _boom():
        raise ValueError("inner detail")

    import logging
    with caplog.at_level(logging.ERROR):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/boom")
    logged = "\n".join(r.message for r in caplog.records)
    assert "unhandled_exception" in logged
    # Full trace in the log.
    assert "ValueError" in logged
    assert "inner detail" in logged
