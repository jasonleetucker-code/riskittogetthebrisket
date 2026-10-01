#!/usr/bin/env python3
"""Resolve a requested deploy ref ONCE to a full commit SHA (Deploy Production).

Every later stage -- the validate checkout, the deploy checkout, the
non-fast-forward guard, the command sent to the box and the post-deploy smoke
identity -- consumes the SHA this prints, so the tree that is tested is the
tree that ships (owner decision C, 2026-10-01). Nothing re-resolves a branch or
tag later, so a ref that moves after resolution cannot change the target.

Input is untrusted (``workflow_dispatch`` text). It is validated against a
conservative grammar, never interpolated into a shell, and resolved with
``git rev-parse --verify --end-of-options`` only after validation.

Accepted:
  * empty            -> the workflow's own commit (``--default``)
  * a full 40-hex SHA that exists as a commit
  * a branch name    -> ``refs/remotes/origin/<name>``
  * a tag name       -> ``refs/tags/<name>`` (annotated tags peel to the commit)
A full SHA is accepted in either case and normalised to lowercase.

Refused: abbreviated SHAs (their meaning can change as history grows), names
matching both a branch and a tag (ambiguous), anything outside the grammar, and
revision expressions or qualified refs (``origin/main``, ``refs/heads/x``,
``HEAD~1``) -- pass the plain branch/tag name or the full SHA instead.

Name lookup comes before the abbreviated-SHA check: a hex-looking string that
IS a branch or tag name (``cafe``) resolves as that ref, exactly as git would.

Writes ``sha`` and ``kind`` to ``$GITHUB_OUTPUT`` when set.
Exit codes: 0 resolved; 2 invalid input; 3 not found; 4 ambiguous.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

FULL_SHA = re.compile(r"[0-9a-f]{40}")
HEXISH = re.compile(r"[0-9a-fA-F]{4,39}")
REF_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


class ResolveError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )


def _commit_of(repo: Path, ref: str) -> str | None:
    out = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    value = out.stdout.strip()
    return value if out.returncode == 0 and FULL_SHA.fullmatch(value) else None


def validate_name(requested: str) -> None:
    if not REF_NAME.fullmatch(requested):
        raise ResolveError(2, f"deploy_ref {requested!r} is not a valid ref name")
    if (
        ".." in requested
        or "@{" in requested
        or requested.endswith((".lock", "/", "."))
        or "//" in requested
    ):
        raise ResolveError(2, f"deploy_ref {requested!r} uses a forbidden ref construct")


def resolve(repo: Path, requested: str, default: str) -> tuple[str, str]:
    """``(sha, kind)`` for ``requested``; raises :class:`ResolveError`."""
    requested = (requested or "").strip()
    if not requested:
        if not FULL_SHA.fullmatch(default or ""):
            raise ResolveError(2, "default (workflow commit) is not a full SHA")
        if _commit_of(repo, default) != default:
            raise ResolveError(3, f"default commit {default} is not in this checkout")
        return default, "default"
    validate_name(requested)
    if FULL_SHA.fullmatch(requested.lower()):
        requested = requested.lower()
        if _commit_of(repo, requested) != requested:
            raise ResolveError(3, f"commit {requested} does not exist in this repository")
        return requested, "commit"
    candidates = {
        "branch": _commit_of(repo, f"refs/remotes/origin/{requested}"),
        "tag": _commit_of(repo, f"refs/tags/{requested}"),
    }
    found = {kind: sha for kind, sha in candidates.items() if sha}
    if len(found) > 1:
        raise ResolveError(
            4, f"{requested!r} names both a branch and a tag; pass the full commit SHA"
        )
    if found:
        kind, sha = next(iter(found.items()))
        return sha, kind
    if HEXISH.fullmatch(requested):
        raise ResolveError(
            2, f"{requested!r} looks like an abbreviated SHA; pass the full 40-character SHA"
        )
    raise ResolveError(
        3,
        f"{requested!r} is not a branch, tag or commit in this repository "
        "(pass a plain branch/tag name such as 'main', or the full commit SHA)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--requested", default="", help="workflow_dispatch deploy_ref (may be empty)"
    )
    parser.add_argument("--default", required=True, help="the workflow's own commit (github.sha)")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        sha, kind = resolve(args.repo, args.requested, args.default)
    except ResolveError as exc:
        print(f"::error title=Unresolvable deploy_ref::{exc}", file=sys.stderr)
        return exc.code
    print(f"resolved deploy target: {sha} ({kind}; requested {args.requested or '<default>'!r})")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"sha={sha}\nkind={kind}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
