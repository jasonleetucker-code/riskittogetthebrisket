"""Stale-while-revalidate for the public-league response memos.

Production baseline 2026-11-06 (public curl, n=5): ``/api/public/league/overview``
p50 0.45 s, one sample 89.8 s, an earlier probe timed out at 60 s.  The
snapshot cache already served stale-while-revalidate, but the per-generation
response memos built from it (overview, activity, full-contract bytes, heavy
sections) rebuilt INLINE whenever their generation key moved (every
private-board publish) or their entry aged past two snapshot windows -- so an
unlucky visitor waited for a full public-contract build.

Pinned here, with builders that cannot finish until the test opens a gate
(a request that waited on a build would deadlock until the gate's timeout,
then fail -- so "served at once" is proved by construction, not by a timing
threshold):

    1. An expired / superseded entry is served at once with its old bytes and
       exactly ONE background refresh runs, off the request path, for every
       memo: overview, full contract, activity, heavy section.
    2. Concurrent cold misses build once -- the full-contract route included
       (it had no single-flight), and across the overview + full-contract
       routes, which share one build.
    3. A failing refresh keeps serving the last good entry, files no error as
       data, and is paced by the failure cooldown rather than by requests.
    4. League isolation: another league's entry is never served, stale or not.
    5. A hung refresh stops suppressing a replacement after the timeout, and
       its late result cannot displace the newer build.
    6. The activity job defers to a running generation job, which seeds it.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest

from tests.public_league.fixtures import (
    reset_public_memo_refresh_state,
    wait_for_public_memo_refreshes,
)

try:
    import httpx
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False

#: How long a gated builder waits for its gate before failing.  Far longer
#: than any request in these tests may take -- a request that blocks on a
#: gated build therefore fails loudly instead of passing slowly.
GATE_TIMEOUT_SECONDS = 10.0


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class PublicMemoStaleWhileRevalidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.public_league.fixtures import build_stub_client, install_stubs

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"

        import server

        cls.server = server
        server._public_league_cache.clear()
        server._public_league_cache.update(
            {"snapshot": None, "snapshot_league_id": None, "fetched_at": 0.0}
        )
        cls.client = TestClient(server.app)

    def setUp(self) -> None:
        from src.api import rate_limit

        server = self.server
        rate_limit.reset_for_tests()
        self.addCleanup(rate_limit.reset_for_tests)
        self._wait_for_snapshot_refresh()
        if server._public_league_cache.get("snapshot") is None:
            server._get_public_snapshot()
        # Pin a fresh snapshot: no snapshot rebuild (which seeds these memos
        # with the REAL builder) may start mid-test.
        server._public_league_cache["fetched_at"] = time.time()
        self._wait_for_snapshot_refresh()
        reset_public_memo_refresh_state(server)
        with server._PUBLIC_CONTRACT_BYTES_LOCK:
            server._PUBLIC_CONTRACT_BYTES_CACHE.clear()
        server._PUBLIC_OVERVIEW_CACHE.clear()
        with server._PUBLIC_ACTIVITY_LOCK:
            server._PUBLIC_ACTIVITY_CACHE.clear()
        server._heavy_section_cache.clear()
        server._public_overview_async_lock = None
        server._public_activity_async_lock = None
        server._heavy_section_async_locks.clear()
        self._etag = server.latest_data_etag
        self._real = {
            name: getattr(server, name)
            for name in (
                "build_public_contract",
                "build_activity_serving_payload",
                "build_section_payload",
            )
        }
        self._gates: list[threading.Event] = []

    def tearDown(self) -> None:
        server = self.server
        for gate in self._gates:
            gate.set()
        wait_for_public_memo_refreshes(server)
        for name, fn in self._real.items():
            setattr(server, name, fn)
        server.latest_data_etag = self._etag
        reset_public_memo_refresh_state(server)

    # ── helpers ──────────────────────────────────────────────────────
    def _wait_for_snapshot_refresh(self) -> None:
        deadline = time.monotonic() + 30
        while self.server._public_league_cache.get("refreshing") and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.server._public_league_cache.get("refreshing"))

    def _gate(self, name: str, *, only_section: str | None = None):
        """Replace ``server.<name>`` with a builder that records the calling
        thread and cannot finish until the returned gate is set."""
        real = self._real[name]
        gate = threading.Event()
        self._gates.append(gate)
        calls: list[str] = []

        def gated(*args, **kwargs):
            section = args[1] if len(args) > 1 else kwargs.get("section")
            if only_section is not None and section != only_section:
                return real(*args, **kwargs)
            calls.append(threading.current_thread().name)
            if not gate.wait(GATE_TIMEOUT_SECONDS):
                raise RuntimeError("gate never opened")
            return real(*args, **kwargs)

        setattr(self.server, name, gated)
        return gate, calls

    def _concurrent_get(self, paths):
        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.server.app), base_url="http://fixture"
            ) as client:
                return await asyncio.gather(*[client.get(path) for path in paths])

        started = time.monotonic()
        results = asyncio.run(run())
        return results, time.monotonic() - started

    def _metric(self, name: str) -> int:
        return int(self.server._public_league_metrics.get(name, 0))

    def _assert_stale_served_and_refreshed_once(self, path, builder, job, *, only_section=None):
        server = self.server
        warm = self.client.get(path)
        self.assertEqual(warm.status_code, 200, warm.text[:300])
        before = {k: self._metric(k) for k in ("memo_stale_served", "memo_refresh_started")}
        server.latest_data_etag = f"swr-{job}-new-generation"
        gate, calls = self._gate(builder, only_section=only_section)

        results, elapsed = self._concurrent_get([path] * 8)

        # Every caller answered while the refresh was still gated shut.
        self.assertEqual([r.status_code for r in results], [200] * 8)
        self.assertEqual({r.content for r in results}, {warm.content})
        self.assertLess(elapsed, GATE_TIMEOUT_SECONDS / 2)
        # Exactly one refresh, on a background memo thread.
        self.assertEqual(calls, [f"public-league-memo-{job}"])
        self.assertEqual(self._metric("memo_stale_served") - before["memo_stale_served"], 8)
        self.assertEqual(self._metric("memo_refresh_started") - before["memo_refresh_started"], 1)

        gate.set()
        wait_for_public_memo_refreshes(server)
        self.assertEqual(len(calls), 1)
        return calls

    # 1 ---------------------------------------------------------------
    def test_overview_serves_stale_and_refreshes_once(self) -> None:
        self._assert_stale_served_and_refreshed_once(
            "/api/public/league/overview", "build_public_contract", "generation"
        )
        key = self.server._public_contract_cache_key(self.server._public_league_cache["snapshot"])
        self.assertIsNotNone(self.server._memoized_overview(key))
        # The refresh seeded the whole generation, not just the overview.
        self.assertIsNotNone(
            self.server._cached_public_contract_bytes(self.server._public_league_cache["snapshot"])
        )
        self.assertIsNotNone(self.server._memoized_activity(key))

    def test_full_contract_serves_stale_and_refreshes_once(self) -> None:
        self._assert_stale_served_and_refreshed_once(
            "/api/public/league", "build_public_contract", "generation"
        )
        self.assertIsNotNone(
            self.server._cached_public_contract_bytes(self.server._public_league_cache["snapshot"])
        )

    def test_activity_serves_stale_and_refreshes_once(self) -> None:
        self._assert_stale_served_and_refreshed_once(
            "/api/public/league/activity", "build_activity_serving_payload", "activity"
        )
        key = self.server._public_contract_cache_key(self.server._public_league_cache["snapshot"])
        self.assertIsNotNone(self.server._memoized_activity(key))

    def test_heavy_section_serves_stale_and_refreshes_once(self) -> None:
        self._assert_stale_served_and_refreshed_once(
            "/api/public/league/archives",
            "build_section_payload",
            "heavy:archives",
            only_section="archives",
        )
        entry = self.server._heavy_section_cache["archives"]
        snapshot = self.server._public_league_cache["snapshot"]
        self.assertEqual(entry[0], self.server._heavy_section_cache_key(snapshot))

    def test_an_aged_entry_is_served_and_refreshed_in_the_background(self) -> None:
        server = self.server
        warm = self.client.get("/api/public/league/overview")
        self.assertEqual(warm.status_code, 200)
        key, payload, _ = server._PUBLIC_OVERVIEW_CACHE["overview"]
        aged = time.monotonic() - 2 * server._PUBLIC_LEAGUE_CACHE_TTL_SECONDS - 1
        server._PUBLIC_OVERVIEW_CACHE["overview"] = (key, payload, aged)
        gate, calls = self._gate("build_public_contract")
        results, _ = self._concurrent_get(["/api/public/league/overview"] * 4)
        self.assertEqual({r.status_code for r in results}, {200})
        self.assertEqual({r.content for r in results}, {warm.content})
        self.assertEqual(calls, ["public-league-memo-generation"])
        gate.set()
        wait_for_public_memo_refreshes(server)
        self.assertIsNotNone(server._memoized_overview(key))

    # 2 ---------------------------------------------------------------
    def test_concurrent_cold_full_contract_misses_build_once(self) -> None:
        calls = []
        real = self._real["build_public_contract"]

        def slow(*args, **kwargs):
            calls.append(threading.current_thread().name)
            time.sleep(0.3)  # keep the build open while the others arrive
            return real(*args, **kwargs)

        self.server.build_public_contract = slow
        paths = ["/api/public/league"] * 4 + ["/api/public/league/overview"] * 4
        results, _ = self._concurrent_get(paths)
        self.assertEqual({r.status_code for r in results}, {200})
        self.assertEqual(len({r.content for r in results[:4]}), 1)
        self.assertEqual(len(calls), 1, "concurrent cold misses must share one build")

    # 3 ---------------------------------------------------------------
    def test_a_failing_refresh_keeps_serving_the_last_good_entry(self) -> None:
        server = self.server
        warm = self.client.get("/api/public/league/overview")
        self.assertEqual(warm.status_code, 200)
        old_key = server._PUBLIC_OVERVIEW_CACHE["overview"][0]
        failures = self._metric("memo_refresh_failures")
        attempts = []

        def failing(*args, **kwargs):
            attempts.append(1)
            raise RuntimeError("upstream exploded")

        server.build_public_contract = failing
        server.latest_data_etag = "swr-failing-generation"
        first = self.client.get("/api/public/league/overview")
        wait_for_public_memo_refreshes(server)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, warm.content)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self._metric("memo_refresh_failures") - failures, 1)
        # The error was not filed as data: the last good entry is still there.
        self.assertEqual(server._PUBLIC_OVERVIEW_CACHE["overview"][0], old_key)

        # Inside the cooldown, requests keep the good entry and start nothing.
        for _ in range(3):
            again = self.client.get("/api/public/league/overview")
            self.assertEqual(again.status_code, 200)
            self.assertEqual(again.content, warm.content)
        wait_for_public_memo_refreshes(server)
        self.assertEqual(len(attempts), 1)

        # After the cooldown it retries -- once -- and still serves the entry.
        with server._public_memo_refresh_lock:
            server._public_memo_refresh_failed_at["generation"] -= (
                server._PUBLIC_LEAGUE_FAILURE_COOLDOWN_SECONDS + 1
            )
        later = self.client.get("/api/public/league/overview")
        wait_for_public_memo_refreshes(server)
        self.assertEqual(later.content, warm.content)
        self.assertEqual(len(attempts), 2)

    # 4 ---------------------------------------------------------------
    def test_another_leagues_entry_is_never_served(self) -> None:
        server = self.server
        snapshot = server._public_league_cache["snapshot"]
        own = server._public_contract_cache_key(snapshot)
        foreign = ("OTHER-LEAGUE",) + own[1:]
        sentinel = {"section": "overview", "data": {"sentinel": "other league"}}
        server._PUBLIC_OVERVIEW_CACHE["overview"] = (foreign, sentinel, time.monotonic())
        server._store_public_contract_bytes(
            snapshot, {"sentinel": "other league"}, key=foreign, started_at=time.monotonic()
        )
        calls = []
        real = self._real["build_public_contract"]

        def counting(*args, **kwargs):
            calls.append(threading.current_thread().name)
            return real(*args, **kwargs)

        server.build_public_contract = counting
        overview = self.client.get("/api/public/league/overview")
        full = self.client.get("/api/public/league")
        self.assertEqual((overview.status_code, full.status_code), (200, 200))
        self.assertNotIn(b"other league", overview.content)
        self.assertNotIn(b"other league", full.content)
        # A cold build on the request path, not a stale serve of the foreign one.
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(name.startswith("public-league-memo") for name in calls))

    def test_lineage_rules(self) -> None:
        same = self.server._public_memo_same_lineage
        key = ("L1", "gen-2", "etag-2", "vorp-1")
        self.assertTrue(same(("L1", "gen-1", "etag-1", "vorp-1"), key))
        self.assertFalse(same(("L2", "gen-2", "etag-2", "vorp-1"), key), "another league")
        self.assertFalse(same(("L1", "gen-2", "etag-2", "vorp-0"), key), "another VORP version")
        self.assertFalse(same(("", "g", "e", "v"), ("", "g2", "e", "v")), "no league identity")
        self.assertFalse(same(("L1", "gen-1"), key), "another key shape")
        self.assertTrue(same(("L1", "gen-1", "etag-1"), ("L1", "gen-2", "etag-2")))

    def test_a_new_vorp_version_is_a_cold_build_not_a_stale_serve(self) -> None:
        from src.public_league import awards as awards_module

        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        calls = []
        real = self._real["build_public_contract"]

        def counting(*args, **kwargs):
            calls.append(threading.current_thread().name)
            return real(*args, **kwargs)

        self.server.build_public_contract = counting
        old = awards_module._VORP_CALC_VERSION
        awards_module._VORP_CALC_VERSION = "swr-bumped-version"
        try:
            self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        finally:
            awards_module._VORP_CALC_VERSION = old
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].startswith("public-league-memo"))

    # 5 ---------------------------------------------------------------
    def test_a_hung_refresh_stops_suppressing_after_the_timeout(self) -> None:
        server = self.server
        warm = self.client.get("/api/public/league/overview")
        self.assertEqual(warm.status_code, 200)
        timed_out = self._metric("memo_refresh_timed_out")
        hung_gate, calls = self._gate("build_public_contract")
        server.latest_data_etag = "swr-hung-generation"
        self.assertEqual(self.client.get("/api/public/league/overview").content, warm.content)
        self.assertEqual(self.client.get("/api/public/league/overview").content, warm.content)
        self.assertEqual(len(calls), 1, "a running job suppresses a second one")
        # Age the hung job's claim past the timeout (no sleeping on a clock).
        with server._public_memo_refresh_lock:
            token, started = server._public_memo_refresh_inflight["generation"]
            server._public_memo_refresh_inflight["generation"] = (
                token,
                started - server._PUBLIC_LEAGUE_MEMO_REFRESH_TIMEOUT_SECONDS - 1,
            )
        # Past the timeout: a replacement starts (with the real builder).
        real = self._real["build_public_contract"]
        server.build_public_contract = real
        self.assertEqual(self.client.get("/api/public/league/overview").content, warm.content)
        self.assertEqual(self._metric("memo_refresh_timed_out") - timed_out, 1)
        # The replacement owns the claim now; waiting for it does not wait
        # for the hung thread, whose late exit must not clear that claim.
        wait_for_public_memo_refreshes(server)
        new_key = server._public_contract_cache_key(server._public_league_cache["snapshot"])
        replacement = server._PUBLIC_OVERVIEW_CACHE["overview"]
        self.assertEqual(replacement[0], new_key)
        # The hung build lands late; it started first, so it cannot replace.
        hung_gate.set()
        for thread in threading.enumerate():
            if thread.name == "public-league-memo-generation":
                thread.join(GATE_TIMEOUT_SECONDS)
        self.assertEqual(server._PUBLIC_OVERVIEW_CACHE["overview"][2], replacement[2])
        self.assertEqual(server._public_memo_refresh_inflight, {})

    # 6 ---------------------------------------------------------------
    def test_the_activity_job_defers_to_a_running_generation_job(self) -> None:
        server = self.server
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        activity_calls = []
        real_activity = self._real["build_activity_serving_payload"]

        def counting_activity(*args, **kwargs):
            activity_calls.append(1)
            return real_activity(*args, **kwargs)

        server.build_activity_serving_payload = counting_activity
        gate, calls = self._gate("build_public_contract")
        server.latest_data_etag = "swr-covered-generation"
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        self.assertEqual(self.client.get("/api/public/league/activity").status_code, 200)
        self.assertEqual(calls, ["public-league-memo-generation"])
        gate.set()
        wait_for_public_memo_refreshes(server)
        self.assertEqual(activity_calls, [], "the generation build seeds activity itself")
        key = server._public_contract_cache_key(server._public_league_cache["snapshot"])
        self.assertIsNotNone(server._memoized_activity(key))


if __name__ == "__main__":
    unittest.main()
