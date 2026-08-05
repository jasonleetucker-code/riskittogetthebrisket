#!/usr/bin/env python3
"""Tell a session, before it starts, whether someone else is already on this.

WHY THIS EXISTS
---------------
On 2026-08-05 five sessions independently solved the SAME defects inside one
window, and nobody noticed until a branch had already merged:

    market gap in value space              #740, #722 AND #742
    tepMultiplier default -> null          #740 and #722
    _sanitize_next_path backslash          #740 and #722
    FAAB budget normalisation              #740 and #707
    ROS absence as 0.0 odds                #740 and #736
    compact-view appliedWeight             #740 and main
    SSR streaming duplicate (#716)         #741 and #747

Eight repairs, done twice or three times.  #742 was pushed AFTER #740 merged
and does not contain it, so this is not a closed incident. Every individual collision was resolved sensibly —
the better-documented version was kept each time — but roughly a third of a
session's output was thrown away, and which version survived came down to
which branch happened to be mergeable first rather than which was better.

``ASSISTANT_COORDINATION.md`` already told everyone to branch and to pull
before starting. That was not the gap. The gap is that nothing tells you
**what someone else is currently touching**, and a branch you cannot see is
a branch you will duplicate.

WHAT THIS CHECKS
----------------
Two questions, both answerable in seconds:

1. Does ``docs/WORK_CLAIMS.md`` have an open claim overlapping the files or
   defect ids you are about to work on?
2. Do any *remote branches* — merged or not — already touch those files?
   Claims are voluntary and will be forgotten; branches are evidence.

WHAT IT DOES NOT DO
-------------------
It does not block anything. A collision is sometimes correct (two people
fixing different bugs in one file), and a gate that cries wolf gets ignored,
which is how the last one failed. This prints what it found and exits 0
unless you ask for ``--strict``.

USAGE
-----
    python scripts/check_work_claims.py --files src/api/faab_analytics.py ...
    python scripts/check_work_claims.py --defect C12 --defect W22-F001
    python scripts/check_work_claims.py --claim "FAAB budget regimes" \\
        --files src/api/faab_analytics.py --branch claude/my-session

Run it BEFORE writing code, not after. After is a merge conflict.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = REPO_ROOT / "docs" / "WORK_CLAIMS.md"

# Branches whose overlap is never interesting.
_IGNORED_BRANCH_RE = re.compile(r"^origin/(HEAD|main)$")


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return ""


def parse_claims() -> list[dict[str, str]]:
    """Read the claim table.  A malformed row is skipped, never fatal.

    The format is a markdown table on purpose: it has to be editable in the
    same commit as the work, readable in a PR diff, and mergeable without a
    tool.  A JSON registry would conflict on every concurrent claim, which
    is precisely the failure mode this is meant to reduce.
    """
    if not CLAIMS_PATH.exists():
        return []
    claims: list[dict[str, str]] = []
    for line in CLAIMS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        if cells[0].lower() in {"claim", "what"} or set(cells[0]) <= {"-", ":"}:
            continue
        claims.append(
            {
                "what": cells[0],
                "paths": cells[1],
                "defects": cells[2],
                "branch": cells[3],
                "status": cells[4].lower(),
            }
        )
    return claims


def branches_touching(paths: list[str], *, exclude: str | None) -> dict[str, list[str]]:
    """Remote branches whose diff against main touches any of ``paths``.

    Evidence beats self-report: this catches the session that never wrote a
    claim down, which — on the record above — is every session so far.
    """
    out: dict[str, list[str]] = {}
    raw = _git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
    for branch in (b.strip() for b in raw.splitlines() if b.strip()):
        if _IGNORED_BRANCH_RE.match(branch) or (exclude and branch.endswith(exclude)):
            continue
        base = _git("merge-base", "origin/main", branch).strip()
        if not base:
            continue
        changed = set(_git("diff", "--name-only", f"{base}..{branch}").split())
        hits = sorted(p for p in paths if p in changed)
        if hits:
            out[branch] = hits
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--files", nargs="*", default=[], help="paths you intend to change")
    ap.add_argument("--defect", action="append", default=[], help="defect id (C12, W22-F001, ...)")
    ap.add_argument("--claim", help="short description, for the suggested row")
    ap.add_argument("--branch", help="your branch, excluded from the overlap scan")
    ap.add_argument("--strict", action="store_true", help="exit 1 when something overlaps")
    args = ap.parse_args()

    if not args.files and not args.defect:
        ap.error("give --files and/or --defect — there is nothing to check otherwise")

    collided = False

    claims = parse_claims()
    open_claims = [c for c in claims if c["status"].startswith("open")]
    for c in open_claims:
        paths = [p.strip() for p in c["paths"].split(",") if p.strip()]
        defects = {d.strip().upper() for d in c["defects"].split(",") if d.strip()}
        path_hits = sorted(set(args.files) & set(paths))
        defect_hits = sorted({d.upper() for d in args.defect} & defects)
        if path_hits or defect_hits:
            collided = True
            print(f"OPEN CLAIM — {c['what']}  ({c['branch']})")
            if path_hits:
                print(f"    shared files:   {', '.join(path_hits)}")
            if defect_hits:
                print(f"    shared defects: {', '.join(defect_hits)}")

    if args.files:
        for branch, hits in branches_touching(args.files, exclude=args.branch).items():
            collided = True
            print(f"BRANCH ALREADY TOUCHES THESE — {branch}")
            print(f"    {', '.join(hits)}")

    if not collided:
        print("No overlapping claim or branch found.")
        if args.claim:
            paths = ", ".join(args.files) or "—"
            defects = ", ".join(args.defect) or "—"
            branch = args.branch or "<your-branch>"
            print("\nAdd this row to docs/WORK_CLAIMS.md in your first commit:\n")
            print(f"| {args.claim} | {paths} | {defects} | {branch} | open |")
        return 0

    print(
        "\nOverlap is not automatically wrong — two people can fix different "
        "bugs in one file.\nBut find out which it is BEFORE writing the code. "
        "After is a merge conflict, or worse,\ntwo correct implementations "
        "where the one that survives is whichever merged first."
    )
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
