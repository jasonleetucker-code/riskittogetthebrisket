"""The stance taxonomy, and the one rule it exists to enforce.

Owner spec §4.16: *"STASH must not create false consensus with true
conviction BUY calls."*  These tests hold that structurally — not by
checking a number, but by checking there is no shape in which the two can be
added together by accident.
"""

from __future__ import annotations

import pytest

from src.analyst import stance as S


class TestTheOwnerVocabularyIsComplete:
    def test_every_canonical_stance_in_the_spec_exists(self):
        assert {s.value for s in S.Stance} == {
            "STRONG_BUY",
            "BUY",
            "CONDITIONAL_BUY",
            "STASH",
            "HOLD",
            "CONDITIONAL_SELL",
            "SELL",
            "STRONG_SELL",
            "NO_SIGNAL",
        }

    def test_every_extraction_label_in_the_spec_exists(self):
        assert {label.value for label in S.SourceLabel} == {
            "BUY",
            "SELL",
            "HOLD",
            "FADE",
            "BREAKOUT",
            "SLEEPER",
            "STASH",
            "INSUFFICIENT_SIGNAL",
        }

    def test_every_stance_declares_a_class_and_a_direction(self):
        """The properties are declared as data so they cannot drift apart;
        a stance missing from the table would raise at first use, which is
        too late."""
        for stance in S.Stance:
            assert isinstance(S.conviction_class(stance), S.ConvictionClass)
            assert isinstance(S.direction(stance), S.Direction)

    def test_every_source_label_translates(self):
        for label in S.SourceLabel:
            assert isinstance(S.stance_for_label(label), S.Stance)


class TestStashIsNotConviction:
    """The headline rule."""

    def test_stash_is_its_own_conviction_class(self):
        assert S.conviction_class(S.Stance.STASH) is S.ConvictionClass.SPECULATIVE
        assert S.is_speculative(S.Stance.STASH)

    def test_nothing_else_is_speculative(self):
        others = [s for s in S.Stance if s is not S.Stance.STASH]
        assert not [s for s in others if S.is_speculative(s)]

    def test_stashes_do_not_become_buys(self):
        t = S.tally([S.Stance.STASH] * 5)
        assert t.conviction(S.Direction.BUY_SIDE) == 0
        assert t.speculative(S.Direction.BUY_SIDE) == 5

    def test_conviction_and_speculation_are_reported_side_by_side(self):
        t = S.tally([S.Stance.BUY, S.Stance.STRONG_BUY, S.Stance.STASH, S.Stance.STASH])
        assert t.conviction(S.Direction.BUY_SIDE) == 2
        assert t.speculative(S.Direction.BUY_SIDE) == 2
        payload = t.to_dict()
        assert payload["convictionBuy"] == 2
        assert payload["speculativeBuy"] == 2

    def test_there_is_no_combined_bullish_count_to_misread(self):
        """Structural, not stylistic.  A single ``buys`` accessor is exactly
        how the two would get summed, so the API does not offer one — a
        caller has to say which quantity it means."""
        t = S.tally([S.Stance.BUY])
        for forbidden in ("buys", "bullish", "buy_count", "total_buys"):
            assert not hasattr(t, forbidden)

    def test_a_stash_still_counts_as_interest_on_the_buy_side(self):
        """Separated, not discarded — a stash is real information."""
        assert S.direction(S.Stance.STASH) is S.Direction.BUY_SIDE


class TestConditionalStances:
    def test_conditional_stances_are_marked_as_needing_a_trigger(self):
        assert S.requires_condition(S.Stance.CONDITIONAL_BUY)
        assert S.requires_condition(S.Stance.CONDITIONAL_SELL)

    def test_unconditional_stances_are_not(self):
        for stance in (S.Stance.BUY, S.Stance.STASH, S.Stance.HOLD, S.Stance.SELL):
            assert not S.requires_condition(stance)

    def test_conditional_is_counted_apart_from_conviction(self):
        t = S.tally([S.Stance.CONDITIONAL_BUY, S.Stance.BUY])
        assert t.conviction(S.Direction.BUY_SIDE) == 1
        assert t.conditional(S.Direction.BUY_SIDE) == 1


class TestTheDeclaredTranslations:
    def test_a_sleeper_is_a_buy_not_a_stash(self):
        """§4.16: a sleeper is 'an undervalued player with a meaningful
        upside/start case, not merely any deep bench name'.  Demoting it to
        STASH would lose a real start-case call."""
        assert S.stance_for_label(S.SourceLabel.SLEEPER) is S.Stance.BUY

    def test_a_stash_stays_a_stash(self):
        assert S.stance_for_label(S.SourceLabel.STASH) is S.Stance.STASH

    def test_insufficient_signal_is_an_answer_not_an_absence(self):
        assert S.stance_for_label(S.SourceLabel.INSUFFICIENT_SIGNAL) is S.Stance.NO_SIGNAL
        assert S.conviction_class(S.Stance.NO_SIGNAL) is S.ConvictionClass.NONE
        assert S.direction(S.Stance.NO_SIGNAL) is S.Direction.NEITHER

    def test_a_fade_is_bearish_without_conviction_inflation(self):
        stance = S.stance_for_label(S.SourceLabel.FADE)
        assert S.direction(stance) is S.Direction.SELL_SIDE
        assert S.conviction_class(stance) is not S.ConvictionClass.CONVICTION

    def test_no_signal_carries_no_directional_weight_in_a_tally(self):
        t = S.tally([S.Stance.NO_SIGNAL] * 3)
        for side in (S.Direction.BUY_SIDE, S.Direction.SELL_SIDE):
            assert t.conviction(side) == 0
            assert t.speculative(side) == 0
            assert t.conditional(side) == 0


class TestTally:
    def test_an_empty_tally_is_zero_everywhere_not_an_error(self):
        t = S.tally([])
        assert t.conviction(S.Direction.BUY_SIDE) == 0
        assert t.to_dict()["byStance"] == {}

    def test_raw_strings_are_accepted_and_validated(self):
        assert S.tally(["BUY", "STASH"]).conviction(S.Direction.BUY_SIDE) == 1
        with pytest.raises(ValueError):
            S.tally(["ENTHUSIASTIC_MAYBE"])

    def test_class_counts_agree_with_stance_counts(self):
        t = S.tally([S.Stance.BUY, S.Stance.STASH, S.Stance.HOLD, S.Stance.SELL])
        assert sum(t.by_class.values()) == sum(t.by_stance.values()) == 4
