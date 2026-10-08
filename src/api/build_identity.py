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


# --- Frontend tree digest -------------------------------------------------------
#
# Two algorithms, selected by ``identity["frontend_tree_digest_version"]``:
#
# * absent (every manifest produced before this field existed) -- LEGACY: every
#   file under ``.next`` except the top-level ``cache/`` build cache.  Kept byte
#   for byte so a saved manifest in the rollback window still verifies exactly as
#   it did when it was written; an existing field never changes meaning.
# * ``FRONTEND_TREE_DIGEST_VERSION`` -- additionally excludes Next's runtime
#   response cache, ``server/route-cache/``.
#
# Why the second exists (deploy run 37700964086, 2026-10-07): ``next start``
# writes response-cache entries into the served build tree.  Measured on this
# repo's own build (Next 16.3.8): the FIRST request to ANY prerendered route --
# static ones included, not only ``revalidate`` routes -- promotes the build seed
# into ``server/route-cache/<KIND>/<sha256(source route)>/$<path>.{html,rsc,meta,
# body,segments/...}``, and ISR regeneration writes there too.  So a digest of the
# live tree taken after any traffic could never match the CI digest, and the
# deploy's post-start "live frontend matches the tested artifact" check failed on
# a correct deploy.  The compiled seeds under ``server/app/`` are never rewritten.
#
# The exclusion is DERIVED, never a free-form glob, and fails closed:
#   - ``ROUTE_CACHE_DIRECTORY`` is Next's own constant
#     (``next/dist/server/lib/route-cache-key.js``); the Next version is pinned by
#     ``frontend_lock_sha256``.
#   - an excluded file must sit at ``<KIND>/<sha256(source)>/$/...`` where
#     ``source`` is a route the IMMUTABLE build declares -- a key of
#     ``server/app-paths-manifest.json`` (``.../page`` -> APP_PAGE,
#     ``.../route`` -> APP_ROUTE) or ``server/pages-manifest.json`` (PAGES) --
#     and carry a response-cache suffix (or Next's atomic-write temp suffix).
#     Anything else under the directory (a ``.js`` chunk, an unknown route hash,
#     a symlink) refuses verification.
#   - both route manifests are themselves covered by the digest, so the excluded
#     set cannot be widened without changing the identity; a missing or
#     malformed manifest refuses.
#   - the tested artifact must contain NO route cache at all (``create`` refuses),
#     so the exclusion can only ever hide runtime-generated response data, never
#     a byte CI tested.
FRONTEND_TREE_DIGEST_VERSION = "next-build-output-excluding-route-cache/v1"
NEXT_ROUTE_CACHE_DIRECTORY = "route-cache"
_ROUTE_CACHE_RESPONSE_FILE = re.compile(r".+\.(?:html|rsc|meta|body|json)(?:\.tmp\.[0-9a-z]+)?")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _load_route_manifest(build_dir: Path, relative: str) -> dict:
    path = build_dir / relative
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"frontend route manifest missing or unreadable: {relative}") from exc
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and key.startswith("/") for key in loaded
    ):
        raise ValueError(f"frontend route manifest is malformed: {relative}")
    return loaded


def _route_cache_owners(build_dir: Path) -> dict[str, frozenset[str]]:
    """``{kind: {sha256(source route)}}`` declared by the immutable build."""
    owners: dict[str, set[str]] = {"APP_PAGE": set(), "APP_ROUTE": set(), "PAGES": set()}
    for source in _load_route_manifest(build_dir, "server/app-paths-manifest.json"):
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source.endswith("/page"):
            owners["APP_PAGE"].add(digest)
        elif source.endswith("/route"):
            owners["APP_ROUTE"].add(digest)
    for source in _load_route_manifest(build_dir, "server/pages-manifest.json"):
        owners["PAGES"].add(hashlib.sha256(source.encode("utf-8")).hexdigest())
    return {kind: frozenset(values) for kind, values in owners.items()}


def _is_runtime_route_cache_entry(relative: Path, owners: dict[str, frozenset[str]]) -> bool:
    """True for a response-cache file Next writes at runtime; refuse anything odd."""
    parts = relative.parts
    if len(parts) < 2 or parts[0] != "server" or parts[1] != NEXT_ROUTE_CACHE_DIRECTORY:
        return False
    entry = parts[2:]
    if (
        len(entry) < 4
        or entry[0] not in owners
        or not _SHA256_HEX.fullmatch(entry[1])
        or entry[1] not in owners[entry[0]]
        or entry[2] != "$"
        or not _ROUTE_CACHE_RESPONSE_FILE.fullmatch(entry[-1])
    ):
        raise ValueError(
            f"frontend runtime route cache holds an undeclared entry: {relative.as_posix()}"
        )
    return True


def _frontend_tree_digest(build_dir: Path, version: str | None = None) -> str:
    """Content-address the served Next output, excluding its build cache.

    ``version=None`` is the legacy algorithm; see the block comment above.
    """
    if version not in (None, FRONTEND_TREE_DIGEST_VERSION):
        raise ValueError("unsupported frontend tree digest version")
    if not build_dir.is_dir():
        raise ValueError(f"frontend build directory is missing: {build_dir}")
    owners = _route_cache_owners(build_dir) if version is not None else None
    files: list[tuple[str, str]] = []
    for path in sorted(build_dir.rglob("*")):
        relative = path.relative_to(build_dir)
        if relative.parts[0] == "cache":
            continue
        if path.is_symlink():
            raise ValueError(f"frontend artifact contains a symlink: {path}")
        if not path.is_file():
            continue
        if owners is not None and _is_runtime_route_cache_entry(relative, owners):
            continue
        files.append((relative.as_posix(), _sha256_file(path)))
    if not files:
        raise ValueError("frontend artifact is empty")
    payload = json.dumps(files, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_ARTIFACT_ID_KEYS = (
    "commit",
    "python_lock_sha256",
    "frontend_lock_sha256",
    "python_abi",
    "node_version",
    "next_build_id",
    "frontend_tree_sha256",
    "backend_artifact_sha256",
)


def _artifact_id(identity: dict) -> str:
    content = {key: identity[key] for key in _ARTIFACT_ID_KEYS}
    # Bound only when present, so every pre-existing manifest keeps the exact
    # artifact ID it was published under.
    if "frontend_tree_digest_version" in identity:
        content["frontend_tree_digest_version"] = identity["frontend_tree_digest_version"]
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
    backend_archive: Path | None = None,
) -> dict:
    """Describe exact CI build bytes, including an optional backend archive."""
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
    if backend_archive is not None and (
        backend_archive.is_symlink() or not backend_archive.is_file()
    ):
        raise ValueError("backend artifact must be a regular file")
    backend_digest = _sha256_file(backend_archive) if backend_archive is not None else None
    if (build_dir / "server" / NEXT_ROUTE_CACHE_DIRECTORY).exists():
        # The tested artifact must carry no runtime response cache, so the
        # digest's exclusion can never hide a byte CI tested.
        raise ValueError("frontend build already contains a runtime route cache")
    identity = {
        "commit": commit,
        "python_lock_sha256": _sha256_text(repo_root / "requirements.lock.txt"),
        "frontend_lock_sha256": _sha256_text(repo_root / "frontend/package-lock.json"),
        "python_abi": f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}",
        "node_version": node_version.strip(),
        "next_build_id": build_id,
        "frontend_tree_sha256": _frontend_tree_digest(build_dir, FRONTEND_TREE_DIGEST_VERSION),
        "frontend_tree_digest_version": FRONTEND_TREE_DIGEST_VERSION,
        "backend_artifact_sha256": backend_digest,
    }
    manifest = {
        "schema_version": "calculator-release/v2" if backend_digest else "calculator-release/v1",
        "artifact_id": _artifact_id(identity),
        "identity": identity,
        "built_at_utc": built_at_utc or datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": run_id,
    }
    if backend_digest is None:
        manifest["backend_artifact_unavailable_reason"] = "backend_artifact_not_built_in_this_phase"
    return manifest


def verify_release_manifest(
    manifest: dict,
    repo_root: Path,
    build_dir: Path,
    *,
    expected_commit: str,
    backend_archive: Path | None = None,
) -> None:
    """Refuse a stale, substituted or corrupted build before deployment."""
    schema = manifest.get("schema_version")
    if schema not in ("calculator-release/v1", "calculator-release/v2"):
        raise ValueError("unsupported release manifest schema")
    identity = manifest.get("identity")
    if not isinstance(identity, dict) or identity.get("commit") != expected_commit:
        raise ValueError("release artifact Git SHA mismatch")
    if schema == "calculator-release/v1":
        if (
            identity.get("backend_artifact_sha256") is not None
            or manifest.get("backend_artifact_unavailable_reason")
            != "backend_artifact_not_built_in_this_phase"
        ):
            raise ValueError("release artifact backend identity is unsupported in v1")
    else:
        digest = identity.get("backend_artifact_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("release artifact backend digest is invalid")
        artifact = backend_archive or repo_root / "backend-wheelhouse.tar"
        if artifact.is_file() and not artifact.is_symlink():
            if _sha256_file(artifact) != digest:
                raise ValueError("release artifact backend bytes mismatch")
        else:
            receipt = repo_root / ".backend-artifact-receipt.json"
            try:
                installed = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("release artifact backend install receipt missing") from exc
            expected_receipt = {
                "commit": expected_commit,
                "backend_artifact_sha256": digest,
                "python_lock_sha256": identity.get("python_lock_sha256"),
                "python_abi": identity.get("python_abi"),
                "pip_check": "passed",
            }
            if not isinstance(installed, dict):
                raise ValueError("release artifact backend install receipt mismatch")
            wheel_count = installed.get("installed_wheels_verified")
            if (
                set(installed) != set(expected_receipt) | {"installed_wheels_verified"}
                or any(installed.get(key) != value for key, value in expected_receipt.items())
                or type(wheel_count) is not int
                or not 1 <= wheel_count <= 500
            ):
                raise ValueError("release artifact backend install receipt mismatch")
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
    # Absent = a manifest written before the field existed: verify it with the
    # algorithm it was written under.  Any other unknown value refuses.
    digest_version = identity.get("frontend_tree_digest_version")
    if "frontend_tree_digest_version" in identity and digest_version != (
        FRONTEND_TREE_DIGEST_VERSION
    ):
        raise ValueError("release artifact frontend digest version is unsupported")
    if identity.get("frontend_tree_sha256") != _frontend_tree_digest(build_dir, digest_version):
        raise ValueError("release artifact frontend bytes mismatch")
    if manifest.get("artifact_id") != _artifact_id(identity):
        raise ValueError("release artifact identity mismatch")


def resolve_runtime_release_identity(repo_root: Path, *, commit: str | None) -> dict:
    """Snapshot the verified release when the backend process starts."""
    repo_root = Path(repo_root)
    lock = repo_root / "requirements.lock.txt"
    frontend_lock = repo_root / "frontend/package-lock.json"

    def optional_digest(path: Path) -> str | None:
        try:
            return _sha256_text(path)
        except OSError:
            return None

    lock_digest = optional_digest(lock)
    frontend_lock_digest = optional_digest(frontend_lock)
    result = {
        "dependency_lock_sha256": lock_digest,
        "dependency_lock_unavailable_reason": None if lock_digest else "lock_missing_or_unreadable",
        "frontend_lock_sha256": frontend_lock_digest,
        "frontend_lock_unavailable_reason": (
            None if frontend_lock_digest else "frontend_lock_missing_or_unreadable"
        ),
        "python_abi": f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}",
        "ci_python_abi": None,
        "frontend_artifact_id": None,
        "frontend_build_id": None,
        "frontend_tree_sha256": None,
        "frontend_tree_digest_version": None,
        "frontend_artifact_unavailable_reason": "manifest_missing",
        "backend_artifact_sha256": None,
        "backend_artifact_unavailable_reason": "backend_artifact_not_built_in_this_phase",
    }
    manifest_path = repo_root / ".release-manifest.json"
    if not manifest_path.is_file():
        return result
    if not commit:
        result["frontend_artifact_unavailable_reason"] = "commit_unknown"
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_release_manifest(
            manifest, repo_root, repo_root / "frontend/.next", expected_commit=commit
        )
    except (OSError, ValueError, TypeError, KeyError):
        result["frontend_artifact_unavailable_reason"] = "manifest_invalid_or_mismatch"
        return result
    identity = manifest["identity"]
    result.update(
        ci_python_abi=identity["python_abi"],
        frontend_artifact_id=manifest["artifact_id"],
        frontend_build_id=identity["next_build_id"],
        frontend_tree_sha256=identity["frontend_tree_sha256"],
        frontend_tree_digest_version=identity.get("frontend_tree_digest_version", "legacy"),
        frontend_artifact_unavailable_reason=None,
        backend_artifact_sha256=identity["backend_artifact_sha256"],
        backend_artifact_unavailable_reason=(
            None
            if identity["backend_artifact_sha256"]
            else "backend_artifact_not_built_in_this_phase"
        ),
    )
    return result


# Captured once per process, at import -- see the module docstring.
PROCESS_BUILD = {
    **resolve_build_identity(Path(__file__).resolve().parents[2]),
    "process_started_at": datetime.now(timezone.utc).isoformat(),
}
PROCESS_RELEASE = resolve_runtime_release_identity(
    Path(__file__).resolve().parents[2], commit=PROCESS_BUILD["commit"]
)
