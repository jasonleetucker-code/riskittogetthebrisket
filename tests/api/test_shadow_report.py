"""Tests for build_shadow_comparison_report — the diagnostic analysis
that powers /api/scaffold/shadow and server logs in shadow mode."""
from __future__ import annotations

import unittest

from src.api.data_contract import build_shadow_comparison_report


def _snapshot(assets):
    """Wrap a list of asset dicts into a minimal canonical snapshot."""
    return {
        "run_id": "test-001",
        "source_snapshot_id": "snap-test",
        "source_count": 2,
        "asset_count": len(assets),
        "asset_count_by_universe": {},
        "assets": assets,
    }


def _asset(name, value, universe="offense_vet", sources=None):
    return {
        "display_name": name,
        "blended_value": value,
        "universe": universe,
        "source_values": sources or {"KTC": value},
    }


def _legacy(name, value):
    return {name: {"_finalAdjusted": value, "_composite": value}}


class TestOverlapAnalysis(unittest.TestCase):
    def test_matched_players_counted(self):
        snap = _snapshot([_asset("Josh Allen", 9000), _asset("Lamar Jackson", 8500)])
        legacy = {**_legacy("Josh Allen", 8500), **_legacy("Lamar Jackson", 8200)}
        report = build_shadow_comparison_report(snap, legacy)
        self.assertEqual(report["summary"]["matchedCount"], 2)

    def test_canonical_only_detected(self):
        snap = _snapshot([_asset("Josh Allen", 9000), _asset("New Rookie", 3000)])
        legacy = _legacy("Josh Allen", 8500)
        report = build_shadow_comparison_report(snap, legacy)
        self.assertEqual(report["summary"]["canonicalOnlyCount"], 1)
        self.assertIn("New Rookie", report["canonicalOnlySample"])

    def test_legacy_only_detected(self):
        snap = _snapshot([_asset("Josh Allen", 9000)])
        legacy = {**_legacy("Josh Allen", 8500), **_legacy("Old Veteran", 2000)}
        report = build_shadow_comparison_report(snap, legacy)
        self.assertEqual(report["summary"]["legacyOnlyCount"], 1)
        self.assertIn("Old Veteran", report["legacyOnlySample"])

    def test_empty_canonical(self):
        report = build_shadow_comparison_report(_snapshot([]), _legacy("Josh Allen", 8500))
        self.assertEqual(report["summary"]["matchedCount"], 0)
        self.assertEqual(report["summary"]["legacyOnlyCount"], 1)

    def test_empty_legacy(self):
        report = build_shadow_comparison_report(_snapshot([_asset("Josh Allen", 9000)]), {})
        self.assertEqual(report["summary"]["matchedCount"], 0)
        self.assertEqual(report["summary"]["canonicalOnlyCount"], 1)


class TestDeltaComputation(unittest.TestCase):
    def test_delta_values(self):
        snap = _snapshot([_asset("Josh Allen", 9000)])
        legacy = _legacy("Josh Allen", 8500)
        report = build_shadow_comparison_report(snap, legacy)
        mismatch = report["biggestMismatches"][0]
        self.assertEqual(mismatch["canonicalValue"], 9000)
        self.assertEqual(mismatch["legacyValue"], 8500)
        self.assertEqual(mismatch["delta"], 500)
        self.assertEqual(mismatch["absDelta"], 500)
        self.assertAlmostEqual(mismatch["pctDelta"], 5.9, places=1)

    def test_negative_delta(self):
        snap = _snapshot([_asset("Josh Allen", 7000)])
        legacy = _legacy("Josh Allen", 9000)
        report = build_shadow_comparison_report(snap, legacy)
        mismatch = report["biggestMismatches"][0]
        self.assertEqual(mismatch["delta"], -2000)

    def test_sorted_by_abs_delta(self):
        snap = _snapshot([
            _asset("Small Gap", 5100),
            _asset("Big Gap", 9000),
            _asset("Medium Gap", 6000),
        ])
        legacy = {
            **_legacy("Small Gap", 5000),
            **_legacy("Big Gap", 5000),
            **_legacy("Medium Gap", 5000),
        }
        report = build_shadow_comparison_report(snap, legacy)
        names = [m["name"] for m in report["biggestMismatches"]]
        self.assertEqual(names[0], "Big Gap")
        self.assertEqual(names[-1], "Small Gap")


class TestTopMovers(unittest.TestCase):
    def test_risers_positive_delta(self):
        snap = _snapshot([_asset("Riser", 9000), _asset("Faller", 3000)])
        legacy = {**_legacy("Riser", 7000), **_legacy("Faller", 5000)}
        report = build_shadow_comparison_report(snap, legacy)
        self.assertEqual(len(report["topRisers"]), 1)
        self.assertEqual(report["topRisers"][0]["name"], "Riser")
        self.assertEqual(report["topRisers"][0]["delta"], 2000)

    def test_fallers_negative_delta(self):
        snap = _snapshot([_asset("Riser", 9000), _asset("Faller", 3000)])
        legacy = {**_legacy("Riser", 7000), **_legacy("Faller", 5000)}
        report = build_shadow_comparison_report(snap, legacy)
        self.assertEqual(len(report["topFallers"]), 1)
        self.assertEqual(report["topFallers"][0]["name"], "Faller")
        self.assertEqual(report["topFallers"][0]["delta"], -2000)

    def test_limited_to_10(self):
        assets = [_asset(f"Player{i}", 9000 - i * 100) for i in range(20)]
        legacy = {}
        for i in range(20):
            legacy.update(_legacy(f"Player{i}", 5000))
        report = build_shadow_comparison_report(_snapshot(assets), legacy)
        self.assertLessEqual(len(report["topRisers"]), 10)


class TestDeltaDistribution(unittest.TestCase):
    def test_distribution_buckets(self):
        snap = _snapshot([
            _asset("Near Even", 5050),    # delta = 50, bucket: under200
            _asset("Lean", 5400),         # delta = 400, bucket: 200to600
            _asset("Strong", 5900),       # delta = 900, bucket: 600to1200
            _asset("Major", 6500),        # delta = 1500, bucket: over1200
        ])
        legacy = {}
        for name in ["Near Even", "Lean", "Strong", "Major"]:
            legacy.update(_legacy(name, 5000))
        report = build_shadow_comparison_report(snap, legacy)
        dist = report["summary"]["deltaDistribution"]
        self.assertEqual(dist["under200"], 1)
        self.assertEqual(dist["200to600"], 1)
        self.assertEqual(dist["600to1200"], 1)
        self.assertEqual(dist["over1200"], 1)


class TestRankCorrelation(unittest.TestCase):
    def test_perfect_overlap(self):
        # Same top-50 players in both
        assets = [_asset(f"Player{i}", 10000 - i * 100) for i in range(60)]
        legacy = {}
        for i in range(60):
            legacy.update(_legacy(f"Player{i}", 10000 - i * 100))
        report = build_shadow_comparison_report(_snapshot(assets), legacy)
        self.assertEqual(report["summary"]["top50Overlap"], 50)
        self.assertEqual(report["summary"]["top50OverlapPct"], 100)

    def test_no_overlap(self):
        assets = [_asset(f"Canonical{i}", 10000 - i * 100) for i in range(60)]
        legacy = {}
        for i in range(60):
            legacy.update(_legacy(f"Legacy{i}", 10000 - i * 100))
        report = build_shadow_comparison_report(_snapshot(assets), legacy)
        self.assertEqual(report["summary"]["top50Overlap"], 0)

    def test_small_sample_denominator(self):
        """When fewer than 50 assets exist, overlap % uses actual count as denominator."""
        # 10 canonical, 10 legacy, all matching — should be 100%, not 20%
        assets = [_asset(f"Player{i}", 10000 - i * 100) for i in range(10)]
        legacy = {}
        for i in range(10):
            legacy.update(_legacy(f"Player{i}", 10000 - i * 100))
        report = build_shadow_comparison_report(_snapshot(assets), legacy)
        self.assertEqual(report["summary"]["top50Overlap"], 10)
        self.assertEqual(report["summary"]["top50OverlapPct"], 100)

    def test_empty_lists_no_division_by_zero(self):
        """Empty canonical or legacy should produce 0% without crashing."""
        report = build_shadow_comparison_report(_snapshot([]), {})
        self.assertEqual(report["summary"]["top50Overlap"], 0)
        self.assertEqual(report["summary"]["top50OverlapPct"], 0)


class TestFinalValueUsed(unittest.TestCase):
    """Shadow comparisons must use the final calibrated canonical value, not blended."""

    def test_prefers_calibrated_over_blended(self):
        asset = {
            "display_name": "Josh Allen",
            "blended_value": 5000,
            "calibrated_value": 8000,
            "universe": "offense_vet",
            "source_values": {"KTC": 5000},
        }
        legacy = _legacy("Josh Allen", 8500)
        report = build_shadow_comparison_report(_snapshot([asset]), legacy)
        match = report["biggestMismatches"][0]
        # Should use calibrated (8000), not blended (5000)
        self.assertEqual(match["canonicalValue"], 8000)
        self.assertEqual(match["delta"], -500)  # 8000 - 8500

    def test_falls_back_to_blended(self):
        # No calibrated_value, only blended
        asset_raw = {
            "display_name": "Player B",
            "blended_value": 2000,
            "universe": "offense_vet",
            "source_values": {"KTC": 2000},
        }
        legacy = {**_legacy("Player B", 5000)}
        report = build_shadow_comparison_report(_snapshot([asset_raw]), legacy)
        by_name = {m["name"]: m for m in report["biggestMismatches"]}
        self.assertEqual(by_name["Player B"]["canonicalValue"], 2000)


class TestShadowCollisionResolution(unittest.TestCase):
    """Duplicate display_names must not silently overwrite — higher value wins."""

    def test_keeps_higher_value_on_collision(self):
        """Same player in rookie + vet: higher calibrated_value should be used."""
        snap = _snapshot([
            _asset("Carnell Tate", 7000, universe="offense_vet"),
            _asset("Carnell Tate", 8200, universe="offense_rookie"),
        ])
        legacy = _legacy("Carnell Tate", 5000)
        report = build_shadow_comparison_report(snap, legacy)
        # Should use 8200 (rookie), not 7000 (vet)
        self.assertEqual(report["summary"]["canonicalAssetCount"], 1)
        match = report["biggestMismatches"][0]
        self.assertEqual(match["canonicalValue"], 8200)
        self.assertEqual(match["delta"], 3200)  # 8200 - 5000

    def test_lower_value_does_not_overwrite(self):
        """If higher-value entry appears first, lower one must not replace it."""
        snap = _snapshot([
            _asset("CJ Allen", 4500, universe="idp_vet"),
            _asset("CJ Allen", 2200, universe="idp_rookie"),
        ])
        legacy = _legacy("CJ Allen", 3000)
        report = build_shadow_comparison_report(snap, legacy)
        match = report["biggestMismatches"][0]
        self.assertEqual(match["canonicalValue"], 4500)

    def test_no_collision_preserves_all(self):
        """Unique names should all be preserved."""
        snap = _snapshot([
            _asset("Player A", 9000),
            _asset("Player B", 8000),
            _asset("Player C", 7000),
        ])
        report = build_shadow_comparison_report(snap, {})
        self.assertEqual(report["summary"]["canonicalAssetCount"], 3)

    def test_collision_does_not_inflate_asset_count(self):
        """canonicalAssetCount should reflect unique names, not raw asset count."""
        snap = _snapshot([
            _asset("Dupe", 5000, universe="offense_vet"),
            _asset("Dupe", 6000, universe="offense_rookie"),
            _asset("Unique", 4000),
        ])
        report = build_shadow_comparison_report(snap, {})
        self.assertEqual(report["summary"]["canonicalAssetCount"], 2)  # not 3


class TestSummaryStats(unittest.TestCase):
    def test_avg_and_median(self):
        snap = _snapshot([
            _asset("A", 5100),  # delta = 100
            _asset("B", 5500),  # delta = 500
            _asset("C", 6000),  # delta = 1000
        ])
        legacy = {}
        for name in ["A", "B", "C"]:
            legacy.update(_legacy(name, 5000))
        report = build_shadow_comparison_report(snap, legacy)
        s = report["summary"]
        self.assertEqual(s["avgAbsDelta"], 533)    # (100+500+1000)/3 ≈ 533
        self.assertEqual(s["medianAbsDelta"], 500)  # middle value
        self.assertEqual(s["maxAbsDelta"], 1000)

    def test_p90(self):
        # 10 players with deltas 100, 200, ..., 1000
        assets = [_asset(f"P{i}", 5000 + (i + 1) * 100) for i in range(10)]
        legacy = {}
        for i in range(10):
            legacy.update(_legacy(f"P{i}", 5000))
        report = build_shadow_comparison_report(_snapshot(assets), legacy)
        # p90 = 90th percentile index = int(10 * 0.9) = 9th element (0-indexed) of sorted
        # sorted abs_deltas = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        # index 9 = 1000
        self.assertEqual(report["summary"]["p90AbsDelta"], 1000)


class TestReportMetadata(unittest.TestCase):
    def test_has_required_keys(self):
        snap = _snapshot([_asset("Josh Allen", 9000)])
        legacy = _legacy("Josh Allen", 8500)
        report = build_shadow_comparison_report(snap, legacy)
        self.assertIn("generatedAt", report)
        self.assertIn("snapshotRunId", report)
        self.assertIn("summary", report)
        self.assertIn("topRisers", report)
        self.assertIn("topFallers", report)
        self.assertIn("biggestMismatches", report)
        self.assertIn("canonicalOnlySample", report)
        self.assertIn("legacyOnlySample", report)

    def test_snapshot_metadata_passed_through(self):
        snap = _snapshot([])
        snap["source_count"] = 3
        snap["asset_count_by_universe"] = {"offense_vet": 100}
        report = build_shadow_comparison_report(snap, {})
        self.assertEqual(report["snapshotSourceCount"], 3)
        self.assertEqual(report["snapshotUniverses"], {"offense_vet": 100})


if __name__ == "__main__":
    unittest.main()
