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


def test_packages_per_team_limit_caps_results_per_team():
    """One opposing team shouldn't fill the results with 50 slight
    variations of the same trade. per_team_limit caps each team's
    contribution before the global limit is applied."""
    # Team A owns the offer. Team B has 10 good players — lots of
    # combinations will qualify. Team C has 1 good player.
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": [f"B {i}" for i in range(10)],
        },
        {
            "name": "Team C",
            "ownerId": "owner-c",
            "players": ["C Star"],
        },
    ]
    players = [_player("Jayden Daniels", my_val=5000, ktc_val=5000)]
    for i in range(10):
        # Each B player is +20% my-value, -0% KTC — all qualify.
        players.append(_player(f"B {i}", my_val=6000 + i * 10, ktc_val=5000))
    players.append(_player("C Star", my_val=6500, ktc_val=5000))

    # Default per_team_limit = 4
    result = find_angle_packages(players, offer, "owner-a", teams)
    # Count how many from each team.
    counts: dict[str, int] = {}
    for c in result["candidates"]:
        counts[c["owner_id"]] = counts.get(c["owner_id"], 0) + 1
    # Team B should be capped at 4 despite having many qualifying
    # combinations. Team C has only 1 player so its size-1 count is 1.
    assert counts.get("owner-b", 0) <= 4
    assert counts.get("owner-c", 0) <= 4


def test_packages_per_team_limit_disabled_by_zero_or_negative():
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": [f"B {i}" for i in range(10)],
        },
    ]
    players = [_player("Jayden Daniels", my_val=5000, ktc_val=5000)]
    for i in range(10):
        players.append(_player(f"B {i}", my_val=6000 + i * 10, ktc_val=5000))
    # per_team_limit=0 disables the cap — lots of Team B candidates.
    result = find_angle_packages(
        players, offer, "owner-a", teams, per_team_limit=0, limit=100,
    )
    team_b_count = sum(1 for c in result["candidates"] if c["owner_id"] == "owner-b")
    assert team_b_count > 4


def test_packages_position_filter_restricts_candidates():
    """When ``positions`` is given, only players at those positions
    can appear in counter-packages."""
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": ["B WR", "B RB", "B TE"],
        },
    ]
    players = [
        _player("Jayden Daniels", my_val=5000, ktc_val=5000, position="QB"),
        _player("B WR", my_val=6000, ktc_val=5000, position="WR"),
        _player("B RB", my_val=6000, ktc_val=5000, position="RB"),
        _player("B TE", my_val=6000, ktc_val=5000, position="TE"),
    ]
    # Only want WRs back.
    result = find_angle_packages(
        players, offer, "owner-a", teams, positions=["WR"],
    )
    pos_seen = {p["position"] for c in result["candidates"] for p in c["players"]}
    assert pos_seen == {"WR"}
    # Empty position filter = any position accepted.
    result2 = find_angle_packages(
        players, offer, "owner-a", teams, positions=[],
    )
    pos_seen2 = {p["position"] for c in result2["candidates"] for p in c["players"]}
    assert pos_seen2 == {"WR", "RB", "TE"}


def test_packages_position_filter_case_insensitive():
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["B WR"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000, position="QB"),
        _player("B WR", 6000, 5000, position="WR"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams, positions=["wr"],
    )
    assert any(p["name"] == "B WR" for c in result["candidates"] for p in c["players"])


def test_packages_min_player_my_value_filters_filler():
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": ["B Star", "B Filler"],
        },
    ]
    players = [
        _player("Jayden Daniels", my_val=5000, ktc_val=5000),
        _player("B Star", my_val=6000, ktc_val=5000),
        _player("B Filler", my_val=500, ktc_val=500),
    ]
    # Default 3000 floor — B Filler's my_value=500 is excluded.
    result = find_angle_packages(
        players, offer, "owner-a", teams, min_player_my_value=3000,
    )
    names = {p["name"] for c in result["candidates"] for p in c["players"]}
    assert "B Filler" not in names
    # Zero floor — Filler can come along.
    result2 = find_angle_packages(
        players, offer, "owner-a", teams, min_player_my_value=0,
    )
    names2 = {p["name"] for c in result2["candidates"] for p in c["players"]}
    assert "B Star" in names2  # at minimum


def test_packages_filters_surfaced_in_thresholds():
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["B WR"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000, position="QB"),
        _player("B WR", 6000, 5000, position="WR"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        positions=["WR", "TE"], min_player_my_value=2500,
    )
    th = result["thresholds"]
    assert th["positions"] == ["TE", "WR"]  # sorted
    assert th["min_player_my_value"] == 2500


def test_packages_target_teams_restrict_candidates():
    """When target_team_owner_ids is non-empty, candidates come only
    from those teams (and the result package carries a combined
    team label)."""
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["B Star"]},
        {"name": "Team C", "ownerId": "owner-c", "players": ["C Star"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("B Star", 6000, 5000),
        _player("C Star", 6000, 5000),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        target_team_owner_ids=["owner-b"],
    )
    # Every candidate has owner_id == "owner-b" (our single target).
    assert all(c["owner_id"] == "owner-b" for c in result["candidates"])
    names = {p["name"] for c in result["candidates"] for p in c["players"]}
    assert "C Star" not in names  # Team C excluded by target filter


def test_packages_seed_player_must_appear_in_every_candidate():
    """Seeded players are required in every counter-package."""
    offer = ["Jayden Daniels", "CeeDee Lamb"]  # N = 2
    teams = [
        {
            "name": "Team A", "ownerId": "owner-a",
            "players": ["Jayden Daniels", "CeeDee Lamb"],
        },
        {
            "name": "Team B", "ownerId": "owner-b",
            "players": ["B Star", "B Mid", "B Bench"],
        },
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("CeeDee Lamb", 5000, 5000),
        _player("B Star", 6500, 5200),    # this is the seed
        _player("B Mid", 5500, 4800),
        _player("B Bench", 4500, 4500),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        target_team_owner_ids=["owner-b"],
        seed_player_names=["B Star"],
    )
    assert result["candidates"], "Expected at least one candidate"
    # Every candidate contains the seed.
    for c in result["candidates"]:
        names = {p["name"] for p in c["players"]}
        assert "B Star" in names


def test_packages_two_target_teams_draw_from_union():
    """With 2 target teams selected, the counter-package candidate
    pool is the union of both teams' top-N players."""
    offer = ["Jayden Daniels", "CeeDee Lamb"]
    teams = [
        {
            "name": "Team A", "ownerId": "owner-a",
            "players": ["Jayden Daniels", "CeeDee Lamb"],
        },
        {"name": "Team B", "ownerId": "owner-b", "players": ["B Star"]},
        {"name": "Team C", "ownerId": "owner-c", "players": ["C Star"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("CeeDee Lamb", 5000, 5000),
        _player("B Star", 6000, 5000),
        _player("C Star", 6000, 5000),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        target_team_owner_ids=["owner-b", "owner-c"],
        seed_player_names=["B Star", "C Star"],
    )
    assert result["candidates"], "Expected 2-player counter with both seeds"
    # Every candidate contains both seeds.
    for c in result["candidates"]:
        names = {p["name"] for p in c["players"]}
        assert "B Star" in names and "C Star" in names
    # Team label reflects multi-team nature.
    assert "+" in result["candidates"][0]["team"]


def test_packages_warning_for_seed_not_on_target_team():
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["B Star"]},
        {"name": "Team C", "ownerId": "owner-c", "players": ["C Star"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("B Star", 6000, 5000),
        _player("C Star", 6000, 5000),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        target_team_owner_ids=["owner-b"],
        seed_player_names=["C Star"],  # not on Team B — should be ignored w/ warning
    )
    assert any("not on any selected target team" in w for w in result["warnings"])


def test_packages_no_targets_uses_existing_per_team_mode():
    """Existing per-team behaviour is preserved when no targets given."""
    offer = ["Jayden Daniels"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Jayden Daniels"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["B Star"]},
        {"name": "Team C", "ownerId": "owner-c", "players": ["C Star"]},
    ]
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("B Star", 6000, 5000),
        _player("C Star", 6000, 5000),
    ]
    result = find_angle_packages(players, offer, "owner-a", teams)
    # Should see packages from both Team B and Team C independently.
    owners = {c["owner_id"] for c in result["candidates"]}
    assert owners == {"owner-b", "owner-c"}
