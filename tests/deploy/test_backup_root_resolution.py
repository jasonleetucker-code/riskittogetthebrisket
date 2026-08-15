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
from datetime import datetime, timezone
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
    assert f"effective backup root: {fallback}" in out, out
    assert f"proving generation: {fallback}/daily/{TODAY}" in out, out
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
    assert f"effective backup root: {primary}" in out, out
    assert f"proving generation: {primary}/daily/{TODAY}" in out, out
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
    assert "no recorded backup generation in any candidate root" in out, out


def test_no_recorded_generation_anywhere_is_a_failure(tmp_path):
    app, data = _app(tmp_path)

    result = _run_proof(app, data, tmp_path / "primary", tmp_path / "fallback", run_backup="0")
    out = result.stdout + result.stderr

    assert result.returncode == 1, out
    assert "no recorded backup generation in any candidate root" in out, out


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
    assert f"proving generation: {primary}/daily/{TODAY}" in out, out
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
    assert f"effective backup root: {fallback}" in out, out
    assert f"proving generation: {newer}" in out, out


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

    installed = {
        line.split('"')[1].rsplit("/", 1)[-1]
        for line in body.splitlines()
        if "install_priv_script " in line and not line.lstrip().startswith("#")
    }
    assert "riskit-state-backup.sh" in installed, installed

    # Anything a root-installed script resolves relative to ITSELF has to
    # travel with it.
    sibling = re.compile(r'\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/([\w.-]+)')
    for name in sorted(installed):
        src = next(REPO.glob(f"deploy/**/{name}"), None)
        assert src is not None, f"apply_hardening.sh installs {name}, which is not in deploy/"
        for needed in sorted(set(sibling.findall(src.read_text(encoding="utf-8")))):
            assert needed in installed, (
                f"{name} resolves {needed} beside itself, but apply_hardening.sh "
                f"does not install {needed} into the root-owned dir — the nightly "
                f"would run without it"
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
