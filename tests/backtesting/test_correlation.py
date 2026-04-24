"""Tests for Spearman correlation + per-source accuracy scoring."""
from __future__ import annotations

from src.backtesting import correlation


def test_spearman_perfectly_monotonic_is_one():
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert correlation.spearman(a, b) == 1.0


def test_spearman_reverse_is_neg_one():
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [50.0, 40.0, 30.0, 20.0, 10.0]
    assert correlation.spearman(a, b) == -1.0


def test_spearman_empty_is_zero():
    assert correlation.spearman([], []) == 0.0


def test_spearman_handles_ties():
    a = [1.0, 1.0, 2.0, 2.0]
    b = [5.0, 5.0, 10.0, 10.0]
    # Perfectly monotonic despite ties.
    assert correlation.spearman(a, b) == 1.0


def test_score_source_perfect_source():
    # Source says rank 1→5 for A–E, realized points 50→10 for A–E.
    # Perfect inverse relationship between rank-number and points
    # = high Spearman after the -rank flip.
    source_ranks = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    realized = {"A": 50.0, "B": 40.0, "C": 30.0, "D": 20.0, "E": 10.0}
    acc = correlation.score_source("perfect", source_ranks, realized)
    assert acc.spearman_rho == 1.0
    assert acc.n_players == 5


def test_score_source_random_ranks_near_zero():
    import random
    random.seed(42)
    source_ranks = {f"p{i}": i + 1 for i in range(40)}
    # Shuffle points independently so there's no relationship.
    pts = list(range(1, 41))
    random.shuffle(pts)
    realized = {f"p{i}": float(pts[i]) for i in range(40)}
    acc = correlation.score_source("random", source_ranks, realized)
    assert abs(acc.spearman_rho) < 0.4


def test_score_source_top_k_hit_rate():
    source_ranks = {f"p{i}": i + 1 for i in range(100)}  # 1..100
    # Realized: top 10 are exactly p0..p9
    realized = {f"p{i}": float(100 - i) for i in range(100)}
    acc = correlation.score_source("good", source_ranks, realized, top_k=10)
    assert acc.top_50_hit_rate == 1.0


def test_score_source_handles_sparse_overlap():
    source_ranks = {"A": 1, "B": 2}
    realized = {"X": 50}
    acc = correlation.score_source("sparse", source_ranks, realized)
    assert acc.n_players == 0
    assert acc.spearman_rho == 0.0


def test_score_all_sources_sorts_descending():
    realized = {f"p{i}": float(100 - i) for i in range(50)}
    # Good source: ranks by real order.
    good = {f"p{i}": i + 1 for i in range(50)}
    # Bad source: inverse of real order.
    bad = {f"p{i}": 50 - i for i in range(50)}
    results = correlation.score_all_sources({"good": good, "bad": bad}, realized)
    assert results[0].source == "good"
    assert results[1].source == "bad"
