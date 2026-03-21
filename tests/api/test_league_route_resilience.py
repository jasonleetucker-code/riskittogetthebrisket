import asyncio
import tempfile
import unittest
from pathlib import Path

import server


LEAGUE_TOP_LEVEL_ROUTES = [
    "/league",
    "/league/standings",
    "/league/franchises",
    "/league/awards",
    "/league/draft",
    "/league/trades",
    "/league/records",
    "/league/money",
    "/league/constitution",
    "/league/history",
    "/league/league-media",
]

PRIVATE_ROUTE_EXPECTATIONS = {
    "/app": {"handler": "serve_dashboard", "authRedirect": "/?next=/app&jason=1"},
    "/rankings": {"handler": "serve_rankings", "authRedirect": "/?next=/rankings&jason=1"},
    "/trade": {"handler": "serve_trade", "authRedirect": "/?next=/trade&jason=1"},
    "/calculator": {"handler": "serve_calculator", "authRedirect": "/?next=/calculator&jason=1"},
}


class _DummyUrl:
    def __init__(self, path: str, query: str = ""):
        self.path = path
        self.query = query


class _DummyRequest:
    def __init__(self, path: str = "/calculator", query: str = "", cookies: dict | None = None):
        self.url = _DummyUrl(path, query)
        self.cookies = cookies or {}


class LeagueRouteResilienceTests(unittest.TestCase):
    def test_runtime_authority_lists_all_public_league_routes(self):
        payload = server._runtime_route_authority_payload()
        routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
        self.assertTrue(routes, "routes payload should be present")

        for route in LEAGUE_TOP_LEVEL_ROUTES:
            self.assertIn(route, routes, f"missing route authority entry for {route}")
            self.assertEqual(routes[route].get("handler"), "serve_league_entry")

        self.assertIn("/league/{league_path:path}", routes)
        self.assertFalse(bool(routes["/league"].get("nextProxyFallbackEnabled")))
        self.assertTrue(bool(routes["/league"].get("fallbackEnabled")))
        self.assertEqual(
            str(routes["/league"].get("fallbackAuthority")),
            server.LEAGUE_INLINE_FALLBACK_AUTHORITY,
        )

        readiness = payload.get("deployReadiness") if isinstance(payload.get("deployReadiness"), dict) else {}
        league_shell = readiness.get("leagueShell") if isinstance(readiness.get("leagueShell"), dict) else {}
        self.assertTrue(league_shell, "deploy readiness must include league shell block")
        self.assertIn("ok", league_shell)
        self.assertIn("runtimeFallbackEnabled", league_shell)

    def test_league_route_falls_back_instead_of_500_when_shell_missing(self):
        original_asset_candidates = server._league_asset_candidates
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                missing_path = Path(temp_dir) / "missing" / "league" / "index.html"
                server._league_asset_candidates = lambda _rel: [missing_path]
                response = asyncio.run(server.serve_league_entry("standings"))
        finally:
            server._league_asset_candidates = original_asset_candidates

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("x-route-authority"),
            server.LEAGUE_INLINE_FALLBACK_AUTHORITY,
        )
        body = response.body.decode("utf-8")
        self.assertIn("League shell fallback is active", body)
        self.assertIn("/league/standings", body)

    def test_runtime_authority_preserves_public_private_contract(self):
        payload = server._runtime_route_authority_payload()
        routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}

        self.assertEqual(str(routes.get("/", {}).get("access")), "public")
        for route in LEAGUE_TOP_LEVEL_ROUTES:
            self.assertEqual(str(routes.get(route, {}).get("access")), "public", f"{route} should stay public")

        for route, expected in PRIVATE_ROUTE_EXPECTATIONS.items():
            self.assertIn(route, routes)
            self.assertEqual(str(routes[route].get("access")), "auth-gated")
            self.assertEqual(str(routes[route].get("handler")), expected["handler"])
            self.assertEqual(str(routes[route].get("authRedirect")), expected["authRedirect"])
        self.assertEqual(str(routes["/calculator"].get("redirectTarget")), "/trade")
        self.assertEqual(str(routes["/calculator"].get("runtimeAuthority")), "private-trade-compat-redirect")

    def test_calculator_alias_redirects_to_trade_when_authenticated_and_login_when_not(self):
        unauth_response = asyncio.run(server.serve_calculator(_DummyRequest()))
        self.assertEqual(unauth_response.status_code, 302)
        self.assertEqual(unauth_response.headers.get("location"), "/?next=/calculator&jason=1")
        self.assertEqual(unauth_response.headers.get("x-route-authority"), "auth-gate-redirect")
        self.assertEqual(unauth_response.headers.get("x-route-id"), "auth_gate:/calculator")

        session_id = server._create_auth_session("unit-test")
        try:
            authed_response = asyncio.run(
                server.serve_calculator(
                    _DummyRequest(cookies={server.JASON_AUTH_COOKIE_NAME: session_id})
                )
            )
        finally:
            server.auth_sessions.pop(session_id, None)

        self.assertEqual(authed_response.status_code, 302)
        self.assertEqual(authed_response.headers.get("location"), "/trade")
        self.assertEqual(authed_response.headers.get("x-route-authority"), "private-trade-compat-redirect")
        self.assertEqual(authed_response.headers.get("x-route-id"), "/calculator")

    def test_league_authority_is_not_transferred_by_frontend_runtime_mode(self):
        original_mode = server.FRONTEND_RUNTIME
        try:
            for mode in ("static", "auto", "next"):
                server.FRONTEND_RUNTIME = mode
                server._runtime_route_authority_cache = None
                server._runtime_route_authority_cache_at = 0.0
                payload = server._runtime_route_authority_payload()
                self.assertEqual(str(payload.get("configuredFrontendRuntime")), mode)

                routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
                league = routes.get("/league", {})
                self.assertEqual(str(league.get("handler")), "serve_league_entry")
                self.assertFalse(bool(league.get("nextProxyFallbackEnabled")))
                self.assertTrue(bool(league.get("fallbackEnabled")))
                self.assertIn(
                    str(league.get("runtimeAuthority")),
                    {"public-static-league-shell", server.LEAGUE_INLINE_FALLBACK_AUTHORITY},
                )
        finally:
            server.FRONTEND_RUNTIME = original_mode


if __name__ == "__main__":
    unittest.main()
