"""X-HEALTH (2026-11-20): reading /api/health or /api/status writes nothing.

Both used to call ``_scrape_status_payload``, which ran the orphan
reconciler and the once-only stall event: an anonymous GET flipped in-memory
scrape state and appended a durable telemetry line.  The view is now
read-only and ``scrape_status_watchdog_loop`` does the recording.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import server


class _HeldLock:
    def locked(self) -> bool:
        return True


class _FreeLock:
    def locked(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    before = copy.deepcopy(server.scrape_status)
    writes: list = []
    alerts: list = []
    monkeypatch.setattr(server._scrape_telemetry, "record", lambda *a, **k: writes.append((a, k)))
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: alerts.append(a))
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
    yield writes, alerts
    server.scrape_status.clear()
    server.scrape_status.update(before)


def _old(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _stalled_run(monkeypatch):
    """A run that holds the lock but has not heartbeat for > the threshold."""
    monkeypatch.setattr(server, "scrape_run_lock", _HeldLock())
    server.scrape_status.update(
        {
            "running": True,
            "stalled": False,
            "hung": False,
            "interrupted": False,
            "error": None,
            "last_heartbeat": _old(server.SCRAPE_STALL_SECONDS + 120),
            "current_step": "sources",
            "current_source": "ktc",
        }
    )


def _orphaned_run(monkeypatch):
    """running=True with nobody holding the lock: a worker that died."""
    monkeypatch.setattr(server, "scrape_run_lock", _FreeLock())
    server.scrape_status.update(
        {
            "running": True,
            "stalled": False,
            "hung": False,
            "interrupted": False,
            "interrupted_at": None,
            "error": None,
            "last_heartbeat": _old(30),
            "current_step": "sources",
            "current_source": "ktc",
        }
    )


@pytest.mark.parametrize("setup", [_stalled_run, _orphaned_run], ids=["stalled", "orphaned"])
@pytest.mark.parametrize("path", ["/api/health", "/api/status"])
def test_anonymous_reads_change_nothing(monkeypatch, _isolate, setup, path):
    writes, alerts = _isolate
    setup(monkeypatch)
    snapshot = copy.deepcopy(server.scrape_status)
    client = TestClient(server.app, raise_server_exceptions=False)
    for _ in range(2):
        resp = client.get(path)
        # /api/health answers 503 for a stalled scrape; that is its verdict.
        assert resp.status_code in (200, 503), resp.text[:300]
    assert server.scrape_status == snapshot
    assert writes == []
    assert alerts == []


def test_the_view_still_reports_the_truth(monkeypatch):
    _stalled_run(monkeypatch)
    view = server._scrape_status_payload()
    assert view["stalled"] is True and view["hung"] is True
    assert view["status_summary"] == "stalled"

    _orphaned_run(monkeypatch)
    view = server._scrape_status_payload()
    assert view["running"] is False and view["interrupted"] is True
    assert view["interrupted_at"] and view["status_summary"] == "interrupted"
    assert view["stalled"] is False
    # ...without recording it.
    assert server.scrape_status["running"] is True
    assert server.scrape_status["interrupted"] is False


def test_the_watchdog_tick_records_a_stall_once(monkeypatch, _isolate):
    writes, _ = _isolate
    _stalled_run(monkeypatch)
    server._reconcile_scrape_status()
    server._reconcile_scrape_status()
    events = [a[0] for a, _ in writes]
    assert events == ["scrape_stalled_detected"]
    assert server.scrape_status["stalled"] is True


def test_the_watchdog_tick_resets_an_orphan(monkeypatch, _isolate):
    writes, _ = _isolate
    _orphaned_run(monkeypatch)
    server._reconcile_scrape_status()
    assert [a[0] for a, _ in writes] == ["orphaned_running_reset"]
    assert server.scrape_status["running"] is False
    assert server.scrape_status["interrupted"] is True


def test_the_watchdog_loop_ticks_and_survives_errors(monkeypatch):
    calls = []

    def _tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) >= 3:
            raise asyncio.CancelledError

    real_sleep = asyncio.sleep
    monkeypatch.setattr(server, "_reconcile_scrape_status", _tick)
    monkeypatch.setattr(server.asyncio, "sleep", lambda s: real_sleep(0))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server.scrape_status_watchdog_loop())
    assert len(calls) == 3


def test_lifespan_starts_and_cancels_the_watchdog():
    src = (server.BASE_DIR / "server.py").read_text(encoding="utf-8")
    assert "asyncio.create_task(scrape_status_watchdog_loop())" in src
    assert "scrape_status_watch_task.cancel()" in src
