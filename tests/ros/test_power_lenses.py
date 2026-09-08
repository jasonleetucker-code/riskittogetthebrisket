"""One canonical Power answer plus a results-only diagnostic lens."""

from __future__ import annotations

import pytest

from src.ros import power_v2
from tests.ros.test_power_v2 import _make_snapshot


def _scored_snapshot(weeks: int = 3):
    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 120.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0 + wk},
            {"roster_id": 3, "matchup_id": 2, "points": 95.0 + wk},
            {"roster_id": 4, "matchup_id": 2, "points": 80.0 + wk},
        ]
        for wk in range(1, weeks + 1)
    }
    return _make_snapshot(rosters, matchups)


def test_owner_approved_target_vector_is_the_only_weight_spec():
    assert power_v2.WEIGHTS == {
        "team_ros_strength": 0.40,
        "all_play": 0.20,
        "recent": 0.15,
        "team_vorp": 0.15,
        "wl_record": 0.10,
    }
    assert sum(power_v2.WEIGHTS.values()) == pytest.approx(1.0)


def test_default_is_canonical_not_forward_looking_label(monkeypatch):
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda snapshot=None: {"o1": 0.9, "o2": 0.7, "o3": 0.3, "o4": 0.1},
    )
    out = power_v2.build_section(_scored_snapshot())
    assert out["lens"] == power_v2.LENS_CANONICAL
    assert out["requestedLens"] == power_v2.LENS_CANONICAL


def test_legacy_forward_query_is_only_a_compatibility_alias(monkeypatch):
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda snapshot=None: {"o1": 0.9, "o2": 0.7, "o3": 0.3, "o4": 0.1},
    )
    canonical = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_CANONICAL)
    legacy = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)

    assert legacy["lens"] == power_v2.LENS_CANONICAL
    assert legacy["requestedLens"] == power_v2.LENS_FORWARD_LOOKING
    assert legacy["currentRanking"] == canonical["currentRanking"]
    assert legacy["effectiveWeights"] == canonical["effectiveWeights"]


def test_results_only_never_reads_team_strength(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("results-only consulted team strength")

    monkeypatch.setattr(power_v2, "_load_team_strength_rows", boom)
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", boom)
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)

    assert out["lens"] == power_v2.LENS_RESULTS_ONLY
    assert "team_ros_strength" not in out["effectiveWeights"]
    assert sum(out["effectiveWeights"].values()) == pytest.approx(1.0)
    assert out["blend"]["forwardWeight"] == 0.0
    assert out["blend"]["resultsWeight"] == 1.0


def test_missing_vorp_keeps_results_component_ratios(monkeypatch):
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda snapshot=None: {})
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
    applied = out["effectiveWeights"]

    assert set(applied) == {"all_play", "recent", "wl_record"}
    assert applied["all_play"] / applied["recent"] == pytest.approx(0.20 / 0.15)
    assert applied["recent"] / applied["wl_record"] == pytest.approx(0.15 / 0.10)


def test_canonical_blends_ros_and_results_after_games(monkeypatch):
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda snapshot=None: {"o1": 0.9, "o2": 0.7, "o3": 0.3, "o4": 0.1},
    )
    out = power_v2.build_section(_scored_snapshot(4), lens=power_v2.LENS_CANONICAL)

    assert "team_ros_strength" in out["effectiveWeights"]
    assert {"all_play", "recent", "wl_record"} <= set(out["effectiveWeights"])
    assert out["blend"]["forwardWeight"] > 0
    assert out["blend"]["resultsWeight"] > 0
    assert out["blend"]["forwardWeight"] + out["blend"]["resultsWeight"] == pytest.approx(1.0)


def test_trend_remains_results_only_and_never_backfills_current_ros(monkeypatch):
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda snapshot=None: {"o1": 0.99, "o2": 0.7, "o3": 0.2, "o4": 0.1},
    )
    out = power_v2.build_section(_scored_snapshot(4), lens=power_v2.LENS_CANONICAL)

    assert out["trend"]["lens"] == power_v2.LENS_RESULTS_ONLY
    assert "Diagnostic results-only history" in out["trend"]["note"]
    for week in out["trend"]["weeks"]:
        assert "team_ros_strength" not in week["effectiveWeights"]
        for row in week["rankings"]:
            assert row["rosStrengthPercentile"] is None


def test_each_trend_point_is_as_of_that_week(monkeypatch):
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda snapshot=None: {})
    full = power_v2.build_section(_scored_snapshot(4), lens=power_v2.LENS_RESULTS_ONLY)

    for week_number in (1, 2, 3, 4):
        as_of = power_v2.build_section(
            _scored_snapshot(week_number),
            lens=power_v2.LENS_RESULTS_ONLY,
        )
        expected = {r["ownerId"]: r["powerScore"] for r in as_of["currentRanking"]}
        week = next(w for w in full["trend"]["weeks"] if w["week"] == week_number)
        got = {r["ownerId"]: r["powerScore"] for r in week["rankings"]}
        assert got == expected


def test_exact_score_ties_share_standard_competition_rank(monkeypatch):
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda snapshot=None: {})
    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0},
            {"roster_id": 3, "matchup_id": 2, "points": 100.0},
            {"roster_id": 4, "matchup_id": 2, "points": 100.0},
        ]
        for wk in (1, 2, 3, 4)
    }
    out = power_v2.build_section(
        _make_snapshot(rosters, matchups),
        lens=power_v2.LENS_RESULTS_ONLY,
    )
    rows = out["currentRanking"]
    assert {row["powerScore"] for row in rows} == {50.0}
    assert [row["rank"] for row in rows] == [1, 1, 1, 1]
    assert [row["ownerId"] for row in rows] == ["o1", "o2", "o3", "o4"]
