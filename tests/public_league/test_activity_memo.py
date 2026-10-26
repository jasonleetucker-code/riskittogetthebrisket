"""Tests for the prepared ``GET /api/public/league/activity`` response.

The activity section used to be rebuilt on EVERY request -- as-of trade
grading, two safety walks and a ~421 KB encode (p50 1.95 s / p95 3.60 s in
production, 2026-10-03) -- while every snapshot rebuild already built the
same section into the full contract and discarded it.  It is now served
from ``server._PUBLIC_ACTIVITY_CACHE``: seeded from that contract, keyed
by the full contract's generation key, trimmed to its readers' fields, and
pre-encoded + pre-gzipped.

Pinned here (mirrors ``test_overview_memo.py``):
    1. Repeat requests for one generation build once, identical bytes.
    2. A full-contract build (overview / full contract / snapshot rebuild)
       seeds it -- the activity request builds nothing.
    3. A new private-board generation and a new VORP calc version miss;
       a miss builds ONLY the activity section, never the full contract.
    4. Only an AUTHORIZED ``?refresh`` bypasses the memo read (B8).
    5. Entries age out with the snapshot window; an older build never
       replaces a newer one; a broken activity section cannot cost the
       overview its seed.
    6. The served body equals the serving view of a direct section build.
    7. Concurrent misses build once.
    8. gzip is negotiated from the prepared bytes, identity is the raw body.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
import unittest

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class PublicActivityMemoTests(unittest.TestCase):
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

        rate_limit.reset_for_tests()
        self.addCleanup(rate_limit.reset_for_tests)
        # Quiesce any background snapshot refresh first (it would seed these
        # memos from an uncounted build), then pin a fresh snapshot.
        self._wait_for_snapshot_refresh()
        if self.server._public_league_cache.get("snapshot") is None:
            self.server._get_public_snapshot()
        self.server._public_league_cache["fetched_at"] = time.time()
        self._wait_for_snapshot_refresh()
        with self.server._PUBLIC_CONTRACT_BYTES_LOCK:
            self.server._PUBLIC_CONTRACT_BYTES_CACHE.clear()
        self.server._PUBLIC_OVERVIEW_CACHE.clear()
        self.server._public_overview_async_lock = None
        with self.server._PUBLIC_ACTIVITY_LOCK:
            self.server._PUBLIC_ACTIVITY_CACHE.clear()
        self.server._public_activity_async_lock = None

        self.calls = {"contract": 0, "activity": 0}
        self._real_contract = self.server.build_public_contract
        self._real_activity = self.server.build_activity_serving_payload

        def counting_contract(*args, **kwargs):
            self.calls["contract"] += 1
            return self._real_contract(*args, **kwargs)

        def counting_activity(*args, **kwargs):
            self.calls["activity"] += 1
            return self._real_activity(*args, **kwargs)

        self.server.build_public_contract = counting_contract
        self.server.build_activity_serving_payload = counting_activity

    def tearDown(self) -> None:
        self.server.build_public_contract = self._real_contract
        self.server.build_activity_serving_payload = self._real_activity

    def _wait_for_snapshot_refresh(self) -> None:
        deadline = time.monotonic() + 30
        while self.server._public_league_cache.get("refreshing") and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(
            self.server._public_league_cache.get("refreshing"), "snapshot refresh never finished"
        )

    def _get(self, path: str = "/api/public/league/activity", **kwargs):
        r = self.client.get(path, **kwargs)
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r

    # 1 ---------------------------------------------------------------
    def test_repeat_requests_build_once(self) -> None:
        r1, r2 = self._get(), self._get()
        self.assertEqual(r1.content, r2.content)
        self.assertEqual(r1.json()["section"], "activity")
        self.assertEqual(self.calls, {"contract": 0, "activity": 1})

    # 2 ---------------------------------------------------------------
    def test_an_overview_build_seeds_the_activity_memo(self) -> None:
        self._get("/api/public/league/overview")
        self._get()
        self.assertEqual(self.calls, {"contract": 1, "activity": 0})

    def test_a_full_contract_build_seeds_the_activity_memo(self) -> None:
        self._get("/api/public/league")
        self._get()
        self.assertEqual(self.calls, {"contract": 1, "activity": 0})

    def test_a_snapshot_rebuild_seeds_the_activity_memo_before_publishing(self) -> None:
        self.server._public_league_cache["fetched_at"] = 0.0  # due for a rebuild
        persist = self.server._PUBLIC_LEAGUE_PERSIST
        self.server._PUBLIC_LEAGUE_PERSIST = True
        try:
            new = self.server._rebuild_public_snapshot("L2025", trigger="test")
        finally:
            self.server._PUBLIC_LEAGUE_PERSIST = persist
        self.assertIs(self.server._public_league_cache["snapshot"], new)
        self._get()
        self.assertEqual(self.calls, {"contract": 1, "activity": 0})

    # 3 ---------------------------------------------------------------
    def test_a_new_private_board_generation_rebuilds_only_activity(self) -> None:
        self._get()
        old = self.server.latest_data_etag
        self.server.latest_data_etag = "new-private-generation"
        try:
            self._get()
            self._get()
        finally:
            self.server.latest_data_etag = old
        self.assertEqual(self.calls, {"contract": 0, "activity": 2})

    def test_a_new_vorp_calc_version_rebuilds(self) -> None:
        from src.public_league import awards as awards_module

        self._get()
        old = awards_module._VORP_CALC_VERSION
        awards_module._VORP_CALC_VERSION = "test-bumped-version"
        try:
            self._get()
        finally:
            awards_module._VORP_CALC_VERSION = old
        self.assertEqual(self.calls["activity"], 2)

    # 4 ---------------------------------------------------------------
    def test_an_anonymous_refresh_reads_the_memo(self) -> None:
        self._get()
        for flag in ("1", "0", "yes"):
            self._get(f"/api/public/league/activity?refresh={flag}")
        self.assertEqual(self.calls["activity"], 1)

    def test_an_authorized_refresh_bypasses_the_memo_read(self) -> None:
        self._get()
        real_auth = self.server._authorized_force_refresh
        self.server._authorized_force_refresh = lambda request, refresh: bool(refresh)
        try:
            self._get("/api/public/league/activity?refresh=1")
        finally:
            self.server._authorized_force_refresh = real_auth
        self.assertEqual(self.calls["activity"], 2)

    # 5 ---------------------------------------------------------------
    def test_entries_age_out_with_the_snapshot_refresh_window(self) -> None:
        self._get()
        key, raw, gz, _ = self.server._PUBLIC_ACTIVITY_CACHE["activity"]
        ttl = self.server._PUBLIC_LEAGUE_CACHE_TTL_SECONDS
        self.server._PUBLIC_ACTIVITY_CACHE["activity"] = (key, raw, gz, time.monotonic() - ttl - 1)
        self.assertEqual(self.server._memoized_activity(key), (raw, gz))
        self.server._PUBLIC_ACTIVITY_CACHE["activity"] = (
            key,
            raw,
            gz,
            time.monotonic() - 2 * ttl - 1,
        )
        self.assertIsNone(self.server._memoized_activity(key))

    def test_an_older_build_never_replaces_a_newer_one(self) -> None:
        server = self.server
        server._remember_activity(("G2",), {"g": 2}, started_at=200.0)
        raw, _ = server._remember_activity(("G1",), {"g": 1}, started_at=100.0)
        self.assertEqual(server._PUBLIC_ACTIVITY_CACHE["activity"][0], ("G2",))
        # The older build's caller still gets ITS bytes to serve.
        self.assertEqual(json.loads(raw), {"g": 1})

    def test_a_broken_activity_section_does_not_cost_the_overview_its_seed(self) -> None:
        contract = {
            "contractVersion": "v",
            "league": {"name": "L"},
            "sections": {"overview": {"ok": True}, "activity": {"totalCount": float("nan")}},
        }
        self.server._seed_public_generation(object(), contract, ("K", "nan"), started_at=1e12)
        self.assertEqual(self.server._PUBLIC_OVERVIEW_CACHE["overview"][1]["data"], {"ok": True})
        self.assertNotIn("activity", self.server._PUBLIC_ACTIVITY_CACHE)

    def test_a_seed_runs_the_safety_walk_over_what_is_served(self) -> None:
        contract = {
            "contractVersion": "v",
            "league": {"name": "L"},
            "sections": {
                "overview": {"ok": True},
                # A blocked key on a SERVED field must refuse the seed.
                "activity": {"mostActiveTrader": {"rankDerivedValue": 1}},
            },
        }
        self.server._seed_public_generation(object(), contract, ("K", "leak"), started_at=1e12)
        self.assertNotIn("activity", self.server._PUBLIC_ACTIVITY_CACHE)

    # 6 ---------------------------------------------------------------
    def test_served_body_is_the_serving_view_of_a_direct_build(self) -> None:
        from src.public_league import activity
        from src.public_league.public_contract import build_section_payload

        served = self._get().json()
        snapshot = self.server._public_league_cache["snapshot"]
        direct = build_section_payload(
            snapshot,
            "activity",
            activity_valuation=self.server._build_public_activity_valuation(),
        )
        direct["data"] = activity.serving_view(direct["data"])
        self.assertEqual(served, json.loads(json.dumps(direct)))
        self.assertGreater(len(served["data"]["feed"]), 0)

    def test_the_seeded_body_equals_the_miss_path_body(self) -> None:
        miss = self._get().content
        with self.server._PUBLIC_ACTIVITY_LOCK:
            self.server._PUBLIC_ACTIVITY_CACHE.clear()
        self._get("/api/public/league/overview")  # builds the contract, seeds activity
        self.assertEqual(self._get().content, miss)

    # 7 ---------------------------------------------------------------
    def test_concurrent_misses_build_once(self) -> None:
        import httpx

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.server.app), base_url="http://fixture"
            ) as client:
                return await asyncio.gather(
                    *[client.get("/api/public/league/activity") for _ in range(6)]
                )

        results = asyncio.run(run())
        self.assertEqual({r.status_code for r in results}, {200})
        self.assertEqual(len({r.content for r in results}), 1)
        self.assertEqual(self.calls, {"contract": 0, "activity": 1})

    # 8 ---------------------------------------------------------------
    def test_gzip_is_served_from_the_prepared_bytes(self) -> None:
        import httpx

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.server.app), base_url="http://fixture"
            ) as client:
                zipped = await client.get(
                    "/api/public/league/activity", headers={"Accept-Encoding": "gzip"}
                )
                plain = await client.get(
                    "/api/public/league/activity", headers={"Accept-Encoding": "identity"}
                )
                return zipped, plain

        zipped, plain = asyncio.run(run())
        self.assertEqual(zipped.headers.get("content-encoding"), "gzip")
        self.assertIsNone(plain.headers.get("content-encoding"))
        self.assertEqual(zipped.headers.get("vary"), "Accept-Encoding")
        self.assertIn("max-age", plain.headers.get("cache-control", ""))
        # httpx decodes the gzip body; it must be byte-identical to identity.
        self.assertEqual(zipped.content, plain.content)
        _, raw, gz, _ = self.server._PUBLIC_ACTIVITY_CACHE["activity"]
        self.assertEqual(plain.content, raw)
        self.assertEqual(gzip.decompress(gz), raw)
        self.assertEqual(self.calls["activity"], 1)


if __name__ == "__main__":
    unittest.main()
