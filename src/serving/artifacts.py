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
import math
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
_ROOT_OWNED_FILES = {
    "store.lock",
    "producer.lock",
    "league-producer.lock",
    "source-request.lock",
    "league-request.lock",
    "retention-pins.json",
    "retention-report.json",
    "source-producer-status.json",
    "source-producer-receipt.json",
    "source-refresh.request",
    "source-refresh-claim.json",
    "league-refresh.request",
    "league-refresh-claim.json",
}


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


class RetentionCapacityError(ArtifactError):
    """Protected generations or the filesystem reserve prevent publication."""


@dataclass(frozen=True)
class RetentionPolicy:
    keep_seconds: float = 48 * 3600
    min_generations: int = 3
    max_bytes: int | None = None
    min_free_bytes: int | None = None

    def __post_init__(self):
        if not math.isfinite(self.keep_seconds) or self.keep_seconds < 0:
            raise ValueError("keep_seconds must be finite and nonnegative")
        if type(self.min_generations) is not int or self.min_generations < 3:
            raise ValueError("at least three accepted generations must be retained")
        for name in ("max_bytes", "min_free_bytes"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer")

    @classmethod
    def from_environment(cls):
        return cls(
            max_bytes=int(os.environ["RISKIT_SERVING_MAX_BYTES"])
            if "RISKIT_SERVING_MAX_BYTES" in os.environ
            else None,
            min_free_bytes=int(os.environ["RISKIT_SERVING_MIN_FREE_BYTES"])
            if "RISKIT_SERVING_MIN_FREE_BYTES" in os.environ
            else None,
        )

    def limits(self, total_bytes):
        budget = (
            self.max_bytes if self.max_bytes is not None else min(4 * 1024**3, total_bytes // 10)
        )
        # Preserve the standalone source producer's existing configured floor.
        reserve = (
            self.min_free_bytes
            if self.min_free_bytes is not None
            else int(os.getenv("DISK_SPACE_MIN_MB", "500")) * 1024**2
        )
        if reserve < 0:
            raise ValueError("filesystem reserve must be nonnegative")
        return budget, reserve


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
    observation: Mapping[str, Any] | None = None
    manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", _freeze(self.manifest))
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        object.__setattr__(self, "observation", _freeze(self.observation))

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


def _mkdir(path: Path, *, mode=0o700, gid=None) -> None:
    _check_path(path)
    # Path.mkdir(parents=True) applies mode only to the final directory.
    # Make every newly created ancestor private as well.
    for part in (*reversed(path.parents), path):
        if not part.exists():
            part.mkdir(mode=0o700, exist_ok=True)
            if part == path and gid is not None:
                os.chown(part, -1, gid)
                os.chmod(part, mode)
    _check_path(path)


def _write_new(path: Path, body: bytes, *, mode=0o600, gid=None) -> None:
    _check_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        if gid is not None:
            os.fchown(handle.fileno(), -1, gid)
            os.fchmod(handle.fileno(), mode)
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
        for attempt in range(8):
            try:
                body = path.read_bytes()
                break
            except PermissionError as exc:
                # Opening a just-replaced Windows pointer can briefly fail
                # alongside the atomic rename. Immutable generations do not
                # need this retry, and persistent permission errors still fail.
                if (
                    os.name != "nt"
                    or path.name != "current.json"
                    or getattr(exc, "winerror", None) not in {None, 5, 32}
                    or attempt == 7
                ):
                    raise
                time.sleep(0.01 * (attempt + 1))
        value = json.loads(body)
    except (OSError, ValueError) as exc:
        raise CorruptArtifact(f"Cannot read artifact JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CorruptArtifact(f"Artifact JSON must be an object: {path}")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise UnsupportedSchema(f"Unsupported artifact schema: {value.get('schemaVersion')!r}")
    return value, body


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _optional_json(path, default):
    _check_path(path)
    if not path.exists():
        return default
    if path.stat().st_size > 2 * 1024**2:
        raise CorruptArtifact("Operational artifact metadata exceeds bound")
    return _read_json(path)[0]


def _replace_json(path, value, *, mode=0o600, gid=None):
    pending = path.parent / f".{path.name}-{uuid.uuid4().hex}.tmp"
    try:
        _write_new(pending, _json_bytes(value), mode=mode, gid=gid)
        _check_path(path)
        os.replace(pending, path)
        _sync_directory(path.parent)
    finally:
        pending.unlink(missing_ok=True)


def _tree_files(root):
    """Walk without following links; reject devices and any linked descendant."""
    _check_path(root)
    if not root.exists():
        return {}
    result = {}
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            _check_path(Path(parent) / name)
        for name in files:
            path = Path(parent) / name
            _check_path(path)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise UnsafeArtifactPath("Artifact tree contains a nonregular file")
            result[path.relative_to(root).as_posix()] = info.st_size
    return result


def _tree_bytes(root):
    return sum(_tree_files(root).values())


def _stamp(value):
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("unqualified time")
        return instant.timestamp()
    except (AttributeError, TypeError, ValueError) as exc:
        raise CorruptArtifact("Invalid artifact acceptance timestamp") from exc


def _reference(value):
    if not isinstance(value, Mapping):
        raise CorruptArtifact("Invalid artifact dependency")
    asset, key, generation = value.get("asset"), value.get("key"), value.get("generationId")
    _name(asset)
    _name(key)
    if not isinstance(generation, str) or not _DIGEST.fullmatch(generation):
        raise CorruptArtifact("Invalid artifact dependency identity")
    return asset, key, generation


class ArtifactStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        lock_timeout: float = 30.0,
        retention_policy: RetentionPolicy | None = None,
        reader_gid: int | None = None,
    ):
        configured = (
            root if root is not None else os.getenv("RISKIT_SERVING_DIR", "data/private_serving")
        )
        self.root = Path(configured).absolute()
        _check_path(self.root)
        if lock_timeout < 0:
            raise ValueError("lock_timeout must be nonnegative")
        self.lock_timeout = lock_timeout
        self.retention_policy = retention_policy or RetentionPolicy.from_environment()
        configured_gid = os.getenv("RISKIT_SERVING_READER_GID")
        if reader_gid is None and configured_gid is not None:
            if not configured_gid.isdecimal():
                raise ValueError("RISKIT_SERVING_READER_GID must be a numeric group id")
            reader_gid = int(configured_gid)
        if reader_gid is not None and (
            type(reader_gid) is not int or reader_gid < 0 or os.name != "posix"
        ):
            raise ValueError("Reader group access requires a nonnegative POSIX group id")
        self.reader_gid = reader_gid

    def _directory(self, path):
        # Ancestors inside the store need traversal too; never chmod existing
        # paths or ancestors outside this explicitly provisioned root.
        if self.reader_gid is None:
            _mkdir(path)
            return
        relative = path.relative_to(self.root)
        current = self.root
        self._check_group_path(current, directory=True)
        for part in relative.parts:
            current /= part
            _mkdir(current, mode=0o2750, gid=self.reader_gid)
            self._check_group_path(current, directory=True)

    def write_new(self, path, body, *, queue=False):
        _write_new(path, body, mode=0o660 if queue else 0o640, gid=self.reader_gid)

    def _replace_json(self, path, value):
        _replace_json(path, value, mode=0o640, gid=self.reader_gid)

    def provision_access(self):
        """Explicit producer/provisioner operation; never migrate existing ACLs.

        Existing private stores require a reviewed offline migration. This
        method only creates missing layout and refuses incompatible permissions.
        """
        if self.reader_gid is None:
            _mkdir(self.root)
            return
        _mkdir(self.root, mode=0o2750, gid=self.reader_gid)
        self._check_group_path(self.root, directory=True)
        queue = self.root / "requests"
        _mkdir(queue, mode=0o2770, gid=self.reader_gid)
        self._check_group_path(queue, directory=True, writable=True)
        for name in ("store.lock", "source-request.lock", "league-request.lock"):
            path = self.root / name
            if not path.exists():
                _write_new(path, b"\0", mode=0o660, gid=self.reader_gid)
            self._check_group_path(path, writable=True)

    def _check_group_path(self, path, *, directory=False, writable=False):
        _check_path(path)
        info = path.stat()
        kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        expected = (0o2750 if directory else 0o640) | (0o020 if writable else 0)
        if not kind_ok or info.st_gid != self.reader_gid or stat.S_IMODE(info.st_mode) != expected:
            raise UnsafeArtifactPath("Incompatible provisioned serving permissions")

    @property
    def request_root(self):
        if self.reader_gid is None:
            return self.root
        self._check_group_path(self.root, directory=True)
        queue = self.root / "requests"
        self._check_group_path(queue, directory=True, writable=True)
        # Switching layouts must not abandon pre-existing queued obligations.
        for name in ("source-refresh.request", "league-refresh.request"):
            if (self.root / name).exists():
                raise UnsafeArtifactPath("Legacy request requires offline queue migration")
        return queue

    def request_lock(self, kind):
        if kind not in {"source", "league"}:
            raise ValueError("Unknown request owner")
        path = self.root / f"{kind}-request.lock"
        if self.reader_gid is not None:
            self._check_group_path(path, writable=True)
        return _publish_lock(path, 2)

    @contextmanager
    def _locked(self):
        # Lock order is root store -> partition publisher. Coordinator/source
        # locks are held by callers; retention never acquires those locks.
        if self.reader_gid is None:
            _mkdir(self.root)
        else:
            self._check_group_path(self.root, directory=True)
            self._check_group_path(self.root / "store.lock", writable=True)
        with _publish_lock(self.root / "store.lock", self.lock_timeout):
            yield

    def _partition(self, asset: str, key: str) -> Path:
        if self.reader_gid is not None and asset == "requests":
            raise UnsafeArtifactPath("Operational queue name is reserved")
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
        return Generation(asset, key, manifest, files, manifest_sha256=_digest(body))

    def read_current(self, asset: str, key: str) -> Generation:
        with self._locked():
            return self._read_current_unlocked(asset, key)

    def _read_current_unlocked(self, asset: str, key: str) -> Generation:
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
        exposed = Generation(
            asset, key, manifest, result.files, current.get("observation"), result.manifest_sha256
        )
        from src.serving import attestation

        if attestation.enabled() and (
            asset in attestation.ATTESTED_ASSETS or attestation.CERTIFICATE_FILE in result.files
        ):
            attestation.validate_key_locations(self)
            attestation.verify_observation(exposed)
        return exposed

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
        candidate, meta = self._candidate(asset, key, files, metadata)
        from src.serving import attestation

        sign_observation = None
        if attestation.enabled() and (
            asset in attestation.ATTESTED_ASSETS or attestation.CERTIFICATE_FILE in candidate.files
        ):
            attestation.verify_artifact(candidate, require_observation=False)
            sign_observation = attestation.observation_signer(
                self, source_as_of=meta.get("sourceAsOf")
            )
        # Domain validation may read other accepted assets. It operates only on
        # the immutable candidate, before acquisition of the nonrecursive lease.
        if validator is not None and validator(candidate) is False:
            raise RejectedCandidate(f"Validation rejected {asset}/{key}")
        with self._locked():
            report = self._retention_unlocked(apply=True, candidate=candidate)
            if report["candidateDependencyBlocked"]:
                self._save_retention_report(report)
                raise RejectedCandidate("Candidate artifact dependencies could not be verified")
            if report["capacityBlocked"]:
                self._save_retention_report(report, failure=True)
                raise RetentionCapacityError(
                    "Protected artifacts or free-space reserve prevent publication"
                )
            result = self._publish_unlocked(candidate, meta, sign_observation=sign_observation)
            try:
                report["bytesAfter"] = self._owned_bytes()
                if report["generationCount"] is not None:
                    report["generationCount"] += int(report.pop("candidateIsNew", False))
                report["projectedBytes"] = report["bytesAfter"]
                self._save_retention_report(report)
            except OSError:
                # A diagnostic write cannot turn an accepted publication into
                # a reported candidate failure. Next maintenance retries it.
                pass
            return result

    def _candidate(self, asset, key, files, metadata):
        self._partition(asset, key)
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
        candidate = Generation(
            asset, key, manifest, contents, manifest_sha256=_digest(_json_bytes(manifest))
        )
        return candidate, meta

    def _publish_unlocked(self, candidate, meta, *, sign_observation=None):
        asset, key = candidate.asset, candidate.key
        partition = self._partition(asset, key)
        contents = candidate.files
        manifest = _plain(candidate.manifest)
        self._directory(partition)
        with _publish_lock(partition / "publisher.lock", self.lock_timeout):
            generations = partition / "generations"
            self._directory(generations)
            target = generations / candidate.generation_id
            _check_path(target)
            pointer_path = partition / "current.json"
            try:
                active_pointer = _optional_json(pointer_path, {})
            except CorruptArtifact:
                active_pointer = {}
            if target.exists():
                # Never repair/overwrite an immutable generation silently.
                # A freshly verified producer may replace a corrupt signed
                # observation; verify immutable content without trusting the
                # old freshness pointer it is authorized to replace.
                candidate = (
                    self._read_current_unlocked(asset, key)
                    if sign_observation is None
                    and active_pointer.get("generationId") == candidate.generation_id
                    else self._read_generation(asset, key, candidate.generation_id)
                )
                manifest_body = (target / "manifest.json").read_bytes()
            else:
                temporary = generations / f".tmp-{uuid.uuid4().hex}"
                self._directory(temporary)
                try:
                    for name, body in contents.items():
                        destination = temporary / "files" / name
                        self._directory(destination.parent)
                        self.write_new(destination, body)
                        _sync_directory(destination.parent)
                    manifest_body = _json_bytes(manifest)
                    self.write_new(temporary / "manifest.json", manifest_body)
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
            if sign_observation is not None:
                pointer["observation"] = sign_observation(asset, key, pointer)
            # Validate history before selecting the pointer. Admission is
            # recorded only after successful selection: failed candidates must
            # never displace accepted generations from the three-generation
            # floor. A crash between selection and history leaves an unknown
            # generation, which retention protects conservatively.
            accepted_path = partition / "accepted.json"
            accepted = _optional_json(accepted_path, {"schemaVersion": 1, "generations": {}})
            entries = accepted.get("generations")
            if not isinstance(entries, dict):
                raise CorruptArtifact("Invalid accepted-generation history")
            if active_pointer.get("generationId") != candidate.generation_id:
                entries[candidate.generation_id] = pointer["observedAt"]
            else:
                entries.setdefault(candidate.generation_id, pointer["observedAt"])
            pending = partition / f".current-{uuid.uuid4().hex}.tmp"
            try:
                self.write_new(pending, _json_bytes(pointer))
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
            try:
                self._replace_json(accepted_path, accepted)
            except OSError:
                # The pointer is already accepted. Missing admission evidence
                # makes this generation protected/unknown until reobserved.
                pass
            exposed = dict(candidate.manifest)
            exposed.update(sourceAsOf=pointer["sourceAsOf"], observedAt=pointer["observedAt"])
            return Generation(
                asset,
                key,
                exposed,
                candidate.files,
                pointer.get("observation"),
                _digest(manifest_body),
            )

    def pin(self, asset: str, key: str, generation_id: str, label: str) -> None:
        """Keep an explicitly selected rollback generation until unpinned."""
        _name(label)
        with self._locked():
            self._read_generation(asset, key, generation_id)
            path = self.root / "retention-pins.json"
            state = _optional_json(path, {"schemaVersion": 1, "pins": {}})
            pins = state.get("pins")
            if not isinstance(pins, dict) or len(pins) >= 128 and label not in pins:
                raise CorruptArtifact("Invalid or full retention pin registry")
            pins[label] = {"asset": asset, "key": key, "generationId": generation_id}
            self._replace_json(path, state)

    def unpin(self, label: str) -> None:
        _name(label)
        with self._locked():
            path = self.root / "retention-pins.json"
            state = _optional_json(path, {"schemaVersion": 1, "pins": {}})
            if not isinstance(state.get("pins"), dict):
                raise CorruptArtifact("Invalid retention pin registry")
            state["pins"].pop(label, None)
            self._replace_json(path, state)

    def read_retention_report(self) -> dict:
        """Bounded persisted diagnostics, without scanning any generation."""
        path = self.root / "retention-report.json"
        _check_path(path)
        try:
            with path.open("rb") as stream:
                body = stream.read(65537)
            value = json.loads(body) if len(body) <= 65536 else None
            if not isinstance(value, dict) or value.get("schemaVersion") != 1:
                raise ValueError("invalid report")
            return value
        except FileNotFoundError:
            return {"schemaVersion": 1, "status": "unknown"}
        except (OSError, ValueError):
            return {"schemaVersion": 1, "status": "unknown", "error": "invalid_retention_report"}

    def _save_retention_report(self, report, *, failure=False):
        previous = self.read_retention_report()
        count = previous.get("capacityFailureCount", 0)
        if type(count) is not int or count < 0:
            count = 0
        report.pop("candidateIsNew", None)
        report.update(
            schemaVersion=1,
            observedAt=_now(),
            capacityFailureCount=count + int(failure),
            lastCapacityFailureAt=_now() if failure else previous.get("lastCapacityFailureAt"),
            freeBytes=shutil.disk_usage(self.root).free,
        )
        self._replace_json(self.root / "retention-report.json", report)

    def retention(self, *, apply=False, now=None) -> dict:
        """Plan or prune under the same lease as all reads and publications.

        A dry run performs integrity checks but does not delete or persist a
        report. Returned generations contain owned bytes; their readers remain
        valid after the read lease ends, even if later maintenance removes disk.
        """
        with self._locked():
            report = self._retention_unlocked(apply=apply, now=now)
            report.pop("candidateIsNew", None)
            if apply:
                self._save_retention_report(report, failure=report["capacityBlocked"])
            return report

    def _inspect_generation(self, asset, key, directory, accepted):
        if (directory / "manifest.json").stat().st_size > 16 * 1024**2:
            raise CorruptArtifact("Artifact manifest exceeds retention bound")
        manifest, body = _read_json(directory / "manifest.json")
        ident = (asset, key, directory.name)
        if (
            manifest.get("asset"),
            manifest.get("key"),
            manifest.get("generationId"),
        ) != ident or _identity(manifest) != directory.name:
            raise CorruptArtifact("Retention encountered an invalid generation manifest")
        entries = manifest.get("files")
        if not isinstance(entries, dict) or not entries:
            raise CorruptArtifact("Retention encountered an empty generation")
        actual = _tree_files(directory)
        if set(actual) != {"manifest.json", *("files/" + _file_name(name) for name in entries)}:
            raise CorruptArtifact("Generation tree differs from its manifest")
        extra = {}
        for name, description in entries.items():
            if not isinstance(description, dict) or actual["files/" + name] != description.get(
                "size"
            ):
                raise CorruptArtifact("Generation file size differs from its manifest")
            digest = hashlib.sha256()
            with (directory / "files" / name).open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != description.get("sha256"):
                raise CorruptArtifact("Generation file checksum differs from its manifest")
            if name in {"index.json", "receipt.json"} and asset in {
                "canonical-serving",
                "source-ownership",
            }:
                if actual["files/" + name] > 16 * 1024**2:
                    raise CorruptArtifact("Artifact dependency index exceeds bound")
                document = json.loads((directory / "files" / name).read_bytes())
                if not isinstance(document, dict):
                    raise CorruptArtifact("Invalid artifact dependency document")
                field = "generation" if name == "index.json" else "acceptedGeneration"
                # Keep only the dependency identity in the inventory; do not
                # retain every historical source/health/index payload in RAM.
                extra[name] = _json_bytes({field: document.get(field)})
        # Filesystem mtime and generatedAt are not evidence of acceptance. A
        # legacy generation with no admission record remains protected.
        instant = _stamp(accepted[directory.name]) if directory.name in accepted else None
        return {
            "id": ident,
            "manifest": manifest,
            "files": extra,
            "size": sum(actual.values()),
            "time": instant,
            "path": directory,
            "manifestHash": _digest(body),
        }

    def _owned_partitions(self):
        # The private root can also contain local labs or unrelated caches.
        # Only directories bearing an ArtifactStore partition marker are ours.
        for asset_path in self.root.iterdir():
            _check_path(asset_path)
            if self.reader_gid is not None and asset_path.name == "requests":
                continue
            if (
                asset_path.is_symlink()
                or getattr(asset_path, "is_junction", lambda: False)()
                or not asset_path.is_dir()
            ):
                continue
            for partition in asset_path.iterdir():
                _check_path(partition)
                if (
                    partition.is_symlink()
                    or getattr(partition, "is_junction", lambda: False)()
                    or not partition.is_dir()
                ):
                    continue
                if any(
                    (partition / name).exists()
                    for name in ("current.json", "generations", "accepted.json")
                ):
                    _check_path(partition)
                    yield _name(asset_path.name), _name(partition.name), partition

    def _owned_bytes(self):
        total = sum(_tree_bytes(partition) for _, _, partition in self._owned_partitions())
        if self.reader_gid is not None:
            total += _tree_bytes(self.request_root)
        for name in _ROOT_OWNED_FILES:
            path = self.root / name
            _check_path(path)
            if path.exists():
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    # Queue markers are claimed under their own short lease.
                    pass
        return total

    def _inventory(self, now, *, replacing=None):
        records, current, staging = {}, set(), []
        replacement_history_uncertain = False
        for asset, key, partition in self._owned_partitions():
            accepted = _optional_json(
                partition / "accepted.json", {"schemaVersion": 1, "generations": {}}
            ).get("generations")
            if not isinstance(accepted, dict):
                raise CorruptArtifact("Invalid accepted-generation history")
            for generation, stamp in accepted.items():
                if not _DIGEST.fullmatch(generation):
                    raise CorruptArtifact("Invalid accepted-generation identity")
                _stamp(stamp)
            generations = partition / "generations"
            if generations.exists():
                for directory in generations.iterdir():
                    _check_path(directory)
                    if not directory.is_dir():
                        raise CorruptArtifact("Unexpected file in generations directory")
                    if re.fullmatch(r"\.tmp-[a-f0-9]{32}", directory.name):
                        staging.append(
                            {
                                "path": directory,
                                "size": _tree_bytes(directory),
                                "time": directory.stat().st_mtime,
                            }
                        )
                        continue
                    if not _DIGEST.fullmatch(directory.name):
                        raise CorruptArtifact("Unexpected generation directory")
                    try:
                        record = self._inspect_generation(asset, key, directory, accepted)
                    except (CorruptArtifact, OSError):
                        if (asset, key) != replacing:
                            raise
                        # Preserve a corrupt predecessor, never overwrite it.
                        # Retain its verified manifest identity/aliases so a
                        # dependent candidate cannot resolve around bad bytes.
                        if (directory / "manifest.json").stat().st_size > 16 * 1024**2:
                            raise CorruptArtifact("Artifact manifest exceeds retention bound")
                        manifest, body = _read_json(directory / "manifest.json")
                        ident = (asset, key, directory.name)
                        if (
                            manifest.get("asset"),
                            manifest.get("key"),
                            manifest.get("generationId"),
                        ) != ident or _identity(manifest) != directory.name:
                            raise CorruptArtifact("Invalid replacement history identity")
                        entries = manifest.get("files")
                        if (
                            not isinstance(entries, dict)
                            or not entries
                            or any(
                                not isinstance(entry, dict)
                                or type(entry.get("size")) is not int
                                or entry["size"] < 0
                                or not isinstance(entry.get("sha256"), str)
                                or not _DIGEST.fullmatch(entry["sha256"])
                                for entry in entries.values()
                            )
                        ):
                            raise CorruptArtifact("Invalid replacement history file inventory")
                        for name in entries:
                            _file_name(name)
                        record = {
                            "id": ident,
                            "manifest": manifest,
                            "files": {},
                            "size": _tree_bytes(directory),
                            "time": None,
                            "path": directory,
                            "manifestHash": _digest(body),
                            "unverified": True,
                            "unknownLogicalIdentity": asset == "canonical-serving",
                        }
                        replacement_history_uncertain = True
                    records[record["id"]] = record
                    if len(records) > 10000:
                        raise CorruptArtifact("Retention inventory exceeds generation bound")
            try:
                pointer = _optional_json(partition / "current.json", None)
                if pointer is not None:
                    ident = (asset, key, pointer.get("generationId"))
                    if ident not in records or records[ident]["manifestHash"] != pointer.get(
                        "manifestSha256"
                    ):
                        raise CorruptArtifact(
                            "Current pointer does not identify a verified generation"
                        )
                    current.add(ident)
            except CorruptArtifact:
                if (asset, key) != replacing:
                    raise
                # Only its own pointer is replaceable. Unverified historical
                # bytes remain explicit; uncertainty always forbids pruning.
                replacement_history_uncertain = True
        return records, current, staging, replacement_history_uncertain

    def _dependencies(self, records, *, roots=None):
        physical = {ident[2]: ident for ident in records}
        aliases = {}
        refs = {ident: set() for ident in records}
        for ident, record in records.items():
            if record.get("unknownLogicalIdentity"):
                raise CorruptArtifact("Corrupt canonical history has an unknown logical identity")
            manifest = record["manifest"]
            logical = manifest.get("logicalGeneration")
            if ident[0] == "canonical-serving" and "index.json" in record["files"]:
                index = json.loads(record["files"]["index.json"])
                if not isinstance(index, dict):
                    raise CorruptArtifact("Invalid canonical dependency index")
                logical = index.get("generation")
            if logical:
                if not isinstance(logical, str) or not _DIGEST.fullmatch(logical):
                    raise CorruptArtifact("Invalid logical artifact identity")
                aliases.setdefault(logical, set()).add(ident)
                record["logicalContentHash"] = (
                    manifest.get("files", {}).get("views/full.json") or {}
                ).get("sha256")

        def resolve(version, *, required=False):
            targets = aliases.get(version, set()) | (
                {physical[version]} if version in physical else set()
            )
            if len(targets) > 1 and any(
                records[target].get("logicalContentHash") != version for target in targets
            ):
                raise CorruptArtifact("Ambiguous artifact dependency identity")
            if required and not targets:
                raise CorruptArtifact("Missing protected artifact dependency")
            return targets

        pending = list(records if roots is None else roots)
        visited = set()
        while pending:
            ident = pending.pop()
            if ident in visited:
                continue
            visited.add(ident)
            if records[ident].get("unverified"):
                raise CorruptArtifact("Artifact dependency has unverified immutable bytes")
            manifest = records[ident]["manifest"]
            inputs = manifest.get("inputGenerations")
            if not isinstance(inputs, Mapping):
                raise CorruptArtifact("Invalid artifact input versions")
            for name, version in inputs.items():
                if not isinstance(version, str):
                    raise CorruptArtifact("Invalid artifact input version")
                refs[ident].update(
                    resolve(
                        version,
                        required=name
                        in {"board", "canonicalBoard", "acceptedGeneration", "artifactGeneration"}
                        or (ident[0] == "news-serving" and name == "canonical"),
                    )
                )
            declared = manifest.get("artifactReferences", [])
            if not isinstance(declared, (list, tuple)):
                raise CorruptArtifact("Invalid declared artifact references")
            for item in declared:
                target = _reference(item)
                if target not in records:
                    raise CorruptArtifact("Missing declared artifact reference")
                refs[ident].add(target)
            if ident[0] == "source-ownership":
                receipt = json.loads(records[ident]["files"].get("receipt.json", b"null"))
                if not isinstance(receipt, dict) or not isinstance(
                    receipt.get("acceptedGeneration"), str
                ):
                    raise CorruptArtifact("Invalid ownership proof reference")
                refs[ident].update(resolve(receipt["acceptedGeneration"], required=True))
            if roots is not None:
                pending.extend(refs[ident] - visited)
        if roots is not None:
            return refs, set()
        protected = set()
        pins = _optional_json(
            self.root / "retention-pins.json", {"schemaVersion": 1, "pins": {}}
        ).get("pins")
        if not isinstance(pins, dict) or len(pins) > 128:
            raise CorruptArtifact("Invalid retention pins")
        for value in pins.values():
            target = _reference(value)
            if target not in records:
                raise CorruptArtifact("Pinned generation is missing")
            protected.add(target)
        receipt = _optional_json(self.root / "source-producer-receipt.json", None)
        if receipt is not None:
            version = receipt.get("acceptedGeneration")
            if not isinstance(version, str):
                raise CorruptArtifact("Invalid source receipt reference")
            protected.update(resolve(version, required=True))
        return refs, protected

    def _retention_unlocked(self, *, apply, now=None, candidate=None):
        policy = self.retention_policy
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("retention time must be timezone-qualified")
        timestamp = instant.timestamp()
        usage = shutil.disk_usage(self.root)
        budget, reserve = policy.limits(usage.total)
        before = self._owned_bytes()
        candidate_id = (
            (candidate.asset, candidate.key, candidate.generation_id) if candidate else None
        )
        candidate_new = bool(
            candidate
            and not (
                self._partition(candidate.asset, candidate.key)
                / "generations"
                / candidate.generation_id
            ).exists()
        )
        # Includes manifest, admission/pointer/report replacement and filesystem
        # bookkeeping headroom. Never write a new generation into the reserve.
        pending = (
            sum(map(len, candidate.files.values())) + len(_json_bytes(_plain(candidate.manifest)))
            if candidate_new
            else 0
        ) + (4096 if candidate else 0)
        # Uncertain inventory must not admit a dependent candidate. Standalone
        # repairs may still publish without pruning corrupt unrelated history.
        inputs = candidate.manifest.get("inputGenerations") if candidate else {}
        declared = candidate.manifest.get("artifactReferences", []) if candidate else []
        requires_dependencies = bool(
            candidate
            and (
                not isinstance(inputs, Mapping)
                or any(
                    name in {"board", "canonicalBoard", "acceptedGeneration", "artifactGeneration"}
                    or (candidate.asset == "news-serving" and name == "canonical")
                    for name in inputs
                )
                or not isinstance(declared, (list, tuple))
                or declared
                or candidate.asset == "source-ownership"
            )
        )
        candidate_dependencies_pending = requires_dependencies
        report = {
            "schemaVersion": 1,
            "status": "ok",
            "dryRun": not apply,
            "bytesBefore": before,
            "bytesAfter": before,
            "projectedBytes": before + pending,
            "budgetBytes": budget,
            "minFreeBytes": reserve,
            "freeBytes": usage.free,
            "generationCount": 0,
            "protectedCount": 0,
            "deletedCount": 0,
            "plannedDeleteCount": 0,
            "reclaimedBytes": 0,
            "oldestRetainedAt": None,
            "unknownAcceptanceCount": 0,
            "shortenedRollbackWindow": False,
            "blocked": False,
            "capacityBlocked": False,
            "candidateDependencyBlocked": False,
            "candidateIsNew": candidate_new,
        }
        try:
            records, hard, staging, replacement_history_uncertain = self._inventory(
                timestamp, replacing=candidate_id[:2] if candidate_id else None
            )
            report["generationCount"] = len(records)
            if candidate_new:
                records[candidate_id] = {
                    "id": candidate_id,
                    "manifest": candidate.manifest,
                    "files": candidate.files,
                    "size": pending,
                    "time": timestamp,
                    "path": None,
                }
            if candidate_id:
                hard.add(candidate_id)
                if requires_dependencies:
                    self._dependencies(records, roots=[candidate_id])
                    candidate_dependencies_pending = False
            if replacement_history_uncertain:
                raise CorruptArtifact("Replacement history is uncertain; pruning refused")
            dependencies, pins = self._dependencies(records)
            hard.update(pins)
            partitions = {}
            for ident, record in records.items():
                partitions.setdefault(ident[:2], []).append(record)
                if (
                    ident[0] == "source-ownership"
                    or ident[0].endswith("-proof")
                    or record["manifest"].get("retentionProtected") is True
                ):
                    hard.add(ident)
                if record["time"] is None:
                    hard.add(ident)
                    report["unknownAcceptanceCount"] += 1
            for group in partitions.values():
                existing = [
                    record
                    for record in group
                    if record["path"] is not None and record["time"] is not None
                ]
                hard.update(
                    r["id"]
                    for r in sorted(
                        existing,
                        key=lambda r: (
                            r["time"] if r["time"] is not None else float("inf"),
                            r["id"],
                        ),
                        reverse=True,
                    )[: policy.min_generations]
                )
            pending_refs = list(hard)
            while pending_refs:
                for target in dependencies[pending_refs.pop()]:
                    if target not in hard:
                        hard.add(target)
                        pending_refs.append(target)
            report["protectedCount"] = len(hard)
            remaining = set(records)
            chosen = []
            reclaimed = 0
            while True:
                pressure = (
                    before - reclaimed + pending > budget
                    or usage.free + reclaimed - pending < reserve
                )
                incoming = {
                    ref for ident in remaining for ref in dependencies[ident] if ref != ident
                }
                eligible = [
                    records[ident]
                    for ident in remaining - hard - incoming
                    if pressure or timestamp - records[ident]["time"] > policy.keep_seconds
                ]
                if not eligible:
                    break
                record = min(eligible, key=lambda r: (r["time"], r["id"]))
                chosen.append(record)
                reclaimed += record["size"]
                remaining.remove(record["id"])
            # In-flight temporary directories cannot exist while this lease is
            # held. Old crash leftovers can be deleted after the full window.
            chosen.extend(
                record for record in staging if timestamp - record["time"] > policy.keep_seconds
            )
            reclaimed += sum(r["size"] for r in chosen if "id" not in r)
            report.update(
                plannedDeleteCount=len(chosen),
                reclaimedBytes=reclaimed,
                projectedBytes=before - reclaimed + pending,
            )
            report["capacityBlocked"] = (
                before - reclaimed + pending > budget or usage.free + reclaimed - pending < reserve
            )
            retained_times = [
                records[ident]["time"] for ident in remaining if records[ident]["time"] is not None
            ]
            if retained_times and not report["unknownAcceptanceCount"]:
                report["oldestRetainedAt"] = datetime.fromtimestamp(
                    min(retained_times), timezone.utc
                ).isoformat()
            if apply and not report["capacityBlocked"]:
                # Entire inventory and dependency graph were validated first.
                for record in chosen:
                    directory = record["path"]
                    expected_parent = (
                        self._partition(*record["id"][:2]) / "generations"
                        if "id" in record
                        else directory.parent
                    )
                    if (
                        directory.parent != expected_parent
                        or directory.parent.name != "generations"
                        or not directory.is_relative_to(self.root)
                    ):
                        raise UnsafeArtifactPath(
                            "Retention target escaped its generation partition"
                        )
                    _tree_files(directory)
                    shutil.rmtree(directory)
                    _sync_directory(expected_parent)
                    report["deletedCount"] += 1
                    if "id" in record and timestamp - record["time"] <= policy.keep_seconds:
                        report["shortenedRollbackWindow"] = True
                for (asset, key), group in partitions.items():
                    path = self._partition(asset, key) / "accepted.json"
                    if path.exists():
                        state = _read_json(path)[0]
                        state["generations"] = {
                            generation: stamp
                            for generation, stamp in state["generations"].items()
                            if (asset, key, generation) in remaining
                        }
                        self._replace_json(path, state)
                report["bytesAfter"] = self._owned_bytes()
                report["generationCount"] -= sum("id" in r for r in chosen)
            elif apply:
                report["reclaimedBytes"] = 0
                report["projectedBytes"] = before + pending
        except (ArtifactError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Corrupt/ambiguous evidence authorizes no deletions. A publisher
            # may still repair data if it fits without relying on any pruning.
            report.update(status="blocked", blocked=True, error=type(exc).__name__)
            report["candidateDependencyBlocked"] = candidate_dependencies_pending
            report["generationCount"] = None
            report["projectedBytes"] = self._owned_bytes() + pending
            report["bytesAfter"] = self._owned_bytes()
        freed = before - report["bytesAfter"] if apply else report["reclaimedBytes"]
        report["capacityBlocked"] = (
            report["capacityBlocked"]
            or report["projectedBytes"] > budget
            or usage.free + freed - pending < reserve
        )
        if report["capacityBlocked"]:
            report.update(status="blocked", blocked=True)
        return report
