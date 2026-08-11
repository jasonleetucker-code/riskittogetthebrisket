"""Governance defects that let unvalidated scopes reach production.

B1.2. ADR-008 moved the refit from "rewrites production" to "produces a
challenger a human promotes". That closed the loop it was written for.
These are the holes B1/B1.1 found in what remained — each independent of
the still-unresolved model-selection question, and each able to let a
promotion carry something nobody scored.

  A  the scheduled refit does not pin the board snapshot it trains on
  B  the registry fingerprints a SUBSET of the model set's inputs
  D  there is no `appliedAt` — the registry cannot say whether the
     champion it names is the one actually live
  E  the holdout scores OFFENSE; promotion moves all four scopes

Two things deliberately NOT repaired here, with reasons:

  C  `measuredAt` — already emitted by `HoldoutResult.to_dict()` since
     `705cdc03e` (2026-08-05). All three stored versions predate that
     commit, so the nulls are a HISTORICAL gap, not a live defect. What is
     added is a guard: a scored version must carry a measurement time.
     Backfilling the three with invented dates is refused (ADR §45 — do
     not falsify history).
  F  unanimity — ADR-008's Decision clause specifies a MEAN per-source
     RMSE and a 25-point margin derived from a measured noise floor. It
     nowhere makes "every board improves" a condition. The only unanimity
     language is descriptive: v2's promotion note observes it happened,
     and the margin derivation cites "zero sign flips" as evidence the
     PAIRED DELTA is stable — a noise statement, not a gate. Codifying it
     would be inventing policy, so it is reported for owner decision
     instead. This test file asserts the current rule so a future change
     is deliberate.

Every test here works on a TEMPORARY registry. `config/model_registry/`
is production state; the final report confirms it was not written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.model_registry.hill_masters import (
    CONSTANT_NAMES,
    VALIDATED_PARAMS,
    training_input_paths,
)
from src.model_registry.versioning import ModelRegistry, ModelVersion, RegistryError

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "refit-hill-curves.yml"
FIT = REPO / "scripts" / "fit_hill_curve_percentile.py"
PROD_REGISTRY = REPO / "config" / "model_registry" / "hill_scope_masters.json"


def _version(**kw) -> ModelVersion:
    base = dict(
        model_id="test_masters",
        version=1,
        params={n: 0.1 for n in CONSTANT_NAMES},
        fitted_at="2026-08-11T00:00:00+00:00",
        producer="test",
    )
    base.update(kw)
    return ModelVersion(**base)


# ── A — the scheduled refit must pin its snapshot ───────────────────


class TestScheduledRefitPinsItsSnapshot:
    """The fit's snapshot is a MATERIAL input, not a convenience.

    It supplies the position filter and the IDPTradeCalc values behind the
    IDP scope, and every rookie slice. `_latest_snapshot()` falls through to
    **mtime** order when `RISKIT_FIT_SNAPSHOT` is unset, so two runs a day
    apart can train different data with identical code — and the registry
    records neither which file nor its hash.
    """

    def test_the_fitter_honours_an_explicit_pin(self):
        """The mechanism exists; the question is whether the caller uses it."""
        source = FIT.read_text()
        assert 'SNAPSHOT_ENV_VAR = "RISKIT_FIT_SNAPSHOT"' in source

    def test_the_workflow_pins_the_snapshot_before_fitting(self):
        """RED: the scheduled refit sets no pin, so selection is by mtime."""
        wf = WORKFLOW.read_text()
        assert "RISKIT_FIT_SNAPSHOT" in wf, (
            "the weekly refit does not pin its board snapshot, so "
            "`_latest_snapshot()` selects by mtime and the IDP and ROOKIE "
            "scopes train against a board the run neither chose nor recorded"
        )

    def test_the_pin_is_resolved_and_hashed_not_just_exported(self):
        """A pin that is not verified is a suggestion.

        Exporting a path that has since been rewritten by a data refresh
        would still fit the wrong bytes while looking pinned.
        """
        wf = WORKFLOW.read_text()
        assert re.search(r"sha256sum|hashlib|sha256", wf), (
            "the pinned snapshot must be hashed so the challenger record can "
            "state which bytes produced it"
        )

    def test_a_missing_pin_target_is_fatal_rather_than_a_fallback(self):
        """Already true in the fitter — pinned so it stays true."""
        source = FIT.read_text()
        block = source.split("def _latest_snapshot")[1].split("\ndef ")[0]
        assert "raise SystemExit" in block
        assert "Refusing to fall back" in block


# ── B — fingerprint every input, not the OFFENSE ones ───────────────


class TestInputFingerprintCoversTheWholeModelSet:
    """A version records eight constants across four scopes.

    It fingerprints the six OFFENSE training CSVs. GLOBAL's IDPTradeCalc,
    IDP's DraftSharks-IDP and the board snapshot behind the IDP and ROOKIE
    slices are absent, so the provenance answers "what produced
    HILL_PERCENTILE_C" and silently implies it answers for the rest.
    """

    def test_it_covers_the_global_and_idp_fit_sources(self):
        paths = {p.name for p in training_input_paths().values()}
        missing = {"idpTradeCalc.csv", "draftSharksIdp.csv"} - paths
        assert not missing, (
            f"model inputs {sorted(missing)} are not fingerprinted, yet the "
            "recorded params include the GLOBAL and IDP scopes they fit"
        )

    def test_it_covers_the_board_snapshot(self):
        keys = set(training_input_paths())
        assert any("snapshot" in k.lower() or "board" in k.lower() for k in keys), (
            "the board snapshot feeds the IDP slice and every rookie slice; "
            "without it a challenger cannot be reproduced from its own record"
        )

    def test_the_input_set_is_derived_from_the_fitter_not_hand_listed(self):
        """A hand-maintained mirror stops covering the thing it mirrors.

        This is the same failure the B1 pin instrument had and was corrected
        for; the registry still has it.
        """
        import inspect

        import src.model_registry.hill_masters as hm

        src = inspect.getsource(hm.training_input_paths)
        assert "OFFENSE_SOURCES" in src or "fit_hill_curve_percentile" in src, (
            "training_input_paths() must derive from the fitter's own source "
            "declarations, or a source added upstream silently goes unpinned"
        )


# ── D — the registry cannot say what is actually live ───────────────


class TestApplyIsRecorded:
    """ADR-008 split promote from apply so a human performs the second step.

    The registry records the first and has no field for the second, so it
    cannot answer "are the live constants the champion?" — the question the
    split exists to make askable.
    """

    def test_a_version_can_carry_an_applied_timestamp(self):
        v = _version()
        assert hasattr(v, "applied_at"), (
            "ModelVersion has no applied_at; promote and apply are separate "
            "acts and only one of them is recorded"
        )

    def test_applied_at_round_trips_through_the_stored_shape(self):
        v = _version(applied_at="2026-08-11T00:00:00+00:00")
        assert v.to_dict()["appliedAt"] == "2026-08-11T00:00:00+00:00"
        assert ModelVersion.from_dict(v.to_dict()).applied_at == v.applied_at

    def test_an_unknown_historical_apply_time_is_expressible(self, tmp_path):
        """§39 — do not invent a date for state we cannot reconstruct.

        The live champion's exact apply time is not recoverable, so the
        schema must be able to say so rather than force either a null that
        reads as 'never applied' or a fabricated timestamp.
        """
        v = _version(applied_at="UNKNOWN_HISTORICAL_APPLY_TIME")
        assert ModelVersion.from_dict(v.to_dict()).applied_at == ("UNKNOWN_HISTORICAL_APPLY_TIME")


class TestAScoredVersionCarriesItsMeasurementTime:
    """Guard for C. The lifecycle already emits `measuredAt`; this stops a
    future path from recording a criterion without one."""

    def test_holdout_result_emits_measured_at(self):
        from src.model_registry.holdout import HoldoutResult

        r = HoldoutResult(
            criterion=1.0,
            per_source={"A": 1.0},
            per_source_rows={"A": 100},
            skipped={},
            params={"c": 0.1, "s": 1.0},
            holdout_labels=("A",),
            training_labels=("B",),
        )
        assert r.to_dict().get("measuredAt")

    def test_recording_a_criterion_without_a_measurement_time_is_refused(self):
        """Enforced on the WRITE path, so loading historical nulls still works."""
        reg = ModelRegistry("test_masters")
        bad = _version(holdout={"criterion": 100.0, "perSource": {"A": 1.0}})
        with pytest.raises(RegistryError, match="measuredAt"):
            reg.seed_champion(bad)
        with pytest.raises(RegistryError, match="measuredAt"):
            reg.add(_version(version=2, holdout={"criterion": 100.0}))

    def test_a_historical_record_without_a_date_still_loads(self):
        """ADR §45 — annotate history, never make it unreadable.

        The shipped registry's three versions predate `measuredAt`. A guard
        that refused to LOAD them would have destroyed the champion history
        rather than protected it.
        """
        v = _version(holdout={"criterion": 100.0})
        assert ModelVersion.from_dict(v.to_dict()).holdout["criterion"] == 100.0


# ── E — a scope must not ride another scope's validation ────────────


class TestChangedScopesNeedTheirOwnEvidence:
    """The holdout scores ONE scope; promotion moves FOUR.

    `VALIDATED_PARAMS` is literally the two OFFENSE constants. The v1 -> v2
    promotion moved GLOBAL 0.113/0.87 -> 0.112/0.725 and IDP 0.093/0.97 ->
    0.083/1.11 with no out-of-sample evidence for either. That already
    shipped; it is not a hypothetical.
    """

    def test_the_holdout_still_validates_only_offense(self):
        """Not a defect to fix here — the fact the guard must account for."""
        assert VALIDATED_PARAMS == ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")

    def test_scope_validation_states_exist(self):
        from src.model_registry.scope_validation import ScopeValidation

        assert ScopeValidation.UNCHANGED_FROM_CHAMPION
        assert ScopeValidation.VALIDATED_EXTERNAL_HOLDOUT
        assert ScopeValidation.UNVALIDATED_NO_HOLDOUT

    def test_an_unchanged_scope_is_not_treated_as_validated(self):
        from src.model_registry.scope_validation import classify_scopes

        champion = {n: 0.1 for n in CONSTANT_NAMES}
        states = classify_scopes(champion, dict(champion), validated_scopes={"OFFENSE"})
        assert states["GLOBAL"] == "UNCHANGED_FROM_CHAMPION"
        assert states["IDP"] == "UNCHANGED_FROM_CHAMPION"

    def test_a_changed_unscored_scope_is_flagged_unvalidated(self):
        from src.model_registry.scope_validation import classify_scopes

        champion = {n: 0.1 for n in CONSTANT_NAMES}
        challenger = dict(champion)
        challenger["IDP_HILL_PERCENTILE_C"] = 0.2
        states = classify_scopes(champion, challenger, validated_scopes={"OFFENSE"})
        assert states["IDP"] == "UNVALIDATED_NO_HOLDOUT"
        assert states["OFFENSE"] == "UNCHANGED_FROM_CHAMPION"

    def test_promotion_fails_closed_on_an_unvalidated_changed_scope(self, tmp_path):
        """THE GATE. A challenger that moves IDP without IDP evidence must
        not be promotable by the ordinary path."""
        from src.model_registry.scope_validation import assert_promotable

        champion = {n: 0.1 for n in CONSTANT_NAMES}
        challenger = dict(champion)
        challenger["IDP_HILL_PERCENTILE_C"] = 0.2
        with pytest.raises(RegistryError, match="IDP"):
            assert_promotable(champion, challenger, validated_scopes={"OFFENSE"})

    def test_a_changed_validated_scope_passes(self):
        from src.model_registry.scope_validation import assert_promotable

        champion = {n: 0.1 for n in CONSTANT_NAMES}
        challenger = dict(champion)
        challenger["HILL_PERCENTILE_C"] = 0.2
        assert_promotable(champion, challenger, validated_scopes={"OFFENSE"})

    def test_an_override_is_possible_but_must_be_recorded(self):
        """§42 — an explicit owner override may exist; a silent one may not."""
        from src.model_registry.scope_validation import assert_promotable

        champion = {n: 0.1 for n in CONSTANT_NAMES}
        challenger = dict(champion)
        challenger["IDP_HILL_PERCENTILE_C"] = 0.2
        with pytest.raises(RegistryError, match="reason"):
            assert_promotable(
                champion, challenger, validated_scopes={"OFFENSE"}, override_scopes={"IDP"}
            )
        assert_promotable(
            champion,
            challenger,
            validated_scopes={"OFFENSE"},
            override_scopes={"IDP"},
            override_reason="owner accepted IDP risk 2026-08-11",
        )


# ── F — the current rule, asserted so a change is deliberate ────────


class TestTheBindingPromotionRuleIsTheMarginNotUnanimity:
    """ADR-008 specifies a mean criterion and a 25-point margin.

    Unanimity is not in its Decision clause. Asserting the current rule
    means a future switch to unanimity has to change this test and say so,
    rather than arriving as an undocumented tightening.
    """

    def test_the_margin_is_the_gate(self):
        from src.model_registry.promotion import PROMOTION_MARGIN, decide_promotion

        assert PROMOTION_MARGIN == 25.0
        assert not decide_promotion(1000.0, 1000.0 - (PROMOTION_MARGIN - 1)).promote
        assert decide_promotion(1000.0, 1000.0 - (PROMOTION_MARGIN + 1)).promote

    def test_decide_promotion_does_not_consult_per_board_signs(self):
        """It takes two scalars; it structurally cannot see per-board signs."""
        import inspect

        from src.model_registry.promotion import decide_promotion

        sig = inspect.signature(decide_promotion)
        assert "per_source" not in sig.parameters
        assert "unanimous" not in sig.parameters


class TestProductionRegistryIsNotTouchedByTests:
    def test_the_shipped_registry_still_names_v2_champion(self):
        blob = json.loads(PROD_REGISTRY.read_text())
        assert blob["championVersion"] == 2
