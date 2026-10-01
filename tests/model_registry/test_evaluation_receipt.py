"""AL-0 evaluation receipt: A3 (missing is never zero) and A5 (fixed verdicts, no promotion)."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.model_registry import evaluation_receipt as er
from src.model_registry.learning_receipt import (
    NotApplicable,
    ReceiptError,
    Unobserved,
    model_version_id,
)

REPO = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc)
PINS = {
    "codeSha": "abc123",
    "sourceHashes": {"panelDigest": "d"},
    "snapshotHash": Unobserved("not pinned"),
    "scoringFingerprint": NotApplicable("scoring-independent"),
}


def _eval(
    overall, *, verdict=er.VERDICT_CHAMPION_RETAINED, cohorts=(), pins=PINS, role="challenger"
):
    return er.EvaluationReceipt(
        producer="test_producer",
        native_id="e1",
        model_family="test_family",
        model_version_id=model_version_id("test_family", "c1"),
        role=role,
        task="t",
        target="y",
        horizon="21d",
        cohort_keys=("stratum",),
        cutoff=CUTOFF,
        point_in_time_rule="known_at <= t",
        feature_manifest_hash="f" * 64,
        input_pins=pins,
        prediction_set=Unobserved("not persisted"),
        outcome_set=Unobserved("not persisted"),
        preregistration=Unobserved("none"),
        overall=overall,
        cohorts=cohorts,
        holdout_design=("chronological",),
        proposed_verdict=verdict,
        verdict_basis="test",
    )


def _ok(n=100):
    return er.cohort_result({"stratum": "ALL"}, n=n, metrics={"m": er.Estimate(point=0.5)})


class TestMissingIsNeverZero:
    def test_an_empty_cohort_is_insufficient_and_carries_no_metric(self):
        c = er.cohort_result({"stratum": "inSeason"}, n=0, metrics={"m": er.Estimate(point=0.0)})
        assert c.status == er.COHORT_INSUFFICIENT and c.metrics == {} and c.n == 0

    def test_an_empty_overall_population_forces_insufficient_sample(self):
        empty = er.cohort_result({"stratum": "ALL"}, n=0)
        body = _eval(empty, verdict=er.VERDICT_CHALLENGER_BETTER).body()
        assert body["verdict"] == er.VERDICT_INSUFFICIENT
        assert body["proposedVerdict"] == er.VERDICT_CHALLENGER_BETTER
        assert body["verdictOverridden"] is True
        assert body["overallResult"]["metrics"] == {}

    def test_unknown_n_must_say_why_and_is_never_coerced(self):
        with pytest.raises(ReceiptError, match="missing is never zero"):
            er.cohort_result({"s": "x"}, n=None, metrics={"m": er.Estimate(point=1.0)})
        c = er.cohort_result(
            {"s": "x"}, n=None, n_reason="not recorded", metrics={"m": er.Estimate(point=1.0)}
        )
        assert c.n is None and c.to_dict()["nReason"] == "not recorded"

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "10"])
    def test_n_is_a_nonnegative_int(self, bad):
        with pytest.raises(ReceiptError):
            er.cohort_result({"s": "x"}, n=bad, metrics={"m": er.Estimate(point=1.0)})

    def test_a_populated_cohort_without_a_metric_is_refused(self):
        with pytest.raises(ReceiptError):
            er.cohort_result({"s": "x"}, n=10, metrics={})

    @pytest.mark.parametrize("pin", er.PIN_KEYS)
    def test_every_pin_is_stated_and_none_is_empty(self, pin):
        missing = {k: v for k, v in PINS.items() if k != pin}
        with pytest.raises(ReceiptError):
            _eval(_ok(), pins=missing).body()
        with pytest.raises(ReceiptError):
            _eval(_ok(), pins={**PINS, pin: None}).body()

    def test_an_interval_must_state_level_and_method(self):
        with pytest.raises(ReceiptError):
            er.Estimate(point=1.0, interval=(0.5, 1.5))
        with pytest.raises(ReceiptError):
            er.Estimate(point=float("nan"))


class TestVerdictsAndPromotion:
    def test_the_vocabulary_is_fixed(self):
        assert er.VERDICTS == (
            "champion_retained",
            "challenger_better_pending_policy",
            "inconclusive",
            "insufficient_sample",
        )
        with pytest.raises(ReceiptError):
            _eval(_ok(), verdict="promote").body()

    def test_a_better_challenger_promotes_nothing(self):
        r = _eval(_ok(), verdict=er.VERDICT_CHALLENGER_BETTER).to_learning_receipt()
        assert r.body["verdict"] == er.VERDICT_CHALLENGER_BETTER
        assert r.body["promotes"] is False
        assert r.body["promotionRequires"]

    def test_role_and_holdout_design_vocabularies(self):
        with pytest.raises(ReceiptError):
            _eval(_ok(), role="king").body()

    def test_no_al0_module_touches_a_champion_pointer_or_promotion_writer(self):
        """A5 structurally: no learning module references the registry's promotion surface."""
        forbidden = {
            "promote",
            "apply",
            "set_champion",
            "champion_version",
            "decide_promotion",
            "compose_offense_only",
            "write_run_artifact",
            "prune_training_runs",
            "save",
            "record_version",
        }
        for rel in (
            "src/model_registry/learning_receipt.py",
            "src/model_registry/evaluation_receipt.py",
            "src/model_registry/feature_dictionary.py",
            "src/model_registry/receipt_store.py",
            "src/model_registry/learning_adapters.py",
        ):
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    pytest.fail(f"{rel} references .{node.attr}")
                if isinstance(node, ast.ImportFrom):
                    names = {a.name for a in node.names}
                    assert not (names & forbidden), f"{rel} imports {names & forbidden}"
                    assert node.module not in (
                        "src.model_registry.promotion",
                        "src.model_registry.autopilot",
                        "src.model_registry.versioning",
                    ), f"{rel} imports {node.module}"
