"""The hard unit suite must not depend on the live site being up.

Measured incident, 2026-08-12: production's ``/api/`` stopped responding
(nginx and the Next frontend stayed healthy; the FastAPI upstream
accepted connections and never answered). Within roughly half an hour
``PR Validation`` stopped fitting in its 20-minute job budget and was
killed three times in a row, and the local suite went from ~13 minutes to
~37. The cause was not any product change — the previously-green commit
timed out identically when re-run.

The mechanism is this file's subject. ``server`` reads
``UPTIME_CHECK_ENABLED`` at import (default **True**) and the lifespan
starts ``uptime_watchdog_loop``, which runs a blocking
``check_uptime_once`` on a worker thread via ``asyncio.to_thread``.
Every ``TestClient`` therefore fired a real request at
``https://chaseupside.com/api/health`` and, because the loop's shutdown
joins that thread, every ``TestClient.__exit__`` waited on it. Profiled:
6.07 s per client, of which startup was 0.009 s. Disabling the watchdog
took the same two tests from 12.59 s to 1.94 s.

So a production outage could not fail CI honestly — it made CI time out,
which reads like a broken pull request.

The rule these tests pin:

* a **pure unit test** makes no external uptime request at all;
* the watchdog itself stays testable — a test that wants it enables it
  explicitly and controls its network dependency;
* production runtime is untouched: the watchdog remains enabled by
  default outside the test environment.

Deliberately NOT solved by sniffing for pytest inside ``server``.
Production code should not behave differently because it suspects it is
being tested; the boundary is an explicit environment default set by the
test bootstrap, and stated again in the CI workflow so the policy is
visible rather than inherited by accident.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import unittest

from fastapi.testclient import TestClient

import server

#: Separates a lifespan that FINISHED from one blocked on a hung network
#: call, which never finishes.  It is not a performance bound: a healthy
#: lifespan takes ~2-7 s depending on load, so this is loose by an order of
#: magnitude and still cannot pass a real wait, which is unbounded here.
_LIFESPAN_DEADLINE_S = 90.0


class TestThePureUnitSuiteIsSelfContained(unittest.TestCase):
    """What the suite must guarantee."""

    def test_the_watchdog_is_disabled_for_unit_tests(self):
        self.assertFalse(
            server.UPTIME_CHECK_ENABLED,
            "the unit suite starts the production uptime watchdog, so every "
            "TestClient waits on the live site",
        )

    def test_the_test_environment_sets_it_explicitly(self):
        """An explicit boundary, not an accident of the ambient env."""
        self.assertEqual(os.environ.get("UPTIME_CHECK_ENABLED"), "0")

    def test_no_uptime_probe_happens_during_a_client_lifespan(self):
        """The behavioural assertion, not just the config one."""
        calls: list[float] = []
        original = server.check_uptime_once

        def _record():
            calls.append(time.time())
            return (True, None, 200)

        server.check_uptime_once = _record
        self.addCleanup(setattr, server, "check_uptime_once", original)

        with TestClient(server.app):
            pass

        self.assertEqual(
            calls,
            [],
            "a unit-test client probed the configured uptime URL " f"({server.UPTIME_CHECK_URL!r})",
        )

    def test_a_client_lifespan_is_not_paying_a_network_wait(self):
        """Guards the symptom directly, in case the mechanism moves.

        Reproduces the 2026-08-12 incident instead of timing a healthy
        run: for the length of one client lifespan, EVERY outbound network
        attempt in the process (name resolution or connect, on any thread)
        hangs exactly like the upstream that accepted connections and never
        answered.  A lifespan that waits on any network call — at startup,
        or by joining a worker at shutdown, as the uptime watchdog did —
        then never finishes; one that does not wait finishes as fast as it
        always does.  Fire-and-forget daemon work (the post-prime overlay
        warm) is allowed to block, because nothing in the lifespan waits on
        it; it is released when the test ends.

        Replaced a ``elapsed < 4.0`` wall-clock bound on the whole
        lifespan.  That bound mostly measured the board prime, so it failed
        under parallel load (6.47 s with pytest-xdist ``-n 6``, no network
        involved) while a real network wait of under 4 s would have passed
        it.  The only clock left is ``_LIFESPAN_DEADLINE_S``, which
        separates "finished" from "blocked forever", not fast from slow.
        """
        release = threading.Event()
        attempts: list[str] = []
        attempts_lock = threading.Lock()

        def _hang(kind: str, target) -> None:
            with attempts_lock:
                attempts.append(f"{kind} {target!r} on thread {threading.current_thread().name!r}")
            release.wait()
            raise OSError(f"network blocked by {self.id()}")

        def _connect(sock, address):
            _hang("connect", address)

        def _connect_ex(sock, address):
            _hang("connect_ex", address)

        def _getaddrinfo(host, *args, **kwargs):
            _hang("getaddrinfo", host)

        for owner, name, replacement in (
            (socket.socket, "connect", _connect),
            (socket.socket, "connect_ex", _connect_ex),
            (socket, "getaddrinfo", _getaddrinfo),
        ):
            self.addCleanup(setattr, owner, name, getattr(owner, name))
            setattr(owner, name, replacement)
        # Registered last, so it runs FIRST: release every blocked thread
        # before the real socket functions are restored.
        self.addCleanup(release.set)

        outcome: dict[str, BaseException | None] = {}

        def _lifespan() -> None:
            try:
                with TestClient(server.app):
                    pass
                outcome["error"] = None
            except BaseException as exc:  # noqa: BLE001 — reported below
                outcome["error"] = exc

        runner = threading.Thread(target=_lifespan, name="lifespan-under-hung-network", daemon=True)
        runner.start()
        runner.join(_LIFESPAN_DEADLINE_S)

        with attempts_lock:
            seen = list(attempts)
        self.assertFalse(
            runner.is_alive(),
            "a TestClient lifespan is waiting on the network: with every outbound "
            f"network call hung, it did not finish within {_LIFESPAN_DEADLINE_S:.0f}s. "
            f"Network attempts made meanwhile: {seen}",
        )
        self.assertIsNone(outcome.get("error"), "the lifespan raised while the network was hung")


class TestNoLifespanStartsARealScrape(unittest.TestCase):
    """The lifespan's startup scrape must not run inside the unit suite.

    ``run_scraper`` imports ``Dynasty Scraper.py``, whose top level fetches
    the live Sleeper league and rewrites tracked ``data/`` artifacts.  The
    lifespan schedules it 3 s after boot, so a client held open that long —
    routine under parallel load — scraped for real (measured under
    ``pytest -n 6``, 2026-10-18).
    """

    _HOLD_S = 3.5  # past the lifespan's 3 s startup-scrape delay

    def _hold_client_and_record_scrapes(self) -> list[str]:
        calls: list[str] = []
        original = server.run_scraper

        async def _record(trigger: str = "manual"):
            calls.append(trigger)
            return None

        server.run_scraper = _record
        self.addCleanup(setattr, server, "run_scraper", original)
        with TestClient(server.app):
            time.sleep(self._HOLD_S)
        return calls

    def test_the_scheduler_is_disabled_for_unit_tests(self):
        self.assertFalse(server.SCRAPE_SCHEDULER_ENABLED)
        self.assertEqual(os.environ.get("SCRAPE_SCHEDULER_ENABLED"), "0")

    def test_a_long_lived_client_does_not_start_a_scrape(self):
        self.assertEqual(self._hold_client_and_record_scrapes(), [])

    def test_enabling_it_explicitly_still_starts_the_startup_scrape(self):
        """Disabling it by default must not make it unverifiable."""
        original = server.SCRAPE_SCHEDULER_ENABLED
        server.SCRAPE_SCHEDULER_ENABLED = True
        self.addCleanup(setattr, server, "SCRAPE_SCHEDULER_ENABLED", original)
        self.assertEqual(self._hold_client_and_record_scrapes(), ["startup"])


class TestNoSleeperOverlayWarmFromALifespan(unittest.TestCase):
    """The lifespan's overlay warm pass must not reach Sleeper in the suite.

    ``lifespan`` primes the cached contract at boot, and
    ``_prime_latest_payload`` hands it to ``_warm_overlays_in_background``,
    which starts the ``sleeper-overlay-warm`` daemon thread.  For every
    active league it refreshes the scoring and draft-class snapshots and
    force-refreshes the Sleeper overlay, and then, whatever the registry
    says, it warms the global trending-adds feed
    (``https://api.sleeper.app/v1/players/nfl/trending/add``).  Every
    ``TestClient`` therefore made a real Sleeper request on a thread the
    lifespan never joins (closed 2026-10-18, the same way #1792 closed the
    startup scrape).
    """

    _HOLD_S = 5.0  # upper bound; the enabled control returns as soon as it sees Sleeper

    def _hold_client_and_record_sleeper_hosts(self) -> tuple[list[str], list[str]]:
        """Hold a client open and record every outbound Sleeper request.

        Recorded at the three layers the warm pass can use: ``requests``
        (the trending adapter), ``urllib`` (the overlay) and the resolver
        (anything connecting directly).  The HTTP layers are needed as well
        as the resolver because behind an HTTPS proxy the resolver only
        ever sees the proxy host.  Every layer refuses, so nothing leaves
        the machine either way.
        """
        import urllib.request  # noqa: PLC0415

        import requests.adapters  # noqa: PLC0415

        hosts: list[str] = []
        threads: list[str] = []
        original_getaddrinfo = socket.getaddrinfo
        original_send = requests.adapters.HTTPAdapter.send
        original_open = urllib.request.OpenerDirector.open
        original_start = threading.Thread.start

        def _refuse_if_sleeper(target) -> None:
            text = str(target or "")
            if "sleeper" in text:
                hosts.append(text)
                raise OSError("network disabled by test")

        def _getaddrinfo(host, *args, **kwargs):
            _refuse_if_sleeper(host)
            return original_getaddrinfo(host, *args, **kwargs)

        def _send(adapter, request, *args, **kwargs):
            _refuse_if_sleeper(getattr(request, "url", ""))
            return original_send(adapter, request, *args, **kwargs)

        def _open(opener, fullurl, *args, **kwargs):
            _refuse_if_sleeper(getattr(fullurl, "full_url", fullurl))
            return original_open(opener, fullurl, *args, **kwargs)

        def _start(thread, *args, **kwargs):
            threads.append(thread.name)
            return original_start(thread, *args, **kwargs)

        patches = (
            (socket, "getaddrinfo", original_getaddrinfo, _getaddrinfo),
            (requests.adapters.HTTPAdapter, "send", original_send, _send),
            (urllib.request.OpenerDirector, "open", original_open, _open),
            (threading.Thread, "start", original_start, _start),
        )
        for owner, name, original, replacement in patches:
            setattr(owner, name, replacement)
            self.addCleanup(setattr, owner, name, original)
        try:
            with TestClient(server.app):
                deadline = time.time() + self._HOLD_S
                while not hosts and time.time() < deadline:
                    time.sleep(0.05)
        finally:
            for owner, name, original, _replacement in patches:
                setattr(owner, name, original)
        return hosts, threads

    def test_the_warm_pass_is_disabled_for_unit_tests(self):
        self.assertFalse(server.SLEEPER_OVERLAY_WARM_ENABLED)
        self.assertEqual(os.environ.get("SLEEPER_OVERLAY_WARM_ENABLED"), "0")

    def test_a_held_open_client_makes_no_sleeper_call(self):
        hosts, threads = self._hold_client_and_record_sleeper_hosts()
        self.assertEqual(hosts, [], "a TestClient lifespan resolved a Sleeper host")
        self.assertNotIn("sleeper-overlay-warm", threads)

    def test_enabling_it_explicitly_still_runs_the_warm_pass(self):
        """Disabling it by default must not make it unverifiable.

        Positive control: with the flag on, the same held-open client does
        start the warm thread and does try to resolve Sleeper (the resolver
        stub refuses, so nothing leaves the machine).  Without this, the
        test above could pass because the warm pass was never reachable.
        """
        original = server.SLEEPER_OVERLAY_WARM_ENABLED
        server.SLEEPER_OVERLAY_WARM_ENABLED = True
        self.addCleanup(setattr, server, "SLEEPER_OVERLAY_WARM_ENABLED", original)
        hosts, threads = self._hold_client_and_record_sleeper_hosts()
        self.assertIn("sleeper-overlay-warm", threads)
        self.assertTrue(hosts, "the enabled warm pass never reached for Sleeper")


class TestTheWatchdogItselfRemainsTestable(unittest.TestCase):
    """Disabling it by default must not make it unverifiable.

    A test that wants the watchdog turns it on explicitly and supplies
    its own probe — no live host involved either way.
    """

    def test_enabling_it_explicitly_runs_the_probe(self):
        calls: list[int] = []
        original_flag = server.UPTIME_CHECK_ENABLED
        original_probe = server.check_uptime_once
        original_interval = server.UPTIME_CHECK_INTERVAL_SEC

        def _probe():
            calls.append(1)
            return (True, None, 200)

        server.UPTIME_CHECK_ENABLED = True
        server.check_uptime_once = _probe
        # Keep the loop from sleeping for its production interval while
        # the client is open.
        server.UPTIME_CHECK_INTERVAL_SEC = 3600
        self.addCleanup(setattr, server, "UPTIME_CHECK_INTERVAL_SEC", original_interval)
        self.addCleanup(setattr, server, "check_uptime_once", original_probe)
        self.addCleanup(setattr, server, "UPTIME_CHECK_ENABLED", original_flag)

        with TestClient(server.app):
            deadline = time.time() + 5.0
            while not calls and time.time() < deadline:
                time.sleep(0.05)

        self.assertTrue(
            calls,
            "the watchdog did not run its probe even when explicitly enabled — "
            "disabling it by default has made the feature untestable",
        )

    def test_the_probe_target_is_still_configured_for_production(self):
        """The default is not removed, only switched off under test."""
        self.assertTrue(server.UPTIME_CHECK_URL)


if __name__ == "__main__":
    unittest.main()
