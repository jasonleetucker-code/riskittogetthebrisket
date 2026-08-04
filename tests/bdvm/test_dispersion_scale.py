"""Unmeasured dispersion must never buy a row more market confidence.

WHY THIS EXISTS
===============
``_dispersion_for_row`` used to pour three incommensurable numbers into
the single slot the liquidity and precision params were calibrated
against:

1. ``marketDispersionCV`` — a coefficient of variation.  The real one.
2. ``sourceRankPercentileSpread`` — a percentile spread, a DIFFERENT
   statistic.  On the 684 rows of the pinned 2026-07-30 contract that
   carry both, it runs a median **4.03x** larger (p10 1.46x, p90 8.61x).
3. a hardcoded ``0.20`` when neither was present — which sits near the
   **maximum** of the real CV scale (observed max 0.263, median 0.0215).

Because ``liquidity = clip(base + coeff x dispersion)``, that last one
is the sharp end: it ranked rows by how little was known about them.
Scoped to BDVM-priceable positions, against ``strong_buy_min_liquidity``
of 0.5:

    branch                          rows   liquidity > 0.5
    A measured marketDispersionCV    833    57 (  6.8%)
    B percentile-spread fallback      28    20 ( 71.4%)
    C hardcoded 0.20 (unmeasured)     53    53 (100.0%)

A player with no dispersion data at all was ~15x more likely to clear
the gate than one whose dispersion had actually been measured.

WHAT COULD DISAGREE WITH THAT, BEFORE
=====================================
Nothing.  The only assertion touching liquidity anywhere was
``test_market_isolation.py``'s ``alpha == 2000.0 * view.liquidity`` —
the expectation re-derived from the value under test, so its residual
was zero for any dispersion, any scale, any default.

SCOPE HONESTY
=============
The STRONG_BUY gate above is separately unreachable in production:
``buy_hold_sell`` requires ``persisted``, and ``service.py`` — the only
production caller — never passes ``gap_persisted_days``.  So the
15x-eligibility inversion sat downstream of an already-dead condition.
The channel that IS live is ``alpha = gap x liquidity``, feeding the
reachable BUY / SELL / STRONG_SELL: an unmeasured row's alpha was
inflated 1.74x (0.67 vs the 0.384 median measured liquidity) against
thresholds of +-400 / +-900.  Both are fixed here; the tests below pin
both.

NOT ``livedata``-marked: pure logic on synthetic rows, must block.
"""

from __future__ import annotations

import unittest

import copy
import json

from src.bdvm.market import (
    _dispersion_for_row,
    buy_hold_sell,
    market_comparison,
    market_view_for_row,
)
from src.bdvm.params import PARAMS_DIR, ParamSet, load_param_set

PARAMS = load_param_set("params_v1")
_LIQ = PARAMS["market"]["liquidity"]
_TH = PARAMS["market"]["signal_thresholds"]


def _params_with_liquidity_threshold(value: float) -> ParamSet:
    """A ParamSet identical to params_v1 but for one threshold.

    ``ParamSet`` is a read-only wrapper, not a mapping, so it cannot be
    spread — rebuild from the JSON through the public constructor.
    """
    payload = copy.deepcopy(json.loads((PARAMS_DIR / "params_v1.json").read_text()))
    payload["market"]["signal_thresholds"]["strong_buy_min_liquidity"] = value
    return ParamSet("params_v1_permissive_test", payload)


def _row(**fields):
    row = {"canonicalSiteValues": {"ktcSfTep": 4000.0}}
    row.update(fields)
    return row


class TestDispersionIsOneStatistic(unittest.TestCase):
    def test_measured_cv_is_used(self):
        self.assertAlmostEqual(_dispersion_for_row(_row(marketDispersionCV=0.08)), 0.08)

    def test_percentile_spread_is_not_a_substitute_for_a_cv(self):
        """The wrong-scale fallback, measured at a median 4.03x ratio."""
        d = _dispersion_for_row(_row(sourceRankPercentileSpread=0.21))
        self.assertIsNone(
            d,
            msg=(
                "sourceRankPercentileSpread is a percentile spread, not a coefficient "
                "of variation — on the live contract it runs a median 4.03x larger. "
                "Substituting it silently re-prices every row that lacks a CV."
            ),
        )

    def test_absent_dispersion_is_none_not_a_number(self):
        self.assertIsNone(_dispersion_for_row(_row()))

    def test_unmeasured_is_not_collapsed_to_zero(self):
        """Zero dispersion means 'every source agrees' — the strongest
        possible statement about a row, and the opposite of knowing
        nothing.  Absent, zero and unmeasured are three different things.
        """
        self.assertIsNotNone(_dispersion_for_row(_row(marketDispersionCV=0.0)))
        self.assertEqual(_dispersion_for_row(_row(marketDispersionCV=0.0)), 0.0)
        self.assertIsNone(_dispersion_for_row(_row()))


class TestUnmeasuredNeverBuysConfidence(unittest.TestCase):
    """The headline invariant: absence must not out-rank measurement."""

    def test_unmeasured_row_has_no_liquidity_number(self):
        view = market_view_for_row(_row(), "WR", PARAMS)
        self.assertIsNone(view.dispersion)
        self.assertIsNone(view.liquidity)
        out = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=False)
        self.assertIsNone(out["liquidity"])
        self.assertFalse(out["liquidityMeasured"])

    def test_unmeasured_alpha_never_exceeds_a_typical_measured_alpha(self):
        """The live channel.  Old behaviour inflated it 1.74x."""
        gap_fund = {"balanced": 6000.0}
        unmeasured = market_comparison(
            gap_fund,
            market_view_for_row(_row(), "WR", PARAMS),
            PARAMS,
            is_idp=False,
            is_rookie=False,
        )
        # 0.0215 is the measured median marketDispersionCV on the live board.
        typical = market_comparison(
            gap_fund,
            market_view_for_row(_row(marketDispersionCV=0.0215), "WR", PARAMS),
            PARAMS,
            is_idp=False,
            is_rookie=False,
        )
        self.assertLessEqual(
            abs(unmeasured["alpha"]),
            abs(typical["alpha"]),
            msg=(
                f"unmeasured alpha {unmeasured['alpha']} exceeds the typical measured "
                f"alpha {typical['alpha']}. A row we know nothing about must be HARDER "
                f"to signal on, never easier — scale it by the clip floor, not by a "
                f"default near the top of the real CV range."
            ),
        )

    def test_unmeasured_row_cannot_earn_a_liquidity_gated_signal(self):
        """STRONG_BUY requires a MEASURED liquidity, explicitly.

        The threshold is deliberately pushed BELOW where ``None -> 0.0``
        would land.  With the production 0.5 threshold, an unmeasured row
        fails this gate either way — by the explicit check OR by the
        arithmetic — and a test that cannot tell those apart is vacuous.
        Mutation-tested: with the production threshold, deleting
        ``and liquidity_measured`` from ``buy_hold_sell`` left this
        assertion GREEN. Lowering the threshold is what makes the
        explicit check the only thing standing between an unmeasured row
        and a STRONG_BUY, which is precisely the claim being pinned.

        This is not a hypothetical: the gate's correctness must not rest
        on a coincidence between a param value and a clip floor that are
        edited independently.
        """
        permissive = _params_with_liquidity_threshold(-1.0)
        huge_alpha = {
            "alpha": float(_TH["strong_buy_alpha"]) * 10,
            "liquidity": None,
            "liquidityMeasured": False,
        }
        got = buy_hold_sell(
            huge_alpha,
            permissive,
            gap_persisted_days=int(_TH["gap_persistence_days"]) + 5,
        )
        self.assertNotEqual(
            got["signal"],
            "STRONG_BUY",
            msg=(
                "a row with NO dispersion measurement earned STRONG_BUY once the "
                "threshold dropped below the clip floor. The gate must require "
                "liquidityMeasured explicitly, so absence fails it on purpose "
                "rather than by arithmetic accident."
            ),
        )

    def test_a_measured_row_clears_that_same_permissive_gate(self):
        """Control for the test above: the permissive threshold really is
        permissive, so the refusal there is about MEASUREMENT and not
        about the threshold being unreachable.
        """
        permissive = _params_with_liquidity_threshold(-1.0)
        got = buy_hold_sell(
            {
                "alpha": float(_TH["strong_buy_alpha"]) * 10,
                "liquidity": 0.0,
                "liquidityMeasured": True,
            },
            permissive,
            gap_persisted_days=int(_TH["gap_persistence_days"]) + 5,
        )
        self.assertEqual(got["signal"], "STRONG_BUY")

    def test_a_measured_liquid_row_still_can(self):
        """The asymmetry is the point — this must NOT be a blanket off switch."""
        got = buy_hold_sell(
            {
                "alpha": float(_TH["strong_buy_alpha"]) * 10,
                "liquidity": float(_TH["strong_buy_min_liquidity"]) + 0.2,
                "liquidityMeasured": True,
            },
            PARAMS,
            gap_persisted_days=int(_TH["gap_persistence_days"]) + 5,
        )
        self.assertEqual(got["signal"], "STRONG_BUY")

    def test_buy_and_sell_still_work_for_unmeasured_rows(self):
        """Degrade, never fail.

        BUY/SELL are not liquidity-gated and must keep working for rows
        with no dispersion — refusing to signal on them would take down
        working functionality to protect an optional refinement.
        """
        buy = buy_hold_sell(
            {"alpha": float(_TH["buy_alpha"]) + 50, "liquidity": None, "liquidityMeasured": False},
            PARAMS,
        )
        self.assertEqual(buy["signal"], "BUY")
        sell = buy_hold_sell(
            {
                "alpha": float(_TH["strong_sell_alpha"]) - 50,
                "liquidity": None,
                "liquidityMeasured": False,
            },
            PARAMS,
        )
        self.assertEqual(sell["signal"], "STRONG_SELL")


class TestParamsStillStraddleTheGate(unittest.TestCase):
    """C4 check: a threshold whose population sits entirely on one side
    is decorative or inverted.  Pin that the measured CV range actually
    reaches the gate, so a future param edit that makes STRONG_BUY
    unreachable for EVERY measured row is loud rather than silent.
    """

    def test_the_gate_is_currently_decorative_for_measured_rows(self):
        """Pins a MEASURED fact, and it is not a flattering one.

        Under ``clip(1.0 - 1.6·d, 0.2, 1.0)`` the worst observable
        dispersion (CV 0.263, live board max) still yields 0.579, above
        the 0.5 gate. So **no measured row can fail
        ``strong_buy_min_liquidity``** — 833 of 833 clear it. A
        threshold whose population sits entirely on one side is
        decorative, which is class 4 of the audit this module belongs to.

        This test does not pretend otherwise. It pins the current state
        so that (a) the fact is discoverable rather than folklore, and
        (b) a future re-tune that makes the gate bite — the fix — turns
        it red and forces this docstring to be rewritten with the new
        numbers, rather than leaving a stale claim behind.

        Deliberately NOT asserting the gate straddles: it does not, and
        an assertion that it does would fail today. Re-tuning the
        threshold is a calibration decision, recorded rather than made
        here.
        """
        cv_max_observed = 0.263  # live board maximum, 2026-07-30
        worst = min(
            float(_LIQ["clip_hi"]),
            max(
                float(_LIQ["clip_lo"]),
                float(_LIQ["base"]) - float(_LIQ["dispersion_coeff"]) * cv_max_observed,
            ),
        )
        self.assertGreater(
            worst,
            float(_TH["strong_buy_min_liquidity"]),
            msg=(
                f"the most dispersed observable row (CV {cv_max_observed}) now yields "
                f"liquidity {worst:.4f}, at or below the {_TH['strong_buy_min_liquidity']} "
                f"gate — so the gate has started to bite. That is an IMPROVEMENT over the "
                f"decorative state this test was written to pin. Update this test with the "
                f"new measured distribution rather than deleting it."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
