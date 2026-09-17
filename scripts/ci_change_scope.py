#!/usr/bin/env python3
"""Single owner for "which systems does this change touch" (tiered-validation workflow).

WHY THIS EXISTS
---------------
The tiered fast-development workflow (``docs/AGENT_OPERATING_SYSTEM.md`` §3,
"Tiered validation workflow — L0 through L3") needs one answer to "does this
diff touch backend code, frontend code, or something high-risk enough to
require full validation regardless" — and it needs the SAME answer whether
the question is asked by a human/agent running a fast local loop or by
``.github/workflows/pr-validation.yml`` deciding which expensive steps to
run. Two independent path-matching implementations (one in YAML, one in a
dev script) drift the moment someone updates one and forgets the other —
exactly the class of defect this repository's "ONE CONCEPT, ONE CANONICAL
OWNER" rule exists to prevent. This module is that owner. Both consumers
call it; neither re-implements path matching.

FAIL-SAFE, NOT FAIL-FAST
-------------------------
If the diff cannot be computed (shallow clone with no merge base, detached
history, git error), every scope defaults to ``True`` — run everything. A
change-detection bug must never cause validation to be silently narrowed;
it may only ever cause MORE validation to run than strictly necessary. This
mirrors ``docs/AGENT_OPERATING_SYSTEM.md``'s "never classify high-risk work
as low-risk simply to save time" rule.

SCOPES
------
* ``python``    — backend/tooling code changed (src/, scripts/, tests/,
  server.py, "Dynasty Scraper.py", config/) and needs the Python test
  suite.
* ``frontend``  — anything under frontend/ changed and needs the Next.js
  build + vitest suite.
* ``high_risk`` — a change that must force FULL validation on both sides
  regardless of the above: CI workflows themselves, dependency manifests,
  the deploy scripts, canonical valuation/identity/history owners, shared
  adapters, and anything resembling a schema/migration. See
  ``docs/AGENT_OPERATING_SYSTEM.md`` §9 "High-risk escalation" for the
  product-level statement of this rule; this module is its mechanical
  enforcement for CI path-awareness specifically.

When ``high_risk`` is True, both ``python`` and ``frontend`` are forced
True as well — a high-risk change is never allowed to skip either suite.

This module deliberately does NOT decide pass/fail, does NOT run any test,
and does NOT talk to GitHub. It only classifies a set of changed paths.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass, field

# Path prefixes (relative to repo root, forward slashes) that mark a change
# as touching backend/tooling code.
_PYTHON_PREFIXES = (
    "src/",
    "scripts/",
    "tests/",
    "config/",
    "CSVs/",
)
_PYTHON_EXACT_FILES = (
    "server.py",
    "Dynasty Scraper.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
)

_FRONTEND_PREFIXES = ("frontend/",)

# Glob patterns (fnmatch-style) that force full validation on BOTH sides.
# Keep this list narrow and explicit — it is deliberately allow-listed
# evidence, not an inferred heuristic (the same posture
# scripts/ci_gate_classification.py's docstring documents for why a
# heuristic classifier was tried and rejected elsewhere in this repo).
_HIGH_RISK_PATTERNS = (
    ".github/workflows/*",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "frontend/package.json",
    "frontend/package-lock.json",
    "deploy/*",
    "deploy/**",
    "server.py",
    "Dynasty Scraper.py",
    "src/api/data_contract.py",
    "src/adapters/base.py",
    "src/adapters/*.py",
    "src/canonical/*",
    "src/canonical/**",
    "src/identity/*",
    "src/identity/**",
    "src/history/*",
    "src/history/**",
    "src/utils/*",
    "config/model_registry/*",
    "config/model_registry/**",
    "*/migrations/*",
    "*migrate*.py",
    "scripts/format_python_changes.sh",
    "scripts/ci_change_scope.py",
    "scripts/ci_gate_classification.py",
    "config/ci/release_gate_classification.json",
)


@dataclass
class ChangeScope:
    python: bool
    frontend: bool
    high_risk: bool
    changed_paths: list[str] = field(default_factory=list)
    fallback_reason: str | None = None

    def as_env_lines(self) -> list[str]:
        return [
            f"python={'true' if self.python else 'false'}",
            f"frontend={'true' if self.frontend else 'false'}",
            f"high_risk={'true' if self.high_risk else 'false'}",
        ]


def _run_git(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    return result.stdout


def _repo_root() -> str:
    out = _run_git(["rev-parse", "--show-toplevel"], os.getcwd())
    return out.strip() if out else os.getcwd()


def _everything_scope(reason: str) -> ChangeScope:
    return ChangeScope(python=True, frontend=True, high_risk=True, fallback_reason=reason)


def _matches_high_risk(path: str) -> bool:
    for pattern in _HIGH_RISK_PATTERNS:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def _is_python_path(path: str) -> bool:
    if path in _PYTHON_EXACT_FILES:
        return True
    return any(path.startswith(prefix) for prefix in _PYTHON_PREFIXES)


def _is_frontend_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _FRONTEND_PREFIXES)


def compute_scope(
    base_ref: str = "origin/main", head_ref: str = "HEAD", repo_root: str | None = None
) -> ChangeScope:
    """Classify the diff between ``base_ref`` and ``head_ref``.

    Falls back to "run everything" (never "run nothing") whenever the diff
    itself cannot be established, per the fail-safe rule in the module
    docstring.
    """
    root = repo_root or _repo_root()

    if _run_git(["rev-parse", "--verify", base_ref], root) is None:
        # Base ref not fetched/available (e.g. a shallow checkout that never
        # fetched origin/main). Try fetching it once before giving up.
        _run_git(["fetch", "origin", base_ref.removeprefix("origin/"), "--depth=200"], root)

    if _run_git(["rev-parse", "--verify", base_ref], root) is None:
        return _everything_scope(f"base ref {base_ref!r} unavailable")

    merge_base = _run_git(["merge-base", base_ref, head_ref], root)
    if not merge_base:
        return _everything_scope(f"no merge-base between {base_ref!r} and {head_ref!r}")
    merge_base = merge_base.strip()

    diff_output = _run_git(
        ["diff", "--name-only", "--diff-filter=ACMRTD", f"{merge_base}...{head_ref}"],
        root,
    )
    if diff_output is None:
        return _everything_scope("git diff failed")

    # Also fold in uncommitted local changes (working tree + staged) so an
    # agent running the local fast loop mid-edit gets an accurate answer
    # before committing anything.
    working_diff = _run_git(["diff", "--name-only", "--diff-filter=ACMRTD"], root) or ""
    staged_diff = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMRTD"], root) or ""
    untracked = _run_git(["ls-files", "--others", "--exclude-standard"], root) or ""

    paths = {
        p.strip()
        for p in (
            diff_output.splitlines()
            + working_diff.splitlines()
            + staged_diff.splitlines()
            + untracked.splitlines()
        )
        if p.strip()
    }

    if not paths:
        # No detectable change at all (e.g. an empty diff). Nothing to
        # validate, but do not claim certainty either — treat as
        # low-risk/no-op rather than forcing full validation.
        return ChangeScope(python=False, frontend=False, high_risk=False, changed_paths=[])

    high_risk = any(_matches_high_risk(p) for p in paths)
    is_python = high_risk or any(_is_python_path(p) for p in paths)
    is_frontend = high_risk or any(_is_frontend_path(p) for p in paths)

    return ChangeScope(
        python=is_python,
        frontend=is_frontend,
        high_risk=high_risk,
        changed_paths=sorted(paths),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("CI_CHANGE_SCOPE_BASE_REF", "origin/main"))
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Append KEY=value lines to $GITHUB_OUTPUT for use as step outputs.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable summary (still writes --github-output if requested).",
    )
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Print only the changed paths, one per line (for shell consumption). Implies --quiet.",
    )
    args = parser.parse_args(argv)

    scope = compute_scope(base_ref=args.base, head_ref=args.head)

    if args.paths_only:
        for p in scope.changed_paths:
            print(p)
        return 0

    if not args.quiet:
        print(f"python={scope.python} frontend={scope.frontend} high_risk={scope.high_risk}")
        if scope.fallback_reason:
            print(f"FAIL-SAFE: {scope.fallback_reason} -> defaulting to full validation")
        if scope.changed_paths:
            print(f"changed paths ({len(scope.changed_paths)}):")
            for p in scope.changed_paths[:200]:
                print(f"  {p}")

    if args.github_output:
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as fh:
                for line in scope.as_env_lines():
                    fh.write(line + "\n")
        else:
            # Not running inside GitHub Actions; print for visibility/tests.
            for line in scope.as_env_lines():
                print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
