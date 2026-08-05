"""The Unknown type, and the coercions it exists to make impossible.

Each test here corresponds to a real substitution the 2026-08-04 audit
found in production, expressed as the expression that produced it.
``None`` was always available and prevented none of them, because
``None`` coerces silently — so the property under test is not "can
represent absence" but "refuses to be used as a number".
"""

from __future__ import annotations

import unittest

from src.utils.unknown import (
    Unknown,
    UnknownArithmeticError,
    aggregate,
    is_unknown,
    stamp,
)


class TestArithmeticIsRefused(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Unknown(reason="team_absent_from_sim", field="playoffOdds")

    def test_or_zero_the_single_most_common_form_raises(self) -> None:
        """``value or 0.0`` is the expression behind N-2.

        It turned a manager absent from a sim file into 0% playoff odds
        and a "Seller" recommendation. Making Unknown falsy would have
        let this keep working, so ``__bool__`` raises.
        """
        with self.assertRaises(UnknownArithmeticError):
            _ = self.u or 0.0

    def test_float_conversion_raises(self) -> None:
        with self.assertRaises(UnknownArithmeticError):
            float(self.u)

    def test_comparison_into_a_threshold_raises(self) -> None:
        """``if odds < 0.25`` must not silently classify an absence."""
        with self.assertRaises(UnknownArithmeticError):
            _ = self.u < 0.25

    def test_arithmetic_raises_in_both_operand_orders(self) -> None:
        for op in (
            lambda: self.u + 1,
            lambda: 1 + self.u,
            lambda: self.u * 2,
            lambda: 2 * self.u,
            lambda: self.u - 1,
            lambda: self.u / 2,
        ):
            with self.assertRaises(UnknownArithmeticError):
                op()

    def test_the_error_says_what_went_missing(self) -> None:
        """The traceback is usually where someone learns it was absent."""
        with self.assertRaises(UnknownArithmeticError) as ctx:
            float(self.u)
        message = str(ctx.exception)
        self.assertIn("team_absent_from_sim", message)
        self.assertIn("playoffOdds", message)


class TestSerialization(unittest.TestCase):
    def test_unknown_writes_null_plus_a_reason(self) -> None:
        """A bare null is indistinguishable from a forgotten field."""
        payload: dict = {}
        stamp(payload, "playoffOdds", Unknown(reason="team_absent_from_sim", detail="why"))
        self.assertIsNone(payload["playoffOdds"])
        self.assertEqual(payload["playoffOddsUnknown"]["reason"], "team_absent_from_sim")
        self.assertEqual(payload["playoffOddsUnknown"]["detail"], "why")

    def test_a_known_value_writes_plainly_and_clears_any_stale_reason(self) -> None:
        payload = {"playoffOdds": None, "playoffOddsUnknown": {"reason": "stale"}}
        stamp(payload, "playoffOdds", 0.42)
        self.assertEqual(payload["playoffOdds"], 0.42)
        self.assertNotIn("playoffOddsUnknown", payload)

    def test_zero_is_a_real_value_and_survives(self) -> None:
        """0.0 and unknown must never collapse into each other."""
        payload: dict = {}
        stamp(payload, "playoffOdds", 0.0)
        self.assertEqual(payload["playoffOdds"], 0.0)
        self.assertNotIn("playoffOddsUnknown", payload)


class TestAggregate(unittest.TestCase):
    def test_reports_what_it_excluded(self) -> None:
        """ "The average of the 8 we could measure" != "the average of 12"."""
        value, excluded = aggregate([1.0, 2.0, Unknown(reason="x"), 3.0])
        self.assertEqual(value, 2.0)
        self.assertEqual(excluded, 1)

    def test_all_unknown_is_unknown_not_zero(self) -> None:
        """An average of nothing is not zero."""
        value, excluded = aggregate([Unknown(reason="a"), Unknown(reason="b")])
        self.assertTrue(is_unknown(value))
        self.assertEqual(excluded, 2)
        # And the result is still arithmetically inert.
        with self.assertRaises(UnknownArithmeticError):
            float(value)

    def test_none_counts_as_excluded_too(self) -> None:
        value, excluded = aggregate([1.0, None, 3.0])
        self.assertEqual(value, 2.0)
        self.assertEqual(excluded, 1)


if __name__ == "__main__":
    unittest.main()
