"""Every held / non-voting / shadow / seasonally inactive source has a plan."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.sources import rehabilitation as R

REPO = Path(__file__).resolve().parents[2]


def _registry():
    return R.load_registry()


def test_registry_is_valid():
    assert R.validate(_registry()) == []


def test_every_held_or_non_voting_source_has_an_entry():
    from scripts import source_inventory as inv
    from src.api import data_contract as dc

    required = (
        set(dc.PRIVATE_SOURCE_VOTE_HOLDS)
        | set(dc.POLICY_SOURCE_VOTE_HOLDS)
        | set(dc._NON_VOTING_SOURCE_CSV_KEYS)
        | set(inv.KNOWN_NON_VOTING_REASONS)
    )
    policy = json.loads(
        (REPO / "config/sources/seasonal_policy_v1.json").read_text(encoding="utf-8")
    )
    required |= set(policy["sources"])  # declared seasonal windows
    missing = sorted(required - set(_registry()["entries"]))
    assert missing == [], f"held/non-voting sources with no rehabilitation plan: {missing}"


def test_overdue_lists_only_plans_past_review():
    reg = {
        "states": ["shadow", "permanent_role"],
        "entries": {
            "a": {"state": "shadow", "reviewBy": "2026-10-01"},
            "b": {"state": "shadow", "reviewBy": "2026-12-01"},
            "c": {"state": "permanent_role", "reason": "x"},
        },
    }
    assert [r["sourceKey"] for r in R.overdue(reg, date(2026, 10, 17))] == ["a"]


def test_a_plan_without_a_gate_is_invalid():
    reg = {"states": ["shadow"], "entries": {"x": {"state": "shadow", "reason": "r"}}}
    problems = R.validate(reg)
    assert any("promotionGate" in p for p in problems)
