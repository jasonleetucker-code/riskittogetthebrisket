"""A flapping uptime check must not storm the owner's phone (2026-11-20 review).

THE DEFECT
----------
``send_alert`` exempted ``uptime_recovery`` from the cooldown AND, once a
recovery was delivered, cleared the uptime class's cooldown.  The watchdog
sends a failure on every check at or above the threshold and a recovery on
every down -> OK transition, so a check that flaps around its threshold
(fail, fail, ok, ...) pushed a failure + recovery pair every cycle.  Measured
with the REAL ``uptime_watchdog_loop`` on a fake clock: 8 pushes per hour at
the default 300 s interval, 80 per hour at the 30 s floor.

Pinned here, on the same real loop: at most one failure alert per class per
cooldown window; every ANNOUNCED outage gets exactly one recovery; an outage
the owner was never told about gets none.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

import server
from src.utils import owner_alerts, owner_notify

PUSH = "https://ntfy.sh/private-topic-for-tests"
T0 = 1_800_000_000.0
FAIL = (False, "connection refused", None)
OK = (True, None, 200)


class _Stop(Exception):
    pass


class _FakeTime:
    """``server.time`` with a controllable ``time()`` (everything else real)."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


def _settle() -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        threads = [t for t in threading.enumerate() if t.name == "alert-smtp"]
        if not threads:
            return
        for t in threads:
            t.join(timeout=5)


def _run_watchdog(monkeypatch, pattern, *, interval: int, hours: float):
    """Drive the real loop over ``hours`` of fake time with the check results
    cycling through ``pattern``; return ``[(seconds since start, title)]``."""
    clock = _FakeTime(T0)
    end = T0 + hours * 3600

    class _FakeAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(seconds):
            _settle()  # every alert of this check is delivered before time moves
            clock.now += seconds
            if clock.now >= end:
                raise _Stop

    results = iter(pattern * int(hours * 3600 // max(30, interval) + len(pattern)))
    pushed: list[tuple[float, str]] = []

    def fake_send(title, body, **_k):
        pushed.append((clock.now - T0, title))
        return True

    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    monkeypatch.setattr(owner_notify, "send", fake_send)
    monkeypatch.setattr(server, "time", clock)
    monkeypatch.setattr(server, "asyncio", _FakeAsyncio())
    monkeypatch.setattr(server, "check_uptime_once", lambda: next(results))
    monkeypatch.setattr(server, "UPTIME_CHECK_ENABLED", True)
    monkeypatch.setattr(server, "UPTIME_CHECK_URL", "http://127.0.0.1:8000/api/health")
    monkeypatch.setattr(server, "UPTIME_CHECK_INTERVAL_SEC", interval)
    monkeypatch.setattr(server, "UPTIME_ALERT_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(server, "uptime_status", dict(server.uptime_status, consecutive_failures=0))
    with pytest.raises(_Stop):
        asyncio.run(server.uptime_watchdog_loop())
    return pushed


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(server, "_last_alert_time_by_key", {})
    monkeypatch.setattr(server, "_alerts_in_flight", set())
    monkeypatch.setattr(server, "_alert_unconfigured_logged_at", {})
    monkeypatch.setattr(server, "_alert_incident_open", set())
    monkeypatch.setattr(server, "_alert_recovery_deferred", {})
    for name in ("ALERT_ENABLED", "ALERT_FROM", "ALERT_PASSWORD", "ALERT_TO"):
        monkeypatch.setattr(server, name, "" if name != "ALERT_ENABLED" else False)
    owner_alerts.reset_delivery_health_for_tests()
    yield
    _settle()


def _per_hour(pushed, hours):
    buckets = []
    for h in range(int(hours)):
        titles = [t for s, t in pushed if h * 3600 <= s < (h + 1) * 3600]
        buckets.append(
            (
                sum("check failing" in t for t in titles),
                sum(t.endswith("Uptime recovered") for t in titles),
            )
        )
    return buckets


@pytest.mark.parametrize("interval", [300, 30])
def test_a_flapping_check_is_one_failure_and_one_recovery_per_window(monkeypatch, interval):
    hours = 4
    pushed = _run_watchdog(monkeypatch, [FAIL, FAIL, OK], interval=interval, hours=hours)
    per_hour = _per_hour(pushed, hours)
    # The defect sent 4+4 per hour at 300 s and 40+40 at 30 s.
    assert per_hour == [(1, 1)] * hours, per_hour
    # Each announced outage is followed by exactly one recovery, in order.
    kinds = ["fail" if "check failing" in t else "recovered" for _s, t in pushed]
    assert kinds == ["fail", "recovered"] * hours


def test_one_outage_is_one_failure_and_one_recovery(monkeypatch):
    pattern = [OK] + [FAIL] * 6 + [OK] * 5
    pushed = _run_watchdog(monkeypatch, pattern, interval=300, hours=len(pattern) * 300 / 3600)
    titles = [t for _s, t in pushed]
    assert titles == [
        "[Dynasty Server] Uptime check failing (2 consecutive)",
        "[Dynasty Server] Uptime recovered",
    ]


def test_a_long_outage_is_reannounced_hourly_and_recovered_once(monkeypatch):
    pattern = [FAIL] * 30 + [OK] * 6  # 2.5 h down at 300 s
    pushed = _run_watchdog(monkeypatch, pattern, interval=300, hours=3)
    titles = [t for _s, t in pushed]
    assert sum("check failing" in t for t in titles) == 3  # t=5 min, 65 min, 125 min
    assert sum(t.endswith("Uptime recovered") for t in titles) == 1
    assert titles[-1].endswith("Uptime recovered")
