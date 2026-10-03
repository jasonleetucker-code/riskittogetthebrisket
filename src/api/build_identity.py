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

Not to be confused with script-time provenance such as
``src/model_registry/hill_masters.py``'s ``git rev-parse``: that records which
commit produced an artifact, this records which commit a running server loaded.
"""

from __future__ import annotations

import re
import hashlib
import json
import sys
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(path: Path) -> str:
    """Hash Git-normalized text, independent of Windows checkout line endings."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _frontend_tree_digest(build_dir: Path) -> str:
    """Content-address the served Next output, excluding its build cache."""
    if not build_dir.is_dir():
        raise ValueError(f"frontend build directory is missing: {build_dir}")
    files: list[tuple[str, str]] = []
    for path in sorted(build_dir.rglob("*")):
        relative = path.relative_to(build_dir)
        if relative.parts[0] == "cache":
            continue
        if path.is_symlink():
            raise ValueError(f"frontend artifact contains a symlink: {path}")
        if not path.is_file():
            continue
        files.append((relative.as_posix(), _sha256_file(path)))
    if not files:
        raise ValueError("frontend artifact is empty")
    payload = json.dumps(files, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact_id(identity: dict) -> str:
    content = {
        key: identity[key]
        for key in (
            "commit",
            "python_lock_sha256",
            "frontend_lock_sha256",
            "python_abi",
            "node_version",
            "next_build_id",
            "frontend_tree_sha256",
            "backend_artifact_sha256",
        )
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_release_manifest(
    repo_root: Path,
    build_dir: Path,
    *,
    commit: str,
    node_version: str,
    run_id: str | None = None,
    built_at_utc: str | None = None,
) -> dict:
    """Describe exact CI build bytes; unbuilt backend artifacts stay unknown."""
    if not _FULL_SHA.fullmatch(commit):
        raise ValueError("release manifest requires a full lowercase Git SHA")
    observed_commit = resolve_build_identity(repo_root)["commit"]
    if observed_commit != commit:
        raise ValueError("release manifest Git SHA differs from the checkout")
    build_id_path = build_dir / "BUILD_ID"
    try:
        build_id = build_id_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Next BUILD_ID is missing") from exc
    if not build_id or len(build_id) > 256:
        raise ValueError("Next BUILD_ID is invalid")
    if not node_version.strip():
        raise ValueError("Node version is missing")
    identity = {
        "commit": commit,
        "python_lock_sha256": _sha256_text(repo_root / "requirements.lock.txt"),
        "frontend_lock_sha256": _sha256_text(repo_root / "frontend/package-lock.json"),
        "python_abi": f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}",
        "node_version": node_version.strip(),
        "next_build_id": build_id,
        "frontend_tree_sha256": _frontend_tree_digest(build_dir),
        "backend_artifact_sha256": None,
    }
    return {
        "schema_version": "calculator-release/v1",
        "artifact_id": _artifact_id(identity),
        "identity": identity,
        "backend_artifact_unavailable_reason": "backend_artifact_not_built_in_this_phase",
        "built_at_utc": built_at_utc or datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": run_id,
    }


def verify_release_manifest(
    manifest: dict, repo_root: Path, build_dir: Path, *, expected_commit: str
) -> None:
    """Refuse a stale, substituted or corrupted build before deployment."""
    if manifest.get("schema_version") != "calculator-release/v1":
        raise ValueError("unsupported release manifest schema")
    identity = manifest.get("identity")
    if not isinstance(identity, dict) or identity.get("commit") != expected_commit:
        raise ValueError("release artifact Git SHA mismatch")
    if (
        identity.get("backend_artifact_sha256") is not None
        or manifest.get("backend_artifact_unavailable_reason")
        != "backend_artifact_not_built_in_this_phase"
    ):
        raise ValueError("release artifact backend identity is unsupported in v1")
    if identity.get("python_lock_sha256") != _sha256_text(repo_root / "requirements.lock.txt"):
        raise ValueError("release artifact Python lock mismatch")
    if identity.get("frontend_lock_sha256") != _sha256_text(
        repo_root / "frontend/package-lock.json"
    ):
        raise ValueError("release artifact frontend lock mismatch")
    if (
        identity.get("next_build_id")
        != (build_dir / "BUILD_ID").read_text(encoding="utf-8").strip()
    ):
        raise ValueError("release artifact Next BUILD_ID mismatch")
    if identity.get("frontend_tree_sha256") != _frontend_tree_digest(build_dir):
        raise ValueError("release artifact frontend bytes mismatch")
    if manifest.get("artifact_id") != _artifact_id(identity):
        raise ValueError("release artifact identity mismatch")


# Captured once per process, at import -- see the module docstring.
PROCESS_BUILD = {
    **resolve_build_identity(Path(__file__).resolve().parents[2]),
    "process_started_at": datetime.now(timezone.utc).isoformat(),
}
