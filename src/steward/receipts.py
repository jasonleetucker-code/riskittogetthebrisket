"""Canonical report-only runReceipt construction, informed by unmerged PR #1318."""

from __future__ import annotations

import re
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
        "cost": {"usd": None},
    }
