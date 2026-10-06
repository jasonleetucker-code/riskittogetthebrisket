"""Verify and install the exact CI backend wheelhouse without a package index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from scripts import backend_wheelhouse
from src.api.build_identity import _artifact_id, resolve_build_identity

_SHA = re.compile(r"[0-9a-f]{64}")
_BACKEND_MEMBERS = {
    "backend-wheelhouse-manifest.json",
    "requirements.lock.txt",
    "requirements-build.lock.txt",
}
_BACKEND_DIRS = {"backend-wheels", "backend-sources"}
_MAX_BACKEND_BYTES = 400 * 1024 * 1024


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_member(bundle: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> None:
    if not member.isfile():
        raise ValueError(f"backend artifact contains a non-file: {member.name}")
    source = bundle.extractfile(member)
    if source is None:
        raise ValueError(f"backend artifact member is unreadable: {member.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output)


def _extract_wheelhouse(archive: Path, destination: Path) -> None:
    total = 0
    seen: set[str] = set()
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        if len(members) > 1000:
            raise ValueError("backend artifact has too many members")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("backend artifact has an unsafe path")
            name = path.as_posix().rstrip("/")
            if name in seen:
                raise ValueError("backend artifact has duplicate paths")
            seen.add(name)
            if name in _BACKEND_DIRS:
                if not member.isdir():
                    raise ValueError("backend artifact directory is invalid")
                (destination / name).mkdir(parents=True, exist_ok=True)
                continue
            if name not in _BACKEND_MEMBERS and (
                len(path.parts) != 2 or path.parts[0] not in _BACKEND_DIRS
            ):
                raise ValueError(f"unexpected backend artifact path: {name}")
            if not member.isfile() or member.size < 0:
                raise ValueError("backend artifact contains a link or special file")
            total += member.size
            if total > _MAX_BACKEND_BYTES:
                raise ValueError("backend artifact exceeds size limit")
            _copy_member(bundle, member, destination / name)
    if not _BACKEND_MEMBERS.issubset(seen) or not _BACKEND_DIRS.issubset(seen):
        raise ValueError("backend artifact is missing required members")


def install(
    *,
    release_archive: Path,
    archive_sha256: str,
    checkout: Path,
    commit: str,
    venv_python: Path,
    receipt: Path,
) -> str:
    """Verify both archive layers and the lock before changing the runtime."""
    if (
        not _SHA.fullmatch(archive_sha256)
        or release_archive.is_symlink()
        or not release_archive.is_file()
        or _digest(release_archive) != archive_sha256
    ):
        raise ValueError("release archive SHA-256 mismatch")
    if resolve_build_identity(checkout)["commit"] != commit:
        raise ValueError("release checkout Git SHA mismatch")
    if not venv_python.is_file() or not os.access(venv_python, os.X_OK):
        raise ValueError("runtime Python is unavailable")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    minimum_free = max(2 * 1024**3, 4 * release_archive.stat().st_size)
    if shutil.disk_usage(receipt.parent).free < minimum_free:
        raise ValueError("insufficient free space for backend artifact staging and rollback")
    with tempfile.TemporaryDirectory(prefix=".backend-stage-", dir=receipt.parent) as temp:
        stage = Path(temp)
        with tarfile.open(release_archive, "r:") as bundle:
            members = bundle.getmembers()
            names = [member.name for member in members]
            if len(members) > 50000 or len(names) != len(set(names)):
                raise ValueError("release archive has duplicate or excessive members")
            for name in ("release-manifest.json", "backend-wheelhouse.tar"):
                if name not in names:
                    raise ValueError(f"release archive missing {name}")
                member = bundle.getmember(name)
                if not member.isfile():
                    raise ValueError(f"release archive has an unsafe {name}")
                if name == "backend-wheelhouse.tar" and member.size > _MAX_BACKEND_BYTES:
                    raise ValueError("backend wheelhouse is too large")
                _copy_member(bundle, member, stage / name)
        manifest = json.loads((stage / "release-manifest.json").read_text(encoding="utf-8"))
        identity = manifest.get("identity")
        if (
            manifest.get("schema_version") != "calculator-release/v2"
            or not isinstance(identity, dict)
            or identity.get("commit") != commit
            or manifest.get("artifact_id") != _artifact_id(identity)
        ):
            raise ValueError("release backend manifest identity mismatch")
        backend_sha = identity.get("backend_artifact_sha256")
        if not isinstance(backend_sha, str) or not _SHA.fullmatch(backend_sha):
            raise ValueError("release backend digest is invalid")
        if _digest(stage / "backend-wheelhouse.tar") != backend_sha:
            raise ValueError("release backend artifact digest mismatch")
        if backend_wheelhouse._lock_sha256(checkout / "requirements.lock.txt") != identity.get(
            "python_lock_sha256"
        ):
            raise ValueError("backend artifact checkout lock mismatch")
        if (
            identity.get("python_abi")
            != subprocess.check_output(
                [
                    str(venv_python),
                    "-c",
                    "import sys; print(f'{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}')",
                ],
                text=True,
            ).strip()
        ):
            raise ValueError("backend artifact Python ABI mismatch")
        _extract_wheelhouse(stage / "backend-wheelhouse.tar", stage / "wheelhouse")
        artifact = stage / "wheelhouse"
        if (
            backend_wheelhouse._lock_sha256(artifact / "requirements.lock.txt")
            != identity["python_lock_sha256"]
        ):
            raise ValueError("backend artifact embedded lock mismatch")
        if backend_wheelhouse._lock_sha256(
            artifact / "requirements-build.lock.txt"
        ) != backend_wheelhouse._lock_sha256(checkout / "requirements-build.lock.txt"):
            raise ValueError("backend artifact build lock mismatch")
        wheels_manifest = json.loads(
            (artifact / "backend-wheelhouse-manifest.json").read_text(encoding="utf-8")
        )
        requirements = backend_wheelhouse.install_requirements(
            wheels_manifest,
            artifact / "backend-wheels",
            artifact / "requirements.lock.txt",
            artifact / "requirements-build.lock.txt",
            artifact / "backend-sources",
        )
        install_file = artifact / "backend-install.requirements.txt"
        install_file.write_text(requirements, encoding="utf-8")
        subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--require-hashes",
                "--force-reinstall",
                "-r",
                str(install_file),
            ],
            check=True,
            env={**os.environ, "PIP_NO_INDEX": "1"},
        )
        subprocess.run([str(venv_python), "-m", "pip", "check"], check=True)
        installed = {
            "commit": commit,
            "backend_artifact_sha256": backend_sha,
            "python_lock_sha256": identity["python_lock_sha256"],
            "python_abi": identity["python_abi"],
            "pip_check": "passed",
        }
        candidate = stage / "backend-artifact-receipt.json"
        candidate.write_text(json.dumps(installed, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(candidate, receipt)
        return backend_sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--venv-python", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(install(**vars(args)))


if __name__ == "__main__":
    main()
