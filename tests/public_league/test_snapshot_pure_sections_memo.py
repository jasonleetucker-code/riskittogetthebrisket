"""``records``, ``franchise`` and ``weekly`` are served from the heavy-section memo.

They used to rebuild on every request.  The census of 2026-11-15
(``docs/security/PUBLIC_SURFACE_CENSUS_2026-11-15.md`` section 5) measured
first hits of 4.99 / 3.28 / 1.74 s and 1.80 / 1.49 s right after a publish,
while memoized ``awards`` took 0.58 s in the same pass.  The contract here:

* the bytes served are the bytes the removed per-request build produced
  (same process, same snapshot, same board generation);
* a repeat request builds nothing;
* ``?owner=`` attaches one manager's detail to a COPY: the memoized payload is
  shared by every request and never carries a detail;
* the CSV exports are unchanged, and ``franchise.csv?owner=`` still narrows;
* the post-publish warm fills the new members, and ``franchise`` reuses the
  memoized ``awards`` body exactly as the route always did.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    _HAVE_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAVE_TESTCLIENT = False

from tests.public_league.fixtures import wait_for_public_memo_refreshes

_NEW_MEMBERS = ("records", "franchise", "weekly")


def _route_bytes(payload) -> bytes:
    from fastapi.responses import JSONResponse

    return JSONResponse(content=payload).body


@unittest.skipUnless(_HAVE_TESTCLIENT, "fastapi TestClient (httpx) not installed")
class SnapshotPureSectionsMemoTests(unittest.TestCase):
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
        self.client.get("/api/public/league/history")  # warm the snapshot
        server._heavy_section_cache.clear()
        self.snapshot = server._get_public_snapshot()

    def _get(self, path: str):
        r = self.client.get(f"/api/public/league/{path}")
        self.assertEqual(r.status_code, 200, path)
        return r

    def _removed_build(self, section: str, owner: str = "") -> bytes:
        """The per-request construction the route used before this change."""
        import server
        from src.public_league.public_contract import build_section_payload, public_payload

        payload = build_section_payload(
            self.snapshot,
            section,
            activity_valuation=server._build_public_activity_valuation(),
            team_assignment_contract=server.latest_contract_data,
            awards_section=(
                server._exact_memoized_awards_body(self.snapshot)
                if section == "franchise"
                else None
            ),
        )
        if section == "franchise" and owner:
            detail_map = payload.get("data", {}).get("detail") or {}
            payload["franchiseDetail"] = detail_map.get(str(owner).strip())
        return _route_bytes(public_payload(payload))

    def test_members(self) -> None:
        import server

        for section in _NEW_MEMBERS:
            self.assertIn(section, server._HEAVY_SECTION_KEYS)
        # Time- or artifact-dependent sections stay out: a snapshot key would
        # hide a newer clock reading or ROS artifact.
        for section in ("matchupPreview", "playoffOdds", "rosPlayoffOdds", "rosPower", "overview"):
            self.assertNotIn(section, server._HEAVY_SECTION_KEYS)

    def test_bytes_equal_the_removed_per_request_build(self) -> None:
        for section in _NEW_MEMBERS:
            served = self._get(section).content
            self.assertEqual(served, self._removed_build(section), section)
            # And again from the memo.
            self.assertEqual(self._get(section).content, served, section)

    def test_owner_detail_bytes_and_isolation(self) -> None:
        import server

        for owner in ("owner-A", "owner-X", "nobody"):
            served = self._get(f"franchise?owner={owner}").content
            self.assertEqual(served, self._removed_build("franchise", owner), owner)
        cached = server._heavy_section_cache["franchise"][1]
        self.assertNotIn("franchiseDetail", cached)
        plain = self._get("franchise").json()
        self.assertNotIn("franchiseDetail", plain)
        a = self._get("franchise?owner=owner-A").json()["franchiseDetail"]
        x = self._get("franchise?owner=owner-X").json()["franchiseDetail"]
        self.assertIsNotNone(a)
        self.assertIsNotNone(x)
        self.assertNotEqual(a, x)
        self.assertIsNone(self._get("franchise?owner=nobody").json()["franchiseDetail"])

    def test_repeat_requests_build_nothing(self) -> None:
        import server

        for section in _NEW_MEMBERS:
            self._get(section)
        with mock.patch.object(
            server, "build_section_payload", side_effect=AssertionError("rebuilt")
        ):
            for section in _NEW_MEMBERS:
                self._get(section)
            self._get("franchise?owner=owner-A")

    def test_new_board_generation_is_not_an_exact_hit(self) -> None:
        import server

        self._get("records")
        key = server._heavy_section_cache["records"][0]
        with mock.patch.object(server, "latest_data_etag", "another-board-generation"):
            self.assertNotEqual(server._heavy_section_cache_key(self.snapshot), key)

    def test_csv_exports_unchanged_and_owner_still_narrows(self) -> None:
        from src.public_league import csv_export as public_csv_export
        from src.public_league.public_contract import build_section_payload

        for section in _NEW_MEMBERS:
            served = self._get(f"{section}.csv").text
            _name, expected = public_csv_export.export_section(
                section, build_section_payload(self.snapshot, section)["data"]
            )
            self.assertEqual(served, expected, section)
        everyone = self._get("franchise.csv").text
        one = self._get("franchise.csv?owner=owner-A").text
        _name, expected_one = public_csv_export.export_section(
            "franchise",
            build_section_payload(self.snapshot, "franchise")["data"],
            owner_id="owner-A",
        )
        self.assertEqual(one, expected_one)
        self.assertNotEqual(one, everyone)

    def test_warm_fills_the_new_members_and_franchise_reuses_awards(self) -> None:
        import server
        from src.public_league import awards

        # ``awards`` itself builds through ``_SECTION_BUILDERS`` (bound at
        # import); ``franchise`` falls back to the module attribute only when
        # no exact-key awards body is memoized.  The warm builds ``awards``
        # first, so the fallback must never run.
        with mock.patch.object(
            awards, "build_section", side_effect=AssertionError("franchise recomputed awards")
        ):
            warmed = server._warm_public_sections_once()
        for section in _NEW_MEMBERS:
            self.assertIn(section, warmed)
        with mock.patch.object(
            server, "build_section_payload", side_effect=AssertionError("rebuilt after warm")
        ):
            for section in _NEW_MEMBERS:
                self._get(section)


if __name__ == "__main__":
    unittest.main()
