import unittest

from src.api.data_contract import (
    KTC_RANK_LIMIT,
    _compute_ktc_rankings,
    build_api_data_contract,
    build_api_startup_payload,
    build_canonical_comparison_block,
    validate_api_data_contract,
)
from src.canonical.player_valuation import rank_to_value


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


class TestPositionSafetyAndIdpIntegrity(unittest.TestCase):
    def test_partial_positions_by_id_is_backfilled_from_legacy_id_map(self):
        raw = {
            "players": {
                "Player A": {
                    "_sleeperId": "1",
                    "_composite": 7000,
                    "_rawComposite": 7000,
                    "_finalAdjusted": 7000,
                    "_canonicalSiteValues": {"ktc": 7000},
                    "position": "",
                },
                "Player B": {
                    "_sleeperId": "2",
                    "_composite": 6800,
                    "_rawComposite": 6800,
                    "_finalAdjusted": 6800,
                    "_canonicalSiteValues": {"ktc": 6800},
                    "position": "",
                },
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {
                "positionsById": {"1": "QB"},
                "positions": {"Player A": "QB", "Player B": "WR"},
                "playerIds": {"Player A": "1", "Player B": "2"},
            },
        }
        payload = build_api_data_contract(raw)
        pos_by_name = {r["canonicalName"]: r["position"] for r in payload["playersArray"]}
        self.assertEqual(pos_by_name["Player A"], "QB")  # explicit positionsById
        self.assertEqual(pos_by_name["Player B"], "WR")  # backfilled from legacy map
        self.assertEqual(payload["sleeper"]["positionsById"]["2"], "WR")

    def test_canonical_offense_position_wins_over_name_based_idp_map(self):
        raw = {
            "players": {
                "Josh Allen": {
                    "_sleeperId": "111",
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000},
                    "position": "QB",
                },
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {
                "positions": {"Josh Allen": "LB"},
                "playerIds": {"Josh Allen": "111"},
            },
        }
        payload = build_api_data_contract(raw)
        allen = payload["playersArray"][0]
        self.assertEqual(allen["position"], "QB")
        self.assertEqual(allen["assetClass"], "offense")

    def test_rankings_pool_not_shrunk_by_partial_positions_by_id(self):
        raw = {
            "players": {
                "QB One": {
                    "_sleeperId": "11",
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000},
                    "position": "",
                },
                "WR Two": {
                    "_sleeperId": "22",
                    "_composite": 8500,
                    "_rawComposite": 8500,
                    "_finalAdjusted": 8500,
                    "_canonicalSiteValues": {"ktc": 8500},
                    "position": "",
                },
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {
                "positionsById": {"11": "QB"},  # partial on purpose
                "positions": {"QB One": "QB", "WR Two": "WR"},
                "playerIds": {"QB One": "11", "WR Two": "22"},
            },
        }
        payload = build_api_data_contract(raw)
        ranked = [r for r in payload["playersArray"] if r.get("ktcRank")]
        self.assertEqual(len(ranked), 2)
        self.assertEqual({r["canonicalName"] for r in ranked}, {"QB One", "WR Two"})

    def test_fallback_position_requires_stable_id_match(self):
        raw = {
            "players": {
                "Alex Carter (OFF)": {
                    "_sleeperId": "1001",
                    "_composite": 5000,
                    "_rawComposite": 5000,
                    "_finalAdjusted": 5000,
                    "_canonicalSiteValues": {"ktc": 5000},
                    "position": "",
                },
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {
                "positions": {"Alex Carter (OFF)": "LB"},
                "playerIds": {"Alex Carter (OFF)": "2002"},
                "positionsById": {"2002": "LB"},
            },
        }
        payload = build_api_data_contract(raw)
        row = payload["playersArray"][0]
        # No stable-ID match -> keep canonical unknown instead of guessing from name.
        self.assertIsNone(row["position"])

    def test_idp_pool_validation_fails_when_idp_data_present_but_output_tiny(self):
        raw = {
            "players": {
                f"LB Player {i}": {
                    "_sleeperId": str(i),
                    "_composite": 4000 + i,
                    "_rawComposite": 4000 + i,
                    "_finalAdjusted": 4000 + i,
                    "_canonicalSiteValues": {"ktc": 4000 + i},
                    "position": "LB",
                }
                for i in range(4)
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {"positionsById": {str(i): "LB" for i in range(4)}},
        }
        payload = build_api_data_contract(raw)
        report = validate_api_data_contract(payload)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("implausibly tiny IDP pool" in err for err in report["errors"]),
            report["errors"],
        )

    def test_idp_pool_validation_passes_with_plausible_defensive_pool(self):
        players = {}
        for i in range(10):
            players[f"Defender {i}"] = {
                "_sleeperId": f"d{i}",
                "_composite": 3500 + i,
                "_rawComposite": 3500 + i,
                "_finalAdjusted": 3500 + i,
                "_canonicalSiteValues": {"ktc": 3500 + i},
                "position": "LB" if i % 2 == 0 else "DL",
            }
        players["Offense Anchor"] = {
            "_sleeperId": "o1",
            "_composite": 9000,
            "_rawComposite": 9000,
            "_finalAdjusted": 9000,
            "_canonicalSiteValues": {"ktc": 9000},
            "position": "QB",
        }
        payload = build_api_data_contract({
            "players": players,
            "sites": [{"key": "ktc"}],
            "sleeper": {"positionsById": {f"d{i}": ("LB" if i % 2 == 0 else "DL") for i in range(10)}},
        })
        report = validate_api_data_contract(payload)
        self.assertTrue(report["ok"], report["errors"])

    def test_validation_fails_if_offense_player_emitted_as_idp(self):
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["playersArray"][0]["position"] = "LB"
        report = validate_api_data_contract(payload)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("offense players emitted in IDP buckets" in err for err in report["errors"]),
            report["errors"],
        )

    def test_name_collision_cannot_reclassify_offense_with_backfill(self):
        raw = {
            "players": {
                "Alex Smith": {
                    "_sleeperId": "off-1",
                    "_composite": 7000,
                    "_rawComposite": 7000,
                    "_finalAdjusted": 7000,
                    "_canonicalSiteValues": {"ktc": 7000},
                    "position": "QB",
                },
                "Alex Smith IDP": {
                    "_sleeperId": "def-2",
                    "_composite": 4200,
                    "_rawComposite": 4200,
                    "_finalAdjusted": 4200,
                    "_canonicalSiteValues": {"ktc": 4200},
                    "position": "",
                },
            },
            "sites": [{"key": "ktc"}],
            "sleeper": {
                "positionsById": {"def-2": "LB"},  # offense id intentionally missing
                "positions": {
                    "Alex Smith": "LB",       # unsafe name map entry (defender)
                    "Alex Smith IDP": "LB",
                },
                "playerIds": {
                    "Alex Smith": "def-2",    # points to defender ID, not offense ID
                    "Alex Smith IDP": "def-2",
                },
            },
        }
        payload = build_api_data_contract(raw)
        by_name = {r["canonicalName"]: r for r in payload["playersArray"]}
        self.assertEqual(by_name["Alex Smith"]["position"], "QB")
        self.assertEqual(by_name["Alex Smith"]["assetClass"], "offense")


class TestComputeKtcRankings(unittest.TestCase):
    """Tests for _compute_ktc_rankings — the backend single source of truth.

    This function stamps ktcRank + rankDerivedValue onto playersArray entries
    and mirrors them back to the legacy players dict.  Both JS frontends then
    consume these pre-computed values instead of recomputing independently.
    """

    def _make_player_row(self, name: str, pos: str, ktc: int) -> dict:
        """Minimal playersArray-shaped row with a KTC site value."""
        return {
            "canonicalName": name,
            "displayName": name,
            "legacyRef": name,
            "position": pos,
            "assetClass": "offense",
            "values": {"overall": ktc, "rawComposite": ktc, "scoringAdjusted": None,
                       "scarcityAdjusted": None, "finalAdjusted": ktc, "displayValue": None},
            "canonicalSiteValues": {"ktc": ktc},
            "sourceCount": 1,
        }

    def test_top_player_gets_rank_1(self):
        rows = [
            self._make_player_row("Alpha", "QB", 9000),
            self._make_player_row("Beta",  "WR", 7000),
        ]
        _compute_ktc_rankings(rows, {})
        alpha = next(r for r in rows if r["canonicalName"] == "Alpha")
        self.assertEqual(alpha["ktcRank"], 1)

    def test_rank_order_follows_ktc_value_descending(self):
        rows = [
            self._make_player_row("Low",  "RB", 3000),
            self._make_player_row("High", "QB", 9000),
            self._make_player_row("Mid",  "WR", 6000),
        ]
        _compute_ktc_rankings(rows, {})
        by_rank = sorted(
            (r for r in rows if "ktcRank" in r),
            key=lambda r: r["ktcRank"],
        )
        self.assertEqual([r["canonicalName"] for r in by_rank], ["High", "Mid", "Low"])

    def test_rank_derived_value_uses_hill_formula(self):
        rows = [self._make_player_row("Solo", "QB", 9999)]
        _compute_ktc_rankings(rows, {})
        self.assertEqual(rows[0]["ktcRank"], 1)
        expected = int(rank_to_value(1))
        self.assertEqual(rows[0]["rankDerivedValue"], expected)
        self.assertEqual(rows[0]["rankDerivedValue"], 9999)

    def test_rank_50_value_matches_hill_formula(self):
        rows = [self._make_player_row(f"P{i}", "WR", 9999 - i * 10) for i in range(60)]
        _compute_ktc_rankings(rows, {})
        rank_50_row = next(r for r in rows if r.get("ktcRank") == 50)
        expected = int(rank_to_value(50))
        self.assertEqual(rank_50_row["rankDerivedValue"], expected)

    def test_picks_excluded(self):
        rows = [
            self._make_player_row("2026 Early 1st", "PICK", 8000),
            self._make_player_row("Real Player",    "QB",   7000),
        ]
        rows[0]["assetClass"] = "pick"
        _compute_ktc_rankings(rows, {})
        pick = next(r for r in rows if r["canonicalName"] == "2026 Early 1st")
        self.assertNotIn("ktcRank", pick)
        real = next(r for r in rows if r["canonicalName"] == "Real Player")
        self.assertEqual(real["ktcRank"], 1)

    def test_unresolved_position_excluded(self):
        rows = [
            self._make_player_row("UnknownGuy", "?",  8000),
            self._make_player_row("KnownGuy",   "QB", 7000),
        ]
        _compute_ktc_rankings(rows, {})
        unknown = next(r for r in rows if r["canonicalName"] == "UnknownGuy")
        self.assertNotIn("ktcRank", unknown)

    def test_zero_ktc_excluded(self):
        rows = [
            self._make_player_row("NoKtc", "WR", 0),
            self._make_player_row("HasKtc", "WR", 5000),
        ]
        _compute_ktc_rankings(rows, {})
        no_ktc = next(r for r in rows if r["canonicalName"] == "NoKtc")
        self.assertNotIn("ktcRank", no_ktc)

    def test_respects_rank_limit(self):
        rows = [self._make_player_row(f"P{i}", "RB", 9000 - i) for i in range(600)]
        _compute_ktc_rankings(rows, {})
        ranked = [r for r in rows if "ktcRank" in r]
        self.assertEqual(len(ranked), KTC_RANK_LIMIT)

    def test_mirrors_to_legacy_players_dict(self):
        rows = [self._make_player_row("Josh Allen", "QB", 9000)]
        legacy = {"Josh Allen": {"ktc": 9000, "_finalAdjusted": 9000}}
        _compute_ktc_rankings(rows, legacy)
        self.assertEqual(legacy["Josh Allen"]["ktcRank"], 1)
        self.assertEqual(legacy["Josh Allen"]["rankDerivedValue"], int(rank_to_value(1)))

    def test_build_api_data_contract_stamps_ktc_rank(self):
        """The full contract builder must include ktcRank in playersArray."""
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000, "_rawComposite": 9000, "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000}, "position": "QB",
                },
                "Ja'Marr Chase": {
                    "_composite": 8500, "_rawComposite": 8500, "_finalAdjusted": 8500,
                    "_canonicalSiteValues": {"ktc": 8500}, "position": "WR",
                },
            },
            "sites": [{"key": "ktc"}],
            "maxValues": {"ktc": 9999},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        ranked_rows = [r for r in contract["playersArray"] if "ktcRank" in r]
        self.assertEqual(len(ranked_rows), 2)
        names_by_rank = {r["ktcRank"]: r["canonicalName"] for r in ranked_rows}
        self.assertEqual(names_by_rank[1], "Josh Allen")
        self.assertEqual(names_by_rank[2], "Ja'Marr Chase")

    def test_build_api_data_contract_stamps_legacy_players_dict(self):
        """Contract builder must also write ktcRank into legacy players dict."""
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000, "_rawComposite": 9000, "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000}, "position": "QB",
                },
            },
            "sites": [{"key": "ktc"}],
            "maxValues": {},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        # The legacy players dict in the contract payload must have ktcRank
        self.assertIn("ktcRank", contract["players"]["Josh Allen"])
        self.assertEqual(contract["players"]["Josh Allen"]["ktcRank"], 1)


if __name__ == "__main__":
    unittest.main()
