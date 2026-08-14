#!/usr/bin/env python3
"""Fail when the canonical Chase Upside planning hierarchy drifts.

This is intentionally a structural guard, not a semantic parser. It makes new
planning work start from one front door, requires active owner-spec records to
stay reachable from the hierarchy, and requires known historical planning
records to remain classified instead of quietly becoming parallel roadmaps.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Core governance + active owner scope/spec records. These are not all equal
# kinds of authority: EXECUTION_PLAN alone authorizes current work. Their roles
# are defined in PLANNING_DOCUMENT_STATUS.md and MASTER_PRODUCT_PLAN.md.
ACTIVE = {
    "PRODUCT_PLAN.md",
    "docs/MASTER_PRODUCT_PLAN.md",
    "docs/EXECUTION_PLAN.md",
    "docs/PLANNING_DOCUMENT_STATUS.md",
    "docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md",
    "docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md",
    "docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md",
    "docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/OWNER_REQUESTED_TODO.md",
    "docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md",
    "docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md",
    "docs/PLAYER_IMPACT_WAR_MVP_SPEC.md",
    "docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md",
}

# Dated census/evidence that is deliberately preserved and explicitly
# classified as non-authorization material.
EVIDENCE = {
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/ARCHITECTURE_HANDOFF.md",
    "docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md",
}

KNOWN_HISTORICAL = {
    "UNIMPLEMENTED_BACKLOG.md",
    "docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md",
    "docs/SCOPE_COORDINATION_2026-08-11.md",
    "docs/master-site-audit/NEXT_STEPS.md",
    "docs/master-site-audit/REPAIR_ROADMAP.md",
    "docs/competitive/DYNASTY_DADDY_INTEGRATION_TODO.md",
    "docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md",
}

MASTER_REFERENCES_REQUIRED = {
    "docs/EXECUTION_PLAN.md",
    "docs/PLANNING_DOCUMENT_STATUS.md",
    "docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md",
    "docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md",
    "docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/OWNER_REQUESTED_TODO.md",
    "docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md",
}

POINTER_REFERENCES_REQUIRED = {
    "docs/MASTER_PRODUCT_PLAN.md",
    "docs/EXECUTION_PLAN.md",
    "docs/PLANNING_DOCUMENT_STATUS.md",
    "docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md",
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _contains_reference(text: str, rel: str) -> bool:
    # Accept either full repo-relative path or basename in prose/tables.
    return rel in text or Path(rel).name in text


def main() -> int:
    errors: list[str] = []

    for rel in sorted(ACTIVE | EVIDENCE | KNOWN_HISTORICAL):
        if not (ROOT / rel).exists():
            errors.append(f"missing planning record: {rel}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    master = _read("docs/MASTER_PRODUCT_PLAN.md")
    status = _read("docs/PLANNING_DOCUMENT_STATUS.md")
    sync = _read("docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md")
    pointer = _read("PRODUCT_PLAN.md")
    claude = _read("CLAUDE.md")

    for rel in sorted(MASTER_REFERENCES_REQUIRED):
        if not _contains_reference(master, rel):
            errors.append(f"master plan does not reference active record: {rel}")

    for rel in sorted(POINTER_REFERENCES_REQUIRED):
        if rel not in pointer:
            errors.append(f"root PRODUCT_PLAN.md does not point to {rel}")

    # Technical instructions must remain explicitly subordinate to the product
    # hierarchy; this catches the high-risk failure mode where CLAUDE.md becomes
    # a second roadmap after a later edit.
    for rel in (
        "PRODUCT_PLAN.md",
        "docs/MASTER_PRODUCT_PLAN.md",
        "docs/EXECUTION_PLAN.md",
        "docs/PLANNING_DOCUMENT_STATUS.md",
    ):
        if not _contains_reference(claude, rel):
            errors.append(f"CLAUDE.md does not reference canonical planning record: {rel}")

    for rel in sorted(ACTIVE | EVIDENCE | KNOWN_HISTORICAL):
        if rel == "docs/PLANNING_DOCUMENT_STATUS.md":
            continue
        if not _contains_reference(status, rel):
            errors.append(f"planning record is not classified in status map: {rel}")

    # The sync receipt must cover the active direction/spec layer and the main
    # evidence/historical classes. It may describe whole families rather than
    # literally listing every old dated capture.
    for rel in sorted(ACTIVE - {"docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md"}):
        if not _contains_reference(sync, rel):
            errors.append(f"active planning record missing from sync manifest: {rel}")

    # Prevent the easiest future failure mode: adding another obvious owner
    # TODO/addendum/roadmap snapshot without classifying it. Historical files
    # stay legal only because the authority map says they are historical.
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

    classified = ACTIVE | EVIDENCE | KNOWN_HISTORICAL
    for rel in sorted(candidate_paths - classified):
        errors.append(
            "unclassified planning-like document: "
            f"{rel} — reconcile it into the active hierarchy or classify it explicitly"
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("product-plan governance: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
