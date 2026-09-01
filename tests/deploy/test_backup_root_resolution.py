"""The backup writer and the restore proof must agree on WHERE the backup is.

Production proof run 31872681688 failed with "no backup generation under
/var/backups/riskit-state/daily" while that night's backup had *succeeded*:
the primary root was not writable, the writer fell back to the service
user's home and promoted a complete generation there, and the proof — which
resolved the location itself, from the same two defaults — went on reading
the empty primary.

Two independent implementations of one decision produce exactly one class of
bug, so there is now one owner (``deploy/backup/backup_root_lib.sh``) plus a
machine-readable result the writer emits and the proof reads.  The invariant
these tests hold is:

    the location that successfully receives the promoted backup
      ==
    the location the restore proof subsequently inspects

Everything here runs the SHIPPED scripts end to end — the real
``riskit-state-backup.sh`` under the real
``retention_backup_restore_proof.sh``, against a throwaway data dir. Nothing
is reimplemented, so an edit to either script is what these check.

Unwritable roots are constructed by putting a regular FILE where the root's
parent directory would be: ``mkdir -p`` then fails for every user including
root, so the fallback path is exercised deterministically rather than
depending on who the test runs as.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROOF = REPO / "deploy" / "diagnostics" / "retention_backup_restore_proof.sh"
LIB = REPO / "deploy" / "backup" / "backup_root_lib.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")

# ONE clock, read ONCE, for the whole module.
#
# ``DATE_STAMP`` (``deploy/backup/riskit-state-backup.sh``) exists so the
# script under test names its generation from this same instant rather than
# from its own ``date -u`` — added 2026-08-17 after a suite that straddled UTC
# midnight failed a docs-only pull request at 00:03:49Z.
#
# That pinned the SCRIPT and stopped there.  Two tests still derived a
# relative date from a SECOND, later clock read, and a run that crosses
# midnight between import and those tests collapses ``yesterday`` onto
# ``TODAY`` — the "older" generation is then created at the very path the
# newer one occupies, its 09:00Z pointer outranks the real 00:00Z one, and
# the proof fails on a generation the test never populated.  Measured on
# PR #886 run 32082222024 (imported 23:52:50Z, failed 00:01:47Z).
#
# So every date in this file is derived from ``_TODAY_DT``.  Reading the
# clock a second time anywhere here reintroduces the race; the guard in
# ``test_every_date_in_this_module_comes_from_one_clock`` is what stops it.
_TODAY_DT = datetime.now(timezone.utc)
TODAY = _TODAY_DT.strftime("%Y-%m-%d")


def _sqlite(path: Path, ddl: tuple[str, ...] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for stmt in ddl:
            con.execute(stmt)
        con.commit()
    finally:
        con.close()


def _app(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway APP_DIR holding a real copy of deploy/ and a small data dir."""
    app = tmp_path / "app"
    shutil.copytree(REPO / "deploy", app / "deploy")

    data = app / "data"
    # BACKUP_REQUIRED defaults to these two; without them the writer
    # correctly discards the snapshot.
    _sqlite(data / "user_kv.sqlite", ("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)",))
    _sqlite(data / "session_store.sqlite", ("CREATE TABLE sessions (id TEXT PRIMARY KEY)",))
    # One real retention artifact, so the proof is proving something.
    _sqlite(
        data / "retention" / "evidence.sqlite",
        (
            "CREATE TABLE scoring_card_payloads (card_hash TEXT PRIMARY KEY)",
            "CREATE TABLE scoring_card_observations (sleeper_league_id TEXT, observed_at TEXT)",
            "CREATE TABLE trending_observations (source TEXT, observed_at TEXT)",
        ),
    )
    return app, data


def _run_proof(
    app: Path,
    data: Path,
    primary: Path,
    fallback: Path,
    run_backup: str = "1",
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(primary),
        BACKUP_FALLBACK_ROOT=str(fallback),
        PYTHON_BIN=sys.executable,
        RUN_BACKUP=run_backup,
        # Pin the generation date so the script and this module cannot
        # disagree across a UTC midnight.  ``TODAY`` is evaluated once at
        # import; the script read the clock when it ran, and a suite that
        # straddled midnight failed on that alone (2026-08-17T00:03:49Z).
        DATE_STAMP=TODAY,
    )
    return subprocess.run(
        ["bash", str(PROOF)], env=env, capture_output=True, text=True, timeout=300
    )


def _blocked(tmp_path: Path, name: str) -> Path:
    """A root whose parent is a regular file — `mkdir -p` fails for anyone."""
    blocker = tmp_path / f"{name}-blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    return blocker / name


def _write_pointer(root: Path, generation: Path, promoted_at: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "last_generation").write_text(
        "schema=1\n"
        f"effective_root={root}\n"
        f"generation={generation}\n"
        f"date_stamp={TODAY}\n"
        "artifacts=3\n"
        f"promoted_at={promoted_at}\n",
        encoding="utf-8",
    )


# ── discovery must not fail OPEN ─────────────────────────────────────
#
# Every case below was found by adversarially reviewing the first version
# of this repair, and each was reproduced end to end before being fixed.
# They share one shape: the proof reports success having certified a
# generation that is not the newest one, or not production's at all.


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses the permission bits this exercises")
def test_an_unreadable_candidate_root_refuses_rather_than_certifying_an_older_one(tmp_path):
    """The nightly runs as root and chmods its root 0700.

    An unprivileged prover therefore sees the primary as unreadable — and
    if that reads as "empty", the proof goes on to certify the OLDER
    generation in the readable fallback and exits 0. That is a worse bug
    than the one this file exists to fix: it is the same disagreement
    about location, inverted into a false pass.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    # A FRESH generation in the primary, which we then make unreadable.
    fresh = primary / "daily" / TODAY
    fresh.mkdir(parents=True)
    _write_pointer(primary, fresh, "2026-08-15T02:30:00Z")
    # A STALE one in the readable fallback.
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    primary.chmod(0o000)
    try:
        result = _run_proof(app, data, primary, fallback, run_backup="0")
    finally:
        primary.chmod(0o755)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert "refusing to certify an older one" in out, out
    # The stale candidate is still LOGGED — every candidate examined is,
    # so the refusal is legible. What must not happen is proving it.
    assert f"[backup-proof] proving generation: {stale}" not in out, out
    assert "proven for every artifact" not in out, out


def test_a_root_whose_daily_cannot_be_a_directory_refuses(tmp_path):
    """ROOT-SAFE cover for the `daily/` readability arm.

    The permission version of this needs a non-root runner, and under a root
    runner the whole arm could be reverted to root-only with a green suite —
    so the same policy is also exercised with a `daily` that simply cannot be
    read as a directory, which no uid can bypass.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    primary.mkdir()
    (primary / "daily").write_text("not a directory", encoding="utf-8")
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert f"[backup-proof] proving generation: {stale}" not in out, out


def test_a_root_behind_a_symlink_through_a_non_directory_refuses(tmp_path):
    """ROOT-SAFE cover for the ancestor walk's `! -L` conjunct.

    The permission version of this skips as root, which left the whole walk
    deletable with a green suite under a root runner. This construction uses
    no permission bit at all: the root is a symlink whose target sits below a
    regular FILE, so `-e` is false via ENOTDIR while `lstat` still sees the
    link. Without `! -L` the walk steps off the symlink onto a readable
    lexical parent and reports "does not exist".
    """
    app, data = _app(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    primary = tmp_path / "primary"
    primary.symlink_to(blocker / "riskit-state")

    fallback = tmp_path / "fallback"
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert "does not exist" not in out, "an unresolvable symlink is not an absent root"
    assert f"[backup-proof] proving generation: {stale}" not in out, out


def test_one_unresolvable_entry_in_daily_does_not_empty_the_whole_root(tmp_path):
    """A glob match is lstat; `-d` is stat. One junk entry is not an empty root.

    Taking only the newest match and failing the root when it is not a
    directory discarded every older REAL generation under it and reported the
    root as empty — so an older generation elsewhere was certified, exit 0.
    One dangling symlink, one stray file, or one generation on an unmounted
    volume was enough, and production's nightly shape (a real generation with
    no pointer beside it) is exactly where it bites.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()  # the nightly writes no pointer

    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    # A dated entry that lists but cannot be resolved as a directory.
    (primary / "daily" / "2099-12-31").symlink_to(tmp_path / "unmounted-volume")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "cannot be resolved" in out, out
    assert f"[backup-proof] proving generation: {stale}" not in out, out
    assert "proven for every artifact" not in out, out


def test_a_stray_file_in_daily_is_also_indeterminate(tmp_path):
    """Same rule, no symlink involved — a plain file named like a generation."""
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()
    (primary / "daily" / "2099-12-31").write_text("", encoding="utf-8")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "cannot be resolved" in out, out


def test_an_older_junk_entry_does_not_block_a_newer_real_generation(tmp_path):
    """Fail-closed must not become fail-always.

    An unresolvable entry OLDER than the newest real generation cannot be a
    newer generation, so it must not refuse — otherwise one stray file would
    disable the proof permanently.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()
    (primary / "daily" / "2019-01-01").symlink_to(tmp_path / "long-gone")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out


def test_a_root_whose_daily_is_an_unresolvable_symlink_refuses(tmp_path):
    """ROOT-SAFE cover for the `! -L` pairing on the `daily/` arm.

    `-e` dereferences, so a `daily/` symlink whose target cannot be resolved
    is `! -e` too — and without the pairing that short-circuits the whole
    readability check and reports "holds no generation", letting an older
    root be certified. A dangling symlink reproduces it at any uid: it is
    emphatically not "a root that was never written".
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    primary.mkdir()
    (primary / "daily").symlink_to(tmp_path / "somewhere-unreachable")
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert f"[backup-proof] proving generation: {stale}" not in out, out


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses the permission bits this exercises")
def test_a_root_with_an_unreadable_daily_refuses(tmp_path):
    """The root and its `daily/` are permissioned independently.

    The writer chmods only the root; `daily/` takes whatever `umask 077` gave
    it. A root readable with an unreadable `daily/` used to report "holds no
    generation" and let an older root be certified.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    fresh = primary / "daily" / TODAY
    fresh.mkdir(parents=True)
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    (primary / "daily").chmod(0o000)
    try:
        result = _run_proof(app, data, primary, fallback, run_backup="0")
    finally:
        (primary / "daily").chmod(0o755)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert f"[backup-proof] proving generation: {stale}" not in out, out


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses the permission bits this exercises")
def test_a_symlinked_root_pointing_somewhere_unreachable_refuses(tmp_path):
    """Relocating backups to another volume via a symlink is ordinary.

    `-e` dereferences and `dirname` does not, so the ancestor walk used to
    step OFF the symlink onto its readable lexical parent and call the root
    "absent" — reproducing the very fail-open the walk was added to close.
    """
    app, data = _app(tmp_path)
    real = tmp_path / "vol" / "riskit-state"
    (real / "daily" / TODAY).mkdir(parents=True)
    primary = tmp_path / "primary"
    primary.symlink_to(real)

    fallback = tmp_path / "fallback"
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    (tmp_path / "vol").chmod(0o000)
    try:
        result = _run_proof(app, data, primary, fallback, run_backup="0")
    finally:
        (tmp_path / "vol").chmod(0o755)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert "does not exist" not in out, "a symlink to an unreachable target is not an absent root"
    assert f"[backup-proof] proving generation: {stale}" not in out, out


def test_a_root_behind_a_non_directory_parent_refuses(tmp_path):
    """ROOT-SAFE cover for the ancestor walk.

    The faithful EACCES version needs a non-root runner. This one puts a
    regular file where an ancestor directory belongs, which no uid can
    traverse, so the walk's refusal is exercised at every privilege level.
    """
    app, data = _app(tmp_path)
    primary = _blocked(tmp_path, "primary")
    fallback = tmp_path / "fallback"
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "NOT READABLE" in out, out
    assert f"[backup-proof] proving generation: {stale}" not in out, out


def test_selection_compares_the_date_before_the_instant(tmp_path):
    """A derived midnight and a real `promoted_at` are not one currency.

    Across 00:00 UTC a run mints `daily/<yesterday>` carrying a `promoted_at`
    of *today*, which on a bare-stamp comparison beats a genuinely newer
    pointerless `daily/<today>` sitting at `T00:00:00Z`.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    # The genuinely newer generation, discovered by scan (no pointer).
    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()

    # Yesterday's directory, stamped with an instant later in the day.
    yesterday = (_TODAY_DT - timedelta(days=1)).strftime("%Y-%m-%d")
    older = fallback / "daily" / yesterday
    older.mkdir(parents=True)
    _write_pointer(fallback, older, f"{TODAY}T09:00:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out
    assert f"[backup-proof] proving generation: {older}" not in out, out


def test_a_generation_without_a_pointer_is_still_found(tmp_path):
    """The pointer is younger than the backups.

    Production's nightly runs a root-owned copy of the writer that only
    apply_hardening.sh refreshes, so real generations land with no pointer
    beside them. A discovery pass that could only follow pointers would be
    blind to every one of them — and would silently prefer an older
    generation that happens to have one.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    # Build a real, complete generation in the primary, then remove its
    # pointer to imitate the old writer.
    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()

    # An older, pointered generation next door must not win.
    stale = fallback / "daily" / "2026-01-02"
    stale.mkdir(parents=True)
    _write_pointer(fallback, stale, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "via on-disk scan" in out, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out


def test_a_stale_pointer_does_not_mask_a_newer_generation_in_its_own_root(tmp_path):
    """The pointer is a hint, not an upper bound.

    It is written AFTER promotion and a failed write is only a warning, so
    a run killed in that window leaves a stale pointer sitting in front of
    a newer generation in the same root. Consulting the disk only when the
    pointer says *nothing* lets that stale pointer win unconditionally.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr

    # Age the real generation, and leave the pointer naming it — then put a
    # newer dated generation on disk beside it with no pointer of its own.
    real = primary / "daily" / TODAY
    older = primary / "daily" / "2026-01-02"
    shutil.copytree(real, older)
    _write_pointer(primary, older, "2026-01-02T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "NEWER generation is on disk" in out, out
    assert f"[backup-proof] proving generation: {real}" in out, out


def test_the_proof_reads_the_run_s_result_rather_than_re_deriving(tmp_path):
    """The headline mechanism, pinned.

    Re-deriving the location — `ls -1d $BACKUP_ROOT/daily/20*`, which is
    what `main` did — is the defect. Here the writer records a generation
    the re-derivation could never name, so a proof that re-derives cannot
    pass this.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    # A decoy the old `ls .../daily/20*` scan WOULD have picked: newest by
    # name, in the requested primary, but not what any run promoted.
    decoy = primary / "daily" / "2099-12-31"
    decoy.mkdir(parents=True)

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out
    # The decoy now also appears in the writer's prune warning, which is
    # correct — what must not happen is proving it.
    assert (
        f"proving generation: {decoy}" not in out
    ), "the proof re-derived the location instead of reading the result"


def test_the_on_disk_scan_takes_the_newest_dated_directory(tmp_path):
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()
    for older in ("2019-01-01", "2020-06-30", "2026-01-02"):
        (primary / "daily" / older).mkdir(parents=True)

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out


def test_an_incumbent_with_an_unknown_stamp_is_not_a_blank_slate(tmp_path):
    """`-z BEST_AT` let any later candidate win unconditionally.

    A pointer whose promoted_at line is missing gave the incumbent an
    empty stamp, and an empty incumbent accepted the next candidate
    without comparing anything — measured selecting a 2020 generation over
    a same-day one.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr

    ptr = primary / "last_generation"
    ptr.write_text(
        "\n".join(
            line
            for line in ptr.read_text(encoding="utf-8").splitlines()
            if not line.startswith("promoted_at=")
        )
        + "\n",
        encoding="utf-8",
    )

    ancient = fallback / "daily" / "2020-01-01"
    ancient.mkdir(parents=True)
    _write_pointer(fallback, ancient, "2020-01-01T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out
    # The ancient candidate is LOGGED on purpose — selection must be
    # visible — but it must not be the one proven.
    assert f"[backup-proof] proving generation: {ancient}" not in out, out


def test_proving_the_fallback_lineage_says_so(tmp_path):
    """A green tick must not be read as "the nightly's backups restore"."""
    app, data = _app(tmp_path)
    primary = _blocked(tmp_path, "primary")
    fallback = tmp_path / "fallback"

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "NOT covered by this run" in out, out


# ── the production defect ────────────────────────────────────────────


def test_an_unwritable_primary_root_falls_back_and_the_proof_follows(tmp_path):
    """THE regression. Proof run 31872681688, reproduced.

    The writer must fall back, and the proof must inspect the location the
    writer actually used — not the primary it was asked for.
    """
    app, data = _app(tmp_path)
    primary = _blocked(tmp_path, "primary")
    fallback = tmp_path / "fallback"

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] effective backup root: {fallback}" in out, out
    assert f"[backup-proof] proving generation: {fallback}/daily/{TODAY}" in out, out
    # The proof read the fallback generation back, not merely located it.
    assert "C1-RET-04/05 evidence.sqlite: PRAGMA integrity_check = ok" in out, out
    # And the backup really is there.
    assert (fallback / "daily" / TODAY / "sqlite" / "evidence.sqlite.gz").is_file()


def test_a_writable_primary_root_is_used_by_both(tmp_path):
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] effective backup root: {primary}" in out, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out
    assert not fallback.exists(), "the fallback must not be touched when the primary works"


# ── failures must stay failures ──────────────────────────────────────


def test_a_fatal_backup_failure_is_not_dressed_up_as_a_proof(tmp_path):
    """Neither root usable: the writer exits 1 and the proof cannot run.

    The one outcome that must never happen is exit 0.
    """
    app, data = _app(tmp_path)
    primary = _blocked(tmp_path, "primary")
    fallback = _blocked(tmp_path, "fallback")

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "backup run FAILED" in out, out


def test_a_backup_that_loses_required_state_still_fails(tmp_path):
    """The required-artifact manifest keeps its authority through the change."""
    app, data = _app(tmp_path)
    (data / "user_kv.sqlite").unlink()
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "backup run FAILED" in out, out
    # Nothing was promoted, so nothing can be "proven".
    assert not (primary / "daily" / TODAY).exists()


def test_a_recorded_generation_that_no_longer_exists_is_a_failure(tmp_path):
    """A pointer to a pruned generation is not a generation."""
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    shutil.rmtree(primary / "daily" / TODAY)

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "no backup generation in any readable candidate root" in out, out


def test_no_recorded_generation_anywhere_is_a_failure(tmp_path):
    app, data = _app(tmp_path)

    result = _run_proof(app, data, tmp_path / "primary", tmp_path / "fallback", run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "no backup generation in any readable candidate root" in out, out


# ── the proof must prove the generation this run wrote ───────────────


def test_the_proof_cannot_be_captured_by_a_pointer_in_the_other_root(tmp_path):
    """A newer pointer in the fallback must not hijack a run that just
    promoted into the primary.

    With RUN_BACKUP=1 the generation comes from the result THIS run wrote,
    so selection is not a search at all. The decoy names an empty directory:
    if it were ever selected the proof would report the retention artifact
    missing and exit 2, so this fails loudly in both directions.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    decoy = fallback / "daily" / "2099-01-01"
    decoy.mkdir(parents=True)
    _write_pointer(fallback, decoy, "2099-01-01T00:00:00Z")

    result = _run_proof(app, data, primary, fallback)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out
    assert str(decoy) not in out, out


def test_discovery_takes_the_newest_recorded_generation(tmp_path):
    """RUN_BACKUP=0 across both roots: newest promoted_at wins, and every
    candidate examined is logged rather than silently passed over."""
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr

    # A genuine, newer generation in the other root.
    newer = fallback / "daily" / TODAY
    newer.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(primary / "daily" / TODAY, newer)
    _write_pointer(fallback, newer, "2099-01-01T00:00:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"candidate root {primary}: generation" in out, out
    assert f"candidate root {fallback}: generation" in out, out
    assert f"[backup-proof] effective backup root: {fallback}" in out, out
    assert f"[backup-proof] proving generation: {newer}" in out, out


# ── structural: one owner, not two ───────────────────────────────────


def test_the_proof_refuses_to_run_without_the_shared_resolver(tmp_path):
    """On a revision that predates the library the proof must say it cannot
    run — not fall back to a local copy of the resolution logic."""
    app, data = _app(tmp_path)
    (app / "deploy" / "backup" / "backup_root_lib.sh").unlink()

    result = _run_proof(app, data, tmp_path / "primary", tmp_path / "fallback")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "backup root library missing on the deployed revision" in out, out


def test_a_root_installed_script_gets_the_libraries_it_sources():
    """The nightly does not run the checkout copy.

    `riskit-state-backup.service` points at a root-owned copy under
    /usr/local/lib/riskit, so a script that starts SOURCING a sibling needs
    that sibling installed beside it or the nightly resolves no backup root at
    all and exits 1.

    Stated as the general rule rather than the one instance, because the
    next sourced helper will hit exactly this.

    FOLLOWS THE INVARIANT TO ITS OWNER. The two installs used to sit in
    `apply_hardening.sh::apply_privileged_scripts`; they now live in
    `deploy/backup/install_state_backup.sh`, which that script sources, so the
    deploy account can install the backup line without the root shell its
    sudoers does not grant. The rule did not change, only where it is written.
    `tests/deploy/test_state_backup_installer.py` pins the same ordering
    BEHAVIOURALLY — by running the shipped installer and reading back the
    command log — which is the stronger proof; this stays as the textual guard
    so a future edit that reorders the calls is caught at the source too.
    """
    installer = (REPO / "deploy" / "backup" / "install_state_backup.sh").read_text(encoding="utf-8")
    start = installer.index("state_backup_install_scripts() {")
    body = installer[start : installer.index("\n}\n", start)]

    order = [
        line.split('"')[1].rsplit("/", 1)[-1]
        for line in body.splitlines()
        if "_sb_install_file " in line or "backup/" in line
    ]
    order = [n for n in order if n.endswith(".sh")]
    installed = set(order)
    assert "riskit-state-backup.sh" in installed, installed

    # ORDER MATTERS. The writer treats a missing library as fatal, and the
    # backup timer fires at 02:30 UTC — installing the writer first leaves a
    # window in which a nightly takes no backup at all.
    assert order.index("backup_root_lib.sh") < order.index("riskit-state-backup.sh"), (
        "the sourced library must be installed BEFORE the script that hard-fails "
        f"without it; got {order}"
    )

    # Anything a root-installed script resolves relative to ITSELF has to
    # travel with it.
    # Match on the SOURCED FILE, not on how its directory is spelled. Keying
    # the rule to `$(dirname "${BASH_SOURCE[0]}")/x` matched exactly one
    # idiom, and the repo's dominant form — `SCRIPT_DIR="$(cd "$(dirname
    # "${BASH_SOURCE[0]}")" && pwd)"`, used by ten scripts under deploy/ —
    # slips straight past it, re-opening the lost-nightly window with a
    # green suite. Any sibling .sh a root-installed script sources must
    # travel with it, however the path is written.
    sourced = re.compile(r"^\s*(?:source|\.)\s+.*?([\w.-]+\.sh)", re.MULTILINE)
    for name in sorted(installed):
        src = next(REPO.glob(f"deploy/**/{name}"), None)
        assert src is not None, f"apply_hardening.sh installs {name}, which is not in deploy/"
        body = src.read_text(encoding="utf-8")
        for needed in sorted(set(sourced.findall(body))):
            if needed == name:
                continue
            assert needed in installed, (
                f"{name} sources {needed}, but apply_hardening.sh does not install "
                f"{needed} into the root-owned dir — the nightly would run without it"
            )


def test_neither_script_resolves_the_backup_root_itself():
    """The fallback root may be named in exactly one place.

    This is the structural half of the repair: re-adding a local
    `BACKUP_FALLBACK_ROOT` default to either script would restore the two
    independent implementations that caused run 31872681688 to fail.
    """

    def executable_lines(path: Path) -> str:
        # Comment lines are excluded: the header prose quotes both paths
        # when explaining the defect, and prose is not an implementation.
        return "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

    lib = executable_lines(LIB)
    assert lib.count("/home/dynasty/backups/riskit-state") == 1
    assert lib.count("/var/backups/riskit-state") == 1

    for script in (
        REPO / "deploy" / "backup" / "riskit-state-backup.sh",
        PROOF,
    ):
        code = executable_lines(script)
        assert "/home/dynasty/backups/riskit-state" not in code, script
        assert "/var/backups/riskit-state" not in code, script
        assert "backup_root_lib.sh" in code, f"{script} must source the shared resolver"


# ── the fifth review: a pointer is a hint, not a redirect ────────────


def test_a_pointer_may_not_redirect_out_of_its_own_root(tmp_path):
    """THE critical one. Reproduced with an attacker-planted table.

    `backup_root_read_generation` validated only `schema=1` and `-d`. It never
    required the named path to lie under the root that supplied the pointer,
    nor to have the dated shape the selection algorithm compares on — and in
    this collation EVERY non-digit basename sorts ABOVE every date, so an
    out-of-root pointer named anything else beat the root's own newest
    unconditionally and silently disarmed the on-disk scan.

    Measured before the fix: the prover logged `effective backup root: …/primary`
    while proving `…/elsewhere/restore-scratch`, gunzipped its contents, and
    exited 0. The real generation in the root it named was never opened.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    real = primary / "daily" / TODAY

    # A generation-shaped directory outside any candidate root.
    decoy = tmp_path / "elsewhere" / "restore-scratch"
    decoy.mkdir(parents=True)
    shutil.copytree(real / "sqlite", decoy / "sqlite")
    _write_pointer(primary, decoy, "2026-08-15T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {real}" in out, out
    assert str(decoy) not in out, "a pointer must not redirect out of its own root"
    assert "via on-disk scan" in out, "the scan must take over when the pointer is rejected"


def test_the_selected_generation_must_lie_under_the_root_that_supplied_it(tmp_path):
    """Belt-and-braces: `effective backup root: X` may never be printed for a
    generation that is not under X, whatever produced the selection."""
    body = PROOF.read_text(encoding="utf-8")
    assert "is not under the root that supplied it" in body
    assert '"${GEN}" != "${EFFECTIVE_ROOT%/}/daily/"*' in body


def test_a_generation_beyond_the_clock_skew_bound_fails_closed(tmp_path):
    """`riskit-state-backup.timer` is `Persistent=true`, so a missed nightly
    replays at boot — before NTP has stepped the clock — and promotes a complete
    generation dated years ahead.

    Skipping it is not enough, and that is the whole point. A wrong clock does
    not corrupt one directory: this system decides recency BY NAME, so a wrong
    clock means no ordering in that root can be trusted. The directory also sits
    inside prune's keep window forever — never deletable, and costing a
    retention slot per skewed run. Refusing is what puts it in front of the only
    person who can clear it.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    real = primary / "daily" / TODAY
    skewed = primary / "daily" / "2099-03-04"
    shutil.copytree(real, skewed)
    (primary / "last_generation").unlink()

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "beyond the clock-skew bound" in out, out
    assert (
        f"proving generation: {real}" not in out
    ), "name-ordered recency is untrustworthy in this root; it must refuse, not pick"


def test_a_generation_dated_tomorrow_is_skew_not_corruption(tmp_path):
    """Fail-closed must not become fail-always.

    A writer whose clock runs slightly ahead, or a proof crossing midnight UTC,
    legitimately produces a generation dated tomorrow. Rejecting that would turn
    an ordinary boundary into an outage, so the bound is a tolerance rather than
    a strict `> today`.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    real = primary / "daily" / TODAY
    tomorrow = (_TODAY_DT + timedelta(days=1)).strftime("%Y-%m-%d")
    ahead = primary / "daily" / tomorrow
    shutil.copytree(real, ahead)
    (primary / "last_generation").unlink()

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {ahead}" in out, out
    assert "beyond the clock-skew bound" not in out, out


def test_an_implausible_generation_does_not_consume_a_retention_slot(tmp_path):
    """`sort` puts a 2099 directory at the END of an ascending list, so
    `head -n -N` keeps it forever AND spends one of the N slots on it — real
    retention drops to N-1, and again with every further skewed run.

    It is excluded from the keep window and deliberately NOT deleted: an
    implausible generation is an anomaly for an operator, and this script's
    destructive steps only remove what it can account for.
    """
    body = (REPO / "deploy" / "backup" / "riskit-state-backup.sh").read_text(encoding="utf-8")
    assert "prune_candidates()" in body
    assert "done < <(prune_candidates)" in body
    assert (
        'ls -1 "${BACKUP_ROOT}/daily" 2>/dev/null | sort | head -n -' not in body
    ), "the raw keep-window is the defect"
    assert "excluded from the keep window and NOT deleted" in body


def test_a_relative_backup_root_is_refused(tmp_path):
    """A root is a LOCATION, and only an absolute path is one.

    A relative root resolves against each PROCESS's own cwd, so the writer
    promotes under its cwd while the prover calls the same root "does not
    exist" — two answers to one location question, the exact class this
    library exists to eliminate. Refused, never normalised against $PWD.
    """
    app, data = _app(tmp_path)
    result = _run_proof(app, data, Path("relative/primary"), tmp_path / "fallback")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "absolute path" in out, out


def test_an_empty_certified_generation_is_not_a_proof(tmp_path):
    """ "No artifact failed" is true of a run that read nothing.

    The writer discards any snapshot with zero artifacts and never promotes
    it, so a certified directory holding none is not a generation — and
    announcing a proof over one is indistinguishable from a real pass.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    # No retention source present, so nothing can fail for the ordinary
    # "exists on source, missing from backup" reason — the floor is the only
    # thing that can refuse here.
    (data / "retention" / "evidence.sqlite").unlink()

    empty = primary / "daily" / TODAY
    empty.mkdir(parents=True)
    _write_pointer(primary, empty, f"{TODAY}T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 2, out
    assert "holds NO artifact at all" in out, out
    assert "proven for every artifact" not in out, out


def test_a_successful_proof_reports_what_it_actually_verified(tmp_path):
    """Silence must not read as proof: the verdict prints its counts."""
    app, data = _app(tmp_path)
    result = _run_proof(app, data, tmp_path / "primary", tmp_path / "fallback")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert re.search(
        r"backup \+ restore proven: \d+ retention artifact\(s\) restored and verified", out
    ), out


def test_an_unresolvable_source_is_not_a_stream_that_never_started(tmp_path):
    """ROOT-SAFE. The same ENOENT/EACCES conflation, on the artifact side.

    A retention store on a volume that failed to mount is `! -f` exactly as a
    store that was never created is, so it was excused as "stream has not
    started", omitted from every generation, and the run exited 0. It cannot
    be caught by BACKUP_REQUIRED — the retention artifacts are excluded from
    it by design.
    """
    app, data = _app(tmp_path)
    (data / "retention" / "evidence.sqlite").unlink()
    (data / "retention" / "evidence.sqlite").symlink_to(tmp_path / "unmounted" / "evidence.sqlite")

    result = _run_proof(app, data, tmp_path / "primary", tmp_path / "fallback")
    out = result.stdout + result.stderr

    assert result.returncode == 2, out
    assert "cannot be resolved" in out, out
    # Other streams legitimately report "not started"; the unresolvable one
    # must not be among them.
    for line in out.splitlines():
        if "evidence.sqlite" in line:
            assert "stream has not started" not in line, line


def test_the_writer_only_deletes_a_mirror_it_is_a_replica_of(tmp_path):
    """One fallback night must not destroy the entire remote history.

    `--delete` makes the remote an exact replica of ONE root's `daily/`. On a
    fallback night this root holds only what that run just wrote, while the
    mirrored generations live in the root it could not write to — which is
    precisely the failure that makes the off-box copy the only surviving one.
    """
    body = (REPO / "deploy" / "backup" / "riskit-state-backup.sh").read_text(encoding="utf-8")
    assert "RSYNC_ARGS=(-a)" in body
    assert "RSYNC_ARGS+=(--delete)" in body
    assert "rsync -a --delete" not in body, "unconditional --delete is the defect"
    # Root identity is NECESSARY but not SUFFICIENT — that was the blocker.
    # Continuity is the gate; these name the conditions that must hold.
    assert "MIRROR_DELETE_REFUSED" in body
    assert "local-history continuity cannot be established" in body
    assert "local history SHRANK since the last mirror" in body
    assert "the destination changed" in body


def test_the_orphan_pointer_temp_sweep_reaches_a_symlinked_root(tmp_path):
    """F9's sweep did nothing when the root is a symlink — `find` will not
    descend one without a trailing slash, which is the exact configuration the
    prover's `! -L` guards exist to handle."""
    body = (REPO / "deploy" / "backup" / "riskit-state-backup.sh").read_text(encoding="utf-8")
    assert """find "${BACKUP_ROOT}/" -maxdepth 1 -name 'last_generation.tmp.*'""" in body


def test_the_pointer_temp_name_is_not_derivable(tmp_path):
    """`>` follows a symlink, and `${out}.tmp.$$` is derivable from a
    world-readable result path."""
    lib = LIB.read_text(encoding="utf-8")
    assert 'mktemp "${out}.tmp.XXXXXX"' in lib
    # Assert on the CODE, not on prose that quotes the old form.
    assert 'tmp="${out}.tmp.$$"' not in lib, "the derivable name is the defect"


def test_a_dated_pointer_outside_its_root_is_rejected(tmp_path):
    """Containment, isolated from the shape check.

    The two guards mask each other: a decoy that is both out-of-root AND
    non-dated is rejected by either one alone, so a single test cannot tell
    which is doing the work. This decoy is correctly DATED and merely lives
    somewhere else — only containment rejects it.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    real = primary / "daily" / TODAY

    decoy = tmp_path / "elsewhere" / "daily" / TODAY
    decoy.mkdir(parents=True)
    shutil.copytree(real / "sqlite", decoy / "sqlite")
    _write_pointer(primary, decoy, f"{TODAY}T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert f"[backup-proof] proving generation: {real}" in out, out
    assert str(decoy) not in out, out


def test_a_non_dated_pointer_inside_its_root_is_rejected(tmp_path):
    """The dated-shape check, isolated from BOTH other guards.

    Getting this one to fail the right way took two attempts, and the reason
    is worth recording. A non-dated name that sorts ABOVE dates is already
    rejected by the future-date guard, so removing the shape check changes
    nothing — the guards mask each other by coincidence, not by design. The
    case that needs the shape check specifically is a name that sorts BELOW
    dates in a root holding no dated generation at all: nothing else can rule
    it out, and without the check the prover certifies a scratch directory.
    """
    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    real = primary / "daily" / TODAY

    # "!scratch" sorts below every date, so ordering cannot save us here.
    decoy = primary / "daily" / "!scratch"
    shutil.copytree(real, decoy)
    shutil.rmtree(real)
    _write_pointer(primary, decoy, f"{TODAY}T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "holds no generation" in out, out
    assert f"proving generation: {decoy}" not in out, out


# ── protections review #6 found inadequately pinned ──────────────────


def test_the_mirror_delete_gating_is_behavioural_not_textual(tmp_path):
    """A grep for `--delete` proves nothing about WHEN it is passed.

    The earlier structural test would pass a script that built `RSYNC_ARGS=(-a)`
    and then appended `--delete` unconditionally. This stubs rsync and reads the
    arguments the writer actually chose on a fallback night.
    """
    app, data = _app(tmp_path)
    stub = tmp_path / "bin"
    stub.mkdir()
    argv = tmp_path / "rsync-argv"
    (stub / "rsync").write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" >> {argv}\nexit 0\n', encoding="utf-8"
    )
    (stub / "rsync").chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(_blocked(tmp_path, "primary")),  # forces the fallback
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        OFFBOX_RSYNC_DEST=str(tmp_path / "mirror") + "/",
        PATH=f"{stub}:{os.environ['PATH']}",
    )
    (tmp_path / "mirror").mkdir()
    result = subprocess.run(
        ["bash", str(REPO / "deploy" / "backup" / "riskit-state-backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    args = argv.read_text(encoding="utf-8").split("\n")
    assert "--delete" not in args, (
        "a fallback night must publish additively — the mirrored generations live "
        f"in the root this run could not write to. args={args}"
    )
    assert "WITHOUT --delete" in out, out


def test_the_first_mirror_from_a_root_publishes_additively(tmp_path):
    """There is no continuity evidence yet on a first mirror, so the safe
    direction is additive. Reconciliation is proven on the second run by
    test_a_continuous_root_still_reconciles_the_mirror."""
    app, data = _app(tmp_path)
    stub = tmp_path / "bin"
    stub.mkdir()
    argv = tmp_path / "rsync-argv"
    (stub / "rsync").write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" >> {argv}\nexit 0\n', encoding="utf-8"
    )
    (stub / "rsync").chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(tmp_path / "primary"),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fallback"),
        PYTHON_BIN=sys.executable,
        OFFBOX_RSYNC_DEST=str(tmp_path / "mirror") + "/",
        PATH=f"{stub}:{os.environ['PATH']}",
    )
    (tmp_path / "mirror").mkdir()
    result = subprocess.run(
        ["bash", str(REPO / "deploy" / "backup" / "riskit-state-backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "--delete" not in argv.read_text(encoding="utf-8").split("\n"), out
    assert "no record of a previous mirror" in out, out


def test_a_source_directory_that_cannot_be_enumerated_is_a_failure(tmp_path):
    """`prove_dir`'s find was unguarded: under `set -e` a partially unreadable
    source killed the sweep with no diagnostic. A `|| true` would be worse —
    it undercounts, and an undercount lets an empty restore pass the
    zero-check. So an unenumerable source is a FAIL."""
    body = PROOF.read_text(encoding="utf-8")
    assert "could not be enumerated — coverage cannot be established" in body
    assert 'src_entries="$(find "${src}" -type f 2>/dev/null | wc -l | tr -d \' \')"' in body
    assert 'src_entries="$(find "${src}" -type f | wc -l | tr -d \' \')"' not in body


@pytest.mark.skipif(os.geteuid() == 0, reason="root's rm always succeeds, so the trap cannot fail")
def test_a_failing_cleanup_does_not_rewrite_the_verdict(tmp_path):
    """F15, finally pinned — and pinned deterministically.

    Under `set -Eeuo pipefail` a failing `rm -rf` inside an EXIT trap aborts the
    trap: the pending exit status becomes 1 and every later step is skipped.
    That reports a real artifact failure (exit 2) as infrastructure breakage and
    leaks the result file.

    An end-to-end version of this is a race — the proof finishes before you can
    make the directory undeletable — so this extracts the SHIPPED `cleanup`
    text and runs it with a restore dir that provably cannot be removed.
    """
    body = PROOF.read_text(encoding="utf-8")
    start = body.index("cleanup() {")
    end = body.index("\n}\n", start) + len("\n}\n")
    func = body[start:end]

    jail = tmp_path / "jail"
    (jail / "restore").mkdir(parents=True)
    (jail / "restore" / "held").write_text("x", encoding="utf-8")
    result_file = tmp_path / "result"
    result_file.write_text("schema=1\n", encoding="utf-8")
    jail.chmod(0o500)  # entries inside cannot be unlinked
    try:
        harness = (
            "set -Eeuo pipefail\n"
            f'RESTORE_DIR="{jail / "restore"}"\n'
            f'RESULT_FILE="{result_file}"\n' + func + "trap cleanup EXIT\nexit 2\n"
        )
        proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)
    finally:
        jail.chmod(0o755)

    assert proc.returncode == 2, (
        "a failing cleanup must not rewrite the pending exit status "
        f"(got {proc.returncode}){proc.stdout}{proc.stderr}"
    )
    assert not result_file.exists(), "a failing first step must not skip the second"


def test_the_comparison_stamp_falls_back_to_the_directory_date(tmp_path):
    """F7's derived-midnight fallback, isolated.

    Without it a pointerless generation compares on an EMPTY stamp, and an empty
    incumbent is a blank slate any later candidate overwrites — which is how a
    2020 generation beat a same-day one.
    """
    lib = LIB.read_text(encoding="utf-8")
    assert (
        'at="${base}T00:00:00Z"' in lib
    ), "the derived-midnight fallback is what makes the stamp non-empty"

    app, data = _app(tmp_path)
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"

    first = _run_proof(app, data, primary, fallback)
    assert first.returncode == 0, first.stdout + first.stderr
    (primary / "last_generation").unlink()  # pointerless: stamp must be derived

    older = fallback / "daily" / "2020-01-01"
    older.mkdir(parents=True)
    _write_pointer(fallback, older, "2020-01-01T02:30:00Z")

    result = _run_proof(app, data, primary, fallback, run_backup="0")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert (
        f"promoted_at {TODAY}T00:00:00Z" in out
    ), "the derived stamp must be visible and non-empty"
    assert f"[backup-proof] proving generation: {primary}/daily/{TODAY}" in out, out


# ── off-box destructive reconciliation requires proof of continuity ──


def _rsync_stub(tmp_path: Path) -> Path:
    """A stub implementing the real `--delete` semantic, so the test measures
    behaviour rather than the presence of a flag."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "rsync").write_text(
        "#!/bin/bash\n"
        'args=("$@"); del=0\n'
        'for a in "${args[@]}"; do [[ "$a" == "--delete" ]] && del=1; done\n'
        'src="${args[-2]}"; dst="${args[-1]}"\n'
        'cp -a "${src}." "${dst}" 2>/dev/null\n'
        "if (( del )); then\n"
        '  for e in "${dst}"*/; do n="$(basename "$e")"; [[ -e "${src}${n}" ]] || rm -rf "$e"; done\n'
        "fi\nexit 0\n",
        encoding="utf-8",
    )
    (stub / "rsync").chmod(0o755)
    return stub


def _run_writer(app: Path, data: Path, root: Path, tmp_path: Path, dest: Path):
    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(root),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fb"),
        PYTHON_BIN=sys.executable,
        OFFBOX_RSYNC_DEST=str(dest) + "/",
        PATH=f"{_rsync_stub(tmp_path)}:{os.environ['PATH']}",
    )
    return subprocess.run(
        ["bash", str(REPO / "deploy" / "backup" / "riskit-state-backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_local_history_loss_must_not_delete_the_only_surviving_remote_copies(tmp_path):
    """THE release blocker. Reproduced 5 -> 1 before the fix.

    `BACKUP_ROOT == REQUESTED_ROOT` answers which root we wrote to, not whether
    that root still holds the history the mirror was built from. A writable
    primary whose local generations vanished — disk replaced, /var wiped,
    restored image, fresh host — passed that gate while being exactly the state
    in which the off-box copy is the last one standing.
    """
    app, data = _app(tmp_path)
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    for g in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"):
        (mirror / g / "sqlite").mkdir(parents=True)

    root = tmp_path / "primary"  # writable, but its local history is gone
    (root / "daily").mkdir(parents=True)
    result = _run_writer(app, data, root, tmp_path, mirror)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    survivors = sorted(p.name for p in mirror.iterdir() if p.is_dir())
    assert len(survivors) == 6, f"remote history was destroyed: {survivors}\n{out}"
    assert "WITHOUT --delete" in out and "local-history continuity" in out, out


def test_a_continuous_root_still_reconciles_the_mirror(tmp_path):
    """Fail-closed must not become fail-never: without reconciliation the
    remote grows without bound, which is its own failure."""
    app, data = _app(tmp_path)
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    root = tmp_path / "primary"

    first = _run_writer(app, data, root, tmp_path, mirror)
    assert first.returncode == 0, first.stdout + first.stderr
    # A stale remote generation with no local counterpart.
    (mirror / "2000-01-01" / "sqlite").mkdir(parents=True)

    second = _run_writer(app, data, root, tmp_path, mirror)
    out = second.stdout + second.stderr
    assert second.returncode == 0, out
    assert not (
        mirror / "2000-01-01"
    ).exists(), f"a continuous root must still reconcile, or remote retention grows forever\n{out}"


def test_a_changed_destination_is_not_reconciled(tmp_path):
    """Continuity is proven against a DESTINATION, not in the abstract — a
    remote we have never mirrored to may hold someone else's only copies."""
    app, data = _app(tmp_path)
    root = tmp_path / "primary"
    first_dest = tmp_path / "mirror-a"
    first_dest.mkdir()
    assert _run_writer(app, data, root, tmp_path, first_dest).returncode == 0

    other = tmp_path / "mirror-b"
    other.mkdir()
    for g in ("2026-07-01", "2026-07-02"):
        (other / g / "sqlite").mkdir(parents=True)
    result = _run_writer(app, data, root, tmp_path, other)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert (other / "2026-07-01").exists() and (other / "2026-07-02").exists(), out
    assert "destination changed" in out, out


def test_only_recognised_generations_count_toward_continuity(tmp_path):
    """The continuity count must mean GENERATIONS.

    If a stray entry inflates it, the count can hold steady while real
    generations vanish — which would let `--delete` run in exactly the state
    the gate exists to catch. Positive recognition: a directory, not a symlink,
    the writer's dated shape, and a real calendar date.
    """
    body = (REPO / "deploy" / "backup" / "riskit-state-backup.sh").read_text(encoding="utf-8")
    assert "plausible_generations()" in body
    assert "MIRROR_COUNT=\"$(plausible_generations | wc -l | tr -d ' ')\"" in body
    for guard in (
        '[[ -d "${BACKUP_ROOT}/daily/${dir}" ]] || continue',
        '[[ ! -L "${BACKUP_ROOT}/daily/${dir}" ]] || continue',
        '[[ "${dir}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue',
        '[[ "$(date -u -d "${dir}" +%Y-%m-%d 2>/dev/null)" == "${dir}" ]] || continue',
    ):
        assert guard in body, f"missing positive-recognition guard: {guard}"


def test_an_interleaved_non_generation_entry_costs_no_real_generation(tmp_path):
    """The harmful variant, which two earlier attempts at this test missed.

    A stray entry sorting ABOVE every date is skipped by the clock-skew guard;
    one sorting BELOW every date is pruned first and costs nothing. Both are
    harmless, and both are what I originally tested. The damaging case is an
    entry that sorts INSIDE the date range — a dated restore-scratch directory
    is the likeliest real example — because it consumes a slot in the keep
    window and one REAL generation is deleted to make room, every night it
    exists.

    Measured on the shipped writer with KEEP_DAILY=14: 14 real generations
    became 13 with the entry present, and stayed 14 once entries are recognised
    positively rather than merely not-looking-wrong.

    The 14 seeded Aug 1-14 generations are historical fixture dates; the
    writer run under test ADDS one more, for ``TODAY`` (this module's single
    clock read -- ``DATE_STAMP=TODAY`` pins the script to it, same as
    ``_run_proof``, so this test cannot straddle a midnight race between its
    own date and the script's). Production policy retains the newest 14
    legitimate dated generations, so the correct post-run state is 15
    candidates pruned to 14: the oldest seeded date (2026-08-01) drops, the
    other 13 seeded dates plus the newly written ``TODAY`` survive.
    """
    app, data = _app(tmp_path)
    root = tmp_path / "primary"
    (root / "daily").mkdir(parents=True)
    for i in range(1, 15):
        (root / "daily" / f"2026-08-{i:02d}" / "sqlite").mkdir(parents=True)
    scratch = root / "daily" / "2026-08-07-restore-scratch"
    scratch.mkdir()

    env = {k: v for k, v in os.environ.items() if k not in {"BACKUP_ROOT", "BACKUP_FALLBACK_ROOT"}}
    env.update(
        APP_DIR=str(app),
        DATA_DIR=str(data),
        BACKUP_ROOT=str(root),
        BACKUP_FALLBACK_ROOT=str(tmp_path / "fb"),
        PYTHON_BIN=sys.executable,
        KEEP_DAILY="14",
        DATE_STAMP=TODAY,
    )
    result = subprocess.run(
        ["bash", str(REPO / "deploy" / "backup" / "riskit-state-backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out

    survivors = sorted(
        p.name
        for p in (root / "daily").iterdir()
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
    )
    seeded = [f"2026-08-{i:02d}" for i in range(1, 15)]
    expected = sorted(seeded[1:] + [TODAY])  # 2026-08-01 dropped; TODAY newly written
    assert (
        survivors == expected
    ), f"a stray entry cost a real generation, or the wrong one was pruned: {survivors}\n{out}"
    assert "2026-08-01" not in survivors, "the oldest legitimate generation must be the one pruned"
    assert len(survivors) == 14, f"expected 14 legitimate generations, got {survivors}\n{out}"
    assert scratch.exists(), "an unrecognised entry must be excluded, not deleted"


def test_every_date_in_this_module_comes_from_one_clock():
    """A second clock read in this file is a midnight race, not a style nit.

    Every date here has to name the same generation the script under test
    creates.  ``DATE_STAMP`` pins the script to ``TODAY``; what pins the
    tests to it is that nothing else reads the clock.  Read it twice and a
    run that crosses 00:00 UTC between the two reads gets two different
    days — which is how ``test_selection_compares_the_date_before_the_instant``
    built its "older" generation directly on top of the newer one and failed
    a green pull request.

    The failure is invisible for 23 hours 51 minutes of every day, so no
    amount of re-running finds it.  A source-text guard does.
    """
    # Assembled, not written literally: a guard whose own matcher matches
    # itself reports a defect that is only the guard looking in a mirror.
    needle = "datetime." + "now("
    src = Path(__file__).read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    reads = [ln.strip() for ln in code.splitlines() if needle in ln]
    assert reads == ["_TODAY_DT = " + needle + "timezone.utc)"], (
        "this module must read the clock exactly once, at _TODAY_DT; derive every "
        f"other date from it with timedelta.  Found: {reads}"
    )
    # And the pin to the script must still be in place — one clock is only
    # useful if it is also the script's.
    assert "DATE_STAMP=TODAY" in code, (
        "the generation-name pin to riskit-state-backup.sh is gone; the script "
        "would name generations from its own clock again"
    )
