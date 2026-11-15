"""The finished-week rule needs NFL evidence, not just scored rosters.

Production 2026-09-28 (found by the unified Manager of the Year unit, #1513):
on the evening of Sunday 2026-09-27 every roster in ``dynasty_main`` had
non-zero week-3 points while Monday Night Football (PHI @ CHI) was still
unplayed. ``final_regular_season_weeks``' data-completeness proof ("every
roster scored, in the expected number of rows") therefore read week 3 as
FINAL, and every awards, Luck and Power consumer aggregated a partial week.

Pinned: the completeness proof also requires every NFL game of the week to
be final (``metrics.nfl_week_games_final``); an unknown NFL answer withholds
the week (never a guess, never wall-clock); Sleeper's own host clock still
admits a week on its own authority.
"""

from __future__ import annotations

import math

import pytest

from src.public_league import metrics
from tests.public_league.test_final_weeks import _FULL, _season, _week

pytestmark = pytest.mark.nfl_week_evidence


def _game(
    week, away, home, score=None, game_type="REG", season=2026, day="2026-09-27", time="13:00"
):
    away_score = None if score is None else score[0]
    home_score = None if score is None else score[1]
    try:
        result = home_score - away_score
    except TypeError:
        result = None
    return {
        "season": season,
        "week": week,
        "game_type": game_type,
        "gameday": day,
        "gametime": time,
        "away_team": away,
        "home_team": home,
        "away_score": away_score,
        "home_score": home_score,
        "result": result,
    }


# Week 3 on the evening of Sunday 2026-09-27: Sunday's games are final,
# Monday Night Football is not.
_SUNDAY_EVENING = [
    _game(3, "ATL", "GB", (35, 14)),
    _game(3, "LA", "DEN", (26, 30)),
    _game(3, "PHI", "CHI"),
]
_MONDAY_FINAL = [
    _game(3, "ATL", "GB", (35, 14)),
    _game(3, "LA", "DEN", (26, 30)),
    _game(3, "PHI", "CHI", (24, 21)),
]


@pytest.fixture(autouse=True)
def _fresh_schedule_memo(monkeypatch):
    monkeypatch.setattr(metrics, "_NFL_SCHEDULE_MEMO", {})


@pytest.fixture
def schedule(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(metrics, "_nfl_schedule_rows", lambda year: list(rows))
    return rows


def _week3_all_rosters_scored(**kw):
    # Every roster has real points: the Sunday-evening shape.
    return _season({1: _week(*_FULL), 2: _week(*_FULL), 3: _week(*_FULL)}, **kw)


def test_sunday_evening_is_not_final_while_monday_night_is_unplayed(schedule):
    schedule.extend(_SUNDAY_EVENING + [_game(1, "A", "B", (1, 0)), _game(2, "A", "B", (1, 0))])
    season = _week3_all_rosters_scored(last_scored_leg=2)
    assert metrics.final_regular_season_weeks(season) == [1, 2]


def test_the_week_is_final_once_monday_night_is_final(schedule):
    schedule.extend(_MONDAY_FINAL)
    season = _week3_all_rosters_scored(last_scored_leg=2)
    assert metrics.final_regular_season_weeks(season) == [1, 2, 3]


def test_an_unknown_nfl_answer_withholds_the_week(schedule):
    # No schedule at all: the data proof alone never admits a week.
    season = _week3_all_rosters_scored(last_scored_leg=2)
    assert metrics.final_regular_season_weeks(season) == [1, 2]


def test_the_host_clock_admits_on_its_own_authority(schedule):
    schedule.extend(_SUNDAY_EVENING)
    season = _week3_all_rosters_scored(last_scored_leg=3)
    assert metrics.final_regular_season_weeks(season) == [1, 2, 3]


def test_completed_seasons_are_untouched_by_the_nfl_half(schedule):
    # A finished season's host clock covers every week; no schedule needed.
    season = _week3_all_rosters_scored(last_scored_leg=18)
    assert metrics.final_regular_season_weeks(season) == [1, 2, 3]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (_MONDAY_FINAL, True),
        (_SUNDAY_EVENING, False),
        ([], None),
        ([_game(4, "A", "B", (1, 0))], None),  # nothing listed for week 3
        ([_game(3, "A", "B", ("", 3))], False),  # blank score is not a score
        ([_game(3, "A", "B", (math.nan, 3))], False),  # NaN is not a score
        ([_game(3, "A", "B", day="2099-01-01")], False),  # not kicked off yet
        ([_game(3, "A", "B", (0, 0))], True),  # 0-0 is a real (odd) final
        ([_game(3, "A", "B", (1, 0)), _game(3, "C", "D", game_type="POST")], True),
        ([_game(3, "A", "B", (1, 0), season=2025)], None),  # other season's rows
    ],
)
def test_nfl_week_games_final_is_tri_state(schedule, rows, expected):
    schedule.extend(rows)
    assert metrics.nfl_week_games_final("2026", 3) is expected


def test_a_failing_schedule_owner_is_unknown_not_final(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("cache unreadable")

    from src.nfl_data import ingest

    monkeypatch.setattr(ingest, "fetch_schedules", boom)
    assert metrics.nfl_week_games_final(2026, 3) is None


def test_the_schedule_is_read_cache_only(monkeypatch):
    calls = []

    from src.nfl_data import ingest

    def record(years, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(ingest, "fetch_schedules", record)
    metrics.nfl_week_games_final(2026, 3)
    assert calls and calls[0].get("cache_only") is True


def test_a_complete_season_needs_no_nfl_evidence(schedule):
    # Past years' schedules are not guaranteed to be cached; a season the
    # host marks complete has no week in progress (same rule as final_weeks).
    season = _week3_all_rosters_scored()
    season.league["status"] = "complete"
    assert metrics.final_regular_season_weeks(season) == [1, 2, 3]


def test_the_schedule_is_read_once_per_memo_window(monkeypatch):
    reads = []

    from src.nfl_data import ingest

    def record(years, **kwargs):
        reads.append(years)
        return _MONDAY_FINAL

    monkeypatch.setattr(ingest, "fetch_schedules", record)
    for _ in range(20):
        assert metrics.nfl_week_games_final(2026, 3) is True
    assert len(reads) == 1


def test_sunday_afternoon_with_night_and_monday_games_remaining(schedule):
    # Early/late Sunday windows final; SNF has a future kickoff, MNF too.
    schedule.extend(
        [
            _game(3, "ATL", "GB", (35, 14)),
            _game(3, "LA", "DEN", time="16:25"),  # kicked off, no result yet
            _game(3, "KC", "BUF", day="2099-09-27", time="20:20"),
            _game(3, "PHI", "CHI", day="2099-09-28", time="20:15"),
        ]
    )
    season = _week3_all_rosters_scored(last_scored_leg=2)
    assert metrics.final_regular_season_weeks(season) == [1, 2]


def test_a_postponed_game_keeps_the_week_open(schedule):
    # Kicked off (or scheduled) in the past with no result ever published --
    # the BUF @ CIN 2022 shape. Unknown game state is not final.
    schedule.extend([_game(3, "ATL", "GB", (35, 14)), _game(3, "BUF", "CIN")])
    season = _week3_all_rosters_scored(last_scored_leg=2)
    assert metrics.nfl_week_games_final(2026, 3) is False
    assert metrics.final_regular_season_weeks(season) == [1, 2]


def test_a_real_zero_point_roster_in_a_final_week_is_admitted_by_the_host_clock(schedule):
    # The data proof cannot tell a genuine 0.0 from "hasn't played"; the
    # host clock can, and a missing score is never read as zero.
    schedule.extend(_MONDAY_FINAL)
    season = _season(
        {1: _week(*_FULL), 2: _week(*_FULL), 3: _week(110.0, 0.0, 120.0, 90.0)},
        last_scored_leg=2,
    )
    assert metrics.final_regular_season_weeks(season) == [1, 2]  # withheld, not guessed
    season.league["settings"]["last_scored_leg"] = 3
    assert metrics.final_regular_season_weeks(season) == [1, 2, 3]


def test_playoff_weeks_still_need_the_host_clock(schedule):
    # final_weeks: a playoff week is final on the host clock alone, never on
    # the NFL half -- a playoff week legitimately has fewer rows.
    schedule.extend([_game(15, "A", "B", (1, 0))])
    season = _season(
        {14: _week(*_FULL), 15: _week(110.0, 100.0)},
        last_scored_leg=14,
        playoff_week_start=15,
    )
    assert 15 not in metrics.final_weeks(season)
    season.league["settings"]["last_scored_leg"] = 15
    assert 15 in metrics.final_weeks(season)
