"""TC-C -- the ONE fairness-band owner (owner decision 3, 2026-10-18).

Pins:
* the owner classifies every shared validation case (offense, IDP, picks,
  consolidation, large packages, boundaries) as the fixture's formula says;
* the JS mirror's constants equal the JSON owner (so the meter and the decision
  cannot drift apart);
* the band is RELATIVE with an ABSOLUTE MINIMUM: sign-blind, monotone in the
  gap, scale-invariant above the minimum, and blind to asset class;
* it is labelled PROVISIONAL and does not touch the package model (q = 0.78).
"""

from __future__ import annotations

import inspect
import json
import re
import unittest
from pathlib import Path

from src.valuation_math import fairness_bands as fb
from src.valuation_math import package_model

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/fairness_band_cases.json").read_text(encoding="utf-8"))
JS = (ROOT / "frontend/lib/fairness-bands.js").read_text(encoding="utf-8")


class SharedCases(unittest.TestCase):
    def test_every_case(self) -> None:
        self.assertEqual(FIXTURE["bands"], fb.CONFIG["version"])
        mixes = {c["assetMix"] for c in FIXTURE["cases"]}
        for needed in ("offense", "idp", "picks", "consolidation", "large packages"):
            self.assertTrue(any(needed in m for m in mixes), needed)
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                got = fb.classify(case["adjustedGap"], case["largerAdjusted"])
                self.assertEqual(got["level"], case["expectedLevel"])

    def test_package_cases_match_the_active_model(self) -> None:
        for case in FIXTURE["cases"]:
            if "sideA" not in case:
                continue
            a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(case["sideA"], case["sideB"])
            with self.subTest(case=case["id"]):
                self.assertEqual(round(a_adj - b_adj), case["adjustedGap"])
                self.assertEqual(round(max(a_adj, b_adj)), case["largerAdjusted"])


class JsMirror(unittest.TestCase):
    def _js_const(self, name: str):
        m = re.search(rf"export const {name} = ([^;]+);", JS)
        self.assertIsNotNone(m, name)
        return json.loads(m.group(1))

    def test_constants_equal_the_owner(self) -> None:
        self.assertEqual(self._js_const("FAIRNESS_BANDS_VERSION"), fb.CONFIG["version"])
        self.assertEqual(self._js_const("FAIRNESS_BANDS_STATUS"), fb.CONFIG["status"])
        self.assertEqual(float(self._js_const("ABSOLUTE_MINIMUM")), fb.ABSOLUTE_MINIMUM)
        self.assertEqual(float(self._js_const("SLIGHT_PCT")), fb.SLIGHT_PCT)
        self.assertEqual(float(self._js_const("UNFAIR_PCT")), fb.UNFAIR_PCT)
        self.assertEqual(float(self._js_const("LOPSIDED_PCT")), fb.LOPSIDED_PCT)

    def test_labels_equal_the_owner(self) -> None:
        for level, label in fb.LABELS.items():
            self.assertIn(f'{level}: "{label}"', JS)


class Properties(unittest.TestCase):
    def test_sign_blind(self) -> None:
        for g in (0, 100, 400, 1200, 5000):
            self.assertEqual(fb.classify(g, 10000)["level"], fb.classify(-g, 10000)["level"])

    def test_monotone_in_gap(self) -> None:
        order = {lvl: i for i, lvl in enumerate(fb.LEVELS)}
        for larger in (1000, 5000, 10000, 40000):
            prev = 0
            for g in range(0, larger, max(1, larger // 200)):
                cur = order[fb.classify(g, larger)["level"]]
                self.assertGreaterEqual(cur, prev, (g, larger))
                prev = cur

    def test_scale_invariant_above_the_minimum(self) -> None:
        for pct in (1.0, 3.0, 4.0, 8.9, 9.1, 17.9, 18.1, 30.0):
            levels = {
                fb.classify(larger * pct / 100, larger)["level"]
                for larger in (10000, 20000, 40000)  # every gap here is >= 250
            }
            self.assertEqual(len(levels), 1, pct)

    def test_absolute_minimum_protects_small_packages(self) -> None:
        # 20% of a 1,000-point package is 200: below the minimum, never a verdict.
        self.assertEqual(fb.classify(200, 1000)["level"], "fair")
        self.assertEqual(fb.classify(250, 1000)["level"], "lopsided")

    def test_no_asset_class_input(self) -> None:
        self.assertEqual(list(inspect.signature(fb.classify).parameters), ["gap", "larger_side"])

    def test_empty_pairing_is_fair_with_no_relative(self) -> None:
        self.assertEqual(
            fb.classify(0, 0), {**fb.classify(0, 0), "level": "fair", "relativePct": None}
        )


class Provenance(unittest.TestCase):
    def test_provisional_and_model_untouched(self) -> None:
        self.assertEqual(fb.receipt()["status"], "PROVISIONAL")
        self.assertEqual(package_model.PACKAGE_MODELS[package_model.GEOM_Q078_V1]["q"], 0.78)
        self.assertEqual(fb.legacy_magnitude("fair"), "even")
        self.assertEqual(fb.legacy_magnitude("slight"), "lean")
        self.assertEqual(fb.legacy_magnitude("unfair"), "stretch")
        self.assertEqual(fb.legacy_magnitude("lopsided"), "stretch")


if __name__ == "__main__":
    unittest.main()
