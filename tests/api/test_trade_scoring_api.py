import asyncio
import json
import unittest

import server
from src.api.data_contract import build_api_data_contract


class _DummyJsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class TradeScoringApiTests(unittest.TestCase):
    def setUp(self):
        self._prev_contract = server.latest_contract_data
        self.contract = self._build_contract_fixture()
        server.latest_contract_data = self.contract

    def tearDown(self):
        server.latest_contract_data = self._prev_contract

    @staticmethod
    def _build_contract_fixture():
        raw_payload = {
            "sites": [
                {"key": "ktc"},
                {"key": "fantasyCalc"},
                {"key": "idpTradeCalc"},
            ],
            "maxValues": {
                "ktc": 10000,
                "fantasyCalc": 10000,
                "idpTradeCalc": 10000,
            },
            "players": {
                "Alpha QB": {
                    "_sites": 3,
                    "_rawComposite": 5000,
                    "_scoringAdjusted": 5400,
                    "_scarcityAdjusted": 5600,
                    "_bestBallAdjusted": 5650,
                    "_finalAdjusted": 6100,
                    "_marketConfidence": 0.81,
                    "_canonicalSiteValues": {"ktc": 5050, "fantasyCalc": 4980, "idpTradeCalc": None},
                },
                "Beta LB": {
                    "_sites": 3,
                    "_rawComposite": 4100,
                    "_scoringAdjusted": 4200,
                    "_scarcityAdjusted": 4300,
                    "_bestBallAdjusted": 4410,
                    "_finalAdjusted": 4525,
                    "_marketConfidence": 0.74,
                    "_canonicalSiteValues": {"ktc": 4150, "fantasyCalc": 4050, "idpTradeCalc": 4300},
                    "_isRookie": True,
                },
                "Gamma TE": {
                    "_sites": 3,
                    "_rawComposite": 4600,
                    "_scoringAdjusted": 4950,
                    "_scarcityAdjusted": 5050,
                    "_bestBallAdjusted": 5120,
                    "_finalAdjusted": 5280,
                    "_marketConfidence": 0.79,
                    "_canonicalSiteValues": {"ktc": 4700, "fantasyCalc": 4550, "idpTradeCalc": None},
                },
                "2026 Pick 1.01": {
                    "_sites": 3,
                    "_rawComposite": 7000,
                    "_scoringAdjusted": 7000,
                    "_scarcityAdjusted": 7000,
                    "_bestBallAdjusted": 7000,
                    "_finalAdjusted": 7000,
                    "_marketConfidence": 0.66,
                    "_canonicalSiteValues": {"ktc": 7000, "fantasyCalc": 6900, "idpTradeCalc": None},
                },
                # No position mapping on purpose so this is quarantined from final authority.
                "Mystery Asset": {
                    "_sites": 2,
                    "_rawComposite": 3900,
                    "_scoringAdjusted": 4000,
                    "_scarcityAdjusted": 4100,
                    "_bestBallAdjusted": 4200,
                    "_finalAdjusted": 4300,
                    "_marketConfidence": 0.73,
                    "_canonicalSiteValues": {"ktc": 3950, "fantasyCalc": 3850, "idpTradeCalc": None},
                },
            },
            "sleeper": {
                "positions": {
                    "Alpha QB": "QB",
                    "Beta LB": "LB",
                    "Gamma TE": "TE",
                    "2026 Pick 1.01": "PICK",
                }
            },
        }
        return build_api_data_contract(raw_payload)

    def _row_bundle(self, canonical_name: str):
        for row in self.contract.get("playersArray", []):
            if str(row.get("canonicalName")) == canonical_name:
                bundle = row.get("valueBundle") if isinstance(row.get("valueBundle"), dict) else {}
                return row, bundle
        self.fail(f"Missing fixture row for {canonical_name}")

    def _score(self, payload: dict):
        response = asyncio.run(server.score_trade(_DummyJsonRequest(payload)))
        self.assertEqual(response.status_code, 200, response.body.decode("utf-8"))
        return json.loads(response.body.decode("utf-8"))

    def test_backend_resolves_known_assets_and_ignores_bad_fallback_values(self):
        alpha_row, alpha_bundle = self._row_bundle("Alpha QB")
        beta_row, beta_bundle = self._row_bundle("Beta LB")
        pick_row, pick_bundle = self._row_bundle("2026 Pick 1.01")

        payload = {
            "valueBasis": "full",
            "alpha": 1.7,
            "bestBallMode": True,
            "sides": {
                "A": [
                    {"label": "Alpha QB", "fallbackValue": 111},
                    {"label": "2026 Pick 1.01 (from Team X)", "fallbackValue": 222},
                ],
                "B": [
                    {"label": "Beta LB", "fallbackValue": 333},
                ],
                "C": [],
            },
        }
        data = self._score(payload)
        side_a = data["sides"]["A"]
        side_b = data["sides"]["B"]

        resolved_a = {str(entry.get("canonicalName") or entry.get("name")): entry for entry in side_a.get("resolvedEntries", [])}
        resolved_b = {str(entry.get("canonicalName") or entry.get("name")): entry for entry in side_b.get("resolvedEntries", [])}

        self.assertEqual(int(resolved_a["Alpha QB"]["value"]), int(alpha_bundle.get("fullValue")))
        self.assertEqual(int(resolved_a["2026 Pick 1.01"]["value"]), int(pick_bundle.get("fullValue")))
        self.assertEqual(int(resolved_b["Beta LB"]["value"]), int(beta_bundle.get("fullValue")))
        self.assertNotEqual(int(resolved_a["Alpha QB"]["value"]), 111)
        self.assertNotEqual(int(resolved_a["2026 Pick 1.01"]["value"]), 222)
        self.assertNotEqual(int(resolved_b["Beta LB"]["value"]), 333)
        self.assertTrue(str(resolved_b["Beta LB"]["assetClass"]).lower() == "idp")
        self.assertTrue(str(resolved_a["2026 Pick 1.01"]["assetClass"]).lower() == "pick")
        self.assertTrue(bool(side_a.get("weightedTotal")))
        self.assertTrue(bool(side_b.get("weightedTotal")))

    def test_quarantined_asset_excluded_and_manual_override_uses_fallback(self):
        payload = {
            "valueBasis": "full",
            "alpha": 1.678,
            "bestBallMode": True,
            "sides": {
                "A": [
                    {"label": "Mystery Asset", "fallbackValue": 3900},
                ],
                "B": [
                    {"label": "Unknown Manual", "fallbackValue": 1550, "manualOverride": True, "pos": "WR"},
                ],
                "C": [],
            },
        }
        data = self._score(payload)
        side_a = data["sides"]["A"]
        side_b = data["sides"]["B"]

        self.assertEqual(int(side_a["resolution"]["quarantinedExcluded"]), 1)
        unresolved_reasons = [str(row.get("reason")) for row in side_a.get("unresolvedEntries", [])]
        self.assertIn("quarantined_from_final_authority", unresolved_reasons)

        self.assertEqual(int(side_b["resolution"]["fallbackUsed"]), 1)
        resolved_b = side_b.get("resolvedEntries", [])
        self.assertEqual(len(resolved_b), 1)
        self.assertEqual(int(resolved_b[0]["value"]), 1550)
        self.assertEqual(str(resolved_b[0]["resolution"]), "fallback_manual_override")
        self.assertGreater(float(side_b.get("weightedTotal") or 0), 0)

    def test_basis_selection_changes_backend_value(self):
        _, alpha_bundle = self._row_bundle("Alpha QB")
        payload_scoring = {
            "valueBasis": "scoring",
            "alpha": 1.678,
            "bestBallMode": True,
            "sides": {"A": [{"label": "Alpha QB", "fallbackValue": 1}], "B": [], "C": []},
        }
        payload_full = {
            "valueBasis": "full",
            "alpha": 1.678,
            "bestBallMode": True,
            "sides": {"A": [{"label": "Alpha QB", "fallbackValue": 1}], "B": [], "C": []},
        }

        scoring = self._score(payload_scoring)
        full = self._score(payload_full)
        scoring_entry = scoring["sides"]["A"]["resolvedEntries"][0]
        full_entry = full["sides"]["A"]["resolvedEntries"][0]

        self.assertEqual(int(scoring_entry["value"]), int(alpha_bundle.get("scoringAdjustedValue")))
        self.assertEqual(int(full_entry["value"]), int(alpha_bundle.get("fullValue")))
        self.assertNotEqual(int(scoring_entry["value"]), int(full_entry["value"]))

    def test_te_asset_resolves_from_backend_bundle_value(self):
        _, te_bundle = self._row_bundle("Gamma TE")
        payload = {
            "valueBasis": "full",
            "alpha": 1.678,
            "bestBallMode": True,
            "sides": {"A": [{"label": "Gamma TE", "fallbackValue": 99}], "B": [], "C": []},
        }
        data = self._score(payload)
        entry = data["sides"]["A"]["resolvedEntries"][0]
        self.assertEqual(int(entry["value"]), int(te_bundle.get("fullValue")))
        self.assertNotEqual(int(entry["value"]), 99)
        self.assertEqual(str(entry["pos"]).upper(), "TE")

    def test_mixed_resolution_summary_surfaces_backend_fallback_quarantine_and_unresolved_truth(self):
        payload = {
            "valueBasis": "full",
            "alpha": 1.678,
            "bestBallMode": True,
            "sides": {
                "A": [
                    {"label": "Alpha QB", "fallbackValue": 5},
                    {"label": "Gamma TE", "fallbackValue": 6},
                    {"label": "Unknown With Fallback", "fallbackValue": 1200, "pos": "WR"},
                ],
                "B": [
                    {"label": "Beta LB", "fallbackValue": 7},
                    {"label": "2026 Pick 1.01", "fallbackValue": 8},
                ],
                "C": [
                    {"label": "Mystery Asset", "fallbackValue": 3900},
                    {"label": "Unknown No Value"},
                    {"label": "Unknown Manual", "fallbackValue": 2222, "manualOverride": True, "pos": "RB"},
                ],
            },
        }
        data = self._score(payload)

        self.assertEqual(str(data.get("authority")), "backend_trade_scoring_v1")
        summary = data.get("summary") or {}
        self.assertEqual(int(summary.get("inputItems") or 0), 8)
        self.assertEqual(int(summary.get("backendResolved") or 0), 4)
        self.assertEqual(int(summary.get("fallbackUsed") or 0), 2)
        self.assertEqual(int(summary.get("quarantinedExcluded") or 0), 1)
        self.assertEqual(int(summary.get("unresolvedExcluded") or 0), 1)

        side_a = data["sides"]["A"]
        side_c = data["sides"]["C"]
        self.assertEqual(int(side_a["resolution"]["backendResolved"]), 2)
        self.assertEqual(int(side_a["resolution"]["fallbackUsed"]), 1)
        self.assertEqual(int(side_c["resolution"]["fallbackUsed"]), 1)
        self.assertEqual(int(side_c["resolution"]["quarantinedExcluded"]), 1)
        self.assertEqual(int(side_c["resolution"]["unresolvedExcluded"]), 1)

        all_resolved = []
        for key in ("A", "B", "C"):
            all_resolved.extend(data["sides"][key].get("resolvedEntries", []))
        resolutions = {str(entry.get("resolution")) for entry in all_resolved}
        self.assertIn("fallback_unresolved", resolutions)
        self.assertIn("fallback_manual_override", resolutions)


if __name__ == "__main__":
    unittest.main()
