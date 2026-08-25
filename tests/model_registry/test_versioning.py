"""Tests for model versioning, the champion pointer, and rollback."""

from __future__ import annotations

import json

import pytest

from src.model_registry.versioning import (
    ModelRegistry,
    ModelVersion,
    RegistryError,
    fingerprint_file,
    fingerprint_inputs,
)

PARAMS = {"HILL_PERCENTILE_C": 0.118, "HILL_PERCENTILE_S": 1.17}


def _v(n: int, *, status: str = "challenger", holdout=None, **kw) -> ModelVersion:
    return ModelVersion(
        model_id="m",
        version=n,
        params=dict(PARAMS),
        fitted_at=f"2026-07-{n:02d}T00:00:00+00:00",
        producer="test",
        status=status,
        holdout=holdout,
        **kw,
    )


class TestInvariants:
    def test_two_champions_is_rejected(self):
        with pytest.raises(RegistryError, match="2 champions"):
            ModelRegistry("m", [_v(1, status="champion"), _v(2, status="champion")])

    def test_duplicate_versions_rejected(self):
        with pytest.raises(RegistryError, match="duplicate version"):
            ModelRegistry("m", [_v(1), _v(1)])

    def test_foreign_version_rejected(self):
        other = ModelVersion(model_id="other", version=1, params={}, fitted_at="", producer="x")
        with pytest.raises(RegistryError, match="belongs to"):
            ModelRegistry("m", [other])

    def test_unknown_status_rejected(self):
        with pytest.raises(RegistryError, match="unknown status"):
            _v(1, status="great")

    def test_add_cannot_introduce_a_champion(self):
        """MECHANISM TEST. A refit must not be able to write itself
        straight to champion — promotion has to be its own recorded act."""
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        with pytest.raises(RegistryError, match="cannot introduce a champion"):
            reg.add(_v(2, status="champion"))


class TestPromotion:
    def test_promote_retires_the_incumbent(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.promote(2, reason="beat it")
        assert reg.champion.version == 2
        assert reg.get(1).status == "retired"
        assert reg.get(1).retired_at

    def test_promotion_reason_is_mandatory_and_recorded(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        with pytest.raises(RegistryError, match="non-empty reason"):
            reg.promote(2, reason="   ")
        reg.promote(2, reason="held-out win")
        assert any("held-out win" in n for n in reg.champion.notes)

    def test_rejected_versions_are_kept_not_deleted(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.reject(2, reason="lost")
        assert reg.get(2).status == "rejected"
        assert len(reg.versions) == 2

    def test_champion_cannot_be_rejected(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        with pytest.raises(RegistryError, match="cannot be rejected"):
            reg.reject(1, reason="nope")

    def test_seeding_twice_is_refused(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        with pytest.raises(RegistryError, match="already has a champion"):
            reg.seed_champion(_v(2))


class TestRollback:
    def test_rollback_reinstates_the_previous_champion(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.promote(2, reason="win")
        reg.rollback(reason="regression in prod")
        assert reg.champion.version == 1
        assert reg.get(2).status == "retired"
        assert any("rolled back" in n for n in reg.get(2).notes)

    def test_rollback_picks_the_most_recent_former_champion(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.add(_v(3))
        reg.promote(2, reason="a")
        reg.promote(3, reason="b")
        reg.rollback(reason="undo")
        assert reg.champion.version == 2, "rollback must undo one step, not jump to v1"

    def test_rollback_refuses_a_version_that_was_never_champion(self):
        """MECHANISM TEST. Rolling back to something never live is an
        unvalidated promotion wearing the word 'rollback'."""
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.add(_v(3))
        reg.promote(2, reason="a")
        with pytest.raises(RegistryError, match="never a champion"):
            reg.rollback(to_version=3, reason="sideways")

    def test_rollback_with_no_history_refuses(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        with pytest.raises(RegistryError, match="no former champion"):
            reg.rollback(reason="undo")

    def test_rollback_reason_is_mandatory(self):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        reg.add(_v(2))
        reg.promote(2, reason="a")
        with pytest.raises(RegistryError, match="non-empty reason"):
            reg.rollback(reason="")

    def test_round_trip_returns_to_the_original_params(self):
        """Rollback must restore the exact numbers, not approximately."""
        reg = ModelRegistry("m")
        original = {"HILL_PERCENTILE_C": 0.118, "HILL_PERCENTILE_S": 1.17}
        reg.seed_champion(
            ModelVersion(model_id="m", version=1, params=original, fitted_at="", producer="t")
        )
        reg.add(
            ModelVersion(
                model_id="m",
                version=2,
                params={"HILL_PERCENTILE_C": 0.098, "HILL_PERCENTILE_S": 1.30},
                fitted_at="",
                producer="t",
                # Carries a holdout record because it MOVES the OFFENSE
                # curve, and ``promote()`` runs the per-scope evidence gate
                # (``scope_validation``): a routed scope that changed with
                # nothing scoring it is refused.  This test is about
                # rollback fidelity, so the promotion is scaffolding — the
                # record makes the scaffolding legal rather than exempt.
                holdout={
                    "criterion": 700.0,
                    "measuredAt": "2026-08-20T00:00:00+00:00",
                    "perSource": {"a": 1.0, "b": 2.0, "c": 3.0},
                },
            )
        )
        reg.promote(2, reason="win")
        reg.rollback(reason="undo")
        assert reg.champion.params == original


class TestConfidenceHonesty:
    """The directive's 'do not present low-confidence output as precise'."""

    def test_unevaluated_version_is_unqualified(self):
        v = _v(1)
        assert not v.qualified
        assert v.confidence == "unvalidated"

    def test_holdout_without_a_criterion_does_not_qualify(self):
        """MECHANISM TEST. A holdout block that exists but carries no
        score must not read as validated."""
        v = _v(1, holdout={"perSource": {"A": 1.0}, "criterion": None})
        assert not v.qualified
        assert v.confidence == "unvalidated"

    def test_thin_evidence_reads_provisional_not_measured(self):
        v = _v(1, holdout={"criterion": 500.0, "perSource": {"A": 500.0}})
        assert v.qualified
        assert v.confidence == "provisional"

    def test_broad_evidence_reads_measured(self):
        v = _v(1, holdout={"criterion": 500.0, "perSource": dict.fromkeys("abc", 500.0)})
        assert v.confidence == "measured"

    def test_confidence_is_serialized(self):
        blob = _v(1).to_dict()
        assert blob["confidence"] == "unvalidated"
        assert blob["qualified"] is False


class TestPersistence:
    def test_round_trips_through_disk(self, tmp_path):
        reg = ModelRegistry("m")
        reg.seed_champion(
            _v(
                1,
                holdout={
                    "criterion": 12.5,
                    "perSource": {"A": 12.5},
                    "measuredAt": "2026-08-11T00:00:00Z",
                },
            )
        )
        reg.add(_v(2))
        reg.promote(2, reason="win")
        reg.save(tmp_path)

        loaded = ModelRegistry.load("m", tmp_path)
        assert loaded.champion.version == 2
        assert loaded.get(1).status == "retired"
        assert loaded.get(1).holdout["criterion"] == 12.5

    def test_saved_document_names_the_champion(self, tmp_path):
        reg = ModelRegistry("m")
        reg.seed_champion(_v(1))
        path = reg.save(tmp_path)
        blob = json.loads(path.read_text())
        assert blob["championVersion"] == 1
        assert blob["schemaVersion"] == 1

    def test_missing_registry_raises(self, tmp_path):
        with pytest.raises(RegistryError, match="no registry"):
            ModelRegistry.load("nope", tmp_path)


class TestProvenance:
    def test_fingerprint_changes_with_content(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text("a,b\n1,2\n")
        first = fingerprint_file(p)
        p.write_text("a,b\n1,3\n")
        assert fingerprint_file(p) != first

    def test_missing_inputs_are_stamped_not_dropped(self, tmp_path):
        """MECHANISM TEST. Omitting a missing input would make a fit on
        five sources indistinguishable from one on six."""
        present = tmp_path / "p.csv"
        present.write_text("x\n1\n")
        out = fingerprint_inputs({"P": present, "Gone": tmp_path / "nope.csv"})
        assert out["Gone"] == "missing"
        assert out["P"].startswith("sha256:")
        assert len(out) == 2
