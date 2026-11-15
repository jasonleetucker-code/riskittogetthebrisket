"""The restore proof leaves a result the app can read (MD-103).

``retention_backup_restore_proof.sh`` used to leave its verdict only in a CI log,
so ``/api/health`` could not say whether the last backup RESTORED.  It now writes
``data/diagnostics/backup_restore_proof.json`` -- enumerated states and integers,
no path -- which ``src/api/backup_health.py`` reads as ``restoreProof``.

Pinned here: a clean run records ``proven``; a missing artifact records ``failed``
(exit 2); a run that could not start records ``could_not_run`` (exit 1); the
FIRST write is ``running`` (so a killed run cannot leave the previous pass
standing); an unwritable result location changes nothing about the exit status;
and what the reader makes of each file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.api import backup_health as bh

REPO = Path(__file__).resolve().parents[2]
PROOF = REPO / "deploy" / "diagnostics" / "retention_backup_restore_proof.sh"

if not hasattr(os, "geteuid"):
    pytest.skip(
        "Unix path semantics are required by the proof script's absolute-root rules",
        allow_module_level=True,
    )

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _app(tmp_path: Path) -> tuple[Path, Path]:
    app = tmp_path / "app"
    shutil.copytree(REPO / "deploy", app / "deploy")
    data = app / "data"
    data.mkdir()
    for rel, ddl in (
        ("user_kv.sqlite", "CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)"),
        ("session_store.sqlite", "CREATE TABLE sessions (id TEXT PRIMARY KEY)"),
    ):
        con = sqlite3.connect(data / rel)
        con.execute(ddl)
        con.commit()
        con.close()
    (data / "retention").mkdir()
    con = sqlite3.connect(data / "retention" / "evidence.sqlite")
    for ddl in (
        "CREATE TABLE scoring_card_payloads (card_hash TEXT PRIMARY KEY)",
        "CREATE TABLE scoring_card_observations (sleeper_league_id TEXT, observed_at TEXT)",
        "CREATE TABLE trending_observations (source TEXT, observed_at TEXT)",
    ):
        con.execute(ddl)
    con.commit()
    con.close()
    return app, data


def _run(app: Path, data: Path, tmp_path: Path, run_backup: str = "1", **extra):
    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "primary"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        RUN_BACKUP=run_backup,
    )
    env.update(extra)
    return subprocess.run(
        ["bash", str(PROOF)], env=env, capture_output=True, text=True, timeout=300
    )


def _result(data: Path) -> dict:
    return json.loads((data / "diagnostics" / "backup_restore_proof.json").read_text("utf-8"))


def test_a_clean_run_records_proven_and_the_app_reads_it_back(tmp_path):
    app, data = _app(tmp_path)
    proc = _run(app, data, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = _result(data)
    assert doc["state"] == "proven" and doc["exitCode"] == 0 and doc["failures"] == 0
    assert doc["provenArtifacts"] >= 1 and doc["runBackup"] is True
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["generationDate"])
    # The record is enumerated states and integers: no path, no log text.
    assert "/" not in json.dumps(doc)
    read = bh.restore_proof_health(data_dir=str(data))
    assert (read["result"], read["reason"]) == ("proven", "all_artifacts_verified")


def test_a_missing_artifact_records_failed_with_exit_two(tmp_path):
    app, data = _app(tmp_path)
    assert _run(app, data, tmp_path).returncode == 0
    gens = sorted((tmp_path / "primary" / "daily").glob("*")) + sorted(
        (tmp_path / "fallback" / "daily").glob("*")
    )
    assert gens, "the first run should have promoted a generation"
    for gen in gens:
        (gen / "sqlite" / "evidence.sqlite.gz").unlink(missing_ok=True)
    proc = _run(app, data, tmp_path, run_backup="0")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = _result(data)
    assert doc["state"] == "failed" and doc["exitCode"] == 2 and doc["failures"] >= 1
    assert bh.restore_proof_health(data_dir=str(data))["result"] == "failed"


def test_a_run_that_cannot_start_records_could_not_run(tmp_path):
    app, data = _app(tmp_path)
    proc = _run(app, data, tmp_path, run_backup="0")  # no generation anywhere
    assert proc.returncode == 1, proc.stdout + proc.stderr
    doc = _result(data)
    assert doc["state"] == "could_not_run" and doc["exitCode"] == 1
    assert bh.restore_proof_health(data_dir=str(data))["result"] == "could_not_run"


def test_the_first_write_is_running_so_a_killed_run_cannot_leave_the_old_pass(tmp_path):
    script = PROOF.read_text(encoding="utf-8")
    first = script.index("write_proof_result running null null")
    # The verdict is recorded from the EXIT trap, installed before anything runs.
    assert script.index('write_proof_result "${ps}"') < script.index("trap cleanup EXIT")
    assert script.index("trap cleanup EXIT") < first < script.index("BACKUP_ROOT_LIB=")
    # ... and the reader treats a stale `running` as interrupted, not as the earlier pass.
    app, data = _app(tmp_path)
    target = data / "diagnostics" / "backup_restore_proof.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "schema": 1,
                "state": "running",
                "startedAt": "2020-01-01T00:00:00Z",
                "completedAt": None,
                "exitCode": None,
            }
        ),
        encoding="utf-8",
    )
    assert bh.restore_proof_health(data_dir=str(data))["result"] == "interrupted"


def test_an_unwritable_result_location_never_changes_the_verdict(tmp_path):
    app, data = _app(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    proc = _run(app, data, tmp_path, PROOF_RESULT_FILE=str(blocker / "sub" / "result.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "could not" in (proc.stdout + proc.stderr)
    assert not (data / "diagnostics" / "backup_restore_proof.json").exists()
    # A host whose result cannot be written reads unknown, never healthy.
    assert bh.restore_proof_health(data_dir=str(data))["result"] == "unknown"
