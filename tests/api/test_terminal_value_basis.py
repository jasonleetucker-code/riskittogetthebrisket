"""``teamAggregates.totalValue`` says which concept it is.

Audit W20-F003 / W30-F017. The number is the plain sum of
``rankDerivedValue`` over the roster's PLAYERS — no lineup solve, no
starter/depth weighting, no replacement level, picks excluded — and it
was rendered beside a Portfolio panel that composes picks back in.  Two
unlabelled totals differing by 22.5% of a portfolio on one screen.

Team value is not renamed away (the delta series is computed over the
same player set, so moving the level without the history would make
level and delta describe different portfolios).  It is LABELLED, which
is the other half of the finding's own required repair.
"""

from __future__ import annotations

import unittest

from src.api.terminal import build_terminal_payload


def _contract() -> dict:
    players = [
        {"name": "Alpha", "pos": "QB", "rankDerivedValue": 9000, "age": 25},
        {"name": "Bravo", "pos": "RB", "rankDerivedValue": 4000, "age": 27},
        {"name": "2027 Mid 1st", "pos": "PICK", "rankDerivedValue": 5000},
    ]
    return {
        "contractVersion": "test",
        "generatedAt": "2026-08-05T00:00:00+00:00",
        "playersArray": players,
        "sleeper": {
            "teams": [
                {
                    "ownerId": "owner-1",
                    "name": "Testers",
                    "roster_id": 1,
                    "players": ["Alpha", "Bravo"],
                    "picks": ["2027 Mid 1st"],
                }
            ],
            "rosterPositions": ["QB", "RB", "BN"],
        },
    }


class ValueBasisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_terminal_payload(
            _contract(),
            resolved_team={
                "ownerId": "owner-1",
                "name": "Testers",
                "roster_id": 1,
                "players": ["Alpha", "Bravo"],
                "picks": ["2027 Mid 1st"],
            },
        )
        self.aggs = self.payload["teamAggregates"]

    def test_the_total_is_players_only(self) -> None:
        self.assertEqual(self.aggs["totalValue"], 13000)  # 9000 + 4000, no pick

    def test_the_payload_names_the_concept(self) -> None:
        basis = self.aggs["valueBasis"]
        self.assertEqual(basis["concept"], "portfolioValue")
        self.assertEqual(basis["assetScope"], "playersOnly")
        self.assertIs(basis["includesPicks"], False)
        self.assertIs(basis["lineupWeighted"], False)
        self.assertEqual(basis["valueField"], "rankDerivedValue")
        self.assertIn("Not a", basis["note"])

    def test_the_basis_is_present_even_with_no_team_resolved(self) -> None:
        payload = build_terminal_payload(_contract(), resolved_team=None)
        aggs = payload["teamAggregates"]
        # An absent total must not also lose the label saying what the
        # total WOULD have been — "missing" and "unlabelled" are
        # different failures.
        self.assertIsNone(aggs["totalValue"])
        self.assertEqual(aggs["valueBasis"]["assetScope"], "playersOnly")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
