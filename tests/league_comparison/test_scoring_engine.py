"""Test the per-player season scoring engine."""
from __future__ import annotations

import pytest

from src.league_comparison.scoring_engine import (
    compute_player_season_scores,
    _canonical_position,
)


_PPR = {
    "pass_yd": 0.04, "pass_td": 4, "pass_int": -2,
    "rush_yd": 0.1, "rush_td": 6,
    "rec": 1.0, "rec_yd": 0.1, "rec_td": 6,
    "fum_lost": -2,
}


def _stat(pid: str, pos: str, week: int, **stats):
    return {
        "player_id": pid,
        "player_name": pid.upper(),
        "position": pos,
        "season": 2024,
        "week": week,
        "passing_yards": 0, "passing_tds": 0, "interceptions": 0,
        "rushing_yards": 0, "rushing_tds": 0,
        "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
        "fumbles_lost": 0,
        **stats,
    }


def test_canonical_position_offense_passthrough():
    assert _canonical_position("QB") == "QB"
    assert _canonical_position("RB") == "RB"
    assert _canonical_position("WR") == "WR"
    assert _canonical_position("TE") == "TE"


def test_canonical_position_collapses_idp():
    assert _canonical_position("DE") == "DL"
    assert _canonical_position("EDGE") == "DL"
    assert _canonical_position("OLB") == "LB"
    assert _canonical_position("CB") == "DB"
    assert _canonical_position("FS") == "DB"


def test_canonical_position_filters_unknown():
    assert _canonical_position("K") is None    # kickers excluded
    assert _canonical_position("OL") is None
    assert _canonical_position("") is None
    assert _canonical_position(None) is None


def test_player_aggregates_across_weeks():
    rows = [
        _stat("p1", "QB", 1, passing_yards=300, passing_tds=2, interceptions=0),
        _stat("p1", "QB", 2, passing_yards=200, passing_tds=1),
    ]
    scores = compute_player_season_scores(rows, _PPR)
    assert len(scores) == 1
    s = scores[0]
    assert s.player_id == "p1"
    assert s.position == "QB"
    # week 1: 300*0.04 + 2*4 = 12+8 = 20.  week 2: 200*0.04 + 1*4 = 8+4 = 12
    assert s.total_points == pytest.approx(32.0)
    assert s.games_played == 2


def test_multiple_players_split_correctly():
    rows = [
        _stat("qb1", "QB", 1, passing_yards=400, passing_tds=4),
        _stat("rb1", "RB", 1, rushing_yards=120, rushing_tds=1, receptions=4, receiving_yards=30),
        _stat("wr1", "WR", 1, receptions=8, receiving_yards=110, receiving_tds=1),
    ]
    scores = compute_player_season_scores(rows, _PPR)
    by_pos = {s.position: s for s in scores}
    assert set(by_pos.keys()) == {"QB", "RB", "WR"}
    # QB: 400*0.04 + 4*4 = 32
    assert by_pos["QB"].total_points == pytest.approx(32.0)
    # RB: 120*0.1 + 6 + 4 + 30*0.1 = 12+6+4+3 = 25
    assert by_pos["RB"].total_points == pytest.approx(25.0)
    # WR: 8 + 11 + 6 = 25
    assert by_pos["WR"].total_points == pytest.approx(25.0)


def test_te_premium_only_applies_to_te():
    scoring = {**_PPR, "bonus_rec_te": 0.5}
    rows = [
        _stat("te1", "TE", 1, receptions=6, receiving_yards=70),
        _stat("wr1", "WR", 1, receptions=6, receiving_yards=70),
    ]
    scores = compute_player_season_scores(rows, scoring)
    by_pos = {s.position: s for s in scores}
    # TE: 6 + 7 + 6*0.5 = 6+7+3 = 16
    assert by_pos["TE"].total_points == pytest.approx(16.0)
    # WR: 6 + 7 = 13 (no premium)
    assert by_pos["WR"].total_points == pytest.approx(13.0)


def test_unknown_position_filtered_out():
    rows = [
        _stat("k1", "K", 1, rushing_yards=10),       # kicker — drop
        _stat("ol1", "OL", 1, fumbles_lost=1),       # offensive line — drop
        _stat("qb1", "QB", 1, passing_yards=200),    # keep
    ]
    scores = compute_player_season_scores(rows, _PPR)
    assert {s.player_id for s in scores} == {"qb1"}


def test_missing_scoring_settings_returns_empty():
    rows = [_stat("qb1", "QB", 1, passing_yards=300)]
    assert compute_player_season_scores(rows, {}) == []
    assert compute_player_season_scores(rows, None) == []  # type: ignore[arg-type]


def test_handles_player_id_field_alias():
    """nflverse uses player_id; some fixtures might use player_id_gsis."""
    row = {
        "player_id_gsis": "g1", "player_name": "G1", "position": "RB",
        "season": 2024, "week": 1,
        "rushing_yards": 100, "rushing_tds": 1,
    }
    scores = compute_player_season_scores([row], _PPR)
    assert len(scores) == 1
    assert scores[0].player_id == "g1"
