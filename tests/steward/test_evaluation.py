from src.steward.evaluation import DEFERRED_STAGES, IMPLEMENTED_STAGES, PIPELINE_STAGES, evaluate
from src.steward.evidence import RunMetrics


def test_evaluation_requires_held_out_evidence_and_authority():
    record = evaluate(
        "p",
        "champion",
        "challenger",
        ["held-out-1"],
        [RunMetrics("a", True, 1)],
        [RunMetrics("b", True, 1)],
    )
    assert record.recommendation == "CHALLENGER_ELIGIBLE_FOR_AUTHORITY_REVIEW"
    assert record.authority_required is True
    assert record.held_out_case_ids == ("held-out-1",)
    assert record.pipeline_stage_reached == "held_out_evaluation"


def test_deferred_pipeline_stages_are_named_and_disjoint_from_implemented_ones():
    # Naming a stage is not the same as having built it -- this proves the
    # two lists are genuinely disjoint and together cover every stage the
    # directive named, so a stage can't quietly be both or neither.
    assert set(IMPLEMENTED_STAGES) & set(DEFERRED_STAGES) == set()
    assert set(IMPLEMENTED_STAGES) | set(DEFERRED_STAGES) == set(PIPELINE_STAGES)
    assert "baseline" in DEFERRED_STAGES
    assert "held_out_evaluation" in IMPLEMENTED_STAGES
