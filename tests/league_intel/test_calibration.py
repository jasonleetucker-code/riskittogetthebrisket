"""LI-7 — paired-board TE-premium calibration, including the scale guard.

The guard is the point of these tests: a rank-encoded source passes the
"controls at unity" check vacuously, so without a cardinal-scale
requirement the measurement silently returns an artifact.
"""

from __future__ import annotations

import pytest

from src.league_intel.calibration import (
    CARDINAL_MIN_DYNAMIC_RANGE,
    measure_paired_te_premium,
)


def row(pos: str, base: float, premium: float, key_a="a", key_b="b"):
    return {"position": pos, "canonicalSiteValues": {key_a: base, key_b: premium}}


def cardinal_board(te_multiplier: float, *, n_ctrl=12, n_te=12, control_shift=1.0):
    """Non-TE rows identical (or shifted), TE rows scaled — on a scale
    with real dynamic range (top asset ~100x the bottom) so the
    cardinal guard passes, as a real value board does."""
    rows = []
    for pos, n in (("QB", n_ctrl), ("RB", n_ctrl), ("WR", n_ctrl)):
        for i in range(n):
            v = 9000.0 * (0.7**i) + 50.0
            rows.append(row(pos, v, v * control_shift))
    for i in range(n_te):
        v = 7000.0 * (0.7**i) + 50.0
        rows.append(row("TE", v, v * te_multiplier))
    return rows


class TestCardinalScaleGuard:
    def test_rank_encoded_pair_is_rejected_not_measured(self):
        """The failure this guard exists for: every ratio ~1.0 because
        the scale is compressed, controls pass vacuously."""
        rows = []
        for pos in ("QB", "RB", "WR", "TE"):
            for i in range(12):
                base = 990000.0 - i * 100
                rows.append(row(pos, base, base + 150))
        result = measure_paired_te_premium(rows, "a", "b")
        assert result.usable is False
        assert "cardinal" in result.reason
        assert result.te_premium is None  # never a fallback number

    def test_cardinal_pair_is_accepted(self):
        result = measure_paired_te_premium(cardinal_board(1.37), "a", "b")
        assert result.usable is True
        assert result.te_premium == pytest.approx(1.37, abs=0.01)

    def test_threshold_is_documented_and_pinned(self):
        assert CARDINAL_MIN_DYNAMIC_RANGE == 3.0


class TestControlDrift:
    def test_confounded_pair_is_rejected(self):
        """Controls off unity => the pair differs on more than TE."""
        rows = cardinal_board(1.37, control_shift=1.08)
        result = measure_paired_te_premium(rows, "a", "b")
        assert result.usable is False
        assert "confounded" in result.reason
        assert result.te_premium is None

    def test_identical_control_rows_are_counted(self):
        result = measure_paired_te_premium(cardinal_board(1.37), "a", "b")
        assert result.identical_control_rows == result.control_rows == 36


class TestNeverGuesses:
    def test_unusable_result_carries_no_premium(self):
        for rows in (
            [],
            cardinal_board(1.37, n_te=2),  # too few TE rows
        ):
            result = measure_paired_te_premium(rows, "a", "b")
            assert result.usable is False
            assert result.te_premium is None

    def test_missing_source_keys_yield_unusable(self):
        result = measure_paired_te_premium(cardinal_board(1.37), "nope", "alsonope")
        assert result.usable is False
        assert result.te_premium is None


class TestDepthGrading:
    def test_depth_bands_are_reported(self):
        result = measure_paired_te_premium(cardinal_board(1.37, n_te=45), "a", "b")
        assert result.depth_bands
        assert "TE1-12" in result.depth_bands

    def test_graded_premium_is_not_flattened(self):
        """A board that pays deeper TEs more must show a rising band
        profile — flattening it to one constant discards the signal."""
        rows = []
        for pos in ("QB", "RB", "WR"):
            for i in range(12):
                v = 9000.0 * (0.7**i) + 50.0
                rows.append(row(pos, v, v))
        for i in range(48):
            v = 7000.0 * (0.93**i) + 50.0
            mult = 1.28 + 0.005 * i  # premium rises with depth
            rows.append(row("TE", v, v * mult))
        result = measure_paired_te_premium(rows, "a", "b")
        assert result.usable is True
        bands = result.depth_bands
        assert bands["TE1-12"] < bands["TE13-24"] < bands["TE25-40"] < bands["TE41+"]


class TestLiveBoard:
    """The real measurement behind ADR-009, run on the committed
    baseline contract so the claim stays reproducible.

    NOTE FOR WHOEVER SEES THIS FAIL: these numbers are read off
    ``audit/baseline/api_data.json``, a committed snapshot (generated
    2026-04-28).  A legitimate baseline refresh CAN change them and
    that is not necessarily a regression — the KTC TE premium measured
    1.3682 on this April snapshot and 1.3196 on the 2026-07-26 scrape,
    a real ~3.6% drift over three months.  What must NOT change is the
    STRUCTURE: controls byte-identical, TE premium well above 1, and a
    depth profile that rises.  Those are asserted separately below and
    a failure there is a genuine problem.
    """

    @staticmethod
    def _rows():
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "audit" / "baseline" / "api_data.json"
        if not path.exists():
            pytest.skip("baseline contract snapshot not present")
        return json.loads(path.read_text())["playersArray"]

    def test_ktc_pair_is_the_one_usable_calibration(self):
        result = measure_paired_te_premium(self._rows(), "ktc", "ktcSfTep")
        assert result.usable is True
        # Controls are not merely near unity — they are byte-identical.
        assert result.identical_control_rows == result.control_rows
        assert result.control_drift == 0.0
        # Structural claim, tolerant of board drift (see class docstring).
        assert 1.25 < result.te_premium < 1.45

    def test_baseline_snapshot_value_is_pinned_for_reproducibility(self):
        """Exact pin on the committed fixture, so the ADR's quoted
        number stays checkable.  Update it WITH the ADR when the
        baseline is refreshed — never silently."""
        result = measure_paired_te_premium(self._rows(), "ktc", "ktcSfTep")
        assert result.te_premium == pytest.approx(1.3682, abs=0.001)

    def test_ktc_premium_rises_with_te_depth(self):
        bands = measure_paired_te_premium(self._rows(), "ktc", "ktcSfTep").depth_bands
        assert bands["TE1-12"] == pytest.approx(1.287, abs=0.01)
        assert bands["TE41+"] == pytest.approx(1.512, abs=0.01)
        assert bands["TE1-12"] < bands["TE41+"]

    def test_fantasypros_pair_is_rejected_as_rank_encoded(self):
        result = measure_paired_te_premium(self._rows(), "fantasyProsSf", "fantasyProsFitzmaurice")
        assert result.usable is False
        assert "cardinal" in result.reason
        assert result.te_premium is None
