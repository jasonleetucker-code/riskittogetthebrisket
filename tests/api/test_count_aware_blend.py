"""Framework step 9: count-aware mean-median blend.

Unit tests for ``count_aware_mean_median_blend`` — the helper that
decides per-source-count aggregation:

  n == 1   → passthrough
  n == 2   → mean; MAD = half-range
  n == 3-4 → untrimmed mean-median
  n ≥ 5    → trimmed (drop one max + one min) mean-median

The prior implementation trimmed at n≥3, which collapsed sparse
IDP / rookie groups.  These tests pin the updated rule so no future
refactor silently over-trims or silently switches the threshold.
"""
from __future__ import annotations

import pytest

from src.api.data_contract import count_aware_mean_median_blend as blend


class TestSingleSource:
    def test_single_value_passthrough(self):
        center, mad = blend([5000.0])
        assert center == 5000.0
        assert mad is None

    def test_empty_input(self):
        center, mad = blend([])
        assert center == 0.0
        assert mad is None


class TestTwoSources:
    def test_two_sources_use_mean(self):
        center, mad = blend([6000.0, 8000.0])
        assert center == 7000.0
        # half-range equals MAD of 2 around their mean
        assert mad == 1000.0

    def test_two_sources_equal(self):
        center, mad = blend([5000.0, 5000.0])
        assert center == 5000.0
        assert mad == 0.0


class TestThreeSourcesUntrimmed:
    """n=3 must use ALL three values — prior impl trimmed to 1."""

    def test_three_sources_use_untrimmed_mean_median(self):
        center, mad = blend([3000.0, 5000.0, 9000.0])
        # mean = 17000/3 ≈ 5666.67
        # median = 5000
        # center = (5666.67 + 5000) / 2 ≈ 5333.33
        assert abs(center - 5333.33) < 0.1
        # MAD = mean(|v - mean|) = mean(|3000-5667|, |5000-5667|, |9000-5667|)
        #     = mean(2667, 667, 3333) ≈ 2222.22
        assert abs(mad - 2222.22) < 0.1

    def test_three_sources_clustered(self):
        center, mad = blend([5000.0, 5100.0, 5200.0])
        # mean = 5100, median = 5100, center = 5100
        assert center == 5100.0
        # Sparse case — MAD is modest, no spurious penalty
        assert abs(mad - 66.67) < 0.1

    def test_three_sources_not_collapsed_to_median(self):
        """Regression guard: the OLD rule trimmed n=3 to 1 element,
        which collapsed center to the median value.  Under the
        updated rule, center must differ from the bare median when
        mean and median disagree.
        """
        values = [2000.0, 5000.0, 8000.0]  # mean=5000, median=5000
        center_skewed, _ = blend(values)
        assert center_skewed == 5000.0  # both equal here

        values = [2000.0, 3000.0, 10000.0]  # mean=5000, median=3000
        center_skewed, _ = blend(values)
        # Under the UNTRIMMED rule center = (5000 + 3000) / 2 = 4000.
        # Under the OLD trimmed-to-1 rule center would have been 3000.
        assert center_skewed == 4000.0


class TestFourSourcesUntrimmed:
    """n=4 must use ALL four values — prior impl trimmed to 2."""

    def test_four_sources_use_untrimmed(self):
        values = [2000.0, 4000.0, 6000.0, 10000.0]
        center, mad = blend(values)
        # mean = 22000/4 = 5500
        # median = (4000 + 6000) / 2 = 5000
        # center = (5500 + 5000) / 2 = 5250
        assert center == 5250.0
        # MAD = mean(|2000-5500|, |4000-5500|, |6000-5500|, |10000-5500|)
        #     = mean(3500, 1500, 500, 4500) = 10000/4 = 2500
        assert mad == 2500.0

    def test_four_sources_differ_from_mean_of_middle_two(self):
        """Under OLD rule (trim to middle 2), mean would equal median.
        Under new rule (use all 4), mean and median generally differ.
        """
        values = [1000.0, 4000.0, 6000.0, 11000.0]
        center, _ = blend(values)
        # mean = 22000/4 = 5500
        # median = 5000
        # center = 5250
        assert center == 5250.0
        # OLD rule would have given center = (4000 + 6000) / 2 = 5000.
        # Assert the new rule's skew-toward-mean behavior.
        assert center != 5000.0


class TestFiveOrMoreSourcesTrimmed:
    """n ≥ 5 uses the trimmed mean-median (drop one high + one low)."""

    def test_five_sources_trimmed(self):
        values = [1000.0, 3000.0, 5000.0, 7000.0, 100000.0]
        center, mad = blend(values)
        # Trimmed set = [3000, 5000, 7000]
        # trimmed mean = 5000
        # trimmed median = 5000
        # center = 5000
        assert center == 5000.0
        # MAD over trimmed set: mean(|3000-5000|, |5000-5000|, |7000-5000|) = 1333.33
        assert abs(mad - 1333.33) < 0.1

    def test_outlier_removed_at_five_plus(self):
        """An extreme outlier at n=5 should get trimmed out —
        regression guard that the threshold at 5 is respected.
        """
        with_outlier = blend([5000.0, 5100.0, 5200.0, 5300.0, 50000.0])
        without_outlier = blend([5000.0, 5100.0, 5200.0, 5300.0])
        # With outlier (n=5): outlier trimmed, center should be close
        # to "small-value" cluster.
        assert abs(with_outlier[0] - 5200.0) < 10
        # Without outlier (n=4): untrimmed mean-median of the 4.
        # mean=5150, median=5150, center=5150.
        assert without_outlier[0] == 5150.0

    def test_seven_sources_trimmed(self):
        values = [1000.0, 2000.0, 4000.0, 5000.0, 6000.0, 8000.0, 20000.0]
        center, mad = blend(values)
        # Trimmed = [2000, 4000, 5000, 6000, 8000]
        # trimmed mean = 5000
        # trimmed median = 5000
        # center = 5000
        assert center == 5000.0


class TestMADConsistency:
    """MAD must be computed over the same set used to compute center."""

    def test_mad_matches_set_used_for_center_n3(self):
        # n=3 uses untrimmed; MAD should reflect full variation.
        values = [1000.0, 5000.0, 9000.0]
        _, mad = blend(values)
        # MAD over all 3 around their mean (5000): mean(4000, 0, 4000)
        #                                        = 8000/3 ≈ 2666.67
        assert abs(mad - 2666.67) < 0.1

    def test_mad_matches_set_used_for_center_n5(self):
        # n=5 trims outer pair; MAD should reflect only middle 3.
        values = [0.0, 1000.0, 5000.0, 9000.0, 20000.0]
        _, mad = blend(values)
        # Trimmed = [1000, 5000, 9000], mean = 5000
        # MAD = mean(4000, 0, 4000) ≈ 2666.67
        assert abs(mad - 2666.67) < 0.1
