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

A row counts as OPEN when its status begins with ``open`` or one of the
in-flight spellings the table actually uses (``active``, ``in progress``,
``pending``, ``FEATURE_GREEN``, ``implemented``, ``reviewed``, ``routed``),
and as finished when it begins with ``done``, ``merged``, ``closed``,
``stale`` or ``superseded``.  Until 2026-10-07 only ``open`` was recognised,
so 47 in-flight-sounding rows were invisible to this check while the only
two rows it did see were both long merged.

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
    python scripts/check_work_claims.py --list-open     # audit: every open row

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

#: A row is OPEN when its status BEGINS with one of these (case-insensitive,
#: after leading markdown emphasis/backticks are stripped).
OPEN_STATUS_PREFIXES = (
    "open",
    "active",
    "in progress",
    "in-progress",
    "pending",
    "feature_green",
    "implemented",
    "reviewed",
    "routed",
)
#: A status beginning with any of these is finished, whatever follows.
CLOSED_STATUS_PREFIXES = ("done", "merged", "closed", "stale", "superseded")

_BACKTICK_RE = re.compile(r"`([^`]+)`")


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


def normalize_status(status: str) -> str:
    """Lower-case a status cell and strip LEADING markdown emphasis/backticks.

    Only the front is stripped, so ``FEATURE_GREEN`` keeps its underscore.
    """
    return status.strip().lower().lstrip("*`_~ ")


def is_open_status(status: str) -> bool:
    """True when a claim row's status says the work is still in flight."""
    text = normalize_status(status)
    if text.startswith(CLOSED_STATUS_PREFIXES):
        return False
    return text.startswith(OPEN_STATUS_PREFIXES)


def _split(body: str, *, respect_code: bool) -> tuple[list[str], bool]:
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not (respect_code and in_code):
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells, in_code


def split_row(line: str) -> list[str]:
    r"""Split one markdown table row on UNESCAPED pipes outside code spans.

    ``\|`` is a literal pipe inside a cell, so it must not shift the cells
    after it — an escaped pipe in a claim used to turn a path fragment into
    that row's "status".  Rows here also quote things like ``a | b`` inside
    backticks; those pipes are kept in the cell too.  If the row's backticks
    do not balance, code spans cannot be trusted and every unescaped pipe
    splits.
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, unbalanced = _split(body, respect_code=True)
    if unbalanced:
        cells, _ = _split(body, respect_code=False)
    return cells


def parse_claim_text(text: str) -> list[dict[str, str]]:
    """Parse claim rows out of markdown text.  Malformed rows are skipped.

    Columns are read from the END of the row: the trailing cells (defect ids,
    branch, status) are short, while the claim and paths cells are long prose
    that occasionally carries a stray pipe.  A row with more than five cells
    folds the surplus into ``paths``; a four-cell row (an older shape with no
    separate paths column) uses its second cell for both paths and defect ids;
    anything shorter is not a claim row.
    """
    claims: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = split_row(line)
        if len(cells) < 4:
            continue
        if cells[0].lower() in {"claim", "what"} or set(cells[0]) <= {"-", ":", " "}:
            continue
        if len(cells) == 4:
            what, middle, branch, status = cells
            paths = defects = middle
        else:
            what = cells[0]
            paths = " | ".join(cells[1:-3])
            defects, branch, status = cells[-3], cells[-2], cells[-1]
        claims.append(
            {
                "what": what,
                "paths": paths,
                "defects": defects,
                "branch": branch,
                "status": normalize_status(status),
            }
        )
    return claims


def parse_claims(path: Path | None = None) -> list[dict[str, str]]:
    """Read the claim table.  A malformed row is skipped, never fatal.

    The format is a markdown table on purpose: it has to be editable in the
    same commit as the work, readable in a PR diff, and mergeable without a
    tool.  A JSON registry would conflict on every concurrent claim, which
    is precisely the failure mode this is meant to reduce.
    """
    path = CLAIMS_PATH if path is None else path
    if not path.exists():
        return []
    return parse_claim_text(path.read_text(encoding="utf-8"))


def claim_paths(cell: str) -> set[str]:
    """Every path a claim's Paths cell names.

    Cells are written as backticked paths with annotations, e.g. a path
    followed by "(call site only)".  A bare comma split compared that
    decorated text against the plain path and never matched, so take every
    backticked token plus every comma-separated item with backticks and a
    trailing parenthetical removed.
    """
    out = {m.strip() for m in _BACKTICK_RE.findall(cell) if m.strip()}
    for piece in cell.split(","):
        item = piece.replace("`", "").strip().split(" (", 1)[0].strip()
        if item:
            out.add(item)
    return out


def claim_defects(cell: str) -> set[str]:
    return {d.replace("`", "").strip().upper() for d in cell.split(",") if d.strip()}


def open_claims(claims: list[dict[str, str]]) -> list[dict[str, str]]:
    return [c for c in claims if is_open_status(c["status"])]


def overlapping_claims(
    claims: list[dict[str, str]], files: list[str], defects: list[str]
) -> list[tuple[dict[str, str], list[str], list[str]]]:
    """Open claims sharing a file or defect id with the request."""
    wanted_defects = {d.upper() for d in defects}
    out = []
    for c in open_claims(claims):
        path_hits = sorted(set(files) & claim_paths(c["paths"]))
        defect_hits = sorted(wanted_defects & claim_defects(c["defects"]))
        if path_hits or defect_hits:
            out.append((c, path_hits, defect_hits))
    return out


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--files", nargs="*", default=[], help="paths you intend to change")
    ap.add_argument("--defect", action="append", default=[], help="defect id (C12, W22-F001, ...)")
    ap.add_argument("--claim", help="short description, for the suggested row")
    ap.add_argument("--branch", help="your branch, excluded from the overlap scan")
    ap.add_argument("--strict", action="store_true", help="exit 1 when something overlaps")
    ap.add_argument(
        "--list-open",
        action="store_true",
        help="print every row the checker treats as open (for audits) and exit 0",
    )
    ap.add_argument(
        "--claims-file",
        type=Path,
        help="read this claims file instead of docs/WORK_CLAIMS.md (skips the branch scan)",
    )
    ap.add_argument(
        "--no-branch-scan", action="store_true", help="skip the remote-branch overlap scan"
    )
    args = ap.parse_args(argv)

    claims = parse_claims(args.claims_file)

    if args.list_open:
        rows = open_claims(claims)
        for c in rows:
            print(f"{c['branch']}  |  {c['status'][:80]}  |  {c['what'][:100]}")
        print(f"\n{len(rows)} open of {len(claims)} parsed claim rows.")
        return 0

    if not args.files and not args.defect:
        ap.error("give --files and/or --defect — there is nothing to check otherwise")

    collided = False

    for c, path_hits, defect_hits in overlapping_claims(claims, args.files, args.defect):
        collided = True
        print(f"OPEN CLAIM — {c['what']}  ({c['branch']})")
        if path_hits:
            print(f"    shared files:   {', '.join(path_hits)}")
        if defect_hits:
            print(f"    shared defects: {', '.join(defect_hits)}")

    if args.files and not (args.claims_file or args.no_branch_scan):
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
