#!/usr/bin/env python3
"""Emit a deterministic receipt for the exact Agent OS file loaded at session start."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT_OS = REPO / "docs" / "AGENT_OPERATING_SYSTEM.md"


def git_blob_sha(path: Path) -> str:
    """Return Git's blob object id for the exact bytes at *path*."""
    result = subprocess.run(
        ["git", "hash-object", "--no-filters", str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or f"git hash-object exited {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def main() -> int:
    if not AGENT_OS.is_file():
        print("  Agent OS loaded: UNAVAILABLE")
        print(f"  ACTION NEEDED: missing {AGENT_OS.relative_to(REPO)}")
        return 1

    # Read the exact bytes before emitting the receipt. The digest below is
    # therefore a receipt for the same working-tree content this startup
    # harness actually loaded, including any legitimate local modification.
    AGENT_OS.read_bytes()
    try:
        sha = git_blob_sha(AGENT_OS)
    except Exception as exc:
        print("  Agent OS loaded: UNAVAILABLE")
        print(f"  ACTION NEEDED: could not hash Agent OS: {exc}")
        return 1

    print(f"  Agent OS loaded: {sha}")
    print(
        "  Receipt: carry this exact SHA into the first material checkpoint "
        "and any PR/handoff from this session."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
