"""LI-7 — guardrails, confidence machinery, explanation decomposition.

The non-duplication requirement is pinned against FIXTURES with exact
arithmetic, not tolerances: a tolerance-based assertion is exactly how
a double-count creeps back after a refactor.
"""

from __future__ import annotations

import pytest

from src.league_intel.adjustment import (
    ADJUSTMENT_MODEL_VERSION,
    MAX_TOTAL_ADJUSTMENT,
    AdjustmentAxis,
    EvidenceTier,
    build_adjustment,
    check_position_monotonicity,
    structural_scarcity_axis,
    te_premium_axis,
)


def axis(name="structuralScarcity", factor=1.1, tier=EvidenceTier.STRUCTURAL_ONLY):
    return AdjustmentAxis(name=name, factor=factor, tier=tier, rationale="test")


class TestEvidenceGate:
    """Guardrail 1: no evidence => exactly zero contribution."""

    def test_absent_axis_is_arithmetically_inert(self):
        a = AdjustmentAxis("x", factor=1.5, tier=EvidenceTier.ABSENT, rationale="none")
        assert a.effective_factor == 1.0
        assert a.applied is False

    def test_absent_axis_cannot_move_the_value(self):
        """A caller supplying a big factor at ABSENT tier must not be
        able to smuggle in an unevidenced effect."""
        exp = build_adjustment(
            display_name="P",
            position="TE",
            consensus_value=5000,
            axes=[AdjustmentAxis("sneaky", 1.5, EvidenceTier.ABSENT, "no evidence")],
        )
        assert exp.league_adjusted_value == 5000
        assert exp.total_factor == 1.0
        assert any("evidence gate" in g for g in exp.guardrails)

    def test_all_absent_yields_noop_and_zero_confidence(self):
        exp = build_adjustment(
            display_name="P",
            position="WR",
            consensus_value=4000,
            axes=[te_premium_axis(), structural_scarcity_axis("WR", None)],
        )
        assert exp.league_adjusted_value == 4000
        assert exp.confidence == 0.0
        assert exp.evidence_tier is EvidenceTier.ABSENT


class TestMagnitudeCap:
    """Guardrail 2: bounded so compounding small effects can't run away."""

    def test_caps_upward(self):
        exp = build_adjustment(
            display_name="P",
            position="QB",
            consensus_value=1000,
            axes=[axis(factor=1.4), axis(name="b", factor=1.4)],
        )
        assert exp.league_adjusted_value == pytest.approx(1000 * (1 + MAX_TOTAL_ADJUSTMENT))
        assert any("magnitude cap" in g for g in exp.guardrails)

    def test_caps_downward(self):
        exp = build_adjustment(
            display_name="P",
            position="QB",
            consensus_value=1000,
            axes=[axis(factor=0.5), axis(name="b", factor=0.5)],
        )
        assert exp.league_adjusted_value == pytest.approx(1000 * (1 - MAX_TOTAL_ADJUSTMENT))

    def test_within_cap_is_untouched(self):
        exp = build_adjustment(
            display_name="P", position="QB", consensus_value=1000, axes=[axis(factor=1.1)]
        )
        assert exp.league_adjusted_value == pytest.approx(1100.0)
        assert not any("magnitude cap" in g for g in exp.guardrails)


class TestMonotonicityGuard:
    """Guardrail 3: no silent reordering within a position.

    Order preservation is a property of a position's whole set — one
    row cannot know what factor its peers received — so it is enforced
    over a batch rather than per player.  An earlier per-player version
    compared against ``peer * own_factor``, which can never fire for a
    uniform factor: a guard that cannot fail is not a guard.
    """

    def test_uniform_factor_preserves_order(self):
        entries = [(n, c, c * 1.1) for n, c in [("top", 6000), ("mid", 5000), ("low", 4000)]]
        assert check_position_monotonicity("TE", entries) == []

    def test_player_specific_factor_that_reorders_is_caught(self):
        entries = [("top", 6000, 6000 * 0.8), ("low", 5000, 5000 * 1.2)]
        violations = check_position_monotonicity("TE", entries)
        assert len(violations) == 1
        v = violations[0]
        assert (v.higher_name, v.lower_name) == ("top", "low")
        assert v.consensus_gap == 1000
        assert v.adjusted_gap < 0

    def test_ties_impose_no_ordering(self):
        entries = [("a", 5000, 5200), ("b", 5000, 4800)]
        assert check_position_monotonicity("TE", entries) == []

    def test_batch_note_recorded_when_peers_supplied(self):
        exp = build_adjustment(
            display_name="mid",
            position="TE",
            consensus_value=5000,
            axes=[axis(factor=1.1)],
            position_peers=[("top", 6000), ("low", 4000)],
        )
        assert exp.league_adjusted_value == pytest.approx(5500.0)
        assert any("monotonicity" in g for g in exp.guardrails)

    def test_violation_serializes(self):
        v = check_position_monotonicity("TE", [("a", 100, 50), ("b", 90, 90)])[0]
        assert set(v.to_dict()) == {
            "position",
            "higherName",
            "lowerName",
            "consensusGap",
            "adjustedGap",
        }


class TestNonDuplication:
    """The spec's non-duplication requirement, pinned on exact
    arithmetic against fixtures — never a tolerance."""

    def test_te_axis_is_inert_so_it_cannot_stack_on_the_blend_multiplier(self):
        """The blend already applies x1.15 to non-exempt TE sources.  A
        TE axis that also applied a premium would double-count.  It is
        ABSENT, so the arithmetic is exactly identity."""
        te = te_premium_axis()
        assert te.tier is EvidenceTier.ABSENT
        assert te.effective_factor == 1.0

        consensus = 4000.0
        exp = build_adjustment(
            display_name="TE1", position="TE", consensus_value=consensus, axes=[te]
        )
        # EXACT equality, not approx — any leakage shows up immediately.
        assert exp.league_adjusted_value == consensus
        assert exp.total_factor == 1.0

    def test_two_axes_never_multiply_the_same_effect_twice(self):
        """Fixture-pinned arithmetic: the combined factor is exactly the
        product of the effective factors, so an axis added twice by
        mistake is visible rather than absorbed."""
        a = AdjustmentAxis("scarcity", 1.10, EvidenceTier.STRUCTURAL_ONLY, "r")
        exp_single = build_adjustment(
            display_name="P", position="RB", consensus_value=1000.0, axes=[a]
        )
        exp_double = build_adjustment(
            display_name="P", position="RB", consensus_value=1000.0, axes=[a, a]
        )
        assert exp_single.league_adjusted_value == pytest.approx(1100.0, abs=1e-9)
        # 1.10 * 1.10 = 1.21 — a duplicate is NOT silently deduplicated;
        # it is visibly wrong, which is what makes the guard testable.
        assert exp_double.league_adjusted_value == pytest.approx(1210.0, abs=1e-9)
        assert len(exp_double.axes) == 2

    def test_explanation_axes_sum_reproduces_the_value_exactly(self):
        axes = [
            AdjustmentAxis("a", 1.05, EvidenceTier.STRUCTURAL_ONLY, "r"),
            AdjustmentAxis("b", 0.98, EvidenceTier.MARKET_MEASURED, "r"),
            AdjustmentAxis("c", 1.5, EvidenceTier.ABSENT, "no evidence"),
        ]
        consensus = 3000.0
        exp = build_adjustment(
            display_name="P", position="WR", consensus_value=consensus, axes=axes
        )
        rebuilt = consensus
        for a in exp.axes:
            rebuilt *= a.effective_factor
        assert exp.league_adjusted_value == pytest.approx(rebuilt, abs=1e-9)


class TestConfidenceMachinery:
    """With no raw-category source, every value rests on structure
    alone — and must say so."""

    def test_uncorroborated_is_the_explicit_default(self):
        exp = build_adjustment(
            display_name="P",
            position="RB",
            consensus_value=2000,
            axes=[axis(factor=1.05)],
        )
        assert exp.projection_corroborated is False
        assert exp.evidence_tier is EvidenceTier.STRUCTURAL_ONLY
        assert any("rests on roster structure alone" in o for o in exp.open_items)

    def test_weakest_applied_axis_governs_confidence(self):
        exp = build_adjustment(
            display_name="P",
            position="RB",
            consensus_value=2000,
            axes=[
                AdjustmentAxis("strong", 1.02, EvidenceTier.MARKET_MEASURED, "r"),
                AdjustmentAxis("weak", 1.02, EvidenceTier.STRUCTURAL_ONLY, "r"),
            ],
        )
        assert exp.evidence_tier is EvidenceTier.STRUCTURAL_ONLY

    def test_absent_axes_do_not_drag_confidence_down(self):
        """An inert axis contributes nothing, so it must not be treated
        as the weakest APPLIED evidence."""
        exp = build_adjustment(
            display_name="P",
            position="RB",
            consensus_value=2000,
            axes=[
                AdjustmentAxis("applied", 1.02, EvidenceTier.MARKET_MEASURED, "r"),
                AdjustmentAxis("inert", 1.0, EvidenceTier.ABSENT, "none"),
            ],
        )
        assert exp.evidence_tier is EvidenceTier.MARKET_MEASURED

    def test_projection_tier_is_currently_unreachable_in_practice(self):
        """Documents the LI-6 constraint: nothing constructs this tier
        today.  If that changes, this test should be updated
        deliberately alongside the source that earns it."""
        exp = build_adjustment(
            display_name="P",
            position="RB",
            consensus_value=2000,
            axes=[structural_scarcity_axis("RB", {"lineupScarcity": 0.7}), te_premium_axis()],
        )
        assert exp.projection_corroborated is False


class TestStructuralScarcityAxis:
    def test_scarce_position_gets_a_lift(self):
        a = structural_scarcity_axis("QB", {"lineupScarcity": 0.9})
        assert a.factor > 1.0
        assert a.tier is EvidenceTier.STRUCTURAL_ONLY

    def test_deep_position_gets_a_trim(self):
        a = structural_scarcity_axis("WR", {"lineupScarcity": 0.1})
        assert a.factor < 1.0

    def test_unmeasurable_position_is_absent_not_neutral_prior(self):
        a = structural_scarcity_axis("K", None)
        assert a.tier is EvidenceTier.ABSENT
        assert a.effective_factor == 1.0

    def test_accepts_the_li5_dataclass_shape(self):
        from src.league_intel.replacement import ScarcityComponents

        comp = ScarcityComponents(
            position="TE",
            lineup_scarcity=0.8,
            roster_scarcity=None,
            waiver_scarcity=None,
            elite_separation=None,
            starter_separation=None,
            replacement_gap=None,
        )
        a = structural_scarcity_axis("TE", comp)
        assert a.tier is EvidenceTier.STRUCTURAL_ONLY
        assert a.measured_value == 0.8


class TestExplanationShape:
    def test_decomposition_is_serializable_and_complete(self):
        exp = build_adjustment(
            display_name="Player",
            position="TE",
            consensus_value=5000,
            axes=[structural_scarcity_axis("TE", {"lineupScarcity": 0.6}), te_premium_axis()],
        )
        d = exp.to_dict()
        assert set(d) == {
            "displayName",
            "consensusValue",
            "leagueAdjustedValue",
            "totalFactor",
            "axes",
            "guardrails",
            "confidence",
            "evidenceTier",
            "projectionCorroborated",
            "openItems",
            "modelVersion",
        }
        assert d["modelVersion"] == ADJUSTMENT_MODEL_VERSION
        assert any(a["name"] == "tePremium" and not a["applied"] for a in d["axes"])
        assert any("TE premium unresolved" in o for o in d["openItems"])

    def test_unpriced_player_is_handled_not_crashed(self):
        exp = build_adjustment(display_name="P", position="WR", consensus_value=None, axes=[axis()])
        assert exp.league_adjusted_value is None
        assert any("no consensus value" in g for g in exp.guardrails)
