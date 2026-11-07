"""AL-P6: the point-in-time playoff / title forecast archive (capture only).

Pins, without network or a live board:

* an archived record round-trips (forecast exactly as produced + identity);
* re-archiving the same forecast -- by any transport, with or without the
  keys index -- writes nothing;
* an archive failure never breaks the refresh, and never changes the served
  sim file bytes;
* every identity field is present or ``None`` with a reason in
  ``nullReasons``; a sidecar that does not describe its forecast is never
  trusted;
* the store lives outside every path the scheduled refresh force-adds to git;
* the points model is identified three ways (artifact hash, the source actually
  used, and -- for the fallback constants, which have no file -- their hash),
  without a missing file ever becoming a hash of empty input, and without
  moving ``inputsSha256`` or ``simParamsSha256`` for existing inputs;
* the playoff / title simulators never read the dynasty contract (which is why
  ``inputs.contractGeneration`` is ``None`` by design), held by a behavioural
  tripwire over every canonical contract getter plus a lexical scan of the
  whole simulator path.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import fnmatch
import functools
import hashlib
import importlib.util
import io
import json
import logging
import os
import random
import re
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.ros as ros_pkg
from src.league_intel import sim_calibration
from src.ros import championship, forecast_archive, playoff_sim, scrape, team_strength

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPUTED_AT = "2026-10-01T12:00:00+00:00"

PLAYOFF_PAYLOAD = {
    "playoffOdds": [
        {"ownerId": "o1", "displayName": "A", "playoffOdds": 0.2, "byeOdds": 0.05},
        {"ownerId": "o2", "displayName": "B", "playoffOdds": 0.8, "byeOdds": 0.4},
    ],
    "n_simulations": 6000,
    "converged": True,
    "playoffSeeds": 7,
    "byeSeeds": 1,
    "pointsModelSource": "fallback-constants",
    "pointsModelGeneratedAt": None,
}
CHAMP_PAYLOAD = {
    "championshipOdds": [
        {"ownerId": "o1", "displayName": "A", "championshipOdds": 0.03},
        {"ownerId": "o2", "displayName": "B", "championshipOdds": 0.31},
    ],
    "n_simulations": 10000,
    "playoffSeeds": 7,
    "byeSeeds": 1,
}


def _snapshot(*, leg=4, last_scored=3):
    season = SimpleNamespace(
        season="2026",
        league_id="L2026",
        league={"settings": {"leg": leg, "last_scored_leg": last_scored}},
        rosters=[{"owner_id": "o1", "roster_id": 1, "players": ["p1"]}],
        matchups_by_week={1: [{"roster_id": 1, "points": 101.5, "matchup_id": 1}]},
        winners_bracket=[],
        losers_bracket=[],
    )
    return SimpleNamespace(
        root_league_id="L2026",
        generated_at="2026-10-01T11:59:00+00:00",
        seasons=[season],
        current_season=season,
        managers=SimpleNamespace(ordered_managers=lambda: [SimpleNamespace(owner_id="o1")]),
    )


@pytest.fixture
def ros_tmp(tmp_path, monkeypatch):
    """Relocate every ROS data read/write and the archive into ``tmp_path``."""
    ros_dir = tmp_path / "ros"
    (ros_dir / "aggregate").mkdir(parents=True)
    (ros_dir / "aggregate" / "latest.json").write_text(
        json.dumps({"aggregatedAt": "2026-10-01T11:00:00+00:00", "players": []}), encoding="utf-8"
    )
    (ros_dir / "team_strength").mkdir()
    (ros_dir / "team_strength" / "latest.json").write_text("[]", encoding="utf-8")
    archive = tmp_path / "forecast_archive"
    monkeypatch.setattr(ros_pkg, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(scrape, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(team_strength, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(forecast_archive, "DEFAULT_DIR", archive)
    monkeypatch.setattr(team_strength, "resolve_snapshot_league_key", lambda snap: None)
    # No developer-local ``sim_points_model.json`` may leak into a test: the
    # default is an ABSENT artifact (the fallback constants), as on the runner.
    model_path = tmp_path / "league_intel" / "sim_points_model.json"
    monkeypatch.setattr(sim_calibration, "MODEL_PATH", model_path)
    return SimpleNamespace(ros=ros_dir, archive=archive, model_path=model_path)


def _doc(payload):
    return {"computedAt": COMPUTED_AT, **payload}


# ── round trip ──────────────────────────────────────────────────────


def test_archived_record_round_trips(ros_tmp):
    doc = _doc(PLAYOFF_PAYLOAD)
    sim = ros_tmp.ros / "sims" / "latest_playoff.json"
    sim.parent.mkdir(parents=True)
    sim.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)

    identity = forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context, sim_path=sim
    )

    records = list(forecast_archive.iter_records(ros_tmp.archive))
    assert len(records) == 1
    rec = records[0]
    assert rec["forecast"] == doc  # the forecast exactly as produced
    assert rec["computedAt"] == COMPUTED_AT
    assert rec["leagueKey"] == "dynasty_main"
    assert rec["kind"] == "playoff"
    assert (rec["season"], rec["week"], rec["lastScoredWeek"]) == ("2026", 4, 3)
    assert rec["nSimulations"] == 6000
    assert rec["producer"] == forecast_archive.PRODUCER
    assert rec["transport"] == forecast_archive.TRANSPORT_PRODUCER
    assert rec["forecastSha256"] == forecast_archive.canonical_sha256(doc)
    assert rec["key"] == forecast_archive.record_key(
        "dynasty_main", "playoff", COMPUTED_AT, rec["forecastSha256"]
    )
    assert rec["model"]["simParams"]["bestBall"] is True
    assert rec["model"]["simParamsSha256"] == forecast_archive.canonical_sha256(
        rec["model"]["simParams"]
    )
    assert rec["inputs"]["rosAggregatedAt"] == "2026-10-01T11:00:00+00:00"
    # Monthly rotation by the forecast's own stamp.
    assert forecast_archive.ledger_files(ros_tmp.archive) == [
        ros_tmp.archive / "forecasts-2026-10.jsonl"
    ]
    # The sidecar carries the identity, never the forecast.
    sidecar = json.loads(
        (ros_tmp.ros / "sims" / "latest_playoff.identity.json").read_text(encoding="utf-8")
    )
    assert sidecar == json.loads(json.dumps(identity))
    assert "forecast" not in sidecar


def test_published_file_plus_sidecar_reproduces_the_producer_record(ros_tmp):
    doc = _doc(CHAMP_PAYLOAD)
    sim = ros_tmp.ros / "sims" / "latest_championship.json"
    sim.parent.mkdir(parents=True)
    sim.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    context = forecast_archive.collect_context(_snapshot(), best_ball=False)
    forecast_archive.archive_safely(
        league_key="dynasty_main",
        kind="championship",
        forecast=doc,
        context=context,
        sim_path=sim,
        base=ros_tmp.archive / "elsewhere",  # the runner's store, discarded
    )
    side = forecast_archive.sidecar_path(sim).read_text(encoding="utf-8")

    status = forecast_archive.ingest_text(
        sim.read_text(encoding="utf-8"),
        side,
        league_key="dynasty_main",
        kind="championship",
        transport=forecast_archive.TRANSPORT_PUBLISHED_FILE,
        base=ros_tmp.archive,
    )

    assert status == "written"
    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["forecast"] == doc
    assert rec["model"] == json.loads(side)["model"]
    assert rec["inputs"] == json.loads(side)["inputs"]
    (runner_rec,) = forecast_archive.iter_records(ros_tmp.archive / "elsewhere")
    assert rec["key"] == runner_rec["key"]  # one forecast, one key, any transport


# ── idempotency ─────────────────────────────────────────────────────


def test_rearchiving_the_same_forecast_is_a_no_op(ros_tmp):
    doc = _doc(PLAYOFF_PAYLOAD)
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    for _ in range(3):
        forecast_archive.archive_safely(
            league_key="dynasty_main", kind="playoff", forecast=doc, context=context
        )
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 1

    # Losing the keys index must not turn into a duplicate line.
    (ros_tmp.archive / forecast_archive.INDEX_NAME).unlink()
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context
    )
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 1

    # Nor may a crash between the ledger append and the index append.
    index = ros_tmp.archive / forecast_archive.INDEX_NAME
    index.write_text("", encoding="utf-8")
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context
    )
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 1


def test_identity_is_not_part_of_the_key(ros_tmp):
    """The same forecast arriving with an untrustworthy sidecar (identity
    ``None``) is the SAME calibration sample, never a second one."""
    doc = _doc(PLAYOFF_PAYLOAD)
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context
    )
    status = forecast_archive.ingest_text(
        json.dumps(doc),
        "{not json",
        league_key="dynasty_main",
        kind="playoff",
        transport=forecast_archive.TRANSPORT_PUBLISHED_FILE,
        base=ros_tmp.archive,
    )
    assert status == "duplicate"
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 1


def test_a_new_forecast_is_a_new_record(ros_tmp):
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=_doc(PLAYOFF_PAYLOAD), context=context
    )
    later = {**_doc(PLAYOFF_PAYLOAD), "computedAt": "2026-10-01T14:00:00+00:00"}
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=later, context=context
    )
    forecast_archive.archive_safely(
        league_key="dynasty_new", kind="playoff", forecast=later, context=context
    )
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 3


# ── never fail the refresh, never change what is served ─────────────


def _run_refresh(ros_tmp, monkeypatch):
    stamps = iter([COMPUTED_AT, "2026-10-01T12:00:05+00:00"])
    monkeypatch.setattr(scrape, "_now", lambda: next(stamps))
    cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id="L2026", best_ball=True)

    # C5-PLAY-01: ONE simulation per refresh.  The championship file is the
    # playoff forecast reshaped, so a second simulator is never called — the
    # guard below fails the refresh if anything tries.
    def _no_second_simulation(*args, **kwargs):
        raise AssertionError("the refresh ran a second, independent simulation")

    with (
        patch("src.public_league.snapshot.build_public_snapshot", return_value=_snapshot()),
        patch.object(playoff_sim, "simulate_playoff_odds", return_value=dict(PLAYOFF_PAYLOAD)),
        patch.object(championship, "simulate_championship_odds", _no_second_simulation),
    ):
        out = scrape._refresh_sim_caches_for_league(cfg, "dynasty_main")
    return out


def _expected_served_bytes():
    """The served files exactly as the writer produces them: the playoff
    forecast, and (C5-PLAY-01) the SAME forecast reshaped for the
    championship file, stamped with the forecast's own ``computedAt``."""
    return (
        json.dumps({"computedAt": COMPUTED_AT, **PLAYOFF_PAYLOAD}, indent=2),
        json.dumps(
            {
                "computedAt": COMPUTED_AT,
                **championship.championship_from_forecast(dict(PLAYOFF_PAYLOAD)),
            },
            indent=2,
        ),
    )


def test_served_sim_files_are_byte_identical_to_the_pre_archive_writer(ros_tmp, monkeypatch):
    out = _run_refresh(ros_tmp, monkeypatch)
    playoff, champ = _expected_served_bytes()
    assert out["playoff"].read_text(encoding="utf-8") == playoff
    assert out["championship"].read_text(encoding="utf-8") == champ
    assert len(list(forecast_archive.iter_records(ros_tmp.archive))) == 2


@pytest.mark.parametrize(
    "target",
    ["collect_context", "build_identity", "append_record", "write_identity_sidecar_safely"],
)
def test_archive_failure_does_not_break_the_refresh(ros_tmp, monkeypatch, target):
    def boom(*args, **kwargs):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(forecast_archive, target, boom)
    out = _run_refresh(ros_tmp, monkeypatch)

    assert out is not None and set(out) == {"playoff", "championship"}
    playoff, champ = _expected_served_bytes()
    assert out["playoff"].read_text(encoding="utf-8") == playoff
    assert out["championship"].read_text(encoding="utf-8") == champ


def test_unwritable_archive_directory_does_not_break_the_refresh(ros_tmp, monkeypatch):
    ros_tmp.archive.parent.mkdir(parents=True, exist_ok=True)
    ros_tmp.archive.write_text("a file where the archive directory should be", encoding="utf-8")
    out = _run_refresh(ros_tmp, monkeypatch)
    assert set(out) == {"playoff", "championship"}
    assert out["playoff"].read_text(encoding="utf-8") == _expected_served_bytes()[0]


# ── identity: present, or None with a reason ────────────────────────

IDENTITY_FIELDS = ("leagueKey", "computedAt", "season", "week", "lastScoredWeek", "nSimulations")
MODEL_FIELDS = ("codeSha", "simParamsSha256")
INPUT_FIELDS = (
    "inputsSha256",
    "leagueSnapshotSha256",
    "teamStrengthFileSha256",
    "teamStrengthFileFresh",
    "rosAggregateSha256",
    "rosAggregatedAt",
    "pointsModelFileSha256",
    "pointsModelSource",
    "pointsModelFallbackSha256",
    "contractGeneration",
)


def _assert_present_or_explained(identity):
    nulls = identity["nullReasons"]
    for field in IDENTITY_FIELDS:
        assert field in identity
        if identity[field] is None:
            assert nulls.get(field), f"{field} is None with no reason"
    for field in MODEL_FIELDS:
        assert field in identity["model"]
        if identity["model"][field] is None:
            assert nulls.get(f"model.{field}"), f"model.{field} is None with no reason"
    for field in INPUT_FIELDS:
        assert field in identity["inputs"]
        if identity["inputs"][field] is None:
            assert nulls.get(f"inputs.{field}"), f"inputs.{field} is None with no reason"


def test_identity_fields_present_on_a_complete_context(ros_tmp):
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    identity = forecast_archive.build_identity(
        league_key="dynasty_main", kind="playoff", forecast=_doc(PLAYOFF_PAYLOAD), context=context
    )
    _assert_present_or_explained(identity)
    assert identity["inputs"]["leagueSnapshotSha256"]
    assert identity["inputs"]["teamStrengthFileSha256"]
    assert identity["inputs"]["rosAggregateSha256"]
    assert identity["inputs"]["inputsSha256"]
    # The simulators do not read the dynasty contract; claiming a generation
    # would fabricate an input.
    assert identity["inputs"]["contractGeneration"] is None
    assert identity["nullReasons"]["inputs.contractGeneration"]


# ── points-model identity (RPA-COL-022) ─────────────────────────────

#: The ``inputs`` keys that existed before the points-model identity fields.
#: ``inputsSha256`` hashed exactly these (the ``*Sha256`` ones plus
#: ``rosAggregatedAt``) and must keep doing so for the same inputs.
LEGACY_FINGERPRINT_KEYS = (
    "leagueSnapshotSha256",
    "teamStrengthFileSha256",
    "rosAggregateSha256",
    "rosAggregatedAt",
    "pointsModelFileSha256",
)
LEGACY_INPUT_KEYS = LEGACY_FINGERPRINT_KEYS + (
    "leagueSnapshotScope",
    "leagueSnapshotGeneratedAt",
    "teamStrengthFileFresh",
    "contractGeneration",
    "inputsSha256",
)
SHA256_OF_EMPTY_INPUT = hashlib.sha256(b"").hexdigest()


def _write_points_model(path, *, schema_version=sim_calibration.SCHEMA_VERSION, per_point=2.5):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": schema_version,
                "generatedAt": "2026-09-20T00:00:00+00:00",
                "sampleSize": 1415,
                "scale": {"rosValuePerPoint": per_point},
                "byPosition": {"QB": {"cv": 0.3}},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fallback_constants_are_named_and_hashed_never_an_empty_file_hash(ros_tmp):
    """No artifact -> ``None`` file hash, ``fallback-constants``, a hash of the constants."""
    assert not ros_tmp.model_path.exists()
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    inputs = context["inputs"]
    nulls = context["nullReasons"]

    assert inputs["pointsModelFileSha256"] is None
    assert inputs["pointsModelFileSha256"] != SHA256_OF_EMPTY_INPUT
    assert inputs["pointsModelSource"] == "fallback-constants"
    assert inputs["pointsModelSource"] == sim_calibration.DEFAULT_POINTS_MODEL.source
    # The constants' identity is the hash of the very model simParams carries,
    # so it is independently recomputable from the same record.
    pinned = context["model"]["simParams"]["pointsModel"]
    assert pinned["source"] == "fallback-constants"
    assert inputs["pointsModelFallbackSha256"] == forecast_archive.canonical_sha256(pinned)
    assert inputs["pointsModelFallbackSha256"] == forecast_archive.canonical_sha256(
        sim_calibration.PointsModel().to_dict()
    )
    # The null is explained as the fallback being in use, not just "no file".
    assert nulls["inputs.pointsModelFileSha256"] == "fallback_constants_in_use:file_absent"
    assert "inputs.pointsModelFallbackSha256" not in nulls
    assert "inputs.pointsModelSource" not in nulls


def test_fallback_hash_changes_when_the_fallback_constants_change(ros_tmp, monkeypatch):
    before = forecast_archive.collect_context(_snapshot(), best_ball=True)["inputs"]
    monkeypatch.setitem(sim_calibration.FALLBACK_CV_BY_POSITION, "QB", 0.99)
    # A fresh ``PointsModel`` copies the table when it is built, so it sees the
    # patched constants.
    after = forecast_archive.collect_context(_snapshot(), best_ball=True)["inputs"]
    assert before["pointsModelFallbackSha256"] != after["pointsModelFallbackSha256"]


def test_calibrated_artifact_is_hashed_and_named(ros_tmp):
    _write_points_model(ros_tmp.model_path)
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    inputs = context["inputs"]
    nulls = context["nullReasons"]

    assert (
        inputs["pointsModelFileSha256"]
        == hashlib.sha256(ros_tmp.model_path.read_bytes()).hexdigest()
    )
    assert inputs["pointsModelSource"] == "calibrated"
    # A calibrated model's identity is the file; there is no fallback hash.
    assert inputs["pointsModelFallbackSha256"] is None
    assert nulls["inputs.pointsModelFallbackSha256"] == "points_model_is_not_the_fallback"
    assert "inputs.pointsModelFileSha256" not in nulls
    assert context["model"]["simParams"]["pointsModel"]["source"] == "calibrated"


def test_a_present_but_rejected_artifact_records_both_facts(ros_tmp):
    """The file exists but the loader refused it: the run used the constants."""
    _write_points_model(ros_tmp.model_path, schema_version=99)
    inputs = forecast_archive.collect_context(_snapshot(), best_ball=True)["inputs"]

    assert (
        inputs["pointsModelFileSha256"]
        == hashlib.sha256(ros_tmp.model_path.read_bytes()).hexdigest()
    )
    assert inputs["pointsModelSource"] == "fallback-constants"
    assert inputs["pointsModelFallbackSha256"] == forecast_archive.canonical_sha256(
        sim_calibration.PointsModel().to_dict()
    )


def test_points_model_identity_describes_the_model_simparams_pinned(ros_tmp, monkeypatch):
    """One load per context: the two descriptions of the model cannot disagree."""
    calls = []
    real = sim_calibration.load_points_model

    def counting(path=None):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(sim_calibration, "load_points_model", counting)
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    assert len(calls) == 1
    assert (
        context["inputs"]["pointsModelSource"]
        == (context["model"]["simParams"]["pointsModel"]["source"])
    )


def test_a_new_record_carries_the_points_model_identity_end_to_end(ros_tmp):
    doc = _doc(PLAYOFF_PAYLOAD)
    sim = ros_tmp.ros / "sims" / "latest_playoff.json"
    sim.parent.mkdir(parents=True)
    sim.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    forecast_archive.archive_safely(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context, sim_path=sim
    )

    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["inputs"]["pointsModelFileSha256"] is None
    assert rec["inputs"]["pointsModelSource"] == "fallback-constants"
    assert rec["inputs"]["pointsModelFallbackSha256"] == forecast_archive.canonical_sha256(
        rec["model"]["simParams"]["pointsModel"]
    )
    reason = rec["nullReasons"]["inputs.pointsModelFileSha256"]
    assert reason.startswith("fallback_constants_in_use")
    # The sidecar (what the box joins) carries the same identity.
    sidecar = json.loads(
        (ros_tmp.ros / "sims" / "latest_playoff.identity.json").read_text(encoding="utf-8")
    )
    assert sidecar["inputs"] == json.loads(json.dumps(rec["inputs"]))


def test_existing_identity_is_unchanged_by_the_new_fields(ros_tmp):
    """New records differ from old ones ONLY by the added keys."""
    snapshot = _snapshot()
    context = forecast_archive.collect_context(snapshot, best_ball=True)
    inputs = context["inputs"]

    assert set(inputs) == set(LEGACY_INPUT_KEYS) | {
        "pointsModelSource",
        "pointsModelFallbackSha256",
    }
    assert inputs["leagueSnapshotSha256"] == forecast_archive._league_snapshot_sha(snapshot, {})
    assert (
        inputs["teamStrengthFileSha256"]
        == hashlib.sha256((ros_tmp.ros / "team_strength" / "latest.json").read_bytes()).hexdigest()
    )
    assert (
        inputs["rosAggregateSha256"]
        == hashlib.sha256((ros_tmp.ros / "aggregate" / "latest.json").read_bytes()).hexdigest()
    )
    assert inputs["rosAggregatedAt"] == "2026-10-01T11:00:00+00:00"
    # The fingerprint is byte-for-byte what it was before the new fields: the
    # hash of exactly the legacy keys.
    assert inputs["inputsSha256"] == forecast_archive.canonical_sha256(
        {k: inputs[k] for k in LEGACY_FINGERPRINT_KEYS}
    )
    # ``simParams`` carries the same five parameter groups as before, so
    # ``simParamsSha256`` still pins exactly them.
    params = context["model"]["simParams"]
    assert set(params) == {
        "bestBall",
        "playoffSim",
        "rosEvidenceMethod",
        "championship",
        "pointsModel",
    }
    assert context["model"]["simParamsSha256"] == forecast_archive.canonical_sha256(params)


# ── contract generation: not an input of these simulators ───────────

#: The claim under test: the playoff / title simulators never read the dynasty
#: contract, so ``inputs.contractGeneration`` is ``None`` by design. It is held
#: by TWO guards that fail differently, and neither is enough alone:
#:
#: * a LEXICAL scan (below) -- cheap and exact about where a read would be
#:   written, but blind to anything not spelled out (a helper that reads it, a
#:   name built at runtime);
#: * a BEHAVIOURAL tripwire (further down) -- arms every canonical contract
#:   getter, runs the real forecast code, and fails if one is called, however
#:   the call was spelled, but only for the paths the fixtures execute.
#:
#: Directories whose every ``*.py`` is on the simulator path unless it is listed
#: in ``GUARD_EXCLUDED``. A new module is therefore scanned by default.
GUARDED_DIRS = ("src/ros", "src/ros/sources", "src/public_league")

#: The original six, kept as a floor so the guard can never silently narrow
#: back to them (see ``test_guard_covers_the_whole_simulator_path``).
SIMULATOR_INPUT_MODULES = (
    "playoff_sim",
    "championship",
    "team_strength",
    "lineup",
    "availability",
    "game_day_sim",
)

#: Modules that are NOT on the playoff / title simulator path, each with the
#: reason. Archive and analytics modules sit here because they legitimately talk
#: ABOUT the board (and the archive is the one place that will stamp
#: ``contract_generation`` if a simulator ever reads it). The behavioural
#: tripwire still executes the archive's ``collect_context``.
GUARD_EXCLUDED = {
    "src/ros/forecast_archive.py": (
        "the forecast archive itself: the comment on its null ``contractGeneration`` "
        "says to stamp ``trade_analyze_runtime.contract_generation`` there the day a "
        "simulator reads the board"
    ),
    "src/ros/game_day_archive.py": "Game Day prediction archive (append-only store)",
    "src/ros/game_day_capture.py": "scheduled caller of the Game Day archive",
    "src/ros/game_day_live.py": (
        "Game Day live collector: the current-week scoring lens, a different "
        "simulation from the playoff / title Monte Carlo; reads "
        "``src.api.matchup_intel`` for its own lineup lens. ONE of its functions "
        "is on the simulator path all the same: ``persisted_players_meta`` (a disk "
        "read of the persisted Sleeper players DB) is reached from the best-ball "
        "pre-sim -- see 'Where the stubs stop' below"
    ),
    "src/ros/pick_forecast_snapshot.py": (
        "dynasty-side pick-forecast CAPTURE (AL-P4): consumes "
        "``roster_intelligence`` by design, and nothing in the simulators imports it"
    ),
    "src/ros/power_snapshots.py": "immutable weekly Power Rankings snapshots (an archive)",
    "src/ros/projection_source_census.py": "projection-source capability census (analytics)",
    "src/public_league/public_contract.py": (
        "the public-section assembler: ``_team_assignment_section`` is handed the "
        "contract by its HTTP caller, and its field names are the public/private "
        "DENYLIST. No simulator calls it"
    ),
}

#: Reads that are lexically contract-adjacent but are not contract reads, keyed
#: ``(file, import)``. Anything else the same file imports from the same module
#: is NOT covered: the key names the exact imported symbol.
CONTRACT_ADJACENT_IMPORTS = {
    ("src/ros/playoff_sim.py", "src.api.matchup_intel:players_meta_for_rosters"): (
        "``_presim_availability`` uses ``players_meta_for_rosters``, which reads "
        "SLEEPER PLAYER METADATA (the persisted players DB, else the shared "
        "``players/nfl`` client) to find injured / bye players. It touches no "
        "board, and ``matchup_intel`` -> ``roster_intelligence`` -> ``data_contract`` "
        "is only an import-time module load. "
        "``test_best_ball_presim_availability_reads_no_contract`` runs this exact "
        "call under the tripwire"
    ),
}

#: Names that mean "the loaded dynasty contract" (or its generation, or a
#: helper that reads one handed to it). Every other ``server.latest_*`` cache
#: is added at scan time from ``_static_host_cache_names`` (below).
CONTRACT_READERS = (
    "latest_contract_data",
    "latest_data",
    "contract_generation",
    "build_api_data_contract",
    "contract_roster_pools",
    "contract_slot_eligibility",
    "capture_contract_roster_settings",
)
CONTRACT_VALUE_FIELDS = ("rankDerivedValue", "canonicalConsensusRank")
#: Import-path fragments of the modules that read a contract. ``roster_intelligence``
#: and ``team_assignment`` take the contract as an argument; ``matchup_intel``
#: imports ``roster_intelligence`` (and so ``data_contract``) at load time.
CONTRACT_MODULES = (
    "data_contract",
    "trade_analyze_runtime",
    "roster_intelligence",
    "team_assignment",
    "matchup_intel",
)

#: In a string, the raw board's export file name: ``exports/latest/dynasty_data_<date>.json``
#: and its ``data/`` and repo-root copies. A module that builds that path reads
#: the board from disk, which no getter trap sees. (Today every reader is in
#: ``server.py``, ``src/api``, ``src/sources``, ``src/history``,
#: ``src/consensus_edge``, ``src/model_registry`` or ``scripts/``: none is in a
#: guarded directory, and this keeps it that way.)
BOARD_EXPORT_FRAGMENT = "dynasty_data_"

#: Every ``server`` module global named ``latest_*`` is a cached copy of a
#: served payload: the contract and ``latest_data``, the runtime / startup /
#: array / compact projections, each one's encoded bytes, gzip bytes and ETag,
#: and the data-source descriptor. The tripwire traps the PREFIX, so a cache
#: added tomorrow is trapped with no edit here.
HOST_CACHE_PREFIX = "latest_"


def _host_cache_names_in(source):
    """Every ``latest_*`` name ``source`` binds at module scope, read with ``ast``:
    assignments (plain, annotated, unpacked, inside ``if`` / ``try``), imports,
    ``def`` / ``class``, and ``global`` declarations inside functions."""
    tree = ast.parse(source)
    names = set()
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)  # a module-level ``def`` is a module attribute too
            continue  # its body binds locals, not module globals
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        stack.extend(ast.iter_child_nodes(node))
    # ``global latest_x`` in a function rebinds -- or creates -- a module global.
    names.update(n for node in ast.walk(tree) if isinstance(node, ast.Global) for n in node.names)
    return tuple(sorted(n for n in names if n.startswith(HOST_CACHE_PREFIX)))


@functools.lru_cache(maxsize=1)
def _static_host_cache_names():
    """The host caches ``server.py`` declares, enumerated STATICALLY.

    Deliberately not ``import server``. This file's pattern is to stand in for
    the host (``_arm_contract_tripwire``) because the claim under test is that
    the forecast path runs with NO host loaded -- the refresh runner has none.
    Importing the real module would load the FastAPI app, its ~100 routes and
    the scraper bridge into every run of this file (about 3 s), and it raises
    at import unless the dev-login override is set (``tests/conftest.py`` sets
    it; production refuses it). Where an earlier test in the session HAS loaded
    ``server``, ``_host_cache_names`` adds its live globals, so a name created
    at runtime is not missed.
    """
    return _host_cache_names_in((REPO_ROOT / "server.py").read_text(encoding="utf-8"))


def _host_cache_names():
    """The static host caches, plus -- where ``server`` is already loaded --
    every ``latest_*`` name in its live globals (the dynamic enumeration)."""
    names = set(_static_host_cache_names())
    host = sys.modules.get("server")
    if host is not None:
        names.update(n for n in vars(host) if n.startswith(HOST_CACHE_PREFIX))
    return sorted(names)


def _contract_reads_in(source):
    """Every lexical form of a contract read in ``source``: ``(line, kind, detail)``."""
    tree = ast.parse(source)
    readers = (*CONTRACT_READERS, *_static_host_cache_names())
    # Bare string statements (docstrings) are prose, never a read.
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            module = getattr(node, "module", None) or ""
            if any(frag in text for text in [module, *names] for frag in CONTRACT_MODULES):
                hits.append((node.lineno, "import", f"{module}:{','.join(names)}"))
            hits += [(node.lineno, "import", n) for n in names if n in readers]
        elif isinstance(node, ast.Name) and node.id in readers:
            hits.append((node.lineno, "name", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in readers:
            hits.append((node.lineno, "attribute", node.attr))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in (*CONTRACT_VALUE_FIELDS, *readers):
                # ``getattr(server, "latest_contract_data")`` is a string, not a name.
                hits.append((node.lineno, "string", node.value))
            elif BOARD_EXPORT_FRAGMENT in node.value and id(node) not in prose:
                hits.append((node.lineno, "board export path", node.value))
    return hits


def _repo_relative(path):
    return path.relative_to(REPO_ROOT).as_posix()


def _unexcused(rel, hits):
    """``hits`` minus the named, justified adjacent imports of file ``rel``."""
    return [
        hit
        for hit in hits
        if not (hit[1] == "import" and (rel, hit[2]) in CONTRACT_ADJACENT_IMPORTS)
    ]


def _contract_reads(path):
    return _unexcused(_repo_relative(path), _contract_reads_in(path.read_text(encoding="utf-8")))


def _guarded_modules():
    """``{repo-relative path: Path}`` for every scanned simulator-path module."""
    found = {}
    for directory in GUARDED_DIRS:
        for path in sorted((REPO_ROOT / directory).glob("*.py")):
            rel = _repo_relative(path)
            if rel not in GUARD_EXCLUDED:
                found[rel] = path
    return found


def test_simulators_do_not_read_the_dynasty_contract():
    """Why ``inputs.contractGeneration`` is ``None``: it is not a simulator input.

    The playoff / title Monte Carlo runs on the ROS aggregate (the seasonal
    lane) and the persisted team strength, both pinned in ``inputs``. Stamping
    the dynasty board's generation would claim an input the forecast never read
    -- and the refresh runner has no contract loaded at all. If a simulator ever
    starts reading the board, this fails: stamp
    ``trade_analyze_runtime.contract_generation`` into ``contractGeneration``
    (and drop the null reason) in the same change.

    This is the LEXICAL half of "tripwire + scan" (the other is
    ``test_forecast_production_path_reads_no_contract`` and its siblings). It
    scans every ``src/ros``, ``src/ros/sources`` and ``src/public_league``
    module except the archive / analytics ones in ``GUARD_EXCLUDED``, for
    imports of the contract modules and helpers, contract-reading names and
    attributes, ``getattr(host, "latest_contract_data")`` strings, and the
    board's value fields. It cannot see a read that is not spelled out; the
    tripwire can.
    """
    offenders = {}
    for rel, path in _guarded_modules().items():
        hits = _contract_reads(path)
        if hits:
            offenders[rel] = hits
    assert not offenders, f"simulator-path modules now read the dynasty contract: {offenders}"


def test_guard_covers_the_whole_simulator_path():
    """The scan cannot silently shrink back to a handful of files."""
    guarded = _guarded_modules()
    for name in SIMULATOR_INPUT_MODULES:
        assert f"src/ros/{name}.py" in guarded
    # The modules a first review found the original six-file guard missing.
    for name in (
        "aggregate",
        "mapping",
        "parse",
        "scrape",
        "power_v2",
        "direction",
        "trade_deadline",
    ):
        assert f"src/ros/{name}.py" in guarded, name
    assert "src/ros/sources/__init__.py" in guarded
    # ``src/public_league`` is the snapshot / odds / structure the simulator imports.
    for name in ("playoff_odds", "playoff_structure", "snapshot", "draft_order"):
        assert f"src/public_league/{name}.py" in guarded, name

    # Every exclusion is real, lives under a guarded directory, and says why.
    for rel, reason in GUARD_EXCLUDED.items():
        assert (REPO_ROOT / rel).is_file(), f"stale exclusion: {rel}"
        assert any(rel.startswith(d + "/") for d in GUARDED_DIRS), rel
        assert len(reason) > 20, f"{rel} is excluded without a reason"


def test_contract_adjacent_exceptions_are_live_and_justified():
    """An exception that no longer matches the source would be dead weight that
    silently re-widens: delete it, or it grants a free pass to a different import."""
    for (rel, detail), reason in CONTRACT_ADJACENT_IMPORTS.items():
        hits = _contract_reads_in((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert any(
            h[1] == "import" and h[2] == detail for h in hits
        ), f"{rel} no longer imports {detail}; remove the exception"
        assert len(reason) > 40
    # ... and the exception is exactly one symbol, not the module: a second
    # import from ``matchup_intel`` in the same file is still an offender.
    widened = (REPO_ROOT / "src/ros/playoff_sim.py").read_text(
        encoding="utf-8"
    ) + "\nfrom src.api.matchup_intel import build_matchup_intel\n"
    still_flagged = [
        h[2] for h in _unexcused("src/ros/playoff_sim.py", _contract_reads_in(widened))
    ]
    assert "src.api.matchup_intel:build_matchup_intel" in still_flagged
    assert "src.api.matchup_intel:players_meta_for_rosters" not in still_flagged


@pytest.mark.parametrize(
    "source",
    [
        "from src.api.trade_analyze_runtime import contract_generation",
        "from src.api import trade_analyze_runtime",
        "from src.api.data_contract import contract_roster_pools",
        "from .data_contract import build_api_data_contract",
        "import server\nserver.latest_contract_data",
        "x = getattr(srv, 'latest_contract_data', None)",
        "x = getattr(mod, 'latest_data')",
        "from src.api import roster_intelligence",
        "from src.api.roster_intelligence import build_league_roster_intelligence",
        "from src.api import team_assignment",
        "from src.api.team_assignment import build_section",
        "from src.api import matchup_intel as mi",
        "from src.api.matchup_intel import build_matchup_intel",
        "row['rankDerivedValue']",
        "row.get('canonicalConsensusRank')",
        # Every host cache, not only the two the scan started with.
        "import server\nserver.latest_runtime_data",
        "from server import latest_startup_data_bytes as cached",
        "x = getattr(srv, 'latest_compact_data_etag', None)",
        # The board's export file, however the path is spelled.
        "paths = sorted(root.glob('dynasty_data_*.json'))",
        "p = root / 'exports' / 'latest' / f'dynasty_data_{day}.json'",
    ],
)
def test_contract_scan_flags_every_form_it_claims_to(source):
    assert _contract_reads_in(source), source


@pytest.mark.parametrize(
    "source",
    [
        '"""latest_contract_data is mentioned only in prose."""',
        "# trade_analyze_runtime.contract_generation, in a comment",
        "from src.ros import lineup\nfrom src.public_league import playoff_odds",
        "from src.roster_intel.core import build_meaningful_core",
        "value = row['rosValue']",
        '"""Never opens exports/latest/dynasty_data_*.json."""',
        # Exact host names, not the prefix: a local ``latest_*`` is no host cache.
        "latest_playoff = sims / 'latest_playoff.json'",
    ],
)
def test_contract_scan_does_not_flag_prose_or_unrelated_imports(source):
    assert _contract_reads_in(source) == [], source


# ── the behavioural half: arm every contract getter, run the real code ──

#: Every canonical entry point that READS (or builds, or stamps the generation
#: of) the loaded dynasty contract, as ``(module, names)``. ``roster_intelligence``
#: and ``team_assignment`` reach the board through ``contract_roster_pools``,
#: which they bind with ``from ... import``; ``_arm_contract_tripwire`` replaces
#: every such binding, not only the defining module's.
CONTRACT_GETTERS = (
    (
        "src.api.data_contract",
        (
            "build_api_data_contract",
            "contract_roster_pools",
            "contract_slot_eligibility",
            "capture_contract_roster_settings",
            "build_rankings_delta_payload",
            "build_api_startup_payload",
        ),
    ),
    ("src.api.trade_analyze_runtime", ("contract_generation",)),
    (
        "src.api.roster_intelligence",
        ("build_league_roster_intelligence", "get_team_roster_intelligence", "team_weakness_for"),
    ),
    ("src.api.team_assignment", ("build_section",)),
)
#: The host's module globals: ``server.latest_contract_data`` is how ``src/``
#: reaches the served board (``getattr(server_module, "latest_contract_data")``),
#: and every other ``latest_*`` global is a cached copy of a served payload.
#: All are trapped by ``HOST_CACHE_PREFIX``; ``_host_cache_names`` lists them.
#:
#: The raw board on disk: any file named like this, wherever the copy lives
#: (``exports/latest/``, ``data/``, the repo root), and anything in the
#: published export directory (``dynasty_data.js``, ``dynasty_full.csv``, ...).
BOARD_EXPORT_GLOB = "dynasty_data_*.json"
BOARD_EXPORT_DIR = ("exports", "latest")

# ── Where the stubs stop ────────────────────────────────────────────
#
# The tripwire only sees code the fixtures EXECUTE. These are the edges of that,
# named so a passing run is not read as covering more than it does:
#
# * ``team_strength.load_or_compute_team_strength`` and
#   ``sleeper_overlay.fetch_sleeper_overlay`` never run under the tripwire.
#   ``sim_env`` stubs ``playoff_sim._load_ros_strength_map`` and
#   ``_load_team_depth_ratios``, and the best-ball test stubs
#   ``_load_team_rosters`` -- the three simulator callers of
#   ``load_or_compute_team_strength``, whose cold path falls through to the
#   (network) ``fetch_sleeper_overlay``. Only the LEXICAL scan holds them:
#   ``team_strength.py`` is guarded; ``sleeper_overlay.py`` lives in
#   ``src/api`` and is not scanned at all. (It takes the contract's NFL id map
#   only when a caller passes ``id_to_player``; the forecast-path callers pass
#   none.) ``build_public_snapshot`` is stubbed likewise: the snapshot is built
#   in memory, never fetched.
# * The ``game_day_live`` exclusion's disk read sits on the best-ball pre-sim
#   path: ``playoff_sim._presim_availability`` -> ``matchup_intel._players_meta``
#   -> ``game_day_live.persisted_players_meta``, which reads the persisted
#   Sleeper players DB (``data/game_day/live/_nfl/nfl_players.json``). ``game_day_live.py``
#   is excluded from the lexical scan (``GUARD_EXCLUDED``) and the best-ball
#   test stubs that call, so NEITHER guard reads its body. It is player
#   metadata, not the board; that rests on review, not on a test here.
# * Direct disk reads of the board's export (``exports/latest/dynasty_data_*.json``
#   and its ``data/`` copies) never touch a getter or a host attribute, so the
#   getter and host traps cannot see them. Two guards cover that instead: the
#   lexical scan flags any guarded module that spells ``BOARD_EXPORT_FRAGMENT``
#   (no guarded module does today -- every reader is in ``server.py``,
#   ``src/api``, ``src/sources``, ``src/history``, ``src/consensus_edge``,
#   ``src/model_registry`` or ``scripts/``), and the tripwire wraps
#   ``builtins.open`` / ``io.open`` (which ``Path.read_text``, ``read_bytes``,
#   ``Path.open``, ``json.load(open(...))`` and ``gzip.open`` all reach) and
#   trips on ``BOARD_EXPORT_GLOB`` or ``BOARD_EXPORT_DIR``. It does not see
#   ``os.open``, ``_io.open`` / ``io.FileIO``, a name bound before arming
#   (``from io import open``), or a subprocess (``git show`` of an export).
# * A function DEFINED in ``server.py`` reads its own ``latest_*`` globals
#   through the module dict, never the trapped attribute. No simulator path
#   calls into ``server`` (``src/ros/api.py``'s ``_require_admin_session`` is
#   the HTTP layer).
# * The identity scan rebinds MODULE GLOBALS. A getter or a host cache held in
#   a container, a class attribute, a closure, a default argument or a
#   ``functools.partial`` is not rebound, so a call or a use through it is not
#   seen. An alias bound while the host held ``None`` is not rebound either,
#   and need not be: it holds ``None`` for good (see ``_identity_bearing``).

SIM_OWNERS = [f"owner{i:02d}" for i in range(1, 7)]
SIM_STRENGTH = dict(zip(SIM_OWNERS, [41.0, 77.0, 58.0, 90.0, 33.0, 66.0]))
SIM_SLOTS = ["QB", "RB", "WR", "TE", "SUPER_FLEX"]


class _ContractRead(BaseException):
    """A contract getter was called.

    A ``BaseException`` on purpose: the forecast code degrades on
    ``except Exception`` in several places (and ``collect_context`` /
    ``_refresh_sim_caches_for_league`` promise never to raise), so an ordinary
    exception would be swallowed and the read would go unseen. The tripwire also
    RECORDS every call, so even a bare ``except:`` cannot hide one.
    """


class _Tripwire:
    def __init__(self):
        self.reads: list[str] = []
        #: ``(module, binding, getter)`` for every rebound getter binding.
        self.armed: list[tuple[str, str, str]] = []
        #: ``(module, binding, host cache)`` for every ``src`` alias of a host cache.
        self.aliased: list[tuple[str, str, str]] = []

    def trip(self, what):
        self.reads.append(what)
        raise _ContractRead(what)

    def getter(self, what):
        def _tripped(*args, **kwargs):
            self.trip(what)

        _tripped.__name__ = what.rsplit(".", 1)[-1]
        _tripped.target = what
        return _tripped


class _TrippedValue:
    """Stands in for a host cache wherever a ``src`` module holds the SAME object.

    Reading a module global cannot be intercepted, so this trips on any USE of
    it: attribute access (``.get``, ``.items``, and ``__class__``, so
    ``isinstance`` too), indexing, iteration, ``len``, ``in``, truthiness,
    comparison, hashing, ``str`` / ``format``, copying and calling. A bare
    identity test (``x is None``) is the one use it cannot see. ``repr`` stays
    safe so a failing assertion can still print it.
    """

    __slots__ = ("_tripwire", "_what")

    def __init__(self, tripwire, what):
        object.__setattr__(self, "_tripwire", tripwire)
        object.__setattr__(self, "_what", what)

    def _trip(self, *args, **kwargs):
        object.__getattribute__(self, "_tripwire").trip(object.__getattribute__(self, "_what"))

    def __getattribute__(self, attr):
        object.__getattribute__(self, "_trip")()

    def __repr__(self):
        return f"<tripped {object.__getattribute__(self, '_what')}>"


for _dunder in (
    "__bool__ __len__ __iter__ __reversed__ __contains__ __getitem__ __setitem__ "
    "__delitem__ __eq__ __ne__ __lt__ __le__ __gt__ __ge__ __hash__ __str__ "
    "__format__ __bytes__ __fspath__ __index__ __int__ __float__ __call__ "
    "__setattr__ __delattr__ __or__ __ror__ __add__ __radd__ __copy__ "
    "__deepcopy__ __reduce__ __reduce_ex__"
).split():
    setattr(_TrippedValue, _dunder, _TrippedValue._trip)


def _identity_bearing(value):
    """Whether ``value is x`` can only mean "``x`` IS that cached object".

    ``None``, booleans and numbers are shared or interned, and an empty str /
    bytes / tuple is one object process-wide, so the same identity in a ``src``
    module says nothing about where it came from. Skipping them loses nothing:
    such a value is immutable, so an alias bound to it holds that value for good
    -- one bound while the host held ``None`` can never reach a later board
    (``server`` REBINDS its ``latest_*`` globals; it cannot fill in ``None``).
    """
    if value is None or isinstance(value, (bool, int, float, complex)):
        return False
    return not (isinstance(value, (str, bytes, tuple, frozenset)) and not value)


def _board_export_path(file):
    """``file`` as a POSIX path when it names the dynasty board on disk, else ``None``."""
    if isinstance(file, int):
        return None  # an already-open descriptor
    try:
        path = os.fsdecode(os.fspath(file))
    except TypeError:
        return None
    parts = Path(os.path.normcase(os.path.abspath(path))).parts
    in_export_dir = any(
        parts[i : i + len(BOARD_EXPORT_DIR)] == BOARD_EXPORT_DIR for i in range(len(parts))
    )
    if in_export_dir or fnmatch.fnmatch(os.path.basename(path), BOARD_EXPORT_GLOB):
        return Path(path).as_posix()
    return None


def _arm_contract_tripwire(monkeypatch):
    """Make every way of reading the loaded dynasty contract raise and record.

    Importing the getters' modules is not a read; calling a getter, touching a
    host ``latest_*`` cache, or opening the board's export file is. Bindings are
    matched by OBJECT IDENTITY, not by name, so ``from ... import
    contract_roster_pools as pools``, ``_pools = contract_roster_pools`` and
    ``from server import latest_contract_data as board`` are all trapped.
    """
    tripwire = _Tripwire()
    getters = {}
    for module_name, names in CONTRACT_GETTERS:
        module = importlib.import_module(module_name)
        for name in names:
            # ``getattr`` (no default): a renamed getter fails here, loudly, rather
            # than leaving a tripwire that guards a name nothing calls any more.
            original = getattr(module, name)
            getters[id(original)] = (original, tripwire.getter(f"{module_name}.{name}"))

    # ``server`` is heavy and usually not imported in a unit test: stand in for
    # it. If it IS loaded, trap reads on the real module instead -- and find its
    # cached objects wherever a ``src`` module aliased them.
    host = sys.modules.get("server")
    host_caches = {}
    if host is not None:
        for attr in _host_cache_names():
            value = vars(host).get(attr)
            if _identity_bearing(value):
                host_caches[id(value)] = (value, attr)

    for holder_name, holder in list(sys.modules.items()):
        if not isinstance(holder, types.ModuleType):
            continue
        in_src = holder_name.startswith("src.")
        if not (in_src or holder_name == "server"):
            continue
        for binding, value in list(vars(holder).items()):
            getter = getters.get(id(value))
            if getter is not None and getter[0] is value:
                monkeypatch.setattr(holder, binding, getter[1])
                tripwire.armed.append((holder_name, binding, getter[1].target))
                continue
            cached = host_caches.get(id(value)) if in_src else None
            if cached is not None and cached[0] is value:
                what = f"server.{cached[1]} (bound as {holder_name}.{binding})"
                # ``setitem`` on the module dict, not ``setattr``: ``setattr``
                # type-checks the new value, and that check is itself a use.
                monkeypatch.setitem(vars(holder), binding, _TrippedValue(tripwire, what))
                tripwire.aliased.append((holder_name, binding, f"server.{cached[1]}"))

    class _TrippedHost(types.ModuleType):
        def __getattribute__(self, attr):
            if attr.startswith(HOST_CACHE_PREFIX):
                tripwire.trip(f"server.{attr}")
            return super().__getattribute__(attr)

    if host is None:
        monkeypatch.setitem(sys.modules, "server", _TrippedHost("server"))
    else:
        monkeypatch.setattr(host, "__class__", _TrippedHost)

    real_open = builtins.open

    def _guarded_open(file, *args, **kwargs):
        board = _board_export_path(file)
        if board is not None:
            tripwire.trip(f"open:{board}")
        return real_open(file, *args, **kwargs)

    # ``io.open`` is what ``pathlib`` calls; ``builtins.open`` is everything else.
    monkeypatch.setattr(builtins, "open", _guarded_open)
    monkeypatch.setattr(io, "open", _guarded_open)
    return tripwire


@pytest.fixture
def contract_tripwire(monkeypatch):
    return _arm_contract_tripwire(monkeypatch)


def _sim_league(*, weeks=6, finished_weeks=3, playoff_teams=4, root="LTRIPWIRE"):
    """A six-team league mid-season: enough for the real playoff engine."""
    rng = random.Random(11)
    n = len(SIM_OWNERS)
    matchups = {}
    for wk in range(1, weeks + 1):
        rot = SIM_OWNERS[:1] + SIM_OWNERS[1:][wk % (n - 1) :] + SIM_OWNERS[1:][: wk % (n - 1)]
        rows = []
        for m in range(n // 2):
            for owner in (rot[m], rot[-(m + 1)]):
                pts = round(rng.uniform(80, 160), 2) if wk <= finished_weeks else 0.0
                rows.append(
                    {"roster_id": SIM_OWNERS.index(owner) + 1, "matchup_id": m + 1, "points": pts}
                )
        matchups[wk] = rows
    season = SimpleNamespace(
        season="2026",
        league_id=root,
        league={
            "settings": {
                "last_scored_leg": finished_weeks,
                "leg": finished_weeks + 1,
                "playoff_teams": playoff_teams,
                "playoff_week_start": weeks + 1,
                "playoff_seed_type": 1,
                "league_average_match": 0,
            }
        },
        num_teams=n,
        rosters=[{"roster_id": i + 1, "owner_id": o} for i, o in enumerate(SIM_OWNERS)],
        matchups_by_week=matchups,
        regular_season_weeks=list(range(1, weeks + 1)),
        winners_bracket=[],
        losers_bracket=[],
    )
    managers = SimpleNamespace(
        roster_to_owner={(root, i + 1): o for i, o in enumerate(SIM_OWNERS)},
        by_owner_id={o: SimpleNamespace(display_name=o.upper()) for o in SIM_OWNERS},
        ordered_managers=lambda: [SimpleNamespace(owner_id=o) for o in SIM_OWNERS],
    )
    return SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=managers,
        root_league_id=root,
        generated_at="2026-10-07T17:39:18+00:00",
    )


@pytest.fixture
def sim_env(ros_tmp, monkeypatch):
    """The real playoff engine on a synthetic league: offline, no developer data."""
    snap = _sim_league()
    monkeypatch.setattr(playoff_sim, "ROS_DATA_DIR", ros_tmp.ros)
    monkeypatch.setattr(playoff_sim, "_load_team_depth_ratios", lambda *a, **k: {})
    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", lambda *a, **k: dict(SIM_STRENGTH))
    monkeypatch.setattr(
        "src.api.league_registry.default_league_key", lambda *a, **k: "dynasty_main"
    )
    monkeypatch.setattr(
        "src.public_league.draft_order.league_draft_order_rule", lambda *a, **k: None
    )
    monkeypatch.setattr("src.public_league.snapshot.build_public_snapshot", lambda *a, **k: snap)
    return SimpleNamespace(snap=snap, archive=ros_tmp.archive)


def test_contract_tripwire_is_armed(contract_tripwire):
    """A tripwire that cannot trip would make every test below pass vacuously."""
    host = importlib.import_module("server")
    caches = _host_cache_names()
    for attr in caches:
        with pytest.raises(_ContractRead):
            getattr(host, attr, None)  # a default does not mask it
    assert contract_tripwire.reads == [f"server.{a}" for a in caches]
    # The PREFIX is trapped, not a list: a cache added tomorrow trips unedited.
    with pytest.raises(_ContractRead):
        getattr(host, "latest_cache_added_tomorrow", None)
    assert getattr(host, "not_a_contract_name", None) is None  # nothing else is trapped
    host_reads = len(contract_tripwire.reads)

    # Every binding of every getter, including the ``from ... import`` copies
    # that patching only the defining module would have missed.
    armed = contract_tripwire.armed
    bound = {(module_name, binding) for module_name, binding, _ in armed}
    assert ("src.api.data_contract", "contract_roster_pools") in bound
    assert ("src.api.roster_intelligence", "contract_roster_pools") in bound
    assert ("src.api.team_assignment", "contract_roster_pools") in bound
    assert ("src.api.trade_analyze_runtime", "contract_generation") in bound
    assert {target for *_, target in armed} == {
        f"{module_name}.{name}" for module_name, names in CONTRACT_GETTERS for name in names
    }
    for module_name, binding, _ in armed:
        with pytest.raises(_ContractRead):
            getattr(sys.modules[module_name], binding)()
    assert len(contract_tripwire.reads) == host_reads + len(armed)


def test_every_host_cache_is_enumerated():
    """Every ``server.latest_*`` cache, not only ``latest_contract_data`` / ``latest_data``."""
    static = set(_static_host_cache_names())
    for family in ("data", "runtime_data", "startup_data", "array_data", "compact_data"):
        for suffix in ("", "_bytes", "_gzip_bytes", "_etag"):
            assert f"latest_{family}{suffix}" in static
    assert {"latest_contract_data", "latest_data_source"} <= static
    # Where an earlier test loaded the real host, the static list must name
    # nothing the live module lacks (the dynamic half is unioned in by
    # ``_host_cache_names``). This file never imports it to check: see
    # ``_static_host_cache_names``.
    host = sys.modules.get("server")
    if getattr(host, "__file__", None):
        assert static <= set(vars(host)), "server.py no longer binds a name listed here"


def test_static_host_enumeration_reads_every_module_scope_binding():
    source = textwrap.dedent(
        """
        latest_plain = None
        latest_annotated: dict | None = None
        latest_left, latest_right = None, None
        if True:
            latest_in_if = {}
        from cache import thing as latest_imported

        def latest_function():
            latest_local = 1

        def _loader():
            global latest_declared_in_function
            latest_declared_in_function = {}

        not_a_cache = None
        """
    )
    assert _host_cache_names_in(source) == (
        "latest_annotated",
        "latest_declared_in_function",
        "latest_function",
        "latest_imported",
        "latest_in_if",
        "latest_left",
        "latest_plain",
        "latest_right",
    )


def _probe_module(monkeypatch, source):
    """A stand-in ``src`` module whose top level runs BEFORE the tripwire arms --
    exactly when a real module's ``from ... import`` runs. It lives only in
    ``sys.modules`` for one test; nothing is written under ``src/``."""
    probe = types.ModuleType("src._tripwire_probe")
    monkeypatch.setitem(sys.modules, probe.__name__, probe)
    exec(compile(textwrap.dedent(source), "<tripwire probe>", "exec"), vars(probe))
    return probe


def _loaded_host(monkeypatch, **caches):
    """A host that has loaded a board, as ``server`` has in production."""
    host = types.ModuleType("server")
    vars(host).update(caches)
    monkeypatch.setitem(sys.modules, "server", host)
    return host


def test_an_aliased_getter_binding_is_trapped_by_identity(monkeypatch):
    """Matching by name missed ``as`` imports and module-level rebinding."""
    probe = _probe_module(
        monkeypatch,
        """
        from src.api.data_contract import contract_roster_pools as pools
        from src.api import trade_analyze_runtime
        _generation = trade_analyze_runtime.contract_generation

        def read_pools():
            return pools({})

        def read_generation():
            return _generation()
        """,
    )
    tripwire = _arm_contract_tripwire(monkeypatch)

    for read in (probe.read_pools, probe.read_generation):
        with pytest.raises(_ContractRead):
            read()
    assert tripwire.reads == [
        "src.api.data_contract.contract_roster_pools",
        "src.api.trade_analyze_runtime.contract_generation",
    ]
    assert ("src._tripwire_probe", "pools", tripwire.reads[0]) in tripwire.armed
    assert ("src._tripwire_probe", "_generation", tripwire.reads[1]) in tripwire.armed


def test_an_aliased_host_cache_is_trapped_by_identity(monkeypatch):
    """``from server import latest_contract_data as board`` is never a host
    attribute read once bound; the cached OBJECT is what gives it away."""
    _loaded_host(
        monkeypatch,
        latest_contract_data={"players": {"p1": {"rankDerivedValue": 9000.0}}},
        latest_runtime_data={"players": {}},
        latest_runtime_data_bytes=b'{"players": {}}',
        latest_startup_data=None,
    )
    probe = _probe_module(
        monkeypatch,
        """
        from server import latest_contract_data as board
        import server as _host
        _runtime = _host.latest_runtime_data
        from server import latest_runtime_data_bytes as runtime_bytes
        from server import latest_startup_data as startup
        unrelated = None

        def read_board():
            return board.get("players")

        def read_runtime():
            return isinstance(_runtime, dict) and len(_runtime)

        def read_bytes():
            return runtime_bytes.decode()
        """,
    )
    tripwire = _arm_contract_tripwire(monkeypatch)

    for read in (probe.read_board, probe.read_runtime, probe.read_bytes):
        with pytest.raises(_ContractRead):
            read()
    assert tripwire.reads == [
        "server.latest_contract_data (bound as src._tripwire_probe.board)",
        "server.latest_runtime_data (bound as src._tripwire_probe._runtime)",
        "server.latest_runtime_data_bytes (bound as src._tripwire_probe.runtime_bytes)",
    ]
    # Identity, not equality or type: ``None`` is everyone's ``None``, so neither
    # ``None`` binding is touched (and an alias of ``None`` holds no board).
    assert probe.startup is None and probe.unrelated is None
    assert {b for _, b, _ in tripwire.aliased} == {"board", "_runtime", "runtime_bytes"}


@pytest.mark.parametrize("read", ["open", "read_text", "read_bytes", "path_open", "json_load"])
def test_reading_the_board_export_from_disk_trips(tmp_path, monkeypatch, read):
    board = tmp_path / "exports" / "latest" / "dynasty_data_2026-10-26.json"
    board.parent.mkdir(parents=True)
    board.write_text('{"players": {}}', encoding="utf-8")
    tripwire = _arm_contract_tripwire(monkeypatch)

    def _open():
        with open(board, encoding="utf-8") as fh:
            return fh.read()

    def _path_open():
        with board.open("rb") as fh:
            return fh.read()

    def _json_load():
        with open(str(board), "rb") as fh:
            return json.load(fh)

    readers = {
        "open": _open,
        "read_text": board.read_text,
        "read_bytes": board.read_bytes,
        "path_open": _path_open,
        "json_load": _json_load,
    }
    with pytest.raises(_ContractRead):
        readers[read]()
    assert tripwire.reads == [f"open:{board.as_posix()}"]


@pytest.mark.parametrize(
    "rel, is_board",
    [
        ("exports/latest/dynasty_data_2026-10-26.json", True),
        ("data/dynasty_data_2026-10-26.json", True),
        ("dynasty_data_2026-10-26.json", True),
        ("exports/latest/dynasty_full.csv", True),
        ("ros/aggregate/latest.json", False),
        ("ros/sims/latest_playoff.json", False),
        ("exports/narratives/week4.json", False),
    ],
)
def test_the_board_export_guard_traps_the_board_and_nothing_else(
    tmp_path, monkeypatch, rel, is_board
):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    tripwire = _arm_contract_tripwire(monkeypatch)

    if is_board:
        with pytest.raises(_ContractRead):
            target.read_text(encoding="utf-8")
        assert tripwire.reads == [f"open:{target.as_posix()}"]
    else:
        assert target.read_text(encoding="utf-8") == "{}"
        assert tripwire.reads == []


@pytest.mark.parametrize(
    "injected", ["host_cache", "aliased_host_cache", "aliased_getter", "board_export"]
)
def test_a_read_injected_into_the_forecast_path_is_caught(sim_env, tmp_path, monkeypatch, injected):
    """The mutation check, kept: each trap fires on the REAL refresh path.

    The read is injected into a stub (the team-strength loader ``sim_env``
    already stubs), never into ``src``. The clean-path tests above assert
    ``reads == []``, so a read of any of these forms appearing in a simulator
    fails them.
    """
    if injected == "host_cache":
        probe = SimpleNamespace(read=lambda: importlib.import_module("server").latest_startup_data)
        expected = "server.latest_startup_data"
    elif injected == "aliased_host_cache":
        _loaded_host(monkeypatch, latest_contract_data={"players": {}})
        probe = _probe_module(
            monkeypatch,
            """
            from server import latest_contract_data as board

            def read():
                return board.get("players")
            """,
        )
        expected = "server.latest_contract_data (bound as src._tripwire_probe.board)"
    elif injected == "aliased_getter":
        probe = _probe_module(
            monkeypatch,
            """
            from src.api.data_contract import contract_roster_pools as pools

            def read():
                return pools({})
            """,
        )
        expected = "src.api.data_contract.contract_roster_pools"
    else:
        board = tmp_path / "exports" / "latest" / "dynasty_data_2026-10-26.json"
        board.parent.mkdir(parents=True)
        board.write_text("{}", encoding="utf-8")
        probe = SimpleNamespace(read=board.read_text)
        expected = f"open:{board.as_posix()}"
    tripwire = _arm_contract_tripwire(monkeypatch)

    def _strength_that_reads(*args, **kwargs):
        probe.read()
        return dict(SIM_STRENGTH)

    monkeypatch.setattr(playoff_sim, "_load_ros_strength_map", _strength_that_reads)
    cfg = SimpleNamespace(key="dynasty_tripwire", sleeper_league_id="LTRIPWIRE", best_ball=False)

    with contextlib.suppress(_ContractRead):
        scrape._refresh_sim_caches_for_league(cfg, "dynasty_main")

    assert tripwire.reads, "the injected read never ran; this test proved nothing"
    assert set(tripwire.reads) == {expected}


def test_forecast_production_path_reads_no_contract(sim_env, contract_tripwire):
    """The refresh runner's own entry point -- sim, reshape, archive -- touches no board.

    ``_refresh_sim_caches_for_league`` and ``collect_context`` both swallow
    errors by design, so this also checks the work actually HAPPENED (both
    forecasts written and archived): a run that quietly bailed would read no
    contract either.
    """
    cfg = SimpleNamespace(key="dynasty_tripwire", sleeper_league_id="LTRIPWIRE", best_ball=False)

    out = scrape._refresh_sim_caches_for_league(cfg, "dynasty_main")

    assert out is not None and set(out) == {"playoff", "championship"}
    playoff = json.loads(out["playoff"].read_text(encoding="utf-8"))
    assert len(playoff["playoffOdds"]) == len(SIM_OWNERS)
    records = list(forecast_archive.iter_records(sim_env.archive))
    assert {r["kind"] for r in records} == {"playoff", "championship"}
    for record in records:
        assert record["inputs"]["contractGeneration"] is None
        assert record["nullReasons"]["inputs.contractGeneration"]
    assert contract_tripwire.reads == []


def test_context_and_title_simulation_read_no_contract(sim_env, contract_tripwire):
    """``collect_context`` plus a direct title simulation, called without the scrape."""
    context = forecast_archive.collect_context(sim_env.snap, best_ball=False)
    title = championship.simulate_championship_odds(
        sim_env.snap, n_simulations=300, best_ball=False, rng=random.Random(3)
    )
    identity = forecast_archive.build_identity(
        league_key="dynasty_tripwire",
        kind="championship",
        forecast={"computedAt": COMPUTED_AT, **title},
        context=context,
    )

    assert len(title["championshipOdds"]) == len(SIM_OWNERS)
    assert identity["inputs"]["contractGeneration"] is None
    assert identity["inputs"]["rosAggregateSha256"] is not None  # the inputs it DOES read
    assert contract_tripwire.reads == []


def test_best_ball_presim_availability_reads_no_contract(sim_env, contract_tripwire, monkeypatch):
    """The ``matchup_intel`` exception, justified by running it.

    ``playoff_sim._presim_availability`` imports ``players_meta_for_rosters``
    from ``src.api.matchup_intel`` -- a module whose own imports reach
    ``data_contract``. The lexical guard allows exactly that one symbol; this
    runs the real call under the tripwire to show it is a Sleeper
    player-metadata read and nothing else. The calendar, the persisted players DB
    and the network client are stubbed so the test stays offline and fast.
    """
    from src.public_league import sleeper_client
    from src.ros import availability, game_day_live

    def _player(owner, pos, ros):
        return {
            "playerId": f"{owner}_{pos}",
            "canonicalName": f"{owner} {pos}",
            "position": pos,
            "rosValue": ros,
            "fantasyPositions": [pos],
        }

    rosters = {
        owner: {
            "starters": [
                _player(owner, "QB", 5000.0 + i * 100),
                _player(owner, "RB", 4000.0),
                _player(owner, "WR", 4200.0),
                _player(owner, "TE", 2500.0),
            ],
            "bench": [_player(owner, "QB2", 1800.0)],
        }
        for i, owner in enumerate(SIM_OWNERS)
    }
    monkeypatch.setattr(playoff_sim, "_load_team_rosters", lambda *a, **k: rosters)
    monkeypatch.setattr(playoff_sim, "_load_starter_slots", lambda *a, **k: list(SIM_SLOTS))
    monkeypatch.setattr(
        availability, "load_context", lambda **k: SimpleNamespace(weeks=[4, 5, 6], basis={})
    )
    monkeypatch.setattr(availability, "player_week_states", lambda pid, meta, ctx: {})
    monkeypatch.setattr(game_day_live, "persisted_players_meta", lambda ids, now=None: None)
    metadata_reads = []
    monkeypatch.setattr(
        sleeper_client, "fetch_nfl_players", lambda *a, **k: metadata_reads.append(1) or {}
    )

    out = playoff_sim.simulate_playoff_odds(
        sim_env.snap, n_simulations=200, best_ball=True, rng=random.Random(4)
    )

    assert metadata_reads == [1], "players_meta_for_rosters did not run; this test proved nothing"
    assert out["bestBallVarianceMode"] == "depth_aware"
    assert len(out["playoffOdds"]) == len(SIM_OWNERS)
    assert contract_tripwire.reads == []


def test_missing_identity_is_none_with_a_reason_never_fabricated(ros_tmp, monkeypatch):
    (ros_tmp.ros / "aggregate" / "latest.json").unlink()
    (ros_tmp.ros / "team_strength" / "latest.json").unlink()
    monkeypatch.setattr(
        "src.api.build_identity.PROCESS_BUILD",
        {"commit": None, "commit_source": None, "unavailable_reason": "no_repository"},
    )
    bare = SimpleNamespace(root_league_id="L", generated_at=None, seasons=[], current_season=None)
    context = forecast_archive.collect_context(bare, best_ball=None)
    identity = forecast_archive.build_identity(
        league_key=None, kind="playoff", forecast={"playoffOdds": []}, context=context
    )

    _assert_present_or_explained(identity)
    nulls = identity["nullReasons"]
    assert identity["model"]["codeSha"] is None and nulls["model.codeSha"] == "no_repository"
    assert identity["season"] is None and nulls["season"] == "snapshot_has_no_current_season"
    assert identity["inputs"]["rosAggregateSha256"] is None
    assert nulls["inputs.rosAggregateSha256"] == "file_absent"
    assert identity["inputs"]["leagueSnapshotSha256"] is None
    assert identity["computedAt"] is None and nulls["computedAt"] == "absent_from_forecast"
    assert identity["nSimulations"] is None and nulls["nSimulations"] == "absent_from_forecast"


def test_code_sha_is_the_process_build_commit(ros_tmp):
    from src.api.build_identity import PROCESS_BUILD

    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    assert context["model"]["codeSha"] == PROCESS_BUILD["commit"]
    assert context["model"]["codeShaCapturedAt"] == PROCESS_BUILD["process_started_at"]


def test_code_sha_does_not_follow_head_drift_after_the_process_loaded(ros_tmp, monkeypatch):
    """In-server ``run_all``: a checkout after the server started (not yet
    followed by a restart) must not be claimed as the code that ran."""
    from src.api import build_identity

    loaded = {
        "commit": "a" * 40,
        "commit_source": "refs/heads/main",
        "unavailable_reason": None,
        "process_started_at": "2026-10-01T00:00:00+00:00",
    }
    monkeypatch.setattr(build_identity, "PROCESS_BUILD", loaded)
    monkeypatch.setattr(
        build_identity,
        "resolve_build_identity",
        lambda root: {"commit": "b" * 40, "commit_source": "drifted", "unavailable_reason": None},
    )
    model = forecast_archive.collect_context(_snapshot(), best_ball=True)["model"]
    assert model["codeSha"] == "a" * 40
    assert model["codeShaSource"] == "refs/heads/main"
    assert model["codeShaCapturedAt"] == "2026-10-01T00:00:00+00:00"


def test_scrape_captures_the_build_identity_at_module_load():
    """The runner's ``PROCESS_BUILD`` is taken when ``src.ros.scrape`` loads,
    not lazily at the first forecast."""
    import sys

    assert "src.api.build_identity" in sys.modules
    assert "from src.api import build_identity" in Path(scrape.__file__).read_text(encoding="utf-8")


def test_missing_sidecar_is_pre_archive_and_writes_nothing(ros_tmp):
    status = forecast_archive.ingest_text(
        json.dumps(_doc(PLAYOFF_PAYLOAD)),
        None,
        league_key="dynasty_main",
        kind="playoff",
        transport=forecast_archive.TRANSPORT_PUBLISHED_FILE,
        base=ros_tmp.archive,
    )
    assert status == "skipped:pre_archive"
    assert list(forecast_archive.iter_records(ros_tmp.archive)) == []


@pytest.mark.parametrize(
    ("sidecar", "reason"),
    [
        ("{not json", "identity_sidecar_unreadable"),
        (json.dumps({"schema": "something-else"}), "identity_sidecar_unreadable"),
    ],
)
def test_untrustworthy_sidecar_archives_the_forecast_unidentified(ros_tmp, sidecar, reason):
    doc = _doc(PLAYOFF_PAYLOAD)
    status = forecast_archive.ingest_text(
        json.dumps(doc),
        sidecar,
        league_key="dynasty_main",
        kind="playoff",
        transport=forecast_archive.TRANSPORT_PUBLISHED_FILE,
        base=ros_tmp.archive,
    )
    assert status == "written"
    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["forecast"] == doc
    assert rec["model"] is None and rec["inputs"] is None
    assert rec["nullReasons"]["model"] == reason


def test_sidecar_describing_a_different_forecast_is_never_trusted(ros_tmp):
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    other = forecast_archive.build_identity(
        league_key="dynasty_main", kind="playoff", forecast=_doc(CHAMP_PAYLOAD), context=context
    )
    forecast_archive.ingest_text(
        json.dumps(_doc(PLAYOFF_PAYLOAD)),
        json.dumps(other),
        league_key="dynasty_main",
        kind="playoff",
        transport=forecast_archive.TRANSPORT_PUBLISHED_FILE,
        base=ros_tmp.archive,
    )
    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["model"] is None
    assert rec["nullReasons"]["model"] == "identity_sidecar_mismatch"


# ── box-side ingest ─────────────────────────────────────────────────


def test_git_history_archives_only_sidecar_bearing_commits(ros_tmp, monkeypatch):
    sims = ros_tmp.ros / "sims"
    sims.mkdir()
    sim = sims / "latest_playoff.json"
    monkeypatch.setattr(forecast_archive, "REPO_ROOT", ros_tmp.ros.parent.resolve())
    monkeypatch.setattr(
        forecast_archive, "published_paths", lambda: [("dynasty_main", "playoff", sim)]
    )
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    new_doc = _doc(PLAYOFF_PAYLOAD)
    old_doc = {**new_doc, "computedAt": "2026-09-30T12:00:00+00:00"}
    new_side = forecast_archive.build_identity(
        league_key="dynasty_main", kind="playoff", forecast=new_doc, context=context
    )
    blobs = {
        "new:ros/sims/latest_playoff.json": json.dumps(new_doc),
        "new:ros/sims/latest_playoff.identity.json": json.dumps(new_side),
        "old:ros/sims/latest_playoff.json": json.dumps(old_doc),
    }

    def fake_git(*args):
        if args[0] == "log":
            return "new\nold\n"
        return blobs.get(args[1])

    monkeypatch.setattr(forecast_archive, "_git", fake_git)
    counts = forecast_archive.ingest_git_history(ros_tmp.archive, max_commits=5)
    assert counts == {"written": 1, "skipped:pre_archive": 1}
    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["transport"] == forecast_archive.TRANSPORT_GIT_HISTORY
    assert rec["model"] == json.loads(json.dumps(new_side["model"]))

    again = forecast_archive.ingest_git_history(ros_tmp.archive, max_commits=5)
    assert again == {"stopped:already_archived": 1}


def test_ingest_published_archives_what_the_deploy_shipped(ros_tmp, monkeypatch):
    sims = ros_tmp.ros / "sims"
    sims.mkdir()
    sim = sims / "latest_playoff.json"
    doc = _doc(PLAYOFF_PAYLOAD)
    sim.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    forecast_archive.write_identity_sidecar_safely(
        sim,
        forecast_archive.build_identity(
            league_key="dynasty_main", kind="playoff", forecast=doc, context=context
        ),
    )
    missing = sims / "latest_championship.json"
    monkeypatch.setattr(
        forecast_archive,
        "published_paths",
        lambda: [("dynasty_main", "playoff", sim), ("dynasty_main", "championship", missing)],
    )
    assert forecast_archive.ingest_published(ros_tmp.archive) == {
        "written": 1,
        "skipped:absent": 1,
    }
    assert forecast_archive.ingest_published(ros_tmp.archive) == {
        "duplicate": 1,
        "skipped:absent": 1,
    }


def test_first_deploy_without_sidecars_archives_nothing(ros_tmp, monkeypatch):
    """The first deploy after merge ships committed sim files with no sidecar.
    Archiving them identity-less would freeze their identity as None forever
    (identity is not part of the key), so they are pre-archive, exactly as the
    git history walk classifies the same commit."""
    sims = ros_tmp.ros / "sims"
    sims.mkdir()
    playoff = sims / "latest_playoff.json"
    champ = sims / "latest_championship.json"
    playoff.write_text(json.dumps(_doc(PLAYOFF_PAYLOAD), indent=2), encoding="utf-8")
    champ.write_text(json.dumps(_doc(CHAMP_PAYLOAD), indent=2), encoding="utf-8")
    monkeypatch.setattr(
        forecast_archive,
        "published_paths",
        lambda: [("dynasty_main", "playoff", playoff), ("dynasty_main", "championship", champ)],
    )
    assert forecast_archive.ingest_published(ros_tmp.archive) == {"skipped:pre_archive": 2}
    assert list(forecast_archive.iter_records(ros_tmp.archive)) == []
    assert not (ros_tmp.archive / forecast_archive.INDEX_NAME).exists()

    # Once the producer has written the sidecar, the same forecast archives
    # WITH its identity -- nothing identity-less is in the way.
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    doc = json.loads(playoff.read_text(encoding="utf-8"))
    identity = forecast_archive.build_identity(
        league_key="dynasty_main", kind="playoff", forecast=doc, context=context
    )
    forecast_archive.write_identity_sidecar_safely(playoff, identity)
    assert forecast_archive.ingest_published(ros_tmp.archive) == {
        "written": 1,
        "skipped:pre_archive": 1,
    }
    (rec,) = forecast_archive.iter_records(ros_tmp.archive)
    assert rec["model"] == json.loads(json.dumps(identity["model"]))


def test_sidecar_temp_file_never_survives_a_failed_replace(ros_tmp, monkeypatch):
    sims = ros_tmp.ros / "sims"
    sims.mkdir()
    sim = sims / "latest_playoff.json"
    sim.write_text("{}", encoding="utf-8")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(forecast_archive.os, "replace", boom)
    assert forecast_archive.write_identity_sidecar_safely(sim, {"schema": "x"}) is False
    assert sorted(p.name for p in sims.iterdir()) == ["latest_playoff.json"]


# ── git history against a REAL repository ───────────────────────────


def _run_git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


@pytest.fixture
def git_repo(tmp_path, ros_tmp, monkeypatch):
    """A real repository holding one published sim file, plus helpers."""
    repo = tmp_path / "repo"
    sims = repo / "data" / "ros" / "sims"
    sims.mkdir(parents=True)
    _run_git(repo, "init", "-q")
    sim = sims / "latest_playoff.json"
    monkeypatch.setattr(forecast_archive, "REPO_ROOT", repo.resolve())
    monkeypatch.setattr(
        forecast_archive, "published_paths", lambda: [("dynasty_main", "playoff", sim)]
    )
    context = forecast_archive.collect_context(_snapshot(), best_ball=True)
    counter = iter(range(1, 10_000))

    def commit(*, with_sidecar: bool) -> str:
        n = next(counter)
        doc = {**_doc(PLAYOFF_PAYLOAD), "computedAt": f"2026-09-{n:02d}T12:00:00+00:00"}
        sim.write_bytes(json.dumps(doc).encode("utf-8"))
        side = forecast_archive.sidecar_path(sim)
        if with_sidecar:
            identity = forecast_archive.build_identity(
                league_key="dynasty_main", kind="playoff", forecast=doc, context=context
            )
            side.write_bytes(json.dumps(identity).encode("utf-8"))
        elif side.exists():
            side.unlink()
        _run_git(repo, "add", "-A")
        _run_git(
            repo,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            f"refresh {n}",
        )
        return doc["computedAt"]

    return SimpleNamespace(repo=repo, sim=sim, commit=commit, archive=ros_tmp.archive)


def _archived_stamps(archive: Path) -> list[str]:
    return sorted(r["computedAt"] for r in forecast_archive.iter_records(archive))


def test_real_git_history_walks_back_to_the_last_archived_forecast(git_repo):
    pre = [git_repo.commit(with_sidecar=False) for _ in range(2)]
    first = [git_repo.commit(with_sidecar=True) for _ in range(3)]
    counts = forecast_archive.ingest_git_history(git_repo.archive)
    # Nothing archived yet: the walk runs through all history, under the cap.
    assert counts == {"written": 3, "skipped:pre_archive": 2}
    assert _archived_stamps(git_repo.archive) == first
    assert not set(pre) & set(_archived_stamps(git_repo.archive))

    # Deploys stall for far longer than the old 24-commit window: 30 refreshes.
    stalled = [git_repo.commit(with_sidecar=True) for _ in range(30)]
    counts = forecast_archive.ingest_git_history(git_repo.archive)
    assert counts == {"written": 30, "stopped:already_archived": 1}
    assert _archived_stamps(git_repo.archive) == sorted(first + stalled)

    # Nothing new: the walk stops at the newest commit.
    assert forecast_archive.ingest_git_history(git_repo.archive) == {"stopped:already_archived": 1}


def test_real_git_history_warns_when_the_safety_cap_is_hit(git_repo, caplog):
    for _ in range(4):
        git_repo.commit(with_sidecar=True)
    with caplog.at_level(logging.WARNING, logger="ros.forecast_archive"):
        counts = forecast_archive.ingest_git_history(git_repo.archive, max_commits=3)
    assert counts == {"written": 3, "warning:cap_reached": 1}
    assert any("safety cap of 3 commits" in r.getMessage() for r in caplog.records)


def test_published_ingest_of_head_does_not_stop_the_history_walk(git_repo):
    """The deploy archives its own HEAD forecast first; the walk's stop
    condition is the archive BEFORE this run, so the stalled window between the
    last deploy and HEAD is still recovered."""
    earlier = git_repo.commit(with_sidecar=True)
    assert forecast_archive.ingest_git_history(git_repo.archive) == {"written": 1}
    stalled = [git_repo.commit(with_sidecar=True) for _ in range(5)]

    spec = importlib.util.spec_from_file_location(
        "archive_ros_forecasts_under_test", REPO_ROOT / "scripts" / "archive_ros_forecasts.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--dir", str(git_repo.archive), "--git-history"]) == 0
    assert _archived_stamps(git_repo.archive) == sorted([earlier, *stalled])


# ── where the store lives ───────────────────────────────────────────


def test_store_is_outside_every_force_added_path():
    """``scheduled-refresh.yml`` ``git add -f``s whole trees, overriding
    ``.gitignore``. A private archive under any of them would be committed to a
    public repository every two hours."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "scheduled-refresh.yml").read_text(
        encoding="utf-8"
    )
    forced: set[str] = set()
    for match in re.finditer(r"for p in ([^;]+); do", workflow):
        forced.update(match.group(1).split())
    forced.update(re.findall(r"git add -f ([\w./-]+)", workflow))
    assert "data/ros/" in forced  # the parse found the real list
    store = forecast_archive.DEFAULT_DIR.relative_to(REPO_ROOT).as_posix() + "/"
    for path in forced:
        assert not store.startswith(path.rstrip("/") + "/") and store != path, path
    assert forecast_archive.DEFAULT_DIR.relative_to(REPO_ROOT).parts[:2] != ("data", "ros")


def test_league_snapshot_hash_ignores_sleeper_chat_cursors(ros_tmp):
    a, b = _snapshot(), _snapshot()
    a.current_season.league["last_message_time"] = 1
    b.current_season.league["last_message_time"] = 2
    ha = forecast_archive.collect_context(a, best_ball=True)["inputs"]["leagueSnapshotSha256"]
    hb = forecast_archive.collect_context(b, best_ball=True)["inputs"]["leagueSnapshotSha256"]
    assert ha == hb
    b.current_season.league["settings"]["last_scored_leg"] = 4  # a real input
    hc = forecast_archive.collect_context(b, best_ball=True)["inputs"]["leagueSnapshotSha256"]
    assert hc != ha
