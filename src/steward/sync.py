"""Read-only Git observations and conservative evidence-reuse decisions."""

from __future__ import annotations

import subprocess
from pathlib import Path

GENERATED = ("CSVs/", "exports/", "data/", "config/model_registry/")
GLOBAL_DEPENDENCIES = (
    ".github/workflows/",
    "pyproject.toml",
    "requirements",
    "package",
    "frontend/package",
    "ASSISTANT_COORDINATION.md",
    "docs/EXECUTION_PLAN.md",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
    ).strip()


def overlaps(path: str, surfaces: list[str]) -> bool:
    return any(
        path == s.rstrip("/")
        or path.startswith(s.rstrip("/") + "/")
        or s.startswith(path.rstrip("/") + "/")
        for s in surfaces
    )


def observe(repo: Path, previous_main: str | None = None) -> dict:
    result = {
        "head": git(repo, "rev-parse", "HEAD"),
        "origin_main": git(repo, "rev-parse", "origin/main"),
        "branch": git(repo, "branch", "--show-current"),
        "dirty": bool(git(repo, "status", "--porcelain")),
        "previous_main": previous_main,
        "changed_paths": [],
        "commits": [],
        "observation": "local refs; caller must fetch and compare GitHub HEAD",
    }
    if previous_main and previous_main != result["origin_main"]:
        result["changed_paths"] = git(
            repo, "diff", "--name-only", previous_main, result["origin_main"]
        ).splitlines()
        result["commits"] = git(
            repo, "log", "--format=%H %an %s", f"{previous_main}..{result['origin_main']}"
        ).splitlines()
    return result


def classify_movement(
    observation: dict, surfaces: list[str], *, automation_proof: dict | None = None
) -> dict:
    changed = observation["changed_paths"]
    if observation["previous_main"] == observation["origin_main"]:
        return {"classification": "UNCHANGED", "affected": [], "reason": "same observed main"}
    if not observation["previous_main"]:
        return {
            "classification": "UNKNOWN_REQUIRES_INSPECTION",
            "affected": changed,
            "reason": "no prior base",
        }
    affected = [p for p in changed if overlaps(p, surfaces) or p.startswith(GLOBAL_DEPENDENCIES)]
    if affected:
        return {
            "classification": "RELEVANT_BASE_MOVE",
            "affected": affected,
            "reason": "dependency or governance overlap",
        }
    commit_ids = {c.split()[0] for c in observation["commits"]}
    proven = bool(
        automation_proof
        and automation_proof.get("reviewed_paths") == sorted(changed)
        and set(automation_proof.get("commits", [])) == commit_ids
        and commit_ids
        and automation_proof.get("workflow_evidence")
    )
    if proven:
        return {
            "classification": "BENIGN_AUTOMATION_MOVE",
            "affected": [],
            "reason": "reviewed exact paths and workflow provenance; no dependency overlap",
            "proof": automation_proof,
        }
    return {
        "classification": "UNKNOWN_REQUIRES_INSPECTION",
        "affected": changed,
        "reason": "automation provenance and relevance not proven; integration treats unknown as relevant",
    }


def evidence_reuse(evidence: dict, *, candidate_head: str, movement: dict) -> dict:
    if evidence.get("head") != candidate_head:
        return {"reuse": False, "reason": "candidate changed"}
    if evidence.get("result") != "PASS":
        return {"reuse": False, "reason": "no passing evidence"}
    if evidence.get("scope") == "release_tree" and movement["classification"] != "UNCHANGED":
        return {"reuse": False, "reason": "new composed release tree needs bounded validation"}
    if movement["classification"] in ("UNCHANGED", "BENIGN_AUTOMATION_MOVE"):
        return {"reuse": True, "reason": "same implementation with proven unaffected base"}
    if (
        movement["classification"] == "RELEVANT_BASE_MOVE"
        and evidence.get("dependencies_complete") is True
    ):
        touched = movement["affected"]
        if evidence.get("dependencies") and not any(
            overlaps(p, evidence["dependencies"]) or p.startswith(GLOBAL_DEPENDENCIES)
            for p in touched
        ):
            return {"reuse": True, "reason": "complete evidence dependency surface unaffected"}
    return {"reuse": False, "reason": "affected or unknown evidence dependencies"}


def generated_conflicts(repo: Path, base: str, candidate: str, main: str) -> list[str]:
    branch_paths = set(git(repo, "diff", "--name-only", base, candidate).splitlines())
    main_paths = set(git(repo, "diff", "--name-only", base, main).splitlines())
    return sorted(p for p in branch_paths & main_paths if p.startswith(GENERATED))
