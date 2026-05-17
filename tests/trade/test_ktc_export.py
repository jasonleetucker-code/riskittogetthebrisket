"""Tests for build_ktc_url (Phase 3) — inverse of resolve_trade_url."""
from __future__ import annotations

import unittest

from src.trade import ktc_import


_MAP = {
    1001: {"name": "Josh Allen", "position": "QB", "team": "BUF", "slug": "josh-allen", "rookie": False},
    1002: {"name": "Bijan Robinson", "position": "RB", "team": "ATL", "slug": "bijan", "rookie": False},
    1003: {"name": "2026 Mid 1st", "position": "RDP", "team": "", "slug": "", "rookie": False},
}


class BuildKtcUrlTests(unittest.TestCase):
    def test_resolves_and_builds_url(self) -> None:
        out = ktc_import.build_ktc_url(["Josh Allen"], ["Bijan Robinson", "2026 Mid 1st"], player_map=_MAP)
        self.assertIn("keeptradecut.com/trade-calculator", out["url"])
        self.assertIn("teamOne=1001", out["url"])
        self.assertIn("teamTwo=1002|1003", out["url"])
        self.assertEqual(out["unresolved"], {"sideOne": [], "sideTwo": []})
        self.assertEqual(out["resolvedCount"], {"sideOne": 1, "sideTwo": 2})

    def test_normalized_and_case_insensitive_match(self) -> None:
        out = ktc_import.build_ktc_url(["josh allen"], ["BIJAN ROBINSON"], player_map=_MAP)
        self.assertIn("teamOne=1001", out["url"])
        self.assertIn("teamTwo=1002", out["url"])

    def test_unknown_names_surfaced_not_dropped(self) -> None:
        out = ktc_import.build_ktc_url(["Nobody McGhost"], [], player_map=_MAP)
        self.assertEqual(out["unresolved"]["sideOne"], ["Nobody McGhost"])
        self.assertEqual(out["resolvedCount"]["sideOne"], 0)

    def test_round_trip_through_parse_and_resolve(self) -> None:
        built = ktc_import.build_ktc_url(["Josh Allen"], ["Bijan Robinson"], player_map=_MAP)
        one, two = ktc_import.parse_trade_url(built["url"])
        r1, _ = ktc_import.resolve_ktc_ids(one, player_map=_MAP)
        r2, _ = ktc_import.resolve_ktc_ids(two, player_map=_MAP)
        self.assertEqual([r["name"] for r in r1], ["Josh Allen"])
        self.assertEqual([r["name"] for r in r2], ["Bijan Robinson"])


if __name__ == "__main__":
    unittest.main()
