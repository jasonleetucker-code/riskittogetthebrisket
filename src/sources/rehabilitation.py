"""Source rehabilitation lifecycle — one registry of every non-voting source's plan.

Owner master package 2026-10-17, Workstream J: "No source should remain
indefinitely in shadow without a named blocker, next experiment, and
measurable promotion criterion."  ``config/sources/rehabilitation.json`` is
that record; this module reads and validates it, and answers which entries are
overdue for review.  It never changes a vote — activation stays behind each
source's own gate (freshness weighting, a promotion gate, or owner approval).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "sources" / "rehabilitation.json"

PERMANENT = "permanent_role"
#: Fields a non-permanent entry must state: the plan, not just the reason.
PLAN_FIELDS = (
    "reason",
    "evidence",
    "recoveryAction",
    "owner",
    "nextTrigger",
    "promotionGate",
    "reviewBy",
)


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(registry: dict[str, Any]) -> list[str]:
    """Problems with the registry itself (empty list = valid)."""
    problems: list[str] = []
    states = set(registry.get("states") or ())
    for key, entry in (registry.get("entries") or {}).items():
        state = entry.get("state")
        if state not in states:
            problems.append(f"{key}: unknown state {state!r}")
            continue
        if state == PERMANENT:
            if not entry.get("reason"):
                problems.append(f"{key}: permanent_role needs a reason")
            continue
        for f in PLAN_FIELDS:
            if not str(entry.get(f) or "").strip():
                problems.append(f"{key}: missing {f}")
        try:
            date.fromisoformat(str(entry.get("reviewBy") or ""))
        except ValueError:
            problems.append(f"{key}: reviewBy is not an ISO date")
    return problems


def overdue(registry: dict[str, Any], today: date) -> list[dict[str, Any]]:
    """Non-permanent entries whose review date has passed — the reminder that
    keeps a held source from being forgotten."""
    out = []
    for key, entry in (registry.get("entries") or {}).items():
        if entry.get("state") == PERMANENT:
            continue
        try:
            due = date.fromisoformat(str(entry.get("reviewBy")))
        except ValueError:
            continue
        if due < today:
            out.append({"sourceKey": key, "state": entry.get("state"), "reviewBy": due.isoformat()})
    return sorted(out, key=lambda r: r["reviewBy"])


def plan_for(key: str, registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    reg = registry if registry is not None else load_registry()
    return (reg.get("entries") or {}).get(key)
