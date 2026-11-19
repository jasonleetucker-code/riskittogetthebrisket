#!/usr/bin/env python3
"""DRY RUN: which tracked paths would the recommended data-exposure policy move?

Read-only.  Moves, untracks and deletes NOTHING; prints counts, sizes and paths
only, never a value.  It sizes the staged migration in
``docs/security/DATA_EXPOSURE_POLICY_RECOMMENDATION_2026-11-19.md`` (STAB-7) so the
owner signs a decision with the numbers in front of them.  It reuses the detectors
in ``scripts/audit_tracked_data_exposure.py`` (the CI guard's owner), so the report
and the guard cannot disagree about what counts as paid-vendor data or an owner id.

Classes, first match wins:

``PROTECTED_STAY``      must stay tracked: ``data/scrape_state/`` (the refresh
                        commit stamps deploy dispatch keys on, CLAUDE.md W31-F001)
                        and ``data/sleeper_last_good.json``.  The script FAILS
                        (exit 3) if any proposed move overlaps this set.
``MOVE_PAID_VENDOR``    path names a vendor the inventory heuristically treats as
                        paid / account-gated (``is_paid_vendor_data_path``).
``MOVE_TERMS_FORBID``   FantasyPros: the only vendor whose terms were located
                        (2026-11-18) and they bar redistribution without written
                        permission.
``MOVE_OWNER_IDS``      outside ``config/`` and ``tests/``: carries owner/user-id
                        fields (detected inside zip members too).
``FIXTURE_OWNER_IDS``   ``tests/``: a fixture that carries owner/user-id fields
                        (pseudonymise in place; do not move).
``REVIEW_CONFIG``       ``config/`` files carrying owner/user-id fields (hand-edited,
                        reviewed; the Sleeper league id is accepted as public).
``UNVERIFIED_FREE``     a free/public vendor whose terms were NOT located.  Stays
                        tracked under the recommendation (explicit risk acceptance);
                        ``--include-unverified-free`` shows what moving them adds.
``OTHER_STAY``          everything else.

Usage::

    python scripts/report_data_policy_migration.py            # markdown
    python scripts/report_data_policy_migration.py --json
    python scripts/report_data_policy_migration.py --scan none   # path-only, seconds

``--scan owner-ids`` (default) opens in-scope non-vendor files to find owner ids and
takes about two minutes on the full tree; ``--scan none`` classifies by path only.

Exit: 0 report produced, 3 a proposed move overlaps a PROTECTED_STAY path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_tracked_data_exposure as audit  # noqa: E402

PROTECTED_PREFIXES = ("data/scrape_state/",)
PROTECTED_EXACT = ("data/sleeper_last_good.json",)

MOVE_CLASSES = ("MOVE_PAID_VENDOR", "MOVE_TERMS_FORBID", "MOVE_OWNER_IDS")
ALL_CLASSES = (
    "PROTECTED_STAY",
    *MOVE_CLASSES,
    "FIXTURE_OWNER_IDS",
    "REVIEW_CONFIG",
    "UNVERIFIED_FREE",
    "OTHER_STAY",
)

#: Free vendors whose terms were verified (2026-11-18 brief section 2) to bar redistribution.
TERMS_FORBID_VENDORS = ("FantasyPros",)


def is_protected(rel: str) -> bool:
    return rel in PROTECTED_EXACT or rel.startswith(PROTECTED_PREFIXES)


def _vendor_free(rel: str) -> str | None:
    """Free-vendor name for a data path (data extension, under a data root)."""
    if not rel.lower().endswith(audit.PAID_EXTS):
        return None
    if not rel.startswith(("CSVs/", "data/", "exports/")):
        return None
    vendor, paid = audit.vendor_of(rel)
    return vendor if vendor and not paid else None


def classify(rel: str, *, scan: bool, owner_ids=None) -> str:
    """Policy class for one tracked path.  ``owner_ids`` overrides the scan (tests)."""
    if is_protected(rel):
        return "PROTECTED_STAY"
    if audit.is_paid_vendor_data_path(rel):
        return "MOVE_PAID_VENDOR"
    free = _vendor_free(rel)
    if free in TERMS_FORBID_VENDORS:
        return "MOVE_TERMS_FORBID"
    if audit.in_scope(rel) and (scan or owner_ids is not None):
        has_ids = owner_ids if owner_ids is not None else audit.scan_file(rel)[0]["ownerIds"] > 0
        if has_ids:
            if rel.startswith("tests/"):
                return "FIXTURE_OWNER_IDS"
            if rel.startswith("config/"):
                return "REVIEW_CONFIG"
            return "MOVE_OWNER_IDS"
    if free:
        return "UNVERIFIED_FREE"
    return "OTHER_STAY"


def _size(rel: str) -> int:
    try:
        return os.stat(audit.REPO / rel).st_size
    except OSError:
        return 0


def group_of(rel: str) -> str:
    parts = rel.split("/")[:-1]  # the directory, never the file name
    if not parts:
        return "(repo root)"
    depth = 3 if parts[0] == "data" else 2
    return "/".join(parts[:depth]) + "/"


def build_report(
    files: list[str] | None = None, *, scan: bool = True, include_unverified_free: bool = False
) -> dict:
    files = audit.tracked_files() if files is None else files
    move_classes = set(MOVE_CLASSES)
    if include_unverified_free:
        move_classes.add("UNVERIFIED_FREE")
    counts: Counter = Counter()
    bytes_: Counter = Counter()
    groups: dict[str, Counter] = defaultdict(Counter)
    overlap: list[str] = []
    for rel in files:
        cls = classify(rel, scan=scan)
        counts[cls] += 1
        bytes_[cls] += _size(rel)
        groups[cls][group_of(rel)] += 1
        if cls in move_classes and is_protected(rel):  # defensive: classify() orders this out
            overlap.append(rel)
    moved = sum(counts[c] for c in move_classes)
    moved_bytes = sum(bytes_[c] for c in move_classes)
    return {
        "scan": "owner-ids" if scan else "none",
        "includeUnverifiedFree": include_unverified_free,
        "trackedFiles": len(files),
        "classes": {
            c: {
                "files": counts[c],
                "mb": round(bytes_[c] / 1e6, 1),
                "topGroups": [{"group": g, "files": n} for g, n in groups[c].most_common(8)],
            }
            for c in ALL_CLASSES
        },
        "wouldMove": {"files": moved, "mb": round(moved_bytes / 1e6, 1)},
        # `git rm --cached` is not "files kept on disk" on the box: deploy.sh runs
        # `reset --hard`, which deletes working-tree files that the target commit no
        # longer tracks.  So every moved path is a path the box LOSES unless the
        # private copy is preserved first (the plan's stage 6 gate).
        "boxLossOnResetHardUnlessPreserved": moved,
        "protectedOverlap": sorted(overlap),
    }


def to_markdown(rep: dict) -> str:
    out = [
        "# Data policy migration dry run (no file was moved, untracked or deleted)",
        "",
        f"Tracked files: {rep['trackedFiles']}.  Scan: `{rep['scan']}`.  "
        f"Unverified free sources counted as moves: {rep['includeUnverifiedFree']}.",
        "",
        "| Class | files | MB | largest path groups |",
        "|---|---:|---:|---|",
    ]
    for cls in ALL_CLASSES:
        row = rep["classes"][cls]
        tops = ", ".join(f"`{g['group']}` ({g['files']})" for g in row["topGroups"][:4]) or "-"
        out.append(f"| `{cls}` | {row['files']} | {row['mb']} | {tops} |")
    out += [
        "",
        f"**Would move: {rep['wouldMove']['files']} files, {rep['wouldMove']['mb']} MB.**  "
        f"The box would lose {rep['boxLossOnResetHardUnlessPreserved']} working-tree files on "
        "`reset --hard` unless preserved first.",
        f"Protected overlap: {len(rep['protectedOverlap'])} (must be 0).",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scan", choices=("owner-ids", "none"), default="owner-ids")
    ap.add_argument("--include-unverified-free", action="store_true")
    args = ap.parse_args(argv)
    rep = build_report(
        scan=args.scan == "owner-ids", include_unverified_free=args.include_unverified_free
    )
    sys.stdout.write(
        json.dumps(rep, indent=2, sort_keys=True) + "\n" if args.json else to_markdown(rep)
    )
    return 3 if rep["protectedOverlap"] else 0


if __name__ == "__main__":
    sys.exit(main())
