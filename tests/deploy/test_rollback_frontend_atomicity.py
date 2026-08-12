"""A failed frontend build must never replace the serviceable one.

Incident of 2026-08-12, defect 4 of 4.  During the auto-rollback the
frontend rebuild exited 1, and 80 ms later the rollback verified and
swapped that incomplete staging directory over the last known-good
``.next``::

    17:22:19.122  Next.js build worker exited with code: 1
    17:22:19.268  [verify-build] OK: 52 manifest-referenced asset(s)
    17:22:49.577  Rolled-back frontend build swapped into place
    17:22:51.704  Frontend service failed to start
                  ENOENT .../frontend/.next/prerender-manifest.json

The frontend was then down from 17:22:49 until the second rollback
finished at 17:25:22 — two and a half minutes of self-inflicted outage
on top of the backend one.

Two independent holes, and the tests below cover both:

* ``rollback.sh`` ran ``npm run build`` in a subshell whose exit status
  nothing read.  ``deploy.sh`` has the identical subshell and DID abort,
  because on that path ``set -e`` was live; here ``main()`` calls the
  function as ``if ! maybe_rebuild_frontend_after_rollback``, and bash
  disables errexit for the whole body of a function invoked as a
  condition.  Same code, opposite behaviour.
* ``verify_frontend_build_manifest`` walked the assets that the manifests
  REFERENCE, and required only ``build-manifest.json`` to exist.  An
  aborted export writes that file early and never reaches
  ``prerender-manifest.json``, so a build that could not start passed
  verification.

These drive the REAL functions from ``deploy/rollback.sh`` (sourced, not
reimplemented — a copy would pass while production still broke) against a
fixture frontend whose ``npm`` is a stub script we control.  The
invariant under test is the one the incident violated:

    if the staged build is not usable, the live .next is untouched
    and still serviceable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SH = REPO_ROOT / "deploy" / "rollback.sh"

# Every root-level artifact a successful `next build` leaves behind that
# `next start` opens at boot.  Kept in step with the list in
# deploy/rollback.sh + deploy/deploy.sh.
RUNTIME_ARTIFACTS = (
    "BUILD_ID",
    "build-manifest.json",
    "app-path-routes-manifest.json",
    "prerender-manifest.json",
    "routes-manifest.json",
    "required-server-files.json",
)

KNOWN_GOOD_MARKER = "this-is-the-serviceable-build"


def _write_dist(dist: Path, *, marker: str, omit: tuple[str, ...] = ()) -> None:
    """Write a build output that looks like a real one."""
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "static").mkdir(exist_ok=True)
    (dist / "static" / "app.js").write_text("//js\n")
    (dist / "MARKER").write_text(marker)
    for name in RUNTIME_ARTIFACTS:
        if name in omit:
            continue
        if name == "BUILD_ID":
            (dist / name).write_text("build-id\n")
        elif name == "build-manifest.json":
            # One real reference so the asset walk has something to do.
            (dist / name).write_text(json.dumps({"pages": {"/": ["static/app.js"]}}))
        else:
            (dist / name).write_text("{}")


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    """An app dir with a serviceable .next and a scriptable `npm`."""
    app_dir = tmp_path / "app"
    fe = app_dir / "frontend"
    fe.mkdir(parents=True)
    (fe / "package.json").write_text(json.dumps({"name": "fixture"}))
    _write_dist(fe / ".next", marker=KNOWN_GOOD_MARKER)
    return app_dir


def _stub_npm(bin_dir: Path, *, build_exit: int, produce: str) -> None:
    """A stand-in `npm` whose build outcome the test chooses.

    ``produce`` is one of: ``complete`` (a full build), ``partial`` (an
    aborted export — manifests written early, prerender-manifest never
    reached, which is exactly what production had), or ``none``.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    omit = "prerender-manifest.json" if produce == "partial" else ""
    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # `npm ci` / `npm install` are no-ops here.
        if [[ "$1" != "run" ]]; then exit 0; fi
        dist="${{NEXT_DIST_DIR:-.next}}"
        if [[ "{produce}" != "none" ]]; then
          mkdir -p "$dist/static"
          echo '//js' > "$dist/static/app.js"
          echo 'this-is-the-STAGED-build' > "$dist/MARKER"
          echo 'build-id' > "$dist/BUILD_ID"
          echo '{{"pages": {{"/": ["static/app.js"]}}}}' > "$dist/build-manifest.json"
          for f in app-path-routes-manifest.json prerender-manifest.json \\
                   routes-manifest.json required-server-files.json; do
            if [[ "$f" == "{omit}" ]]; then continue; fi
            echo '{{}}' > "$dist/$f"
          done
        fi
        exit {build_exit}
        """)
    npm = bin_dir / "npm"
    npm.write_text(script)
    npm.chmod(0o755)


def _run_rebuild(app_dir: Path, bin_dir: Path) -> subprocess.CompletedProcess:
    """Source rollback.sh and run the real rebuild-and-swap function.

    ``systemctl`` is absent from PATH, so the function's
    ``sudo -n systemctl cat`` probe fails and the service stop/start
    branch is skipped — the swap itself still runs, which is the part
    under test.

    The call form is load-bearing and must match ``main()``'s::

        if ! maybe_rebuild_frontend_after_rollback; then

    Bash disables ``errexit`` for the entire body of a function invoked
    as a condition, and that suppression is *the* mechanism of this
    incident.  An earlier version of this harness called the function
    plainly, which left ``set -e`` active, so the failing build aborted
    on its own and the test passed against the UNFIXED script — proving
    nothing.  Calling it exactly as production does is what makes the
    RED real.
    """
    driver = textwrap.dedent(f"""\
        set -Eeuo pipefail
        export APP_DIR={app_dir!s}
        export APP_NAME=fixture
        export SERVICE_NAME=fixture
        export PATH={bin_dir!s}:$PATH
        source {ROLLBACK_SH!s}
        rc=0
        if ! maybe_rebuild_frontend_after_rollback; then rc=1; fi
        echo "FUNC_RC=$rc"
        """)
    env = dict(os.environ, APP_DIR=str(app_dir))
    return subprocess.run(
        ["bash", "-c", driver], capture_output=True, text=True, env=env, timeout=120
    )


def _live_marker(app_dir: Path) -> str | None:
    p = app_dir / "frontend" / ".next" / "MARKER"
    return p.read_text().strip() if p.exists() else None


def _live_is_serviceable(app_dir: Path) -> bool:
    dist = app_dir / "frontend" / ".next"
    return all((dist / name).exists() for name in RUNTIME_ARTIFACTS)


class TestAFailedStagedBuildCannotReachTheLiveDirectory:
    def test_a_nonzero_build_leaves_the_known_good_build_in_place(self, frontend, tmp_path):
        """The incident, exactly: build exits 1, output is partial."""
        bin_dir = tmp_path / "bin"
        _stub_npm(bin_dir, build_exit=1, produce="partial")

        result = _run_rebuild(frontend, bin_dir)

        assert "FUNC_RC=0" not in result.stdout, (
            "the rollback reported success after its frontend build failed:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert _live_marker(frontend) == KNOWN_GOOD_MARKER, (
            "a FAILED staged build replaced the serviceable frontend — this is "
            "the 2026-08-12 defect"
        )
        assert _live_is_serviceable(frontend)

    def test_the_incomplete_staging_dir_is_not_left_behind(self, frontend, tmp_path):
        """A half-built .next.new must not be inherited by the next run."""
        bin_dir = tmp_path / "bin"
        _stub_npm(bin_dir, build_exit=1, produce="partial")
        _run_rebuild(frontend, bin_dir)
        assert not (frontend / "frontend" / ".next.new").exists()


class TestAnIncompleteBuildIsNotUsableEvenWhenItExitsZero:
    """Exit status is necessary, not sufficient.

    A build can report success and still be missing what `next start`
    opens — and the reference-walk check passed on exactly such a
    directory in production.
    """

    def test_missing_prerender_manifest_blocks_the_swap(self, frontend, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_npm(bin_dir, build_exit=0, produce="partial")

        result = _run_rebuild(frontend, bin_dir)

        assert "FUNC_RC=0" not in result.stdout, (
            "a build with no prerender-manifest.json was accepted; "
            "next start would ENOENT on it:\n" + result.stdout + result.stderr
        )
        assert _live_marker(frontend) == KNOWN_GOOD_MARKER
        assert _live_is_serviceable(frontend)


class TestASuccessfulBuildStillSwaps:
    """The guard must not be a blanket refusal.

    Without this, every test above passes on a rollback that never
    swaps anything — which would be a different outage.
    """

    def test_a_complete_build_replaces_the_live_directory(self, frontend, tmp_path):
        bin_dir = tmp_path / "bin"
        _stub_npm(bin_dir, build_exit=0, produce="complete")

        result = _run_rebuild(frontend, bin_dir)

        assert "FUNC_RC=0" in result.stdout, (
            "a healthy rollback build did not complete:\n" + result.stdout + result.stderr
        )
        assert _live_marker(frontend) == "this-is-the-STAGED-build"
        assert _live_is_serviceable(frontend)


class TestBothScriptsAgree:
    """deploy.sh and rollback.sh must not diverge on this again.

    Their own comments require the two verifiers to stay behaviourally
    identical; the incident happened in the gap between them.
    """

    @pytest.mark.parametrize("script", ["deploy.sh", "rollback.sh"])
    def test_each_requires_the_runtime_artifacts(self, script):
        text = (REPO_ROOT / "deploy" / script).read_text()
        for name in RUNTIME_ARTIFACTS:
            assert f'"{name}"' in text, f"{script} does not require {name}"

    def test_the_rollback_build_status_is_read(self):
        text = ROLLBACK_SH.read_text()
        assert "build_rc" in text, (
            "rollback.sh no longer captures its frontend build's exit status"
        )


@pytest.fixture(autouse=True)
def _no_stray_dirs(tmp_path):
    yield
    shutil.rmtree(tmp_path, ignore_errors=True)
