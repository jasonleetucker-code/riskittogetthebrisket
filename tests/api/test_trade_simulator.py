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


# ── Window fit follows the canonical posture (C7-POST-01) ────────────
#
# ``team_impact._classify_window`` (contendIndex vs a fixed 0.15) was a second,
# hard-threshold posture owner and is retired.  The window fit now scores the
# moving assets against the canonical Competitive Posture, and without one it
# is NOT computed — no posture is guessed.


def _impact(posture_label, receiving, sending):
    return team_impact.compute(
        before_assets=[{"name": "QB1", "pos": "QB", "value": 5000, "age": 27}],
        after_assets=[{"name": "QB1", "pos": "QB", "value": 5000, "age": 27}],
        receiving=receiving,
        sending=sending,
        equity=0,
        roster_settings={"starters": {"QB": 1}},
        canonical_posture={"label": posture_label} if posture_label else None,
    )


_PRIME = {"name": "Prime", "pos": "WR", "value": 4000, "age": 26}
_PICK = {"name": "2027 Round 1", "pos": "PICK", "value": 4000, "assetClass": "pick"}


def test_push_team_window_fit_rewards_receiving_prime_production():
    impact = _impact("PUSH", [_PRIME], [_PICK])
    assert impact["posture"] == "contender" and impact["competitivePosture"] == "PUSH"
    assert impact["windowFit"] > 0


def test_rebuild_and_retool_score_the_future_side():
    for label in ("REBUILD", "RETOOL"):
        impact = _impact(label, [_PICK], [_PRIME])
        assert impact["posture"] == "rebuilder"
        assert impact["windowFit"] > 0


def test_hold_is_balanced():
    impact = _impact("HOLD", [_PRIME], [_PICK])
    assert impact["posture"] == "balanced" and impact["windowFit"] == 0.0


def test_without_a_canonical_posture_window_fit_is_not_computed():
    impact = _impact(None, [_PRIME], [_PICK])
    assert impact["posture"] is None
    assert impact["windowFit"] is None
    assert impact["postureSource"] == "unavailable"


def test_the_retired_hard_threshold_owner_is_gone():
    assert not hasattr(team_impact, "_classify_window")


# ── Final roster simulation: C2-SIM-01 (roster_intel.simulation) composed  ──
# via C3-CAP-01 (roster_capacity.simulate_final_legal_roster) at THIS
# endpoint. Before this, ``/api/trade/simulate`` reported only a forced-drop
# COST estimate via ``rosterCapacity`` and never resolved WHICH player, the
# re-solved lineup, or the Team Strength delta — even though both primitives
# already existed and were independently tested
# (``tests/trade/test_trade_consumes_roster.py``). Fixture mirrors that
# file's ``TINY_ROSTER``/``TINY_SETTINGS`` exactly, so the same forced-drop
# outcome (TE1, the cheapest RB/WR/TE-flex-redundant player) is expected here.

_CAPACITY_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 6,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 1, "FLEX": 1},
}


def _mk_capacity_contract():
    """A 6-man roster already AT a 6-man cap: any incoming player forces a drop."""

    def row(name, value, pos):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": "offense",
            "position": pos,
            "pos": pos,
            "rankDerivedValue": value,
            "values": {"full": value},
        }

    roster = [
        ("QB1", 5000.0, "QB"),
        ("RB1", 4000.0, "RB"),
        ("WR1", 3000.0, "WR"),
        ("RB2", 800.0, "RB"),
        ("WR2", 700.0, "WR"),
        ("TE1", 600.0, "TE"),
    ]
    free_agents = [
        row(f"FA {i}", 200.0 + i, p) for i, p in enumerate(("QB", "RB", "WR", "TE", "RB", "WR"))
    ]
    incoming = [("IN1", 6000.0, "WR")]
    rows = (
        [row(n, v, p) for n, v, p in roster] + free_agents + [row(n, v, p) for n, v, p in incoming]
    )
    team = {
        "ownerId": "o1",
        "name": "Us",
        "roster_id": 1,
        "players": [n for n, _v, _p in roster],
        "playerIds": [n.lower() for n, _v, _p in roster],
        "picks": [],
    }
    opponent = {
        "ownerId": "o2",
        "name": "Them",
        "roster_id": 2,
        "players": [n for n, _v, _p in incoming],
        "playerIds": [n.lower() for n, _v, _p in incoming],
        "picks": [],
    }
    return {"playersArray": rows, "sleeper": {"teams": [team, opponent]}}


def test_final_roster_simulation_names_the_forced_drop():
    contract = _mk_capacity_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["IN1"],
        players_out=[],
        roster_settings=_CAPACITY_SETTINGS,
        league_key=None,
    )
    capacity = result["rosterCapacity"]
    assert capacity["requiresDrops"] is True
    assert capacity["forcedDrops"], "fixture must actually force a drop"

    sim = result["finalRosterSimulation"]
    assert sim["available"] is True
    # The cleanup IS the capacity answer's own forced drops, not a second,
    # independently-chosen selection (mirrors
    # test_trade_consumes_roster.py::test_a_forced_drop_is_never_also_retained).
    capacity_drop_ids = {d["playerId"] for d in capacity["forcedDrops"]}
    cleanup_ids = {d["playerId"] for d in sim["cleanupApplied"]}
    assert cleanup_ids == capacity_drop_ids
    assert cleanup_ids  # non-empty: a real player was named, not a placeholder
    # A re-solved lineup and Team Strength delta, not merely a value delta.
    assert "strengthDelta" in sim
    assert "movements" in sim
    assert sim["isVerdict"] is False


def test_final_roster_simulation_absent_without_resolved_team():
    contract = _mk_capacity_contract()
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=None,
        players_in=["IN1"],
        players_out=[],
        roster_settings=_CAPACITY_SETTINGS,
    )
    # Not null, not {} — genuinely absent, matching rosterCapacity's own
    # absence in the same no-team case.
    assert "finalRosterSimulation" not in result
    assert "rosterCapacity" not in result


def test_final_roster_simulation_clean_fit_reports_empty_cleanup():
    contract = _mk_capacity_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    # 1-for-1: roster size is unchanged, so no forced drop is required.
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["IN1"],
        players_out=["TE1"],
        roster_settings=_CAPACITY_SETTINGS,
        league_key=None,
    )
    assert result["rosterCapacity"]["requiresDrops"] is False
    sim = result["finalRosterSimulation"]
    assert sim["available"] is True
    assert sim["cleanupApplied"] == []


def test_final_roster_simulation_unavailable_when_starter_slots_unresolved():
    contract = _mk_capacity_contract()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    settings_no_starters = {"teamCount": 12, "rosterSize": 6, "taxiSize": 0}
    result = trade_simulator.simulate_trade(
        contract,
        resolved_team=team,
        players_in=["IN1"],
        players_out=[],
        roster_settings=settings_no_starters,
        league_key=None,
    )
    sim = result["finalRosterSimulation"]
    assert sim["available"] is False
    assert sim["unavailableReason"] == "starter_slots_unresolved"
