"""Unit tests for src.trade.angle.find_angles / find_angle_packages."""
from __future__ import annotations

import pytest

from src.trade.angle import find_angle_packages, find_angles


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


# ─── find_angle_packages ─────────────────────────────────────────────


def _pkg_teams():
    return [
        {
            "name": "Team A",
            "ownerId": "owner-a",
            "players": ["Jayden Daniels", "CeeDee Lamb", "Bench Guy"],
        },
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": [
                "B Star",
                "B Mid 1",
                "B Mid 2",
                "B Filler",
            ],
        },
        {
            "name": "Team C",
            "ownerId": "owner-c",
            "players": ["C Overpriced", "C Filler 1", "C Filler 2"],
        },
    ]


def _pkg_players():
    return [
        _player("Jayden Daniels", my_val=5000, ktc_val=5000),
        _player("CeeDee Lamb", my_val=5000, ktc_val=5000),
        _player("Bench Guy", my_val=200, ktc_val=200),
        # Team B: B Star is great, Mids are good. A 2-star package
        # (Star + Mid1) should beat the Daniels + Lamb offer.
        _player("B Star", my_val=6000, ktc_val=5100),
        _player("B Mid 1", my_val=5500, ktc_val=4900),
        _player("B Mid 2", my_val=5400, ktc_val=4800),
        _player("B Filler", my_val=100, ktc_val=100),
        # Team C: only overpriced targets on KTC — should be filtered.
        _player("C Overpriced", my_val=6500, ktc_val=7500),
        _player("C Filler 1", my_val=200, ktc_val=200),
        _player("C Filler 2", my_val=100, ktc_val=100),
    ]


def test_packages_returns_counter_offers_sized_within_plus_minus_one():
    offer = ["Jayden Daniels", "CeeDee Lamb"]  # N = 2
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    # Target sizes must be {1, 2, 3} — no 4 or higher.
    target_sizes = set(result["thresholds"]["target_sizes"])
    assert target_sizes == {1, 2, 3}
    for c in result["candidates"]:
        assert c["size"] in target_sizes


def test_packages_offer_of_one_allows_sizes_one_and_two():
    offer = ["Jayden Daniels"]  # N = 1 — size 0 collapses to 1
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    assert set(result["thresholds"]["target_sizes"]) == {1, 2}


def test_packages_excludes_same_team_players_from_candidates():
    offer = ["Jayden Daniels"]
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    owners = {c["owner_id"] for c in result["candidates"]}
    assert "owner-a" not in owners  # never trade with yourself


def test_packages_filters_on_ktc_gap_threshold():
    offer = ["Jayden Daniels", "CeeDee Lamb"]
    # Default max_ktc_gain_pct = 5. Team B's Star+Mid1 is KTC 10000
    # (fair). Team C's Overpriced is KTC 7500 alone which is -25%
    # versus offer's 10000 ktc — passes; good single-player counter.
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    # Every candidate satisfies KTC gap constraint.
    offer_ktc = 10000
    for c in result["candidates"]:
        assert (c["ktc_total"] - offer_ktc) / offer_ktc * 100.0 <= 5.001


def test_packages_sorts_by_arb_score_desc():
    offer = ["Jayden Daniels", "CeeDee Lamb"]
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    scores = [c["arb_score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_packages_offer_totals_are_correct():
    offer = ["Jayden Daniels", "CeeDee Lamb"]
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    assert result["offer"]["my_total"] == 10000
    assert result["offer"]["ktc_total"] == 10000
    assert result["offer"]["size"] == 2


def test_packages_unknown_offer_players_dropped_with_warning():
    result = find_angle_packages(
        _pkg_players(),
        ["Jayden Daniels", "Ghost Player"],
        "owner-a",
        _pkg_teams(),
    )
    assert result["offer"]["size"] == 1
    assert any("Ghost Player" in w for w in result["warnings"])


def test_packages_empty_offer_returns_empty_result():
    result = find_angle_packages(_pkg_players(), [], "owner-a", _pkg_teams())
    assert result["candidates"] == []
    assert result["offer"]["size"] == 0
