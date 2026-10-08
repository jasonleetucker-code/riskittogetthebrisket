#!/usr/bin/env python3
"""Calculator completion ledger — assemble, validate and render the dashboard.

Owner directive 2026-10-07 ("FINISH THE CALCULATOR SITE"): every live Calculator
requirement resolves to exactly ONE ledger row with exactly ONE disposition,
using the repository's existing canonical IDs. This script is the single owner
of that dashboard; it creates no new requirement taxonomy.

Inputs  : docs/completion/families/*.json  (one evidence file per audit family)
Outputs : docs/completion/CALCULATOR_COMPLETION_DASHBOARD.md  (rendered dashboard, committed)
          --json PATH  writes the merged, machine-readable ledger (regenerable; not committed)

Checks (exit 1 on failure, so CI can run ``--check``):
  * every disposition is in the closed enum;
  * no requirement id appears twice (ids and aliases are one namespace per row);
  * every C-Series manifest row id (docs/C_SERIES_SCOPE_MANIFEST.md §4) resolves to
    exactly one ledger row (as its id, an alias, or an ``<ID>/<member>`` split);
  * every ``dependsOn`` target exists;
  * every non-complete row carries a nextAction or a blocker;
  * OWNER_ACTION_REQUIRED / EXTERNAL rows carry a structured blocker.

Completion is REQUIREMENT-WEIGHTED (row ``weight`` 1/2/3), never an issue count.
The ledger is evidence, not authorization: ``docs/EXECUTION_PLAN.md`` authorizes.

Usage:
    python scripts/completion_ledger.py            # assemble + write outputs
    python scripts/completion_ledger.py --check    # validate committed outputs are current
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAMILY_DIR = REPO / "docs" / "completion" / "families"
OUT_MD = REPO / "docs" / "completion" / "CALCULATOR_COMPLETION_DASHBOARD.md"
MANIFEST = REPO / "docs" / "C_SERIES_SCOPE_MANIFEST.md"

DISPOSITIONS = (
    "COMPLETE_AND_PROVEN",
    "IMPLEMENTED_NOT_INTEGRATED",
    "INTEGRATED_NOT_DEPLOYED",
    "DEPLOYED_NOT_PRODUCTION_VERIFIED",
    "PARTIAL",
    "AUTHORIZED_AND_READY",
    "DEPENDENCY_BLOCKED",
    "OWNER_ACTION_REQUIRED",
    "EXTERNAL_DATA_OR_PROVIDER_BLOCKED",
    "INTENTIONALLY_FUTURE",
    "SUPERSEDED",
    "REJECTED",
    "NOT_ACTUALLY_REQUIRED",
)
# Removed from the active completion denominator (truthful final dispositions).
OUT_OF_DENOMINATOR = {"INTENTIONALLY_FUTURE", "SUPERSEDED", "REJECTED", "NOT_ACTUALLY_REQUIRED"}
COMPLETE = {"COMPLETE_AND_PROVEN"}
BLOCKED = {"DEPENDENCY_BLOCKED"}
OWNER = {"OWNER_ACTION_REQUIRED"}
EXTERNAL = {"EXTERNAL_DATA_OR_PROVIDER_BLOCKED"}
# Everything else in the denominator is engineering-actionable (ACTIVE).

# The product families the 2026-10-07 completion directive verifies family by family.
# First matching rule wins; the auditor's own label is kept on the row as ``auditFamily``.
CANONICAL_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Out of scope", ("out of scope",)),
    ("DFS", ("dfs",)),
    ("Rookie Auction", ("auction",)),
    (
        "Adaptive Learning & Model Lab",
        ("adaptive learning", "model governance", "hill", "model lab"),
    ),
    ("Premium UI, mobile & accessibility", ("premium ui", "accessibility", "mobile")),
    ("Performance", ("performance",)),
    ("Security & auth", ("security", "auth")),
    ("Game Day", ("game day",)),
    ("Power, schedule & playoff odds", ("power", "schedule", "playoff")),
    ("Awards, public league & reports", ("award", "public league", "report")),
    ("Projections & BDVM", ("projection", "bdvm", "scoring")),
    ("Analyst & manager intelligence", ("analyst", "manager intelligence")),
    ("Sharp & market evidence", ("sharp", "market")),
    ("Waivers & FAAB", ("waiver", "faab")),
    ("Draft capital & picks", ("pick", "draft")),
    ("Team strength & rosters", ("roster", "team strength")),
    ("Trade", ("trade",)),
    ("Player File & explainability", ("player file", "explainab", "valuation display")),
    ("Rankings, sources & valuation", ("ranking", "source", "valuation", "identity", "history")),
    ("Decision products", ("decision products", "competitive expansion")),
    (
        "Delivery, governance & data",
        (
            "ci",
            "deploy",
            "governance",
            "contract",
            "evidence retention",
            "data durability",
            "site-wide closure",
            "residue",
        ),
    ),
)


def canonical_family(label: str | None) -> str:
    low = str(label or "").lower()
    for name, keys in CANONICAL_FAMILIES:
        if any(k in low for k in keys):
            return name
    return "Delivery, governance & data"


_MANIFEST_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9]*-[A-Za-z0-9-]+)`\s*\|", re.M)


def manifest_ids(text: str) -> list[str]:
    body = text.split("# 4. The manifest", 1)[-1].split("# 5. Counts", 1)[0]
    return sorted(set(_MANIFEST_ROW.findall(body)))


def load_overrides(family_dir: Path) -> list[dict]:
    """Coordinator overrides: ``{"overrides": [{"id": ..., "reason": ..., <fields>}]}``
    in any family file. Applied AFTER reconciliation so a status change (e.g. a PR
    merged after the audit) is an explicit, attributed edit, never a silent one."""
    out: list[dict] = []
    for path in sorted(family_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for ov in data.get("overrides") or []:
            out.append({**ov, "_file": path.name})
    return out


def apply_overrides(rows: list[dict], overrides: list[dict]) -> list[str]:
    errors: list[str] = []
    index = {str(r.get("id")): r for r in rows}
    for r in rows:
        for a in r.get("aliases") or []:
            index.setdefault(str(a), r)
    for ov in overrides:
        target = index.get(str(ov.get("id")))
        if target is None:
            errors.append(f"override for unknown id {ov.get('id')!r} ({ov.get('_file')})")
            continue
        if not ov.get("reason"):
            errors.append(f"override for {ov.get('id')} has no reason")
        changes = {k: v for k, v in ov.items() if k not in ("id", "reason", "_file")}
        before = {k: target.get(k) for k in changes}
        target.update(changes)
        target.setdefault("coordinatorOverrides", []).append(
            {
                "reason": ov.get("reason"),
                "file": ov.get("_file"),
                "changed": sorted(changes),
                "before": {k: before[k] for k in ("disposition",) if k in before},
            }
        )
    return errors


def load_families(family_dir: Path) -> tuple[list[dict], list[dict]]:
    meta, rows = [], []
    for path in sorted(family_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta.append(
            {
                "file": path.name,
                "family": data.get("family"),
                "auditedAt": data.get("auditedAt"),
                "mainSha": data.get("mainSha"),
                "rows": len(data.get("rows") or []),
            }
        )
        for row in data.get("rows") or []:
            rows.append({**row, "_familyFile": path.name})
    return meta, rows


# Conservative order: when audits disagree about ONE requirement, the least-complete
# disposition wins (a gate beats "ready", "ready" beats "complete"), and the
# disagreement is recorded on the row, never silently dropped.
_CONSERVATIVE_ORDER = (
    "OWNER_ACTION_REQUIRED",
    "EXTERNAL_DATA_OR_PROVIDER_BLOCKED",
    "DEPENDENCY_BLOCKED",
    "AUTHORIZED_AND_READY",
    "PARTIAL",
    "IMPLEMENTED_NOT_INTEGRATED",
    "INTEGRATED_NOT_DEPLOYED",
    "DEPLOYED_NOT_PRODUCTION_VERIFIED",
    "COMPLETE_AND_PROVEN",
    "INTENTIONALLY_FUTURE",
    "SUPERSEDED",
    "REJECTED",
    "NOT_ACTUALLY_REQUIRED",
)


def reconcile(rows: list[dict], manifest: list[str]) -> list[dict]:
    """Merge rows that describe ONE requirement (same id, or an alias equal to
    another row's id) into a single row. The manifest id is the primary id when
    one is involved; otherwise the first row's id (stable file order)."""
    manifest_set = set(manifest)
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_id: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_id[str(r.get("id"))].append(i)
    for i, r in enumerate(rows):
        for key in [str(r.get("id")), *[str(a) for a in (r.get("aliases") or [])]]:
            for j in by_id.get(key, []):
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(i)
    merged: list[dict] = []
    for members in groups.values():
        if len(members) == 1:
            merged.append(rows[members[0]])
            continue
        group = [rows[i] for i in members]
        primary = next((r for r in group if r.get("id") in manifest_set), group[0])
        chosen = min(
            group,
            key=lambda r: _CONSERVATIVE_ORDER.index(r["disposition"])
            if r.get("disposition") in _CONSERVATIVE_ORDER
            else -1,
        )
        out = dict(primary)
        out["disposition"] = chosen["disposition"]
        for field in ("nextAction", "blocker", "reality", "evidence", "prOrBranch"):
            out[field] = (
                chosen.get(field)
                or primary.get(field)
                or next((r.get(field) for r in group if r.get(field)), None)
            )
        aliases = set()
        for r in group:
            aliases.add(str(r.get("id")))
            aliases.update(str(a) for a in (r.get("aliases") or []))
        aliases.discard(str(out["id"]))
        out["aliases"] = sorted(aliases)
        out["weight"] = max(int(r.get("weight") or 1) for r in group)
        deps = []
        for r in group:
            for d in r.get("dependsOn") or []:
                if d not in deps and d != out["id"]:
                    deps.append(d)
        out["dependsOn"] = deps
        out["mergedFrom"] = [
            f"{r.get('id')} ({r.get('_familyFile')}: {r.get('disposition')})" for r in group
        ]
        dispositions = {r.get("disposition") for r in group}
        if len(dispositions) > 1:
            out["dispositionConflict"] = (
                "audits disagreed: "
                + ", ".join(sorted(dispositions))
                + f"; conservative choice {out['disposition']}"
            )
        merged.append(out)
    return merged


_ID_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9]*[-_]")


def _dep_resolves(dep: str, ids: set[str], covered: set[str]) -> bool:
    d = re.sub(r"\s*\(.*?\)\s*$", "", str(dep)).strip()
    if not d or d.startswith("#") or d == "*" or not _ID_LIKE.match(d):
        return True  # a PR/issue reference or free-text note, not a requirement id
    if d.endswith("/*"):
        prefix = d[:-2]
        return any(i == prefix or i.startswith(prefix + "/") for i in ids)
    return d in ids or d in covered or any(i.startswith(d + "/") for i in ids)


def validate(rows: list[dict], manifest: list[str]) -> list[str]:
    errors: list[str] = []
    owner_of: dict[str, str] = {}
    for row in rows:
        rid = str(row.get("id") or "").strip()
        if not rid:
            errors.append(f"{row.get('_familyFile')}: row without id")
            continue
        if row.get("disposition") not in DISPOSITIONS:
            errors.append(f"{rid}: disposition {row.get('disposition')!r} not in enum")
        for name in [rid, *[str(a) for a in (row.get("aliases") or [])]]:
            key = name.strip()
            owner_of.setdefault(key, rid)
        ids_seen = Counter(r.get("id") for r in rows)
        if ids_seen[rid] > 1:
            errors.append(f"{rid}: duplicate row id ({ids_seen[rid]}x)")
        disp = row.get("disposition")
        explained = (
            row.get("nextAction")
            or row.get("blocker")
            or (disp in BLOCKED and row.get("dependsOn"))
        )
        if disp not in COMPLETE | OUT_OF_DENOMINATOR and not explained:
            errors.append(f"{rid}: non-complete row has neither nextAction nor blocker")
        if disp in OWNER | EXTERNAL and not isinstance(row.get("blocker"), dict):
            errors.append(f"{rid}: {disp} row needs a structured blocker")
        if row.get("weight") not in (1, 2, 3):
            errors.append(f"{rid}: weight must be 1, 2 or 3")
    all_ids = {r.get("id") for r in rows}
    covered = set(owner_of)
    for row in rows:
        for dep in row.get("dependsOn") or []:
            if not _dep_resolves(dep, all_ids, covered):
                errors.append(f"{row.get('id')}: dependsOn {dep!r} does not resolve")
    for mid in manifest:
        hits = {owner_of[mid]} if mid in owner_of else set()
        hits |= {r["id"] for r in rows if str(r.get("id", "")).startswith(mid + "/")}
        if not hits:
            errors.append(f"manifest row {mid} has no ledger row")
    return sorted(set(errors))


def summarize(rows: list[dict]) -> dict:
    def bucket(disp: str) -> str:
        if disp in OUT_OF_DENOMINATOR:
            return "outOfDenominator"
        if disp in COMPLETE:
            return "complete"
        if disp in OWNER:
            return "ownerAction"
        if disp in EXTERNAL:
            return "externalWait"
        if disp in BLOCKED:
            return "dependencyBlocked"
        return "active"

    fam: dict[str, Counter] = defaultdict(Counter)
    fam_w: dict[str, Counter] = defaultdict(Counter)
    total, total_w = Counter(), Counter()
    by_disp = Counter()
    for r in rows:
        b = bucket(r["disposition"])
        f = str(r.get("productFamily") or "unassigned")
        w = int(r.get("weight") or 1)
        fam[f][b] += 1
        fam_w[f][b] += w
        total[b] += 1
        total_w[b] += w
        by_disp[r["disposition"]] += 1

    def pct(c: Counter) -> float | None:
        denom = sum(v for k, v in c.items() if k != "outOfDenominator")
        return round(100.0 * c["complete"] / denom, 1) if denom else None

    return {
        "rows": len(rows),
        "byDisposition": dict(sorted(by_disp.items())),
        "rowBuckets": dict(total),
        "weightedBuckets": dict(total_w),
        "weightedCompletionPct": pct(total_w),
        "families": {
            f: {
                "rows": dict(fam[f]),
                "weighted": dict(fam_w[f]),
                "weightedCompletionPct": pct(fam_w[f]),
            }
            for f in sorted(fam)
        },
    }


def _owner_asks(family_dir: Path | None = None) -> list[dict]:
    out: list[dict] = []
    for path in sorted((family_dir or FAMILY_DIR).glob("*.json")):
        out.extend(json.loads(path.read_text(encoding="utf-8")).get("ownerAsks") or [])
    return out


def render(meta: list[dict], rows: list[dict], summary: dict) -> str:
    L: list[str] = []
    L.append("# Calculator completion dashboard")
    L.append("")
    L.append(
        "Generated by `scripts/completion_ledger.py` from the evidence files in "
        "`docs/completion/families/`. **Do not edit by hand** — edit the family file and "
        "re-run. This is an evidence record, not authorization (`docs/EXECUTION_PLAN.md` "
        "authorizes). Completion is requirement-weighted (row weight 1/2/3), not an issue count."
    )
    L.append("")
    wb = summary["weightedBuckets"]
    rb = summary["rowBuckets"]
    L.append("## Totals")
    L.append("")
    L.append("| | rows | weight |")
    L.append("|---|---:|---:|")
    labels = [
        ("TOTAL REQUIRED (in denominator)", None),
        ("COMPLETE", "complete"),
        ("ACTIVE (engineering-actionable)", "active"),
        ("BLOCKED (dependency)", "dependencyBlocked"),
        ("OWNER ACTION", "ownerAction"),
        ("EXTERNAL WAIT", "externalWait"),
        ("FUTURE / SUPERSEDED / REJECTED / NOT REQUIRED (outside denominator)", "outOfDenominator"),
    ]
    for label, key in labels:
        if key is None:
            r = sum(v for k, v in rb.items() if k != "outOfDenominator")
            w = sum(v for k, v in wb.items() if k != "outOfDenominator")
        else:
            r, w = rb.get(key, 0), wb.get(key, 0)
        L.append(f"| {label} | {r} | {w} |")
    L.append("")
    L.append(
        f"**Weighted completion: {summary['weightedCompletionPct']}%** of the in-denominator requirement weight."
    )
    L.append("")
    L.append("## By product family")
    L.append("")
    L.append(
        "| family | complete % (weighted) | complete | active | dep-blocked | owner | external | outside |"
    )
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for f, s in summary["families"].items():
        w = s["weighted"]
        L.append(
            f"| {f} | {s['weightedCompletionPct']} | {w.get('complete', 0)} | {w.get('active', 0)} | "
            f"{w.get('dependencyBlocked', 0)} | {w.get('ownerAction', 0)} | {w.get('externalWait', 0)} | "
            f"{w.get('outOfDenominator', 0)} |"
        )
    L.append("")
    L.append("## By disposition")
    L.append("")
    for d in DISPOSITIONS:
        L.append(f"- `{d}`: {summary['byDisposition'].get(d, 0)}")
    L.append("")
    asks = _owner_asks()
    L.append("## Owner actions (true owner-only gates), grouped by urgency")
    L.append("")
    if asks:
        L.append(
            "Distinct owner asks (duplicate rows merged; criteria: a spend, b credential/account/consent, "
            "c official launch, d new product behavior with no owner preference, e methodology evidence "
            "cannot resolve, f explicit owner-only gate)."
        )
        L.append("")
        for urgency in ("URGENT", "SEASON", "WHENEVER"):
            group = [a for a in asks if a.get("urgency") == urgency]
            if not group:
                continue
            L.append(f"### {urgency}")
            L.append("")
            for a in group:
                due = f" (due {a['dueBy']})" if a.get("dueBy") else ""
                also = f" — also covers {', '.join(a['alsoCovers'])}" if a.get("alsoCovers") else ""
                L.append(f"- **{a['id']}** [{a.get('criterion')}]{due}: {a.get('ask')}{also}")
            L.append("")
    owner_rows = sorted((r for r in rows if r["disposition"] in OWNER), key=lambda r: r["id"])
    L.append(
        f"Rows in OWNER_ACTION_REQUIRED: {len(owner_rows)} — "
        + ", ".join(r["id"] for r in owner_rows)
    )
    L.append("")
    L.append("## External waits")
    L.append("")
    for r in sorted((r for r in rows if r["disposition"] in EXTERNAL), key=lambda r: r["id"]):
        b = r.get("blocker") or {}
        L.append(f"- **{r['id']}** — {b.get('what')}: {b.get('ownerOrExternalAction')}")
    L.append("")
    L.append("## Evidence files")
    L.append("")
    for m in meta:
        L.append(
            f"- `{m['file']}` — {m['family']} — {m['rows']} rows, audited {m['auditedAt']} at `{m['mainSha']}`"
        )
    L.append("")
    L.append(
        "Full per-requirement detail: `python scripts/completion_ledger.py --json <path>` "
        "(merges the family files; nothing is hand-maintained)."
    )
    return "\n".join(L) + "\n"


def build(
    family_dir: Path = FAMILY_DIR, manifest_path: Path = MANIFEST
) -> tuple[dict, str, list[str]]:
    meta, raw_rows = load_families(family_dir)
    manifest = manifest_ids(manifest_path.read_text(encoding="utf-8"))
    rows = reconcile(raw_rows, manifest)
    errors = apply_overrides(rows, load_overrides(family_dir))
    errors += validate(rows, manifest)
    clean = [
        {k: v for k, v in r.items() if k != "_familyFile"} | {"auditFile": r.get("_familyFile")}
        for r in rows
    ]
    for r in clean:
        r["auditFamily"] = r.get("productFamily")
        r["productFamily"] = canonical_family(r.get("auditFamily"))
    clean.sort(key=lambda r: (str(r.get("productFamily")), str(r["id"])))
    summary = summarize(clean)
    ledger = {
        "generatedBy": "scripts/completion_ledger.py",
        "families": meta,
        "summary": summary,
        "rows": clean,
    }
    return ledger, render(meta, clean, summary), errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if the dashboard is stale or the ledger is invalid",
    )
    ap.add_argument(
        "--json", type=Path, default=None, help="also write the merged ledger JSON to this path"
    )
    args = ap.parse_args(argv)
    ledger, md, errors = build()
    payload = json.dumps(ledger, indent=1, ensure_ascii=False) + "\n"
    for e in errors:
        print(f"[completion-ledger] ERROR {e}", file=sys.stderr)
    if args.check:
        stale = not OUT_MD.exists() or OUT_MD.read_text(encoding="utf-8") != md
        if stale:
            print(
                "[completion-ledger] ERROR outputs are stale; run scripts/completion_ledger.py",
                file=sys.stderr,
            )
        return 1 if (errors or stale) else 0
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(payload, encoding="utf-8")
    s = ledger["summary"]
    print(
        f"[completion-ledger] {s['rows']} rows; weighted completion {s['weightedCompletionPct']}%"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
