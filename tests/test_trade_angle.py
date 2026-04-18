"""Unit tests for src.trade.angle.find_angles."""
from __future__ import annotations

import pytest

from src.trade.angle import find_angles


def _player(name, my_val, ktc_val, *, position="QB"):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_val,
        "canonicalSiteValues": {"ktc": ktc_val},
    }


def _teams():
    return [
        {
            "name": "Team A",
            "ownerId": "owner-a",
            "players": ["Jayden Daniels", "Waiver QB A"],
        },
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": ["Trade Target Good", "Trade Target Overpriced"],
        },
        {
            "name": "Team C",
            "ownerId": "owner-c",
            "players": ["Trade Target Gold", "Waiver QB C"],
        },
    ]


def test_finds_candidate_when_my_gain_and_ktc_is_fair():
    players = [
        _player("Jayden Daniels", my_val=5000, ktc_val=5000),
        _player("Trade Target Good", my_val=6000, ktc_val=5000),  # +20% my, 0% KTC — ideal pitch
        _player("Trade Target Overpriced", my_val=6000, ktc_val=6500),  # KTC too high
    ]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    names = [c["name"] for c in result["candidates"]]
    assert "Trade Target Good" in names
    assert "Trade Target Overpriced" not in names


def test_excludes_same_team_players():
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("Waiver QB A", 7000, 4000),  # same team — should be filtered
        _player("Trade Target Good", 6000, 5000),
    ]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    names = [c["name"] for c in result["candidates"]]
    assert "Waiver QB A" not in names


def test_sorts_by_arb_score_desc():
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("Trade Target Good", 6000, 5100),   # +20% / +2% => arb 18
        _player("Trade Target Gold", 7500, 4800),   # +50% / -4% => arb 54
    ]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    names = [c["name"] for c in result["candidates"]]
    assert names[0] == "Trade Target Gold"
    assert names[1] == "Trade Target Good"


def test_respects_min_my_gain_threshold():
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("Trade Target Good", 5100, 4900),  # only +2% my gain
    ]
    result = find_angles(
        players, "Jayden Daniels", "owner-a", _teams(), min_my_gain_pct=10.0,
    )
    assert result["candidates"] == []


def test_respects_max_ktc_gain_threshold():
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("Trade Target Good", 6000, 5600),  # +20% my, +12% KTC
    ]
    # Default max is 5%; 12% KTC gap too much.
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    names = [c["name"] for c in result["candidates"]]
    assert "Trade Target Good" not in names
    # Raise the ceiling and it should now qualify.
    result2 = find_angles(
        players,
        "Jayden Daniels",
        "owner-a",
        _teams(),
        max_ktc_gain_pct=20.0,
    )
    names2 = [c["name"] for c in result2["candidates"]]
    assert "Trade Target Good" in names2


def test_missing_selected_player_returns_warning():
    players = [_player("Someone Else", 5000, 5000)]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    assert result["selected"] is None
    assert result["candidates"] == []
    assert result["warnings"]


def test_selected_missing_ktc_value_returns_warning():
    players = [
        {
            "canonicalName": "Jayden Daniels",
            "displayName": "Jayden Daniels",
            "position": "QB",
            "rankDerivedValue": 5000,
            "canonicalSiteValues": {},  # no KTC
        },
    ]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    assert result["candidates"] == []
    assert any("KTC" in w for w in result["warnings"])


def test_limit_caps_results():
    players = [_player("Jayden Daniels", 5000, 5000)]
    # Build Team B with lots of qualifying targets so we can verify the cap.
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": [f"Target {i}" for i in range(30)],
        },
    ]
    for i in range(30):
        players.append(_player(f"Target {i}", 6000 + i, 5000))
    result = find_angles(players, "Jayden Daniels", "owner-a", teams, limit=5)
    assert len(result["candidates"]) == 5
