"""Wave B (B0) — the suggestions equalizer obeys the generated-trade rules.

Two owner rules bind a balancer, because a balancer puts a FURTHER asset into
a generated package (spec §2.3 "trade equalizers"):

* **C7-PICKGEN-01 rule 5** (``docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_
  ADDENDUM_2026-08-14.md``): "Do not use a pick merely to make raw totals line
  up."  A balancer is, by definition, an asset chosen to make totals line up —
  so a draft pick may never be one.  Picks enter generated trades only through
  the posture-aware generator, which reasons about both teams' strategy.
* **C3-TOPO-01** (``src/packages/construction.py::topology_is_allowed``): a
  generated package keeps ``abs(players_A - players_B) <= 1``.  Adding a player
  to the larger side of a 2-for-1 proposes a 3-for-1, which the owner rule
  forbids.
"""

from __future__ import annotations

from src.trade.suggestions import (
    PlayerAsset,
    TradeSuggestion,
    _fairness_label,
    _find_balancers,
    _va_gap,
)


def _asset(name: str, value: int, position: str = "RB") -> PlayerAsset:
    return PlayerAsset(
        name=name,
        position=position,
        display_value=value,
        calibrated_value=value,
        source_count=6,
    )


def _suggestion(give: list[PlayerAsset], receive: list[PlayerAsset]) -> TradeSuggestion:
    gap = _va_gap([p.display_value for p in give], [p.display_value for p in receive])
    return TradeSuggestion(
        type="sell_high",
        give=give,
        receive=receive,
        give_total=sum(p.display_value for p in give),
        receive_total=sum(p.display_value for p in receive),
        gap=gap,
        fairness=_fairness_label(gap),
        rationale="",
        why_this_helps="",
        confidence="high",
        strategy="neutral",
    )


def test_a_draft_pick_is_never_a_balancer():
    # 2-for-1 where the opponent must sweeten; the ONLY assets in the pool are
    # picks.  The retired eligibility rule (``a.position`` truthy) offered them
    # as filler — the control test below proves a player of the same value is
    # a working balancer here, so an empty answer is the rule, not the math.
    suggestion = _suggestion([_asset("A", 5000), _asset("B", 5000)], [_asset("Star", 6000)])
    assert suggestion.gap > 0  # user overpays → they_add
    pool = [_asset(f"2027 Pick {v}", v, "PICK") for v in range(1000, 4001, 250)]
    balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
    assert balancers == [] and residuals == []
    assert side == "they_add"


def test_players_still_balance_when_picks_are_excluded():
    suggestion = _suggestion([_asset("A", 5000), _asset("B", 5000)], [_asset("Star", 6000)])
    pool = [_asset(f"2027 Pick {v}", v, "PICK") for v in range(1000, 4001, 250)]
    pool.append(_asset("Depth WR", 3000, "WR"))
    balancers, _side, _res = _find_balancers(suggestion, pool, set(), set())
    assert [b.name for b in balancers] == ["Depth WR"]


def test_a_balancer_never_turns_two_for_one_into_three_for_one():
    # User gives two players for one and still underpays → "you_add".  One more
    # player on the user's side is a 3-for-1: refused by C3-TOPO-01.
    suggestion = _suggestion(
        [_asset("A", 3000), _asset("B", 3000)],
        [_asset("Star", 9500)],
    )
    assert suggestion.gap < 0
    pool = [_asset(f"p{v}", v, "WR") for v in range(1000, 4001, 250)]
    balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
    assert side == "you_add"
    assert balancers == [] and residuals == []


def test_a_balancer_may_even_up_a_two_for_one():
    # User gives two for one and OVERPAYS → "they_add": one more player on the
    # opponent's side makes it 2-for-2, which is allowed.
    suggestion = _suggestion(
        [_asset("A", 5000), _asset("B", 5000)],
        [_asset("Star", 6000)],
    )
    assert suggestion.gap > 0
    pool = [_asset(f"p{v}", v, "WR") for v in range(1000, 4001, 250)]
    balancers, side, _res = _find_balancers(suggestion, pool, set(), set())
    assert side == "they_add"
    assert balancers, "a 2-for-2 landing is legal topology"
