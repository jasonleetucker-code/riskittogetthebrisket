"""Deploy/rollback blockers found reviewing the artifact release train (#1667).

* B1 — a legacy (pre-artifact) rollback target cannot pass validation if an
  ungated validate step runs a script that only exists in artifact-era trees.
* B3 — restoring a saved artifact on rollback must not run the target's .next
  on the failed forward deploy's ``node_modules``: a mismatched (or unknown)
  install is reinstalled before staging, while an install already matching the
  target's lock needs no npm at all (the registry-unavailable property pinned in
  ``test_rollback_frontend_atomicity.py`` stays intact).
* B4 — the archive the workflow transfers to ``<state>/incoming/`` must not
  accumulate on the production disk.

(B2, the same-revision artifact replacement, is pinned in
``test_save_release_archive.py``.)

The bash tests drive the SHIPPED function text from ``deploy/rollback.sh`` and
``deploy/deploy.sh`` against stub commands, never a copy of the logic.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO / "deploy" / "deploy.sh"
ROLLBACK_SH = REPO / "deploy" / "rollback.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"

ARTIFACT_CONDITION = "${{ needs.resolve.outputs.release_mode == 'artifact' }}"

# Repository entry points that arrived with the artifact release contract and
# therefore do not exist in any legacy (pre-artifact) rollback target.
ARTIFACT_ERA_ENTRY_POINTS = (
    "scripts/python_lock.py",
    "scripts.release_artifact",
    "scripts/build_backend_wheelhouse.sh",
    "scripts.generate_leagues_contract",
    "scripts/generate_leagues_contract.py",
)

requires_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _bash_path(path: Path) -> str:
    """A path bash can use in PATH and ``source`` on Linux and Git Bash alike."""
    text = path.resolve().as_posix()
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    return f"/{match[1].lower()}/{match[2]}" if match else text


# ── B1 ───────────────────────────────────────────────────────────────


def test_validate_never_runs_an_artifact_era_script_in_legacy_mode():
    """Every validate step invoking an artifact-era script is artifact-gated.

    The one exception is a step that branches on ``RELEASE_MODE`` itself (the
    dependency install), which must then mention the legacy branch.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    offenders = []
    for step in workflow["jobs"]["validate"]["steps"]:
        run = step.get("run") or ""
        if not any(entry in run for entry in ARTIFACT_ERA_ENTRY_POINTS):
            continue
        if step.get("if") == ARTIFACT_CONDITION:
            continue
        if '"${RELEASE_MODE}" == "legacy"' in run and "RELEASE_MODE" in (step.get("env") or {}):
            continue
        offenders.append(step.get("name"))
    assert offenders == [], (
        "these validate steps run a script that a legacy rollback target does not "
        f"contain, so every legacy rollback would fail validation: {offenders}"
    )


def test_leagues_contract_check_is_artifact_gated():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = {step.get("name"): step for step in workflow["jobs"]["validate"]["steps"]}
    step = steps["Check generated leagues contract"]
    assert step.get("if") == ARTIFACT_CONDITION


# ── B3 ───────────────────────────────────────────────────────────────

RUNTIME_ARTIFACTS = (
    "BUILD_ID",
    "build-manifest.json",
    "app-path-routes-manifest.json",
    "prerender-manifest.json",
    "routes-manifest.json",
    "required-server-files.json",
)


def _write_dist(dist: Path, marker: str) -> None:
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "static").mkdir(exist_ok=True)
    (dist / "static" / "app.js").write_text("//js\n")
    (dist / "MARKER").write_text(marker)
    for name in RUNTIME_ARTIFACTS:
        if name == "BUILD_ID":
            (dist / name).write_text("build-id\n")
        elif name == "build-manifest.json":
            (dist / name).write_text(json.dumps({"pages": {"/": ["static/app.js"]}}))
        else:
            (dist / name).write_text("{}")


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), newline="\n")
    path.chmod(0o755)


STAMP = ".calculator-package-lock.sha256"
TARGET_LOCK = json.dumps({"lockfileVersion": 3, "name": "rollback-target"})


def _artifact_rollback_fixture(tmp_path: Path, *, npm_exit: int = 0, stamp: str = "absent"):
    """``stamp``: absent | mismatch (the failed deploy's lock) | match (target's)."""
    app_dir = tmp_path / "app"
    frontend = app_dir / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"name": "fixture"}))
    (frontend / "package-lock.json").write_text(TARGET_LOCK, newline="\n")
    node_modules = frontend / "node_modules"
    node_modules.mkdir()
    if stamp == "match":
        (node_modules / STAMP).write_text(hashlib.sha256(TARGET_LOCK.encode()).hexdigest())
    elif stamp == "mismatch":
        (node_modules / STAMP).write_text(hashlib.sha256(b"failed deploy lock").hexdigest())
    _write_dist(frontend / ".next", "live-build-of-the-failed-deploy")
    state = tmp_path / "state"
    state.mkdir()
    archive = state / "saved.tar"
    archive.write_bytes(b"saved artifact")
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(
        bin_dir / "npm",
        f"""\
        echo "npm $*" >> {shlex.quote(_bash_path(log))}
        exit {npm_exit}
        """,
    )
    _write_stub(bin_dir / "node", 'echo "v20.0.0"\n')
    marker = "this-is-the-SAVED-artifact"
    manifest_lines = "\n".join(
        f"echo '{{}}' > \"$staging/{name}\""
        for name in RUNTIME_ARTIFACTS
        if name not in ("BUILD_ID", "build-manifest.json")
    )
    _write_stub(
        bin_dir / "python3",
        f"""\
        echo "python3 $*" >> {shlex.quote(_bash_path(log))}
        staging=""
        while [[ $# -gt 0 ]]; do
          if [[ "$1" == "--staging" ]]; then staging="$2"; fi
          shift
        done
        [[ -n "$staging" ]] || exit 0
        mkdir -p "$staging/static"
        echo '//js' > "$staging/static/app.js"
        echo '{marker}' > "$staging/MARKER"
        echo 'build-id' > "$staging/BUILD_ID"
        echo '{{"pages": {{"/": ["static/app.js"]}}}}' > "$staging/build-manifest.json"
        {manifest_lines}
        """,
    )
    return app_dir, state, archive, bin_dir, log, marker


def _run_artifact_rollback(app_dir: Path, state: Path, archive: Path, bin_dir: Path):
    driver = textwrap.dedent(f"""\
        set -Eeuo pipefail
        export APP_DIR={shlex.quote(_bash_path(app_dir))}
        export APP_NAME=fixture
        export SERVICE_NAME=fixture
        export DEPLOY_STATE_DIR={shlex.quote(_bash_path(state))}
        export PATH={shlex.quote(_bash_path(bin_dir))}:$PATH
        source {shlex.quote(_bash_path(ROLLBACK_SH))}
        ROLLBACK_ARTIFACT_ARCHIVE={shlex.quote(_bash_path(archive))}
        ROLLBACK_ARTIFACT_SHA256={"a" * 64}
        ROLLBACK_TARGET_REV={"b" * 40}
        rc=0
        if ! maybe_rebuild_frontend_after_rollback; then rc=1; fi
        echo "FUNC_RC=$rc"
        """)
    return subprocess.run(
        ["bash", "-c", driver], capture_output=True, text=True, env=dict(os.environ), timeout=120
    )


@requires_bash
@pytest.mark.parametrize("stamp", ["absent", "mismatch"])
def test_mismatched_install_is_reinstalled_before_staging(tmp_path, stamp):
    app_dir, state, archive, bin_dir, log, marker = _artifact_rollback_fixture(
        tmp_path, stamp=stamp
    )

    result = _run_artifact_rollback(app_dir, state, archive, bin_dir)

    assert "FUNC_RC=0" in result.stdout, result.stdout + result.stderr
    calls = log.read_text().splitlines()
    npm_ci = [i for i, line in enumerate(calls) if line.startswith("npm ci ")]
    stage = [i for i, line in enumerate(calls) if "scripts.stage_release_artifact" in line]
    assert npm_ci, (
        "the saved .next was restored against node_modules that do not match the "
        f"rollback target's lock; no `npm ci` ran. Calls: {calls}"
    )
    assert "--prefer-offline" in calls[npm_ci[0]]
    assert calls[npm_ci[0]].endswith("--prefix " + _bash_path(app_dir / "frontend"))
    assert stage and npm_ci[0] < stage[0], f"npm ci must precede staging: {calls}"
    assert (app_dir / "frontend" / ".next" / "MARKER").read_text().strip() == marker
    recorded = (app_dir / "frontend" / "node_modules" / STAMP).read_text().strip()
    assert recorded == hashlib.sha256(TARGET_LOCK.encode()).hexdigest()


@requires_bash
def test_consistent_install_restores_without_npm(tmp_path):
    """Stamp already matches the target lock: no npm, so no registry needed."""
    app_dir, state, archive, bin_dir, log, marker = _artifact_rollback_fixture(
        tmp_path, npm_exit=91, stamp="match"
    )

    result = _run_artifact_rollback(app_dir, state, archive, bin_dir)

    assert "FUNC_RC=0" in result.stdout, result.stdout + result.stderr
    assert not any(line.startswith("npm ") for line in log.read_text().splitlines())
    assert (app_dir / "frontend" / ".next" / "MARKER").read_text().strip() == marker


@requires_bash
def test_impossible_reinstall_fails_before_the_live_next_is_touched(tmp_path):
    app_dir, state, archive, bin_dir, log, _ = _artifact_rollback_fixture(
        tmp_path, npm_exit=1, stamp="mismatch"
    )

    result = _run_artifact_rollback(app_dir, state, archive, bin_dir)

    assert "FUNC_RC=1" in result.stdout, result.stdout + result.stderr
    assert "scripts.stage_release_artifact" not in log.read_text()
    live = (app_dir / "frontend" / ".next" / "MARKER").read_text().strip()
    assert live == "live-build-of-the-failed-deploy"
    assert not (
        app_dir / "frontend" / "node_modules" / STAMP
    ).exists(), "a stale stamp survived a failed reinstall and would vouch for the wrong tree"


def test_deploy_records_the_install_stamp_after_npm_ci():
    body = DEPLOY_SH.read_text(encoding="utf-8")
    install = body.index('npm ci --prefix "${APP_DIR}/frontend"')
    stamp = body.index("${FRONTEND_INSTALL_STAMP}", install)
    stage = body.index("python3 -m scripts.stage_release_artifact", install)
    assert install < stamp < stage


# ── B4 ───────────────────────────────────────────────────────────────


def _deploy_function(name: str) -> str:
    body = DEPLOY_SH.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = body.index(f"{name}() {{")
    return body[start : body.index("\n}\n", start) + len("\n}\n")]


def _deploy_line(prefix: str) -> str:
    body = DEPLOY_SH.read_text(encoding="utf-8").replace("\r\n", "\n")
    return next(line for line in body.splitlines() if line.startswith(prefix))


def test_deploy_cleans_incoming_on_every_exit():
    body = DEPLOY_SH.read_text(encoding="utf-8")
    assert "trap cleanup_incoming_release_archives EXIT" in body


def _run_deploy_exit(tmp_path: Path, archive: Path, *, exit_code: int):
    """Simulate a deploy.sh exit with the shipped cleanup function and traps."""
    driver = (
        textwrap.dedent(f"""\
        set -Eeuo pipefail
        warn() {{ printf '[warn] %s\\n' "$*" >&2; }}
        on_error() {{ echo "ERR_TRAP_FIRED"; }}
        RELEASE_ARCHIVE={shlex.quote(_bash_path(archive))}
        """)
        + _deploy_line("_INCOMING_ARCHIVE_NAME=")
        + "\n"
        + _deploy_function("cleanup_incoming_release_archives")
        + _deploy_line("trap 'on_error $LINENO' ERR")
        + "\n"
        + _deploy_line("trap cleanup_incoming_release_archives EXIT")
        + "\n"
        + f"exit {exit_code}\n"
    )
    return subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=60)


def _incoming(tmp_path: Path):
    incoming = tmp_path / "state" / "incoming"
    incoming.mkdir(parents=True)
    stale = incoming / f"{'1' * 40}-100.tar"
    stale.write_bytes(b"left by an interrupted earlier run")
    os.utime(stale, (1_000_000_000, 1_000_000_000))
    current = incoming / f"{'2' * 40}-200.tar"
    current.write_bytes(b"this run")
    os.utime(current, (1_500_000_000, 1_500_000_000))
    newer = incoming / f"{'3' * 40}-300.tar"
    newer.write_bytes(b"not ours to judge")
    os.utime(newer, (2_000_000_000, 2_000_000_000))
    unrelated = incoming / "operator-notes.tar"
    unrelated.write_bytes(b"not a workflow archive")
    os.utime(unrelated, (1_000_000_000, 1_000_000_000))
    return incoming, stale, current, newer, unrelated


@requires_bash
@pytest.mark.parametrize("exit_code", [0, 3])
def test_no_incoming_archive_survives_a_deploy_exit(tmp_path, exit_code):
    incoming, stale, current, newer, unrelated = _incoming(tmp_path)

    result = _run_deploy_exit(tmp_path, current, exit_code=exit_code)

    assert result.returncode == exit_code, "cleanup changed the deploy's exit status"
    assert "ERR_TRAP_FIRED" not in result.stdout, "cleanup re-entered the auto-rollback trap"
    assert not current.exists(), "this run's transferred archive was left on disk"
    assert not stale.exists(), "an earlier run's leftover archive was not pruned"
    assert newer.exists(), "an archive newer than this run's must not be deleted"
    assert unrelated.exists(), "only workflow-shaped archive names may be deleted"


@requires_bash
def test_cleanup_only_touches_a_directory_named_incoming(tmp_path):
    elsewhere = tmp_path / "releases"
    elsewhere.mkdir()
    archive = elsewhere / f"{'4' * 40}-400.tar"
    archive.write_bytes(b"saved rollback bytes")

    result = _run_deploy_exit(tmp_path, archive, exit_code=0)

    assert result.returncode == 0
    assert archive.exists()


# ── Single auto-rollback (re-review follow-up 1) ──────────────────────
# `set -E` makes the ERR trap fire inside $(...) command substitutions. The
# rollback then ran inside the subshell (its log captured into the variable)
# and, because ROLLBACK_ATTEMPTED cannot leave a subshell, the parent ran it a
# second time: a doubled outage window and lost log lines.


@requires_bash
def test_a_failure_inside_command_substitution_rolls_back_exactly_once(tmp_path):
    log = tmp_path / "rollbacks.log"
    driver = (
        textwrap.dedent(f"""\
        set -Eeuo pipefail
        error() {{ printf '[error] %s\n' "$*" >&2; }}
        ROLLBACK_ATTEMPTED="false"
        attempt_auto_rollback() {{
          [[ "${{ROLLBACK_ATTEMPTED}}" == "true" ]] && return 0
          ROLLBACK_ATTEMPTED="true"
          echo "rollback pid=${{BASHPID}}" >> {shlex.quote(_bash_path(log))}
        }}
        """)
        + _deploy_function("on_error")
        + "trap 'on_error $LINENO' ERR\n"
        + 'captured="$(false; echo unreachable)"\n'
        + "echo not-reached\n"
    )
    proc = subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert "not-reached" not in proc.stdout
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert len(lines) == 1, f"expected exactly one auto-rollback, got {lines}"
    assert "Deployment failed" in proc.stderr
    # The subshell names its failing line too, on stderr (not the captured value).
    assert "Command substitution failed" in proc.stderr
