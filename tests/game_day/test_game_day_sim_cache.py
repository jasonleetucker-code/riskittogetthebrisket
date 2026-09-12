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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def test_a_model_version_change_invalidates_the_cache(cache_dir):
    """A deployment that changes simulation semantics must not reuse a
    disk result produced by the prior model version."""
    rules, teams, opponents = _league()
    with mock.patch.object(gds, "simulate_league_week", wraps=gds.simulate_league_week) as spy:
        _call(rules, teams, opponents)
        with mock.patch.object(gds, "MODEL_VERSION", "game-day-sim-next"):
            _call(rules, teams, opponents)
    assert spy.call_count == 2, "model-version change reused a stale simulation result"


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


def test_concurrent_same_inputs_simulate_once(cache_dir):
    rules, teams, opponents = _league()
    original = gds.simulate_league_week
    start = threading.Barrier(6)

    def simulate(**kwargs):
        time.sleep(0.05)
        return original(**kwargs)

    def request(_):
        start.wait(timeout=5)
        return _call(rules, teams, opponents)

    with (
        mock.patch.object(gds, "simulate_league_week", side_effect=simulate) as solve,
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        outcomes = list(pool.map(request, range(6)))
    assert solve.call_count == 1
    assert all(outcome.teams == outcomes[0].teams for outcome in outcomes)
    assert sum(not outcome.cached for outcome in outcomes) == 1


def test_failed_simulation_does_not_poison_retry(cache_dir):
    rules, teams, opponents = _league()
    with mock.patch.object(gds, "simulate_league_week", side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError, match="failed"):
            _call(rules, teams, opponents)
    assert _call(rules, teams, opponents).cached is False
    assert _call(rules, teams, opponents).cached is True


def test_concurrent_publishers_use_distinct_temporary_files(cache_dir, monkeypatch):
    """Also covers writers outside the process-local simulation single-flight."""
    rules, teams, opponents = _league()
    simulation = _call(rules, teams, opponents)
    path = gds._sim_cache_path(rules.league_key, 2026, 1)
    ready_to_publish = threading.Barrier(2)
    original_replace = Path.replace
    temporary_paths = []
    attempted = set()
    attempts_lock = threading.Lock()

    def publish(source, destination):
        with attempts_lock:
            first_attempt = source not in attempted
            attempted.add(source)
            temporary_paths.append(source)
        if first_attempt:
            ready_to_publish.wait(timeout=5)
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: gds._write_sim_cache(path, "same-inputs", simulation), range(2)))
    assert len(set(temporary_paths)) == 2
    assert gds._read_sim_cache(path, "same-inputs").teams == simulation.teams
    assert not list(path.parent.glob("*.tmp"))


def test_failed_publication_preserves_previous_file_and_cleans_temp(cache_dir):
    rules, teams, opponents = _league()
    simulation = _call(rules, teams, opponents)
    path = gds._sim_cache_path(rules.league_key, 2026, 1)
    previous = path.read_bytes()
    with mock.patch.object(Path, "replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            gds._write_sim_cache(path, "new-inputs", simulation)
    assert path.read_bytes() == previous
    assert not list(path.parent.glob("*.tmp"))
