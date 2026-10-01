#!/usr/bin/env python3
"""Is the feature-dictionary lock append-only ACROSS HISTORY? (AL-0, A4 rule 3a)

``tests/model_registry/test_feature_dictionary.py`` already proves, with no git,
that every committed definition matches its row in
``config/model_registry/feature_dictionary.lock.json``. That cannot catch one
commit that rewrites BOTH a definition and its lock row: the two still agree.
Only a comparison against an earlier lock can. This script makes it: every row
the BASE lock holds must survive in the current lock, unchanged and in order.

Which base
──────────
* ``GITHUB_EVENT_NAME=push`` (deploy, a push to main): the previous commit,
  ``HEAD~1``. The merge-base with ``origin/main`` is HEAD itself there, so it
  would compare the lock with itself and prove nothing.
* otherwise the merge-base of HEAD with ``origin/$GITHUB_BASE_REF`` (a pull
  request), else ``origin/main``, else ``main`` — and if that merge-base IS
  HEAD (checked out on main itself), ``HEAD~1``.

Fail-closed rules
─────────────────
* No base resolvable: exit 2 ("not checked") locally; exit 1 when ``CI`` is
  set — a CI job that cannot find its base has not passed the check.
* The base lock is absent (history before AL-0): nothing to preserve — pass.
* The base lock EXISTS but cannot be read or parsed: exit 1, never an empty list.

Exit codes: 0 append-only, 1 violation / unreadable base / CI without a base,
2 no base locally.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry import feature_dictionary as fd  # noqa: E402

#: ``git(*args) -> (returncode, stdout)``; injectable for tests.
GitRunner = Callable[..., "tuple[int, str]"]


class LockCheckError(RuntimeError):
    """The base lock exists but could not be read: an error, never 'no rows'."""


def run_git(*args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 128, str(exc)
    return out.returncode, out.stdout


def _rev(git: GitRunner, ref: str) -> str | None:
    code, out = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if code != 0:
        return None
    return out.strip() or None


def resolve_base(
    env: Mapping[str, str] | None = None, git: GitRunner = run_git
) -> tuple[str | None, str]:
    """``(base_sha, how)``; ``base_sha`` is None when no base can be resolved."""
    env = os.environ if env is None else env
    head = _rev(git, "HEAD")
    if head is None:
        return None, "HEAD does not resolve"
    if env.get("GITHUB_EVENT_NAME") == "push":
        prev = _rev(git, "HEAD~1")
        return prev, "push event: HEAD~1" if prev else "push event but HEAD~1 is not available"
    refs = []
    if env.get("GITHUB_BASE_REF"):
        refs.append(f"origin/{env['GITHUB_BASE_REF']}")
    refs += ["origin/main", "main"]
    for ref in refs:
        if _rev(git, ref) is None:
            continue
        code, out = git("merge-base", "HEAD", ref)
        mb = out.strip() if code == 0 else ""
        if not mb:
            continue
        if mb == head:
            prev = _rev(git, "HEAD~1")
            return prev, (
                f"merge-base with {ref} is HEAD: HEAD~1"
                if prev
                else f"merge-base with {ref} is HEAD and HEAD~1 is not available"
            )
        return mb, f"merge-base with {ref}"
    return None, f"none of {refs} resolves to a merge-base"


def base_lock_rows(base: str, git: GitRunner = run_git) -> list[tuple[str, int, str]] | None:
    """The base lock's rows; ``None`` when the base predates the lock file.

    Raises :class:`LockCheckError` when the file exists at ``base`` but cannot
    be read or parsed — an unreadable lock is not an empty lock."""
    rel = fd.DEFAULT_LOCK_PATH.relative_to(fd.REPO).as_posix()
    code, _ = git("cat-file", "-e", f"{base}:{rel}")
    if code != 0:
        return None
    code, text = git("show", f"{base}:{rel}")
    if code != 0:
        raise LockCheckError(f"{rel} exists at {base} but `git show` failed (exit {code})")
    try:
        return fd.parse_lock(json.loads(text))
    except (ValueError, fd.FeatureDictionaryError) as exc:
        raise LockCheckError(f"{rel} at {base} does not parse: {exc}") from exc


@dataclass(frozen=True)
class LockCheck:
    ok: bool
    message: str


def compare(
    current: list[tuple[str, int, str]], base: list[tuple[str, int, str]] | None
) -> LockCheck:
    if base is None:
        return LockCheck(True, "the base predates the lock file; nothing to preserve")
    if current[: len(base)] != base:
        changed = [
            f"{row[0]} v{row[1]}"
            for i, row in enumerate(base)
            if i >= len(current) or current[i] != row
        ]
        return LockCheck(
            False,
            "a lock row present on the base was edited, removed or reordered: "
            + ", ".join(changed),
        )
    return LockCheck(True, f"{len(base)} base row(s) preserved, {len(current) - len(base)} added")


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="compare against this commit instead of resolving one")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    if args.base:
        base, how = args.base, "--base"
    else:
        base, how = resolve_base(env)
    if base is None:
        print(f"feature-dictionary lock history: NOT CHECKED ({how})")
        return 1 if env.get("CI") else 2
    try:
        rows = base_lock_rows(base)
    except LockCheckError as exc:
        print(f"feature-dictionary lock history: ERROR — {exc}")
        return 1
    result = compare(fd.parse_lock(fd.load_lock()), rows)
    print(f"feature-dictionary lock history vs {base[:12]} ({how}): {result.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
