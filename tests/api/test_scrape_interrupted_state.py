"""T4-4: an orphaned scrape must not report as a healthy idle server.

`_reconcile_orphaned_running_state` fires when status says a scrape is
running but the run lock is free — a worker that died without cleaning
up. It set `hung=True` and `stalled=True` to record that.

Both were DEAD ASSIGNMENTS. `_scrape_status_payload` calls the
reconciler and then immediately evaluates `_is_scrape_stalled()`, which
returns False the moment `running` is False, and its else branch resets
`hung` and `stalled` three lines later. So the verdict was overwritten
before the payload was built.

Observed before the fix, on a simulated dead worker:

    running=False  hung=False  stalled=False
    status_summary='idle'  error=None

Indistinguishable from a healthy server that had not scraped recently.
`/api/health`'s `scrape_stalled` stayed false too, so `StaleDataBanner`
never fired and nobody was told.

`interrupted` is a verdict on the LAST RUN rather than on the current
moment, which is why nothing downstream recomputes it away.
"""

from __future__ import annotations

import asyncio

import pytest

import server


@pytest.fixture(autouse=True)
def _restore_status():
    before = dict(server.scrape_status)
    yield
    server.scrape_status.clear()
    server.scrape_status.update(before)


def _simulate_dead_worker():
    """running=True with the lock free: a worker that exited mid-run."""
    assert not server.scrape_run_lock.locked(), "precondition: lock must be free"
    server.scrape_status.update(
        {
            "running": True,
            "hung": False,
            "stalled": False,
            "interrupted": False,
            "interrupted_at": None,
            "started_at": server._utc_now_iso(),
            "finished_at": None,
            "last_heartbeat": server._utc_now_iso(),
            "current_step": "sources",
            "current_source": "ktc",
            "worker_id": "run-deadbeef",
            "error": None,
        }
    )


def test_an_orphaned_worker_does_not_report_idle():
    """The headline assertion. 'idle' told the operator nothing was
    wrong while the last run was lying dead."""
    _simulate_dead_worker()
    payload = server._scrape_status_payload()
    assert payload["status_summary"] == "interrupted"
    assert payload["running"] is False
    assert payload["interrupted"] is True
    assert payload["interrupted_at"]


def test_the_verdict_survives_repeated_status_reads():
    """The original bug was a value being recomputed away between the
    write and the read, so reading twice has to be stable."""
    _simulate_dead_worker()
    server._scrape_status_payload()
    again = server._scrape_status_payload()
    assert again["status_summary"] == "interrupted"
    assert again["interrupted"] is True


def test_a_new_run_clears_the_previous_verdict():
    """`interrupted` describes the last run. A run that is underway
    supersedes it — otherwise the flag would be permanent and would stop
    being read, which is the un-clearable-alarm failure §6.15 names.

    The lock is an asyncio.Lock and must genuinely be held: without it
    the reconciler treats the new run as orphaned too.
    """

    async def _run():
        server.scrape_status.update({"interrupted": True, "interrupted_at": "x"})
        async with server.scrape_run_lock:
            server._start_scrape_run("test")
            return server._scrape_status_payload()

    payload = asyncio.run(_run())
    assert payload["running"] is True
    assert payload["interrupted"] is False
    assert payload["status_summary"] == "running"


def test_a_healthy_idle_server_still_reads_idle():
    """The control. Without it this suite would pass against a server
    that reported 'interrupted' unconditionally."""
    server.scrape_status.update(
        {"running": False, "interrupted": False, "stalled": False, "error": None}
    )
    assert server._scrape_status_payload()["status_summary"] == "idle"


def test_a_failed_run_still_reads_failed():
    """`error` outranks `interrupted`: a run that failed with a reason
    is more informative than one that merely vanished."""
    server.scrape_status.update(
        {"running": False, "interrupted": True, "stalled": False, "error": "boom"}
    )
    assert server._scrape_status_payload()["status_summary"] == "failed"


def test_health_exposes_the_interrupted_state_separately_from_stalled():
    """`StaleDataBanner` gates on `/api/health`. `scrape_stalled` means
    running-but-stuck and stays false here, so a separate field is what
    lets the banner fire at all."""
    _simulate_dead_worker()
    payload = server._scrape_status_payload()
    assert payload["stalled"] is False
    assert payload["interrupted"] is True
