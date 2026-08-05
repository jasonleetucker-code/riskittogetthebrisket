"""A trade the board cannot fully price is not graded — W19-F003.

``sanitize_side_values`` keeps only strictly-positive values, so an
asset the valuation could not price was dropped from BOTH the linear
sum and the KTC value adjustment.  It was treated as if it had never
been in the trade, not as "cannot grade this".  The letter grade was
emitted anyway.

Measured on the live 191-trade public feed: 224 of 1,708 asset slots
priced to 0.0 — 156 pick slots and 68 player slots — touching 63 of
191 trades (33%) and 126 of 393 sides (32%).  The dropped picks include
six ``2024 R1`` and fourteen ``2025 R1`` slots: first-round rookie
picks that were the headline asset of their trade.  Nothing on the
payload and nothing on ``activity.jsx`` recorded the omission, so a
trade whose biggest piece vanished still rendered "Robbery" or
"Fleeced" with full confidence.

The 2026 board carries pick rows for 2026-2028 rounds 1-6 only.  Every
2024/2025 pick and every round >= 5 future pick has no row at all, so
"the board does not cover this asset" is a permanent condition for a
third of the historical feed — not a transient gap.
"""

from __future__ import annotations

import unittest

from src.public_league import activity, trade_grading


def _trade(sides: list[tuple[list[dict], list[dict]]]) -> dict:
    return {
        "transactionId": "synthetic",
        "sides": [{"receivedAssets": got, "sentAssets": gave} for got, gave in sides],
    }


_A = {"kind": "player", "playerId": "a"}
_B = {"kind": "player", "playerId": "b"}
_PICK = {"kind": "pick", "season": "2025", "round": 1, "label": "2025 R1"}


def _priced(asset: dict) -> float | None:
    """Prices the two players; the 2025 first is off the board."""
    if asset.get("playerId") == "a":
        return 4400.0
    if asset.get("playerId") == "b":
        return 5200.0
    return None


class UnpricedAssetsSuppressTheGrade(unittest.TestCase):
    def test_a_fully_priced_trade_still_gets_a_letter(self) -> None:
        trade = _trade([([_A], [_B]), ([_B], [_A])])
        activity._apply_trade_grades([trade], _priced)
        for side in trade["sides"]:
            self.assertIn(side["grade"]["grade"], {"A", "A-", "A+", "B+", "B", "C", "D", "F"})
            self.assertEqual(side["unpricedAssetCount"], 0)

    def test_an_unpriced_asset_suppresses_the_letter_on_every_side(self) -> None:
        # Side 0 receives a 2025 first the board cannot price.  Side 1's
        # net is wrong by the same amount — it GAVE that pick — so the
        # abstention is per-trade, not per-side.
        trade = _trade([([_A, _PICK], [_B]), ([_B], [_A, _PICK])])
        activity._apply_trade_grades([trade], _priced)
        for side in trade["sides"]:
            self.assertEqual(side["grade"]["grade"], trade_grading.UNGRADED["grade"])
            self.assertIn("unpriced", side["grade"]["label"].lower())
        self.assertEqual(trade["sides"][0]["unpricedAssetCount"], 1)
        self.assertEqual(trade["sides"][1]["unpricedAssetCount"], 1)
        self.assertEqual(trade["unpricedAssetCount"], 2)

    def test_the_count_reaches_the_payload_not_just_the_badge(self) -> None:
        trade = _trade([([_A, _PICK, _PICK], [_B]), ([_B], [_A, _PICK, _PICK])])
        activity._apply_trade_grades([trade], _priced)
        self.assertEqual(trade["sides"][0]["unpricedAssetCount"], 2)
        self.assertEqual(trade["unpricedAssetCount"], 4)

    def test_a_valuation_that_cannot_answer_is_unpriced_not_zero(self) -> None:
        """NaN and a raising callable are both "no value", not "no worth"."""

        def _hostile(asset: dict) -> float:
            if asset.get("playerId") == "a":
                return float("nan")
            if asset.get("playerId") == "b":
                raise ValueError("no row")
            return 100.0

        trade = _trade([([_A], [_B]), ([_B], [_A])])
        activity._apply_trade_grades([trade], _hostile)
        for side in trade["sides"]:
            self.assertEqual(side["grade"]["grade"], trade_grading.UNGRADED["grade"])
            # Each side both RECEIVED one unpriceable asset and GAVE the
            # other, so each side carries two.
            self.assertEqual(side["unpricedAssetCount"], 2)

    def test_a_genuine_zero_is_graded_not_suppressed(self) -> None:
        """0.0 means "worth nothing", which IS a value the grade can use."""
        trade = _trade([([_A], [_B]), ([_B], [_A])])
        activity._apply_trade_grades([trade], lambda _a: 0.0)
        for side in trade["sides"]:
            self.assertEqual(side["grade"]["grade"], "A")
            self.assertEqual(side["unpricedAssetCount"], 0)


class GradeTradeSidesCarriesTheCount(unittest.TestCase):
    """The math half, independent of the activity feed."""

    def test_two_tuples_still_grade_exactly_as_before(self) -> None:
        graded = trade_grading.grade_trade_sides([([9000.0], [4000.0]), ([4000.0], [9000.0])])
        self.assertEqual(graded[0]["unpricedAssetCount"], 0)
        self.assertNotEqual(graded[0]["grade"]["grade"], trade_grading.UNGRADED["grade"])

    def test_a_three_tuple_supplies_the_unpriced_count(self) -> None:
        graded = trade_grading.grade_trade_sides(
            [([9000.0], [4000.0], 1), ([4000.0], [9000.0], 0)]
        )
        for side in graded:
            self.assertEqual(side["grade"]["grade"], trade_grading.UNGRADED["grade"])
            self.assertEqual(side["grade"]["label"], "Not graded — 1 unpriced asset")
            self.assertEqual(side["tradeUnpricedAssetCount"], 1)
        self.assertEqual(graded[0]["unpricedAssetCount"], 1)
        self.assertEqual(graded[1]["unpricedAssetCount"], 0)
        # The arithmetic is still reported — only the verdict abstains.
        self.assertEqual(graded[0]["gotValue"], 9000.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
