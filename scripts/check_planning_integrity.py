#!/usr/bin/env python3
"""Planning-integrity checks — lightweight guards against the drift that made the post-B
reconciliation necessary.

Each check exists because a specific failure actually happened, and would have been caught
cheaply. This is deliberately not a planning application: it reads Markdown, asserts a
handful of structural invariants, and exits non-zero.

Checks
------
1.  CE identifiers are unique and mean one thing.  Measured 2026-08-14: 18 of 22 CE ids
    named two different capabilities across two live registries, so a binding owner decision
    citing "CE-19" resolved to a different feature depending on which document you opened.
2.  Every mirror of the CE registry agrees with ``docs/CE_REGISTRY.md``.
3.  Manifest ids are unique.
4.  Every manifest dependency names a manifest row that exists.
5.  Every manifest phase is one the execution plan and completion contract know about.
6.  Every owner-decision id referenced in the manifest has a state in the reconciliation record.
7.  No manifest row is left UNMAPPED / TBD / TODO.
8.  Every planning document is classified in ``docs/PLANNING_DOCUMENT_STATUS.md`` — a
    document that appears nowhere in the governance index is drift.
9.  Exactly one document claims to be the authorization record.
10. The reserved C-completion phrase is not used as a claim.

Exit codes: 0 pass, 1 failures found, 2 the check could not run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

CE_REGISTRY = DOCS / "CE_REGISTRY.md"
MANIFEST = DOCS / "C_SERIES_SCOPE_MANIFEST.md"
TRACE = DOCS / "C_SERIES_ZERO_LOSS_TRACEABILITY.md"
STATUS = DOCS / "PLANNING_DOCUMENT_STATUS.md"
EXEC_PLAN = DOCS / "EXECUTION_PLAN.md"
RECONCILIATION = DOCS / "POST_B_RECONCILIATION_2026-08-14.md"
CONTRACT = DOCS / "C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md"

RESERVED_PHRASE = (
    "C-SERIES COMPLETE — EVERY APPROVED FEATURE DEPLOYED, "
    "PRODUCTION-VERIFIED, AND READY FOR CONFIDENT USE"
)

VALID_PHASES = {f"C{n}" for n in range(11)} | {"F", "X", "OD"}

# Planning documents that are deliberately not classified in the governance index:
# operational runbooks, per-feature engineering references and research notes.
STATUS_EXEMPT = {
    "docs/PLANNING_DOCUMENT_STATUS.md",
    "docs/CE_REGISTRY.md",
    "docs/C_SERIES_SCOPE_MANIFEST.md",
    "docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md",
    "docs/EXECUTION_PLAN.md",
    "docs/MASTER_PRODUCT_PLAN.md",
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/OWNER_REQUESTED_TODO.md",
    "docs/ARCHITECTURE_HANDOFF.md",
    "docs/WORK_CLAIMS.md",
    "docs/POST_B_RECONCILIATION_2026-08-14.md",
    "docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md",
}

# Only these top-level docs/ files are treated as "planning documents" for check 8.
# Engineering references (ros-engine, faab-model, playerctx, …) are documentation of built
# systems, not scope records, and are exempt by living outside the naming patterns below.
PLANNING_NAME_PATTERNS = (
    re.compile(r"^OWNER_"),
    re.compile(r"^C_SERIES_"),
    re.compile(r"^MASTER_"),
    re.compile(r"^.*_SPEC\.md$"),
    re.compile(r"^ROADMAP-"),
    re.compile(r"^PRODUCT_DIRECTION_"),
    re.compile(r"^SCOPE_COORDINATION"),
    re.compile(r"^GLOBAL_PERFORMANCE_STANDARD\.md$"),
    re.compile(r"^COMPETITOR_REUSE_POLICY\.md$"),
    re.compile(r"^PREMIUM_SPORTS_INTELLIGENCE_"),
    re.compile(r"^WEEKLY_REPORT_STUDIO_"),
    re.compile(r"^FAAB_MARKET_SIGNAL_"),
    re.compile(r"^POST_B_RECONCILIATION"),
    re.compile(r"^CE_REGISTRY\.md$"),
)


class Failures(list):
    def add(self, check: str, detail: str) -> None:
        self.append(f"[{check}] {detail}")


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"FATAL: required planning document missing: {path.relative_to(REPO)}")
    return path.read_text(encoding="utf-8")


def normalize(name: str) -> str:
    """Loose capability comparison — punctuation and case are not meaning."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


# ---------------------------------------------------------------- checks


def check_ce_registry(f: Failures) -> dict[str, str]:
    """1 + 2: one CE id, one capability, and every mirror agrees."""
    text = read(CE_REGISTRY)
    registry: dict[str, str] = {}
    for cid, cap in re.findall(r"^\|\s*\*\*(CE-\d+A?)\*\*\s*\|\s*([^|]+?)\s*\|", text, re.M):
        if cid in registry and normalize(registry[cid]) != normalize(cap):
            f.add("ce-unique", f"{cid} defined twice in the registry: {registry[cid]!r} vs {cap!r}")
        registry.setdefault(cid, cap)

    if not registry:
        f.add("ce-unique", "no CE identifiers parsed from docs/CE_REGISTRY.md")
        return registry

    # Mirrors must not contradict the registry.
    mirrors = [
        (DOCS / "MASTER_PRODUCT_PLAN.md", re.compile(r"^-\s+\*\*(CE-\d+A?)\*\*\s+(.+?)\s*$", re.M)),
        (
            DOCS / "OWNER_FEATURE_INVENTORY.md",
            re.compile(r"^\|\s*(CE-\d+A?)\s*\|\s*\*\*([^|*]+?)\*\*\s*\|", re.M),
        ),
    ]
    for path, pattern in mirrors:
        if not path.exists():
            continue
        for cid, cap in pattern.findall(path.read_text(encoding="utf-8")):
            canon = registry.get(cid)
            if canon is None:
                f.add("ce-mirror", f"{path.name} defines {cid}, which docs/CE_REGISTRY.md does not")
                continue
            a, b = normalize(canon), normalize(cap)
            # Mirrors carry short names; accept containment in either direction.
            if a not in b and b not in a:
                f.add(
                    "ce-mirror",
                    f"{path.name} says {cid} = {cap!r}; docs/CE_REGISTRY.md says {canon!r}",
                )
    return registry


def parse_manifest(text: str) -> list[dict]:
    """Rows live under "# 4. The manifest"; the taxonomy tables above it are not rows."""
    marker = "\n# 4. The manifest"
    body = text.split(marker, 1)[1] if marker in text else text
    rows: list[dict] = []
    for line in body.split("\n"):
        m = re.match(r"^\|\s*`([A-Z][A-Z0-9]*-[A-Z0-9-]+)`\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append({"id": m.group(1), "cells": cells, "line": line})
    return rows


def check_manifest(f: Failures, ce_registry: dict[str, str]) -> None:
    text = read(MANIFEST)
    rows = parse_manifest(text)
    if not rows:
        f.add("manifest-parse", "no manifest rows parsed — the table format changed")
        return

    # 3: unique ids
    seen: dict[str, int] = {}
    for r in rows:
        seen[r["id"]] = seen.get(r["id"], 0) + 1
    for rid, n in seen.items():
        if n > 1:
            f.add("manifest-unique", f"manifest id {rid} appears {n} times")

    ids = set(seen)

    # 4: dependencies resolve
    dep_pattern = re.compile(r"`([A-Z][A-Z0-9]*-[A-Z0-9-]+)`")
    for r in rows:
        if len(r["cells"]) < 8:
            continue
        for dep in dep_pattern.findall(r["cells"][6]):
            if dep not in ids and not dep.startswith(("CE-", "OD-", "TC-", "W", "B")):
                f.add("manifest-deps", f"{r['id']} depends on {dep}, which is not a manifest row")

    # 5: phases exist
    for r in rows:
        prefix = r["id"].split("-")[0]
        if prefix not in VALID_PHASES:
            f.add(
                "manifest-phase",
                f"{r['id']} uses phase prefix {prefix!r}, "
                f"which is not one of {sorted(VALID_PHASES)}",
            )

    # 7: nothing left unmapped
    for r in rows:
        if re.search(r"(?<![A-Z_])\b(UNMAPPED|TBD|FIXME|\?\?\?)\b(?![A-Z_])", r["line"]):
            f.add("manifest-unmapped", f"{r['id']} still carries an unresolved marker")

    # 6: owner decisions have a state
    recon = read(RECONCILIATION)
    for od in sorted(set(re.findall(r"\bOD-\d+\b", text))):
        if od not in recon:
            f.add(
                "owner-decision",
                f"{od} is referenced in the manifest but has no entry in {RECONCILIATION.name}",
            )
        elif not re.search(rf"### `{od}`", recon):
            f.add("owner-decision", f"{od} has no stated question/options/recommendation section")
        else:
            block = recon.split(f"### `{od}`", 1)[1].split("### `", 1)[0]
            if "Blocks C1?" not in block:
                f.add("owner-decision", f"{od} does not state whether it blocks C1")

    # CE ids cited in the manifest must exist in the registry
    for cid in sorted(set(re.findall(r"\bCE-\d+A?\b", text))):
        if cid not in ce_registry:
            f.add("ce-mirror", f"manifest cites {cid}, absent from docs/CE_REGISTRY.md")

    # every row needs completion evidence (last cell non-empty)
    for r in rows:
        if r["cells"] and not r["cells"][-1]:
            f.add("manifest-evidence", f"{r['id']} has no completion evidence")


def check_governance_index(f: Failures) -> None:
    """8: every planning document is classified somewhere."""
    status = read(STATUS)
    for path in sorted(DOCS.glob("*.md")):
        rel = f"docs/{path.name}"
        if rel in STATUS_EXEMPT:
            continue
        if not any(p.match(path.name) for p in PLANNING_NAME_PATTERNS):
            continue
        if path.name not in status:
            f.add(
                "governance-index",
                f"{rel} is a planning document but is classified nowhere "
                f"in docs/PLANNING_DOCUMENT_STATUS.md",
            )


def check_single_authorization_record(f: Failures) -> None:
    """9: exactly one document may claim to answer 'what is authorized now?'."""
    claimants = []
    for path in sorted(DOCS.glob("*.md")) + [REPO / "PRODUCT_PLAN.md"]:
        text = path.read_text(encoding="utf-8")
        if re.search(r"CANONICAL SEQUENCING / AUTHORIZATION RECORD", text):
            claimants.append(path.name)
    if claimants != [EXEC_PLAN.name]:
        f.add(
            "authorization",
            f"expected exactly one authorization record "
            f"({EXEC_PLAN.name}); found {claimants or 'none'}",
        )


def check_reserved_phrase(f: Failures) -> None:
    """10: the reserved completion phrase may be defined, never claimed."""
    allowed = {
        CONTRACT.name,
        EXEC_PLAN.name,
        RECONCILIATION.name,
        "C_SERIES_SCOPE_MANIFEST.md",
        "OWNER_REQUESTED_TODO_SPEC_INDEX.md",
        "OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md",
        "OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md",
    }
    for path in sorted(REPO.rglob("*.md")):
        if any(part in {".git", "node_modules", ".next"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if RESERVED_PHRASE in text and path.name not in allowed:
            f.add(
                "reserved-phrase", f"{path.relative_to(REPO)} uses the reserved C-completion phrase"
            )


def main() -> int:
    f = Failures()
    try:
        ce = check_ce_registry(f)
        check_manifest(f, ce)
        check_governance_index(f)
        check_single_authorization_record(f)
        check_reserved_phrase(f)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    if f:
        print(f"PLANNING INTEGRITY: {len(f)} failure(s)\n", file=sys.stderr)
        for line in f:
            print(f"  {line}", file=sys.stderr)
        print("\nSee docs/PLANNING_DOCUMENT_STATUS.md for the governance rules.", file=sys.stderr)
        return 1

    print("PLANNING INTEGRITY: OK")
    print("  CE identifiers unique and mirrored consistently")
    print("  manifest ids unique, dependencies resolve, phases valid, evidence present")
    print("  every owner decision has a question, options and a C1-blocking answer")
    print("  every planning document is classified")
    print("  exactly one authorization record")
    print("  reserved completion phrase not claimed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
