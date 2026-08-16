#!/usr/bin/env python3
"""Is the tree CI validated the tree that will actually be merged?

THE RACE THIS CLOSES
────────────────────
2026-08-16, PR #871.

    18:53  CI starts on head edc25300d (base = main @ 84c24093a)
    19:08  CI concludes SUCCESS on that exact head
    19:10  an automated data refresh pushes 801bf940d to main
    19:10  the owner merges → GitHub creates ce8a8341a =
           merge(801bf940d, edc25300d)

``ce8a8341a`` had never been validated by anything.  Its second parent
carried a scrape in which KTC had timed out, and the merged tree failed
the deploy's validate job minutes later.  Nothing shipped broken — the
deploy gate held — but ``main`` went red on a combination no gate had
ever seen, and the post-mortem cost more than the release.

WHY "IT'S JUST DATA" IS NOT AN ANSWER
─────────────────────────────────────
The refresh commit touched only ``data/`` and ``exports/``.  In this
repository those are **inputs to the build, the tests and the contract**:
``exports/latest/dynasty_data_*.json`` is the payload
``validate_api_data_contract`` runs on, ``exports/archive/*.zip`` is what
several tests build real boards from, and ``CSVs/site_raw`` feeds the
per-source enrichment.  A commit that changes them changes what the test
suite means.  It is not drift.

THE CLASSES
───────────
* **A — inert.**  Ordinary prose that nothing reads at build or test
  time.  Safe to merge over.
* **B — source / governance.**  Code, tests, workflows, deploy scripts,
  and the canonical planning records.  A merge across these is a
  semantic merge and must be revalidated.
* **C — build/test/contract-consumed data.**  ``data/``, ``exports/``,
  ``CSVs/``, ``config/``.  Revalidate: the tests will not mean the same
  thing.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
─────────────────────────────────────────────────
It reports which classes of change exist on the base branch that the
head does not contain, and in ``--strict`` mode exits non-zero when any
class B or C change is outstanding.

It does NOT try to make the race impossible.  A gate cannot hold a lock
across a human clicking a button, and chasing every 2-hourly refresh
would be an infinite loop — green, refresh, merge, revalidate, refresh —
which is exactly the failure mode the owner named.  So the discipline is
bounded rather than continuous:

    develop → local/full checks → one bounded final review
            → HEAD FREEZE
            → merge base in ONCE, run --strict, validate that exact SHA
            → merge promptly
            → deploy validates the merged tree anyway

Advisory on every PR (so the state is always visible); strict once, at
the release moment.  If a refresh lands inside that window, you merge it
once more and re-run — the loop terminates because you only enter it
when you are about to merge.

Exit codes:
  0 — head is a valid release candidate for the classes checked
  1 — outstanding class B/C changes (strict mode only)
  2 — could not determine (missing refs)
"""

from __future__ import annotations

import argparse
import os
import subprocess

# Ordered most-specific first; the first match wins.
_CLASS_C_PREFIXES = ("data/", "exports/", "CSVs/", "config/")
_CLASS_B_PREFIXES = (
    ".github/workflows/",
    "deploy/",
    "frontend/",
    "scripts/",
    "src/",
    "tests/",
)
_CLASS_B_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".sh", ".yml", ".yaml", ".json", ".toml")
#: Canonical planning records — governance, not prose.  Kept as an
#: explicit list because the rest of ``docs/`` genuinely is class A.
_CLASS_B_EXACT = {
    "PRODUCT_PLAN.md",
    "CLAUDE.md",
    "docs/MASTER_PRODUCT_PLAN.md",
    "docs/EXECUTION_PLAN.md",
    "docs/C_SERIES_SCOPE_MANIFEST.md",
    "docs/C_SERIES_EXECUTION_MAP.md",
    "docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md",
    "docs/CE_REGISTRY.md",
    "docs/PLANNING_DOCUMENT_STATUS.md",
    "docs/WORK_CLAIMS.md",
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
}


def classify(path: str) -> str:
    """``"A"`` / ``"B"`` / ``"C"`` for one repository path."""
    if path in _CLASS_B_EXACT:
        return "B"
    for prefix in _CLASS_C_PREFIXES:
        if path.startswith(prefix):
            return "C"
    for prefix in _CLASS_B_PREFIXES:
        if path.startswith(prefix):
            return "B"
    if path.endswith(_CLASS_B_SUFFIXES):
        return "B"
    return "A"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def outstanding_paths(base: str, head: str) -> list[str] | None:
    """Paths changed on ``base`` that ``head`` does not contain.

    ``git diff --name-only <merge-base> <base>`` — i.e. what the base
    branch has moved by since this head branched from it.  ``None`` when
    either ref is unresolvable.
    """
    if not _git("rev-parse", "--verify", "--quiet", base):
        return None
    if not _git("rev-parse", "--verify", "--quiet", head):
        return None
    merge_base = _git("merge-base", base, head)
    if not merge_base:
        return None
    raw = _git("diff", "--name-only", merge_base, base)
    return [line for line in raw.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="Base ref (default: origin/main)")
    parser.add_argument("--head", default="HEAD", help="Candidate head ref (default: HEAD)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when class B or C changes are outstanding (use at the release moment).",
    )
    args = parser.parse_args()

    paths = outstanding_paths(args.base, args.head)
    if paths is None:
        print(f"::warning title=Release candidate::cannot resolve {args.base}...{args.head}")
        return 2

    buckets: dict[str, list[str]] = {"A": [], "B": [], "C": []}
    for path in paths:
        buckets[classify(path)].append(path)

    base_sha = _git("rev-parse", "--short", args.base)
    head_sha = _git("rev-parse", "--short", args.head)
    print(f"[release-candidate] base={args.base}@{base_sha} head={args.head}@{head_sha}")
    print(
        f"[release-candidate] outstanding on base: "
        f"{len(buckets['C'])} class-C (build/test data), "
        f"{len(buckets['B'])} class-B (source/governance), "
        f"{len(buckets['A'])} class-A (inert)"
    )
    for cls, label in (("C", "build/test/contract-consumed data"), ("B", "source/governance")):
        for path in buckets[cls][:15]:
            print(f"[release-candidate][{cls}] {path}  ({label})")
        if len(buckets[cls]) > 15:
            print(f"[release-candidate][{cls}] … and {len(buckets[cls]) - 15} more")

    blocking = buckets["B"] + buckets["C"]
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(
                    "\n## Release candidate\n\n"
                    f"- base `{args.base}@{base_sha}` · head `{args.head}@{head_sha}`\n"
                    f"- outstanding: **{len(buckets['C'])}** class-C data, "
                    f"**{len(buckets['B'])}** class-B source/governance, "
                    f"{len(buckets['A'])} class-A inert\n"
                )
        except OSError:
            pass

    if not blocking:
        print("[release-candidate] the validated tree IS the tree that will merge.")
        return 0

    message = (
        f"{len(blocking)} change(s) on {args.base} are not in this head, and they are "
        "consumed by the build, the tests or the contract. The merge commit would be a "
        "combination nothing has validated."
    )
    if args.strict:
        print(f"::error title=Release candidate stale::{message}")
        print(
            "[release-candidate] Merge the base in ONCE, re-run the exact-head validation, "
            "and merge promptly. Do not chase further refreshes — see the docstring."
        )
        return 1
    print(f"::warning title=Release candidate stale::{message}")
    print(
        "[release-candidate] Advisory here by design. Run with --strict at the release "
        "moment (see .github/workflows/release-candidate.yml)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
