import json
import tempfile
import unittest
from pathlib import Path

from src.offseason.mike_clay.matcher import (
    CanonicalPlayer,
    PlayerMatcher,
    load_manual_match_overrides,
    manual_override_for_row,
    normalize_position_code,
    normalize_team_code,
)
from src.offseason.mike_clay.pipeline import run_mike_clay_import
from src.offseason.mike_clay.pipeline import (
    _enrich_identity_review_row,
    _sort_identity_review_rows,
)
from src.offseason.mike_clay.parser import parse_mike_clay_pdf
from src.utils import normalize_player_name


class MikeClayIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        fixture_path = cls.repo_root / "tests" / "fixtures" / "mike_clay_match_cases.json"
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        cls.pdf_path = cls.repo_root / "data" / "imports" / "mike_clay" / "NFLDK2026_CS_ClayProjections2026.pdf"

    def _build_matcher(self) -> PlayerMatcher:
        players = []
        for row in self.fixture["canonicalPlayers"]:
            players.append(
                CanonicalPlayer(
                    canonical_player_id=row["canonical_player_id"],
                    canonical_name=row["canonical_name"],
                    normalized_name=normalize_player_name(row["canonical_name"]),
                    position_canonical=row["position_canonical"],
                    team_canonical=row["team_canonical"],
                    sleeper_id=row["canonical_player_id"].split(":")[-1],
                )
            )
        return PlayerMatcher(players)

    def test_team_and_position_normalization(self):
        self.assertEqual(normalize_team_code("BLT"), "BAL")
        self.assertEqual(normalize_team_code("CLV"), "CLE")
        self.assertEqual(normalize_team_code("HST"), "HOU")
        self.assertEqual(normalize_position_code("DI"), "DL")
        self.assertEqual(normalize_position_code("ED"), "DL")
        self.assertEqual(normalize_position_code("CB"), "DB")

    def test_player_matching_cases(self):
        matcher = self._build_matcher()
        for case in self.fixture["matchCases"]:
            result = matcher.match(
                player_name_source=case["name"],
                team_canonical=case["team"],
                position_canonical=case["position"],
            )
            self.assertEqual(result.match_status, case["expectedStatus"], case["name"])
            self.assertEqual(result.canonical_player_id, case["expectedId"], case["name"])

    def test_manual_override_path(self):
        matcher = self._build_matcher()
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manual_overrides.csv"
            csv_path.write_text(
                "player_name_source,team_source,position_source,canonical_player_id,match_status,match_confidence\n"
                "Completely Different,SEA,RB,sleeper:1,fuzzy_match_reviewed,0.93\n",
                encoding="utf-8",
            )
            overrides = load_manual_match_overrides(csv_path)
            override = manual_override_for_row(
                overrides,
                player_name_source="Completely Different",
                team_source="SEA",
                position_source="RB",
            )
            result = matcher.match(
                player_name_source="Completely Different",
                team_canonical="SEA",
                position_canonical="RB",
                manual_override=override,
            )
            self.assertEqual(result.match_status, "fuzzy_match_reviewed")
            self.assertEqual(result.canonical_player_id, "sleeper:1")

    def test_position_guardrail_blocks_cross_family_mismatch(self):
        players = [
            CanonicalPlayer(
                canonical_player_id="sleeper:100",
                canonical_name="Will Johnson",
                normalized_name=normalize_player_name("Will Johnson"),
                position_canonical="TE",
                team_canonical="ARI",
                sleeper_id="100",
            )
        ]
        matcher = PlayerMatcher(players)
        result = matcher.match(
            player_name_source="Will Johnson",
            team_canonical="ARI",
            position_canonical="DB",
        )
        self.assertEqual(result.match_status, "unresolved")
        self.assertIsNone(result.canonical_player_id)

    def test_position_guardrail_keeps_dl_lb_compatibility(self):
        players = [
            CanonicalPlayer(
                canonical_player_id="sleeper:101",
                canonical_name="Alex Highsmith",
                normalized_name=normalize_player_name("Alex Highsmith"),
                position_canonical="LB",
                team_canonical="PIT",
                sleeper_id="101",
            )
        ]
        matcher = PlayerMatcher(players)
        result = matcher.match(
            player_name_source="Alex Highsmith",
            team_canonical="PIT",
            position_canonical="DL",
        )
        self.assertIn(result.match_status, {"exact_match", "deterministic_match"})
        self.assertEqual(result.canonical_player_id, "sleeper:101")

    def test_identity_review_rows_sorted_by_impact(self):
        rows = [
            {
                "player_name_source": "Low Impact",
                "position_canonical": "WR",
                "projected_points": 12,
                "starter_projected": False,
                "match_status": "unresolved",
                "match_method": "no_fuzzy_candidates",
            },
            {
                "player_name_source": "High Impact",
                "position_canonical": "QB",
                "projected_points": 210,
                "starter_projected": True,
                "match_status": "unresolved",
                "match_method": "no_fuzzy_candidates",
            },
        ]
        sorted_rows = _sort_identity_review_rows(rows)
        self.assertEqual(sorted_rows[0]["player_name_source"], "High Impact")
        self.assertEqual(sorted_rows[0]["impact_tier"], "high")
        self.assertEqual(sorted_rows[0]["recommended_action"], "needs_canonical_input_or_manual_review")

    def test_identity_review_enrichment_high_risk_tie(self):
        row = {
            "player_name_source": "Risky Name",
            "position_canonical": "WR",
            "projected_points": 80,
            "starter_projected": True,
            "match_status": "unresolved",
            "match_method": "fuzzy_ratio_tie",
        }
        enriched = _enrich_identity_review_row(row)
        self.assertEqual(enriched["impact_tier"], "high")
        self.assertEqual(enriched["recommended_action"], "leave_unresolved_high_risk")

    def test_parser_known_sections(self):
        if not self.pdf_path.exists():
            self.skipTest(f"Missing Mike Clay PDF at {self.pdf_path}")
        bundle = parse_mike_clay_pdf(self.pdf_path)
        self.assertGreaterEqual(len(bundle.positional_rows), 700)
        self.assertGreaterEqual(len(bundle.team_rows), 30)
        self.assertGreaterEqual(len(bundle.sos_rows), 30)
        self.assertGreaterEqual(len(bundle.unit_grade_rows), 30)
        self.assertGreaterEqual(len(bundle.starter_rows), 900)
        positions = {normalize_position_code(r.get("position_source")) for r in bundle.positional_rows}
        for required in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
            self.assertIn(required, positions)

    def test_import_metadata_persistence_and_reuse_controls(self):
        if not self.pdf_path.exists():
            self.skipTest(f"Missing Mike Clay PDF at {self.pdf_path}")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            output_dir = data_dir / "imports" / "mike_clay"
            data_dir.mkdir(parents=True, exist_ok=True)
            # Copy current canonical universe dependency.
            latest_dynasty = sorted((self.repo_root / "data").glob("dynasty_data_*.json"), reverse=True)[0]
            (data_dir / latest_dynasty.name).write_text(latest_dynasty.read_text(encoding="utf-8"), encoding="utf-8")

            result = run_mike_clay_import(
                pdf_path=self.pdf_path,
                data_dir=data_dir,
                output_dir=output_dir,
                guide_year_hint=2027,
                write_csv=False,
            )
            self.assertEqual(result.get("guide_year"), 2027)
            self.assertIn("run_dir", result)
            summary_path = Path(result["run_dir"]) / "reports" / "import_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary.get("guide_year"), 2027)
            self.assertIn("ready_for_formula_integration", summary)
            self.assertIn("counts", summary)
            self.assertGreater(summary["counts"].get("normalized_players", 0), 0)


if __name__ == "__main__":
    unittest.main()
