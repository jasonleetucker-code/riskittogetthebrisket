"""Tests for the canonical curve + tiering primitives.

Covers:
    - Tier detection (rolling-median rank-gap analysis)
    - Rank-form Hill value-curve properties

SCOPE NOTE (2026-07-29).  This file used to also cover the retired
offline canonical-build engine — ``run_valuation`` and its consensus
rank / tier-cliff / volatility-compression steps, the
``PlayerInput`` → ``ValuationResult`` dataclasses, the
``build_player_inputs_from_*`` adapter bridges and
``valuation_result_to_asset_dicts``, plus the trade-scenario, stability,
calibration-fixture and parameter-sweep suites built on top of them.
That engine had no production caller and was deleted from
``src/canonical/player_valuation.py`` in the dead-code audit, so its
tests went with it.  Nothing that survives here was weakened: the
``detect_tiers`` and ``rank_to_value`` coverage below is unchanged.

Scope-routing coverage for ``rank_to_value_for_scope`` and
``percentile_to_value`` lives in ``test_rank_to_value_scope.py`` and
``test_ktc_reconciliation.py`` respectively.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.player_valuation import (  # noqa: E402
    detect_tiers,
    rank_to_value,
)


# ─────────────────────────────────────────────────────────────
# Tier detection
# ─────────────────────────────────────────────────────────────


class TestTierDetection:
    def test_no_tiers_for_uniform_gaps(self):
        """Uniformly spaced players should produce one tier."""
        ranks = [float(i) for i in range(1, 21)]
        ids = [f"P{i}" for i in range(20)]
        tier_ids, _, _, boundaries = detect_tiers(ranks, ids)
        assert all(t == 1 for t in tier_ids)
        assert len(boundaries) == 0

    def test_obvious_cliff_detected(self):
        """A large gap in the middle should produce a tier break."""
        # 10 players clustered 1–10, then a gap, then 10 players at 30–39
        ranks = [float(i) for i in range(1, 11)] + [float(i) for i in range(30, 40)]
        ids = [f"P{i}" for i in range(20)]
        tier_ids, _, gap_scores, boundaries = detect_tiers(ranks, ids)
        assert len(boundaries) >= 1
        # The break should be between P9 (rank 10) and P10 (rank 30)
        break_players = {b.player_below for b in boundaries}
        assert "P10" in break_players

    def test_multiple_cliffs(self):
        """Multiple well-separated clusters should produce multiple tiers."""
        ranks = (
            [float(i) for i in range(1, 6)]  # tier 1: 1–5
            + [float(i) for i in range(25, 30)]  # tier 2: 25–29
            + [float(i) for i in range(55, 60)]  # tier 3: 55–59
        )
        ids = [f"P{i}" for i in range(15)]
        tier_ids, _, _, boundaries = detect_tiers(ranks, ids)
        assert len(boundaries) >= 2
        unique_tiers = set(tier_ids)
        assert len(unique_tiers) >= 3

    def test_single_player(self):
        tier_ids, gaps, scores, boundaries = detect_tiers([1.0], ["P0"])
        assert tier_ids == [1]
        assert boundaries == []

    def test_empty(self):
        tier_ids, gaps, scores, boundaries = detect_tiers([], [])
        assert tier_ids == []
        assert boundaries == []

    def test_min_tier_size_respected(self):
        """A gap right after 2 players shouldn't break if min_tier_size=3."""
        ranks = [1.0, 2.0, 50.0, 51.0, 52.0, 53.0, 54.0]
        ids = [f"P{i}" for i in range(7)]
        tier_ids, _, _, boundaries = detect_tiers(
            ranks,
            ids,
            min_tier_size=3,
        )
        # First 2 players can't form a tier of size 3, so break should
        # be deferred or not happen at rank index 1
        for b in boundaries:
            # If a boundary exists, the upper tier should have >= 3 players
            upper_count = sum(1 for t in tier_ids if t == b.tier_id_above)
            assert upper_count >= 3 or len(boundaries) == 0

    def test_tier_ids_monotonically_increase(self):
        ranks = [1, 2, 3, 20, 21, 22, 50, 51, 52]
        ranks = [float(r) for r in ranks]
        ids = [f"P{i}" for i in range(9)]
        tier_ids, _, _, _ = detect_tiers(ranks, ids)
        for i in range(1, len(tier_ids)):
            assert tier_ids[i] >= tier_ids[i - 1]


# ─────────────────────────────────────────────────────────────
# Rank-form value curve
# ─────────────────────────────────────────────────────────────


class TestBaseValueCurve:
    """Tests for rank_to_value (Hill-style rank-form curve)."""

    def test_rank_1_exactly_9999(self):
        assert rank_to_value(1) == 9999

    def test_correct_spot_values(self):
        # Hill curve fit to the simple mean of KTC / IDPTradeCalc /
        # DynastyDaddy / DynastyNerds. Re-run
        # ``scripts/fit_hill_curve_from_market.py`` to refresh the
        # constants and update these expected values together.
        expected = {
            1: 9999,
            2: 9885,
            3: 9749,
            5: 9460,
            10: 8736,
            25: 6914,
            50: 4967,
            100: 3055,
            200: 1648,
            500: 643,
        }
        for rank, val in expected.items():
            assert (
                rank_to_value(rank) == val
            ), f"rank {rank}: got {rank_to_value(rank)}, expected {val}"

    def test_monotonically_decreasing(self):
        values = [rank_to_value(r) for r in range(1, 301)]
        for i in range(1, len(values)):
            assert values[i] <= values[i - 1], f"Not decreasing at rank {i + 1}"

    def test_rank_1_highest(self):
        assert rank_to_value(1) > rank_to_value(2)

    def test_top_gap_larger_than_mid_gap(self):
        """Top-of-board gap should exceed mid-range gap of same span."""
        top_gap = rank_to_value(1) - rank_to_value(5)
        mid_gap = rank_to_value(50) - rank_to_value(54)
        assert top_gap > mid_gap

    def test_tail_compression(self):
        """Tail gaps should be much smaller than top-of-board gap."""
        top_gap = rank_to_value(1) - rank_to_value(2)
        tail_gap = rank_to_value(200) - rank_to_value(201)
        assert top_gap > 10 * tail_gap

    def test_positive_for_large_ranks(self):
        assert rank_to_value(500) >= 1
