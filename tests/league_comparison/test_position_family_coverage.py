"""Every IDP position nflverse actually emits must resolve to a family.

``scoring_engine._canonical_position`` collapses fine-grained nflverse
positions into DL / LB / DB. A position it does not recognise is dropped
from every scoring comparison, and the only trace is one
``unknown_positions_dropped`` log line that also lists genuinely
untracked positions (K, P, OL, C, G...) — so a real gap looks exactly
like the intended behaviour.

``SAF`` sat in that gap. It is nflverse's spelling for a safety and
covers **1,468 of the 18,539 persisted 2025 regular-season rows**, the
third-largest defensive group after LB and CB. It was in neither
``POSITION_ALIASES`` nor the local collapse table, so every safety was
silently excluded from the IDP scoring-fit measurement — which shrank
the DB cohort from 288 to 188 and moved DB's measured multiplier from
1.0366 to 1.0594.

These tests pin the vocabulary against what the feed actually contains,
rather than against a list someone remembered to update.
"""

from __future__ import annotations

import pytest

from src.league_comparison.scoring_engine import _canonical_position

#: Every defensive position observed on the live 2025 nflverse weekly
#: feed, with the family it must collapse to. Counts are the measured
#: regular-season row counts, kept so a future reader can tell a
#: high-volume gap from a rounding error.
OBSERVED_IDP_POSITIONS = {
    "LB": ("LB", 2819),
    "CB": ("DB", 1926),
    "DT": ("DL", 1517),
    "SAF": ("DB", 1468),  # the one that was missing
    "DE": ("DL", 1440),
    "DB": ("DB", 386),
    "OLB": ("LB", 224),
    "FS": ("DB", 140),
}


@pytest.mark.parametrize(
    "raw,expected", sorted((k, v[0]) for k, v in OBSERVED_IDP_POSITIONS.items())
)
def test_every_observed_idp_position_resolves(raw, expected):
    assert _canonical_position(raw) == expected, (
        f"{raw!r} does not collapse to {expected}. nflverse emits it on the live "
        "feed, so an unmapped value silently drops those players from every "
        "scoring comparison."
    )


def test_safety_spellings_all_land_on_db():
    """The specific gap, and its neighbours.

    ``S``, ``FS`` and ``SS`` were already mapped; ``SAF`` was not, which
    is why the hole was invisible — safeties *appeared* to be handled.
    """
    for spelling in ("S", "SS", "FS", "SAF"):
        assert _canonical_position(spelling) == "DB", spelling


def test_the_mapper_still_refuses_genuinely_untracked_positions():
    """Non-vacuity, and the reason this cannot be fixed by mapping
    everything to something.

    Offensive line, kickers and punters have no IDP or skill scoring in
    this model. If they started resolving, they would enter cohorts they
    do not belong in and quietly move every measured ratio.
    """
    for raw in ("K", "P", "LS", "OL", "OT", "C", "G", "FB"):
        assert _canonical_position(raw) is None, f"{raw!r} should not be tracked"


def test_offensive_positions_are_untouched_by_the_idp_collapse():
    for raw, expected in (("QB", "QB"), ("RB", "RB"), ("WR", "WR"), ("TE", "TE")):
        assert _canonical_position(raw) == expected


def test_blank_and_garbage_return_none_rather_than_guessing():
    for raw in (None, "", "   ", "NOT_A_POSITION"):
        assert _canonical_position(raw) is None
