"""Owner methodology decision 1: Hill Autopilot automatic OFFENSE promotion
requires at least one genuinely independent validation target.

The board-holdout gates stay required (necessary, not sufficient). With no
eligible target the outcome is ``AUTO_PROMOTION_BLOCKED`` with reason exactly
``no_independent_validation_target``. Targets here are SYNTHETIC and test-only:
the production registry is empty and must stay empty until a real
preregistered target exists.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.model_registry import independent_validation as iv
from src.model_registry.autopilot import (
    BOARD_GATES,
    INDEPENDENT_GATE,
    OUTCOME_BLOCKED,
    OUTCOME_HOLD,
    OUTCOME_READY,
    AutopilotPolicy,
    CandidateScore,
    ForwardScore,
    decide,
)
from src.model_registry.independent_validation import (
    INDEPENDENT_VALIDATION_TARGETS,
    REASON_EVIDENCE_MISMATCH,
    REASON_NO_TARGET,
    REASON_TARGET_FAILED,
    TREATMENT_COMPONENT_EXCLUDED,
    TREATMENT_NO_SHARED_PROVENANCE,
    IndependenceTreatment,
    IndependentValidationTarget,
    ProvenanceComponent,
    RuleOutcome,
    assess_target,
    evaluate_independent_validation,
)

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "refit-hill-curves.yml"

TRAINING = ("ktcCrowd", "dynastyDaddySf")
WINNER = 7


# ── synthetic fixtures ──────────────────────────────────────────────────────


def _candidate(version: int, c: float, s: float, criterion: float) -> CandidateScore:
    return CandidateScore(
        version=version,
        c=c,
        s=s,
        criterion=criterion,
        per_source={"A": 500.0, "B": 600.0, "C": 700.0, "D": 300.0},
        per_source_rows={"A": 400, "B": 400, "C": 400, "D": 399},
        fitted_at=f"2026-08-{version + 10:02d}T00:00:00+00:00",
        status="challenger",
        training_inputs={"fit": "sha256:abc"},
    )


def _board_passing_kwargs(**overrides):
    """Inputs that clear every BOARD gate, with v7 the winner."""
    kw = dict(
        champion_criterion=1160.0,
        champion_per_source={"A": 1000.0, "B": 1200.0, "C": 1300.0, "D": 500.0},
        candidates=[
            _candidate(6, 0.073, 1.130, 619.4),
            _candidate(7, 0.074, 1.150, 617.3),
            _candidate(8, 0.075, 1.135, 636.3),
        ],
        fitted_span_days={6: 0.0, 7: 7.0, 8: 14.0},
        forward_scores=[ForwardScore(str(i), 1160.0 + i, 620.0 + i) for i in range(5)],
        policy=AutopilotPolicy(),
    )
    kw.update(overrides)
    return kw


def _rule(passed: bool):
    def rule(cc, cs, xc, xs):
        return RuleOutcome(passed, {"championC": cc, "challengerC": xc})

    return rule


def _target(
    target_id="synthetic-independent",
    *,
    provenance=None,
    independence=None,
    rule=None,
    prereg=("docs/prereg/synthetic.md", "abc123"),
):
    provenance = (
        provenance
        if provenance is not None
        else (ProvenanceComponent("sleeper", "sleeperTxn", ("sleeperTxnKey",)),)
    )
    independence = (
        independence
        if independence is not None
        else {f: IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE) for f in TRAINING}
    )
    return IndependentValidationTarget(
        target_id=target_id,
        preregistration_path=prereg[0],
        preregistration_commit=prereg[1],
        provenance=provenance,
        independence=independence,
        rule=rule or _rule(True),
        rule_id="synthetic-rule",
    )


FAMILIES = {
    "sleeperTxnKey": "sleeperTxn",
    "ktcTradeDbKey": "ktcTrades",
    "ktc": "ktcCrowd",
}


def _providers(*, committed=True, lineage=None):
    lineage = lineage if lineage is not None else {}

    def prereg(path, commit):
        return committed

    def lineage_for(key):
        if key in lineage:
            return lineage[key]
        return {f: "INDEPENDENT_NO_EVIDENCE" for f in TRAINING}

    return dict(
        preregistration_committed=prereg,
        lineage_for=lineage_for,
        family_of=FAMILIES.get,
    )


def _evidence(targets, *, version=WINNER, **prov):
    return evaluate_independent_validation(
        targets,
        challenger_version=version,
        training_families=TRAINING,
        champion_c=0.11,
        champion_s=1.11,
        challenger_c=0.074,
        challenger_s=1.15,
        **_providers(**prov),
    )


def _assess(target, **prov):
    return assess_target(target, training_families=TRAINING, **_providers(**prov))


# ── the empty production registry ───────────────────────────────────────────


class TestEmptyRegistryBlocks:
    def test_production_registry_is_empty(self):
        """Owner decision 1: no target may be created merely to restore promotion.
        Adding one requires a committed preregistration; update this pin then."""
        assert INDEPENDENT_VALIDATION_TARGETS == ()

    def test_otherwise_passing_challenger_is_blocked_with_the_exact_reason(self):
        evidence = _evidence(INDEPENDENT_VALIDATION_TARGETS)
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert all(d.gates[g] for g in BOARD_GATES)
        assert d.gates[INDEPENDENT_GATE] is False
        assert not d.ready
        assert d.outcome == OUTCOME_BLOCKED == "AUTO_PROMOTION_BLOCKED"
        assert d.reason == REASON_NO_TARGET == "no_independent_validation_target"
        assert d.independent_validation_reason == "no_independent_validation_target"

    def test_missing_evidence_fails_closed_the_same_way(self):
        d = decide(**_board_passing_kwargs())
        assert (d.ready, d.outcome, d.reason) == (False, OUTCOME_BLOCKED, REASON_NO_TARGET)

    def test_all_targets_ineligible_is_no_target(self):
        evidence = _evidence([_target()], committed=False)
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert d.reason == REASON_NO_TARGET


# ── board gates still required; precedence ──────────────────────────────────


class TestBoardGatesStillRequired:
    def test_failing_board_gate_blocks_for_its_own_reason_even_with_a_passing_target(self):
        evidence = _evidence([_target()])
        d = decide(**_board_passing_kwargs(forward_scores=[]), independent_validation=evidence)
        assert d.gates[INDEPENDENT_GATE] is True
        assert not d.ready
        assert d.outcome == OUTCOME_HOLD
        assert d.reason == "blocked by: forward_persistence"

    def test_board_reason_takes_precedence_over_independent_reason(self):
        d = decide(**_board_passing_kwargs(forward_scores=[]))
        assert d.outcome == OUTCOME_HOLD
        assert d.reason == "blocked by: forward_persistence"
        assert "independent" not in d.reason
        # ...while the independent verdict is still recorded.
        assert d.gates[INDEPENDENT_GATE] is False
        assert d.independent_validation_reason == REASON_NO_TARGET

    def test_no_winner_takes_precedence_over_everything(self):
        d = decide(**_board_passing_kwargs(candidates=[]), independent_validation=None)
        assert (d.outcome, d.reason) == (OUTCOME_HOLD, "no eligible standing challenger")
        assert d.independent_validation_reason == REASON_NO_TARGET

    def test_every_existing_board_gate_is_unchanged_and_reported(self):
        d = decide(**_board_passing_kwargs(), independent_validation=_evidence([_target()]))
        assert tuple(d.gates) == (*BOARD_GATES, INDEPENDENT_GATE)
        assert BOARD_GATES == (
            "winner",
            "current_margin",
            "per_source",
            "leave_one_market_out",
            "cross_market_bootstrap",
            "row_health",
            "parameter_stability",
            "forward_persistence",
        )

    def test_row_health_failure_still_blocks(self):
        d = decide(
            **_board_passing_kwargs(recent_row_health_ok=False),
            independent_validation=_evidence([_target()]),
        )
        assert (d.outcome, d.reason) == (OUTCOME_HOLD, "blocked by: row_health")


# ── eligibility ─────────────────────────────────────────────────────────────


class TestEligibility:
    def test_clean_synthetic_target_is_eligible(self):
        a = _assess(_target())
        assert a.eligible and a.ineligible_reasons == ()

    def test_target_deriving_from_a_training_family_is_ineligible(self):
        t = _target(
            provenance=(ProvenanceComponent("ktc-db", "ktcCrowd", ("ktc",)),),
            independence={
                "ktcCrowd": IndependenceTreatment(TREATMENT_COMPONENT_EXCLUDED, ()),
                "dynastyDaddySf": IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE),
            },
        )
        a = _assess(t)
        assert not a.eligible
        assert "derives_from_training_family:ktc-db:ktcCrowd" in a.ineligible_reasons

    def test_no_shared_provenance_contradicted_by_a_component_is_ineligible(self):
        t = _target(provenance=(ProvenanceComponent("ktc-db", "ktcCrowd", ("ktc",)),))
        a = _assess(t)
        assert not a.eligible
        assert "treatment_contradicts_provenance:ktcCrowd:ktc-db" in a.ineligible_reasons
        assert "derives_from_training_family:ktc-db:ktcCrowd" in a.ineligible_reasons

    @pytest.mark.parametrize(
        "lineage",
        [
            {},  # the owner names no category -> UNKNOWN
            {"ktcCrowd": "UNKNOWN", "dynastyDaddySf": "INDEPENDENT_NO_EVIDENCE"},
            {"ktcCrowd": "SUSPECTED_DEPENDENCE", "dynastyDaddySf": "INDEPENDENT_NO_EVIDENCE"},
            {"ktcCrowd": "MEASURED_DEPENDENCE", "dynastyDaddySf": "INDEPENDENT_NO_EVIDENCE"},
            {"ktcCrowd": "PROVEN_COMMON_ANCESTRY", "dynastyDaddySf": "INDEPENDENT_NO_EVIDENCE"},
        ],
    )
    def test_unknown_or_dependent_lineage_is_ineligible(self, lineage):
        a = _assess(_target(), lineage={"sleeperTxnKey": lineage})
        assert not a.eligible
        assert any(
            r.startswith("lineage_not_independent:sleeperTxnKey:") for r in a.ineligible_reasons
        )

    def test_lineage_lookup_that_raises_fails_closed(self):
        def boom(key):
            raise RuntimeError("lineage file unreadable")

        a = assess_target(
            _target(),
            training_families=TRAINING,
            preregistration_committed=lambda p, c: True,
            lineage_for=boom,
            family_of=FAMILIES.get,
        )
        assert not a.eligible
        assert "lineage_not_independent:sleeperTxnKey:ktcCrowd:UNKNOWN" in a.ineligible_reasons

    def test_unregistered_source_and_unverifiable_component_are_ineligible(self):
        t = _target(
            provenance=(
                ProvenanceComponent("mystery", "sleeperTxn", ("notARegisteredKey",)),
                ProvenanceComponent("blank", "otherFam", ()),
            )
        )
        a = _assess(t)
        assert "source_unregistered:notARegisteredKey" in a.ineligible_reasons
        assert "provenance_unverifiable:blank" in a.ineligible_reasons

    def test_declared_family_must_match_the_source_registry(self):
        t = _target(provenance=(ProvenanceComponent("c", "sleeperTxn", ("ktcTradeDbKey",)),))
        a = _assess(t)
        assert "family_mismatch:ktcTradeDbKey:ktcTrades!=sleeperTxn" in a.ineligible_reasons

    def test_uncommitted_preregistration_is_ineligible(self):
        a = _assess(_target(), committed=False)
        assert not a.eligible
        assert "preregistration_not_committed:docs/prereg/synthetic.md@abc123" in (
            a.ineligible_reasons
        )

    def test_undeclared_preregistration_is_ineligible(self):
        a = _assess(_target(prereg=("", "")))
        assert "preregistration_undeclared" in a.ineligible_reasons

    def test_preregistration_check_that_raises_fails_closed(self):
        def boom(p, c):
            raise OSError("no git")

        a = assess_target(
            _target(),
            training_families=TRAINING,
            preregistration_committed=boom,
            lineage_for=_providers()["lineage_for"],
            family_of=FAMILIES.get,
        )
        assert not a.eligible

    def test_mixed_provenance_without_explicit_treatment_is_ineligible(self):
        """Sleeper transactions mixed with KTC Trade DB rows, with no treatment for
        the challenger family the KTC component touches: never wholesale independent."""
        t = _target(
            provenance=(
                ProvenanceComponent("sleeper", "sleeperTxn", ("sleeperTxnKey",)),
                ProvenanceComponent("ktc-db", "ktcCrowd", ("ktc",)),
            ),
            independence={"dynastyDaddySf": IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE)},
        )
        a = _assess(t)
        assert not a.eligible
        assert "missing_independence_treatment:ktcCrowd" in a.ineligible_reasons

    def test_mixed_provenance_with_explicit_exclusion_can_be_eligible(self):
        t = _target(
            provenance=(
                ProvenanceComponent("sleeper", "sleeperTxn", ("sleeperTxnKey",)),
                ProvenanceComponent("ktc-db", "ktcCrowd", ("ktc",)),
            ),
            independence={
                "ktcCrowd": IndependenceTreatment(
                    TREATMENT_COMPONENT_EXCLUDED, ("ktc-db",), "scored without KTC rows"
                ),
                "dynastyDaddySf": IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE),
            },
        )
        assert _assess(t).eligible

    def test_exclusion_must_cover_every_component_of_the_family(self):
        t = _target(
            provenance=(
                ProvenanceComponent("sleeper", "sleeperTxn", ("sleeperTxnKey",)),
                ProvenanceComponent("ktc-a", "ktcCrowd", ("ktc",)),
                ProvenanceComponent("ktc-b", "ktcCrowd", ("ktc",)),
            ),
            independence={
                "ktcCrowd": IndependenceTreatment(TREATMENT_COMPONENT_EXCLUDED, ("ktc-a", "ghost")),
                "dynastyDaddySf": IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE),
            },
        )
        a = _assess(t)
        assert "family_component_not_excluded:ktcCrowd:ktc-b" in a.ineligible_reasons
        assert "excluded_component_unknown:ktcCrowd:ghost" in a.ineligible_reasons

    def test_unanticipated_training_family_is_ineligible(self):
        a = assess_target(_target(), training_families=(*TRAINING, "newFamily"), **_providers())
        assert "missing_independence_treatment:newFamily" in a.ineligible_reasons

    def test_unknown_training_families_fail_closed(self):
        a = assess_target(_target(), training_families=(), **_providers())
        assert "challenger_training_families_unknown" in a.ineligible_reasons

    def test_unknown_treatment_vocabulary_is_ineligible(self):
        t = _target(
            independence={
                "ktcCrowd": IndependenceTreatment("independent"),
                "dynastyDaddySf": IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE),
            }
        )
        assert "unknown_independence_treatment:ktcCrowd:independent" in (
            _assess(t).ineligible_reasons
        )

    def test_ktc_trade_database_alone_is_not_independent_for_the_live_ktc_trained_curve(self):
        """Owner rule, against the REAL lineage owner and the live OFFENSE trainers:
        a target built only from KTC Trade Database evidence is ineligible even when
        it declares 'no shared provenance' for every family."""
        families, by_family = iv.offense_training_lineage()
        assert "ktcCrowd" in families
        t = IndependentValidationTarget(
            target_id="ktc-trade-db-only",
            preregistration_path="CLAUDE.md",
            preregistration_commit="HEAD",
            provenance=(ProvenanceComponent("ktc-db", "ktcTrades", ("ktcTradesSfTep",)),),
            independence={
                f: IndependenceTreatment(TREATMENT_NO_SHARED_PROVENANCE) for f in families
            },
            rule=_rule(True),
        )
        a = assess_target(
            t,
            training_families=families,
            preregistration_committed=lambda p, c: True,
            lineage_for=iv.lineage_lookup(by_family),
            family_of=iv.registry_family_lookup(),
        )
        assert not a.eligible
        assert any(
            r.startswith("lineage_not_independent:ktcTradesSfTep:ktcCrowd:")
            for r in a.ineligible_reasons
        )


# ── passing / failing an eligible target ────────────────────────────────────


class TestEligibleTargetRule:
    def test_passing_an_eligible_synthetic_target_allows_promotion(self):
        evidence = _evidence([_target(rule=_rule(True))])
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert d.ready
        assert d.outcome == OUTCOME_READY
        assert d.reason == "all automatic-promotion evidence gates cleared"
        assert d.independent_validation_reason is None

    def test_failing_an_eligible_target_blocks(self):
        evidence = _evidence([_target(rule=_rule(False))])
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert not d.ready
        assert (d.outcome, d.reason) == (OUTCOME_BLOCKED, REASON_TARGET_FAILED)

    def test_every_eligible_target_must_pass(self):
        evidence = _evidence([_target("a", rule=_rule(True)), _target("b", rule=_rule(False))])
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert (d.outcome, d.reason) == (OUTCOME_BLOCKED, REASON_TARGET_FAILED)

    def test_ineligible_targets_neither_help_nor_hurt(self):
        evidence = _evidence(
            [
                _target("ok", rule=_rule(True)),
                _target("bad", rule=_rule(False), prereg=("", "")),
            ]
        )
        assert [a.target_id for a in evidence.eligible] == ["ok"]
        assert decide(**_board_passing_kwargs(), independent_validation=evidence).ready

    def test_rule_is_never_run_for_an_ineligible_target(self):
        def explode(*a):
            raise AssertionError("rule ran for an ineligible target")

        evidence = _evidence([_target(rule=explode)], committed=False)
        assert evidence.assessments[0].passed is None

    def test_a_rule_that_raises_fails_closed(self):
        def broken(*a):
            raise ValueError("scorer crashed")

        evidence = _evidence([_target(rule=broken)])
        assert evidence.assessments[0].passed is False
        assert "ruleError" in evidence.assessments[0].rule_detail
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert d.reason == REASON_TARGET_FAILED

    def test_evidence_for_another_challenger_does_not_count(self):
        evidence = _evidence([_target(rule=_rule(True))], version=6)
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert (d.outcome, d.reason) == (OUTCOME_BLOCKED, REASON_EVIDENCE_MISMATCH)


# ── evidence keeps accumulating while blocked ───────────────────────────────


class TestPersistenceContinuesWhileBlocked:
    def test_blocked_decision_carries_the_same_persistence_evidence(self):
        blocked = decide(**_board_passing_kwargs())
        passing = decide(**_board_passing_kwargs(), independent_validation=_evidence([_target()]))
        assert blocked.outcome == OUTCOME_BLOCKED and passing.outcome == OUTCOME_READY
        for field_name in (
            "winner_version",
            "stable_versions",
            "forward_days",
            "forward_win_rate",
            "forward_median_improvement",
            "bootstrap_lower_improvement",
            "current_improvement",
            "required_improvement",
        ):
            assert getattr(blocked, field_name) == getattr(passing, field_name), field_name
        assert blocked.forward_days == 5
        assert blocked.stable_versions == (6, 7, 8)
        assert {k: v for k, v in blocked.gates.items() if k != INDEPENDENT_GATE} == {
            k: v for k, v in passing.gates.items() if k != INDEPENDENT_GATE
        }


# ── the refit script and workflow treat blocked as success ──────────────────


class TestScriptAndWorkflow:
    def test_blocked_maps_to_exit_zero(self):
        from scripts import hill_autopilot as ha

        blocked = decide(**_board_passing_kwargs())
        assert blocked.outcome == OUTCOME_BLOCKED
        assert ha.exit_code_for(blocked) == 0
        ready = decide(**_board_passing_kwargs(), independent_validation=_evidence([_target()]))
        assert ha.exit_code_for(ready) == 10

    def test_script_assesses_the_empty_registry_without_error(self, monkeypatch):
        from scripts import hill_autopilot as ha

        monkeypatch.setattr(ha, "offense_training_lineage", lambda: (TRAINING, {}))
        champ = type("C", (), {"params": {"HILL_PERCENTILE_C": 0.11, "HILL_PERCENTILE_S": 1.11}})
        winner = _board_passing_kwargs()["candidates"][1]
        evidence, error = ha.independent_validation_evidence(champ, winner)
        assert error is None
        assert evidence.registry_size == 0
        assert evidence.reason == REASON_NO_TARGET
        assert evidence.to_dict()["gatesPromotion"] is True

    def test_script_assessment_failure_fails_closed(self, monkeypatch):
        from scripts import hill_autopilot as ha

        def boom():
            raise RuntimeError("manifest unavailable")

        monkeypatch.setattr(ha, "offense_training_lineage", boom)
        champ = type("C", (), {"params": {"HILL_PERCENTILE_C": 0.11, "HILL_PERCENTILE_S": 1.11}})
        evidence, error = ha.independent_validation_evidence(
            champ, _board_passing_kwargs()["candidates"][1], targets=[_target()]
        )
        assert evidence is None and "manifest unavailable" in error
        d = decide(**_board_passing_kwargs(), independent_validation=evidence)
        assert d.reason == REASON_NO_TARGET

    def test_workflow_skips_state_change_steps_unless_ready(self):
        wf = WORKFLOW.read_text(encoding="utf-8")
        # exit 0 (HOLD / AUTO_PROMOTION_BLOCKED) -> ready=false, not a failure.
        assert 'elif [[ "$CODE" == "0" ]]; then\n            echo "ready=false"' in wf
        steps = wf.split("\n      - name: ")
        gated = {
            "Verify the tournament winner reproduces from its own pins",
            "Register scope-safe candidate",
            "Downstream board-impact gate",
            "Promote and apply canonical OFFENSE curve",
            "Trigger deploy after canonical promotion",
        }
        seen = set()
        for step in steps:
            name = step.splitlines()[0].strip()
            if name in gated:
                seen.add(name)
                assert (
                    "steps.autopilot.outputs.ready == 'true'" in step
                    or "steps.promote.outputs.applied == 'true'" in step
                ), name
        assert seen == gated
        # Evidence is still committed when nothing is promoted.
        commit = next(s for s in steps if s.startswith("Commit calibration evidence"))
        assert "ready" not in commit.split("run:")[0]
        assert "git add config/model_registry/" in commit

    def test_job_summary_reports_the_outcome_and_independent_reason(self):
        wf = WORKFLOW.read_text(encoding="utf-8")
        summary = wf.split("- name: Job summary", 1)[1]
        assert ".outcome" in summary
        assert ".independentValidation.reason" in summary


# ── default providers ───────────────────────────────────────────────────────


class TestGitPreregistrationCheck:
    def _head(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()

    def test_committed_file_at_an_ancestor_commit(self):
        assert iv.git_preregistration_committed("CLAUDE.md", self._head())

    def test_file_absent_from_the_commit(self):
        assert not iv.git_preregistration_committed("docs/no/such/prereg.md", self._head())

    def test_unknown_commit(self):
        assert not iv.git_preregistration_committed("CLAUDE.md", "0" * 40)


def test_evidence_dict_never_reports_false_for_an_unrun_rule():
    ev = _evidence([_target()], committed=False)
    assert ev.to_dict()["assessments"][0]["passed"] is None
    assert replace(ev, assessments=()).reason == REASON_NO_TARGET
