"""Run `deploy/playerctx_history_push.sh` for real, against a bare repo.

Until this file, the script had **never executed** — not in CI, not
locally, not on the box.  `test_playerctx_history_timer_is_wired.py`
greps its source text, which proves the wiring and nothing about the
behaviour.  Its first real run was scheduled against production `main`,
where a bug costs a week and is discovered by absence: no snapshot
appears, and nobody can tell "the timer never fired" from "the timer
fired and did nothing".

Everything here drives the script through the env overrides it already
exposes, with a local bare repo standing in for GitHub.  No network, no
ssh: `GIT_SSH_COMMAND` is set by the script but git never consults it
for a filesystem remote.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "playerctx_history_push.sh"

pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "git"], capture_output=True).returncode != 0,
    reason="git not available",
)


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return proc.stdout


def _make_origin(tmp_path: Path) -> Path:
    """A bare repo with one commit on `main`, standing in for GitHub."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-q", "-b", "main", cwd=seed)
    _git("config", "user.email", "t@t.local", cwd=seed)
    _git("config", "user.name", "t", cwd=seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    # data/ gitignored repo-wide, exactly as in the real repo — this is
    # what makes the script's `git add -f` load-bearing rather than
    # incidental.
    (seed / ".gitignore").write_text("data/\n", encoding="utf-8")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "seed", cwd=seed)

    origin = tmp_path / "origin.git"
    _git("clone", "-q", "--bare", str(seed), str(origin), cwd=tmp_path)
    return origin


def _make_live_dir(tmp_path: Path, dates: list[str]) -> Path:
    """A fake live deploy dir holding dated snapshots plus a decoy."""
    live = tmp_path / "live"
    hist = live / "data" / "playerctx" / "history"
    hist.mkdir(parents=True)
    for d in dates:
        (hist / f"snapshot_{d}.json").write_text(
            json.dumps({"asOf": d, "players": {}}), encoding="utf-8"
        )
    # The 38 MB depth-chart CSV and 14 MB Sleeper dump live one directory
    # up in production.  A directory-level add would sweep them in; the
    # script names each file instead, and this decoy is what proves it.
    (live / "data" / "playerctx" / "depth_charts_2026.csv").write_text("x" * 4096, encoding="utf-8")
    (hist / "notes.txt").write_text("not a snapshot", encoding="utf-8")
    return live


def _run(
    tmp_path: Path, live: Path, origin: Path, *, key: Path | None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "PLAYERCTX_HISTORY_WORK_DIR": str(tmp_path / "work"),
            "PLAYERCTX_HISTORY_REPO_URL": str(origin),
            "PLAYERCTX_HISTORY_APP_DIR": str(live),
            "PLAYERCTX_HISTORY_SSH_KEY": str(key) if key else str(tmp_path / "absent-key"),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    return subprocess.run(
        ["bash", str(_SCRIPT)], env=env, capture_output=True, text=True, timeout=120
    )


def _committed_files(origin: Path) -> list[str]:
    return [
        ln.strip()
        for ln in _git("ls-tree", "-r", "--name-only", "main", cwd=origin).splitlines()
        if ln.strip()
    ]


def test_a_snapshot_actually_lands_as_a_commit(tmp_path):
    """The whole point, executed rather than asserted about."""
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11"])
    key = tmp_path / "key"
    key.write_text("not-a-real-key", encoding="utf-8")

    proc = _run(tmp_path, live, origin, key=key)
    assert proc.returncode == 0, proc.stderr

    files = _committed_files(origin)
    assert "data/playerctx/history/snapshot_2026-08-11.json" in files, files
    log = _git("log", "--format=%s", "main", cwd=origin)
    assert "chore(playerctx): retain snapshot" in log


def test_every_pending_snapshot_is_taken_not_just_the_newest(tmp_path):
    """This is what makes exit-0-on-a-missing-key safe.

    If the push took one file per run, every week spent without a deploy
    key would be a week permanently unretained — and an unretained day
    cannot be recovered afterwards.  The wiring test asserts the glob's
    SHAPE; this asserts the consequence.
    """
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11", "2026-08-18", "2026-08-25"])
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")

    proc = _run(tmp_path, live, origin, key=key)
    assert proc.returncode == 0, proc.stderr

    files = _committed_files(origin)
    for d in ("2026-08-11", "2026-08-18", "2026-08-25"):
        assert f"data/playerctx/history/snapshot_{d}.json" in files, (d, files)


def test_nothing_outside_the_history_directory_is_ever_staged(tmp_path):
    """`git add -f` with an explicit path list, never a directory.

    A `git add -A` is what put an earlier PR into merge conflict by
    committing two scrape-state timestamps nobody intended, and the
    directory next door holds a 38 MB CSV.  Neither the decoy nor the
    non-snapshot file may appear.
    """
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11"])
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")

    assert _run(tmp_path, live, origin, key=key).returncode == 0

    files = _committed_files(origin)
    assert not any("depth_charts" in f for f in files), files
    assert not any(f.endswith("notes.txt") for f in files), files
    assert [f for f in files if "playerctx/history" in f] == [
        "data/playerctx/history/snapshot_2026-08-11.json"
    ]


def test_a_missing_key_no_longer_aborts_the_push(tmp_path):
    """The absence of the nominal -i target is NOT proof that git cannot
    authenticate, and treating it as proof cost C1-RET-08 every snapshot it
    ever produced.

    Measured on production 2026-08-15 (preflight run 31912677700): all three
    pushers run as the same user with the same HOME, ``github_deploy_key`` is
    absent for all three, and DLF and IDP Show push anyway because
    ``~/.ssh/config`` supplies ``IdentityFile ~/.ssh/github_push``. ``-i``
    accumulates WITH that rather than replacing it, so the siblings' ``-i`` is
    a no-op. This script alone decided on ssh's behalf, before ssh ran, that a
    push was impossible — and exited 0, so the timer went green weekly while
    publishing nothing.

    The old test asserted that keyless meant "pushes nothing". That was the
    defect, written down as the contract.
    """
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11"])

    proc = _run(tmp_path, live, origin, key=None)
    assert proc.returncode == 0, proc.stderr
    # It says what it is doing rather than going quiet.
    assert "falling back to ssh" in proc.stdout + proc.stderr
    # And it PUBLISHES, which is the whole point.
    assert "data/playerctx/history/snapshot_2026-08-11.json" in _committed_files(origin)


def test_an_explicit_readable_key_is_still_used_explicitly(tmp_path):
    """Unchanged behaviour where a key IS configured: it is passed as -i with
    IdentitiesOnly, so naming a key still pins the identity."""
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11"])
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")

    proc = _run(tmp_path, live, origin, key=key)
    assert proc.returncode == 0, proc.stderr
    assert "falling back to ssh" not in proc.stdout + proc.stderr
    assert "data/playerctx/history/snapshot_2026-08-11.json" in _committed_files(origin)


def test_the_whole_backlog_publishes_on_one_keyless_run(tmp_path):
    """Every dated snapshot, not just the newest — the backlog claim now has to
    hold on the run itself rather than on a later run that has a key."""
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11", "2026-08-18"])

    assert _run(tmp_path, live, origin, key=None).returncode == 0

    files = _committed_files(origin)
    assert "data/playerctx/history/snapshot_2026-08-11.json" in files
    assert "data/playerctx/history/snapshot_2026-08-18.json" in files


def test_a_real_authentication_failure_is_still_a_failure(tmp_path):
    """Relaxing the pre-flight guard must NOT relax the outcome. An
    unreachable remote has to fail the run loudly — the failure this repair
    removes is the one that reported success while publishing nothing, not
    every failure.
    """
    origin = tmp_path / "does-not-exist.git"
    live = _make_live_dir(tmp_path, ["2026-08-11"])

    proc = _run(tmp_path, live, origin, key=None)
    assert proc.returncode != 0, (
        "an unreachable remote must fail the unit; got exit 0 with stdout:\n" + proc.stdout
    )
    # And it must not have claimed to publish.
    assert "pushed on attempt" not in proc.stdout


def test_no_snapshots_exits_clean(tmp_path):
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, [])
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")

    proc = _run(tmp_path, live, origin, key=key)
    assert proc.returncode == 0, proc.stderr
    assert "no dated snapshots" in proc.stdout + proc.stderr


def test_a_second_run_with_no_new_files_is_a_no_op(tmp_path):
    """Re-pushing an unchanged tree must not create an empty commit —
    the weekly timer runs whether or not the refresh produced anything."""
    origin = _make_origin(tmp_path)
    live = _make_live_dir(tmp_path, ["2026-08-11"])
    key = tmp_path / "key"
    key.write_text("k", encoding="utf-8")

    assert _run(tmp_path, live, origin, key=key).returncode == 0
    first = _git("rev-parse", "main", cwd=origin).strip()

    proc = _run(tmp_path, live, origin, key=key)
    assert proc.returncode == 0, proc.stderr
    assert "no changes after copy" in proc.stdout + proc.stderr
    assert _git("rev-parse", "main", cwd=origin).strip() == first
