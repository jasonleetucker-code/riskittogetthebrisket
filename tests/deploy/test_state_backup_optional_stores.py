"""CORE vs OPTIONAL stores, the free-space guard and staging cleanup —
driven end to end through the SHIPPED ``riskit-state-backup.sh``.

PR #1611 review findings, each reproduced here against the real script:

* an OPTIONAL store's failure (the intel ledger has a corruption history on
  the box) used to count as an ERROR, and the run then discarded the WHOLE
  generation — user_kv and session_store included — and exited 1;
* a run with too little disk had no guard at all;
* a run killed mid-way (systemd's TimeoutStartSec) leaked its staging
  directory, and the start-of-run sweep only removed staging older than a day.

Linux semantics throughout (flock, /proc, GNU tar), so this module is skipped
on Windows; Linux CI is the authority.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

if os.name == "nt":
    pytest.skip("Linux backup semantics (flock, /proc)", allow_module_level=True)

fcntl = pytest.importorskip("fcntl")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "backup" / "riskit-state-backup.sh"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _sqlite(path: Path, *ddl: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for stmt in ddl or ("CREATE TABLE t (x)",):
            con.execute(stmt)
        con.commit()
    finally:
        con.close()


def _corrupt(path: Path) -> None:
    """A file sqlite cannot open as a database: the online backup fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"definitely not an sqlite database\n" * 256)


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "app" / "data"
    _sqlite(data / "user_kv.sqlite", "CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
    _sqlite(data / "session_store.sqlite", "CREATE TABLE sessions (id TEXT PRIMARY KEY)")
    return data


def _run(tmp_path: Path, data: Path, **env: str) -> subprocess.CompletedProcess:
    full = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BACKUP_") and k not in {"OFFBOX_RSYNC_DEST", "KEEP_DAILY"}
    }
    full.update(
        APP_DIR=str(tmp_path / "app"),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "root"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        DATE_STAMP=TODAY,
        # The real floor is 5 GiB; a CI runner's free space must not decide
        # these tests.  The low-space test sets its own.
        BACKUP_MIN_FREE_KB="0",
        BACKUP_STORE_MARGIN_KB="0",
    )
    full.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=full, capture_output=True, text=True, timeout=300
    )


def _gen(tmp_path: Path) -> Path:
    return tmp_path / "root" / "daily" / TODAY


def _manifest(gen: Path) -> dict[str, str]:
    path = gen / "optional_stores.tsv"
    if not path.exists():
        return {}
    rows = [ln.split("\t") for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    return {r[0]: r[1] for r in rows}


# ── finding 1: an optional failure keeps the generation ──────────────────


def test_an_optional_store_failure_keeps_the_generation_and_exits_3(tmp_path):
    data = _data(tmp_path)
    _corrupt(data / "consensus_edge.sqlite")
    _sqlite(data / "market_trades" / "archive.sqlite")

    result = _run(tmp_path, data)
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert (gen / "sqlite" / "session_store.sqlite.gz").is_file(), out
    # The healthy optional store is still there; the broken one is not, and
    # the generation says so.
    assert (gen / "sqlite" / "market_trades_archive.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "consensus_edge.sqlite.gz").exists()
    assert _manifest(gen) == {"consensus_edge.sqlite": "failed"}, out
    assert "OPTIONAL store consensus_edge.sqlite is NOT in this generation" in out, out
    assert "complete WITH WARNINGS" in out, out
    # No staging left behind.
    assert not list((tmp_path / "root" / "daily").glob(".staging-*")), out


def test_a_core_store_failure_still_discards_the_generation(tmp_path):
    data = _data(tmp_path)
    _corrupt(data / "guest_passes.sqlite")

    result = _run(tmp_path, data)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert not _gen(tmp_path).exists(), out
    assert "run FAILED" in out, out
    assert not list((tmp_path / "root" / "daily").glob(".staging-*")), out


def test_a_corrupt_intel_ledger_falls_back_to_raw_files_in_the_tar(tmp_path):
    """The corruption-tolerant pre-AL-P2 path: the generation still holds the
    ledger's bytes for a recovery to work from."""
    data = _data(tmp_path)
    _corrupt(data / "intel" / "ledger.sqlite3")
    (data / "intel" / "snapshot.json").write_text("{}", encoding="utf-8")

    result = _run(tmp_path, data)
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert not (gen / "sqlite" / "intel_ledger.sqlite3.gz").exists()
    assert _manifest(gen) == {"intel_ledger.sqlite3": "failed"}, out
    with tarfile.open(gen / "dirs" / "intel.tar.gz") as tf:
        names = tf.getnames()
    assert "intel/ledger.sqlite3" in names, names
    assert "intel/snapshot.json" in names, names


def test_a_healthy_intel_ledger_is_copied_online_and_excluded_from_the_tar(tmp_path):
    data = _data(tmp_path)
    _sqlite(data / "intel" / "ledger.sqlite3")
    (data / "intel" / "snapshot.json").write_text("{}", encoding="utf-8")

    result = _run(tmp_path, data)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "intel_ledger.sqlite3.gz").is_file(), out
    with tarfile.open(gen / "dirs" / "intel.tar.gz") as tf:
        names = tf.getnames()
    assert "intel/ledger.sqlite3" not in names, names
    assert "intel/snapshot.json" in names, names
    assert _manifest(gen) == {}


def test_a_requested_skip_is_recorded_but_is_not_a_warning(tmp_path):
    """The post-deploy proof skips the two large stores on purpose."""
    data = _data(tmp_path)
    _sqlite(data / "temporal_ledger.sqlite")
    _sqlite(data / "intel" / "ledger.sqlite3")

    result = _run(
        tmp_path, data, BACKUP_SKIP_OPTIONAL="temporal_ledger.sqlite intel_ledger.sqlite3"
    )
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    gen = _gen(tmp_path)
    assert not (gen / "sqlite" / "temporal_ledger.sqlite.gz").exists()
    assert not (gen / "sqlite" / "intel_ledger.sqlite3.gz").exists()
    assert _manifest(gen) == {
        "temporal_ledger.sqlite": "skipped_requested",
        "intel_ledger.sqlite3": "skipped_requested",
    }, out
    # Skipped online copy => the raw ledger rides in the intel tar.
    with tarfile.open(gen / "dirs" / "intel.tar.gz") as tf:
        assert "intel/ledger.sqlite3" in tf.getnames()


# ── finding 4: the free-space guard ───────────────────────────────────────


def test_low_disk_sheds_optional_stores_and_still_backs_up_core(tmp_path):
    data = _data(tmp_path)
    _sqlite(data / "temporal_ledger.sqlite")
    _sqlite(data / "consensus_edge.sqlite")
    _sqlite(data / "retention" / "evidence.sqlite")  # CORE

    # A floor no filesystem satisfies.
    result = _run(tmp_path, data, BACKUP_MIN_FREE_KB=str(10**15))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert (gen / "sqlite" / "evidence.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "temporal_ledger.sqlite.gz").exists()
    assert not (gen / "sqlite" / "consensus_edge.sqlite.gz").exists()
    assert _manifest(gen) == {
        "consensus_edge.sqlite": "skipped_low_space",
        "temporal_ledger.sqlite": "skipped_low_space",
    }, out
    assert "LOW DISK" in out, out


def test_a_per_store_margin_sheds_only_that_store(tmp_path):
    data = _data(tmp_path)
    _sqlite(data / "temporal_ledger.sqlite")

    result = _run(tmp_path, data, BACKUP_STORE_MARGIN_KB=str(10**15))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    assert _manifest(_gen(tmp_path)) == {"temporal_ledger.sqlite": "skipped_low_space"}, out
    assert (_gen(tmp_path) / "sqlite" / "user_kv.sqlite.gz").is_file()


def test_a_non_numeric_free_space_knob_refuses_to_run(tmp_path):
    data = _data(tmp_path)
    result = _run(tmp_path, data, BACKUP_MIN_FREE_KB="5G")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BACKUP_MIN_FREE_KB must be a non-negative integer" in result.stderr


# ── finding 3: staging cleanup ────────────────────────────────────────────


def test_stale_staging_from_a_dead_run_is_swept_regardless_of_age(tmp_path):
    data = _data(tmp_path)
    daily = tmp_path / "root" / "daily"
    # A PID that cannot be alive (beyond pid_max), no lock: a dead run's dir,
    # created just now — the old `-mtime +1` rule would have kept it.
    dead = daily / f".staging-{TODAY}-99999999"
    (dead / "sqlite").mkdir(parents=True)
    (dead / "sqlite" / "partial.gz").write_bytes(b"x")
    # A LIVE writer (this test process) without a lock — must be left alone.
    live = daily / f".staging-{TODAY}-{os.getpid()}"
    live.mkdir(parents=True)

    result = _run(tmp_path, data)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert not dead.exists(), out
    assert live.exists(), out


def test_staging_whose_lock_is_held_is_left_alone(tmp_path):
    data = _data(tmp_path)
    daily = tmp_path / "root" / "daily"
    held = daily / f".staging-{TODAY}-99999998"
    held.mkdir(parents=True)
    lock = Path(f"{held}.lock")
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _run(tmp_path, data)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert held.exists(), "a staging dir whose lock is held belongs to a live run"

    # Released: the next run sweeps it, lock file included.
    result = _run(tmp_path, data)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not held.exists()
    assert not lock.exists()


def test_a_terminated_run_removes_its_own_staging(tmp_path):
    """systemd's TimeoutStartSec SIGTERMs the cgroup; the EXIT trap must
    remove that run's staging rather than leaking a partial generation."""
    data = _data(tmp_path)
    slow = tmp_path / "slow_python"
    # Stalls inside the first online backup, as a wedged copy would.
    slow.write_text(f'#!/usr/bin/env bash\nsleep 60\nexec "{sys.executable}" "$@"\n')
    slow.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BACKUP_") and k not in {"OFFBOX_RSYNC_DEST", "KEEP_DAILY"}
    }
    env.update(
        APP_DIR=str(tmp_path / "app"),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "root"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=str(slow),
        DATE_STAMP=TODAY,
        BACKUP_MIN_FREE_KB="0",
        BACKUP_STORE_MARGIN_KB="0",
    )
    proc = subprocess.Popen(
        ["bash", str(SCRIPT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    daily = tmp_path / "root" / "daily"
    deadline = time.time() + 30
    while time.time() < deadline and not [p for p in daily.glob(".staging-*") if p.is_dir()]:
        time.sleep(0.1)
    assert [p for p in daily.glob(".staging-*") if p.is_dir()], "run never staged"
    os.killpg(proc.pid, signal.SIGTERM)  # the whole group, as systemd does
    proc.wait(timeout=30)
    assert proc.returncode != 0
    assert not list(daily.glob(".staging-*")), list(daily.iterdir())
    assert not (daily / TODAY).exists()
