"""Tests for the ``/api/trade/simulate`` helper."""
from __future__ import annotations

import pytest

from src.api import trade_simulator, terminal
from src.canonical.player_valuation import rank_to_value


def _mk_contract() -> dict:
    """A tiny contract with 4 players on 2 teams.  Values derived
    from ``rank_to_value`` so the simulator can operate on real
    Hill-curve numbers.
    """
    def row(name, rank, pos="WR", asset="offense"):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": asset,
            "position": pos,
            "pos": pos,
            "canonicalConsensusRank": rank,
            "rankChange": 0,
            "rankDerivedValue": int(rank_to_value(rank)),
            "values": {"full": int(rank_to_value(rank))},
        }
    return {
        "playersArray": [
            row("Alice", 5, "QB"),
            row("Bob", 20, "WR"),
            row("Carlo", 45, "RB"),
            row("Diana", 90, "TE"),
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "o1",
                    "name": "Team Alpha",
                    "roster_id": 1,
                    "players": ["Alice", "Bob"],
                    "picks": [],
                },
                {
                    "ownerId": "o2",
                    "name": "Team Bravo",
                    "roster_id": 2,
                    "players": ["Carlo", "Diana"],
                    "picks": [],
                },
            ],
        },
    }


def test_simulate_empty_trade_equity_zero():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    result = trade_simulator.simulate_trade(
        contract, resolved_team=team,
        players_in=[], players_out=[],
    )
    assert result["equity"] == 0
    assert result["before"]["totalValue"] == result["after"]["totalValue"]
    assert result["delta"]["totalValue"] == 0


def test_simulate_straight_swap():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    # Alice(QB rank 5) OUT for Diana(TE rank 90) IN — big value loss.
    result = trade_simulator.simulate_trade(
        contract, resolved_team=team,
        players_in=["Diana"], players_out=["Alice"],
    )
    assert len(result["receiving"]) == 1
    assert len(result["sending"]) == 1
    expected_equity = int(rank_to_value(90)) - int(rank_to_value(5))
    assert result["equity"] == expected_equity
    assert result["delta"]["totalValue"] == expected_equity
    # After the swap, QB count should be 0 and TE should be 1.
    assert result["after"]["byPosition"]["QB"]["count"] == 0
    assert result["after"]["byPosition"]["TE"]["count"] == 1


def test_simulate_two_for_one_net_positive():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    # Sending Alice + Bob, receiving Diana only — equity is negative.
    result = trade_simulator.simulate_trade(
        contract, resolved_team=team,
        players_in=["Diana"],
        players_out=["Alice", "Bob"],
    )
    expected_equity = int(rank_to_value(90)) - int(rank_to_value(5)) - int(rank_to_value(20))
    assert result["equity"] == expected_equity
    assert result["delta"]["totalValue"] == expected_equity
    # Bench got shorter (2 players out, 1 in).
    total_count_before = sum(
        result["before"]["byPosition"][g]["count"] for g in result["before"]["byPosition"]
    )
    total_count_after = sum(
        result["after"]["byPosition"][g]["count"] for g in result["after"]["byPosition"]
    )
    assert total_count_after == total_count_before - 1


def test_simulate_unresolved_names_surfaced():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    result = trade_simulator.simulate_trade(
        contract, resolved_team=team,
        players_in=["Totally Fake Person"],
        players_out=["Alice"],
    )
    assert result["unresolvedIn"] == ["Totally Fake Person"]
    assert result["unresolvedOut"] == []
    # Unresolved receiving side doesn't add value, but sending
    # side still removes it — equity is a net loss.
    expected_equity = -int(rank_to_value(5))
    assert result["equity"] == expected_equity


def test_simulate_dedupes_when_outbound_player_not_on_roster():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    # Trying to trade Carlo (on Team Bravo, not Alpha) OUT shouldn't
    # crash; the simulator treats it as "removed if present".
    result = trade_simulator.simulate_trade(
        contract, resolved_team=team,
        players_in=["Diana"],
        players_out=["Carlo"],
    )
    # Before state still only has Alice + Bob.
    assert result["before"]["totalValue"] == int(rank_to_value(5)) + int(rank_to_value(20))
    # After: Alice, Bob, Diana all present (Carlo was never on the
    # team, so the "OUT" was a no-op).
    assert result["after"]["totalValue"] == (
        int(rank_to_value(5)) + int(rank_to_value(20)) + int(rank_to_value(90))
    )


def test_simulate_no_team_returns_empty_before():
    contract = _mk_contract()
    result = trade_simulator.simulate_trade(
        contract, resolved_team=None,
        players_in=["Alice"], players_out=[],
    )
    assert result["team"] is None
    assert result["before"]["totalValue"] == 0
    assert result["after"]["totalValue"] == int(rank_to_value(5))
