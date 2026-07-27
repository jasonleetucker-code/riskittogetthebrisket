"""League-config construction: sleeper block first, registry fallback,
fail-loud when neither is coherent."""

from __future__ import annotations

import unittest

from src.bdvm.league_config import (
    BdvmLeagueConfig,
    DEFAULT_POS_GROUPS,
    LeagueConfigError,
    from_contract,
)

SLEEPER_CONTRACT = {
    "sleeper": {
        "scoringSettings": {"rec": 1.0, "bonus_rec_te": 0.5, "pass_td": 4.0},
        "rosterPositions": (
            [
                "QB",
                "RB",
                "RB",
                "WR",
                "WR",
                "WR",
                "TE",
                "FLEX",
                "FLEX",
                "SUPER_FLEX",
                "K",
                "DL",
                "DL",
                "DL",
                "LB",
                "LB",
                "LB",
                "DB",
                "DB",
            ]
            + ["BN"] * 20
            + ["TAXI"] * 3
        ),
        "leagueSettings": {"num_teams": 12, "taxi_slots": 3, "best_ball": False},
    }
}

REGISTRY_SETTINGS = {
    "teamCount": 10,
    "rosterSize": 24,
    "taxiSize": 5,
    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SFLEX": 1},
    "flexEligible": ["RB", "WR", "TE"],
    "sflexEligible": ["QB", "RB", "WR", "TE"],
}


class TestFromContract(unittest.TestCase):
    def test_sleeper_block_is_ground_truth(self):
        cfg = from_contract(SLEEPER_CONTRACT, league_key="dynasty_main")
        self.assertEqual(cfg.source, "sleeper_block")
        self.assertEqual(cfg.teams, 12)
        self.assertEqual(cfg.starters["RB"], 2)
        self.assertEqual(cfg.starters["WR"], 3)
        self.assertEqual(cfg.starters["DL"], 3)
        self.assertEqual(cfg.flex["FLEX"], (2, ("RB", "WR", "TE")))
        self.assertEqual(cfg.flex["SUPER_FLEX"][0], 1)
        self.assertTrue(cfg.superflex)
        self.assertTrue(cfg.te_premium)
        # bench-type slots never count
        self.assertNotIn("BN", cfg.starters)
        self.assertEqual(cfg.taxi_size, 3)

    def test_registry_fallback_when_sleeper_missing(self):
        contract = {"sleeper": {"scoringSettings": {"rec": 0.5}}}
        cfg = from_contract(
            contract,
            league_key="dynasty_new",
            registry_roster_settings=REGISTRY_SETTINGS,
            idp_enabled=False,
        )
        self.assertEqual(cfg.source, "registry")
        self.assertEqual(cfg.teams, 10)
        self.assertEqual(cfg.flex["FLEX"], (2, ("RB", "WR", "TE")))
        self.assertEqual(cfg.flex["SUPER_FLEX"][0], 1)
        self.assertFalse(cfg.te_premium)

    def test_idp_disabled_strips_idp_slots(self):
        cfg = from_contract(SLEEPER_CONTRACT, league_key="x", idp_enabled=False)
        self.assertNotIn("DL", cfg.starters)
        self.assertNotIn("LB", cfg.starters)
        self.assertNotIn("DB", cfg.starters)

    def test_no_lineup_anywhere_fails_loud(self):
        with self.assertRaises(LeagueConfigError):
            from_contract({"sleeper": {"scoringSettings": {"rec": 1.0}}}, league_key="x")

    def test_no_scoring_fails_loud(self):
        contract = {
            "sleeper": {
                "rosterPositions": ["QB", "RB"],
                "leagueSettings": {"num_teams": 12},
            }
        }
        with self.assertRaises(LeagueConfigError):
            from_contract(contract, league_key="x")

    def test_config_hash_stable_and_sensitive(self):
        cfg1 = from_contract(SLEEPER_CONTRACT, league_key="x")
        cfg2 = from_contract(SLEEPER_CONTRACT, league_key="x")
        self.assertEqual(cfg1.config_hash, cfg2.config_hash)
        changed = {
            "sleeper": {
                **SLEEPER_CONTRACT["sleeper"],
                "scoringSettings": {"rec": 0.5},
            }
        }
        cfg3 = from_contract(changed, league_key="x")
        self.assertNotEqual(cfg1.config_hash, cfg3.config_hash)


class TestValidation(unittest.TestCase):
    def _base_kwargs(self):
        return dict(
            league_key="t",
            starters={"QB": 1},
            flex={},
            waiver_buffer={},
            default_buffer=0.5,
            pos_groups=dict(DEFAULT_POS_GROUPS),
            scoring_settings={"rec": 1.0},
        )

    def test_teams_must_be_at_least_two(self):
        with self.assertRaises(LeagueConfigError):
            BdvmLeagueConfig(teams=1, **self._base_kwargs())

    def test_unknown_position_group_fails_loud(self):
        cfg = BdvmLeagueConfig(teams=12, **self._base_kwargs())
        with self.assertRaises(LeagueConfigError):
            cfg.group("XX")

    def test_negative_starters_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["starters"] = {"QB": -1}
        with self.assertRaises(LeagueConfigError):
            BdvmLeagueConfig(teams=12, **kwargs)


if __name__ == "__main__":
    unittest.main()
