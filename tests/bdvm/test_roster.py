"""Roster analysis + double-positive trade scan."""

from __future__ import annotations

import unittest

from src.bdvm.params import load_param_set
from src.bdvm.roster import (
    analyze_rosters,
    rosters_from_contract,
    scan_double_positive_trades,
    strategy_for_direction,
)

PARAMS = load_param_set("params_v1")


def player_entry(pid, name, group, fpg, age, cont, bal, reb, market=None):
    return {
        "playerId": pid,
        "name": name,
        "position": group,
        "group": group,
        "raw": {"age": age},
        "projection": {"fpg": fpg},
        "tradeValue": {"contender": cont, "balanced": bal, "rebuilder": reb, "risk_neutral": bal},
        "market": {
            "marketValue": market,
            "tradeClearing": (bal + market) / 2 if market is not None else None,
        },
    }


def build_fixture():
    """Three rosters: an old win-now team, a young future team, a middle one.

    Crucially, the timelines are MISALIGNED: the contender is stuck
    holding a young stash and the rebuilder an aging vet — the exact
    situation a double-positive trade resolves.
    """
    players = [
        # old team assets: contender-heavy...
        player_entry("o1", "Old Star Wr", "WR", 16.0, 30.0, 8000, 4000, 1500, 4100),
        player_entry("o2", "Old Rb", "RB", 14.0, 28.0, 5000, 2000, 600, 2100),
        player_entry("o3", "Old Te", "TE", 11.0, 29.0, 3000, 1500, 500, 1500),
        # ...plus a young stash the contender can't use
        player_entry("o4", "Young Stash Wr", "WR", 11.0, 22.0, 2500, 5200, 7000, 5200),
        # young team assets: rebuilder-heavy...
        player_entry("y1", "Young Wr", "WR", 11.0, 22.0, 4000, 7000, 9000, 7100),
        player_entry("y2", "Young Te", "TE", 8.0, 23.0, 3000, 6000, 7500, 6000),
        player_entry("y3", "Young Rb", "RB", 9.0, 22.0, 2500, 4500, 6000, 4400),
        # ...plus an aging vet the rebuilder should sell
        player_entry("y4", "Aging Vet Wr", "WR", 15.0, 29.0, 7000, 3800, 1200, 5000),
        # middle team
        player_entry("m1", "Mid Wr", "WR", 12.0, 26.0, 5000, 5000, 5000, 5000),
        player_entry("m2", "Mid Lb", "LB", 12.0, 25.0, 3000, 3000, 3000, 3000),
    ]
    payload = {
        "players": players,
        "replacement": {
            "WR": {"replacementFpg": 6.0},
            "RB": {"replacementFpg": 6.5},
            "TE": {"replacementFpg": 4.5},
            "LB": {"replacementFpg": 7.0},
            "QB": {"replacementFpg": 12.0},
        },
    }
    contract = {
        "sleeper": {
            "teams": [
                {
                    "name": "OldTeam",
                    "ownerId": "1",
                    "roster_id": 1,
                    "playerIds": ["o1", "o2", "o3", "o4"],
                    "players": [],
                    "pickDetails": [],
                },
                {
                    "name": "YoungTeam",
                    "ownerId": "2",
                    "roster_id": 2,
                    "playerIds": ["y1", "y2", "y3", "y4"],
                    "players": [],
                    "pickDetails": ["2027 1st", "2027 2nd"],
                },
                {
                    "name": "MidTeam",
                    "ownerId": "3",
                    "roster_id": 3,
                    "playerIds": ["m1", "m2"],
                    "players": [],
                    "pickDetails": [],
                },
            ]
        }
    }
    meta = {
        "starters": {"WR": 2, "RB": 1, "TE": 1, "LB": 1},
        "flex": {"FLEX": {"count": 1, "eligible": ["RB", "WR", "TE"]}},
    }
    return payload, contract, meta


class TestAnalyzeRosters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload, contract, meta = build_fixture()
        cls.analysis = analyze_rosters(payload, contract, PARAMS, league_cfg_meta=meta)
        cls.by_name = {r["name"]: r for r in cls.analysis["rosters"]}

    def test_capitals_and_ratio(self):
        old = self.by_name["OldTeam"]
        self.assertEqual(old["capitals"]["contender"], 18500.0)
        self.assertEqual(old["capitals"]["rebuilder"], 9600.0)
        self.assertGreater(old["nowFutureRatio"], 1.5)

    def test_relative_directions_diverge(self):
        self.assertEqual(self.by_name["OldTeam"]["direction"], "contend")
        self.assertEqual(self.by_name["YoungTeam"]["direction"], "rebuild")
        self.assertEqual(self.by_name["MidTeam"]["direction"], "retool")

    def test_strategy_mapping(self):
        self.assertEqual(strategy_for_direction("contend"), "contender")
        self.assertEqual(strategy_for_direction("rebuild"), "rebuilder")
        self.assertEqual(strategy_for_direction("retool"), "balanced")

    def test_value_weighted_age_and_surplus(self):
        old = self.by_name["OldTeam"]
        self.assertGreater(old["valueWeightedAge"], 26.0)
        # o1 (16.0) + o4 (11.0) above the 6.0 WR replacement → have 2, need 2
        self.assertEqual(old["positionalSurplus"]["WR"], 0)
        self.assertEqual(self.by_name["YoungTeam"]["pickCount"], 2)

    def test_unmatched_ids_counted(self):
        payload, contract, meta = build_fixture()
        contract["sleeper"]["teams"][0]["playerIds"].append("ghost")
        analysis = analyze_rosters(payload, contract, PARAMS, league_cfg_meta=meta)
        old = next(r for r in analysis["rosters"] if r["name"] == "OldTeam")
        self.assertEqual(old["unmatchedPlayerIds"], 1)

    def test_rosters_from_contract_shape(self):
        _, contract, _ = build_fixture()
        rosters = rosters_from_contract(contract)
        self.assertEqual(len(rosters), 3)
        self.assertEqual(rosters[0]["ownerId"], "1")


class TestTradeScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload, contract, meta = build_fixture()
        cls.analysis = analyze_rosters(payload, contract, PARAMS, league_cfg_meta=meta)
        cls.scan = scan_double_positive_trades(cls.analysis, PARAMS)

    def test_finds_timeline_trade(self):
        """Old star (contender-valuable) for young asset (rebuilder-valuable)
        must surface as double-positive between the old and young teams."""
        self.assertGreater(len(self.scan["trades"]), 0)
        pair_found = any(
            {t["from"]["name"], t["to"]["name"]} == {"OldTeam", "YoungTeam"}
            for t in self.scan["trades"]
        )
        self.assertTrue(pair_found)

    def test_each_side_gains_in_own_currency(self):
        for t in self.scan["trades"]:
            self.assertGreater(t["from"]["gain"], 0)
            self.assertGreater(t["to"]["gain"], 0)
            self.assertTrue(t["doublePositive"])

    def test_market_fairness_gate(self):
        for t in self.scan["trades"]:
            self.assertLessEqual(t["marketFairnessPct"], 12.0)

    def test_no_mirror_duplicates(self):
        seen = set()
        for t in self.scan["trades"]:
            key = frozenset(
                [
                    (t["from"]["ownerId"], tuple(sorted(t["from"]["gives"]))),
                    (t["to"]["ownerId"], tuple(sorted(t["to"]["gives"]))),
                ]
            )
            self.assertNotIn(key, seen, "mirror duplicate in scan output")
            seen.add(key)

    def test_team_filter(self):
        scan = scan_double_positive_trades(self.analysis, PARAMS, team="OldTeam")
        for t in scan["trades"]:
            self.assertEqual(t["from"]["name"], "OldTeam")
        bad = scan_double_positive_trades(self.analysis, PARAMS, team="NoSuchTeam")
        self.assertEqual(bad.get("error"), "unknown_team")


if __name__ == "__main__":
    unittest.main()
