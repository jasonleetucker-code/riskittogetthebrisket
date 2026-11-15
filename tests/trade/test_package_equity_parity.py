"""TC-A #15 -- cross-surface package-equity parity (Python half).

Every surface that publishes an adjusted package gap must report the SAME gap
for the same inputs and the same package model.  The expectations live in ONE
shared fixture, ``tests/fixtures/trade_package_equity_parity_cases.json``,
derived in closed form from the active model -- neither language's code
produced them.  The JavaScript half is
``frontend/__tests__/trade-package-equity-parity.test.js``.

Surfaces asserted here:

* ``analyze_trade.equity_verdict`` -- the Analyze Trade market lens;
* ``suggestions._va_gap`` -- the suggestions scorer and equalizer;
* ``finder_value_adjustment.score_with_value_adjustment`` -- the finder scorer
  (on market values; see the fixture's ``intentionalDifferences``);
* ``public_league.trade_grading.grade_trade_sides`` -- the public trade-history
  grade (the private /trades twin is pinned by the JS half);
* ``monte_carlo._apply_consolidation_adjustment`` +
  ``symmetrize.enrich_with_decision_shape`` -- the simulation's applied
  adjustment and its published ``adjustedDelta``.

Intentional differences (finder market basis, analyze's unpriced / not-held
exclusions, 3+-team scope, rounding) are documented in the fixture and the two
that are reachable with a plain pairing are pinned below.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.public_league import trade_grading
from src.trade import finder, finder_value_adjustment, monte_carlo, suggestions, symmetrize
from src.trade.analyze_trade import equity_verdict
from src.valuation_math import package_model

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "trade_package_equity_parity_cases.json"
FIXTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = FIXTURE["cases"]


def _finder_asset(name: str, value: int, market: int | None = None) -> finder.Asset:
    return finder.Asset(
        name=name,
        position="WR",
        team="X",
        model_value=value,
        market_value=value if market is None else market,
    )


def _finder_gap(side_a: list[int], side_b: list[int], **overrides: Any) -> int:
    """The finder's adjusted gap (give minus receive) through its real scorer seam."""
    give = [_finder_asset(f"a{i}", v) for i, v in enumerate(side_a)]
    receive = [_finder_asset(f"b{i}", v) for i, v in enumerate(side_b)]
    for key, market in overrides.items():
        side, idx = key[0], int(key[1:])
        target = give if side == "a" else receive
        target[idx] = _finder_asset(target[idx].name, target[idx].model_value, market)

    def score(g: list[finder.Asset], r: list[finder.Asset]) -> finder.TradeCandidate:
        return finder.TradeCandidate(
            give=g,
            receive=r,
            give_ktc_total=sum(int(a.market_value or 0) for a in g),
            receive_ktc_total=sum(int(a.market_value or 0) for a in r),
        )

    cand = finder_value_adjustment.score_with_value_adjustment(give, receive, score)
    return int(cand.adjusted_give_ktc_total) - int(cand.adjusted_receive_ktc_total)


def _mc_player(name: str, value: int) -> monte_carlo.TradePlayer:
    return monte_carlo.TradePlayer(
        name=name,
        team="X",
        position_group="offense",
        p10=value * 0.85,
        p50=float(value),
        p90=value * 1.15,
    )


class FixtureIntegrity(unittest.TestCase):
    def test_fixture_is_for_the_active_model(self) -> None:
        self.assertEqual(FIXTURE["model"], package_model.active_model_id())
        self.assertGreaterEqual(len(CASES), 8)
        self.assertEqual(len({c["id"] for c in CASES}), len(CASES))

    def test_fixture_exercises_both_recipients_and_no_adjustment(self) -> None:
        recipients = {c["expected"]["vaRecipient"] for c in CASES}
        self.assertEqual(recipients, {"A", "B", None})


class PackageEquityParity(unittest.TestCase):
    def test_owner_adjustment(self) -> None:
        for case in CASES:
            exp = case["expected"]
            with self.subTest(case=case["id"]):
                value, side, displayed = package_model.adjust_pair(case["sideA"], case["sideB"])
                self.assertEqual(value if displayed else 0, exp["vaValue"])
                want_side = {"A": 1, "B": 2, None: 0}[exp["vaRecipient"]]
                self.assertEqual(side if displayed else 0, want_side)

    def test_analyze_trade_market_lens(self) -> None:
        # sideA is SENT, sideB RECEIVED: the lens publishes receive - send.
        for case in CASES:
            exp = case["expected"]
            with self.subTest(case=case["id"]):
                v = equity_verdict(case["sideA"], case["sideB"])
                self.assertEqual(v["vaAdjustedGap"], -exp["adjustedGap"])
                self.assertEqual(v["rawGap"], -exp["rawGap"])
                self.assertEqual(v["sendingAdjusted"], exp["adjustedA"])
                self.assertEqual(v["receivingAdjusted"], exp["adjustedB"])

    def test_suggestions_scorer(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    suggestions._va_gap(case["sideA"], case["sideB"]),
                    case["expected"]["adjustedGap"],
                )

    def test_finder_scorer(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    _finder_gap(case["sideA"], case["sideB"]), case["expected"]["adjustedGap"]
                )

    def test_trade_history_grade(self) -> None:
        # Side 0 gave A and got B; side 1 gave B and got A.
        for case in CASES:
            exp = case["expected"]
            with self.subTest(case=case["id"]):
                gave_a, gave_b = trade_grading.grade_trade_sides(
                    [(case["sideB"], case["sideA"]), (case["sideA"], case["sideB"])]
                )
                self.assertEqual(gave_a["netAdjusted"], -exp["adjustedGap"])
                self.assertEqual(gave_b["netAdjusted"], exp["adjustedGap"])

    def test_monte_carlo_adjustment_and_adjusted_delta(self) -> None:
        for case in CASES:
            exp = case["expected"]
            with self.subTest(case=case["id"]):
                side_a = [_mc_player(f"a{i}", v) for i, v in enumerate(case["sideA"])]
                side_b = [_mc_player(f"b{i}", v) for i, v in enumerate(case["sideB"])]
                new_a, new_b, info = monte_carlo._apply_consolidation_adjustment(side_a, side_b)
                applied = sum(p.p50 for p in new_a) - sum(p.p50 for p in new_b)
                self.assertAlmostEqual(applied, exp["adjustedGap"], places=6)
                enriched = symmetrize.enrich_with_decision_shape(
                    {"vaAdjustment": info, "winProbA": 0.5}, side_a, side_b
                )
                self.assertAlmostEqual(enriched["adjustedDelta"], exp["adjustedGap"], places=6)


class IntentionalDifferences(unittest.TestCase):
    """The documented differences that a plain pairing can reach."""

    def test_finder_applies_no_adjustment_without_full_market_coverage(self) -> None:
        case = next(c for c in CASES if c["id"] == "stud_for_two")
        # One receive-side asset has no market price: the finder scores the
        # priced pieces linearly (no package adjustment), by design.
        gap = _finder_gap(case["sideA"], case["sideB"], b1=0)
        self.assertEqual(gap, case["sideA"][0] - case["sideB"][0])

    def test_analyze_leaves_an_unpriced_asset_out_of_the_package_math(self) -> None:
        case = next(c for c in CASES if c["id"] == "stud_for_two")
        with_zero = equity_verdict(case["sideA"], [*case["sideB"], 0])
        without = equity_verdict(case["sideA"], case["sideB"])
        self.assertEqual(with_zero["vaAdjustedGap"], without["vaAdjustedGap"])


if __name__ == "__main__":
    unittest.main()
