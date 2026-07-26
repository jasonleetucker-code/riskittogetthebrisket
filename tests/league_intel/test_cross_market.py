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


class TestSuppression:
    """Never silently rank what cannot be defensibly valued."""

    def test_mixed_package_with_ktc_only_offense_is_suppressed(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)]  # no IDPTC for WR1
        )
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED
        assert pkg.is_rankable is False
        assert pkg.total is None
        assert "WR1" in pkg.suppressed_reason

    def test_suppressed_package_has_zero_confidence(self):
        pkg = value_package([asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)])
        assert pkg.normalization_confidence == 0.0

    def test_empty_package_is_suppressed(self):
        pkg = value_package([])
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED
        assert pkg.is_rankable is False

    def test_unpriced_asset_suppresses_even_with_fallback_allowed(self):
        pkg = value_package(
            [asset("Ghost", "WR"), asset("LB1", "LB", idptc=3000)], allow_scalar_fallback=True
        )
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED


class TestScalarFallbackIsOptInAndLabelled:
    def test_fallback_is_off_by_default(self):
        pkg = value_package([asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)])
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED

    def test_fallback_converts_and_marks_the_converted_asset(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)],
            allow_scalar_fallback=True,
        )
        assert pkg.strategy is NormalizationStrategy.SCALAR_FALLBACK
        wr = next(a for a in pkg.assets if a.name == "WR1")
        assert wr.converted is True
        assert wr.raw_market_source == MARKET_KTC
        assert wr.normalized_market_value == pytest.approx(6000 * 1.012)

    def test_fallback_confidence_is_materially_lower(self):
        exact = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        approx = value_package(
            [asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)],
            allow_scalar_fallback=True,
        )
        assert approx.normalization_confidence < exact.normalization_confidence

    def test_fallback_states_its_measured_error(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000), asset("LB1", "LB", idptc=3000)],
            allow_scalar_fallback=True,
        )
        assert any("3.0%" in w and "11.7%" in w for w in pkg.warnings)


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

    def test_mixed_packages_mostly_resolve_on_the_exact_path(self):
        rows = self._rows()
        offense = [
            r
            for r in rows
            if (r.get("position") or "") in {"QB", "RB", "WR", "TE"}
            and (r.get("canonicalSiteValues") or {}).get(MARKET_KTC)
        ][:60]
        idp = [
            r
            for r in rows
            if (r.get("position") or "") in {"DL", "LB", "DB"}
            and (r.get("canonicalSiteValues") or {}).get(MARKET_IDPTC)
        ][:20]
        assert offense and idp
        exact = suppressed = 0
        for o in offense:
            pkg = value_package([o, idp[0]])
            if pkg.strategy is NormalizationStrategy.SINGLE_MARKET:
                exact += 1
            else:
                suppressed += 1
        # Most offense players carry an IDPTC value, so the exact path
        # dominates; the rest suppress rather than mis-sum.
        assert exact > suppressed
        assert exact + suppressed == len(offense)

    def test_no_package_is_ever_valued_across_two_markets(self):
        """The invariant that closes F-1."""
        rows = self._rows()
        pool = [r for r in rows if (r.get("canonicalSiteValues") or {})][:200]
        for i in range(0, len(pool) - 1, 7):
            pkg = value_package([pool[i], pool[i + 1]])
            if pkg.is_rankable:
                sources = {a.raw_market_source for a in pkg.assets if not a.converted}
                assert len(sources) == 1, f"mixed sources {sources}"
