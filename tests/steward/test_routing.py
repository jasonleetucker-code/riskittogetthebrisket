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
    assert summary["groups"][0]["status"] == "NO_EXECUTION_EVIDENCE"
    assert summary["groups"][0]["auto_promote"] is False
    for value in (-1, float("nan"), True):
        with pytest.raises(ValueError):
            measured(result, cost_usd=value)


def test_scorecards_require_execution_and_artifact_evidence():
    base = route()
    evaluated = [
        measured(
            base
            | {
                "execution": "EXECUTED",
                "acceptance": n != 0,
                "acceptance_evidence": "VERIFIED_AGAINST_ARTIFACT",
                "eval_case_id": f"case-{n}",
                "repo_head_end": "a" * 40,
                "first_pass": n > 1,
                "false_completion": n == 0,
            },
            input_tokens=100,
            output_tokens=20,
            duration_ms=100 + n,
            tool_calls=2,
            reviewer_corrections=int(n == 0),
            retries=int(n == 0),
            cost_usd=None,
        )
        for n in range(5)
    ]
    unevaluated = base | {"execution": "EXECUTED", "acceptance": True}
    unverified = base | {
        "execution": "EXECUTED",
        "acceptance": True,
        "eval_case_id": "claimed-case",
        "repo_head_end": "a" * 40,
    }
    card = retrospective(evaluated + [unevaluated, unverified, base])["groups"][0]
    assert (card["runs"], card["executed"], card["evaluated"]) == (8, 7, 5)
    assert (card["accepted"], card["rejected"], card["unknown"]) == (4, 1, 3)
    assert card["acceptance_rate"] == 0.8
    assert card["first_pass_acceptance_rate"] == 0.6
    assert card["false_completion_rate"] == 0.2
    assert card["tokens_per_accepted_task"] == 120
    assert card["mean_measured_cost_usd"] is None
    assert card["measured_cost_per_accepted_task_usd"] is None
    assert card["coverage"]["tool_calls"] == 5
    assert card["coverage"]["context_tokens"] == 0
    assert card["status"] == "CHALLENGER_CANDIDATE"
    assert card["auto_promote"] is False


def test_scorecards_keep_different_models_and_missing_evidence_separate():
    base = route()
    rows = [
        base | {"execution": "EXECUTED", "acceptance": True},
        base | {"execution": "EXECUTED", "model": "other", "acceptance": False},
    ]
    cards = retrospective(rows)["groups"]
    assert len(cards) == 2
    assert all(card["evaluated"] == 0 for card in cards)
    assert all(card["proposal"] is None for card in cards)


def test_cost_per_accepted_task_includes_failed_runs_only_with_full_cost_coverage():
    base = route()
    rows = [
        measured(
            base
            | {
                "execution": "EXECUTED",
                "acceptance": n > 0,
                "acceptance_evidence": "VERIFIED_AGAINST_ARTIFACT",
                "eval_case_id": f"case-{n}",
                "repo_head_end": "a" * 40,
            },
            cost_usd=2,
        )
        for n in range(5)
    ]
    card = retrospective(rows)["groups"][0]
    assert card["measured_cost_per_accepted_task_usd"] == 2.5
    rows[0] = measured(rows[0], cost_usd=None)
    assert retrospective(rows)["groups"][0]["measured_cost_per_accepted_task_usd"] is None
    rows[0]["repo_head_end"] = "not-a-sha"
    assert retrospective(rows)["groups"][0]["evaluated"] == 4


def test_cheaper_challenger_requires_costs_for_failed_runs_too():
    base = route()
    rows = [
        measured(
            base
            | {
                "execution": "EXECUTED",
                "acceptance": n > 0,
                "acceptance_evidence": "VERIFIED_AGAINST_ARTIFACT",
                "eval_case_id": f"case-{n}",
                "repo_head_end": "a" * 40,
                "first_pass": True,
            },
            cost_usd=None if n == 0 else 2,
        )
        for n in range(6)
    ]
    card = retrospective(rows)["groups"][0]
    assert card["acceptance_rate"] == 5 / 6
    assert card["first_pass_acceptance_rate"] == 5 / 6
    assert card["measured_cost_per_accepted_task_usd"] is None
    assert card["proposal"] == "collect measured cost before cheaper challenger"

    rows[0] = measured(rows[0], cost_usd=2)
    card = retrospective(rows)["groups"][0]
    assert card["measured_cost_per_accepted_task_usd"] == 12 / 5
    assert card["proposal"] == "evaluate cheaper challenger"


def test_failure_layer_needs_evidence_and_consistent_attribution():
    failures = [
        {"accepted": False, "failure_layer": "LOOP", "failure_layer_evidence_refs": ["receipt:1"]},
        {"accepted": False, "failure_layer": "LOOP", "failure_layer_evidence_refs": ["receipt:2"]},
    ]
    result = diagnose_failures(failures)
    assert result["engineering_layer"] == "LOOP"
    assert result["layer_evidence_refs"] == ["receipt:1", "receipt:2"]
    failures[1]["failure_layer_evidence_refs"] = []
    assert diagnose_failures(failures)["engineering_layer"] == "UNKNOWN"
    failures[1]["failure_layer_evidence_refs"] = ["receipt:2"]
    failures[1]["failure_layer"] = "GRAPH"
    assert diagnose_failures(failures)["engineering_layer"] == "UNKNOWN"


def test_repeated_distinct_context_failures_surface_instruction_reference():
    result = diagnose_failures(
        [
            {"accepted": False, "session": "A", "rule_ref": "docs/rule#1"},
            {"accepted": False, "session": "B", "rule_ref": "docs/rule#1"},
        ]
    )
    assert result["classification"] == "POSSIBLE_INSTRUCTION_DEFECT"
    assert result["rule_refs"] == ["docs/rule#1"]
