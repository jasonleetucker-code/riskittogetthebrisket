"""Unit tests for src.trade.angle.find_angles / find_angle_packages."""
from __future__ import annotations

import pytest

from src.trade.angle import (
    _value_adjustment,
    find_acquisition_packages,
    find_angle_packages,
    find_angles,
)


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


def test_respects_max_market_gain_threshold():
    players = [
        _player("Jayden Daniels", 5000, 5000),
        _player("Trade Target Good", 6000, 5600),  # +20% my, +12% market
    ]
    # Default max is 5%; 12% gap too much.
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    names = [c["name"] for c in result["candidates"]]
    assert "Trade Target Good" not in names
    # Raise the ceiling and it should now qualify.
    result2 = find_angles(
        players,
        "Jayden Daniels",
        "owner-a",
        _teams(),
        max_market_gain_pct=20.0,
    )
    names2 = [c["name"] for c in result2["candidates"]]
    assert "Trade Target Good" in names2


def test_missing_selected_player_returns_warning():
    players = [_player("Someone Else", 5000, 5000)]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    assert result["selected"] is None
    assert result["candidates"] == []
    assert result["warnings"]


def test_selected_missing_market_value_returns_warning():
    players = [
        {
            "canonicalName": "Jayden Daniels",
            "displayName": "Jayden Daniels",
            "position": "QB",
            "rankDerivedValue": 5000,
            "canonicalSiteValues": {},  # no market value
        },
    ]
    result = find_angles(players, "Jayden Daniels", "owner-a", _teams())
    assert result["candidates"] == []
    # Warning mentions the market source that's missing (ktc for QB).
    assert any("ktc" in w for w in result["warnings"])


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


def test_packages_filters_on_market_gap_threshold():
    offer = ["Jayden Daniels", "CeeDee Lamb"]
    # Default max_market_gain_pct = 5. Every candidate must satisfy
    # the market gap constraint vs the offer's market total (which
    # for this all-offense offer happens to equal the KTC total).
    result = find_angle_packages(
        _pkg_players(), offer, "owner-a", _pkg_teams(),
    )
    offer_market = 10000
    for c in result["candidates"]:
        assert (c["market_total"] - offer_market) / offer_market * 100.0 <= 5.001


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
    assert result["offer"]["market_total"] == 10000
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


# ── Per-position market source ─────────────────────────────────────


def _player_with_markets(name, my_val, ktc, idptc, *, position="QB"):
    """Build a row carrying BOTH site values so the helper can pick."""
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_val,
        "canonicalSiteValues": {"ktc": ktc, "idpTradeCalc": idptc},
    }


def test_idp_players_compared_on_idptc_not_ktc():
    """An IDP counter is accepted/rejected based on IDPTC, not KTC —
    even if KTC would place it out of range."""
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My DL"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["Better DL"]},
    ]
    # Offer: My DL with IDPTC 5000. Target: Better DL with IDPTC
    # 5100 (+2% — fair on IDPTC) but KTC 7000 (+40% — way over on
    # KTC). The per-position rule should compare on IDPTC and
    # accept.
    players = [
        _player_with_markets("My DL", my_val=5000, ktc=5000, idptc=5000, position="DL"),
        _player_with_markets(
            "Better DL", my_val=6000, ktc=7000, idptc=5100, position="DL",
        ),
    ]
    result = find_angles(
        players, "My DL", "owner-a", teams,
        min_my_gain_pct=5.0, max_market_gain_pct=5.0,
    )
    names = [c["name"] for c in result["candidates"]]
    assert "Better DL" in names, (
        "IDP counter should qualify on IDPTC (+2%) despite bad KTC (+40%) "
        f"— got candidates {names}"
    )
    # And the market source stamped on the row reflects IDPTC.
    cand = next(c for c in result["candidates"] if c["name"] == "Better DL")
    assert cand["market_source"] == "idpTradeCalc"


def test_offense_players_still_compared_on_ktc():
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["Other QB"]},
    ]
    # Offense trade — should compare on KTC, not IDPTC. IDPTC fair
    # (+1%) but KTC bad (+30%) → should reject.
    players = [
        _player_with_markets("My QB", my_val=5000, ktc=5000, idptc=5000, position="QB"),
        _player_with_markets(
            "Other QB", my_val=6000, ktc=6500, idptc=5050, position="QB",
        ),
    ]
    result = find_angles(
        players, "My QB", "owner-a", teams,
        min_my_gain_pct=5.0, max_market_gain_pct=5.0,
    )
    names = [c["name"] for c in result["candidates"]]
    assert "Other QB" not in names
    # Raising the ceiling admits it.
    result2 = find_angles(
        players, "My QB", "owner-a", teams,
        min_my_gain_pct=5.0, max_market_gain_pct=40.0,
    )
    cand = next(c for c in result2["candidates"] if c["name"] == "Other QB")
    assert cand["market_source"] == "ktc"


# ─── find_acquisition_packages ───────────────────────────────────────


def _acq_teams():
    return [
        {
            "name": "Team A",
            "ownerId": "owner-a",
            "players": ["My QB1", "My WR1", "My WR2", "My Bench"],
        },
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": ["Target Star", "B Filler"],
        },
        {
            "name": "Team C",
            "ownerId": "owner-c",
            "players": ["Target Gold"],
        },
    ]


def _acq_players():
    return [
        # My roster: a couple of good offerables + deep bench.
        _player("My QB1", my_val=5500, ktc_val=5200),
        _player("My WR1", my_val=4800, ktc_val=4900),
        _player("My WR2", my_val=4500, ktc_val=4600),
        _player("My Bench", my_val=200, ktc_val=200),
        # Acquisition targets on other teams.
        _player("Target Star", my_val=6500, ktc_val=5200),  # nice arb
        _player("B Filler", my_val=300, ktc_val=300),
        _player("Target Gold", my_val=9000, ktc_val=8500),
    ]


def test_acquire_returns_offer_packages_from_user_roster():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
    )
    assert result["acquire"]["size"] == 1
    # Every candidate player must come from the user's roster.
    own_roster = {"My QB1", "My WR1", "My WR2", "My Bench"}
    for c in result["candidates"]:
        names = {p["name"] for p in c["players"]}
        assert names <= own_roster, f"candidate leaks non-own players: {names}"


def test_acquire_candidate_sizes_within_plus_minus_one():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star", "B Filler"], "owner-a", _acq_teams(),
    )
    # Desired N=2 → sizes {1,2,3}
    assert set(result["thresholds"]["target_sizes"]) == {1, 2, 3}
    for c in result["candidates"]:
        assert c["size"] in {1, 2, 3}


def test_acquire_my_gain_threshold_enforced():
    # Desired my_val = 6500. Lone offer "My QB1" has my_val 5500 →
    # (6500-5500)/5500 = 18.2% my-gain. With min_my_gain_pct=25, no
    # single-player combo qualifies and only multi-player combos that
    # under-shoot enough on my-value remain.
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
        min_my_gain_pct=25.0,
    )
    for c in result["candidates"]:
        assert c["my_gain_pct"] >= 25.0 - 1e-6


def test_acquire_market_gap_threshold_enforced():
    # Target Star KTC=5200. My QB1 KTC=5200 → gap 0%. With
    # max_market_gain_pct=2, the single-player My QB1 offer is the
    # tightest fit.
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
        min_my_gain_pct=5.0, max_market_gain_pct=2.0,
    )
    assert result["candidates"], "expected at least one qualifying offer"
    for c in result["candidates"]:
        assert c["market_gain_pct"] <= 2.0 + 1e-6


def test_acquire_rejects_own_roster_targets_with_warning():
    # "My QB1" is on owner-a's roster — can't "acquire" from yourself.
    result = find_acquisition_packages(
        _acq_players(), ["My QB1"], "owner-a", _acq_teams(),
    )
    assert result["acquire"]["size"] == 0
    assert result["candidates"] == []
    assert any("already on your roster" in w for w in result["warnings"])


def test_acquire_unknown_targets_dropped_with_warning():
    result = find_acquisition_packages(
        _acq_players(), ["Ghost Player", "Target Star"], "owner-a", _acq_teams(),
    )
    assert result["acquire"]["size"] == 1
    assert any("Ghost Player" in w for w in result["warnings"])


def test_acquire_sorts_by_arb_score_desc():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
    )
    scores = [c["arb_score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_acquire_target_team_list_in_response():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star", "Target Gold"], "owner-a", _acq_teams(),
    )
    owner_ids = {t["owner_id"] for t in result["acquire"]["targets"]}
    assert owner_ids == {"owner-b", "owner-c"}


def test_acquire_unknown_owner_returns_warning():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-missing", _acq_teams(),
    )
    assert result["candidates"] == []
    assert any("not found" in w for w in result["warnings"])


def test_acquire_respects_position_filter_on_own_roster():
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
        positions=["WR"],
    )
    for c in result["candidates"]:
        for p in c["players"]:
            assert p["position"] == "WR"


def test_acquire_respects_min_player_value_on_own_roster():
    # With floor 3000, "My Bench" (my_val=200) is excluded.
    result = find_acquisition_packages(
        _acq_players(), ["Target Star"], "owner-a", _acq_teams(),
        min_player_my_value=3000,
    )
    names = {p["name"] for c in result["candidates"] for p in c["players"]}
    assert "My Bench" not in names


def test_acquire_idp_target_compares_on_idptc():
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My DL"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["Target DL"]},
    ]
    # IDPTC: 5000 vs 5100 (1% gap — fair on IDPTC). KTC: 5000 vs 7000
    # (40% gap — would reject). Per-position rule uses IDPTC for DL.
    players = [
        _player_with_markets("My DL", 5000, 5000, 5000, position="DL"),
        _player_with_markets("Target DL", 6000, 7000, 5100, position="DL"),
    ]
    # include_idp must be True — the offer-side "My DL" would
    # otherwise be filtered out of the candidate pool by the default
    # IDP gate.
    result = find_acquisition_packages(
        players, ["Target DL"], "owner-a", teams,
        min_my_gain_pct=5.0, max_market_gain_pct=5.0,
        include_idp=True,
    )
    assert result["candidates"], "IDP acquire should qualify on IDPTC"
    # market source stamped on acquire and candidate rows.
    assert result["acquire"]["players"][0]["market_source"] == "idpTradeCalc"


def test_packages_player_rows_expose_per_position_market_source():
    offer = ["My QB"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {
            "name": "Team B", "ownerId": "owner-b",
            "players": ["IDP Target", "Off Target"],
        },
    ]
    players = [
        _player_with_markets("My QB", 5000, 5000, 5000, position="QB"),
        _player_with_markets("IDP Target", 6000, 7000, 5100, position="DL"),
        _player_with_markets("Off Target", 6000, 5100, 7000, position="WR"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        min_my_gain_pct=5.0, max_market_gain_pct=5.0,
    )
    for c in result["candidates"]:
        for p in c["players"]:
            if p["position"] == "DL":
                assert p["market_source"] == "idpTradeCalc"
                assert p["market_value"] == 5100  # IDPTC value
            elif p["position"] == "WR":
                assert p["market_source"] == "ktc"
                assert p["market_value"] == 5100  # KTC value


# ─── Value Adjustment (consolidation premium) ────────────────────────


def test_value_adjustment_matches_js_calibration_point_case_a():
    """Parity check against the KTC-native algorithm.

    For [9999] vs [7846,5717], KTC.com displays VA = 3712 (captured).
    Both the JS port (frontend/lib/trade-logic.js::ktcAdjustPackage)
    and this Python port (src/trade/ktc_va.py) reproduce KTC's number
    exactly.  Pre-2026-04-27 the angle module used a V2 regression
    fit that returned 3748 here; now :func:`_value_adjustment` thin-
    wraps the native algorithm.
    """
    va = _value_adjustment([9999], [7846, 5717])
    assert round(va) == 3712


def test_value_adjustment_zero_when_sides_truly_equal():
    # KTC's actual algorithm fires VA on equal-count trades whenever
    # one side has a stud advantage.  Equal piece counts alone do NOT
    # suppress (V2's behavior was wrong on this).  Suppression only
    # fires when totals AND raw_adj are both within KTC's 5% variance
    # threshold AND the algorithm's display gates trigger — easiest
    # way to construct that is identical sides.
    assert _value_adjustment([8000, 7000], [8000, 7000]) == 0.0
    assert _value_adjustment([8000, 7000], [7900, 7100]) == 0.0


def test_value_adjustment_positive_for_smaller_side_with_top_gap():
    # 1v2 with a clear top-piece gap: small tops at 9999, large tops
    # at 7846. Smaller side receives a positive VA.
    va = _value_adjustment([9999], [7846, 5717])
    assert va > 0.0


def test_value_adjustment_grows_with_top_gap():
    # A bigger gap between the consolidated star and the best piece
    # on the longer side should produce a larger VA.
    low_gap = _value_adjustment([8000], [7500, 5000])
    high_gap = _value_adjustment([9999], [6000, 4000])
    assert high_gap > low_gap


def test_packages_consolidation_trade_is_filtered_by_va():
    """Classic "4 filler for 1 stud" trade: raw totals match, but VA
    should make the single stud side bigger under the adjusted math,
    pushing the counterparty's perceived market gap past the cap."""
    # Offer: 1 stud. Counter: 4 filler pieces whose KTC sum lines up
    # with the stud but no single piece is close to the stud's value.
    offer = ["Stud Star"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["Stud Star"]},
        {
            "name": "Team B",
            "ownerId": "owner-b",
            "players": ["Filler 1", "Filler 2", "Filler 3", "Filler 4"],
        },
    ]
    # Stud: my=9500, ktc=9500.  Four fillers each ≈ 2400 → sum ≈ 9600.
    # Raw math would accept this as +1% my-gain, +1% ktc-gap (both
    # within threshold). VA on the consolidated side should flip the
    # market gap past the 5% cap.
    players = [
        _player("Stud Star", 9500, 9500),
        _player("Filler 1", 2400, 2400),
        _player("Filler 2", 2400, 2400),
        _player("Filler 3", 2400, 2400),
        _player("Filler 4", 2400, 2400),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        min_my_gain_pct=0.0, max_market_gain_pct=5.0,
    )
    # Under raw arithmetic the 4-filler counter is within both
    # thresholds. With VA applied to the smaller (stud) side, the
    # market gap climbs well past 5% and the package is rejected.
    four_filler = [c for c in result["candidates"] if c["size"] == 4]
    assert four_filler == [], (
        "4-filler counter should be rejected once VA is applied to the "
        f"consolidated stud side; got {four_filler}"
    )


def test_packages_candidate_exposes_va_adjustment_fields():
    """Successful candidates ship the adjusted totals so the UI can
    show consolidation premiums."""
    offer = ["Offer Star", "Offer Depth"]
    teams = [
        {
            "name": "Team A", "ownerId": "owner-a",
            "players": ["Offer Star", "Offer Depth"],
        },
        {"name": "Team B", "ownerId": "owner-b", "players": ["Target Star"]},
    ]
    # 2-for-1 — the single counter piece should receive VA.
    players = [
        _player("Offer Star", 5000, 5000),
        _player("Offer Depth", 3000, 3000),
        _player("Target Star", 9000, 8200),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        # KTC's native algorithm produces a stronger consolidation
        # premium than the V2 regression fit (~50% market gap on this
        # 2-for-1) so the threshold has to be loose enough for the
        # candidate to survive.  100% gives ample headroom while still
        # being a meaningful filter for less-extreme topologies.
        min_my_gain_pct=0.0, max_market_gain_pct=100.0,
    )
    size_one = next((c for c in result["candidates"] if c["size"] == 1), None)
    assert size_one is not None, "expected the single-player counter to qualify"
    assert size_one["my_value_adjustment"] > 0
    assert size_one["market_value_adjustment"] > 0
    assert size_one["my_total_adjusted"] > size_one["my_total"]


# ─── IDP filter default ──────────────────────────────────────────────


def test_packages_idp_excluded_from_pool_by_default():
    offer = ["My QB"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {
            "name": "Team B", "ownerId": "owner-b",
            "players": ["Opp DL", "Opp WR"],
        },
    ]
    players = [
        _player("My QB", 5000, 5000, position="QB"),
        _player("Opp DL", 6000, 5000, position="DL"),
        _player("Opp WR", 6000, 5000, position="WR"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,  # include_idp default False
    )
    names = {p["name"] for c in result["candidates"] for p in c["players"]}
    assert "Opp DL" not in names
    assert "Opp WR" in names


def _idp_player(name, my_val, idptc_val, *, position="DL"):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_val,
        "canonicalSiteValues": {"idpTradeCalc": idptc_val},
    }


def test_packages_idp_included_when_flag_set():
    offer = ["My QB"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["Opp DL"]},
    ]
    players = [
        _player("My QB", 5000, 5000, position="QB"),
        _idp_player("Opp DL", 6000, 5000, position="DL"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams, include_idp=True,
    )
    names = {p["name"] for c in result["candidates"] for p in c["players"]}
    assert "Opp DL" in names


def test_packages_idp_filter_does_not_touch_seed_players():
    """Seed players are user-selected — the IDP gate should let them
    through even when include_idp is False."""
    offer = ["My QB"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {
            "name": "Team B", "ownerId": "owner-b",
            "players": ["Opp Seed DL", "Opp WR"],
        },
    ]
    players = [
        _player("My QB", 5000, 5000, position="QB"),
        _idp_player("Opp Seed DL", 6000, 5000, position="DL"),
        _player("Opp WR", 6000, 5000, position="WR"),
    ]
    result = find_angle_packages(
        players, offer, "owner-a", teams,
        target_team_owner_ids=["owner-b"],
        seed_player_names=["Opp Seed DL"],
    )
    # Every candidate must carry the IDP seed even though include_idp
    # is False and the pool is otherwise IDP-stripped.
    assert result["candidates"]
    for c in result["candidates"]:
        names = {p["name"] for p in c["players"]}
        assert "Opp Seed DL" in names


def test_acquire_idp_excluded_from_offer_pool_by_default():
    """In acquire mode, the default IDP gate strips IDP players from
    the user's own roster pool — so an IDP-only owner ends up with
    zero offers."""
    teams = [
        {
            "name": "Team A", "ownerId": "owner-a",
            "players": ["My LB 1", "My LB 2"],
        },
        {"name": "Team B", "ownerId": "owner-b", "players": ["Target WR"]},
    ]
    players = [
        _idp_player("My LB 1", 5500, 5200, position="LB"),
        _idp_player("My LB 2", 5400, 5100, position="LB"),
        _player("Target WR", 6000, 5000, position="WR"),
    ]
    result = find_acquisition_packages(
        players, ["Target WR"], "owner-a", teams,  # include_idp default False
    )
    assert result["candidates"] == []
    # Flip include_idp on and the offer packages appear.
    result2 = find_acquisition_packages(
        players, ["Target WR"], "owner-a", teams,
        include_idp=True,
    )
    assert result2["candidates"], "LB offers should qualify once IDP is allowed"


def test_acquire_idp_filter_does_not_drop_desired_player():
    """The acquire-side (fixed) set is user-selected — it should
    survive the IDP gate even when include_idp is False."""
    teams = [
        {
            "name": "Team A", "ownerId": "owner-a",
            "players": ["My WR 1", "My WR 2"],
        },
        {"name": "Team B", "ownerId": "owner-b", "players": ["Target DL"]},
    ]
    players = [
        _player("My WR 1", 5500, 5500, position="WR"),
        _player("My WR 2", 5400, 5400, position="WR"),
        _idp_player("Target DL", 6000, 5500, position="DL"),
    ]
    result = find_acquisition_packages(
        players, ["Target DL"], "owner-a", teams,  # default include_idp=False
        min_my_gain_pct=0.0, max_market_gain_pct=50.0,
    )
    # Desired player survives the gate.
    assert result["acquire"]["size"] == 1
    assert result["acquire"]["players"][0]["name"] == "Target DL"
    # And the offer pool (all-WR) can still produce candidates.
    assert result["candidates"]


def test_packages_include_idp_flag_surfaced_in_thresholds():
    offer = ["My QB"]
    teams = [
        {"name": "Team A", "ownerId": "owner-a", "players": ["My QB"]},
        {"name": "Team B", "ownerId": "owner-b", "players": ["Opp WR"]},
    ]
    players = [
        _player("My QB", 5000, 5000, position="QB"),
        _player("Opp WR", 6000, 5000, position="WR"),
    ]
    result_off = find_angle_packages(players, offer, "owner-a", teams)
    assert result_off["thresholds"]["include_idp"] is False
    result_on = find_angle_packages(
        players, offer, "owner-a", teams, include_idp=True,
    )
    assert result_on["thresholds"]["include_idp"] is True
