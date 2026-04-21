"""Offense anchor VOR correctness — top-24 RB+WR across both scoring systems.

Pins the no-phantom-demand invariant: when either side's replacement
map omits a position (the engine strips zero-starter-demand positions
upstream), that position must be dropped from the anchor cohort on
that side — never treated as "replacement = 0," which would silently
turn raw points into pure VOR and inflate the anchor.
"""
from __future__ import annotations

from src.idp_calibration.vor import ScoredPlayer, compute_offense_anchor_vor


def _players(*triples: tuple[str, str, float, float]) -> list[ScoredPlayer]:
    """Build a ScoredPlayer list from (player_id, position, pts_mine, pts_test) tuples."""
    return [
        ScoredPlayer(
            player_id=pid,
            name=f"P_{pid}",
            position=pos,
            games=16,
            points_mine=pm,
            points_test=pt,
        )
        for pid, pos, pm, pt in triples
    ]


def test_standard_lineup_both_sides_contribute():
    """Baseline: both leagues have RB+WR demand. Anchor is mean VOR
    of the top-24 combined RB+WR on each side."""
    # 12 RBs and 12 WRs with identical points on both sides; demand
    # present on both. Expected VOR per player = points - replacement.
    cohort = _players(
        *[(f"rb{i}", "RB", 200 - i * 10, 200 - i * 10) for i in range(12)],
        *[(f"wr{i}", "WR", 180 - i * 8, 180 - i * 8) for i in range(12)],
    )
    rep_mine = {"RB": 50.0, "WR": 40.0}
    rep_test = {"RB": 50.0, "WR": 40.0}
    am, at = compute_offense_anchor_vor(cohort, rep_mine, rep_test)
    assert am == at
    assert am > 0


def test_zero_rb_demand_drops_rb_cohort_on_that_side():
    """My league has no RB slots (replacement_mine omits RB). RBs
    must be dropped from the mine-side anchor rather than silently
    contributing their raw points as VOR. Test side still has RB
    demand, so RBs DO contribute there.
    """
    # 12 RBs with inflated raw points + 12 WRs with modest points.
    # Under the old ``.get(pos, 0.0)`` behaviour, RBs would get pure
    # points as VOR on the mine side, dominating the top-24 and
    # inflating ``anchor_mine`` far beyond the honest WR-only anchor.
    cohort = _players(
        *[(f"rb{i}", "RB", 500 - i * 10, 200 - i * 10) for i in range(12)],
        *[(f"wr{i}", "WR", 180 - i * 8, 180 - i * 8) for i in range(12)],
    )
    rep_mine = {"WR": 40.0}  # no RB demand
    rep_test = {"RB": 50.0, "WR": 40.0}
    am, at = compute_offense_anchor_vor(cohort, rep_mine, rep_test)

    # Mine anchor is the mean WR VOR only (12 players).
    expected_wr_vor = [(180 - i * 8) - 40.0 for i in range(12)]
    expected_am = sum(expected_wr_vor) / len(expected_wr_vor)
    assert abs(am - expected_am) < 1e-9, (
        f"anchor_mine should be WR-only mean VOR ({expected_am:.3f}); "
        f"got {am:.3f} — phantom RB demand was not filtered"
    )

    # Test anchor includes both: top-24 of the combined 24-player
    # cohort, so it uses every row.
    rb_vors_test = [(200 - i * 10) - 50.0 for i in range(12)]
    wr_vors_test = [(180 - i * 8) - 40.0 for i in range(12)]
    combined = sorted(rb_vors_test + wr_vors_test, reverse=True)[:24]
    expected_at = sum(combined) / len(combined)
    assert abs(at - expected_at) < 1e-9


def test_both_sides_missing_position_produces_zero_cohort_contribution():
    """If neither league has RB demand, RBs don't contribute anywhere —
    both anchors collapse to the WR-only mean VOR.
    """
    cohort = _players(
        *[(f"rb{i}", "RB", 500, 500) for i in range(12)],
        *[(f"wr{i}", "WR", 180 - i * 8, 180 - i * 8) for i in range(12)],
    )
    rep_mine = {"WR": 40.0}
    rep_test = {"WR": 40.0}
    am, at = compute_offense_anchor_vor(cohort, rep_mine, rep_test)
    expected = sum((180 - i * 8) - 40.0 for i in range(12)) / 12
    assert abs(am - expected) < 1e-9
    assert abs(at - expected) < 1e-9


def test_empty_replacement_maps_produce_zero_anchors():
    """When neither side has ANY offense demand, both anchors are 0
    and the upstream relativity math falls through to identity
    (see ``translation.compute_position_multipliers`` missing-anchor
    branch)."""
    cohort = _players(
        *[(f"rb{i}", "RB", 500, 500) for i in range(12)],
    )
    am, at = compute_offense_anchor_vor(cohort, {}, {})
    assert am == 0.0
    assert at == 0.0
