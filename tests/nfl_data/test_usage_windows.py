"""Tests for rolling-window usage derivatives."""
from __future__ import annotations

from src.nfl_data import usage_windows as uw


def test_single_week_produces_zero_history():
    """First week → mean/SD = 0 and z-scores = None (no history)."""
    stat_rows = [
        {
            "player_id_gsis": "00-1", "season": 2024, "week": 1, "recent_team": "BUF",
            "targets": 10, "carries": 0, "snap_pct": 0.9,
        }
    ]
    windows = uw.build_rolling_windows(stat_rows)
    assert len(windows) == 1
    w = windows[0]
    assert w.snap_pct_mean == 0.0
    assert w.snap_pct_z is None


def test_rolling_mean_tracks_history():
    # Player has 4 weeks of consistent 0.80 snap share, then week 5.
    stat_rows = [
        {"player_id_gsis": "A", "season": 2024, "week": w, "recent_team": "BUF",
         "targets": 10, "snap_pct": 0.80}
        for w in range(1, 5)
    ]
    stat_rows.append({
        "player_id_gsis": "A", "season": 2024, "week": 5, "recent_team": "BUF",
        "targets": 10, "snap_pct": 0.80,
    })
    windows = uw.build_rolling_windows(stat_rows)
    final = [w for w in windows if w.week == 5][0]
    assert abs(final.snap_pct_mean - 0.80) < 0.01


def test_spike_produces_positive_zscore():
    """Player at 0.30 for 4 weeks, then spikes to 0.80 — z should
    be positive and large."""
    rows = []
    for w in range(1, 5):
        rows.append({
            "player_id_gsis": "A", "season": 2024, "week": w, "recent_team": "BUF",
            "targets": 3, "snap_pct": 0.30,
        })
    rows.append({
        "player_id_gsis": "A", "season": 2024, "week": 5, "recent_team": "BUF",
        "targets": 10, "snap_pct": 0.80,
    })
    windows = uw.build_rolling_windows(rows)
    final = [w for w in windows if w.week == 5][0]
    # With exactly-equal history, SD is 0 → z is None.  So insert a
    # small variance and re-check.
    rows[0]["snap_pct"] = 0.32
    rows[1]["snap_pct"] = 0.28
    rows[2]["snap_pct"] = 0.30
    rows[3]["snap_pct"] = 0.30
    windows2 = uw.build_rolling_windows(rows)
    final2 = [w for w in windows2 if w.week == 5][0]
    assert final2.snap_pct_z is not None
    assert final2.snap_pct_z > 0


def test_target_share_normalizes_by_team_total():
    """Share math: my_targets / team_total.  Two players on the
    same team-week split correctly."""
    rows = [
        {"player_id_gsis": "A", "season": 2024, "week": 1, "recent_team": "BUF",
         "targets": 7, "snap_pct": 0.9},
        {"player_id_gsis": "B", "season": 2024, "week": 1, "recent_team": "BUF",
         "targets": 3, "snap_pct": 0.8},
    ]
    # Build windows — at week 1 there's no history, so mean_share=0,
    # but the internal computation uses team totals correctly.
    windows = uw.build_rolling_windows(rows)
    # Extend for week 2 to push last-week share into history.
    rows.append({"player_id_gsis": "A", "season": 2024, "week": 2, "recent_team": "BUF",
                 "targets": 5, "snap_pct": 0.9})
    rows.append({"player_id_gsis": "B", "season": 2024, "week": 2, "recent_team": "BUF",
                 "targets": 5, "snap_pct": 0.8})
    windows = uw.build_rolling_windows(rows)
    week2_A = [w for w in windows if w.player_id == "A" and w.week == 2][0]
    # Week 1: A had 7/10 = 0.7 share
    assert abs(week2_A.target_share_mean - 0.7) < 0.01


def test_latest_window_per_player():
    rows = [
        {"player_id_gsis": "A", "season": 2024, "week": 1, "recent_team": "BUF",
         "targets": 1, "snap_pct": 0.5},
        {"player_id_gsis": "A", "season": 2024, "week": 2, "recent_team": "BUF",
         "targets": 2, "snap_pct": 0.6},
        {"player_id_gsis": "B", "season": 2024, "week": 1, "recent_team": "BUF",
         "targets": 3, "snap_pct": 0.7},
    ]
    windows = uw.build_rolling_windows(rows)
    latest = uw.latest_window_per_player(windows)
    assert latest["A"].week == 2
    assert latest["B"].week == 1


def test_malformed_rows_dont_crash():
    rows = [None, {}, "garbage", {"player_id_gsis": ""}]
    windows = uw.build_rolling_windows(rows)
    assert windows == []
