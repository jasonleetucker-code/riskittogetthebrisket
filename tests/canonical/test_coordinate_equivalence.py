"""Reference N is a UNIT, not a model. Clamping is what makes it a model.

B1.2. B1 unified fit, holdout and serving onto one percentile coordinate
(W30-F008). B1.1 then asked a follow-up question — "is 500 the right
reference universe?" — refit under N=400/500/800, and reported three
different `c` values with three very different holdout criteria, reading
the spread as evidence about which universe fits better.

Independent review found that reading rests on a second coordinate
mistake, of exactly the family B1 repaired. The algebra:

    V(p) = 9999 / (1 + (p/c)^s),   p = (rank − 1) / (N − 1)

    =>  p/c = (rank − 1) / ((N − 1) · c)

so V depends on rank ONLY through

    M = c · (N − 1)        the rank-space midpoint

and `s`. Refitting the same observations under a different N therefore
rescales `c` and leaves the rank→value relationship alone. Two `c` values
under two universes describe the SAME curve when M agrees, and the
transform between them is

    c₂ = c₁ · (N₁ − 1) / (N₂ − 1)

The measured B1.1 fits bear this out exactly — M is constant per scope to
within the fitter's own grid resolution:

    OFFENSE   N=400 c=0.0960 → M 38.30 | N=500 c=0.0770 → M 38.42 | N=800 c=0.0480 → M 38.35
    GLOBAL    N=400 c=0.1120 → M 44.69 | N=500 c=0.0890 → M 44.41 | N=800 c=0.0560 → M 44.74
    IDP       N=400 c=0.0480 → M 19.15 | N=500 c=0.0380 → M 18.96 | N=800 c=0.0240 → M 19.18

`evaluate_offense_master(c, s)` builds its percentiles from
`training_percentiles(n)` at the DEFAULT reference — 500 — so a `c` fitted
under N=800 was scored as though it were an N=500 `c`. That evaluates
M = 0.048 × 499 = 23.95, a genuinely different and much steeper curve,
rather than the M = 38.35 that was actually fitted. The "N=800 scores
502 against the challenger's 671" result is a units error, not a finding.

These tests pin the distinction so it cannot recur:

  * equivalent parameterizations agree in rank space (this file's core
    invariant, and the thing B1.1 assumed without checking);
  * the agreement ends exactly where the smaller universe clamps — which
    is why TAIL POLICY is a real modelling choice while N alone is not.

Everything here drives the production evaluator and the canonical owner.
No constant is read from a fixture; the transform is applied to the real
`percentile_to_value`.
"""

from __future__ import annotations

import pytest

from src.canonical.player_valuation import (
    PERCENTILE_REFERENCE_N,
    percentile_to_value,
    rank_to_percentile,
)

#: (N₁, N₂) pairs worth protecting. 400 is `FIT_TOP_N`, 500 the serving
#: reference, 800 `OVERALL_RANK_LIMIT` — the three universes B1.1 compared.
UNIVERSE_PAIRS = ((400, 500), (500, 800), (400, 800), (500, 1000))

#: Slopes spanning the three live scopes (IDP 0.87, GLOBAL 0.725,
#: OFFENSE 1.11) plus the extremes of the fitter's own grid.
SLOPES = (0.4, 0.725, 0.87, 1.11, 2.5)


def rank_space_midpoint(c: float, reference_n: int) -> float:
    """``M = c · (N − 1)`` — the parameterization-independent midpoint."""
    return float(c) * (int(reference_n) - 1)


def transform_c(c: float, *, from_n: int, to_n: int) -> float:
    """Express ``c`` in another reference universe, preserving the curve."""
    return float(c) * (int(from_n) - 1) / (int(to_n) - 1)


def value_at_rank(rank: float, c: float, s: float, reference_n: int) -> float:
    """Serve one rank through the REAL production mapping and evaluator."""
    p = rank_to_percentile(rank, reference_n=reference_n)
    return float(percentile_to_value(p, midpoint=c, slope=s))


class TestTheTransformIsAnIdentity:
    """c₂ = c₁·(N₁−1)/(N₂−1) is a change of units, nothing more."""

    @pytest.mark.parametrize("n1,n2", UNIVERSE_PAIRS)
    def test_transform_preserves_the_rank_space_midpoint(self, n1, n2):
        c1 = 0.0770
        c2 = transform_c(c1, from_n=n1, to_n=n2)
        assert rank_space_midpoint(c1, n1) == pytest.approx(rank_space_midpoint(c2, n2), rel=1e-12)

    @pytest.mark.parametrize("n1,n2", UNIVERSE_PAIRS)
    @pytest.mark.parametrize("s", SLOPES)
    def test_equivalent_parameters_serve_identical_values(self, n1, n2, s):
        """The invariant B1.1 needed and did not have.

        Only ranks inside BOTH universes' un-clamped support are compared —
        past `min(n1, n2)` the smaller one clamps and the curves genuinely
        diverge, which the next class pins deliberately.
        """
        c1 = 0.0770
        c2 = transform_c(c1, from_n=n1, to_n=n2)
        limit = min(n1, n2)
        for rank in (1, 10, 25, 50, 100, 200, 300, 400, 500, 600, 700, 800):
            if rank > limit:
                continue
            v1 = value_at_rank(rank, c1, s, n1)
            v2 = value_at_rank(rank, c2, s, n2)
            assert v1 == pytest.approx(v2, abs=1.0), (
                f"rank {rank}: N={n1} c={c1:.4f} -> {v1:.1f} but "
                f"N={n2} c={c2:.6f} -> {v2:.1f}; these are the same curve"
            )

    def test_the_b1_1_alt_n_fits_are_one_curve_in_three_units(self):
        """The measured constants, not a synthetic example.

        If a future refit genuinely separates these universes, this fails
        and the separation is real rather than assumed away.
        """
        measured = {
            "OFFENSE": {400: 0.0960, 500: 0.0770, 800: 0.0480},
            "GLOBAL": {400: 0.1120, 500: 0.0890, 800: 0.0560},
            "IDP": {400: 0.0480, 500: 0.0380, 800: 0.0240},
        }
        for scope, by_n in measured.items():
            midpoints = {n: rank_space_midpoint(c, n) for n, c in by_n.items()}
            lo, hi = min(midpoints.values()), max(midpoints.values())
            # 2% covers the fitter's own grid step (c step 0.005, refined
            # +/-0.002); anything wider would be a real model difference.
            assert (hi - lo) / lo < 0.02, (
                f"{scope}: rank-space midpoints {midpoints} disagree by "
                f"{100 * (hi - lo) / lo:.1f}% — these are NOT the same curve"
            )

    def test_the_n800_fit_transforms_onto_the_challenger(self):
        """The specific claim under review, checked as arithmetic."""
        assert transform_c(0.0480, from_n=800, to_n=500) == pytest.approx(0.0770, abs=0.0005)


class TestClampingIsWhatMakesTailPolicySubstantive:
    """Equivalence holds inside shared support and ends at the clamp.

    This is the distinction B1.2 exists to draw. Declaring a larger N is
    not by itself a modelling decision — but it moves where `p` saturates,
    and THAT changes served values. So the real question was never
    "which N", it is "what happens past the reference population".
    """

    def test_ranks_past_the_reference_population_share_one_coordinate(self):
        n = PERCENTILE_REFERENCE_N
        collapsed = {rank_to_percentile(r, reference_n=n) for r in (n, n + 20, 700, 899, 5000)}
        assert collapsed == {1.0}, "the clamp is the mechanism under test"

    def test_equivalence_breaks_exactly_where_the_smaller_universe_clamps(self):
        """Same curve, two universes; they part company past rank 500."""
        c500 = 0.0770
        c800 = transform_c(c500, from_n=500, to_n=800)
        s = 1.110

        # Inside shared support: indistinguishable.
        for rank in (100, 300, 499):
            assert value_at_rank(rank, c500, s, 500) == pytest.approx(
                value_at_rank(rank, c800, s, 800), abs=1.0
            )

        # Past it: the N=500 representation is pinned to its p=1 tail while
        # the N=800 representation keeps resolving deeper ranks.
        tail_500 = {r: value_at_rank(r, c500, s, 500) for r in (500, 600, 700, 800)}
        assert len(set(tail_500.values())) == 1, "N=500 must collapse its tail"

        tail_800 = {r: value_at_rank(r, c800, s, 800) for r in (500, 600, 700, 800)}
        assert len(set(tail_800.values())) == 4, "N=800 must still separate these ranks"
        assert sorted(tail_800.values(), reverse=True) == list(
            tail_800.values()
        ), "deeper rank must not be worth more"

        # And the gap is material, not a rounding artifact.
        assert tail_500[800] - tail_800[800] > 50


class TestTheHoldoutEvaluatorHardCodesTheServingCoordinate:
    """Why the B1.1 experiment produced a units error.

    Not a defect in `evaluate_offense_master` — scoring in the serving
    coordinate is correct for the job it was written for. It is a defect in
    handing it parameters expressed in some OTHER coordinate. Pinned here so
    the constraint is visible at the call site.
    """

    def test_evaluator_percentiles_come_from_the_canonical_reference(self):
        from src.model_registry.holdout import _percentile_pairs

        pairs = _percentile_pairs([float(1000 - i) for i in range(300)])
        ps = [p for p, _ in pairs]
        assert ps[0] == 0.0
        assert ps[-1] == pytest.approx(
            rank_to_percentile(300, reference_n=PERCENTILE_REFERENCE_N)
        ), "the evaluator scores in the N=500 coordinate, whatever N a candidate was fit under"

    def test_passing_a_foreign_coordinate_c_scores_a_different_curve(self):
        """MECHANISM TEST — the actual B1.1 mistake, made explicit.

        Feeding the N=800 `c` straight to the evaluator does not score the
        N=800 fit; it scores a curve whose rank-space midpoint is ~38% of it.
        """
        c800 = 0.0480
        intended = rank_space_midpoint(c800, 800)
        as_evaluated = rank_space_midpoint(c800, PERCENTILE_REFERENCE_N)
        assert as_evaluated < 0.7 * intended, (
            f"intended M={intended:.2f}, evaluated as M={as_evaluated:.2f} — "
            "this gap is the artifact B1.1 reported as a holdout improvement"
        )
