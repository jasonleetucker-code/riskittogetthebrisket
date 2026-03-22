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


def _pipeline_format_snapshot():
    """Snapshot in the format actually produced by CanonicalAssetValue.to_dict()."""
    return {
        "run_id": "pipeline-run-001",
        "source_snapshot_id": "snap-xyz",
        "assets": [
            {
                "asset_key": "player::josh allen",
                "display_name": "Josh Allen",
                "blended_value": 8200,
                "universe": "offense_vet",
                "source_values": {"DLF_SF": 8500, "KTC_STUB": 7900},
                "source_weights_used": {"DLF_SF": 1.0, "KTC_STUB": 1.0},
                "metadata": {},
            },
            {
                "asset_key": "player::ja marr chase",
                "display_name": "Ja'Marr Chase",
                "blended_value": 8900,
                "universe": "offense_vet",
                "source_values": {"DLF_SF": 8900},
                "source_weights_used": {"DLF_SF": 1.0},
                "metadata": {},
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

    def test_summary_present(self):
        block = build_canonical_comparison_block(_minimal_canonical_snapshot())
        self.assertIn("summary", block)
        summary = block["summary"]
        self.assertEqual(summary["canonicalAssetCount"], 3)
        # No legacy_players passed → no matches
        self.assertEqual(summary["matchedToLegacy"], 0)
        self.assertEqual(summary["unmatchedCanonical"], 3)


class TestComparisonBlockCollision(unittest.TestCase):
    """Duplicate display_names in canonicalComparison must not silently overwrite."""

    def test_keeps_higher_value_on_collision(self):
        snap = {"assets": [
            {"display_name": "Carnell Tate", "blended_value": 7000, "universe": "offense_vet", "source_values": {"A": 1}},
            {"display_name": "Carnell Tate", "blended_value": 8200, "universe": "offense_rookie", "source_values": {"A": 1}},
        ]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assetCount"], 1)
        self.assertEqual(block["assets"]["Carnell Tate"]["canonicalValue"], 8200)

    def test_lower_value_does_not_overwrite(self):
        snap = {"assets": [
            {"display_name": "CJ Allen", "blended_value": 4500, "universe": "idp_vet", "source_values": {"A": 1}},
            {"display_name": "CJ Allen", "blended_value": 2200, "universe": "idp_rookie", "source_values": {"A": 1}},
        ]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assets"]["CJ Allen"]["canonicalValue"], 4500)

    def test_collision_does_not_inflate_count(self):
        snap = {"assets": [
            {"display_name": "Dupe", "blended_value": 5000, "universe": "offense_vet", "source_values": {"A": 1}},
            {"display_name": "Dupe", "blended_value": 6000, "universe": "offense_rookie", "source_values": {"A": 1}},
            {"display_name": "Unique", "blended_value": 4000, "universe": "offense_vet", "source_values": {"A": 1}},
        ]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assetCount"], 2)
        self.assertEqual(block["summary"]["canonicalAssetCount"], 2)

    def test_collision_delta_uses_higher_value(self):
        """When a collision exists and legacy is provided, the delta should use the kept (higher) value."""
        snap = {"assets": [
            {"display_name": "Player X", "blended_value": 3000, "universe": "offense_vet", "source_values": {"A": 1}},
            {"display_name": "Player X", "blended_value": 5000, "universe": "offense_rookie", "source_values": {"A": 1}},
        ]}
        legacy = {"Player X": {"_composite": 4000}}
        block = build_canonical_comparison_block(snap, legacy_players=legacy)
        entry = block["assets"]["Player X"]
        self.assertEqual(entry["canonicalValue"], 5000)
        self.assertEqual(entry["delta"], 1000)  # 5000 - 4000

    def test_unique_names_unaffected(self):
        snap = {"assets": [
            {"display_name": "A", "blended_value": 9000, "source_values": {"X": 1}},
            {"display_name": "B", "blended_value": 8000, "source_values": {"X": 1}},
            {"display_name": "C", "blended_value": 7000, "source_values": {"X": 1}},
        ]}
        block = build_canonical_comparison_block(snap)
        self.assertEqual(block["assetCount"], 3)


class TestPipelineFormatSnapshot(unittest.TestCase):
    """Tests using the actual format produced by CanonicalAssetValue.to_dict()."""

    def test_source_values_dict_counted_correctly(self):
        """Pipeline outputs source_values as dict — should be counted as source count."""
        block = build_canonical_comparison_block(_pipeline_format_snapshot())
        allen = block["assets"]["Josh Allen"]
        self.assertEqual(allen["sourcesUsed"], 2)  # DLF_SF + KTC_STUB

        chase = block["assets"]["Ja'Marr Chase"]
        self.assertEqual(chase["sourcesUsed"], 1)  # DLF_SF only

    def test_source_breakdown_included(self):
        """Per-source canonical scores should appear in sourceBreakdown."""
        block = build_canonical_comparison_block(_pipeline_format_snapshot())
        allen = block["assets"]["Josh Allen"]
        self.assertIn("sourceBreakdown", allen)
        self.assertEqual(allen["sourceBreakdown"]["DLF_SF"], 8500)
        self.assertEqual(allen["sourceBreakdown"]["KTC_STUB"], 7900)

    def test_source_breakdown_absent_for_legacy_format(self):
        """Legacy sources_used (list) should not produce sourceBreakdown."""
        block = build_canonical_comparison_block(_minimal_canonical_snapshot())
        allen = block["assets"]["Josh Allen"]
        self.assertNotIn("sourceBreakdown", allen)


class TestDeltaComputation(unittest.TestCase):
    """Tests for delta computation between canonical and legacy values."""

    def test_delta_computed_when_legacy_provided(self):
        legacy_players = {
            "Josh Allen": {"_finalAdjusted": 8400},
            "Ja'Marr Chase": {"_finalAdjusted": 9100},
        }
        block = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=legacy_players,
        )
        allen = block["assets"]["Josh Allen"]
        self.assertEqual(allen["legacyValue"], 8400)
        self.assertEqual(allen["delta"], 8200 - 8400)  # -200

        chase = block["assets"]["Ja'Marr Chase"]
        self.assertEqual(chase["legacyValue"], 9100)
        self.assertEqual(chase["delta"], 8900 - 9100)  # -200

    def test_no_delta_when_legacy_not_provided(self):
        block = build_canonical_comparison_block(_minimal_canonical_snapshot())
        allen = block["assets"]["Josh Allen"]
        self.assertNotIn("delta", allen)
        self.assertNotIn("legacyValue", allen)

    def test_no_delta_for_unmatched_player(self):
        """Player in canonical but not in legacy should have no delta."""
        legacy_players = {"Other Player": {"_finalAdjusted": 5000}}
        block = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=legacy_players,
        )
        allen = block["assets"]["Josh Allen"]
        self.assertNotIn("delta", allen)

    def test_delta_uses_composite_fallback(self):
        """When _finalAdjusted is missing, falls back to _composite."""
        legacy_players = {"Josh Allen": {"_composite": 8000}}
        block = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=legacy_players,
        )
        allen = block["assets"]["Josh Allen"]
        self.assertEqual(allen["legacyValue"], 8000)
        self.assertEqual(allen["delta"], 8200 - 8000)

    def test_summary_stats_with_deltas(self):
        legacy_players = {
            "Josh Allen": {"_finalAdjusted": 8400},
            "Ja'Marr Chase": {"_finalAdjusted": 9100},
        }
        block = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=legacy_players,
        )
        summary = block["summary"]
        self.assertEqual(summary["matchedToLegacy"], 2)
        self.assertEqual(summary["unmatchedCanonical"], 1)  # "2026 Early 1st"
        self.assertEqual(summary["avgAbsDelta"], 200)  # both are -200
        self.assertEqual(summary["maxAbsDelta"], 200)
        self.assertEqual(summary["avgDelta"], -200)

    def test_summary_no_delta_stats_without_matches(self):
        block = build_canonical_comparison_block(_minimal_canonical_snapshot())
        summary = block["summary"]
        self.assertNotIn("avgAbsDelta", summary)
        self.assertNotIn("maxAbsDelta", summary)


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

    def test_contract_valid_with_deltas(self):
        """Contract validates with delta-enriched comparison block."""
        raw = _minimal_raw_payload()
        payload = build_api_data_contract(raw)
        payload["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=raw["players"],
        )
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"], f"Errors: {report['errors']}")
        self.assertEqual(report["warningCount"], 0)

    def test_contract_valid_with_pipeline_format(self):
        """Contract validates with pipeline-format snapshot (source_values dict)."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = build_canonical_comparison_block(
            _pipeline_format_snapshot()
        )
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"], f"Errors: {report['errors']}")

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

    def test_malformed_summary_produces_warning(self):
        """If canonicalComparison.summary is not a dict, warn."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = {"mode": "shadow", "assets": {}, "summary": "bad"}
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"])
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

    def test_live_values_unchanged_even_with_deltas(self):
        """Delta computation must not mutate the live contract values."""
        raw = _minimal_raw_payload()
        payload_without = build_api_data_contract(raw)
        payload_with = build_api_data_contract(raw)
        payload_with["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot(),
            legacy_players=raw["players"],
        )

        for pw, pwo in zip(payload_with["playersArray"], payload_without["playersArray"]):
            self.assertEqual(pw["values"], pwo["values"])

    def test_runtime_view_keeps_comparison(self):
        """Runtime view (used by Static app) should keep canonicalComparison."""
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["canonicalComparison"] = build_canonical_comparison_block(
            _minimal_canonical_snapshot()
        )
        # Runtime view: pop playersArray, keep everything else
        runtime = dict(payload)
        runtime.pop("playersArray", None)
        runtime["payloadView"] = "runtime"
        self.assertIn("canonicalComparison", runtime)


if __name__ == "__main__":
    unittest.main()
