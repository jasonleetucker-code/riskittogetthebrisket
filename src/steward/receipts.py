"""Canonical report-only runReceipt construction, informed by unmerged PR #1318."""

from __future__ import annotations

import re
import secrets
import math
from datetime import datetime, timezone
from uuid import uuid4


def run_receipt(
    *,
    head: str,
    agent_os: str,
    evidence: list[dict],
    unresolved: list[str],
    routes: list[dict],
    started_at: str,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("receipt requires observed full repository SHA")
    return {
        "schema_version": "steward-receipt/v1",
        "run_id": str(uuid4()),
        "trace_id": secrets.token_hex(16),
        "lane": "harness_audit",
        "status": "PARTIAL" if unresolved else "DONE",
        "agent_os_receipt": agent_os,
        "repo_head_start": head,
        "repo_head_end": head,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence,
        "unresolved": unresolved,
        "actions": [],
        "model_routes": routes,
        "execution_spans": [],
        "cost": {"usd": None},
    }


def execution_span(
    receipt: dict,
    *,
    phase: str,
    action: str,
    started_at: str,
    ended_at: str,
    duration_ms: float,
    status: str,
    evidence_refs: list[str],
    producer: dict | None = None,
) -> dict:
    """Attach one observed operation to the existing private run receipt."""
    if phase not in {"plan", "turn", "tool", "guard", "handoff", "verifier", "write"}:
        raise ValueError("unknown Steward execution phase")
    if status not in {"DONE", "FAILED", "BLOCKED", "HALTED"}:
        raise ValueError("unknown Steward execution status")
    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("execution duration must be finite and nonnegative")
    producer = producer or {}
    return {
        "schema_version": "steward-execution-span/v1",
        "run_id": receipt["run_id"],
        "trace_id": receipt["trace_id"],
        "span_id": secrets.token_hex(8),
        "parent_span_id": None,
        "task_id": "steward-brief",
        "phase": phase,
        "action": action,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "provider": producer.get("provider"),
        "model": producer.get("model"),
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
        "cost_usd": None,
        "retry": 0,
        "evidence_refs": evidence_refs,
        "repo_head_start": receipt["repo_head_start"],
        "repo_head_end": receipt["repo_head_end"],
        "authority_decision": "A_REPORT_ONLY",
    }
