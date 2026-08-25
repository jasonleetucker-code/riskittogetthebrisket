"""The per-scope evidence gate is WIRED to ``promote()``, not merely written.

``src/model_registry/scope_validation.py`` exists to stop one scope riding
another scope's evidence into production.  It was fully implemented and
fully unit-tested, and had **no caller outside its own tests**: every
recorded version carried ``scopeValidation: {}``, and
``scripts/model_registry.py`` said so in a comment ("``cmd_promote`` has NO
holdout gate").  So the module could refuse nothing.

These tests assert the WIRING, using the real production registry where the
question is real.  They are deliberately not a second copy of
``test_governance_hardening.py``'s classification tests — that file already
pins what the states mean; this one pins that promotion consults them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.model_registry.versioning import ModelRegistry, ModelVersion, RegistryError

REPO = Path(__file__).resolve().parents[2]
LIVE_REGISTRY = REPO / "config" / "model_registry" / "hill_scope_masters.json"

_HOLDOUT = {
    "criterion": 700.0,
    "measuredAt": "2026-08-20T00:00:00+00:00",
    "perSource": {"a": 1.0, "b": 2.0, "c": 3.0},
}


def _v(n: int, params: dict[str, float], *, status: str = "challenger", holdout=None):
    return ModelVersion(
        model_id="m",
        version=n,
        params=dict(params),
        fitted_at=f"2026-08-{n:02d}T00:00:00+00:00",
        producer="test",
        status=status,
        holdout=holdout,
    )


def _reg(champ_params, chal_params, *, chal_holdout=_HOLDOUT) -> ModelRegistry:
    reg = ModelRegistry("m")
    reg.seed_champion(_v(1, champ_params, status="champion", holdout=_HOLDOUT))
    reg.add(_v(2, chal_params, holdout=chal_holdout))
    return reg


OFFENSE_ONLY = {"HILL_PERCENTILE_C": 0.110, "HILL_PERCENTILE_S": 1.110}


class TestGateIsWired:
    def test_an_offense_only_move_still_promotes(self):
        """The gate must not block the case it was designed to permit.

        OFFENSE is the one scope the held-out criterion actually scores,
        so a challenger that moves only OFFENSE has evidence for
        everything it changed.
        """
        reg = _reg(OFFENSE_ONLY, {"HILL_PERCENTILE_C": 0.101, "HILL_PERCENTILE_S": 1.240})
        reg.promote(2, reason="held-out win")
        assert reg.champion.version == 2
        assert reg.champion.scope_validation["OFFENSE"] == "VALIDATED_EXTERNAL_HOLDOUT"

    def test_an_unscored_routed_scope_is_refused(self):
        """IDP moved and nothing scored it — the promotion must fail closed."""
        reg = _reg(
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.083},
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.038},
        )
        with pytest.raises(RegistryError, match="IDP=UNVALIDATED_NO_HOLDOUT"):
            reg.promote(2, reason="criterion improved")
        # and it must not have half-promoted
        assert reg.champion.version == 1
        assert reg.get(2).status == "challenger"

    def test_offense_without_a_holdout_record_is_not_validated(self):
        """Evidence is derived from the record, never assumed.

        ``qualified`` is False with no recorded out-of-sample score, so
        OFFENSE has nothing scoring it and moving it must be refused —
        the same fail-closed posture, in the one scope that usually has
        evidence.
        """
        reg = _reg(
            OFFENSE_ONLY, {"HILL_PERCENTILE_C": 0.101, "HILL_PERCENTILE_S": 1.24}, chal_holdout=None
        )
        with pytest.raises(RegistryError, match="OFFENSE=UNVALIDATED_NO_HOLDOUT"):
            reg.promote(2, reason="looks better")

    def test_an_unrouted_scope_does_not_block(self):
        """ROOKIE is fit and not routed, so it needs no evidence to move."""
        reg = _reg(
            {**OFFENSE_ONLY, "HILL_ROOKIE_PERCENTILE_C": 0.153},
            {**OFFENSE_ONLY, "HILL_ROOKIE_PERCENTILE_C": 0.022},
        )
        reg.promote(2, reason="rookie refit")
        assert reg.champion.scope_validation["ROOKIE"] == "NOT_ROUTED"

    def test_owner_override_records_a_decision_not_a_measurement(self):
        reg = _reg(
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.083},
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.038},
        )
        with pytest.raises(RegistryError, match="requires a non-empty override_reason"):
            reg.promote(2, reason="x", override_scopes={"IDP"})
        reg.promote(2, reason="x", override_scopes={"IDP"}, override_reason="owner accepts")
        assert reg.champion.scope_validation["IDP"] == "OVERRIDDEN_BY_OWNER"
        assert "VALIDATED" not in reg.champion.scope_validation["IDP"]

    def test_rollback_is_not_gated(self):
        """Reinstating a former champion returns production to a state it
        already ran; demanding fresh evidence would block the documented undo."""
        reg = _reg(
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.083},
            {**OFFENSE_ONLY, "IDP_HILL_PERCENTILE_C": 0.038},
        )
        reg.promote(2, reason="x", override_scopes={"IDP"}, override_reason="owner accepts")
        reg.rollback(reason="prod regression")
        assert reg.champion.version == 1

    def test_the_recorded_states_are_persisted(self):
        reg = _reg(OFFENSE_ONLY, {"HILL_PERCENTILE_C": 0.101, "HILL_PERCENTILE_S": 1.24})
        reg.promote(2, reason="held-out win")
        round_tripped = ModelVersion.from_dict(json.loads(json.dumps(reg.champion.to_dict())))
        assert round_tripped.scope_validation == reg.champion.scope_validation
        assert round_tripped.scope_validation  # not {}


class TestAgainstTheLiveRegistry:
    """The gate's verdict on the real standing challengers.

    Not a hypothetical: `hill_scope_masters` carries champion v2 and two
    open challengers, and every one of them moves a routed scope that
    nothing scored.  If this ever starts passing, either real per-scope
    evidence arrived or the gate was weakened — both are things a reader
    of this file should be forced to notice.
    """

    def _live(self) -> ModelRegistry:
        return ModelRegistry.load("hill_scope_masters")

    @pytest.mark.parametrize("version", [3, 4, 5])
    def test_every_standing_challenger_is_refused(self, version: int):
        reg = self._live()
        assert reg.champion.version == 2, "test assumes v2 is champion"
        with pytest.raises(RegistryError, match="UNVALIDATED_NO_HOLDOUT"):
            reg.promote(version, reason="held-out criterion improved")
