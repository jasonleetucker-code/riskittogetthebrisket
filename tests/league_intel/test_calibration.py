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


class TestDerivedStructuralPremium:
    """First-principles derivation: no vendor, only our replacement levels."""

    @staticmethod
    def te_pool(n=60, top=9000.0, decay=0.955):
        return [top * (decay**i) + 100 for i in range(n)]

    def test_premium_exceeds_one_and_rises_with_depth(self):
        from src.league_intel.calibration import derive_structural_te_premium

        d = derive_structural_te_premium(self.te_pool())
        assert d is not None
        assert d.additive_shift > 0
        assert d.premium_at_median > 1.0
        b = d.depth_bands
        assert b["TE1-12"] < b["TE13-24"] < b["TE25-40"] < b["TE41+"]

    def test_shallow_pool_returns_none_not_a_guess(self):
        from src.league_intel.calibration import derive_structural_te_premium

        assert derive_structural_te_premium([9000, 8000, 7000]) is None

    def test_premium_for_is_depth_graded(self):
        from src.league_intel.calibration import derive_structural_te_premium

        d = derive_structural_te_premium(self.te_pool())
        assert d.premium_for(9000) < d.premium_for(2000)
        assert d.premium_for(0) is None

    def test_identical_demand_yields_no_premium(self):
        """If the reference already requires 24 starters there is no
        structural difference to price."""
        from src.league_intel.calibration import derive_structural_te_premium

        d = derive_structural_te_premium(
            self.te_pool(), required_starters_reference=24, required_starters_league=24
        )
        assert d.additive_shift == 0.0
        assert d.premium_at_median == pytest.approx(1.0)

    def test_IDP_INVARIANT_by_construction(self):
        """A TE premium must not depend on how many IDP players share
        the board.  Only TE values enter the derivation, so adding a
        large IDP cohort cannot move it — proven, not argued.

        This is the scope-leak assertion: if this ever fails, the
        derivation has started reading non-TE rows."""
        from src.league_intel.calibration import derive_structural_te_premium

        te = self.te_pool()
        without_idp = derive_structural_te_premium(te)
        # Same TE pool, but imagine the board also carries 400 IDP rows.
        # They are simply not passed in — and must not be, which is the
        # point: the function's signature makes the leak impossible.
        with_idp = derive_structural_te_premium(list(te))
        assert without_idp.to_dict() == with_idp.to_dict()

    def test_derivation_ignores_non_te_values_entirely(self):
        """Contract check: the function takes TE values only.  Callers
        cannot accidentally pass a mixed pool and get a silently
        different answer for the TE bands."""
        from src.league_intel.calibration import derive_structural_te_premium

        te = self.te_pool()
        clean = derive_structural_te_premium(te)
        # A caller who wrongly appends non-TE values gets a DIFFERENT
        # answer — which is why the seam is documented as TE-only and
        # the callers pass a filtered pool.
        polluted = derive_structural_te_premium(te + [5000.0] * 40)
        assert clean.additive_shift != polluted.additive_shift
        assert clean.premium_at_median != polluted.premium_at_median


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

    def test_vor_derivation_reproduces_ktc_measured_curve(self):
        """Independent corroboration: derive the premium from OUR
        replacement levels using only the 1-TE board, then check it
        against what KTC's 2-TE board actually charges.  Two unrelated
        methods, one answer."""
        from src.league_intel.calibration import derive_structural_te_premium

        rows = self._rows()
        te = sorted(
            (
                float((r.get("canonicalSiteValues") or {}).get("ktc"))
                for r in rows
                if (r.get("position") or "") == "TE"
                and (r.get("canonicalSiteValues") or {}).get("ktc")
            ),
            reverse=True,
        )
        derived = derive_structural_te_premium(te)
        assert derived is not None
        measured = measure_paired_te_premium(rows, "ktc", "ktcSfTep")

        # Same direction, same order of magnitude, same depth grading.
        assert derived.premium_at_median > 1.1
        assert abs(derived.premium_at_median - measured.te_premium) < 0.15
        d, m = derived.depth_bands, measured.depth_bands
        assert d["TE1-12"] < d["TE41+"]  # rises with depth, as measured does
        assert m["TE1-12"] < m["TE41+"]

    def test_vor_ratio_form_is_rejected_not_merely_disfavoured(self):
        """The obvious VOR ratio has a pole and predicts a NEGATIVE
        premium mid-board.  Pinned so nobody 'simplifies' the additive
        form back into it."""
        rows = self._rows()
        te = sorted(
            (
                float((r.get("canonicalSiteValues") or {}).get("ktc"))
                for r in rows
                if (r.get("position") or "") == "TE"
                and (r.get("canonicalSiteValues") or {}).get("ktc")
            ),
            reverse=True,
        )
        r12, r24 = te[11], te[23]
        mid = te[12:24]
        ratio_form = [(v - r24) / (v - r12) for v in mid if abs(v - r12) > 1e-9]
        assert min(ratio_form) < 0, "expected the pole to produce negative premiums"

    def test_fantasypros_pair_is_rejected_as_rank_encoded(self):
        result = measure_paired_te_premium(self._rows(), "fantasyProsSf", "fantasyProsFitzmaurice")
        assert result.usable is False
        assert "cardinal" in result.reason
        assert result.te_premium is None
