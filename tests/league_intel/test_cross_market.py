"""WS-J F-1 — cross-market package valuation.

The defect this prevents: summing KTC points and IDPTC points for a
mixed offense/IDP package and gating market-fairness on the result.
The tests below pin that such a package is either valued on ONE market
or suppressed — never silently summed across two.
"""

from __future__ import annotations

import pytest

from src.league_intel.cross_market import (
    MARKET_IDPTC,
    MARKET_KTC,
    NORMALIZATION_VERSION,
    NormalizationStrategy,
    compare_packages,
    value_package,
)


def asset(name, position, ktc=None, idptc=None):
    sites = {}
    if ktc is not None:
        sites[MARKET_KTC] = ktc
    if idptc is not None:
        sites[MARKET_IDPTC] = idptc
    return {"displayName": name, "position": position, "canonicalSiteValues": sites}


class TestSingleMarketIsExact:
    def test_offense_only_uses_ktc(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("RB1", "RB", ktc=4000, idptc=3950)]
        )
        assert pkg.strategy is NormalizationStrategy.SINGLE_MARKET
        assert pkg.market == MARKET_KTC
        assert pkg.total == 10000
        assert all(not a.converted for a in pkg.assets)

    def test_mixed_package_uses_idptc_the_only_spanning_board(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert pkg.strategy is NormalizationStrategy.SINGLE_MARKET
        assert pkg.market == MARKET_IDPTC
        assert pkg.total == 9050  # 6050 + 3000, both IDPTC
        assert pkg.is_mixed_market is True

    def test_mixed_package_never_sums_across_markets(self):
        """The live defect: 6000 (KTC) + 3000 (IDPTC) = 9000 is the
        wrong answer and must not appear."""
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert pkg.total != 9000
        assert all(a.raw_market_source == MARKET_IDPTC for a in pkg.assets)

    def test_idp_only_uses_idptc(self):
        pkg = value_package([asset("LB1", "LB", idptc=3000), asset("DL1", "DL", idptc=2500)])
        assert pkg.market == MARKET_IDPTC
        assert pkg.total == 5500

    def test_shared_scale_assumption_is_stamped_on_mixed_packages(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert any("assumed CORRECT" in w for w in pkg.warnings)

    def test_offense_only_package_carries_no_cross_market_assumption(self):
        pkg = value_package([asset("WR1", "WR", ktc=6000), asset("RB1", "RB", ktc=4000)])
        assert pkg.warnings == []


class TestPackageLevelSuppressionIsOnlyForUnvaluable:
    """A package in isolation has NO decision boundary, so it cannot
    adjudicate materiality.  It measures and stamps; the verdict-level
    decision lives in compare_packages."""

    def test_fringe_asset_is_converted_not_suppressed(self):
        pkg = value_package(
            [
                asset("Fringe", "WR", ktc=493),  # unpriced on IDPTC
                asset("WR1", "WR", ktc=6000, idptc=6050),
                asset("LB1", "LB", idptc=3000),
            ]
        )
        assert pkg.strategy is NormalizationStrategy.SCALAR_FALLBACK
        assert pkg.is_rankable is True
        assert pkg.uncertainty_band > 0

    def test_small_package_with_a_big_band_is_still_valued(self):
        """Revision 2's mistake: suppressing here presumed a boundary
        the package does not have."""
        pkg = value_package([asset("Fringe", "WR", ktc=493), asset("LB1", "LB", idptc=300)])
        assert pkg.strategy is NormalizationStrategy.SCALAR_FALLBACK
        assert pkg.uncertainty_band > 0

    def test_empty_package_is_suppressed_and_labelled(self):
        pkg = value_package([])
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED
        assert pkg.is_rankable is False
        assert pkg.label

    def test_asset_priced_on_neither_market_suppresses_and_labels(self):
        pkg = value_package([asset("Ghost", "WR"), asset("LB1", "LB", idptc=3000)])
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED
        assert "Ghost" in pkg.label


class TestBoundaryAwareComparison:
    """The materiality decision, where the boundary exists."""

    @staticmethod
    def _converted_counter():
        # IDP forces IDPTC; the fringe WR has no IDPTC value -> converted.
        return value_package([asset("Fringe", "WR", ktc=1000), asset("LB1", "LB", idptc=4200)])

    def test_far_from_the_gate_a_wide_band_does_not_matter(self):
        counter = self._converted_counter()
        offer = value_package([asset("WR2", "WR", ktc=2000, idptc=2000)])
        cmp = compare_packages(counter, offer)
        assert counter.uncertainty_band > 0
        assert cmp.market_gain_pct > 100
        assert cmp.verdict_certain is True
        assert cmp.is_rankable is True

    def test_near_the_gate_the_same_band_withholds(self):
        counter = self._converted_counter()
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        cmp = compare_packages(counter, offer)
        assert cmp.gain_low_pct < cmp.gate_pct < cmp.gain_high_pct
        assert cmp.verdict_certain is False
        assert cmp.is_rankable is False

    def test_exact_path_near_the_gate_stays_certain(self):
        """No conversion means no band means no doubt, however close."""
        counter = value_package([asset("WR1", "WR", ktc=5200, idptc=5200)])
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        cmp = compare_packages(counter, offer)
        assert counter.uncertainty_band == 0
        assert abs(cmp.market_gain_pct - 4.0) < 0.1
        assert cmp.verdict_certain is True

    def test_withheld_comparison_is_labelled_not_silent(self):
        counter = self._converted_counter()
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        cmp = compare_packages(counter, offer)
        assert cmp.label
        assert "too close to call" in cmp.label
        assert "uncertainty band" in cmp.suppressed_reason

    def test_unvaluable_side_propagates_its_label(self):
        counter = value_package([asset("Ghost", "WR"), asset("LB1", "LB", idptc=3000)])
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        cmp = compare_packages(counter, offer)
        assert cmp.is_rankable is False
        assert "Ghost" in cmp.label

    def test_gate_is_configurable(self):
        counter = self._converted_counter()
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        wide = compare_packages(counter, offer, gate_pct=50.0)
        assert wide.verdict_certain is True  # 4.2% nowhere near a 50% gate

    def test_comparison_serializes_with_the_band(self):
        counter = self._converted_counter()
        offer = value_package([asset("WR2", "WR", ktc=5000, idptc=5000)])
        d = compare_packages(counter, offer).to_dict()
        for key in ("marketGainPct", "gainLowPct", "gainHighPct", "verdictCertain", "label"):
            assert key in d


class TestScalarConversionIsLabelled:
    def test_conversion_marks_the_converted_asset(self):
        pkg = value_package(
            [
                asset("Fringe", "WR", ktc=1000),
                asset("WR1", "WR", ktc=6000, idptc=6050),
                asset("LB1", "LB", idptc=3000),
            ]
        )
        wr = next(a for a in pkg.assets if a.name == "Fringe")
        assert wr.converted is True
        assert wr.raw_market_source == MARKET_KTC
        assert wr.normalized_market_value == pytest.approx(1000 * 1.012)

    def test_conversion_confidence_is_materially_lower_than_exact(self):
        exact = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        approx = value_package(
            [
                asset("Fringe", "WR", ktc=1000),
                asset("WR1", "WR", ktc=6000, idptc=6050),
                asset("LB1", "LB", idptc=3000),
            ]
        )
        assert approx.normalization_confidence < exact.normalization_confidence

    def test_conversion_reports_its_uncertainty_band(self):
        pkg = value_package(
            [
                asset("Fringe", "WR", ktc=1000),
                asset("WR1", "WR", ktc=6000, idptc=6050),
                asset("LB1", "LB", idptc=3000),
            ]
        )
        assert any("uncertainty band" in w for w in pkg.warnings)
        assert pkg.to_dict()["uncertaintyBand"] > 0


class TestStamps:
    def test_required_stamps_present_on_every_asset(self):
        pkg = value_package([asset("WR1", "WR", ktc=6000)])
        d = pkg.assets[0].to_dict()
        for key in (
            "rawMarketValue",
            "rawMarketSource",
            "normalizedMarketValue",
            "normalizationVersion",
            "normalizationConfidence",
        ):
            assert key in d
        assert d["normalizationVersion"] == NORMALIZATION_VERSION

    def test_package_serializes_with_strategy_and_rankability(self):
        pkg = value_package([asset("WR1", "WR", ktc=6000)])
        d = pkg.to_dict()
        assert d["strategy"] == "singleMarket"
        assert d["isRankable"] is True
        assert d["normalizationVersion"] == NORMALIZATION_VERSION

    def test_legacy_ktc_key_still_reads(self):
        row = {
            "displayName": "Old",
            "position": "WR",
            "canonicalSiteValues": {"ktc": 5000},
        }
        pkg = value_package([row])
        assert pkg.total == 5000


class TestRealBoardCoverage:
    """How often does the exact path actually work on live data?"""

    @staticmethod
    def _rows():
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "audit" / "baseline" / "api_data.json"
        if not path.exists():
            pytest.skip("baseline contract snapshot not present")
        return json.loads(path.read_text())["playersArray"]

    @staticmethod
    def _value(row):
        sites = row.get("canonicalSiteValues") or {}
        for key in (MARKET_KTC, MARKET_IDPTC):
            try:
                v = float(sites.get(key) or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                return v
        return 0.0

    def test_realistic_trade_candidates_all_resolve_on_the_exact_path(self):
        """The measurement that settled the suppression debate: among
        assets anyone would actually trade (value >= 1500), EVERY mixed
        package resolves exactly.  The suppression bucket was entirely
        fringe players."""
        rows = self._rows()
        offense = [
            r
            for r in rows
            if (r.get("position") or "") in {"QB", "RB", "WR", "TE"} and self._value(r) >= 1500
        ][:80]
        idp = [
            r
            for r in rows
            if (r.get("position") or "") in {"DL", "LB", "DB"} and self._value(r) >= 1500
        ][:20]
        assert offense and idp
        strategies = {value_package([o, idp[0]]).strategy for o in offense}
        assert strategies == {NormalizationStrategy.SINGLE_MARKET}

    def test_unpriced_on_idptc_assets_are_all_fringe(self):
        """Why the exact path suffices: IDPTC only declines to price
        the tail."""
        rows = self._rows()
        ktc_only = [
            r
            for r in rows
            if (r.get("canonicalSiteValues") or {}).get(MARKET_KTC)
            and not (r.get("canonicalSiteValues") or {}).get(MARKET_IDPTC)
        ]
        assert ktc_only, "expected some KTC-only assets"
        assert max(self._value(r) for r in ktc_only) < 1500

    def test_no_package_is_ever_valued_across_two_markets(self):
        """The invariant that closes F-1."""
        rows = self._rows()
        pool = [r for r in rows if (r.get("canonicalSiteValues") or {})][:200]
        for i in range(0, len(pool) - 1, 7):
            pkg = value_package([pool[i], pool[i + 1]])
            if pkg.is_rankable:
                sources = {a.raw_market_source for a in pkg.assets if not a.converted}
                assert len(sources) == 1, f"mixed sources {sources}"
