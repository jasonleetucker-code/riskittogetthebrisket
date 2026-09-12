#!/usr/bin/env python3
"""CLI for agent-evals.

Grades a captured run artifact against a case using only deterministic,
model-free checks. Makes no network request and dispatches no model.

Usage:
    python agent-evals/run_eval.py --list
    python agent-evals/run_eval.py --case <id> --artifact <path/to/artifact.json>

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
    args = parser.parse_args(argv)

    if args.list:
        for case_id in list_case_ids():
            case = load_case(case_id)
            print(f"{case_id}\t[{case['category']}]\t{case['title']}")
        return 0

    if not args.case or not args.artifact:
        parser.error("--case and --artifact are required unless --list is given")

    try:
        result = grade_file(args.case, Path(args.artifact))
    except CaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if result.passed:
        print(f"PASS: {result.case_id}")
        return 0

    print(f"FAIL: {result.case_id}")
    for failure in result.failures:
        print(f"  - {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
