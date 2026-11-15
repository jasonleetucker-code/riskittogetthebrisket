from __future__ import annotations

import pytest

from src.auction.schedule import (
    ActiveWindow,
    active_between,
    add_active,
    is_active,
    next_active_start,
)
from tests.auction.helpers import et

W = ActiveWindow()
HOUR = 3600


def test_boundaries_inclusive_start_exclusive_end():
    assert is_active(W, et(2026, 10, 5, 8, 0))
    assert not is_active(W, et(2026, 10, 5, 7, 59, 59))
    assert is_active(W, et(2026, 10, 5, 20, 59, 59))
    assert not is_active(W, et(2026, 10, 5, 21, 0))


def test_one_hour_left_at_2030_closes_0830_next_day():
    assert add_active(W, et(2026, 10, 5, 20, 30), HOUR) == et(2026, 10, 6, 8, 30)


def test_deadline_exactly_at_2100_stays_at_2100():
    assert add_active(W, et(2026, 10, 5, 20, 0), HOUR) == et(2026, 10, 5, 21, 0)


def test_from_quiet_time_starts_at_0800():
    assert add_active(W, et(2026, 10, 5, 23, 0), HOUR) == et(2026, 10, 6, 9, 0)
    assert next_active_start(W, et(2026, 10, 6, 3, 0)) == et(2026, 10, 6, 8, 0)


def test_65_active_hours_is_five_days():
    # 13 active hours/day: 65h from 08:00 Monday ends 21:00 Friday.
    assert add_active(W, et(2026, 10, 5, 8, 0), 65 * HOUR) == et(2026, 10, 9, 21, 0)


@pytest.mark.parametrize(
    "start,expected",
    [
        # DST ends Sun 2026-11-01 (02:00 -> 01:00).  Window is wall-clock 8-21.
        (et(2026, 10, 31, 20, 0), et(2026, 11, 1, 9, 0)),
        # DST starts Sun 2026-03-08.
        (et(2026, 3, 7, 20, 30), et(2026, 3, 8, 9, 30)),
    ],
)
def test_dst_transitions_keep_wall_clock_window(start, expected):
    assert add_active(W, start, 2 * HOUR) == expected


def test_year_and_month_rollover():
    assert add_active(W, et(2026, 12, 31, 20, 0), 2 * HOUR) == et(2027, 1, 1, 9, 0)
    assert add_active(W, et(2026, 9, 30, 20, 0), 2 * HOUR) == et(2026, 10, 1, 9, 0)


def test_active_between_inverse_of_add_active():
    for start in (
        et(2026, 10, 5, 7),
        et(2026, 10, 5, 12, 17),
        et(2026, 10, 31, 19),
        et(2026, 3, 7, 20, 45),
    ):
        for secs in (1, 1800, 3600, 13 * 3600, 65 * 3600):
            end = add_active(W, start, secs)
            assert active_between(W, start, end) == pytest.approx(secs)


def test_disabled_window_is_always_active():
    w = ActiveWindow(enabled=False)
    t = et(2026, 10, 5, 23)
    assert is_active(w, t)
    assert add_active(w, t, 600) == t + 600
