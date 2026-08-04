"""Market-layer tests: isolation, source hygiene, gap/alpha, signals.

Phase-5 gates: the fundamental output must be fully reproducible with
no market data; the market can never alter a stored fundamental value;
raw incompatible values are never summed; rank-signal sources are never
read as market prices.
"""

from __future__ import annotations

import unittest

from src.bdvm.market import (
    MarketIsolationError,
    NORMALIZATION_VERSION,
    buy_hold_sell,
    market_comparison,
    market_view_for_row,
)
from src.bdvm.params import load_param_set

PARAMS = load_param_set("params_v1")


def offense_row(ktc=5000.0, extra=None):
    row = {"canonicalSiteValues": {"ktcSfTep": ktc}}
    if extra:
        row["canonicalSiteValues"].update(extra)
    return row


class TestMarketSourceHygiene(unittest.TestCase):
    def test_offense_prefers_ktc_sf_tep(self):
        view = market_view_for_row(offense_row(5000.0, {"ktc": 4800.0}), "WR", PARAMS)
        self.assertEqual(view.market_source, "ktcSfTep")
        self.assertEqual(view.market_value, 5000.0)
        self.assertEqual(view.market_type, "crowd")

    def test_idp_anchors_on_idp_trade_calc_only(self):
        row = {"canonicalSiteValues": {"ktcSfTep": 5000.0, "idpTradeCalc": 3200.0}}
        view = market_view_for_row(row, "LB", PARAMS)
        self.assertEqual(view.market_source, "idpTradeCalc")
        self.assertEqual(view.market_value, 3200.0)

    def test_rank_signal_sources_are_never_market_values(self):
        """fantasyCalc & friends store a synthetic rank encoding in
        canonicalSiteValues — reading them as prices is forbidden."""
        row = {"canonicalSiteValues": {"fantasyCalc": 999600.0, "dlfSf": 999500.0}}
        view = market_view_for_row(row, "WR", PARAMS)
        self.assertIsNone(view.market_value)
        self.assertIsNone(view.market_source)

    def test_missing_anchor_yields_no_gap_not_zero_gap(self):
        view = market_view_for_row({"canonicalSiteValues": {}}, "WR", PARAMS)
        out = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=False)
        self.assertIsNone(out["marketValue"])
        self.assertIsNone(out["gap"])
        self.assertIsNone(out["alpha"])
        self.assertIsNone(out["marketAdjusted"])

    def test_normalization_version_is_stamped(self):
        view = market_view_for_row(offense_row(), "WR", PARAMS)
        out = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=False)
        self.assertEqual(out["normalizationVersion"], NORMALIZATION_VERSION)


class TestIsolation(unittest.TestCase):
    def test_market_before_fundamentals_raises(self):
        view = market_view_for_row(offense_row(), "WR", PARAMS)
        with self.assertRaises(MarketIsolationError):
            market_comparison({}, view, PARAMS, is_idp=False, is_rookie=False)

    def test_market_never_mutates_fundamentals(self):
        fund = {"balanced": 6000.0, "contender": 5500.0, "rebuilder": 6400.0}
        before = dict(fund)
        view = market_view_for_row(offense_row(4000.0), "WR", PARAMS)
        out = market_comparison(fund, view, PARAMS, is_idp=False, is_rookie=False)
        self.assertEqual(fund, before)
        # marketAdjusted is a separate labeled output, not an overwrite
        self.assertNotEqual(out["marketAdjusted"], fund["balanced"])


class TestGapAlphaMath(unittest.TestCase):
    def _view_at_dispersion(self, cv):
        row = offense_row(4000.0)
        row["marketDispersionCV"] = cv
        return market_view_for_row(row, "WR", PARAMS)

    def test_gap_and_alpha(self):
        view = market_view_for_row(offense_row(4000.0), "WR", PARAMS)
        out = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=False)
        self.assertAlmostEqual(out["gap"], 2000.0)
        self.assertAlmostEqual(out["alpha"], 2000.0 * view.liquidity, places=1)
        # λ=0.25 display blend
        self.assertAlmostEqual(out["marketAdjusted"], 6000.0 + 0.25 * (4000.0 - 6000.0), places=1)
        # λ=0.50 trade-clearing estimate
        self.assertAlmostEqual(out["tradeClearing"], 5000.0, places=1)

    def test_dispersion_lowers_liquidity_and_market_precision_together(self):
        """One input, one meaning (audit M7).

        ``liquidity`` used to RISE with cross-source disagreement while
        ``tau_market`` fell for the same input — the same number reading
        as "easy to trade" and "nobody agrees on the price" at once.
        Disagreement now lowers both.  Hand-derived from the config:
        liquidity = clip(1.0 − 1.6·d, 0.2, 1.0) → 0.92 at d=0.05,
        0.36 at d=0.40, and the 0.2 floor from d=0.5 on.
        """
        tight = self._view_at_dispersion(0.05)
        wide = self._view_at_dispersion(0.40)
        floored = self._view_at_dispersion(0.90)
        self.assertAlmostEqual(tight.liquidity, 0.92, places=6)
        self.assertAlmostEqual(wide.liquidity, 0.36, places=6)
        self.assertAlmostEqual(floored.liquidity, 0.2, places=6)
        # …and the model's weight vs. the market rises with the same input
        out_tight = market_comparison(
            {"balanced": 6000.0}, tight, PARAMS, is_idp=False, is_rookie=False
        )
        out_wide = market_comparison(
            {"balanced": 6000.0}, wide, PARAMS, is_idp=False, is_rookie=False
        )
        self.assertGreater(out_wide["blendWeightModel"], out_tight["blendWeightModel"])
        self.assertLess(out_wide["liquidity"], out_tight["liquidity"])

    def test_idp_and_rookie_lower_market_precision(self):
        view = market_view_for_row(offense_row(4000.0), "WR", PARAMS)
        base = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=False)
        idp = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=True, is_rookie=False)
        rook = market_comparison({"balanced": 6000.0}, view, PARAMS, is_idp=False, is_rookie=True)
        self.assertGreater(idp["blendWeightModel"], base["blendWeightModel"])
        self.assertGreater(rook["blendWeightModel"], base["blendWeightModel"])


class TestSignals(unittest.TestCase):
    def _out(self, alpha, liquidity=0.8):
        return {"alpha": alpha, "liquidity": liquidity}

    def test_strong_buy_requires_persistence_and_liquidity(self):
        s = buy_hold_sell(self._out(1500.0), PARAMS, gap_persisted_days=30)
        self.assertEqual(s["signal"], "STRONG_BUY")
        s2 = buy_hold_sell(self._out(1500.0), PARAMS, gap_persisted_days=3)
        self.assertEqual(s2["signal"], "HOLD")  # momentum guard
        s3 = buy_hold_sell(self._out(1500.0, liquidity=0.3), PARAMS, gap_persisted_days=30)
        self.assertEqual(s3["signal"], "BUY")  # liquid enough to buy, not to pound the table

    def test_strong_buy_is_reachable_without_gap_history(self):
        """No production caller has gap history, and none can: nothing
        stores it.  Requiring it made STRONG_BUY unreachable — a state
        ``ACTIONABLE_BDVM_SIGNALS`` advertises and alerts on (audit M7).
        Magnitude + liquidity, symmetric with STRONG_SELL, is the bar.
        """
        s = buy_hold_sell(self._out(1500.0), PARAMS)
        self.assertEqual(s["signal"], "STRONG_BUY")
        # …still gated on both halves of the bar
        self.assertEqual(buy_hold_sell(self._out(600.0), PARAMS)["signal"], "BUY")
        self.assertEqual(buy_hold_sell(self._out(1500.0, liquidity=0.3), PARAMS)["signal"], "BUY")

    def test_hold_band_and_sell(self):
        self.assertEqual(buy_hold_sell(self._out(100.0), PARAMS)["signal"], "HOLD")
        self.assertEqual(buy_hold_sell(self._out(-600.0), PARAMS)["signal"], "SELL")
        self.assertEqual(buy_hold_sell(self._out(-1200.0), PARAMS)["signal"], "STRONG_SELL")

    def test_collapse_strong_sell_needs_a_magnitude_floor(self):
        """A collapse probability escalates a sell; it does not invent one.

        The rule used to be ``p_collapse > 0.5 and alpha < 0``, checked
        BEFORE the alpha ladder — so a 1-point negative gap fired the
        loudest signal in the model (audit M7).
        """
        quiet = buy_hold_sell(self._out(-100.0), PARAMS, p_collapse_1y=0.65)
        self.assertEqual(quiet["signal"], "HOLD")  # inside the hold band
        loud = buy_hold_sell(self._out(-600.0), PARAMS, p_collapse_1y=0.65)
        self.assertEqual(loud["signal"], "STRONG_SELL")
        self.assertIn("collapse", loud["reason"])
        # without the collapse probability the same alpha is a plain SELL
        self.assertEqual(buy_hold_sell(self._out(-600.0), PARAMS)["signal"], "SELL")

    def test_no_market_signal(self):
        s = buy_hold_sell({"alpha": None}, PARAMS)
        self.assertEqual(s["signal"], "NO_MARKET")


if __name__ == "__main__":
    unittest.main()
