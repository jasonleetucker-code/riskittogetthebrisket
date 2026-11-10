"""Deterministic tests of the trade-uncertainty study's metric functions.

Every expected number below is computed by hand in the comment beside it.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from scripts.research import trade_uncertainty_study as tu


def test_pinball_hand_computed():
    # y=1, q=[0, 2], taus=[.25,.75]
    # k0: d=1  -> max(.25*1, -.75*1) = .25 ; k1: d=-1 -> max(.75*-1, -.25*-1) = .25
    got = tu.pinball_per_row(np.array([1.0]), np.array([[0.0, 2.0]]), [0.25, 0.75])
    assert got == pytest.approx([0.25])


def test_pinball_perfect_quantile_and_asymmetry():
    assert tu.pinball_per_row(np.array([3.0]), np.array([[3.0, 3.0]]), [0.1, 0.9])[0] == 0.0
    # under-prediction at tau=.9 costs .9*d: y=2,q=1 -> .9
    assert tu.pinball_per_row(np.array([2.0]), np.array([[1.0]]), [0.9])[0] == pytest.approx(0.9)
    # over-prediction at tau=.9 costs .1*|d|: y=1,q=2 -> .1
    assert tu.pinball_per_row(np.array([1.0]), np.array([[2.0]]), [0.9])[0] == pytest.approx(0.1)


def test_interval_bounds_and_coverage():
    taus = tu.TAUS
    q = np.tile(np.arange(len(taus), dtype=float), (2, 1))  # q_k = k
    lo, hi = tu.interval_bounds(q, taus, 0.8)  # tau .10 -> idx 1, tau .90 -> idx 17
    assert (lo == 1).all() and (hi == 17).all()
    lo5, hi5 = tu.interval_bounds(q, taus, 0.5)  # .25 -> idx 4, .75 -> idx 14
    assert (lo5 == 4).all() and (hi5 == 14).all()
    flags = tu.coverage_flags(np.array([0.0, 0.1, 0.2]), np.array([-0.1] * 3), np.array([0.1] * 3))
    assert flags.tolist() == [1.0, 1.0, 0.0]  # endpoints inclusive
    assert flags.mean() == pytest.approx(2 / 3)


def test_interval_bounds_rejects_off_grid():
    with pytest.raises(ValueError):
        tu.interval_bounds(np.zeros((1, 3)), [0.1, 0.5, 0.9], 0.5)  # .25 not on grid


def test_empirical_quantiles_linear():
    # [0..4], tau .25/.5/.75 -> positions 1,2,3 exactly
    got = tu.empirical_quantiles(np.array([0, 1, 2, 3, 4]), [0.25, 0.5, 0.75])
    assert got.tolist() == [1.0, 2.0, 3.0]
    # [0,10], tau .3 -> 3.0 (linear)
    assert tu.empirical_quantiles(np.array([0.0, 10.0]), [0.3])[0] == pytest.approx(3.0)


def test_incumbent_quantiles_match_the_simulators_own_map():
    q = dict(zip(tu.TAUS.tolist(), tu.incumbent_quantiles()))
    assert q[0.5] == pytest.approx(0.0)
    assert q[0.1] == pytest.approx(-0.15)
    assert q[0.9] == pytest.approx(0.15)
    # tau .25: t = (.25-.10)/.40 = .375 along p10 -> p50 (-.15 -> 0): -.15 + .375*.15
    assert q[0.25] == pytest.approx(-0.09375)
    assert q[0.75] == pytest.approx(0.09375)
    # extrapolated tail tau .05: slope .15, t=.5 -> -.15 - .15*(1-.5) = -.225
    assert q[0.05] == pytest.approx(-0.225)
    assert q[0.95] == pytest.approx(0.225)


def test_tier_and_age_and_group():
    assert tu.tier_of(np.array([999.9, 1000.0, 2499.0, 5000.0, 7500.0, 9999.0])).tolist() == [
        0,
        1,
        1,
        3,
        4,
        4,
    ]
    assert tu.age_bucket(None, False, "offense") == "unknown"
    assert tu.age_bucket(24.0, False, "offense") == "le24"
    assert tu.age_bucket(25.0, False, "idp") == "25_28"
    assert tu.age_bucket(29.0, False, "offense") == "ge29"
    assert tu.age_bucket(22.0, True, "offense") == "rookie"
    assert tu.age_bucket(None, False, "pick") == "pick"
    assert tu.asset_group("PICK", "pick") == "pick"
    assert tu.asset_group("LB", "idp") == "idp"
    assert tu.asset_group("QB", "offense") == "offense"


def test_select_cell_backoff_needs_both_floors():
    table = {
        ("a",): {"n": 500, "dates": 3},  # enough rows, too few dates
        ("b",): {"n": 100, "dates": 20},  # enough dates, too few rows
        ("c",): {"n": 300, "dates": 8},  # exactly at both floors
    }
    assert tu.select_cell([("a",), ("b",), ("c",)], table) == (2, ("c",))
    assert tu.select_cell([("a",), ("b",)], table) == (2, None)
    assert tu.select_cell([("c",), ("a",)], table) == (0, ("c",))


def _meta(stems=("a", "b"), n=100, lag=0):
    return {"stems": tuple(stems), "n_priced": n, "payload_lag_days": lag}


def test_break_rules_are_input_based():
    d0 = date(2026, 7, 1)
    meta = {
        d0: _meta(),
        d0 + timedelta(days=1): _meta(stems=("a", "b", "c")),  # source added
        d0 + timedelta(days=2): _meta(stems=("a", "b", "c"), n=89),  # 11% drop vs 100
        d0 + timedelta(days=3): _meta(stems=("a", "b", "c"), n=89, lag=4),  # stale payload
        d0 + timedelta(days=4): _meta(stems=("a", "b", "c"), n=95, lag=3),  # 6.7% up, lag==3 ok
    }
    got = tu.flag_break_dates(meta)
    assert got[d0 + timedelta(days=1)] == ["source_set_changed"]
    assert got[d0 + timedelta(days=2)] == ["priced_count_jump_gt_10pct"]
    assert got[d0 + timedelta(days=3)] == ["payload_stale_gt_3d"]
    assert d0 not in got and (d0 + timedelta(days=4)) not in got


def test_pair_exclusion_covers_origin_target_and_interior():
    br = {date(2026, 7, 5)}
    assert tu.pair_is_excluded(date(2026, 7, 1), 7, br)  # break strictly inside
    assert tu.pair_is_excluded(date(2026, 7, 5), 7, br)  # at origin
    assert tu.pair_is_excluded(date(2026, 6, 28), 7, br)  # at target (7/5)
    assert not tu.pair_is_excluded(date(2026, 7, 6), 7, br)  # after
    assert not tu.pair_is_excluded(date(2026, 6, 20), 7, br)  # before


def test_walk_forward_never_trains_on_a_future_outcome():
    store = tu.TrainStore()
    base = date(2026, 6, 1)
    for k in range(40):
        o = base + timedelta(days=k)
        store.add(
            o,
            7,
            {
                "r": np.array([0.0]),
                "group": np.array(["offense"]),
                "pos": np.array(["QB"]),
                "age_b": np.array(["ge29"]),
                "tier": np.array([1]),
                "cv": np.array([0.1]),
            },
        )
    cutoff = date(2026, 6, 20)
    t = store.training(cutoff, 7)
    # every kept pair's TARGET date (origin + 7) is on or before the cutoff
    assert (t["odate"] + 7 <= cutoff.toordinal()).all()
    # origins 6/1..6/13 qualify (6/13 + 7 = 6/20): 13 pairs; 6/14 would target 6/21
    assert len(t["r"]) == 13
    assert store.training(date(2026, 5, 31), 7) == {}


def test_block_bootstrap_is_deterministic_and_length_n():
    a = tu.block_bootstrap_indices(20, 7, np.random.default_rng(1))
    b = tu.block_bootstrap_indices(20, 7, np.random.default_rng(1))
    assert a.tolist() == b.tolist() and len(a) == 20
    assert (np.diff(a[:7]) == 1).all()  # within a block, indices are consecutive


def test_bootstrap_ratio_ci_degenerate_and_hand_value():
    est, lo, hi = tu.bootstrap_ratio_ci(np.array([8.0] * 10), np.array([10.0] * 10), 3, reps=50)
    assert est == pytest.approx(0.8) and lo == pytest.approx(0.8) and hi == pytest.approx(0.8)
    e, lo2, hi2 = tu.bootstrap_diff_ci(
        np.array([3.0, 3.0]), np.array([1.0, 1.0]), np.array([4.0, 4.0]), 1, reps=20
    )
    # (6 - 2) / 8 = .5 in every replicate
    assert (e, lo2, hi2) == (pytest.approx(0.5), pytest.approx(0.5), pytest.approx(0.5))


def test_m1_prediction_scales_with_dispersion():
    qz = np.array([-2.0, 0.0, 2.0])
    got = tu.predict_m1(qz, np.array([0.1, 0.5]))
    assert got.tolist() == [[-0.2, 0.0, 0.2], [-1.0, 0.0, 1.0]]


def test_m3_recovers_known_variance_law():
    rng = np.random.default_rng(0)
    cv = rng.uniform(0.05, 0.4, 900)
    h = rng.choice([7, 14, 28], 900)
    a, b = 0.5, 0.002
    r = np.sqrt(a * cv**2 + b * h) * rng.choice([-1.0, 1.0], 900)
    fa, fb, qz = tu.fit_m3(r, cv, h)
    assert fa == pytest.approx(a, rel=1e-6) and fb == pytest.approx(b, rel=1e-6)
    assert qz[0] == pytest.approx(-1.0) and qz[-1] == pytest.approx(1.0)
    pred = tu.predict_m3(fa, fb, qz, np.array([0.2]), 14)
    assert pred[0, -1] == pytest.approx(np.sqrt(a * 0.04 + b * 14))


def test_dispersion_models_are_unavailable_without_cv_or_floor():
    assert tu.fit_m1(np.zeros(10), np.full(10, 0.1)) is None  # below N_FLOOR
    assert tu.fit_m1(np.ones(400), np.full(400, np.nan)) is None  # null CV is not 0
    assert tu.fit_m3(np.ones(400), np.zeros(400), np.full(400, 7)) is None  # cv<=0 unusable


def test_sign_persistence_and_gap_bins():
    got = tu.sign_persists(np.array([5.0, 5.0, -3.0, 0.0]), np.array([1.0, -1.0, -9.0, 4.0]))
    assert got.tolist() == [True, False, True, False]
    # edges 2%,5%,10%,20%: bins 0..4
    assert tu.gap_bin(np.array([0.0, 0.0199, 0.02, 0.07, 0.15, 0.5])).tolist() == [0, 0, 1, 2, 3, 4]


def test_decision_rule_requires_decidable_7_and_14():
    base = {"models": {}, "decidable": False}
    s = {"byHorizon": {"7": dict(base, decidable=True), "14": dict(base), "28": dict(base)}}
    assert tu.apply_decision_rule(s)["verdict"].startswith("(c)")
