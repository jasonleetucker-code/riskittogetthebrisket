"""The router's gate, its refusals, and what it promises about itself."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import server
from src.api import feature_flags

REPO = Path(__file__).resolve().parents[2]


def _registered_paths(app) -> set[str]:
    """Route paths as FastAPI itself publishes them.

    Deliberately reads the OpenAPI schema rather than walking
    ``app.routes``.  ``app.routes`` is an internal representation and its
    shape changes: through FastAPI 0.135 an ``include_router`` call left
    plain routes in the list, so ``{r.path for r in app.routes}`` worked.
    On 0.141 it leaves an ``_IncludedRouter`` wrapper instead, which has
    no ``.path`` — so that expression raises ``AttributeError``, and the
    wrapped routes are not reachable via ``.routes`` or ``.router``
    either (the attribute is ``original_router``).

    Chasing that attribute would just re-break on the next refactor.
    ``app.openapi()["paths"]`` is the public, supported answer to "what
    routes does this app expose", and it reported all five
    consensus-edge paths correctly on both versions.

    One limit worth naming: this cannot see routes registered with
    ``include_in_schema=False``.  None of the routes asserted here are,
    and the HTTP-level tests below are the stronger check regardless —
    they kept passing throughout the 0.141 upgrade, which is how we knew
    the routes were fine and only the introspection was broken.
    """
    return set((app.openapi().get("paths") or {}).keys())


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
    def test_the_flag_defaults_on_and_the_evidence_exists(self):
        """ON since 2026-08-04, and only because the evidence arrived.

        This test asserted OFF for as long as the composite rested on one
        measured component and two declared priors. What changed is not
        a judgement call: Opportunity was measured and zeroed, and the
        board a user actually sees was scored — the top-20 buy list
        returns a median +3.59% cohort-excess over 7 non-overlapping
        folds, beating a random-20 draw in 6 of 7.

        The flag flips only alongside a committed measurement, so this
        asserts both. Turning it on without one should fail here.
        """
        self.assertTrue(feature_flags._DEFAULTS["consensus_edge"])
        measurements = sorted(
            (REPO / "docs" / "measurements").glob("consensus-edge-board-validation-*.json")
        )
        self.assertTrue(
            measurements,
            "the flag is on with no committed board-validation measurement behind it",
        )

    def test_what_is_still_unvalidated_is_stated_rather_than_implied(self):
        # Shipping ON does not mean shipping unqualified. The sell side
        # carries no measured edge and every payload has to say so.
        from src.consensus_edge import service

        self.assertFalse(service.SELL_SIDE_VALIDATION["validated"])
        self.assertTrue(service.SELL_SIDE_VALIDATION["note"])

    def test_routes_are_registered(self):
        paths = _registered_paths(server.app)
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
