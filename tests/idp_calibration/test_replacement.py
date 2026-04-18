from __future__ import annotations

from src.idp_calibration.lineup import parse_lineup
from src.idp_calibration.replacement import (
    ReplacementSettings,
    compute_replacement_levels,
)

LEAGUE = {
    "league_id": "L",
    "season": 2024,
    "total_rosters": 12,
    "roster_positions": [
        "QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
        "DL", "DL", "LB", "LB", "LB", "DB", "DB",
        "IDP_FLEX",
        "BN", "BN", "BN", "BN",
    ],
}


def _scored(points):
    return [{"position": "DL", "points": p} for p in points]


def test_strict_starter_mode_uses_exact_demand():
    demand = parse_lineup(LEAGUE)
    settings = ReplacementSettings(mode="strict_starter", buffer_pct=0.5)
    # 2 DL + 1 IDP_FLEX/3 = 2.33, * 12 teams ≈ 28
    pts = list(range(40, 0, -1))
    levels = compute_replacement_levels(_scored(pts), demand, settings)
    assert levels["DL"].replacement_rank == 28
    # Replacement rank 28 => points[27]
    assert levels["DL"].replacement_points == pts[27]


def test_buffer_mode_adds_team_count_fraction():
    demand = parse_lineup(LEAGUE)
    settings = ReplacementSettings(mode="starter_plus_buffer", buffer_pct=0.25)
    pts = list(range(50, 0, -1))
    levels = compute_replacement_levels(_scored(pts), demand, settings)
    # Base 28 + ceil(12 * 0.25) = 28 + 3 = 31
    assert levels["DL"].replacement_rank == 31


def test_manual_mode_overrides_with_explicit_rank():
    demand = parse_lineup(LEAGUE)
    settings = ReplacementSettings(mode="manual", manual={"DL": 10})
    pts = list(range(20, 0, -1))
    levels = compute_replacement_levels(_scored(pts), demand, settings)
    assert levels["DL"].replacement_rank == 10
    assert levels["DL"].replacement_points == pts[9]


def test_non_integer_demand_ceils_instead_of_rounding_down():
    league = dict(LEAGUE)
    league["total_rosters"] = 10  # 10 * 2.33 = 23.33 -> 24 after ceil
    demand = parse_lineup(league)
    settings = ReplacementSettings(mode="strict_starter")
    pts = list(range(40, 0, -1))
    levels = compute_replacement_levels(_scored(pts), demand, settings)
    # Previously this path used round() which would have produced 23 and
    # picked too-strong a replacement. Ceil keeps us honest.
    assert levels["DL"].replacement_rank == 24


def test_shortfall_falls_back_to_last_player_with_note():
    demand = parse_lineup(LEAGUE)
    settings = ReplacementSettings(mode="manual", manual={"DL": 99})
    pts = [10.0, 7.0, 3.0]
    levels = compute_replacement_levels(_scored(pts), demand, settings)
    assert levels["DL"].replacement_rank == 99
    assert levels["DL"].replacement_points == 3.0
    assert "exceeds cohort size" in levels["DL"].note
