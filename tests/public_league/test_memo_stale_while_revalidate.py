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
import gzip
import json
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

    def _wait_until(self, condition, what: str) -> None:
        deadline = time.monotonic() + GATE_TIMEOUT_SECONDS
        while not condition():
            if time.monotonic() > deadline:
                self.fail(f"timed out waiting for {what}")
            time.sleep(0.005)

    def _expire_claim(self, job: str) -> None:
        """Age ``job``'s claim past the refresh timeout (no sleeping on a clock)."""
        server = self.server
        with server._public_memo_refresh_lock:
            claim = server._public_memo_refresh_inflight[job]
            server._public_memo_refresh_inflight[job] = (
                claim[0],
                claim[1] - server._PUBLIC_LEAGUE_MEMO_REFRESH_TIMEOUT_SECONDS - 1,
                *claim[2:],
            )

    def _never_returning_builder(self, name: str):
        """Replace ``server.<name>`` with a builder that hangs until the test
        releases that call (tearDown releases any it did not).  Returns the
        per-call release events and the threads that called it."""
        real = self._real[name]
        releases: list[threading.Event] = []
        threads: list[threading.Thread] = []

        def hung(*args, **kwargs):
            release = threading.Event()
            self._gates.append(release)
            releases.append(release)
            threads.append(threading.current_thread())
            if not release.wait(GATE_TIMEOUT_SECONDS * 6):
                raise RuntimeError("never released")
            return real(*args, **kwargs)

        setattr(self.server, name, hung)
        return releases, threads

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
        self._expire_claim("generation")
        # Past the timeout: a replacement starts (with the real builder).
        real = self._real["build_public_contract"]
        server.build_public_contract = real
        self.assertEqual(self.client.get("/api/public/league/overview").content, warm.content)
        self.assertEqual(self._metric("memo_refresh_timed_out") - timed_out, 1)
        # The replacement owns the claim now; waiting for it does not wait
        # for the hung thread, whose late exit must not clear that claim.
        self._wait_until(lambda: not server._public_memo_refresh_inflight, "the replacement")
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

    # 8 ---------------------------------------------------------------
    # A timed-out job keeps running (a thread cannot be killed) and holds its
    # snapshot.  Without a cap, every timeout started one more replacement
    # while the hung ones lived on: an unbounded pile of hung builds.  Cap:
    # per job, at most ONE abandoned (timed-out, still alive) job.
    def test_at_most_one_abandoned_job_per_memo(self) -> None:
        server = self.server
        warm = self.client.get("/api/public/league/overview")
        self.assertEqual(warm.status_code, 200)
        releases, threads = self._never_returning_builder("build_public_contract")

        def stale_get():
            response = self.client.get("/api/public/league/overview")
            self.assertEqual(response.status_code, 200)
            return response

        def alive_jobs():
            return [t for t in threads if t.is_alive()]

        server.latest_data_etag = "swr-abandoned-generation"
        self.assertEqual(stale_get().content, warm.content)  # job A starts, hangs
        self._wait_until(lambda: len(releases) == 1, "job A")
        self._expire_claim("generation")
        timed_out = self._metric("memo_refresh_timed_out")
        self.assertEqual(stale_get().content, warm.content)  # A abandoned; B starts
        self._wait_until(lambda: len(releases) == 2, "replacement B")
        self.assertEqual(self._metric("memo_refresh_timed_out") - timed_out, 1)
        self.assertEqual(len(alive_jobs()), 2)

        # B times out as well, but abandoned A is still alive: no third job.
        self._expire_claim("generation")
        skipped = self._metric("memo_refresh_skipped_abandoned")
        for _ in range(3):
            self.assertEqual(stale_get().content, warm.content)
        self.assertEqual(self._metric("memo_refresh_skipped_abandoned") - skipped, 3)
        self.assertEqual(len(releases), 2, "no replacement while an abandoned job lives")
        self.assertEqual(len(alive_jobs()), 2)
        self.assertEqual(self._metric("memo_refresh_timed_out") - timed_out, 1)

        # Once A ends, the hung B may be abandoned in turn -- still one.
        releases[0].set()
        threads[0].join(GATE_TIMEOUT_SECONDS)
        self.assertFalse(threads[0].is_alive())
        server.latest_data_etag = "swr-abandoned-generation-2"
        stale_get()
        self._wait_until(lambda: len(releases) == 3, "replacement C")
        self.assertEqual(self._metric("memo_refresh_timed_out") - timed_out, 2)
        self.assertEqual(len(alive_jobs()), 2)

    # 9 ---------------------------------------------------------------
    # stale != current: a memo entry is served stale only while its build is
    # younger than the bound -- the repo's scrape-cadence staleness rule,
    # SCRAPE_INTERVAL_HOURS * 3 (6 h).  Past it the request takes the cold
    # path, which answers exactly as with no entry: a fresh build, or a 503.
    _TOO_OLD_MARKER = "too-old-stale-sentinel"

    def _stale_bound(self) -> float:
        server = self.server
        return getattr(
            server,
            "_PUBLIC_LEAGUE_MEMO_MAX_STALE_SECONDS",
            float(server.SCRAPE_INTERVAL_HOURS) * 3 * 3600,
        )

    def _plant_stale_entry(self, memo: str, started_at: float) -> None:
        """Replace ``memo``'s entry with a same-league, older-generation one
        whose body is recognisable, built at ``started_at``."""
        server = self.server
        snapshot = server._public_league_cache["snapshot"]
        key = server._public_contract_cache_key(snapshot)
        older = (key[0], "1999-01-01T00:00:00+00:00", "older-etag", key[3])
        payload = {"section": memo, "data": {"marker": self._TOO_OLD_MARKER}}
        raw = json.dumps(payload).encode()
        if memo == "overview":
            server._PUBLIC_OVERVIEW_CACHE["overview"] = (older, payload, started_at)
        elif memo == "contract":
            with server._PUBLIC_CONTRACT_BYTES_LOCK:
                server._PUBLIC_CONTRACT_BYTES_CACHE.clear()
                server._PUBLIC_CONTRACT_BYTES_CACHE[older] = (raw, started_at)
        elif memo == "activity":
            with server._PUBLIC_ACTIVITY_LOCK:
                server._PUBLIC_ACTIVITY_CACHE["activity"] = (
                    older,
                    raw,
                    gzip.compress(raw),
                    started_at,
                )
        else:
            server._heavy_section_cache[memo] = (older[:3], payload, started_at)

    _BOUND_CASES = (
        ("overview", "/api/public/league/overview", "build_public_contract", None),
        ("contract", "/api/public/league", "build_public_contract", None),
        ("activity", "/api/public/league/activity", "build_activity_serving_payload", None),
        ("archives", "/api/public/league/archives", "build_section_payload", "archives"),
    )

    def _counting(self, name: str, only_section: str | None = None) -> list[str]:
        real = self._real[name]
        calls: list[str] = []

        def counting(*args, **kwargs):
            section = args[1] if len(args) > 1 else kwargs.get("section")
            if only_section is None or section == only_section:
                calls.append(threading.current_thread().name)
            return real(*args, **kwargs)

        setattr(self.server, name, counting)
        return calls

    def test_the_staleness_bound_reuses_the_scrape_cadence_rule(self) -> None:
        server = self.server
        self.assertEqual(
            server._PUBLIC_LEAGUE_MEMO_MAX_STALE_SECONDS,
            float(server.SCRAPE_INTERVAL_HOURS) * 3 * 3600,
        )

    def test_an_entry_past_the_staleness_bound_is_not_served_stale(self) -> None:
        server = self.server
        for memo, path, builder, section in self._BOUND_CASES:
            with self.subTest(memo=memo):
                self.assertEqual(self.client.get(path).status_code, 200)
                self._plant_stale_entry(memo, time.monotonic() - self._stale_bound() - 1)
                calls = self._counting(builder, section)
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text[:300])
                self.assertNotIn(self._TOO_OLD_MARKER.encode(), response.content)
                # The cold path: one build for this request, none in the background.
                self.assertEqual(len(calls), 1, calls)
                self.assertFalse(calls[0].startswith("public-league-memo"), calls)
                wait_for_public_memo_refreshes(server)
                setattr(server, builder, self._real[builder])

    def test_an_entry_inside_the_staleness_bound_is_still_served_stale(self) -> None:
        server = self.server
        for memo, path, builder, section in self._BOUND_CASES:
            with self.subTest(memo=memo):
                self.assertEqual(self.client.get(path).status_code, 200)
                self._plant_stale_entry(memo, time.monotonic() - self._stale_bound() + 60)
                gate, calls = self._gate(builder, only_section=section)
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text[:300])
                self.assertIn(self._TOO_OLD_MARKER.encode(), response.content)
                self.assertEqual(len(calls), 1, calls)
                self.assertTrue(calls[0].startswith("public-league-memo"), calls)
                gate.set()
                wait_for_public_memo_refreshes(server)
                setattr(server, builder, self._real[builder])

    def test_past_the_bound_a_failing_build_answers_503_not_the_old_entry(self) -> None:
        server = self.server
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        self._plant_stale_entry("overview", time.monotonic() - self._stale_bound() - 1)

        def failing(*args, **kwargs):
            raise RuntimeError("upstream exploded")

        server.build_public_contract = failing
        response = self.client.get("/api/public/league/overview")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(self._TOO_OLD_MARKER.encode(), response.content)

    # 10 --------------------------------------------------------------
    # The failure cooldown belongs to the job that holds the claim.  A
    # superseded (abandoned) job finishing late must neither set it -- which
    # would hold off the next refresh for a failure nobody is serving -- nor
    # clear the cooldown its replacement set.
    def _superseded_job(self, *, late_outcome_fails: bool, replacement_fails: bool):
        server = self.server
        real = self._real["build_public_contract"]
        gate = threading.Event()
        self._gates.append(gate)
        hung: list[threading.Thread] = []

        def builder(*args, **kwargs):
            if not hung:
                hung.append(threading.current_thread())
                gate.wait(GATE_TIMEOUT_SECONDS)
                if late_outcome_fails:
                    raise RuntimeError("superseded job failed late")
                return real(*args, **kwargs)
            if replacement_fails:
                raise RuntimeError("replacement failed")
            return real(*args, **kwargs)

        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        server.build_public_contract = builder
        server.latest_data_etag = "swr-superseded-generation"
        self.client.get("/api/public/league/overview")  # job A starts and hangs
        self._wait_until(lambda: hung, "job A")
        self._expire_claim("generation")
        self.client.get("/api/public/league/overview")  # replacement B runs
        self._wait_until(lambda: not server._public_memo_refresh_inflight, "replacement B")
        gate.set()
        hung[0].join(GATE_TIMEOUT_SECONDS)
        self.assertFalse(hung[0].is_alive())

    def test_a_superseded_jobs_late_failure_does_not_set_the_cooldown(self) -> None:
        server = self.server
        self._superseded_job(late_outcome_fails=True, replacement_fails=False)
        self.assertNotIn("generation", server._public_memo_refresh_failed_at)
        server.latest_data_etag = "swr-superseded-generation-2"
        started = self._metric("memo_refresh_started")
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        self.assertEqual(self._metric("memo_refresh_started") - started, 1)

    def test_a_superseded_jobs_late_success_does_not_clear_the_cooldown(self) -> None:
        server = self.server
        self._superseded_job(late_outcome_fails=False, replacement_fails=True)
        self.assertIn("generation", server._public_memo_refresh_failed_at)

    # 7 ---------------------------------------------------------------
    # B8 on the heavy sections: an AUTHORIZED ``?refresh=1`` forces a snapshot
    # rebuild, which always moves ``generated_at`` -- so the memo entry is a
    # same-league, older-generation entry, exactly what stale-while-revalidate
    # serves.  The refresh must answer with the NEW generation (as on main,
    # where the key miss built inline), never the pre-refresh body.  An
    # anonymous ``?refresh`` forces nothing and reads the memo like anyone.
    _PRE_REFRESH_MARKER = "pre-refresh-sentinel"

    def _plant_pre_refresh_archives_entry(self) -> None:
        """Warm the archives memo, then replace it with a same-league entry of
        an OLDER generation whose body is recognisable in JSON and CSV."""
        server = self.server
        warm = self.client.get("/api/public/league/archives")
        self.assertEqual(warm.status_code, 200, warm.text[:300])
        key, _, _ = server._heavy_section_cache["archives"]
        older = (key[0], "1999-01-01T00:00:00+00:00", key[2])
        sentinel = {
            "section": "archives",
            "data": {"trades": [{"marker": self._PRE_REFRESH_MARKER}]},
        }
        server._heavy_section_cache["archives"] = (older, sentinel, time.monotonic())

    def _count_archives_builds(self) -> list[str]:
        real = self._real["build_section_payload"]
        calls: list[str] = []

        def counting(*args, **kwargs):
            section = args[1] if len(args) > 1 else kwargs.get("section")
            if section == "archives":
                calls.append(threading.current_thread().name)
            return real(*args, **kwargs)

        self.server.build_section_payload = counting
        return calls

    def _authorized(self) -> None:
        real = self.server._is_authenticated
        self.server._is_authenticated = lambda request: True
        self.addCleanup(setattr, self.server, "_is_authenticated", real)

    def _assert_authorized_refresh_serves_the_new_generation(self, path: str) -> bytes:
        server = self.server
        self._plant_pre_refresh_archives_entry()
        self._authorized()
        calls = self._count_archives_builds()
        forced = self._metric("force_refresh")

        response = self.client.get(f"{path}?refresh=1")

        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(self._metric("force_refresh") - forced, 1, "the refresh was authorized")
        self.assertNotIn(self._PRE_REFRESH_MARKER.encode(), response.content)
        # Built inline for the request (not a background job serving stale).
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].startswith("public-league-memo"), calls)
        snapshot = server._public_league_cache["snapshot"]
        self.assertEqual(
            server._heavy_section_cache["archives"][0], server._heavy_section_cache_key(snapshot)
        )
        return response.content

    def test_an_authorized_refresh_of_a_heavy_section_serves_the_new_generation(self) -> None:
        body = self._assert_authorized_refresh_serves_the_new_generation(
            "/api/public/league/archives"
        )
        snapshot = self.server._public_league_cache["snapshot"]
        self.assertEqual(json.loads(body)["league"]["generatedAt"], snapshot.generated_at)

    def test_an_authorized_refresh_of_a_heavy_section_csv_serves_the_new_generation(
        self,
    ) -> None:
        self._assert_authorized_refresh_serves_the_new_generation("/api/public/league/archives.csv")

    def test_an_anonymous_refresh_of_a_heavy_section_forces_nothing(self) -> None:
        for path in ("/api/public/league/archives", "/api/public/league/archives.csv"):
            with self.subTest(path=path):
                self._plant_pre_refresh_archives_entry()
                forced = self._metric("force_refresh")
                gate, gated = self._gate("build_section_payload", only_section="archives")
                response = self.client.get(f"{path}?refresh=1")
                self.assertEqual(response.status_code, 200, response.text[:300])
                self.assertEqual(self._metric("force_refresh"), forced)
                # Read the memo like any caller: the stale entry, revalidated
                # in the background -- never built inline for this request.
                self.assertIn(self._PRE_REFRESH_MARKER.encode(), response.content)
                self.assertEqual(gated, ["public-league-memo-heavy:archives"])
                gate.set()
                wait_for_public_memo_refreshes(self.server)
                self.server.build_section_payload = self._real["build_section_payload"]


if __name__ == "__main__":
    unittest.main()
