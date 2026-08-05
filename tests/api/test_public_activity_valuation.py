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

    def test_falls_back_through_board_scale_keys_only(self) -> None:
        # If ``displayValue`` is missing / zero, the resolver walks
        # ``overall`` → ``finalAdjusted``.  All three mirror the board's
        # ``rankDerivedValue``, so walking them cannot change scale.
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

    def test_raw_composite_is_not_a_fallback(self) -> None:
        """A row the board declined to price grades as unpriced, never on
        the composite scale.

        Math audit 2026-07-30, finding H1.  ``values.rawComposite`` is the
        legacy scraper composite and runs ~1.131x the canonical board, so
        splicing it into this chain put two scales inside one trade-side
        sum.  Measured on a real payload: 270 rows carried a composite
        number with no board value, every suppressed generic pick tier
        among them (``2026 Early 1st`` = 6136 composite, against real slot
        picks at 1.01 = 7852 / 1.02 = 6101 on the board).

        This test previously asserted the OPPOSITE — it pinned the
        composite as the last fallback — so it is the regression guard
        turned the right way round.
        """
        contract = {
            "playersArray": [
                # Board-priced row: still resolves normally.
                {
                    "playerId": "priced",
                    "displayName": "Priced",
                    "values": {"overall": 5000, "rawComposite": 5655},
                },
                # Board declined to price it, but the scrape composite is
                # present — exactly the 270-row case.
                {
                    "playerId": "unpriced",
                    "displayName": "Unpriced",
                    "values": {
                        "displayValue": None,
                        "overall": None,
                        "finalAdjusted": None,
                        "rawComposite": 2500,
                    },
                },
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertEqual(
            valuation({"kind": "player", "playerId": "priced"}),
            5000.0,
        )
        # ``None`` means "cannot price this asset", which is what
        # ``activity._side_values`` needs to hear.  2500.0 would be the
        # composite leaking in on the wrong scale.
        #
        # This assertion read ``0.0`` until W19-F003.  0.0 is dropped by
        # ``sanitize_side_values``, so an asset the board refused to
        # price became indistinguishable from one that was never in the
        # trade — 224 of 1,708 live slots, including 20 first-round
        # picks, silently removed from a grade that was still emitted.
        self.assertIsNone(valuation({"kind": "player", "playerId": "unpriced"}))

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
            valuation(
                {
                    "kind": "player",
                    "playerId": "unknown-id",
                    "playerName": "Jahmyr Gibbs",
                }
            ),
            7500.0,
        )
        self.assertEqual(
            valuation(
                {
                    "kind": "player",
                    "playerId": "",
                    "playerName": "JAHMYR GIBBS",
                }
            ),
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

    def test_unknown_asset_is_unpriced_not_worthless(self) -> None:
        """Every miss returns ``None`` (W19-F003).

        The 2026 board carries pick rows for 2026-2028 rounds 1-6 only,
        so a 2025 first is a PERMANENT miss on the historical public
        feed — 156 of the 224 unpriced slots there are picks.  Returning
        0.0 reported each of them as an asset worth nothing.
        """
        contract = {
            "playersArray": [
                {"playerId": "p1", "displayName": "A", "values": {"displayValue": 100}},
            ],
        }
        valuation = build_valuation_from_contract(contract)
        self.assertIsNotNone(valuation)
        self.assertIsNone(valuation({"kind": "player", "playerId": "unknown"}))
        self.assertIsNone(valuation({"kind": "pick", "season": "2099", "round": 1}))
        self.assertIsNone(valuation({"kind": "pick", "season": "2025", "round": 1}))
        self.assertIsNone(valuation({"kind": "other"}))
        self.assertIsNone(valuation(None))
        # …and a real hit is unaffected.
        self.assertEqual(valuation({"kind": "player", "playerId": "p1"}), 100.0)


if __name__ == "__main__":
    unittest.main()
