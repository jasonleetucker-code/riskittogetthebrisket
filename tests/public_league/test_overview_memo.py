"""Tests for the per-generation ``GET /api/public/league/overview`` memo.

The overview is the public /league page's first request.  It used to
build EVERY public section (awards included) and keep only the overview
-- the full contract's work on every request, 2-8 s TTFB in production
(2026-09-28).  The overview is the same object the full contract carries
in ``sections["overview"]``, so one single-flighted build per generation
now fills both ``server._PUBLIC_OVERVIEW_CACHE`` and the full-contract
bytes memo, under the full contract's generation key.

Pinned here:
    1. Repeat requests for one generation build once, identical bytes.
    2. That build also serves ``GET /api/public/league`` (no second build).
    3. A new private-board generation and a new VORP calc version miss.
    4. ``?refresh=1`` bypasses the memo read.
    5. The memoized overview equals a direct ``build_section_payload``.
    6. Concurrent misses build once.
"""

from __future__ import annotations

import asyncio
import os
import unittest

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class PublicOverviewMemoTests(unittest.TestCase):
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

        # Public routes share a per-client budget (60/min) across the whole
        # test process; neither inherit nor leak it.
        rate_limit.reset_for_tests()
        self.addCleanup(rate_limit.reset_for_tests)
        with self.server._PUBLIC_CONTRACT_BYTES_LOCK:
            self.server._PUBLIC_CONTRACT_BYTES_CACHE.clear()
        self.server._PUBLIC_OVERVIEW_CACHE.clear()
        self.server._public_overview_async_lock = None
        self.calls = {"n": 0}
        self._real = self.server.build_public_contract

        def counting(*args, **kwargs):
            self.calls["n"] += 1
            return self._real(*args, **kwargs)

        self.server.build_public_contract = counting

    def tearDown(self) -> None:
        self.server.build_public_contract = self._real

    def test_repeat_requests_build_once(self) -> None:
        r1 = self.client.get("/api/public/league/overview")
        r2 = self.client.get("/api/public/league/overview")
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertEqual(r1.content, r2.content)
        self.assertEqual(r1.json()["section"], "overview")
        self.assertEqual(self.calls["n"], 1)

    def test_the_overview_build_also_serves_the_full_contract(self) -> None:
        overview = self.client.get("/api/public/league/overview")
        full = self.client.get("/api/public/league")
        self.assertEqual((overview.status_code, full.status_code), (200, 200))
        self.assertEqual(self.calls["n"], 1, "the full contract must come from the same build")
        self.assertEqual(full.json()["sections"]["overview"], overview.json()["data"])

    def test_a_new_private_board_generation_rebuilds(self) -> None:
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        old = self.server.latest_data_etag
        self.server.latest_data_etag = "new-private-generation"
        try:
            self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        finally:
            self.server.latest_data_etag = old
        self.assertEqual(self.calls["n"], 2)

    def test_a_new_vorp_calc_version_rebuilds(self) -> None:
        from src.public_league import awards as awards_module

        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        old = awards_module._VORP_CALC_VERSION
        awards_module._VORP_CALC_VERSION = "test-bumped-version"
        try:
            self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        finally:
            awards_module._VORP_CALC_VERSION = old
        self.assertEqual(self.calls["n"], 2)

    def test_refresh_bypasses_the_memo_read(self) -> None:
        self.assertEqual(self.client.get("/api/public/league/overview").status_code, 200)
        self.assertEqual(self.client.get("/api/public/league/overview?refresh=1").status_code, 200)
        self.assertEqual(self.calls["n"], 2)

    def test_a_snapshot_rebuild_seeds_the_overview_memo(self) -> None:
        # Cold snapshot: the rebuild's persist step builds the contract once;
        # the overview request that triggered it is answered from that build.
        self.server._public_league_cache.update({"snapshot": None, "fetched_at": 0.0})
        persist = self.server._PUBLIC_LEAGUE_PERSIST
        self.server._PUBLIC_LEAGUE_PERSIST = True
        try:
            r = self.client.get("/api/public/league/overview")
        finally:
            self.server._PUBLIC_LEAGUE_PERSIST = persist
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.calls["n"], 1)

    def test_memoized_overview_equals_a_direct_section_build(self) -> None:
        import json

        from src.public_league.public_contract import build_section_payload

        served = self.client.get("/api/public/league/overview")
        self.assertEqual(served.status_code, 200)
        snapshot = self.server._public_league_cache["snapshot"]
        direct = build_section_payload(
            snapshot,
            "overview",
            activity_valuation=self.server._build_public_activity_valuation(),
        )
        self.assertEqual(served.json(), json.loads(json.dumps(direct)))

    def test_concurrent_misses_build_once(self) -> None:
        import httpx

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.server.app), base_url="http://fixture"
            ) as client:
                return await asyncio.gather(
                    *[client.get("/api/public/league/overview") for _ in range(6)]
                )

        results = asyncio.run(run())
        self.assertEqual({r.status_code for r in results}, {200})
        self.assertEqual(len({r.content for r in results}), 1)
        self.assertEqual(self.calls["n"], 1)
