"""Tests for the NFL data freshness guard.

The rule: don't fire alerts on current-week data before Thursday
(NFL-TZ).  The tests pin every quadrant of the decision tree."""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

from src.nfl_data import freshness


NFL_TZ = ZoneInfo("America/New_York")


def _mk(year, month, day, hour=10, weekday=None):
    """Build a tz-aware NFL-TZ datetime at given date/time."""
    return _dt.datetime(year, month, day, hour, tzinfo=NFL_TZ)


def test_historical_year_is_always_fresh():
    # Current season 2026, stat year 2024 → fresh regardless of day.
    assert freshness.is_fresh_for_alerts(
        stat_week=10, stat_year=2024,
        now=_mk(2026, 4, 24),  # a Friday
        season_year=2026, season_current_week=3,
    ) is True


def test_prior_completed_week_is_fresh():
    # Stat week 2 of 2026, current week 4 → finalized → fresh.
    assert freshness.is_fresh_for_alerts(
        stat_week=2, stat_year=2026,
        now=_mk(2026, 9, 29),  # arbitrary
        season_year=2026, season_current_week=4,
    ) is True


def test_future_week_is_never_fresh():
    # Stat week 8 when current week is only 5 → bogus data.
    assert freshness.is_fresh_for_alerts(
        stat_week=8, stat_year=2026,
        now=_mk(2026, 10, 10),
        season_year=2026, season_current_week=5,
    ) is False


def test_current_week_monday_morning_is_not_fresh():
    # Monday Oct 13, 2025 — Mon=0, before Thursday cutoff.
    monday = _dt.datetime(2025, 10, 13, 9, tzinfo=NFL_TZ)
    assert monday.weekday() == 0
    assert freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=monday,
        season_year=2025, season_current_week=6,
    ) is False


def test_current_week_thursday_morning_is_fresh():
    # Thursday Oct 16, 2025.
    thursday = _dt.datetime(2025, 10, 16, 9, tzinfo=NFL_TZ)
    assert thursday.weekday() == 3
    assert freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=thursday,
        season_year=2025, season_current_week=6,
    ) is True


def test_current_week_sunday_evening_is_fresh():
    # Sunday evening after the games — week games are over.
    sunday = _dt.datetime(2025, 10, 19, 23, tzinfo=NFL_TZ)
    assert sunday.weekday() == 6
    assert freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=sunday,
        season_year=2025, season_current_week=6,
    ) is True


def test_unknown_season_context_is_conservative():
    # No season_current_week → conservative False.
    assert freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=_mk(2025, 10, 13),
        season_year=2025,
        season_current_week=None,
    ) is False


def test_naive_datetime_assumed_nfl_tz():
    """Passing a naive datetime works; treated as NFL-TZ.  Would be
    awkward if it raised — callers sometimes pass datetime.utcnow()
    forgetting the tz."""
    naive = _dt.datetime(2025, 10, 13, 9)
    # Shouldn't raise.
    freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=naive,
        season_year=2025, season_current_week=6,
    )


def test_week_is_in_flight_matches_inverse():
    """week_is_in_flight = True iff is_fresh_for_alerts = False for
    a current-week row."""
    monday = _dt.datetime(2025, 10, 13, 9, tzinfo=NFL_TZ)
    assert freshness.week_is_in_flight(
        stat_week=6, stat_year=2025,
        now=monday,
        season_year=2025, season_current_week=6,
    ) is True
    assert freshness.is_fresh_for_alerts(
        stat_week=6, stat_year=2025,
        now=monday,
        season_year=2025, season_current_week=6,
    ) is False
