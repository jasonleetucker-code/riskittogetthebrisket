"""Tests for the bridge between the private canonical contract and
the public ``/api/public/league`` activity trade-grading pipeline.

Pins the contract-shape dependency — specifically that the valuation
walks ``values.displayValue`` / ``values.overall`` /
``values.finalAdjusted`` / ``values.rawComposite`` against the
contract ``playersArray`` rows, and NOT a ``values.full`` key (which
is a frontend-only rename).  An earlier version of this bridge
assumed ``values.full`` and silently disabled public trade grading
in production; this test would have caught that immediately.
"""
from __future__ import annotations

import unittest

from src.api.public_activity_valuation import build_valuation_from_contract


class BuildValuationFromContractTests(unittest.TestCase):
    def test_returns_none_when_contract_missing(self) -> None:
        self.assertIsNone(build_valuation_from_contract(None))
        self.assertIsNone(build_valuation_from_contract({}))
        self.assertIsNone(build_valuation_from_contract({"playersArray": []}))

    def test_returns_none_when_every_row_has_no_value(self) -> None:
        # A contract full of rows whose value bundles are all zero /
        # missing must degrade gracefully rather than returning a
        # valuation that always resolves to 0.
        contract = {
            "playersArray": [
                {"playerId": "p1", "displayName": "A", "values": {}},
                {"playerId": "p2", "displayName": "B", "values": {"displayValue": 0}},
                {"playerId": "p3", "displayName": "C", "values": {"displayValue": None}},
            ],
        }
        self.assertIsNone(build_valuation_from_contract(contract))

    def test_reads_display_value_preferred_over_overall(self) -> None:
        # Regression: the backend contract's ``values`` bundle uses
        # ``displayValue`` / ``overall`` / ``finalAdjusted`` /
        # ``rawComposite``.  A previous bug read ``values.full`` (a
        # frontend-only rename) and returned None for every asset,
        # silently disabling grading in production.  Here we assert
        # the 1–9999 ``displayValue`` is the primary source, matching
        # the frontend ``inferValueBundle`` fallback chain.
        contract = {
            "playersArray": [
                {
                    "playerId": "sleeper-1",
                    "displayName": "Josh Allen",
                    "values": {
                        "displayValue": 9500,
                        "overall": 8200,
                        "finalAdjusted": 8200,
                        "rawComposite": 8100,
                    },
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(
            valuation({"kind": "player", "playerId": "sleeper-1"}),
            9500.0,
        )

    def test_falls_back_through_value_bundle_keys(self) -> None:
        # If ``displayValue`` is missing / zero, the resolver walks
        # ``overall`` → ``finalAdjusted`` → ``rawComposite`` in the
        # same order the frontend ``inferValueBundle`` fallback uses.
        contract = {
            "playersArray": [
                {
                    "playerId": "fallback-overall",
                    "displayName": "A",
                    "values": {"displayValue": 0, "overall": 4200},
                },
                {
                    "playerId": "fallback-final",
                    "displayName": "B",
                    "values": {"finalAdjusted": 3100},
                },
                {
                    "playerId": "fallback-raw",
                    "displayName": "C",
                    "values": {"rawComposite": 2500},
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(
            valuation({"kind": "player", "playerId": "fallback-overall"}),
            4200.0,
        )
        self.assertEqual(
            valuation({"kind": "player", "playerId": "fallback-final"}),
            3100.0,
        )
        self.assertEqual(
            valuation({"kind": "player", "playerId": "fallback-raw"}),
            2500.0,
        )

    def test_falls_back_to_player_name_when_id_misses(self) -> None:
        contract = {
            "playersArray": [
                {
                    "playerId": "real-id",
                    "displayName": "Jahmyr Gibbs",
                    "values": {"displayValue": 7500},
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        # ID miss → name fallback (case-insensitive).
        self.assertEqual(
            valuation({
                "kind": "player",
                "playerId": "unknown-id",
                "playerName": "Jahmyr Gibbs",
            }),
            7500.0,
        )
        self.assertEqual(
            valuation({
                "kind": "player",
                "playerId": "",
                "playerName": "JAHMYR GIBBS",
            }),
            7500.0,
        )

    def test_pick_value_probes_tier_centers(self) -> None:
        contract = {
            "playersArray": [
                {
                    "displayName": "2026 Mid 1st",
                    "values": {"displayValue": 6000},
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(
            valuation({"kind": "pick", "season": "2026", "round": 1}),
            6000.0,
        )

    def test_pick_value_honors_pick_aliases(self) -> None:
        # Canonical-pipeline authored aliases redirect generic tier
        # labels to slot-specific siblings — the resolver must apply
        # the alias before hitting the name map, otherwise picks
        # would resolve to stale suppressed-tier values (or zero).
        contract = {
            "pickAliases": {"2026 Mid 1st": "2026 Pick 1.06"},
            "playersArray": [
                {
                    "displayName": "2026 Pick 1.06",
                    "values": {"displayValue": 7200},
                },
                # Suppressed tier row is intentionally present to
                # confirm the resolver does NOT return its stale
                # value — it must follow the alias to the slot row.
                {
                    "displayName": "2026 Mid 1st",
                    "pickGenericSuppressed": True,
                    "values": {"displayValue": 99},
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(
            valuation({"kind": "pick", "season": "2026", "round": 1}),
            7200.0,
        )

    def test_unknown_asset_returns_zero(self) -> None:
        contract = {
            "playersArray": [
                {"playerId": "p1", "displayName": "A", "values": {"displayValue": 100}},
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(valuation({"kind": "player", "playerId": "unknown"}), 0.0)
        self.assertEqual(valuation({"kind": "pick", "season": "2099", "round": 1}), 0.0)
        self.assertEqual(valuation({"kind": "other"}), 0.0)
        self.assertEqual(valuation(None), 0.0)


if __name__ == "__main__":
    unittest.main()
