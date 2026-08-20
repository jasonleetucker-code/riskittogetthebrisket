"""Defect #800 — the equalizer must solve the gap the user is shown.

``TradeSuggestion.gap`` is :func:`src.trade.suggestions._va_gap`: the gap
AFTER KTC's package Value Adjustment, which is what the fairness verdict
and the trade page both display.  ``_find_balancers`` used to rank
candidates by ``abs(candidate.display_value - abs(gap))`` — a **raw**
player value matched against an **adjusted** target.

That is only valid if adding a piece worth ``V`` moves the adjusted gap
by ``V``, and it does not: VA is a function of BOTH sides' complete
value arrays, so adding a piece re-runs ``ktc_adjust_package`` from
scratch.

These tests pin the repair.  They build packages directly rather than
reading the live board, so nothing here depends on which sources
answered the last scrape.
"""

from __future__ import annotations

import pytest

from src.trade.suggestions import (
    MAX_BALANCERS,
    MIN_RELEVANT_VALUE,
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


def _suggestion(give: list[int], receive: list[int], positions: str = "RB") -> TradeSuggestion:
    give_assets = [_asset(f"give{i}", v, positions) for i, v in enumerate(give)]
    receive_assets = [_asset(f"recv{i}", v, positions) for i, v in enumerate(receive)]
    gap = _va_gap(give, receive)
    return TradeSuggestion(
        type="sell_high",
        give=give_assets,
        receive=receive_assets,
        give_total=sum(give),
        receive_total=sum(receive),
        gap=gap,
        fairness=_fairness_label(gap),
        rationale="",
        why_this_helps="",
        confidence="high",
        strategy="neutral",
    )


def _pool(
    step: int = 100, lo: int = 600, hi: int = 9500, position: str = "RB"
) -> list[PlayerAsset]:
    return [_asset(f"pool{v}", v, position) for v in range(lo, hi + 1, step)]


def _residual_for(suggestion: TradeSuggestion, value: int, side: str) -> int:
    give = [p.display_value for p in suggestion.give]
    receive = [p.display_value for p in suggestion.receive]
    if side == "you_add":
        return _va_gap([*give, value], receive)
    return _va_gap(give, [*receive, value])


# ── The shapes the lane brief names ──────────────────────────────────

_SHAPES = [
    pytest.param([8000], [3000, 2500], id="1-for-2"),
    pytest.param([3000, 2500], [8000], id="2-for-1"),
    pytest.param([7000, 1200], [4500, 1500], id="2-for-2"),
    pytest.param([9500], [3500, 2000, 1200], id="1-for-3"),
    pytest.param([6400, 3100, 1800], [7900, 2200], id="3-for-2"),
    pytest.param([9000], [4000], id="1-for-1"),
]


@pytest.mark.parametrize("give,receive", _SHAPES)
def test_chosen_balancer_never_leaves_the_trade_further_apart(give, receive):
    """The repaired rule cannot make a trade worse than it started."""

    suggestion = _suggestion(give, receive)
    pool = _pool()
    balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
    if not balancers:
        return
    for residual in residuals:
        assert abs(residual) < abs(suggestion.gap)


@pytest.mark.parametrize("give,receive", _SHAPES)
def test_chosen_balancer_is_the_best_available_from_the_pool(give, receive):
    """Exhaustive check: nothing eligible closes the gap better."""

    suggestion = _suggestion(give, receive)
    pool = _pool()
    balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
    if not balancers:
        # Only legitimate when nothing in the pool improves on the gap.
        for candidate in pool:
            assert abs(
                _residual_for(
                    suggestion,
                    candidate.display_value,
                    "you_add" if suggestion.gap < 0 else "they_add",
                )
            ) >= abs(suggestion.gap)
        return
    best = min(abs(_residual_for(suggestion, c.display_value, side)) for c in pool)
    assert abs(residuals[0]) == best


@pytest.mark.parametrize("give,receive", _SHAPES)
def test_published_residual_matches_a_recomputation(give, receive):
    """``balancerResidualGaps`` must be the gap that actually remains."""

    suggestion = _suggestion(give, receive)
    balancers, side, residuals = _find_balancers(suggestion, _pool(), set(), set())
    assert len(residuals) == len(balancers)
    for balancer, residual in zip(balancers, residuals):
        assert residual == _residual_for(suggestion, balancer.display_value, side)


def test_the_retired_value_matching_rule_would_have_picked_worse():
    """The fix has to bite, not just be differently spelled.

    Reproduces the old rule — nearest raw value to ``abs(gap)`` — on a
    package where it demonstrably overshoots, and asserts the repaired
    engine does better.  Without this, a refactor that reinstated
    value-matching would pass every other test in this file.
    """

    suggestion = _suggestion([8000], [3000, 2500])
    pool = _pool()
    side = "they_add"
    target = abs(suggestion.gap)

    old_pick = min(pool, key=lambda c: (abs(c.display_value - target), c.name))
    old_residual = _residual_for(suggestion, old_pick.display_value, side)

    _balancers, new_side, residuals = _find_balancers(suggestion, pool, set(), set())
    assert new_side == side
    assert abs(residuals[0]) < abs(old_residual)


def test_overshoot_does_not_hand_the_lead_to_the_other_side():
    """A balancer must not flip which side is ahead.

    This is the visible symptom of #800: the equalizer targets the
    adjusted gap with a raw value, lands past it, and the meter swings
    to the other team.
    """

    for give, receive in [
        ([428, 3420], [2808, 6451, 4484]),
        ([8000], [3000, 2500]),
        ([9500], [3500, 2000, 1200]),
    ]:
        suggestion = _suggestion(give, receive)
        pool = _pool(step=50)
        balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
        if not balancers:
            continue
        # A residual strictly smaller in magnitude is already asserted
        # elsewhere; here the sign must not have crossed over, given a
        # candidate existed that keeps it on the same side.
        keeps_side = [
            c
            for c in pool
            if _residual_for(suggestion, c.display_value, side) * suggestion.gap > 0
            and abs(_residual_for(suggestion, c.display_value, side)) < abs(suggestion.gap)
        ]
        if keeps_side:
            best_keeping = min(
                abs(_residual_for(suggestion, c.display_value, side)) for c in keeps_side
            )
            assert abs(residuals[0]) <= best_keeping


# ── Missing is never zero ────────────────────────────────────────────


def test_unpriced_candidates_never_become_balancers():
    """A candidate the board declined to price cannot close a gap.

    ``MIN_RELEVANT_VALUE`` already gates the pools; this pins that a
    zero-valued asset is not silently treated as a legitimate
    no-op balancer that "closes" nothing.
    """

    suggestion = _suggestion([8000], [3000, 2500])
    pool = [_asset("unpriced", 0), _asset("token", MIN_RELEVANT_VALUE - 1)]
    balancers, _side, residuals = _find_balancers(suggestion, pool, set(), set())
    assert balancers == []
    assert residuals == []


def test_small_gaps_need_no_balancer():
    suggestion = _suggestion([6100], [6000])
    balancers, side, residuals = _find_balancers(suggestion, _pool(), set(), set())
    assert (balancers, side, residuals) == ([], "", [])


def test_cap_is_respected():
    suggestion = _suggestion([9000], [3000, 2000])
    balancers, _side, residuals = _find_balancers(suggestion, _pool(step=25), set(), set())
    assert len(balancers) <= MAX_BALANCERS
    assert len(residuals) == len(balancers)


# ── Mixed asset classes ──────────────────────────────────────────────


def test_idp_and_pick_assets_are_scored_the_same_way():
    """One canonical value per asset — no per-asset-class second board."""

    give = [_asset("Defender", 6800, "LB"), _asset("2027 Round 1", 3100, "PICK")]
    receive = [_asset("Receiver", 8900, "WR")]
    gap = _va_gap([p.display_value for p in give], [p.display_value for p in receive])
    suggestion = TradeSuggestion(
        type="consolidation",
        give=give,
        receive=receive,
        give_total=9900,
        receive_total=8900,
        gap=gap,
        fairness=_fairness_label(gap),
        rationale="",
        why_this_helps="",
        confidence="medium",
        strategy="neutral",
    )
    pool = [
        _asset("Pick 2028 1st", 2600, "PICK"),
        _asset("Edge rusher", 4100, "DL"),
        _asset("Slot WR", 1500, "WR"),
    ]
    balancers, side, residuals = _find_balancers(suggestion, pool, set(), set())
    for balancer, residual in zip(balancers, residuals):
        assert residual == _residual_for(suggestion, balancer.display_value, side)
        assert abs(residual) < abs(gap)
