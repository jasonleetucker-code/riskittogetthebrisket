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
* the store lives outside every path the scheduled refresh force-adds to git.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.ros as ros_pkg
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
        json.dumps({"aggregatedAt": "2026-10-01T11:00:00+00:00", "players": []})
    )
    (ros_dir / "team_strength").mkdir()
    (ros_dir / "team_strength" / "latest.json").write_text("[]")
    archive = tmp_path / "forecast_archive"
    monkeypatch.setattr(ros_pkg, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(scrape, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(team_strength, "ROS_DATA_DIR", ros_dir)
    monkeypatch.setattr(forecast_archive, "DEFAULT_DIR", archive)
    monkeypatch.setattr(team_strength, "resolve_snapshot_league_key", lambda snap: None)
    return SimpleNamespace(ros=ros_dir, archive=archive)


def _doc(payload):
    return {"computedAt": COMPUTED_AT, **payload}


# ── round trip ──────────────────────────────────────────────────────


def test_archived_record_round_trips(ros_tmp):
    doc = _doc(PLAYOFF_PAYLOAD)
    sim = ros_tmp.ros / "sims" / "latest_playoff.json"
    sim.parent.mkdir(parents=True)
    sim.write_text(json.dumps(doc, indent=2))
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
    sidecar = json.loads((ros_tmp.ros / "sims" / "latest_playoff.identity.json").read_text())
    assert sidecar == json.loads(json.dumps(identity))
    assert "forecast" not in sidecar


def test_published_file_plus_sidecar_reproduces_the_producer_record(ros_tmp):
    doc = _doc(CHAMP_PAYLOAD)
    sim = ros_tmp.ros / "sims" / "latest_championship.json"
    sim.parent.mkdir(parents=True)
    sim.write_text(json.dumps(doc, indent=2))
    context = forecast_archive.collect_context(_snapshot(), best_ball=False)
    forecast_archive.archive_safely(
        league_key="dynasty_main",
        kind="championship",
        forecast=doc,
        context=context,
        sim_path=sim,
        base=ros_tmp.archive / "elsewhere",  # the runner's store, discarded
    )
    side = forecast_archive.sidecar_path(sim).read_text()

    status = forecast_archive.ingest_text(
        sim.read_text(),
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
    index.write_text("")
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
    assert out["playoff"].read_text() == playoff
    assert out["championship"].read_text() == champ
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
    assert out["playoff"].read_text() == playoff
    assert out["championship"].read_text() == champ


def test_unwritable_archive_directory_does_not_break_the_refresh(ros_tmp, monkeypatch):
    ros_tmp.archive.parent.mkdir(parents=True, exist_ok=True)
    ros_tmp.archive.write_text("a file where the archive directory should be")
    out = _run_refresh(ros_tmp, monkeypatch)
    assert set(out) == {"playoff", "championship"}
    assert out["playoff"].read_text() == _expected_served_bytes()[0]


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
    sim.write_text(json.dumps(doc, indent=2))
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
    playoff.write_text(json.dumps(_doc(PLAYOFF_PAYLOAD), indent=2))
    champ.write_text(json.dumps(_doc(CHAMP_PAYLOAD), indent=2))
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
    doc = json.loads(playoff.read_text())
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
    sim.write_text("{}")

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
