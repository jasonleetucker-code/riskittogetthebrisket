"""Tests for KTC trade-URL parsing in
``src.trade.ktc_import.parse_trade_url``.

KTC uses either ``,`` or ``|`` to separate multiple player IDs in
``teamOne`` / ``teamTwo``.  The parser must accept both forms.
"""
from __future__ import annotations

import unittest

from src.trade.ktc_import import parse_trade_url


class TestParseTradeUrl(unittest.TestCase):
    def test_single_ids_both_sides(self):
        url = "https://keeptradecut.com/trade-calculator?teamOne=1274&teamTwo=1555&tep=0"
        one, two = parse_trade_url(url)
        self.assertEqual(one, [1274])
        self.assertEqual(two, [1555])

    def test_comma_separated_multi_ids(self):
        """Legacy KTC URL form — comma-delimited."""
        url = (
            "https://keeptradecut.com/trade-calculator"
            "?teamOne=1274,542&teamTwo=1555,1751&tep=0"
        )
        one, two = parse_trade_url(url)
        self.assertEqual(one, [1274, 542])
        self.assertEqual(two, [1555, 1751])

    def test_pipe_separated_multi_ids(self):
        """Current KTC URL form — pipe-delimited.  Regression guard
        for the ``non-integer KTC id in URL: '1934|1771'`` error
        users hit when importing trades from the live site."""
        url = (
            "https://keeptradecut.com/trade-calculator"
            "?var=5&pickVal=0&teamOne=1934|1771&teamTwo=542|1751&format=2"
        )
        one, two = parse_trade_url(url)
        self.assertEqual(one, [1934, 1771])
        self.assertEqual(two, [542, 1751])

    def test_mixed_delimiters_on_same_url(self):
        """Defensive: if KTC ever generates mixed ``,`` and ``|``, we
        still handle it.  Not observed in the wild, but cheap to
        support with a single regex split."""
        url = (
            "https://keeptradecut.com/trade-calculator"
            "?teamOne=100,200|300&teamTwo=400|500,600"
        )
        one, two = parse_trade_url(url)
        self.assertEqual(one, [100, 200, 300])
        self.assertEqual(two, [400, 500, 600])

    def test_non_integer_still_raises(self):
        url = "https://keeptradecut.com/trade-calculator?teamOne=abc&teamTwo=1555"
        with self.assertRaises(ValueError) as ctx:
            parse_trade_url(url)
        self.assertIn("non-integer KTC id", str(ctx.exception))

    def test_empty_url_raises(self):
        url = "https://keeptradecut.com/trade-calculator?foo=bar"
        with self.assertRaises(ValueError) as ctx:
            parse_trade_url(url)
        self.assertIn("missing both teamOne and teamTwo", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
