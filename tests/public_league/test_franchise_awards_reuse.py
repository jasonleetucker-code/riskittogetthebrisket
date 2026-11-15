"""``franchise`` reuses the memoized awards section instead of rebuilding it.

``/api/public/league/franchise`` recomputed the whole awards section (and the
rivalries) on EVERY request -- twice per franchise page view, because the page
and its OpenGraph image each fetch it.  The full-contract path already hands
``franchise.build_section`` the awards section it built; the section route now
does the same when the heavy-section memo holds awards for EXACTLY this
snapshot and board generation.

The contract this pins: the served bytes are identical either way, and a memo
that is not an exact-key hit (stale, absent) is never used.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests.public_league.fixtures import build_test_snapshot, wait_for_public_memo_refreshes

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False


class BuilderByteIdentityTests(unittest.TestCase):
    def test_reusing_the_projected_awards_body_is_byte_identical(self) -> None:
        from src.public_league.public_contract import build_section_payload

        snapshot = build_test_snapshot()
        fresh = build_section_payload(snapshot, "franchise")
        # What the server memoizes for awards: the PROJECTED section payload.
        awards_body = build_section_payload(snapshot, "awards")["data"]
        reused = build_section_payload(snapshot, "franchise", awards_section=awards_body)
        self.assertEqual(
            json.dumps(fresh, ensure_ascii=False, allow_nan=False),
            json.dumps(reused, ensure_ascii=False, allow_nan=False),
        )
        self.assertTrue(fresh["data"], "precondition: franchise section is non-empty")

    def test_the_reused_awards_body_is_not_mutated(self) -> None:
        from src.public_league.public_contract import build_section_payload

        snapshot = build_test_snapshot()
        awards_body = build_section_payload(snapshot, "awards")["data"]
        before = json.dumps(awards_body, sort_keys=True)
        build_section_payload(snapshot, "franchise", awards_section=awards_body)
        self.assertEqual(json.dumps(awards_body, sort_keys=True), before)

    def test_other_sections_ignore_the_argument(self) -> None:
        from src.public_league.public_contract import build_section_payload

        snapshot = build_test_snapshot()
        junk = {"bySeason": []}
        for section in ("history", "records"):
            self.assertEqual(
                json.dumps(build_section_payload(snapshot, section)),
                json.dumps(build_section_payload(snapshot, section, awards_section=junk)),
            )


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class FranchiseRouteReuseTests(unittest.TestCase):
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

        wait_for_public_memo_refreshes(server)
        # Warm the snapshot, then start every test from an empty heavy memo.
        self.client.get("/api/public/league/history")
        server._heavy_section_cache.clear()

    def _franchise_bytes(self) -> bytes:
        r = self.client.get("/api/public/league/franchise")
        self.assertEqual(r.status_code, 200)
        return r.content

    def test_memo_hit_serves_the_same_bytes_without_recomputing_awards(self) -> None:
        from src.public_league import awards

        without_memo = self._franchise_bytes()
        self.assertEqual(self.client.get("/api/public/league/awards").status_code, 200)
        with mock.patch.object(awards, "build_section", wraps=awards.build_section) as spy:
            with_memo = self._franchise_bytes()
        self.assertEqual(spy.call_count, 0, "an exact memo hit must not rebuild awards")
        self.assertEqual(with_memo, without_memo)

    def test_without_a_memo_awards_is_built_standalone(self) -> None:
        from src.public_league import awards

        with mock.patch.object(awards, "build_section", wraps=awards.build_section) as spy:
            self._franchise_bytes()
        self.assertEqual(spy.call_count, 1)

    def test_a_stale_generation_entry_is_never_used(self) -> None:
        import server

        self.assertEqual(self.client.get("/api/public/league/awards").status_code, 200)
        snapshot = server._get_public_snapshot()
        self.assertIsNotNone(server._exact_memoized_awards_body(snapshot))
        key, payload, started = server._heavy_section_cache["awards"]
        server._heavy_section_cache["awards"] = (("other", "gen", key[2]), payload, started)
        self.assertIsNone(server._exact_memoized_awards_body(snapshot))
