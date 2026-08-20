"""Standings-credit primitives — pinned against
docs/PLAYER_IMPACT_WAR_MVP_SPEC.md §3, §11, §12.
"""

from __future__ import annotations

from src.war.standings import (
    LOSS_CREDIT,
    TIE_CREDIT,
    WIN_CREDIT,
    h2h_credit,
    median_credit,
    median_value,
    standings_credit,
)


class TestH2hCredit:
    def test_win(self):
        assert h2h_credit(120.0, 100.0) == WIN_CREDIT

    def test_loss(self):
        assert h2h_credit(90.0, 100.0) == LOSS_CREDIT

    def test_tie_uses_fractional_credit(self):
        assert h2h_credit(100.0, 100.0) == TIE_CREDIT == 0.5


class TestMedianValue:
    def test_odd_count(self):
        assert median_value([80.0, 100.0, 120.0]) == 100.0

    def test_even_count_averages_the_middle_two(self):
        assert median_value([80.0, 90.0, 110.0, 120.0]) == 100.0

    def test_empty_is_unavailable_not_zero(self):
        assert median_value([]) is None


class TestMedianCredit:
    def test_above_median_wins(self):
        assert median_credit(120.0, [80.0, 100.0, 120.0]) == WIN_CREDIT

    def test_below_median_loses(self):
        assert median_credit(80.0, [80.0, 100.0, 120.0]) == LOSS_CREDIT

    def test_exactly_at_median_ties(self):
        assert median_credit(100.0, [80.0, 100.0, 120.0]) == TIE_CREDIT

    def test_unavailable_when_no_scores(self):
        assert median_credit(100.0, []) is None


class TestStandingsCredit:
    def test_h2h_only_when_median_disabled(self):
        credit = standings_credit(120.0, 100.0, [120.0, 100.0, 80.0, 60.0], median_enabled=False)
        assert credit == WIN_CREDIT

    def test_win_both_is_2_0(self):
        """The spec's own worked example: a 2-0 week."""
        scores = [130.0, 90.0, 80.0, 70.0]  # this team 130, opponent 90
        credit = standings_credit(130.0, 90.0, scores, median_enabled=True)
        assert credit == 2.0

    def test_lose_both_is_0_0(self):
        scores = [70.0, 130.0, 90.0, 80.0]  # this team 70 (lowest)
        credit = standings_credit(70.0, 130.0, scores, median_enabled=True)
        assert credit == 0.0

    def test_win_h2h_lose_median_is_1_1_via_h2h(self):
        # This team 85 beats opponent 80 (H2H win), but the field is
        # strong enough that 85 sits below the league median.
        scores = [85.0, 80.0, 200.0, 190.0]
        credit = standings_credit(85.0, 80.0, scores, median_enabled=True)
        assert credit == 1.0  # win H2H (1.0) + lose median (0.0)

    def test_lose_h2h_win_median_is_1_1_via_median(self):
        scores = [85.0, 90.0, 20.0, 10.0]
        credit = standings_credit(85.0, 90.0, scores, median_enabled=True)
        assert credit == 1.0  # lose H2H (0.0) + win median (1.0)

    def test_ties_both_ways_sum_the_fractional_credits(self):
        scores = [100.0, 100.0, 100.0, 100.0]
        credit = standings_credit(100.0, 100.0, scores, median_enabled=True)
        assert credit == 1.0  # 0.5 tie H2H + 0.5 tie median
