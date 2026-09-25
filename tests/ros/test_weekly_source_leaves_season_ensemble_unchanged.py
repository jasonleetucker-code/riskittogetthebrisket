"""C5-PROJ-C weekly source must not move the season / ROS ensemble.

Adding ``sleeperWeeklyProjections`` to the census (a WEEKLY-horizon
member) and shipping its module must leave every season / ROS ensemble
output byte-identical. This pins that with a digest of the full ``repr``
of :func:`build_ros_full_season_ensemble` over a fixed snapshot, computed
on ``origin/main`` BEFORE the weekly source existed (bd37d94ad), and
re-checks it with the weekly module imported and its flag ON — so a
future change that lets the weekly source leak into the default
full-season source set, or into its horizon, fails here.
"""

from __future__ import annotations

import hashlib
import importlib
import tempfile
from pathlib import Path

import pytest

from src.api import feature_flags
from src.bdvm.projections import ProjectionRecord, write_snapshot
from src.ros.projection_ensemble import (
    ProjectionEnsembleError,
    build_ros_full_season_ensemble,
)

SCORING = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rush_yd": 0.1,
    "idp_tkl_solo": 1.5,
    "idp_sack": 4.0,
}

#: sha256 of ``repr(build_ros_full_season_ensemble(...))`` for the snapshot
#: below, measured on origin/main bd37d94ad before this unit's change.
_PINNED_DIGEST = "d6be82c6e95b4e5ba127cde315a3aa8d0b08512e622f7cd96d422f7a8d73dae3"


def _records() -> list[ProjectionRecord]:
    return [
        ProjectionRecord(
            source="clayProjections",
            player_key="shared linebacker",
            position="LB",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            stat_line={"idp_tkl_solo": 80.0, "idp_sack": 3.0},
        ),
        ProjectionRecord(
            source="idpShowProjections",
            player_key="shared linebacker",
            position="LB",
            season=2026,
            as_of="2026-07-21",
            games=17.0,
            fpg=16.0,
            scoring_native=True,
        ),
        ProjectionRecord(
            source="clayProjections",
            player_key="clay only qb",
            position="QB",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            stat_line={"pass_yd": 4100.0, "pass_td": 28.0, "rush_yd": 300.0},
        ),
        ProjectionRecord(
            source="clayProjections",
            player_key="proxy wr",
            position="WR",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            fpg=9.0,
            is_proxy=True,
        ),
    ]


def _digest() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        write_snapshot(_records(), season=2026, as_of="2026-07-21", base_dir=base_dir)
        result = build_ros_full_season_ensemble(
            season=2026, scoring_settings=SCORING, base_dir=base_dir
        )
    return hashlib.sha256(repr(result).encode("utf-8")).hexdigest()


def test_season_ensemble_output_is_byte_identical_to_pre_weekly_main():
    assert _digest() == _PINNED_DIGEST


def test_still_identical_with_weekly_module_loaded_and_flag_on(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS", "1")
    feature_flags.reload()
    try:
        importlib.import_module("src.ros.sleeper_weekly_projections")
        assert _digest() == _PINNED_DIGEST
    finally:
        feature_flags.reload()


def test_weekly_source_cannot_be_requested_for_a_season_horizon():
    """The census horizon guard refuses it rather than returning an
    empty-but-green full-season build."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ProjectionEnsembleError):
            build_ros_full_season_ensemble(
                season=2026,
                scoring_settings=SCORING,
                census_source_keys=("clayProjections", "sleeperWeeklyProjections"),
                base_dir=Path(tmp),
            )
