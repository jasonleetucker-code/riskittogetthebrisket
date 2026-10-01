"""Unit tests for the joint outlier/sparse challenger's robustness step.

The documented trap (``tests/api/test_value_replay.py``): three observations at
3000/3100/3200 with weight 0.03 each and one at 4600 with weight 1.0. The
incumbent value-only filter drops the 4600; a naive weighted filter drops the
three and then the 0.30 single-source rule turns 4600 into 1380. The challenger
must do neither.
"""

from __future__ import annotations

import itertools

import pytest

from src.api.joint_robust_filter import (
    effective_family_count,
    joint_robust_filter,
    weighted_median,
)

K, MIN_N, FLOOR = 2.75, 4, 1000.0
TRAP = [("stale_a", 3000.0), ("stale_b", 3100.0), ("stale_c", 3200.0), ("fresh", 4600.0)]
TRAP_W = {"stale_a": 0.03, "stale_b": 0.03, "stale_c": 0.03, "fresh": 1.0}
DISTINCT = {k: k for k, _ in TRAP}


def _run(obs, weights, families=None, **kw):
    return joint_robust_filter(
        obs,
        weights,
        families or {k: k for k, _ in obs},
        k=K,
        min_n=MIN_N,
        min_threshold=FLOOR,
        **kw,
    )


def test_dominant_fresh_evidence_is_never_dropped_for_disagreeing():
    result = _run(TRAP, TRAP_W, DISTINCT)
    assert "fresh" in result.kept
    assert result.centre == 4600.0


def test_the_filter_does_not_manufacture_a_single_family_row():
    # Dropping the weak trio would leave one family: refused, disagreement kept.
    result = _run(TRAP, TRAP_W, DISTINCT)
    assert result.dropped == ()
    assert {result.reasons[k] for k in ("stale_a", "stale_b", "stale_c")} == {
        "kept_to_avoid_single_family"
    }


def test_a_genuine_outlier_with_little_weight_is_still_removed():
    obs = [("a", 3000.0), ("b", 3050.0), ("c", 3100.0), ("d", 2950.0), ("bad", 9000.0)]
    w = {k: 1.0 for k, _ in obs}
    result = _run(obs, w)
    assert result.dropped == ("bad",)
    assert result.reasons["bad"] == "outlier"


def test_equal_weights_reproduce_the_incumbent_decision_on_a_plain_outlier():
    from src.api.data_contract import _hampel_filter_per_player

    obs = [("a", 3000.0), ("b", 3050.0), ("c", 3100.0), ("d", 2950.0), ("bad", 9000.0)]
    _kept, incumbent = _hampel_filter_per_player(obs)
    assert tuple(incumbent) == _run(obs, {k: 1.0 for k, _ in obs}).dropped


def test_order_invariance():
    obs = [("a", 3000.0), ("b", 3050.0), ("c", 3100.0), ("d", 2950.0), ("bad", 9000.0)]
    w = {"a": 1.0, "b": 0.5, "c": 0.7, "d": 0.2, "bad": 0.1}
    reference = _run(obs, w)
    for perm in itertools.permutations(obs):
        assert _run(list(perm), w) == reference


def test_zero_dispersion_uses_the_floor():
    obs = [("a", 3000.0), ("b", 3000.0), ("c", 3000.0), ("far", 3900.0), ("farther", 4100.0)]
    result = _run(obs, {k: 1.0 for k, _ in obs})
    assert result.scale == 0.0 and result.threshold == FLOOR
    assert result.dropped == ("farther",)  # 1100 > floor; 900 is not


def test_below_min_n_and_zero_weights_skip():
    assert _run(TRAP[:3], TRAP_W).reasons == {"skipped": "below_min_n"}
    assert _run(TRAP, {k: 0.0 for k in TRAP_W}).reasons == {"skipped": "no_positive_weight"}


def test_duplicate_family_members_cannot_outvote_independent_evidence():
    # Three members of one family (capped weights sum to 1.0) vs two independent
    # sources: the family is one piece of evidence, not three.
    obs = [("fam1", 5000.0), ("fam2", 5050.0), ("fam3", 5100.0), ("x", 3000.0), ("y", 3050.0)]
    families = {"fam1": "F", "fam2": "F", "fam3": "F", "x": "X", "y": "Y"}
    capped = {"fam1": 1 / 3, "fam2": 1 / 3, "fam3": 1 / 3, "x": 1.0, "y": 1.0}
    result = _run(obs, capped, families)
    assert result.centre == 3050.0  # weighted median sides with the two independents


@pytest.mark.parametrize(
    ("values", "weights", "expected"),
    [([1, 2, 3], [1, 1, 1], 2), ([1, 2, 3], [0, 0, 1], 3), ([5], [0], None), ([1, 9], [3, 1], 1)],
)
def test_weighted_median(values, weights, expected):
    assert weighted_median(values, weights) == expected


def test_effective_family_count_discloses_concentration():
    assert effective_family_count({"A": 1.0, "B": 1.0}) == pytest.approx(2.0)
    assert effective_family_count({"A": 1.0, "B": 0.01}) == pytest.approx(1.02, abs=0.01)
    assert effective_family_count({}) is None


def test_the_trap_through_the_real_blend_lands_near_the_dominant_evidence():
    # Filter + the pipeline's own weighted blend: ~4538, not the incumbent's
    # 3100 (fresh 4600 dropped) nor the naive weighted filter's 1380 (4600 alone
    # then x0.30).
    from src.api.data_contract import (
        _SINGLE_SOURCE_VALUE_RETENTION,
        _hampel_filter_per_player,
        weighted_count_aware_mean_median_blend,
    )

    result = _run(TRAP, TRAP_W, DISTINCT)
    kept = [(k, v) for k, v in TRAP if k in result.kept]
    value, _spread = weighted_count_aware_mean_median_blend(
        [v for _k, v in kept], [TRAP_W[k] for k, _v in kept]
    )
    assert 4500 < value < 4600
    incumbent_kept, _ = _hampel_filter_per_player(TRAP)
    incumbent, _ = weighted_count_aware_mean_median_blend(
        [v for _k, v in incumbent_kept], [TRAP_W[k] for k, _v in incumbent_kept]
    )
    assert incumbent == 3100.0
    assert round(4600 * _SINGLE_SOURCE_VALUE_RETENTION) == 1380
