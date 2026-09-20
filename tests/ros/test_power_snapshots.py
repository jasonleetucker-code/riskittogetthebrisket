"""Immutable canonical weekly Power publication tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ros import power_snapshots, scrape
from tests.ros.test_power_v2 import _make_snapshot


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
    assert power_snapshots.scoring_config_fingerprint(
        snap_a
    ) == power_snapshots.scoring_config_fingerprint(snap_b)
    assert power_snapshots.scoring_config_fingerprint(
        snap_a
    ) != power_snapshots.scoring_config_fingerprint(snap_c)


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


def test_atomic_publication_leaves_no_visible_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    path, created = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks={"a": 1, "b": 2}),
        scoring_fingerprint="abc",
    )
    assert created
    assert json.loads(path.read_text())["week"] == 1
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def _publisher_snapshot(*, incomplete=False):
    rosters = [
        {"owner_id": "a", "roster_id": 1},
        {"owner_id": "b", "roster_id": 2},
        {"owner_id": "c", "roster_id": 3},
        {"owner_id": "d", "roster_id": 4},
    ]
    rows = [
        {"roster_id": 1, "matchup_id": 1, "points": 120.0},
        {"roster_id": 2, "matchup_id": 1, "points": 110.0},
        {"roster_id": 3, "matchup_id": 2, "points": 100.0},
        {"roster_id": 4, "matchup_id": 2, "points": 0.0 if incomplete else 90.0},
    ]
    return _make_snapshot(rosters=rosters, matchups_by_week={1: rows})


def test_publisher_requires_complete_scored_matchup_coverage():
    complete = _publisher_snapshot()
    assert scrape._power_week_is_complete(complete, "2026", 1)

    incomplete = _publisher_snapshot(incomplete=True)
    assert not scrape._power_week_is_complete(incomplete, "2026", 1)


def test_publisher_rejects_missing_matchup_pair():
    snapshot = _publisher_snapshot()
    snapshot.current_season.matchups_by_week[1] = snapshot.current_season.matchups_by_week[1][:-1]
    assert not scrape._power_week_is_complete(snapshot, "2026", 1)


# --- Week 0 (preseason) publication + movement baseline ------------------
#
# Movement is "change since the previous OFFICIAL publication". Before Week 0
# was publishable there was no legitimate baseline for Week 1 at all, and the
# UI filled the gap by walking a results-only reconstruction that chains every
# tracked season together — so a season's first week compared against LAST
# season's standings-derived ranking and produced movement nobody could
# reconcile. These pin the supported path instead.

#: The owner-supplied acceptance scenario. Last official publication (a
#: preseason Week 0) and the first scored week that follows it.
_WK0_RANKS = {
    "brent": 1,
    "joey": 2,
    "eric": 3,
    "jason": 4,
    "collin": 5,
    "makayla": 6,
    "kich": 7,
    "blaine": 8,
    "ed": 9,
    "ty": 10,
    "jstuedle": 11,
    "roy": 12,
}

_WK1_RANKS = {
    "eric": 1,
    "joey": 2,
    "jason": 3,
    "makayla": 4,
    "brent": 5,
    "ed": 6,
    "collin": 7,
    "blaine": 8,
    "jstuedle": 9,
    "kich": 10,
    "ty": 11,
    "roy": 12,
}

#: Positive = moved up. Exactly ``previous rank - new rank`` for every owner.
_EXPECTED_MOVEMENT = {
    "eric": 2,
    "joey": 0,
    "jason": 1,
    "makayla": 2,
    "brent": -4,
    "ed": 3,
    "collin": -2,
    "blaine": 0,
    "jstuedle": 2,
    "kich": -3,
    "ty": -1,
    "roy": 0,
}


def test_preseason_week_zero_is_publishable(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    path, created = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=0, ranks=_WK0_RANKS),
        scoring_fingerprint="abc",
        finalized_at="2026-09-01T00:00:00+00:00",
    )
    assert created
    assert path.name == "week_00.json"
    payload = json.loads(path.read_text())
    assert payload["week"] == 0
    # Self-describing: a consumer never has to infer "preseason" from the number.
    assert payload["preseason"] is True
    # Week 0 is the FIRST publishable week, so it has no predecessor of its own.
    assert all(row["rankDelta"] is None for row in payload["ranking"])


def test_week_one_movement_is_measured_against_the_published_week_zero(tmp_path, monkeypatch):
    """The owner's 12-team acceptance scenario, exactly."""
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=0, ranks=_WK0_RANKS),
        scoring_fingerprint="abc",
        finalized_at="2026-09-01T00:00:00+00:00",
    )
    path, _ = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks=_WK1_RANKS),
        scoring_fingerprint="abc",
        finalized_at="2026-09-09T00:00:00+00:00",
    )
    rows = {row["ownerId"]: row for row in json.loads(path.read_text())["ranking"]}
    assert {oid: rows[oid]["rankDelta"] for oid in _EXPECTED_MOVEMENT} == _EXPECTED_MOVEMENT
    # And the baseline each arrow was measured against is published with it,
    # so the number is auditable rather than merely asserted.
    assert {oid: rows[oid]["priorRank"] for oid in _WK0_RANKS} == _WK0_RANKS


def test_week_one_movement_never_reflects_the_results_only_reconstruction(tmp_path, monkeypatch):
    """The specific wrong answer this work exists to stop.

    The results-only diagnostic ranked a DIFFERENT population in a different
    order (ten owners, standings-shaped). If it ever reached the movement
    computation it would produce arrows like Eric +8 instead of +2. Movement
    reads published snapshots only, so the reconstruction cannot touch it.
    """
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    results_only_week_1 = {
        "brent": 1,
        "joey": 2,
        "ed": 3,
        "kich": 4,
        "makayla": 5,
        "ty": 6,
        "collin": 7,
        "roy": 8,
        "eric": 9,
        "jason": 10,
    }
    power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=0, ranks=_WK0_RANKS),
        scoring_fingerprint="abc",
        finalized_at="2026-09-01T00:00:00+00:00",
    )
    path, _ = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=1, ranks=_WK1_RANKS),
        scoring_fingerprint="abc",
        finalized_at="2026-09-09T00:00:00+00:00",
    )
    rows = {row["ownerId"]: row for row in json.loads(path.read_text())["ranking"]}
    # Eric is the sharpest discriminator: +2 against the published Week 0,
    # but +8 if the results-only series had been the baseline.
    assert rows["eric"]["rankDelta"] == 2
    assert rows["eric"]["rankDelta"] != _WK1_RANKS["eric"] - results_only_week_1["eric"]
    assert rows["eric"]["priorRank"] == _WK0_RANKS["eric"]


def test_movement_never_crosses_a_season_boundary(tmp_path, monkeypatch):
    """A new season's Week 0 does not compare against last season's finale."""
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    prior = _section(week=14, ranks={"a": 1, "b": 2})
    prior["asOfSeason"] = "2025"
    power_snapshots.record_snapshot(
        league_key="main",
        section=prior,
        scoring_fingerprint="abc",
        finalized_at="2025-12-20T00:00:00+00:00",
    )
    path, _ = power_snapshots.record_snapshot(
        league_key="main",
        section=_section(week=0, ranks={"a": 2, "b": 1}),
        scoring_fingerprint="abc",
        finalized_at="2026-09-01T00:00:00+00:00",
    )
    payload = json.loads(path.read_text())
    assert payload["season"] == "2026"
    assert all(row["rankDelta"] is None for row in payload["ranking"])
