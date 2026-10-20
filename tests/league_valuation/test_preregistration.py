"""Preregistration gate and evaluation receipts (spec test i + governance)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.league_valuation import preregistration as pr
from src.model_registry.evaluation_receipt import VERDICTS, EvaluationReceipt
from src.model_registry.learning_receipt import NotApplicable, ReceiptError, Unobserved

REPO = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)
PINS = {
    "codeSha": "a" * 40,
    "sourceHashes": {"contract": "h1", "bdvmSnapshot": "h2"},
    "snapshotHash": "s" * 64,
    "scoringFingerprint": "sf1:0123456789abcdef",
    "formatFingerprint": "tmf1:fedcba9876543210",
    "bdvmParamSetId": "params_v1:abcdef123456",
    "hillMasterParamSet": "hill:v5",
    "challengerParamSetId": "league_fair_value_v1:1ba0dfff046b",
}


def _results(point=0.08, lo=0.04, hi=0.12, n=400, cohort_point=0.05, cohort_n=50, **inv):
    invariants = {"outOfRangeCount": 0, "lineageViolations": 0, "reproducibleFromPins": True}
    invariants.update(inv)
    return {
        "nativeId": "lfv-eval-test",
        "cutoff": CUTOFF,
        "championModelVersionId": "mv:canonical_board:rankDerivedValue",
        "primary": {
            "metric": pr.PRIMARY_METRIC,
            "n": n,
            "point": point,
            "ciLow": lo,
            "ciHigh": hi,
            "level": 0.9,
            "method": "paired bootstrap",
        },
        "cohorts": [
            {
                "position": p,
                "n": cohort_n,
                "point": cohort_point,
                "ciLow": -0.1,
                "ciHigh": 0.2,
                "level": 0.9,
            }
            for p in pr.COHORTS
        ],
        "invariants": invariants,
        "secondary": {"forward_ros_realized_points_spearman_delta": 0.9},
    }


FROZEN = pr.GateThresholds(
    frozen=True,
    min_ci_lower_bound=0.0,
    ci_level=0.9,
    bootstrap_iterations=2000,
    min_n_per_cohort=30,
    max_cohort_regression=0.05,
    holdout_window="2026-2027 NFL seasons",
    preregistration_commit="b" * 40,
    preregistration_committed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    owner_preconditions={
        "projectionUtilityInDynastyRuling": "owner ruling recorded 2026-08-01",
        "canonicalIdentityArchitecture": "league-scoped canonical",
    },
)


# (i) unfrozen thresholds give insufficient_sample, never challenger_better
def test_unfrozen_thresholds_are_insufficient_however_good_the_results():
    receipt = pr.build_evaluation_receipt(
        _results(point=0.9, lo=0.8, hi=1.0), pr.UNFROZEN, pins=PINS
    )
    body = receipt.body()
    assert body["verdict"] == "insufficient_sample"
    assert body["verdict"] != "challenger_better_pending_policy"
    assert body["promotes"] is False
    assert body["extra"]["disposition"] == pr.INSUFFICIENT


def test_committed_state_is_unfrozen_with_unrecorded_preconditions():
    assert pr.UNFROZEN.frozen is False
    assert not pr.UNFROZEN.preconditions_recorded
    assert all(getattr(pr.UNFROZEN, f) in (None, "") for f in pr.TO_FREEZE_FIELDS)


def test_receipt_is_an_evaluation_receipt_with_the_fixed_vocabulary():
    receipt = pr.build_evaluation_receipt(_results(), FROZEN, pins=PINS)
    assert isinstance(receipt, EvaluationReceipt)
    body = receipt.body()
    assert body["verdict"] in VERDICTS
    assert body["verdict"] == "challenger_better_pending_policy"
    assert body["promotes"] is False
    assert body["holdoutDesign"] == ["chronological"]
    assert set(body["inputPins"]) == {
        "codeSha",
        "sourceHashes",
        "snapshotHash",
        "scoringFingerprint",
    }
    assert set(body["extra"]["inputPinsExtended"]) == set(pr.EXTENDED_PIN_KEYS)
    receipt.to_learning_receipt()  # point-in-time validation passes


def test_disposition_map_covers_exactly_the_verdicts():
    assert set(pr.DISPOSITION_TO_VERDICT.values()) == set(VERDICTS)


@pytest.mark.parametrize(
    "kwargs,disposition",
    [
        ({"lo": -0.01, "hi": 0.1}, pr.INCONCLUSIVE),
        ({"point": -0.2, "lo": -0.3, "hi": -0.1}, pr.NOT_ELIGIBLE),
        ({"cohort_point": -0.2}, pr.NOT_ELIGIBLE),
        ({"outOfRangeCount": 1}, pr.NOT_ELIGIBLE),
        ({"lineageViolations": 2}, pr.NOT_ELIGIBLE),
        ({"reproducibleFromPins": False}, pr.NOT_ELIGIBLE),
        ({"cohort_n": 5}, pr.INSUFFICIENT),
    ],
)
def test_preregistered_dispositions(kwargs, disposition):
    receipt = pr.build_evaluation_receipt(_results(**kwargs), FROZEN, pins=PINS)
    assert receipt.extra["disposition"] == disposition
    assert receipt.body()["verdict"] == pr.DISPOSITION_TO_VERDICT[disposition]


def test_missing_invariant_evidence_fails_closed():
    res = _results()
    res["invariants"] = {}
    assert pr.disposition(res, FROZEN)[0] == pr.NOT_ELIGIBLE


def test_unrecorded_owner_preconditions_block_eligibility():
    thresholds = replace(FROZEN, owner_preconditions=pr._unrecorded_preconditions())
    receipt = pr.build_evaluation_receipt(_results(), thresholds, pins=PINS)
    assert receipt.extra["disposition"] == pr.INCONCLUSIVE
    assert receipt.body()["verdict"] == "inconclusive"


def test_secondary_metrics_never_gate():
    res = _results()
    res["primary"] = None
    res["secondary"] = {m: 0.99 for m in pr.SECONDARY_METRICS}
    receipt = pr.build_evaluation_receipt(res, FROZEN, pins=PINS)
    assert receipt.body()["verdict"] == "insufficient_sample"
    assert receipt.extra["secondaryMetricsGate"] is False


def test_a_different_primary_metric_is_refused():
    res = _results()
    res["primary"]["metric"] = "forward_ros_realized_points_spearman_delta"
    with pytest.raises(ReceiptError):
        pr.build_evaluation_receipt(res, FROZEN, pins=PINS)


def test_every_extended_pin_is_required():
    for key in pr.EXTENDED_PIN_KEYS:
        pins = dict(PINS)
        pins.pop(key)
        with pytest.raises(ReceiptError):
            pr.build_evaluation_receipt(_results(), FROZEN, pins=pins)
    pins = dict(
        PINS, hillMasterParamSet=Unobserved("not pinned"), formatFingerprint=NotApplicable("x")
    )
    pr.build_evaluation_receipt(_results(), FROZEN, pins=pins)


def test_freezing_requires_every_to_freeze_field():
    with pytest.raises(pr.PreregistrationError):
        pr.GateThresholds(frozen=True)
    with pytest.raises(pr.PreregistrationError):
        replace(FROZEN, preregistration_commit="abc123")
    with pytest.raises(pr.PreregistrationError):
        replace(FROZEN, forward_seasons=1)
    with pytest.raises(pr.PreregistrationError):
        replace(FROZEN, primary_metric="something_else")


def test_preregistration_must_precede_the_cutoff():
    late = replace(FROZEN, preregistration_committed_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ReceiptError):
        pr.build_evaluation_receipt(_results(), late, pins=PINS)


def test_markdown_twin_carries_every_machine_field():
    text = (REPO / pr.PREREGISTRATION_PATH).read_text(encoding="utf-8")
    assert pr.PRIMARY_METRIC in text
    for name in pr.TO_FREEZE_FIELDS + pr.OWNER_PRECONDITIONS + pr.SECONDARY_METRICS:
        assert name in text, name
    for disposition, verdict in pr.DISPOSITION_TO_VERDICT.items():
        assert re.search(rf"{disposition}.*{verdict}", text), (disposition, verdict)
    assert "TO-FREEZE" in text
