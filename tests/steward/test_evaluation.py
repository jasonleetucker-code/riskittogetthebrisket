from src.steward.evaluation import evaluate
from src.steward.evidence import RunMetrics

def test_evaluation_requires_held_out_evidence_and_authority():
    record = evaluate("p", "champion", "challenger", ["held-out-1"], [RunMetrics("a", True, 1)], [RunMetrics("b", True, 1)])
    assert record.recommendation == "CHALLENGER_ELIGIBLE_FOR_AUTHORITY_REVIEW"
    assert record.authority_required is True
    assert record.held_out_case_ids == ("held-out-1",)
