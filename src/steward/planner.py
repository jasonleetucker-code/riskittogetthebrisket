"""Dependency and touch-aware planning over observed work, never a scope authority."""

from __future__ import annotations

from graphlib import TopologicalSorter, CycleError
import re

STATES = {
    "UNTOUCHED",
    "PLANNED",
    "READY",
    "IN_PROGRESS",
    "IMPLEMENTED_UNVERIFIED",
    "VERIFIED",
    "PRODUCTION_VERIFIED",
    "BLOCKED",
    "SUPERSEDED",
    "ABANDONED",
}
DONE = {"VERIFIED", "PRODUCTION_VERIFIED", "SUPERSEDED", "ABANDONED"}
SATISFIED = {"VERIFIED", "PRODUCTION_VERIFIED"}


def satisfy(tasks: list[dict], evidence: dict) -> list[dict]:
    """One shared implementation may close several contracts only with per-item proof."""
    result = []
    for task in tasks:
        proof = evidence.get(task["id"])
        if proof:
            if (
                proof.get("result") != "PASS"
                or task.get("candidate_clean") is not True
                or not task.get("acceptance")
                or not re.fullmatch(r"[0-9a-f]{40}", str(proof.get("head", "")))
                or proof.get("head") != task.get("expected_head")
                or set(proof.get("criteria", [])) != set(task["acceptance"])
                or not proof.get("references")
                or proof.get("unresolved")
            ):
                raise ValueError(f"{task['id']}: incomplete acceptance evidence")
            production = task.get("production_required", False)
            if production and not proof.get("production_identity"):
                result.append(task | {"state": "IMPLEMENTED_UNVERIFIED", "evidence": proof})
                continue
            result.append(
                task
                | {"state": "PRODUCTION_VERIFIED" if production else "VERIFIED", "evidence": proof}
            )
        else:
            result.append(task)
    return result


def compatible(a: dict, b: dict) -> tuple[bool, str]:
    if a.get("risk") not in {"low", "medium", "high"} or b.get("risk") not in {
        "low",
        "medium",
        "high",
    }:
        return False, "unknown risk requires inspection"
    if a["id"] in b.get("dependencies", []) or b["id"] in a.get("dependencies", []):
        return False, "dependency requires serial proof"
    if a.get("risk") == "high" or b.get("risk") == "high":
        return False, "high risk needs separate review and rollback"
    if not a.get("rollback_group") or a.get("rollback_group") != b.get("rollback_group"):
        return False, "distinct or unknown rollback boundary"
    if not a.get("authority") or a.get("authority") != b.get("authority"):
        return False, "distinct authority boundary"
    shared = set(a.get("touches", [])) & set(b.get("touches", []))
    return bool(shared), "shared canonical touch" if shared else "no shared touch benefit"


def plan(tasks: list[dict], *, max_phase_items: int = 4) -> dict:
    if max_phase_items < 1:
        raise ValueError("positive WIP bound required")
    by_id = {t["id"]: t for t in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("duplicate task identity")
    for task in tasks:
        if task["state"] not in STATES:
            raise ValueError("unknown work state")
        if task["state"] in SATISFIED:
            if not task.get("evidence"):
                raise ValueError("verified task lacks evidence")
            validated = satisfy([task], {task["id"]: task["evidence"]})[0]
            if validated["state"] != task["state"]:
                raise ValueError("persisted verification does not satisfy current acceptance")
    graph = {t["id"]: set(t.get("dependencies", [])) for t in tasks}

    def replacement(key, visited=None):
        visited = set() if visited is None else visited
        if key in visited:
            raise ValueError("supersession cycle")
        row = by_id.get(key, {})
        if row.get("state") == "SUPERSEDED" and row.get("replacement"):
            return replacement(row["replacement"], visited | {key})
        return key

    graph = {key: {replacement(dep) for dep in deps} for key, deps in graph.items()}
    missing = sorted({dep for deps in graph.values() for dep in deps} - by_id.keys())
    try:
        ordered = list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise ValueError("dependency cycle requires reconciliation") from exc
    depth = {}
    for key in ordered:
        depth[key] = 1 + max((depth[d] for d in graph.get(key, [])), default=-1)
    dependents = {key: sum(key in deps for deps in graph.values()) for key in by_id}
    ordered.sort(
        key=lambda key: (
            depth[key],
            -dependents.get(key, 0),
            by_id.get(key, {}).get("estimated_ci_cost")
            if by_id.get(key, {}).get("estimated_ci_cost") is not None
            else float("inf"),
            by_id.get(key, {}).get("estimated_context_chars")
            if by_id.get(key, {}).get("estimated_context_chars") is not None
            else float("inf"),
            key,
        )
    )
    pending = [by_id[key] for key in ordered if key in by_id and by_id[key]["state"] not in DONE]
    phases, rejected = [], []
    scheduled = {t["id"] for t in tasks if t["state"] in SATISFIED}
    for task in pending:
        blockers = list(task.get("blockers", []))
        if task["state"] == "BLOCKED":
            blockers.append(
                "persisted BLOCKED state; reconcile its durable evidence before execution"
            )
        blockers += [f"dependency:{dep}" for dep in graph[task["id"]] if dep not in scheduled]
        # An unverified dependency may be scheduled earlier but still gates execution.
        dependency_gates = [
            dep
            for dep in graph[task["id"]]
            if dep not in by_id or by_id[dep]["state"] not in SATISFIED
        ]
        merged = False
        for phase in reversed(phases):
            if len(phase["tasks"]) >= max_phase_items or set(blockers) != set(phase["blockers"]):
                continue
            decisions = [compatible(task, by_id[key]) for key in phase["tasks"]]
            if all(ok for ok, _ in decisions) and set(dependency_gates) == set(
                phase["dependencies"]
            ):
                phase["tasks"].append(task["id"])
                shared = len(set(task.get("touches", [])) & set(phase["touches"]))
                phase["touches"] = sorted(set(phase["touches"]) | set(task.get("touches", [])))
                phase["acceptance"][task["id"]] = task["acceptance"]
                phase["tests"] = sorted(set(phase["tests"]) | set(task.get("tests", [])))
                phase["docs"] = sorted(set(phase["docs"]) | set(task.get("docs", [])))
                phase["unresolved"] += task.get("unresolved", [])
                phase["production_required"] |= task.get("production_required", False)
                phase["review"] |= task.get("risk") in {"medium", "high"}
                phase["shared_touch_savings"] += shared
                merged = True
                break
            if set(task.get("touches", [])) & set(phase["touches"]):
                rejected.append(
                    {
                        "task": task["id"],
                        "phase": phase["tasks"],
                        "reasons": sorted({why for ok, why in decisions if not ok}),
                    }
                )
        if not merged:
            phases.append(
                {
                    "tasks": [task["id"]],
                    "objective": task["title"],
                    "kind": task.get("kind", "FEATURE IMPLEMENTATION"),
                    "touches": task.get("touches", []),
                    "blockers": blockers,
                    "dependencies": dependency_gates,
                    "acceptance": {task["id"]: task["acceptance"]},
                    "tests": task.get("tests", []),
                    "docs": task.get("docs", []),
                    "review": task.get("risk") in {"medium", "high"},
                    "production_required": task.get("production_required", False),
                    "rollback": task.get("rollback_group", "UNKNOWN"),
                    "shared_touch_savings": 0,
                    "unresolved": task.get("unresolved", []),
                    "execution": "BLOCKED"
                    if blockers or dependency_gates
                    else "READY_FOR_AUTHORITY_CHECK",
                }
            )
        scheduled.add(task["id"])
    return {
        "phases": phases,
        "unsafe_combinations": rejected,
        "missing_dependencies": missing,
        "optimization": [
            "dependencies first",
            "shared touch and test reuse",
            "bounded review/rollback",
            "WIP limit",
            "avoid repeated context/CI",
            "production and authority gates",
        ],
        "authority": "recommendation only",
    }
