"""Manual-deploy SHA pinning (owner decision C, 2026-10-01).

The requested ref is resolved once (``scripts/resolve_deploy_ref.py``) and every
stage of Deploy Production -- validate checkout, deploy checkout, guard, box
command, smoke identity -- consumes that one SHA. Before this, a dispatch with
``deploy_ref`` validated the workflow commit (validate's checkout ignored the
input), and the box re-resolved a branch name after its own fetch, so a manual
deploy could ship a commit neither validated nor guarded.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from resolve_deploy_ref import ResolveError, resolve  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("pin") / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    first = _commit(root, "a")
    second = _commit(root, "b")
    # Remote-tracking branches and tags, as actions/checkout + fetch --tags produce.
    _git(root, "update-ref", "refs/remotes/origin/main", second)
    _git(root, "update-ref", "refs/remotes/origin/hotfix", first)
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "tag",
        "-a",
        "v1",
        first,
        "-m",
        "v1",
    )
    _git(root, "update-ref", "refs/remotes/origin/clash", first)
    _git(root, "tag", "clash", second)
    return {"root": root, "first": first, "second": second}


def test_empty_request_resolves_to_the_workflow_commit(repo):
    assert resolve(repo["root"], "", repo["second"]) == (repo["second"], "default")


def test_explicit_full_commit(repo):
    assert resolve(repo["root"], repo["first"], repo["second"]) == (repo["first"], "commit")


def test_branch_and_annotated_tag_resolve_to_commits(repo):
    assert resolve(repo["root"], "hotfix", repo["second"]) == (repo["first"], "branch")
    assert resolve(repo["root"], "v1", repo["second"]) == (repo["first"], "tag")


def test_a_ref_that_moves_after_resolution_does_not_move_the_target(repo):
    sha, _ = resolve(repo["root"], "hotfix", repo["second"])
    _git(repo["root"], "update-ref", "refs/remotes/origin/hotfix", repo["second"])
    try:
        # The resolved value is what every stage carries; re-resolving later would
        # now give a different commit, which is exactly what pinning prevents.
        assert sha == repo["first"]
        assert resolve(repo["root"], "hotfix", repo["second"])[0] == repo["second"]
    finally:
        _git(repo["root"], "update-ref", "refs/remotes/origin/hotfix", repo["first"])


@pytest.mark.parametrize(
    ("requested", "code"),
    [
        ("main; rm -rf /", 2),
        ("$(whoami)", 2),
        ("-x", 2),
        ("a..b", 2),
        ("main@{1}", 2),
        ("feature/", 2),
        ("x.lock", 2),
        ("has space", 2),
        ("no-such-branch", 3),
        ("f" * 40, 3),
        ("abc1234", 2),  # abbreviated SHA refused, not guessed
        ("clash", 4),  # both a branch and a tag
    ],
)
def test_malformed_missing_abbreviated_and_ambiguous_refs_are_refused(repo, requested, code):
    with pytest.raises(ResolveError) as exc:
        resolve(repo["root"], requested, repo["second"])
    assert exc.value.code == code


def test_cli_writes_only_the_sha_and_kind_to_github_output(repo, tmp_path):
    out = tmp_path / "out.txt"
    env = {"GITHUB_OUTPUT": str(out), "PATH": __import__("os").environ["PATH"]}
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "resolve_deploy_ref.py"),
            "--requested",
            "hotfix",
            "--default",
            repo["second"],
            "--repo",
            str(repo["root"]),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8").splitlines() == [f"sha={repo['first']}", "kind=branch"]


# --- the workflow consumes one SHA everywhere ----------------------------------


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), WORKFLOW.read_text(
        encoding="utf-8"
    )


def _step(job, name_prefix):
    return next(s for s in job["steps"] if s.get("name", "").startswith(name_prefix))


def test_resolve_job_publishes_the_sha_and_holds_no_secrets(workflow):
    parsed, text = workflow
    resolve_job = parsed["jobs"]["resolve"]
    assert resolve_job["outputs"]["sha"] == "${{ steps.resolve.outputs.sha }}"
    assert "secrets." not in yaml.safe_dump(resolve_job)
    step = _step(resolve_job, "Resolve the requested ref")
    assert step["env"]["REQUESTED_REF"] == "${{ inputs.deploy_ref }}"
    assert "resolve_deploy_ref.py" in step["run"]


def test_validate_and_deploy_check_out_the_resolved_sha(workflow):
    parsed, _ = workflow
    sha = "${{ needs.resolve.outputs.sha }}"
    validate, deploy = parsed["jobs"]["validate"], parsed["jobs"]["deploy"]
    assert validate["needs"] == "resolve"
    assert _step(validate, "Checkout")["with"]["ref"] == sha
    assert "git rev-parse HEAD" in _step(validate, "Assert the validated tree")["run"]
    assert deploy["needs"] == ["resolve", "validate"]
    assert deploy["env"]["DEPLOY_TARGET_SHA"] == sha
    assert _step(deploy, "Checkout")["with"]["ref"] == sha


def test_guard_and_box_command_never_re_resolve_the_raw_input(workflow):
    parsed, text = workflow
    deploy = parsed["jobs"]["deploy"]
    guard = _step(deploy, "Guard against skipping")
    remote = _step(deploy, "Run remote deploy script")
    for step in (guard, remote):
        assert "DEPLOY_REF_INPUT" not in yaml.safe_dump(step)
        assert "deploy_ref" not in yaml.safe_dump(step.get("env", {}))
    assert 'TARGET_SHA="${DEPLOY_TARGET_SHA:-}"' in guard["run"]
    assert 'DEPLOY_REF="${DEPLOY_TARGET_SHA:-}"' in remote["run"]
    assert "^[0-9a-f]{40}$" in remote["run"]
    # The raw input appears exactly once: as an env value for the resolver.
    assert len(re.findall(r"inputs\.deploy_ref", text)) == 1


def test_rollback_still_needs_explicit_authorization(workflow):
    parsed, _ = workflow
    flag = parsed[True]["workflow_dispatch"]["inputs"]["allow_non_fast_forward"]
    assert flag["default"] is False
    guard = _step(parsed["jobs"]["deploy"], "Guard against skipping")
    assert guard["env"]["ALLOW_NON_FF"] == "${{ inputs.allow_non_fast_forward }}"
    assert "would move production BACKWARDS" in guard["run"]
