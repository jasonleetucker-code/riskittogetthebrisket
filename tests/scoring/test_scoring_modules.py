import unittest
import tempfile
import json
import os

from src.scoring.baseline_config import build_default_baseline_config
from src.scoring.player_adjustment import (
    build_player_scoring_adjustment,
    ratio_to_multiplier,
)
from src.scoring.scoring_delta import compare_to_baseline, persist_scoring_delta_map
from src.scoring.sleeper_ingest import normalize_scoring_settings


class ScoringModuleTests(unittest.TestCase):
    def test_normalize_scoring_aliases(self):
        cfg = normalize_scoring_settings(
            {
                "idp_solo": 2,
                "idp_ast": 1,
                "pass_td": 6,
                "unknown_custom_key": 3,
            },
            ["QB", "LB"],
            league_id="x",
            season=2026,
        )
        self.assertEqual(cfg.scoring_map["idp_tkl_solo"], 2.0)
        self.assertEqual(cfg.scoring_map["idp_tkl_ast"], 1.0)
        self.assertEqual(cfg.scoring_map["pass_td"], 6.0)
        self.assertIn("unknown_custom_key", cfg.metadata.get("unknownSleeperKeys", {}))

    def test_compare_to_baseline_contains_changed_rule(self):
        baseline = build_default_baseline_config("b")
        league = normalize_scoring_settings({"pass_td": 5, "rec": 0.5}, ["QB", "WR"], league_id="l")
        delta = compare_to_baseline(baseline, league)
        keys = {r.key for r in delta}
        self.assertIn("pass_td", keys)
        self.assertIn("rec", keys)

    def test_ratio_to_multiplier_bounded(self):
        self.assertLessEqual(ratio_to_multiplier(10.0), 1.12)
        self.assertGreaterEqual(ratio_to_multiplier(0.01), 0.90)

    def test_player_adjustment_output(self):
        adj = build_player_scoring_adjustment(
            baseline_scoring_version="b1",
            league_scoring_version="l1",
            league_id="123",
            baseline_ppg=14.0,
            league_ppg=16.0,
            position_bucket="RB",
            archetype="receiving_rb",
            confidence=0.8,
            sample_size_score=0.7,
            projection_weight=0.2,
            data_quality_flag="ok",
            scoring_tags=["reception_sensitive"],
            rule_contributions={"receptions": 1.4},
            archetype_prior_ratio=1.05,
            value_anchor=5000,
        )
        self.assertGreater(adj.raw_scoring_ratio, 1.0)
        self.assertGreaterEqual(adj.final_scoring_multiplier, 0.90)
        self.assertLessEqual(adj.final_scoring_multiplier, 1.12)
        self.assertEqual(adj.position_bucket, "RB")

    def test_persist_scoring_delta_map(self):
        baseline = build_default_baseline_config("b")
        league = normalize_scoring_settings({"pass_td": 5}, ["QB"], league_id="l")
        rules = compare_to_baseline(baseline, league)
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "delta.json")
            persist_scoring_delta_map(
                out,
                custom_league_id="123",
                baseline_league_id="456",
                baseline_scoring_version="b1",
                league_scoring_version="l1",
                rules=rules,
            )
            self.assertTrue(os.path.exists(out))
            with open(out, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["customLeagueId"], "123")
            self.assertTrue(any(r.get("key") == "pass_td" for r in payload.get("rules", [])))


if __name__ == "__main__":
    unittest.main()
