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


def test_build_multi_year_multipliers_produces_offense_anchored_curves():
    # Schema v2: ``intrinsic`` and ``market`` carry offense-anchored
    # VOR (bucket_center / offense_anchor), and ``final`` is their
    # cross-league ratio. Setup: both anchors set to 100 so ``intrinsic``
    # is the bucket center expressed as a multiple of "one top-24 flex
    # starter's VOR", and ``final`` is the mine/test VOR ratio.
    per_position = {
        "DL": {
            2025: _three_bucket_series(100, 120),
            2024: _three_bucket_series(95, 115),
            2023: _three_bucket_series(90, 110),
            2022: _three_bucket_series(85, 100),
        }
    }
    year_weights = normalise_year_weights(
        DEFAULT_YEAR_WEIGHTS, seasons=[2022, 2023, 2024, 2025]
    )
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights=year_weights,
        blend=DEFAULT_BLEND,
        offense_anchor_mine=100.0,
        offense_anchor_test=100.0,
    )
    dl = multipliers["DL"].buckets
    # Bucket centers divided by anchor: top-bucket intrinsic =
    # weighted-mean(mine_seed) / 100. For this fixture the bucket
    # centers shrink with rank, so intrinsic monotonically decreases.
    assert dl[0].intrinsic > dl[1].intrinsic > dl[2].intrinsic
    assert dl[0].market > dl[1].market > dl[2].market
    # Every final is the offense-anchored ratio. With both anchors ==
    # 100 it collapses to mine_center / test_center.
    for b in dl:
        expected = b.intrinsic / b.market
        assert abs(b.final - expected) < 1e-6


def test_final_lifts_above_one_when_my_league_values_a_bucket_more():
    # Setup: both sides agree on the top bucket but my league scores
    # rank 7-12 much more generously (edge-premium scoring). The
    # relativity ratio for 7-12 must climb above 1.0 — this is the
    # exact behaviour the schema-v1 engine could not produce.
    per_position = {
        "DL": {
            2025: [
                _bucket("1-6", 1, 6, 100.0, 100.0),
                _bucket("7-12", 7, 12, 40.0, 80.0),  # my-league doubles the bucket
            ]
        }
    }
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights={2025: 1.0},
        blend=DEFAULT_BLEND,
        offense_anchor_mine=100.0,
        offense_anchor_test=100.0,
    )
    dl = multipliers["DL"].buckets
    assert abs(dl[0].final - 1.0) < 1e-6  # agreeing top bucket → 1.0
    assert dl[1].final > 1.5  # my-league 80 / test 40 = 2.0 → lifted


def test_anchors_preserve_relativity_signal():
    # The v2 anchor smoothing pass must NOT force monotone descent —
    # otherwise a lifted mid-rank bucket (final > top) would get
    # clamped down to the top bucket value and destroy the signal.
    per_position = {
        "LB": {
            2025: [
                _bucket("1-6", 1, 6, 100.0, 100.0),
                _bucket("7-12", 7, 12, 40.0, 80.0),  # lifted bucket
                _bucket("13-24", 13, 24, 25.0, 25.0),
            ]
        }
    }
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights={2025: 1.0},
        blend=DEFAULT_BLEND,
        offense_anchor_mine=100.0,
        offense_anchor_test=100.0,
    )
    anchors = build_all_anchors(multipliers)
    # rank=12 sits inside the 7-12 bucket where final ≈ 2.0. Rank=1
    # sits in the 1-6 bucket where final ≈ 1.0. The v1 code would have
    # forced rank=12 <= rank=1 (≈1.0) and lost the lift signal.
    pts = {p.rank: p.value for p in anchors["LB"]["final"]}
    assert pts[12] > 1.5, "7-12 lift was flattened by monotone smoothing"
    # Floor is still respected (no negative/zero values).
    for v in pts.values():
        assert v >= 0.05 - 1e-9


def test_bucket_labels_aggregate_across_seasons_not_just_first():
    # Season A merged 13-24 away; season B kept it. The multiplier table
    # must still include the 13-24 bucket in the aggregate.
    season_a = [_bucket("1-6", 1, 6, 100, 110), _bucket("7-12", 7, 12, 60, 65)]
    season_b = _three_bucket_series(100, 115)  # includes 13-24
    per_position = {"DL": {2025: season_a, 2024: season_b}}
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights={2025: 0.6, 2024: 0.4},
        blend=DEFAULT_BLEND,
    )
    labels = [b.label for b in multipliers["DL"].buckets]
    assert "1-6" in labels
    assert "7-12" in labels
    assert "13-24" in labels  # Previously silently dropped.
    # Ordering must be by numeric low bound — 1-6 before 7-12 before 13-24.
    assert labels.index("1-6") < labels.index("7-12") < labels.index("13-24")


def test_normalise_year_weights_handles_missing_seasons():
    weights = normalise_year_weights(DEFAULT_YEAR_WEIGHTS, seasons=[2023, 2024])
    assert 2022 not in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_normalise_year_weights_uniform_fallback_for_custom_seasons():
    # User picks seasons outside the default weight keys. Every year
    # has weight 0 in the defaults. We must NOT return all zeros —
    # that silently produces a no-op calibration downstream.
    weights = normalise_year_weights(
        DEFAULT_YEAR_WEIGHTS, seasons=[2021, 2020, 2019]
    )
    # Uniform fallback: each season gets 1/3.
    assert set(weights.keys()) == {2021, 2020, 2019}
    for v in weights.values():
        assert abs(v - 1.0 / 3.0) < 1e-9
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_normalise_year_weights_empty_seasons_returns_empty():
    # Edge case — protect against ZeroDivisionError in the uniform
    # branch when nothing is selected.
    assert normalise_year_weights(DEFAULT_YEAR_WEIGHTS, seasons=[]) == {}


def _series(*pairs, count=10):
    """Build a single-season bucket series where each tuple is
    (label, lo, hi, test_val, mine_val)."""
    return [_bucket(lbl, lo, hi, tv, mv, count=count) for lbl, lo, hi, tv, mv in pairs]


def test_sub_replacement_buckets_fall_through_to_identity():
    # v2 behaviour: sub-replacement buckets (center <= 0 on either side)
    # can't produce a meaningful cross-league ratio, so they fall
    # through to ``final=1.0`` (identity). The ``intrinsic`` /
    # ``market`` display fields still surface the raw offense-anchored
    # VOR, including negatives, for audit.
    series = _series(
        ("1-6", 1, 6, 100.0, 120.0),
        ("7-12", 7, 12, 50.0, 60.0),
        ("13-24", 13, 24, 20.0, 25.0),
        ("25-36", 25, 36, 0.0, 5.0),                # zero bucket on test side
        ("37-60", 37, 60, -30.0, -20.0),            # sub-replacement both sides
        ("61-100", 61, 100, -55.0, -45.0),          # deep sub-replacement
    )
    per_position = {"DL": {2025: series}}
    multipliers = build_multi_year_multipliers(
        per_position,
        year_weights={2025: 1.0},
        blend=DEFAULT_BLEND,
        offense_anchor_mine=100.0,
        offense_anchor_test=100.0,
    )
    dl = multipliers["DL"].buckets
    # Bucket 1-6 and 7-12 and 13-24 have positive VOR on both sides
    # → real ratio.
    for lbl in ("1-6", "7-12", "13-24"):
        b = next(x for x in dl if x.label == lbl)
        assert b.final != 1.0 or abs(b.intrinsic - b.market) < 1e-9
    # Bucket 25-36 and deeper: at least one side is ≤ 0, so ``final``
    # falls through to 1.0 rather than producing a negative multiplier.
    for lbl in ("25-36", "37-60", "61-100"):
        b = next(x for x in dl if x.label == lbl)
        assert abs(b.final - 1.0) < 1e-9, (
            f"{lbl} final={b.final} should be identity under sub-replacement"
        )


def test_missing_offense_anchor_falls_through_to_identity():
    # If the engine couldn't compute a usable offense anchor on either
    # side (e.g. offense universe was empty every season), every
    # bucket's final must default to 1.0 so the live pipeline runs as
    # a no-op rather than applying garbage ratios.
    series = _series(
        ("1-6", 1, 6, 100.0, 120.0),
        ("7-12", 7, 12, 50.0, 60.0),
    )
    multipliers = build_multi_year_multipliers(
        {"DL": {2025: series}},
        year_weights={2025: 1.0},
        blend=DEFAULT_BLEND,
        offense_anchor_mine=0.0,  # missing anchor
        offense_anchor_test=0.0,
    )
    for b in multipliers["DL"].buckets:
        assert abs(b.final - 1.0) < 1e-9


def test_relativity_clamped_to_engineering_bounds():
    # Pathologically large disparity (10× on one side) must clamp to
    # the ``[0.25, 4.0]`` engineering band so a single weird bucket
    # can't ship an absurd multiplier to production.
    series = _series(
        ("1-6", 1, 6, 100.0, 100.0),
        ("7-12", 7, 12, 1.0, 100.0),    # test says ~nothing, mine says a lot
        ("13-24", 13, 24, 100.0, 1.0),  # mirror case
    )
    multipliers = build_multi_year_multipliers(
        {"DL": {2025: series}},
        year_weights={2025: 1.0},
        blend=DEFAULT_BLEND,
        offense_anchor_mine=100.0,
        offense_anchor_test=100.0,
    )
    dl = multipliers["DL"].buckets
    lifted = next(b for b in dl if b.label == "7-12")
    cut = next(b for b in dl if b.label == "13-24")
    assert abs(lifted.final - 4.0) < 1e-6  # pinned at ceiling
    assert abs(cut.final - 0.25) < 1e-6    # pinned at floor
