import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.api.data_contract import build_api_data_contract
from src.offseason.mike_clay.integration import get_mike_clay_runtime_context


class MikeClayValueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = dict(os.environ)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

        self.normalized_rows_path = self.tmp / "mike_clay_players_normalized.json"
        rows = [
            {
                "canonical_player_id": "sleeper:4984",
                "player_name_source": "Josh Allen",
                "player_name_canonical": "Josh Allen",
                "position_canonical": "QB",
                "team_canonical": "BUF",
                "projected_games": 17,
                "projected_points": 352,
                "passing_attempts": 494,
                "rushing_attempts": 116,
                "passing_tds": 25,
                "rushing_tds": 12,
                "receiving_tds": 0,
                "targets": 0,
                "starter_projected": True,
                "starter_slot": "QB1",
                "team_projected_wins": 10.5,
                "team_strength_of_schedule_rank": 14,
                "team_offense_grade": 7.1,
                "team_offense_rank": 4,
                "team_position_grade": 10.0,
                "match_status": "exact_match",
                "match_confidence": 1.0,
                "parse_confidence": 1.0,
            },
            {
                "canonical_player_id": "sleeper:7640",
                "player_name_source": "Micah Parsons",
                "player_name_canonical": "Micah Parsons",
                "position_canonical": "DL",
                "team_canonical": "DAL",
                "projected_games": None,
                "projected_points": 210,
                "idp_snaps": 900,
                "idp_total_tackles": 74,
                "idp_sacks": 13.5,
                "idp_interceptions": 1.2,
                "idp_forced_fumbles": 2.0,
                "idp_tfl": 17.0,
                "starter_projected": True,
                "starter_slot": "ED1",
                "team_projected_wins": 10.2,
                "team_strength_of_schedule_rank": 23,
                "team_defense_grade": 4.2,
                "team_defense_rank": 4,
                "team_position_grade": 6.0,
                "match_status": "exact_match",
                "match_confidence": 0.99,
                "parse_confidence": 1.0,
            },
            {
                "canonical_player_id": "sleeper:12345",
                "player_name_source": "Risky Runner",
                "player_name_canonical": "Risky Runner",
                "position_canonical": "RB",
                "team_canonical": "MIA",
                "projected_games": 9,
                "projected_points": 170,
                "rushing_attempts": 190,
                "targets": 50,
                "rushing_tds": 5,
                "receiving_tds": 1,
                "starter_projected": False,
                "starter_slot": "RB2",
                "team_projected_wins": 2.5,
                "team_strength_of_schedule_rank": 30,
                "team_offense_grade": 3.8,
                "team_offense_rank": 29,
                "team_position_grade": 4.0,
                "match_status": "deterministic_match",
                "match_confidence": 0.92,
                "parse_confidence": 1.0,
            },
        ]
        self.normalized_rows_path.write_text(json.dumps(rows), encoding="utf-8")

        self.latest_path = self.tmp / "mike_clay_import_latest.json"
        self.latest_path.write_text(
            json.dumps(
                {
                    "status": "success",
                    "guide_year": 2026,
                    "guide_version": "3/18/2026",
                    "import_timestamp": "2026-03-19T18:41:41+00:00",
                    "run_id": "test-run",
                    "ready_for_formula_integration": True,
                    "readiness_reasons": ["all_readiness_thresholds_met"],
                    "counts": {
                        "unmatched_count": 11,
                        "ambiguous_count": 2,
                        "low_confidence_count": 5,
                    },
                    "rates": {"match_rate": 0.9},
                    "normalized_players_path": str(self.normalized_rows_path),
                }
            ),
            encoding="utf-8",
        )

        self.config_path = self.tmp / "mike_clay_integration.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "seasonWindowsByYear": {
                        "2026": {
                            "offseasonStartDate": "2026-01-15",
                            "week1StartDate": "2026-09-10",
                            "week1EndDate": "2026-09-14",
                        }
                    },
                    "weights": {"offseason": 0.25, "week1": 0.06, "postWeek1Initial": 0.02},
                    "positionDeltaCapPct": {
                        "QB": 0.08,
                        "RB": 0.12,
                        "WR": 0.11,
                        "TE": 0.10,
                        "DL": 0.10,
                        "LB": 0.09,
                        "DB": 0.08,
                    },
                }
            ),
            encoding="utf-8",
        )

        os.environ["MIKE_CLAY_IMPORT_LATEST_PATH"] = str(self.latest_path)
        os.environ["MIKE_CLAY_INTEGRATION_CONFIG"] = str(self.config_path)
        os.environ["MIKE_CLAY_ENABLED"] = "1"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)
        self.temp_dir.cleanup()

    def _build_payload(self):
        return {
            "sites": [{"key": "ktc"}, {"key": "fantasyCalc"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktc": 10000, "fantasyCalc": 10000, "idpTradeCalc": 10000},
            "players": {
                "Josh Allen": {
                    "_sleeperId": "4984",
                    "_sites": 3,
                    "_rawComposite": 7900,
                    "_scoringAdjusted": 8050,
                    "_scarcityAdjusted": 8150,
                    "_finalAdjusted": 8250,
                    "_leagueAdjusted": 8250,
                    "_canonicalSiteValues": {"ktc": 9900, "fantasyCalc": 9600, "idpTradeCalc": 9700},
                },
                "Micah Parsons": {
                    "_sleeperId": "7640",
                    "_sites": 3,
                    "_rawComposite": 4200,
                    "_scoringAdjusted": 4300,
                    "_scarcityAdjusted": 4400,
                    "_finalAdjusted": 4450,
                    "_leagueAdjusted": 4450,
                    "_canonicalSiteValues": {"ktc": 5200, "fantasyCalc": 4100, "idpTradeCalc": 5600},
                },
                "Risky Runner": {
                    "_sleeperId": "12345",
                    "_sites": 2,
                    "_rawComposite": 3600,
                    "_scoringAdjusted": 3650,
                    "_scarcityAdjusted": 3700,
                    "_finalAdjusted": 3750,
                    "_leagueAdjusted": 3750,
                    "_canonicalSiteValues": {"ktc": 4100, "fantasyCalc": 3200, "idpTradeCalc": None},
                },
            },
            "sleeper": {
                "positions": {
                    "Josh Allen": "QB",
                    "Micah Parsons": "LB",
                    "Risky Runner": "RB",
                }
            },
        }

    def test_offseason_active_behavior(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0.25"
        contract = build_api_data_contract(self._build_payload())
        rows = {r["canonicalName"]: r for r in contract["playersArray"]}
        josh = rows["Josh Allen"]
        clay_layer = josh["valueBundle"]["layers"]["offseasonClay"]
        self.assertTrue(clay_layer.get("active"))
        self.assertEqual(clay_layer.get("seasonPhase"), "offseason")
        self.assertGreater(josh["valueBundle"]["fullValue"], 0)
        self.assertNotEqual(clay_layer.get("baseValue"), clay_layer.get("value"))

    def test_post_week1_deactivation_behavior(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "in_season_inactive"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0"
        contract = build_api_data_contract(self._build_payload())
        rows = {r["canonicalName"]: r for r in contract["playersArray"]}
        josh = rows["Josh Allen"]
        clay_layer = josh["valueBundle"]["layers"]["offseasonClay"]
        self.assertFalse(clay_layer.get("active"))
        self.assertEqual(clay_layer.get("value"), clay_layer.get("baseValue"))

    def test_rankings_trade_alignment_fields(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0.25"
        contract = build_api_data_contract(self._build_payload())
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Josh Allen")
        self.assertEqual(row["values"]["overall"], row["valueBundle"]["fullValue"])
        self.assertEqual(contract["players"]["Josh Allen"]["_finalAdjusted"], row["valueBundle"]["fullValue"])
        self.assertEqual(contract["players"]["Josh Allen"]["_leagueAdjusted"], row["valueBundle"]["fullValue"])

    def test_idp_signal_path(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0.25"
        contract = build_api_data_contract(self._build_payload())
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Micah Parsons")
        clay_layer = row["valueBundle"]["layers"]["offseasonClay"]
        self.assertGreater(clay_layer["signals"]["idpProductionScore"], 0.0)
        self.assertGreater(clay_layer["signals"]["idpOpportunityScore"], 0.0)

    def test_missing_dataset_fallback(self):
        os.environ["MIKE_CLAY_IMPORT_LATEST_PATH"] = str(self.tmp / "missing_latest.json")
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0.25"
        contract = build_api_data_contract(self._build_payload())
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Josh Allen")
        clay_layer = row["valueBundle"]["layers"]["offseasonClay"]
        self.assertFalse(clay_layer["active"])
        self.assertEqual(clay_layer["source"], "offseason_clay_inactive")

    def test_stability_guardrail_caps_delta(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "1.0"
        contract = build_api_data_contract(self._build_payload())
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Josh Allen")
        clay_layer = row["valueBundle"]["layers"]["offseasonClay"]
        delta_pct = abs(float(clay_layer.get("deltaPctFromBase") or 0.0))
        self.assertLessEqual(delta_pct, 0.080001)

    def test_low_games_role_penalty_case(self):
        os.environ["MIKE_CLAY_FORCE_PHASE"] = "offseason"
        os.environ["MIKE_CLAY_FORCE_WEIGHT"] = "0.25"
        contract = build_api_data_contract(self._build_payload())
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Risky Runner")
        clay_layer = row["valueBundle"]["layers"]["offseasonClay"]
        self.assertLessEqual(float(clay_layer.get("signals", {}).get("durabilityGamesScore", 1.0)), 0.5)
        self.assertLessEqual(float(clay_layer.get("deltaPctFromBase") or 0.0), 0.0)

    def test_explicit_window_in_season_disables_overlay(self):
        runtime = get_mike_clay_runtime_context(now_utc=datetime(2026, 9, 11, tzinfo=timezone.utc))
        self.assertTrue(runtime.get("seasonalGatingConfigured"))
        self.assertFalse(runtime.get("seasonalGatingActive"))
        self.assertFalse(runtime.get("active"))
        self.assertEqual(runtime.get("seasonPhase"), "week1_inactive")
        self.assertEqual(runtime.get("seasonalGatingReason"), "outside_active_window:week1_inactive")

    def test_explicit_window_boundary_dates(self):
        at_start = get_mike_clay_runtime_context(now_utc=datetime(2026, 1, 15, tzinfo=timezone.utc))
        self.assertEqual(at_start.get("seasonPhase"), "offseason")
        self.assertTrue(at_start.get("seasonalGatingActive"))

        at_cutover = get_mike_clay_runtime_context(now_utc=datetime(2026, 9, 10, tzinfo=timezone.utc))
        self.assertEqual(at_cutover.get("seasonPhase"), "week1_inactive")
        self.assertFalse(at_cutover.get("seasonalGatingActive"))
        self.assertFalse(at_cutover.get("active"))

    def test_missing_window_config_fails_safe(self):
        missing_cfg = self.tmp / "missing_mike_clay_config.json"
        os.environ["MIKE_CLAY_INTEGRATION_CONFIG"] = str(missing_cfg)
        runtime = get_mike_clay_runtime_context(now_utc=datetime(2026, 3, 20, tzinfo=timezone.utc))
        self.assertFalse(runtime.get("seasonalGatingConfigured"))
        self.assertFalse(runtime.get("seasonalGatingActive"))
        self.assertFalse(runtime.get("active"))
        self.assertEqual(runtime.get("seasonPhase"), "season_window_invalid")
        self.assertEqual(runtime.get("seasonalGatingReason"), "season_window_invalid")
        self.assertTrue(runtime.get("seasonalGatingErrors"))

    def test_malformed_window_config_fails_safe(self):
        bad_config_path = self.tmp / "mike_clay_bad_window_config.json"
        bad_config_path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "seasonWindowsByYear": {
                        "2026": {
                            "offseasonStartDate": "bad-date",
                            "week1StartDate": "2026-09-10",
                            "week1EndDate": "2026-09-09",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.environ["MIKE_CLAY_INTEGRATION_CONFIG"] = str(bad_config_path)
        runtime = get_mike_clay_runtime_context(now_utc=datetime(2026, 3, 20, tzinfo=timezone.utc))
        self.assertFalse(runtime.get("seasonalGatingConfigured"))
        self.assertEqual(runtime.get("seasonPhase"), "season_window_invalid")
        self.assertFalse(runtime.get("active"))
        errors = list(runtime.get("seasonalGatingErrors") or [])
        self.assertTrue(any("offseasonStartDate must be YYYY-MM-DD" in e for e in errors))
        self.assertTrue(any("week1EndDate must be on/after week1StartDate" in e for e in errors))

    def test_offseason_status_exposes_effective_gate_truth(self):
        contract = build_api_data_contract(self._build_payload())
        status = contract.get("offseasonClayStatus") or {}
        self.assertIn("enabled", status)
        self.assertIn("importDataReady", status)
        self.assertIn("seasonalGatingActive", status)
        self.assertIn("seasonalGatingConfigured", status)
        self.assertIn("seasonalGatingReason", status)
        self.assertIn("cutoverWindow", status)
        cutover = status.get("cutoverWindow") or {}
        self.assertEqual(cutover.get("policy"), "explicit_yearly_window")
        self.assertEqual(cutover.get("guideYear"), 2026)


if __name__ == "__main__":
    unittest.main()
