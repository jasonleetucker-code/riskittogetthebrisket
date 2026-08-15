"""``backup_dir`` archives the real directory, whatever the label says.

Both cases here were found by the FIRST real production run of the
backup + restore proof, and both discarded the entire nightly
generation — every retention artifact included — because of one
unrelated directory.

The tests run the actual function out of the shipped script rather than
re-implementing it, so a future edit to the script is what they check.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "backup" / "riskit-state-backup.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _run_backup_dir(tmp_path: Path, src: Path, label: str = "") -> subprocess.CompletedProcess:
    """Source the script's helpers and call backup_dir on one directory.

    The script runs its whole backup at import, so the function is
    extracted by sed rather than sourced wholesale — the point is to
    exercise the SHIPPED text of ``backup_dir``, not a copy of it.
    """
    body = SCRIPT.read_text(encoding="utf-8")
    start = body.index("backup_dir() {")
    end = body.index("\n}\n", start) + len("\n}\n")
    func = body[start:end]

    dest = tmp_path / "dest"
    (dest / "dirs").mkdir(parents=True)
    harness = (
        textwrap.dedent(f"""
        set -uo pipefail
        DEST={dest}
        ERRORS=0
        ARTIFACTS=0
        OK_LIST=" "
        log()  {{ printf '[log] %s\\n' "$*"; }}
        warn() {{ printf '[warn] %s\\n' "$*"; }}
    """)
        + func
        + f'\nbackup_dir "{src}" "{label}"\n'
        + ('printf "ARTIFACTS=%s ERRORS=%s\\n" "$ARTIFACTS" "$ERRORS"\n')
    )
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)


def test_a_relabelled_directory_is_still_archived(tmp_path):
    """THE production defect: the label was used as the tar MEMBER.

    tar was asked for "playerctx_history" inside data/playerctx/, which
    does not exist — so the archive failed, the run counted an error, and
    the whole generation (retention stores included) was discarded.
    """
    src = tmp_path / "data" / "playerctx" / "history"
    src.mkdir(parents=True)
    (src / "snapshot_2026-08-11.json").write_text("{}", encoding="utf-8")

    result = _run_backup_dir(tmp_path, src, "playerctx_history")

    assert "ARTIFACTS=1 ERRORS=0" in result.stdout, result.stdout + result.stderr
    archive = tmp_path / "dest" / "dirs" / "playerctx_history.tar.gz"
    assert archive.exists(), "the label must name the OUTPUT file"

    listing = subprocess.run(["tar", "-tzf", str(archive)], capture_output=True, text=True).stdout
    assert "history/snapshot_2026-08-11.json" in listing, listing


def test_an_unlabelled_directory_still_uses_its_basename(tmp_path):
    src = tmp_path / "data" / "faab"
    src.mkdir(parents=True)
    (src / "crowd_history_dynasty_main.json").write_text("{}", encoding="utf-8")

    result = _run_backup_dir(tmp_path, src)

    assert "ARTIFACTS=1 ERRORS=0" in result.stdout, result.stdout + result.stderr
    assert (tmp_path / "dest" / "dirs" / "faab.tar.gz").exists()


def test_a_file_changing_mid_read_warns_but_keeps_the_generation(tmp_path):
    """GNU tar exits 1 for "file changed as we read it" and 2 for a fatal
    error; treating them alike discarded every OTHER artifact because one
    live directory was busy.

    Measured on production: data/intel holds a SQLite WAL the app writes
    continuously, so this fires routinely.
    """
    src = tmp_path / "data" / "intel"
    src.mkdir(parents=True)
    big = src / "ledger.sqlite3-wal"
    big.write_bytes(b"x" * (8 * 1024 * 1024))

    body = SCRIPT.read_text(encoding="utf-8")
    start = body.index("backup_dir() {")
    end = body.index("\n}\n", start) + len("\n}\n")
    func = body[start:end]

    dest = tmp_path / "dest"
    (dest / "dirs").mkdir(parents=True)
    # Grow the file while tar reads it — the real race, not a stub.
    harness = (
        textwrap.dedent(f"""
        set -uo pipefail
        DEST={dest}
        ERRORS=0
        ARTIFACTS=0
        OK_LIST=" "
        log()  {{ printf '[log] %s\\n' "$*"; }}
        warn() {{ printf '[warn] %s\\n' "$*"; }}
        ( for i in $(seq 1 400); do printf 'yyyyyyyy' >> "{big}"; done ) &
        writer=$!
    """)
        + func
        + f'\nbackup_dir "{src}"\nwait $writer\n'
        + ('printf "ARTIFACTS=%s ERRORS=%s\\n" "$ARTIFACTS" "$ERRORS"\n')
    )
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=120)

    # Whether the race actually fires is timing-dependent; what must NEVER
    # happen is an ERROR that discards the generation.
    assert "ERRORS=0" in result.stdout, result.stdout + result.stderr
    assert "ARTIFACTS=1" in result.stdout, result.stdout + result.stderr


def test_the_retention_artifacts_are_in_the_backup_list():
    """A retention store that is not in this list is not durable, which
    is the state C1-RET-01 was in before the tranche."""
    body = SCRIPT.read_text(encoding="utf-8")

    for expected in (
        'backup_sqlite "${DATA_DIR}/retention/evidence.sqlite"',
        'backup_sqlite "${DATA_DIR}/retention/league_events.sqlite"',
        'backup_sqlite "${DATA_DIR}/board_history.sqlite"',
        'backup_file   "${DATA_DIR}/rank_history.jsonl"',
        'backup_dir "${DATA_DIR}/faab"',
        'backup_dir "${DATA_DIR}/identity"',
        'backup_dir "${DATA_DIR}/playerctx/history" "playerctx_history"',
    ):
        assert expected in body, f"missing from the backup list: {expected}"
