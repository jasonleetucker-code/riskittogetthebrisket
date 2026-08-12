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
import time
import unittest

from fastapi.testclient import TestClient

import server


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

        The pre-fix cost was 6.07 s per client, essentially all of it in
        ``__exit__``. The bound is deliberately loose — this is a
        regression tripwire for a seconds-scale wait, not a benchmark.
        """
        start = time.perf_counter()
        with TestClient(server.app):
            pass
        elapsed = time.perf_counter() - start
        self.assertLess(
            elapsed,
            3.0,
            f"a TestClient lifespan took {elapsed:.2f}s — the suite is waiting "
            "on something external again",
        )


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
