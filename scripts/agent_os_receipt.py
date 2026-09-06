#!/usr/bin/env python3
"""Write and print a deterministic local receipt for the Agent OS loaded at SessionStart."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT_OS_REL = Path("docs/AGENT_OPERATING_SYSTEM.md")
AGENT_OS = REPO / AGENT_OS_REL
RECEIPT_DIR = REPO / ".claude" / "session-receipts"
RECEIPT_PATH = RECEIPT_DIR / "latest.env"
UNKNOWN = "UNKNOWN"


def _git_text(*args: str, input_bytes: bytes | None = None) -> str:
    """Return stripped git stdout, or UNKNOWN when the fact cannot be proven."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO,
            input=input_bytes,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return UNKNOWN
    if result.returncode != 0 or not result.stdout.strip():
        return UNKNOWN
    return result.stdout.decode(errors="replace").strip()


def _loaded_blob_sha(content: bytes | None) -> str:
    if content is None:
        return UNKNOWN
    return _git_text("hash-object", "--stdin", input_bytes=content)


def build_receipt() -> dict[str, str]:
    """Build receipt fields from observable local repository state only."""
    try:
        content = AGENT_OS.read_bytes()
    except Exception:
        content = None

    loaded_sha = _loaded_blob_sha(content)
    head_blob_sha = _git_text("rev-parse", f"HEAD:{AGENT_OS_REL.as_posix()}")
    repo_head_sha = _git_text("rev-parse", "HEAD")

    if loaded_sha == UNKNOWN or head_blob_sha == UNKNOWN:
        dirty = UNKNOWN
    else:
        dirty = "true" if loaded_sha != head_blob_sha else "false"

    return {
        "AGENT_OS_PATH": AGENT_OS_REL.as_posix(),
        "AGENT_OS_LOADED_BLOB_SHA": loaded_sha,
        "AGENT_OS_HEAD_BLOB_SHA": head_blob_sha,
        "REPO_HEAD_SHA": repo_head_sha,
        "AGENT_OS_DIRTY": dirty,
        "LOADED_AT_UTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_receipt(values: dict[str, str]) -> None:
    """Atomically replace the ignored local latest receipt."""
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".latest.", suffix=".tmp", dir=RECEIPT_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for key in (
                "AGENT_OS_PATH",
                "AGENT_OS_LOADED_BLOB_SHA",
                "AGENT_OS_HEAD_BLOB_SHA",
                "REPO_HEAD_SHA",
                "AGENT_OS_DIRTY",
                "LOADED_AT_UTC",
            ):
                handle.write(f"{key}={values.get(key, UNKNOWN)}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, RECEIPT_PATH)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def format_startup_line(values: dict[str, str]) -> str:
    return (
        "AGENT OS LOAD RECEIPT: "
        f"loaded={values.get('AGENT_OS_LOADED_BLOB_SHA', UNKNOWN)} "
        f"head_blob={values.get('AGENT_OS_HEAD_BLOB_SHA', UNKNOWN)} "
        f"repo_head={values.get('REPO_HEAD_SHA', UNKNOWN)} "
        f"dirty={values.get('AGENT_OS_DIRTY', UNKNOWN)} "
        f"at={values.get('LOADED_AT_UTC', UNKNOWN)}"
    )


def main() -> int:
    values = build_receipt()
    try:
        write_receipt(values)
    except Exception:
        # The printed receipt still carries truthful values even if the local
        # convenience file cannot be written. Never invent success.
        pass
    print(format_startup_line(values))
    return 0 if values["AGENT_OS_LOADED_BLOB_SHA"] != UNKNOWN else 1


if __name__ == "__main__":
    sys.exit(main())
