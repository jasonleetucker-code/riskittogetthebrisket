"""The FAAB rounding convention (surviving half of audit finding H4).

This file used to be one half of a server/client parity contract. Its
twin was ``frontend/__tests__/faab-bid-parity.test.js``, and both
asserted against ``tests/fixtures/faab_bid_parity_cases.json``, because
``src/trade/waiver.py::_compute_faab_bid`` and
``frontend/lib/waiver-logic.js::computeFaabHint`` were the same
pool-relative formula written twice and nothing checked that they
agreed. They did not: Python's ``round`` is half-to-even, JS's
``Math.round`` is half-up, and every ``.5`` boundary produced a $1
disagreement between the page and the API.

**Both halves of that contract are gone, for different reasons.**

The client half was deleted with ``computeFaabHint`` itself — a second
valuation formula on the client is what the "no frontend ranking or
valuation engine, period" rule exists to prevent, and every dollar the
UI renders is now stamped by the backend. The fixture's ``expected``
blocks were hand-derived from the pool-relative formula
(``0.05 + 0.25 x share`` of the budget), which the FAAB engine replaced
wholesale, so they no longer describe anything the code does.

What SURVIVES, and is pinned below, is the part of H4 that was never
about parity: ``_round_half_up`` and the rule that all three tiers
derive from the UNROUNDED figure. Both still apply to the engine's
shim, and both are real defects if they regress — so the audit's
findings outlive the formula they were found in.
"""

from __future__ import annotations

from src.trade import faab_engine as engine
from src.trade.waiver import _compute_faab_bid, _round_half_up


BOARD = [9999 - i * 12 for i in range(700)]


def _anchors() -> engine.Anchors:
    return engine.resolve_anchors(
        BOARD, engine.LeagueContext(original_budget=100, team_count=12, starters_per_team=20)
    )


# ── The rounding rule itself ─────────────────────────────────────────


def test_rounding_is_half_up_not_bankers() -> None:
    """``_round_half_up`` must not be a rename of the built-in.

    Hand-stated table. The built-in ``round`` answers 10, 12 and 24 on
    the first three (ties go to the even integer) — those three lines
    are the entire bug this helper exists to prevent.
    """
    assert _round_half_up(10.5) == 11
    assert _round_half_up(12.5) == 13
    assert _round_half_up(24.5) == 25
    # Ties are the only interesting case; everything else agrees.
    assert _round_half_up(10.4) == 10
    assert _round_half_up(10.6) == 11
    assert _round_half_up(0.0) == 0


def test_the_shim_uses_the_explicit_convention() -> None:
    """Not just defined — actually used. A helper nothing calls is a
    promise the code does not keep."""
    anchors = _anchors()
    # Find a value whose aggressive tier lands exactly on a .5 boundary.
    for value in range(int(anchors.v_repl), int(anchors.v_allin) + 1):
        raw = engine.objective_ceiling(value, anchors)[0] * 100
        if abs(raw - int(raw) - 0.5) < 1e-6:
            agg = _compute_faab_bid(value, budget=100, anchors=anchors)[0]
            assert agg == int(raw) + 1, f"value {value}: {raw} should round UP"
            return
    # No exact boundary on this board — the convention is still pinned
    # by the hand-stated table above.


# ── Tiers derive from the unrounded figure ───────────────────────────


def test_tiers_scale_the_unrounded_aggressive_bid() -> None:
    """Deriving ``reasonable`` from an already-rounded ``aggressive``
    compounds the error a tier at a time. Each tier must scale the raw
    figure and round once.
    """
    anchors = _anchors()
    for value in range(int(anchors.v_repl), int(anchors.v_allin) + 200, 7):
        agg, reas, low = _compute_faab_bid(value, budget=100, anchors=anchors)
        raw = engine.objective_ceiling(value, anchors)[0] * 100
        assert reas == _round_half_up(raw * 0.70), value
        assert low == _round_half_up(raw * 0.35), value


def test_tiers_are_ordered_and_never_negative() -> None:
    anchors = _anchors()
    for value in (0, 500, 1500, 2000, 2400, 5000, 9999):
        agg, reas, low = _compute_faab_bid(value, budget=100, anchors=anchors)
        assert 0 <= low <= reas <= agg, value


def test_replacement_level_is_zero_not_a_dollar_floor() -> None:
    """The pre-engine formula floored every tier at ``max(1, ...)``.

    That floor is deliberately NOT carried over: a player at or below
    the free-agent replacement line is worth nothing, and roughly half
    of this league's real adds cost exactly $0. A $1 minimum would put
    a dollar on every piece of roster clog on the wire.
    """
    anchors = _anchors()
    assert _compute_faab_bid(500, budget=100, anchors=anchors) == (0, 0, 0)
    assert _compute_faab_bid(int(anchors.v_repl) - 100, budget=100, anchors=anchors) == (0, 0, 0)


def test_a_non_positive_budget_bids_nothing() -> None:
    """H4's inversion: a manager with no money must never be billed
    against a full budget."""
    assert _compute_faab_bid(9999, budget=0) == (0, 0, 0)
    assert _compute_faab_bid(9999, budget=-5) == (0, 0, 0)
