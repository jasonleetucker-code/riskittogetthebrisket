"""Pin: the scraper's own ``run()`` must not freeze the server's event loop.

THE INCIDENT (2026-09-28, #1338)
--------------------------------
``Dynasty Scraper.py::run`` is ``async def``, but after its browser phase it
runs ~3,000 lines of synchronous merge/normalization with no ``await``
(``health_report`` -> ``build_payload``: ~68 s in production scrape telemetry).
``run_scraper`` awaited it directly on the server's single event-loop thread,
so every request -- ``/api/health`` included -- went unanswered for that span:
production probes timed out at 20 s and 40 s during scheduled and startup
scrapes.  Same defect class as the import phase pinned in
``test_run_scraper_nonblocking.py``, one phase later.

Pinned here: the run executes on its own loop in a worker thread; progress
still reaches ``scrape_status`` on the server loop, in order; the run timeout
still applies; cancelling the scrape cancels the scraper coroutine.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time

import server
from tests.api.test_run_scraper_nonblocking import (
    _RELEASE_DELAY_SECONDS,
    _isolate_scrape_state,  # noqa: F401 -- autouse fixture, re-used
    _tick_prober,
)

_RESULT = {
    "players": {"1": {"name": "Test Player"}},
    "sites": [],
    "coverageAudit": {},
    "date": "2026-01-01",
}


def _scraper(run):
    class _Scraper:
        SCRIPT_DIR = ""

    scraper = _Scraper()
    scraper.run = run
    return scraper


def test_a_synchronous_span_inside_run_does_not_freeze_the_loop(monkeypatch):
    release = threading.Event()

    async def run(progress_callback=None):
        # The production shape: an async function that stops awaiting and
        # grinds synchronously (here: blocked until an independent timer).
        release.wait(timeout=5)
        return dict(_RESULT)

    monkeypatch.setattr(server, "_import_scraper_module", lambda: _scraper(run))
    releaser = threading.Timer(_RELEASE_DELAY_SECONDS, release.set)
    releaser.start()
    try:

        async def scenario():
            scrape = asyncio.create_task(server.run_scraper(trigger="test"))
            prober_elapsed = await _tick_prober()
            return prober_elapsed, await scrape

        prober_elapsed, result = asyncio.run(scenario())
    finally:
        releaser.cancel()

    assert prober_elapsed < _RELEASE_DELAY_SECONDS * 0.7, (
        f"event loop prober took {prober_elapsed:.2f}s while scraper.run() ground "
        "synchronously -- the run is freezing the loop again"
    )
    assert result is not None and result["players"]


def test_progress_reaches_scrape_status_on_the_loop_thread_in_order(monkeypatch):
    applied: list[tuple[str, int]] = []
    real = server._update_scrape_progress

    def recording(**kwargs):
        applied.append((kwargs.get("source"), threading.get_ident()))
        return real(**kwargs)

    monkeypatch.setattr(server, "_update_scrape_progress", recording)

    async def run(progress_callback=None):
        worker = threading.get_ident()
        for i in range(25):
            progress_callback({"step": "scrape", "source": f"s{i}", "event": "phase_start"})
        return dict(_RESULT, _worker=worker)

    monkeypatch.setattr(server, "_import_scraper_module", lambda: _scraper(run))

    async def scenario():
        return threading.get_ident(), await server.run_scraper(trigger="test")

    loop_thread, result = asyncio.run(scenario())
    assert result["_worker"] != loop_thread, "scraper.run() executed on the loop thread"
    sources = [s for s, _ in applied]
    ours = [s for s in sources if s and s.startswith("s") and s[1:].isdigit()]
    assert ours == [f"s{i}" for i in range(25)]
    # Every one applied before the server's own next phase ("validate").
    assert sources.index("s24") < sources.index("result_payload")
    assert {t for _, t in applied} == {loop_thread}


def test_the_run_timeout_still_applies(monkeypatch):
    unwound = threading.Event()

    async def run(progress_callback=None):
        try:
            await asyncio.sleep(30)
        finally:
            unwound.set()

    monkeypatch.setattr(server, "_import_scraper_module", lambda: _scraper(run))
    monkeypatch.setattr(server, "SCRAPE_RUN_TIMEOUT_SECONDS", 0.2)
    failures = []
    monkeypatch.setattr(server, "_mark_scrape_failure", lambda e, elapsed: failures.append(e))
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)

    t0 = time.monotonic()
    result = asyncio.run(server.run_scraper(trigger="test"))
    assert result is None
    assert time.monotonic() - t0 < 10
    assert len(failures) == 1 and isinstance(failures[0], TimeoutError)
    assert unwound.is_set()


def _cancellable_scrape(monkeypatch):
    started = threading.Event()
    state = {"cancelled": False, "lock_held_while_unwinding": None}

    async def run(progress_callback=None):
        started.set()
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            state["cancelled"] = True  # Playwright's ``async with`` unwinds here
            time.sleep(0.3)  # unwinding takes a moment (closing the browser)
            state["lock_held_while_unwinding"] = server.scrape_run_lock.locked()
            raise

    monkeypatch.setattr(server, "_import_scraper_module", lambda: _scraper(run))
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    return started, state


def _scraper_threads_alive():
    return [t for t in threading.enumerate() if t.name == "scraper-run" and t.is_alive()]


def test_cancelling_the_scrape_cancels_the_scraper_coroutine(monkeypatch):
    started, state = _cancellable_scrape(monkeypatch)

    async def scenario():
        scrape = asyncio.create_task(server.run_scraper(trigger="test"))
        assert await asyncio.to_thread(started.wait, 5)
        scrape.cancel()
        try:
            await scrape
        except asyncio.CancelledError:
            return "cancelled"
        return "returned"

    t0 = time.monotonic()
    assert asyncio.run(scenario()) == "cancelled"
    assert state["cancelled"], "the scraper coroutine was never cancelled"
    assert time.monotonic() - t0 < 10
    assert not _scraper_threads_alive()
    # The scrape still owned the lock while it unwound; released after.
    assert state["lock_held_while_unwinding"] is True
    assert not server.scrape_run_lock.locked()


def test_a_second_cancel_during_shutdown_still_cancels_the_worker(monkeypatch):
    """Lifespan shutdown cancels the scrape task, then the server runner
    cancels every remaining task again: the second cancel must neither skip
    the worker cancel nor return before the worker has unwound."""
    started, state = _cancellable_scrape(monkeypatch)

    async def scenario():
        scrape = asyncio.create_task(server.run_scraper(trigger="test"))
        assert await asyncio.to_thread(started.wait, 5)
        scrape.cancel()
        await asyncio.sleep(0)
        scrape.cancel()
        await asyncio.sleep(0)
        scrape.cancel()
        try:
            await scrape
        except asyncio.CancelledError:
            return "cancelled"
        return "returned"

    t0 = time.monotonic()
    assert asyncio.run(scenario()) == "cancelled"
    assert state["cancelled"], "a repeated cancel skipped cancelling the worker"
    assert time.monotonic() - t0 < 10
    assert not _scraper_threads_alive()
    assert state["lock_held_while_unwinding"] is True


def test_a_worker_thread_loop_can_spawn_subprocesses():
    """Playwright's async API starts its driver with
    ``asyncio.create_subprocess_exec``; that must work on a loop owned by a
    non-main thread on the platforms this runs on."""

    async def spawn():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "print('ok')", stdout=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.strip()

    box = {}

    def worker():
        box["result"] = asyncio.run(spawn())

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=30)
    assert box.get("result") == (0, b"ok")
