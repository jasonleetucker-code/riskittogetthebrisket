"""``backup_dir`` archives the real directory, whatever the label says.

Both cases here were found by the FIRST real production run of the
backup + restore proof, and both discarded the entire nightly
generation — every retention artifact included — because of one
unrelated directory.

The tests run the actual function out of the shipped script rather than
re-implementing it, so a future edit to the script is what they check.
"""

from __future__ import annotations

import posixpath
import shlex
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "backup" / "riskit-state-backup.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")

# Every backup_* function reports a failed store through store_failed and asks
# optional_gate before writing (the CORE / OPTIONAL split).  A harness that
# extracts one function must extract these too, or the call is "command not
# found" and the harness tests something the script does not do.
_HELPERS = ("record_optional() {", "store_failed() {", "free_kb() {", "optional_gate() {")


def _funcs(*names: str) -> str:
    body = SCRIPT.read_text(encoding="utf-8")
    out = []
    for name in _HELPERS + names:
        start = body.index(name)
        out.append(body[start : body.index("\n}\n", start) + len("\n}\n")])
    return "".join(out)


_HARNESS_STATE = """
STORE_CLASS=core
OPTIONAL_ISSUES=0
OPTIONAL_NOT_BACKED_UP=""
OPTIONAL_MANIFEST_NAME=optional_stores.tsv
OPTIONAL_LOW_SPACE=""
BACKUP_SKIP_OPTIONAL=""
BACKUP_STORE_MARGIN_KB=0
"""


def _run_backup_dir(tmp_path: Path, src: Path, label: str = "") -> subprocess.CompletedProcess:
    """Source the script's helpers and call backup_dir on one directory.

    The script runs its whole backup at import, so the function is
    extracted by sed rather than sourced wholesale — the point is to
    exercise the SHIPPED text of ``backup_dir``, not a copy of it.
    """
    func = _funcs("backup_dir() {")

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
        + _HARNESS_STATE
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

    func = _funcs("backup_dir() {")

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
        + _HARNESS_STATE
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
        # C5-GD-02. A pregame prediction snapshot records the state that
        # produced a prediction BEFORE the outcome was known; once the
        # week scores, that state is gone. It is the one artifact here
        # that could not be re-created even with unlimited access to
        # Sleeper, so a generation that omits it is not a backup of
        # irreplaceable state.
        'backup_dir "${DATA_DIR}/game_day"',
        # AL-0 (plan §23 A9): the append-only learning-receipt store.
        'backup_sqlite "${DATA_DIR}/learning/receipts.sqlite"',
    ):
        assert expected in body, f"missing from the backup list: {expected}"


# ── AL-P2: every irreplaceable evidence store is in the backup list ───────
#
# docs/BRISKET_IDEAS.md §13.4 (AL-P2) and the register's AL-P2 addendum.  A
# store that is not here is not durable: one box loss erases it.

AL_P2_LINES = (
    # KTC Trade Database raw archive — a ~200-row rolling window upstream.
    'backup_sqlite "${DATA_DIR}/market_trades/archive.sqlite" "market_trades_archive.sqlite"',
    'backup_dir    "${DATA_DIR}/market_trades/reports" "market_trades_reports"',
    'backup_sqlite "${DATA_DIR}/consensus_edge.sqlite"',
    'backup_sqlite "${DATA_DIR}/source_archive/boards.sqlite" "source_archive_boards.sqlite"',
    'backup_sqlite "${DATA_DIR}/leagues/own_league_format_captures.sqlite"',
    # Its 2-hourly live:server rows are not reproducible by the rebuild.
    'backup_sqlite "${DATA_DIR}/temporal_ledger.sqlite"',
    'backup_sqlite "${DATA_DIR}/dfs/workspace.sqlite" "dfs_workspace.sqlite"',
    # Sharp transactions + Sharp league-format captures, now ONLINE.
    'backup_sqlite "${DATA_DIR}/intel/ledger.sqlite3" "intel_ledger.sqlite3"',
    'backup_dir "${DATA_DIR}/bdvm"',
    'backup_dir "${DATA_DIR}/forecast_archive"',
    'backup_dir "${DATA_DIR}/pick_forecast_snapshots"',
    'backup_dir "${DATA_DIR}/sparse_evidence_shadow"',
    'backup_dir "${DATA_DIR}/robust_filter_shadow"',
    # Already present; pinned here because the stale nightly copy lacked them.
    'backup_sqlite "${DATA_DIR}/retention/acquisition.sqlite"',
    'backup_sqlite "${DATA_DIR}/auction/auction.sqlite"',
)


@pytest.mark.parametrize("line", AL_P2_LINES)
def test_al_p2_store_is_in_the_backup_list(line):
    assert line in SCRIPT.read_text(encoding="utf-8"), f"missing from the backup list: {line}"


def _classified_backup_calls() -> list[tuple[str, str, list[str]]]:
    """Every backup_* call as (class, function, args); `optional` is the
    wrapper that makes a store OPTIONAL, everything else is CORE."""
    text = SCRIPT.read_text(encoding="utf-8").replace("\\\n", " ")
    calls = []
    for raw in text.splitlines():
        line = raw.strip()
        cls = "core"
        if line.startswith("optional "):
            cls, line = "optional", line[len("optional ") :].strip()
        head = line.split(" ", 1)[0]
        if head in {"backup_sqlite", "backup_file", "backup_dir"} and not line.endswith("{"):
            calls.append((cls, head, shlex.split(line)[1:]))
    return calls


def _backup_calls() -> list[tuple[str, list[str]]]:
    """Every backup_* call in the script, continuation lines joined."""
    return [(head, args) for _, head, args in _classified_backup_calls()]


def test_sqlite_stores_go_through_the_online_backup_helper():
    """A raw copy (backup_file) or a plain tar (backup_dir) of a live WAL
    database is a torn copy.  Every .sqlite / .sqlite3 path must use
    backup_sqlite, and the intel tar must exclude its live database."""
    calls = _backup_calls()
    assert len(calls) > 20, calls
    for head, args in calls:
        src = args[0]
        if head == "backup_sqlite":
            assert src.endswith((".sqlite", ".sqlite3")), src
        else:
            assert not src.endswith((".sqlite", ".sqlite3")), f"{head} on a database: {src}"
    intel = next(a for h, a in calls if h == "backup_dir" and a[0].endswith("/intel"))
    for member in ("intel/ledger.sqlite3", "intel/ledger.sqlite3-wal", "intel/ledger.sqlite3-shm"):
        assert member in intel[2:], f"intel tar must exclude the live database: {member}"


def test_artifact_names_are_unique_within_a_generation():
    """Outputs are named after the basename unless labelled; two stores
    sharing one would overwrite each other silently inside a generation."""
    names: dict[str, str] = {}
    for head, args in _backup_calls():
        src = args[0]
        label = args[1] if len(args) > 1 and head != "backup_file" else posixpath.basename(src)
        kind = {"backup_sqlite": "sqlite", "backup_file": "files", "backup_dir": "dirs"}[head]
        key = f"{kind}/{label}"
        # The one legitimate repeat is the same source under the same name in
        # alternative branches (the intel tar, with or without its ledger).
        assert names.get(key, src) == src, f"{key} produced by both {names[key]} and {src}"
        names[key] = src


def test_backup_dir_excludes_named_members(tmp_path):
    """The exclusion arguments keep the live database out of the tar and
    leave everything else in it."""
    src = tmp_path / "data" / "intel"
    src.mkdir(parents=True)
    for name in (
        "ledger.sqlite3",
        "ledger.sqlite3-wal",
        "ledger.sqlite3-shm",
        "snapshot_x.json",
        "ledger.sqlite3.bak-2026-07-30",
    ):
        (src / name).write_text("x", encoding="utf-8")

    dest = tmp_path / "dest"
    (dest / "dirs").mkdir(parents=True)
    harness = (
        textwrap.dedent(f"""
        set -uo pipefail
        DEST={dest.as_posix()}
        ERRORS=0
        ARTIFACTS=0
        OK_LIST=" "
        log()  {{ printf '[log] %s\\n' "$*"; }}
        warn() {{ printf '[warn] %s\\n' "$*"; }}
    """)
        + _HARNESS_STATE
        + _funcs("backup_dir() {")
        + f'\nbackup_dir "{src.as_posix()}" "intel" "intel/ledger.sqlite3" '
        + '"intel/ledger.sqlite3-wal" "intel/ledger.sqlite3-shm"\n'
        + 'printf "ARTIFACTS=%s ERRORS=%s\\n" "$ARTIFACTS" "$ERRORS"\n'
    )
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    assert "ARTIFACTS=1 ERRORS=0" in result.stdout, result.stdout + result.stderr
    listing = subprocess.run(
        ["tar", "-tzf", "intel.tar.gz"], capture_output=True, text=True, cwd=dest / "dirs"
    ).stdout.split()
    assert "intel/snapshot_x.json" in listing, listing
    assert "intel/ledger.sqlite3.bak-2026-07-30" in listing, listing
    for live in ("intel/ledger.sqlite3", "intel/ledger.sqlite3-wal", "intel/ledger.sqlite3-shm"):
        assert live not in listing, f"live database archived by tar: {live}"


def test_backup_sqlite_label_names_the_artifact(tmp_path):
    """The label renames the OUTPUT and the manifest entry; the source is
    still copied with the online-backup primitive and integrity-checked."""
    db = tmp_path / "data" / "market_trades" / "archive.sqlite"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()

    funcs = [_funcs("sqlite_backup() {", "sqlite_integrity_ok() {", "backup_sqlite() {")]
    dest = tmp_path / "dest"
    (dest / "sqlite").mkdir(parents=True)
    harness = (
        textwrap.dedent(f"""
        set -uo pipefail
        DEST={dest.as_posix()}
        PYTHON_BIN="{Path(sys.executable).as_posix()}"
        ERRORS=0
        ARTIFACTS=0
        OK_LIST=" "
        log()  {{ printf '[log] %s\\n' "$*"; }}
        warn() {{ printf '[warn] %s\\n' "$*"; }}
        backup_source_absent() {{ return 0; }}
    """)
        + _HARNESS_STATE
        + "".join(funcs)
        + f'\nbackup_sqlite "{db.as_posix()}" "market_trades_archive.sqlite"\n'
        + 'printf "ARTIFACTS=%s ERRORS=%s OK=[%s]\\n" "$ARTIFACTS" "$ERRORS" "$OK_LIST"\n'
    )
    try:
        result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    finally:
        con.close()
    assert "ARTIFACTS=1 ERRORS=0" in result.stdout, result.stdout + result.stderr
    assert " market_trades_archive.sqlite " in result.stdout, result.stdout
    assert (dest / "sqlite" / "market_trades_archive.sqlite.gz").is_file()
    assert not (dest / "sqlite" / "archive.sqlite.gz").exists()


# ── CORE / OPTIONAL classification (PR #1611 review) ──────────────────────
#
# An OPTIONAL store's failure keeps the generation; a CORE store's discards it.
# Which is which is a statement about the script's text, pinned here; the
# behaviour is driven end to end in test_state_backup_optional_stores.py.

PRE_AL_P2_CORE = {
    "user_kv.sqlite",
    "session_store.sqlite",
    "guest_passes.sqlite",
    "evidence.sqlite",
    "league_events.sqlite",
    "acquisition.sqlite",
    "board_history.sqlite",
    "auction.sqlite",
    "receipts.sqlite",
    "rank_history.jsonl",
    "public_league",
    "intel",
    "faab",
    "identity",
    "game_day",
    "playerctx_history",
}
AL_P2_OPTIONAL = {
    "market_trades_archive.sqlite",
    "market_trades_reports",
    "consensus_edge.sqlite",
    "source_archive_boards.sqlite",
    "own_league_format_captures.sqlite",
    "temporal_ledger.sqlite",
    "dfs_workspace.sqlite",
    "intel_ledger.sqlite3",
    "bdvm",
    "forecast_archive",
    "pick_forecast_snapshots",
    "sparse_evidence_shadow",
    "robust_filter_shadow",
}


def _artifact_name(head: str, args: list[str]) -> str:
    if head != "backup_file" and len(args) > 1:
        return args[1]
    return posixpath.basename(args[0])


def test_every_store_is_classified_core_or_optional_as_intended():
    seen: dict[str, set[str]] = {}
    for cls, head, args in _classified_backup_calls():
        seen.setdefault(_artifact_name(head, args), set()).add(cls)
    for name in PRE_AL_P2_CORE:
        assert seen.get(name) == {"core"}, f"{name} must be CORE, got {seen.get(name)}"
    for name in AL_P2_OPTIONAL:
        assert seen.get(name) == {"optional"}, f"{name} must be OPTIONAL, got {seen.get(name)}"
    unclassified = set(seen) - PRE_AL_P2_CORE - AL_P2_OPTIONAL
    assert (
        not unclassified
    ), f"new store(s) need a deliberate CORE/OPTIONAL decision: {unclassified}"


def test_core_stores_run_before_any_optional_store():
    """A large optional store must never consume the disk a core store needs."""
    classes = [cls for cls, _, _ in _classified_backup_calls()]
    first_optional = classes.index("optional")
    trailing_core = [
        _artifact_name(h, a)
        for i, (c, h, a) in enumerate(_classified_backup_calls())
        if c == "core" and i > first_optional
    ]
    # The intel tar is the one CORE artifact after an optional one: it has to
    # know whether the intel ledger's online copy succeeded.
    assert trailing_core in ([], ["intel"], ["intel", "intel"]), trailing_core


def test_a_failed_optional_store_is_recorded_and_keeps_errors_at_zero(tmp_path):
    """The function-level contract: an optional failure is a manifest row and
    an OPTIONAL_ISSUES count, never an ERROR."""
    bad = tmp_path / "data" / "consensus_edge.sqlite"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"this is not a sqlite database" * 64)
    dest = tmp_path / "dest"
    (dest / "sqlite").mkdir(parents=True)
    harness = (
        textwrap.dedent(f"""
        set -uo pipefail
        DEST={dest.as_posix()}
        PYTHON_BIN="{Path(sys.executable).as_posix()}"
        ERRORS=0
        ARTIFACTS=0
        OK_LIST=" "
        log()  {{ printf '[log] %s\\n' "$*"; }}
        warn() {{ printf '[warn] %s\\n' "$*"; }}
        backup_source_absent() {{ return 0; }}
    """)
        + _HARNESS_STATE
        + "BACKUP_ROOT="
        + dest.as_posix()
        + "\n"
        + _funcs(
            "optional() {", "sqlite_backup() {", "sqlite_integrity_ok() {", "backup_sqlite() {"
        )
        + f'\noptional backup_sqlite "{bad.as_posix()}"\n'
        + 'printf "ERRORS=%s OPTIONAL_ISSUES=%s CLASS=%s\\n" "$ERRORS" "$OPTIONAL_ISSUES" "$STORE_CLASS"\n'
        + f'\nbackup_sqlite "{bad.as_posix()}"\n'
        + 'printf "AFTER_CORE ERRORS=%s\\n" "$ERRORS"\n'
    )
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    out = result.stdout + result.stderr
    assert "ERRORS=0 OPTIONAL_ISSUES=1 CLASS=core" in out, out
    assert "AFTER_CORE ERRORS=1" in out, out
    manifest = (dest / "optional_stores.tsv").read_text(encoding="utf-8").splitlines()
    assert manifest and manifest[0].split("\t")[:2] == ["consensus_edge.sqlite", "failed"], manifest
    assert not (dest / "sqlite" / "consensus_edge.sqlite.gz").exists()
