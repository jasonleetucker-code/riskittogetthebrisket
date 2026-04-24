"""Tests for src.identity.unified_mapper.

Pins the 3-layer match ladder, the override short-circuit, the
coverage-metric snapshot, and graceful handling of absent data.
"""
from __future__ import annotations

import json

import pytest

from src.identity import unified_mapper


@pytest.fixture(autouse=True)
def _reset():
    unified_mapper.reset_metrics()
    unified_mapper.reload_overrides()
    yield
    unified_mapper.reset_metrics()
    unified_mapper.reload_overrides()


@pytest.fixture
def sleeper_dir():
    """A minimal Sleeper-shaped player directory."""
    return {
        "4017": {
            "player_id": "4017",
            "full_name": "Josh Allen",
            "position": "QB",
            "team": "BUF",
            "gsis_id": "00-0034857",
            "espn_id": "3918298",
        },
        "9479": {
            "player_id": "9479",
            "full_name": "Bijan Robinson",
            "position": "RB",
            "team": "ATL",
            "gsis_id": "00-0039196",
            "espn_id": "4430807",
        },
        "6794": {
            "player_id": "6794",
            "full_name": "Josh Allen",
            "position": "LB",
            "team": "JAX",
            "gsis_id": "00-0034868",
            "espn_id": "4040715",
        },
    }


def test_exact_sleeper_id_wins_with_full_confidence(sleeper_dir):
    got = unified_mapper.resolve_player(sleeper_dir, sleeper_id="4017")
    assert got is not None
    assert got.sleeper_id == "4017"
    assert got.full_name == "Josh Allen"
    assert got.position == "QB"
    assert got.confidence == 1.00
    assert got.match_method == "sleeper_id"


def test_exact_gsis_id_matches(sleeper_dir):
    got = unified_mapper.resolve_player(sleeper_dir, gsis_id="00-0034857")
    assert got is not None
    assert got.sleeper_id == "4017"
    assert got.match_method == "gsis_id"


def test_exact_espn_id_matches(sleeper_dir):
    got = unified_mapper.resolve_player(sleeper_dir, espn_id="4430807")
    assert got is not None
    assert got.sleeper_id == "9479"
    assert got.match_method == "espn_id"


def test_name_plus_team_plus_pos_disambiguates_same_name(sleeper_dir):
    """Two "Josh Allen" exist — QB in BUF, LB in JAX.  Name+team+pos
    must land on the QB."""
    got = unified_mapper.resolve_player(
        sleeper_dir, name="Josh Allen", team="BUF", position="QB",
    )
    assert got is not None
    assert got.sleeper_id == "4017"
    assert got.position == "QB"
    assert got.confidence == 0.98


def test_name_plus_pos_ladder_rung(sleeper_dir):
    got = unified_mapper.resolve_player(
        sleeper_dir, name="Josh Allen", position="LB",
    )
    assert got is not None
    assert got.sleeper_id == "6794"
    assert got.position == "LB"
    assert got.confidence == 0.93


def test_fuzzy_name_match_for_dropped_suffix(sleeper_dir):
    """The nflverse frequently strips 'Jr.' / 'II'; fuzzy must
    still land on the right player."""
    dir_with_suffix = dict(sleeper_dir)
    dir_with_suffix["11000"] = {
        "player_id": "11000",
        "full_name": "Marvin Harrison Jr.",
        "position": "WR",
        "team": "ARI",
        "gsis_id": "00-0039900",
        "espn_id": "4432577",
    }
    got = unified_mapper.resolve_player(
        dir_with_suffix, name="Marvin Harrison", position="WR",
    )
    assert got is not None
    assert got.sleeper_id == "11000"
    assert got.confidence >= 0.85
    assert got.match_method in ("fuzzy_name", "name_pos", "name_unique")


def test_unresolved_returns_none_and_bumps_metric(sleeper_dir):
    got = unified_mapper.resolve_player(
        sleeper_dir, name="Totally Made Up Player", position="QB",
    )
    assert got is None
    snap = unified_mapper.mapping_coverage_snapshot()
    assert snap["metrics"]["unresolved"] >= 1


def test_manual_override_short_circuits_mapper(sleeper_dir, tmp_path):
    """A manual override means: don't even try the Sleeper dir —
    use these values verbatim.  Use case: a practice-squad call-up
    not yet in the Sleeper player dir on the day of the injury."""
    overrides_file = tmp_path / "id_overrides.json"
    overrides_file.write_text(json.dumps({
        "99999": {
            "gsis_id": "00-0099999",
            "espn_id": "9999999",
            "full_name": "Practice Squad Guy",
            "position": "WR",
            "team": "SF",
        }
    }), encoding="utf-8")
    unified_mapper.reload_overrides()
    got = unified_mapper.resolve_player(
        sleeper_dir,
        sleeper_id="99999",
        overrides_path=overrides_file,
    )
    assert got is not None
    assert got.full_name == "Practice Squad Guy"
    assert got.match_method == "manual_override"
    assert got.confidence == 1.00


def test_absent_overrides_file_is_not_an_error(tmp_path):
    """id_overrides.json is optional.  Missing → empty override
    set, not a crash."""
    # Point at a file that doesn't exist.
    missing = tmp_path / "nope.json"
    unified_mapper.reload_overrides()
    got = unified_mapper.resolve_player(
        {"4017": {"player_id": "4017", "full_name": "Josh Allen", "position": "QB", "team": "BUF"}},
        sleeper_id="4017",
        overrides_path=missing,
    )
    assert got is not None


def test_empty_directory_returns_none_without_crashing():
    got = unified_mapper.resolve_player(None, sleeper_id="4017")
    assert got is None
    got2 = unified_mapper.resolve_player({}, name="Josh Allen")
    assert got2 is None


def test_coverage_metric_tracks_hit_rate(sleeper_dir):
    """After N attempts with a known hit rate, snapshot should
    reflect it."""
    for _ in range(8):
        unified_mapper.resolve_player(sleeper_dir, sleeper_id="4017")
    for _ in range(2):
        unified_mapper.resolve_player(sleeper_dir, sleeper_id="ghost")
    snap = unified_mapper.mapping_coverage_snapshot()
    assert snap["metrics"]["resolve_attempts"] == 10
    assert snap["metrics"]["unresolved"] == 2
    assert snap["coverage_pct"] == 0.8


def test_resolve_many_batches_inputs(sleeper_dir):
    inputs = [
        {"sleeper_id": "4017"},
        {"gsis_id": "00-0039196"},
        {"name": "Nobody", "position": "QB"},
    ]
    resolved, unresolved = unified_mapper.resolve_many(sleeper_dir, inputs)
    assert len(resolved) == 2
    assert len(unresolved) == 1
    assert unresolved[0]["name"] == "Nobody"
