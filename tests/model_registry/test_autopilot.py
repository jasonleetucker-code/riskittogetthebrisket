from __future__ import annotations

import pytest

from src.model_registry.autopilot import (
    AutopilotPolicy,
    CandidateScore,
    ForwardScore,
    compose_offense_only,
    decide,
)
from src.model_registry.versioning import ModelRegistry, ModelVersion, RegistryError


def _candidate(version: int, c: float, s: float, criterion: float) -> CandidateScore:
    return CandidateScore(
        version=version,
        c=c,
        s=s,
        criterion=criterion,
        per_source={"A": 500.0, "B": 600.0, "C": 700.0, "D": 300.0},
        per_source_rows={"A": 400, "B": 400, "C": 400, "D": 399},
        fitted_at=f"2026-08-{version + 10:02d}T00:00:00+00:00",
        status="challenger",
        training_inputs={"fit": "sha256:abc"},
    )


def test_tournament_can_select_an_older_candidate_and_clear_when_evidence_persists():
    candidates = [
        _candidate(6, 0.073, 1.130, 619.4),
        _candidate(7, 0.074, 1.150, 617.3),
        _candidate(8, 0.075, 1.135, 636.3),
    ]
    forward = [ForwardScore(str(i), 1160.0 + i, 620.0 + i) for i in range(5)]
    decision = decide(
        champion_criterion=1160.0,
        champion_per_source={"A": 1000.0, "B": 1200.0, "C": 1300.0, "D": 500.0},
        candidates=candidates,
        fitted_span_days={6: 0.0, 7: 7.0, 8: 14.0},
        forward_scores=forward,
        policy=AutopilotPolicy(),
    )
    assert decision.ready
    assert decision.winner_version == 7
    assert decision.stable_versions == (6, 7, 8)
    assert decision.forward_days == 5


def test_forward_persistence_is_mandatory_even_for_a_huge_current_win():
    candidate = _candidate(7, 0.074, 1.150, 500.0)
    decision = decide(
        champion_criterion=1160.0,
        champion_per_source={"A": 1000.0, "B": 1200.0, "C": 1300.0, "D": 500.0},
        candidates=[
            _candidate(6, 0.073, 1.130, 510.0),
            candidate,
            _candidate(8, 0.075, 1.135, 520.0),
        ],
        fitted_span_days={6: 0.0, 7: 7.0, 8: 14.0},
        forward_scores=[],
        policy=AutopilotPolicy(),
    )
    assert not decision.ready
    assert not decision.gates["forward_persistence"]


def test_composed_promotion_changes_offense_only():
    champ = {
        "HILL_GLOBAL_PERCENTILE_C": 0.112,
        "HILL_GLOBAL_PERCENTILE_S": 0.725,
        "HILL_PERCENTILE_C": 0.110,
        "HILL_PERCENTILE_S": 1.110,
        "IDP_HILL_PERCENTILE_C": 0.083,
        "IDP_HILL_PERCENTILE_S": 1.110,
        "HILL_ROOKIE_PERCENTILE_C": 0.153,
        "HILL_ROOKIE_PERCENTILE_S": 0.885,
    }
    winner = _candidate(7, 0.074, 1.150, 617.3)
    out = compose_offense_only(champ, winner)
    assert out["HILL_PERCENTILE_C"] == 0.074
    assert out["HILL_PERCENTILE_S"] == 1.150
    for key in set(champ) - {"HILL_PERCENTILE_C", "HILL_PERCENTILE_S"}:
        assert out[key] == champ[key]


def test_rejected_version_cannot_be_promoted():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    champ = ModelVersion(
        model_id="x",
        version=1,
        params={"HILL_PERCENTILE_C": 0.11, "HILL_PERCENTILE_S": 1.11},
        fitted_at="now",
        producer="test",
        holdout={"criterion": 100.0, "perSource": {"a": 1, "b": 1, "c": 1}, "measuredAt": now},
    )
    reg = ModelRegistry("x")
    reg.seed_champion(champ)
    challenger = ModelVersion(
        model_id="x",
        version=2,
        params={"HILL_PERCENTILE_C": 0.10, "HILL_PERCENTILE_S": 1.11},
        fitted_at="now",
        producer="test",
        holdout={"criterion": 50.0, "perSource": {"a": 1, "b": 1, "c": 1}, "measuredAt": now},
    )
    reg.add(challenger)
    reg.reject(2, reason="lost")
    with pytest.raises(RegistryError, match="only a standing challenger"):
        reg.promote(2, reason="should not happen")


def test_mark_applied_records_the_state_transition():
    reg = ModelRegistry("x")
    reg.seed_champion(
        ModelVersion(
            model_id="x",
            version=1,
            params={},
            fitted_at="now",
            producer="test",
        )
    )
    assert reg.champion.applied_at is None
    applied = reg.mark_applied(1)
    assert applied.applied_at is not None


class TestPolicyJsonWiring:
    """``scripts/hill_autopilot.py::_policy()`` must actually read every
    ``AutopilotPolicy`` field from ``config/model_registry/hill_autopilot_policy.json``.

    ``bootstrap_lower_quantile`` and ``min_bootstrap_lower_improvement_points``
    were added to the dataclass and to the JSON file, but ``_policy()`` never
    named them when constructing ``AutopilotPolicy(...)`` -- so both silently
    fell back to the dataclass defaults. The JSON values happened to equal
    those defaults, so the gate behaved correctly by coincidence; editing
    either key in the JSON would have changed nothing. This test sets every
    field to a distinct sentinel value not equal to its dataclass default and
    asserts the loaded policy actually reflects it, so a newly added field
    that isn't wired into ``_policy()`` fails here instead of shipping silent.
    """

    def test_every_field_is_sourced_from_the_json_not_the_default(self, tmp_path, monkeypatch):
        import importlib
        import json as json_module
        from dataclasses import fields

        hill_autopilot = importlib.import_module("scripts.hill_autopilot")

        camel_by_snake = {
            "min_current_improvement_points": "minCurrentImprovementPoints",
            "min_current_improvement_fraction": "minCurrentImprovementFraction",
            "min_improved_boards": "minImprovedBoards",
            "max_board_worsening_fraction": "maxBoardWorseningFraction",
            "min_rows_per_board": "minRowsPerBoard",
            "stable_candidates_required": "stableCandidatesRequired",
            "stable_span_days": "stableSpanDays",
            "candidate_criterion_band_fraction": "candidateCriterionBandFraction",
            "c_relative_tolerance": "cRelativeTolerance",
            "s_relative_tolerance": "sRelativeTolerance",
            "forward_days_required": "forwardDaysRequired",
            "forward_win_rate_required": "forwardWinRateRequired",
            "forward_median_improvement_points": "forwardMedianImprovementPoints",
            "bootstrap_lower_quantile": "bootstrapLowerQuantile",
            "min_bootstrap_lower_improvement_points": "minBootstrapLowerImprovementPoints",
        }
        policy_fields = {f.name for f in fields(AutopilotPolicy)}
        assert policy_fields == set(camel_by_snake), (
            "AutopilotPolicy grew or lost a field this test doesn't know about -- "
            "update camel_by_snake above, and confirm _policy() wires the new field."
        )

        default = AutopilotPolicy()
        sentinel_raw: dict[str, object] = {"schemaVersion": 1}
        for snake, camel in camel_by_snake.items():
            default_value = getattr(default, snake)
            # A sentinel that is guaranteed different from the default,
            # for both int-like and float-like fields.
            sentinel_raw[camel] = default_value + 1

        fake_policy_path = tmp_path / "hill_autopilot_policy.json"
        fake_policy_path.write_text(json_module.dumps(sentinel_raw))
        monkeypatch.setattr(hill_autopilot, "POLICY_PATH", fake_policy_path)

        loaded, raw = hill_autopilot._policy()

        for snake, camel in camel_by_snake.items():
            expected = sentinel_raw[camel]
            actual = getattr(loaded, snake)
            assert actual == expected, (
                f"AutopilotPolicy.{snake} did not pick up config/model_registry/"
                f"hill_autopilot_policy.json's '{camel}' -- _policy() is not wiring "
                f"this field, so editing it in the JSON has no effect."
            )
        assert raw == sentinel_raw
