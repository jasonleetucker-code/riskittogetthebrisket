"""The trusted publisher can write one branch and cannot select main."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import class_b_model_publish as publisher
from scripts import class_b_model_verify as verifier

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    _git(repo, "switch", "-c", "main")
    _git(repo, "config", "user.name", "Class B Test")
    _git(repo, "config", "user.email", "class-b-test@example.invalid")
    source = repo / publisher.TARGET
    source.parent.mkdir(parents=True)
    source.write_bytes((ROOT / publisher.TARGET).read_bytes().replace(b"\r\n", b"\n"))
    evidence = repo / publisher.EVIDENCE
    evidence.write_bytes((ROOT / publisher.EVIDENCE).read_bytes().replace(b"\r\n", b"\n"))
    _git(repo, "add", "--", publisher.TARGET.as_posix(), publisher.EVIDENCE.as_posix())
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    output = tmp_path / "output"
    output.mkdir()
    before = source.read_bytes()
    after = (
        before.decode("utf-8")
        .replace(verifier.BEFORE_STATUS, verifier.AFTER_STATUS, 1)
        .replace(verifier.BEFORE_BODY, verifier.AFTER_BODY, 1)
        .encode("utf-8")
    )
    (output / "candidate.md").write_bytes(after)
    (output / "model-output.txt").write_bytes(b"COMPLETE\n")
    receipt = {
        "schema": "class-b-model-task/v1",
        "task_id": verifier.TASK_ID,
        "model_sha256": verifier.MODEL_SHA256,
        "runtime_sha256": verifier.RUNTIME_SHA256,
        "source_sha256": verifier._digest(before),
        "candidate_sha256": verifier._digest(after),
        "model_output_sha256": verifier._digest(b"COMPLETE\n"),
        "decision": "COMPLETE",
        "test": "exact-document-contract",
        "test_result": "passed",
        "refusals": [
            "path_denied",
            "command_denied",
            "network_denied_by_container",
        ],
    }
    (output / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return repo, remote, output


def test_publisher_pushes_only_the_verified_branch(tmp_path):
    repo, remote, output = _fixture(tmp_path)
    main_before = _git(repo, "rev-parse", "main")
    branch = publisher.publish(repo, output, run_id="12345")
    assert branch == "codex/class-b-isolation-12345"
    assert _git(repo, "rev-parse", "HEAD") != main_before
    assert _git(repo, "rev-parse", "main") == main_before
    assert _git(remote, "rev-parse", "refs/heads/main") == main_before
    assert _git(remote, "rev-parse", f"refs/heads/{branch}") == _git(repo, "rev-parse", "HEAD")
    assert (
        _git(repo, "show", "--pretty=format:", "--name-only", "HEAD") == publisher.TARGET.as_posix()
    )


@pytest.mark.parametrize("bad", ["0", "../main", "main", "123;echo", "1" * 21])
def test_publisher_rejects_untrusted_branch_names(bad):
    with pytest.raises(ValueError, match="run ID"):
        publisher.branch_name(bad)
