"""Pure routing recommendations. No dispatch, credentials, or authority mutation."""

from __future__ import annotations

from datetime import datetime, timezone
import math

PROFILES = ("ROUTINE", "STANDARD", "COMPLEX", "CRITICAL")
METRICS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "duration_ms",
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
    """Compare like task classes; unknown results are not successful runs."""
    groups = {}
    for row in receipts:
        key = (row["task_class"], row["profile"])
        groups.setdefault(key, []).append(row)
    proposals = []
    for (kind, profile), rows in sorted(groups.items()):
        accepted = sum(row.get("acceptance") is True for row in rows)
        rejected = sum(row.get("acceptance") is False for row in rows)
        costs = [
            row["metrics"]["cost_usd"] for row in rows if row["metrics"]["cost_usd"] is not None
        ]
        proposals.append(
            {
                "task_class": kind,
                "profile": profile,
                "runs": len(rows),
                "accepted": accepted,
                "rejected": rejected,
                "unknown": len(rows) - accepted - rejected,
                "mean_measured_cost_usd": sum(costs) / len(costs) if costs else None,
                "cost_coverage": len(costs),
                "proposal": "evaluate stronger/context challenger"
                if rejected
                else "evaluate cheaper challenger",
                "status": "PROPOSED_CHALLENGER",
                "auto_promote": False,
            }
        )
    return {"groups": proposals, "authority": "A_REPORT_ONLY"}


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
    return {
        "classification": classification,
        "rule_refs": rule_refs,
        "evidence": failures,
        "next_action": "inspect specification, test and architecture before retry"
        if len(failures) > 1
        else "inspect failure",
    }
