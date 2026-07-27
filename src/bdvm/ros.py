"""Rest-of-season value math (BDVM §5.13) — SCAFFOLDING in v1.

ROS is a single-horizon concept: no aging, no survival, no discounting;
playoff-week weighting only.  It is not dynasty value and not market
value, and it is stored separately.

v1 status: the shrinkage blend and weekly-sum shapes are implemented and
tested, but the production inputs (weekly schedule, byes, expected
return dates, in-season recent form under league scoring) are not wired
— the existing ``src/ros`` package remains the live ROS surface (it is
rank-consensus based).  Replacing its rank index with this points-based
ROS is future work recorded in the implementation report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.bdvm.params import ParamSet
from src.bdvm.surplus import expected_positive_surplus


def ros_projection_weight(weeks_played: float, *, is_idp: bool, params: ParamSet) -> float:
    """w_proj = n_prior / (n_prior + weeks_played)."""
    cfg = params["ros"]
    n_prior = float(cfg["n_prior_idp"] if is_idp else cfg["n_prior_offense"])
    return n_prior / (n_prior + max(0.0, weeks_played))


def blend_ros_mu(
    mu_preseason_updated: float,
    mu_recent_form: float,
    weeks_played: float,
    *,
    is_idp: bool,
    params: ParamSet,
) -> float:
    w = ros_projection_weight(weeks_played, is_idp=is_idp, params=params)
    return w * mu_preseason_updated + (1.0 - w) * mu_recent_form


@dataclass(frozen=True)
class RosWeek:
    week: int
    is_bye: bool
    p_active: float  # availability probability (injury/return/ramp)
    is_league_playoff: bool = False


def ros_value(
    mu_ros: float,
    sigma: float,
    replacement_fpg: float,
    weeks: Sequence[RosWeek],
    *,
    playoff_weight: float = 0.0,
) -> float:
    """Σ_w 1{not bye} · P(active) · E[max(0, X_w − R)] · PlayoffWeight(w)."""
    per_game = expected_positive_surplus(mu_ros, sigma, replacement_fpg)
    total = 0.0
    for wk in weeks:
        if wk.is_bye:
            continue
        weight = 1.0 + (playoff_weight if wk.is_league_playoff else 0.0)
        total += max(0.0, min(1.0, wk.p_active)) * per_game * weight
    return total
