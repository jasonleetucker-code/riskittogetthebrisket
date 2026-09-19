"""Power ranking as-of-week integrity regressions."""

from __future__ import annotations

import pytest

from src.ros import power_snapshots, power_v2
from tests.ros.test_power_v2 import _make_snapshot


def test_live_power_ignores_sleeper_record_from_a_later_week(monkeypatch):
    rosters = [
        {
            "owner_id": "a",
            "roster_id": 1,
            "settings": {"wins": 2, "losses": 0, "ties": 0},
        },
        {
            "owner_id": "b",
            "roster_id": 2,
            "settings": {"wins": 1, "losses": 1, "ties": 0},
        },
    ]
    snapshot = _make_snapshot(
        rosters=rosters,
        matchups_by_week={
            1: [
                {"roster_id": 1, "matchup_id": 1, "points": 120.0},
                {"roster_id": 2, "matchup_id": 1, "points": 100.0},
            ]
        },
    )
    monkeypatch.setattr(power_v2, "_load_team_strength_rows", lambda snapshot=None: [])
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda snapshot=None: {"a": 0.75, "b": 0.25},
    )

    section = power_v2.build_section(snapshot)
    rows = {row["ownerId"]: row for row in section["currentRanking"]}

    assert section["asOfWeek"] == 1
    assert section["blend"]["scoredGames"] == 1
    assert rows["a"]["record"] == "1-0"
    assert rows["b"]["record"] == "0-1"
    assert rows["a"]["recordSource"] == "matchups_as_of_week"
    assert rows["b"]["recordSource"] == "matchups_as_of_week"
    assert rows["a"]["recordGames"] == 1
    assert rows["b"]["recordGames"] == 1
    assert rows["a"]["components"]["wl_record"] == 1.0
    assert rows["b"]["components"]["wl_record"] == 0.0


def _publication_section(*, week: int, scored_games: int, record_games: int):
    return {
        "asOfSeason": "2026",
        "asOfWeek": week,
        "methodologyVersion": "test-v1",
        "blend": {"scoredGames": scored_games},
        "weights": {"team_ros_strength": 1.0},
        "effectiveWeights": {"team_ros_strength": 1.0},
        "currentRanking": [
            {
                "ownerId": "a",
                "displayName": "A",
                "teamName": "Team A",
                "rank": 1,
                "powerScore": 80.0,
                "record": "2-0" if record_games == 2 else "1-0",
                "recordGames": record_games,
                "recordSource": "sleeper_as_of_week",
                "rosStrengthPercentile": 0.5,
                "components": {
                    "team_ros_strength": 0.5,
                    "all_play": 0.5,
                    "recent": 0.5,
                    "team_vorp": None,
                    "wl_record": 1.0,
                    "pointsPerGame": 100.0,
                    "recentAvg": 100.0,
                },
            }
        ],
    }


def test_week_one_publication_refuses_two_game_record(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    section = _publication_section(week=1, scored_games=1, record_games=2)

    with pytest.raises(ValueError, match="record horizon mismatch"):
        power_snapshots.record_snapshot(
            league_key="main", section=section, scoring_fingerprint="abc"
        )

    assert not power_snapshots.snapshot_path("main", "2026", 1).exists()


def test_publication_refuses_blend_week_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    section = _publication_section(week=2, scored_games=1, record_games=2)

    with pytest.raises(ValueError, match="horizon mismatch"):
        power_snapshots.record_snapshot(
            league_key="main", section=section, scoring_fingerprint="abc"
        )


def test_aligned_week_publication_persists_audit_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    section = _publication_section(week=1, scored_games=1, record_games=1)

    path, created = power_snapshots.record_snapshot(
        league_key="main", section=section, scoring_fingerprint="abc"
    )

    assert created
    payload = __import__("json").loads(path.read_text())
    row = payload["ranking"][0]
    assert row["recordGames"] == 1
    assert row["recordSource"] == "sleeper_as_of_week"
