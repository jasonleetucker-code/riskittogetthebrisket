"""Tests for the Phase 1 effective-auction-power lens.

Pins the economic invariants from src/api/auction_power.py:
zero-sum ($ total preserved), S-shaped/saturating premium, leapfrog,
and provable raw passthrough when uninformative or disabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.auction_power import effective_auction_power


def _total(d: dict[str, int]) -> int:
    return sum(d.values())


def test_zero_sum_preserves_league_total():
    raw = {"A": 175, "B": 180, "C": 90, "D": 60, "E": 40, "F": 55}
    eff = effective_auction_power(raw)
    assert _total(eff) == round(sum(raw.values()))


def test_thousand_two_hundred_invariant():
    # 12 teams summing to exactly the $1200 league pool.
    raw = {f"T{i}": v for i, v in enumerate([200, 180, 150, 130, 110, 90, 80, 70, 60, 50, 45, 35])}
    assert sum(raw.values()) == 1200
    eff = effective_auction_power(raw)
    assert _total(eff) == 1200


def test_disabled_is_exact_raw_passthrough():
    raw = {"A": 175, "B": 180, "C": 90, "D": 60, "E": 40, "F": 55}
    eff = effective_auction_power(raw, enabled=False)
    assert eff == {k: int(v) for k, v in raw.items()}


def test_degenerate_equal_field_is_identity():
    raw = {"A": 100, "B": 100, "C": 100, "D": 100}
    eff = effective_auction_power(raw)
    assert eff == {k: int(v) for k, v in raw.items()}


def test_single_team_is_identity():
    raw = {"A": 1200}
    assert effective_auction_power(raw) == {"A": 1200}


def test_biggest_stack_gets_a_premium_above_raw():
    # The clear leader's effective power should exceed its raw $; the
    # field collectively gives it up (zero-sum).
    raw = {"A": 260, "B": 130, "C": 120, "D": 110, "E": 100, "F": 80}
    eff = effective_auction_power(raw)
    assert eff["A"] > raw["A"]
    # And the smallest stacks should not be inflated.
    assert eff["F"] <= raw["F"]


def test_leapfrog_user_hypothetical():
    # User's scenario: trailing team (was 175, rival 180) trades to
    # pass the leader.  Once it edges ahead and becomes the clear top
    # stack, its effective power should reflect a premium vs the field.
    after = {"me": 188, "rival": 167, "c": 95, "d": 85, "e": 75, "f": 65}
    eff_after = effective_auction_power(after)
    # Leapfrogging into the lead is worth strictly more effective
    # power than the raw dollar lead alone.
    assert eff_after["me"] > after["me"]
    assert eff_after["me"] > eff_after["rival"]


def test_marginal_value_saturates_for_dominant_stack():
    # Adding the same $20 to an already-commanding stack yields less
    # effective gain than adding it to a mid-pack team — the S-curve
    # saturates at the top (dominant team is a natural pick seller).
    base = {"dom": 320, "b": 90, "c": 85, "d": 80, "e": 75, "f": 70, "g": 60, "h": 50}
    dom_plus = effective_auction_power({**base, "dom": base["dom"] + 20})
    mid_plus = effective_auction_power({**base, "c": base["c"] + 20})
    base_eff = effective_auction_power(base)
    dom_gain = dom_plus["dom"] - base_eff["dom"]
    mid_gain = mid_plus["c"] - base_eff["c"]
    assert mid_gain > dom_gain


def test_monotone_in_raw_for_a_given_team():
    base = {"A": 120, "B": 110, "C": 100, "D": 90, "E": 80, "F": 70}
    more = effective_auction_power({**base, "A": 160})
    less = effective_auction_power({**base, "A": 130})
    assert more["A"] > less["A"]
