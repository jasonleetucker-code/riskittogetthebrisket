"""A pre-season 404 and a broken release path must not look alike.

nflverse publishes a season's play-by-play only once that season kicks
off. Asking for the current season in July therefore 404s, and that is
normal. Asking for a season that HAS started and getting a 404 means the
release path moved — which is exactly what happened to this repo before,
when an nflverse rename made IDP tackles score zero for a season.

Before this, both logged ERROR "the pbp release path no longer exists;
update _PBP_URL". That fires every offseason for a URL that is fine, and
once an operator learns to ignore it, the real breakage reads the same.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.nfl_data.reception_depth import season_has_plausibly_started


def _at(year, month):
    return datetime(year, month, 15, tzinfo=timezone.utc)


def test_the_current_season_has_not_started_in_the_offseason():
    """The live case: it is July 2026 and play_by_play_2026.csv 404s."""
    assert not season_has_plausibly_started(2026, now=_at(2026, 7))


def test_the_current_season_has_started_once_september_arrives():
    assert season_has_plausibly_started(2026, now=_at(2026, 9))
    assert season_has_plausibly_started(2026, now=_at(2026, 12))


def test_every_past_season_counts_as_started():
    """So a genuinely stale URL is never silenced.

    A 404 on a completed season is always a real problem, whatever month
    it is asked in.
    """
    for month in (1, 7, 9, 12):
        assert season_has_plausibly_started(2024, now=_at(2026, month))
        assert season_has_plausibly_started(2025, now=_at(2026, month))


def test_a_future_season_has_not_started():
    assert not season_has_plausibly_started(2027, now=_at(2026, 12))


def test_the_two_states_are_actually_distinguishable():
    """Non-vacuity: the predicate must not answer the same for both."""
    assert season_has_plausibly_started(2025, now=_at(2026, 7)) is True
    assert season_has_plausibly_started(2026, now=_at(2026, 7)) is False
