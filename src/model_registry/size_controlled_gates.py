"""Size-controlled calibration gates (AMATH-S01 / POC-B) -- research layer only.

The preregistered sim-calibration gates (``scripts/sim_calibration_study.py``:
SC-G1 coverage bands, SC-G4 ``KS D <= 0.08``) use FIXED thresholds. Under a
perfectly calibrated model a family's PIT values are iid Uniform(0, 1), so the
pass probability depends only on the family size n -- and at the real sizes
(n = 56..95) the fixed gates fail a perfect model most of the time
(``scripts/sim_calibration_gate_operating_characteristics.py``; AMATH-S01 cites
SC-G4 0.2% and SC-G1 16% at week-7 sizes).

This module is the audit's specification, nothing more: **a gate is admitted
only if a perfectly calibrated synthetic model passes it at least 90% of the
time at the real sample size.** Implementation:

* every per-family test has its critical region derived from n, not a constant:
  exact Kolmogorov (``scipy.stats.kstwo``) for uniformity, exact Binomial for an
  interval-coverage count;
* the family-wise level is split with Sidak, so a perfectly calibrated model
  passes the whole gate family with probability >= ``1 - OVERALL_ALPHA`` (0.90).

This is a SCORECARD / research helper. It is imported by no production path,
promotes nothing and changes no served value, probability or label. The existing
promotion gates are untouched. Ambiguity (documented, not resolved here): the
audit does not say how to treat dependence between a player's weeks; iid PITs
are assumed, which makes the nominal level a lower bound on real difficulty.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

#: 1 - the audit's admission bar (a perfect model must pass >= 90%).
OVERALL_ALPHA: float = 0.10
TESTS_PER_FAMILY = 3  # KS, coverage80, coverage95


def sidak_alpha(overall_alpha: float, tests: int) -> float:
    """Per-test level so ``tests`` independent null tests all pass w.p. 1 - overall."""
    if tests < 1:
        raise ValueError("tests must be >= 1")
    if not 0.0 < overall_alpha < 1.0:
        raise ValueError("overall_alpha must be in (0, 1)")
    return 1.0 - (1.0 - overall_alpha) ** (1.0 / tests)


@lru_cache(maxsize=4096)
def ks_critical_value(n: int, alpha: float) -> float:
    """Smallest D such that P(D_n >= D) <= alpha under uniformity (exact)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    return float(stats.kstwo.isf(alpha, n))


@lru_cache(maxsize=4096)
def coverage_acceptance(n: int, level: float, alpha: float) -> tuple[int, int]:
    """Inclusive covered-count interval [lo, hi] a calibrated ``level`` interval keeps.

    Equal-tailed exact Binomial region: each rejected tail has probability <= alpha/2.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    half = alpha / 2.0
    lo = 0
    while lo < n and stats.binom.cdf(lo, n, level) <= half:
        lo += 1  # counts <= lo-1 have cumulative probability <= alpha/2: rejected
    hi = n
    while hi > 0 and stats.binom.sf(hi - 1, n, level) <= half:
        hi -= 1  # counts >= hi+1 have tail probability <= alpha/2: rejected
    return lo, hi


def _ks_d(sorted_u: np.ndarray) -> float:
    n = sorted_u.size
    i = np.arange(1, n + 1)
    return float(max((i / n - sorted_u).max(), (sorted_u - (i - 1) / n).max()))


def family_gate(pits: Sequence[float], *, alpha: float) -> dict[str, Any]:
    """KS-uniformity + 80%/95% central-interval coverage for one family, each at ``alpha``.

    Coverage of the central ``level`` interval of a PIT is the share inside
    ``[(1-level)/2, 1-(1-level)/2]``.
    """
    u = np.sort(np.asarray(pits, dtype=float))
    n = int(u.size)
    if n < 2:
        return {"n": n, "status": "insufficient_sample", "pass": None}
    d = _ks_d(u)
    d_crit = ks_critical_value(n, alpha)
    out: dict[str, Any] = {
        "n": n,
        "alphaPerTest": alpha,
        "ks": {"D": d, "critical": d_crit, "pass": d <= d_crit},
    }
    ok = d <= d_crit
    for level in (0.80, 0.95):
        tail = (1.0 - level) / 2.0
        covered = int(((u >= tail) & (u <= 1.0 - tail)).sum())
        lo, hi = coverage_acceptance(n, level, alpha)
        passed = lo <= covered <= hi
        out[f"coverage{int(level * 100)}"] = {
            "covered": covered,
            "accept": [lo, hi],
            "pass": passed,
        }
        ok = ok and passed
    out["status"] = "ok"
    out["pass"] = ok
    return out


def gate_family_set(
    families: Mapping[str, Sequence[float]], *, overall_alpha: float = OVERALL_ALPHA
) -> dict[str, Any]:
    """Run every family; the whole set passes only if every family does.

    The level is split over ``len(families) * TESTS_PER_FAMILY`` tests (Sidak), so a
    perfectly calibrated model passes the set w.p. >= 1 - ``overall_alpha`` (tests
    within one family are positively dependent, which only makes this conservative;
    discreteness of the Binomial makes it conservative too). Families with fewer than
    2 observations are reported, not scored.
    """
    scored = {k: v for k, v in families.items() if len(v) >= 2}
    alpha = sidak_alpha(overall_alpha, max(1, len(scored) * TESTS_PER_FAMILY))
    results = {k: family_gate(v, alpha=alpha) for k, v in sorted(scored.items())}
    return {
        "overallAlpha": overall_alpha,
        "alphaPerTest": alpha,
        "families": results,
        "unscoredFamilies": sorted(set(families) - set(scored)),
        "pass": all(r["pass"] for r in results.values()) if results else None,
        "note": "report-only; changes no served value and promotes nothing",
    }


def pass_rate_under_null(
    sizes: Mapping[str, int],
    *,
    reps: int = 2000,
    seed: int = 20261106,
    overall_alpha: float = OVERALL_ALPHA,
) -> dict[str, float]:
    """Pass rate of the size-controlled gate set for a PERFECT model at ``sizes``."""
    rng = np.random.default_rng(seed)
    passed = 0
    for _ in range(reps):
        fam = {k: rng.random(n) for k, n in sizes.items()}
        if gate_family_set(fam, overall_alpha=overall_alpha)["pass"]:
            passed += 1
    rate = passed / reps
    return {
        "reps": reps,
        "passRate": rate,
        "typeIError": 1.0 - rate,
        "mcStdErr": math.sqrt(rate * (1 - rate) / reps),
    }
