"""Trusted local runner: the actual changed-file set between two pinned commits.

This is the only place agent-evals reads anything beyond the case and artifact
JSON. It exists so one grading check -- "which files did this run change?" --
can be answered from the repository instead of from the run's own report.

Trust boundary. The repository -- its path, ``.git/config``, attributes and
object store -- is trusted and comes from the operator. Grade against a clean
clone the operator controls, never the evaluated agent's own working copy,
which the run may have edited. Everything taken from the run artifact is
untrusted: the two revision strings must be full 40-character lowercase hex (so
they cannot be read by git as options, ranges or refs), and nothing else from
the artifact reaches git.
No declared path is ever opened or read, no command embedded in a transcript
is executed, git runs without a shell under a timeout with lazy fetching,
transports, prompts, optional locks and fsmonitor disabled (so a pinned but
missing object in a partial clone cannot trigger a fetch), and output is
capped.

What a successful result proves: the tree difference between two commits that
exist in this repository. It does not prove the run authored those commits,
that the commits are the ones the run actually worked on, or that the change
behaves correctly. A missing or unresolvable revision is reported as
unverified, never as a pass.

Reasons split by who can cause them. ``no_pinned_revisions``: the artifact made
no claim. ``OPERATOR_FAULTS``: the supplied repository or git is unusable --
a grading error, not a grade. Anything else: the artifact pinned revisions
whose diff could not be established, which the grader treats as a failure.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

FULL_SHA = re.compile(r"[0-9a-f]{40}")
GIT_TIMEOUT_SECONDS = 30
MAX_CHANGED_FILES = 5000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
OPERATOR_FAULTS = frozenset({"repository_unavailable", "git_unavailable"})
_HARDENED_ENV = {
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}
_HARDENED_CONFIG = ("-c", "core.fsmonitor=false", "-c", "protocol.allow=never")


@dataclass(frozen=True)
class DiffEvidence:
    """``files`` is set only when the diff was actually established."""

    files: tuple[str, ...] | None
    base: str | None
    head: str | None
    reason: str | None = None

    @property
    def established(self) -> bool:
        return self.files is not None


def is_full_sha(value) -> bool:
    return isinstance(value, str) and FULL_SHA.fullmatch(value) is not None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *_HARDENED_CONFIG, "-C", str(repo), *args],
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
        env={**os.environ, **_HARDENED_ENV},
    )


def _commit_exists(repo: Path, sha: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def changed_files_between(
    repo: Path, base, head, *, max_files: int = MAX_CHANGED_FILES
) -> DiffEvidence:
    """Changed paths from ``base`` to ``head`` in ``repo``, or why that is unknown."""
    # The operator's repository is checked first, so a mistyped path is reported even
    # when the artifact pins nothing.
    repo = Path(repo)
    if not repo.is_dir():
        return DiffEvidence(None, base, head, "repository_unavailable")
    try:
        if _git(repo, "rev-parse", "--git-dir").returncode != 0:
            return DiffEvidence(None, base, head, "repository_unavailable")
        if base is None or head is None:
            return DiffEvidence(None, base, head, "no_pinned_revisions")
        if not (is_full_sha(base) and is_full_sha(head)):
            return DiffEvidence(None, base, head, "revision_not_full_sha")
        for sha in (base, head):
            if not _commit_exists(repo, sha):
                return DiffEvidence(None, base, head, "revision_not_in_repository")
        # --no-renames: a rename is both paths touched, independent of diff.renames config.
        result = _git(
            repo, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", base, head, "--"
        )
    except OSError:
        return DiffEvidence(None, base, head, "git_unavailable")
    except subprocess.TimeoutExpired:
        return DiffEvidence(None, base, head, "git_timeout")
    if result.returncode != 0:
        return DiffEvidence(None, base, head, "git_diff_failed")
    if len(result.stdout) > MAX_OUTPUT_BYTES:
        return DiffEvidence(None, base, head, "diff_exceeds_bound")
    files = tuple(p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p)
    if len(files) > max_files:
        return DiffEvidence(None, base, head, "diff_exceeds_bound")
    return DiffEvidence(tuple(sorted(files)), base, head)
