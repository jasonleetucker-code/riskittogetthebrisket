"""Metric primitives for the ROS scale calibration study."""

from __future__ import annotations

import numpy as np
import pytest

from src.ros_calibration import metrics as mt


def test_basic_errors_and_ratio():
    assert mt.mae([1.0, 3.0], [2.0, 2.0]) == pytest.approx(1.0)
    assert mt.rmse([1.0, 3.0], [2.0, 2.0]) == pytest.approx(1.0)
    assert mt.ratio([2.0, 2.0], [1.0, 1.0]) == pytest.approx(2.0)
    assert mt.ratio([1.0], [0.0]) is None
    assert mt.mae([], []) is None


def test_spearman_ties_and_degenerate():
    assert mt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert mt.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert mt.spearman([1, 1, 1], [1, 2, 3]) is None
    assert mt.spearman([1, 2], [1, 2]) is None


def test_cross_group_concordance_counts_ties_half_and_skips_realized_ties():
    off = [(10.0, 20.0), (5.0, 1.0)]
    idp = [(7.0, 10.0), (7.0, 1.0)]
    conc, valid = mt.cross_group_concordance_matrices(off, idp)
    # pairs: (10,20)v(7,10) conc; (10,20)v(7,1) conc; (5,1)v(7,10) conc; (5,1)v(7,1) realized tie -> invalid
    assert valid.sum() == 3
    assert conc.sum() == 3
    assert mt.concordance_from_weeks({1: (conc, valid)}) == pytest.approx(1.0)
    w = {1: (np.array([2.0, 0.0]), np.array([1.0, 1.0]))}
    assert mt.concordance_from_weeks({1: (conc, valid)}, w) == pytest.approx(1.0)


def test_all_play_concordance():
    c, d = mt.all_play_concordance([3.0, 2.0, 1.0], [30.0, 10.0, 20.0])
    assert d == 3
    assert c == pytest.approx(2 / 3)


def test_cluster_bootstrap_is_deterministic():
    recs = [{"c": str(i % 5), "v": float(i)} for i in range(50)]
    f = lambda rs: sum(r["v"] for r in rs) / len(rs)  # noqa: E731
    a = mt.cluster_bootstrap(recs, lambda r: r["c"], f, b=200, seed=7)
    b = mt.cluster_bootstrap(recs, lambda r: r["c"], f, b=200, seed=7)
    assert a == b
    assert a["clusters"] == 5
    assert a["ci95"][0] <= a["estimate"] <= a["ci95"][1]


def test_calibration_slope():
    assert mt.calibration_slope([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(2.0)
    assert mt.calibration_slope([1.0, 1.0], [2.0, 3.0]) is None
