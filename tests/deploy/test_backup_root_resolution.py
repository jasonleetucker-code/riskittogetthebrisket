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

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
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
    assert str(decoy) not in out, "the proof re-derived the location instead of reading the result"


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
    /usr/local/lib/riskit that `apply_hardening.sh` installs, so a script
    that starts SOURCING a sibling needs that sibling installed beside it
    or the nightly resolves no backup root at all and exits 1.

    Stated as the general rule rather than the one instance, because the
    next sourced helper will hit exactly this.
    """
    hardening = (REPO / "deploy" / "apply_hardening.sh").read_text(encoding="utf-8")
    start = hardening.index("apply_privileged_scripts() {")
    body = hardening[start : hardening.index("\n}\n", start)]

    order = [
        line.split('"')[1].rsplit("/", 1)[-1]
        for line in body.splitlines()
        if "install_priv_script " in line and not line.lstrip().startswith("#")
    ]
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
