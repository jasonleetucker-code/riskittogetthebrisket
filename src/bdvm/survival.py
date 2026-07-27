"""Fantasy-relevance survival (BDVM module 6).

Discrete-time hazard of losing fantasy-startable status:

    S(t) = prod_{k=1..t} (1 - h(k)),    S(0) = 1

Base hazards are position/age-band priors adjusted multiplicatively by
role security, decayed draft capital, contract security, durability,
production and (IDP) designation risk.  Hazard uses CHRONOLOGICAL age;
mileage-adjusted effective age belongs to the aging curve only — using
it here would double-count workload (pinned by tests).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.bdvm.params import ParamSet


@dataclass(frozen=True)
class RiskProfile:
    """All scores 0-1.  Higher = safer, except the ones marked RISK."""

    role_security: float = 0.6
    draft_capital: float = 0.5  # 1.0 = top-10 pick, 0.0 = UDFA
    contract_security: float = 0.6
    durability: float = 0.6
    production_z: float = 0.0  # z-score of current VOR vs position
    scheme_stability: float = 0.6
    role_uncertainty: float = 0.25  # RISK: higher = worse
    event_volatility: float = 0.30  # RISK: higher = worse
    small_sample: float = 0.0  # RISK: 1.0 = no NFL sample
    designation_risk: float = 0.0  # RISK: IDP eligibility-flip risk


def base_hazard(params: ParamSet, pos: str, age: float) -> float:
    for cutoff, h in params.base_hazard_schedule(pos):
        if age < cutoff:
            return h
    return 0.5


def hazard(
    params: ParamSet,
    pos: str,
    age: float,
    risk: RiskProfile,
    dc_decay: float,
) -> float:
    """Annual hazard of losing startable status at chronological ``age``."""
    adjust = params["hazard_adjusters"]
    h = base_hazard(params, pos, age)
    adj = 1.0
    adj *= 1.0 + float(adjust["role_security"]["gamma"]) * (
        float(adjust["role_security"]["reference"]) - risk.role_security
    )
    adj *= 1.0 + float(adjust["draft_capital"]["gamma"]) * dc_decay * (
        float(adjust["draft_capital"]["reference"]) - risk.draft_capital
    )
    adj *= 1.0 + float(adjust["contract_security"]["gamma"]) * (
        float(adjust["contract_security"]["reference"]) - risk.contract_security
    )
    adj *= 1.0 + float(adjust["durability"]["gamma"]) * (
        float(adjust["durability"]["reference"]) - risk.durability
    )
    z_clip = float(adjust["production_z"]["clip"])
    adj *= 1.0 - float(adjust["production_z"]["gamma"]) * max(
        -z_clip, min(z_clip, risk.production_z)
    )
    adj *= 1.0 + float(adjust["designation_risk"]["gamma"]) * risk.designation_risk
    return max(float(adjust["clip_lo"]), min(float(adjust["clip_hi"]), h * adj))


def survival_path(
    params: ParamSet,
    pos: str,
    start_age: float,
    risk: RiskProfile,
    dc_decay: float,
    horizon: int,
) -> list[float]:
    """[S(0), S(1), ..., S(horizon)] with S(0) = 1."""
    out = [1.0]
    s = 1.0
    for t in range(1, horizon + 1):
        s *= 1.0 - hazard(params, pos, start_age + t, risk, dc_decay)
        out.append(s)
    return out


def expected_remaining_seasons(path: list[float]) -> float:
    """E[remaining fantasy-relevant seasons] = sum_{t>=1} S(t)."""
    return sum(path[1:])
