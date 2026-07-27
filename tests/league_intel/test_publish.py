"""LI-9 overlay payload.

The properties that matter are the ones a wrong answer would make
invisible: that an unmeasurable league degrades to consensus instead of
to a guess, and that the TE axis stays out so the anchor is not
double-counted.
"""

from __future__ import annotations

import pytest

from src.league_intel.publish import build_league_adjusted_payload


def _row(name, position, value):
    return {"displayName": name, "position": position, "rankDerivedValue": value}


BOARD = [
    _row("Scarce One", "RB", 5000),
    _row("Scarce Two", "RB", 3000),
    _row("Deep One", "K", 2000),
    _row("Tight End", "TE", 4000),
]

# lineupScarcity 0.5 is the axis reference, so DEEP (0.2) trims and
# SCARCE (0.8) lifts, with TE parked exactly at the reference so any
# TE movement can only have come from the TE axis.
SCARCITY = {
    "RB": {"lineupScarcity": 0.8},
    "K": {"lineupScarcity": 0.2},
    "TE": {"lineupScarcity": 0.5},
}


class TestOverlayShape:
    def test_only_moved_rows_are_carried(self):
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert "Tight End" not in p["values"], "a row at the reference did not move"
        assert p["adjustedCount"] == len(p["values"])
        assert p["playerCount"] == len(BOARD)

    def test_scarce_position_is_lifted_and_deep_position_trimmed(self):
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert p["values"]["Scarce One"] > 5000
        assert p["values"]["Deep One"] < 2000

    def test_payload_is_json_safe(self):
        import json

        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        json.loads(json.dumps(p))

    def test_stamps_travel_with_the_values(self):
        p = build_league_adjusted_payload(
            BOARD, SCARCITY, league_key="dynasty_main", config_version=1, data_through="2026-07-27"
        )
        assert p["leagueKey"] == "dynasty_main"
        assert p["configVersion"] == 1
        assert p["dataThrough"] == "2026-07-27"
        assert p["modelVersion"] and p["adjustmentModelVersion"]


class TestDegradesToConsensusNotToAGuess:
    """The failure mode worth testing: no roster snapshot."""

    def test_absent_scarcity_yields_an_empty_overlay(self):
        p = build_league_adjusted_payload(BOARD, None, league_key="dynasty_main")
        assert p["values"] == {}
        assert p["isNoop"] is True
        assert p["adjustedCount"] == 0

    def test_empty_scarcity_is_treated_as_absent(self):
        p = build_league_adjusted_payload(BOARD, {}, league_key="dynasty_main")
        assert p["values"] == {}

    def test_position_missing_from_scarcity_is_left_alone(self):
        p = build_league_adjusted_payload(
            BOARD, {"RB": {"lineupScarcity": 0.8}}, league_key="dynasty_main"
        )
        assert "Deep One" not in p["values"], "K had no measurement; it must not move"

    def test_unpriced_row_never_enters_the_overlay(self):
        p = build_league_adjusted_payload(
            BOARD + [_row("Ghost", "RB", 0)], SCARCITY, league_key="dynasty_main"
        )
        assert "Ghost" not in p["values"]


class TestTePremiumStaysOut:
    """Guards the double-count. See test_te_premium_invariants.py — the
    anchor ktcSfTep IS the TE++ board, so the blend already embeds the
    structural 2-TE premium."""

    def test_te_axis_is_declared_inactive(self):
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert "tePremium" in p["inactiveAxes"]

    def test_te_at_reference_scarcity_is_untouched(self):
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert "Tight End" not in p["values"], (
            "a TE priced at reference scarcity moved — something is applying a "
            "TE premium on top of an anchor that already embeds it"
        )


class TestGuardrailsAreReported:
    def test_monotonicity_is_checked_and_reported(self):
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert p["monotonicityViolations"] == []

    def test_scarcity_used_is_echoed_back(self):
        """A served value must be explainable from the payload alone."""
        p = build_league_adjusted_payload(BOARD, SCARCITY, league_key="dynasty_main")
        assert p["scarcity"]["RB"]["lineupScarcity"] == pytest.approx(0.8)


class TestScarcityComponentObjects:
    def test_dataclass_components_are_accepted(self):
        """Callers pass ScarcityComponents straight from LI-5; the
        payload must normalise them rather than serialise an object."""

        class Comp:
            def to_dict(self):
                return {"lineupScarcity": 0.8}

        p = build_league_adjusted_payload(BOARD, {"RB": Comp()}, league_key="dynasty_main")
        assert p["values"]["Scarce One"] > 5000
        assert p["scarcity"]["RB"] == {"lineupScarcity": 0.8}
