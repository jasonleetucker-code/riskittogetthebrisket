"""End-to-end HTTP tests for the /api/public/league* endpoints.

Uses the FastAPI TestClient so we exercise the actual route handlers,
not just the section builders.  The sleeper client is stubbed via
tests/public_league/fixtures so no network calls are made.
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
class PublicLeagueRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.public_league.fixtures import build_stub_client, install_stubs

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"

        from server import app, _public_league_cache

        # Force the on-process cache to refresh with the stubbed client.
        _public_league_cache.clear()
        _public_league_cache.update({
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
        })
        cls.client = TestClient(app)

    def test_full_contract_returns_expected_shape(self) -> None:
        r = self.client.get("/api/public/league?refresh=1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("contractVersion", body)
        self.assertIn("sections", body)
        self.assertIn("league", body)
        self.assertIn("sectionKeys", body)
        # Overview must be the first public section so the UI front-door
        # is always populated.
        self.assertEqual(body["sectionKeys"][0], "overview")
        for key in ("overview", "history", "rivalries", "awards"):
            self.assertIn(key, body["sections"])

    def test_cache_control_header_present(self) -> None:
        r = self.client.get("/api/public/league")
        self.assertEqual(r.status_code, 200)
        cc = r.headers.get("cache-control", "")
        self.assertIn("public", cc)
        self.assertIn("max-age=60", cc)

    def test_section_endpoint_returns_slim_payload(self) -> None:
        r = self.client.get("/api/public/league/overview")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["section"], "overview")
        self.assertIn("data", body)
        self.assertIn("currentChampion", body["data"])

    def test_franchise_owner_narrowed_detail(self) -> None:
        r = self.client.get("/api/public/league/franchise?owner=owner-B")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("franchiseDetail", body)
        self.assertIsNotNone(body["franchiseDetail"])
        self.assertEqual(body["franchiseDetail"]["ownerId"], "owner-B")

    def test_unknown_section_returns_404(self) -> None:
        r = self.client.get("/api/public/league/nope")
        self.assertEqual(r.status_code, 404)

    def test_full_contract_never_leaks_private_field_names(self) -> None:
        r = self.client.get("/api/public/league")
        self.assertEqual(r.status_code, 200)
        blob = r.text.lower()
        for name in (
            '"ourvalue":',
            '"edgescore":',
            '"tradefinder":',
            '"siteweights":',
            '"siteoverrides":',
            '"rankderivedvalue":',
            '"canonicalsitevalues":',
            '"arbitragescore":',
        ):
            self.assertNotIn(name, blob, msg=f"Leaked private field: {name}")


if __name__ == "__main__":
    unittest.main()
