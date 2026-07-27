"""Generic package display math + both-sides trade evaluation (§3.13).

Layer 1 (this module): CES package aggregation for DISPLAY —
``(Σ v^θ)^(1/θ) − C_spot·overflow``.  θ>1 prices consolidation: the best
asset dominates, so a 3-for-1 quantity dump must clear a real bar.

Layer 2 (the authoritative personalized verdict, ΔU on actual rosters)
lives with the roster tooling — ``src/roster_intel`` already computes
real marginal utility via the exact lineup solver; BDVM feeds it values
rather than re-implementing it.  Do not judge 2-for-1s by adding
displayed values.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.bdvm.params import ParamSet


def package_value(
    values: Sequence[float],
    params: ParamSet,
    *,
    spots_available: int = 3,
    roster_size: int | None = None,
) -> float:
    """CES aggregation with a roster-spot overflow charge."""
    if not values:
        return 0.0
    pkg = params["package"]
    theta = float(pkg["theta"])
    if roster_size is not None and roster_size <= int(pkg["shallow_roster_size_threshold"]):
        theta = float(pkg["theta_shallow_league"])
    spot_cost = float(pkg["roster_spot_cost"])
    core = sum(max(0.0, v) ** theta for v in values) ** (1.0 / theta)
    overflow = max(0, len(values) - max(1, spots_available))
    return core - spot_cost * overflow


def trade_verdict(
    side_a: Sequence[float],
    side_b: Sequence[float],
    params: ParamSet,
    *,
    spots_available_a: int = 3,
    spots_available_b: int = 3,
    roster_size: int | None = None,
) -> dict[str, float]:
    a = package_value(side_a, params, spots_available=spots_available_a, roster_size=roster_size)
    b = package_value(side_b, params, spots_available=spots_available_b, roster_size=roster_size)
    total = max(1.0, a + b)
    return {"side_a": a, "side_b": b, "edge": a - b, "edge_pct": 100.0 * (a - b) / total}


def evaluate_both_sides(
    *,
    gives_by_strategy_a: Mapping[str, Sequence[float]],
    gets_by_strategy_a: Mapping[str, Sequence[float]],
    strategy_a: str,
    strategy_b: str,
    params: ParamSet,
    spots_available_a: int = 3,
    spots_available_b: int = 3,
) -> dict[str, Any]:
    """Double-positive evaluation: each side priced in ITS OWN currency.

    ``gives_by_strategy_a[s]`` / ``gets_by_strategy_a[s]`` are the trade
    values of the assets A sends/receives, computed under strategy ``s``.
    Side B receives what A gives and vice versa.  A trade is
    ``double_positive`` when each manager gains under their own
    strategy profile — those are the trades that actually get accepted.
    """
    a_out = list(gives_by_strategy_a.get(strategy_a, ()))
    a_in = list(gets_by_strategy_a.get(strategy_a, ()))
    b_out = list(gets_by_strategy_a.get(strategy_b, ()))  # B sends what A gets
    b_in = list(gives_by_strategy_a.get(strategy_b, ()))  # B gets what A gives

    a_gain = package_value(a_in, params, spots_available=spots_available_a) - package_value(
        a_out, params, spots_available=spots_available_a
    )
    b_gain = package_value(b_in, params, spots_available=spots_available_b) - package_value(
        b_out, params, spots_available=spots_available_b
    )
    return {
        "a_gain": a_gain,
        "b_gain": b_gain,
        "double_positive": a_gain > 0 and b_gain > 0,
        "a_strategy": strategy_a,
        "b_strategy": strategy_b,
    }
