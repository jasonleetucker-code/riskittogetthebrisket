"""Lineup outcome RANGE from the owner's imported player ranges — descriptive only.

For each built lineup: the p10 / p50 / p90 of its total, from each player's
imported spread (``SlateAthlete.distribution``):

* ``sd`` supplied → that standard deviation;
* otherwise two or more percentiles → the normal whose spread matches the
  outermost pair (``(v_hi − v_lo) / (z_hi − z_lo)``);
* an unlabelled floor/ceiling, or nothing → no spread for that player.

Assumptions, stated on every result: players are INDEPENDENT (real teammates
and opponents are correlated, so a stacked lineup's true range is wider than
shown) and each player is NORMAL around the forecast actually used (owner
override or projection, × the slot multiplier).  One player without a spread
makes the whole lineup ``unavailable`` — a missing spread is never treated as
certainty (zero width).  This is not contest EV and ranks nothing.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from src.dfs.imports import SlateAthlete

_STD = NormalDist()
_Z90 = _STD.inv_cdf(0.9)
ASSUMPTIONS = [
    "Players are treated as independent; stacked lineups really swing more than shown.",
    "Each player is a normal distribution around the forecast used, from your imported ranges.",
]


def player_spread(a: SlateAthlete) -> tuple[float, str] | None:
    """(standard deviation, basis) from the imported distribution, or None."""
    d = a.distribution
    if not d:
        return None
    if d.get("sd") is not None:
        return float(d["sd"]), "stdev"
    qs = sorted((float(q), float(v)) for q, v in (d.get("quantiles") or {}).items())
    if len(qs) >= 2:
        (qlo, vlo), (qhi, vhi) = qs[0], qs[-1]
        return (vhi - vlo) / (_STD.inv_cdf(qhi) - _STD.inv_cdf(qlo)), "quantile_spread"
    return None


def lineup_outcome(lineup: dict[str, Any], by_id: dict[str, SlateAthlete]) -> dict[str, Any]:
    players = lineup["players"]
    spreads, missing, bases = [], [], set()
    for p in players:
        got = player_spread(by_id[p["playerId"]])
        if got is None or p.get("slotProjection") is None:
            missing.append(p["name"])
            continue
        sd, basis = got
        spreads.append(sd * (p.get("slotMultiplier") or 1.0))
        bases.add(basis)
    coverage = f"{len(players) - len(missing)} of {len(players)}"
    if missing:
        return {"state": "unavailable", "coverage": coverage, "missing": missing[:20]}
    mean = lineup["projection"]
    sd = math.sqrt(sum(s * s for s in spreads))
    return {
        "state": "available",
        "coverage": coverage,
        "mean": round(mean, 2),
        "sd": round(sd, 2),
        "p10": round(mean - _Z90 * sd, 2),
        "p50": round(mean, 2),
        "p90": round(mean + _Z90 * sd, 2),
        "basis": sorted(bases),
        "assumptions": ASSUMPTIONS,
    }


def attach_outcomes(result: dict[str, Any], athletes: list[SlateAthlete]) -> int:
    """Stamp ``outcome`` on every built lineup in place; return how many are available."""
    by_id = {a.player_id: a for a in athletes}
    n = 0
    for lu in result.get("lineups") or []:
        lu["outcome"] = lineup_outcome(lu, by_id)
        n += lu["outcome"]["state"] == "available"
    return n
