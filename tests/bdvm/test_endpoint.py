"""/api/bdvm/values wiring: auth-gated, flag-gated (default OFF), honest errors."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from src.api import feature_flags


class TestBdvmEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def setUp(self):
        # Bypass the private-API session gate (same pattern as the other
        # endpoint tests); the flag gate below is what we are testing.
        self._auth_patch = mock.patch.object(server, "_is_authenticated", lambda request: True)
        self._auth_patch.start()

    def tearDown(self):
        self._auth_patch.stop()
        os.environ.pop("RISKIT_FEATURE_BDVM_ENGINE", None)
        feature_flags.reload()

    def test_endpoint_requires_auth(self):
        self._auth_patch.stop()
        try:
            resp = self.client.get("/api/bdvm/values")
            self.assertEqual(resp.status_code, 401)
        finally:
            self._auth_patch.start()

    def test_flag_registered_and_default_off(self):
        feature_flags.reload()
        self.assertFalse(feature_flags.is_enabled("bdvm_engine"))

    def test_disabled_flag_returns_503_feature_disabled(self):
        feature_flags.reload()
        resp = self.client.get("/api/bdvm/values")
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body.get("error"), "feature_disabled")
        self.assertEqual(body.get("flag"), "bdvm_engine")

    def test_enabled_flag_proceeds_past_the_gate(self):
        os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "1"
        feature_flags.reload()
        resp = self.client.get("/api/bdvm/values")
        body = resp.json()
        # With the flag ON the request reaches league resolution / data
        # readiness.  In the test environment there is no registry and no
        # loaded contract, so the honest outcomes are those errors — never
        # feature_disabled, and never a fabricated 200 board.
        self.assertNotEqual(body.get("error"), "feature_disabled")
        self.assertIn(resp.status_code, (200, 404, 503))
        if resp.status_code == 200:
            self.assertIn(body.get("status"), ("ok", "no_projection_snapshot"))

    def test_bad_surplus_mode_rejected(self):
        os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "1"
        feature_flags.reload()
        resp = self.client.get("/api/bdvm/values?surplusMode=banana")
        # 400 only if league resolution succeeds first; otherwise the
        # resolver error wins.  Either way it must not be a 500.
        self.assertLess(resp.status_code, 500)

    def test_trade_eval_body_league_key_reaches_the_resolver(self):
        # BdvmTradePanel sends leagueKey in the JSON body (the POST
        # convention).  The route must parse the body BEFORE the gate
        # and thread it through — resolving from the query string only
        # would silently price the trade against the wrong league's
        # replacement levels (review finding, 2026-07-28).
        os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "1"
        feature_flags.reload()
        seen: dict = {}

        def spy_resolve(request, *, body=None, require_loaded_contract=False):
            seen["body"] = body
            raise server.LeagueResolutionError(400, "unknown_league", "short-circuit for test")

        with mock.patch.object(server, "_resolve_league_for_request", spy_resolve):
            resp = self.client.post(
                "/api/bdvm/trade-eval",
                json={
                    "sideA": [{"name": "Someone"}],
                    "sideB": [{"name": "Someone Else"}],
                    "leagueKey": "league_b",
                },
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual((seen.get("body") or {}).get("leagueKey"), "league_b")


if __name__ == "__main__":
    unittest.main()
