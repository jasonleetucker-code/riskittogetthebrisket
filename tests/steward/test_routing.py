import pytest

from src.steward.evidence import RunMetrics
from src.steward.routing import recommend_route


def test_deterministic_and_high_risk_work_do_not_get_cost_downgrades():
    assert recommend_route("deterministic", []).recommendation == "NO_MODEL"
    assert recommend_route("high_risk", []).recommendation == "INDEPENDENT_CONTEXT"


def test_rejections_prevent_automatic_downgrade():
    result = recommend_route("engineering", [RunMetrics("x", False, 1, reviewer_rejected=True)])
    assert result.recommendation == "CHAMPION_DEFAULT"


def test_a_clean_recommendation_cites_the_measured_evidence_behind_it():
    # A recommendation with no numbers attached is a guess, not "measurably
    # informed" -- the evidence must travel with the label.
    result = recommend_route(
        "engineering",
        [
            RunMetrics("a", True, 1, cost_usd=0.10, latency_ms=1000),
            RunMetrics("b", True, 1, cost_usd=0.20, latency_ms=2000),
        ],
    )
    assert result.recommendation == "LOWEST_MEASURED_SUFFICIENT"
    assert result.measured_runs == 2
    assert result.measured_mean_cost_usd == pytest.approx(0.15)
    assert result.measured_mean_latency_ms == 1500
    assert result.measured_rejection_rate == 0.0


def test_missing_cost_or_latency_on_some_runs_never_fabricates_a_mean_of_zero():
    result = recommend_route(
        "engineering", [RunMetrics("a", True, 1, cost_usd=None, latency_ms=None)]
    )
    assert result.measured_mean_cost_usd is None
    assert result.measured_mean_latency_ms is None


def test_no_model_and_independent_context_paths_report_no_measured_evidence():
    # These two paths never consult the evidence at all -- confirming they
    # stay at the zero-value defaults rather than silently picking some up.
    assert recommend_route("deterministic", []).measured_runs == 0
    assert (
        recommend_route(
            "high_risk", [RunMetrics("a", True, 1, cost_usd=5.0)]
        ).measured_mean_cost_usd
        is None
    )
