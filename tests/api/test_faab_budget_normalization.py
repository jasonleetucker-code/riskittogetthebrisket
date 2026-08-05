"""FAAB history must be comparable across seasons before it is averaged.

A bid only means something as a share of the budget it was placed under. This
league's waiver budget has been $1000, $200 and $100 across seasons, and every
aggregate in `faab_analytics` pooled the RAW dollar figures — so a $200 bid
from a $1000-budget season (20% of it) was averaged against $100 budgets as
though it were 200% of one.

Captured from the live endpoint during the audit
(`docs/master-site-audit/evidence/W11/faab-analytics.json`):

    leagueBudget          100
    positionBids.RB       avg 43.0, max 340
    positionBids.QB       avg 37.74, max 223
    positionBids.WR       avg 20.84, max 200

A max of 340 in a $100 league is the tell. `faab_recommender` blends the
position average 50/50 into every recommendation for any position with 3+
historical bids — all eight of them — so replacement-level running backs drew
$22-$32 bids on a $100 budget. That is the over-aggression the owner reported.
Audit finding W11-F001 (P0, upheld under adversarial review).

The aggregates are now normalized into current-season dollars. `recentWins`
and `playerHistory` keep the raw figures with their own `seasonBudget`,
because "$223 in 2023" is a true statement about that season and rescaling it
would falsify a record the UI presents as history.
"""

from __future__ import annotations

import unittest

from src.api.faab_analytics import _normalize_bid


class TestNormalizeBid(unittest.TestCase):
    def test_expresses_a_bid_as_the_same_share_of_the_current_budget(self):
        # 20% of a $1000 budget is $20 of a $100 one.
        self.assertEqual(_normalize_bid(200, 1000, 100), 20.0)
        # 34% of $1000 -> $34 of $100. The live RB max was 340.
        self.assertEqual(_normalize_bid(340, 1000, 100), 34.0)
        # 25% of $200 -> $25 of $100.
        self.assertEqual(_normalize_bid(50, 200, 100), 25.0)

    def test_is_a_no_op_within_the_current_budget(self):
        self.assertEqual(_normalize_bid(30, 100, 100), 30.0)
        self.assertEqual(_normalize_bid(0, 100, 100), 0.0)

    def test_scales_up_when_the_current_budget_is_larger(self):
        # 10% of $100 is $100 of a $1000 budget.
        self.assertEqual(_normalize_bid(10, 100, 1000), 100.0)

    def test_a_zero_or_missing_season_budget_passes_the_bid_through(self):
        # Better to leave a figure unscaled than to divide by zero or
        # invent a denominator.
        self.assertEqual(_normalize_bid(25, 0, 100), 25.0)
        self.assertEqual(_normalize_bid(25, -5, 100), 25.0)

    def test_the_defect_arithmetic_no_longer_holds(self):
        """The specific 5x inflation the audit measured.

        Mixed-budget history for one position: three bids that are each
        ~20% of their own season's budget. Raw pooling averages them to
        113.33 in a $100 league — larger than the entire budget. Normalized,
        every one is $20.
        """
        history = [(200, 1000), (40, 200), (20, 100)]
        raw_avg = sum(b for b, _ in history) / len(history)
        norm_avg = sum(_normalize_bid(b, sb, 100) for b, sb in history) / len(history)

        self.assertAlmostEqual(raw_avg, 86.667, places=2)
        self.assertEqual(norm_avg, 20.0)
        # The raw average exceeds a plausible single bid by >4x.
        self.assertGreater(raw_avg / norm_avg, 4.0)

    def test_a_bid_can_never_normalize_above_the_current_budget(self):
        """A full-budget bid is the ceiling, whatever season it came from."""
        for season_budget in (100, 200, 1000):
            with self.subTest(season_budget=season_budget):
                full = _normalize_bid(season_budget, season_budget, 100)
                self.assertEqual(full, 100.0)


if __name__ == "__main__":
    unittest.main()
