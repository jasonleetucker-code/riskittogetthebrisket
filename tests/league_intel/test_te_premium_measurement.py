"""Axis A (KTC's measured uplift) and Axis B (the league's own scoring).

Collaborative audit, finding F.  These pin the two things the live
``_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15`` conflates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel.te_premium import (
    load_tep_curve,
    measure_league_te_premium,
    tep_uplift,
)

REPO = Path(__file__).resolve().parents[2]

# The operator's league, read from the committed snapshot rather than
# retyped, so this test tracks the real scoring rather than a copy of it.
_SNAPSHOT = REPO / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json"


class TestAxisBTheLeagueScoring:
    def test_operators_league_measures_exactly_one(self):
        """The finding that motivated this module.

        The live pipeline applies a 1.15x TE boost. The league grants no
        TE premium at all — and not merely because ``bonus_rec_te`` is 0:
        every TE-touching key is matched by its WR/RB equivalent.
        """
        scoring = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["scoring_settings"]
        m = measure_league_te_premium(scoring)
        assert m.measured is True
        assert m.has_positional_edge is False
        assert m.multiplier == 1.0

    def test_first_down_bonus_shared_with_wr_is_not_a_te_premium(self):
        """``bonus_fd_te = 1.0`` looks like a TE premium until you notice
        ``bonus_fd_wr`` is also 1.0. Reading the TE key alone — which the
        existing ``_derive_tep_multiplier_from_league`` does — would miss
        this in the other direction."""
        m = measure_league_te_premium(
            {"bonus_rec_te": 0.0, "bonus_fd_te": 1.0, "bonus_fd_wr": 1.0, "bonus_fd_rb": 1.0}
        )
        assert m.has_positional_edge is False
        assert m.multiplier == 1.0
        assert m.edges["bonus_fd_te"] == 0.0

    def test_a_real_te_only_bonus_is_detected(self):
        m = measure_league_te_premium(
            {"bonus_rec_te": 0.5, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0}
        )
        assert m.has_positional_edge is True
        assert m.edges["bonus_rec_te"] == 0.5

    def test_a_real_edge_yields_no_multiplier_rather_than_a_guess(self):
        """The module must not invent a points-to-value slope it cannot
        measure. ``None`` is the honest answer; 1.15 was not."""
        m = measure_league_te_premium({"bonus_rec_te": 0.5, "bonus_rec_wr": 0.0})
        assert m.multiplier is None
        assert "volume data" in m.reason

    def test_a_te_first_down_edge_over_wr_counts(self):
        m = measure_league_te_premium({"bonus_fd_te": 1.5, "bonus_fd_wr": 1.0, "bonus_fd_rb": 1.0})
        assert m.has_positional_edge is True
        assert m.edges["bonus_fd_te"] == pytest.approx(0.5)

    def test_absent_scoring_is_unmeasured_not_neutral(self):
        """'No data' and 'measured as no premium' must not collapse to the
        same answer — that is how an assumption becomes a measurement."""
        for empty in (None, {}):
            m = measure_league_te_premium(empty)
            assert m.measured is False
            assert m.multiplier is None

    def test_zero_is_a_measurement_not_an_absence(self):
        m = measure_league_te_premium({"bonus_rec_te": 0.0, "bonus_rec_wr": 0.0})
        assert m.measured is True
        assert m.multiplier == 1.0


class TestAxisATheKtcUpliftCurve:
    def test_uplift_never_drops_below_one(self):
        """A TE premium cannot lower a tight end's value. The rejected
        log-linear fit predicted a ratio of 0.938 at the top of the board;
        this form cannot, at any input."""
        for v in (0, 1, 10, 500, 1000, 5000, 9999, 10**6):
            assert tep_uplift(v) >= 1.0

    def test_uplift_is_monotone_decreasing_in_value(self):
        """Measured: the premium is proportionally larger for cheaper TEs."""
        values = [500, 1000, 2000, 3000, 5000, 8000, 9999]
        ratios = [tep_uplift(v) for v in values]
        assert ratios == sorted(ratios, reverse=True)

    def test_curve_never_reads_below_the_observed_minimum(self):
        """The floor exists because the unconstrained fit read 1.146 at the
        most valuable TE against an observed 1.209 — it would have
        UNDER-credited the premium exactly where the board is densest in
        value."""
        curve = json.loads(
            (REPO / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
        )
        floor = curve["floor"]
        for v in (1, 500, 3000, 8169, 9999, 10**6):
            assert tep_uplift(v) >= floor - 1e-9

    def test_curve_brackets_the_observed_range_across_the_board(self):
        """73 real TEs span 1.209..2.053; the curve should sit inside that
        band across the value range those TEs actually occupy."""
        assert 1.20 <= tep_uplift(8169) < 1.30  # the top TE's base value
        assert 1.60 < tep_uplift(490) < 2.20  # the bottom TE's base value

    def test_live_blanket_constant_is_below_every_observed_ratio(self):
        """The finding, stated as an executable assertion.

        ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` is 1.15. The smallest uplift
        KTC actually applies to any TE is 1.209. So the live constant
        under-corrects for every single tight end, not merely on average.
        """
        from src.api.data_contract import _TE_BLANKET_NON_NATIVE_MULTIPLIER

        curve = json.loads(
            (REPO / "config" / "weights" / "te_premium_curve.json").read_text(encoding="utf-8")
        )
        observed_min = curve["observed_ratio_range"][0]
        assert _TE_BLANKET_NON_NATIVE_MULTIPLIER < observed_min, (
            "the live blanket TE multiplier is no longer below the observed "
            "range — re-read the audit before changing this test"
        )

    def test_config_and_fallback_agree(self):
        """A fresh checkout without the config must not silently use a
        different curve from a checkout with it."""
        from src.league_intel import te_premium as tp

        a, k, floor = load_tep_curve()
        assert a == pytest.approx(tp._FALLBACK_A, rel=1e-6)
        assert k == pytest.approx(tp._FALLBACK_K, rel=1e-6)
        assert floor == pytest.approx(tp._FALLBACK_FLOOR, rel=1e-4)


class TestTheTwoAxesStaySeparate:
    def test_league_measurement_does_not_consult_any_board(self):
        """Axis B must be a pure function of scoring rules. If it started
        reading KTC, a board change would silently move the league's
        premium."""
        import inspect

        from src.league_intel import te_premium as tp

        src = inspect.getsource(tp.measure_league_te_premium)
        for forbidden in ("ktc", "csv", "uplift", "load_tep_curve"):
            assert forbidden not in src.lower(), (
                f"measure_league_te_premium references {forbidden!r} — Axis B "
                "must not depend on any source board"
            )

    def test_uplift_does_not_consult_league_scoring(self):
        import inspect

        from src.league_intel import te_premium as tp

        src = inspect.getsource(tp.tep_uplift)
        for forbidden in ("bonus_rec", "scoring", "league"):
            assert forbidden not in src.lower(), (
                f"tep_uplift references {forbidden!r} — Axis A must not depend "
                "on league scoring, or the two multiply"
            )
