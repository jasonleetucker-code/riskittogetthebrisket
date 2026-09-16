"""Pin: ``run_scraper``'s blocking segments must not freeze the event loop.

THE INCIDENT
------------
``run_scraper`` (server.py) is ``async def`` and mostly correct, but it used
to run several genuinely synchronous, unawaited blocks directly on the one
shared event-loop thread:

* ``spec.loader.exec_module(scraper)`` — executes Dynasty Scraper.py's whole
  module top level, which (via ``fetch_sleeper_rosters``) makes up to ~90
  sequential blocking ``requests.get`` calls;
* four ``scripts/fetch_*.py`` ``main()`` calls, each plain synchronous
  ``requests`` code.

Because uvicorn runs a single worker (no ``workers=`` arg), that meant every
other request — ``/api/health``, ``/api/status``, login — went unserved for
however long those calls took. Reproduced live 2026-09-16: a real login POST
timed out for 15s with zero response while a scrape was mid-import.

This file pins the fix (each of those calls now runs via
``run_in_threadpool``) with the same pattern ``test_startup_nonblocking.py``
already established for the very next line in this function
(``_prime_latest_payload``): block on a ``threading.Event``, prove the loop
kept servicing other coroutines while a worker thread was stuck.
"""

from __future__ import annotations

import asyncio
import importlib
import threading
import time

import pytest

import server


def _fake_scraper_module():
    """A stand-in for the imported Dynasty_Scraper module.

    Only needs the two things run_scraper touches on it: the ``SCRIPT_DIR``
    attribute assignment and an awaitable ``run(progress_callback=...)``.
    """

    class _FakeScraper:
        SCRIPT_DIR = ""

        async def run(self, progress_callback=None):
            return {
                "players": {"1": {"name": "Test Player"}},
                "sites": [],
                "coverageAudit": {},
                "date": "2026-01-01",
            }

    return _FakeScraper()


@pytest.fixture(autouse=True)
def _isolate_scrape_state(monkeypatch):
    """Every test gets a clean, hermetic run_scraper path.

    Fakes everything run_scraper touches EXCEPT the specific call under
    test in each test, so a slow/failing real network call can never make
    these tests flaky, and so ``_prime_latest_payload``'s own disk/overlay
    work never runs.
    """
    monkeypatch.setattr(server, "_import_scraper_module", _fake_scraper_module)
    monkeypatch.setattr(server, "_prime_latest_payload", lambda *a, **k: None)

    for mod_path in (
        "scripts.fetch_dynasty_nerds",
        "scripts.fetch_fantasypros_offense",
        "scripts.fetch_fantasypros_idp",
    ):
        mod = importlib.import_module(mod_path)
        monkeypatch.setattr(mod, "main", lambda argv=None: 0)

    yield


async def _tick_prober(n: int = 20, interval: float = 0.01) -> float:
    """Run ``n`` short sleeps back-to-back, return total elapsed time.

    A responsive event loop finishes this in roughly ``n * interval``. A
    loop stuck inside a blocking call on the SAME thread cannot service
    this coroutine at all until the blocking call returns — so a large
    elapsed time here is direct evidence the loop was frozen, not just
    that the awaited call was slow.
    """
    t0 = time.monotonic()
    for _ in range(n):
        await asyncio.sleep(interval)
    return time.monotonic() - t0


# How long the (correctly offloaded) blocking call is held before an
# INDEPENDENT background thread — not asyncio, not this test's own event
# loop — releases it.
#
# This independence is load-bearing, not incidental. An earlier version of
# these two tests synchronized via ``await asyncio.to_thread(started.wait,
# ...)`` before starting the prober. That is fatally circular when the call
# under test is NOT actually offloaded: if the freeze happens on the same
# thread as the loop, the result of ``to_thread(...)`` cannot be DELIVERED
# back to the waiting coroutine until the loop itself resumes — which only
# happens once the freeze already ends. So the prober only ever started
# measuring AFTER the freeze was already over, and silently reported a
# small, "healthy" elapsed time regardless of whether the call had been
# offloaded at all. Verified directly: reverting the fix and running the
# old version of this test suite left both responsiveness tests GREEN
# (each quietly eating ~10s of hanging_main's own internal timeout) while
# only the separate structural test below caught the regression.
#
# A plain ``threading.Timer`` fires from its own OS thread regardless of
# whether the asyncio loop is currently servicing anything, which is
# exactly the property needed to test a same-thread freeze without
# depending on the loop to detect it.
_RELEASE_DELAY_SECONDS = 0.5


def test_event_loop_stays_responsive_during_import(monkeypatch):
    """The core proof for the import step: a hung exec_module must not
    starve concurrent requests, because it now runs off the loop thread."""
    release = threading.Event()

    def hanging_import():
        release.wait(timeout=5)
        return _fake_scraper_module()

    monkeypatch.setattr(server, "_import_scraper_module", hanging_import)

    releaser = threading.Timer(_RELEASE_DELAY_SECONDS, release.set)
    releaser.start()
    try:

        async def scenario():
            scrape_task = asyncio.create_task(server.run_scraper(trigger="test"))
            # Driven directly alongside scrape_task — not gated on any
            # signal FROM it — so a same-thread freeze in scrape_task shows
            # up as this coroutine itself failing to make progress.
            prober_elapsed = await _tick_prober()
            result = await scrape_task
            return prober_elapsed, result

        prober_elapsed, result = asyncio.run(scenario())
    finally:
        releaser.cancel()

    # Correctly offloaded: the prober finishes on its own ~0.2s schedule,
    # independent of _RELEASE_DELAY_SECONDS, because the loop never waits
    # on the background thread to service unrelated coroutines. A
    # same-thread freeze instead gates the prober's own sleeps on the
    # release firing, pushing its elapsed time up to ~_RELEASE_DELAY_SECONDS.
    # The threshold sits well between the two.
    assert prober_elapsed < _RELEASE_DELAY_SECONDS * 0.7, (
        f"event loop prober took {prober_elapsed:.2f}s while a blocking import "
        "ran concurrently — the import is freezing the loop again"
    )
    assert result is not None
    assert result["players"]


@pytest.mark.parametrize(
    "fetch_module_path",
    [
        "scripts.fetch_dynasty_nerds",
        "scripts.fetch_fantasypros_offense",
        "scripts.fetch_fantasypros_idp",
    ],
)
def test_event_loop_stays_responsive_during_each_fetch_main(monkeypatch, fetch_module_path):
    """Same proof, once per offloaded .main() call site. See
    ``_RELEASE_DELAY_SECONDS`` for why the release is an independent
    background thread rather than an awaited signal."""
    release = threading.Event()

    def hanging_main(argv=None):
        release.wait(timeout=5)
        return 0

    mod = importlib.import_module(fetch_module_path)
    monkeypatch.setattr(mod, "main", hanging_main)

    releaser = threading.Timer(_RELEASE_DELAY_SECONDS, release.set)
    releaser.start()
    try:

        async def scenario():
            scrape_task = asyncio.create_task(server.run_scraper(trigger="test"))
            prober_elapsed = await _tick_prober()
            result = await scrape_task
            return prober_elapsed, result

        prober_elapsed, result = asyncio.run(scenario())
    finally:
        releaser.cancel()

    assert prober_elapsed < _RELEASE_DELAY_SECONDS * 0.7, (
        f"event loop prober took {prober_elapsed:.2f}s while {fetch_module_path}.main "
        "ran concurrently — this fetch call is freezing the loop again"
    )
    assert result is not None


def test_every_blocking_call_is_routed_through_run_in_threadpool(monkeypatch):
    """Structural guard.

    A future revert to a direct (unwrapped) call would not necessarily
    show up as a timing flake in CI — fast test machines, no real
    contention — so this asserts WHICH functions actually went through
    ``run_in_threadpool``, by recording every call it makes, rather than
    only timing the result.
    """
    recorded: list[object] = []
    real_run_in_threadpool = server.run_in_threadpool

    async def recording_run_in_threadpool(func, *args, **kwargs):
        recorded.append(func)
        return await real_run_in_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(server, "run_in_threadpool", recording_run_in_threadpool)

    result = asyncio.run(server.run_scraper(trigger="test"))

    assert result is not None
    dn_main = importlib.import_module("scripts.fetch_dynasty_nerds").main
    fpoff_main = importlib.import_module("scripts.fetch_fantasypros_offense").main
    fp_main = importlib.import_module("scripts.fetch_fantasypros_idp").main

    assert server._import_scraper_module in recorded
    assert dn_main in recorded
    assert fpoff_main in recorded
    assert fp_main in recorded


def test_second_concurrent_run_is_rejected_without_blocking_on_the_first(monkeypatch):
    """The asyncio.Lock still serializes scrapes; a run_in_threadpool
    worker cannot let a second scrape race past it."""
    release = threading.Event()
    started = threading.Event()

    def hanging_import():
        started.set()
        release.wait(timeout=10)
        return _fake_scraper_module()

    monkeypatch.setattr(server, "_import_scraper_module", hanging_import)

    async def scenario():
        pre_existing_data = server.latest_data
        first = asyncio.create_task(server.run_scraper(trigger="first"))
        reached = await asyncio.to_thread(started.wait, 5)
        assert reached, "first run never reached the blocking import"

        worker_before = server.scrape_status.get("worker_id")
        second_result = await server.run_scraper(trigger="second")

        release.set()
        first_result = await first
        return worker_before, second_result, pre_existing_data, first_result

    worker_before, second_result, pre_existing_data, first_result = asyncio.run(scenario())

    # The second call took the existing "already running" rejection path —
    # it returned whatever was already cached (never the first run's still
    # in-flight result), and the first run's worker id is untouched.
    assert second_result is pre_existing_data
    assert server.scrape_status.get("worker_id") == worker_before
    assert first_result is not None
