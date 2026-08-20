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
        _public_league_cache.update(
            {
                "snapshot": None,
                "snapshot_league_id": None,
                "fetched_at": 0.0,
            }
        )
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

    def test_ros_power_default_lens_is_forward_looking(self) -> None:
        from src.ros import power_v2

        r = self.client.get("/api/public/league/rosPower")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data"]["lens"], power_v2.LENS_FORWARD_LOOKING)

    def test_ros_power_results_only_lens_is_reachable_over_http(self) -> None:
        """V1-52 step 1 shipped the results-only lens inside power_v2, but
        nothing threaded it through the HTTP route — the query param did
        not exist. This is the plumbing that closes that gap."""
        from src.ros import power_v2

        r = self.client.get("/api/public/league/rosPower?lens=results_only")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data"]["lens"], power_v2.LENS_RESULTS_ONLY)
        # A real ranking, not a passthrough of the default payload — the
        # fixture has real weekly matchups so results-only components
        # (wl_record, ppg, all_play, streak) survive without a team
        # strength file.
        self.assertTrue(body["data"]["currentRanking"])

    def test_ros_power_unknown_lens_rejected(self) -> None:
        r = self.client.get("/api/public/league/rosPower?lens=bogus")
        self.assertEqual(r.status_code, 400)
        self.assertIn("availableLenses", r.json())

    def test_lens_param_is_a_noop_outside_ros_power(self) -> None:
        # The lens only means something for rosPower; every other section
        # must ignore it silently rather than erroring on an unrecognized
        # query param that happens to be present.
        r = self.client.get("/api/public/league/overview?lens=results_only")
        self.assertEqual(r.status_code, 200)

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

    def test_metrics_endpoint_exposes_counters(self) -> None:
        # Prime the cache at least once so the counters move.
        self.client.get("/api/public/league?refresh=1")
        r = self.client.get("/api/public/league/metrics")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("leagueId", body)
        self.assertIn("cacheTtlSeconds", body)
        self.assertIn("metrics", body)
        m = body["metrics"]
        for key in (
            "cache_hit",
            "cache_stale_served",
            "cache_miss_cold_rebuild",
            "rebuild_count",
            "rebuild_failures",
            "total_served",
            "cache_hit_ratio",
        ):
            self.assertIn(key, m)
        # Refresh triggered at least one rebuild.
        self.assertGreaterEqual(m["rebuild_count"], 1)
        # Metrics endpoint should not be cached by clients.
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_heavy_section_is_single_flight_cached(self) -> None:
        """playoffOdds (a 10k-sim Monte Carlo) must be memoized per
        snapshot: repeated requests reuse one build instead of each
        launching an independent GIL-bound simulation in the threadpool.
        """
        import server

        # Warm a single shared snapshot so both section calls key to it.
        self.client.get("/api/public/league?refresh=1")
        server._heavy_section_cache.clear()

        calls = {"n": 0}
        real = server.build_section_payload

        def _counting(snapshot, section, **kw):
            if section == "playoffOdds":
                calls["n"] += 1
            return real(snapshot, section, **kw)

        server.build_section_payload = _counting
        try:
            r1 = self.client.get("/api/public/league/playoffOdds")
            r2 = self.client.get("/api/public/league/playoffOdds")
        finally:
            server.build_section_payload = real

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["section"], "playoffOdds")
        # Single-flight: the expensive builder ran once; the second
        # request was served from the per-snapshot cache.
        self.assertEqual(calls["n"], 1)
        # Both responses are identical (same cached payload).
        self.assertEqual(r1.json()["data"], r2.json()["data"])

    def test_archives_section_is_single_flight_cached(self) -> None:
        """archives must be memoized per snapshot, same as playoffOdds.

        It is the most expensive builder in the contract — it rebuilds
        history, activity, draft and awards before its own five walks,
        and the safety walk then recurses the whole ~800 KB result. Run
        fresh per request (which it was until 2026-07-30) that measured
        1.8-34.3s TTFB on production against a ~0.53s baseline for every
        other section, because concurrent requests each launched their
        own build and held an AnyIO worker token for the duration.
        """
        import server

        self.client.get("/api/public/league?refresh=1")
        server._heavy_section_cache.clear()

        calls = {"n": 0}
        real = server.build_section_payload

        def _counting(snapshot, section, **kw):
            if section == "archives":
                calls["n"] += 1
            return real(snapshot, section, **kw)

        server.build_section_payload = _counting
        try:
            r1 = self.client.get("/api/public/league/archives")
            r2 = self.client.get("/api/public/league/archives")
        finally:
            server.build_section_payload = real

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["section"], "archives")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(r1.json()["data"], r2.json()["data"])

    def test_archives_stays_in_the_aggregate_contract(self) -> None:
        """Memoizing is a ROUTING change, not a builder-registry change.

        The tempting-looking alternative — moving archives into
        ``_LAZY_SECTION_BUILDERS`` — drops it from the aggregate
        contract, which is a public shape change, and would not touch
        the per-request rebuild that was the actual cost.
        """
        import server
        from src.public_league.public_contract import (
            _LAZY_SECTION_BUILDERS,
            _SECTION_BUILDERS,
        )

        self.assertIn("archives", server._HEAVY_SECTION_KEYS)
        self.assertIn("archives", _SECTION_BUILDERS)
        self.assertNotIn("archives", _LAZY_SECTION_BUILDERS)

        r = self.client.get("/api/public/league?refresh=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("archives", r.json()["sections"])

    def test_archives_csv_honours_the_kind_qualifier(self) -> None:
        """The regression the ``and not kind`` guard exists for.

        The heavy-section CSV branch never forwards a qualifier, and
        ``export_section`` falls back to trades when ``kind`` is absent.
        Without the guard, adding archives to ``_HEAVY_SECTION_KEYS``
        would make ``archives.csv?kind=waivers`` return a trades CSV
        with a 200 and nothing saying the qualifier was dropped.
        """
        self.client.get("/api/public/league?refresh=1")

        trades = self.client.get("/api/public/league/archives.csv")
        waivers = self.client.get("/api/public/league/archives.csv?kind=waivers")

        self.assertEqual(trades.status_code, 200)
        self.assertEqual(waivers.status_code, 200)
        trades_header = trades.text.splitlines()[0]
        waivers_header = waivers.text.splitlines()[0]
        self.assertNotEqual(
            waivers_header,
            trades_header,
            "?kind=waivers silently returned the default trades export",
        )
        self.assertIn("waiver", waivers.headers.get("content-disposition", "").lower())

    def test_only_playoff_odds_is_cached(self) -> None:
        """Only ``playoffOdds`` (always-simulate, purely snapshot-derived)
        is cached.  The file-backed ROS sections are intentionally NOT
        cached — caching them by snapshot identity would hide fresh
        results the ROS publisher writes between snapshot refreshes — and
        cheap sections like ``awards`` must not silently go stale."""
        import server

        self.assertIn("playoffOdds", server._HEAVY_SECTION_KEYS)
        # File-backed ROS sims read their artifact fresh each request.
        self.assertNotIn("rosPlayoffOdds", server._HEAVY_SECTION_KEYS)
        self.assertNotIn("rosChampionship", server._HEAVY_SECTION_KEYS)
        self.assertNotIn("awards", server._HEAVY_SECTION_KEYS)
        self.assertNotIn("overview", server._HEAVY_SECTION_KEYS)

    def test_metrics_endpoint_never_leaks_private_fields(self) -> None:
        r = self.client.get("/api/public/league/metrics")
        blob = r.text.lower()
        for name in (
            '"ourvalue":',
            '"edgescore":',
            '"tradefinder":',
            '"siteweights":',
            '"siteoverrides":',
        ):
            self.assertNotIn(name, blob)


if __name__ == "__main__":
    unittest.main()
