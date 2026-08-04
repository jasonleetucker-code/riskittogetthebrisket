"""Tests for Next.js frontend migration: runtime default, login, deploy config."""

from __future__ import annotations

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestFrontendRuntimeDefault(unittest.TestCase):
    """The backend must not serve pages under any runtime setting (#555).

    This class used to assert ``FRONTEND_RUNTIME = "next"`` was present in
    server.py, guarding against a relapse to the removed Static frontend.
    That constant is gone: it recorded which frontend THIS PROCESS served
    pages from, and this process serves no pages. It had no runtime reader
    even before the deletion — ``docs/OWNER_ACTION_AUDIT_2026-07-29.md``
    already listed it "obsolete as a variable".

    The underlying concern — no second frontend, no fallback shell — is
    still worth guarding, so the assertions are inverted rather than
    dropped. Every symbol below is one the deleted proxy needed, so any of
    them reappearing means page serving came back.
    """

    def test_server_py_serves_no_frontend(self):
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        # The removed Static frontend, still guarded.
        self.assertNotIn('FRONTEND_RUNTIME = "static"', text)
        self.assertNotIn("LEGACY_STATIC_DIR", text)
        # The page proxy and its helpers. A comment may NAME these (this
        # PR leaves several explaining what went and why), so match on the
        # definition, not on a bare mention.
        for symbol in ("_proxy_next", "_serve_app_shell", "_require_auth_or_redirect"):
            self.assertNotIn(
                f"def {symbol}(",
                text,
                f"{symbol} is defined again — the page proxy is back (#555)",
            )
        self.assertNotIn(
            '@app.get("/{full_path:path}"',
            text,
            "the page catch-all is back — this is the route that actually "
            "served every page, so its return is the whole regression",
        )


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


# ``TestSettingsRoute`` was here, asserting server.py contained the string
# ``"/settings"`` and a ``serve_settings`` handler. Both went with the page
# proxy (#555): Next serves /settings, and its auth gate is
# frontend/middleware.js, which frontend/__tests__/public-routes.test.js
# pins as private.
#
# Worth noting HOW this test breaks, because it is the shape most likely to
# be missed next time: it reads server.py AS TEXT and makes no HTTP
# request, so no route-shaped grep, no route-table assertion and no live
# probe would ever have surfaced it. It only appears when the suite runs.


class TestCanonicalOverlayRemoved(unittest.TestCase):
    """The deprecated canonical overlay path has been fully removed from
    server.py.  The authoritative ranking pipeline is build_api_data_contract
    in src/api/data_contract.py; any re-introduction of a side pipeline should
    trip this guard."""

    def test_overlay_helper_is_absent(self):
        """server.py must not define or call _apply_canonical_primary_overlay."""
        server_py = REPO_ROOT / "server.py"
        text = server_py.read_text()
        self.assertNotIn("_apply_canonical_primary_overlay", text)
        self.assertNotIn("canonical overlay applied", text.lower())

    def test_settings_wired_to_trade_logic(self):
        """useSettings hook must exist and be imported by trade page."""
        hook_file = REPO_ROOT / "frontend" / "components" / "useSettings.js"
        self.assertTrue(hook_file.exists())
        trade_page = REPO_ROOT / "frontend" / "app" / "trade" / "page.jsx"
        text = trade_page.read_text()
        self.assertIn("useSettings", text)

    def test_trade_logic_does_not_reapply_pick_year_discount(self):
        """trade-logic.js must NOT re-discount future picks.

        The future-year pick discount is backend-authoritative: the
        canonical pipeline (``src/api/data_contract.py::
        _pick_year_discount_for``, keyed off the self-rolling
        ``current_rookie_draft_year()``) bakes it into every pick's
        ``rankDerivedValue`` before the contract reaches the frontend.
        The old client-side ``pickYearDiscount`` /
        ``PICK_YEAR_DISCOUNTS`` helper double-discounted with divergent,
        non-self-rolling constants and has been removed.  This pins
        that it is not reintroduced (mirrors the TEP invariant below).
        """
        trade_logic = REPO_ROOT / "frontend" / "lib" / "trade-logic.js"
        text = trade_logic.read_text()
        self.assertNotIn("PICK_YEAR_DISCOUNTS", text)
        self.assertNotIn("settings.pickCurrentYear", text)
        # The backend stays the single source of truth for the discount.
        self.assertIn(
            "_pick_year_discount_for",
            REPO_ROOT.joinpath("src", "api", "data_contract.py").read_text(),
        )

    def test_effective_value_does_not_apply_tep(self):
        """effectiveValue must NOT multiply TE values by tepMultiplier.

        TE premium is backend-authoritative as of 2026-04-15: the
        backend canonical ranking pipeline
        (``src/api/data_contract.py::_compute_unified_rankings``) bakes
        the TEP boost into every TE row's ``rankDerivedValue`` stamp
        before the contract reaches the frontend.  Multiplying again
        on render would double-boost every TE whenever TEP > 1.0 and
        would completely miss the TEP-native source carve-out
        (dynastyNerdsSfTep).  This test pins that the frontend never
        reintroduces a client-side TEP multiplication.
        """
        trade_logic = REPO_ROOT / "frontend" / "lib" / "trade-logic.js"
        text = trade_logic.read_text()
        # effectiveValue must NOT multiply by tepMultiplier.  The
        # frontend may still MENTION tepMultiplier in doc comments
        # (explaining that it's backend-authoritative), so we only
        # guard against the literal multiplication pattern the old
        # implementation used.
        self.assertNotIn("val *= settings.tepMultiplier", text)
        self.assertNotIn("*= tepMultiplier", text)
        # Settings wiring still lives in useSettings + dynasty-data.
        settings_hook = REPO_ROOT / "frontend" / "components" / "useSettings.js"
        self.assertIn("tepMultiplier", settings_hook.read_text())


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
                "Test QB": {
                    "_composite": 9000,
                    "_canonicalSiteValues": {"ktcSfTep": 9000},
                    "position": "QB",
                },
                "Test DL": {"_composite": 6000, "_canonicalSiteValues": {"idpTradeCalc": 5800}},
                "Test LB": {"_composite": 5000, "_canonicalSiteValues": {"idpTradeCalc": 4000}},
            },
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
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
        ranks = sorted(
            [
                qb["canonicalConsensusRank"],
                dl["canonicalConsensusRank"],
                lb["canonicalConsensusRank"],
            ]
        )
        self.assertEqual(ranks, [1, 2, 3])
        # IDP players have rankDerivedValue
        self.assertGreater(dl["rankDerivedValue"], 0)

    def test_frontend_is_backend_authoritative_materializer(self):
        """dynasty-data.js must be a pure materializer over the backend
        canonical contract — no JS-side ranking engine, no dead
        ``computeUnifiedRanks`` / ``SOURCE_KEYS`` / ``OVERALL_RANK_LIMIT``
        symbols (either active code or stale comment strings).  The
        unified ranking function lives exclusively at
        ``src/api/data_contract.py::_compute_unified_rankings``.
        """
        dd = REPO_ROOT / "frontend" / "lib" / "dynasty-data.js"
        text = dd.read_text()
        # Must read the backend-stamped fields verbatim
        self.assertIn("canonicalConsensusRank", text)
        self.assertIn("rankDerivedValue", text)
        self.assertIn("export function buildRows", text)
        # Must NOT re-introduce the removed frontend engine symbols
        self.assertNotIn("computeUnifiedRanks", text)
        self.assertNotIn("OVERALL_RANK_LIMIT", text)
        self.assertNotIn("SOURCE_KEYS", text)


class TestEdgeAndFinderRoutes(unittest.TestCase):
    """Server must have auth-gated routes for Edge and Finder pages.

    2026-07-29: the Finder page merged into /rankings.  It was a second
    copy of the rankings table wearing five saved filters, computing
    nothing the board could not express — so the presets moved onto the
    board as ``SCREENS`` (carried over verbatim; their thresholds differ
    from the board lenses) and /finder became a redirect shim.  The
    route must keep resolving so saved links do not 404; what changed is
    where the filtering lives.
    """

    # ``test_server_has_edge_route`` and ``test_server_has_finder_route``
    # were here. Both asserted server.py's SOURCE TEXT contained a route
    # literal and a handler name; both went with the page proxy (#555).
    #
    # The four methods below are the ones that carry this class's actual
    # claim — that /edge and /finder still resolve for saved links — and
    # they check the frontend, which is where that now lives. Deleting the
    # whole class would have dropped real coverage along with the two dead
    # assertions.

    def test_edge_page_exists(self):
        page = REPO_ROOT / "frontend" / "app" / "edge" / "page.jsx"
        self.assertTrue(page.exists())
        text = page.read_text()
        self.assertIn("useDynastyData", text)
        self.assertIn("edge-helpers", text)

    def test_finder_route_still_resolves_to_the_board(self):
        page = REPO_ROOT / "frontend" / "app" / "finder" / "page.jsx"
        self.assertTrue(page.exists(), "/finder is gone — saved links now 404")
        text = page.read_text()
        self.assertIn("/rankings", text)
        # Every workflow key keeps a mapping, so a bookmarked preset
        # lands on that preset rather than the default board.
        for workflow in ("wr-gaps", "stable-idp", "single-risk", "rookie-spread"):
            self.assertIn(workflow, text)

    def test_the_screener_lives_on_the_board(self):
        helpers = REPO_ROOT / "frontend" / "lib" / "edge-helpers.js"
        text = helpers.read_text()
        self.assertIn("export const SCREENS", text)
        for workflow in ("wr-gaps", "stable-idp", "single-risk", "rookie-spread"):
            self.assertIn(workflow, text)

    def test_nav_includes_edge(self):
        # R1 moved the navigation IA out of AppShellWrapper.jsx into the
        # pure-data model in frontend/lib/nav-model.js — every nav
        # surface (top bar, mobile drawer, /more site map, command
        # palette) renders from it, so it is the source of truth for
        # "is a route in the nav".
        #
        # /finder is deliberately NOT here any more: it is a redirect
        # shim, and a nav entry pointing at a redirect is a rung with
        # nothing on it.  Its vocabulary ("screener", "signal blotter")
        # lives on the /rankings entry's keywords so search still finds
        # it.
        nav_model = REPO_ROOT / "frontend" / "lib" / "nav-model.js"
        text = nav_model.read_text()
        self.assertIn('"/edge"', text)
        self.assertIn("screener", text)


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
        # ExecStart must invoke `npm start` via the __NPM_BIN__
        # placeholder, which install-systemd-service.sh substitutes at
        # install time with an absolute path to npm (system-wide or
        # nvm-managed).  See deploy/install-systemd-service.sh
        # resolve_npm_bin_for_systemd().
        self.assertIn("ExecStart=__NPM_BIN__ start", text)
        self.assertIn("__NODE_BIN_DIR__", text)
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
