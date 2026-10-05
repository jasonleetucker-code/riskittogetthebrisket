"""Record and verify the exact Linux wheels used by release validation.

The manifest is an evidence artifact, not permission to install or deploy it.
The deploy cutover must separately verify the archive and install offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import sysconfig
from pathlib import Path

SCHEMA = "calculator-backend-wheelhouse/v1"
WHEEL_NAME = re.compile(r"[A-Za-z0-9_.+\-]+\.whl")
MAX_WHEELS = 500
MAX_WHEEL_BYTES = 750 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def inspect(wheel_dir: Path, lock: Path) -> dict:
    if wheel_dir.is_symlink() or not wheel_dir.is_dir():
        raise ValueError("wheelhouse must be a regular directory")
    if lock.is_symlink() or not lock.is_file():
        raise ValueError("lock must be a regular file")
    paths = sorted(wheel_dir.iterdir(), key=lambda path: path.name)
    if not paths or len(paths) > MAX_WHEELS:
        raise ValueError("wheelhouse has an invalid wheel count")
    wheels = []
    names = set()
    total_bytes = 0
    for path in paths:
        size = path.stat().st_size
        if (
            path.is_symlink()
            or not path.is_file()
            or not WHEEL_NAME.fullmatch(path.name)
            or size > MAX_WHEEL_BYTES
        ):
            raise ValueError(f"unsafe wheelhouse entry: {path.name}")
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("wheelhouse exceeds size budget")
        folded = path.name.casefold()
        if folded in names:
            raise ValueError("duplicate wheel name")
        names.add(folded)
        wheels.append({"name": path.name, "sha256": _sha256(path), "bytes": size})
    identity = {
        "schema": SCHEMA,
        "python_abi": f"{sys.implementation.name}-{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sysconfig.get_platform(),
        "lock_sha256": _lock_sha256(lock),
        "wheels": wheels,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**identity, "wheelhouse_sha256": hashlib.sha256(encoded).hexdigest()}


def verify(manifest: dict, wheel_dir: Path, lock: Path) -> str:
    observed = inspect(wheel_dir, lock)
    if manifest != observed:
        raise ValueError("wheelhouse manifest differs from local bytes, lock or runtime")
    return observed["wheelhouse_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "create":
        manifest = inspect(args.wheel_dir, args.lock)
        args.manifest.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        verify(manifest, args.wheel_dir, args.lock)
    print(manifest["wheelhouse_sha256"])


if __name__ == "__main__":
    main()
