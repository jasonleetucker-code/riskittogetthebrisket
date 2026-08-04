"""M1: the board publishes more ranks than its inputs can resolve.

Math audit 2026-07-30, finding M1.  This is a TRIPWIRE, not a fix — the
constant is deliberately left where it is, and this test exists so the gap
cannot widen silently or be closed by accident without a decision.

The facts, measured on the live payload:

* ``p = (effective_rank - 1) / (_PERCENTILE_REFERENCE_N - 1)`` is clamped to
  1.0, so every per-source rank at or beyond N produces one identical value.
  Verified by independent recomputation of the Hill form: at N=500, ranks
  500, 600, 800 and 1000 all yield OFFENSE 794.3 / IDP 593.7 / GLOBAL 1697.6.
* ``OVERALL_RANK_LIMIT`` is 800, so the board publishes 300 ranks past the
  point where its own inputs stop resolving. 240 of 740 ranked rows (32%)
  sit in that region; 716 of 6,251 per-source votes (11.5%) land on the
  flattened tail and are mutually indistinguishable.

Why the constant was NOT changed here.  ``scripts/backtest_percentile_reference_n.py``
recommends N=1000, and that recommendation cannot be acted on: it scores
*stability*, which this clamp makes degenerate (a smaller N flattens more of
the board and so has less left to churn), and its snapshots pair an archived
payload with the CURRENT ``CSVs/site_raw/`` tree — measured 2026-07-30, a
2026-07-14 replay had 21 sources voting, 18 of them from today's files. With
no ground truth for dynasty value, moving a constant that reprices every row
on a contaminated stability metric would be exactly the unmeasured change
this audit exists to remove. Both caveats are now printed in that script's
report.
"""

from __future__ import annotations

from src.api.data_contract import OVERALL_RANK_LIMIT, _PERCENTILE_REFERENCE_N
from src.canonical.player_valuation import (
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    percentile_to_value,
)


def _p(rank: int, n: int = _PERCENTILE_REFERENCE_N) -> float:
    """The production percentile map, transcribed (data_contract.py)."""
    if n < 2:
        return 0.0
    return max(0.0, min(1.0, (float(rank) - 1.0) / float(n - 1)))


class TestTheFlatTailIsRealAndMeasured:
    def test_ranks_past_the_reference_are_indistinguishable(self):
        """The defect, stated directly: distinct ranks, one identical vote."""
        beyond = [_PERCENTILE_REFERENCE_N, _PERCENTILE_REFERENCE_N + 100, 800, 1000]
        values = {
            percentile_to_value(_p(r), midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S)
            for r in beyond
        }
        assert len(values) == 1, "the tail is expected to be flat — has the clamp changed?"

    def test_ranks_inside_the_reference_still_resolve(self):
        """Control: the flatness is the clamp, not the curve going flat."""
        inside = [400, 450, 480, _PERCENTILE_REFERENCE_N - 1]
        values = [
            percentile_to_value(_p(r), midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S)
            for r in inside
        ]
        assert len(set(values)) == len(inside)
        assert values == sorted(values, reverse=True)

    def test_hand_computed_tail_value(self):
        """V(1) = 9999 / (1 + (1/0.11)^1.11).

        (1/0.11) = 9.0909...;  9.0909^1.11 = exp(1.11 * ln 9.0909)
                 = exp(1.11 * 2.20727) = exp(2.45007) = 11.5900...
        V = 9999 / 12.5900 = 794.2...  — computed here from the constants
        rather than by calling the production helper twice.
        """
        v = percentile_to_value(1.0, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S)
        assert abs(v - 794.0) < 2.0


class TestTheGapIsPinnedUntilSomebodyDecides:
    def test_the_published_board_still_outruns_its_own_resolution(self):
        """If this fails, the gap was closed — update the audit finding and
        the docs rather than just re-pinning the numbers, because closing it
        reprices every row past rank 500."""
        assert _PERCENTILE_REFERENCE_N == 500
        assert OVERALL_RANK_LIMIT == 800
        assert OVERALL_RANK_LIMIT > _PERCENTILE_REFERENCE_N

    def test_the_gap_must_not_widen(self):
        """A future change that publishes deeper without resolving deeper
        makes this worse.  300 is the gap as measured; it may shrink, never
        grow, without a recorded decision."""
        assert OVERALL_RANK_LIMIT - _PERCENTILE_REFERENCE_N <= 300
