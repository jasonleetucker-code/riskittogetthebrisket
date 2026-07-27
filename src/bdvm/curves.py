"""Aging curves, effective age (career mileage), and role ascension.

Conditional production ONLY — "how good is he if he still has a role".
Loss of role / disappearance belongs to ``survival.py``; merging the two
is the #1 double-counting failure in public dynasty models (BDVM §3.4)
and the separation is pinned by tests.
"""

from __future__ import annotations

import math

from src.bdvm.params import ParamSet


def curve_key(pos: str, archetype: str | None) -> str:
    if pos == "QB":
        return "QB_dual" if archetype == "dual" else "QB_pocket"
    return pos


def aging_mult(
    params: ParamSet,
    pos: str,
    age: float,
    archetype: str | None = None,
    *,
    dual_blend: float | None = None,
) -> float:
    """Asymmetric-Gaussian production factor, conditional on playing.

    QBs support a continuous pocket/dual blend: ``dual_blend`` in [0,1]
    interpolates between the two curves (a hard flag mishandles the
    many QBs in between — BDVM §4.1).
    """
    if pos == "QB" and dual_blend is not None:
        w = min(1.0, max(0.0, dual_blend))
        return (1.0 - w) * _curve_value(params, "QB_pocket", age) + w * _curve_value(
            params, "QB_dual", age
        )
    return _curve_value(params, curve_key(pos, archetype), age)


def _curve_value(params: ParamSet, key: str, age: float) -> float:
    peak, c_up, c_dn = params.age_curve(key)
    if age <= peak:
        return math.exp(-c_up * (peak - age) ** 2)
    return math.exp(-c_dn * (age - peak) ** 2)


def effective_age(params: ParamSet, pos: str, age: float, career_load: float) -> float:
    """Chronological age + mileage penalty (only ever increases age)."""
    mileage = params.mileage(pos)
    if mileage is None:
        return age
    _unit, ref, per_year, cap = mileage
    extra = min(cap, max(0.0, (career_load - ref) / per_year))
    return age + extra


def ascension_mult(params: ParamSet, kappa: float, t: int) -> float:
    """Bounded, saturating role-growth multiplier: 1 + κ(1 − e^(−t/τ))."""
    if kappa <= 0 or t <= 0:
        return 1.0
    tau = float(params["ascension"]["tau"])
    return 1.0 + kappa * (1.0 - math.exp(-t / tau))


def draft_capital_decay(params: ParamSet, nfl_season: int) -> float:
    """exp(−rate·(n−1)); n=1 is the rookie season."""
    rate = float(params["ascension"]["draft_capital_decay_rate"])
    return math.exp(-rate * max(0, nfl_season - 1))


def college_decay(params: ParamSet, nfl_season: int) -> float:
    rate = float(params["ascension"]["college_decay_rate"])
    return math.exp(-rate * max(0, nfl_season - 1))


def compute_kappa(
    params: ParamSet,
    *,
    nfl_season: int,
    draft_capital_score: float = 0.0,  # 0-1 (1.0 = top-10 pick)
    college_score: float = 0.0,  # standardized 0-1
    opportunity_score: float = 0.0,  # vacated/projected role growth, 0-1
    incumbency: float = 0.0,  # current role saturation, 0-1
    documented_role_change: bool = False,
) -> float:
    """Role-ascension coefficient κ (BDVM §5.4).

    κ = clip(b1·DC·w_dc + b2·w_col·COL + b3·OPP + b4·YOUTH − b5·INCUMBENT)

    Forced to 0 from ``kappa_force_zero_after_season`` on, unless a
    documented role change exists — ascension must never become a
    generic youth multiplier.
    """
    asc = params["ascension"]
    if nfl_season >= int(asc["kappa_force_zero_after_season"]) and not documented_role_change:
        return 0.0
    w = asc["kappa_weights"]
    youth = 1.0 if nfl_season <= 2 else 0.0
    kappa = (
        float(w["draft_capital"]) * draft_capital_score * draft_capital_decay(params, nfl_season)
        + float(w["college"]) * college_score * college_decay(params, nfl_season)
        + float(w["opportunity"]) * opportunity_score
        + float(w["youth"]) * youth
        - float(w["incumbency"]) * incumbency
    )
    return min(float(asc["kappa_max"]), max(float(asc["kappa_min"]), kappa))
