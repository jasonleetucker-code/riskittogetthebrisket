"""The pregame weekly-projection archive survives the raw-log retention prune.

Owner authorization 2026-09-29 (#1519 G1): the four-week Game Day prune must
not destroy what Calculator knew before kickoff.  Before an old NFL week's raw
observations are deleted, the last pre-kickoff Sleeper weekly projection row
per player is preserved -- selected by the canonical
``lock_baseline_at_kickoff`` -- and when that cannot be established the raw
log is kept instead.
"""

from __future__ import annotations

import dataclasses
import gzip
import json

import pytest

from src.ros import game_day_live as live
from src.ros.sleeper_weekly_projections import row_refusal_reason
from tests.game_day.test_game_day_replay import (
    PRE_KICKOFF_FETCH,
    REAL_FETCH,
    SEASON,
    WEEK,
    _scenario,
    _schedule_rows,
)

SCHEDULE = _schedule_rows(_scenario("real_halftime")["espn"])
NOW = 2_000_000_000.0
TNF_TEAMS = {"ATL", "GB"}  # kicked off 2026-09-25T00:15Z, between the two fetches


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    live._weekly_history_cache.clear()
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(SCHEDULE))
    yield
    live._weekly_history_cache.clear()


def _valid(row) -> bool:
    return row_refusal_reason(row, season=SEASON, week=WEEK) is None


def _record(*fetches) -> None:
    log = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY)
    for fetch in fetches:
        status, meta, content = live.weekly_to_observation(fetch)
        log.append(fetched_at=meta["observedAt"], status=status, meta=meta, content=content)


def _obs_dir():
    return live.league_week_dir(live.NFL_KEY, SEASON, WEEK) / "observations"


def _read(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def test_the_archive_keeps_each_players_last_pre_kickoff_row_unchanged():
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    archive = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)
    players = archive["players"]

    pre_by_pid = {str(r["player_id"]): r for r in PRE_KICKOFF_FETCH.rows if _valid(r)}
    real_by_pid = {str(r["player_id"]): r for r in REAL_FETCH.rows if _valid(r)}
    tnf = [pid for pid, r in real_by_pid.items() if r.get("team") in TNF_TEAMS]
    sunday = [pid for pid, r in real_by_pid.items() if r.get("team") not in TNF_TEAMS]
    assert tnf and sunday

    for pid in tnf:
        if pid in pre_by_pid:
            # The post-kickoff read is never the pregame answer.
            assert players[pid]["observedAt"] == live._iso(
                live._epoch(PRE_KICKOFF_FETCH.observed_at)
            )
            assert players[pid]["row"] == pre_by_pid[pid]
        else:
            assert pid not in players and pid in archive["noPreKickoffObservation"]
    for pid in sunday:
        # The later fetch is still before a Sunday kickoff, so it wins.
        assert players[pid]["observedAt"] == live._iso(live._epoch(REAL_FETCH.observed_at))
        assert players[pid]["row"] == real_by_pid[pid]  # raw provider row, not rescored
        assert players[pid]["kickoffAt"].startswith("2026-09-2")
    assert archive["postKickoffObservationsIgnored"] > 0
    # Placeholder rows the scoring path refuses are counted, never archived.
    refused = [r for r in REAL_FETCH.rows if not _valid(r)]
    assert refused and sum(archive["refusedRows"].values()) >= len(refused)
    assert not any(
        str(r["player_id"]) in players for r in refused if str(r["player_id"]) not in pre_by_pid
    )
    # Known post-kickoff-only players are not "timing unverified".
    assert not set(archive["noPreKickoffObservation"]) & set(archive["timingUnverified"])
    assert archive["season"] == SEASON and archive["week"] == WEEK
    assert archive["source"] == live.SOURCE_WEEKLY
    assert archive["schemaVersion"] == live.PREGAME_ARCHIVE_SCHEMA


def test_the_prune_cannot_delete_the_pregame_evidence():
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    expected = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)

    removed = live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)

    assert str(_obs_dir()) in removed
    assert not _obs_dir().exists()
    archive_path = live.pregame_archive_path(SEASON, WEEK)
    assert archive_path.parent == _obs_dir().parent  # outside observations/
    stored = _read(archive_path)
    assert stored["players"] == json.loads(json.dumps(expected["players"]))
    # A second prune neither removes nor rewrites it.
    before = archive_path.read_bytes()
    live.prune_retention(SEASON, WEEK + 10)
    assert archive_path.read_bytes() == before


def test_the_prune_keeps_the_raw_log_when_kickoffs_are_unknown(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: [])

    live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)

    assert _obs_dir().is_dir()  # fail closed: the evidence stays
    assert not live.pregame_archive_path(SEASON, WEEK).exists()


def test_the_prune_keeps_the_raw_log_when_the_archive_is_unreadable():
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    path = live.pregame_archive_path(SEASON, WEEK)
    path.write_bytes(b"not gzip")

    live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)

    assert _obs_dir().is_dir()
    assert path.read_bytes() == b"not gzip"  # never silently replaced


def test_an_existing_archive_is_never_rebuilt_from_later_evidence():
    _record(PRE_KICKOFF_FETCH)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW)
    first = live.pregame_archive_path(SEASON, WEEK).read_bytes()
    _record(REAL_FETCH)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60)
    assert live.pregame_archive_path(SEASON, WEEK).read_bytes() == first


def test_a_week_without_weekly_projections_prunes_as_before():
    obs = _obs_dir()
    obs.mkdir(parents=True)
    (obs / "espn_scoreboard.jsonl").write_text("{}\n")

    live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)

    assert not obs.exists()
    assert not live.pregame_archive_path(SEASON, WEEK).exists()


def test_league_logs_prune_unchanged_and_archives_are_bounded_by_season():
    league_obs = live.league_week_dir("lk", SEASON, WEEK) / "observations"
    league_obs.mkdir(parents=True)
    (league_obs / "x.jsonl").write_text("{}\n")
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)
    assert not league_obs.exists()
    path = live.pregame_archive_path(SEASON, WEEK)
    assert path.exists()

    live.prune_retention(SEASON + live.PREGAME_ARCHIVE_SEASONS, 1)
    assert path.exists()
    live.prune_retention(SEASON + live.PREGAME_ARCHIVE_SEASONS + 1, 1)
    assert not path.exists()


def test_an_emptied_later_row_never_displaces_an_earlier_valid_projection():
    sunday = next(r for r in REAL_FETCH.rows if _valid(r) and r.get("team") not in TNF_TEAMS)
    pid = str(sunday["player_id"])
    early = dataclasses.replace(PRE_KICKOFF_FETCH, rows=(sunday,))
    emptied = dict(sunday, stats={})
    later = dataclasses.replace(REAL_FETCH, rows=(emptied,))
    _record(early, later)

    archive = live.build_pregame_projection_archive(SEASON, WEEK, schedule_rows=SCHEDULE, now=NOW)

    assert archive["players"][pid]["row"] == sunday
    assert archive["refusedRows"] == {"placeholder_no_projection": 1}


def test_a_failure_is_persisted_and_throttled_across_processes(monkeypatch):
    _record(PRE_KICKOFF_FETCH, REAL_FETCH)
    calls = []

    def no_schedule(season):
        calls.append(season)
        return []

    monkeypatch.setattr(live, "_archive_schedule_rows", no_schedule)
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW) is False
    marker = live._pregame_failure_path(SEASON, WEEK)
    stored = json.loads(marker.read_text())
    assert "kickoffs_unknown" in stored["reason"]

    live._weekly_history_cache.clear()  # a fresh collector process
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 60) is False
    assert calls == [SEASON]  # throttled from disk, not rebuilt

    monkeypatch.setattr(live, "_archive_schedule_rows", lambda season: list(SCHEDULE))
    assert live.ensure_pregame_archive(SEASON, WEEK, now=NOW + 3601) is True
    assert not marker.exists()


def test_a_damaged_weekly_log_is_kept_not_treated_as_empty():
    log = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY)
    log.log_path.parent.mkdir(parents=True, exist_ok=True)
    log.log_path.write_text("not json\n")

    live.prune_retention(SEASON, WEEK + live.RAW_RETENTION_WEEKS + 1)

    assert log.log_path.exists()
    assert not live.pregame_archive_path(SEASON, WEEK).exists()
