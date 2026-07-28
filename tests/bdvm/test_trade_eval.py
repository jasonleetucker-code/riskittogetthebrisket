"""BDVM trade-eval: CES per-strategy grading of one specific trade.

The honesty rule under test: unresolvable refs are REPORTED per side,
never silently priced at zero — a grade that quietly dropped an asset
would be worse than no grade.  And package math is CES, never a plain
sum (a 2-for-1 quantity dump must not grade as the sum of its parts).
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.api import bdvm_api
from src.bdvm.params import load_param_set
from src.bdvm.trade_math import package_value

PARAMS = load_param_set("params_v1")

VALUES_PAYLOAD = {
    "status": "ok",
    "meta": {"asOf": "2026-07-28T00:00:00Z", "paramSetId": "params_v1:test"},
    "players": [
        {
            "playerId": "p1",
            "name": "Elite Backer",
            "tradeValue": {
                "contender": 7000.0,
                "balanced": 7200.0,
                "rebuilder": 7400.0,
                "risk_neutral": 7100.0,
            },
        },
        {
            "playerId": "p2",
            "name": "Old Vet",
            "tradeValue": {
                "contender": 6000.0,
                "balanced": 5000.0,
                "rebuilder": 3000.0,
                "risk_neutral": 4900.0,
            },
        },
        {
            "playerId": "p3",
            "name": "Young Stash",
            "tradeValue": {
                "contender": 2000.0,
                "balanced": 3500.0,
                "rebuilder": 5000.0,
                "risk_neutral": 3400.0,
            },
        },
    ],
    "picks": [
        {
            "name": "2027 1.05",
            "distribution": {
                "contender": {"ev": 3000.0},
                "balanced": {"ev": 3600.0},
                "rebuilder": {"ev": 4200.0},
                "risk_neutral": {"ev": 3500.0},
            },
        }
    ],
}


class TestTradeEval(unittest.TestCase):
    def setUp(self):
        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)
        patcher = mock.patch.object(bdvm_api, "get_bdvm_values", return_value=VALUES_PAYLOAD)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _eval(self, side_a, side_b):
        return bdvm_api.get_bdvm_trade_eval(
            {"generatedAt": "x"}, "dynasty_main", side_a=side_a, side_b=side_b
        )

    def test_ces_not_plain_sum(self):
        out = self._eval([{"playerId": "p1"}], [{"playerId": "p2"}, {"playerId": "p3"}])
        self.assertEqual(out["status"], "ok")
        bal = out["byStrategy"]["balanced"]
        expected_a = package_value([7200.0], PARAMS)
        expected_b = package_value([5000.0, 3500.0], PARAMS)
        self.assertAlmostEqual(bal["sideA"], round(expected_a, 1))
        self.assertAlmostEqual(bal["sideB"], round(expected_b, 1))
        # CES with theta>1 prices consolidation: the 2-asset side grades
        # BELOW the plain sum of its parts.
        self.assertLess(bal["sideB"], 5000.0 + 3500.0)
        self.assertAlmostEqual(bal["edge"], round(expected_a - expected_b, 1))

    def test_strategy_currencies_flip_the_verdict(self):
        out = self._eval([{"playerId": "p2"}], [{"playerId": "p3"}])
        self.assertGreater(out["byStrategy"]["contender"]["edge"], 0)  # vet wins now
        self.assertLess(out["byStrategy"]["rebuilder"]["edge"], 0)  # stash wins later

    def test_picks_resolve_by_name_with_strategy_ev(self):
        out = self._eval(["2027 1.05"], [{"playerId": "p3"}])
        self.assertEqual(out["sideAAssets"][0]["kind"], "pick")
        self.assertAlmostEqual(out["byStrategy"]["rebuilder"]["sideA"], 4200.0)
        self.assertEqual(out["unresolved"], {"sideA": [], "sideB": []})

    def test_name_refs_resolve_case_insensitively(self):
        out = self._eval(["elite backer"], ["OLD VET"])
        self.assertEqual(out["unresolved"], {"sideA": [], "sideB": []})
        self.assertEqual(out["sideAAssets"][0]["kind"], "player")

    def test_unresolved_refs_are_reported_not_zeroed(self):
        out = self._eval([{"playerId": "p1"}, "Total Mystery"], [{"playerId": "p2"}])
        self.assertEqual(out["unresolved"]["sideA"], ["Total Mystery"])
        # side A's package contains ONLY the resolved asset
        self.assertAlmostEqual(
            out["byStrategy"]["balanced"]["sideA"], round(package_value([7200.0], PARAMS), 1)
        )

    def test_non_ok_board_passes_through(self):
        with mock.patch.object(
            bdvm_api,
            "get_bdvm_values",
            return_value={"status": "no_projection_snapshot", "message": "m"},
        ):
            out = self._eval([{"playerId": "p1"}], [])
        self.assertEqual(out["status"], "no_projection_snapshot")
        self.assertEqual(out["byStrategy"], {})


if __name__ == "__main__":
    unittest.main()
