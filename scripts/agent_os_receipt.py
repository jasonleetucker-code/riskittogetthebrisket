#!/usr/bin/env python3
"""Emit a deterministic receipt for the exact Agent OS bytes loaded at session start."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT_OS = REPO / "docs" / "AGENT_OPERATING_SYSTEM.md"


def git_blob_sha(content: bytes) -> str:
    """Return Git's blob object id for exactly *content*."""
    result = subprocess.run(
        ["git", "hash-object", "--stdin"],
        cwd=REPO,
        input=content,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or f"git hash-object exited {result.returncode}")
    return result.stdout.decode().strip()


def main() -> int:
    if not AGENT_OS.is_file():
        print("  Agent OS loaded: UNAVAILABLE")
        print(f"  ACTION NEEDED: missing {AGENT_OS.relative_to(REPO)}")
        return 1

    try:
        content = AGENT_OS.read_bytes()
        sha = git_blob_sha(content)
    except Exception as exc:
        print("  Agent OS loaded: UNAVAILABLE")
        print(f"  ACTION NEEDED: could not load/hash Agent OS: {exc}")
        return 1

    print(f"  Agent OS loaded: {sha}")
    print(
        "  Receipt: carry this exact SHA into the first material checkpoint "
        "and any PR/handoff from this session."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
