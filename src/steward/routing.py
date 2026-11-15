"""Pure routing recommendations. No dispatch, credentials, or authority mutation."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from statistics import median

PROFILES = ("ROUTINE", "STANDARD", "COMPLEX", "CRITICAL")
METRICS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "context_tokens",
    "context_bytes",
    "repository_docs_selected",
    "mandatory_docs_selected",
    "task_docs_selected",
    "duration_ms",
    "tool_calls",
    "tool_definitions_exposed",
    "tool_definitions_used",
    "tool_definition_tokens",
    "compaction_events",
    "subagent_summary_bytes",
    "final_evidence_refs",
    "cost_usd",
    "allowance_consumed",
    "retries",
    "reviewer_corrections",
)


def classify(task: dict) -> str:
    """Risk wins over cheapness; resolved mechanical work can downgrade."""
    if task.get("security_risk") or task.get("production_risk") == "high":
        return "CRITICAL"
    if task.get("unresolved_failures", 0) >= 2 or task.get("conflicting_evidence"):
        return "CRITICAL"
    if task.get("cross_system") or task.get("ambiguity") == "high":
        return "COMPLEX"
    if task.get("mechanical") and not task.get("unresolved_failures"):
        return "ROUTINE"
    return "STANDARD"


def recommend(task: dict, policy: dict, *, available: list[str], owner: dict | None = None) -> dict:
    """Availability is a fresh harness observation, never inferred from catalog presence."""
    owner = owner or {}
    profile = classify(task)
    previous = task.get("previous_profile")
    failures = task.get("unresolved_failures", 0)
    if failures and previous in PROFILES:
        profile = PROFILES[max(PROFILES.index(profile), min(PROFILES.index(previous) + 1, 3))]
    if owner.get("minimum_profile") in PROFILES:
        profile = PROFILES[max(PROFILES.index(profile), PROFILES.index(owner["minimum_profile"]))]
    receipt = {
        "schema_version": "steward-route/v1",
        "at": datetime.now(timezone.utc).isoformat(),
        "task_id": task["id"],
        "task_class": task.get("kind", "implementation"),
        "profile": profile,
        "previous_profile": previous,
        "reason": "risk/classification plus unresolved acceptance evidence",
        "model": None,
        "provider": None,
        "reasoning": None,
        "status": "BLOCKED",
        "execution": "RECOMMENDATION_ONLY",
        "authority": "A_REPORT_ONLY",
        "max_incremental_usd": 0,
        "delegation_allowed": not owner.get("disable_delegation", False),
        "metrics": dict.fromkeys(METRICS),
        "context_refs": task.get("context_refs", []),
        "acceptance": None,
        "escalations": int(bool(failures)),
    }
    if task.get("deterministic"):
        return receipt | {"status": "NO_MODEL", "reason": "executable deterministic judge"}
    if failures and owner.get("approve_escalation"):
        return receipt | {"reason": "owner approval required for escalation"}
    if owner.get("usage_remaining") is not None and owner["usage_remaining"] <= 0:
        return receipt | {"reason": "owner usage ceiling exhausted"}
    candidates = policy["profiles"][profile]
    pin = owner.get("model")
    if pin:
        candidates = [pin]
    for model in candidates:
        cap = policy["models"].get(model)
        if (
            not cap
            or model not in available
            or cap["provider"] in owner.get("prohibited_providers", [])
        ):
            continue
        # This installed foundation never invokes metered inference, even with a larger local budget.
        if cap.get("billing") != "included_interactive":
            continue
        effort = owner.get("reasoning", policy["effort"][profile])
        if effort not in cap["reasoning"]:
            if "reasoning" in owner:
                continue
            effort = cap.get("default_reasoning")
        if effort not in cap["reasoning"]:
            continue
        return receipt | {
            "model": model,
            "provider": cap["provider"],
            "reasoning": effort,
            "status": "RECOMMENDED",
            "reason": "owner pin" if pin else "lowest configured sufficient available profile",
        }
    return receipt | {
        "reason": "pinned configuration unavailable"
        if pin
        else "no permitted sufficient model available"
    }


def measured(receipt: dict, **metrics) -> dict:
    unknown = set(metrics) - set(METRICS)
    if unknown:
        raise ValueError(f"unknown telemetry fields: {sorted(unknown)}")
    for value in metrics.values():
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("telemetry must be a nonnegative finite measurement or null")
    return receipt | {"metrics": receipt["metrics"] | metrics}


def retrospective(receipts: list[dict]) -> dict:
    """Summarize comparable, evidenced executions without changing routing policy."""
    groups = {}
    for row in receipts:
        key = (row["task_class"], row["profile"], row.get("model"), row.get("reasoning"))
        groups.setdefault(key, []).append(row)
    cards = []
    for (kind, profile, model, reasoning), rows in sorted(
        groups.items(), key=lambda item: tuple(str(value) for value in item[0])
    ):
        executed = [row for row in rows if row.get("execution") == "EXECUTED"]
        evaluated = [
            row
            for row in executed
            if type(row.get("acceptance")) is bool
            and row.get("acceptance_evidence") == "VERIFIED_AGAINST_ARTIFACT"
            and row.get("eval_case_id")
            and isinstance(row.get("repo_head_end"), str)
            and re.fullmatch(r"[0-9a-f]{40}", row["repo_head_end"])
        ]
        accepted_rows = [row for row in evaluated if row["acceptance"] is True]
        accepted = len(accepted_rows)
        rejected = len(evaluated) - accepted
        costs = [
            row["metrics"]["cost_usd"]
            for row in evaluated
            if row.get("metrics", {}).get("cost_usd") is not None
        ]
        latencies = [
            row.get("metrics", {}).get("duration_ms")
            for row in evaluated
            if row.get("metrics", {}).get("duration_ms") is not None
        ]
        accepted_costs = [
            row["metrics"]["cost_usd"]
            for row in accepted_rows
            if row.get("metrics", {}).get("cost_usd") is not None
        ]
        accepted_tokens = [
            row["metrics"]["input_tokens"] + row["metrics"]["output_tokens"]
            for row in accepted_rows
            if row.get("metrics", {}).get("input_tokens") is not None
            and row.get("metrics", {}).get("output_tokens") is not None
        ]
        accepted_retries = [
            row["metrics"]["retries"]
            for row in accepted_rows
            if row.get("metrics", {}).get("retries") is not None
        ]
        first_pass = [
            row["acceptance"] and row["first_pass"]
            for row in evaluated
            if type(row.get("first_pass")) is bool
        ]
        corrections = [
            row["metrics"]["reviewer_corrections"]
            for row in evaluated
            if row.get("metrics", {}).get("reviewer_corrections") is not None
        ]
        false_completions = [
            row["false_completion"]
            for row in evaluated
            if type(row.get("false_completion")) is bool
        ]
        coverage_metrics = (
            "context_tokens",
            "context_bytes",
            "repository_docs_selected",
            "mandatory_docs_selected",
            "task_docs_selected",
            "tool_calls",
            "tool_definitions_exposed",
            "tool_definitions_used",
            "tool_definition_tokens",
            "compaction_events",
            "subagent_summary_bytes",
            "final_evidence_refs",
        )
        status = (
            "NO_EXECUTION_EVIDENCE"
            if not executed
            else "INSUFFICIENT_EVIDENCE"
            if len(evaluated) < 5
            else "CHALLENGER_CANDIDATE"
        )
        proposal = None
        if status == "CHALLENGER_CANDIDATE":
            proposal = (
                "evaluate stronger/context challenger"
                if rejected / len(evaluated) > 0.2
                else "evaluate cheaper challenger"
                if len(accepted_costs) >= 3 and len(costs) == len(evaluated)
                else "collect measured cost before cheaper challenger"
            )
        cards.append(
            {
                "task_class": kind,
                "profile": profile,
                "model": model,
                "reasoning": reasoning,
                "runs": len(rows),
                "executed": len(executed),
                "evaluated": len(evaluated),
                "accepted": accepted,
                "rejected": rejected,
                "unknown": len(rows) - len(evaluated),
                "acceptance_rate": accepted / len(evaluated) if evaluated else None,
                "first_pass_acceptance_rate": sum(first_pass) / len(first_pass)
                if first_pass
                else None,
                "reviewer_correction_rate": sum(value > 0 for value in corrections)
                / len(corrections)
                if corrections
                else None,
                "false_completion_rate": sum(false_completions) / len(false_completions)
                if false_completions
                else None,
                "median_latency_ms": median(latencies) if latencies else None,
                "tokens_per_accepted_task": sum(accepted_tokens) / len(accepted_tokens)
                if accepted_tokens
                else None,
                "measured_cost_per_accepted_task_usd": sum(costs) / accepted
                if accepted and len(costs) == len(evaluated)
                else None,
                "retries_per_accepted_task": sum(accepted_retries) / len(accepted_retries)
                if accepted_retries
                else None,
                "mean_measured_cost_usd": sum(costs) / len(costs) if costs else None,
                "cost_coverage": len(costs),
                "coverage": {
                    "latency": len(latencies),
                    "accepted_tokens": len(accepted_tokens),
                    "accepted_cost": len(accepted_costs),
                    "accepted_retries": len(accepted_retries),
                    "first_pass": len(first_pass),
                    "reviewer_corrections": len(corrections),
                    "false_completion": len(false_completions),
                    **{
                        metric: sum(
                            row.get("metrics", {}).get(metric) is not None for row in evaluated
                        )
                        for metric in coverage_metrics
                    },
                },
                "proposal": proposal,
                "status": status,
                "auto_promote": False,
            }
        )
    return {"groups": cards, "authority": "A_REPORT_ONLY"}


def diagnose_failures(events: list[dict]) -> dict:
    failures = [e for e in events if e.get("accepted") is False]
    contexts = {e.get("session") for e in failures if e.get("session")}
    rule_refs = sorted({e["rule_ref"] for e in failures if e.get("rule_ref")})
    classification = "UNKNOWN"
    if failures:
        classification = "ISOLATED_AGENT_ERROR"
    if len(failures) > 1:
        classification = "RECURRING_EXECUTION_FAILURE"
    if len(contexts) > 1 and rule_refs:
        classification = "POSSIBLE_INSTRUCTION_DEFECT"
    layers = {
        e.get("failure_layer")
        for e in failures
        if e.get("failure_layer") in {"HARNESS", "LOOP", "GRAPH", "DATA", "MODEL", "INFRA"}
        and e.get("failure_layer_evidence_refs")
    }
    attributed = len(layers) == 1 and all(
        e.get("failure_layer") in layers
        and isinstance(e.get("failure_layer_evidence_refs"), list)
        and any(isinstance(ref, str) and ref for ref in e["failure_layer_evidence_refs"])
        for e in failures
    )
    return {
        "classification": classification,
        "engineering_layer": next(iter(layers)) if attributed else "UNKNOWN",
        "layer_evidence_refs": sorted(
            {
                ref
                for e in failures
                if e.get("failure_layer") in layers
                for ref in e.get("failure_layer_evidence_refs", [])
                if isinstance(ref, str) and ref
            }
        )
        if attributed
        else [],
        "rule_refs": rule_refs,
        "evidence": failures,
        "next_action": "inspect specification, test and architecture before retry"
        if len(failures) > 1
        else "inspect failure",
    }
