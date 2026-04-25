"""Tests for per-request correlation context."""
from __future__ import annotations

import asyncio
import concurrent.futures

from src.utils import request_context as rc


def test_default_empty_outside_request():
    assert rc.current_request_id() == ""
    assert rc.current_user() == {}


def test_set_and_read_request_id():
    tok = rc.set_request_id("abc123")
    try:
        assert rc.current_request_id() == "abc123"
    finally:
        rc.reset_request_id(tok)
    assert rc.current_request_id() == ""


def test_new_request_id_is_url_safe_and_short():
    rid = rc.new_request_id()
    assert isinstance(rid, str)
    assert 10 <= len(rid) <= 16
    # URL-safe: no spaces / special chars.
    for c in rid:
        assert c.isalnum() or c in "-_"


def test_context_isolated_across_async_tasks():
    """Each async task has its own context — one task's request
    ID doesn't leak to a sibling."""
    async def _run(tag):
        rc.set_request_id(f"req-{tag}")
        await asyncio.sleep(0.01)
        return rc.current_request_id()

    async def _driver():
        a, b = await asyncio.gather(_run("a"), _run("b"))
        return a, b

    a, b = asyncio.run(_driver())
    assert a == "req-a"
    assert b == "req-b"


def test_context_isolated_across_threads():
    """Separate thread → separate context.  Context only crosses
    task/thread boundaries via explicit copy, which we don't do."""
    rc.set_request_id("main-thread")
    def _inner():
        return rc.current_request_id()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        val = ex.submit(_inner).result()
    # The thread doesn't inherit the ContextVar (no copy_context).
    assert val == ""
    # Main thread still has it.
    assert rc.current_request_id() == "main-thread"
    rc.set_request_id("")


def test_user_context_isolated():
    tok = rc.set_user({"username": "alice"})
    try:
        assert rc.current_user()["username"] == "alice"
    finally:
        rc.reset_user(tok)
    assert rc.current_user() == {}
