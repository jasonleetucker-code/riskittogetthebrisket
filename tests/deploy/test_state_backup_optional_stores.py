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
import re
import shutil
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


# ── PR #1611 re-review ────────────────────────────────────────────────────


def _stub_bin(tmp_path: Path, **scripts: str) -> str:
    """A PATH prefix whose named commands are replaced by the given bodies."""
    stub = tmp_path / "stub-bin"
    stub.mkdir(exist_ok=True)
    for name, body in scripts.items():
        path = stub / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
    return f"{stub}:{os.environ['PATH']}"


def test_failing_to_record_an_optional_failure_keeps_the_generation(tmp_path):
    """Finding A.  On ENOSPC the optional_stores.tsv append itself fails; under
    errexit that used to exit 1 and the EXIT trap deleted the staging holding
    the CORE stores.  Simulated by making the manifest path a directory at the
    moment the optional store fails (the staging name carries the run's PID, so
    it cannot be prepared beforehand)."""
    data = _data(tmp_path)
    _sqlite(data / "consensus_edge.sqlite")
    wrapper = tmp_path / "python_fails_consensus_edge"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        # sqlite_backup is invoked as: python - <src> <dst>
        'if [[ "${3:-}" == */sqlite/consensus_edge.sqlite ]]; then\n'
        '    : > "$3"   # a partial artifact\n'
        '    mkdir -p "$(dirname "$(dirname "$3")")/optional_stores.tsv"\n'
        "    exit 1\n"
        "fi\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = _run(tmp_path, data, PYTHON_BIN=str(wrapper))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert (gen / "sqlite" / "session_store.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "consensus_edge.sqlite").exists(), "partial artifact left"
    assert not (gen / "sqlite" / "consensus_edge.sqlite.gz").exists()
    assert "could not record OPTIONAL store consensus_edge.sqlite" in out, out
    assert "complete WITH WARNINGS" in out, out


def test_unmeasurable_free_space_sheds_optional_and_still_writes_core(tmp_path):
    """Finding C.  A failing `df` under errexit + pipefail used to exit the run
    silently (status 1, no generation); unknown must mean short."""
    data = _data(tmp_path)
    _sqlite(data / "consensus_edge.sqlite")
    _sqlite(data / "retention" / "evidence.sqlite")  # CORE

    result = _run(tmp_path, data, PATH=_stub_bin(tmp_path, df="exit 1"))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert (gen / "sqlite" / "evidence.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "consensus_edge.sqlite.gz").exists()
    assert _manifest(gen) == {"consensus_edge.sqlite": "skipped_space_unmeasurable"}, out
    assert "could not be measured" in out, out


def test_an_unmeasurable_store_size_is_skipped_not_assumed_small(tmp_path):
    """Findings C + D.  With a previous generation present the run-level guard
    `du`s it, and the per-store gate `du`s each source: a failing `du` must
    neither exit the run nor let the store through as if it were tiny."""
    data = _data(tmp_path)
    _sqlite(data / "consensus_edge.sqlite")
    first = _run(tmp_path, data)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(tmp_path, data, PATH=_stub_bin(tmp_path, du="exit 1"))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "consensus_edge.sqlite.gz").exists()
    assert _manifest(gen) == {"consensus_edge.sqlite": "skipped_space_unmeasurable"}, out


def test_the_per_store_estimate_counts_the_wal(tmp_path):
    """Finding D.  The online copy carries what is still in the -wal, so a
    store whose WAL alone tips it over the margin is shed."""
    data = _data(tmp_path)
    _sqlite(data / "consensus_edge.sqlite")
    wal_bytes = 64 * 1024 * 1024
    (data / "consensus_edge.sqlite-wal").write_bytes(os.urandom(wal_bytes))
    wal_kb = wal_bytes // 1024
    src_kb = int(
        subprocess.run(
            ["du", "-sk", str(data / "consensus_edge.sqlite")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
    )
    root = tmp_path / "root"
    root.mkdir()
    st = os.statvfs(root)
    avail_kb = st.f_bavail * st.f_frsize // 1024
    # Halfway: 2*src + margin fits with wal_kb to spare; 2*(src+wal) + margin
    # overshoots by wal_kb.  A 64 MiB band absorbs ordinary disk churn.
    margin = avail_kb - 2 * src_kb - wal_kb
    assert margin > 0, "test needs more free disk than it has"

    result = _run(tmp_path, data, BACKUP_STORE_MARGIN_KB=str(margin))
    out = result.stdout + result.stderr

    assert result.returncode == 3, out
    assert _manifest(_gen(tmp_path)) == {"consensus_edge.sqlite": "skipped_low_space"}, out
    assert "incl. WAL" in out, out


def test_a_reused_pid_never_inherits_a_dead_runs_staging(tmp_path):
    """Finding E.  A SIGKILLed run leaves .staging-<date>-<pid>; if that PID is
    reused the same day, the sweep skips "this run's own" name.  `exec` keeps
    the PID, so the staging can be planted under the exact name the script
    will compute."""
    data = _data(tmp_path)
    daily = tmp_path / "root" / "daily"
    plant = (
        f'stg="{daily}/.staging-{TODAY}-$$"; '
        'mkdir -p "$stg/sqlite"; '
        'printf junk > "$stg/sqlite/dead_run_partial.sqlite.gz"; '
        "printf 'consensus_edge.sqlite\\tfailed\\tstale\\n' > \"$stg/optional_stores.tsv\"; "
        f'exec bash "{SCRIPT}"'
    )
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
        PYTHON_BIN=sys.executable,
        DATE_STAMP=TODAY,
        BACKUP_MIN_FREE_KB="0",
        BACKUP_STORE_MARGIN_KB="0",
    )
    result = subprocess.run(
        ["bash", "-c", plant], env=env, capture_output=True, text=True, timeout=300
    )
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    gen = _gen(tmp_path)
    assert (gen / "sqlite" / "user_kv.sqlite.gz").is_file(), out
    assert not (gen / "sqlite" / "dead_run_partial.sqlite.gz").exists(), out
    assert not (gen / "optional_stores.tsv").exists(), out


# ── the post-deploy proof: known optional names (G) + the nightly status (B) ─

PROOF = REPO / "deploy" / "diagnostics" / "retention_backup_restore_proof.sh"


def _optional_names_in_writer() -> set[str]:
    names = set()
    pattern = re.compile(r'^optional\s+backup_(?:sqlite|dir|file)\s+"([^"]+)"(?:\s+"([^"]+)")?')
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line.strip())
        if m:
            names.add(m.group(2) or Path(m.group(1)).name)
    return names


def test_the_proofs_known_optional_set_matches_the_writer():
    body = PROOF.read_text(encoding="utf-8")
    m = re.search(r'^KNOWN_OPTIONAL_STORES=" (.*) "$', body, re.M)
    assert m, "KNOWN_OPTIONAL_STORES not found in the proof"
    writer = _optional_names_in_writer()
    assert len(writer) >= 10, writer
    assert set(m.group(1).split()) == writer


def _proof_app(tmp_path: Path) -> tuple[Path, Path]:
    app = tmp_path / "app"
    shutil.copytree(REPO / "deploy", app / "deploy")
    data = _data(tmp_path)
    _sqlite(
        data / "retention" / "evidence.sqlite",
        "CREATE TABLE scoring_card_payloads (card_hash TEXT PRIMARY KEY)",
        "CREATE TABLE scoring_card_observations (sleeper_league_id TEXT, observed_at TEXT)",
        "CREATE TABLE trending_observations (source TEXT, observed_at TEXT)",
    )
    return app, data


def _run_proof(tmp_path: Path, app: Path, data: Path, **env: str) -> subprocess.CompletedProcess:
    full = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BACKUP_") and k not in {"OFFBOX_RSYNC_DEST", "KEEP_DAILY"}
    }
    full.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "root"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        DATE_STAMP=TODAY,
        BACKUP_MIN_FREE_KB="0",
        BACKUP_STORE_MARGIN_KB="0",
        # No real unit on a test host; tests that want one stub systemctl.
        NIGHTLY_UNIT="riskit-state-backup-test-absent.service",
    )
    full.update(env)
    return subprocess.run(
        ["bash", str(PROOF)], env=full, capture_output=True, text=True, timeout=300
    )


def test_a_manifest_row_cannot_excuse_a_missing_core_artifact(tmp_path):
    """Finding G.  The manifest is a file in the generation; only a name the
    writer wraps in `optional` may be explained by it."""
    app, data = _proof_app(tmp_path)
    first = _run_proof(tmp_path, app, data)
    assert first.returncode == 0, first.stdout + first.stderr

    gen = _gen(tmp_path)
    (gen / "sqlite" / "evidence.sqlite.gz").unlink()
    (gen / "optional_stores.tsv").write_text(
        "evidence.sqlite\tskipped_requested\tforged\n", encoding="utf-8"
    )
    result = _run_proof(tmp_path, app, data, RUN_BACKUP="0")
    out = result.stdout + result.stderr
    assert result.returncode == 2, out
    assert "MISSING from the backup" in out, out


def test_a_known_optional_row_is_still_explained(tmp_path):
    app, data = _proof_app(tmp_path)
    _sqlite(data / "consensus_edge.sqlite")
    first = _run_proof(tmp_path, app, data)
    assert first.returncode == 0, first.stdout + first.stderr

    gen = _gen(tmp_path)
    (gen / "sqlite" / "consensus_edge.sqlite.gz").unlink()
    (gen / "optional_stores.tsv").write_text(
        "consensus_edge.sqlite\tskipped_space_unmeasurable\tdf failed\n", encoding="utf-8"
    )
    result = _run_proof(tmp_path, app, data, RUN_BACKUP="0")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "::warning title=Backup proof: optional store::" in result.stdout, out


def _systemctl_stub(result: str, status: str) -> str:
    # Called as: systemctl show <unit> -p <Property> --value
    return (
        'case "$*" in\n'
        "  *' -p LoadState '*) echo loaded ;;\n"
        f"  *' -p Result '*) echo {result} ;;\n"
        f"  *' -p ExecMainStatus '*) echo {status} ;;\n"
        "  *' -p ExecMainExitTimestamp '*) echo 'Thu 2026-10-01 02:31:07 UTC' ;;\n"
        "esac"
    )


def test_the_proof_surfaces_a_nightly_exit_3(tmp_path):
    """Finding B.  The proof's own run skips the two large stores, so the only
    place a nightly exit 3 can surface is the nightly unit's own status."""
    app, data = _proof_app(tmp_path)
    result = _run_proof(
        tmp_path,
        app,
        data,
        NIGHTLY_UNIT="riskit-state-backup.service",
        PATH=_stub_bin(tmp_path, systemctl=_systemctl_stub("success", "3")),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "::warning title=Backup proof: optional store::the nightly" in result.stdout, out
    assert "exited 3" in result.stdout, out


def test_the_proof_reports_a_clean_nightly_without_a_warning(tmp_path):
    app, data = _proof_app(tmp_path)
    result = _run_proof(
        tmp_path,
        app,
        data,
        NIGHTLY_UNIT="riskit-state-backup.service",
        PATH=_stub_bin(tmp_path, systemctl=_systemctl_stub("success", "0")),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "last run (Thu 2026-10-01 02:31:07 UTC) exit 0" in out, out
    assert "::warning" not in result.stdout, out


def test_the_proof_warns_on_a_failed_nightly_without_failing_itself(tmp_path):
    app, data = _proof_app(tmp_path)
    result = _run_proof(
        tmp_path,
        app,
        data,
        NIGHTLY_UNIT="riskit-state-backup.service",
        PATH=_stub_bin(tmp_path, systemctl=_systemctl_stub("exit-code", "1")),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "::warning title=Backup proof: nightly backup::" in result.stdout, out


def test_the_proof_skips_the_nightly_check_when_the_unit_is_not_installed(tmp_path):
    app, data = _proof_app(tmp_path)
    result = _run_proof(tmp_path, app, data)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "last exit status is not checked" in out, out


# ── Signals private store: backed up, restorable, credentials excluded ──


def test_the_signals_store_is_backed_up_and_restores_without_the_session(tmp_path):
    """The box-local Signals releases are durable state (the vendor serves
    current values only), so the nightly copies them — and only them: the
    owner session lives under its own owner and must never ride along."""
    data = _data(tmp_path)
    store = data / "sources" / "signals"
    release = store / "values" / "sf" / "releases" / "2026-10-04T00-00-00Z.json"
    release.parent.mkdir(parents=True)
    release.write_text('{"rowCount": 1}', encoding="utf-8")
    (store / "values" / "sf" / "fetch_state.json").write_text("{}", encoding="utf-8")
    (store / "board").mkdir(parents=True)
    (store / "board" / "signalsSf.csv").write_text("name,rank\nA,1\n", encoding="utf-8")
    # A session file beside the data tree, as if mis-configured: never copied.
    auth = tmp_path / "var" / "lib" / "signals-auth"
    auth.mkdir(parents=True)
    (auth / "session.json").write_text('{"refreshToken": "secret"}', encoding="utf-8")

    res = _run(tmp_path, data)
    assert res.returncode in (0, 3), res.stdout + res.stderr
    tgz = _gen(tmp_path) / "dirs" / "signals_sources.tar.gz"
    assert tgz.is_file(), res.stdout + res.stderr

    restore = tmp_path / "restore"
    with tarfile.open(tgz) as tf:
        names = tf.getnames()
        tf.extractall(restore, filter="data")
    assert "signals/values/sf/releases/2026-10-04T00-00-00Z.json" in names
    assert (restore / "signals" / "board" / "signalsSf.csv").read_text(
        encoding="utf-8"
    ) == "name,rank\nA,1\n"
    assert not any("session" in n or "signals-auth" in n for n in names), names
    for member in (_gen(tmp_path)).rglob("*"):
        assert "signals-auth" not in member.name
