import os
import unittest

from src.api.data_contract import build_api_data_contract


class ValueAuthorityGuardrailTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = dict(os.environ)
        os.environ["MIKE_CLAY_ENABLED"] = "0"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _base_payload(self):
        return {
            "sites": [{"key": "ktc"}, {"key": "fantasyCalc"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktc": 10000, "fantasyCalc": 10000, "idpTradeCalc": 10000},
            "players": {},
            "sleeper": {"positions": {}},
        }

    def test_unresolved_position_asset_is_quarantined(self):
        payload = self._base_payload()
        payload["players"]["Mystery Asset"] = {
            "_sites": 2,
            "_rawComposite": 4200,
            "_scoringAdjusted": 4300,
            "_scarcityAdjusted": 4400,
            "_bestBallAdjusted": 4450,
            "_finalAdjusted": 4520,
            "_marketConfidence": 0.72,
            "_canonicalSiteValues": {"ktc": 4300, "fantasyCalc": 4150, "idpTradeCalc": None},
        }

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Mystery Asset")
        bundle = row["valueBundle"]
        guardrails = bundle.get("guardrails") or {}

        self.assertIsNone(row.get("position"))
        self.assertTrue(guardrails.get("quarantined"))
        self.assertIn("position_unresolved", list(guardrails.get("quarantineReasons") or []))
        self.assertIsNone(bundle.get("fullValue"))
        self.assertIsNone(row.get("fullValue"))
        self.assertIsNone(contract["players"]["Mystery Asset"].get("_finalAdjusted"))
        self.assertIsNone(contract["players"]["Mystery Asset"].get("_leagueAdjusted"))

    def test_single_source_low_confidence_value_is_capped(self):
        payload = self._base_payload()
        payload["players"]["Risky Runner"] = {
            "_sites": 1,
            "_rawComposite": 5000,
            "_scoringAdjusted": 5200,
            "_scarcityAdjusted": 5400,
            "_bestBallAdjusted": 5450,
            "_finalAdjusted": 7200,
            "_marketConfidence": 0.40,
            "_canonicalSiteValues": {"ktc": 6100, "fantasyCalc": None, "idpTradeCalc": None},
        }
        payload["sleeper"]["positions"]["Risky Runner"] = "RB"

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Risky Runner")
        bundle = row["valueBundle"]
        guardrails = bundle.get("guardrails") or {}

        self.assertFalse(guardrails.get("quarantined"))
        self.assertTrue(guardrails.get("capped"))
        self.assertIn("single_source_low_confidence_cap", list(guardrails.get("capReasons") or []))
        self.assertLessEqual(int(bundle.get("fullValue") or 0), int(round(5400 * 1.03)))
        self.assertGreater(int(bundle.get("fullValue") or 0), 0)

    def test_persisted_scoring_and_scarcity_layers_take_authority(self):
        payload = self._base_payload()
        payload["players"]["Layer Larry"] = {
            "_sites": 3,
            "_rawComposite": 5000,
            "_scoringAdjusted": 5200,
            "_scarcityAdjusted": 5050,
            "_bestBallAdjusted": 5100,
            "_leagueAdjusted": 7000,
            "_marketConfidence": 0.74,
            "_canonicalSiteValues": {"ktc": 5100, "fantasyCalc": 5000, "idpTradeCalc": 4950},
        }
        payload["sleeper"]["positions"]["Layer Larry"] = "RB"

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Layer Larry")
        bundle = row["valueBundle"]
        layers = bundle.get("layers") or {}
        tags = set(bundle.get("adjustmentTags") or [])
        mapped = contract["players"]["Layer Larry"]

        self.assertEqual(int(bundle.get("rawValue") or 0), 5000)
        self.assertEqual(int(bundle.get("scoringAdjustedValue") or 0), 5200)
        self.assertEqual(int(bundle.get("scarcityAdjustedValue") or 0), 5050)
        self.assertEqual((layers.get("scoring") or {}).get("source"), "backend_scoring_adjusted")
        self.assertEqual((layers.get("scarcity") or {}).get("source"), "backend_scarcity_adjusted")
        self.assertNotIn("scoring_layer_fallback", tags)
        self.assertNotIn("scarcity_layer_fallback", tags)
        self.assertEqual(mapped.get("_scoringAdjusted"), 5200)
        self.assertEqual(mapped.get("_scarcityAdjusted"), 5050)
        self.assertNotEqual(int(bundle.get("rawValue") or 0), int(bundle.get("scoringAdjustedValue") or 0))
        self.assertNotEqual(int(bundle.get("scoringAdjustedValue") or 0), int(bundle.get("scarcityAdjustedValue") or 0))

    def test_full_value_no_longer_aliases_league_adjusted_when_final_missing(self):
        payload = self._base_payload()
        payload["players"]["Fallback Frank"] = {
            "_sites": 3,
            "_rawComposite": 4600,
            "_leagueAdjusted": 7800,
            "_scarcityAdjusted": 4700,
            "_bestBallAdjusted": 4800,
            "_marketConfidence": 0.78,
            "_canonicalSiteValues": {"ktc": 5000, "fantasyCalc": 4700, "idpTradeCalc": 4650},
        }
        payload["sleeper"]["positions"]["Fallback Frank"] = "WR"

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Fallback Frank")
        bundle = row["valueBundle"]
        guardrails = bundle.get("guardrails") or {}
        mapped = contract["players"]["Fallback Frank"]
        layers = bundle.get("layers") or {}

        self.assertEqual(guardrails.get("finalAuthorityStatus"), "derived_without_final_adjusted")
        self.assertEqual((bundle.get("layers") or {}).get("full", {}).get("baseSource"), "derived_best_ball_final")
        self.assertEqual(int(bundle.get("fullValue") or 0), int(bundle.get("bestBallAdjustedValue") or 0))
        self.assertEqual((layers.get("scoring") or {}).get("source"), "fallback_league_adjusted")
        self.assertEqual((layers.get("scarcity") or {}).get("source"), "backend_scarcity_adjusted")
        self.assertIn("scoring_layer_fallback", set(bundle.get("adjustmentTags") or []))
        self.assertIsNone(mapped.get("_finalAdjusted"))
        self.assertEqual(mapped.get("_leagueAdjusted"), row["values"]["scoringAdjusted"])

    def test_summary_and_diagnostics_include_guardrail_counts(self):
        payload = self._base_payload()
        payload["players"]["Unknown U"] = {
            "_sites": 2,
            "_rawComposite": 3000,
            "_scoringAdjusted": 3200,
            "_scarcityAdjusted": 3300,
            "_bestBallAdjusted": 3400,
            "_finalAdjusted": 3500,
            "_marketConfidence": 0.66,
            "_canonicalSiteValues": {"ktc": 3200, "fantasyCalc": 3050, "idpTradeCalc": None},
        }
        payload["players"]["Cap C"] = {
            "_sites": 1,
            "_rawComposite": 5000,
            "_scoringAdjusted": 5200,
            "_scarcityAdjusted": 5400,
            "_bestBallAdjusted": 5450,
            "_finalAdjusted": 7200,
            "_marketConfidence": 0.40,
            "_canonicalSiteValues": {"ktc": 6000, "fantasyCalc": None, "idpTradeCalc": None},
        }
        payload["sleeper"]["positions"]["Cap C"] = "RB"

        contract = build_api_data_contract(payload)
        coverage = (contract.get("valueAuthority") or {}).get("coverage") or {}
        diagnostics = contract.get("valueResolverDiagnostics") or {}

        self.assertGreaterEqual(int(coverage.get("finalQuarantinedAssets") or 0), 1)
        self.assertGreaterEqual(int(coverage.get("finalCappedAssets") or 0), 1)
        self.assertIn("quarantinedAssets", diagnostics)
        self.assertIn("cappedAssets", diagnostics)
        self.assertIn("guardrailSamples", diagnostics)

    def test_source_count_uses_positive_canonical_values_not_declared_sites(self):
        payload = self._base_payload()
        payload["players"]["Ghost Source"] = {
            "_sites": 3,
            "_rawComposite": 2100,
            "_scoringAdjusted": 2150,
            "_scarcityAdjusted": 2200,
            "_marketConfidence": 0.61,
            "_canonicalSiteValues": {"ktc": None, "fantasyCalc": None, "idpTradeCalc": None},
            "_fallbackValue": True,
        }
        payload["sleeper"]["positions"]["Ghost Source"] = "WR"

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Ghost Source")
        bundle = row["valueBundle"] or {}
        source_coverage = bundle.get("sourceCoverage") or {}

        self.assertEqual(int(row.get("sourceCount") or 0), 0)
        self.assertEqual(int(source_coverage.get("count") or 0), 0)
        self.assertEqual(int(contract["players"]["Ghost Source"].get("_sites") or 0), 0)

    def test_idp_signal_without_position_is_inferred_to_idp_bucket(self):
        payload = self._base_payload()
        payload["players"]["Deep Defender"] = {
            "_sites": 1,
            "_rawComposite": 2900,
            "_scoringAdjusted": 2950,
            "_scarcityAdjusted": 3000,
            "_marketConfidence": 0.49,
            "_canonicalSiteValues": {"ktc": None, "fantasyCalc": None, "idpTradeCalc": 3050},
            "_assetClass": "idp",
        }

        contract = build_api_data_contract(payload)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Deep Defender")
        bundle = row["valueBundle"] or {}
        guardrails = bundle.get("guardrails") or {}
        source_coverage = bundle.get("sourceCoverage") or {}

        self.assertEqual(row.get("position"), "LB")
        self.assertEqual(row.get("assetClass"), "idp")
        self.assertNotIn("position_unresolved", list(guardrails.get("quarantineReasons") or []))
        self.assertEqual(int(source_coverage.get("totalSites") or 0), 1)


if __name__ == "__main__":
    unittest.main()
