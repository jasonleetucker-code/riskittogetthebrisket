"""``get_cached_league_week_simulation`` (Defect 1 fix, 2026-09-06).

``simulate_league_week`` computes every team's outcome for a league-week in
one call, so every manager checking their own Game Day page for the same
league-week is asking the identical question. Without sharing, N managers
in the same window trigger N independent full recomputes of the exact same
simulation — this is what makes it worth caching rather than just faster.

What actually matters here is not "is there a file on disk" but two
properties: a cache HIT must not re-run the simulation, and a genuine input
change must never be served a stale answer. Both are asserted by spying on
``simulate_league_week`` itself rather than by timing, which is the only way
to prove the cache is doing what it claims rather than merely being fast by
coincidence.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.league_intel.sim_calibration import PointsModel
from src.ros import game_day_sim as gds
from src.ros.game_day_sim import (
    LeagueWeekRules,
    PlayerWeek,
    TeamWeek,
    get_cached_league_week_simulation,
)

_MODEL = PointsModel(ros_value_per_point=1.0, cv_by_position={}, default_cv=0.20)

_SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")


def _roster(prefix, remaining=10.0):
    spec = [
        ("qb1", "QB"),
        ("rb1", "RB"),
        ("rb2", "RB"),
        ("wr1", "WR"),
        ("wr2", "WR"),
        ("te1", "TE"),
    ]
    return tuple(
        PlayerWeek(
            player_id=f"{prefix}_{pid}",
            position=pos,
            state="not_started",
            projected_remaining=remaining,
        )
        for pid, pos in spec
    )


def _league(remaining=10.0):
    rules = LeagueWeekRules(
        league_key="cache_test_league",
        starter_slots=_SLOTS,
        best_ball=True,
        median_enabled=True,
        team_count=4,
    )
    teams = [TeamWeek(team_id=f"t{i}", players=_roster(f"t{i}", remaining)) for i in range(1, 5)]
    opponents = {"t1": "t2", "t2": "t1", "t3": "t4", "t4": "t3"}
    return rules, teams, opponents


@pytest.fixture
def cache_dir():
    """A throwaway cache root, patched in for the duration of one test —
    this suite must never touch the repo's real `data/game_day/sims/`."""
    tmp = tempfile.mkdtemp(prefix="game_day_sim_cache_test_")
    with mock.patch.object(gds, "_SIM_CACHE_ROOT", Path(tmp)):
        yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def _call(rules, teams, opponents, **kw):
    return get_cached_league_week_simulation(
        rules=rules,
        teams=teams,
        opponents=opponents,
        season=2026,
        week=1,
        draws=50,
        seed=1,
        points_model=_MODEL,
        **kw,
    )


def test_a_cold_call_computes_and_is_marked_uncached(cache_dir):
    rules, teams, opponents = _league()
    with mock.patch.object(gds, "simulate_league_week", wraps=gds.simulate_league_week) as spy:
        result = _call(rules, teams, opponents)
    assert spy.call_count == 1
    assert result.cached is False
    assert result.cache_computed_at is None


def test_a_second_identical_call_is_served_from_cache_without_recomputing(cache_dir):
    rules, teams, opponents = _league()
    with mock.patch.object(gds, "simulate_league_week", wraps=gds.simulate_league_week) as spy:
        first = _call(rules, teams, opponents)
        second = _call(rules, teams, opponents)
    assert spy.call_count == 1, "the second call re-ran the simulation instead of reusing the cache"
    assert second.cached is True
    assert second.cache_computed_at is not None
    assert first.teams == second.teams, "a cache hit must return the SAME outcome, not a fresh draw"


def test_a_changed_player_input_forces_a_real_recompute(cache_dir):
    """The fingerprint, not a blind TTL, is what must catch this: a
    roster move or a projection refresh must never be served the old
    answer just because it arrived inside the TTL window."""
    rules, teams, opponents = _league(remaining=10.0)
    _, changed_teams, _ = _league(remaining=999.0)

    with mock.patch.object(gds, "simulate_league_week", wraps=gds.simulate_league_week) as spy:
        _call(rules, teams, opponents)
        _call(rules, changed_teams, opponents)
    assert spy.call_count == 2, "a genuine input change was served a stale cached answer"


def test_a_different_week_does_not_collide_with_another_weeks_cache(cache_dir):
    rules, teams, opponents = _league()
    with mock.patch.object(gds, "simulate_league_week", wraps=gds.simulate_league_week) as spy:
        get_cached_league_week_simulation(
            rules=rules, teams=teams, opponents=opponents, season=2026, week=1,
            draws=50, seed=1, points_model=_MODEL,
        )  # fmt: skip
        get_cached_league_week_simulation(
            rules=rules, teams=teams, opponents=opponents, season=2026, week=2,
            draws=50, seed=1, points_model=_MODEL,
        )  # fmt: skip
    assert spy.call_count == 2


def test_the_cache_never_writes_under_data_ros():
    """`scheduled-refresh.yml` force-adds `data/ros/` to git every 2 hours
    (`git add -f`, overriding .gitignore) and only explicitly un-stages
    `data/ros/team_strength/*.json` afterward — confirmed live,
    `data/ros/sims/*.json` (a different, existing cache) IS tracked and
    committed to the public repo on that cadence. A Game Day simulation
    cache holds real per-manager win probabilities and lineups, so this
    module's REAL (unpatched) cache root must never resolve under
    `data/ros/` — deliberately not using the `cache_dir` fixture, which
    patches this constant to a throwaway path for every other test here.
    """
    real_root = str(gds._SIM_CACHE_ROOT).replace("\\", "/")
    assert "data/ros" not in real_root
    assert "data/game_day" in real_root
