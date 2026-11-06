"""AMATH-S01: size-controlled gates keep their nominal level at small n (research layer)."""

from __future__ import annotations

import numpy as np
import pytest

from src.model_registry import size_controlled_gates as scg

SMALL = {"QB": 24, "RB": 40, "WR": 56, "TE": 64, "DL": 80, "LB": 95, "DB": 95}


def test_sidak_split_recovers_overall_level():
    a = scg.sidak_alpha(0.10, 7)
    assert (1 - a) ** 7 == pytest.approx(0.90)


def test_critical_regions_depend_on_n():
    assert scg.ks_critical_value(24, 0.01) > scg.ks_critical_value(95, 0.01) > 0
    lo24, hi24 = scg.coverage_acceptance(24, 0.8, 0.01)
    lo95, hi95 = scg.coverage_acceptance(95, 0.8, 0.01)
    assert (hi24 - lo24) / 24 > (hi95 - lo95) / 95  # relative band narrows with n


def test_acceptance_region_tails_are_within_alpha():
    from scipy import stats

    for n in (24, 56, 95):
        lo, hi = scg.coverage_acceptance(n, 0.8, 0.02)
        assert stats.binom.cdf(lo - 1, n, 0.8) <= 0.01
        assert stats.binom.sf(hi, n, 0.8) <= 0.01


def test_perfect_model_passes_at_least_nominal_at_small_n():
    r = scg.pass_rate_under_null(SMALL, reps=1500)
    # the audit's admission bar: a perfect model passes >= 90% (3 MC standard errors slack)
    assert r["passRate"] >= 0.90 - 3 * r["mcStdErr"], r
    # and the gate is not vacuous: it is not so loose that it never rejects
    assert r["typeIError"] > 0.0


def test_fixed_gate_would_fail_the_same_perfect_model():
    """Contrast: the preregistered fixed KS bound (D <= 0.08) rejects a perfect model here."""
    rng = np.random.default_rng(1)
    reps = 400
    fails = 0
    for _ in range(reps):
        ok = all(scg._ks_d(np.sort(rng.random(n))) <= 0.08 for n in SMALL.values())
        fails += not ok
    assert fails / reps > 0.5


def test_miscalibrated_model_is_still_rejected():
    rng = np.random.default_rng(2)
    # overconfident forecasts: PITs pile up in the tails
    fam = {k: rng.beta(0.5, 0.5, 150) for k in ("QB", "RB")}
    assert scg.gate_family_set(fam)["pass"] is False


def test_tiny_family_is_reported_not_scored():
    out = scg.gate_family_set({"QB": [0.5], "RB": list(np.linspace(0.01, 0.99, 50))})
    assert out["unscoredFamilies"] == ["QB"]
