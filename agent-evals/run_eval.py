#!/usr/bin/env python3
"""CLI for agent-evals.

Grades a captured run artifact against a case using only deterministic,
model-free checks. Makes no network request and dispatches no model.

Usage:
    python agent-evals/run_eval.py --list
    python agent-evals/run_eval.py --case <id> --artifact <path/to/artifact.json>
    python agent-evals/run_eval.py --case <id> --artifact <path> --repo . [--require-verified-diff]

With --repo, the changed-file claim and path scope are checked against the
actual diff between the artifact's pinned repo_head_start and repo_head_end in
that local repository. With --ci-repo owner/name, a case's required CI
workflows are checked against GitHub Actions' records for the pinned
repo_head_end (read-only `gh api`; needs --repo so the workflow file's identity
can be checked). Each check is printed with its evidence level.

Capturing a real interactive agent run against a case is a manual step:
give the case's "objective" to an actual agent session, then transcribe the
outcome into the run_artifact shape (schema/run_artifact.schema.json) and
save it to a file. This script never dispatches a model itself and must
never be invoked from ordinary CI in a mode that would incur paid
inference -- see README.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graders.deterministic import CaseError, grade_file, list_case_ids, load_case  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="List available case ids and exit.")
    parser.add_argument("--case", help="Case id to grade against.")
    parser.add_argument("--artifact", help="Path to a run_artifact JSON file to grade.")
    parser.add_argument(
        "--repo", type=Path, help="Local repository holding the artifact's pinned revisions."
    )
    parser.add_argument(
        "--require-verified-diff",
        action="store_true",
        help="Fail when the changed-file claim cannot be verified against --repo.",
    )
    parser.add_argument("--ci-repo", help="GitHub owner/name whose Actions records to read.")
    parser.add_argument(
        "--require-verified-ci",
        action="store_true",
        help="Fail when a required CI workflow cannot be verified.",
    )
    args = parser.parse_args(argv)

    if args.list:
        for case_id in list_case_ids():
            case = load_case(case_id)
            print(f"{case_id}\t[{case['category']}]\t{case['title']}")
        return 0

    if not args.case or not args.artifact:
        parser.error("--case and --artifact are required unless --list is given")
    if args.require_verified_diff and args.repo is None:
        parser.error("--require-verified-diff needs --repo")
    if args.require_verified_ci and args.ci_repo is None:
        parser.error("--require-verified-ci needs --ci-repo")

    try:
        result = grade_file(
            args.case,
            Path(args.artifact),
            repo=args.repo,
            require_verified_diff=args.require_verified_diff,
            ci_repo=args.ci_repo,
            require_verified_ci=args.require_verified_ci,
        )
    except (CaseError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"{'PASS' if result.passed else 'FAIL'}: {result.case_id}")
    for failure in result.failures:
        print(f"  - {failure}")
    for item in result.evidence:
        reason = f" ({item['reason']})" if item.get("reason") else ""
        print(f"  [{item['level']}] {item['check']}{reason}")
    print("  run as a whole: NOT VERIFIED (only checks marked VERIFIED_AGAINST_ARTIFACT are)")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
