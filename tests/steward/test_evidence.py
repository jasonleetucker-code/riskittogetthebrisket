from src.steward.evidence import RunMetrics, autonomy_evidence, evaluate_challenger, retrospective

def test_unknown_cache_metrics_are_not_zero():
    assert RunMetrics("r", True, 1).cache_hit_ratio is None

def test_cost_cannot_override_correctness_or_review_failure():
    assert evaluate_challenger([RunMetrics("c", True, 1, cost_usd=10)], [RunMetrics("x", False, 1, reviewer_rejected=True, cost_usd=0)])["recommendation"] == "KEEP_CHAMPION"

def test_eligibility_does_not_grant_authority():
    assert autonomy_evidence([RunMetrics("r", True, 1)]).eligible
    assert evaluate_challenger([RunMetrics("a", True, 1)], [RunMetrics("b", True, 1)])["authority_required"]

def test_retrospective_only_proposes():
    assert retrospective([RunMetrics("r", True, 1, retries=2)])[0]["status"] == "PROPOSED_CHALLENGER"
