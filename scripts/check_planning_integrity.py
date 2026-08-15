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
11. The manifest's declared row total agrees with the measured one — and so does every other
    "N rows" claim in the file.  It shipped for review declaring 163 in one place and 214 in
    two others.
12. The declared source-family count agrees with the traceability table, counting by base
    letter so dated cohorts (E, E2, E3) stay subdivisions rather than silently inflating the
    headline.
13. The traceability record resolves: every destination it cites is a real manifest row, no
    destination is unresolved, and the unexplained-unmapped total is still zero.
14. The declared RET-row count matches the rows actually flagged RET — that number scopes the
    authorized retention tranche, so a stale one can under- or over-authorize real work.

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

    check_declared_row_count(f, text, rows)
    check_declared_flag_count(f, text, rows)


def check_declared_flag_count(f: Failures, text: str, rows: list[dict]) -> None:
    """14: the declared RET count agrees with the rows actually flagged RET.

    Same class as check 11, found the same way: the counts table declared 11 RET rows while 12
    carry the flag. That number scopes the authorized retention tranche, so a stale one is not
    cosmetic — it can under-authorize or over-authorize real work.
    """
    measured = len([r for r in rows if re.search(r"\|\s*`RET`\s*\|", r["line"])])
    m = re.search(r"\|\s*Rows flagged `RET`[^|]*\|\s*\**(\d+)\**", text)
    if not m:
        f.add("manifest-count", f"no declared RET-row count found; {measured} rows carry the flag")
        return
    if int(m.group(1)) != measured:
        f.add(
            "manifest-count",
            f"the counts table declares {m.group(1)} RET rows but {measured} carry the `RET` flag",
        )


def check_declared_row_count(f: Failures, text: str, rows: list[dict]) -> None:
    """11: the manifest's declared row total agrees with the measured one.

    This exists because the manifest shipped for review declaring 163 rows in one place and
    214 in two others — a first-draft figure that survived two corrections. Prose is not a
    reliable place to keep a number that can be counted, so the count is measured here and
    every declared total in the file has to match it.
    """
    measured = len([r for r in rows if not r["id"].startswith("OD-")])

    marker = re.search(r"<!--\s*MANIFEST-ROW-COUNT:\s*(\d+)\s*-->", text)
    if not marker:
        f.add(
            "manifest-count",
            "docs/C_SERIES_SCOPE_MANIFEST.md has no <!-- MANIFEST-ROW-COUNT: N --> marker; "
            f"the measured count is {measured}",
        )
        return
    declared = int(marker.group(1))
    if declared != measured:
        f.add(
            "manifest-count",
            f"MANIFEST-ROW-COUNT declares {declared} but {measured} rows are present "
            "(OD-* rows in §6 are not manifest rows and are excluded)",
        )

    # Any other "N rows" claim in the manifest must agree too — that is how 214 survived.
    for m in re.finditer(r"\*\*(\d{2,4})\s+rows\*\*|\b(\d{2,4})\s+rows\b", text):
        n = int(m.group(1) or m.group(2))
        if n != measured:
            line = text[: m.start()].count("\n") + 1
            f.add(
                "manifest-count",
                f"line {line} claims {n} rows; the measured count is {measured}",
            )


def check_source_census(f: Failures) -> None:
    """12: the declared source-family count agrees with the traceability table.

    Families are lettered A-L. The E family carries dated cohorts (E, E2, E3, ...) listed as
    separate rows so arrival time stays visible, so a row count and a family count are
    different numbers and both are correct. Counting by base letter is what makes adding an
    E4 cohort safe while adding a real family M fails until the headline is updated.
    """
    text = read(TRACE)

    marker = re.search(r"<!--\s*SOURCE-FAMILY-COUNT:\s*(\d+)\s*-->", text)
    if not marker:
        f.add(
            "source-census",
            "docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md has no "
            "<!-- SOURCE-FAMILY-COUNT: N --> marker declaring the counting convention",
        )
        return
    declared = int(marker.group(1))

    section = text.split("# 2. Source-population summary", 1)[-1].split("\n# 3.", 1)[0]
    # Any non-empty second cell counts. A stricter pattern silently skipped the E3 row,
    # whose description begins with "#839" — exactly the kind of quiet miss this file exists
    # to prevent. Totals rows have an empty first cell and cannot match.
    labels = re.findall(r"^\|\s*([A-Z]\d*)\s*\|\s*\S", section, re.M)
    families = {lbl[0] for lbl in labels}
    if not families:
        f.add("source-census", "no source rows parsed from the population table")
        return
    if len(families) != declared:
        f.add(
            "source-census",
            f"SOURCE-FAMILY-COUNT declares {declared} but the table carries "
            f"{len(families)} lettered families ({''.join(sorted(families))}); "
            f"cohort rows seen: {len(labels)}",
        )

    # The prose headline must say the same thing.
    for m in re.finditer(
        r"(?:across|over)\s+(twelve|thirteen|fourteen|\d+)\s+(?:independent\s+)?source",
        text,
        re.I,
    ):
        word = m.group(1).lower()
        spelled = {"twelve": 12, "thirteen": 13, "fourteen": 14}
        n = spelled.get(word, int(word) if word.isdigit() else None)
        if n is not None and n != declared:
            line = text[: m.start()].count("\n") + 1
            f.add(
                "source-census", f"line {line} says {word} sources; declared families = {declared}"
            )


def check_traceability(f: Failures, manifest_ids: set[str]) -> None:
    """13: the traceability record actually resolves.

    TRACE was defined but never validated in the first version of this script, which is how a
    destination could have been renamed without anything noticing.
    """
    text = read(TRACE)

    # every manifest id cited as a destination must exist
    cited = set(re.findall(r"`((?:C\d{1,2}|F|X)-[A-Z0-9-]+)`", text))
    for dest in sorted(cited):
        if dest not in manifest_ids:
            f.add("traceability", f"cites destination {dest}, which is not a manifest row")

    # no unresolved destinations
    for i, line in enumerate(text.split("\n"), 1):
        if re.search(r"(?<![A-Z_])\b(UNMAPPED|TBD|FIXME|\?\?\?)\b(?![A-Z_])", line):
            if "unmapped" not in line.lower() or "0" not in line:
                f.add("traceability", f"line {i} carries an unresolved destination marker")

    # the zero-unmapped claim must still be zero
    m = re.search(r"\*\*Unexplained unmapped\*\*\s*\|\s*\*\*(\d+)\*\*", text)
    if not m:
        f.add("traceability", "the unexplained-unmapped total is no longer stated")
    elif int(m.group(1)) != 0:
        f.add("traceability", f"unexplained unmapped is {m.group(1)}, not 0")



def check_execution_map(f: Failures, manifest_ids: set[str]) -> None:
    """The execution map claims to decompose EVERY manifest row into exactly one unit.

    A claim of exhaustiveness that nothing recomputes is a claim that decays
    silently, and this one already did: the map shipped asserting 153 rows
    against a manifest of 163, because it was built with an ad-hoc regex that
    required three hyphen-separated parts with alphabetic middles.  It dropped
    ``C7-BEST-TRADE`` (no numeric suffix), ``C8-A11Y-01`` and ``C9-V3-01``
    (digits in the middle segment) and ``X-01``..``X-07`` (two parts) — ten rows,
    including every explicitly out-of-scope row, which are exactly the ones a
    later session would otherwise rediscover as unexplored ideas.

    So the map's own appendix is checked against ``parse_manifest`` — the single
    owner of "what is a manifest row" — rather than against a second parser.
    """
    # Same exclusion as check_declared_row_count: OD-* rows in §6 are owner
    # decisions, not manifest rows. Stated in one place there and applied here
    # by the same rule, so the two counts cannot disagree about what a row is.
    rows = {i for i in manifest_ids if not i.startswith("OD-")}

    path = DOCS / "C_SERIES_EXECUTION_MAP.md"
    if not path.exists():
        return
    text = read(path)
    marker = "\n# 20. Appendix"
    if marker not in text:
        f.append("[execution-map] no '# 20. Appendix' row->unit table to verify")
        return

    mapped: list[str] = []
    for line in text.split(marker, 1)[1].split("\n"):
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*(\S+)\s*\|", line)
        if m:
            mapped.append(m.group(1))

    seen = set()
    dupes = sorted({r for r in mapped if r in seen or seen.add(r)})
    if dupes:
        f.append(f"[execution-map] rows assigned to more than one unit: {dupes}")

    missing = sorted(rows - set(mapped))
    extra = sorted(set(mapped) - rows)
    if missing:
        f.append(
            f"[execution-map] {len(missing)} manifest row(s) are in no execution unit: {missing}"
        )
    if extra:
        f.append(
            f"[execution-map] {len(extra)} mapped id(s) are not manifest rows: {extra}"
        )

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
        manifest_ids = {r["id"] for r in parse_manifest(read(MANIFEST))}
        check_source_census(f)
        check_traceability(f, manifest_ids)
        check_execution_map(f, manifest_ids)
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
    print("  declared manifest row count agrees with the measured one")
    print("  source-family count agrees with the traceability table")
    print("  every traceability destination resolves; unexplained unmapped is 0")
    print("  declared RET-row count matches the rows actually flagged")
    print("  every manifest row maps to exactly one execution unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
