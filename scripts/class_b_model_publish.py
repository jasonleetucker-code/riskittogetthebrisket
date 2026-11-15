"""Trusted branch publisher for the one verified Class-B model task.

Run only from the default-branch workflow's separate write-token job. The
worker output is data; it cannot select a path, command, Git ref, or PR base.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from scripts.class_b_model_verify import verify

TARGET = Path("docs/engineering/CLASS_B_ISOLATION.md")
EVIDENCE = Path("docs/engineering/CLASS_B_BRANCH_PILOT.md")


def _git(repo: Path, *args: str, capture: bool = False) -> str:
    command = ["git", "-C", str(repo), *args]
    if capture:
        return subprocess.check_output(command, text=True).strip()
    subprocess.run(command, check=True)
    return ""


def branch_name(run_id: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
        raise ValueError("workflow run ID must be a positive decimal integer")
    return f"codex/class-b-isolation-{run_id}"


def publish(repo: Path, output_dir: Path, *, run_id: str) -> str:
    branch = branch_name(run_id)
    repo = repo.resolve()
    source = repo / TARGET
    evidence = repo / EVIDENCE
    verify(source, evidence, output_dir, require_network=True)
    if _git(repo, "status", "--porcelain", "--untracked-files=no", capture=True):
        raise ValueError("trusted checkout has tracked changes before publication")
    if _git(repo, "branch", "--list", branch, capture=True):
        raise ValueError("Class-B branch already exists locally")
    if _git(repo, "ls-remote", "--heads", "origin", branch, capture=True):
        raise ValueError("Class-B branch already exists remotely")
    _git(repo, "switch", "-c", branch)
    shutil.copyfile(output_dir / "candidate.md", source)
    _git(repo, "add", "--", TARGET.as_posix())
    staged = _git(repo, "diff", "--cached", "--name-only", capture=True).splitlines()
    if staged != [TARGET.as_posix()]:
        raise ValueError("staged paths exceed the Class-B contract")
    _git(repo, "diff", "--cached", "--check")
    _git(repo, "commit", "-m", "docs: update bounded Class-B evidence status")
    _git(repo, "push", "origin", f"HEAD:refs/heads/{branch}")
    return branch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(publish(args.repo, args.output_dir, run_id=args.run_id))


if __name__ == "__main__":
    main()
