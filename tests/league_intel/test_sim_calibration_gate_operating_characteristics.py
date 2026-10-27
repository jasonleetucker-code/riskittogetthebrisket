"""Tests for ``scripts/sim_calibration_gate_operating_characteristics.py`` (preregistration §6.1).

The disclosure "a perfectly calibrated model passes SC-G4 about 2% of the time and SC-G1 about 27% of the
time" is committed code with a fixed seed, and is cross-checked here against exact results that need no
simulation: the multinomial for SC-G1 (PIT coverage 80 and 95 are two nested counts of an iid Uniform(0,1)
sample) and the exact finite-n Kolmogorov distribution for SC-G4.
"""

from __future__ import annotations

import math

import pytest

from scripts import sim_calibration_gate_operating_characteristics as oc
from scripts import sim_calibration_study as v1

REPS = 20_000


@pytest.fixture(scope="module")
def result():
    return oc.operating_characteristics(reps=REPS, seed=v1.SEED)


def test_a_perfectly_calibrated_model_passes_sc_g1_about_27_percent_of_the_time(result):
    assert result["SC-G1"]["everyGatedFamily"] == pytest.approx(0.27, abs=0.015)
    assert result["SC-G1"]["byFamily"]["QB"] == pytest.approx(0.70, abs=0.03)


def test_a_perfectly_calibrated_model_passes_sc_g4_about_2_percent_of_the_time(result):
    assert result["SC-G4"]["everyGatedFamily"] == pytest.approx(0.02, abs=0.01)
    assert result["SC-G4"]["byFamily"]["QB"] == pytest.approx(0.22, abs=0.03)
    assert result["SC-G4"]["byFamily"]["TE"] == pytest.approx(0.42, abs=0.03)


def test_both_halves_together_pass_well_under_one_percent_of_the_time(result):
    assert result["SC-G1_and_SC-G4"] < 0.01
    assert result["SC-G5_coverageHalves"] == pytest.approx(0.90, abs=0.02)


def test_the_run_is_deterministic_for_a_fixed_seed():
    a = oc.operating_characteristics(reps=500, seed=v1.SEED)
    b = oc.operating_characteristics(reps=500, seed=v1.SEED)
    assert a == b
    assert a != oc.operating_characteristics(reps=500, seed=v1.SEED + 1)


def test_the_simulation_uses_v1s_gate_constants():
    # The simulated bands are v1's, imported rather than copied; a change there changes this study.
    assert (v1.G1_COV80, v1.G1_COV95, v1.G4_MAX_KS_D) == ((0.75, 0.85), (0.90, 1.00), 0.08)
    assert (oc.PIT80, oc.PIT95) == ((0.10, 0.90), (0.025, 0.975))


def _exact_g1(n: int) -> float:
    """P(PIT cov80 in [.75,.85] and cov95 >= .90) for n iid Uniform(0,1): a three-cell multinomial."""
    total = 0.0
    for a in range(n + 1):  # a in the 80% interval
        if not (0.75 - 1e-9 <= a / n <= 0.85 + 1e-9):
            continue
        for b in range(n - a + 1):  # b in the 95% interval but outside the 80% one
            if (a + b) / n < 0.90 - 1e-9:
                continue
            c = n - a - b
            total += math.exp(
                math.lgamma(n + 1)
                - math.lgamma(a + 1)
                - math.lgamma(b + 1)
                - math.lgamma(c + 1)
                + a * math.log(0.80)
                + b * math.log(0.15)
                + c * math.log(0.05)
            )
    return total


def test_the_simulation_agrees_with_the_exact_results(result):
    kstwo = pytest.importorskip("scipy.stats").kstwo
    exact_g1 = math.prod(_exact_g1(n) for n in oc.FAMILY_N.values())
    exact_g4 = math.prod(float(kstwo.cdf(v1.G4_MAX_KS_D, n)) for n in oc.FAMILY_N.values())
    assert exact_g1 == pytest.approx(0.273, abs=0.001)
    assert exact_g4 == pytest.approx(0.0178, abs=0.0005)
    for got, exact in (
        (result["SC-G1"]["everyGatedFamily"], exact_g1),
        (result["SC-G4"]["everyGatedFamily"], exact_g4),
    ):
        se = math.sqrt(exact * (1.0 - exact) / REPS)
        assert abs(got - exact) < 4.0 * se
