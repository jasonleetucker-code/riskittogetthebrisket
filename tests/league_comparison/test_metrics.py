"""Unit tests for src.league_comparison.metrics — the pure stat math."""

from __future__ import annotations

import math

import pytest

from src.league_comparison import metrics as m
from src.league_comparison.scoring_engine import PlayerSeasonScore


def _score(pts: float, pos: str = "QB", pid: str | None = None) -> PlayerSeasonScore:
    return PlayerSeasonScore(
        player_id=pid or f"p{int(pts*100)}",
        player_name=f"Player {pts}",
        position=pos,
        raw_position=pos,
        season=2024,
        total_points=pts,
        games_played=17,
    )


# ── top_n_by_position / flex_top_n ────────────────────────────────────


def test_top_n_filters_by_position_and_sorts_desc():
    pool = [
        _score(100, "QB"),
        _score(200, "RB"),
        _score(300, "QB"),
        _score(150, "QB"),
        _score(50, "QB"),
    ]
    out = m.top_n_by_position(pool, "QB", 3)
    assert [s.total_points for s in out] == [300, 150, 100]


def test_top_n_breaks_ties_with_player_id():
    pool = [
        _score(100, "QB", pid="b"),
        _score(100, "QB", pid="a"),
        _score(100, "QB", pid="c"),
    ]
    out = m.top_n_by_position(pool, "QB", 3)
    assert [s.player_id for s in out] == ["a", "b", "c"]


def test_top_n_handles_oversized_request():
    pool = [_score(100, "QB"), _score(50, "QB")]
    out = m.top_n_by_position(pool, "QB", 10)
    assert len(out) == 2


def test_flex_excludes_qb():
    pool = [
        _score(500, "QB"),  # would be #1 by points but excluded
        _score(200, "RB"),
        _score(150, "WR"),
        _score(100, "TE"),
    ]
    out = m.flex_top_n(pool, n=10)
    positions = {s.position for s in out}
    assert "QB" not in positions
    assert positions == {"RB", "WR", "TE"}
    assert [s.total_points for s in out] == [200, 150, 100]


def test_flex_top_n_with_size_limit():
    pool = [_score(p, "WR") for p in [100, 95, 90, 85, 80]]
    out = m.flex_top_n(pool, n=3)
    assert [s.total_points for s in out] == [100, 95, 90]


# ── position_metrics ─────────────────────────────────────────────────


def test_position_metrics_basic():
    pts = [300, 250, 200, 150, 100]
    samples = [_score(p, "QB") for p in pts]
    out = m.position_metrics(samples)
    assert out.sample_size == 5
    assert out.average == pytest.approx(200.0)
    assert out.median == pytest.approx(200.0)
    assert out.replacement_level == 100.0  # the Nth (last) player
    assert out.elite == pytest.approx(250.0)  # mean of top 3 = (300+250+200)/3
    assert out.replacement_adj == pytest.approx(100.0)


def test_position_metrics_empty():
    out = m.position_metrics([])
    assert out.sample_size == 0
    assert out.average == 0
    assert out.median == 0


def test_position_metrics_single_value():
    out = m.position_metrics([_score(50, "TE")])
    assert out.sample_size == 1
    assert out.average == 50
    assert out.median == 50
    assert out.replacement_level == 50
    assert out.replacement_adj == 0
    assert out.elite == 50


# ── blended scores ───────────────────────────────────────────────────


def test_legacy_blended_is_avg_median_average():
    metrics = m.PositionMetrics(
        average=200,
        median=180,
        p25=150,
        p75=250,
        replacement_level=100,
        elite=300,
        replacement_adj=100,
        sample_size=5,
    )
    assert m.legacy_blended(metrics) == pytest.approx(190.0)


def test_improved_blended_uses_documented_weights():
    metrics = m.PositionMetrics(
        average=200,
        median=180,
        p25=120,
        p75=240,
        replacement_level=100,
        elite=300,
        replacement_adj=100,
        sample_size=5,
    )
    expected = 0.35 * 180 + 0.25 * 200 + 0.20 * 240 + 0.10 * 120 + 0.10 * 100
    assert m.improved_blended(metrics) == pytest.approx(expected)


# ── shares ───────────────────────────────────────────────────────────


def test_position_shares_sum_to_100():
    inp = {"QB": 100, "RB": 200, "WR": 300, "TE": 400}
    shares = m.position_shares(inp)
    assert sum(shares.values()) == pytest.approx(100.0)
    assert shares["QB"] == pytest.approx(10.0)
    assert shares["TE"] == pytest.approx(40.0)


def test_position_shares_handles_zero_total():
    shares = m.position_shares({"QB": 0, "RB": 0})
    assert all(v == 0 for v in shares.values())


def test_position_shares_treats_negative_as_zero():
    shares = m.position_shares({"QB": -50, "RB": 100, "WR": 100, "TE": 100})
    # Negative QB drops to zero in the total; RB/WR/TE split 100% three ways
    assert shares["QB"] == 0
    assert shares["RB"] == pytest.approx(100 / 3)


# ── status_label ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "diff,expected",
    [
        (0.3, "Excellent match"),
        (-0.4, "Excellent match"),
        (1.0, "Good match"),
        (-1.4, "Good match"),
        (2.5, "Slightly high"),
        (-2.5, "Slightly low"),
        (4.5, "High"),
        (-4.5, "Low"),
        (8.0, "Too high"),
        (-9.0, "Too low"),
    ],
)
def test_status_label_bands(diff, expected):
    assert m.status_label(diff) == expected


# ── similarity score ─────────────────────────────────────────────────


def test_similarity_score_perfect_match_is_100():
    shares = {"QB": 25, "RB": 25, "WR": 30, "TE": 20}
    out = m.similarity_score(shares, dict(shares), my_flex=200, baseline_flex=200)
    assert out.score == 100
    assert out.distortion_label == "Low"
    assert "Extremely close" in out.label


def test_similarity_score_small_difference_high():
    my = {"QB": 26, "RB": 24, "WR": 30, "TE": 20}
    base = {"QB": 25, "RB": 25, "WR": 30, "TE": 20}
    # Combined = 2.0 pp diff + 0 flex dev → at 2 boundary, score 95
    out = m.similarity_score(my, base, my_flex=200, baseline_flex=200)
    assert out.score >= 95


def test_similarity_score_meaningful_difference_drops():
    my = {"QB": 35, "RB": 20, "WR": 25, "TE": 20}
    base = {"QB": 25, "RB": 25, "WR": 30, "TE": 20}
    # share dev = 10 + 5 + 5 + 0 = 20 pp -> straddles "Meaningfully different"
    out = m.similarity_score(my, base, my_flex=200, baseline_flex=200)
    assert 60 <= out.score <= 74
    assert out.distortion_label == "High"


def test_similarity_score_severe_distortion():
    my = {"QB": 50, "RB": 20, "WR": 20, "TE": 10}
    base = {"QB": 25, "RB": 25, "WR": 30, "TE": 20}
    out = m.similarity_score(my, base, my_flex=300, baseline_flex=200)
    assert out.score < 60
    assert out.distortion_label == "Severe"


def test_similarity_score_handles_zero_baseline_flex():
    out = m.similarity_score(
        {"QB": 25, "RB": 25, "WR": 30, "TE": 20},
        {"QB": 25, "RB": 25, "WR": 30, "TE": 20},
        my_flex=200,
        baseline_flex=0,
    )
    # No NaN, no crash; flex deviation simply zero
    assert math.isfinite(out.score)
    assert out.flex_dev_pct == 0


# ── recommendations ──────────────────────────────────────────────────


def test_recommendation_aligned_says_no_adjustment():
    text = m.recommendation("QB", 0.3, my_share=25.0, baseline_share=24.7)
    assert "essentially aligned" in text
    assert "No adjustment" in text


def test_recommendation_includes_culprit_hints_for_meaningful_diff():
    text = m.recommendation("TE", 4.0, my_share=20.0, baseline_share=16.0)
    assert "TE" in text
    assert "+4.0" in text
    assert "TE premium" in text or "PPR" in text  # one of the culprit hints


def test_recommendation_lower_direction():
    text = m.recommendation("WR", -3.0, my_share=27.0, baseline_share=30.0)
    assert "lower" in text
    assert "-3.0" in text
