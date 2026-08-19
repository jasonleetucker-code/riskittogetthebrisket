"""A consensus must be over ONE known scoring basis.

WHAT IS WRONG
-------------
``ProjectionRecord.resolve_fpg`` returns ``(value, scoring_native)``, and
``scoring_native`` is False whenever the value is a points TOTAL the
source published under its own scoring rather than a stat line this
league can score. The manual-CSV adapter — the documented drop-in for
"the moment a real projection feed lands" — sets it ``False``
unconditionally.

``blend_consensus`` then averages every record together regardless, and
stamps ``all_scoring_native`` on the result. **Nothing reads that flag.**
Measured 2026-08-19: it is written in exactly one place and consumed in
none, so a projection denominated in some other provider's scoring lands
in the same ``mu_fpg`` as one scored under this league's card, and no
consumer can tell.

Averaging points from two different scoring systems is a category error,
not an imprecision. The same body of evidence rule that governs signal
independence applies to units: you cannot mean two quantities that are
not the same quantity.

WHY THIS IS NOT HYPOTHETICAL
----------------------------
The repo already contains a real forward-looking projection feed that
would arrive exactly this way. ``CSVs/site_raw/draftSharksSf.csv`` and
``draftSharksIdp.csv`` publish ``1yr. Proj`` — 412 of 439 offensive rows
and 375 of 410 IDP rows populated, with the season-total shape you would
expect (QB max 403, RB1 309, WR1 257, TE1 214). It publishes **totals,
not stat lines**, and **no scoring metadata at all**, so its basis
cannot be verified and its numbers cannot be rescored under this
league's card.

That feed is the reason to fix the consumer before ingesting anything:
the hazard is not the source's fault, it is that the blend cannot
currently refuse.

THE RULE
--------
Non-native records are EXCLUDED from the mean, named in
``excluded_foreign_basis``, and the consensus says so. Excluded rather
than down-weighted, because a weight expresses "less reliable" and this
is "different unit". If every record is non-native there is nothing to
verify against, so the consensus is returned flagged rather than
silently — the owners of the number get to see the state, the same
posture the rest of this lane takes for an unknown quantity.
"""

from __future__ import annotations

from src.bdvm.params import load_param_set
from src.bdvm.projections import ProjectionRecord, blend_consensus

CARD = {"pass_yd": 0.04, "pass_td": 4.0, "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1}
AS_OF = "2026-08-01"


def _rec(source: str, *, fpg: float, native: bool) -> ProjectionRecord:
    return ProjectionRecord(
        source=source,
        player_key="test player",
        position="WR",
        season=2026,
        as_of=AS_OF,
        games=17.0,
        fpg=fpg,
        scoring_native=native,
    )


def _blend(*records):
    return blend_consensus(
        records,
        scoring_settings=CARD,
        snapshot_as_of=AS_OF,
        params=load_param_set(),
    )


def test_a_foreign_basis_record_does_not_enter_the_mean():
    """The whole point: 10.0 league-scored points and 20.0 points in
    somebody else's scoring do not average to 15.0."""
    native_only = _blend(_rec("a", fpg=10.0, native=True))
    mixed = _blend(
        _rec("a", fpg=10.0, native=True),
        _rec("foreign", fpg=20.0, native=False),
    )
    assert native_only is not None and mixed is not None
    assert mixed.mu_fpg == native_only.mu_fpg, (
        f"a record in an unverified scoring basis moved the consensus "
        f"{native_only.mu_fpg} -> {mixed.mu_fpg}; points from two scoring "
        f"systems cannot be averaged"
    )
    assert "foreign" in mixed.excluded_foreign_basis
    assert "foreign" not in mixed.sources


def test_the_exclusion_is_reported_not_silent():
    """A dropped source must be visible. Silently discarding evidence is
    the other way to get a number nobody can account for."""
    mixed = _blend(
        _rec("a", fpg=10.0, native=True),
        _rec("foreign", fpg=20.0, native=False),
    )
    assert mixed.excluded_foreign_basis == ("foreign",)
    assert mixed.n_sources == 1, "n_sources must count what was actually blended"


def test_all_native_is_untouched():
    """NON-VACUITY. A change that excluded everything, or that fired on
    any multi-source blend, would satisfy the tests above."""
    both = _blend(
        _rec("a", fpg=10.0, native=True),
        _rec("b", fpg=20.0, native=True),
    )
    assert both is not None
    assert both.excluded_foreign_basis == ()
    assert both.n_sources == 2
    assert 10.0 < both.mu_fpg < 20.0, both.mu_fpg


def test_all_foreign_is_flagged_rather_than_dropped_to_nothing():
    """If every record is non-native there is nothing to verify against.
    Returning None would report the player as unpriced when a real
    projection exists; blending silently would hide the basis. So it
    blends and declares the state."""
    only_foreign = _blend(
        _rec("x", fpg=10.0, native=False),
        _rec("y", fpg=20.0, native=False),
    )
    assert only_foreign is not None, "an unpriced player is a different claim"
    assert only_foreign.all_scoring_native is False
    assert only_foreign.excluded_foreign_basis == (), (
        "with nothing native to protect, excluding every record would "
        "report unpriced rather than unverified"
    )
    assert 10.0 <= only_foreign.mu_fpg <= 20.0


def test_the_flag_is_no_longer_write_only():
    """The defect was a declared property nothing acted on. This asserts
    it now changes an outcome, which is what stops it regressing to a
    decoration."""
    mixed = _blend(
        _rec("a", fpg=10.0, native=True),
        _rec("foreign", fpg=99.0, native=False),
    )
    assert (
        mixed.all_scoring_native is True
    ), "after excluding the foreign row, everything blended IS native"
    assert mixed.mu_fpg == 10.0
