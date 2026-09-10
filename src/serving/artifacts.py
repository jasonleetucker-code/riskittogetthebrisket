"""Private, immutable serving generations with an atomic current pointer.

This module owns files and publication only. Producers provide domain validation;
it imports no scraper, API server or valuation code. Readers capture one verified
``Generation`` and keep it for their entire request. They may memoize reads using
``current_version``; no large-file parsing is needed while that token is unchanged.

``modelVersion``, ``inputGenerations`` and ``configHash`` are required metadata.
Additional JSON metadata participates in identity, except ``generatedAt`` and
``sourceAsOf``. A successful unchanged revalidation updates source timestamps in
the current pointer without rewriting or recomputing an immutable generation.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

SCHEMA_VERSION = 1
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_RESERVED = {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
_VOLATILE = {"generatedAt", "sourceAsOf", "observedAt"}
_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class ArtifactError(Exception):
    """An asset could not be safely read or published."""


class MissingArtifact(ArtifactError):
    """No current generation has been published for this partition."""


class CorruptArtifact(ArtifactError):
    """A published pointer, manifest or file is missing or inconsistent."""


class UnsupportedSchema(CorruptArtifact):
    """The artifact requires a different reader schema."""


class UnsafeArtifactPath(ArtifactError, ValueError):
    """A name or filesystem link would escape the intended storage path."""


class PublishLockTimeout(ArtifactError, TimeoutError):
    """Another publisher still owns this partition's OS lock."""


class RejectedCandidate(ArtifactError):
    """The producer's validator explicitly rejected a candidate."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Generation:
    asset: str
    key: str
    manifest: Mapping[str, Any]
    files: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", _freeze(self.manifest))
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @property
    def generation_id(self) -> str:
        return str(self.manifest["generationId"])


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not _NAME.fullmatch(value)
        or value.endswith(".")
        or value.split(".", 1)[0].upper() in _DEVICE_NAMES
    ):
        raise UnsafeArtifactPath(f"Invalid artifact path component: {value!r}")
    return value


def _file_name(value: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise UnsafeArtifactPath(f"Invalid artifact filename: {value!r}")
    parts = value.split("/")
    for part in parts:
        _name(part)
    if str(PurePosixPath(value)) != value:
        raise UnsafeArtifactPath(f"Invalid artifact filename: {value!r}")
    return value


def _check_path(path: Path) -> None:
    """Reject existing symlinks/junctions, including configured-root ancestors.

    Store directories are created mode 0700; callers must likewise keep existing
    roots private. The store is not a sandbox against another process with the
    same OS identity replacing ancestors concurrently.
    """
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(part, "is_junction", lambda: False)():
            raise UnsafeArtifactPath(f"Artifact paths may not contain filesystem links: {part}")


def _mkdir(path: Path) -> None:
    _check_path(path)
    # Path.mkdir(parents=True) applies mode only to the final directory.
    # Make every newly created ancestor private as well.
    for part in (*reversed(path.parents), path):
        if not part.exists():
            part.mkdir(mode=0o700, exist_ok=True)
    _check_path(path)


def _write_new(path: Path, body: bytes) -> None:
    _check_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    # Windows does not expose directory fsync through the stdlib. File fsync
    # and same-volume os.replace still provide complete old-or-new reads.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@contextmanager
def _publish_lock(path: Path, timeout: float) -> Iterator[None]:
    """OS-owned locks release on process exit; the lock file is never deleted."""
    deadline = time.monotonic() + timeout
    with _THREAD_LOCKS_GUARD:
        local_lock = _THREAD_LOCKS.setdefault(os.path.normcase(str(path)), threading.Lock())
    if not local_lock.acquire(timeout=max(0.0, timeout)):
        raise PublishLockTimeout(str(path))
    descriptor = None
    locked = False
    try:
        _check_path(path)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise UnsafeArtifactPath(f"Publisher lock must be a regular file: {path}")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise PublishLockTimeout(str(path)) from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if descriptor is not None:
            try:
                if locked:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        local_lock.release()


def _identity(manifest: Mapping[str, Any]) -> str:
    return _digest(
        _json_bytes(
            {
                key: value
                for key, value in manifest.items()
                if key not in _VOLATILE | {"generationId"}
            }
        )
    )


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    _check_path(path)
    try:
        body = path.read_bytes()
        value = json.loads(body)
    except (OSError, ValueError) as exc:
        raise CorruptArtifact(f"Cannot read artifact JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CorruptArtifact(f"Artifact JSON must be an object: {path}")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise UnsupportedSchema(f"Unsupported artifact schema: {value.get('schemaVersion')!r}")
    return value, body


class ArtifactStore:
    def __init__(self, root: str | Path | None = None, *, lock_timeout: float = 30.0):
        configured = (
            root if root is not None else os.getenv("RISKIT_SERVING_DIR", "data/private_serving")
        )
        self.root = Path(configured).absolute()
        _check_path(self.root)
        if lock_timeout < 0:
            raise ValueError("lock_timeout must be nonnegative")
        self.lock_timeout = lock_timeout

    def _partition(self, asset: str, key: str) -> Path:
        path = self.root / _name(asset) / _name(key)
        _check_path(path)
        return path

    def current_version(self, asset: str, key: str) -> tuple[int, int]:
        """Cheap cache token; changes include unchanged-data freshness updates."""
        pointer = self._partition(asset, key) / "current.json"
        _check_path(pointer)
        try:
            info = pointer.stat()
        except FileNotFoundError as exc:
            raise MissingArtifact(f"No published artifact: {asset}/{key}") from exc
        return info.st_mtime_ns, info.st_size

    def _read_generation(
        self, asset: str, key: str, generation_id: str, *, manifest_hash: str | None = None
    ) -> Generation:
        if not isinstance(generation_id, str) or not _DIGEST.fullmatch(generation_id):
            raise CorruptArtifact("Invalid generation identity")
        directory = self._partition(asset, key) / "generations" / generation_id
        manifest, body = _read_json(directory / "manifest.json")
        if manifest_hash is not None and _digest(body) != manifest_hash:
            raise CorruptArtifact("Manifest checksum mismatch")
        if (
            manifest.get("asset") != asset
            or manifest.get("key") != key
            or manifest.get("generationId") != generation_id
            or _identity(manifest) != generation_id
        ):
            raise CorruptArtifact("Manifest identity mismatch")
        entries = manifest.get("files")
        if not isinstance(entries, dict) or not entries:
            raise CorruptArtifact("Manifest has no files")
        files = {}
        for name, description in entries.items():
            _file_name(name)
            if (
                not isinstance(description, dict)
                or type(description.get("size")) is not int
                or description["size"] < 0
                or not isinstance(description.get("sha256"), str)
                or not _DIGEST.fullmatch(description["sha256"])
            ):
                raise CorruptArtifact(f"Invalid file description: {name}")
            path = directory / "files" / name
            _check_path(path)
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise CorruptArtifact(f"Cannot read artifact file: {name}") from exc
            if len(content) != description["size"] or _digest(content) != description["sha256"]:
                raise CorruptArtifact(f"File checksum mismatch: {name}")
            files[name] = content
        return Generation(asset, key, manifest, files)

    def read_current(self, asset: str, key: str) -> Generation:
        pointer = self._partition(asset, key) / "current.json"
        _check_path(pointer)
        if not pointer.exists():
            raise MissingArtifact(f"No published artifact: {asset}/{key}")
        current, _ = _read_json(pointer)
        manifest_hash = current.get("manifestSha256")
        if not isinstance(manifest_hash, str) or not _DIGEST.fullmatch(manifest_hash):
            raise CorruptArtifact("Invalid current manifest checksum")
        result = self._read_generation(
            asset, key, current.get("generationId"), manifest_hash=manifest_hash
        )
        manifest = dict(result.manifest)
        manifest["sourceAsOf"] = current.get("sourceAsOf")
        manifest["observedAt"] = current.get("observedAt")
        return Generation(asset, key, manifest, result.files)

    def publish(
        self,
        asset: str,
        key: str,
        files: Mapping[str, bytes],
        metadata: Mapping[str, Any],
        validator: Callable[[Generation], Any] | None = None,
    ) -> Generation:
        """Validate and atomically select a complete generation.

        Validator exceptions propagate unchanged; returning False explicitly
        rejects the candidate. Either outcome leaves current.json untouched.
        Re-publishing an existing identity verifies its stored checksums first.
        """
        partition = self._partition(asset, key)
        contents = dict(files)
        if not contents:
            raise ValueError("At least one artifact file is required")
        casefolded: set[str] = set()
        for name, body in contents.items():
            _file_name(name)
            if not isinstance(body, bytes):
                raise TypeError(f"Artifact files must be bytes: {name}")
            if name.casefold() in casefolded:
                raise UnsafeArtifactPath(
                    "Artifact filenames collide on case-insensitive filesystems"
                )
            casefolded.add(name.casefold())
        meta = json.loads(_json_bytes(dict(metadata)))
        if _RESERVED.intersection(meta):
            raise ValueError(f"Reserved metadata keys: {sorted(_RESERVED.intersection(meta))}")
        if not isinstance(meta.get("modelVersion"), str) or not meta["modelVersion"]:
            raise ValueError("modelVersion must be a nonempty string")
        if not isinstance(meta.get("configHash"), str) or not meta["configHash"]:
            raise ValueError("configHash must be a nonempty string")
        if not isinstance(meta.get("inputGenerations"), dict) or any(
            not isinstance(value, str) or not value for value in meta["inputGenerations"].values()
        ):
            raise ValueError("inputGenerations must map input names to nonempty version strings")
        manifest = {
            **meta,
            "schemaVersion": SCHEMA_VERSION,
            "asset": asset,
            "key": key,
            "generatedAt": meta.get("generatedAt") or _now(),
            "sourceAsOf": meta.get("sourceAsOf"),
            "files": {
                name: {"sha256": _digest(body), "size": len(body)}
                for name, body in sorted(contents.items())
            },
        }
        manifest["generationId"] = _identity(manifest)
        candidate = Generation(asset, key, manifest, contents)
        _mkdir(partition)
        with _publish_lock(partition / "publisher.lock", self.lock_timeout):
            if validator is not None and validator(candidate) is False:
                raise RejectedCandidate(f"Validation rejected {asset}/{key}")
            generations = partition / "generations"
            _mkdir(generations)
            target = generations / candidate.generation_id
            _check_path(target)
            if target.exists():
                # Never repair/overwrite an immutable generation silently.
                pointer_path = partition / "current.json"
                _check_path(pointer_path)
                if pointer_path.exists():
                    active_pointer, _ = _read_json(pointer_path)
                else:
                    active_pointer = {}
                candidate = (
                    self.read_current(asset, key)
                    if active_pointer.get("generationId") == candidate.generation_id
                    else self._read_generation(asset, key, candidate.generation_id)
                )
                manifest_body = (target / "manifest.json").read_bytes()
            else:
                temporary = generations / f".tmp-{uuid.uuid4().hex}"
                _mkdir(temporary)
                try:
                    for name, body in contents.items():
                        destination = temporary / "files" / name
                        _mkdir(destination.parent)
                        _write_new(destination, body)
                        _sync_directory(destination.parent)
                    manifest_body = _json_bytes(manifest)
                    _write_new(temporary / "manifest.json", manifest_body)
                    _sync_directory(temporary)
                    os.replace(temporary, target)
                    _sync_directory(generations)
                finally:
                    # Only this uniquely named candidate directory is ours.
                    if temporary.exists():
                        _check_path(temporary)
                        shutil.rmtree(temporary)
            pointer = {
                "schemaVersion": SCHEMA_VERSION,
                "generationId": candidate.generation_id,
                "manifestSha256": _digest(manifest_body),
                "sourceAsOf": meta.get("sourceAsOf"),
                "observedAt": _now(),
            }
            pending = partition / f".current-{uuid.uuid4().hex}.tmp"
            try:
                _write_new(pending, _json_bytes(pointer))
                _check_path(partition / "current.json")
                # Windows readers/virus scanners can momentarily deny rename
                # of an open pointer. Retry the atomic replacement only; never
                # unlink the accepted pointer or expose a partial document.
                for attempt in range(8):
                    try:
                        os.replace(pending, partition / "current.json")
                        break
                    except PermissionError as exc:
                        if (
                            os.name != "nt"
                            or getattr(exc, "winerror", None) not in {5, 32}
                            or attempt == 7
                        ):
                            raise
                        time.sleep(0.01 * (attempt + 1))
                _sync_directory(partition)
            finally:
                pending.unlink(missing_ok=True)
            exposed = dict(candidate.manifest)
            exposed.update(sourceAsOf=pointer["sourceAsOf"], observedAt=pointer["observedAt"])
            return Generation(asset, key, exposed, candidate.files)
