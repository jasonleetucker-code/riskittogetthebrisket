"""Tests for the ``/api/trade/simulate`` helper."""

from __future__ import annotations


from src.api import trade_simulator, terminal
from src.trade import team_impact
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
        contract,
        resolved_team=team,
        players_in=[],
        players_out=[],
    )
    assert result["equity"] == 0
    assert result["before"]["totalValue"] == result["after"]["totalValue"]
    assert result["delta"]["totalValue"] == 0


def test_simulate_straight_swap():
    contract = _mk_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    # Alice(QB rank 5) OUT for Diana(TE rank 90) IN — big value loss.
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["Diana"],
        players_out=["Alice"],
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
        contract,
        resolved_team=team,
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
        contract,
        resolved_team=team,
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
        contract,
        resolved_team=team,
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
        contract,
        resolved_team=None,
        players_in=["Alice"],
        players_out=[],
    )
    assert result["team"] is None
    assert result["before"]["totalValue"] == 0
    assert result["after"]["totalValue"] == int(rank_to_value(5))


# ── Team-aware impact analyzer ─────────────────────────────────────────

_IDP_LEAGUE_SETTINGS = {
    "teamCount": 12,
    "starters": {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 1,
        "FLEX": 2,
        "SFLEX": 1,
        "DL": 2,
        "LB": 2,
        "DB": 2,
        "IDP_FLEX": 2,
    },
    "flexEligible": ["RB", "WR", "TE"],
    "sflexEligible": ["QB", "RB", "WR", "TE"],
    "idpFlexEligible": ["DL", "LB", "DB"],
}

_NON_IDP_LEAGUE_SETTINGS = {
    "teamCount": 10,
    "starters": {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 1,
        "FLEX": 2,
        "SFLEX": 1,
    },
    "flexEligible": ["RB", "WR", "TE"],
    "sflexEligible": ["QB", "RB", "WR", "TE"],
}


def _mk_full_roster_contract():
    """Roster with realistic depth/holes for fit-score tests."""

    def row(name, rank, pos, age=27, asset="offense"):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": asset,
            "position": pos,
            "pos": pos,
            "age": age,
            "canonicalConsensusRank": rank,
            "rankChange": 0,
            "rankDerivedValue": int(rank_to_value(rank)),
            "values": {"full": int(rank_to_value(rank))},
        }

    rows = [
        row("StarQB", 5, "QB", age=27),
        row("StarQB2", 12, "QB", age=26),
        row("RB1", 18, "RB", age=25),
        row("RB2", 35, "RB", age=24),
        row("RB3", 70, "RB", age=23),
        row("WR1", 8, "WR", age=24),
        row("WR2", 22, "WR", age=26),
        row("WR3", 48, "WR", age=27),
        row("TE1", 60, "TE", age=28),
        row("FreeWR", 30, "WR", age=24),
        row("FreeWR2", 33, "WR", age=25),
        row("FreeRB", 40, "RB", age=23),
        row("Pick26", 50, "PICK", age=None, asset="pick"),
    ]
    return {
        "playersArray": rows,
        "sleeper": {
            "teams": [
                {
                    "ownerId": "u1",
                    "name": "User",
                    "roster_id": 1,
                    "players": [
                        "StarQB",
                        "StarQB2",
                        "RB1",
                        "RB2",
                        "RB3",
                        "WR1",
                        "WR2",
                        "WR3",
                        "TE1",
                    ],
                    "picks": [],
                }
            ],
        },
    }


def test_team_impact_absent_without_roster_settings():
    contract = _mk_full_roster_contract()
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["FreeWR"],
        players_out=["TE1"],
    )
    assert "teamImpact" not in result


def test_team_impact_absent_without_resolved_team():
    contract = _mk_full_roster_contract()
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=None,
        players_in=["FreeWR"],
        players_out=["TE1"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    assert "teamImpact" not in result


def test_team_impact_filling_starter_hole_positive_fit():
    """Acquiring a starting-quality TE when team has only one
    weak TE should produce positive fitScore."""
    contract = _mk_full_roster_contract()
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    # Add a strong TE to acquire.  Inject directly.
    contract["playersArray"].append(
        {
            "displayName": "EliteTE",
            "canonicalName": "EliteTE",
            "assetClass": "offense",
            "position": "TE",
            "pos": "TE",
            "age": 25,
            "canonicalConsensusRank": 15,
            "rankChange": 0,
            "rankDerivedValue": int(rank_to_value(15)),
            "values": {"full": int(rank_to_value(15))},
        }
    )
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["EliteTE"],
        players_out=["FreeWR"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    impact = result["teamImpact"]
    assert impact["fitScore"] > 0
    assert impact["starterValueDelta"]["TE"] > 0


def test_team_impact_duplicating_saturated_position_negative():
    """Acquiring a 4th startable RB onto a 3-RB roster + saturated FLEX
    should flag redundancy and depress fitScore."""
    contract = _mk_full_roster_contract()
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["FreeRB"],
        players_out=["TE1"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    impact = result["teamImpact"]
    # TE went from 1 to 0 starters (lost a starter); RB total went up
    # but team was already at the FLEX cap.
    assert impact["starterDelta"]["TE"] < 0


def test_team_impact_redundancy_skipped_in_non_idp_league():
    """Acquiring an IDP player in a non-IDP league must not generate
    redundancy flags or starterDelta entries for DL/LB/DB."""
    contract = _mk_full_roster_contract()
    contract["playersArray"].append(
        {
            "displayName": "IDPGuy",
            "canonicalName": "IDPGuy",
            "assetClass": "idp",
            "position": "LB",
            "pos": "LB",
            "age": 25,
            "canonicalConsensusRank": 80,
            "rankChange": 0,
            "rankDerivedValue": int(rank_to_value(80)),
            "values": {"full": int(rank_to_value(80))},
        }
    )
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["IDPGuy"],
        players_out=["FreeWR"],
        roster_settings=_NON_IDP_LEAGUE_SETTINGS,
    )
    impact = result["teamImpact"]
    assert "LB" not in impact["starterDelta"]
    assert "DL" not in impact["starterDelta"]
    assert "DB" not in impact["starterDelta"]
    assert all(r["pos"] != "LB" for r in impact["redundancy"])


def test_team_impact_verdict_thresholds_cross_correctly():
    """Verdict ladders as compositeScore moves."""
    contract = _mk_full_roster_contract()
    contract["playersArray"].append(
        {
            "displayName": "EliteTE",
            "canonicalName": "EliteTE",
            "assetClass": "offense",
            "position": "TE",
            "pos": "TE",
            "age": 25,
            "canonicalConsensusRank": 8,
            "rankChange": 0,
            "rankDerivedValue": int(rank_to_value(8)),
            "values": {"full": int(rank_to_value(8))},
        }
    )
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["EliteTE"],
        players_out=["FreeRB"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    impact = result["teamImpact"]
    assert impact["verdict"] in {"accept", "lean accept", "neutral", "lean decline", "decline"}
    assert -100 <= impact["fitScore"] <= 100
    assert -100 <= impact["equityScore"] <= 100
    assert -100 <= impact["compositeScore"] <= 100


def test_team_impact_idp_trade_in_idp_league_seen():
    """Codex P1 regression: terminal._normalize_pos collapses DL/LB/DB
    to ``IDP``, so team_impact must read from ``basePos`` (preserved
    DL/LB/DB) — otherwise IDP trades are invisible to the analyzer.
    """
    contract = _mk_full_roster_contract()
    contract["playersArray"].extend(
        [
            # Roster gets two starting LBs + two starting DLs already.
            {
                "displayName": "MyLB1",
                "canonicalName": "MyLB1",
                "assetClass": "idp",
                "position": "LB",
                "pos": "LB",
                "age": 25,
                "canonicalConsensusRank": 80,
                "rankChange": 0,
                "rankDerivedValue": int(rank_to_value(80)),
                "values": {"full": int(rank_to_value(80))},
            },
            {
                "displayName": "MyLB2",
                "canonicalName": "MyLB2",
                "assetClass": "idp",
                "position": "LB",
                "pos": "LB",
                "age": 26,
                "canonicalConsensusRank": 95,
                "rankChange": 0,
                "rankDerivedValue": int(rank_to_value(95)),
                "values": {"full": int(rank_to_value(95))},
            },
            # Trade target — an elite LB upgrade.
            {
                "displayName": "EliteLB",
                "canonicalName": "EliteLB",
                "assetClass": "idp",
                "position": "LB",
                "pos": "LB",
                "age": 25,
                "canonicalConsensusRank": 25,
                "rankChange": 0,
                "rankDerivedValue": int(rank_to_value(25)),
                "values": {"full": int(rank_to_value(25))},
            },
        ]
    )
    # Add the LBs to the roster.
    contract["sleeper"]["teams"][0]["players"].extend(["MyLB1", "MyLB2"])
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["EliteLB"],
        players_out=["MyLB2"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    impact = result["teamImpact"]
    # LB must appear in starterDelta — the trade swaps the team's
    # weaker LB for an elite one, so starter VALUE at LB should rise.
    assert "LB" in impact["starterValueDelta"]
    assert impact["starterValueDelta"]["LB"] > 0


def test_team_impact_rationale_bullets_max_five():
    contract = _mk_full_roster_contract()
    team = terminal.resolve_team(contract, owner_id="u1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["FreeWR2"],
        players_out=["WR3"],
        roster_settings=_IDP_LEAGUE_SETTINGS,
    )
    assert len(result["teamImpact"]["rationale"]) <= 5


# ── Window classification (src/trade/team_impact.py::_classify_window) ──
#
# Regression pins for the math audit's H5(c).  ``contendIndex`` used to
# read ``top10_share − (pick_share + young_share)`` with the top-10
# slice taken over EVERY asset, so pick and young value landed on both
# sides of the subtraction and cancelled: the most extreme rebuilder in
# the league came out "balanced".  The positive term is now the top 10
# WIN-NOW assets only.
#
# Shares below are hand-computed; the threshold is ±0.15.

_WINDOW_CFG = {"windowFit": {"contendIndexThreshold": 0.15, "youngStarterMaxAge": 23}}


def _pick(value: int) -> dict:
    return {"name": f"pick-{value}", "assetClass": "pick", "value": value}


def _player_asset(name: str, value: int, age: int) -> dict:
    return {"name": name, "assetClass": "offense", "pos": "WR", "value": value, "age": age}


def test_classify_window_pick_stuffed_roster_is_a_rebuilder():
    """Ten firsts + five spare parts is the archetypal rebuild.

    total = 10 × 1000 (picks) + 5 × 200 (vets) = 11,000.
    win-now top 10 = the five vets = 1,000 → 0.0909
    pick share      = 10,000 / 11,000        → 0.9091
    index = 0.0909 − 0.9091 = −0.818 → rebuilder.

    Counting the picks in the top-10 slice too gave 0.909 − 0.909 = 0.0,
    i.e. "balanced", and the whole window-fit leg of the trade verdict
    then graded this roster as if it should be buying veterans.
    """
    assets = [_pick(1000) for _ in range(10)]
    assets += [_player_asset(f"Vet{i}", 200, 28) for i in range(5)]
    assert team_impact._classify_window(assets, _WINDOW_CFG) == "rebuilder"


def test_classify_window_young_core_is_a_rebuilder():
    """Same double-count, other half of the negative term.

    total = 10 × 1000 (age 22) + 2 × 500 (age 28) = 11,000.
    win-now top 10 = the two vets = 1,000 → 0.0909
    young share    = 10,000 / 11,000       → 0.9091
    index = −0.818 → rebuilder (it read 0.0 → "balanced").
    """
    assets = [_player_asset(f"Kid{i}", 1000, 22) for i in range(10)]
    assets += [_player_asset(f"Vet{i}", 500, 28) for i in range(2)]
    assert team_impact._classify_window(assets, _WINDOW_CFG) == "rebuilder"


def test_classify_window_veteran_roster_is_still_a_contender():
    """No picks, no kids: index = 1.0 − 0.0.  Unchanged by the fix."""
    assets = [_player_asset(f"Vet{i}", 1000, 27) for i in range(10)]
    assert team_impact._classify_window(assets, _WINDOW_CFG) == "contender"


def test_classify_window_mixed_roster_is_balanced():
    """An even split between win-now and future sits in the band.

    total = 5 × 1000 (age 27) + 5 × 1000 (picks) = 10,000.
    win-now top 10 = 5,000 → 0.5; pick share = 0.5.
    index = 0.0, inside ±0.15 → balanced.
    """
    assets = [_player_asset(f"Vet{i}", 1000, 27) for i in range(5)]
    assets += [_pick(1000) for _ in range(5)]
    assert team_impact._classify_window(assets, _WINDOW_CFG) == "balanced"
