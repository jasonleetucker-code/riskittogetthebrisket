"""Classify an exact deploy target for the artifact-era workflow.

The workflow executes this helper from its own trusted commit, before checking
out the target. Only an explicit manual rollback may use the historical build
path for a target predating the complete artifact deployment contract.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess

_SHA = re.compile(r"[0-9a-f]{40}")
_ARTIFACT_PATHS = (
    "requirements.lock.txt",
    "requirements-dev.lock.txt",
    "scripts/release_artifact.py",
    "scripts/stage_release_artifact.py",
)


def release_mode(repo: Path, target: str, event: str, allow_legacy: bool) -> str:
    """Return artifact or legacy, refusing accidental downgrades to legacy."""
    if not _SHA.fullmatch(target):
        raise ValueError("deploy target must be an exact commit SHA")
    commit = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{target}^{{commit}}"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if commit.returncode:
        raise ValueError("deploy target commit is unavailable")
    missing = [
        path
        for path in _ARTIFACT_PATHS
        if subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{target}:{path}"],
            check=False,
            capture_output=True,
            timeout=30,
        ).returncode
    ]
    if not missing:
        return "artifact"
    if event == "workflow_dispatch" and allow_legacy:
        return "legacy"
    raise ValueError(
        "target lacks artifact contract paths: "
        + ", ".join(missing)
        + "; legacy deployment requires explicit manual rollback override"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--allow-legacy", choices=("true", "false"), default="false")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        mode = release_mode(args.repo, args.target, args.event, args.allow_legacy == "true")
    except ValueError as exc:
        parser.error(str(exc))
    print(f"deploy release mode: {mode}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"mode={mode}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
