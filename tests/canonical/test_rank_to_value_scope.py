"""One scope-aware rank→value reconstruction, shared by both callers.

2026-07-29 audit.  ``terminal.py`` and ``rank_history.py`` both answer
"what value corresponds to this board rank?" on their fallback paths,
and they answered it DIFFERENTLY: rank_history routed IDP rows to the
IDP Hill constants while terminal ran every row — IDP and picks
included — through the offense curve.

Measured against the live board (740 ranked rows,
``scripts/backtest_legacy_rank_curve.py``), the offense curve on IDP
rows scored RMSE 826 where the IDP curve scored 79.  These tests pin
the single shared implementation and the routing, so the two modules
cannot drift apart again.

They deliberately do NOT pin absolute values against a golden number —
the constants are refit by ``scripts/fit_hill_curve_from_market.py``
and a refit must not break the suite.  They pin the STRUCTURE:
same-curve-for-same-scope, correct routing, monotonicity, and the
boundary behaviours.
"""

from __future__ import annotations

from src.canonical.player_valuation import (
    HILL_MIDPOINT,
    HILL_SLOPE,
    IDP_HILL_MIDPOINT,
    IDP_HILL_SLOPE,
    rank_to_value,
    rank_to_value_for_scope,
)


class TestRouting:
    def test_idp_scope_uses_the_idp_constants(self):
        for rank in (1, 5, 25, 100, 400):
            assert rank_to_value_for_scope(rank, "idp") == int(
                rank_to_value(float(rank), midpoint=IDP_HILL_MIDPOINT, slope=IDP_HILL_SLOPE)
            )

    def test_offense_scope_uses_the_offense_constants(self):
        for rank in (1, 5, 25, 100, 400):
            assert rank_to_value_for_scope(rank, "offense") == int(
                rank_to_value(float(rank), midpoint=HILL_MIDPOINT, slope=HILL_SLOPE)
            )

    def test_unknown_scope_falls_back_to_offense(self):
        """Picks and anything unrecognised take the offense curve."""
        for scope in ("pick", "", "something-else"):
            assert rank_to_value_for_scope(50, scope) == rank_to_value_for_scope(50, "offense")

    def test_scope_matching_is_case_insensitive(self):
        assert rank_to_value_for_scope(50, "IDP") == rank_to_value_for_scope(50, "idp")

    def test_the_two_scopes_actually_differ(self):
        """Guard against a future refit collapsing the two curves into
        one without anyone noticing the routing became pointless."""
        assert rank_to_value_for_scope(100, "idp") != rank_to_value_for_scope(100, "offense")


class TestCurveShape:
    def test_rank_one_is_the_scale_max_in_both_scopes(self):
        assert rank_to_value_for_scope(1, "offense") == 9999
        assert rank_to_value_for_scope(1, "idp") == 9999

    def test_monotonically_non_increasing_in_rank(self):
        for scope in ("offense", "idp"):
            values = [rank_to_value_for_scope(r, scope) for r in range(1, 400, 7)]
            assert values == sorted(values, reverse=True), scope

    def test_stays_inside_the_display_scale(self):
        for scope in ("offense", "idp"):
            for rank in (1, 2, 50, 500, 5000, 100000):
                v = rank_to_value_for_scope(rank, scope)
                assert 1 <= v <= 9999, (scope, rank, v)


class TestBothCallersShareIt:
    def test_rank_history_delegates(self):
        from src.api.rank_history import _value_from_rank

        for scope in ("offense", "idp"):
            for rank in (1, 30, 250):
                assert _value_from_rank(rank, scope) == rank_to_value_for_scope(rank, scope)

    def test_terminal_fallback_is_scope_aware(self):
        """A ranked IDP row with no value must reconstruct off the IDP
        curve, not the offense one.  This is the defect: terminal used
        the offense curve for every row."""
        from src.api.terminal import _row_value

        idp_row = {"displayName": "Some LB", "position": "LB", "canonicalConsensusRank": 100}
        off_row = {"displayName": "Some WR", "position": "WR", "canonicalConsensusRank": 100}

        assert _row_value(idp_row) == float(rank_to_value_for_scope(100, "idp"))
        assert _row_value(off_row) == float(rank_to_value_for_scope(100, "offense"))
        assert _row_value(idp_row) != _row_value(off_row)

    def test_terminal_still_prefers_the_stamped_board_value(self):
        """The fallback must remain a fallback — a row carrying
        ``rankDerivedValue`` uses it verbatim, never the curve."""
        from src.api.terminal import _row_value

        row = {
            "displayName": "Some LB",
            "position": "LB",
            "canonicalConsensusRank": 100,
            "rankDerivedValue": 4242,
        }
        assert _row_value(row) == 4242.0
