"""Lineup outcome range: honest about what it assumes and what it lacks."""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest

from src.dfs.imports import SlateAthlete
from src.dfs.outcomes import lineup_outcome, player_spread

Z90 = NormalDist().inv_cdf(0.9)


def _a(pid, dist):
    return SlateAthlete(
        player_id=pid,
        name=f"P{pid}",
        positions=["F"],
        team="T",
        opponent=None,
        game=None,
        salary=5000,
        projection=20.0,
        distribution=dist,
    )


def _lineup(ids, mults=None, proj=20.0):
    mults = mults or [1.0] * len(ids)
    players = [
        {"playerId": p, "name": f"P{p}", "slotProjection": proj * m, "slotMultiplier": m}
        for p, m in zip(ids, mults)
    ]
    return {"players": players, "projection": sum(p["slotProjection"] for p in players)}


def test_stdev_and_percentile_ranges_agree_for_a_normal_player():
    sd = player_spread(_a("1", {"sd": 6.0, "quantiles": {}, "unassigned": {}}))
    # p10/p90 of a N(20, 6) player, imported as percentiles, recover the same spread.
    q = {"0.10": 20 - Z90 * 6.0, "0.90": 20 + Z90 * 6.0}
    from_q = player_spread(_a("2", {"sd": None, "quantiles": q, "unassigned": {}}))
    assert sd == (6.0, "stdev")
    assert from_q[0] == pytest.approx(6.0) and from_q[1] == "quantile_spread"


def test_unlabelled_floor_ceiling_gives_no_spread():
    assert (
        player_spread(
            _a("1", {"sd": None, "quantiles": {}, "unassigned": {"floor": 5, "ceiling": 30}})
        )
        is None
    )
    assert player_spread(_a("1", None)) is None


def test_independent_sum_and_captain_scaling():
    by = {p: _a(p, {"sd": 3.0, "quantiles": {}, "unassigned": {}}) for p in "123"}
    out = lineup_outcome(_lineup(["1", "2", "3"], [1.5, 1.0, 1.0]), by)
    sd = math.sqrt(4.5**2 + 3.0**2 + 3.0**2)  # captain's spread scales with the 1.5x
    assert out["state"] == "available" and out["sd"] == pytest.approx(sd, abs=0.01)
    assert out["p90"] - out["p50"] == pytest.approx(Z90 * sd, abs=0.02)
    assert out["mean"] == pytest.approx(70.0) and "independent" in out["assumptions"][0]


def test_one_missing_spread_makes_the_lineup_unavailable_never_zero_width():
    by = {"1": _a("1", {"sd": 3.0, "quantiles": {}, "unassigned": {}}), "2": _a("2", None)}
    out = lineup_outcome(_lineup(["1", "2"]), by)
    assert out == {"state": "unavailable", "coverage": "1 of 2", "missing": ["P2"]}
