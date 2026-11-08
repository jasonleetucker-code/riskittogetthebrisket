"""MISSING IS NEVER ZERO at the trade asset record (MD-105).

An on-board player the pipeline did not price is UNKNOWN (``value`` None +
``valueState: "unpriced"``).  A row that STATES a numeric zero is a known
zero and stays 0.  Downstream sums treat unknown as absent from the total.
"""

from __future__ import annotations

from src.api.trade_simulator import _aggregate, _priced_value, resolve_trade_asset


def _row(name: str, **kw):
    return {"displayName": name, "canonicalName": name.lower(), "position": "WR", **kw}


def _contract(*rows):
    return {"playersArray": list(rows), "players": {}}


def _resolve(row):
    return resolve_trade_asset(row["displayName"], contract=_contract(row))


def test_unpriced_player_is_null_with_explicit_state():
    a = _resolve(_row("Ghost Wr"))
    assert a is not None
    assert a["value"] is None and a["valueState"] == "unpriced" and a["tier"] is None


def test_priced_player_is_unchanged_and_carries_no_state():
    a = _resolve(_row("Real Wr", rankDerivedValue=4200))
    assert a["value"] == 4200 and "valueState" not in a


def test_stated_zero_is_a_known_zero_not_unknown():
    a = _resolve(_row("Zero Wr", rankDerivedValue=0))
    assert a["value"] == 0 and "valueState" not in a


def test_sums_and_tiers_exclude_unknown_without_inventing_zero():
    ghost = _resolve(_row("Ghost Wr"))
    real = _resolve(_row("Real Wr", rankDerivedValue=4200))
    assert _priced_value(ghost) == 0
    agg = _aggregate([ghost, real])
    assert agg["totalValue"] == 4200
    assert sum(agg["tiers"].values()) == 1  # the unknown sits in no tier
    assert agg["byPosition"]["WR"]["count"] == 2  # but still occupies a position
