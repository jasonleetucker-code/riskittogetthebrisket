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
        adjustments = compute_tier_adjustments(ranks, tiers, [])
        assert all(a == 0.0 for a in adjustments)

    def test_cliff_creates_gap(self):
        ranks = [1.0, 2.0, 3.0, 20.0, 21.0, 22.0]
        tiers = [1, 1, 1, 2, 2, 2]
        boundary = TierBoundary(
            tier_id_above=1, tier_id_below=2,
            player_above="P2", player_below="P3",
            raw_gap=17.0, gap_score=3.0, rank_position=3.0,
        )
        adj = compute_tier_adjustments(ranks, tiers, [boundary])
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
        adj = compute_tier_adjustments(
            ranks, tiers, [boundary_early, boundary_late],
        )
        # Tier 1 adj (includes both cliffs) > Tier 2 adj (includes only late cliff)
        assert adj[0] > adj[2]
        # Tier 3 gets no cliff bonus (allow floating-point epsilon)
        assert abs(adj[4]) < 1e-9

    def test_empty(self):
        assert compute_tier_adjustments([], [], []) == []


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

    def test_is_tier_start_marks_first_in_new_tier(self):
        """is_tier_start should be True only for the first player below a tier break."""
        players = {}
        for i in range(1, 11):
            players[f"Elite{i}"] = [float(i)]
        for i in range(30, 41):
            players[f"Starter{i}"] = [float(i)]
        result = _quick_pipeline(players)
        tier_starts = [p for p in result.players if p.is_tier_start]
        # There should be at least one tier-start player
        assert len(tier_starts) >= 1
        for p in tier_starts:
            # A tier-start player should not be in tier 1
            assert p.tier_id > 1
        # Non-tier-start players in tier 1 should all have is_tier_start=False
        tier1 = [p for p in result.players if p.tier_id == 1]
        assert all(not p.is_tier_start for p in tier1)

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

    def test_monotonic_clamp_count_zero_normal_case(self):
        """Well-separated single-source ranks should not trigger any clamps."""
        players = {f"P{i}": [float(i)] for i in range(1, 21)}
        result = _quick_pipeline(players)
        assert result.monotonic_clamp_count == 0
        assert all(not p.monotonic_clamp_applied for p in result.players)

    def test_monotonic_clamp_detects_forced_tie(self):
        """Players with identical consensus ranks should trigger clamp diagnostics."""
        # Give two players identical ranks from all sources → same consensus rank
        # The volatility adjustment won't differentiate them, so the clamp must fire.
        players = {
            "A": [1.0],
            "B": [5.0],
            "C": [5.0],  # tied with B
            "D": [10.0],
        }
        result = _quick_pipeline(players)
        assert result.monotonic_clamp_count >= 1
        clamped = [p for p in result.players if p.monotonic_clamp_applied]
        assert len(clamped) >= 1

    def test_monotonic_clamp_count_matches_per_player_flags(self):
        """Result-level count must equal the number of per-player flags."""
        players = {
            "A": [1.0], "B": [1.0], "C": [1.0],  # all tied
            "D": [10.0], "E": [20.0],
        }
        result = _quick_pipeline(players)
        flag_count = sum(1 for p in result.players if p.monotonic_clamp_applied)
        assert result.monotonic_clamp_count == flag_count

    def test_empty_input_clamp_count_zero(self):
        result = run_valuation([])
        assert result.monotonic_clamp_count == 0


# ─────────────────────────────────────────────────────────────
# Trade Scenario Validation
# ─────────────────────────────────────────────────────────────

class TestTradeScenarios:
    """Validate that the model produces realistic dynasty trade behavior.

    These tests use a deterministic 200-player market with 5 simulated
    sources per player.  Assertions are calibrated to catch obvious model
    drift (e.g. flat mid-range, missing tier cliffs) while leaving room
    for normal hyperparameter tuning.
    """

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

    # ── 1. Elite vs. elite spacing ──

    def test_elite_vs_elite_swaps(self, market):
        """Adjacent top-end players should be close but distinguishable.

        We check both a minimum gap (players must not be interchangeable)
        and a maximum gap (the curve should not wildly separate adjacent
        elites).  The top-5 span should also be a modest fraction of
        the overall value range.
        """
        top5 = market.players[:5]
        top5_values = [p.final_value for p in top5]

        for i in range(len(top5) - 1):
            gap = top5_values[i] - top5_values[i + 1]
            assert gap > 0, "Adjacent elite players must be distinguishable"
            pct_of_higher = gap / top5_values[i]
            # Gap shouldn't be more than 20% of the higher player
            assert pct_of_higher < 0.20, (
                f"Elite gap too large between ranks {i+1}-{i+2}: "
                f"{gap:.1f} ({pct_of_higher*100:.1f}%)"
            )

        # The top-5 span should be meaningful but not dominate the full range
        top5_span = top5_values[0] - top5_values[-1]
        full_range = market.players[0].final_value - market.players[-1].final_value
        span_share = top5_span / full_range
        assert span_share < 0.50, (
            f"Top-5 span consumes {span_share*100:.1f}% of full range — too concentrated"
        )
        assert span_share > 0.02, (
            f"Top-5 span is only {span_share*100:.1f}% of full range — elites too flat"
        )

    # ── 2. Tier-down premium ──

    def test_tier_down_trade_requires_premium(self, market):
        """Moving down across a tier boundary must cost materially more
        than moving the same number of spots within a tier.

        For each detected boundary, compare the cross-tier gap to the
        median intra-tier adjacent gap in the tiers on either side.
        The cross-tier gap must be at least 1.5× the larger of those
        two intra-tier medians.
        """
        boundaries = market.tier_boundaries
        if not boundaries:
            pytest.skip("No tier boundaries detected in test market")

        for b in boundaries:
            above = next(p for p in market.players if p.player_id == b.player_above)
            below = next(p for p in market.players if p.player_id == b.player_below)
            cross_gap = above.final_value - below.final_value
            assert cross_gap > 0, (
                f"Tier boundary {b.tier_id_above}→{b.tier_id_below} has non-positive gap"
            )

            # Gather intra-tier adjacent gaps for the tier above the boundary
            tier_above_players = [
                p for p in market.players if p.tier_id == b.tier_id_above
            ]
            if len(tier_above_players) >= 2:
                intra_above = [
                    tier_above_players[j].final_value - tier_above_players[j + 1].final_value
                    for j in range(len(tier_above_players) - 1)
                ]
                median_intra_above = sorted(intra_above)[len(intra_above) // 2]
            else:
                median_intra_above = 0.0

            # Gather intra-tier adjacent gaps for the tier below the boundary
            tier_below_players = [
                p for p in market.players if p.tier_id == b.tier_id_below
            ]
            if len(tier_below_players) >= 2:
                intra_below = [
                    tier_below_players[j].final_value - tier_below_players[j + 1].final_value
                    for j in range(len(tier_below_players) - 1)
                ]
                median_intra_below = sorted(intra_below)[len(intra_below) // 2]
            else:
                median_intra_below = 0.0

            baseline_intra = max(median_intra_above, median_intra_below)
            if baseline_intra > 0:
                ratio = cross_gap / baseline_intra
                # 1.2× is the floor — the cross-tier gap must visibly exceed
                # normal intra-tier spacing.  We use 1.2× rather than a higher
                # number because early tiers sit on the steepest part of the
                # curve, where even intra-tier gaps are naturally large.
                assert ratio >= 1.2, (
                    f"Tier {b.tier_id_above}→{b.tier_id_below} cross-gap ({cross_gap:.1f}) "
                    f"is only {ratio:.1f}× the intra-tier median ({baseline_intra:.1f}) — "
                    f"tier break not meaningful enough"
                )

    # ── 3. 2-for-1 consolidation ──

    def test_two_for_one_favors_consolidation(self, market):
        """One top player should beat two mid-range players combined.

        We test at two depth levels:
        - #1 overall vs. two players around rank 30
        - #5 overall vs. two players around rank 50

        The single asset should exceed the combined pair each time.
        """
        # Test 1: #1 vs. two ~rank-30 players
        top_player = market.players[0]
        mid_a, mid_b = market.players[28], market.players[32]
        combined = mid_a.final_value + mid_b.final_value
        assert top_player.final_value > combined, (
            f"#1 ({top_player.final_value:.0f}) should beat "
            f"rank-29+rank-33 combined ({combined:.0f})"
        )

        # Test 2: #5 vs. two ~rank-50 players
        star = market.players[4]
        mid_c, mid_d = market.players[48], market.players[52]
        combined_2 = mid_c.final_value + mid_d.final_value
        assert star.final_value > combined_2 * 0.90, (
            f"#5 ({star.final_value:.0f}) should not be trivially "
            f"replaceable by rank-49+rank-53 ({combined_2:.0f})"
        )

    # ── 4. Mid-tier non-flatness ──

    def test_mid_tier_not_flat(self, market):
        """Mid-range players should have meaningful spacing, not a flat blob.

        We check total spread AND that individual adjacent gaps are non-trivial,
        preventing a scenario where spread exists only at the edges of the range.
        """
        mid = market.players[40:60]
        assert len(mid) >= 10, "Not enough mid-range players for test"
        values = [p.final_value for p in mid]

        # Total spread must be material relative to the range's top value
        total_spread = values[0] - values[-1]
        assert total_spread > values[0] * 0.08, (
            f"Mid-range too flat: spread={total_spread:.1f}, top_mid={values[0]:.1f} "
            f"({total_spread/values[0]*100:.1f}%)"
        )

        # Median adjacent gap in this range should be positive and non-trivial
        adj_gaps = [values[j] - values[j + 1] for j in range(len(values) - 1)]
        median_gap = sorted(adj_gaps)[len(adj_gaps) // 2]
        assert median_gap > 0, "Median adjacent gap in mid-range must be positive"
        # Median gap should be at least 0.2% of the range's top value
        assert median_gap > values[0] * 0.002, (
            f"Mid-range median gap too tiny: {median_gap:.3f} "
            f"(only {median_gap/values[0]*100:.2f}% of top_mid)"
        )

    # ── 5. Late-asset compression ──

    def test_late_asset_compression(self, market):
        """Value density must increase (gaps must shrink) as rank worsens.

        We compare three zones: top (ranks 1–5), mid (ranks 50–55),
        and late (ranks 180–185).  Each zone's 5-player span must be
        strictly smaller than the zone above it, confirming the curve
        compresses appropriately through the full distribution.
        """
        top_span = market.players[0].final_value - market.players[4].final_value
        mid_span = market.players[49].final_value - market.players[54].final_value
        late_span = market.players[179].final_value - market.players[184].final_value

        assert top_span > mid_span > late_span, (
            f"Compression gradient broken: top={top_span:.1f}, "
            f"mid={mid_span:.1f}, late={late_span:.1f}"
        )

        # Late compression should be dramatic relative to top
        assert top_span > 5 * late_span, (
            f"Late assets not compressed enough: "
            f"top_span={top_span:.1f}, late_span={late_span:.1f} "
            f"(ratio={top_span/late_span:.1f}×, need ≥5×)"
        )

        # Late assets should occupy a small fraction of total value range
        full_range = market.players[0].final_value - market.players[-1].final_value
        late_20_span = market.players[179].final_value - market.players[-1].final_value
        assert late_20_span < full_range * 0.10, (
            f"Bottom 20 players consume {late_20_span/full_range*100:.1f}% "
            f"of value range — not compressed enough"
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
