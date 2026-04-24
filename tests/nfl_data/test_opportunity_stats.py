"""Tests for red-zone + 3rd-down opportunity aggregation."""
from __future__ import annotations

import pytest

from src.api import feature_flags
from src.nfl_data import opportunity_stats as op


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _pass(yardline_100, down=1, receiver_id="wr1", name="WR One",
          complete=0, td=0, first_down=0, season=2024):
    return {
        "play_type": "pass", "season": season,
        "down": down, "yardline_100": yardline_100,
        "receiver_player_id": receiver_id,
        "receiver_player_name": name,
        "complete_pass": complete, "touchdown": td, "first_down": first_down,
    }


def _run(yardline_100, down=1, rusher_id="rb1", name="RB One",
         td=0, first_down=0, season=2024):
    return {
        "play_type": "run", "season": season,
        "down": down, "yardline_100": yardline_100,
        "rusher_player_id": rusher_id, "rusher_player_name": name,
        "touchdown": td, "first_down": first_down,
    }


def test_empty_pbp_returns_empty():
    assert op.build_opportunity_from_pbp([]) == []


def test_rz_target_counted():
    plays = [_pass(15, receiver_id="A", complete=1)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    assert len(stats) == 1
    assert stats[0].rz_targets == 1
    assert stats[0].rz_receptions == 1


def test_outside_rz_does_not_count_rz():
    """Mid-field plays don't create a player bucket at all — the
    aggregator only records a player once they have at least one
    qualifying play.  This is intentional: it keeps the
    opportunity table focused on high-value touches only."""
    plays = [_pass(50, receiver_id="A", complete=1)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    # No RZ touches → no bucket.  This is a feature.
    assert len(stats) == 0
    # Same play on 3rd down DOES create a bucket (3D tracking applies).
    plays_3d = [_pass(50, down=3, receiver_id="A", complete=1, first_down=1)]
    stats_3d = op.build_opportunity_from_pbp(plays_3d, season=2024)
    assert len(stats_3d) == 1
    assert stats_3d[0].rz_targets == 0
    assert stats_3d[0].third_down_conversions == 1


def test_gl_carry_inside_5():
    plays = [_run(3, rusher_id="RB", td=1)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    assert stats[0].rz_carries == 1
    assert stats[0].gl_carries == 1
    assert stats[0].rz_touchdowns == 1


def test_third_down_conversion_tracked():
    # 3rd & long pass converted.
    plays = [_pass(45, down=3, receiver_id="X", complete=1, first_down=1)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    assert stats[0].third_down_attempts == 1
    assert stats[0].third_down_conversions == 1
    assert stats[0].third_down_targets == 1


def test_third_down_failed_conversion():
    plays = [_pass(45, down=3, receiver_id="X", complete=1, first_down=0)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    assert stats[0].third_down_conversions == 0
    assert stats[0].third_down_attempts == 1


def test_opportunity_score_monotonic():
    """More RZ touches → higher opportunity score."""
    plays_low = [_pass(15, receiver_id="A", complete=1)]
    plays_high = [
        _pass(15, receiver_id="A", complete=1)
        for _ in range(10)
    ]
    low = op.build_opportunity_from_pbp(plays_low, season=2024)
    high = op.build_opportunity_from_pbp(plays_high, season=2024)
    assert low[0].opportunity_score < high[0].opportunity_score


def test_opportunity_score_capped_at_100():
    """Even a mythical monster season can't exceed 100."""
    plays = [_run(2, rusher_id="R", td=1) for _ in range(100)]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    assert stats[0].opportunity_score <= 100.0


def test_gl_carry_scored_higher_than_rz_carry():
    """Goal-line carries should weight heavier in the score."""
    # Player A: 20 RZ carries (but none at GL).
    a_plays = [_run(15, rusher_id="A") for _ in range(20)]
    # Player B: 20 GL carries (also counted as RZ).
    b_plays = [_run(3, rusher_id="B") for _ in range(20)]
    stats = op.build_opportunity_from_pbp(a_plays + b_plays, season=2024)
    by_id = {s.player_id_gsis: s for s in stats}
    assert by_id["B"].opportunity_score > by_id["A"].opportunity_score


def test_multi_player_separation():
    plays = [
        _pass(15, receiver_id="A", name="A"),
        _pass(15, receiver_id="B", name="B"),
        _pass(15, receiver_id="A", name="A"),
    ]
    stats = op.build_opportunity_from_pbp(plays, season=2024)
    by_id = {s.player_id_gsis: s for s in stats}
    assert by_id["A"].rz_targets == 2
    assert by_id["B"].rz_targets == 1


def test_fetch_flag_off_returns_empty(tmp_path):
    # Default: flag off.
    result = op.fetch_opportunity_stats(
        [2024], _provider=lambda _: [_pass(15)], cache_dir=tmp_path,
    )
    assert result == []


def test_fetch_flag_on_round_trips_through_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
    feature_flags.reload()
    calls = []
    def provider(years):
        calls.append(years)
        return [_pass(15, receiver_id="WR1", complete=1)]
    r1 = op.fetch_opportunity_stats(
        [2024], _provider=provider, cache_dir=tmp_path,
    )
    assert r1 and r1[0]["playerIdGsis"] == "WR1"
    r2 = op.fetch_opportunity_stats(
        [2024], _provider=provider, cache_dir=tmp_path,
    )
    assert r2 == r1
    assert len(calls) == 1  # cache hit on 2nd call


def test_to_dict_shape():
    stats = op.build_opportunity_from_pbp(
        [_pass(15, receiver_id="A")], season=2024,
    )
    d = stats[0].to_dict()
    assert "rzTargets" in d
    assert "opportunityScore" in d
    assert d["season"] == 2024
