"""WS-J F-1 — cross-market package valuation.

The defect this prevents: summing KTC points and IDPTC points for a
mixed offense/IDP package and gating market-fairness on the result.
The tests below pin that such a package is either valued on ONE market
or suppressed — never silently summed across two.
"""

from __future__ import annotations

import pytest

from src.league_intel.cross_market import (
    _RATIO_P10,
    _RATIO_P90,
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


class TestScalarFallbackFlagIsLive:
    """P1-a regression: ``allow_scalar_fallback`` was declared and never
    read, so the scalar path ran unconditionally and the docstring's
    "opt-in only" promise was false.  A parameter that changes nothing
    is worse than no parameter — a caller can believe it opted out.

    The default is True: the measurement in the module docstring shows
    the assets the fallback rescues are entirely fringe, so refusing
    them protected no decision.  These tests pin that BOTH settings are
    honoured, and that they actually differ.
    """

    @staticmethod
    def _needs_conversion():
        # IDP forces IDPTC; the fringe WR is KTC-only -> no single
        # market covers the package.
        return [asset("Fringe", "WR", ktc=1000), asset("LB1", "LB", idptc=4200)]

    def test_explicit_true_converts(self):
        pkg = value_package(self._needs_conversion(), allow_scalar_fallback=True)
        assert pkg.strategy is NormalizationStrategy.SCALAR_FALLBACK
        assert pkg.is_rankable is True

    def test_explicit_false_suppresses_instead_of_converting(self):
        pkg = value_package(self._needs_conversion(), allow_scalar_fallback=False)
        assert pkg.strategy is NormalizationStrategy.SUPPRESSED
        assert pkg.is_rankable is False
        assert pkg.total is None

    def test_the_flag_actually_changes_the_outcome(self):
        """The exact assertion the inert parameter would have failed."""
        rows = self._needs_conversion()
        assert (
            value_package(rows, allow_scalar_fallback=True).strategy
            is not value_package(rows, allow_scalar_fallback=False).strategy
        )

    def test_strict_suppression_names_the_offending_asset(self):
        pkg = value_package(self._needs_conversion(), allow_scalar_fallback=False)
        assert "Fringe" in pkg.label
        assert "Fringe" in pkg.suppressed_reason
        assert "fallback is disabled" in pkg.suppressed_reason

    def test_strict_mode_does_not_touch_packages_that_never_needed_it(self):
        rows = [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        strict = value_package(rows, allow_scalar_fallback=False)
        assert strict.strategy is NormalizationStrategy.SINGLE_MARKET
        assert strict.total == 9050


class TestExactArithmeticIsNotACertainAnswer:
    """P1-b regression: a mixed offense/IDP package summed on IDPTC was
    stamped ``uncertainty_band = 0.0``, which said the number was beyond
    doubt.  The ARITHMETIC is exact — no conversion happened — but the
    total still rests wholly on SHARED_SCALE_ASSUMPTION.  A zero band
    made the straddle check in compare_packages() unreachable for
    exactly the packages that assumption is load-bearing for.
    """

    def test_mixed_single_market_package_must_not_report_a_zero_band(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert pkg.strategy is NormalizationStrategy.SINGLE_MARKET  # still exact arithmetic
        assert pkg.uncertainty_band > 0, "assumption-priced total reported as certain"

    def test_band_is_the_idp_subtotal_times_the_measured_spread(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert pkg.uncertainty_band == pytest.approx(3000 * (_RATIO_P90 - _RATIO_P10))

    def test_offense_only_package_keeps_a_zero_band(self):
        """The assumption is never used, so there is nothing to size."""
        pkg = value_package([asset("WR1", "WR", ktc=6000), asset("RB1", "RB", ktc=4000)])
        assert pkg.uncertainty_band == 0.0

    def test_the_band_reaches_the_verdict(self):
        """The reported symptom: a mixed IDPTC package landing just
        under a 5% gate came back verdict_certain=True."""
        counter = value_package(
            [asset("WR1", "WR", ktc=3100, idptc=3000), asset("LB1", "LB", idptc=2200)]
        )
        offer = value_package([asset("WR2", "WR", ktc=5000)])
        cmp = compare_packages(counter, offer, gate_pct=5.0)
        assert cmp.market_gain_pct == pytest.approx(4.0)
        assert cmp.gain_low_pct < 5.0 < cmp.gain_high_pct
        assert cmp.verdict_certain is False
        assert cmp.is_rankable is False

    def test_far_from_the_gate_the_assumption_band_is_harmless(self):
        """It must not become a blanket suppression of IDP packages."""
        counter = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6000), asset("LB1", "LB", idptc=3000)]
        )
        offer = value_package([asset("WR2", "WR", ktc=2000)])
        cmp = compare_packages(counter, offer, gate_pct=5.0)
        assert counter.uncertainty_band > 0
        assert cmp.verdict_certain is True

    def test_mixed_package_warning_says_exact_but_assumed(self):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("LB1", "LB", idptc=3000)]
        )
        assert any("no conversion" in w and "assumed" in w for w in pkg.warnings)

    def test_scalar_path_stacks_conversion_and_assumption_bands(self):
        pkg = value_package([asset("Fringe", "WR", ktc=1000), asset("LB1", "LB", idptc=4200)])
        spread = _RATIO_P90 - _RATIO_P10
        assert pkg.uncertainty_band == pytest.approx(1000 * spread + 4200 * spread)


class TestPositionNormalizationIsShared:
    """CLAUDE.md makes POSITION_ALIASES the single source of truth for
    positions.  This module had copied angle.py's 14-spelling IDP list
    instead of importing, which (a) silently disagrees with finder.py's
    normalized ``{DL, LB, DB}`` and (b) breaks on any raw spelling
    nobody remembered to add.  These pin that raw spellings route to
    IDPTC, which is what decides the market.
    """

    @pytest.mark.parametrize(
        "raw",
        ["DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"],
    )
    def test_every_raw_idp_spelling_forces_the_idptc_board(self, raw):
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("D1", raw, idptc=3000)]
        )
        assert pkg.market == MARKET_IDPTC
        assert pkg.strategy is NormalizationStrategy.SINGLE_MARKET

    @pytest.mark.parametrize("raw", ["EDGE", "CB", "MLB"])
    def test_raw_spellings_also_carry_the_assumption_band(self, raw):
        """The band keys on the IDP subtotal, so a missed spelling would
        silently zero it — the P1-b defect through a side door."""
        pkg = value_package(
            [asset("WR1", "WR", ktc=6000, idptc=6050), asset("D1", raw, idptc=3000)]
        )
        assert pkg.uncertainty_band > 0

    @pytest.mark.parametrize("raw", ["QB", "RB", "WR", "TE", "PICK"])
    def test_offense_spellings_are_not_swept_into_idp(self, raw):
        pkg = value_package([asset("X", raw, ktc=6000)])
        assert pkg.market == MARKET_KTC
        assert pkg.uncertainty_band == 0.0


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


# ── The module's own importer census (lane brief: "evaluate cross_market") ──
#
# This file's docstring has now carried TWO wrong claims about its own reach:
# first "zero production importers", then "angle.py is still not rewired and
# the defect is still live there".  Both were true once and neither was true
# when it was read.  A prose census in a docstring decays silently; this one
# fails.


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _python_sources():
    root = _repo_root()
    for path in (root / "src").rglob("*.py"):
        yield path
    yield root / "server.py"


def test_the_documented_importer_census_is_the_real_one():
    """Exactly these modules import from ``cross_market``, and no others.

    A new importer is not forbidden — it is required to update the table in
    the module docstring, which is the only place this module's blast radius
    is written down.
    """
    import re

    documented = {
        "src/api/gameplan.py",
        "src/roster_intel/packages.py",
        "src/trade/angle.py",
    }
    pattern = re.compile(r"^\s*from\s+src\.league_intel\.cross_market\s+import", re.M)
    root = _repo_root()
    found = set()
    for path in _python_sources():
        rel = path.relative_to(root).as_posix()
        if rel == "src/league_intel/cross_market.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            found.add(rel)
    assert found == documented, (
        "cross_market's importer set changed — update the census table in its "
        f"docstring.  added={sorted(found - documented)} "
        f"removed={sorted(documented - found)}"
    )


def test_angle_sums_no_per_asset_market_value():
    """The defect this module exists for stays closed, in live code.

    Docstrings are exempt because ``angle.py`` and this module both QUOTE the
    retired expression to explain what was removed — the same trap that made
    two earlier guards in this repo decorative (#909).
    """
    import ast

    path = _repo_root() / "src" / "trade" / "angle.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        key = node.slice
        if isinstance(key, ast.Constant) and key.value == "market_value":
            offenders.append(node.lineno)
    assert offenders == [], (
        "angle.py reads a per-asset 'market_value' in live code at line(s) "
        f"{offenders} — package totals must come from value_package, which "
        "prices the whole package inside ONE market"
    )
