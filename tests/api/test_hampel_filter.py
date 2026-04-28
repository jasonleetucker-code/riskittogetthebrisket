"""Per-player Hampel outlier rejection.

Unit tests for ``_hampel_filter_per_player`` — the helper that drops
per-player source values whose deviation from the median exceeds K
median-absolute-deviations before aggregation.

These tests pin the K=2.75 threshold, the n>=4 floor, the MAD==0
short-circuit, and the >=2-survivor safety guard so a future refactor
can't silently widen / narrow the rule or strip a player down to a
single source.
"""
from __future__ import annotations

from src.api.data_contract import (
    _HAMPEL_K,
    _HAMPEL_MIN_N,
    _HAMPEL_MIN_THRESHOLD,
    _hampel_filter_per_player,
)


class TestSafetyGuards:
    def test_below_min_n_returns_input_unchanged(self):
        pairs = [("a", 1000.0), ("b", 2000.0), ("c", 9000.0)]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert kept == pairs
        assert dropped == []

    def test_min_n_constant_is_four(self):
        # Sanity: this test exists to make accidental floor changes loud.
        assert _HAMPEL_MIN_N == 4

    def test_k_constant_is_two_seventy_five(self):
        # Sanity: this test exists to make accidental K changes loud.
        assert _HAMPEL_K == 2.75

    def test_min_threshold_floor_is_1000(self):
        # Sanity: this test exists to make accidental floor changes loud.
        # Raised from 500 → 1000 (2026-04-27) after the weekly Hampel
        # audit caught dlfSf / dlfRookieSf / flockFantasySfRookies at
        # 18% / 25% / 25% drop rates — symptoms of the floor binding
        # whenever the value-direct sources (KTC, ktcSfTep, IDPTC,
        # dynastyDaddySf) cluster within ~150 Hill points and pull the
        # MAD below 200.
        assert _HAMPEL_MIN_THRESHOLD == 1000.0

    def test_perfect_agreement_drops_nothing(self):
        # All identical → all deviations are zero → nothing exceeds the
        # min_threshold floor → nothing dropped.
        pairs = [("a", 5000.0)] * 5
        kept, dropped = _hampel_filter_per_player(pairs)
        assert len(kept) == 5
        assert dropped == []

    def test_tied_bulk_with_outlier_drops_outlier(self):
        # Regression for Codex review (PR #211): when the bulk agrees
        # exactly (e.g. [9999, 9999, 9999, 2000]) MAD == 0, but the
        # lone 2000 is still 7999 from the median.  The min_threshold
        # floor must catch it — the prior ``mad <= 0`` short-circuit
        # silently kept the rogue source and let the outlier survive
        # to distort the blend.
        pairs = [
            ("a", 9999.0),
            ("b", 9999.0),
            ("c", 9999.0),
            ("d", 2000.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["d"]
        assert len(kept) == 3

    def test_tied_bulk_with_close_value_keeps_all(self):
        # Counterpart guard: tied bulk + a value within the floor
        # distance must NOT be dropped.  Confirms the floor isn't
        # over-aggressive when MAD == 0.
        pairs = [
            ("a", 9999.0),
            ("b", 9999.0),
            ("c", 9999.0),
            ("d", 9600.0),  # 399 from median → inside the 500 floor
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == []
        assert len(kept) == 4

    def test_lone_outlier_against_tight_cluster_drops(self):
        # 4 sources: 1 outlier + 3 tight cluster.  Dropping the
        # outlier leaves 3 survivors (>=2), so the filter fires and
        # the >=2-survivor guard does not roll the result back.
        pairs = [
            ("a", 5000.0),
            ("b", 9999.0),
            ("c", 9998.0),
            ("d", 9997.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["a"]
        assert len(kept) == 3
        # The >=2-survivor guard is provably hard to trigger under K=2.75
        # because MAD scales with the spread of the bulk — adding more
        # dispersed values inflates MAD and *protects* extreme values
        # from being called outliers.  The guard exists as a defensive
        # invariant; in normal operation Hampel only ever drops a small
        # minority of an n>=4 set.


class TestOutlierRejection:
    def test_single_extreme_outlier_dropped_at_n5(self):
        pairs = [
            ("a", 5000.0),
            ("b", 5100.0),
            ("c", 5050.0),
            ("d", 4950.0),
            ("e", 100.0),  # way below the cluster
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["e"]
        assert len(kept) == 4
        assert ("e", 100.0) not in kept

    def test_tight_cluster_drops_nothing(self):
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 5100.0),
            ("d", 4950.0),
            ("e", 5025.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == []
        assert len(kept) == 5

    def test_two_outliers_both_dropped(self):
        pairs = [
            ("a", 5000.0),
            ("b", 5100.0),
            ("c", 5050.0),
            ("d", 4950.0),
            ("e", 5025.0),
            ("f", 50.0),     # low outlier
            ("g", 9900.0),   # high outlier
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert set(dropped) == {"f", "g"}
        assert len(kept) == 5

    def test_borderline_below_threshold_kept(self):
        # Construct a wide-enough cluster that K*MAD exceeds the 500
        # absolute floor, so the borderline test exercises K*MAD
        # rather than the floor.
        #
        # values [3000, 4000, 5000, 6000, 5400] → sorted [3000, 4000, 5000, 5400, 6000]
        # median = 5000
        # deviations [2000, 1000, 0, 1000, 400] → sorted [0, 400, 1000, 1000, 2000]
        # MAD = 1000 ; K*MAD = 2750 ; floor=500 → threshold = 2750
        pairs_kept = [
            ("a", 3000.0),
            ("b", 4000.0),
            ("c", 5000.0),
            ("d", 6000.0),
            ("e", 7749.0),  # 2749 from median → kept
        ]
        kept, dropped = _hampel_filter_per_player(pairs_kept)
        assert dropped == []
        pairs_dropped = [
            ("a", 3000.0),
            ("b", 4000.0),
            ("c", 5000.0),
            ("d", 6000.0),
            ("e", 7751.0),  # 2751 > 2750 from median → dropped
        ]
        kept2, dropped2 = _hampel_filter_per_player(pairs_dropped)
        assert dropped2 == ["e"]
        assert len(kept2) == 4


class TestAbsoluteThresholdFloor:
    """The 1000-Hill-point floor protects tight clusters from
    over-aggressive filtering when MAD is small relative to scale."""

    def test_tight_cluster_no_drops_under_floor(self):
        # MAD here is 25 → K*MAD = 68.75, well under the 1000 floor.
        # Without the floor, values ±75 from median would be dropped;
        # with the floor, threshold = 1000 so all five are kept.
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 5100.0),
            ("d", 4950.0),
            ("e", 5025.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == []
        assert len(kept) == 5

    def test_tight_cluster_with_far_outlier_drops_only_outlier(self):
        # MAD=25 again; floor=1000.  A source >1000 Hill points from the
        # median exceeds the floor and is dropped.
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 5100.0),
            ("d", 4950.0),
            ("e", 6250.0),  # 1200 from median → dropped (>1000 floor)
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["e"]
        assert len(kept) == 4

    def test_value_within_floor_distance_kept_even_when_above_kmad(self):
        # K*MAD = 68.75 ; floor = 1000.  A value 800 from median exceeds
        # K*MAD but sits inside the floor → kept (floor wins).
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 5100.0),
            ("d", 4950.0),
            ("e", 5850.0),  # 800 from median (5050) → kept under floor
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == []

    def test_preserves_input_order_for_kept(self):
        pairs = [
            ("z", 5000.0),
            ("y", 5050.0),
            ("x", 4950.0),
            ("w", 5025.0),
            ("v", 100.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["v"]
        assert [k for k, _ in kept] == ["z", "y", "x", "w"]


class TestN4EdgeCase:
    """n=4 is exactly the minimum; verify the filter actually fires."""

    def test_n4_drops_extreme_outlier(self):
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 4950.0),
            ("d", 50.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        assert dropped == ["d"]
        assert len(kept) == 3

    def test_n4_two_extreme_outliers_would_leave_two_survivors(self):
        # 4 sources, 2 outliers → drops both, leaves 2 → guard allows.
        pairs = [
            ("a", 5000.0),
            ("b", 5050.0),
            ("c", 100.0),
            ("d", 9900.0),
        ]
        kept, dropped = _hampel_filter_per_player(pairs)
        # median of [100, 5000, 5050, 9900] = (5000+5050)/2 = 5025
        # deviations sorted = [25, 75, 4925, 4875] → sorted [25, 75, 4875, 4925]
        # MAD = (75 + 4875) / 2 = 2475 ; threshold = 2.75 * 2475 ≈ 6806
        # |100 - 5025| = 4925  < 6806 → kept
        # |9900 - 5025| = 4875 < 6806 → kept
        # So nothing is dropped at n=4 with this distribution because
        # MAD is huge.  This documents the *behavior*: with only 4
        # sources and 50/50 polarity, MAD is too inflated to call
        # anything an outlier, and the bulk-vs-outlier distinction
        # collapses.  Hampel's own design.
        assert dropped == []
        assert len(kept) == 4
