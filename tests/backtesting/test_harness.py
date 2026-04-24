"""Tests for the backtesting harness."""
from __future__ import annotations

from src.backtesting import harness as bh


def _record(tid, date, a, b, win_a):
    return bh.TradeRecord(
        trade_id=tid, date=date, side_a_names=a,
        side_b_names=b, win_prob_a=win_a,
    )


def test_empty_records_returns_zero_summary():
    s = bh.run_backtest([], {})
    assert s.total == 0
    assert s.correct == 0
    assert s.to_dict()["accuracy"] == 0.0


def test_correct_prediction_increments_both_counts():
    """Calc said A wins (0.65), A's value went up more → correct."""
    snapshots = {
        ("A", "2024-01-01"): 8000, ("B", "2024-01-01"): 7500,
        ("A", "2024-06-29"): 8500, ("B", "2024-06-29"): 7200,
    }
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.65)]
    s = bh.run_backtest(records, snapshots, horizon_days=180)
    assert s.total == 1
    assert s.correct == 1
    # Bucket 0.65-0.70.
    assert s.buckets["0.65-0.70"].correct == 1


def test_wrong_prediction_still_counted():
    """Calc said A wins (0.65), B actually gained more → incorrect."""
    snapshots = {
        ("A", "2024-01-01"): 8000, ("B", "2024-01-01"): 7500,
        ("A", "2024-06-29"): 7000, ("B", "2024-06-29"): 8500,
    }
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.65)]
    s = bh.run_backtest(records, snapshots, horizon_days=180)
    assert s.total == 1
    assert s.correct == 0


def test_missing_snapshots_skip():
    snapshots = {("A", "2024-01-01"): 8000}  # missing B + future dates
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.65)]
    s = bh.run_backtest(records, snapshots, horizon_days=180)
    assert s.total == 0
    assert s.skipped == 1
    assert "missing_snapshots" in s.skip_reasons


def test_below_50_win_prob_maps_to_inverse_bucket():
    """winProbA=0.30 means calc favors B by 0.70 — bucketed as 0.70-0.75."""
    # |0.30 - 0.5| + 0.5 = 0.70 → bucket [0.70, 0.75).
    assert bh._bucket_for(0.30) == "0.70-0.75"  # noqa: SLF001
    # |0.20 - 0.5| + 0.5 = 0.80 → bucket [0.80, 0.85).
    assert bh._bucket_for(0.20) == "0.80-0.85"  # noqa: SLF001


def test_format_report_has_bucket_lines():
    snapshots = {
        ("A", "2024-01-01"): 8000, ("B", "2024-01-01"): 7500,
        ("A", "2024-06-29"): 8500, ("B", "2024-06-29"): 7200,
    }
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.85)]
    s = bh.run_backtest(records, snapshots)
    report = bh.format_report(s)
    assert "Backtest summary" in report
    assert "0.85-0.90" in report
    assert "calibration" in report


def test_bad_date_format_skip():
    records = [_record("t1", "not-a-date", ["A"], ["B"], 0.65)]
    s = bh.run_backtest(records, {})
    assert s.skipped == 1
    assert "bad_date_format" in s.skip_reasons


def test_horizon_days_configurable():
    snapshots = {
        ("A", "2024-01-01"): 8000, ("B", "2024-01-01"): 7500,
        ("A", "2024-04-01"): 8500, ("B", "2024-04-01"): 7000,
    }
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.65)]
    # Use 91-day horizon (2024 Q1 → Q2).
    s = bh.run_backtest(records, snapshots, horizon_days=91)
    assert s.total == 1


def test_to_dict_round_trips():
    snapshots = {
        ("A", "2024-01-01"): 8000, ("B", "2024-01-01"): 7500,
        ("A", "2024-06-29"): 8500, ("B", "2024-06-29"): 7200,
    }
    records = [_record("t1", "2024-01-01", ["A"], ["B"], 0.65)]
    s = bh.run_backtest(records, snapshots)
    d = s.to_dict()
    assert d["total"] == 1
    assert d["correct"] == 1
    assert d["horizonDays"] == 180
    assert "0.65-0.70" in d["buckets"]
