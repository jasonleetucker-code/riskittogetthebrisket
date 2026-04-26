"""Trade Suggestions: ``apply_scoring_fit`` parameter substitutes the
adjusted IDP value for the consensus ``rankDerivedValue`` when on.

Pin the substitution invariant so future refactors don't silently
drop the flag or apply it to the wrong rows (offense, picks).
"""
from __future__ import annotations

import unittest

from src.trade.suggestions import build_asset_pool_from_contract


class TestBuildAssetPoolApplyScoringFit(unittest.TestCase):
    def _contract(self):
        return {
            "playersArray": [
                {
                    "canonicalName": "Micah Parsons",
                    "displayName": "Micah Parsons",
                    "position": "LB",
                    "rankDerivedValue": 5000,
                    "idpScoringFitAdjustedValue": 6500,
                    "idpScoringFitDelta": 5000,
                },
                {
                    "canonicalName": "Josh Allen",
                    "displayName": "Josh Allen",
                    "position": "QB",
                    "rankDerivedValue": 9500,
                    # Offense rows never carry idpScoringFitAdjustedValue.
                },
                {
                    "canonicalName": "Cedric Gray",
                    "displayName": "Cedric Gray",
                    "position": "LB",
                    "rankDerivedValue": 1500,
                    "idpScoringFitAdjustedValue": 800,  # negative delta
                    "idpScoringFitDelta": -2333,
                },
            ],
            "players": {},
        }

    def test_default_uses_consensus(self):
        """Without the flag, every row uses ``rankDerivedValue``."""
        pool = build_asset_pool_from_contract(self._contract())
        by_name = {a.name: a for a in pool}
        self.assertEqual(by_name["Micah Parsons"].calibrated_value, 5000)
        self.assertEqual(by_name["Josh Allen"].calibrated_value, 9500)
        self.assertEqual(by_name["Cedric Gray"].calibrated_value, 1500)

    def test_flag_swaps_idp_to_adjusted(self):
        """With the flag, IDPs use adjusted; offense unchanged."""
        pool = build_asset_pool_from_contract(
            self._contract(), apply_scoring_fit=True,
        )
        by_name = {a.name: a for a in pool}
        # IDP positive delta — value goes UP.
        self.assertEqual(by_name["Micah Parsons"].calibrated_value, 6500)
        # Offense unchanged — no adjusted value to substitute.
        self.assertEqual(by_name["Josh Allen"].calibrated_value, 9500)
        # IDP negative delta — value goes DOWN.
        self.assertEqual(by_name["Cedric Gray"].calibrated_value, 800)

    def test_idp_without_adjusted_passes_through(self):
        """IDPs that don't have an adjusted value (sentinel rookies,
        offense-only-league pass) use raw consensus even with flag on."""
        contract = {
            "playersArray": [
                {
                    "canonicalName": "Rookie LB",
                    "displayName": "Rookie LB",
                    "position": "LB",
                    "rankDerivedValue": 2000,
                    # No idpScoringFitAdjustedValue.
                },
            ],
            "players": {},
        }
        pool = build_asset_pool_from_contract(contract, apply_scoring_fit=True)
        self.assertEqual(pool[0].calibrated_value, 2000)


if __name__ == "__main__":
    unittest.main()
