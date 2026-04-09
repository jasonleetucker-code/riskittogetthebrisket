"""Tests for Next.js frontend migration: runtime default, login, deploy config."""

from __future__ import annotations

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestFrontendRuntimeDefault(unittest.TestCase):
    """FRONTEND_RUNTIME must be hardcoded to 'next' (Static removed)."""

    def test_server_py_uses_next(self):
        """server.py must set FRONTEND_RUNTIME to 'next'."""
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        self.assertIn('FRONTEND_RUNTIME = "next"', text)
        # Static mode must not exist
        self.assertNotIn('FRONTEND_RUNTIME = "static"', text)
        self.assertNotIn("LEGACY_STATIC_DIR", text)


class TestLoginPageUsesServerAuth(unittest.TestCase):
    """Next.js login page must POST to /api/auth/login, not use localStorage."""

    def test_login_page_calls_api_auth_login(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        self.assertIn("/api/auth/login", text)

    def test_login_page_does_not_use_localstorage(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        self.assertNotIn("localStorage", text)

    def test_login_page_sends_username_not_email(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        # The form must send a username field, not email
        self.assertIn("username", text)
        # Should not have an email input type for the primary credential
        self.assertNotIn('type="email"', text)

    def test_login_page_handles_error_response(self):
        login_page = REPO_ROOT / "frontend" / "app" / "login" / "page.jsx"
        text = login_page.read_text()
        # Must handle non-ok responses (401)
        self.assertIn("data.error", text)


class TestSettingsRoute(unittest.TestCase):
    """Server must have an auth-gated /settings route for the Next.js settings page."""

    def test_server_has_settings_route(self):
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        self.assertIn('"/settings"', text)
        self.assertIn("serve_settings", text)


class TestCanonicalOverlayRankComputation(unittest.TestCase):
    """When canonical snapshots lack canonical_consensus_rank (legacy engine),
    the overlay must compute ranks from calibrated_value sorting."""

    def test_overlay_computes_rank_from_calibrated_value(self):
        """_apply_canonical_primary_overlay should compute rank for legacy snapshots."""
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        # Must have the computed_ranks fallback logic
        self.assertIn("computed_ranks", text)
        self.assertIn("has_ccr", text)

    def test_settings_wired_to_trade_logic(self):
        """useSettings hook must exist and be imported by trade page."""
        hook_file = REPO_ROOT / "frontend" / "components" / "useSettings.js"
        self.assertTrue(hook_file.exists())
        trade_page = REPO_ROOT / "frontend" / "app" / "trade" / "page.jsx"
        text = trade_page.read_text()
        self.assertIn("useSettings", text)

    def test_trade_logic_has_pick_year_discount(self):
        """trade-logic.js must have pickYearDiscount function."""
        trade_logic = REPO_ROOT / "frontend" / "lib" / "trade-logic.js"
        text = trade_logic.read_text()
        self.assertIn("pickYearDiscount", text)
        self.assertIn("PICK_YEAR_DISCOUNTS", text)

    def test_effective_value_applies_tep(self):
        """effectiveValue must apply tepMultiplier for TEs."""
        trade_logic = REPO_ROOT / "frontend" / "lib" / "trade-logic.js"
        text = trade_logic.read_text()
        self.assertIn("tepMultiplier", text)
        self.assertIn('pos === "TE"', text)


class TestIdpRankings(unittest.TestCase):
    """IDP players must get ranked by their IDP source values."""

    def test_unified_ranking_function_exists(self):
        """data_contract.py must have _compute_unified_rankings."""
        dc = REPO_ROOT / "src" / "api" / "data_contract.py"
        text = dc.read_text()
        self.assertIn("_compute_unified_rankings", text)
        self.assertIn("OVERALL_RANK_LIMIT", text)

    def test_idp_players_get_ranked(self):
        """IDP players with IDP source values must receive idpRank and canonicalConsensusRank."""
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from src.api.data_contract import build_api_data_contract

        payload = {
            "players": {
                "Test QB": {"_composite": 9000, "_canonicalSiteValues": {"ktc": 9000}, "position": "QB"},
                "Test DL": {"_composite": 6000, "_canonicalSiteValues": {"idpTradeCalc": 5800}},
                "Test LB": {"_composite": 5000, "_canonicalSiteValues": {"idpTradeCalc": 4000}},
            },
            "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
            "sleeper": {"positions": {"Test QB": "QB", "Test DL": "DL", "Test LB": "LB"}},
        }
        contract = build_api_data_contract(payload)
        pa = contract["playersArray"]
        dl = next(p for p in pa if p["displayName"] == "Test DL")
        lb = next(p for p in pa if p["displayName"] == "Test LB")
        qb = next(p for p in pa if p["displayName"] == "Test QB")

        # All players get unified canonicalConsensusRank on one board
        self.assertEqual(qb["ktcRank"], 1)
        self.assertEqual(dl["idpRank"], 1)
        self.assertEqual(lb["idpRank"], 2)
        # Unified board: all three get canonicalConsensusRank (1, 2, or 3)
        ranks = sorted([qb["canonicalConsensusRank"], dl["canonicalConsensusRank"], lb["canonicalConsensusRank"]])
        self.assertEqual(ranks, [1, 2, 3])
        # IDP players have rankDerivedValue
        self.assertGreater(dl["rankDerivedValue"], 0)

    def test_frontend_unified_ranking_exists(self):
        """dynasty-data.js must have computeUnifiedRanks function."""
        dd = REPO_ROOT / "frontend" / "lib" / "dynasty-data.js"
        text = dd.read_text()
        self.assertIn("computeUnifiedRanks", text)
        self.assertIn("OVERALL_RANK_LIMIT", text)
        self.assertIn("SOURCE_KEYS", text)


class TestEdgeAndFinderRoutes(unittest.TestCase):
    """Server must have auth-gated routes for Edge and Finder pages."""

    def test_server_has_edge_route(self):
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        self.assertIn('"/edge"', text)
        self.assertIn("serve_edge", text)

    def test_server_has_finder_route(self):
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        self.assertIn('"/finder"', text)
        self.assertIn("serve_finder", text)

    def test_edge_page_exists(self):
        page = REPO_ROOT / "frontend" / "app" / "edge" / "page.jsx"
        self.assertTrue(page.exists())
        text = page.read_text()
        self.assertIn("buildEdgeProjection", text)

    def test_finder_page_exists(self):
        page = REPO_ROOT / "frontend" / "app" / "finder" / "page.jsx"
        self.assertTrue(page.exists())
        text = page.read_text()
        self.assertIn("/api/trade/finder", text)

    def test_edge_lib_exists(self):
        lib = REPO_ROOT / "frontend" / "lib" / "edge-detection.js"
        self.assertTrue(lib.exists())
        text = lib.read_text()
        self.assertIn("buildEdgeProjection", text)
        self.assertIn("projectPercentileToCurve", text)

    def test_nav_includes_edge_and_finder(self):
        wrapper = REPO_ROOT / "frontend" / "app" / "AppShellWrapper.jsx"
        text = wrapper.read_text()
        self.assertIn("/edge", text)
        self.assertIn("/finder", text)


class TestDeployFrontendRestart(unittest.TestCase):
    """Deploy scripts must handle frontend service lifecycle."""

    def test_deploy_restarts_frontend_service(self):
        deploy_sh = REPO_ROOT / "deploy" / "deploy.sh"
        text = deploy_sh.read_text()
        self.assertIn("frontend_name", text)
        self.assertIn("restart", text)

    def test_verify_checks_frontend_service(self):
        verify_sh = REPO_ROOT / "deploy" / "verify-deploy.sh"
        text = verify_sh.read_text()
        self.assertIn("frontend_name", text)


class TestDeployConfig(unittest.TestCase):
    """Production deployment must include both backend and frontend services."""

    def test_frontend_service_template_exists(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty-frontend.service.template"
        self.assertTrue(template.exists(), "Frontend systemd service template must exist")

    def test_frontend_service_runs_npm_start(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty-frontend.service.template"
        text = template.read_text()
        self.assertIn("npm start", text)
        self.assertIn("PORT=3000", text)

    def test_backend_service_depends_on_frontend(self):
        template = REPO_ROOT / "deploy" / "systemd" / "dynasty.service.template"
        text = template.read_text()
        self.assertIn("frontend.service", text)

    def test_deploy_builds_frontend_by_default(self):
        deploy_sh = REPO_ROOT / "deploy" / "deploy.sh"
        text = deploy_sh.read_text()
        self.assertIn('RUN_FRONTEND_BUILD="${RUN_FRONTEND_BUILD:-true}"', text)

    def test_install_script_handles_frontend_service(self):
        install_sh = REPO_ROOT / "deploy" / "install-systemd-service.sh"
        text = install_sh.read_text()
        self.assertIn("dynasty-frontend.service.template", text)
