"""Duplication: naive baseline kept; zero-truncated fit recovers truth and must beat it on holdout."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.dfs import duplication


def test_naive_estimate_is_field_times_product_of_ownership():
    own = {"a": 50.0, "b": 20.0, "c": 10.0}
    sal = {"a": 20000, "b": 15000, "c": 15000}
    est = duplication.estimate(["a", "b", "c"], own, sal, 50000, field_size=10001)
    assert est["naive"] == pytest.approx(10000 * 0.5 * 0.2 * 0.1)
    assert est["pDuplicated"]["naive"] == pytest.approx(1 - math.exp(-100.0))
    assert (
        duplication.estimate(["a", "z"], own, {**sal, "z": 1}, 50000, 100)["state"] == "unavailable"
    )


def _synthetic(true, n_lineups, seed, field=20_000):
    """Lineups that would be entered under ``true`` params; keep only those that appear."""
    rng = np.random.default_rng(seed)
    lpo = rng.uniform(-22, -8, n_lineups)
    left = rng.uniform(0, 3, n_lineups)
    lam = field * np.exp(true["a"] + true["b"] * lpo + true["c"] * left)
    counts = rng.poisson(lam)
    return [
        (field, float(x), float(y), int(c), 1.0) for x, y, c in zip(lpo, left, counts) if c >= 1
    ]


def test_zero_truncated_fit_recovers_known_parameters_and_beats_naive_on_holdout():
    true = {"a": 1.5, "b": 0.8, "c": -0.6}
    train = _synthetic(true, 60_000, seed=1)
    holdout = _synthetic(true, 60_000, seed=2)
    assert len(train) > 500  # truncation keeps only lineups that appeared
    fit = duplication.fit(train)
    p = fit["params"]
    assert fit["converged"]
    assert p["b"] == pytest.approx(true["b"], abs=0.08) and p["c"] == pytest.approx(
        true["c"], abs=0.08
    )
    score = duplication.holdout_score(holdout, p)
    assert score["nll"] < score["naiveNll"]  # on data the fit never saw


def test_fit_refuses_thin_evidence_and_rows_use_weights_and_prelock_ownership():
    assert duplication.fit([(100, -10.0, 0.5, 2, 1.0)] * 10)["params"] is None
    sample = {
        "repeated": [{"players": ["a", "b"], "count": 3, "weight": 1.0}],
        "singles": [
            {"players": ["a", "c"], "count": 1, "weight": 40.0},
            {"players": ["a", "z"], "count": 1, "weight": 40.0},
        ],
    }
    own = {
        "a": 50.0,
        "b": 20.0,
        "c": 10.0,
    }  # "z" has no forecast → that lineup is skipped, not zero
    rows = duplication.rows_from_result(
        sample, own, {"a": 1000, "b": 1000, "c": 1000, "z": 1000}, 5000, 300
    )
    assert [(r[3], r[4]) for r in rows] == [(3, 1.0), (1, 40.0)]
