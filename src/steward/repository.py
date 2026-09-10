"""Repository inventory with source provenance; documents are observations, not proof."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from scripts.check_planning_integrity import parse_manifest
from .sync import git

REPLAN = "docs/BACKLOG_REPLAN_2026-09-10.md"
LAUNCH = "docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md"
SOURCES = (
    REPLAN,
    LAUNCH,
    "docs/C_SERIES_SCOPE_MANIFEST.md",
    "docs/OWNER_REQUESTED_TODO.md",
    "docs/OWNER_FEATURE_INVENTORY.md",
    "docs/OWNER_PRODUCT_BACKLOG_SPEC.md",
    "docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md",
    "docs/EXECUTION_PLAN.md",
    "docs/WORK_CLAIMS.md",
    "docs/VERSION_1_COMPLETION_CONTRACT.md",
    "docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md",
    "docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md",
    "UNIMPLEMENTED_BACKLOG.md",
)
PHASE_DEPENDENCIES = {0: [], 1: [0], 2: [1], 3: [0], 4: [0], 5: [1], 6: [0], 7: [0], 8: [0], 9: [0]}
IDS = re.compile(r"(?<![\w-])(?:#\d+|(?:W1|V1|CE|C\d+|T-NEW)-[A-Z0-9-]+)")


def table_rows(text: str):
    """Follow the repository's pipe-table convention; retain full source lines."""
    section = ""
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+$", line):
            yield (
                number,
                section,
                [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))],
                line,
            )


def launch_state(text: str) -> dict:
    rows = {
        cells[0]: {"state": cells[-1], "acceptance": cells[2], "line": line}
        for line, _, cells, _ in table_rows(text)
        if re.fullmatch(r"W1-\d\d", cells[0])
    }
    expected = {f"W1-{number:02}" for number in range(1, 31)}
    if set(rows) != expected:
        raise ValueError("Week 1 denominator or row identities changed; inspect owner contract")
    verified = sum(row["state"] == "VERIFIED" for row in rows.values())
    return {"verified": verified, "total": 30, "complete": verified == 30, "rows": rows}


def inventory(repo: Path) -> dict:
    documents, records, missing = {}, [], []
    for path in SOURCES:
        source = repo / path
        if not source.exists():
            missing.append(path)
            continue
        content = source.read_text(encoding="utf-8")
        documents[path] = {
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "git_blob": git(repo, "hash-object", path),
            "characters": len(content),
        }
        for line, section, cells, raw in table_rows(content):
            ids = sorted(set(IDS.findall(raw)))
            if ids:
                records.append(
                    {
                        "source": path,
                        "line": line,
                        "section": section,
                        "ids": ids,
                        "cells": cells,
                        "raw": raw,
                        "verification": "SOURCE_CLAIM",
                    }
                )
    manifest = [
        row
        for row in parse_manifest(
            (repo / "docs/C_SERIES_SCOPE_MANIFEST.md").read_text(encoding="utf-8")
        )
        if not row["id"].startswith("OD-")
    ]
    work = []
    for row in manifest:
        cells = row["cells"]
        full = len(cells) >= 12
        work.append(
            {
                "id": row["id"],
                "title": cells[1],
                "owner": cells[2],
                "source_status": cells[3] if full else "BASELINE_OR_EXCLUSION_SOURCE_CLAIM",
                "acceptance": cells[4] if full else cells[-1],
                "dependencies": IDS.findall(cells[6]) if full else [],
                "evidence": cells[-1],
                "source": "docs/C_SERIES_SCOPE_MANIFEST.md",
                "raw": row["line"],
                "verification": "SOURCE_CLAIM",
            }
        )
    return {
        "documents": documents,
        "repo_head": git(repo, "rev-parse", "HEAD"),
        "observations": records,
        "missing_sources": missing,
        "work_items": work,
        "manifest_rows": len(manifest),
        "manifest_ids": [row["id"] for row in manifest],
        "launch": launch_state((repo / LAUNCH).read_text(encoding="utf-8")),
    }


def phase_tasks(repo: Path, inv: dict) -> list[dict]:
    """Derive the existing replan's phase inventory; do not install a second roadmap."""
    text = (repo / REPLAN).read_text(encoding="utf-8")
    phase = None
    groups = {}
    for line, section, cells, raw in table_rows(text):
        match = re.match(r"4\.\d+ Phase (\d+) .+? (.+)", section)
        if not match:
            continue
        phase = int(match[1])
        group = groups.setdefault(phase, {"title": section, "rows": []})
        if cells[0] == "ID":
            continue
        group["rows"].append({"ids": sorted(set(IDS.findall(cells[0]))), "raw": raw, "line": line})
    tasks = []
    for phase, group in sorted(groups.items()):
        paths = sorted(
            {
                p
                for row in group["rows"]
                for p in re.findall(r"`((?:src|frontend|tests|docs)/[^`]+)`", row["raw"])
            }
        )
        ids = sorted({key for row in group["rows"] for key in row["ids"]})
        blockers = []
        if phase != 0 and not inv["launch"]["complete"]:
            blockers.append(
                "Week 1 remains below literal 30/30; verify current owner authorization before product execution"
            )
        if phase == 0 and not inv["launch"]["complete"]:
            blockers.append(
                "real LIVE/FINAL production evidence and final launch-tree verification"
            )
        if phase == 1:
            blockers.append(
                "owner ruling on Competitive Posture / canonical duplicate-owner retirement"
            )
        tasks.append(
            {
                "id": f"P{phase}",
                "expected_head": inv["repo_head"],
                "title": group["title"],
                "state": "PLANNED",
                "dependencies": [f"P{p}" for p in PHASE_DEPENDENCIES.get(phase, [])],
                "touches": paths,
                "todo_ids": ids,
                "source_rows": group["rows"],
                "authority": "docs/EXECUTION_PLAN.md + current owner directive",
                "kind": "FOUNDATION" if phase in (1, 4, 7, 9) else "INTEGRATION",
                "risk": "high" if phase in (0, 1, 3, 5) else "medium",
                "rollback_group": f"phase-{phase}",
                "blockers": blockers,
                "acceptance": [
                    f"{REPLAN} section 5 phase {phase}",
                    "each source requirement independently evidenced; partial is not complete",
                ],
                "tests": ["change-class tests from docs/AGENT_OPERATING_SYSTEM.md"],
                "docs": [REPLAN, "docs/C_SERIES_SCOPE_MANIFEST.md"],
                "production_required": phase != 9,
                "unresolved": [
                    "source claims require current live-path verification before selecting implementation"
                ],
            }
        )
    if set(groups) != set(range(10)):
        raise ValueError("combined replan phase structure changed; reconcile parser")
    return tasks


def reconcile(repo: Path, inv: dict, tasks: list[dict], remote: dict | None) -> dict:
    """Keep long-tail work and supersession separate from textual reference counts."""
    by_id = {task["id"]: task for task in tasks}
    prefix_phase = {
        "C0": "P9",
        "C1": "P1",
        "C2": "P1",
        "C3": "P2",
        "C4": "P6",
        "C5": "P5",
        "C6": "P4",
        "C7": "P7",
        "C8": "P8",
        "C9": "P7",
        "C10": "CLOSURE",
        "F": "BASELINE",
        "X": "EXCLUDED",
    }
    manifest = []
    for item in inv["work_items"]:
        phase = prefix_phase.get(item["id"].split("-")[0], "NEEDS_INSPECTION")
        # This is a sequencing association, never a new dependency or acceptance decision.
        manifest.append(
            item
            | {
                "phase": phase,
                "mapping_basis": "C-Series owner taxonomy; confirm at phase selection",
            }
        )
        if phase in by_id:
            by_id[phase].setdefault("manifest_ids", []).append(item["id"])
    text = (repo / REPLAN).read_text(encoding="utf-8")
    supersessions = []
    for line, section, cells, raw in table_rows(text):
        if section.startswith("0.5.") and len(cells) >= 5:
            ids = sorted(set(IDS.findall(cells[3])))
            if ids:
                supersessions.append(
                    {
                        "ids": ids,
                        "status": cells[1],
                        "source": REPLAN,
                        "line": line,
                        "reason": cells[4],
                        "raw": raw,
                        "verification": "SOURCE_CLAIM",
                    }
                )
    closed_verified = {
        key
        for row in supersessions
        if row["status"] == "SHIPPED_AND_VERIFIED"
        for key in row["ids"]
    }
    live_issues = [] if remote is None else [i for i in remote["issues"] if "pull_request" not in i]
    live_ids = {f"#{i['number']}" for i in live_issues}
    # An absent issue in an observed complete open-issue inventory plus a newer source
    # disposition prevents repeating obsolete work. It does not create production proof.
    retired = sorted(closed_verified - live_ids) if remote is not None else []
    for task in tasks:
        task["todo_ids"] = [key for key in task["todo_ids"] if key not in retired]
    mapped = {key for task in tasks for key in task["todo_ids"]}
    new_issues = []
    for issue in live_issues:
        key = f"#{issue['number']}"
        if key in mapped:
            continue
        phase = (
            "P0"
            if "refresh failing" in issue["title"].lower()
            else "P3"
            if "source" in issue["title"].lower()
            else None
        )
        new_issues.append(
            {
                "id": key,
                "title": issue["title"],
                "phase": phase or "NEEDS_INSPECTION",
                "source": issue["html_url"],
                "state": "UNTOUCHED",
                "classification": "OPERATIONAL_OBSERVATION"
                if phase == "P0"
                else "NEEDS_LIVE_PATH_REVIEW",
            }
        )
        if phase:
            by_id[phase]["todo_ids"].append(key)
    return {
        "manifest": manifest,
        "supersessions": supersessions,
        "retired_issue_work": retired,
        "new_issues": new_issues,
        "tasks": tasks,
        "reference_ids_are_not_tasks": True,
    }


def github_disposition(pr: dict) -> str:
    if pr.get("merged_at"):
        return "MERGED_REQUIRES_ACCEPTANCE_CHECK"
    if pr.get("state") == "closed":
        return "PARTIALLY_REUSABLE_REQUIRES_INSPECTION"
    return "NEEDS_REVIEW"


def context(repo: Path, paths: list[str], *, max_chars: int = 12000) -> dict:
    root = repo.resolve()
    output, omitted, remaining = [], [], max_chars
    for path in paths:
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("context path escapes repository")
        if not target.is_file():
            omitted.append({"path": path, "reason": "missing"})
            continue
        content = target.read_text(encoding="utf-8")
        if remaining <= 0:
            omitted.append({"path": path, "reason": "context budget"})
            continue
        excerpt = content[:remaining]
        remaining -= len(excerpt)
        output.append(
            {
                "path": path,
                "git_blob": git(root, "hash-object", path),
                "content": excerpt,
                "complete": len(excerpt) == len(content),
            }
        )
    return {"sources": output, "omitted": omitted, "characters": max_chars - remaining}


def work_units(tasks: list[dict], inv: dict, reconciliation: dict) -> list[dict]:
    """Canonical acceptance and dependencies for every manifest and replan obligation."""
    units = {}
    by_phase = {task["id"]: task for task in tasks}
    excluded = {"BASELINE", "EXCLUDED"}
    for item in reconciliation["manifest"]:
        if item["phase"] in excluded:
            continue
        parent = by_phase.get(item["phase"], {})
        paths = re.findall(r"`((?:src|frontend|tests|docs|scripts)/[^`]+)`", item["owner"])
        units[item["id"]] = {
            "id": item["id"],
            "title": item["title"],
            "state": "PLANNED",
            "expected_head": inv["repo_head"],
            "dependencies": item["dependencies"],
            "touches": paths,
            "authority": parent.get("authority", "current execution plan"),
            "rollback_group": parent.get("rollback_group", item["phase"]),
            "risk": parent.get("risk", "high"),
            "acceptance": [
                item["acceptance"],
                "docs/C_SERIES_SCOPE_MANIFEST.md section 3 acceptance profile",
            ],
            "tests": [item["evidence"]],
            "docs": [item["source"]],
            "production_required": True,
            "blockers": parent.get("blockers", [])[:],
            "unresolved": [
                "source claim; preserve existing evidence and verify only affected scope"
            ],
            "source": {"path": item["source"], "raw": item["raw"]},
            "owning_phase": item["phase"],
        }
    intake = {}
    for row in inv["observations"]:
        if row["source"] == "docs/OWNER_REQUESTED_TODO.md" and len(row["cells"]) == 5:
            for key in IDS.findall(row["cells"][1]):
                intake[key] = {
                    "acceptance": row["cells"][3],
                    "source": row["source"],
                    "line": row["line"],
                }
    for parent in tasks:
        prior_paths = []
        for index, row in enumerate(parent["source_rows"]):
            cells = next(table_rows(row["raw"]))[2]
            keys = [key for key in row["ids"] if key in parent["todo_ids"]]
            if row["ids"] and not keys:
                continue
            keys = keys or [parent["id"] + ":foundation:" + str(index)]
            paths = re.findall(r"`((?:src|frontend|tests|docs)/[^`]+)`", row["raw"])
            if not paths and "same" in row["raw"].lower():
                paths = prior_paths
            prior_paths = paths or prior_paths
            dependencies = set(IDS.findall(cells[5])) if len(cells) > 5 else set()
            dependencies.update(
                re.findall(r"(?:depends on|dependency-gated on)\s*(#\d+)", row["raw"], re.I)
            )
            for key in keys:
                if key in units:
                    units[key].setdefault("also_advanced_by", []).append(parent["id"])
                    continue
                launch = inv["launch"]["rows"].get(key)
                source = intake.get(key)
                acceptance = (
                    [launch["acceptance"]] if launch else [source["acceptance"]] if source else []
                )
                blockers = parent["blockers"][:]
                if not acceptance:
                    blockers.append(
                        "canonical acceptance must be resolved from cited contract/issue before execution"
                    )
                units[key] = {
                    "id": key,
                    "title": cells[1],
                    "state": "PLANNED",
                    "expected_head": inv["repo_head"],
                    "touches": paths,
                    "dependencies": sorted(dependencies - {key}),
                    "authority": parent["authority"],
                    "rollback_group": parent["rollback_group"],
                    "risk": parent["risk"],
                    "acceptance": acceptance,
                    "tests": parent["tests"],
                    "docs": parent["docs"],
                    "production_required": parent["production_required"],
                    "unresolved": ["source claim; independently trace live consumers and evidence"],
                    "blockers": blockers,
                    "source": source or {"path": LAUNCH if launch else REPLAN, "line": row["line"]},
                    "owning_phase": parent["id"],
                }
    # Existing verified baselines are explicit external prerequisites, not new implementation.
    baseline_ids = {
        item["id"] for item in reconciliation["manifest"] if item["phase"] == "BASELINE"
    }
    for unit in units.values():
        baseline_deps = [dep for dep in unit["dependencies"] if dep in baseline_ids]
        if baseline_deps:
            unit["baseline_dependencies"] = baseline_deps
            unit["dependencies"] = [dep for dep in unit["dependencies"] if dep not in baseline_ids]
            unit["unresolved"].append(
                "reuse documented baseline evidence; inspect only affected dependencies"
            )
    return list(units.values())
