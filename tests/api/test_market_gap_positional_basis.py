"""The market gap must measure mispricing, not a difference of scoring format.

`_compute_market_gap` averaged RAW ORDINAL ranks on each side. Two defects
followed, and they compound:

1. POOL DEPTH (W03-F006). Source pools on this board run 169-903 rows deep.
   Rank 50 of 169 and rank 50 of 903 were treated as the same number when
   they sit at wildly different percentiles. 47% of offense rows and 97% of
   pick rows flip sign once depth is accounted for.

2. POSITIONAL BASIS (W12-F002, P0, upheld). The retail side is a single
   source, `ktcSfTep`, and it is a TE-PREMIUM board; the consensus it is
   differenced against is dominated by base-TE boards. Every tight end
   therefore carried a large positive gap that says nothing about that
   player. Measured mean rank gap by position: TE +41.60, WR -6.83,
   RB -8.50, QB -24.69.

   The /rankings Edge column consequently labelled **32 of 35 top-250 tight
   ends SELL, and every single SELL in the top 250 was a tight end** — a user
   was being told to sell every tight end he owned.

Crucially, (2) is NOT fixed by the ADR-015 TE basis conversion: that operates
on VALUES inside the blend and this comparison never sees a value. Verified
by reproducing the same 32-of-35 against a clean `GET /api/data` with no
override in play. Two defects in one family, two code sites.

After the fix, measured on the real board rebuilt from
`exports/latest/dynasty_data_2026-08-04.json`: top-250 tight ends split 14
retail_premium / 21 consensus_premium, and the top-250 SELL side spreads
across QB 13, RB 17, WR 15, TE 14, PICK 11.
"""

from __future__ import annotations

import unittest

from src.api.data_contract import (
    _MARKET_GAP_MIN_POSITION_N,
    _center_market_gaps_by_position,
    _raw_market_gap_percentile,
)

RETAIL = {"ktcSfTep"}


class TestGapIsComputedInPercentileSpace(unittest.TestCase):
    def test_equal_percentiles_across_unequal_pools_are_a_tie(self):
        """Rank 20/200 and rank 90/900 are the same standing."""
        gap = _raw_market_gap_percentile(
            {"ktcSfTep": 20, "dlfSf": 90},
            {"ktcSfTep": {"rawRank": 20}, "dlfSf": {"rawRank": 90}},
            {"ktcSfTep": 200, "dlfSf": 900},
            retail_keys=RETAIL,
        )
        self.assertAlmostEqual(gap, 0.0, places=9)

    def test_ordinal_space_would_have_called_that_a_large_gap(self):
        """Characterises the defect: 90 - 20 = 70 ordinal 'ranks' apart."""
        self.assertEqual(90 - 20, 70)

    def test_sign_means_retail_ranks_the_player_better(self):
        # retail 10/100 = 0.10, consensus 50/100 = 0.50 -> retail higher.
        gap = _raw_market_gap_percentile(
            {"ktcSfTep": 10, "dlfSf": 50},
            {"ktcSfTep": {"rawRank": 10}, "dlfSf": {"rawRank": 50}},
            {"ktcSfTep": 100, "dlfSf": 100},
            retail_keys=RETAIL,
        )
        self.assertGreater(gap, 0)

    def test_none_when_one_side_is_absent(self):
        self.assertIsNone(
            _raw_market_gap_percentile(
                {"ktcSfTep": 10},
                {"ktcSfTep": {"rawRank": 10}},
                {"ktcSfTep": 100},
                retail_keys=RETAIL,
            )
        )

    def test_none_when_pool_depth_is_unknown(self):
        # Better to abstain than to divide by a guessed denominator.
        self.assertIsNone(
            _raw_market_gap_percentile(
                {"ktcSfTep": 10, "dlfSf": 50},
                {},
                {},
                retail_keys=RETAIL,
            )
        )


class TestPositionalCentering(unittest.TestCase):
    def _rows(self, pos: str, gaps: list[float]) -> list[dict]:
        return [{"position": pos, "_rawMarketGapPct": g} for g in gaps]

    def test_a_position_wide_offset_does_not_become_a_signal(self):
        """The W12-F002 shape: every TE offset positive by the same amount."""
        rows = self._rows("TE", [0.20] * 10)
        _center_market_gaps_by_position(rows)
        for r in rows:
            self.assertEqual(r["marketGapDirection"], "none")
            self.assertEqual(r["marketGapMagnitude"], 0.0)

    def test_within_position_deviation_survives(self):
        """Real signal is preserved: an outlier against its own position."""
        rows = self._rows("TE", [0.20] * 9 + [0.60])
        _center_market_gaps_by_position(rows)
        self.assertEqual(rows[-1]["marketGapDirection"], "retail_premium")
        self.assertGreater(rows[-1]["marketGapMagnitude"], 0.3)
        self.assertEqual(rows[0]["marketGapDirection"], "none")

    def test_a_player_below_their_position_baseline_reads_as_consensus_premium(self):
        rows = self._rows("TE", [0.20] * 9 + [0.05])
        _center_market_gaps_by_position(rows)
        self.assertEqual(rows[-1]["marketGapDirection"], "consensus_premium")

    def test_positions_are_centered_independently(self):
        rows = self._rows("TE", [0.20] * 10) + self._rows("RB", [-0.10] * 10)
        _center_market_gaps_by_position(rows)
        self.assertTrue(all(r["marketGapDirection"] == "none" for r in rows))

    def test_thin_positions_are_left_uncentered_rather_than_fit_to_noise(self):
        n = _MARKET_GAP_MIN_POSITION_N - 1
        rows = self._rows("K", [0.20] * n)
        _center_market_gaps_by_position(rows)
        # Uncentered: the raw positive gap stands rather than being
        # zeroed against a median estimated from too few rows.
        self.assertTrue(all(r["marketGapDirection"] == "retail_premium" for r in rows))

    def test_rows_with_no_gap_get_an_explicit_none(self):
        rows = [{"position": "WR", "_rawMarketGapPct": None}]
        _center_market_gaps_by_position(rows)
        self.assertEqual(rows[0]["marketGapDirection"], "none")
        self.assertIsNone(rows[0]["marketGapMagnitude"])

    def test_the_temporary_key_never_reaches_the_payload(self):
        rows = self._rows("WR", [0.1] * 10)
        _center_market_gaps_by_position(rows)
        for r in rows:
            self.assertNotIn("_rawMarketGapPct", r)

    def test_the_baseline_is_published(self):
        """A consumer can see what was subtracted, rather than trusting it."""
        rows = self._rows("TE", [0.20] * 10)
        _center_market_gaps_by_position(rows)
        self.assertAlmostEqual(rows[0]["marketGapPositionBaseline"], 0.20, places=6)


if __name__ == "__main__":
    unittest.main()
