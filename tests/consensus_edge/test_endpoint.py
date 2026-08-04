"""The router's gate, its refusals, and what it promises about itself."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server
from src.api import feature_flags


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def setUp(self):
        # Bypass the private-API session gate; the flag gate is what is
        # under test here.
        self._auth = mock.patch.object(server, "_is_authenticated", lambda request: True)
        self._auth.start()

    def tearDown(self):
        self._auth.stop()
        os.environ.pop("RISKIT_FEATURE_CONSENSUS_EDGE", None)
        feature_flags.reload()

    def _enable(self):
        os.environ["RISKIT_FEATURE_CONSENSUS_EDGE"] = "1"
        feature_flags.reload()

    def _disable(self):
        os.environ["RISKIT_FEATURE_CONSENSUS_EDGE"] = "0"
        feature_flags.reload()


class TestFlagDefault(_Base):
    def test_the_flag_defaults_off(self):
        # Not a style preference: two of three components have never been
        # validated, so the composite must not be on by default.
        self.assertFalse(feature_flags._DEFAULTS["consensus_edge"])

    def test_routes_are_registered(self):
        paths = {r.path for r in server.app.routes}
        self.assertIn("/api/consensus-edge/players", paths)
        self.assertIn("/api/consensus-edge/top", paths)
        self.assertIn("/api/consensus-edge/methodology", paths)
        self.assertIn("/api/consensus-edge/health", paths)


class TestDisabledBehaviour(_Base):
    def test_board_routes_503_when_disabled(self):
        self._disable()
        for path in (
            "/api/consensus-edge/players",
            "/api/consensus-edge/top",
            "/api/consensus-edge/health",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503, path)
            self.assertEqual(response.json()["error"], "feature_disabled")

    def test_methodology_is_readable_even_when_disabled(self):
        # A user who cannot see the board should still be able to read
        # what it does and does not claim.
        self._disable()
        response = self.client.get("/api/consensus-edge/methodology")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])


class TestHonestyOfThePayload(_Base):
    def test_methodology_admits_the_weights_are_not_fitted(self):
        response = self.client.get("/api/consensus-edge/methodology")
        body = response.json()
        self.assertFalse(body["weightsAreFitted"])
        self.assertTrue(body["experimental"])

    def test_methodology_states_the_validation_target(self):
        body = self.client.get("/api/consensus-edge/methodology").json()
        self.assertIn("market movement", body["validationTarget"])

    def test_only_mispricing_is_marked_validated(self):
        components = self.client.get("/api/consensus-edge/methodology").json()["components"]
        validated = {k for k, v in components.items() if v["validated"]}
        self.assertEqual(validated, {"mispricing"})

    def test_every_response_carries_a_model_version_and_param_set(self):
        body = self.client.get("/api/consensus-edge/methodology").json()
        self.assertTrue(body["modelVersion"])
        self.assertTrue(body["paramSetId"])


class TestPrivacy(_Base):
    def test_consensus_edge_is_not_a_public_route(self):
        # The private-API middleware default-denies, so this only fails
        # if someone adds it to the allowlist.
        self.assertNotIn("/api/consensus-edge/players", server._PUBLIC_API_EXACT)
        for prefix in server._PUBLIC_API_PREFIXES:
            self.assertFalse(
                "/api/consensus-edge/players".startswith(prefix),
                f"consensus-edge is public via prefix {prefix}",
            )


if __name__ == "__main__":
    unittest.main()
