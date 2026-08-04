"""The outcome side of the panel, which had no tests at all.

Every measurement this feature has ever published is a function of
`forward_returns`, and nothing exercised it. That is how the survivorship
gap survived: `forward_returns` gives an unmeasurable row a reason rather
than dropping it — which its docstring described as "never silently
dropped" — while every consumer then filtered on `excessReturn is not
None` and reported only what was left. Both halves were reasonable; the
seam between them was where the rows went.

So the tests here are about the seam, not the arithmetic:

- a row that leaves the anchor board between origin and horizon is
  RETAINED with a reason, not absent;
- `attrition` counts exactly those rows, including ones the outcome layer
  never saw at all;
- the cohort baseline is taken at the ORIGIN price, so a player is never
  judged against a peer group he only joined because of the move being
  measured.
"""

from __future__ import annotations

import unittest
from datetime import date

from src.consensus_edge import outcomes as oc


def _prices(**kwargs: float) -> dict[str, dict]:
    """Price map in the shape `market_prices` returns.

    Everyone is a WR so they share a cohort family; the value tier is
    what the price argument controls.
    """
    return {
        name: {"price": price, "assetClass": "offense", "position": "WR"}
        for name, price in kwargs.items()
    }


class TestForwardReturns(unittest.TestCase):
    def test_a_player_who_leaves_the_board_is_kept_with_a_reason(self):
        origin = _prices(stays=1000.0, leaves=1000.0)
        horizon = _prices(stays=1100.0)
        out = oc.forward_returns(origin, horizon)
        self.assertIn("leaves", out, "the row vanished instead of carrying a reason")
        self.assertIsNone(out["leaves"]["rawReturn"])
        self.assertEqual(out["leaves"]["reason"], oc.NO_FUTURE_PRICE)

    def test_a_zero_origin_price_is_refused_rather_than_dividing(self):
        origin = _prices(broken=0.0)
        out = oc.forward_returns(origin, _prices(broken=500.0))
        self.assertEqual(out["broken"]["reason"], oc.NO_START_PRICE)
        self.assertIsNone(out["broken"]["rawReturn"])

    def test_a_cohort_too_thin_to_have_a_median_yields_no_excess(self):
        # Fewer than 3 measurable peers: a "median" over one player is
        # that player, so his excess would be exactly zero by
        # construction — a fake result rather than a missing one.
        origin = _prices(alone=1000.0)
        out = oc.forward_returns(origin, _prices(alone=1200.0))
        self.assertAlmostEqual(out["alone"]["rawReturn"], 0.2, places=9)
        self.assertIsNone(out["alone"]["excessReturn"])
        self.assertEqual(out["alone"]["reason"], oc.NO_COHORT)

    def test_excess_is_measured_against_the_cohort_median(self):
        origin = _prices(a=1000.0, b=1000.0, c=1000.0, d=1000.0)
        horizon = _prices(a=1100.0, b=1100.0, c=1100.0, d=1300.0)
        out = oc.forward_returns(origin, horizon)
        # Median move is +10%; d moved +30%, so its excess is +20 points.
        self.assertAlmostEqual(out["d"]["excessReturn"], 0.2, places=9)
        self.assertAlmostEqual(out["a"]["excessReturn"], 0.0, places=9)

    def test_the_cohort_is_fixed_at_the_origin_price(self):
        # A player who doubles moves into a higher value tier. Judging
        # him against the tier he ENDED in would compare him to peers he
        # only joined because of the move under measurement.
        origin = _prices(mover=500.0, peer1=500.0, peer2=500.0)
        horizon = _prices(mover=5000.0, peer1=510.0, peer2=505.0)
        out = oc.forward_returns(origin, horizon)
        self.assertEqual(out["mover"]["cohort"], out["peer1"]["cohort"])
        self.assertGreater(out["mover"]["excessReturn"], 8.0)


class TestAttrition(unittest.TestCase):
    """The number that turns survivorship from a bias into a stated limit."""

    def test_it_counts_rows_that_could_not_be_scored(self):
        returns = {
            "scored": {"excessReturn": 0.05, "reason": None},
            "gone": {"excessReturn": None, "reason": oc.NO_FUTURE_PRICE},
        }
        lost = oc.attrition(["scored", "gone"], returns)
        self.assertEqual(lost["of"], 2)
        self.assertEqual(lost["dropped"], 1)
        self.assertAlmostEqual(lost["rate"], 0.5, places=9)
        self.assertEqual(lost["byReason"], {oc.NO_FUTURE_PRICE: 1})

    def test_a_key_the_outcome_layer_never_saw_is_still_counted(self):
        # A row the board scored and `forward_returns` has no entry for
        # is the same kind of silence as one with a reason, and must not
        # slip through as if it had been measured.
        lost = oc.attrition(["ghost"], {})
        self.assertEqual(lost["dropped"], 1)
        self.assertEqual(lost["byReason"], {"not_in_panel": 1})

    def test_a_fully_measured_bucket_reports_zero_not_none(self):
        returns = {"a": {"excessReturn": 0.01, "reason": None}}
        lost = oc.attrition(["a"], returns)
        self.assertEqual(lost["dropped"], 0)
        self.assertEqual(lost["rate"], 0.0)
        self.assertEqual(lost["byReason"], {})

    def test_an_empty_bucket_reports_no_rate_rather_than_zero(self):
        # 0/0 is not 0% attrition; it is no information.
        lost = oc.attrition([], {})
        self.assertEqual(lost["of"], 0)
        self.assertIsNone(lost["rate"])


class TestHorizonSnapping(unittest.TestCase):
    def test_it_snaps_forward_never_backward(self):
        available = [date(2026, 5, 1), date(2026, 5, 10), date(2026, 5, 20)]
        # 7 days past 2026-05-01 is 05-08, which is not in the panel. A
        # backward snap would shorten the holding period and bias every
        # return toward zero.
        self.assertEqual(oc.horizon_date(date(2026, 5, 1), 7, available), date(2026, 5, 10))

    def test_an_exact_hit_is_taken_as_is(self):
        available = [date(2026, 5, 1), date(2026, 5, 8)]
        self.assertEqual(oc.horizon_date(date(2026, 5, 1), 7, available), date(2026, 5, 8))

    def test_no_date_past_the_horizon_returns_none(self):
        available = [date(2026, 5, 1), date(2026, 5, 3)]
        self.assertIsNone(oc.horizon_date(date(2026, 5, 1), 30, available))


if __name__ == "__main__":
    unittest.main()
