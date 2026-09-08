"""Immutable canonical weekly Power publication tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ros import power_snapshots


def _section(*, week: int, ranks: dict[str, int], scores: dict[str, float] | None = None):
    scores = scores or {oid: 90.0 - rank for oid, rank in ranks.items()}
    ranking = []
    for oid, rank in ranks.items():
        ranking.append(
            {
                "ownerId": oid,
                "displayName": oid.upper(),
                "teamName": f"Team {oid}",
                "rank": rank,
                "powerScore": scores[oid],
                "record": "1-0",
                "rosStrengthPercentile": 0.5,
                "components": {
                    "team_ros_strength": 0.5,
                    "all_play": 0.5,
                    "recent": 0.5,
                    "team_vorp": None,
                    "wl_record": 0.5,
                    "pointsPerGame": 100.0,
                    "recentAvg": 100.0,
                },
            }
        )
    return {
        "asOfSeason": "2026",
        "asOfWeek": week,
        "methodologyVersion": "test-v1",
        "blend": {"forwardWeight": 0.75, "resultsWeight": 0.25},
        "weights": {"team_ros_strength": 0.4, "all_play": 0.2},
        "effectiveWeights": {"team_ros_strength": 0.75, "all_play": 0.25},
        "currentRanking": ranking,
    }


def test_first_week_has_no_fabricated_movement(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    path, created = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks={"a": 1, "b": 2}),
        scoring_fingerprint="abc",
        finalized_at="2026-09-08T00:00:00+00:00",
    )
    assert created
    payload = json.loads(path.read_text())
    assert all(row["rankDelta"] is None for row in payload["ranking"])


def test_week_two_movement_uses_previous_official_rank_math(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks={"a": 3, "b": 1, "c": 2}),
        scoring_fingerprint="abc",
        finalized_at="2026-09-08T00:00:00+00:00",
    )
    path, _ = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=2, ranks={"a": 1, "b": 2, "c": 3}),
        scoring_fingerprint="abc",
        finalized_at="2026-09-15T00:00:00+00:00",
    )
    rows = {row["ownerId"]: row for row in json.loads(path.read_text())["ranking"]}
    assert rows["a"]["rankDelta"] == 2  # 3 -> 1 means up two
    assert rows["b"]["rankDelta"] == -1
    assert rows["c"]["rankDelta"] == -1


def test_recalculation_cannot_rewrite_an_official_week(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    first = _section(week=2, ranks={"a": 1, "b": 2})
    path, created = power_snapshots.record_snapshot(
        league_key="main",
        section=first,
        scoring_fingerprint="abc",
        finalized_at="2026-09-15T00:00:00+00:00",
    )
    before = path.read_text()

    changed = _section(week=2, ranks={"a": 2, "b": 1})
    same_path, created_again = power_snapshots.record_snapshot(
        league_key="main",
        section=changed,
        scoring_fingerprint="different",
        finalized_at="2026-09-15T03:00:00+00:00",
    )
    assert same_path == path
    assert not created_again
    assert path.read_text() == before


def test_movement_never_skips_a_missing_week(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks={"a": 2, "b": 1}),
        scoring_fingerprint="abc",
    )
    movement = power_snapshots.movement_against_previous(
        league_key="main",
        season="2026",
        week=3,
        rankings=_section(week=3, ranks={"a": 1, "b": 2})["currentRanking"],
    )
    assert movement["a"]["weekRankDelta"] is None
    assert movement["b"]["weekRankDelta"] is None


def test_latest_snapshot_returns_highest_week_in_requested_season(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    for week in (1, 3, 2):
        power_snapshots.record_snapshot(
            league_key="main",
            section=_section(week=week, ranks={"a": 1, "b": 2}),
            scoring_fingerprint="abc",
        )
    assert power_snapshots.latest_snapshot("main", season="2026")["week"] == 3


def test_scoring_fingerprint_is_stable_and_sensitive():
    snap_a = SimpleNamespace(
        current_season=SimpleNamespace(
            league={
                "scoring_settings": {"pass_yd": 0.04},
                "roster_positions": ["QB", "WR"],
                "settings": {"playoff_week_start": 15},
            }
        )
    )
    snap_b = SimpleNamespace(
        current_season=SimpleNamespace(
            league={
                "settings": {"playoff_week_start": 15},
                "roster_positions": ["QB", "WR"],
                "scoring_settings": {"pass_yd": 0.04},
            }
        )
    )
    snap_c = SimpleNamespace(
        current_season=SimpleNamespace(
            league={
                "scoring_settings": {"pass_yd": 0.05},
                "roster_positions": ["QB", "WR"],
                "settings": {"playoff_week_start": 15},
            }
        )
    )
    assert power_snapshots.scoring_config_fingerprint(snap_a) == power_snapshots.scoring_config_fingerprint(snap_b)
    assert power_snapshots.scoring_config_fingerprint(snap_a) != power_snapshots.scoring_config_fingerprint(snap_c)


def test_refuses_unrankable_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    bad = _section(week=1, ranks={"a": 1})
    bad["currentRanking"][0]["rank"] = None
    with pytest.raises(ValueError):
        power_snapshots.record_snapshot(
            league_key="main",
            section=bad,
            scoring_fingerprint="abc",
        )
