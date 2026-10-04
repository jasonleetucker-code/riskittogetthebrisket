"""The typed advisor is an offline shadow, never an authority source."""

from __future__ import annotations

import json

import pytest

from src.steward.decision_advisor import PROFILE_LABELS, main, shadow_profile


def answer(label: str = "ROUTINE") -> dict:
    distribution = dict.fromkeys(PROFILE_LABELS, 0.0)
    distribution[label] = 1.0
    return {
        "schema_version": "steward-decision/v1",
        "decision_id": "shadow-1",
        "question_id": "task_profile",
        "question_type": "CHOICE",
        "candidate_labels": list(PROFILE_LABELS),
        "selected_label": label,
        "distribution": distribution,
        "abstained": label == "needs_system2",
        "provider": None,
        "model": None,
        "model_version": None,
        "raw_confidence": 1.0,
        "calibrated_probability": None,
        "latency_ms": None,
        "cost_usd": None,
        "evaluation_mode": "SHADOW",
    }


def test_confident_wrong_advice_never_changes_risk_baseline():
    result = shadow_profile({"id": "task-1", "production_risk": "high"}, answer("ROUTINE"))
    assert result["baseline_profile"] == "CRITICAL"
    assert result["advisor_label"] == "ROUTINE"
    assert result["disagreed"] is True
    assert result["calibrated_probability"] is None
    assert result["cost_usd_declared"] is None
    assert (result["authority"], result["effect"], result["provider_called"]) == (
        "A_REPORT_ONLY",
        "NONE",
        False,
    )


def test_abstention_is_a_real_escape_hatch():
    result = shadow_profile({"mechanical": True}, answer("needs_system2"))
    assert result["baseline_profile"] == "ROUTINE"
    assert result["abstained"] is True
    assert result["disagreed"] is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("question_id", "authorize_deploy"),
        ("selected_label", "ALLOW"),
        ("calibrated_probability", 0.99),
        ("evaluation_mode", "ACTIVE"),
        ("abstained", True),
        ("raw_confidence", float("nan")),
    ],
)
def test_unsafe_or_unmeasured_answer_fails_closed(key, value):
    candidate = answer()
    candidate[key] = value
    with pytest.raises(ValueError):
        shadow_profile({"mechanical": True}, candidate)


def test_distribution_and_extra_authority_field_fail_closed():
    candidate = answer()
    candidate["distribution"]["ROUTINE"] = 0.4
    with pytest.raises(ValueError, match="sum to one"):
        shadow_profile({}, candidate)
    candidate = answer()
    candidate["authorize_merge"] = True
    with pytest.raises(ValueError, match="fields differ"):
        shadow_profile({}, candidate)


def test_cli_is_offline_and_does_not_echo_task_context(tmp_path, capsys):
    task = tmp_path / "task.json"
    candidate = tmp_path / "answer.json"
    task.write_text(
        json.dumps({"id": "task-1", "goal": "PRIVATE-SOURCE-CONTENT", "mechanical": True}),
        encoding="utf-8",
    )
    candidate.write_text(json.dumps(answer()), encoding="utf-8")
    assert main(["--task", str(task), "--advisor-answer", str(candidate)]) == 0
    output = capsys.readouterr().out
    assert "PRIVATE-SOURCE-CONTENT" not in output
    assert json.loads(output)["effect"] == "NONE"


def test_bad_task_types_cannot_coerce_risk():
    with pytest.raises(ValueError, match="security_risk"):
        shadow_profile({"security_risk": "false"}, answer())
    with pytest.raises(ValueError, match="unresolved_failures"):
        shadow_profile({"unresolved_failures": True}, answer())
