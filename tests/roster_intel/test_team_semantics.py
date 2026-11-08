"""Team-semantics census guards (owner directive 2026-11-08, Priority 15).

Two things are pinned here:

1. Backend classifiers that sound alike but measure different concepts must
   name their concept, and the ones that claim the SAME concept must not
   contradict (PUSH vs a seller stance, REBUILD vs a buyer stance).
2. Any field claiming total asset equity is player + pick, and an unknown
   pick is reported rather than valued at 0.

Record: ``docs/roster_intel/TEAM_SEMANTICS_2026-11-08.md``.
"""

from __future__ import annotations

import pytest

from src.api import rank_history, terminal
from src.bdvm import roster as bdvm_roster
from src.ros import direction as ros_direction
from src.ros import trade_deadline
from src.roster_intel.team_equity import (
    PICKS_COMPLETE,
    PICKS_PARTIAL,
    PICKS_UNAVAILABLE,
    decompose_team_equity,
)
from tests.roster_intel.team_semantics_fixture import census_table, family

# -- 1. classifiers ------------------------------------------------------

PINNED_POSTURE = {
    "t01": "PUSH",
    "t02": "PUSH",
    "t03": "PUSH",
    "t04": "PUSH",
    "t05": "PUSH",
    "t06": "PUSH",
    "t07": "RETOOL",
    "t08": "HOLD",
    "t09": "RETOOL",
    "t10": "REBUILD",
    "t11": "RETOOL",
    "t12": "REBUILD",
}


def test_pinned_census_posture_labels():
    got = {r["owner"]: r["posture"] for r in census_table()}
    assert got == PINNED_POSTURE


def test_census_agreement_is_measured_not_assumed():
    """3 of 12 teams get one direction family from all four classifiers.

    The nine disagreements are DIFFERENT CONCEPTS (horizon mix vs odds vs
    presentation tier), not nine bugs; pinning the count makes a change in any
    classifier's behaviour visible instead of silent.
    """
    rows = census_table()
    assert sum(1 for r in rows if r["agree"]) == 3


def test_odds_based_classifiers_never_flatly_contradict():
    """Posture, the deadline stance and the contender tier all read odds."""
    for r in census_table():
        pf, df = family(r["posture"]), family(r["deadlineDirection"])
        assert {pf, df} != {"contend", "rebuild"}, r
        tf = family(r["contenderTier"])
        assert {pf, tf} != {"contend", "rebuild"}, r


def test_non_canonical_direction_classifiers_name_their_concept():
    assert ros_direction.CONCEPT == "deadline_buy_sell_stance"
    assert bdvm_roster.DIRECTION_CONCEPT == "fundamental_horizon_mix"
    assert ros_direction.CONCEPT != "competitive_posture"
    assert bdvm_roster.DIRECTION_CONCEPT != "competitive_posture"


def test_public_deadline_section_stamps_its_concept(monkeypatch):
    from src.ros import team_strength

    monkeypatch.setattr(trade_deadline, "build_team_directions", lambda **_: [])
    monkeypatch.setattr(
        trade_deadline, "simulation_availability", lambda *_a, **_k: {"playoff": "missing"}
    )
    monkeypatch.setattr(team_strength, "resolve_snapshot_league_key", lambda _s: None)
    assert trade_deadline.build_section(object())["concept"] == "deadline_buy_sell_stance"


def test_posture_vocabulary_is_owned_by_window_only():
    """PUSH/HOLD/RETOOL/REBUILD are defined once (roster_intel.window)."""
    import src.roster_intel.window as window

    assert tuple(window.POSTURE_LABELS) == ("PUSH", "HOLD", "RETOOL", "REBUILD")
    for mod in (ros_direction, bdvm_roster):
        assert not hasattr(mod, "POSTURE_LABELS")
    labels = {r["bdvmDirection"] for r in census_table()}
    assert labels <= {"contend", "retool", "rebuild"}  # distinct (lowercase) vocabulary


# -- 2. equity -----------------------------------------------------------

ROWS = {
    "2027 Round 1": {
        "assetClass": "pick",
        "canonicalName": "2027 Round 1",
        "rankDerivedValue": 3000,
    },
    "2027 Round 2": {
        "assetClass": "pick",
        "canonicalName": "2027 Round 2",
        "rankDerivedValue": 1000,
    },
}


def _pick(rnd, label=None):
    return {
        "assetId": f"pick:dynasty_main:2027:r{rnd}:o3",
        "slot": None,
        "label": label or f"2027 Round {rnd}",
        "season": 2027,
        "round": rnd,
    }


def _team(*picks, **kw):
    return {"pickOwnershipState": "observed", "pickDetails": list(picks), **kw}


def test_player_plus_pick_equals_total():
    out = decompose_team_equity(
        player_value=10_000,
        team=_team(_pick(1), _pick(2)),
        pick_rows_by_name=ROWS,
        current_draft_year=2026,
    )
    assert out["pickValueState"] == PICKS_COMPLETE
    assert out["pickValue"] == 4000
    assert out["totalAssetValue"] == out["playerValue"] + out["pickValue"] == 14_000


def test_unpriced_pick_is_reported_never_zero_in_a_claimed_total():
    out = decompose_team_equity(
        player_value=10_000,
        team=_team(_pick(1), _pick(3)),
        pick_rows_by_name=ROWS,
        current_draft_year=2026,
    )
    assert out["pickValueState"] == PICKS_PARTIAL
    assert out["unpricedPickCount"] == 1 and out["pricedPickCount"] == 1
    assert out["pickValue"] is None and out["totalAssetValue"] is None
    assert out["totalAssetValueLowerBound"] == 13_000  # labelled bound, not a total


def test_unobserved_pick_ownership_is_unknown_not_zero():
    out = decompose_team_equity(
        player_value=10_000,
        team={
            "pickOwnershipState": "unavailable",
            "pickOwnershipReason": "traded_picks_fetch_failed",
            "pickDetails": None,
        },
        pick_rows_by_name=ROWS,
        current_draft_year=2026,
    )
    assert out["pickValueState"] == PICKS_UNAVAILABLE
    assert out["pickValue"] is None and out["totalAssetValue"] is None
    assert out["pickValueReason"] == "traded_picks_fetch_failed"


def test_observed_empty_inventory_is_a_real_zero():
    out = decompose_team_equity(
        player_value=500, team=_team(), pick_rows_by_name=ROWS, current_draft_year=2026
    )
    assert out["pickValue"] == 0 and out["totalAssetValue"] == 500


def test_unknown_draft_year_never_prices_picks():
    out = decompose_team_equity(
        player_value=500, team=_team(_pick(1)), pick_rows_by_name=ROWS, current_draft_year=None
    )
    assert out["pickValue"] is None and out["totalAssetValue"] is None


def _contract(team):
    return {
        "date": "2026-11-08",
        "currentDraftYear": 2026,
        "playersArray": [
            {
                "displayName": "Alice",
                "canonicalName": "Alice",
                "assetClass": "offense",
                "position": "QB",
                "pos": "QB",
                "canonicalConsensusRank": 1,
                "rankDerivedValue": 7000,
            },
            *ROWS.values(),
        ],
        "sleeper": {"teams": [team]},
    }


@pytest.mark.parametrize("picks,expected_total", [((_pick(1), _pick(2)), 11_000), ((), 7000)])
def test_terminal_total_equity_is_player_plus_pick(tmp_path, monkeypatch, picks, expected_total):
    monkeypatch.setattr(rank_history, "HISTORY_PATH", tmp_path / "none.jsonl")
    team = _team(*picks, ownerId="o1", name="T", players=["Alice"], roster_id=1)
    payload = terminal.build_terminal_payload(_contract(team), resolved_team=team, window_days=30)
    agg = payload["teamAggregates"]
    assert agg["valueScope"] == "players_only"  # totalValue names what it is
    assert agg["totalValue"] == 7000  # unchanged for existing consumers
    eq = agg["equity"]
    assert eq["totalAssetValue"] == expected_total
    assert eq["totalAssetValue"] == eq["playerValue"] + eq["pickValue"]
    assert payload["portfolio"]["equity"] == eq


def test_terminal_unknown_picks_are_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(rank_history, "HISTORY_PATH", tmp_path / "none.jsonl")
    team = {
        "ownerId": "o1",
        "name": "T",
        "players": ["Alice"],
        "roster_id": 1,
        "pickOwnershipState": "unavailable",
        "pickOwnershipReason": "traded_picks_fetch_failed",
        "pickDetails": None,
    }
    payload = terminal.build_terminal_payload(_contract(team), resolved_team=team, window_days=30)
    eq = payload["teamAggregates"]["equity"]
    assert eq["pickValue"] is None and eq["totalAssetValue"] is None
    assert eq["totalAssetValueLowerBound"] == 7000
