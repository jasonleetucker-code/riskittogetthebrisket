"""Bound saved frontend release archives after a successful deploy.

Only complete SHA-named archive triplets are eligible. The just-deployed and
immediately previous revisions are always protected; unknown files are left
for an operator rather than guessed at or recursively removed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

_SHA = re.compile(r"[0-9a-f]{40}")


def prune_releases(
    release_dir: Path, *, current: str, previous: str | None, keep: int = 8
) -> list[str]:
    if not _SHA.fullmatch(current) or (previous and not _SHA.fullmatch(previous)):
        raise ValueError("release identities must be full commit SHAs")
    if keep < 2:
        raise ValueError("release retention must keep at least two revisions")
    if release_dir.is_symlink() or not release_dir.is_dir():
        raise ValueError("release directory must be a real directory")

    complete = []
    for archive in release_dir.iterdir():
        if archive.suffix != ".tar" or not _SHA.fullmatch(archive.stem):
            continue
        companions = [archive.with_suffix(suffix) for suffix in (".sha256", ".json")]
        if all(path.is_file() and not path.is_symlink() for path in (archive, *companions)):
            complete.append((archive.stat().st_mtime_ns, archive.stem, archive, companions))

    complete.sort(key=lambda item: (item[0], item[1]), reverse=True)
    protected = {current, previous}
    retained = {item[1] for item in complete[:keep]} | protected
    removed = []
    for _, sha, archive, companions in complete:
        if sha in retained:
            continue
        archive.unlink()
        for path in companions:
            path.unlink()
        removed.append(sha)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--keep", type=int, default=8)
    args = parser.parse_args(argv)
    for sha in prune_releases(
        args.release_dir, current=args.current, previous=args.previous, keep=args.keep
    ):
        print(f"pruned saved release archive: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
