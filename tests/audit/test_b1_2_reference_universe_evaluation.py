"""The reference-universe experiment must not compare units to units.

B1.2 RED→GREEN. `b1_1_model_set_measure.s18_reference_universe` refits each
scope under N=400/500/800 and scores the OFFENSE candidate on the held-out
boards. It fitted each candidate in its own coordinate and then handed the
resulting `c` straight to `evaluate_offense_master`, which builds its
percentiles at the canonical N=500. A `c` expressed in N=800 units was
therefore scored as an N=500 `c` — the same class of coordinate mismatch
B1 was created to repair, reintroduced one layer up.

Measured consequence before the repair:

    N=400  c=0.0960  criterion 927.77
    N=500  c=0.0770  criterion 671.21
    N=800  c=0.0480  criterion 502.12

read as "a deeper reference universe fits better". But
`M = c · (N − 1)` is 38.30 / 38.42 / 38.35 — one curve in three units. The
criterion spread was measuring the units, not the model.

`tests/canonical/test_coordinate_equivalence.py` pins the mathematics.
This file pins the HARNESS: a candidate fitted under one universe must be
transformed into the scoring coordinate before it is scored, so
coordinate-equivalent candidates come back with equivalent criteria.

Deliberately tests the SCORING path rather than re-running the experiment.
Refitting three universes is minutes of grid search, and CI's hard gate
runs everything not marked ``livedata``; the mismatch lives in how a
candidate reaches the evaluator, and that is reachable in milliseconds.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEASURE = ROOT / "docs/master-site-audit/evidence/W30/b1_1_model_set_measure.py"

#: One OFFENSE curve, expressed in the three universes B1.1 compared.
#: These are the constants the B1.1 refit actually produced.
EQUIVALENT_OFFENSE_FITS = ((0.0960, 400), (0.0770, 500), (0.0480, 800))
OFFENSE_SLOPE = 1.110


@pytest.fixture(scope="module")
def measure():
    if not MEASURE.exists():
        pytest.skip("B1.1 measurement harness not present")
    spec = importlib.util.spec_from_file_location("b1_1_measure_under_test", MEASURE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheHarnessTreatsCoordinatesAsUnits:
    def test_it_reports_the_rank_space_midpoint(self, measure):
        """`M = c·(N−1)` is the parameterization-independent quantity.

        Without it on every candidate, two rows of a comparison table can
        differ in `c` by 2x and be the same curve — which is exactly how the
        original reading went wrong.
        """
        assert hasattr(measure, "rank_space_midpoint")
        assert measure.rank_space_midpoint(0.0480, 800) == pytest.approx(38.352, abs=0.01)
        assert measure.rank_space_midpoint(0.0770, 500) == pytest.approx(38.423, abs=0.01)

    def test_it_can_transform_between_universes(self, measure):
        assert hasattr(measure, "transform_c")
        assert measure.transform_c(0.0480, from_n=800, to_n=500) == pytest.approx(
            0.0770, abs=0.0005
        )
        # Round trip, because a transform that is not an involution would
        # quietly bias every comparison that uses it twice.
        there = measure.transform_c(0.1100, from_n=500, to_n=800)
        assert measure.transform_c(there, from_n=800, to_n=500) == pytest.approx(0.1100)


class TestScoringIsCoordinateAware:
    """THE RED ASSERTIONS. Fast: holdout scoring only, no refitting."""

    def test_a_candidate_carries_the_universe_it_was_fit_under(self, measure):
        assert hasattr(measure, "score_candidate"), (
            "scoring must take the candidate's own reference_n; a scorer that "
            "accepts only (c, s) cannot tell an N=800 c from an N=500 c, which "
            "is the defect this file exists to prevent"
        )

    def test_equivalent_candidates_score_equivalently(self, measure):
        """Before the repair: 927.77 / 671.21 / 502.12 on one curve."""
        criteria = {
            n: measure.score_candidate(c, OFFENSE_SLOPE, reference_n=n)["criterion"]
            for c, n in EQUIVALENT_OFFENSE_FITS
        }
        lo, hi = min(criteria.values()), max(criteria.values())
        assert (hi - lo) / lo < 0.05, (
            f"coordinate-equivalent candidates scored {criteria} — a "
            f"{100 * (hi - lo) / lo:.0f}% spread means the evaluation is "
            "measuring the coordinate, not the model"
        )

    def test_per_board_scores_agree_too_not_just_the_aggregate(self, measure):
        """An aggregate can agree while the boards underneath do not."""
        by_board: dict[str, list[float]] = {}
        for c, n in EQUIVALENT_OFFENSE_FITS:
            for board, rmse in measure.score_candidate(c, OFFENSE_SLOPE, reference_n=n)[
                "perBoard"
            ].items():
                by_board.setdefault(board, []).append(rmse)
        for board, scores in by_board.items():
            lo, hi = min(scores), max(scores)
            assert (hi - lo) / lo < 0.05, f"{board} scored {scores} across equivalent candidates"

    def test_the_scoring_coordinate_is_stamped(self, measure):
        """Provenance, so a reader cannot repeat the misreading.

        Reporting only the fitted `c` invites comparing 0.0480 with 0.0770
        as rival proposals for the same knob.
        """
        result = measure.score_candidate(0.0480, OFFENSE_SLOPE, reference_n=800)
        assert result["scoringReferenceN"] == measure.PERCENTILE_REFERENCE_N
        assert result["cAsFit"] == pytest.approx(0.0480)
        assert result["cInScoringCoordinate"] == pytest.approx(0.0770, abs=0.0005)
        assert result["rankSpaceMidpoint"] == pytest.approx(38.352, abs=0.01)

    def test_a_genuinely_different_curve_still_scores_differently(self, measure):
        """MECHANISM TEST — the repair must not flatten every difference.

        The champion is a real rank-space difference from the challenger
        (M 54.89 vs 38.42) and must remain separable after transformation.
        """
        champion = measure.score_candidate(0.1100, OFFENSE_SLOPE, reference_n=500)["criterion"]
        challenger = measure.score_candidate(0.0770, OFFENSE_SLOPE, reference_n=500)["criterion"]
        assert champion > challenger * 1.2, (
            "champion and challenger are different curves and must not be "
            f"collapsed by the transform ({champion} vs {challenger})"
        )
