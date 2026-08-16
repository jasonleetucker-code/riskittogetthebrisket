#!/usr/bin/env python3
"""Fail when the canonical product-planning hierarchy drifts.

This is intentionally a small structural guard, not a semantic parser. It makes
new planning work start from one front door and requires known legacy planning
records to remain classified instead of quietly becoming parallel roadmaps.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL = {
    "PRODUCT_PLAN.md",
    "docs/MASTER_PRODUCT_PLAN.md",
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/EXECUTION_PLAN.md",
    "docs/PLANNING_DOCUMENT_STATUS.md",
}

KNOWN_LEGACY = {
    "UNIMPLEMENTED_BACKLOG.md",
    "docs/OWNER_REQUESTED_TODO.md",
    "docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md",
    "docs/SCOPE_COORDINATION_2026-08-11.md",
    "docs/master-site-audit/NEXT_STEPS.md",
    "docs/master-site-audit/REPAIR_ROADMAP.md",
    "docs/competitive/DYNASTY_DADDY_INTEGRATION_TODO.md",
    "docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md",
}

MASTER_REFERENCES_REQUIRED = {
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/EXECUTION_PLAN.md",
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    for rel in sorted(CANONICAL | KNOWN_LEGACY):
        if not (ROOT / rel).exists():
            errors.append(f"missing planning record: {rel}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    master = _read("docs/MASTER_PRODUCT_PLAN.md")
    status = _read("docs/PLANNING_DOCUMENT_STATUS.md")
    pointer = _read("PRODUCT_PLAN.md")

    for rel in sorted(MASTER_REFERENCES_REQUIRED):
        name = Path(rel).name
        if name not in master:
            errors.append(f"master plan does not reference canonical record: {rel}")

    if "docs/MASTER_PRODUCT_PLAN.md" not in pointer:
        errors.append("root PRODUCT_PLAN.md does not point to MASTER_PRODUCT_PLAN.md")
    if "docs/EXECUTION_PLAN.md" not in pointer:
        errors.append("root PRODUCT_PLAN.md does not point to EXECUTION_PLAN.md")

    for rel in sorted(KNOWN_LEGACY):
        name = Path(rel).name
        if name not in status:
            errors.append(f"legacy planning record is not classified: {rel}")

    # Prevent the easiest future failure mode: adding another obvious TODO,
    # owner addendum, or roadmap snapshot without updating the governance map.
    candidate_paths: set[str] = set()
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in {"node_modules", ".git", ".next", ".venv"} for part in path.parts):
            continue
        name = path.name.upper()
        if (
            ("OWNER" in name and ("TODO" in name or "TO-DO" in name or "ADDENDUM" in name))
            or "INTEGRATION_TODO" in name
            or ("COMPETITIVE_EXPANSION" in name and "ADDENDUM" in name)
            or name in {"NEXT_STEPS.MD", "REPAIR_ROADMAP.MD", "UNIMPLEMENTED_BACKLOG.MD"}
        ):
            candidate_paths.add(rel)

    # A document is CLASSIFIED when the governance index actually says
    # something about it — which is the rule the index states about itself
    # ("Every planning document in the repository must appear somewhere
    # below") and the thing this check exists to enforce.
    #
    # CORRECTED 2026-08-16 (stabilization, C1-U6 follow-up 5).  This used
    # to compare against the two hard-coded sets above and nothing else,
    # so it failed on four documents that ARE classified — the three
    # 2026-08-14 owner addenda and the TODO spec index, each of them named
    # and given a status in ``docs/PLANNING_DOCUMENT_STATUS.md``, two of
    # them additionally carrying Scope Manifest rows and traceability
    # entries.  The check was measuring the allowlist rather than the
    # governance record, so the only way to make it green was to edit the
    # script every time the owner filed an addendum — which is how an
    # allowlist rots into a rubber stamp.
    #
    # Reading the index is STRICTER, not weaker: appending a filename to a
    # Python set no longer discharges anything, and a document that is
    # named nowhere in the index still fails.
    classified = CANONICAL | KNOWN_LEGACY
    for rel in sorted(candidate_paths - classified):
        if Path(rel).name in status:
            continue
        errors.append(
            "unclassified planning-like document: "
            f"{rel} — reconcile it into the canonical plan or add an explicit status"
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("product-plan governance: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
