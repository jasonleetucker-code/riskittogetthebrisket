"""LI-5 P3 replay — capacity ``state`` transitions are reported (review finding F-A).

``scripts/li5_replacement_replay.py`` summarised a forced-drop charge's basis by
``basis.bound`` only.  Under LI-5 ON with forced-drop OFF three charges moved
from ``state: exact`` to ``state: lower_bound`` at 0.0 (team02/2for1,
team08/0for2, team08/3for1) with ``bound`` ``None`` on both sides, so
``boundTransitions`` was ``[]`` and the move was invisible.  The pure
aggregation (``capacity_state_effects``) now also counts ``state`` transitions
and names each changed trade.

Hermetic: synthetic answers for the aggregation; the committed evidence file for
the pin.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import li5_replacement_replay as replay

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "docs/valuation/evidence/li5_p3_replay_2026-10-25/replay.json"


def _answer(
    cost, state, bound=None, *, drops=("p1",), requires=True, waiver_basis=None, reasons=None
):
    basis = {"state": state, "bound": bound, "assumedWaiverBasis": waiver_basis}
    if reasons:
        basis["lowerBoundReasons"] = list(reasons)
    return {
        "capacity": {
            "requiresDrops": requires,
            "forcedDrops": [{"name": n} for n in drops],
        },
        "forcedDropCost": cost,
        "forcedDropCostBasis": basis,
    }


def test_exact_to_lower_bound_is_counted_though_bound_is_unchanged():
    off = {"t/2for1": _answer(1817.0, "exact")}
    on = {
        "t/2for1": _answer(
            0.0, "lower_bound", drops=("p2",), reasons=["unpriced_forced_drops_excluded"]
        )
    }

    out = replay.capacity_state_effects(off, on)

    assert out["boundTransitions"] == []  # the old summary saw nothing
    assert out["stateTransitions"] == {"exact->lower_bound": 1}
    assert out["stateTransitionTrades"] == [
        {
            "trade": "t/2for1",
            "state": "exact->lower_bound",
            "chargeOff": 1817.0,
            "chargeOn": 0.0,
            "lowerBoundReasonsOff": [],
            "lowerBoundReasonsOn": ["unpriced_forced_drops_excluded"],
        }
    ]


def test_same_state_charge_change_and_no_drop_trades_are_not_state_transitions():
    off = {
        "a/0for2": _answer(1817.0, "lower_bound"),  # same state, charge changes
        "b/1for2": _answer(None, "exact", requires=False, drops=()),  # no drops required
        "c/2for1": _answer(10.0, "exact"),  # unchanged
    }
    on = {
        "a/0for2": _answer(1247.0, "lower_bound"),
        "b/1for2": _answer(None, "lower_bound", requires=False, drops=()),
        "c/2for1": _answer(10.0, "exact"),
    }

    out = replay.capacity_state_effects(off, on)

    assert out["stateTransitions"] == {}
    assert out["stateTransitionTrades"] == []
    assert out["tradesRequiringDrops"] == 2
    assert out["chargeChanged"] == 1


def test_transitions_are_counted_per_kind_and_bound_changes_keep_their_own_field():
    off = {
        "a/x": _answer(5.0, "exact"),
        "b/x": _answer(6.0, "exact"),
        "c/x": _answer(7.0, "lower_bound", bound="upper"),
    }
    on = {
        "a/x": _answer(0.0, "lower_bound"),
        "b/x": _answer(0.0, "lower_bound"),
        "c/x": _answer(7.0, "lower_bound", bound="estimate", waiver_basis="li5"),
    }

    out = replay.capacity_state_effects(off, on)

    assert out["stateTransitions"] == {"exact->lower_bound": 2}
    assert out["boundTransitions"] == ["upper->estimate"]
    assert [r["trade"] for r in out["stateTransitionTrades"]] == ["a/x", "b/x"]


def test_committed_evidence_names_the_three_hidden_charges():
    """The regenerated P3 replay carries the three charges the bound-only
    summary hid, in the forced-drop-OFF state only."""
    body = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    cap = body["consumerEffects"]["capacity"]

    assert cap["fds0"]["boundTransitions"] == []
    assert cap["fds0"]["stateTransitions"] == {"exact->lower_bound": 3}
    named = {
        t["trade"]: (t["chargeOff"], t["chargeOn"]) for t in cap["fds0"]["stateTransitionTrades"]
    }
    assert named == {
        "team02/2for1": (1817.0, 0.0),
        "team08/0for2": (1688.0, 0.0),
        "team08/3for1": (1688.0, 0.0),
    }
    assert cap["fds1"]["stateTransitions"] == {}
    assert cap["fds1"]["stateTransitionTrades"] == []
