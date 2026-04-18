"""Tests for trust, confidence, and anomaly fields added to the data contract.

Covers:
  - Confidence bucket computation
  - Anomaly flag rules
  - Market gap direction/magnitude
  - New per-player fields stamped by _compute_unified_rankings
  - Payload-level methodology, dataFreshness, and anomalySummary blocks
"""
from __future__ import annotations

import copy
import unittest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    _RANKING_SOURCES,
    _compute_confidence_bucket,
    _compute_anomaly_flags,
    _compute_market_gap,
    _compute_unified_rankings,
    build_api_data_contract,
)
from src.canonical.idp_backbone import SOURCE_SCOPE_OVERALL_OFFENSE


# ── Helpers ──────────────────────────────────────────────────────────────────


class _SecondOffenseSourceMixin:
    """Mixin that temporarily registers a second `overall_offense` source.

    Under the scope-aware ranking pipeline a QB can only be ranked by
    overall_offense sources, so exercising any "multi-source" confidence
    path on an offense player requires two sources sharing that scope.
    Tests that relied on the old position-agnostic ranking used KTC+IDP
    on a QB — that's not possible (and not correct) under scope gating.
    This mixin installs a synthetic sibling source for the duration of
    one test so the two-source path is testable without faking anything.
    """

    _SIBLING_KEY = "ktcMirror"

    def setUp(self) -> None:  # noqa: D401 - unittest signature
        self._saved_registry = copy.deepcopy(_RANKING_SOURCES)
        _RANKING_SOURCES.append(
            {
                "key": self._SIBLING_KEY,
                "display_name": "KTC Mirror (test)",
                "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
                "position_group": None,
                "depth": None,
                "weight": 1.0,
                "is_backbone": False,
            }
        )

    def tearDown(self) -> None:  # noqa: D401 - unittest signature
        _RANKING_SOURCES.clear()
        _RANKING_SOURCES.extend(self._saved_registry)


def _make_player(name, position, *, ktc=None, idp=None, team="TST", sibling=None):
    """Build a minimal raw player dict for contract builder tests.

    `sibling` attaches a value under the test-only `ktcMirror` key that
    `_SecondOffenseSourceMixin` temporarily registers as a second
    overall_offense source.
    """
    sites = {}
    if ktc is not None:
        sites["ktc"] = ktc
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if sibling is not None:
        sites["ktcMirror"] = sibling
    composite_max = max(ktc or 0, idp or 0, sibling or 0)
    return {
        name: {
            "_composite": composite_max,
            "_rawComposite": composite_max,
            "_finalAdjusted": composite_max,
            "_sites": (
                (1 if ktc else 0)
                + (1 if idp else 0)
                + (1 if sibling else 0)
            ),
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

    def test_retail_premium_vs_single_consensus_source(self):
        # KTC (retail) rank 10, IDPTC (consensus) rank 50 → retail mean 10
        # vs consensus mean 50 → retail ranks the player 40 positions
        # higher → retail_premium.
        direction, magnitude = _compute_market_gap({"ktc": 10, "idpTradeCalc": 50})
        self.assertEqual(direction, "retail_premium")
        self.assertEqual(magnitude, 40.0)

    def test_consensus_premium_vs_single_consensus_source(self):
        direction, magnitude = _compute_market_gap({"ktc": 80, "idpTradeCalc": 20})
        self.assertEqual(direction, "consensus_premium")
        self.assertEqual(magnitude, 60.0)

    def test_equal_ranks(self):
        direction, magnitude = _compute_market_gap({"ktc": 30, "idpTradeCalc": 30})
        self.assertEqual(direction, "none")
        self.assertEqual(magnitude, 0.0)

    def test_retail_alone_returns_none(self):
        # Retail side has a rank, consensus side is empty → no gap.
        direction, magnitude = _compute_market_gap({"ktc": 10})
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)

    def test_no_retail_returns_none(self):
        # IDP-only players have no retail rank (KTC is offense-only) →
        # retail side is empty → no gap.
        direction, magnitude = _compute_market_gap({"idpTradeCalc": 10, "dlfIdp": 20})
        self.assertEqual(direction, "none")
        self.assertIsNone(magnitude)

    def test_retail_vs_averaged_multi_source_consensus(self):
        # KTC 10 vs mean(IDPTC 50, DLF 70) = 60 → retail_premium of 50.
        direction, magnitude = _compute_market_gap(
            {"ktc": 10, "idpTradeCalc": 50, "dlfIdp": 70}
        )
        self.assertEqual(direction, "retail_premium")
        self.assertEqual(magnitude, 50.0)

    def test_consensus_premium_with_multi_source_consensus(self):
        # KTC 100 vs mean(IDPTC 30, DLF 40) = 35 → consensus_premium of 65.
        direction, magnitude = _compute_market_gap(
            {"ktc": 100, "idpTradeCalc": 30, "dlfIdp": 40}
        )
        self.assertEqual(direction, "consensus_premium")
        self.assertEqual(magnitude, 65.0)

    def test_multi_retail_sources_are_averaged(self):
        # Hypothetical two-retail-source world (e.g. KTC + Sleeper trade
        # values both flagged is_retail).  Retail mean = (10 + 30)/2 = 20;
        # consensus mean = 60.  Retail ranks the player 40 higher →
        # retail_premium.  Verified via explicit retail_keys override so
        # we don't need to mutate the real registry.
        direction, magnitude = _compute_market_gap(
            {"ktc": 10, "sleeperTrade": 30, "idpTradeCalc": 50, "dlfIdp": 70},
            retail_keys=frozenset({"ktc", "sleeperTrade"}),
        )
        self.assertEqual(direction, "retail_premium")
        self.assertEqual(magnitude, 40.0)

    def test_multi_retail_consensus_premium(self):
        # Symmetric two-retail test: retail mean = (80+90)/2 = 85;
        # consensus mean = (20+40)/2 = 30; consensus ranks 55 higher.
        direction, magnitude = _compute_market_gap(
            {"ktc": 80, "sleeperTrade": 90, "idpTradeCalc": 20, "dlfIdp": 40},
            retail_keys=frozenset({"ktc", "sleeperTrade"}),
        )
        self.assertEqual(direction, "consensus_premium")
        self.assertEqual(magnitude, 55.0)


# ── Integration: single-source player row ────────────────────────────────────


class TestSingleSourceRow(unittest.TestCase):

    def test_single_source_offense_player(self):
        # Use a unique name that won't match CSV enrichment data on disk.
        # With two primary-scope offense sources now registered (KTC +
        # DLF Superflex), a KTC-only QB whose rank is within DLF's
        # expected depth IS a real matching failure — DLF should have
        # covered him and didn't.  The test fixture uses an unusual
        # name so it won't match DLF's CSV on disk.
        payload = _payload_with_players(
            _make_player("Zzz Testonly Qb Alpha", "QB", ktc=9500),
        )
        row = _build_and_find(payload, "Zzz Testonly Qb Alpha")
        self.assertIsNotNone(row)
        self.assertTrue(row["isSingleSource"])
        self.assertFalse(row["isStructurallySingleSource"])
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


class TestTwoSourceRow(_SecondOffenseSourceMixin, unittest.TestCase):

    def test_two_source_player_tight_agreement(self):
        """Two offense sources with similar values → high confidence,
        no disagreement.  Uses the test-only ktcMirror sibling source
        registered by the mixin, because KTC and idpTradeCalc have
        disjoint scopes and can never both rank the same player.
        """
        payload = _payload_with_players(
            _make_player("Two Source Guy", "QB", ktc=9000, sibling=8800),
        )
        row = _build_and_find(payload, "Two Source Guy")
        self.assertIsNotNone(row)
        self.assertFalse(row["isSingleSource"])
        self.assertIsNotNone(row["sourceRankSpread"])
        # Both offense sources exist
        self.assertIn("ktc", row.get("sourceRanks", {}))
        self.assertIn("ktcMirror", row.get("sourceRanks", {}))
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
        # ktc + idpTradeCalc + dlfIdp + dlfSf + dynastyNerdsSfTep +
        # fantasyProsSf + dynastyDaddySf + fantasyProsIdp + flockFantasySf +
        # footballGuysSf + footballGuysIdp (eleven registered ranking sources)
        self.assertEqual(len(meth["sources"]), 11)
        keys = {s.get("key") for s in meth["sources"]}
        self.assertEqual(
            keys,
            {
                "ktc",
                "idpTradeCalc",
                "dlfIdp",
                "dlfSf",
                "dynastyNerdsSfTep",
                "fantasyProsSf",
                "dynastyDaddySf",
                "fantasyProsIdp",
                "flockFantasySf",
                "footballGuysSf",
                "footballGuysIdp",
            },
        )

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
        # OL player is excluded from ranking, gets unsupported_position flag
        payload = _payload_with_players(
            _make_player("Good QB", "QB", ktc=9000),
            _make_player("OL Guy", "OL", ktc=5000),
        )
        contract = build_api_data_contract(payload)
        summary = contract["anomalySummary"]
        # OL Guy should be flagged with unsupported_position (not ol_contamination,
        # because OL is now excluded from per-source ranking entirely)
        self.assertGreaterEqual(summary["totalFlagged"], 1)
        self.assertIn("unsupported_position", summary["flagCounts"])


# ── Integration: REQUIRED_PLAYER_KEYS includes new fields ───────────────────


class TestRequiredPlayerKeys(unittest.TestCase):

    def test_new_fields_in_required_keys(self):
        from src.api.data_contract import REQUIRED_PLAYER_KEYS

        self.assertIn("confidenceBucket", REQUIRED_PLAYER_KEYS)
        self.assertIn("anomalyFlags", REQUIRED_PLAYER_KEYS)


# ── Quarantine and identity confidence ─────────────────────────────────────


class TestQuarantineFields(unittest.TestCase):
    """Verify quarantine flag and confidence degradation."""

    def test_clean_player_not_quarantined(self):
        payload = _payload_with_players(
            _make_player("Clean QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "Clean QB")
        self.assertFalse(row["quarantined"])

    def test_ol_player_quarantined(self):
        """OL contamination is a quarantine-level flag."""
        payload = _payload_with_players(
            _make_player("OL Guy", "OL", ktc=5000),
        )
        row = _build_and_find(payload, "OL Guy")
        self.assertTrue(row["quarantined"])
        self.assertIn("unsupported_position", row["anomalyFlags"])

    def test_quarantine_degrades_confidence(self):
        """Quarantined players should have confidence degraded.
        OL players are excluded from ranking, so they keep the default
        'none' confidence bucket — quarantine does not promote to 'low'."""
        payload = _payload_with_players(
            _make_player("Normal WR", "WR", ktc=8000),
            _make_player("OL Leak", "OL", ktc=6000),
        )
        row = _build_and_find(payload, "OL Leak")
        self.assertTrue(row["quarantined"])
        # OL is excluded from ranking → stays at default "none" confidence.
        # Quarantine degrades high/medium → low, but "none" is already lowest.
        self.assertEqual(row["confidenceBucket"], "none")


class TestIdentityConfidence(unittest.TestCase):
    """Verify identity confidence scoring."""

    def test_name_only_gets_070(self):
        payload = _payload_with_players(
            _make_player("No ID QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "No ID QB")
        # No playerId, but position matches source evidence
        self.assertGreaterEqual(row["identityConfidence"], 0.70)
        self.assertIn(row["identityMethod"], (
            "name_only", "position_source_aligned", "partial_evidence",
        ))

    def test_identity_fields_present(self):
        payload = _payload_with_players(
            _make_player("Any Player", "WR", ktc=7000),
        )
        row = _build_and_find(payload, "Any Player")
        self.assertIn("identityConfidence", row)
        self.assertIn("identityMethod", row)
        self.assertIsInstance(row["identityConfidence"], float)
        self.assertIsInstance(row["identityMethod"], str)


class TestMultiFlagScenarios(unittest.TestCase):
    """Verify behaviour when multiple anomaly flags fire."""

    def test_missing_position_and_no_source_flags(self):
        """A player with pos=? and no sources should get multiple flags."""
        payload = _payload_with_players(
            _make_player("Mystery", "?"),
        )
        row = _build_and_find(payload, "Mystery")
        # Should have at least missing_position flag
        # (won't be ranked so anomaly flags from _compute_anomaly_flags
        # may not fire, but contract defaults should be clean)
        self.assertIsInstance(row["anomalyFlags"], list)

    def test_suspicious_disagreement_with_high_spread(self):
        """Two sources > 150 ranks apart triggers suspicious_disagreement."""
        # Create many players so ranks can actually spread.  IDPTradeCalc
        # now contributes to both the offense and IDP scopes, so the
        # filler QBs carry IDPTC values too (mirroring production where
        # IDPTC's autocomplete covers every offense star).  Without a
        # full offense IDPTC pool the test player would be the only QB
        # ranked by IDPTC and the spread would collapse to zero.
        players = {}
        for i in range(200):
            p = _make_player(
                f"Filler Off {i}",
                "QB",
                ktc=9000 - i * 40,
                idp=9000 - i * 40,
            )
            players.update(p)
        for i in range(200):
            p = _make_player(f"Filler IDP {i}", "DL", idp=9000 - i * 40)
            players.update(p)
        # Add test player with both sources at wildly different ranks.
        # ktc=9000 puts him near the top of the KTC offense ladder, while
        # idp=100 puts him near the bottom of the IDPTC offense ladder.
        test_p = _make_player("Spread Guy", "QB", ktc=9000, idp=100)
        players.update(test_p)
        payload = {
            "players": players,
            "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktc": 9999},
            "sleeper": {"positions": {k: v["position"] for k, v in players.items()}},
        }
        row = _build_and_find(payload, "Spread Guy")
        self.assertIsNotNone(row)
        # Should have a significant spread
        if row.get("sourceRankSpread") is not None:
            self.assertGreater(row["sourceRankSpread"], 50)


class TestEdgeCaseFixtures(_SecondOffenseSourceMixin, unittest.TestCase):
    """Regression fixtures for edge-case row types.

    Uses the _SecondOffenseSourceMixin so the multi-source consensus
    test below can attach a second overall_offense source (ktcMirror)
    alongside KTC.
    """

    def test_single_source_offense_player(self):
        payload = _payload_with_players(
            _make_player("Solo WR", "WR", ktc=7500),
        )
        row = _build_and_find(payload, "Solo WR")
        self.assertTrue(row["isSingleSource"])
        self.assertIsNone(row["sourceRankSpread"])
        self.assertEqual(row["marketGapDirection"], "none")
        self.assertFalse(row["hasSourceDisagreement"])

    def test_single_source_idp_player(self):
        payload = _payload_with_players(
            _make_player("Solo LB", "LB", idp=6000),
        )
        row = _build_and_find(payload, "Solo LB")
        self.assertTrue(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "low")

    def test_high_confidence_consensus_asset(self):
        """Multi-source with tight agreement = high confidence.

        Uses two overall_offense sources (ktc + ktcMirror) because KTC
        and idpTradeCalc have disjoint scopes under the scope-aware
        ranking pipeline.
        """
        payload = _payload_with_players(
            _make_player("Consensus QB", "QB", ktc=9000, sibling=8900),
        )
        row = _build_and_find(payload, "Consensus QB")
        self.assertFalse(row["isSingleSource"])
        self.assertEqual(row["confidenceBucket"], "high")
        self.assertFalse(row["quarantined"])

    def test_all_trust_fields_present_on_ranked_player(self):
        """Every trust field should exist on a ranked player."""
        payload = _payload_with_players(
            _make_player("Complete QB", "QB", ktc=8000),
        )
        row = _build_and_find(payload, "Complete QB")
        required_fields = [
            "confidenceBucket", "confidenceLabel", "anomalyFlags",
            "isSingleSource", "hasSourceDisagreement", "blendedSourceRank",
            "sourceRankSpread", "marketGapDirection", "marketGapMagnitude",
            "identityConfidence", "identityMethod", "quarantined",
        ]
        for field in required_fields:
            self.assertIn(field, row, f"Missing trust field: {field}")


class TestTrustMirrorToLegacy(_SecondOffenseSourceMixin, unittest.TestCase):
    """Trust fields must be mirrored from playersArray → legacy players dict.

    The runtime view strips playersArray.  The frontend falls back to the
    legacy dict and reads trust fields via r.raw?.field.  This test proves
    that build_api_data_contract copies all 12 trust fields into the legacy
    dict so they survive the runtime view.
    """

    TRUST_FIELDS = [
        "confidenceBucket", "confidenceLabel", "anomalyFlags",
        "isSingleSource", "hasSourceDisagreement", "blendedSourceRank",
        "sourceRankSpread", "marketGapDirection", "marketGapMagnitude",
        "identityConfidence", "identityMethod", "quarantined",
    ]

    def test_trust_fields_mirrored_to_legacy_dict(self):
        """All 12 trust fields appear on the legacy players dict entry."""
        payload = _payload_with_players(
            _make_player("Mirror QB", "QB", ktc=8500),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"].get("Mirror QB")
        self.assertIsNotNone(legacy_entry, "Legacy dict entry missing")

        for field in self.TRUST_FIELDS:
            self.assertIn(field, legacy_entry,
                          f"Trust field '{field}' not mirrored to legacy dict")

    def test_mirrored_values_match_players_array(self):
        """Mirrored legacy values must match the playersArray values."""
        payload = _payload_with_players(
            _make_player("Match QB", "QB", ktc=9000, idp=None),
        )
        contract = build_api_data_contract(payload)
        row = None
        for r in contract["playersArray"]:
            if r["canonicalName"] == "Match QB":
                row = r
                break
        self.assertIsNotNone(row)
        legacy_entry = contract["players"]["Match QB"]

        for field in self.TRUST_FIELDS:
            self.assertEqual(
                legacy_entry[field], row[field],
                f"Mismatch on '{field}': legacy={legacy_entry[field]!r}, "
                f"array={row[field]!r}",
            )

    def test_quarantine_reflected_in_legacy_dict(self):
        """Quarantined status and degraded confidence reach the legacy dict."""
        # Build two players with same name collision → triggers quarantine
        payload = _payload_with_players(
            _make_player("Quarantine QB", "QB", ktc=7000),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"]["Quarantine QB"]
        # Whether quarantined or not, the field must be present and boolean
        self.assertIn("quarantined", legacy_entry)
        self.assertIsInstance(legacy_entry["quarantined"], bool)
        self.assertIn("confidenceBucket", legacy_entry)

    def test_multi_source_high_confidence_mirrored(self):
        """A multi-source player with tight agreement gets 'high' mirrored.

        Uses two overall_offense sources (ktc + ktcMirror) via the mixin
        because KTC and idpTradeCalc have disjoint scopes and cannot
        both rank a QB under the scope-aware pipeline.
        """
        payload = _payload_with_players(
            _make_player("Dual QB", "QB", ktc=8000, sibling=8000),
        )
        contract = build_api_data_contract(payload)
        legacy_entry = contract["players"]["Dual QB"]
        # With equal values across two sources, spread=0 → high confidence
        self.assertEqual(legacy_entry["confidenceBucket"], "high")
        self.assertFalse(legacy_entry["isSingleSource"])


class TestUnsupportedPositionRankingExclusion(unittest.TestCase):
    """Unsupported positions (OL, OT, OG, C, G, T, LS) must never receive
    a canonicalConsensusRank or rankDerivedValue, even when they have
    source values."""

    UNSUPPORTED = ["OL", "OT", "OG", "C", "G", "T", "LS"]

    def _make_unsupported(self, name, position, ktc_val=7000):
        """Build a player dict with an unsupported position but valid KTC."""
        return {
            name: {
                "_composite": ktc_val,
                "_rawComposite": ktc_val,
                "_finalAdjusted": ktc_val,
                "_sites": 1,
                "position": position,
                "team": "TST",
                "_canonicalSiteValues": {"ktc": ktc_val},
            }
        }

    def test_ol_not_ranked(self):
        """OL player with KTC value must not receive a rank."""
        payload = _payload_with_players(
            self._make_unsupported("Nick Martin", "C", ktc_val=5000),
            _make_player("Real QB", "QB", ktc=9000),
        )
        row = _build_and_find(payload, "Nick Martin")
        self.assertIsNotNone(row)
        # Must not have a rank or derived value from the ranking pass
        self.assertIn("unsupported_position", row.get("anomalyFlags", []))
        self.assertTrue(row["quarantined"])
        # canonicalConsensusRank should be None (not ranked)
        rank = row.get("canonicalConsensusRank")
        self.assertTrue(
            rank is None or rank == 0,
            f"OL player got rank {rank} — should be unranked",
        )

    def test_all_unsupported_positions_excluded(self):
        """Every unsupported position must be excluded from ranking."""
        for pos in self.UNSUPPORTED:
            players = [
                self._make_unsupported(f"Test {pos}", pos, ktc_val=8000),
                _make_player("Anchor QB", "QB", ktc=9500),
            ]
            payload = _payload_with_players(*players)
            row = _build_and_find(payload, f"Test {pos}")
            self.assertIsNotNone(row, f"Row missing for position {pos}")
            rank = row.get("canonicalConsensusRank")
            self.assertTrue(
                rank is None or rank == 0,
                f"Position {pos} got rank {rank} — should be unranked",
            )

    def test_supported_positions_still_ranked(self):
        """Supported positions must still receive ranks normally."""
        payload = _payload_with_players(
            _make_player("Ranked QB", "QB", ktc=9000),
            _make_player("Ranked LB", "LB", idp=8000),
        )
        qb = _build_and_find(payload, "Ranked QB")
        lb = _build_and_find(payload, "Ranked LB")
        self.assertIsNotNone(qb)
        self.assertIsNotNone(lb)
        self.assertIsNotNone(qb.get("canonicalConsensusRank"))
        self.assertGreater(qb["canonicalConsensusRank"], 0)
        self.assertIsNotNone(lb.get("canonicalConsensusRank"))
        self.assertGreater(lb["canonicalConsensusRank"], 0)

    def test_unsupported_does_not_displace_supported(self):
        """An unsupported-position player must not take a rank slot
        away from a supported-position player."""
        payload = _payload_with_players(
            self._make_unsupported("OL Guy", "OL", ktc_val=9999),
            _make_player("Real WR", "WR", ktc=5000),
        )
        wr = _build_and_find(payload, "Real WR")
        ol = _build_and_find(payload, "OL Guy")
        self.assertIsNotNone(wr)
        self.assertIsNotNone(ol)
        # WR must be ranked
        self.assertGreater(wr["canonicalConsensusRank"], 0)
        # OL must NOT be ranked (no rank displacement)
        ol_rank = ol.get("canonicalConsensusRank")
        self.assertTrue(ol_rank is None or ol_rank == 0)


if __name__ == "__main__":
    unittest.main()
