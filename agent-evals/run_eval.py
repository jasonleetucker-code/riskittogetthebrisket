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
repo_head_end (read-only `gh api`). A success counts only with --repo and
--trusted-ref, which prove the gate machinery at that revision matches trusted
history. Each check is printed with its evidence level.

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

from graders.deterministic import (  # noqa: E402
    CaseError,
    grade_file,
    list_case_ids,
    load_artifact,
    load_case,
)
from steward_adapter import artifact_from_state  # noqa: E402


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
        "--trusted-ref",
        help="Trusted ref in --repo for gate identity: a full SHA or refs/remotes/... / "
        "refs/heads/... (e.g. refs/remotes/origin/main); short names can be shadowed by tags.",
    )
    parser.add_argument(
        "--ci-base-branch", default="main", help="Branch PR runs must target (default main)."
    )
    parser.add_argument(
        "--require-verified-ci",
        action="store_true",
        help="Fail when a required CI workflow cannot be verified.",
    )
    parser.add_argument(
        "--steward-state", type=Path, help="Private Steward SQLite state holding source receipt."
    )
    parser.add_argument(
        "--require-verified-steward-receipt",
        action="store_true",
        help="Fail when the submitted artifact cannot be matched to its private source receipt.",
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
    if args.require_verified_steward_receipt and args.steward_state is None:
        parser.error("--require-verified-steward-receipt needs --steward-state")

    try:
        result = grade_file(
            args.case,
            Path(args.artifact),
            repo=args.repo,
            require_verified_diff=args.require_verified_diff,
            ci_repo=args.ci_repo,
            require_verified_ci=args.require_verified_ci,
            trusted_ref=args.trusted_ref,
            trusted_base=args.ci_base_branch,
        )
        artifact = load_artifact(Path(args.artifact))
        source = artifact.get("source_receipt")
        if source is not None and args.steward_state is not None:
            expected = artifact_from_state(args.steward_state, source["run_id"])
            result.evidence.append(
                {"check": "steward_receipt_mapping", "level": "VERIFIED_AGAINST_ARTIFACT"}
            )
            if artifact != expected:
                result.failures.append("eval artifact does not match the persisted Steward receipt")
                result.passed = False
        elif source is not None:
            result.evidence.append(
                {
                    "check": "steward_receipt_mapping",
                    "level": "NOT_CHECKED",
                    "reason": "no_steward_state",
                }
            )
        elif args.steward_state is not None:
            result.evidence.append(
                {
                    "check": "steward_receipt_mapping",
                    "level": "NOT_CHECKED",
                    "reason": "no_source_receipt",
                }
            )
            result.failures.append("eval artifact has no source_receipt identity")
            result.passed = False
        if args.require_verified_steward_receipt and source is None:
            result.failures.append("source receipt mapping could not be verified")
            result.passed = False
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
