"""Pin: ``send_alert`` must never block its caller on the network.

THE DEFECT (found during the 2026-10-19 production stall investigation)
----------------------------------------------------------------------
``send_alert`` connected to ``smtp.gmail.com:465`` synchronously with NO
timeout (``smtplib``'s default), and two of its callers run ON the single
event-loop thread:

* ``get_health`` (``async def``), whenever backups look stale;
* ``uptime_watchdog_loop`` (a coroutine), after consecutive uptime failures.

The production VPS firewalls outbound 465 (commit 54af3811cc).  A connect to
a dropped port waits out the kernel's SYN retries, ~127 s per resolved
address, and for that span the process answers nothing.  ``/api/health``
times out, and three timed-out probes make the liveness watchdog restart the
service.  A failed send never set the cooldown, so every trigger tried again.

Pinned here: the caller returns at once while delivery is stuck; delivery
gets a finite timeout; one delivery at a time; success sets the cooldown and
failure releases the slot; every ``smtplib`` connection in ``server.py``
carries a ``timeout=``.
"""

from __future__ import annotations

import ast
import asyncio
import threading
import time
from pathlib import Path

import pytest

import server

_SERVER_PY = Path(server.__file__).resolve()
# Generous for a loaded CI box; the defect blocked for ~127 s.
_PROMPT_SECONDS = 2.0


class _BlockingSMTP:
    """Stands in for ``smtplib.SMTP_SSL``: the constructor (the connect) hangs."""

    instances: list[dict] = []
    release = threading.Event()
    fail = False

    def __init__(self, host, port, **kwargs):
        type(self).instances.append({"host": host, "port": port, **kwargs})
        type(self).release.wait(timeout=10)
        if type(self).fail:
            raise TimeoutError("timed out")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, *_a):
        return None

    def send_message(self, *_a):
        return None


@pytest.fixture(autouse=True)
def _alerting(monkeypatch):
    _BlockingSMTP.instances = []
    _BlockingSMTP.release = threading.Event()
    _BlockingSMTP.fail = False
    monkeypatch.setattr(server, "ALERT_ENABLED", True)
    monkeypatch.setattr(server, "ALERT_FROM", "alerts@example.invalid")
    monkeypatch.setattr(server, "ALERT_TO", "ops@example.invalid")
    monkeypatch.setattr(server, "ALERT_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(server, "_last_alert_time", 0)
    # raising=False so a revert to the unfixed code fails on BEHAVIOUR below,
    # not on this fixture.
    monkeypatch.setattr(server, "_alert_in_flight", False, raising=False)
    monkeypatch.setattr(server.smtplib, "SMTP_SSL", _BlockingSMTP)
    yield
    # Never leave a delivery thread parked on the event.
    _BlockingSMTP.release.set()
    for t in threading.enumerate():
        if t.name == "alert-smtp":
            t.join(timeout=5)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _delivery_threads():
    return [t for t in threading.enumerate() if t.name == "alert-smtp"]


def test_caller_returns_while_the_smtp_connect_is_stuck():
    started = time.monotonic()
    server.send_alert("subject", "body")
    assert time.monotonic() - started < _PROMPT_SECONDS
    assert _wait_for(lambda: len(_BlockingSMTP.instances) == 1)
    assert _delivery_threads(), "delivery should be parked on its own thread"


def test_delivery_carries_a_finite_timeout():
    server.send_alert("subject", "body")
    assert _wait_for(lambda: _BlockingSMTP.instances)
    timeout = _BlockingSMTP.instances[0].get("timeout")
    assert timeout == server.ALERT_SMTP_TIMEOUT_SEC
    assert isinstance(timeout, (int, float)) and 0 < timeout <= 30


def test_only_one_delivery_in_flight():
    server.send_alert("first", "body")
    assert _wait_for(lambda: len(_BlockingSMTP.instances) == 1)
    server.send_alert("second", "body")
    time.sleep(0.1)
    assert len(_BlockingSMTP.instances) == 1


def test_success_sets_the_cooldown():
    _BlockingSMTP.release.set()
    server.send_alert("first", "body")
    assert _wait_for(lambda: server._last_alert_time > 0 and not server._alert_in_flight)
    server.send_alert("second", "body")
    time.sleep(0.1)
    assert len(_BlockingSMTP.instances) == 1, "the cooldown should suppress the second alert"


def test_failure_releases_the_slot_and_leaves_no_cooldown():
    _BlockingSMTP.fail = True
    _BlockingSMTP.release.set()
    server.send_alert("first", "body")
    assert _wait_for(lambda: len(_BlockingSMTP.instances) == 1 and not server._alert_in_flight)
    assert server._last_alert_time == 0
    server.send_alert("second", "body")
    assert _wait_for(lambda: len(_BlockingSMTP.instances) == 2)


def test_unconfigured_alerting_starts_nothing(monkeypatch):
    monkeypatch.setattr(server, "ALERT_ENABLED", False)
    server.send_alert("subject", "body")
    time.sleep(0.05)
    assert _BlockingSMTP.instances == []
    assert not _delivery_threads()


def test_health_keeps_answering_when_backups_are_stale(monkeypatch):
    """The event-loop caller from the incident, end to end.

    Stale backups make ``get_health`` call ``send_alert``.  While the SMTP
    connect hangs, a second coroutine on the same loop must keep ticking and
    the health response must still arrive promptly.
    """
    monkeypatch.setattr(
        server,
        "_backup_freshness",
        lambda: {
            "newestBackupAgeHours": None,
            "newestBackupPath": None,
            "backupDirUsed": "none",
            "dbCount": 0,
        },
    )

    async def scenario():
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        started = time.monotonic()
        response = await server.get_health()
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.1)
        stop.set()
        await task
        return response, elapsed, ticks

    response, elapsed, ticks = asyncio.run(scenario())
    assert response.status_code in (200, 503)
    assert elapsed < _PROMPT_SECONDS
    assert ticks >= 3, "the event loop stalled while the alert was being sent"
    assert _wait_for(lambda: len(_BlockingSMTP.instances) == 1), "the alert was not attempted"


def _smtp_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"SMTP", "SMTP_SSL"}
            and isinstance(func.value, ast.Name)
            and func.value.id == "smtplib"
        ):
            yield node


def test_every_smtp_connection_in_server_py_is_bounded():
    tree = ast.parse(_SERVER_PY.read_text(encoding="utf-8"))
    calls = list(_smtp_calls(tree))
    assert calls, "no smtplib connection found; this guard would pass vacuously"
    unbounded = [c.lineno for c in calls if not any(k.arg == "timeout" for k in c.keywords)]
    assert unbounded == [], f"smtplib connection without timeout= at server.py lines {unbounded}"
