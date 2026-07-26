"""Tests for the champion-challenger decision."""

from __future__ import annotations

from src.model_registry.promotion import (
    PROMOTION_MARGIN,
    REGRESSION_ALARM,
    decide_promotion,
)


class TestGateHasBothOutcomes:
    """A gate with one possible outcome is not a gate."""

    def test_a_clear_win_promotes(self):
        d = decide_promotion(900.0, 600.0)
        assert d.promote
        assert d.improvement == 300.0

    def test_a_clear_loss_rejects(self):
        d = decide_promotion(600.0, 700.0)
        assert not d.promote
        assert d.improvement == -100.0

    def test_both_outcomes_are_reachable(self):
        outcomes = {decide_promotion(800.0, x).promote for x in (500.0, 799.0, 900.0)}
        assert outcomes == {True, False}


class TestMargin:
    def test_improvement_inside_the_margin_does_not_promote(self):
        d = decide_promotion(800.0, 800.0 - (PROMOTION_MARGIN - 1))
        assert not d.promote
        assert "margin" in d.reason

    def test_improvement_at_the_margin_promotes(self):
        d = decide_promotion(800.0, 800.0 - PROMOTION_MARGIN)
        assert d.promote

    def test_ties_go_to_the_incumbent(self):
        assert not decide_promotion(700.0, 700.0).promote

    def test_a_hair_better_is_not_better(self):
        """The specific failure a bare `<` produces: promoting weekly on
        noise, a random walk that always reports an improvement."""
        assert not decide_promotion(700.0, 699.99).promote

    def test_margin_clears_the_measured_noise_floor(self):
        """The paired-delta sd measured across 30 real snapshots was at
        most 1.51 points. The margin must sit well above it."""
        assert PROMOTION_MARGIN > 1.51 * 10


class TestUnmeasuredIncumbent:
    def test_unmeasured_champion_blocks_promotion(self):
        """MECHANISM TEST. An unmeasured incumbent is unknown, not
        beaten — promoting past it is the autonomous rewrite the
        directive prohibits."""
        d = decide_promotion(None, 1.0)
        assert not d.promote
        assert "unmeasured incumbent is unknown" in d.reason

    def test_even_a_spectacular_challenger_cannot_pass_an_unmeasured_champion(self):
        assert not decide_promotion(None, 0.0).promote


class TestRegressionAlarm:
    def test_large_regression_raises_the_alarm(self):
        d = decide_promotion(500.0, 500.0 + REGRESSION_ALARM + 1)
        assert not d.promote
        assert d.alarm
        assert "investigate" in d.reason

    def test_ordinary_regression_does_not_alarm(self):
        d = decide_promotion(500.0, 550.0)
        assert not d.promote
        assert not d.alarm


class TestPayloadHonesty:
    def test_decision_states_what_a_promotion_means(self):
        blob = decide_promotion(900.0, 600.0).to_dict()
        assert "NOT that it is more accurate" in blob["_semantics"]["warning"]
        assert blob["improvement"] == 300.0
        assert blob["marginRequired"] == PROMOTION_MARGIN

    def test_reason_is_always_populated(self):
        for champ, chal in ((None, 1.0), (500.0, 499.0), (500.0, 400.0), (500.0, 900.0)):
            assert decide_promotion(champ, chal).reason.strip()
