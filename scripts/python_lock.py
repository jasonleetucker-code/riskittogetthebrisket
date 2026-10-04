"""Generate and verify the exact Python dependency resolution.

The manifest files remain the human-edited dependency declarations.  The two
hash-locked files are the only install inputs for CI and production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "requirements.lock.txt"
DEV = ROOT / "requirements-dev.lock.txt"
METADATA = ROOT / "config/python-lock.json"
GENERATOR_VERSION = "0.9.26"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)(?:\s*;.*)?\s*\\?$", re.MULTILINE)
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
DECLARATION = re.compile(r"^([A-Za-z0-9_.-]+)\s*(~=|==)\s*([0-9][A-Za-z0-9.]*)")


def digest(path: Path) -> str:
    # Git may check out text with CRLF on Windows. Lock identity is over the
    # normalized repository content so Linux CI sees the same digest.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(path: Path) -> dict[str, tuple[str, str]]:
    requirements: dict[str, tuple[str, str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "-r requirements.txt" and path.name == "requirements-dev.txt":
            requirements.update(declared(ROOT / "requirements.txt"))
            continue
        match = DECLARATION.match(line)
        if match is None:
            raise ValueError(f"unsupported declaration in {path.name}: {line}")
        name, operator, version = match.groups()
        key = normalized(name)
        if key in requirements:
            raise ValueError(f"duplicate declaration: {key}")
        requirements[key] = (operator, version)
    return requirements


def version_parts(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise ValueError(f"unsupported version: {value}")
    return tuple(int(part) for part in value.split("."))


def satisfies(actual: str, operator: str, requested: str) -> bool:
    if operator == "==":
        return actual == requested
    lower = version_parts(requested)
    current = version_parts(actual)
    if len(lower) < 2:
        raise ValueError(f"invalid compatible-release specifier: {requested}")
    prefix = lower[:-1]
    upper = (*prefix[:-1], prefix[-1] + 1)
    width = max(len(lower), len(current), len(upper))

    def padded(value: tuple[int, ...]) -> tuple[int, ...]:
        return value + (0,) * (width - len(value))

    return padded(lower) <= padded(current) < padded(upper)


def locked(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8")
    packages: dict[str, str] = {}
    for block in re.split(r"(?=^[A-Za-z0-9_.-]+==)", content, flags=re.MULTILINE):
        match = PIN.match(block)
        if not match:
            continue
        name, version = match.groups()
        key = normalized(name)
        if key in packages:
            raise ValueError(f"duplicate lock entry in {path.name}: {key}")
        if not HASH.search(block.split("\n    # via", 1)[0]):
            raise ValueError(f"missing SHA-256 hash in {path.name}: {key}")
        packages[key] = version
    if not packages:
        raise ValueError(f"empty lock: {path.name}")
    return packages


def check() -> None:
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    if metadata.get("generator") != f"uv=={GENERATOR_VERSION}":
        raise ValueError("lock generator identity mismatch")
    paths = {
        "requirements.txt": ROOT / "requirements.txt",
        "requirements-dev.txt": ROOT / "requirements-dev.txt",
        "requirements.lock.txt": RUNTIME,
        "requirements-dev.lock.txt": DEV,
    }
    for filename, path in paths.items():
        if metadata.get("sha256", {}).get(filename) != digest(path):
            raise ValueError(f"dependency input changed without lock refresh: {filename}")

    runtime = locked(RUNTIME)
    development = locked(DEV)
    for manifest, packages in (
        (ROOT / "requirements.txt", runtime),
        (ROOT / "requirements-dev.txt", development),
    ):
        for name, (operator, requested) in declared(manifest).items():
            actual = packages.get(name)
            if actual is None or not satisfies(actual, operator, requested):
                raise ValueError(f"{manifest.name}: {name} {operator}{requested} is not locked")
    for name, version in runtime.items():
        if development.get(name) != version:
            raise ValueError(f"dev/runtime lock divergence: {name}")


def refresh(uv: str) -> None:
    version = subprocess.check_output([uv, "--version"], text=True).strip()
    if not version.startswith(f"uv {GENERATOR_VERSION} ("):
        raise ValueError(f"expected uv {GENERATOR_VERSION}; got {version}")
    for manifest, lock, extra in (
        ("requirements.txt", "requirements.lock.txt", []),
        (
            "requirements-dev.txt",
            "requirements-dev.lock.txt",
            ["--constraint", "requirements.lock.txt"],
        ),
    ):
        subprocess.run(
            [
                uv,
                "-q",
                "pip",
                "compile",
                manifest,
                *extra,
                "--universal",
                "--python-version",
                "3.12",
                "--generate-hashes",
                "--output-file",
                lock,
            ],
            cwd=ROOT,
            check=True,
        )
    METADATA.write_text(
        json.dumps(
            {
                "generator": f"uv=={GENERATOR_VERSION}",
                "python": "3.12",
                "sha256": {
                    filename: digest(ROOT / filename)
                    for filename in (
                        "requirements.txt",
                        "requirements-dev.txt",
                        "requirements.lock.txt",
                        "requirements-dev.lock.txt",
                    )
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    check()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "refresh"))
    parser.add_argument("--uv", default="uv", help="uv executable for refresh")
    args = parser.parse_args()
    if args.action == "refresh":
        refresh(args.uv)
    else:
        check()
    print("Python dependency lock: OK")


if __name__ == "__main__":
    main()
