"""Post-publish warm of the heavy public sections (MD-114 / Part 9F).

The warm pass calls the SAME accessors the routes call, so the contract is:
the served bytes are identical with and without it, an entry filed for one
snapshot / board generation is never served for another, a failing warm never
raises into the scrape or refresh that scheduled it, and requests that arrive
during a warm compute or wait once.
"""

from __future__ import annotations

import copy
import os
import threading
import time
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False

from tests.public_league.fixtures import wait_for_public_memo_refreshes


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class PublicSectionsWarmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.public_league.fixtures import build_stub_client, install_stubs

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"
        from server import _public_league_cache, app

        _public_league_cache.clear()
        _public_league_cache.update(
            {"snapshot": None, "snapshot_league_id": None, "fetched_at": 0.0}
        )
        cls.client = TestClient(app)

    def setUp(self) -> None:
        import server
        from src.ros import playoff_sim

        wait_for_public_memo_refreshes(server)
        self.client.get("/api/public/league/history")  # warm the snapshot
        server._heavy_section_cache.clear()
        playoff_sim._LIVE_MEMO.clear()
        self.sim_calls = 0
        real = playoff_sim.simulate_playoff_odds

        def counting(snapshot, **kw):
            self.sim_calls += 1
            return real(snapshot, n_simulations=200, min_simulations=200, max_simulations=200)

        patches = [
            mock.patch.object(playoff_sim, "simulate_playoff_odds", counting),
            # No scheduled file: every request is a live run.
            mock.patch.object(playoff_sim, "_load_cached_payload", lambda *_a, **_k: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _get(self, section: str) -> bytes:
        r = self.client.get(f"/api/public/league/{section}")
        self.assertEqual(r.status_code, 200, section)
        return r.content

    # -- byte identity --------------------------------------------------
    def test_heavy_sections_are_byte_identical_with_and_without_warm(self) -> None:
        import server

        cold = {s: self._get(s) for s in ("awards", "archives")}
        server._heavy_section_cache.clear()
        warmed = server._warm_public_sections_once()
        self.assertIn("awards", warmed)
        self.assertIn("archives", warmed)
        with mock.patch.object(
            server, "build_section_payload", side_effect=AssertionError("rebuilt after warm")
        ):
            hot = {s: self._get(s) for s in ("awards", "archives")}
        self.assertEqual(hot, cold)

    def test_forecast_sections_byte_identical_and_served_without_a_live_run(self) -> None:
        import server
        from src.ros import playoff_sim

        # The real run is unseeded, so pin one payload for both paths: the
        # comparison is about the PATH (memo filled by the warm vs by the
        # request), not about Monte Carlo noise.
        snapshot = server._get_public_snapshot()
        fixed = playoff_sim.simulate_playoff_odds(snapshot)
        fixed["cached"] = False
        with mock.patch.object(
            playoff_sim, "simulate_playoff_odds", lambda *_a, **_k: copy.deepcopy(fixed)
        ):
            cold = {s: self._get(s) for s in ("playoffOdds", "rosPlayoffOdds")}
            playoff_sim._LIVE_MEMO.clear()
            server._warm_public_sections_once()
            self.assertTrue(playoff_sim._LIVE_MEMO, "warm must fill the live memo")
            with mock.patch.object(
                playoff_sim, "simulate_playoff_odds", side_effect=AssertionError("live run")
            ):
                hot = {s: self._get(s) for s in ("playoffOdds", "rosPlayoffOdds")}
        self.assertEqual(hot, cold)

    # -- staleness ------------------------------------------------------
    def test_entry_for_an_older_generation_is_not_an_exact_hit(self) -> None:
        import server

        server._warm_public_sections_once()
        snapshot = server._get_public_snapshot()
        self.assertIsNotNone(server._exact_memoized_awards_body(snapshot))
        with mock.patch.object(server, "latest_data_etag", "new-board-generation"):
            self.assertIsNone(server._exact_memoized_awards_body(snapshot))

    def test_live_memo_is_not_reused_for_a_new_snapshot_generation(self) -> None:
        import server
        from src.ros import playoff_sim

        snapshot = server._get_public_snapshot()
        playoff_sim.canonical_forecast(snapshot)
        self.assertEqual(self.sim_calls, 1)
        playoff_sim.canonical_forecast(snapshot)
        self.assertEqual(self.sim_calls, 1)
        newer = copy.copy(snapshot)
        newer.generated_at = "2999-01-01T00:00:00+00:00"
        playoff_sim.canonical_forecast(newer)
        self.assertEqual(self.sim_calls, 2)

    def test_stale_snapshot_is_not_warmed(self) -> None:
        import server

        with (
            mock.patch.dict(server._public_league_cache, {"fetched_at": 1.0}),
            mock.patch.object(server, "_kick_background_refresh"),
        ):
            self.assertEqual(server._warm_public_sections_once(), [])
        self.assertEqual(self.sim_calls, 0)

    # -- failure isolation ---------------------------------------------
    def test_a_failing_warm_never_raises_and_still_tries_every_step(self) -> None:
        import server
        from src.ros import playoff_sim

        with (
            mock.patch.object(server, "build_section_payload", side_effect=RuntimeError("boom")),
            mock.patch.object(
                playoff_sim, "canonical_forecast", side_effect=RuntimeError("sim")
            ) as forecast,
        ):
            self.assertEqual(server._warm_public_sections_once(), [])
        forecast.assert_called_once()

    def test_scheduling_never_raises_into_the_caller(self) -> None:
        import server

        with (
            mock.patch.object(server, "_PUBLIC_SECTIONS_WARM_ENABLED", True),
            mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no threads")),
        ):
            server._schedule_public_sections_warm("test")
        self.assertFalse(server._public_sections_warm_state["running"])
        server._public_sections_warm_state["pending"] = False

    def test_disabled_flag_schedules_nothing(self) -> None:
        import server

        with (
            mock.patch.object(server, "_PUBLIC_SECTIONS_WARM_ENABLED", False),
            mock.patch.object(threading, "Thread") as thread,
        ):
            server._schedule_public_sections_warm("test")
        thread.assert_not_called()

    def test_worker_survives_a_failing_pass_and_coalesces_requests(self) -> None:
        import server

        gate = threading.Event()
        passes: list[int] = []

        def slow_once() -> list[str]:
            passes.append(1)
            gate.wait(5)
            if len(passes) == 1:
                raise RuntimeError("first pass fails")
            return ["x"]

        with (
            mock.patch.object(server, "_PUBLIC_SECTIONS_WARM_ENABLED", True),
            mock.patch.object(server, "_warm_public_sections_once", slow_once),
        ):
            for _ in range(5):
                server._schedule_public_sections_warm("burst")
            deadline = time.time() + 5
            while not passes and time.time() < deadline:
                time.sleep(0.01)
            gate.set()
            deadline = time.time() + 5
            while server._public_sections_warm_state["running"] and time.time() < deadline:
                time.sleep(0.01)
        self.assertFalse(server._public_sections_warm_state["running"])
        # Five requests during one running pass collapse into one more pass.
        self.assertEqual(len(passes), 2)

    # -- concurrency ----------------------------------------------------
    def test_requests_during_a_warm_compute_the_forecast_once(self) -> None:
        import server
        from src.ros import playoff_sim

        snapshot = server._get_public_snapshot()
        entered = threading.Event()
        release = threading.Event()
        calls: list[int] = []
        real = playoff_sim.simulate_playoff_odds

        def slow(snap, **kw):
            calls.append(1)
            entered.set()
            release.wait(5)
            return real(snap, n_simulations=200, min_simulations=200, max_simulations=200)

        results: list[dict] = []
        with mock.patch.object(playoff_sim, "simulate_playoff_odds", slow):
            warm = threading.Thread(target=playoff_sim.canonical_forecast, args=(snapshot,))
            warm.start()
            self.assertTrue(entered.wait(5))
            req = [
                threading.Thread(
                    target=lambda: results.append(playoff_sim.canonical_forecast(snapshot))
                )
                for _ in range(2)
            ]
            for t in req:
                t.start()
            time.sleep(0.2)
            release.set()
            for t in [warm, *req]:
                t.join(10)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
