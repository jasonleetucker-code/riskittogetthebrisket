"""C4: the TE lift must not collapse distinct source votes onto the ceiling.

Math audit 2026-07-30, finding C4.

``_compute_unified_rankings`` lifts a tight end's per-source contribution onto
the board's TE++ basis, then bounded it with ``min(..., 9999)``.  A hard clamp
is not injective, and the inputs routinely exceed it: a source's contribution
is ``Hill(rank)``, and the OFFENSE Hill master is far steeper at the top than
KTC's real value distribution — KTC ranks Brock Bowers 8th and *values* him
8153, while Hill maps rank 8 to 9076.  Lifting 9076 by the measured 1.2092
floor gives 10975, and the clamp discarded the overflow.

Measured against the live source CSVs, six sources' top-TE votes for Bowers
all became exactly 9999:

    fantasyCalc / pfkDynasty / dynastyDaddySf   rank  8  -> 10975 -> 9999
    idpTradeCalc / dynastyNerdsSfTep            rank  7  -> 10131 -> 9999
    otcffbSf                                    rank 14  -> 10058 -> 9999

Each was then casting an identical vote for a tight end and for the #1 overall
player on its own board.  Offense rows are exempt from the market-corridor
clamp, so nothing downstream contained the result.

The premium itself is NOT the defect — across all 72 tight ends paired on
KTC's base and TE++ boards it reproduces KTC's true ratio to a mean absolute
error of 0.090.  Only the bound was wrong, so only the bound changed:
``_te_lift_under_ceiling`` is the identity below 9900 and a strictly
increasing squash above it.
"""

from __future__ import annotations

import math

from src.api.data_contract import (
    _DISPLAY_SCALE_MAX,
    _TE_LIFT_SOFT_KNEE,
    _te_lift_under_ceiling,
)


class TestIdentityBelowTheKnee:
    """Every number the previous implementation produced below the knee must
    be bit-for-bit unchanged — the fix buys ordering at the ceiling and must
    not pay for it anywhere else."""

    def test_identity_below_and_at_the_knee(self):
        for v in (0.0, 1.0, 500.0, 5000.0, 9000.0, 9899.999, _TE_LIFT_SOFT_KNEE):
            assert _te_lift_under_ceiling(v) == v

    def test_the_knee_is_below_the_ceiling(self):
        assert _TE_LIFT_SOFT_KNEE < _DISPLAY_SCALE_MAX


class TestInjectiveAtTheCeiling:
    """The defect, stated as a test: distinct inputs must stay distinct."""

    # The real uncapped votes measured on the live CSVs.
    BOWERS_VOTES = (10975.0, 10130.8, 10057.8)

    def test_the_six_collapsed_votes_separate_again(self):
        # Under the old ``min(v, 9999)`` all three of these were 9999.0.
        out = [_te_lift_under_ceiling(v) for v in self.BOWERS_VOTES]
        assert len(set(out)) == 3
        # Order is preserved: a source that valued him higher still does.
        assert out[0] > out[1] > out[2]

    # The largest lift the pipeline can produce: the scale ceiling times the
    # uplift curve's FLOOR.  The curve is decreasing in value, so the biggest
    # contributions take the smallest multiplier — the 2.053 ceiling
    # multiplier only ever applies to deep tight ends whose Hill value is
    # small, and 9999 x 2.053 is not reachable.
    MAX_REACHABLE_LIFT = 9999.0 * 1.2092

    def test_strictly_increasing_across_the_reachable_lift_range(self):
        prev = -1.0
        v = 9000.0
        while v <= self.MAX_REACHABLE_LIFT:
            cur = _te_lift_under_ceiling(v)
            assert cur > prev, f"not increasing at {v}"
            prev = cur
            v += 7.5

    def test_never_displaces_the_top_asset_on_its_own_board(self):
        # A lifted tight end may approach the #1 asset's 9999 but must not
        # reach or pass it — KTC's own TE++ board puts Bowers 5th at 9859,
        # not 1st.  Held even for inputs beyond what the pipeline can
        # currently generate, where the exponential underflows.
        for v in (9999.0, 10057.8, 10975.0, self.MAX_REACHABLE_LIFT, 15000.0, 1e9):
            assert _te_lift_under_ceiling(v) < _DISPLAY_SCALE_MAX


class TestShapeIsWhatItClaims:
    def test_continuous_at_the_knee(self):
        left = _te_lift_under_ceiling(_TE_LIFT_SOFT_KNEE)
        right = _te_lift_under_ceiling(_TE_LIFT_SOFT_KNEE + 1e-6)
        assert abs(right - left) < 1e-4

    def test_slope_is_one_at_the_knee(self):
        # C1: the squash must not kink the scale at the join.
        h = 1e-3
        k = _TE_LIFT_SOFT_KNEE
        slope = (_te_lift_under_ceiling(k + h) - _te_lift_under_ceiling(k)) / h
        assert abs(slope - 1.0) < 1e-2

    def test_matches_the_closed_form_independently(self):
        # Recomputed here from the documented formula rather than by calling
        # the implementation, so this checks the code against the spec and
        # not against itself.
        knee = _TE_LIFT_SOFT_KNEE
        ceiling = float(_DISPLAY_SCALE_MAX)
        span = ceiling - knee
        for v in (9950.0, 10057.8, 10130.8, 10975.0):
            expected = ceiling - span * math.exp(-(v - knee) / span)
            assert abs(_te_lift_under_ceiling(v) - expected) < 1e-9

    def test_hand_computed_value(self):
        # knee 9900, ceiling 9999, span 99.
        # v = 10057.8 -> 9999 - 99 * exp(-157.8/99)
        #             = 9999 - 99 * exp(-1.593939...)
        #             = 9999 - 99 * 0.2031477...
        #             = 9999 - 20.1116... = 9978.888...
        assert abs(_te_lift_under_ceiling(10057.8) - 9978.8912) < 0.01
