import unittest
import tempfile
import json
import os

from src.scoring.baseline_config import build_default_baseline_config
from src.scoring.player_adjustment import (
    build_player_scoring_adjustment,
    ratio_to_multiplier,
)
from src.scoring.scoring_delta import (
    RULE_CONTRIBUTION_DETAIL_KEYS,
    bucket_rule_contributions,
    bucket_rule_contributions_detail,
    compare_to_baseline,
    persist_scoring_delta_map,
)
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


    def test_bucket_rule_contributions_detail_isolates_te_bonus(self):
        """`bucket_rule_contributions` aggregates `bonus_fd_te` and
        `rec_fd` into a single `first_downs` bucket on TE rows; the
        `_detail` variant emits each per rule key so the TE Premium
        Lab can isolate just the TE-bonus portion."""
        baseline = build_default_baseline_config("b")
        # League differs from baseline on rec_fd (default 0 → 0.5)
        # AND on bonus_fd_te (default 0 → 0.5), but NOT on
        # bonus_rec_te (the default baseline already carries 0.5;
        # we bump to 1.0 to force a non-zero delta we can read).
        league = normalize_scoring_settings(
            {
                "rec": 1.0,
                "rec_fd": 0.5,
                "bonus_rec_te": 1.0,
                "bonus_fd_te": 0.5,
            },
            ["TE"],
            league_id="l",
        )
        delta_rules = compare_to_baseline(baseline, league)
        stats = {
            "rec": 6.0,
            "rec_fd": 1.0,
            "bonus_rec_te": 6.0,  # same as rec for a TE
            "bonus_fd_te": 1.0,
        }
        agg = bucket_rule_contributions("TE", stats, delta_rules)
        # Aggregate `first_downs` pools rec_fd (1.0 × 0.5 = 0.5) +
        # bonus_fd_te (1.0 × 0.5 = 0.5) = 1.0 total.
        self.assertAlmostEqual(agg.get("first_downs", 0.0), 1.0, places=4)

        detail = bucket_rule_contributions_detail("TE", stats, delta_rules)
        # Detail keeps them separated by rule key.
        self.assertAlmostEqual(detail.get("bonus_fd_te", 0.0), 0.5, places=4)
        # bonus_rec_te delta = 1.0 - 0.5 = 0.5; stat = 6 → 6 × 0.5 = 3.0
        self.assertAlmostEqual(detail.get("bonus_rec_te", 0.0), 3.0, places=4)
        self.assertNotIn("rec_fd", detail)  # not in the detail allowlist

    def test_bucket_rule_contributions_detail_skips_irrelevant_buckets(self):
        baseline = build_default_baseline_config("b")
        league = normalize_scoring_settings(
            {"bonus_fd_te": 0.5, "bonus_rec_te": 0.5},
            ["TE"],
            league_id="l",
        )
        delta_rules = compare_to_baseline(baseline, league)
        # On a QB row, neither TE-bonus rule is relevant — should be
        # absent from the detail map.
        detail = bucket_rule_contributions_detail(
            "QB", {"bonus_fd_te": 5.0, "bonus_rec_te": 5.0}, delta_rules
        )
        self.assertEqual(detail, {})

    def test_player_adjustment_carries_detail_map(self):
        adj = build_player_scoring_adjustment(
            baseline_scoring_version="b",
            league_scoring_version="l",
            league_id="123",
            baseline_ppg=12.0,
            league_ppg=13.0,
            position_bucket="TE",
            archetype="chain_mover",
            confidence=0.7,
            sample_size_score=0.5,
            projection_weight=0.2,
            data_quality_flag="ok",
            scoring_tags=[],
            rule_contributions={"te_premium": 0.5, "first_downs": 0.5},
            rule_contributions_detail={"bonus_rec_te": 0.5, "bonus_fd_te": 0.5},
        )
        self.assertEqual(adj.rule_contributions_detail.get("bonus_fd_te"), 0.5)
        self.assertEqual(adj.rule_contributions_detail.get("bonus_rec_te"), 0.5)


if __name__ == "__main__":
    unittest.main()
