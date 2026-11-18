"""The backup watchdog's first check waits after startup (audit Task 13).

Moving the stale-backup e-mail off anonymous ``GET /api/health`` onto
``backup_watchdog_loop`` made every app start check at once, so any short-lived
app — every ``TestClient`` lifespan in the suite — e-mailed "backups stale"
(``tests/api/test_operator_admin_gate.py`` counted an extra send).  The first
tick now waits ``BACKUP_WATCHDOG_FIRST_DELAY_SEC`` (default 900 s).
"""

from __future__ import annotations

import asyncio

import server


def _run_loop_for(seconds: float, monkeypatch, delay: int) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(server, "BACKUP_WATCHDOG_FIRST_DELAY_SEC", delay)
    monkeypatch.setattr(server, "_alert_if_backups_stale", lambda: calls.append(1) or True)

    async def scenario() -> None:
        task = asyncio.create_task(server.backup_watchdog_loop())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    return calls


def test_default_delay_is_minutes_not_zero() -> None:
    assert server.BACKUP_WATCHDOG_FIRST_DELAY_SEC >= 60


def test_a_short_lived_app_never_checks(monkeypatch) -> None:
    assert _run_loop_for(0.2, monkeypatch, delay=900) == []


def test_zero_delay_checks_immediately(monkeypatch) -> None:
    assert _run_loop_for(0.2, monkeypatch, delay=0) == [1]
