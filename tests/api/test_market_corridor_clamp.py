"""Tests for the market-anchor corridor clamp.

The clamp pulls back players whose blended final value has drifted
further from their market anchor (KTC for offense, IDPTC for IDP)
than the 90th percentile of drift within their confidence bucket.
Non-outliers are untouched.
"""
from __future__ import annotations

import unittest
from typing import Any

from src.api.data_contract import (
    _MARKET_ANCHOR_BY_ASSET_CLASS,
    _apply_market_corridor_clamp,
    _market_anchor_value_for_row,
    _percentile,
)


def _make_row(
    *,
    name: str,
    asset_class: str,
    value: int,
    ktc: int | None = None,
    idpTradeCalc: int | None = None,
    bucket: str = "medium",
) -> dict[str, Any]:
    sites: dict[str, Any] = {}
    if ktc is not None:
        sites["ktc"] = ktc
    if idpTradeCalc is not None:
        sites["idpTradeCalc"] = idpTradeCalc
    return {
        "canonicalName": name,
        "legacyRef": name,
        "assetClass": asset_class,
        "canonicalSiteValues": sites,
        "rankDerivedValue": value,
        "canonicalConsensusRank": 1,  # any truthy value keeps the row in the clamp scope
        "confidenceBucket": bucket,
    }


class TestMarketAnchorSelection(unittest.TestCase):
    def test_offense_uses_ktc(self):
        self.assertEqual(_MARKET_ANCHOR_BY_ASSET_CLASS["offense"], "ktc")

    def test_idp_uses_idptc(self):
        self.assertEqual(_MARKET_ANCHOR_BY_ASSET_CLASS["idp"], "idpTradeCalc")

    def test_anchor_missing_returns_none(self):
        row = _make_row(
            name="No Anchor", asset_class="offense", value=5000,
            ktc=None,
        )
        self.assertIsNone(_market_anchor_value_for_row(row))

    def test_anchor_zero_returns_none(self):
        """Zero-value anchors can't serve as denominators for the drift
        ratio — treat them as absent."""
        row = _make_row(
            name="Zero KTC", asset_class="offense", value=5000,
            ktc=0,
        )
        self.assertIsNone(_market_anchor_value_for_row(row))

    def test_pick_asset_class_has_no_anchor(self):
        row = _make_row(
            name="2026 Pick 1.01", asset_class="pick", value=8000,
            ktc=8200,  # pick KTC values exist but picks aren't in the clamp scope
        )
        self.assertIsNone(_market_anchor_value_for_row(row))


class TestPercentileHelper(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_percentile([], 0.9), 0.0)

    def test_monotone(self):
        xs = sorted([0.1, 0.2, 0.3, 0.5, 0.8])
        self.assertLess(_percentile(xs, 0.5), _percentile(xs, 0.9))

    def test_p100_is_max(self):
        xs = sorted([0.1, 0.5, 0.9])
        self.assertEqual(_percentile(xs, 1.0), 0.9)

    def test_p0_is_min(self):
        xs = sorted([0.1, 0.5, 0.9])
        self.assertEqual(_percentile(xs, 0.0), 0.1)


class TestClampFires(unittest.TestCase):
    """The clamp must pull back rows whose drift exceeds the P90 of
    its confidence bucket, and leave everyone else alone."""

    def test_single_extreme_outlier_gets_clamped_below_market(self):
        """A very-low-value outlier (Parsons-style) should get lifted
        to the band edge."""
        rows = []
        # 39 "normal" medium-confidence rows with drifts ~0.10
        for i in range(39):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="idp",
                value=int(5000 * 1.10),  # 10% above market
                idpTradeCalc=5000,
                bucket="medium",
            ))
        # 1 outlier with drift ~0.70 (way below market)
        outlier = _make_row(
            name="outlier_low",
            asset_class="idp",
            value=1500,  # 70% below market 5000
            idpTradeCalc=5000,
            bucket="medium",
        )
        rows.append(outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})

        # All the "normal" rows have drift 0.10 — the 90th percentile of
        # the sample is also 0.10, so outlier's 0.70 drift exceeds it
        # and gets clamped to the band edge: anchor * (1 - 0.10) = 4500.
        self.assertIn("marketCorridorClamp", outlier)
        self.assertEqual(outlier["marketCorridorClamp"]["direction"], "up")
        self.assertEqual(outlier["marketCorridorClamp"]["originalValue"], 1500)
        # Clamped value should land at anchor × (1 − band).
        self.assertEqual(outlier["rankDerivedValue"], 4500)

    def test_single_extreme_outlier_gets_clamped_above_market(self):
        rows = []
        for i in range(39):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="idp",
                value=int(5000 * 1.10),
                idpTradeCalc=5000,
                bucket="medium",
            ))
        outlier = _make_row(
            name="outlier_high",
            asset_class="idp",
            value=int(5000 * 1.80),  # 80% above market
            idpTradeCalc=5000,
            bucket="medium",
        )
        rows.append(outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})
        self.assertIn("marketCorridorClamp", outlier)
        self.assertEqual(outlier["marketCorridorClamp"]["direction"], "down")
        # Band = 0.10 (P90 of the normal rows), so clamp = 5000 × 1.10
        self.assertEqual(outlier["rankDerivedValue"], 5500)

    def test_inside_band_no_clamp(self):
        """Rows with drifts below the bucket P90 must be untouched."""
        rows = []
        # 40 medium rows with uniform drift 0.20
        for i in range(40):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="offense",
                value=int(5000 * 1.20),
                ktc=5000,
                bucket="medium",
            ))
        _apply_market_corridor_clamp(rows, players_by_name={})
        for row in rows:
            self.assertNotIn("marketCorridorClamp", row)
            self.assertEqual(row["rankDerivedValue"], 6000)

    def test_no_anchor_no_clamp(self):
        """Rows without a market anchor value (e.g. pre-draft rookies
        with no KTC entry) get left alone."""
        rows = [_make_row(
            name="rookie_no_ktc",
            asset_class="offense",
            value=5000,
            ktc=None,
            bucket="low",
        )]
        # Pad with anchored rows so the function has a distribution to
        # compute a band from (otherwise it no-ops on empty).
        for i in range(40):
            rows.append(_make_row(
                name=f"anchored_{i}",
                asset_class="offense",
                value=5500,
                ktc=5000,
                bucket="medium",
            ))
        _apply_market_corridor_clamp(rows, players_by_name={})
        self.assertNotIn("marketCorridorClamp", rows[0])
        self.assertEqual(rows[0]["rankDerivedValue"], 5000)

    def test_small_bucket_falls_back_to_overall_p90(self):
        """A bucket with fewer than 30 rows borrows the overall P90.

        Build a board where the 'high' bucket has 5 rows (too small)
        and 'medium' has 50 rows with well-defined drift.  The 'high'
        outlier should be clamped using the OVERALL P90 (derived from
        medium + high combined), not its own 5-sample distribution.
        """
        rows = []
        for i in range(50):
            rows.append(_make_row(
                name=f"m_{i}",
                asset_class="offense",
                value=int(5000 * 1.15),  # medium drift 0.15
                ktc=5000,
                bucket="medium",
            ))
        # 5 high-confidence rows, one with extreme drift
        for i in range(4):
            rows.append(_make_row(
                name=f"h_{i}",
                asset_class="offense",
                value=int(5000 * 1.05),  # small drift 0.05
                ktc=5000,
                bucket="high",
            ))
        high_outlier = _make_row(
            name="h_outlier",
            asset_class="offense",
            value=int(5000 * 2.50),  # 150% drift
            ktc=5000,
            bucket="high",
        )
        rows.append(high_outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})
        # The high bucket only has 5 rows, so it falls back to overall
        # P90 which is dominated by the 50 medium-drift-0.15 rows →
        # overall P90 ≈ 0.15.  Outlier clamps to 5000 × 1.15 = 5750.
        self.assertIn("marketCorridorClamp", high_outlier)
        self.assertEqual(high_outlier["rankDerivedValue"], 5750)

    def test_unranked_rows_are_skipped(self):
        rows = [_make_row(
            name="unranked",
            asset_class="offense",
            value=100,
            ktc=5000,
            bucket="low",
        )]
        # Clear canonicalConsensusRank to simulate an unranked row.
        rows[0]["canonicalConsensusRank"] = None
        # Pad the distribution.
        for i in range(40):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="offense",
                value=int(5000 * 1.10),
                ktc=5000,
                bucket="medium",
            ))
        _apply_market_corridor_clamp(rows, players_by_name={})
        # Unranked row should NOT be touched.
        self.assertNotIn("marketCorridorClamp", rows[0])
        self.assertEqual(rows[0]["rankDerivedValue"], 100)


class TestClampStamps(unittest.TestCase):
    """When a clamp fires, the stamp must carry enough info to audit
    the decision from the UI / logs."""

    def test_stamp_fields_present(self):
        rows = [_make_row(
            name="outlier",
            asset_class="idp",
            value=100,
            idpTradeCalc=5000,
            bucket="low",
        )]
        for i in range(40):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="idp",
                value=int(5000 * 1.10),
                idpTradeCalc=5000,
                bucket="medium",
            ))
        _apply_market_corridor_clamp(rows, players_by_name={})
        stamp = rows[0].get("marketCorridorClamp")
        self.assertIsNotNone(stamp)
        for field in (
            "applied",
            "originalValue",
            "clampedValue",
            "marketAnchor",
            "marketSource",
            "bandPct",
            "percentile",
            "confidenceBucket",
            "direction",
        ):
            self.assertIn(field, stamp, f"missing {field}")
        self.assertTrue(stamp["applied"])
        self.assertEqual(stamp["marketSource"], "idpTradeCalc")
        self.assertEqual(stamp["marketAnchor"], 5000)
        self.assertEqual(stamp["originalValue"], 100)
        self.assertEqual(stamp["direction"], "up")

    def test_mirror_onto_legacy_dict(self):
        row = _make_row(
            name="Clamped",
            asset_class="offense",
            value=100,
            ktc=5000,
            bucket="low",
        )
        rows = [row]
        for i in range(40):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="offense",
                value=int(5000 * 1.10),
                ktc=5000,
                bucket="medium",
            ))
        legacy = {"Clamped": {"rankDerivedValue": 100}}
        _apply_market_corridor_clamp(rows, players_by_name=legacy)
        self.assertEqual(legacy["Clamped"]["rankDerivedValue"], row["rankDerivedValue"])
        self.assertIn("marketCorridorClamp", legacy["Clamped"])


class TestIdempotence(unittest.TestCase):
    """Running the clamp twice must not compound — after one pass
    every row's drift ≤ band, so a second pass should be a no-op."""

    def test_second_pass_no_additional_clamps(self):
        rows = [_make_row(
            name="outlier",
            asset_class="idp",
            value=100,
            idpTradeCalc=5000,
            bucket="medium",
        )]
        for i in range(40):
            rows.append(_make_row(
                name=f"p_{i}",
                asset_class="idp",
                value=int(5000 * 1.10),
                idpTradeCalc=5000,
                bucket="medium",
            ))
        _apply_market_corridor_clamp(rows, players_by_name={})
        clamped_val = rows[0]["rankDerivedValue"]
        _apply_market_corridor_clamp(rows, players_by_name={})
        # Second pass mustn't shift the value — the first pass already
        # brought every row inside the band.
        self.assertEqual(rows[0]["rankDerivedValue"], clamped_val)


if __name__ == "__main__":
    unittest.main()
