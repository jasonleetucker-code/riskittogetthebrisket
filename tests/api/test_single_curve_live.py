"""Single-curve invariants on the live rankings pipeline.

Pins the structural claim that the live path
(``src/api/data_contract.py::_compute_unified_rankings``) applies
exactly one Hill curve, at most one calibration multiplier, and at
most one volatility adjustment to produce ``rankDerivedValue``.  No
hidden second curve, no accidental double-calibration, no mystery
remap.

The chain, as documented in the audit dated 2026-04-20:

    rankDerivedValueUncalibrated  (snapshot after Hill blend + TEP)
        × (idpCalibrationMultiplier × idpFamilyScale)   (IDP rows only)
        = preVolatilityValue
        × (1 − volatilityCompressionApplied)            (compression z>0)
        OR
        min(preVolatilityValue × (1 + |vol|),           (boost z<0,
            monotonicity_cap, _DISPLAY_SCALE_MAX)       clamped)
        = rankDerivedValue

If a second curve is ever reintroduced (e.g. offense calibration
re-enabled without the right gate, a new post-pass remap added),
the identities below will break and this test will fail loudly.

These tests are invariant-band style (PR #154): they assert the
structural chain holds for today's snapshot, not specific values.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    _DISPLAY_SCALE_MAX,
    _VOLATILITY_COMPRESSION_CEIL,
    _VOLATILITY_COMPRESSION_FLOOR,
    build_api_data_contract,
)


_REPO = Path(__file__).resolve().parents[2]
_IDP_POSITIONS = {"DL", "LB", "DB"}
_OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}


def _load_contract() -> dict[str, Any] | None:
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


_CACHED: dict[str, Any] | None = None


def _get() -> dict[str, Any] | None:
    global _CACHED
    if _CACHED is None:
        _CACHED = _load_contract()
    return _CACHED


def _ranked_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r
        for r in contract.get("playersArray") or []
        if r.get("canonicalConsensusRank") and r.get("assetClass") != "pick"
    ]


class TestOffenseHasNoCalibrationLayer(unittest.TestCase):
    """Live offense rows must NOT carry IDP-calibration fields.

    ``_apply_offense_calibration_post_pass`` is intentionally commented
    out at ``src/api/data_contract.py::_compute_unified_rankings``
    (~line 5021).  Re-enabling it without a new invariant test would
    silently restack a second curve on top of the Hill blend.  This
    test exists to catch that regression.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")

    def test_offense_rows_have_no_offense_calibration_multiplier(self) -> None:
        offending: list[str] = []
        for row in _ranked_rows(self.contract):
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            if "offenseCalibrationMultiplier" in row:
                offending.append(
                    f"{row.get('canonicalName')}: "
                    f"{row['offenseCalibrationMultiplier']}"
                )
        self.assertFalse(
            offending,
            "Offense rows carry offenseCalibrationMultiplier — "
            "_apply_offense_calibration_post_pass was re-enabled without "
            "an accompanying invariant. If intentional, add a test pinning "
            "the offense chain, then delete this assertion. Offenders: "
            f"{offending[:5]}",
        )


class TestPreVolatilityChain(unittest.TestCase):
    """``preVolatilityValue`` must equal the one-time calibration fold.

    For offense rows (no live calibration): preVolatilityValue
    should equal rankDerivedValueUncalibrated exactly.

    For IDP rows: preVolatilityValue should equal
    rankDerivedValueUncalibrated × idpCalibrationMultiplier ×
    idpFamilyScale.  Because ``get_idp_bucket_multiplier`` already
    folds family_scale into the bucket product, the live code
    multiplies by the combined factor EXACTLY ONCE.  If someone
    accidentally multiplies again, this test catches it.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_offense_pre_vol_equals_uncalibrated(self) -> None:
        checked = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            pre_vol = row.get("preVolatilityValue")
            uncal = row.get("rankDerivedValueUncalibrated")
            if pre_vol is None or uncal is None:
                continue
            self.assertEqual(
                int(pre_vol),
                int(uncal),
                f"{row.get('canonicalName')} offense row has "
                f"preVolatilityValue={pre_vol} != "
                f"rankDerivedValueUncalibrated={uncal}. "
                f"Either offense calibration was re-enabled or a new "
                f"mystery multiplier was inserted between Hill blend "
                f"and volatility pass.",
            )
            checked += 1
        self.assertGreater(checked, 50, "expected many offense anchors")

    def test_idp_pre_vol_chain(self) -> None:
        """IDP pre-volatility chain.

        When calibration is ACTIVE (multiplier + family_scale fields
        stamped on the row), preVolatilityValue must equal
        uncalibrated × (bucket × family_scale), applied exactly once.

        When calibration is NEUTRAL (fields absent — the default test
        env, see ``tests/conftest.py``), preVolatilityValue must equal
        uncalibrated exactly, same as offense.

        The deeper invariant — family_scale folded-once under an
        active promoted config — is exercised separately in
        ``tests/idp_calibration/test_family_scale_once_only.py``.
        """
        checked = 0
        calibrated = 0
        neutral = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _IDP_POSITIONS:
                continue
            pre_vol = row.get("preVolatilityValue")
            uncal = row.get("rankDerivedValueUncalibrated")
            if pre_vol is None or uncal is None:
                continue
            bucket = row.get("idpCalibrationMultiplier")
            family = row.get("idpFamilyScale")
            if bucket is not None and family is not None:
                expected = int(round(float(uncal) * float(bucket) * float(family)))
                self.assertLessEqual(
                    abs(int(pre_vol) - expected),
                    2,
                    f"{row.get('canonicalName')} IDP row (calibrated): "
                    f"preVolatilityValue={pre_vol} "
                    f"!= round(uncal={uncal} × bucket={bucket} × "
                    f"family={family}) = {expected}. "
                    f"family_scale may have been double-applied, or a "
                    f"new IDP multiplier was introduced.",
                )
                calibrated += 1
            else:
                self.assertEqual(
                    int(pre_vol),
                    int(uncal),
                    f"{row.get('canonicalName')} IDP row (no "
                    f"calibration): preVolatilityValue={pre_vol} != "
                    f"rankDerivedValueUncalibrated={uncal}. A new IDP "
                    f"post-pass was added between Hill blend and "
                    f"volatility.",
                )
                neutral += 1
            checked += 1
        self.assertGreater(checked, 30, "expected many IDP anchors")


class TestVolatilityChain(unittest.TestCase):
    """``rankDerivedValue`` must equal ``preVolatilityValue`` ± volatility.

    For compression (``volatilityCompressionApplied > 0``):
        rankDerivedValue ≈ preVolatilityValue × (1 − vol)
    (exact to within rounding; compression is not capped, so the
    identity is strict.)

    For boost (``volatilityCompressionApplied < 0``):
        rankDerivedValue ≤ preVolatilityValue × (1 + |vol|) + 1
    AND rankDerivedValue ≤ _DISPLAY_SCALE_MAX
    (the monotonicity cap plus the 9999 ceiling can clamp boosts below
    the natural boosted value).

    For unadjusted (``volatilityCompressionApplied is None``):
        rankDerivedValue == preVolatilityValue exactly.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_compression_matches_identity(self) -> None:
        checked = 0
        for row in self.rows:
            vol = row.get("volatilityCompressionApplied")
            pre_vol = row.get("preVolatilityValue")
            final = row.get("rankDerivedValue")
            if vol is None or pre_vol is None or final is None:
                continue
            if vol <= 0:
                continue  # compression branch only
            expected = int(round(float(pre_vol) * (1.0 - float(vol))))
            self.assertLessEqual(
                abs(int(final) - expected),
                1,
                f"{row.get('canonicalName')} compression chain broken: "
                f"preVol={pre_vol} × (1 − {vol}) = {expected}, "
                f"got rankDerivedValue={final}. A new post-pass may be "
                f"mutating the value after volatility compression.",
            )
            checked += 1
        self.assertGreater(
            checked, 20, "expected many compressed rows in the live board"
        )

    def test_boost_respects_cap_and_ceiling(self) -> None:
        checked = 0
        for row in self.rows:
            vol = row.get("volatilityCompressionApplied")
            pre_vol = row.get("preVolatilityValue")
            final = row.get("rankDerivedValue")
            if vol is None or pre_vol is None or final is None:
                continue
            if vol >= 0:
                continue  # boost branch only
            natural_boost = int(round(float(pre_vol) * (1.0 + abs(float(vol)))))
            # Boost may be capped by monotonicity; final must not
            # EXCEED the natural boost (allowing +1 for rounding).
            self.assertLessEqual(
                int(final),
                natural_boost + 1,
                f"{row.get('canonicalName')} boost exceeded natural "
                f"ceiling: pre={pre_vol}, vol={vol}, "
                f"natural_boost={natural_boost}, final={final}. "
                f"The volatility pass should never produce a value "
                f"above the natural boost.",
            )
            self.assertLessEqual(
                int(final),
                _DISPLAY_SCALE_MAX,
                f"{row.get('canonicalName')} post-boost value {final} "
                f"exceeds display scale {_DISPLAY_SCALE_MAX}",
            )
            checked += 1
        self.assertGreater(checked, 10, "expected many boosted rows")

    def test_unadjusted_rows_pass_through(self) -> None:
        checked = 0
        for row in self.rows:
            vol = row.get("volatilityCompressionApplied")
            pre_vol = row.get("preVolatilityValue")
            final = row.get("rankDerivedValue")
            if vol is not None:
                continue  # only unadjusted rows
            if pre_vol is None or final is None:
                continue
            self.assertEqual(
                int(final),
                int(pre_vol),
                f"{row.get('canonicalName')} has vol=None but "
                f"preVolatilityValue={pre_vol} != rankDerivedValue={final}. "
                f"The volatility pass should be a strict no-op when "
                f"its applied fraction is None.",
            )
            checked += 1

    def test_volatility_fraction_stays_in_bounds(self) -> None:
        """``volatilityCompressionApplied`` must stay within the bounds
        derived from FLOOR/CEIL constants.  A value outside this range
        would indicate the bounds constants drifted or the strength
        clamp broke.
        """
        max_compress = 1.0 - _VOLATILITY_COMPRESSION_FLOOR
        max_boost = _VOLATILITY_COMPRESSION_CEIL - 1.0
        for row in self.rows:
            vol = row.get("volatilityCompressionApplied")
            if vol is None:
                continue
            name = row.get("canonicalName")
            self.assertLessEqual(
                float(vol),
                max_compress + 1e-9,
                f"{name}: compression {vol} exceeds floor-derived "
                f"max {max_compress}",
            )
            self.assertGreaterEqual(
                float(vol),
                -max_boost - 1e-9,
                f"{name}: boost {vol} exceeds ceil-derived "
                f"max {max_boost}",
            )


class TestNoSecondHillCurve(unittest.TestCase):
    """No live row can carry values consistent with a second Hill remap.

    A second Hill application after calibration would collapse the
    dynamic range (two compound S-curves stack into something much
    flatter).  We sanity-check that top-of-board values are spread
    widely enough to be inconsistent with a hidden second curve.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_top_50_value_range_is_wide(self) -> None:
        offense = sorted(
            (
                r
                for r in self.rows
                if str(r.get("position") or "").upper() in _OFFENSE_POSITIONS
            ),
            key=lambda r: int(r["canonicalConsensusRank"]),
        )[:50]
        if len(offense) < 50:
            self.skipTest("fewer than 50 offense rows ranked")
        top = int(offense[0]["rankDerivedValue"])
        bottom = int(offense[-1]["rankDerivedValue"])
        spread = top - bottom
        # Single Hill curve with our constants: rank 1 ≈ 9999,
        # rank 50 ≈ 5000.  A second curve would compress this below
        # ~3000.  2500 is a forgiving floor — a real second-curve
        # regression would drop it far below that.
        self.assertGreater(
            spread,
            2500,
            f"Top-50 offense value spread collapsed to {spread} "
            f"({top}..{bottom}). A second Hill remap may have been "
            f"introduced; investigate calibration / volatility passes.",
        )
