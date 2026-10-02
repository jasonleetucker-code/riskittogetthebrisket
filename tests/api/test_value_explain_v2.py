"""``value-explain/v2`` (#1555 Batch 2 Lane 6): clocks, freshness treatment,
exclusion reasons, the estimator, honest attribution and a non-additive
leave-one-out -- built on the newest complete archived scrape (no network).
"""

from __future__ import annotations

import json

import pytest

from src.api import value_replay as vr
from src.api.source_weighting_explain import EXPLAIN_VERSION, player_explain
from tests.archive_fixtures import newest_complete_raw_payload


@pytest.fixture(scope="module")
def contract():
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    return vr.build(json.loads(json.dumps(payload)))


def _explain(contract, predicate):
    row = next((r for r in contract["playersArray"] if predicate(r)), None)
    if row is None:
        pytest.skip("archive has no such row")
    return row, player_explain(contract, row, {})


def test_every_source_keeps_three_separate_clocks_with_explicit_unknowns(contract):
    _row, out = _explain(contract, lambda r: len(r.get("sourceRankMeta") or {}) >= 5)
    assert out["explainVersion"] == EXPLAIN_VERSION
    for src in out["modelSources"]:
        clocks = src["clocks"]
        assert set(clocks) >= {"lastFetchedAt", "publishedAsOf", "lastConfirmedChangeAt"}
        # No fetch stamps were supplied: the fetch clock is unknown, never invented.
        assert clocks["lastFetchedAt"] is None
        assert "lastFetchedAt" in clocks["unknown"]
        assert src["freshnessTreatment"]["treatment"] in {
            "full_weight",
            "down_weighted",
            "excluded",
            "unknown",
        }


def test_fetch_stamps_fill_the_fetch_clock_only(contract):
    row = next(r for r in contract["playersArray"] if len(r.get("sourceRankMeta") or {}) >= 5)
    key = next(iter(row["sourceRankMeta"]))
    out = player_explain(contract, row, {key: {"lastFetched": "2026-10-01T00:00:00Z"}})
    src = next(s for s in out["modelSources"] if s["source"] == key)
    assert src["clocks"]["lastFetchedAt"] == "2026-10-01T00:00:00Z"
    assert src["clocks"]["publishedAsOf"] != "2026-10-01T00:00:00Z" or (
        src["clocks"]["publishedAsOf"] is None
    )


def test_voters_have_no_exclusion_reason_and_non_voters_always_do(contract):
    _row, out = _explain(contract, lambda r: bool(r.get("droppedSources")))
    for src in out["modelSources"]:
        if src["status"] == "voting":
            assert src["exclusionReason"] is None
        else:
            assert src["exclusionReason"], src["source"]
    assert any((s["exclusionReason"] or "").startswith("outlier:") for s in out["modelSources"])


def test_estimator_and_attribution_are_honest_about_median_rungs(contract):
    _row, out = _explain(
        contract,
        lambda r: r.get("assetClass") == "offense" and len(r.get("sourceRankMeta") or {}) >= 5,
    )
    est = out["estimator"]
    assert est["path"] == "flat_count_aware_blend"
    assert est["rung"] in {"weighted_mean_median_untrimmed", "weighted_mean_median_trimmed"}
    assert out["attribution"]["exact"] is False
    assert all(s["contributionIsApproximate"] for s in out["modelSources"])


def test_leave_one_out_is_labelled_non_additive_and_reproduces_first(contract):
    _row, out = _explain(
        contract,
        lambda r: r.get("assetClass") == "offense"
        and vr.blend_check(r).get("status") == "reproduced"
        and len(r.get("sourceRankMeta") or {}) >= 4,
    )
    loo = out["leaveOneOut"]
    assert loo["nonAdditive"] is True
    assert loo["available"] is True
    assert loo["withoutEach"]
    assert all({"source", "valueWithout", "delta"} <= set(e) for e in loo["withoutEach"])


def test_non_offense_rows_decline_leave_one_out_rather_than_guess(contract):
    _row, out = _explain(contract, lambda r: r.get("assetClass") == "pick")
    assert out["leaveOneOut"]["available"] is False
    assert out["estimator"]["path"]  # provenance class, never blank
