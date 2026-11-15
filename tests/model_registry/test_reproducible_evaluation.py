"""Reproducible model-evaluation receipts (chaseTradeMarket P5 / G11).

Pins the master-plan §3.5 provenance rule as code: every evaluation a promotion
can rest on carries a full code SHA (clean tree), a hash per input, a snapshot
hash, the model version and the evaluation instant — and the receipt's content
hash is a deterministic function of every one of them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.model_registry.evaluation_receipt import (
    VERDICT_CHALLENGER_BETTER,
    Estimate,
    cohort_result,
)
from src.model_registry.feature_dictionary import load_dictionary, validate_manifest
from src.model_registry.learning_receipt import (
    ARTIFACT_STORE_WRITERS,
    ARTIFACT_STORES,
    NATIVE_STORES,
    NotApplicable,
    ReceiptError,
    Unobserved,
)
from src.model_registry.reproducible_evaluation import (
    EvaluationProvenance,
    evaluation_record,
    git_code_identity,
    reproducible_evaluation_receipt,
)
from src.sources import chase_trade_market as ctm

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _prov(**over) -> EvaluationProvenance:
    base = dict(
        code_sha="1" * 40,
        code_tree_clean=True,
        input_hashes={"underlying_trades": "2" * 64},
        snapshot_hash="sha256:" + "3" * 64,
        model_version_id="mv:chase_trade_market:v2",
        model_params_hash="8" * 64,
        evaluated_at=T0,
        scoring_fingerprint=NotApplicable("reference format, not one league card"),
        environment={"numpy": "2.1.0"},
    )
    base.update(over)
    return EvaluationProvenance(**base)


def _receipt(prov: EvaluationProvenance | None = None, **over):
    kwargs = dict(
        producer=ctm.RECEIPT_PRODUCER,
        native_id="ctm-eval-1",
        role="challenger",
        champion_model_version_id="mv:chase_trade_market:v1",
        task="t",
        target="held-out accepted-trade residual",
        horizon="30d",
        cohort_keys=[],
        cutoff=T0 - timedelta(hours=1),
        point_in_time_rule="collectedAt <= cutoff",
        feature_manifest_hash=Unobserved("synthetic"),
        prediction_set=Unobserved("synthetic"),
        outcome_set=Unobserved("synthetic"),
        preregistration=Unobserved("synthetic"),
        overall=cohort_result({"all": "all"}, n=10, metrics={"heldout_trade_loss": Estimate(0.5)}),
        cohorts=[],
        holdout_design=["chronological", "league"],
        proposed_verdict=VERDICT_CHALLENGER_BETTER,
        verdict_basis="synthetic",
    )
    kwargs.update(over)
    return reproducible_evaluation_receipt(provenance=prov or _prov(), **kwargs)


def test_same_pins_build_a_byte_identical_receipt():
    a, b = _receipt(), _receipt()
    assert a.to_dict() == b.to_dict()
    assert a.content_hash() == b.content_hash()


@pytest.mark.parametrize(
    "over",
    [
        {"code_sha": "4" * 40},
        {"input_hashes": {"underlying_trades": "5" * 64}},
        {"input_hashes": {"underlying_trades": "2" * 64, "format_captures": "6" * 64}},
        {"snapshot_hash": "7" * 64},
        {"model_params_hash": "9" * 64},
        {"evaluated_at": T0 + timedelta(seconds=1)},
        {"scoring_fingerprint": "sf1:abc"},
        {"environment": {"numpy": "2.2.0"}},
    ],
)
def test_every_pin_moves_the_content_hash(over):
    assert _receipt(_prov(**over)).content_hash() != _receipt().content_hash()


def test_the_receipt_carries_every_pin_concretely():
    body = _receipt().body
    pins = body["inputPins"]
    assert pins["codeSha"] == "1" * 40
    assert pins["sourceHashes"] == {"underlying_trades": "2" * 64}
    assert pins["snapshotHash"] == "sha256:" + "3" * 64
    assert pins["scoringFingerprint"]["state"] == "not_applicable"
    prov = body["extra"]["provenance"]
    assert prov["evaluatedAt"] == T0.isoformat()
    assert prov["modelVersionId"] == "mv:chase_trade_market:v2"
    assert prov["modelParamsHash"] == "8" * 64
    assert body["promotes"] is False


@pytest.mark.parametrize(
    "over, match",
    [
        ({"code_sha": "abc1234"}, "full 40-hex"),
        ({"code_sha": "unknown"}, "full 40-hex"),
        ({"input_hashes": {}}, "at least one input"),
        ({"input_hashes": {"x": "missing"}}, "sha256 content hash"),
        ({"snapshot_hash": ""}, "sha256 content hash"),
        ({"model_version_id": "chase_trade_market:v2"}, "mv:<family>:<token>"),
        ({"model_params_hash": ""}, "modelParamsHash must be a sha256"),
        ({"model_params_hash": "unknown"}, "modelParamsHash must be a sha256"),
        ({"evaluated_at": datetime(2026, 10, 1, 12)}, "naive"),
        ({"scoring_fingerprint": ""}, "explicit NotApplicable"),
        ({"scoring_fingerprint": NotApplicable("")}, "must say why"),
        ({"code_tree_clean": "yes"}, "must be a bool"),
    ],
)
def test_unprovable_pins_refuse_at_construction(over, match):
    with pytest.raises(ReceiptError, match=match):
        _prov(**over)


def test_an_evaluation_cannot_read_its_own_future():
    with pytest.raises(ReceiptError, match="after evaluatedAt"):
        _receipt(cutoff=T0 + timedelta(hours=1))


def test_provenance_owns_the_model_identity():
    with pytest.raises(ReceiptError, match="taken from the provenance"):
        _receipt(model_version_id="mv:chase_trade_market:v9")


def test_evaluation_record_is_what_the_registry_stores():
    receipt = _receipt()
    rec = evaluation_record(receipt, criterion_name="heldout_trade_loss")
    assert rec["criterion"] == 0.5
    assert rec["measuredAt"] == T0.isoformat()
    assert rec["evaluationReceipt"]["contentHash"] == receipt.content_hash()
    assert rec["evaluationReceipt"]["receiptId"] == receipt.receipt_id
    with pytest.raises(ReceiptError, match="reports no 'other' metric"):
        evaluation_record(receipt, criterion_name="other")


def test_git_code_identity_is_a_full_sha_or_a_refusal(tmp_path):
    sha, clean = git_code_identity()
    assert len(sha) == 40 and isinstance(clean, bool)
    with pytest.raises(ReceiptError, match="no reproducible code identity"):
        git_code_identity(tmp_path)


def test_the_model_store_is_registered_for_its_own_producer():
    assert ctm.MODEL_STORE in NATIVE_STORES
    assert ctm.MODEL_STORE in ARTIFACT_STORES
    assert ARTIFACT_STORE_WRITERS[ctm.MODEL_STORE] == {ctm.RECEIPT_PRODUCER}


def test_the_feature_manifest_validates_against_the_dictionary():
    digest = validate_manifest(
        load_dictionary(), consumer=ctm.MODEL_FAMILY, features=ctm.FEATURE_MANIFEST
    )
    assert len(digest) == 64
    # league maturity is deliberately not defined until P3's exact resolver lands
    names = {f["name"] for f in ctm.FEATURE_MANIFEST}
    assert not {n for n in names if "season" in n or "maturity" in n}
