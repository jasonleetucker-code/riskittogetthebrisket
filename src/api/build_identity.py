"""Which commit this server process is running -- the one owner of that answer.

Production deploys by checking out the target commit and restarting the
service (``deploy/deploy.sh``), so the repository's ``HEAD`` when this module is
imported is the code the process loaded. It is read once, at import, and never
again: a later checkout on disk that was not followed by a restart must not
change what this process claims to be running.

``HEAD`` is read from the ``.git`` files directly rather than by running git, so
the answer does not depend on git being installed, on ``safe.directory``
ownership checks, or on the ``.git/objects`` permission problems the deploy
script documents. Only a full 40-character SHA is ever reported. Anything else --
no repository, an unreadable file, a symbolic ref that does not resolve -- is
``commit: None`` with a reason: unknown is not a commit.

The commit of a public repository is not private, which is why ``/api/status``
(public) may carry it. Deploy verification compares it with the commit the
workflow meant to ship (``.github/workflows/deploy.yml``, post-deploy smoke test).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_REF_NAME = re.compile(r"refs/[A-Za-z0-9._/-]+")
_MAX_READ_BYTES = 4096
_MAX_PACKED_REFS_BYTES = 8 * 1024 * 1024


def _read(path: Path, limit: int = _MAX_READ_BYTES) -> str | None:
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _git_dir(repo_root: Path) -> Path | None:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git
    text = _read(dot_git)  # a worktree or submodule: "gitdir: <path>"
    if text and text.startswith("gitdir:"):
        target = Path(text[len("gitdir:") :].strip())
        target = target if target.is_absolute() else (repo_root / target)
        return target if target.is_dir() else None
    return None


def _resolve_ref(git_dir: Path, ref: str) -> str | None:
    # Loose refs live in the common dir for a linked worktree.
    common = _read(git_dir / "commondir")
    dirs = [git_dir]
    if common:
        common_dir = Path(common.strip())
        dirs.append(common_dir if common_dir.is_absolute() else git_dir / common_dir)
    for base in dirs:
        loose = _read(base / ref)
        if loose is not None:
            value = loose.strip()
            return value if _FULL_SHA.fullmatch(value) else None
    for base in dirs:
        packed = _read(base / "packed-refs", _MAX_PACKED_REFS_BYTES)
        for line in (packed or "").splitlines():
            parts = line.split(" ")
            if len(parts) == 2 and parts[1] == ref and _FULL_SHA.fullmatch(parts[0]):
                return parts[0]
    return None


def resolve_build_identity(repo_root: Path) -> dict:
    """``{"commit", "commit_source", "unavailable_reason"}`` for ``repo_root``."""
    git_dir = _git_dir(Path(repo_root))
    if git_dir is None:
        return {"commit": None, "commit_source": None, "unavailable_reason": "no_repository"}
    head = _read(git_dir / "HEAD")
    if head is None:
        return {"commit": None, "commit_source": None, "unavailable_reason": "head_unreadable"}
    head = head.strip()
    if _FULL_SHA.fullmatch(head):
        return {"commit": head, "commit_source": "detached_head", "unavailable_reason": None}
    if head.startswith("ref: ") and _REF_NAME.fullmatch(head[5:]) and ".." not in head:
        commit = _resolve_ref(git_dir, head[5:])
        if commit:
            return {"commit": commit, "commit_source": head[5:], "unavailable_reason": None}
        return {"commit": None, "commit_source": None, "unavailable_reason": "ref_unresolved"}
    return {"commit": None, "commit_source": None, "unavailable_reason": "head_unrecognized"}


# Captured once per process, at import -- see the module docstring.
PROCESS_BUILD = {
    **resolve_build_identity(Path(__file__).resolve().parents[2]),
    "process_started_at": datetime.now(timezone.utc).isoformat(),
}
