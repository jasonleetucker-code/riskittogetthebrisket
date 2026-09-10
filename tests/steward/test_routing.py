import json
from pathlib import Path

import pytest

from src.steward.routing import diagnose_failures, measured, recommend, retrospective

POLICY = json.loads(
    (Path(__file__).resolve().parents[2] / "config/steward/routing.json").read_text()
)
AVAILABLE = list(POLICY["models"])


def route(**task):
    return recommend({"id": "test", **task}, POLICY, available=AVAILABLE)


def test_difficulty_escalation_and_mechanical_downgrade():
    assert route(mechanical=True)["model"] == "gpt-5.6-luna"
    assert route(cross_system=True)["profile"] == "COMPLEX"
    assert route(production_risk="high")["profile"] == "CRITICAL"
    assert route(previous_profile="ROUTINE", unresolved_failures=1)["profile"] == "STANDARD"
    assert route(unresolved_failures=2)["profile"] == "CRITICAL"
    assert route(previous_profile="CRITICAL", mechanical=True)["profile"] == "ROUTINE"


def test_pins_and_prohibitions_fail_closed():
    task = {"id": "test"}
    pinned = recommend(
        task, POLICY, available=AVAILABLE, owner={"model": "gpt-6-astra", "reasoning": "low"}
    )
    assert (pinned["model"], pinned["reasoning"]) == ("gpt-6-astra", "low")
    for owner in (
        {"model": "missing"},
        {"reasoning": "fictional"},
        {"prohibited_providers": ["openai"]},
        {"usage_remaining": 0},
    ):
        assert recommend(task, POLICY, available=AVAILABLE, owner=owner)["status"] == "BLOCKED"
    assert recommend(task, POLICY, available=["gpt-6-astra"])["model"] == "gpt-6-astra"
    assert recommend(task, POLICY, available=[])["status"] == "BLOCKED"


def test_routing_cannot_expand_authority_or_spend():
    result = recommend(
        {"id": "risk", "production_risk": "high"},
        POLICY,
        available=AVAILABLE,
        owner={
            "authority": "D_CONSEQUENTIAL",
            "max_incremental_usd": 100,
            "disable_delegation": True,
        },
    )
    assert result["authority"] == "A_REPORT_ONLY"
    assert result["max_incremental_usd"] == 0
    assert result["delegation_allowed"] is False
    assert route(deterministic=True)["status"] == "NO_MODEL"


def test_telemetry_unknown_and_challengers_do_not_self_promote():
    result = route()
    assert all(value is None for value in result["metrics"].values())
    result = measured(result, input_tokens=20, cost_usd=None)
    summary = retrospective([result])
    assert summary["groups"][0]["unknown"] == 1
    assert summary["groups"][0]["mean_measured_cost_usd"] is None
    assert summary["groups"][0]["auto_promote"] is False
    for value in (-1, float("nan"), True):
        with pytest.raises(ValueError):
            measured(result, cost_usd=value)


def test_repeated_distinct_context_failures_surface_instruction_reference():
    result = diagnose_failures(
        [
            {"accepted": False, "session": "A", "rule_ref": "docs/rule#1"},
            {"accepted": False, "session": "B", "rule_ref": "docs/rule#1"},
        ]
    )
    assert result["classification"] == "POSSIBLE_INSTRUCTION_DEFECT"
    assert result["rule_refs"] == ["docs/rule#1"]
