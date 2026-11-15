"""Group LIST access to the 0700 backup root, analyst-ledger coverage, and the
restore-verification script — the shipped writer run end to end."""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

if os.name == "nt":
    pytest.skip("Linux backup semantics", allow_module_level=True)

import grp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "backup" / "riskit-state-backup.sh"
VERIFY = REPO / "scripts" / "verify_state_backup_restore.py"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    data = tmp_path / "app" / "data"
    _db(data / "user_kv.sqlite")
    _db(data / "session_store.sqlite")
    _db(data / "analyst_ledger.sqlite")
    full = {k: v for k, v in os.environ.items() if not k.startswith("BACKUP_")}
    full.update(
        APP_DIR=str(tmp_path / "app"),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "root"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        DATE_STAMP=TODAY,
        BACKUP_MIN_FREE_KB="0",
        BACKUP_STORE_MARGIN_KB="0",
    )
    full.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=full, capture_output=True, text=True, timeout=300
    )


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_analyst_ledger_is_in_the_generation(tmp_path):
    result = _run(tmp_path)
    assert result.returncode in (0, 3), result.stdout + result.stderr
    gen = tmp_path / "root" / "daily" / TODAY
    assert (gen / "sqlite" / "analyst_ledger.sqlite.gz").is_file()


def test_group_gets_list_access_but_artifacts_and_sessions_stay_private(tmp_path):
    group = grp.getgrgid(os.getgid()).gr_name
    result = _run(tmp_path, BACKUP_READ_GROUP=group)
    assert result.returncode in (0, 3), result.stdout + result.stderr
    root = tmp_path / "root"
    gen = root / "daily" / TODAY
    for d in (root, root / "daily", gen, gen / "sqlite"):
        assert _mode(d) == 0o750, d
    assert _mode(root / "last_generation") == 0o640
    # Names and sizes are visible; bytes and secrets are not.
    assert _mode(gen / "sqlite" / "user_kv.sqlite.gz") == 0o600
    assert _mode(gen / "sessions") == 0o700


def test_without_a_group_the_root_stays_closed(tmp_path):
    result = _run(tmp_path)
    assert result.returncode in (0, 3), result.stdout + result.stderr
    assert _mode(tmp_path / "root") == 0o700


def test_unknown_group_warns_and_keeps_the_root_closed(tmp_path):
    result = _run(tmp_path, BACKUP_READ_GROUP="no_such_group_xyz")
    assert result.returncode in (0, 3), result.stdout + result.stderr
    assert "could not grant group" in result.stdout + result.stderr
    assert _mode(tmp_path / "root") == 0o700


def test_service_unit_sets_the_group():
    text = (REPO / "deploy" / "backup" / "riskit-state-backup.service").read_text(encoding="utf-8")
    assert 'Environment="BACKUP_READ_GROUP=dynasty"' in text


def test_restore_verify_passes_a_real_generation_and_cleans_scratch(tmp_path):
    assert _run(tmp_path).returncode in (0, 3)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    r = subprocess.run(
        [
            sys.executable,
            str(VERIFY),
            "--root",
            str(tmp_path / "root"),
            "--scratch-dir",
            str(scratch),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK   sqlite/analyst_ledger.sqlite.gz" in r.stdout
    assert list(scratch.iterdir()) == []


def test_restore_verify_fails_on_a_corrupt_artifact(tmp_path):
    assert _run(tmp_path).returncode in (0, 3)
    art = tmp_path / "root" / "daily" / TODAY / "sqlite" / "user_kv.sqlite.gz"
    with gzip.open(art, "wb") as fh:
        fh.write(b"not a database" * 500)
    r = subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(tmp_path / "root")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL sqlite/user_kv.sqlite.gz" in r.stdout


def test_restore_verify_with_no_generation_is_exit_2_not_a_pass(tmp_path):
    r = subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(tmp_path / "nothing")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2
