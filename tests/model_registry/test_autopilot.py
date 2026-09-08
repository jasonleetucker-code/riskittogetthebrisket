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
    champ = ModelVersion(
        model_id="x",
        version=1,
        params={"HILL_PERCENTILE_C": 0.11, "HILL_PERCENTILE_S": 1.11},
        fitted_at="now",
        producer="test",
        holdout={"criterion": 100.0, "perSource": {"a": 1, "b": 1, "c": 1}},
    )
    reg = ModelRegistry("x")
    reg.seed_champion(champ)
    challenger = ModelVersion(
        model_id="x",
        version=2,
        params={"HILL_PERCENTILE_C": 0.10, "HILL_PERCENTILE_S": 1.11},
        fitted_at="now",
        producer="test",
        holdout={"criterion": 50.0, "perSource": {"a": 1, "b": 1, "c": 1}},
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
