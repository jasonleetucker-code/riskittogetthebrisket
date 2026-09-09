from src.steward.evidence import RunMetrics, autonomy_evidence, evaluate_challenger, retrospective


def test_unknown_cache_metrics_are_not_zero():
    assert RunMetrics("r", True, 1).cache_hit_ratio is None


def test_cost_cannot_override_correctness_or_review_failure():
    assert (
        evaluate_challenger(
            [RunMetrics("c", True, 1, cost_usd=10)],
            [RunMetrics("x", False, 1, reviewer_rejected=True, cost_usd=0)],
        )["recommendation"]
        == "KEEP_CHAMPION"
    )


def _fully_eligible_evidence(**overrides):
    kwargs = dict(
        runs=[RunMetrics("r", True, 1)],
        rollback_proven=True,
        cost_compliant_runs=1,
        provenance_complete_runs=1,
    )
    kwargs.update(overrides)
    return autonomy_evidence(**kwargs)


def test_eligibility_does_not_grant_authority():
    assert _fully_eligible_evidence().eligible
    assert evaluate_challenger([RunMetrics("a", True, 1)], [RunMetrics("b", True, 1)])[
        "authority_required"
    ]


def test_eligibility_fails_closed_when_rollback_is_unmeasured_or_disproven():
    # Unmeasured (None, the default) and explicitly disproven (False) both
    # fail closed identically -- neither is "eligible enough."
    assert not autonomy_evidence([RunMetrics("r", True, 1)]).eligible
    assert not _fully_eligible_evidence(rollback_proven=False).eligible
    assert not _fully_eligible_evidence(rollback_proven=None).eligible


def test_eligibility_fails_closed_when_cost_compliance_is_unmeasured():
    assert not _fully_eligible_evidence(cost_compliant_runs=None).eligible


def test_eligibility_fails_closed_when_provenance_is_incomplete():
    assert not _fully_eligible_evidence(provenance_complete_runs=0).eligible


def test_eligibility_fails_closed_on_any_regression_gate_failure_or_owner_intervention():
    assert not _fully_eligible_evidence(regressions=1).eligible
    assert not _fully_eligible_evidence(deterministic_gate_failures=1).eligible
    assert not _fully_eligible_evidence(owner_interventions=1).eligible


def test_retrospective_only_proposes():
    assert (
        retrospective([RunMetrics("r", True, 1, retries=2)])[0]["status"] == "PROPOSED_CHALLENGER"
    )
