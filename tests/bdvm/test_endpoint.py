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

    def test_flag_registered_and_default_on(self):
        """ROLLBACK GUARD, not a restatement of the constant.

        ``bdvm_engine`` shipped ON on 2026-07-28 once real projection
        snapshots existed.  A silent revert to False would not break
        anything loudly — every endpoint would go back to serving a
        well-formed empty payload, and /rankings' Fund gap column
        self-suppresses — so the regression would look exactly like
        "the snapshot is missing again".  This is what tells the two
        apart.
        """
        feature_flags.reload()
        self.assertTrue(feature_flags.is_enabled("bdvm_engine"))

    def test_disabled_flag_returns_503_feature_disabled(self):
        """The OFF path is still the documented rollback, so it stays
        tested — now via the env override rather than the default."""
        os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "0"
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


if __name__ == "__main__":
    unittest.main()
