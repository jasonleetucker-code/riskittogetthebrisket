"""Tier-form picks in rounds 5-6 are priceable, and say so.

Audit finding W13-F004: ``_PICK_TIER_RE`` hardcoded
``(1st|2nd|3rd|4th)`` and ``_ROUND_WORD`` had four entries, so in a
6-round rookie draft every ``YYYY {Early|Mid|Late} {5th|6th}`` row fell
through to ``distribution: None`` with the factually wrong reason
``unparseable_pick_name`` — 24 of the live board's 144 pick rows.

The name was never the problem and neither was the outcome model: the
SLOT form of the same asset ("2026 Pick 5.03") parsed fine, and
``pick_values_all_strategies`` returns real EV for exactly those slots.
The round-word map was the limit, and it is the only one in the tree
that did not cover 1-6.
"""

from __future__ import annotations

import pytest

from src.bdvm.params import load_param_set
from src.bdvm.picks import pick_values_all_strategies
from src.bdvm.service import _ROUND_WORD, _parse_pick_slot

TEAMS = 12


@pytest.mark.parametrize(
    "name,expected",
    [
        ("2026 Early 4th", (39, 2026)),
        ("2026 Early 5th", (51, 2026)),
        ("2026 Mid 6th", (66, 2026)),
        ("2029 Late 5th", (58, 2029)),
        # The slot form of the same round-5 asset, which always worked.
        ("2026 Pick 5.03", (51, 2026)),
    ],
)
def test_tier_form_parses_every_round_of_the_draft(name, expected):
    assert _parse_pick_slot(name, TEAMS) == expected


def test_round_word_map_covers_the_whole_draft():
    # Every other round-word map in the tree spans 1-6
    # (frontend/lib/trade-logic.js::ROUND_NUM,
    # src/canonical/normalization_validator).
    assert _ROUND_WORD == {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}


def test_the_model_can_price_the_slots_that_used_to_be_refused():
    params = load_param_set()
    evs = {
        rnd: pick_values_all_strategies((rnd - 1) * TEAMS + 3, params, years_out=0)[
            "balanced"
        ]["ev"]
        for rnd in (4, 5, 6)
    }
    assert evs[4] > evs[5] > evs[6] > 0


def test_a_genuinely_unparseable_name_still_refuses():
    # The reason label must keep meaning what it says.
    assert _parse_pick_slot("Bijan Robinson", TEAMS) is None
    assert _parse_pick_slot("", TEAMS) is None
