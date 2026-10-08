"""``source_table`` is a display table: it must not present a missing input as
measured, nor a missing / zero coverage factor as full coverage (CLEANUP-3 D13).
Synthetic contracts only -- no live board, no network.
"""

from __future__ import annotations

from src.api.source_weighting_explain import source_table


def _contract(entry: dict) -> dict:
    return {"sourceWeighting": {"asOf": None, "sources": {"srcA": entry}}}


def _row(entry: dict) -> dict:
    (row,) = source_table(_contract(entry))["sources"]
    return row


_SUB = {"players": {"freshness": 0.8, "state": "AGING"}}


def test_unstated_measured_is_unknown_not_true():
    row = _row({"role": "model_input", "subsets": {}})
    assert row["measured"] is None
    assert _row({"role": "model_input", "measured": False, "subsets": {}})["measured"] is False


def test_missing_coverage_factor_leaves_the_product_unknown():
    row = _row(
        {
            "role": "model_input",
            "measured": True,
            "healthFactor": 1.0,
            "baseWeight": 1.0,
            "subsets": _SUB,
        }
    )
    assert row["coverageFactor"] is None
    assert row["dynamicFactor"] is None
    assert row["effectiveWeight"] is None


def test_zero_coverage_factor_is_a_real_zero_not_full_coverage():
    row = _row(
        {
            "role": "model_input",
            "measured": True,
            "healthFactor": 1.0,
            "coverageFactor": 0.0,
            "baseWeight": 1.0,
            "subsets": _SUB,
        }
    )
    assert row["dynamicFactor"] == 0.0
    assert row["effectiveWeight"] == 0.0


def test_fully_published_factors_multiply_unchanged():
    row = _row(
        {
            "role": "model_input",
            "measured": True,
            "healthFactor": 0.5,
            "coverageFactor": 0.5,
            "baseWeight": 2.0,
            "subsets": _SUB,
        }
    )
    assert row["dynamicFactor"] == 0.2
    assert row["effectiveWeight"] == 0.4
