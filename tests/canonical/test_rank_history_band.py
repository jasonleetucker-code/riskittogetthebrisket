"""Tests for the rankHistory band (rolling CI over time)."""
from __future__ import annotations

from src.canonical import rank_history_band as rhb


def _snap(date, p10, p50, p90):
    return {"date": date, "valueBand": {"p10": p10, "p50": p50, "p90": p90}}


def test_empty_input_returns_none():
    assert rhb.build_band_history([]) is None


def test_single_snapshot_returns_stable():
    band = rhb.build_band_history([_snap("2026-04-01", 100, 150, 200)])
    assert band is not None
    assert band.trend == "stable"
    assert band.spread == [100.0]
    assert band.spread_change_30d is None


def test_converging_trend_detected():
    """Spread tightens from 200 → 100 → 50 → converging."""
    snaps = [
        _snap("2026-04-01", 100, 200, 300),  # spread 200
        _snap("2026-04-15", 150, 200, 250),  # spread 100
        _snap("2026-04-30", 175, 200, 225),  # spread 50
    ]
    band = rhb.build_band_history(snaps, window_days=30)
    assert band.trend == "converging"
    assert band.spread_change_30d < 0


def test_diverging_trend_detected():
    """Spread widens → diverging."""
    snaps = [
        _snap("2026-04-01", 150, 200, 250),  # spread 100
        _snap("2026-04-30", 100, 200, 300),  # spread 200
    ]
    band = rhb.build_band_history(snaps, window_days=30)
    assert band.trend == "diverging"
    assert band.spread_change_30d > 0


def test_stable_trend_when_change_small():
    snaps = [
        _snap("2026-04-01", 100, 150, 200),  # spread 100
        _snap("2026-04-30", 105, 150, 200),  # spread 95
    ]
    band = rhb.build_band_history(snaps, window_days=30)
    assert band.trend == "stable"


def test_malformed_snapshots_skipped():
    snaps = [
        None,
        {"date": "2026-04-01", "valueBand": {"p10": "not a number"}},
        _snap("2026-04-02", 100, 150, 200),
    ]
    band = rhb.build_band_history(snaps)
    assert band is not None
    assert len(band.dates) == 1


def test_chronological_sort():
    snaps = [
        _snap("2026-04-30", 175, 200, 225),
        _snap("2026-04-01", 100, 200, 300),
        _snap("2026-04-15", 150, 200, 250),
    ]
    band = rhb.build_band_history(snaps)
    assert band.dates == ["2026-04-01", "2026-04-15", "2026-04-30"]


def test_to_dict_shape():
    band = rhb.build_band_history([_snap("2026-04-01", 100, 150, 200)])
    d = band.to_dict()
    assert "dates" in d
    assert "p10" in d
    assert "trend" in d
    assert d["spreadChange30d"] is None  # single snapshot
