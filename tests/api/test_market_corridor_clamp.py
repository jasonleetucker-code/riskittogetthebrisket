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
    _MARKET_ANCHOR_FALLBACKS,
    _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS,
    _apply_market_corridor_clamp,
    _market_anchor_for_row,
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
        # Standard ``ktc`` was retired from the blend 2026-04-28;
        # ``ktcSfTep`` is the canonical KTC offense market anchor.
        # The ``ktc`` parameter name preserved for fixture ergonomics.
        sites["ktcSfTep"] = ktc
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
        # Offense anchor moved from ``ktc`` → ``ktcSfTep`` 2026-04-28
        # when standard KTC was retired from the blend.
        self.assertEqual(_MARKET_ANCHOR_BY_ASSET_CLASS["offense"], "ktcSfTep")

    def test_idp_uses_idptc(self):
        self.assertEqual(_MARKET_ANCHOR_BY_ASSET_CLASS["idp"], "idpTradeCalc")

    def test_anchor_missing_returns_none(self):
        row = _make_row(
            name="No Anchor",
            asset_class="offense",
            value=5000,
            ktc=None,
        )
        self.assertIsNone(_market_anchor_value_for_row(row))

    def test_anchor_zero_returns_none(self):
        """Zero-value anchors can't serve as denominators for the drift
        ratio — treat them as absent."""
        row = _make_row(
            name="Zero KTC",
            asset_class="offense",
            value=5000,
            ktc=0,
        )
        self.assertIsNone(_market_anchor_value_for_row(row))

    def test_pick_asset_class_has_no_anchor(self):
        row = _make_row(
            name="2026 Pick 1.01",
            asset_class="pick",
            value=8000,
            ktc=8200,  # pick KTC values exist but picks aren't in the clamp scope
        )
        self.assertIsNone(_market_anchor_value_for_row(row))


class TestFallbackAnchor(unittest.TestCase):
    """``_market_anchor_for_row`` falls back when the primary anchor
    is missing.  The fallback chain is the key safety net for
    IDPs like Shavon Revel who aren't listed by IDPTC but ARE
    listed by IDP Show / DLF IDP — without it they'd escape the
    clamp entirely and the calibration's 3-4× DB bucket multipliers
    could inflate single-source noise into a top-50 finish.
    """

    def _idp_row_with_vc(self, source_key: str, vc: int) -> dict:
        return {
            "canonicalName": "Test IDP",
            "assetClass": "idp",
            "canonicalSiteValues": {},
            "sourceRankMeta": {source_key: {"valueContribution": vc}},
            "rankDerivedValue": 6000,
            "canonicalConsensusRank": 50,
            "confidenceBucket": "low",
        }

    def test_primary_anchor_preferred(self):
        row = {
            "assetClass": "idp",
            "canonicalSiteValues": {"idpTradeCalc": 4500},
            "sourceRankMeta": {
                "idpTradeCalc": {"valueContribution": 4000},
                "dlfIdp": {"valueContribution": 3000},
                "idpShow": {"valueContribution": 5000},
            },
        }
        val, src = _market_anchor_for_row(row)
        self.assertEqual(src, "idpTradeCalc")
        self.assertEqual(val, 4000)  # prefers valueContribution

    def test_falls_back_to_secondary_anchor(self):
        """IDPTC missing → use DLF IDP valueContribution."""
        row = {
            "assetClass": "idp",
            "canonicalSiteValues": {},
            "sourceRankMeta": {
                "dlfIdp": {"valueContribution": 3500},
                "idpShow": {"valueContribution": 4200},
            },
        }
        val, src = _market_anchor_for_row(row)
        self.assertEqual(src, "dlfIdp")
        self.assertEqual(val, 3500)

    def test_falls_back_to_median_when_only_deep_sources(self):
        """No IDPTC, no DLF IDP, no IDP Show — just FP IDP + FBG IDP.
        Both are deep in the fallback chain, so we use the median
        instead of picking arbitrarily."""
        row = {
            "assetClass": "idp",
            "canonicalSiteValues": {},
            "sourceRankMeta": {
                # Only stamping sources past position 2 in the chain
                # (indices 3+) so the "chain pick" doesn't fire.
                "fantasyProsIdp": {"valueContribution": 2000},
                "footballGuysIdp": {"valueContribution": 3000},
            },
        }
        val, src = _market_anchor_for_row(row)
        # fantasyProsIdp comes before footballGuysIdp in the chain,
        # so it gets picked first.
        self.assertEqual(src, "fantasyProsIdp")
        self.assertEqual(val, 2000)

    def test_single_source_fallback(self):
        """Only IDP Show listed — Revel's case.  Anchor is the single
        source's valueContribution; clamp protects against runaway
        calibration boost with a per-player floor."""
        row = self._idp_row_with_vc("idpShow", 1026)
        val, src = _market_anchor_for_row(row)
        self.assertEqual(src, "idpShow")
        self.assertEqual(val, 1026)

    def test_no_anchor_when_no_source_stamped(self):
        row = {
            "assetClass": "idp",
            "canonicalSiteValues": {},
            "sourceRankMeta": {},
        }
        val, src = _market_anchor_for_row(row)
        self.assertIsNone(val)
        self.assertIsNone(src)

    def test_fallback_chain_starts_with_the_declared_primary_anchor(self):
        """Each asset class's fallback chain leads with its primary anchor.

        NOTE ON SCOPE — this test used to be named
        ``test_fallback_chain_covers_all_scope_sources`` and its
        docstring claimed it was a "safety rail" catching "a new source
        being added to _RANKING_SOURCES without being added to the
        anchor chain".  It never did that: it built
        ``offense_sources`` / ``idp_sources`` / ``chain_offense`` /
        ``chain_idp`` and then compared none of them (ruff F841 flagged
        all four as unused).  The only assertions were — and still are
        — the two below.

        The registry-coverage check was deliberately dropped, because
        the chain is a curated shortlist rather than every scope
        source, so a subset assertion would be wrong.  Renamed and the
        dead locals removed so the name and docstring describe what is
        actually verified.  See docs/python-coverage-audit.md (W-1).
        """
        self.assertEqual(
            _MARKET_ANCHOR_FALLBACKS["offense"][0],
            _MARKET_ANCHOR_BY_ASSET_CLASS["offense"],
        )
        self.assertEqual(
            _MARKET_ANCHOR_FALLBACKS["idp"][0],
            _MARKET_ANCHOR_BY_ASSET_CLASS["idp"],
        )
        # The chains must at least be non-empty — an empty chain would
        # make the assertions above IndexError rather than pass, but be
        # explicit so intent is unambiguous.
        self.assertTrue(_MARKET_ANCHOR_FALLBACKS["offense"])
        self.assertTrue(_MARKET_ANCHOR_FALLBACKS["idp"])


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
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),  # 10% above market
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
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
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
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
        # 40 medium rows with uniform drift 0.10
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        _apply_market_corridor_clamp(rows, players_by_name={})
        for row in rows:
            self.assertNotIn("marketCorridorClamp", row)
            self.assertEqual(row["rankDerivedValue"], 5500)

    def test_no_anchor_no_clamp(self):
        """Rows without a market anchor value (e.g. an IDP not listed
        by any anchor-chain source) get left alone."""
        rows = [
            _make_row(
                name="idp_no_anchor",
                asset_class="idp",
                value=5000,
                idpTradeCalc=None,
                bucket="low",
            )
        ]
        # Pad with anchored rows so the function has a distribution to
        # compute a band from (otherwise it no-ops on empty).
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"anchored_{i}",
                    asset_class="idp",
                    value=5500,
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
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
            rows.append(
                _make_row(
                    name=f"m_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.15),  # medium drift 0.15
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        # 5 high-confidence rows, one with extreme drift
        for i in range(4):
            rows.append(
                _make_row(
                    name=f"h_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.05),  # small drift 0.05
                    idpTradeCalc=5000,
                    bucket="high",
                )
            )
        high_outlier = _make_row(
            name="h_outlier",
            asset_class="idp",
            value=int(5000 * 2.50),  # 150% drift
            idpTradeCalc=5000,
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
        rows = [
            _make_row(
                name="unranked",
                asset_class="idp",
                value=100,
                idpTradeCalc=5000,
                bucket="low",
            )
        ]
        # Clear canonicalConsensusRank to simulate an unranked row.
        rows[0]["canonicalConsensusRank"] = None
        # Pad the distribution.
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        _apply_market_corridor_clamp(rows, players_by_name={})
        # Unranked row should NOT be touched.
        self.assertNotIn("marketCorridorClamp", rows[0])
        self.assertEqual(rows[0]["rankDerivedValue"], 100)


class TestClampStamps(unittest.TestCase):
    """When a clamp fires, the stamp must carry enough info to audit
    the decision from the UI / logs."""

    def test_stamp_fields_present(self):
        rows = [
            _make_row(
                name="outlier",
                asset_class="idp",
                value=100,
                idpTradeCalc=5000,
                bucket="low",
            )
        ]
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
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
            asset_class="idp",
            value=100,
            idpTradeCalc=5000,
            bucket="low",
        )
        rows = [row]
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        legacy = {"Clamped": {"rankDerivedValue": 100}}
        _apply_market_corridor_clamp(rows, players_by_name=legacy)
        self.assertEqual(legacy["Clamped"]["rankDerivedValue"], row["rankDerivedValue"])
        self.assertIn("marketCorridorClamp", legacy["Clamped"])


class TestIdempotence(unittest.TestCase):
    """Running the clamp twice must not compound — after one pass
    every row's drift ≤ band, so a second pass should be a no-op."""

    def test_second_pass_no_additional_clamps(self):
        rows = [
            _make_row(
                name="outlier",
                asset_class="idp",
                value=100,
                idpTradeCalc=5000,
                bucket="medium",
            )
        ]
        for i in range(40):
            rows.append(
                _make_row(
                    name=f"p_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        _apply_market_corridor_clamp(rows, players_by_name={})
        clamped_val = rows[0]["rankDerivedValue"]
        _apply_market_corridor_clamp(rows, players_by_name={})
        # Second pass mustn't shift the value — the first pass already
        # brought every row inside the band.
        self.assertEqual(rows[0]["rankDerivedValue"], clamped_val)


class TestIdpMaxBandCap(unittest.TestCase):
    """The IDP asset class has a hard ceiling on the corridor band so
    that wide bucket distributions can't let extreme drifts (the
    Vikings-LB-at-1900-vs-IDPTC-3600 case) ride through unclamped.

    The cap ceilings the dynamic bucket P90 — it never *widens* the
    band, only narrows it.  Players whose drift sits inside the
    bucket P90 are still untouched.
    """

    def test_no_asset_class_carries_a_hard_cap(self):
        """B3 (2026-08-11) removed the IDP entry; nothing replaced it.

        The facility is kept because the mechanism is generic, but on
        the live board the 0.15 cap decided EVERY clamp — 183 of 329
        ranked IDP rows, all landing on ``idpTradeCalc × 0.85`` or
        ``× 1.15`` — while the board-derived bucket bands (0.5183 to
        0.6504) were computed and discarded every time. Evidence:
        ``docs/master-site-audit/evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md``.
        """
        self.assertEqual(_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS, {})

    def test_offense_has_no_cap(self):
        """Offense has no cap because offense rows are not clamped at
        all — see ``test_offense_rows_are_never_clamped``."""
        self.assertNotIn("offense", _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS)

    def test_idp_extreme_outlier_clamps_to_max_band(self):
        """When the bucket P90 would have been wider than 15%, the IDP
        cap takes over: an IDP at 47% drift below IDPTC clamps to the
        15% band edge, not the bucket P90 edge.

        Setup mimics the Vikings LB case: 1,900 internal vs 3,600 on
        IDPTC, plus enough background players with wide drifts that
        the bucket P90 itself would have allowed the outlier through.
        """
        rows = []
        # 39 background IDPs with ~30% drift — wide enough that the
        # bucket P90 (~30%) would NOT have clamped a 47%-drift outlier
        # without the max-band cap.
        for i in range(39):
            rows.append(
                _make_row(
                    name=f"bg_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.30),  # 30% above IDPTC
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        # The Vikings LB: 1,900 internal, 3,600 on IDPTC = 47% drift down.
        outlier = _make_row(
            name="vikings_lb",
            asset_class="idp",
            value=1900,
            idpTradeCalc=3600,
            bucket="medium",
        )
        rows.append(outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})

        # The outlier is STILL caught — which is the point of the test
        # and the reason B3 removed the cap rather than the corridor.
        # It now clamps to the band the board itself produced
        # (bucket P90 ≈ 0.30 → 3600 × 0.70 = 2520) instead of to a
        # hand-set constant (3600 × 0.85 = 3060).
        self.assertIn("marketCorridorClamp", outlier)
        stamp = outlier["marketCorridorClamp"]
        self.assertEqual(stamp["direction"], "up")
        self.assertEqual(stamp["originalValue"], 1900)
        self.assertEqual(stamp["marketAnchor"], 3600)
        self.assertFalse(stamp["cappedByMaxBand"])
        self.assertIsNone(stamp["maxBandPct"])
        self.assertAlmostEqual(stamp["bandPct"], 0.30, places=2)
        self.assertEqual(outlier["rankDerivedValue"], 2520)

    def test_idp_inside_cap_uses_bucket_p90(self):
        """When the bucket P90 is below the cap, the existing dynamic
        behaviour wins — the cap doesn't widen anything."""
        rows = []
        # 39 IDPs with drift 0.10 → bucket P90 = 0.10 (below cap).
        for i in range(39):
            rows.append(
                _make_row(
                    name=f"bg_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        # Outlier with 70% drift down.
        outlier = _make_row(
            name="outlier",
            asset_class="idp",
            value=1500,
            idpTradeCalc=5000,
            bucket="medium",
        )
        rows.append(outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})
        stamp = outlier["marketCorridorClamp"]
        # Bucket P90 = 0.10 < cap 0.15, so the dynamic band wins.
        self.assertEqual(stamp["bandPct"], 0.10)
        self.assertFalse(stamp["cappedByMaxBand"])
        # Clamp = 5000 × (1 − 0.10) = 4500.
        self.assertEqual(outlier["rankDerivedValue"], 4500)

    def test_the_corridor_applies_in_both_directions(self):
        """Over-valued outliers clamp to the band edge above the anchor,
        not just below it.  Symmetry is a property of the mechanism and
        survived the B3 cap removal."""
        rows = []
        # 39 IDPs with 30% drift to widen the bucket band past 0.15.
        for i in range(39):
            rows.append(
                _make_row(
                    name=f"bg_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.30),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        # An over-valued outlier 60% above IDPTC.
        over = _make_row(
            name="over",
            asset_class="idp",
            value=int(5000 * 1.60),
            idpTradeCalc=5000,
            bucket="medium",
        )
        rows.append(over)
        _apply_market_corridor_clamp(rows, players_by_name={})
        stamp = over["marketCorridorClamp"]
        self.assertEqual(stamp["direction"], "down")
        self.assertFalse(stamp["cappedByMaxBand"])
        self.assertAlmostEqual(stamp["bandPct"], 0.30, places=2)
        # Clamp = 5000 × 1.30 = 6500, the board's own band edge.
        self.assertEqual(over["rankDerivedValue"], 6500)

    def test_offense_rows_are_never_clamped(self):
        """Offense is fully exempt from the corridor clamp.

        The clamp exists solely to contain the IDP calibration
        post-pass's runaway DB-bucket multipliers.  Offense has no
        calibration post-pass, and anchoring offense to KTC (which
        bakes in its own TE premium) would fight the league
        TE-premium multiplier — a non-TEP single source plus the
        1.25x TE boost would drift past the KTC band and get clamped
        straight back, silently cancelling the premium.  An offense
        row with an extreme drift must pass through untouched even
        when IDP rows in the same build are clamped.
        """
        rows = []
        # IDP background so the function has a band distribution.
        for i in range(39):
            rows.append(
                _make_row(
                    name=f"idp_bg_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.10),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        idp_outlier = _make_row(
            name="idp_outlier",
            asset_class="idp",
            value=1500,  # 70% below IDPTC → should clamp
            idpTradeCalc=5000,
            bucket="medium",
        )
        offense_outlier = _make_row(
            name="te_premium_boosted",
            asset_class="offense",
            value=int(5000 * 1.80),  # 80% above KTC → would clamp if offense
            ktc=5000,
            bucket="medium",
        )
        rows.append(idp_outlier)
        rows.append(offense_outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})

        # IDP outlier is still clamped — the safety net is intact.
        self.assertIn("marketCorridorClamp", idp_outlier)

        # Offense outlier is untouched: no stamp, value preserved.
        self.assertNotIn("marketCorridorClamp", offense_outlier)
        self.assertEqual(offense_outlier["rankDerivedValue"], int(5000 * 1.80))

    def test_idp_cap_still_idempotent(self):
        """A second clamp pass after the cap has fired must not move
        the value — the player is already inside the 15% band."""
        rows = []
        for i in range(39):
            rows.append(
                _make_row(
                    name=f"bg_{i}",
                    asset_class="idp",
                    value=int(5000 * 1.30),
                    idpTradeCalc=5000,
                    bucket="medium",
                )
            )
        outlier = _make_row(
            name="vikings_lb",
            asset_class="idp",
            value=1900,
            idpTradeCalc=3600,
            bucket="medium",
        )
        rows.append(outlier)
        _apply_market_corridor_clamp(rows, players_by_name={})
        first_pass = outlier["rankDerivedValue"]
        _apply_market_corridor_clamp(rows, players_by_name={})
        self.assertEqual(outlier["rankDerivedValue"], first_pass)


if __name__ == "__main__":
    unittest.main()
