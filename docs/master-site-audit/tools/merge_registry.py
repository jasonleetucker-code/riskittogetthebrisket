"""Audit-only: merge per-workstream JSONL shards into one validated registry.

Deliberately dumb and deterministic — no model in the loop. Every workstream
writes only its own shard; this concatenates, validates against the closed
enumerations in AUDIT_PROTOCOL.md, dedupes, and reports what fails validation so
a weak finding is visible rather than silently averaged in.

Usage:
    .venv/bin/python docs/master-site-audit/tools/merge_registry.py
    .venv/bin/python docs/master-site-audit/tools/merge_registry.py --strict
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARD_DIR = ROOT / "docs/master-site-audit/evidence/registry"
OUT = ROOT / "docs/master-site-audit/findings.json"
REPORT = ROOT / "docs/master-site-audit/evidence/registry-validation.txt"

STATUSES = {
    "Implemented and verified",
    "Implemented but defective",
    "Implemented but disconnected",
    "Partially implemented",
    "Scaffolded only",
    "Reference-only",
    "Mocked or hard-coded",
    "Missing",
    "Blocked by data",
    "Blocked by credentials or licensing",
    "Deprecated but still active",
    "Duplicate or conflicting implementation",
    "Unverifiable",
}
PRIORITIES = {"P0", "P1", "P2", "P3"}
SIZES = {"XS", "S", "M", "L", "XL"}
RELATIONS = {"confirmed", "refuted", "not-reproducible", "superseded", "new", "partial", None, ""}


def head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_shards() -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    problems: list[str] = []
    if not SHARD_DIR.exists():
        return findings, ["no shard directory — no workstream has written findings"]
    for shard in sorted(SHARD_DIR.glob("*.jsonl")):
        for lineno, line in enumerate(shard.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{shard.name}:{lineno} unparseable JSON — {exc}")
                continue
            if not isinstance(rec, dict):
                problems.append(f"{shard.name}:{lineno} not an object")
                continue
            rec.setdefault("workstream", shard.stem)
            findings.append(rec)
    return findings, problems


def validate(f: dict, where: str) -> list[str]:
    out = []
    fid = f.get("id", "<no id>")
    if f.get("status") not in STATUSES:
        out.append(f"{where} {fid}: status {f.get('status')!r} not in the closed vocabulary")
    if f.get("priority") not in PRIORITIES:
        out.append(f"{where} {fid}: priority {f.get('priority')!r} invalid")
    if f.get("size") not in SIZES:
        out.append(f"{where} {fid}: size {f.get('size')!r} invalid")
    repro = f.get("reproduction") or {}
    if not repro.get("command"):
        out.append(f"{where} {fid}: NO reproduction command")
    if f.get("status") == "Implemented and verified" and not repro.get("command"):
        out.append(f"{where} {fid}: claims 'Implemented and verified' with no passing proof")
    if not f.get("codeRefs"):
        out.append(f"{where} {fid}: no codeRefs")
    rel = ((f.get("priorFinding") or {}).get("relation"))
    if rel not in RELATIONS:
        out.append(f"{where} {fid}: priorFinding.relation {rel!r} invalid")
    if f.get("priority") == "P0" and not (f.get("surface") or {}).get("pages"):
        out.append(f"{where} {fid}: P0 must name the page a user acts on")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit 1 if any record fails validation")
    args = ap.parse_args()

    findings, problems = load_shards()
    for f in findings:
        problems.extend(validate(f, f.get("workstream", "?")))

    # Dedupe on (title, first codeRef path) — two workstreams can legitimately
    # reach the same file; identical claims are merged and both owners recorded.
    seen: dict[tuple, dict] = {}
    dupes = 0
    for f in findings:
        path = ((f.get("codeRefs") or [{}])[0]).get("path", "")
        key = (str(f.get("title", "")).strip().lower()[:120], path)
        if key in seen:
            dupes += 1
            seen[key].setdefault("alsoFoundBy", []).append(f.get("workstream"))
            continue
        seen[key] = f
    merged = list(seen.values())

    # Contradiction detector: same file, opposite verdicts.
    by_path: dict[str, set] = defaultdict(set)
    for f in merged:
        for ref in f.get("codeRefs") or []:
            by_path[ref.get("path", "")].add(f.get("status"))
    conflicts = [
        p for p, statuses in by_path.items()
        if "Implemented and verified" in statuses and (statuses & {
            "Implemented but defective", "Mocked or hard-coded", "Scaffolded only"})
    ]

    by_status = Counter(f.get("status") for f in merged)
    by_priority = Counter(f.get("priority") for f in merged)
    by_ws = Counter(f.get("workstream") for f in merged)
    by_relation = Counter(((f.get("priorFinding") or {}).get("relation")) for f in merged)

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "commit": head(),
        "totals": {
            "findings": len(merged),
            "rawRecords": len(findings),
            "duplicatesMerged": dupes,
            "workstreams": len(by_ws),
            "validationProblems": len(problems),
        },
        "byStatus": dict(by_status),
        "byPriority": dict(by_priority),
        "byWorkstream": dict(by_ws),
        "byPriorRelation": {str(k): v for k, v in by_relation.items()},
        "filesWithContradictoryVerdicts": conflicts,
        "findings": merged,
    }
    OUT.write_text(json.dumps(payload, indent=1))

    lines = [
        f"registry merge — {payload['generatedAt']} @ {payload['commit']}",
        f"shards: {len(list(SHARD_DIR.glob('*.jsonl'))) if SHARD_DIR.exists() else 0}",
        f"records: {len(findings)} raw -> {len(merged)} after dedupe ({dupes} merged)",
        f"by status: {dict(by_status)}",
        f"by priority: {dict(by_priority)}",
        f"by workstream: {dict(by_ws)}",
        f"prior-finding relations: {dict(by_relation)}",
        f"files with contradictory verdicts: {conflicts or 'none'}",
        "",
        f"VALIDATION PROBLEMS ({len(problems)}):",
        *problems,
    ]
    REPORT.write_text("\n".join(lines))
    print("\n".join(lines[:9]))
    print(f"\n{len(problems)} validation problems -> {REPORT}")
    print(f"wrote {OUT}")
    if args.strict and problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
