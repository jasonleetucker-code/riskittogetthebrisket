"""Tests for realized fantasy points math.  These pin the scoring
rules we actually implement — they're the source of truth for
the 'value vs realized' feature in the upgraded player popup."""
from __future__ import annotations

from src.nfl_data import realized_points as rp


def _half_ppr():
    return {
        "pass_yd": 0.04, "pass_td": 4, "pass_int": -2,
        "rush_yd": 0.1, "rush_td": 6,
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6,
        "fum_lost": -2,
    }


def _ppr():
    return {**_half_ppr(), "rec": 1.0}


def _te_premium():
    return {**_ppr(), "bonus_rec_te": 0.5}


def test_no_stats_returns_none():
    out = rp.compute_weekly_points(None, _ppr())
    assert out is None


def test_no_scoring_settings_returns_zero_with_reason():
    out = rp.compute_weekly_points({"season": 2025, "week": 1}, None)
    assert out is not None
    assert out.fantasy_points == 0.0


def test_passing_qb_ppr_math():
    # 250 yards, 2 TDs, 1 INT → 250*0.04 + 2*4 + -2*1 = 10 + 8 - 2 = 16
    stat = {
        "season": 2025, "week": 1, "position": "QB",
        "passing_yards": 250, "passing_tds": 2, "interceptions": 1,
    }
    out = rp.compute_weekly_points(stat, _ppr())
    assert out is not None
    assert round(out.fantasy_points, 2) == 16.00


def test_rb_receiving_ppr_math():
    # 80 rush yds (8) + 1 rush TD (6) + 3 rec (3) + 30 rec yds (3) = 20
    stat = {
        "season": 2025, "week": 1, "position": "RB",
        "rushing_yards": 80, "rushing_tds": 1, "receptions": 3,
        "receiving_yards": 30,
    }
    out = rp.compute_weekly_points(stat, _ppr())
    assert round(out.fantasy_points, 2) == 20.00


def test_half_ppr_scales_rec_but_not_other():
    stat = {
        "season": 2025, "week": 1, "position": "RB",
        "receptions": 4, "receiving_yards": 40,
    }
    ppr_out = rp.compute_weekly_points(stat, _ppr())
    half_out = rp.compute_weekly_points(stat, _half_ppr())
    # PPR: 4*1.0 + 40*0.1 = 8.0
    # Half: 4*0.5 + 40*0.1 = 6.0
    assert round(ppr_out.fantasy_points, 2) == 8.0
    assert round(half_out.fantasy_points, 2) == 6.0


def test_te_premium_only_applies_to_tes():
    stat_te = {"season": 2025, "week": 1, "position": "TE", "receptions": 6}
    stat_wr = {"season": 2025, "week": 1, "position": "WR", "receptions": 6}
    te_out = rp.compute_weekly_points(stat_te, _te_premium(), position="TE")
    wr_out = rp.compute_weekly_points(stat_wr, _te_premium(), position="WR")
    # TE: 6*1.0 + 6*0.5 (te bonus) = 9
    # WR: 6*1.0 only = 6
    assert round(te_out.fantasy_points, 2) == 9.0
    assert round(wr_out.fantasy_points, 2) == 6.0


def test_threshold_bonus_applies_once():
    stat = {
        "season": 2025, "week": 1, "position": "QB",
        "passing_yards": 350, "passing_tds": 2,
    }
    scoring = {**_ppr(), "bonus_pass_yd_300": 3, "bonus_pass_yd_400": 5}
    out = rp.compute_weekly_points(stat, scoring)
    # base: 350*0.04 + 2*4 = 14 + 8 = 22. +3 for 300 bonus. 400 doesn't fire.
    assert round(out.fantasy_points, 2) == 25.0


def test_breakdown_structure():
    stat = {"season": 2025, "week": 1, "position": "RB", "rushing_yards": 100, "rushing_tds": 1}
    scoring = {"rush_yd": 0.1, "rush_td": 6, "bonus_rush_yd_100": 3}
    out = rp.compute_weekly_points(stat, scoring)
    assert out.fantasy_points == 10 + 6 + 3
    labels = [b[0] for b in out.breakdown]
    assert "Rush Yds" in labels
    assert "Rush TD" in labels
    assert "100+ Rush" in labels


def test_negative_scoring_counts_correctly():
    stat = {"season": 2025, "week": 1, "position": "QB", "interceptions": 3, "fumbles_lost": 2}
    out = rp.compute_weekly_points(stat, _ppr())
    # 3 INT * -2 + 2 FL * -2 = -10
    assert out.fantasy_points == -10.0


def test_cumulative_aggregates_across_weeks():
    rows = [
        {"season": 2025, "week": 1, "position": "WR", "receptions": 5, "receiving_yards": 50},
        {"season": 2025, "week": 2, "position": "WR", "receptions": 7, "receiving_yards": 100},
    ]
    out = rp.compute_cumulative_points(rows, _ppr())
    assert out["weekCount"] == 2
    # week1: 5 + 5 = 10; week2: 7 + 10 = 17; total 27
    assert round(out["totalPoints"], 2) == 27.0
    assert out["bestWeek"]["week"] == 2
    assert out["worstWeek"]["week"] == 1
    assert round(out["averagePoints"], 2) == 13.5


def test_cumulative_empty_returns_zeros():
    out = rp.compute_cumulative_points([], _ppr())
    assert out["weekCount"] == 0
    assert out["totalPoints"] == 0.0
    assert out["bestWeek"] is None


def test_value_vs_realized_delta():
    got = rp.value_vs_realized_delta(12.0, 60.0, 4)  # avg 15
    assert got["realized"] == 15.0
    assert got["expected"] == 12.0
    assert got["delta"] == 3.0
    assert got["deltaPct"] == 25.0


def test_value_vs_realized_handles_no_expected():
    got = rp.value_vs_realized_delta(None, 60.0, 4)
    assert got["expected"] is None
    assert got["delta"] is None


def test_rounding_stable_across_dict_serialization():
    """RealizedPoints.to_dict must not expose long floats from the
    simple multiplication — UI consumers expect 2 decimals."""
    stat = {"season": 2025, "week": 1, "position": "QB", "passing_yards": 333}
    out = rp.compute_weekly_points(stat, _ppr())
    d = out.to_dict()
    # Reproducible rounding, not something like 13.320000000000002.
    assert d["fantasyPoints"] == 13.32
