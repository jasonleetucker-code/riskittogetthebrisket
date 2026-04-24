"""Tests for the Sleeper-derived draft-capital fallback.

We mock the Sleeper HTTP calls so tests run offline."""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from src.api import draft_capital_fallback as dcf


def _stub_fetch_json(responses):
    """Return a patched _fetch_json that reads from a URL→response map."""
    def fake(url):
        for key, resp in responses.items():
            if key in url:
                return resp
        return None
    return fake


def _contract_with_picks():
    return {
        "playersArray": [
            {
                "displayName": "2026 Pick 1.01",
                "rankDerivedValue": 9000,
                "assetClass": "pick",
            },
            {
                "displayName": "2026 Pick 2.05",
                "rankDerivedValue": 4500,
                "assetClass": "pick",
            },
        ]
    }


def test_returns_error_when_sleeper_unreachable(monkeypatch):
    monkeypatch.setattr(dcf, "_fetch_json", lambda _url: None)
    result = dcf.build_sleeper_derived(
        "L1", _contract_with_picks(), current_season=2026, num_teams=12,
    )
    assert result.get("error") == "sleeper_unreachable"


def test_basic_build_returns_expected_shape(monkeypatch):
    responses = {
        "/rosters": [
            {"roster_id": i, "owner_id": str(100 + i)} for i in range(1, 11)
        ],
        "/users": [
            {"user_id": str(100 + i), "display_name": f"Team{i}"} for i in range(1, 11)
        ],
        "/traded_picks": [],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1", _contract_with_picks(), current_season=2026, num_teams=10, draft_rounds=4,
    )
    assert result["source"] == "sleeper_derived"
    assert result["numTeams"] == 10
    assert result["totalBudget"] == 1200
    # 10 teams × 4 rounds × 2 seasons = 80 picks.
    assert len(result["picks"]) == 80
    # Sum of per-pick dollars = total budget.
    total = sum(p["adjustedDollarValue"] for p in result["picks"])
    assert total == 1200
    # Team totals sum to total budget.
    team_total = sum(t["auctionDollars"] for t in result["teamTotals"])
    assert team_total == 1200


def test_traded_pick_updates_ownership(monkeypatch):
    responses = {
        "/rosters": [
            {"roster_id": 1, "owner_id": "u1"},
            {"roster_id": 2, "owner_id": "u2"},
        ],
        "/users": [
            {"user_id": "u1", "display_name": "Alpha"},
            {"user_id": "u2", "display_name": "Beta"},
        ],
        "/traded_picks": [
            # Team 2's 2026 1st (slot 2) now owned by Team 1.
            {
                "season": "2026", "round": 1, "roster_id": 2, "owner_id": 1,
            }
        ],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1", _contract_with_picks(), current_season=2026, num_teams=2, draft_rounds=1,
    )
    # Find the traded pick.
    traded = [p for p in result["picks"] if p["isTraded"]]
    assert len(traded) == 1
    assert traded[0]["currentOwner"] == "Alpha"
    assert traded[0]["originalOwner"] == "Beta"


def test_round_to_budget_sums_exactly(monkeypatch):
    # Non-round-number values that need largest-remainder distribution.
    out = dcf._round_to_budget([1.1, 2.2, 3.3, 4.4, 5.5], target_total=100)  # noqa: SLF001
    assert sum(out) == 100


def test_missing_contract_uses_flat_fallback(monkeypatch):
    """When no pick is found in the canonical contract, _pick_value_from_contract
    falls back to a round-based flat value."""
    responses = {
        "/rosters": [{"roster_id": 1, "owner_id": "u1"}],
        "/users": [{"user_id": "u1", "display_name": "A"}],
        "/traded_picks": [],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1", {}, current_season=2026, num_teams=1, draft_rounds=4,
    )
    # Still produces a valid shape.
    assert result["source"] == "sleeper_derived"
    assert result["totalBudget"] == 1200


def test_pick_value_from_contract_exact_match():
    contract = _contract_with_picks()
    v = dcf._pick_value_from_contract(contract, 2026, 1, 1)  # noqa: SLF001
    assert v == 9000.0


def test_pick_value_from_contract_fallback_monotonic():
    # Empty contract — round 1 should be larger than round 4.
    v1 = dcf._pick_value_from_contract({}, 2026, 1, 5)  # noqa: SLF001
    v4 = dcf._pick_value_from_contract({}, 2026, 4, 5)  # noqa: SLF001
    assert v1 > v4
