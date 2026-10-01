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
* ``GITHUB_EVENT_NAME=push`` (deploy, a push to main): the ref's tip BEFORE the
  push — ``before`` in the event payload at ``$GITHUB_EVENT_PATH``. Not
  ``HEAD~1``: a push carrying several commits would then compare only against
  its own second-newest commit and hide a lock edit made in an earlier one.
  A zero ``before`` (``0000…``: the push CREATED the ref) has no prior tip, so
  the base is the merge-base with ``origin/main`` instead. The payload being
  missing, unreadable or without ``before``, or ``before`` not being a commit in
  this checkout (a shallow clone, or history rewritten by a force-push), is NO
  BASE — never a silent fallback to ``HEAD~1``.
* otherwise (pull request, schedule, dispatch): the merge-base of HEAD with
  ``origin/$GITHUB_BASE_REF`` when that variable is set — and if it is set but
  does not resolve, NO BASE rather than a quiet switch to ``origin/main`` — else
  ``origin/main``, else ``main``; and if that merge-base IS HEAD (checked out on
  main itself: smoke-test's schedule, a dispatch), ``HEAD~1``.

Fail-closed rules
─────────────────
* No base resolvable: exit 2 ("not checked") locally; exit 1 when ``CI`` is
  set — a CI job that cannot find its base has not passed the check.
* The base must be a commit that EXISTS here (``git cat-file -e <base>^{commit}``).
  A bogus or unfetched base is an error (exit 1), never "history before the lock".
* Only a base whose tree provably has no lock file (``git ls-tree`` lists nothing
  at the path) predates AL-0 and passes with nothing to preserve.
* The base lock EXISTS but cannot be read or parsed: exit 1, never an empty list.

Exit codes: 0 append-only, 1 violation / missing or unreadable base / CI without
a base, 2 no base locally.
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

#: The ``before`` GitHub sends when a push creates the ref (all zeros; 40 for
#: SHA-1, 64 for a SHA-256 repository — matched by content, not length).
ZERO_SHA = "0" * 40


def _is_zero_sha(sha: str) -> bool:
    return bool(sha) and set(sha) == {"0"}


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


def push_before(env: Mapping[str, str]) -> tuple[str | None, str]:
    """``(before_sha, problem)`` from the push event payload; one of the two is set.

    Every way of not knowing is a ``problem``: no ``GITHUB_EVENT_PATH``, an
    unreadable or non-JSON file, or no string ``before`` in it."""
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return None, "push event but GITHUB_EVENT_PATH is not set"
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"push event but the event payload {path} is unreadable: {exc}"
    before = payload.get("before") if isinstance(payload, dict) else None
    if not isinstance(before, str) or not before.strip():
        return None, f"push event but the event payload {path} carries no 'before'"
    return before.strip(), ""


def _merge_base(git: GitRunner, head: str, refs: list[str]) -> tuple[str | None, str]:
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


def resolve_base(
    env: Mapping[str, str] | None = None, git: GitRunner = run_git
) -> tuple[str | None, str]:
    """``(base_sha, how)``; ``base_sha`` is None when no base can be resolved."""
    env = os.environ if env is None else env
    head = _rev(git, "HEAD")
    if head is None:
        return None, "HEAD does not resolve"
    if env.get("GITHUB_EVENT_NAME") == "push":
        before, problem = push_before(env)
        if before is None:
            return None, problem
        if _is_zero_sha(before):
            base, how = _merge_base(git, head, ["origin/main", "main"])
            return base, f"push created the ref (before={ZERO_SHA[:7]}…): {how}"
        sha = _rev(git, before)
        if sha is None:
            return None, (
                f"push event: before={before[:12]} is not a commit in this checkout "
                "(shallow clone or rewritten history); fetch-depth 0 is required"
            )
        return sha, f"push event: before={before[:12]}"
    base_ref = env.get("GITHUB_BASE_REF")
    if base_ref:
        ref = f"origin/{base_ref}"
        if _rev(git, ref) is None:
            return None, f"GITHUB_BASE_REF={base_ref!r} is set but {ref} does not resolve"
        return _merge_base(git, head, [ref])
    return _merge_base(git, head, ["origin/main", "main"])


def base_lock_rows(base: str, git: GitRunner = run_git) -> list[tuple[str, int, str]] | None:
    """The base lock's rows; ``None`` ONLY when the base commit exists and its
    tree has no lock file (history before AL-0).

    Raises :class:`LockCheckError` when ``base`` is not a commit here (a bogus or
    unfetched base proves nothing, so it cannot read as "predates the lock"), or
    when the file exists at ``base`` but cannot be read or parsed — an
    unreadable lock is not an empty lock."""
    rel = fd.DEFAULT_LOCK_PATH.relative_to(fd.REPO).as_posix()
    code, _ = git("cat-file", "-e", f"{base}^{{commit}}")
    if code != 0:
        raise LockCheckError(
            f"base {base} is not a commit in this checkout; an unresolvable base is "
            "not history before the lock"
        )
    code, listing = git("ls-tree", base, "--", rel)
    if code != 0:
        raise LockCheckError(f"`git ls-tree {base} -- {rel}` failed (exit {code})")
    if not listing.strip():
        return None  # the base commit's tree has no lock: it predates AL-0
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


def check(
    env: Mapping[str, str] | None = None,
    *,
    base: str | None = None,
    git: GitRunner = run_git,
) -> tuple[int, str]:
    """``(exit_code, message)`` — the whole check, shared by :func:`main` and the
    pytest gate so the two cannot disagree about what passes."""
    env = os.environ if env is None else env
    if base:
        how = "--base"
    else:
        base, how = resolve_base(env, git)
    if base is None:
        return (1 if env.get("CI") else 2), f"feature-dictionary lock history: NOT CHECKED ({how})"
    try:
        rows = base_lock_rows(base, git)
    except LockCheckError as exc:
        return 1, f"feature-dictionary lock history: ERROR ({how}) — {exc}"
    result = compare(fd.parse_lock(fd.load_lock()), rows)
    message = f"feature-dictionary lock history vs {base[:12]} ({how}): {result.message}"
    return (0 if result.ok else 1), message


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="compare against this commit instead of resolving one")
    args = parser.parse_args(argv)
    code, message = check(env, base=args.base)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
