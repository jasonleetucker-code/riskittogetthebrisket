"""Backend half of the trade-grading parity test (math audit finding C3).

A dynasty trade gets a letter grade in two places, and they are not a
primary/fallback pair — they are the same product feature rendered by
two runtimes:

* ``frontend/lib/league-analysis.js::gradeTradeSides`` — the private
  ``/trades`` page.
* ``src/public_league/trade_grading.py`` — the public ``/league``
  activity timeline, server-rendered by
  ``src/public_league/activity.py`` and therefore unable to import the
  JS.

Until 2026-08-04 the public half summed ``max(value, 1) ** 1.65`` over
each side's RECEIVED assets and compared side totals, while the private
half took a plain linear net plus the KTC value adjustment — and both
fed the SAME 3/8/15/25/40 band table.  Raising to 1.65 inflates a gap
(a 10% linear edge becomes ~16%), so one trade rendered "Good win (A-)"
on ``/trades`` and "Clear win (B+)" on ``/league``.  ``activity.py``
carried a comment asserting the two landed in the same bucket.  Nothing
checked, so nothing noticed.

BOTH halves assert against ONE fixture,
``tests/fixtures/trade_grade_parity_cases.json``.  Neither may hardcode
an expectation of its own: if the two implementations disagree, exactly
one of the two suites goes red against a shared, human-authored
statement of what a grade is supposed to mean.

Frontend twin: ``frontend/__tests__/trade-grade-parity.test.js``.

WHAT IS ASSERTED
    * the band table, at every cut point and immediately below it;
    * ``pctGap`` and the ``{grade, label}`` block for a supplied
      ``vaNet`` (``bandCases``) — the ratio arithmetic on its own;
    * the same, end to end with the VA computed (``tradeCases``);
    * the signed VA itself against real keeptradecut.com captures
      (``vaEngineCases``).

WHAT IS DELIBERATELY NOT ASSERTED
    ``winner`` / ``loser`` / ``headlineSide``.  Those live only in the
    JS ``analyzeRawTrade`` card shape — the public payload emits a
    per-side badge and no headline — so there is nothing on this side to
    compare them to.  Their internal consistency is pinned by
    ``frontend/__tests__/league-analysis.test.js``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.public_league import activity, trade_grading

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "trade_grade_parity_cases.json"

with FIXTURE_PATH.open(encoding="utf-8") as _fh:
    FIXTURE: dict[str, Any] = json.load(_fh)

# How far below a cut point we probe for "the band below owns this".
_EPSILON = 1e-9


class TradeGradeParityFixtureIntegrity(unittest.TestCase):
    """The fixture has to be worth trusting before it can bind anything."""

    def test_fixture_is_non_trivial(self) -> None:
        self.assertTrue(FIXTURE_PATH.is_file(), f"missing fixture {FIXTURE_PATH}")
        self.assertGreaterEqual(len(FIXTURE["bandCases"]), 20)
        self.assertGreaterEqual(len(FIXTURE["tradeCases"]), 5)
        self.assertGreaterEqual(len(FIXTURE["vaEngineCases"]["cases"]), 8)

    def test_case_ids_are_unique(self) -> None:
        ids = (
            [c["id"] for c in FIXTURE["bandCases"]]
            + [c["id"] for c in FIXTURE["tradeCases"]]
            + [c["id"] for c in FIXTURE["vaEngineCases"]["cases"]]
        )
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        self.assertFalse(dupes, f"duplicate case ids: {dupes}")


class BandTableParity(unittest.TestCase):
    """The 3/8/15/25/40 ladder, at each cut point and just below it."""

    def test_band_cut_points(self) -> None:
        for role, is_winner in (("winner", True), ("loser", False)):
            bands = FIXTURE["bands"][role]
            for i, band in enumerate(bands):
                pct = float(band["atLeast"])
                got = trade_grading.grade_from_pct(pct, is_winner)
                self.assertEqual(
                    (got["grade"], got["label"]),
                    (band["grade"], band["label"]),
                    f"{role} band at {pct}%",
                )
                if i == 0:
                    continue
                # A hair below the cut belongs to the band underneath.
                below = trade_grading.grade_from_pct(pct - _EPSILON, is_winner)
                prev = bands[i - 1]
                self.assertEqual(
                    (below["grade"], below["label"]),
                    (prev["grade"], prev["label"]),
                    f"{role} band just below {pct}%",
                )


class BandCaseParity(unittest.TestCase):
    """``grade_trade_side`` — the ratio arithmetic, VA supplied."""

    def test_band_cases(self) -> None:
        for case in FIXTURE["bandCases"]:
            with self.subTest(case=case["id"]):
                result = trade_grading.grade_trade_side(
                    trade_grading.sanitize_side_values(case["got"]),
                    trade_grading.sanitize_side_values(case["gave"]),
                    float(case["vaNet"]),
                )
                self.assertAlmostEqual(result["pctGap"], case["pctGap"], places=9, msg=case["why"])
                self.assertEqual(result["grade"]["grade"], case["grade"], case["why"])
                self.assertEqual(result["grade"]["label"], case["label"], case["why"])


class TradeCaseParity(unittest.TestCase):
    """``grade_trade_sides`` — the whole trade, VA computed."""

    def test_trade_cases(self) -> None:
        for case in FIXTURE["tradeCases"]:
            with self.subTest(case=case["id"]):
                graded = trade_grading.grade_trade_sides(
                    (side["got"], side["gave"]) for side in case["sides"]
                )
                self.assertEqual(len(graded), len(case["expected"]), case["why"])
                for i, (result, expected) in enumerate(zip(graded, case["expected"])):
                    self.assertAlmostEqual(
                        result["vaNet"], expected["vaNet"], places=9, msg=f"side {i}"
                    )
                    self.assertAlmostEqual(
                        result["pctGap"], expected["pctGap"], places=9, msg=f"side {i}"
                    )
                    self.assertEqual(result["grade"]["grade"], expected["grade"], f"side {i}")
                    self.assertEqual(result["grade"]["label"], expected["label"], f"side {i}")


class PublicFeedUsesTheCanonicalGrade(unittest.TestCase):
    """The parity contract has to bind the PIPELINE, not just the module.

    ``activity._apply_trade_grades`` is what actually stamps a badge on
    the public timeline, so it — not only ``trade_grading`` — is what has
    to agree with the fixture.  Replaying the shared trade cases through
    it is what catches a future edit that reintroduces a second formula
    on the way in (the retired alpha blend lived exactly here).
    """

    def test_activity_grades_match_the_shared_fixture(self) -> None:
        for case in FIXTURE["tradeCases"]:
            with self.subTest(case=case["id"]):
                # Synthesize one asset per value so the valuation
                # callable is a pure passthrough; grading never sees
                # anything but the numbers the fixture declares.
                trade = {
                    "transactionId": case["id"],
                    "sides": [
                        {
                            "receivedAssets": [{"kind": "player", "v": v} for v in side["got"]],
                            "sentAssets": [{"kind": "player", "v": v} for v in side["gave"]],
                        }
                        for side in case["sides"]
                    ],
                }
                activity._apply_trade_grades([trade], lambda asset: asset["v"])
                if case.get("activityAbstains"):
                    # The fixture declares that this case's values are
                    # not merely garbage numbers but assets the
                    # valuation could not price, and the public feed
                    # withholds the letter for those (W19-F003).  The
                    # fixture states why in ``activityWhy``; the
                    # arithmetic half is still asserted by
                    # ``TradeCaseParity`` above.
                    self.assertEqual(
                        [s["grade"]["grade"] for s in trade["sides"]],
                        [trade_grading.UNGRADED["grade"]] * len(trade["sides"]),
                        case["activityWhy"],
                    )
                    self.assertTrue(all(s["unpricedAssetCount"] > 0 for s in trade["sides"]))
                    continue
                self.assertEqual(
                    [s["grade"]["grade"] for s in trade["sides"]],
                    [e["grade"] for e in case["expected"]],
                    case["why"],
                )
                self.assertEqual(
                    [s["grade"]["label"] for s in trade["sides"]],
                    [e["label"] for e in case["expected"]],
                    case["why"],
                )
                self.assertTrue(all(s["unpricedAssetCount"] == 0 for s in trade["sides"]))


class VaEngineParity(unittest.TestCase):
    """The KTC value adjustment, against keeptradecut.com's own numbers."""

    def test_va_engine_cases(self) -> None:
        block = FIXTURE["vaEngineCases"]
        tolerance = float(block["tolerance"])
        for case in block["cases"]:
            with self.subTest(case=case["id"]):
                got = trade_grading.trade_va_net(
                    trade_grading.sanitize_side_values(case["got"]),
                    trade_grading.sanitize_side_values(case["gave"]),
                )
                self.assertLessEqual(
                    abs(got - float(case["vaNet"])),
                    tolerance,
                    f"{case['id']}: {case['why']} (got {got}, KTC {case['vaNet']})",
                )

    def test_va_is_antisymmetric(self) -> None:
        # Swapping got and gave has to flip the sign, or a two-team
        # trade would grade both sides as winners.
        for case in FIXTURE["vaEngineCases"]["cases"]:
            with self.subTest(case=case["id"]):
                forward = trade_grading.trade_va_net(case["got"], case["gave"])
                reverse = trade_grading.trade_va_net(case["gave"], case["got"])
                self.assertAlmostEqual(forward, -reverse, places=9)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
