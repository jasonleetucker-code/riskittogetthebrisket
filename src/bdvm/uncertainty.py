"""Seasonal outcome dispersion σ(t) (BDVM module 7).

    CV = CV_base,p · (1 + 0.90·role_unc) · (1 + 0.45·event_vol) · (1 + 0.60·small_sample)
    σ(0) = sqrt((CV·µ)² + σ_source²)
    σ(t) = sqrt(σ(0)² + (ψ_p·µ(t)·√t)²)

σ is a MODELLED quantity, not a penalty: the option-value surplus turns
dispersion into value near replacement and is neutral far above it.
"""

from __future__ import annotations

import math

from src.bdvm.params import ParamSet
from src.bdvm.survival import RiskProfile


def sigma_fpg(
    params: ParamSet,
    pos: str,
    mu: float,
    risk: RiskProfile,
    sigma_source: float,
    t: int,
    *,
    true_position_known: bool = True,
) -> float:
    mults = params["sigma_multipliers"]
    cv = params.cv_base(pos)
    cv *= 1.0 + float(mults["role_uncertainty"]) * risk.role_uncertainty
    cv *= 1.0 + float(mults["event_volatility"]) * risk.event_volatility
    cv *= 1.0 + float(mults["small_sample"]) * risk.small_sample
    s0 = math.sqrt((cv * mu) ** 2 + sigma_source**2)
    drift = params.drift_vol(pos) * mu * math.sqrt(max(0, t))
    sigma = math.sqrt(s0**2 + drift**2)
    if not true_position_known:
        sigma *= float(params["unknown_true_position_sigma_mult"])
    return sigma
