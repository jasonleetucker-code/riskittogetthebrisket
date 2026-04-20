"""Single-curve invariants on the live rankings pipeline.

Pins the structural claim that the live path
(``src/api/data_contract.py::_compute_unified_rankings``) applies
exactly one Hill curve + at most one calibration multiplier to
produce ``rankDerivedValue``.  No hidden second curve, no accidental
double-calibration, no mystery remap.

The chain, as of the Final Framework transition PR 1:

    rankDerivedValueUncalibrated  (trimmed mean-median of per-source
                                    Hill values, post-TEP)
        × (idpCalibrationMultiplier × idpFamilyScale)   (IDP rows only)
        = rankDerivedValue

The prior volatility compression + monotonicity-cap post-pass has
been removed outright.  ``preVolatilityValue`` and
``volatilityCompressionApplied`` are no longer stamped.

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
    (around line 5021).  Re-enabling it without a new invariant test
    would silently restack a second curve on top of the Hill blend.
    This test exists to catch that regression.
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


class TestVolatilityPassIsRemoved(unittest.TestCase):
    """No row should carry the stamps the removed volatility pass left.

    If ``_apply_volatility_compression_post_pass`` or an analogous
    second remap is ever re-added without a principled λ / α choice,
    this test will catch the re-introduction of the old stamps and
    fail loudly.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")

    def test_no_row_carries_prevolatility_stamp(self) -> None:
        offending = [
            r.get("canonicalName")
            for r in _ranked_rows(self.contract)
            if "preVolatilityValue" in r
        ]
        self.assertFalse(
            offending,
            f"{len(offending)} row(s) carry the removed "
            f"preVolatilityValue stamp: {offending[:5]}",
        )

    def test_no_row_carries_volatility_fraction_stamp(self) -> None:
        offending = [
            r.get("canonicalName")
            for r in _ranked_rows(self.contract)
            if "volatilityCompressionApplied" in r
        ]
        self.assertFalse(
            offending,
            f"{len(offending)} row(s) carry the removed "
            f"volatilityCompressionApplied stamp: {offending[:5]}",
        )


class TestValueChain(unittest.TestCase):
    """``rankDerivedValue`` is derived from exactly one Hill blend
    and at most one calibration multiplier.

    For offense rows (no live calibration): ``rankDerivedValue`` must
    equal ``rankDerivedValueUncalibrated`` exactly.

    For IDP rows with an active promoted calibration config:
    ``rankDerivedValue`` must equal
    ``rankDerivedValueUncalibrated × idpCalibrationMultiplier × idpFamilyScale``
    applied exactly once.

    For IDP rows without an active config (default test env —
    ``tests/conftest.py`` redirects the config path): same as offense,
    strict equality.

    The deeper invariant under an active config is also exercised in
    ``tests/idp_calibration/test_family_scale_once_only.py``.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_offense_final_equals_uncalibrated(self) -> None:
        checked = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            uncal = row.get("rankDerivedValueUncalibrated")
            final = row.get("rankDerivedValue")
            if uncal is None or final is None:
                continue
            self.assertEqual(
                int(final),
                int(uncal),
                f"{row.get('canonicalName')} offense row has "
                f"rankDerivedValue={final} != "
                f"rankDerivedValueUncalibrated={uncal}. "
                f"Either offense calibration was re-enabled, or a new "
                f"mystery multiplier was inserted after the blend.",
            )
            checked += 1
        self.assertGreater(checked, 50, "expected many offense anchors")

    def test_idp_final_is_one_time_calibration_fold(self) -> None:
        """IDP chain.

        When calibration is active, ``rankDerivedValue`` equals
        ``uncalibrated × (bucket × family_scale)`` applied exactly once.

        When calibration is neutral (fields absent), final equals
        uncalibrated.
        """
        checked = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _IDP_POSITIONS:
                continue
            uncal = row.get("rankDerivedValueUncalibrated")
            final = row.get("rankDerivedValue")
            if uncal is None or final is None:
                continue
            bucket = row.get("idpCalibrationMultiplier")
            family = row.get("idpFamilyScale")
            if bucket is not None and family is not None:
                expected = int(round(float(uncal) * float(bucket) * float(family)))
                self.assertLessEqual(
                    abs(int(final) - expected),
                    2,
                    f"{row.get('canonicalName')} IDP (calibrated): "
                    f"rankDerivedValue={final} != round("
                    f"uncal={uncal} × bucket={bucket} × "
                    f"family={family}) = {expected}.  family_scale may "
                    f"have been double-applied, or a new IDP multiplier "
                    f"was introduced.",
                )
            else:
                self.assertEqual(
                    int(final),
                    int(uncal),
                    f"{row.get('canonicalName')} IDP (no calibration): "
                    f"rankDerivedValue={final} != uncalibrated={uncal}. "
                    f"A new IDP post-pass was added between Hill blend "
                    f"and final.",
                )
            checked += 1
        self.assertGreater(checked, 30, "expected many IDP anchors")


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
        # Single Hill curve with our constants: rank 1 ≈ 9999, rank 50
        # ≈ 5000.  A second curve would compress this below ~3000.
        # 2500 is a forgiving floor — a real second-curve regression
        # would drop it far below that.
        self.assertGreater(
            spread,
            2500,
            f"Top-50 offense value spread collapsed to {spread} "
            f"({top}..{bottom}). A second Hill remap may have been "
            f"introduced; investigate calibration passes.",
        )

    def test_no_value_exceeds_display_scale(self) -> None:
        """rankDerivedValue must stay within the display scale."""
        offenders: list[tuple[str, int]] = []
        for row in self.rows:
            final = row.get("rankDerivedValue")
            if final is None:
                continue
            try:
                v = int(final)
            except (TypeError, ValueError):
                continue
            if v > _DISPLAY_SCALE_MAX:
                offenders.append((str(row.get("canonicalName") or ""), v))
        self.assertFalse(
            offenders,
            f"Rows above _DISPLAY_SCALE_MAX={_DISPLAY_SCALE_MAX}: "
            f"{offenders[:5]}",
        )
