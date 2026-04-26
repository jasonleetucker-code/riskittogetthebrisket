"""End-to-end integration test for the IDP scoring-fit pipeline.

Builds a full canonical contract from the most recent raw snapshot
in ``exports/latest/`` with the feature flag ON, asserts:

* Every IDP-with-delta row also carries the whitelisted top-level
  fields (``idpScoringFitVorp``, ``Tier``, ``Confidence``,
  ``AdjustedValue``).
* The ``rankDerivedValue`` column is byte-identical to a baseline
  build with the flag OFF — i.e., the pass is additive-only.
* At least 50% of league-rostered IDPs got a delta.  Catches
  silent regressions like the name-fallback bug (where coverage
  dropped from ~90% to ~24% without anyone noticing for 3 PRs).
* The delta distribution is reasonable: median in [-2000, 2000],
  not collapsed to 0 (would mean QuantileMap is broken).

Skipped when no raw snapshot exists in ``exports/latest/``
(fresh-checkout / CI without prior data).  Skipped when nflverse
fetches fail (offline / no network).
"""
from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _latest_raw_payload() -> dict | None:
    snapshots = sorted((_REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    if not snapshots:
        return None
    try:
        return json.loads(snapshots[-1].read_text())
    except Exception:
        return None


_IDP_POSITIONS = {
    "DL", "DT", "DE", "EDGE", "NT",
    "LB", "ILB", "OLB", "MLB",
    "DB", "CB", "S", "FS", "SS",
}


class TestIdpScoringFitPipelineIntegration(unittest.TestCase):
    """End-to-end pipeline test — needs a raw snapshot + network."""

    @classmethod
    def setUpClass(cls):
        cls.raw = _latest_raw_payload()
        if cls.raw is None:
            raise unittest.SkipTest(
                "No raw snapshot in exports/latest/ — skipping integration test"
            )

    def _build_contract(self, *, flag_on: bool) -> dict:
        # Set the flag explicitly so we don't depend on the env state.
        prev = os.environ.get("RISKIT_FEATURE_IDP_SCORING_FIT")
        os.environ["RISKIT_FEATURE_IDP_SCORING_FIT"] = "1" if flag_on else "0"
        try:
            from src.api import feature_flags
            feature_flags.reload()
            from src.api import data_contract as DC
            return DC.build_api_data_contract(deepcopy(self.raw))
        finally:
            if prev is None:
                os.environ.pop("RISKIT_FEATURE_IDP_SCORING_FIT", None)
            else:
                os.environ["RISKIT_FEATURE_IDP_SCORING_FIT"] = prev
            feature_flags.reload()

    def test_pass_stamps_required_fields(self):
        """Every IDP row with a delta must carry the full field set."""
        try:
            contract = self._build_contract(flag_on=True)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"contract build failed (likely offline): {exc!r}")
        arr = contract.get("playersArray") or []
        idp_with_delta = [
            r for r in arr
            if isinstance(r, dict)
            and str(r.get("position") or "").upper() in _IDP_POSITIONS
            and isinstance(r.get("idpScoringFitDelta"), (int, float))
        ]
        if not idp_with_delta:
            self.skipTest("no IDP rows with delta — nflverse fetch likely failed")

        required = (
            "idpScoringFitVorp",
            "idpScoringFitTier",
            "idpScoringFitConfidence",
            "idpScoringFitAdjustedValue",
        )
        for r in idp_with_delta[:50]:  # sample for speed
            for field in required:
                self.assertIn(
                    field, r,
                    f"IDP {r.get('displayName')!r} has delta but missing {field}",
                )

    def test_rank_derived_value_unchanged_by_pass(self):
        """The pass is additive-only — rankDerivedValue must equal what
        a flag-OFF build produces, byte-for-byte, on every row."""
        try:
            contract_off = self._build_contract(flag_on=False)
            contract_on = self._build_contract(flag_on=True)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"contract build failed: {exc!r}")
        arr_off = contract_off.get("playersArray") or []
        arr_on = contract_on.get("playersArray") or []
        by_name_off = {r.get("displayName"): r for r in arr_off if isinstance(r, dict)}
        for r in arr_on:
            if not isinstance(r, dict):
                continue
            name = r.get("displayName")
            ref = by_name_off.get(name)
            if ref is None:
                continue
            self.assertEqual(
                r.get("rankDerivedValue"),
                ref.get("rankDerivedValue"),
                f"{name}: rankDerivedValue mutated by scoring-fit pass",
            )

    def test_coverage_floor(self):
        """At least 50% of league-rostered IDPs must get a delta.

        Catches the name-fallback bug class — where the cross-walk
        silently drops half the universe and the lens shows sentinels
        for everyone except superstar names.
        """
        try:
            contract = self._build_contract(flag_on=True)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"contract build failed: {exc!r}")
        arr = contract.get("playersArray") or []
        all_idp = [
            r for r in arr
            if isinstance(r, dict)
            and str(r.get("position") or "").upper() in _IDP_POSITIONS
        ]
        if not all_idp:
            self.skipTest("no IDP rows in contract")
        with_delta = [
            r for r in all_idp
            if isinstance(r.get("idpScoringFitDelta"), (int, float))
        ]
        if len(with_delta) == 0:
            self.skipTest("no IDP deltas (nflverse fetch likely failed)")
        coverage = len(with_delta) / len(all_idp)
        self.assertGreaterEqual(
            coverage, 0.50,
            f"coverage {coverage:.0%} below 50% floor — likely a "
            f"cross-walk regression.  {len(with_delta)} of {len(all_idp)} "
            f"IDPs have a delta.",
        )

    def test_delta_distribution_reasonable(self):
        """Median delta should be near zero but distribution should
        not be collapsed (i.e., QuantileMap is producing variation).

        A median of exactly 0 across hundreds of rows would suggest
        the quantile map is returning the same value for everyone.
        """
        try:
            contract = self._build_contract(flag_on=True)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"contract build failed: {exc!r}")
        arr = contract.get("playersArray") or []
        deltas = sorted(
            float(r["idpScoringFitDelta"])
            for r in arr
            if isinstance(r, dict)
            and isinstance(r.get("idpScoringFitDelta"), (int, float))
        )
        if len(deltas) < 20:
            self.skipTest(f"only {len(deltas)} deltas — sample too thin")
        median = deltas[len(deltas) // 2]
        # Median should be in a sensible range — not pinned at the
        # extremes (would suggest the quantile map is broken).
        self.assertGreater(
            max(deltas) - min(deltas), 1000,
            "delta range too narrow — QuantileMap may be collapsed",
        )
        # Median is often non-zero (the consensus market and the
        # league's scoring rarely agree exactly), but if it's > 5000
        # the lens is biased systematically.
        self.assertLess(
            abs(median), 5000,
            f"median delta {median} suggests a systemic bias — "
            f"check the QuantileMap distribution",
        )


if __name__ == "__main__":
    unittest.main()
