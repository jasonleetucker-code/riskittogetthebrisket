import unittest

from src.api.data_contract import (
    build_api_data_contract,
    build_api_startup_payload,
    build_canonical_comparison_block,
    validate_api_data_contract,
)


def _minimal_raw_payload():
    """Minimal raw scraper-shaped payload for contract builder tests."""
    return {
        "players": {
            "Josh Allen": {
                "_composite": 8500,
                "_rawComposite": 8500,
                "_finalAdjusted": 8400,
                "_sites": 6,
                "position": "QB",
                "team": "BUF",
            },
            "Ja'Marr Chase": {
                "_composite": 9200,
                "_rawComposite": 9200,
                "_finalAdjusted": 9100,
                "_sites": 7,
                "position": "WR",
                "team": "CIN",
            },
        },
        "sites": [{"key": "ktc"}, {"key": "fantasyCalc"}],
        "maxValues": {"ktc": 9999},
        "sleeper": {"positions": {"Josh Allen": "QB", "Ja'Marr Chase": "WR"}},
    }


def _minimal_canonical_snapshot():
    """Minimal canonical pipeline snapshot matching data/canonical/ shape."""
    return {
        "run_id": "test-run-001",
        "source_snapshot_id": "snap-abc",
        "assets": [
            {
                "asset_key": "josh_allen",
                "display_name": "Josh Allen",
                "blended_value": 8200,
                "universe": "offense_vet",
                "sources_used": ["dlf_superflex"],
            },
            {
                "asset_key": "jamarr_chase",
                "display_name": "Ja'Marr Chase",
                "blended_value": 8900,
                "universe": "offense_vet",
                "sources_used": ["dlf_superflex"],
            },
            {
                "asset_key": "2026_early_1st",
                "display_name": "2026 Early 1st",
                "blended_value": 7500,
                "universe": "picks",
                "sources_used": ["dlf_superflex", "dlf_rookie_superflex"],
            },
        ],
    }


class TestBuildCanonicalComparisonBlock(unittest.TestCase):
    def test_returns_shadow_mode_block(self):
        snap = _minimal_canonical_snapshot()
        block = build_canonical_comparison_block(snap, loaded_at="2026-03-21T00:00:00Z")

        self.assertEqual(block["mode"], "shadow")
        self.assertIn("notice", block)
        self.assertEqual(block["snapshotRunId"], "test-run-001")
        self.assertEqual(block["snapshotSourceId"], "snap-abc")
        self.assertEqual(block["loadedAt"], "2026-03-21T00:00:00Z")
        self.assertEqual(block["assetCount"], 3)

    def test_assets_lookup_by_display_name(self):
        snap = _minimal_canonical_snapshot()
        block = build_canonical_comparison_block(snap)

        self.assertIn("Josh Allen", block["assets"])
        self.assertIn("Ja'Marr Chase", block["assets"])
        self.assertIn("2026 Early 1st", block["assets"])

        allen = block["assets"]["Josh Allen"]
        self.assertEqual(allen["canonicalValue"], 8200)
        self.assertEqual(allen["universe"], "offense_vet")
        self.assertEqual(allen["sourcesUsed"], 1)

    def test_empty_snapshot_produces_zero_assets(self):
        block = build_canonical_comparison_block({"assets": []})
        self.assertEqual(block["assetCount"], 0)
        self.assertEqual(block["assets"], {})
        self.assertEqual(block["mode"], "shadow")

    def test_missing_assets_key_produces_zero_assets(self):
        block = build_canonical_comparison_block({})
        self.assertEqual(block["assetCount"], 0)

    def test_asset_with_no_display_name_skipped(self):
        snap = {"assets": [{"blended_value": 100}]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assetCount"], 0)

    def test_sources_used_as_int(self):
        snap = {"assets": [{"display_name": "Test Player", "blended_value": 500, "sources_used": 3}]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assets"]["Test Player"]["sourcesUsed"], 3)


class TestContractWithCanonicalComparison(unittest.TestCase):
    def test_contract_valid_without_comparison(self):
        """Baseline: contract validates without canonicalComparison (mode=off)."""
        payload = build_api_data_contract(_minimal_raw_payload())
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"], f"Errors: {report['errors']}")

    def test_contract_valid_with_comparison(self):
        """Contract validates with canonicalComparison attached (mode=shadow)."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot()
        )
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"], f"Errors: {report['errors']}")
        self.assertEqual(report["warningCount"], 0)

    def test_comparison_stripped_from_startup_payload(self):
        """canonicalComparison should not appear in startup view."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot()
        )
        startup = build_api_startup_payload(payload)
        self.assertNotIn("canonicalComparison", startup)

    def test_malformed_comparison_produces_warning_not_error(self):
        """If canonicalComparison is present but not a dict, it's a warning, not an error."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = "bad"
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"])  # warnings don't break validity
        self.assertGreater(report["warningCount"], 0)

    def test_live_values_unchanged_when_comparison_attached(self):
        """Attaching canonicalComparison must not alter any live player values."""
        payload_without = build_api_data_contract(_minimal_raw_payload())
        payload_with = build_api_data_contract(_minimal_raw_payload())
        payload_with["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot()
        )

        # Compare playersArray content (the authoritative values).
        for pw, pwo in zip(payload_with["playersArray"], payload_without["playersArray"]):
            self.assertEqual(pw["values"], pwo["values"])
            self.assertEqual(pw["canonicalSiteValues"], pwo["canonicalSiteValues"])
            self.assertEqual(pw["sourceCount"], pwo["sourceCount"])


if __name__ == "__main__":
    unittest.main()
