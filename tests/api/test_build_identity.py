"""The commit a server process reports is the one it loaded -- or explicitly unknown.

Pins ``src/api/build_identity.py`` (read ``.git`` directly, once, full SHAs only),
its surfacing on ``/api/status``, and the deploy workflow's use of it: the target
SHA is exported before the guard step can exit, and the smoke test fails when
the served build is not the shipped one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api.build_identity import PROCESS_BUILD, resolve_build_identity

ROOT = Path(__file__).resolve().parents[2]
SHA = "0123456789abcdef0123456789abcdef01234567"


def _repo(tmp_path, head, files=None):
    git_dir = tmp_path / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head + "\n", encoding="utf-8")
    for rel, text in (files or {}).items():
        path = git_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_detached_head_is_the_commit(tmp_path):
    assert resolve_build_identity(_repo(tmp_path, SHA)) == {
        "commit": SHA,
        "commit_source": "detached_head",
        "unavailable_reason": None,
    }


def test_symbolic_ref_resolves_loose_then_packed(tmp_path):
    loose = _repo(tmp_path / "a", "ref: refs/heads/main", {"refs/heads/main": SHA + "\n"})
    assert resolve_build_identity(loose)["commit"] == SHA
    packed = _repo(
        tmp_path / "b",
        "ref: refs/heads/main",
        {"packed-refs": f"# pack-refs with: peeled\n{SHA} refs/heads/main\n"},
    )
    result = resolve_build_identity(packed)
    assert result["commit"] == SHA and result["commit_source"] == "refs/heads/main"


def test_linked_worktree_follows_gitdir_and_commondir(tmp_path):
    common = tmp_path / "main" / ".git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "topic").write_text(SHA, encoding="utf-8")
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
    assert resolve_build_identity(worktree)["commit"] == SHA


@pytest.mark.parametrize(
    ("head", "files", "reason"),
    [
        ("not a ref", {}, "head_unrecognized"),
        ("ref: refs/heads/../../etc/passwd", {}, "head_unrecognized"),
        ("ref: refs/heads/main", {}, "ref_unresolved"),
        ("ref: refs/heads/main", {"refs/heads/main": "abc123\n"}, "ref_unresolved"),
        (SHA[:39], {}, "head_unrecognized"),
        (SHA.upper(), {}, "head_unrecognized"),
    ],
)
def test_anything_but_a_full_sha_is_unknown_never_a_guess(tmp_path, head, files, reason):
    result = resolve_build_identity(_repo(tmp_path, head, files))
    assert result == {"commit": None, "commit_source": None, "unavailable_reason": reason}


def test_no_repository_is_unknown(tmp_path):
    assert resolve_build_identity(tmp_path)["unavailable_reason"] == "no_repository"


def test_matches_git_on_this_checkout():
    expected = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True)
    assert resolve_build_identity(ROOT)["commit"] == expected.strip()


def test_status_serves_the_import_time_identity():
    response = TestClient(server.app).get("/api/status")
    assert response.status_code == 200
    build = response.json()["build"]
    assert build == PROCESS_BUILD
    assert build["process_started_at"]
    assert build["commit"] is None or len(build["commit"]) == 40


def test_deploy_workflow_verifies_the_served_build():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    guard = workflow[workflow.index("- name: Guard against skipping or reversing a deploy") :]
    guard = guard[: guard.index("\n      - name:", 1)]
    export = guard.index('echo "DEPLOY_TARGET_SHA=${TARGET_SHA}" >> "$GITHUB_ENV"')
    assert export < guard.index("exit 0"), "target SHA must be exported before any early exit"
    smoke = workflow[workflow.index("- name: Post-deploy smoke test") :]
    smoke = smoke[: smoke.index("\n      - name:", 1)]
    assert "jq -c '.build // empty'" in smoke
    assert '"${_served}" == "${DEPLOY_TARGET_SHA}"' in smoke
    assert "Served build mismatch" in smoke and "unavailable_reason" in smoke
