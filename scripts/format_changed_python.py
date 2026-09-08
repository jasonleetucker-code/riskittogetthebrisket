#!/usr/bin/env python3
"""Format and lint the Python files changed by the current work.

This is the model-neutral pre-push Ruff entrypoint. It intentionally delegates
all style decisions to the repository-pinned Ruff binary/config instead of
teaching agents to imitate formatter output.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _default_base() -> str | None:
    for ref in ("origin/main", "main"):
        if _git("rev-parse", "--verify", ref):
            return ref
    return None


def changed_python_files(base: str | None = None) -> list[Path]:
    """Return existing changed .py files from branch, index, and worktree."""
    names: set[str] = set()
    resolved_base = base or _default_base()
    if resolved_base:
        names.update(_git("diff", "--name-only", "--diff-filter=ACMR", f"{resolved_base}...HEAD"))
    names.update(_git("diff", "--name-only", "--diff-filter=ACMR"))
    names.update(_git("diff", "--cached", "--name-only", "--diff-filter=ACMR"))
    names.update(_git("ls-files", "--others", "--exclude-standard"))

    out: list[Path] = []
    for name in sorted(names):
        path = REPO / name
        if path.suffix == ".py" and path.is_file():
            out.append(path)
    return out


def _run(*args: str) -> None:
    subprocess.run(args, cwd=REPO, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        default=None,
        help="Git base ref for branch changes (default: origin/main, then main).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional explicit Python paths instead of auto-detecting changed files.",
    )
    args = parser.parse_args()

    if args.paths:
        files = [
            (REPO / path).resolve()
            for path in args.paths
            if Path(path).suffix == ".py" and (REPO / path).is_file()
        ]
    else:
        files = changed_python_files(args.base)

    if not files:
        print("RUFF_FORMAT_OK files=0")
        return 0

    rel = [str(path.relative_to(REPO)) for path in files]
    print(f"Ruff formatting {len(rel)} changed Python file(s):")
    for path in rel:
        print(f"  {path}")

    _run(sys.executable, "-m", "ruff", "format", *rel)
    _run(sys.executable, "-m", "ruff", "format", "--check", *rel)
    _run(sys.executable, "-m", "ruff", "check", *rel)
    _run("git", "diff", "--check", "--", *rel)

    print(f"RUFF_FORMAT_OK files={len(rel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
