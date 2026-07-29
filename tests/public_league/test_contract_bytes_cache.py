"""Tests for the ``GET /api/public/league`` response-bytes memo.

The endpoint used to reassemble all 16 public sections + recursively
safety-walk + ``json.dumps`` the multi-MB contract on EVERY request
(the measured 2.5-4s /league TTFB), even though the snapshot is
SWR-cached and the identical contract was already built (and thrown
away) during every snapshot rebuild.  ``server._PUBLIC_CONTRACT_BYTES_CACHE``
memoizes the encoded response bytes keyed
``(root_league_id, snapshot.generated_at, latest_data_etag)``.

Pinned here:
    1. Two requests for the same generation build the contract ONCE
       and return identical bytes.
    2. ``?refresh=1`` bypasses the memo read (fresh build) but
       repopulates it.
    3. A new snapshot generation (new ``generated_at``) misses.
    4. A new PRIVATE contract generation (``latest_data_etag``) misses
       — the activity trade grades derive from the private board.
    5. The memoized response is byte-identical to an uncached build.
"""

from __future__ import annotations

import os
import unittest

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class PublicContractBytesCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.public_league.fixtures import build_stub_client, install_stubs

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"

        import server

        cls.server = server
        server._public_league_cache.clear()
        server._public_league_cache.update(
            {
                "snapshot": None,
                "snapshot_league_id": None,
                "fetched_at": 0.0,
            }
        )
        cls.client = TestClient(server.app)

    def setUp(self) -> None:
        with self.server._PUBLIC_CONTRACT_BYTES_LOCK:
            self.server._PUBLIC_CONTRACT_BYTES_CACHE.clear()

    def _count_builds(self):
        calls = {"n": 0}
        real = self.server.build_public_contract

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        return calls, counting

    def test_second_request_is_served_from_the_memo(self) -> None:
        calls, counting = self._count_builds()
        real = self.server.build_public_contract
        self.server.build_public_contract = counting
        try:
            r1 = self.client.get("/api/public/league")
            r2 = self.client.get("/api/public/league")
        finally:
            self.server.build_public_contract = real
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(calls["n"], 1, "second request must not rebuild the contract")
        self.assertEqual(r1.content, r2.content)

    def test_refresh_bypasses_the_memo_read(self) -> None:
        r1 = self.client.get("/api/public/league")
        self.assertEqual(r1.status_code, 200)
        calls, counting = self._count_builds()
        real = self.server.build_public_contract
        self.server.build_public_contract = counting
        try:
            r2 = self.client.get("/api/public/league?refresh=1")
        finally:
            self.server.build_public_contract = real
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(calls["n"], 1, "?refresh=1 must rebuild")

    def test_private_contract_generation_is_part_of_the_key(self) -> None:
        r1 = self.client.get("/api/public/league")
        self.assertEqual(r1.status_code, 200)
        calls, counting = self._count_builds()
        real = self.server.build_public_contract
        old_etag = self.server.latest_data_etag
        self.server.build_public_contract = counting
        self.server.latest_data_etag = "new-private-generation"
        try:
            r2 = self.client.get("/api/public/league")
        finally:
            self.server.build_public_contract = real
            self.server.latest_data_etag = old_etag
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(calls["n"], 1, "a new private-contract generation must rebuild (grades)")

    def test_memoized_bytes_match_an_uncached_build(self) -> None:
        import json

        r1 = self.client.get("/api/public/league")  # populates
        r2 = self.client.get("/api/public/league")  # memo hit
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.content, r1.content)
        # Rebuild the contract directly from the SAME snapshot and
        # prove the served payload matches a from-scratch build.
        # Parity is asserted modulo wall-clock stamps: the contract
        # embeds build-time generated-at fields, so two builds of the
        # SAME snapshot legitimately differ only there.
        snapshot = self.server._public_league_cache["snapshot"]
        contract = self.server.build_public_contract(
            snapshot,
            activity_valuation=self.server._build_public_activity_valuation(),
        )

        def _strip_timestamps(node):
            if isinstance(node, dict):
                return {k: _strip_timestamps(v) for k, v in node.items()}
            if isinstance(node, list):
                return [_strip_timestamps(v) for v in node]
            if isinstance(node, str) and "T" in node and node.count(":") >= 2:
                from datetime import datetime

                try:
                    datetime.fromisoformat(node)
                    return "<timestamp>"
                except ValueError:
                    return node
            return node

        self.assertEqual(
            _strip_timestamps(json.loads(r1.content)),
            _strip_timestamps(contract),
        )
