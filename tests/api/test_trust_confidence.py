"""Tests for trust, confidence, and anomaly fields added to the data contract.

Covers:
  - Confidence bucket computation
  - Anomaly flag rules
  - Market gap direction/magnitude
  - New per-player fields stamped by _compute_unified_rankings
  - Payload-level methodology, dataFreshness, and anomalySummary blocks
"""
from __future__ import annotations

import unittest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    _compute_confidence_bucket,
    _compute_anomaly_flags,
    _compute_market_gap,
    _compute_unified_rankings,
    build_api_data_contract,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_player(name, position, *, ktc=None, idp=None, team="TST"):
    """Build a minimal raw player dict for contract builder tests."""
    sites = {}
    if ktc is not None:
        sites["ktc"] = ktc
    if idp is not None:
        sites["idpTradeCalc"] = idp
    return {
        name: {
            "_composite": max(ktc or 0, idp or 0),
            "_rawComposite": max(ktc or 0, idp or 0),
            "_finalAdjusted": max(ktc or 0, idp or 0),
            "_sites": (1 if ktc else 0) + (1 if idp else 0),
            "position": position,
            "team": team,
            "_canonicalSiteValues": sites,
        }
    }


def _payload_with_players(*player_dicts):
    """Merge multiple _make_player dicts into a minimal contract payload."""
    players = {}
    positions = {}
    for d in player_dicts:
        for name, pdata in d.items():
            players[name] = pdata
            positions[name] = pdata["position"]
    return {
        "players": players,
        "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktc": 9999},
        "sleeper": {"positions": positions},
    }


def _build_and_find(payload, player_name):
    """Build contract and return the named player row from playersArray."""
    contract = build_api_data_contract(payload)
    for row in contract["playersArray"]:
        if row["canonicalName"] == player_name:
            return row
    return None


# ── Confidence bucket unit tests ─────────────────────────────────────────────


class TestConfidenceBucket(unittest.TestCase):

    def test_high_bucket(self):
        bucket, label = _compute_confidence_bucket(2, 20.0)
        self.assertEqual(bucket, "high")
        self.assertIn("High", label)

    def test_high_boundary(self):
        bucket, _ = _compute_confidence_bucket(2, 30.0)
        self.assertEqual(bucket, "high")

    def test_medium_bucket(self):
        bucket, label = _compute_confidence_bucket(2, 50.0)
        self.assertEqual(bucket, "medium")
        self.assertIn("Medium", label)

    def test_medium_boundary(self):
        bucket, _ = _compute_confidence_bucket(2, 80.0)
        self.assertEqual(bucket, "medium")

    def test_low_bucket_wide_spread(self):
        bucket, label = _compute_confidence_bucket(2, 100.0)
        self.assertEqual(bucket, "low")
        self.assertIn("Low", label)

    def test_low_bucket_single_source(self):
        bucket, _ = _compute_confidence_bucket(1, None)
        self.assertEqual(bucket, "low")

    def test_none_bucket_zero_sources(self):
        bucket, label = _compute_confidence_bucket(0, None)
        self.assertEqual(bucket, "none")
        self.assertIn("unranked", label.lower())


# ── Anomaly flag unit tests ──────────────────────────────────────────────────


class TestAnomalyFlags(unittest.TestCase):

    def test_no_flags_for_clean_player(self):
        flags = _compute_anomaly_flags(
            name="Patrick Mahomes",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 1},
            rank_derived_value=9999,
            canonical_sites={"ktc": 9999},
        )
        self.assertEqual(flags, [])

    def test_offense_as_idp(self):
        flags = _compute_anomaly_flags(
            name="Fake Player",
            position="WR",
            asset_class="offense",
            source_ranks={"idpTradeCalc": 50},
            rank_derived_value=5000,
            canonical_sites={"idpTradeCalc": 500},
        )
        self.assertIn("offense_as_idp", flags)

    def test_idp_as_offense(self):
        flags = _compute_anomaly_flags(
            name="Fake Defender",
            position="LB",
            asset_class="idp",
            source_ranks={"ktc": 100},
            rank_derived_value=3000,
            canonical_sites={"ktc": 300},
        )
        self.assertIn("idp_as_offense", flags)

    def test_missing_position(self):
        flags = _compute_anomaly_flags(
            name="Mystery Man",
            position="?",
            asset_class="offense",
            source_ranks={"ktc": 200},
            rank_derived_value=2000,
            canonical_sites={"ktc": 200},
        )
        self.assertIn("missing_position", flags)

    def test_missing_position_empty(self):
        flags = _compute_anomaly_flags(
            name="No Pos",
            position="",
            asset_class="offense",
            source_ranks={"ktc": 200},
            rank_derived_value=2000,
            canonical_sites={"ktc": 200},
        )
        self.assertIn("missing_position", flags)

    def test_retired_or_invalid_name(self):
        flags = _compute_anomaly_flags(
            name="Retired Player Test",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 300},
            rank_derived_value=1500,
            canonical_sites={"ktc": 150},
        )
        self.assertIn("retired_or_invalid_name", flags)

    def test_ol_contamination(self):
        flags = _compute_anomaly_flags(
            name="Joe Lineman",
            position="OL",
            asset_class="offense",
            source_ranks={"ktc": 400},
            rank_derived_value=1000,
            canonical_sites={"ktc": 100},
        )
        self.assertIn("ol_contamination", flags)

    def test_suspicious_disagreement(self):
        flags = _compute_anomaly_flags(
            name="Disagreed Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 10, "idpTradeCalc": 200},
            rank_derived_value=5000,
            canonical_sites={"ktc": 9000, "idpTradeCalc": 500},
        )
        self.assertIn("suspicious_disagreement", flags)

    def test_no_suspicious_disagreement_when_close(self):
        flags = _compute_anomaly_flags(
            name="Agreed Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 10, "idpTradeCalc": 20},
            rank_derived_value=9000,
            canonical_sites={"ktc": 9000, "idpTradeCalc": 8500},
        )
        self.assertNotIn("suspicious_disagreement", flags)

    def test_impossible_value(self):
        flags = _compute_anomaly_flags(
            name="Zero Val Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 50},
            rank_derived_value=0,
            canonical_sites={"ktc": 500},
        )
        self.assertIn("impossible_value", flags)

    def test_impossible_value_none(self):
        flags = _compute_anomaly_flags(
            name="None Val Player",
            position="QB",
            asset_class="offense",
            source_ranks={"ktc": 50},
            rank_derived_value=None,
            canonical_sites={"ktc": 500},
        )
        self.assertIn("impossible_value", flags)


# ── Market gap unit tests ────────────────────────────────────────────────────


class TestMarketGap(unittest.TestCase):

    def test_ktc_higher(self):
        direction, magnitude = _compute_market_gap({"ktc": 10, "idpTradeCalc": 50})
        self.assertEqual(direction, "ktc_higher")
        self.assertEqual(magnitude, 40.0)

    def test_idptc_higher(self):
        direction, magnitude = _compute_market_gap({"ktc": 80, "idpTradeCalc": 20})
        self.assertEqual(direction, "idptc_higher")
        self.assertEqual(magnitude, 60.0)

    def test_equal_ranks(self):
        direction, magnitude = _compute_market_gap({"ktc": 30, "idpTradeCalc": 30})
        self.assertEqual(direction, "none")
        self.assertEqual(magnitude, 0.0)

    def test_single_source_none(self):
        direction, magnitude = _compute_market_gap({"ktc": 10})
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)


# ── Integration: single-source player row ────────────────────────────────────


class TestSingleSourceRow(unittest.TestCase):

    def test_single_source_offense_player(self):
        # Use a unique name that won't match CSV enrichment data on disk
        payload = _payload_with_players(
            _make_player("Zzz Testonly Qb Alpha", "QB", ktc=9500),
        )
        row = _build_and_find(payload, "Zzz Testonly Qb Alpha")
        self.assertIsNotNone(row)
        self.assertTrue(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")
        self.assertIsNone(row["sourceRankSpread"])
        self.assertEqual(row["marketGapDirection"], "none")
        self.assertIsNone(row["marketGapMagnitude"])
        self.assertFalse(row["hasSourceDisagreement"])
        self.assertIsInstance(row["anomalyFlags"], list)

    def test_single_source_idp_player(self):
        payload = _payload_with_players(
            _make_player("Zzz Testonly Lb Alpha", "LB", idp=8000),
        )
        row = _build_and_find(payload, "Zzz Testonly Lb Alpha")
        self.assertIsNotNone(row)
        self.assertTrue(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")


# ── Integration: two-source player row ───────────────────────────────────────


class TestTwoSourceRow(unittest.TestCase):

    def test_two_source_player_tight_agreement(self):
        """Two sources with similar values → high confidence, no disagreement."""
        payload = _payload_with_players(
            _make_player("Two Source Guy", "QB", ktc=9000, idp=8800),
        )
        row = _build_and_find(payload, "Two Source Guy")
        self.assertIsNotNone(row)
        self.assertFalse(row["isSingleSource"])
        self.assertIsNotNone(row["sourceRankSpread"])
        # Both sources exist
        self.assertIn("ktc", row.get("sourceRanks", {}))
        self.assertIn("idpTradeCalc", row.get("sourceRanks", {}))
        # blendedSourceRank should be a number
        self.assertIsNotNone(row["blendedSourceRank"])
        self.assertIsInstance(row["blendedSourceRank"], float)


# ── Integration: unranked player (no source values) ─────────────────────────


class TestUnrankedPlayer(unittest.TestCase):

    def test_unranked_player_gets_defaults(self):
        """A player with no source values should still have trust fields."""
        payload = _payload_with_players(
            _make_player("No Value Guy", "QB"),
        )
        row = _build_and_find(payload, "No Value Guy")
        self.assertIsNotNone(row)
        self.assertEqual(row["confidenceBucket"], "none")
        self.assertEqual(row["anomalyFlags"], [])
        self.assertFalse(row["isSingleSource"])
        self.assertFalse(row["hasSourceDisagreement"])
        self.assertIsNone(row["blendedSourceRank"])
        self.assertIsNone(row["sourceRankSpread"])


# ── Integration: contract payload-level blocks ───────────────────────────────


class TestPayloadLevelBlocks(unittest.TestCase):

    def test_methodology_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        meth = contract.get("methodology")
        self.assertIsNotNone(meth)
        self.assertEqual(meth["version"], contract["contractVersion"])
        self.assertEqual(meth["overallRankLimit"], OVERALL_RANK_LIMIT)
        self.assertIn("formula", meth)
        self.assertIn("confidenceBuckets", meth)
        self.assertIn("anomalyFlags", meth)
        self.assertIsInstance(meth["sources"], list)
        self.assertEqual(len(meth["sources"]), 2)

    def test_data_freshness_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        freshness = contract.get("dataFreshness")
        self.assertIsNotNone(freshness)
        self.assertIn("generatedAt", freshness)
        self.assertIn("sourceTimestamps", freshness)
        self.assertIn("ktc", freshness["sourceTimestamps"])
        self.assertIn("idpTradeCalc", freshness["sourceTimestamps"])

    def test_anomaly_summary_block_present(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        summary = contract.get("anomalySummary")
        self.assertIsNotNone(summary)
        self.assertIn("totalFlagged", summary)
        self.assertIn("flagCounts", summary)

    def test_methodology_formula_matches_constants(self):
        payload = _payload_with_players(
            _make_player("Test QB", "QB", ktc=8000),
        )
        contract = build_api_data_contract(payload)
        formula = contract["methodology"]["formula"]
        self.assertEqual(formula["midpoint"], 45)
        self.assertEqual(formula["slope"], 1.10)
        self.assertEqual(formula["scaleMin"], 1)
        self.assertEqual(formula["scaleMax"], 9999)

    def test_anomaly_summary_counts_flagged_players(self):
        """Build a payload with a player that triggers an anomaly, verify count."""
        # OL player will trigger ol_contamination
        payload = _payload_with_players(
            _make_player("Good QB", "QB", ktc=9000),
            _make_player("OL Guy", "OL", ktc=5000),
        )
        contract = build_api_data_contract(payload)
        summary = contract["anomalySummary"]
        # OL Guy should be flagged
        self.assertGreaterEqual(summary["totalFlagged"], 1)
        self.assertIn("ol_contamination", summary["flagCounts"])


# ── Integration: REQUIRED_PLAYER_KEYS includes new fields ───────────────────


class TestRequiredPlayerKeys(unittest.TestCase):

    def test_new_fields_in_required_keys(self):
        from src.api.data_contract import REQUIRED_PLAYER_KEYS

        self.assertIn("confidenceBucket", REQUIRED_PLAYER_KEYS)
        self.assertIn("anomalyFlags", REQUIRED_PLAYER_KEYS)


if __name__ == "__main__":
    unittest.main()
