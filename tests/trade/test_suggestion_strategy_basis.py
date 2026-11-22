"""``strategyBasis`` discloses WHY a suggestion carries its ``strategy`` label.

Disclosure only (owner directive 2026-11-21, DYN10): the ``strategy`` value is
unchanged and is NOT the team's competitive posture
(``src/roster_intel/window.py``).  These tests pin the basis per generator
site and that the label itself did not move.
"""

from __future__ import annotations

import inspect

import pytest

from src.trade import suggestions as sg
from src.trade.suggestions import PlayerAsset, TradeSuggestion, _serialize_suggestion


def _p(name, pos, val, *, rookie=False, yrs=None):
    return PlayerAsset(
        name=name,
        position=pos,
        display_value=val,
        calibrated_value=val,
        rookie=rookie,
        years_exp=yrs,
    )


@pytest.mark.parametrize(
    ("player", "strategy", "basis"),
    [
        (_p("A", "WR", 5000, rookie=True), "rebuilder", "years_experience_proxy"),
        (_p("B", "WR", 5000, yrs=2), "rebuilder", "years_experience_proxy"),
        (_p("C", "WR", 5000, yrs=8), "contender", "years_experience_proxy"),
        (_p("D", "WR", 5000, yrs=5), "neutral", "generator_default"),
        (_p("E", "WR", 5000, yrs=None), "neutral", "generator_default"),
    ],
)
def test_player_strategy_basis_and_unchanged_label(player, strategy, basis):
    assert sg._strategy_for_player(player) == strategy
    assert sg._strategy_basis_for_player(player) == basis


def test_every_construction_site_names_a_basis():
    for fn in (
        sg._generate_sell_high,
        sg._generate_buy_low,
        sg._generate_consolidation,
        sg._generate_positional_upgrades,
    ):
        src = inspect.getsource(fn)
        assert src.count("strategy=") == src.count("strategy_basis="), fn.__name__


def test_consolidation_basis_matches_value_threshold():
    src = inspect.getsource(sg._generate_consolidation)
    assert "STRATEGY_BASIS_VALUE_THRESHOLD_7000" in src
    assert sg.STRATEGY_BASIS_VALUE_THRESHOLD_7000 == "value_threshold_7000"


def test_serialized_payload_carries_basis_and_strategy():
    s = TradeSuggestion(
        type="consolidation",
        give=[_p("G", "WR", 3000)],
        receive=[_p("R", "WR", 7200)],
        give_total=3000,
        receive_total=7200,
        gap=4200,
        fairness="stretch",
        rationale="r",
        why_this_helps="w",
        confidence="low",
        strategy="contender",
        strategy_basis="value_threshold_7000",
    )
    out = _serialize_suggestion(s)
    assert out["strategy"] == "contender"
    assert out["strategyBasis"] == "value_threshold_7000"
