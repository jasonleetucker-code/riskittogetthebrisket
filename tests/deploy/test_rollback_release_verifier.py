"""A rollback certifies the live frontend with the PRE-ROLLBACK revision's verifier.

#1707: Next writes its runtime response cache into the served tree, so the
post-start "live frontend is the tested artifact" check needs the verifier that
knows about it.  rollback.sh checks out the target revision BEFORE that check,
so without this the target's own (possibly pre-#1707) verifier would run and
refuse every correct rollback in the retention window -- including the ERR-trap
rollback of a failed forward deploy.  rollback.sh therefore preserves the
running revision's verifier before the checkout, exactly as it does for the
runtime reconciler.  These tests drive the REAL functions from rollback.sh.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from src.api.build_identity import _artifact_id, _frontend_tree_digest

REPO = Path(__file__).resolve().parents[2]
ROLLBACK_SH = REPO / "deploy/rollback.sh"
SHA = "c" * 40
TARGET_VERIFIER_MARKER = "TARGET REVISION VERIFIER WAS USED"
HOSTILE_MARKER = "HOSTILE PYTHON ENVIRONMENT CODE RAN"
# Produced by the PRE-#1707 src/api/build_identity.py (origin/main 1d0438520)
# for the tree _legacy_release builds -- i.e. what a saved pre-fix manifest says.
GOLDEN_LEGACY_TREE_DIGEST = "891b189d6b38ce487321829a74759d89b37371ea3da471709717f0580cb45a87"
GOLDEN_LEGACY_ARTIFACT_ID = "33603033b905a3a1c87e47b16e529c1fd9204b1741c2f7336e23029af685d82c"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _main_body() -> str:
    text = ROLLBACK_SH.read_text(encoding="utf-8")
    start = text.index("\nmain() {")
    return text[start : text.index("\n}\n", start)]


def test_verifier_is_preserved_before_the_checkout_and_used_for_the_post_start_verify():
    body = _main_body()
    assert body.index("preserve_release_verifier") < body.index("git checkout --force")
    verify = body.index("verify_live_release_with_preserved_verifier")
    assert body.index('bash "${APP_DIR}/deploy/verify-deploy.sh"') < verify
    # The checked-out target's verifier is never invoked after the checkout.
    after_checkout = body[body.index("git checkout --force") :]
    assert "python3 -m scripts.release_artifact" not in after_checkout


def test_the_preserved_closure_is_self_contained():
    """Only these two files are copied; they may import nothing else from the repo."""
    for relative, allowed in (
        ("scripts/release_artifact.py", {"src.api.build_identity"}),
        ("src/api/build_identity.py", set()),
    ):
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root in {"src", "scripts"}:
                    assert node.module in allowed, (relative, node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in {"src", "scripts"}, relative


def _legacy_release(app_dir: Path) -> tuple[Path, str]:
    """A rollback target as a pre-#1707 deploy left it: legacy manifest, real tree."""
    for relative in ("src/api/build_identity.py", "scripts/release_artifact.py"):
        (app_dir / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, app_dir / relative)
    (app_dir / ".git").mkdir()
    (app_dir / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")
    (app_dir / "requirements.lock.txt").write_text("fastapi==1.0\n", encoding="utf-8")
    build = app_dir / "frontend/.next"
    (build / "static").mkdir(parents=True)
    (build / "server").mkdir()
    (app_dir / "frontend/package-lock.json").write_text("{}\n", encoding="utf-8")
    (build / "BUILD_ID").write_text("legacy-build\n", encoding="utf-8")
    (build / "static/app.js").write_bytes(b"tested frontend")
    (build / "server/app-paths-manifest.json").write_text(
        json.dumps({"/login/page": "app/login/page.js"}), encoding="utf-8"
    )
    (build / "server/pages-manifest.json").write_text("{}", encoding="utf-8")
    identity = {
        "commit": SHA,
        "python_lock_sha256": hashlib.sha256(b"fastapi==1.0\n").hexdigest(),
        "frontend_lock_sha256": hashlib.sha256(b"{}\n").hexdigest(),
        "python_abi": "cpython-3.12",
        "node_version": "v20.19.0",
        "next_build_id": "legacy-build",
        # GOLDEN, not computed with this PR's own legacy mode: the value the
        # pre-#1707 build_identity.py (origin/main at 1d0438520) produces for
        # exactly this tree.
        "frontend_tree_sha256": GOLDEN_LEGACY_TREE_DIGEST,
        "backend_artifact_sha256": None,
    }
    artifact_id = GOLDEN_LEGACY_ARTIFACT_ID
    manifest = app_dir / "state/staged_release_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "calculator-release/v1",
                "artifact_id": artifact_id,
                "identity": identity,
                "backend_artifact_unavailable_reason": "backend_artifact_not_built_in_this_phase",
            }
        ),
        encoding="utf-8",
    )
    return manifest, artifact_id


def _serve_traffic(app_dir: Path, name: str = "login.html") -> None:
    owner = hashlib.sha256(b"/login/page").hexdigest()
    cache = app_dir / "frontend/.next/server/route-cache/APP_PAGE" / owner / "$"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / name).write_bytes(b"runtime response")


def _hostile_python_environment(tmp_path: Path) -> str:
    """Exports that would hijack an unisolated `python3 -m scripts...`.

    * PYTHONPATH -> a directory holding a hostile ``scripts`` package;
    * PYTHONSAFEPATH=1 -> would drop the copy's directory from sys.path;
    * PYTHONHOME -> nonexistent, would break the interpreter outright;
    * PYTHONUSERBASE -> a user site-packages holding a hostile ``scripts``
      package AND a ``.pth`` file whose ``import`` line runs at startup.
    """
    hostile = tmp_path / "hostile"
    package = hostile / "path/scripts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    payload = f"import sys; print({HOSTILE_MARKER!r}); sys.exit(0)\n"
    (package / "release_artifact.py").write_text(payload, encoding="utf-8")
    userbase = hostile / "userbase"
    usersite = subprocess.run(
        [
            "bash",
            "-c",
            f"PYTHONUSERBASE={userbase.as_posix()} python3 -c "
            "'import site; print(site.getusersitepackages())'",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    site_dir = Path(usersite)
    (site_dir / "scripts").mkdir(parents=True)
    (site_dir / "scripts/__init__.py").write_text("", encoding="utf-8")
    (site_dir / "scripts/release_artifact.py").write_text(payload, encoding="utf-8")
    (site_dir / "hostile.pth").write_text(payload, encoding="utf-8")
    return textwrap.dedent(f"""\
        export PYTHONPATH={(hostile / "path").as_posix()}
        export PYTHONSAFEPATH=1
        export PYTHONHOME={(hostile / "no-such-home").as_posix()}
        export PYTHONUSERBASE={userbase.as_posix()}
        """)


def _run(app_dir: Path, tmp_path: Path, manifest: Path, *, preserve: bool, hostile_env: str = ""):
    """Preserve (or not), then check out the target, then run the post-start verify."""
    target_copy = tmp_path / "target_build_identity.py"
    target_copy.write_text(f"raise SystemExit({TARGET_VERIFIER_MARKER!r})", encoding="utf-8")
    driver = textwrap.dedent(f"""\
        set -Eeuo pipefail
        export APP_DIR={app_dir.as_posix()}
        export TMPDIR={tmp_path.as_posix()}
        source {ROLLBACK_SH.as_posix()}
        """)
    driver += hostile_env
    driver += textwrap.dedent(f"""\
        {"preserve_release_verifier" if preserve else ":"}
        cp {target_copy.as_posix()} {(app_dir / "src/api/build_identity.py").as_posix()}
        rc=0
        if ! verify_live_release_with_preserved_verifier {manifest.as_posix()} {SHA}; then rc=1; fi
        echo "FUNC_RC=$rc"
        """)
    return subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=120)


@pytest.fixture
def target(tmp_path: Path):
    if subprocess.run(["bash", "-c", "command -v python3"], capture_output=True).returncode:
        pytest.skip("python3 not on bash PATH")
    app_dir = tmp_path / "app"
    manifest, artifact_id = _legacy_release(app_dir)
    _serve_traffic(app_dir)  # verify-deploy.sh has already sent it traffic
    return app_dir, manifest, artifact_id


def test_post_traffic_legacy_target_verifies_with_the_preserved_verifier(target, tmp_path):
    app_dir, manifest, artifact_id = target
    result = _run(app_dir, tmp_path, manifest, preserve=True)
    assert "FUNC_RC=0" in result.stdout, result.stdout + result.stderr
    assert artifact_id in result.stdout
    assert TARGET_VERIFIER_MARKER not in result.stdout + result.stderr


def test_without_a_preserved_verifier_the_post_start_verify_fails_closed(target, tmp_path):
    app_dir, manifest, _ = target
    result = _run(app_dir, tmp_path, manifest, preserve=False)
    assert "FUNC_RC=1" in result.stdout, result.stdout + result.stderr
    assert "No release verifier was preserved" in result.stdout + result.stderr
    # Fail closed means the target's copy is never a fallback.
    assert TARGET_VERIFIER_MARKER not in result.stdout + result.stderr


def test_the_preserved_verifier_still_refuses_an_undeclared_route_cache_entry(target, tmp_path):
    app_dir, manifest, _ = target
    _serve_traffic(app_dir, name="evil.js")
    result = _run(app_dir, tmp_path, manifest, preserve=True)
    assert "FUNC_RC=1" in result.stdout, result.stdout + result.stderr
    assert "undeclared entry" in result.stderr


def test_a_hostile_python_environment_cannot_hijack_the_preserved_verifier(target, tmp_path):
    """-E -s -S: no PYTHON* variable, user site or .pth file reaches the verify."""
    app_dir, manifest, artifact_id = target
    result = _run(
        app_dir,
        tmp_path,
        manifest,
        preserve=True,
        hostile_env=_hostile_python_environment(tmp_path),
    )
    assert HOSTILE_MARKER not in result.stdout + result.stderr
    assert "FUNC_RC=0" in result.stdout, result.stdout + result.stderr
    assert artifact_id in result.stdout


def test_golden_legacy_values_match_the_live_legacy_mode(tmp_path):
    """The golden pins and this PR's legacy algorithm agree on a cache-free tree."""
    manifest, artifact_id = _legacy_release(tmp_path / "app")
    identity = json.loads(manifest.read_text(encoding="utf-8"))["identity"]
    assert _frontend_tree_digest(tmp_path / "app/frontend/.next") == GOLDEN_LEGACY_TREE_DIGEST
    assert _artifact_id(identity) == GOLDEN_LEGACY_ARTIFACT_ID == artifact_id
