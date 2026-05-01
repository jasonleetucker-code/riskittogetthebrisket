"""Test equal-weight season combination + missing-season behavior."""
from __future__ import annotations

import pytest

from src.league_comparison import metrics as m


def _pm(avg: float, med: float, sample: int = 24) -> m.PositionMetrics:
    return m.PositionMetrics(
        average=avg, median=med, p25=med * 0.7, p75=med * 1.3,
        replacement_level=med * 0.5, elite=med * 1.5,
        replacement_adj=avg - med * 0.5, sample_size=sample,
    )


def test_combine_seasons_equal_weight_averages_finite_values():
    out = m.combine_seasons_equal_weight([100, 110, 120, 130])
    assert out == pytest.approx(115.0)


def test_combine_seasons_skips_none_values():
    # 3 of 4 seasons available; the missing one drops out and the
    # remaining three each effectively count 1/3 (the equal-weight rule)
    out = m.combine_seasons_equal_weight([100, None, 120, 130])
    assert out == pytest.approx((100 + 120 + 130) / 3)


def test_combine_seasons_all_none_returns_zero():
    assert m.combine_seasons_equal_weight([None, None, None]) == 0.0


def test_combine_seasons_single_season_returns_that_season():
    assert m.combine_seasons_equal_weight([42.5, None, None, None]) == 42.5


def test_combine_metrics_equal_weight_averages_per_year():
    per_year = {
        2022: _pm(avg=200, med=180),
        2023: _pm(avg=220, med=200),
        2024: _pm(avg=210, med=190),
    }
    out = m.combine_metrics_equal_weight(per_year)
    assert out.average == pytest.approx(210)
    assert out.median == pytest.approx(190)
    assert out.sample_size == 24


def test_combine_metrics_equal_weight_skips_missing_seasons():
    per_year = {
        2022: _pm(avg=200, med=180),
        2023: None,
        2024: _pm(avg=220, med=200),
    }
    out = m.combine_metrics_equal_weight(per_year)
    assert out.average == pytest.approx(210)  # average of (200, 220)
    assert out.median == pytest.approx(190)


def test_combine_metrics_equal_weight_all_empty_returns_zero():
    out = m.combine_metrics_equal_weight({2022: None, 2023: None})
    assert out.sample_size == 0
    assert out.average == 0


def test_combine_metrics_skips_zero_sample_size_seasons():
    """A season that exists but produced an empty sample should still be
    skipped — same effect as None — so the combined value reflects only
    seasons with real data."""
    per_year = {
        2022: _pm(avg=200, med=180),
        2023: m.PositionMetrics(0, 0, 0, 0, 0, 0, 0, 0),
    }
    out = m.combine_metrics_equal_weight(per_year)
    # only 2022 contributes
    assert out.average == pytest.approx(200)
