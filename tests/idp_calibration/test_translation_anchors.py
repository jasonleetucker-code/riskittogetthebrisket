from __future__ import annotations

from src.idp_calibration.anchors import build_all_anchors
from src.idp_calibration.buckets import BucketResult
from src.idp_calibration.translation import (
    DEFAULT_BLEND,
    DEFAULT_YEAR_WEIGHTS,
    build_multi_year_multipliers,
    normalise_year_weights,
)


def _bucket(label, lo, hi, test_val, mine_val, count=20):
    return BucketResult(
        label=label,
        lo=lo,
        hi=hi,
        count=count,
        mean_vor_test=test_val,
        median_vor_test=test_val,
        center_vor_test=test_val,
        mean_vor_mine=mine_val,
        median_vor_mine=mine_val,
        center_vor_mine=mine_val,
        ratio_mine_over_test=mine_val / test_val if test_val else None,
    )


def _three_bucket_series(test_seed, mine_seed):
    return [
        _bucket("1-6", 1, 6, test_seed, mine_seed),
        _bucket("7-12", 7, 12, test_seed * 0.6, mine_seed * 0.65),
        _bucket("13-24", 13, 24, test_seed * 0.3, mine_seed * 0.28),
    ]


def test_build_multi_year_multipliers_produces_normalised_curves():
    per_position = {
        "DL": {
            2025: _three_bucket_series(100, 120),
            2024: _three_bucket_series(95, 115),
            2023: _three_bucket_series(90, 110),
            2022: _three_bucket_series(85, 100),
        }
    }
    year_weights = normalise_year_weights(DEFAULT_YEAR_WEIGHTS, seasons=[2022, 2023, 2024, 2025])
    multipliers = build_multi_year_multipliers(
        per_position, year_weights=year_weights, blend=DEFAULT_BLEND
    )
    dl = multipliers["DL"].buckets
    assert dl[0].intrinsic == 1.0  # Top bucket normalised to 1.0
    assert dl[1].intrinsic < dl[0].intrinsic
    assert dl[2].intrinsic < dl[1].intrinsic
    # Final blend must sit between intrinsic and market at each bucket.
    for b in dl:
        lo = min(b.intrinsic, b.market)
        hi = max(b.intrinsic, b.market)
        assert lo - 1e-6 <= b.final <= hi + 1e-6


def test_anchors_are_non_increasing():
    per_position = {
        "LB": {
            2025: _three_bucket_series(100, 120),
            2024: _three_bucket_series(90, 110),
        }
    }
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights={2025: 0.6, 2024: 0.4},
        blend=DEFAULT_BLEND,
    )
    anchors = build_all_anchors(multipliers)
    for kind in ("intrinsic", "market", "final"):
        points = anchors["LB"][kind]
        for a, b in zip(points, points[1:]):
            assert b.value <= a.value + 1e-9, f"{kind} violates monotonicity"


def test_normalise_year_weights_handles_missing_seasons():
    weights = normalise_year_weights(DEFAULT_YEAR_WEIGHTS, seasons=[2023, 2024])
    assert 2022 not in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6
