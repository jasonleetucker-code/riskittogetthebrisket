from src.steward.evidence import RunMetrics
from src.steward.routing import recommend_route

def test_deterministic_and_high_risk_work_do_not_get_cost_downgrades():
    assert recommend_route("deterministic", []).recommendation == "NO_MODEL"
    assert recommend_route("high_risk", []).recommendation == "INDEPENDENT_CONTEXT"

def test_rejections_prevent_automatic_downgrade():
    result = recommend_route("engineering", [RunMetrics("x", False, 1, reviewer_rejected=True)])
    assert result.recommendation == "CHAMPION_DEFAULT"
