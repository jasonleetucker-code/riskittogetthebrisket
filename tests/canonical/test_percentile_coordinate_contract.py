"""Fit, holdout and serving must share one percentile coordinate system.

Audit finding W30-F008 (B1). The fit truncated each source to its top
`FIT_TOP_N` rows and then divided by the length of the TRUNCATED list, so
a training row's percentile depended on how many rows survived
truncation: /399 for OFFENSE and GLOBAL, /369 for the 370-row IDP slice —
against /499 at serve time.

The same ordinal rank therefore occupied three different coordinates
depending on which stage was asking. Because V(p) = 9999/(1+(p/c)^s)
falls in p, and the serve percentile was the smallest of the three, every
scope served ABOVE anything the fit was ever scored against, by a
DIFFERENT amount per scope:

    OFFENSE  +8.0% .. +25.4%    (ranks 25..400)
    GLOBAL   +6.2% .. +14.2%
    IDP     +14.0% .. +33.9%

The per-scope spread is the defect. A uniform inflation would cancel out
of every comparison that matters; a per-scope stretch means IDP and
offense rows on one board are no longer comparable.

These tests drive the REAL production mappings — the fitter's own
`_percentile_pairs`, the holdout's own `_percentile_pairs`, and the
canonical owner that serving consumes — rather than reproducing the
intended formula in test code and calling that protection.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.canonical.player_valuation import (
    PERCENTILE_REFERENCE_N,
    rank_to_percentile,
    training_percentiles,
)
from src.model_registry import holdout as holdout_mod
from src.model_registry.holdout import FIT_TOP_N

ROOT = Path(__file__).resolve().parents[2]
FITTER_PATH = ROOT / "scripts/fit_hill_curve_percentile.py"

# Ranks worth pinning: the anchor, the shoulder, the mid-board, and a row
# past every fit population so truncation behavior is covered.
REPRESENTATIVE_RANKS = (1, 25, 50, 100, 200, 400)


@pytest.fixture(scope="module")
def fitter():
    spec = importlib.util.spec_from_file_location("b1_fitter_contract", FITTER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    return module


def _descending(n: int) -> list[float]:
    """A synthetic source of ``n`` strictly-descending positive values."""
    return [float(10_000 - i) for i in range(n)]


class TestCanonicalOwner:
    """The contract itself, before anyone consumes it."""

    def test_rank_one_is_zero(self):
        assert rank_to_percentile(1) == 0.0

    def test_the_reference_population_bound(self):
        assert rank_to_percentile(PERCENTILE_REFERENCE_N) == pytest.approx(1.0)

    def test_ranks_past_the_universe_no_longer_clamp_at_one(self):
        """Re-decided by W30-F023, not merely updated.

        This asserted ``rank_to_percentile(750) == 1.0`` — i.e. it pinned
        the saturation defect as the contract. It was correct when written:
        the coordinate genuinely stopped at the reference population, and
        the assertion documented that.

        The tail is now owned by ``tail_policy`` and saturates at rank 904
        (the deepest rank any source has been observed to publish), so
        ranks between the reference population and the boundary resolve
        and ``p`` legitimately exceeds 1.0. Re-asserting ``== 1.0`` here
        would re-pin the defect from a second file.

        What survives is the real contract: the coordinate is
        rank-monotonic and stops resolving exactly where the owner says.
        """
        from src.canonical.tail_policy import TAIL_SATURATION_RANK

        past_reference = rank_to_percentile(PERCENTILE_REFERENCE_N + 250)
        assert past_reference > 1.0, "a rank inside the observed domain must still resolve"

        # Past the owner's boundary, and only there, the coordinate stops.
        assert rank_to_percentile(TAIL_SATURATION_RANK + 1) == rank_to_percentile(
            TAIL_SATURATION_RANK + 5000
        )

    def test_the_coordinate_is_monotonic(self):
        ps = [rank_to_percentile(r) for r in range(1, 501)]
        assert ps == sorted(ps)

    def test_training_percentiles_are_rank_indexed(self):
        ps = training_percentiles(10)
        assert ps == [rank_to_percentile(i + 1) for i in range(10)]

    def test_a_short_population_does_not_stretch_to_one(self):
        """The IDP case, stated as a rule.

        A 370-row source against a 500-row universe ends at 0.7395. If it
        ended at 1.0 the model would be asserting its worst observed
        player is the worst player in the universe.
        """
        short = training_percentiles(370)
        assert short[-1] == pytest.approx(369 / 499, abs=1e-12)
        assert short[-1] < 0.75


class TestFitServeParity:
    """The invariant: one ordinal rank, one coordinate, every stage."""

    @pytest.mark.parametrize("rank", REPRESENTATIVE_RANKS)
    def test_the_fitter_agrees_with_the_canonical_coordinate(self, fitter, rank):
        pairs = fitter._percentile_pairs(_descending(PERCENTILE_REFERENCE_N)[:FIT_TOP_N])
        assert len(pairs) >= rank, "fixture too small for this rank"
        assert pairs[rank - 1][0] == pytest.approx(rank_to_percentile(rank), abs=1e-12)

    @pytest.mark.parametrize("rank", REPRESENTATIVE_RANKS)
    def test_the_holdout_agrees_with_the_canonical_coordinate(self, rank):
        pairs = holdout_mod._percentile_pairs(_descending(PERCENTILE_REFERENCE_N))
        assert len(pairs) >= rank
        assert pairs[rank - 1][0] == pytest.approx(rank_to_percentile(rank), abs=1e-12)

    @pytest.mark.parametrize("rank", REPRESENTATIVE_RANKS)
    def test_fit_and_holdout_agree_with_each_other(self, fitter, rank):
        """Holdout scores a curve; it must grade on the training scale."""
        fit_pairs = fitter._percentile_pairs(_descending(PERCENTILE_REFERENCE_N)[:FIT_TOP_N])
        hold_pairs = holdout_mod._percentile_pairs(_descending(PERCENTILE_REFERENCE_N))
        assert fit_pairs[rank - 1][0] == pytest.approx(hold_pairs[rank - 1][0], abs=1e-12)


class TestTruncationDoesNotRedefineTheUniverse:
    """FIT_TOP_N selects observations. It is not a denominator."""

    def test_truncating_does_not_move_a_surviving_rows_coordinate(self, fitter):
        full = _descending(PERCENTILE_REFERENCE_N)
        truncated = fitter._percentile_pairs(full[:FIT_TOP_N])
        untruncated = fitter._percentile_pairs(full)
        overlap = min(len(truncated), len(untruncated))
        for i in range(overlap):
            assert truncated[i][0] == pytest.approx(untruncated[i][0], abs=1e-12), (
                f"row {i} moved when the population was truncated — truncation is "
                "redefining the coordinate universe"
            )

    def test_two_populations_of_different_length_agree_on_shared_ranks(self, fitter):
        """OFFENSE (400 rows) and IDP (370) must not disagree at rank 50."""
        offense = fitter._percentile_pairs(_descending(500)[:FIT_TOP_N])
        idp = fitter._percentile_pairs(_descending(370))
        for rank in (1, 25, 50, 100, 200, 370):
            assert offense[rank - 1][0] == pytest.approx(idp[rank - 1][0], abs=1e-12), (
                f"scopes disagree at rank {rank} — this is the cross-scope "
                "comparability defect W30-F008 describes"
            )

    def test_a_short_source_ends_below_one_in_the_real_fitter(self, fitter):
        pairs = fitter._percentile_pairs(_descending(370))
        assert pairs[-1][0] == pytest.approx(369 / (PERCENTILE_REFERENCE_N - 1), abs=1e-12)
        assert pairs[-1][0] < 1.0, "a 370-row source must not claim the full universe"

    def test_the_holdout_truncates_rows_not_the_universe(self):
        """`holdout` applies FIT_TOP_N internally; same rule applies."""
        long_pairs = holdout_mod._percentile_pairs(_descending(500))
        assert len(long_pairs) == FIT_TOP_N, "holdout still selects FIT_TOP_N observations"
        assert long_pairs[-1][0] == pytest.approx(
            rank_to_percentile(FIT_TOP_N), abs=1e-12
        ), "the last TRAINING row sits at its own rank, not at 1.0"


class TestServingConsumesTheOwner:
    """Serving must not carry its own copy of the reference population."""

    def test_data_contract_reference_matches_the_canonical_one(self):
        from src.api.data_contract import _PERCENTILE_REFERENCE_N

        assert _PERCENTILE_REFERENCE_N == PERCENTILE_REFERENCE_N

    def test_serving_maps_ranks_through_the_canonical_helper(self):
        """A static guard against the formula being re-inlined later."""
        src = (ROOT / "src/api/data_contract.py").read_text()
        assert "rank_to_percentile" in src, (
            "serving should consume the canonical coordinate owner rather than "
            "recomputing (rank - 1) / (denom - 1) inline"
        )

    def test_the_fitter_and_holdout_import_the_owner(self):
        for rel in ("scripts/fit_hill_curve_percentile.py", "src/model_registry/holdout.py"):
            src = (ROOT / rel).read_text()
            assert (
                "training_percentiles" in src or "rank_to_percentile" in src
            ), f"{rel} still builds percentiles locally"
