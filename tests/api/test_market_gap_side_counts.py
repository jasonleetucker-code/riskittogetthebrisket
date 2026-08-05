"""The contract must say how many voices formed each side of the gap.

W12-F007.  ``marketGapDirection`` / ``marketGapMagnitude`` are framed to
users as "retail versus expert consensus", but nothing on the row said how
many sources were on the consensus side.  On the 2026-08-04 contract, 34 of
the 281 rows carrying a directional verb had exactly ONE non-retail source
there — a disagreement between two numbers, published as a consensus.

The count has to come from where the sides are formed: a source whose pool
depth is unknown never enters either mean, so counting ``sourceRanks`` keys
at the call site would over-report the evidence.
"""

from __future__ import annotations

import unittest

from src.api.data_contract import (
    _market_gap_sides,
    _raw_market_gap_percentile,
)

RETAIL = {"ktcSfTep"}


class TestMarketGapSideCounts(unittest.TestCase):
    def test_counts_the_sources_that_actually_formed_each_side(self):
        retail, consensus = _market_gap_sides(
            {"ktcSfTep": 10, "dlfSf": 50, "fantasycalc": 60},
            {
                "ktcSfTep": {"rawRank": 10},
                "dlfSf": {"rawRank": 50},
                "fantasycalc": {"rawRank": 60},
            },
            {"ktcSfTep": 100, "dlfSf": 100, "fantasycalc": 100},
            RETAIL,
        )
        self.assertEqual(len(retail), 1)
        self.assertEqual(len(consensus), 2)

    def test_a_source_with_no_pool_depth_is_not_counted(self):
        # It never enters the mean, so counting it would over-report the
        # evidence behind the gap.
        retail, consensus = _market_gap_sides(
            {"ktcSfTep": 10, "dlfSf": 50, "fantasycalc": 60},
            {"ktcSfTep": {"rawRank": 10}, "dlfSf": {"rawRank": 50}},
            {"ktcSfTep": 100, "dlfSf": 100},  # no depth for fantasycalc
            RETAIL,
        )
        self.assertEqual(len(retail), 1)
        self.assertEqual(len(consensus), 1)

    def test_a_null_rank_is_not_a_source(self):
        _retail, consensus = _market_gap_sides(
            {"ktcSfTep": 10, "dlfSf": None},
            {"ktcSfTep": {"rawRank": 10}, "dlfSf": {"rawRank": 50}},
            {"ktcSfTep": 100, "dlfSf": 100},
            RETAIL,
        )
        self.assertEqual(len(consensus), 0)

    def test_the_gap_is_still_the_difference_of_those_two_means(self):
        args = (
            {"ktcSfTep": 10, "dlfSf": 30, "fantasycalc": 70},
            {
                "ktcSfTep": {"rawRank": 10},
                "dlfSf": {"rawRank": 30},
                "fantasycalc": {"rawRank": 70},
            },
            {"ktcSfTep": 100, "dlfSf": 100, "fantasycalc": 100},
            RETAIL,
        )
        retail, consensus = _market_gap_sides(*args)
        expected = sum(consensus) / len(consensus) - sum(retail) / len(retail)
        self.assertAlmostEqual(
            _raw_market_gap_percentile(*args), expected, places=12
        )


class TestRowsCarryTheCounts(unittest.TestCase):
    """The stamp has to survive into the payloads the surfaces read."""

    def test_delta_and_mirror_field_lists_carry_the_counts(self):
        from src.api import data_contract as dc

        for field in ("marketGapRetailSources", "marketGapConsensusSources"):
            self.assertIn(field, dc._TRUST_MIRROR_FIELDS, field)
            self.assertIn(field, dc._DELTA_PLAYER_FIELDS, field)

    def test_the_stamp_sits_beside_the_gap_it_describes(self):
        """A row with a gap must never carry an unstamped side count."""
        import inspect

        from src.api import data_contract as dc

        src = inspect.getsource(dc)
        self.assertIn('row["marketGapConsensusSources"] = len(', src)
        self.assertIn('row["marketGapRetailSources"] = len(', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
