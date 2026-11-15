"""T-NEW-02 / #1415 — repeated trade assets are never collapsed server-side.

The trade calculator now sends one payload item per COPY of a repeatable
market-reference pick ("2027 Mid 1st" x2), and an owned league pick by its
ownership label ("2027 Mid 1st (from Team Bravo)").  These tests pin that
the backend owners the calculator consumes count every copy:

* ``src.trade.ktc_va`` / ``suggestions._va_gap`` — the Python Value
  Adjustment agrees with the JS owner (``frontend/lib/trade-logic.js``) on
  packages built from REPEATED values.  The expected numbers are the JS
  owner's outputs, pinned on the JS side by
  ``frontend/__tests__/trade-asset-quantity.test.js`` ("VA parity with
  repeated values"), so a drift on either side fails one of the two.
* ``src.api.trade_simulator.simulate_trade`` (``/api/trade/simulate`` and
  ``/api/trade/analyze``) — repeated inbound copies are all received, and
  trading one of two roster picks that share a board row removes exactly
  one.
"""

from __future__ import annotations

import pytest

from src.api import terminal, trade_simulator
from src.trade.ktc_va import ktc_adjust_package
from src.trade.suggestions import _va_gap
from src.valuation_math import package_model

# (side A values, side B values, JS ktcAdjustPackage value, JS side, JS
# adjusted gap under the KTC ROLLBACK model, JS tradeGapAdjusted(A, B)
# under the ACTIVE model) — computed from frontend/lib/trade-logic.js.
# The ACTIVE column is the geometric model (geom_q078_v1, q = 0.78) since
# the owner's 2026-10-17 promotion; the KTC columns pin the retained
# rollback model.
_JS_REPEATED_VALUE_CASES = [
    ([5606, 5606], [9000], 4240, 2, -2028, 979),
    ([5606, 5606, 5606], [9000, 3000], 3339, 2, 1479, 2049),
    ([4000, 4000, 2500], [7000, 3500], 3759, 2, -3759, -1089),
    ([5606], [9000], 0, 0, -3394, -3394),
]


@pytest.mark.parametrize(
    ("side_a", "side_b", "va", "side", "ktc_gap", "gap"),
    _JS_REPEATED_VALUE_CASES,
)
def test_python_va_matches_js_owner_on_repeated_values(side_a, side_b, va, side, ktc_gap, gap):
    # KTC rollback model: the formula port and its adjusted gap.
    result = ktc_adjust_package(side_a, side_b)
    assert result.value == va
    assert result.side == side
    a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(
        side_a, side_b, model_id=package_model.KTC_2026_04
    )
    assert int(round(a_adj - b_adj)) == ktc_gap
    # ACTIVE model: the consumer gap every surface reads.
    assert _va_gap(side_a, side_b) == gap


def test_every_copy_moves_the_gap():
    """Two copies are not one: the second copy changes the adjusted gap."""
    assert _va_gap([5606, 5606], [9000]) != _va_gap([5606], [9000])


PICK_VALUE = 5606


def _contract() -> dict:
    def row(name, value, pos, asset):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": asset,
            "position": pos,
            "pos": pos,
            "canonicalConsensusRank": 40,
            "rankChange": 0,
            "rankDerivedValue": value,
            "values": {"full": value},
        }

    return {
        "playersArray": [
            row("Alice", 8000, "QB", "offense"),
            row("Carlo", 6000, "RB", "offense"),
            row("2027 Mid 1st", PICK_VALUE, "PICK", "pick"),
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "o1",
                    "name": "Team Alpha",
                    "roster_id": 1,
                    "players": ["Alice"],
                    # Two DISTINCT owned picks that share one board row.
                    "picks": ["2027 Mid 1st (own)", "2027 Mid 1st (from Team Bravo)"],
                },
                {
                    "ownerId": "o2",
                    "name": "Team Bravo",
                    "roster_id": 2,
                    "players": ["Carlo"],
                    "picks": [],
                },
            ],
        },
    }


def test_repeated_inbound_generic_picks_are_all_received():
    contract = _contract()
    team = terminal.resolve_team(contract, owner_id="o2", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_out=["Carlo"],
        picks_in=["2027 Mid 1st", "2027 Mid 1st"],
    )
    assert [a["name"] for a in result["receiving"]] == ["2027 Mid 1st", "2027 Mid 1st"]
    assert result["equity"] == 2 * PICK_VALUE - 6000
    assert result["after"]["totalValue"] == 2 * PICK_VALUE


def test_trading_one_owned_pick_keeps_the_other():
    contract = _contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    before = trade_simulator.simulate_trade(contract, resolved_team=team)
    assert before["before"]["totalValue"] == 8000 + 2 * PICK_VALUE

    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        picks_out=["2027 Mid 1st (from Team Bravo)"],
    )
    assert len(result["sending"]) == 1
    # Exactly one of the two picks left the roster.
    assert result["after"]["totalValue"] == 8000 + PICK_VALUE
