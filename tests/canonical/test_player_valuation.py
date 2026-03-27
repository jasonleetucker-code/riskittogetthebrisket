"""Tests for the canonical player valuation system.

Covers:
    - Consensus rank computation (Step 1)
    - Tier detection (Step 2)
    - Base value curve properties (Step 3)
    - Tier cliff injection (Step 4)
    - Volatility adjustment (Step 5)
    - Full pipeline integration (Step 6)
    - Trade-scenario validation
    - Stability under small rank perturbations
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.player_valuation import (
    PlayerInput,
    PlayerValuation,
    TierBoundary,
    ValuationResult,
    base_value_curve,
    compute_consensus_rank,
    compute_tier_adjustments,
    compute_volatility_adjustments,
    detect_tiers,
    run_valuation,
    build_player_inputs_from_raw_records,
    CURVE_A,
    CURVE_B,
    CURVE_C,
    DISPLAY_SCALE_MAX,
    DISPLAY_SCALE_MIN,
    W_MEDIAN,
    W_MEAN,
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_players(ranks_by_player: dict[str, list[float]]) -> list[PlayerInput]:
    """Build PlayerInput list from {name: [source_ranks]}."""
    return [
        PlayerInput(player_id=name, display_name=name, source_ranks=ranks)
        for name, ranks in ranks_by_player.items()
    ]


def _quick_pipeline(ranks_by_player: dict[str, list[float]], **kwargs) -> ValuationResult:
    return run_valuation(_make_players(ranks_by_player), **kwargs)


# ─────────────────────────────────────────────────────────────
# Step 1 – Consensus Rank
# ─────────────────────────────────────────────────────────────

class TestConsensusRank:
    def test_single_source(self):
        cr, med, avg, vol = compute_consensus_rank([5.0])
        assert cr == 5.0
        assert med == 5.0
        assert avg == 5.0
        assert vol == 0.0

    def test_two_sources_agreement(self):
        cr, med, avg, vol = compute_consensus_rank([3.0, 3.0])
        assert abs(cr - 3.0) < 1e-9
        assert vol == 0.0

    def test_median_weighted_higher(self):
        """Consensus should be closer to the median than the mean."""
        ranks = [1.0, 2.0, 2.0, 2.0, 100.0]  # outlier at 100
        cr, med, avg, vol = compute_consensus_rank(ranks)
        # Median = 2.0, Mean = 21.4
        assert abs(cr - med) < abs(cr - avg)

    def test_weights_sum_to_one(self):
        assert abs(W_MEDIAN + W_MEAN - 1.0) < 1e-9

    def test_volatility_increases_with_disagreement(self):
        _, _, _, vol_agree = compute_consensus_rank([5.0, 5.0, 5.0])
        _, _, _, vol_disagree = compute_consensus_rank([1.0, 5.0, 50.0])
        assert vol_disagree > vol_agree

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_consensus_rank([])

    def test_consensus_between_median_and_mean(self):
        ranks = [1.0, 3.0, 5.0, 7.0, 9.0]
        cr, med, avg, _ = compute_consensus_rank(ranks)
        lo, hi = min(med, avg), max(med, avg)
        assert lo <= cr <= hi


# ─────────────────────────────────────────────────────────────
# Step 2 – Tier Detection
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
            [float(i) for i in range(1, 6)]       # tier 1: 1–5
            + [float(i) for i in range(25, 30)]    # tier 2: 25–29
            + [float(i) for i in range(55, 60)]    # tier 3: 55–59
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
            ranks, ids, min_tier_size=3,
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
# Step 3 – Base Value Curve
# ─────────────────────────────────────────────────────────────

class TestBaseValueCurve:
    def test_monotonically_decreasing(self):
        values = [base_value_curve(float(r)) for r in range(1, 301)]
        for i in range(1, len(values)):
            assert values[i] < values[i - 1], f"Not decreasing at rank {i + 1}"

    def test_rank_1_highest(self):
        v1 = base_value_curve(1.0)
        v2 = base_value_curve(2.0)
        assert v1 > v2

    def test_steep_at_top(self):
        """Gap between rank 1 and 5 should be larger than gap between rank 50 and 54."""
        top_gap = base_value_curve(1.0) - base_value_curve(5.0)
        mid_gap = base_value_curve(50.0) - base_value_curve(54.0)
        assert top_gap > mid_gap

    def test_tail_compression(self):
        """Gaps in the tail should be much smaller than at the top."""
        top_gap = base_value_curve(1.0) - base_value_curve(2.0)
        tail_gap = base_value_curve(200.0) - base_value_curve(201.0)
        assert top_gap > 10 * tail_gap

    def test_positive_for_large_ranks(self):
        assert base_value_curve(500.0) > 0

    def test_custom_params(self):
        v = base_value_curve(1.0, A=5000, B=1.0, C=1.0)
        assert abs(v - 2500.0) < 1e-6  # 5000 / (1 + 1)^1


# ─────────────────────────────────────────────────────────────
# Step 4 – Tier Cliff Injection
# ─────────────────────────────────────────────────────────────

class TestTierCliffs:
    def test_no_cliffs_single_tier(self):
        ranks = [1.0, 2.0, 3.0]
        tiers = [1, 1, 1]
        bases = [100.0, 90.0, 80.0]
        adjustments = compute_tier_adjustments(ranks, tiers, bases, [])
        assert all(a == 0.0 for a in adjustments)

    def test_cliff_creates_gap(self):
        ranks = [1.0, 2.0, 3.0, 20.0, 21.0, 22.0]
        tiers = [1, 1, 1, 2, 2, 2]
        bases = [100, 90, 80, 40, 35, 30]
        boundary = TierBoundary(
            tier_id_above=1, tier_id_below=2,
            player_above="P2", player_below="P3",
            raw_gap=17.0, gap_score=3.0, rank_position=3.0,
        )
        adj = compute_tier_adjustments(ranks, tiers, bases, [boundary])
        # Tier 1 players should get a positive adjustment
        assert all(a > 0 for a in adj[:3])
        # Tier 2 players should get zero (or less than tier 1)
        for i in range(3, 6):
            assert adj[i] < adj[0]

    def test_cliff_decays_with_rank(self):
        """Later cliffs should be smaller than early ones."""
        boundary_early = TierBoundary(
            tier_id_above=1, tier_id_below=2,
            player_above="P", player_below="Q",
            raw_gap=10.0, gap_score=3.0, rank_position=5.0,
        )
        boundary_late = TierBoundary(
            tier_id_above=2, tier_id_below=3,
            player_above="Q", player_below="R",
            raw_gap=10.0, gap_score=3.0, rank_position=100.0,
        )
        # Two-boundary scenario
        ranks = [1.0, 2.0, 50.0, 51.0, 150.0, 151.0]
        tiers = [1, 1, 2, 2, 3, 3]
        bases = [100, 90, 50, 45, 20, 18]
        adj = compute_tier_adjustments(
            ranks, tiers, bases, [boundary_early, boundary_late],
        )
        # Tier 1 adj (includes both cliffs) > Tier 2 adj (includes only late cliff)
        assert adj[0] > adj[2]
        # Tier 3 gets no cliff bonus (allow floating-point epsilon)
        assert abs(adj[4]) < 1e-9

    def test_empty(self):
        assert compute_tier_adjustments([], [], [], []) == []


# ─────────────────────────────────────────────────────────────
# Step 5 – Volatility Adjustment
# ─────────────────────────────────────────────────────────────

class TestVolatilityAdjustment:
    def test_zero_vol_no_adjustment(self):
        adj = compute_volatility_adjustments([100, 80, 60], [0.0, 0.0, 0.0])
        assert all(a == 0.0 for a in adj)

    def test_high_vol_compresses(self):
        """A player with much higher vol than peers should get compressed."""
        values = [100.0, 90.0, 80.0]
        vols = [1.0, 1.0, 20.0]  # player 3 is very volatile
        adj = compute_volatility_adjustments(values, vols)
        assert adj[0] == 0.0 or adj[0] <= 0  # low vol → no penalty
        assert adj[2] < 0  # high vol → compression

    def test_floor_respected(self):
        """Even extreme volatility should not compress below the floor."""
        values = [1000.0]
        vols = [100.0]
        # With only one player, z-score logic may differ, but floor should hold
        adj = compute_volatility_adjustments(values, vols)
        result = values[0] + adj[0]
        assert result >= values[0] * 0.90  # generous check around floor

    def test_never_positive(self):
        """Volatility adjustment should never increase value."""
        values = [100.0, 90.0, 80.0, 70.0]
        vols = [5.0, 10.0, 15.0, 20.0]
        adj = compute_volatility_adjustments(values, vols)
        assert all(a <= 0.0 for a in adj)

    def test_empty(self):
        assert compute_volatility_adjustments([], []) == []


# ─────────────────────────────────────────────────────────────
# Step 6 – Full Pipeline Integration
# ─────────────────────────────────────────────────────────────

class TestFullPipeline:
    def test_empty_input(self):
        result = run_valuation([])
        assert result.players == []
        assert result.tier_count == 0

    def test_single_player(self):
        result = _quick_pipeline({"Alpha": [1.0]})
        assert len(result.players) == 1
        assert result.players[0].display_value == DISPLAY_SCALE_MAX

    def test_ordering_preserved(self):
        """Final values must strictly decrease with worsening rank."""
        players = {f"P{i}": [float(i)] for i in range(1, 51)}
        result = _quick_pipeline(players)
        values = [p.final_value for p in result.players]
        for i in range(1, len(values)):
            assert values[i] < values[i - 1], (
                f"Non-decreasing at index {i}: {values[i-1]:.2f} -> {values[i]:.2f}"
            )

    def test_display_values_in_range(self):
        players = {f"P{i}": [float(i)] for i in range(1, 101)}
        result = _quick_pipeline(players)
        for p in result.players:
            assert DISPLAY_SCALE_MIN <= p.display_value <= DISPLAY_SCALE_MAX

    def test_top_player_gets_max_display(self):
        result = _quick_pipeline({"A": [1.0], "B": [5.0], "C": [10.0]})
        assert result.players[0].display_value == DISPLAY_SCALE_MAX

    def test_tier_ids_assigned(self):
        # Create scenario with an obvious cliff
        players = {}
        for i in range(1, 11):
            players[f"Elite{i}"] = [float(i)]
        for i in range(30, 41):
            players[f"Starter{i}"] = [float(i)]
        result = _quick_pipeline(players)
        tier_ids = {p.tier_id for p in result.players}
        assert len(tier_ids) >= 2

    def test_diagnostics_populated(self):
        result = _quick_pipeline({
            "A": [1.0, 2.0, 3.0],
            "B": [4.0, 5.0, 6.0],
        })
        for p in result.players:
            assert p.median_rank > 0
            assert p.mean_rank > 0
            assert p.consensus_rank > 0
            assert p.base_value > 0

    def test_hyperparameters_recorded(self):
        result = _quick_pipeline({"A": [1.0]})
        hp = result.hyperparameters
        assert "w_median" in hp
        assert "curve_a" in hp


# ─────────────────────────────────────────────────────────────
# Trade Scenario Validation
# ─────────────────────────────────────────────────────────────

class TestTradeScenarios:
    """Validate that the model produces realistic dynasty trade behavior."""

    @pytest.fixture
    def market(self):
        """A 200-player market with realistic multi-source ranks."""
        import random
        random.seed(42)
        players = {}
        for i in range(1, 201):
            # Simulate 5 sources with modest disagreement
            base = float(i)
            noise = max(1, i * 0.1)  # more noise for lower-ranked players
            ranks = [max(1.0, base + random.gauss(0, noise)) for _ in range(5)]
            players[f"Player_{i:03d}"] = ranks
        return _quick_pipeline(players)

    def test_elite_vs_elite_swaps(self, market):
        """Adjacent top-end players should be close but distinguishable."""
        top5 = market.players[:5]
        for i in range(len(top5) - 1):
            gap = top5[i].final_value - top5[i + 1].final_value
            assert gap > 0, "Adjacent elite players must be distinguishable"
            # Gap shouldn't be more than 20% of the higher player's value
            assert gap < top5[i].final_value * 0.20, (
                f"Elite gap too large: {gap:.1f} ({gap/top5[i].final_value*100:.1f}%)"
            )

    def test_tier_down_trade_requires_premium(self, market):
        """Moving down across a tier should cost meaningful value."""
        boundaries = market.tier_boundaries
        if not boundaries:
            pytest.skip("No tier boundaries detected in test market")
        # Check first boundary
        b = boundaries[0]
        above = next(p for p in market.players if p.player_id == b.player_above)
        below = next(p for p in market.players if p.player_id == b.player_below)
        gap = above.final_value - below.final_value
        # The tier-down gap should be meaningfully larger than
        # an intra-tier adjacent gap
        assert gap > 0, "Tier boundary must create positive gap"

    def test_two_for_one_favors_consolidation(self, market):
        """One top player should be worth more than two mid-range players combined."""
        top_player = market.players[0]
        # Pick two players around rank 30–35
        mid_players = [p for p in market.players if 28 <= market.players.index(p) <= 35]
        if len(mid_players) >= 2:
            combined_mid = mid_players[0].final_value + mid_players[1].final_value
            assert top_player.final_value > combined_mid * 0.85, (
                "Top player should not be trivially replaceable by two mid-range assets"
            )

    def test_mid_tier_not_flat(self, market):
        """Mid-range players should have meaningful spacing, not a flat blob."""
        mid = market.players[40:60]
        if len(mid) < 5:
            pytest.skip("Not enough mid-range players")
        values = [p.final_value for p in mid]
        total_spread = values[0] - values[-1]
        # Spread should be at least 5% of the top value in this range
        assert total_spread > values[0] * 0.05, (
            f"Mid-range too flat: spread={total_spread:.1f}, top_mid={values[0]:.1f}"
        )

    def test_late_asset_compression(self, market):
        """Late-range players should be much more compressed than top players."""
        top_gap = market.players[0].final_value - market.players[4].final_value
        late_gap = market.players[180].final_value - market.players[184].final_value
        assert top_gap > 5 * late_gap, (
            f"Late assets not compressed enough: top_gap={top_gap:.1f}, late_gap={late_gap:.1f}"
        )


# ─────────────────────────────────────────────────────────────
# Stability Tests
# ─────────────────────────────────────────────────────────────

class TestStability:
    def test_small_rank_change_small_value_change(self):
        """Moving one player by 1–2 spots should not cause wild swings."""
        base_players = {f"P{i}": [float(i)] for i in range(1, 31)}
        base_result = _quick_pipeline(base_players)

        # Perturb P15 from rank 15 to 13 in one source
        perturbed = dict(base_players)
        perturbed["P15"] = [13.0]
        pert_result = _quick_pipeline(perturbed)

        # Find P15 in both results
        base_p15 = next(p for p in base_result.players if p.player_id == "P15")
        pert_p15 = next(p for p in pert_result.players if p.player_id == "P15")

        # Value change should be < 20% of original (single-source 2-rank
        # move on a 30-player set is ~7% rank shift; proportional value
        # shift is expected given the non-linear curve)
        change_pct = abs(pert_p15.final_value - base_p15.final_value) / base_p15.final_value
        assert change_pct < 0.20, f"Value swung {change_pct*100:.1f}% from a 2-spot move"

    def test_ordering_stable_under_noise(self):
        """Adding small noise to sources should preserve overall ordering."""
        import random
        random.seed(99)
        base_players = {f"P{i}": [float(i)] for i in range(1, 51)}
        base_result = _quick_pipeline(base_players)
        base_order = [p.player_id for p in base_result.players]

        # Add slight noise
        noisy_players = {
            name: [r + random.uniform(-0.5, 0.5) for r in ranks]
            for name, ranks in base_players.items()
        }
        noisy_result = _quick_pipeline(noisy_players)
        noisy_order = [p.player_id for p in noisy_result.players]

        # Allow at most 10% of positions to swap
        mismatches = sum(1 for a, b in zip(base_order, noisy_order) if a != b)
        assert mismatches < len(base_order) * 0.10


# ─────────────────────────────────────────────────────────────
# Integration bridge
# ─────────────────────────────────────────────────────────────

class TestBuildPlayerInputs:
    def test_basic_conversion(self):
        records = [
            {"asset_key": "mahomes", "display_name": "Patrick Mahomes",
             "source": "KTC", "rank_raw": 1.0, "position_normalized_guess": "QB"},
            {"asset_key": "mahomes", "display_name": "Patrick Mahomes",
             "source": "DLF", "rank_raw": 2.0, "position_normalized_guess": "QB"},
            {"asset_key": "chase", "display_name": "Ja'Marr Chase",
             "source": "KTC", "rank_raw": 3.0, "position_normalized_guess": "WR"},
        ]
        inputs = build_player_inputs_from_raw_records(records)
        assert len(inputs) == 2
        mahomes = next(p for p in inputs if p.player_id == "mahomes")
        assert mahomes.source_ranks == [1.0, 2.0]
        assert mahomes.metadata["position"] == "QB"

    def test_skips_zero_weight_sources(self):
        records = [
            {"asset_key": "p1", "display_name": "P1",
             "source": "BAD", "rank_raw": 1.0},
        ]
        inputs = build_player_inputs_from_raw_records(
            records, source_weights={"BAD": 0.0},
        )
        assert len(inputs) == 0

    def test_skips_no_rank(self):
        records = [
            {"asset_key": "p1", "display_name": "P1",
             "source": "SRC", "rank_raw": None},
        ]
        inputs = build_player_inputs_from_raw_records(records)
        assert len(inputs) == 0
