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
    def test_the_default_is_whatever_the_committed_gate_says(self):
        """The default is not a judgement call — it reads the gate.

        This asserted OFF, then ON (on a top-20 study returning +3.59%),
        then OFF again once that study was re-run against a board whose
        IDP rows were no longer priced on a nonexistent scale (ADR-021 /
        ADR-023). Three flips in two days is exactly why the assertion
        should not be a hardcoded boolean anyone can edit to match the
        code.

        So it is derived: the flag may default ON only if EVERY committed
        board-validation study recommends shipping. Flipping the default
        without a passing re-run fails here, and committing a failing
        re-run while the flag is on fails here too — which is the
        direction that actually went wrong.
        """
        import json

        measurements = sorted(
            (REPO / "docs" / "measurements").glob("consensus-edge-board-validation-*.json")
        )
        self.assertTrue(
            measurements,
            "no committed board-validation measurement to read a verdict from",
        )
        verdicts = {
            path.name: (json.loads(path.read_text()).get("decision") or {}).get("recommendation")
            for path in measurements
        }
        # `_decide` emits "ship it (flag ON)", "do not ship yet", or an
        # explicit "inconclusive — ..."; only the first permits ON.
        ships = all(str(v or "").startswith("ship it") for v in verdicts.values())
        self.assertEqual(
            bool(feature_flags._DEFAULTS["consensus_edge"]),
            ships,
            f"the flag default and the committed gate disagree. Verdicts: {verdicts}",
        )

    def test_what_is_unvalidated_is_stated_rather_than_implied(self):
        # The sell side carries no measured edge and every payload has to
        # say so — true whether the flag is on or off, since anyone
        # evaluating it with the env override sees the same payloads.
        from src.consensus_edge import service

        self.assertFalse(service.SELL_SIDE_VALIDATION["validated"])
        self.assertTrue(service.SELL_SIDE_VALIDATION["note"])

    def test_no_component_claims_a_positive_result_it_does_not_have(self):
        # `validated: True` drives the UI's badge. A component may only
        # carry it with an `outcome` of "positive" and an evidence file
        # that exists — the exact combination `mispricing` lost when its
        # rho was re-measured on the repaired board.
        from src.consensus_edge import score

        for name, meta in score.COMPONENT_VALIDATION.items():
            if not meta.get("validated"):
                continue
            self.assertEqual(meta.get("outcome"), "positive", name)
            evidence = meta.get("evidence")
            self.assertTrue(evidence, f"{name} claims validated with no evidence file")
            self.assertTrue((REPO / str(evidence)).is_file(), f"{name}: {evidence} is missing")

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

    def test_the_served_validation_flags_match_the_registry(self):
        # This asserted the validated set was exactly {"mispricing"},
        # which stopped being true when that component's rho was
        # re-measured on the scale-repaired board (ADR-023). What the
        # endpoint owes a caller is that it reports the registry
        # faithfully — not that any particular component is in it.
        from src.consensus_edge import score

        components = self.client.get("/api/consensus-edge/methodology").json()["components"]
        self.assertEqual(set(components), set(score.COMPONENT_VALIDATION))
        for name, meta in score.COMPONENT_VALIDATION.items():
            self.assertEqual(components[name]["validated"], bool(meta["validated"]), name)
            self.assertEqual(components[name]["outcome"], meta["outcome"], name)

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
