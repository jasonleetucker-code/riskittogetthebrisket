"""IDP Show projections adapter: parsing, merge policy, end-to-end."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.bdvm import projections as bdvm_projections
from src.bdvm import idpshow_projections as idp
from src.bdvm.params import load_param_set
from src.bdvm.projections import ProjectionRecord, load_snapshot, write_snapshot

PARAMS = load_param_set("params_v1")
_norm = lambda s: s.lower()  # noqa: E731

FULL_CSV = (
    "Player,Pos,Team,GP,Solo,Ast,TFL,Sacks,INT,PD,FF,FR,Pts\n"
    "1. Elite Backer,LB,DET,17,95,55,8,3.5,1,4,2,1,285.5\n"
    "Edge Monster,ED,CLE,16,45,20,15,13.5,0,3,4,2,240.0\n"
    "Interior Guy,IDL,NYJ,17,38,25,7,6,0,1,1,0,150.2\n"
    "Ball Hawk,S,BAL,17,70,30,3,0.5,4,8,1,1,\n"
    ",LB,XXX,17,50,30,2,1,0,1,0,0,100\n"  # no name → skipped
    "Weird Pos,XX,DAL,17,50,30,2,1,0,1,0,0,100\n"  # unmapped pos → skipped
)

COMBINED_ONLY_CSV = "PLAYER,POSITION,TACKLES,SACKS,INTS\nCombined Carl,LB,140,2.0,1\n"

POINTS_ONLY_CSV = "Player,Pos,Proj Pts\nPoints Pete,LB,250\n"

NOT_A_TABLE_CSV = "Question,Answer\nWho is the GOAT?,Unclear\n"


class TestParsing(unittest.TestCase):
    def test_full_table_parses(self):
        rows, report = idp.parse_projection_csv(FULL_CSV)
        self.assertTrue(report["usable"])
        self.assertEqual(report["rowCount"], 4)
        self.assertEqual(report["skippedRows"], 2)
        self.assertEqual(report["approximations"], [])
        by_name = {r["name"]: r for r in rows}
        lb = by_name["Elite Backer"]  # rank prefix stripped
        self.assertEqual(lb["position"], "LB")
        self.assertEqual(lb["stats"]["def_tackles_solo"], 95.0)
        self.assertEqual(lb["stats"]["def_tackle_assists"], 55.0)
        self.assertEqual(lb["stats"]["def_sacks"], 3.5)
        self.assertEqual(lb["fpts"], 285.5)
        self.assertEqual(by_name["Edge Monster"]["position"], "EDGE")  # ED house style
        self.assertEqual(by_name["Interior Guy"]["position"], "DT")  # IDL house style
        self.assertIsNone(by_name["Ball Hawk"]["fpts"])  # blank cell

    def test_combined_tackles_split_is_flagged(self):
        rows, report = idp.parse_projection_csv(COMBINED_ONLY_CSV)
        self.assertTrue(report["usable"])
        self.assertIn("tackle_split_solo_share_0.62", report["approximations"])
        carl = rows[0]
        self.assertAlmostEqual(carl["stats"]["def_tackles_solo"], 140 * 0.62)
        self.assertAlmostEqual(carl["stats"]["def_tackle_assists"], 140 * 0.38)
        # def_tackles must never survive into the stat line: the scoring
        # path reads that name as pre-2025 gamebook SOLO.
        self.assertNotIn("def_tackles", carl["stats"])

    def test_points_only_table_is_usable(self):
        rows, report = idp.parse_projection_csv(POINTS_ONLY_CSV)
        self.assertTrue(report["usable"])
        self.assertEqual(rows[0]["fpts"], 250.0)

    def test_non_projection_table_rejected(self):
        rows, report = idp.parse_projection_csv(NOT_A_TABLE_CSV)
        self.assertFalse(report["usable"])
        self.assertEqual(rows, [])

    def test_pick_best_table_combines_and_prefers_stat_rich(self):
        rows, summary = idp.pick_best_table(
            [("a", FULL_CSV), ("b", POINTS_ONLY_CSV), ("junk", NOT_A_TABLE_CSV)]
        )
        self.assertTrue(summary["usable"])
        self.assertEqual(summary["usableTableCount"], 2)
        names = {r["name"] for r in rows}
        self.assertIn("Elite Backer", names)
        self.assertIn("Points Pete", names)
        self.assertFalse(summary["tables"]["junk"]["usable"])

    def test_all_junk_is_unusable(self):
        rows, summary = idp.pick_best_table([("junk", NOT_A_TABLE_CSV)])
        self.assertFalse(summary["usable"])
        self.assertEqual(rows, [])


class TestRecordsAndScoring(unittest.TestCase):
    def test_records_score_under_league_rules(self):
        """Stat lines from the real source score under the league's exact
        IDP settings via the shared scoring path — raw-stat preferred,
        Big-3 points ignored when stats exist."""
        rows, _ = idp.parse_projection_csv(FULL_CSV)
        records = idp.records_from_rows(
            rows, season=2026, as_of="2026-07-27", name_normalizer=_norm
        )
        by_key = {r.player_key: r for r in records}
        lb = by_key["elite backer"]
        league = {
            "idp_tkl_solo": 1.33,
            "idp_tkl_ast": 0.8,
            "idp_tkl_loss": 4.25,
            "idp_sack": 2.92,
            "idp_int": 5.32,
            "idp_pass_def": 5.32,
            "idp_ff": 4.25,
            "idp_fum_rec": 3.19,
        }
        fpg, native = lb.resolve_fpg(league)
        expected_season = (
            95 * 1.33 + 55 * 0.8 + 8 * 4.25 + 3.5 * 2.92 + 1 * 5.32 + 4 * 5.32 + 2 * 4.25 + 1 * 3.19
        )
        self.assertTrue(native)
        self.assertAlmostEqual(fpg, expected_season / 17.0, places=6)
        self.assertFalse(lb.is_proxy)

    def test_points_only_record_flags_non_native_scoring(self):
        rows, _ = idp.parse_projection_csv(POINTS_ONLY_CSV)
        rec = idp.records_from_rows(rows, season=2026, as_of="2026-07-27", name_normalizer=_norm)[0]
        fpg, native = rec.resolve_fpg({"idp_tkl_solo": 1.33})
        self.assertFalse(native)  # Big-3 points ≠ this league's scoring
        self.assertAlmostEqual(fpg, 250.0 / 17.0)


class TestMergePolicy(unittest.TestCase):
    def _proxy(self, key, pos="LB"):
        return ProjectionRecord(
            source="reconstructedBaseline",
            player_key=key,
            position=pos,
            season=2026,
            as_of="2026-07-01",
            games=16.0,
            fpg=10.0,
            scoring_native=True,
            is_proxy=True,
        )

    def _real(self, key, pos="LB"):
        return ProjectionRecord(
            source=idp.SOURCE_NAME,
            player_key=key,
            position=pos,
            season=2026,
            as_of="2026-07-27",
            games=17.0,
            fpg=12.0,
            is_proxy=False,
        )

    def test_real_records_supersede_proxies_only_for_covered_players(self):
        # merge_into_snapshot delegates to the shared supersede policy,
        # which resolves SNAPSHOT_DIR at call time — patching it is the
        # only redirection needed.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", base):
                write_snapshot(
                    [self._proxy("covered lb"), self._proxy("uncovered wr", "WR")],
                    season=2026,
                    as_of="2026-07-26",
                    base_dir=base,
                )
                _path, summary = idp.merge_into_snapshot(
                    [self._real("covered lb")],
                    season=2026,
                    as_of="2026-07-27",
                )
                self.assertEqual(summary["proxiesSuperseded"], 1)
                self.assertEqual(summary["mergedRecords"], 2)
                latest = bdvm_projections.latest_snapshot_path(2026, base_dir=base)
                _as_of, records = load_snapshot(latest)
                by_key = {(r.player_key, r.source) for r in records}
                self.assertIn(("covered lb", idp.SOURCE_NAME), by_key)
                self.assertIn(("uncovered wr", "reconstructedBaseline"), by_key)
                self.assertNotIn(("covered lb", "reconstructedBaseline"), by_key)

    def test_rerun_replaces_own_prior_records(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", base):
                idp.merge_into_snapshot(
                    [self._real("guy a")], season=2026, as_of="2026-07-27", label="run1"
                )
                _p, summary = idp.merge_into_snapshot(
                    [self._real("guy b")], season=2026, as_of="2026-07-28", label="run2"
                )
                latest = bdvm_projections.latest_snapshot_path(2026, base_dir=base)
                _as_of, records = load_snapshot(latest)
                keys = {r.player_key for r in records if r.source == idp.SOURCE_NAME}
                self.assertEqual(keys, {"guy b"})  # wholesale replacement per run

    def test_zero_records_refuses_to_write(self):
        with self.assertRaises(idp.IdpShowParseError):
            idp.merge_into_snapshot([], season=2026, as_of="2026-07-27")


class TestEndToEndThroughService(unittest.TestCase):
    def test_real_idp_source_prices_a_player(self):
        """A parsed IDP Show row flows through consensus + engine and
        prices an IDP player with sourceCount 1, no proxy flag."""
        from src.bdvm.service import run_valuation

        rows, _ = idp.parse_projection_csv(FULL_CSV)
        records = idp.records_from_rows(
            rows, season=2026, as_of="2026-07-20", name_normalizer=_norm
        )
        contract = {
            "generatedAt": "x",
            "currentDraftYear": 2026,
            "sleeper": {
                "scoringSettings": {
                    "idp_tkl_solo": 1.33,
                    "idp_tkl_ast": 0.8,
                    "idp_sack": 2.92,
                    "rec": 1.0,
                },
                "rosterPositions": ["QB", "WR", "LB", "LB", "DL", "DB"] + ["BN"] * 5,
                "leagueSettings": {"num_teams": 12},
            },
            "playersArray": [
                {
                    "playerId": "sid1",
                    "canonicalName": "elite backer",
                    "displayName": "Elite Backer",
                    "position": "LB",
                    "assetClass": "idp",
                    "age": 25.0,
                    "yearsExp": 3,
                    "canonicalSiteValues": {"idpTradeCalc": 4200},
                }
            ],
        }
        from tests.bdvm.pool_depth import depth_records

        payload = run_valuation(
            contract,
            league_key="dynasty_main",
            params=PARAMS,
            # + bench depth so the LB replacement rank lands inside a
            # measured pool (tests/bdvm/pool_depth.py).
            projection_records=list(records) + depth_records(),
            snapshot_as_of="2026-07-27",
            season=2026,
        )
        self.assertEqual(payload["meta"]["counts"]["priced"], 1)
        p = payload["players"][0]
        self.assertEqual(p["projection"]["sources"], [idp.SOURCE_NAME])
        self.assertFalse(p["projection"]["anyProxy"])
        self.assertEqual(p["position"], "LB")
        self.assertGreater(p["tradeValue"]["balanced"], 0)
        self.assertEqual(p["market"]["marketSource"], "idpTradeCalc")


if __name__ == "__main__":
    unittest.main()
