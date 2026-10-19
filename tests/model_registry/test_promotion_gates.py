"""``ModelRegistry.promote()`` runs a REAL gate for every family (chaseTradeMarket P5 / G10).

Before this, the only gate was the Hill scope gate, which skips any constant a
challenger does not carry — so a non-Hill model promoted vacuously (every scope
``UNCHANGED_FROM_CHAMPION``) and a Hill challenger that dropped a constant read as
"unchanged". These tests pin, all on synthetic registries:

* an unknown family is refused, never promoted by default;
* the Hill gate refuses a missing / undeclared / non-finite parameter;
* the generic gate refuses a missing, undeclared or out-of-bounds parameter, a
  missing or tampered evaluation receipt, a receipt for another version or
  another champion, a non-winning verdict, a missing holdout design, an
  unobserved pin, and a missing owner approval — and records what it concluded;
* a promotion never touches the chaseTradeMarket vote hold.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.model_registry import promotion_gates as pg
from src.model_registry.evaluation_receipt import (
    VERDICT_CHALLENGER_BETTER,
    VERDICT_INCONCLUSIVE,
    Estimate,
    cohort_result,
)
from src.model_registry.learning_receipt import NotApplicable, Unobserved
from src.model_registry.reproducible_evaluation import (
    EvaluationProvenance,
    evaluation_record,
    reproducible_evaluation_receipt,
)
from src.model_registry.versioning import ModelRegistry, ModelVersion, RegistryError
from src.sources import chase_trade_market as ctm

POLICY = pg.CHASE_TRADE_MARKET_POLICY
MODEL = POLICY.model_id
T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
SHA = "a" * 40
H = "sha256:" + "b" * 64

PARAMS = {
    "min_completed_dynasty_seasons": 3.0,
    "two_season_cohort_weight": 0.0,
    "recency_half_life_days": 90.0,
    "lineage_cap": 25.0,
    "huber_delta": 1.345,
    "prior_tau": 0.5,
}
CHAMP_PARAMS = {**PARAMS, "recency_half_life_days": 120.0}


def _provenance(version: int, **over) -> EvaluationProvenance:
    base = dict(
        code_sha=SHA,
        code_tree_clean=True,
        input_hashes={"underlying_trades": H, "format_captures": "c" * 64},
        snapshot_hash="d" * 64,
        model_version_id=POLICY.version_id(version),
        evaluated_at=T0,
        scoring_fingerprint=NotApplicable(
            "post-stratified to the declared reference format, not one league card"
        ),
    )
    base.update(over)
    return EvaluationProvenance(**base)


def _receipt(version: int = 2, *, champion: int | None = 1, **over):
    prov = over.pop("provenance", None) or _provenance(version)
    kwargs = dict(
        producer=ctm.RECEIPT_PRODUCER,
        native_id=f"ctm-eval-v{version}",
        role="challenger",
        champion_model_version_id=POLICY.version_id(champion) if champion else None,
        task="price completed dynasty trades",
        target="held-out accepted-trade residual",
        horizon="next 30 days",
        cohort_keys=["position"],
        cutoff=T0 - timedelta(days=1),
        point_in_time_rule="collectedAt <= cutoff; folds by manager-lineage component",
        feature_manifest_hash=NotApplicable("synthetic test"),
        prediction_set=Unobserved("synthetic test"),
        outcome_set=Unobserved("synthetic test"),
        preregistration=Unobserved("synthetic test"),
        overall=cohort_result(
            {"all": "all"}, n=120, metrics={"heldout_trade_loss": Estimate(point=0.41)}
        ),
        cohorts=[],
        holdout_design=["chronological", "league"],
        proposed_verdict=VERDICT_CHALLENGER_BETTER,
        verdict_basis="preregistered primary endpoint X3",
    )
    kwargs.update(over)
    return reproducible_evaluation_receipt(provenance=prov, **kwargs)


def _version(n: int, params, *, status="challenger", holdout=None) -> ModelVersion:
    return ModelVersion(
        model_id=MODEL,
        version=n,
        params=dict(params),
        fitted_at=f"2026-09-{n:02d}T00:00:00+00:00",
        producer="test",
        status=status,
        holdout=holdout,
    )


def _registry(*, receipt=None, params=PARAMS, holdout="auto") -> tuple[ModelRegistry, object]:
    receipt = receipt if receipt is not None else _receipt()
    if holdout == "auto":
        holdout = evaluation_record(receipt, criterion_name=POLICY.criterion_name)
    reg = ModelRegistry(MODEL)
    reg.seed_champion(_version(1, CHAMP_PARAMS, status="champion"))
    reg.add(_version(2, params, holdout=holdout))
    return reg, receipt


# ── dispatch ───────────────────────────────────────────────────────────────


def test_an_unknown_family_is_refused_not_promoted_vacuously():
    reg = ModelRegistry("some_new_model")
    reg.seed_champion(
        ModelVersion(
            model_id="some_new_model", version=1, params={"k": 1.0}, fitted_at="", producer="t"
        )
    )
    reg.add(
        ModelVersion(
            model_id="some_new_model", version=2, params={"k": 2.0}, fitted_at="", producer="t"
        )
    )
    with pytest.raises(RegistryError, match="no promotion gate is registered"):
        reg.promote(2, reason="looks better")
    assert reg.champion.version == 1


def test_the_hill_scope_gate_alone_would_have_passed_it():
    """Characterises the defect: the scope gate cannot refuse a non-Hill model."""
    from src.model_registry.scope_validation import assert_promotable

    states = assert_promotable({"k": 1.0}, {"k": 2.0})
    assert set(states.values()) == {"UNCHANGED_FROM_CHAMPION"}


def test_dispatch():
    assert pg.gate_kind_for(MODEL, {}, PARAMS) == pg.GATE_GENERIC_FAMILY
    assert pg.gate_kind_for("m", {}, {"HILL_PERCENTILE_C": 0.1}) == pg.GATE_HILL_SCOPE
    # A generic family's id wins even if someone smuggles Hill names in.
    assert pg.gate_kind_for(MODEL, {}, {"HILL_PERCENTILE_C": 0.1}) == pg.GATE_GENERIC_FAMILY


# ── Hill: no silent skip of missing parameters ─────────────────────────────

HILL_FULL = {name: 0.1 for name in pg.HILL_PARAMETER_NAMES}
_HILL_HOLDOUT = {"criterion": 700.0, "measuredAt": "2026-08-20T00:00:00+00:00"}


def _hill_reg(champ, chal) -> ModelRegistry:
    reg = ModelRegistry("m")
    reg.seed_champion(
        ModelVersion(model_id="m", version=1, params=champ, fitted_at="", producer="t")
    )
    reg.add(
        ModelVersion(
            model_id="m", version=2, params=chal, fitted_at="", producer="t", holdout=_HILL_HOLDOUT
        )
    )
    return reg


def test_hill_challenger_missing_a_champion_constant_is_refused():
    chal = {k: v for k, v in HILL_FULL.items() if k != "IDP_HILL_PERCENTILE_S"}
    with pytest.raises(RegistryError, match=r"missing parameter\(s\) \['IDP_HILL_PERCENTILE_S'\]"):
        _hill_reg(dict(HILL_FULL), chal).promote(2, reason="x")


def test_hill_undeclared_and_non_finite_parameters_are_refused():
    with pytest.raises(RegistryError, match="undeclared parameter"):
        _hill_reg(dict(HILL_FULL), {**HILL_FULL, "EXTRA": 1.0}).promote(2, reason="x")
    with pytest.raises(RegistryError, match="non-finite"):
        _hill_reg(dict(HILL_FULL), {**HILL_FULL, "HILL_PERCENTILE_C": float("nan")}).promote(
            2, reason="x"
        )


def test_hill_complete_offense_move_still_promotes_and_records_no_generic_block():
    chal = {**HILL_FULL, "HILL_PERCENTILE_C": 0.099}
    reg = _hill_reg(dict(HILL_FULL), chal)
    reg.promote(2, reason="held-out win")
    assert reg.champion.scope_validation["OFFENSE"] == "VALIDATED_EXTERNAL_HOLDOUT"
    assert reg.champion.promotion_gate is None
    assert "promotionGate" not in reg.champion.to_dict()


def test_hill_gate_refuses_generic_only_arguments():
    reg = _hill_reg(dict(HILL_FULL), {**HILL_FULL, "HILL_PERCENTILE_C": 0.099})
    with pytest.raises(RegistryError, match="belong to the generic gate"):
        reg.promote(2, reason="x", owner_approval="owner said so")


# ── generic gate: parameters ──────────────────────────────────────────────


def test_generic_happy_path_records_what_the_gate_concluded(tmp_path):
    reg, receipt = _registry()
    reg.promote(
        2, reason="preregistered X3 win", evaluation_receipt=receipt, owner_approval="owner #1"
    )
    gate = reg.champion.promotion_gate
    assert gate["gate"] == "generic_family:chase_trade_market"
    assert gate["parameters"] == "complete:6_of_6"
    assert gate["evaluationReceiptId"] == receipt.receipt_id
    assert gate["evaluationContentHash"] == receipt.content_hash()
    assert gate["modelVersionId"] == "mv:chase_trade_market:v2"
    assert gate["championModelVersionId"] == "mv:chase_trade_market:v1"
    assert gate["ownerApproval"] == "owner #1"
    assert gate["votingEffect"].startswith("none")
    assert reg.champion.scope_validation == {}
    reg.save(tmp_path)
    loaded = ModelRegistry.load(MODEL, tmp_path)
    assert loaded.champion.promotion_gate == gate
    blob = json.loads(ModelRegistry.path_for(MODEL, tmp_path).read_text(encoding="utf-8"))
    assert blob["versions"][0].get("promotionGate") is None  # retired champion: never gated


@pytest.mark.parametrize(
    "params, match",
    [
        (
            {k: v for k, v in PARAMS.items() if k != "lineage_cap"},
            r"missing declared .*lineage_cap",
        ),
        ({**PARAMS, "surprise": 1.0}, r"undeclared parameter\(s\) \['surprise'\]"),
        ({**PARAMS, "recency_half_life_days": float("inf")}, "not finite"),
        ({**PARAMS, "huber_delta": 99.0}, "outside its declared bounds"),
        # The directive clauses: no silent relaxation of three completed seasons.
        ({**PARAMS, "min_completed_dynasty_seasons": 2.0}, "outside its declared bounds"),
        ({**PARAMS, "two_season_cohort_weight": 0.3}, "outside its declared bounds"),
    ],
)
def test_generic_parameter_failures_are_refused(params, match):
    reg, receipt = _registry(params=params)
    with pytest.raises(RegistryError, match=match):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")
    assert reg.champion.version == 1 and reg.get(2).status == "challenger"


# ── generic gate: reproducible evaluation ─────────────────────────────────


def test_no_evaluation_record_is_refused():
    reg, receipt = _registry(holdout=None)
    with pytest.raises(RegistryError, match="no reproducible evaluation record"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_the_receipt_itself_is_required_not_only_its_hash():
    reg, _ = _registry()
    with pytest.raises(RegistryError, match="needs the evaluation receipt itself"):
        reg.promote(2, reason="x", owner_approval="owner")


def test_a_different_receipt_than_the_recorded_one_is_refused():
    reg, _ = _registry()
    other = _receipt(provenance=_provenance(2, snapshot_hash="e" * 64))
    with pytest.raises(RegistryError, match="content hash differs"):
        reg.promote(2, reason="x", evaluation_receipt=other, owner_approval="owner")


def test_a_receipt_for_another_version_is_refused():
    receipt = _receipt(3, provenance=_provenance(3))
    reg, _ = _registry(receipt=receipt)
    with pytest.raises(RegistryError, match="evaluates 'mv:chase_trade_market:v3'"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_a_win_against_another_champion_is_refused():
    receipt = _receipt(champion=None)
    reg, _ = _registry(receipt=receipt)
    with pytest.raises(RegistryError, match="a win against another champion"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_a_non_winning_verdict_is_refused():
    receipt = _receipt(proposed_verdict=VERDICT_INCONCLUSIVE)
    reg, _ = _registry(receipt=receipt)
    with pytest.raises(RegistryError, match="only 'challenger_better_pending_policy'"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_an_insufficient_sample_cannot_promote():
    receipt = _receipt(overall=cohort_result({"all": "all"}, n=0))
    # an empty population has no criterion to record at all
    with pytest.raises(Exception, match="no 'heldout_trade_loss' metric"):
        evaluation_record(receipt, criterion_name=POLICY.criterion_name)


def test_a_chronological_only_design_is_refused():
    receipt = _receipt(holdout_design=["chronological"])
    reg, _ = _registry(receipt=receipt)
    with pytest.raises(RegistryError, match=r"requires holdout design\(s\) \['league'\]"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_a_dirty_tree_is_refused():
    receipt = _receipt(provenance=_provenance(2, code_tree_clean=False))
    reg, _ = _registry(receipt=receipt)
    with pytest.raises(RegistryError, match="dirty tree"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_a_tampered_registry_record_is_refused():
    reg, receipt = _registry()
    v2 = reg.get(2)
    bad = dict(v2.holdout)
    bad["provenance"] = {**bad["provenance"], "snapshotHash": "f" * 64}
    reg = ModelRegistry(MODEL, [reg.get(1), replace(v2, holdout=bad)])
    with pytest.raises(RegistryError, match="registry's provenance differs"):
        reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")


def test_owner_approval_is_required_and_override_is_not_available():
    reg, receipt = _registry()
    with pytest.raises(RegistryError, match="requires explicit owner approval"):
        reg.promote(2, reason="x", evaluation_receipt=receipt)
    with pytest.raises(RegistryError, match="no scope override"):
        reg.promote(
            2,
            reason="x",
            evaluation_receipt=receipt,
            override_scopes={"OFFENSE"},
            override_reason="accept",
        )
    assert reg.champion.version == 1


def test_a_promotion_never_lifts_the_source_vote_hold():
    before = ctm.vote_holds()
    reg, receipt = _registry()
    reg.promote(2, reason="x", evaluation_receipt=receipt, owner_approval="owner")
    assert ctm.vote_holds() == before
    assert not any(ctm.may_vote(k) for k in ctm.SOURCE_KEYS)


def test_every_policy_is_internally_consistent():
    for model_id, policy in pg.GENERIC_FAMILY_POLICIES.items():
        assert model_id == policy.model_id
        assert policy.voting_effect and policy.promotion_policy
        assert set(policy.required_pins) <= {
            "codeSha",
            "sourceHashes",
            "snapshotHash",
            "scoringFingerprint",
        }
    assert POLICY.model_family == ctm.MODEL_FAMILY
