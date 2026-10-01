#!/usr/bin/env python3
"""Is the feature-dictionary lock immutable ACROSS ITS WHOLE HISTORY? (AL-0, A4 rule 3a)

``tests/model_registry/test_feature_dictionary.py`` already proves, with no git,
that every committed definition matches its row in
``config/model_registry/feature_dictionary.lock.json``. That cannot catch one
commit that rewrites BOTH a definition and its lock row: the two still agree.
Only history can. This script reads EVERY version of the lock git has ever
recorded (``git rev-list --full-history HEAD -- <lock>``, then
``git show <sha>:<lock>`` for each), plus the working-tree lock, and fails when:

* **rewritten** — a ``(name, version)`` carries a different ``definitionHash``
  anywhere in that history (or the working tree) than where it was first seen;
* **removed** — any commit's lock lacks a ``(name, version)`` one of its
  parents' locks held (checked per commit against ``git rev-list --parents``,
  so a merge that discards a side branch's row is caught too), or the current
  lock lacks one history ever held. Re-adding the row later with its original
  hash does not repair it: the removing commit stays in history;
* **reordered** — the rows any historical lock holds do not appear in the
  current lock in the same relative order;
* **not appended** — a row no historical lock holds sits before a row one does.

Why the whole history and not one base
──────────────────────────────────────
A comparison against a single base (the previous tip on a push) can be
laundered: push P2 rewrites a row and its deploy goes red — or is never run,
because ``deploy.yml``'s single concurrency group replaces a pending run — and
push P3 then compares against P2's tip, which already holds the rewrite, and
passes. Immutability across history is a property of the commits, not of which
base a run happens to pick: once any commit holding a rewritten row is
reachable from HEAD, every later check sees it disagree with the earlier row.
So there is no base selection at all.

``--full-history`` deliberately includes commits on merged side branches. A PR
branch that defines a new feature and then edits it in a later commit is a
violation: fix it by rewriting the branch (amend/squash) before merge, or by
bumping the version. It fails on the PR, where history is still rewritable,
instead of after the merge, where it is not.

What it cannot prove: a force-push that rewrites ``main``'s history so the
original row never existed. That is branch protection's job; no in-repo check
can see commits that are no longer in the repository.

Fail-closed rules
─────────────────
* A shallow clone (``git rev-parse --is-shallow-repository``) whose shallow
  boundary cuts the lock's history — any lock-touching commit is itself a
  boundary commit, so its true parent (and possibly the lock's root) is
  missing — is INCOMPLETE history. Exit 1 under ``CI``, 2 locally ("not
  checked"). Every workflow that runs this check uses ``fetch-depth: 0``.
* Any git failure (no repository, no HEAD, ``rev-list`` erroring): exit 1 under
  ``CI``, 2 locally.
* A historical lock that exists but cannot be read or parsed: exit 1 always — an
  unreadable lock is not an empty lock. A commit whose tree has no lock (the
  lock was deleted there) contributes no rows; the removal is caught against
  the current lock.

Exit codes: 0 immutable, 1 violation / unreadable history / CI without complete
history, 2 history unavailable locally.
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

LOCK_REL = fd.DEFAULT_LOCK_PATH.relative_to(fd.REPO).as_posix()

#: ``git(*args) -> (returncode, stdout)``.
GitRunner = Callable[..., "tuple[int, str]"]

Row = tuple[str, int, str]


class LockCheckError(RuntimeError):
    """A historical lock exists but could not be read: an error, never 'no rows'."""


class HistoryUnavailable(RuntimeError):
    """The history walk could not run, or ran over incomplete history."""


def git_runner(repo: Path) -> GitRunner:
    def run(*args: str) -> tuple[int, str]:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 128, str(exc)
        return out.returncode, out.stdout

    return run


def _shallow_boundary(git: GitRunner) -> set[str]:
    """The shallow clone's boundary commits; empty for a complete clone."""
    code, out = git("rev-parse", "--is-shallow-repository")
    if code != 0:
        raise HistoryUnavailable("`git rev-parse --is-shallow-repository` failed")
    if out.strip() != "true":
        return set()
    code, path = git("rev-parse", "--path-format=absolute", "--git-path", "shallow")
    if code != 0 or not path.strip():
        raise HistoryUnavailable("shallow clone, and its boundary file cannot be located")
    try:
        text = Path(path.strip()).read_text(encoding="utf-8")
    except OSError as exc:
        raise HistoryUnavailable(f"shallow clone, and its boundary is unreadable: {exc}") from exc
    return {line.strip() for line in text.splitlines() if line.strip()}


@dataclass(frozen=True)
class LockVersion:
    """One commit that touched the lock: its rows (``None`` = the commit deleted
    the file) and each parent's rows, so a removal is seen AT the commit that
    made it even when a later commit puts the row back."""

    sha: str
    rows: list[Row] | None
    parent_rows: tuple[list[Row] | None, ...]


def _lock_at(
    git: GitRunner, rev: str, lock_rel: str, cache: dict[str, list[Row]]
) -> list[Row] | None:
    """The lock's rows at ``rev``; ``None`` only when ``rev``'s tree has no lock."""
    code, listing = git("ls-tree", rev, "--", lock_rel)
    if code != 0:
        raise LockCheckError(f"`git ls-tree {rev} -- {lock_rel}` failed (exit {code})")
    if not listing.strip():
        return None
    blob = listing.split()[2]
    if blob not in cache:
        code, text = git("cat-file", "blob", blob)
        if code != 0:
            raise LockCheckError(f"{lock_rel} exists at {rev} but its blob is unreadable")
        try:
            cache[blob] = fd.parse_lock(json.loads(text))
        except (ValueError, fd.FeatureDictionaryError) as exc:
            raise LockCheckError(f"{lock_rel} at {rev} does not parse: {exc}") from exc
    return cache[blob]


def history_locks(git: GitRunner, lock_rel: str = LOCK_REL) -> list[LockVersion]:
    """Every commit reachable from HEAD that touched the lock, oldest first.

    Raises :class:`HistoryUnavailable` when the walk cannot run or the history
    is cut by a shallow boundary, :class:`LockCheckError` when a historical lock
    exists but does not read or parse."""
    code, _ = git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if code != 0:
        raise HistoryUnavailable("HEAD does not resolve")
    boundary = _shallow_boundary(git)
    code, out = git(
        "rev-list", "--full-history", "--topo-order", "--reverse", "HEAD", "--", lock_rel
    )
    if code != 0:
        raise HistoryUnavailable(f"`git rev-list HEAD -- {lock_rel}` failed (exit {code})")
    shas = [line.strip() for line in out.splitlines() if line.strip()]
    cut = [sha for sha in shas if sha in boundary]
    if cut:
        raise HistoryUnavailable(
            f"shallow clone: lock commit {cut[0][:12]} is a shallow boundary, so the "
            "lock's earlier history is missing; fetch-depth 0 is required"
        )
    cache: dict[str, list[Row]] = {}
    versions: list[LockVersion] = []
    for sha in shas:
        code, line = git("rev-list", "--parents", "-n", "1", sha)
        if code != 0 or not line.strip():
            raise HistoryUnavailable(f"cannot read the parents of {sha[:12]}")
        parents = line.split()[1:]
        versions.append(
            LockVersion(
                sha,
                _lock_at(git, sha, lock_rel, cache),
                tuple(_lock_at(git, p, lock_rel, cache) for p in parents),
            )
        )
    return versions


@dataclass(frozen=True)
class LockCheck:
    ok: bool
    message: str


def _short(sha: str) -> str:
    return sha[:12] if all(c in "0123456789abcdef" for c in sha) else sha


def _keys(rows: list[Row] | None) -> list[tuple[str, int]]:
    return [(name, version) for name, version, _ in rows or ()]


def _is_subsequence(needle: list[tuple[str, int]], hay: list[tuple[str, int]]) -> bool:
    it = iter(hay)
    return all(key in it for key in needle)


def compare_history(current: list[Row], history: list[LockVersion]) -> LockCheck:
    """The rules in the module docstring, over ``history`` (oldest first) plus
    the working-tree lock as the newest version (a child of HEAD)."""
    problems: list[str] = []
    first: dict[tuple[str, int], tuple[str, str]] = {}  # key -> (hash, where)
    rewritten: set[tuple[str, int]] = set()
    for sha, rows in [*((v.sha, v.rows) for v in history), ("working tree", current)]:
        for name, version, digest in rows or ():
            seen = first.setdefault((name, version), (digest, _short(sha)))
            if seen[0] != digest and (name, version) not in rewritten:
                rewritten.add((name, version))
                problems.append(
                    f"{name} v{version} rewritten at {_short(sha)} "
                    f"(first locked at {seen[1]} as {seen[0][:12]}…, now {digest[:12]}…)"
                )
    # removed — at the commit that removed it (a later re-add does not undo it),
    # and from the working tree relative to anything history ever held
    removed: set[tuple[str, int]] = set()
    for v in history:
        mine = set(_keys(v.rows))
        for parent in v.parent_rows:
            for key in _keys(parent):
                if key not in mine and key not in removed:
                    removed.add(key)
                    problems.append(f"{key[0]} v{key[1]} was removed at {_short(v.sha)}")
    current_keys = _keys(current)
    present = set(current_keys)
    historic = {key for v in history for key in _keys(v.rows)}
    for key in sorted(historic - present - removed):
        problems.append(f"{key[0]} v{key[1]} was locked and has been removed")
    # reordered — every historical lock's surviving rows keep their relative order
    for v in history:
        if not _is_subsequence([k for k in _keys(v.rows) if k in present], current_keys):
            problems.append(f"rows locked at {_short(v.sha)} have been reordered")
            break
    # not appended — a row no history holds may not precede one history does
    new_seen = False
    for key in current_keys:
        if key not in historic:
            new_seen = True
        elif new_seen:
            problems.append(f"a new row was inserted before {key[0]} v{key[1]}, not appended")
            break
    if problems:
        return LockCheck(False, "; ".join(problems))
    return LockCheck(
        True,
        f"{len(historic)} historical row(s) immutable across {len(history)} lock "
        f"commit(s), {len(present - historic)} added",
    )


def check(
    env: Mapping[str, str] | None = None,
    *,
    repo: Path = REPO,
    lock_rel: str = LOCK_REL,
    git: GitRunner | None = None,
) -> tuple[int, str]:
    """``(exit_code, message)`` — the whole check, shared by :func:`main` and the
    pytest gate so the two cannot disagree about what passes."""
    env = os.environ if env is None else env
    git = git_runner(repo) if git is None else git
    try:
        history = history_locks(git, lock_rel)
    except HistoryUnavailable as exc:
        return (1 if env.get("CI") else 2), f"feature-dictionary lock history: NOT CHECKED — {exc}"
    except LockCheckError as exc:
        return 1, f"feature-dictionary lock history: ERROR — {exc}"
    try:
        current = fd.parse_lock(fd.load_lock(repo / lock_rel))
    except (OSError, ValueError) as exc:
        return 1, f"feature-dictionary lock history: ERROR — current lock unreadable: {exc}"
    result = compare_history(current, history)
    return (0 if result.ok else 1), f"feature-dictionary lock history: {result.message}"


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    code, message = check(env)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
