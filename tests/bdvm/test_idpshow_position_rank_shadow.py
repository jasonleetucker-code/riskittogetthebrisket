"""IDP Show projections: the ``Position Rank`` layout, and the owner-gated shadow output.

Two things are pinned here.

1. PARSER.  The projections adapter required a ``Pos`` / ``Position`` column.
   The IDP Show re-published its sheets with the position carried only as a
   position-rank code (``ED1`` / ``S69`` / ``DT46``) under a ``Position Rank``
   header - the same 2026-05 rename ``scripts/fetch_idpshow.py::_parse_dataset``
   already handles for the rankings board.  A sheet like that has a name column,
   nine mapped stat columns, a points column - and NO position, so the table was
   rejected as ``not_a_projection_table`` and the stage exited 1 every week.
   The box audit of 2026-10-26 saw exactly two unmapped headers,
   ``Position Rank`` and ``Projected Total Snaps`` (the second is intentionally
   unmapped, see test_idpshow_projected_header_prefix.py).

   THE FIXTURE IS SYNTHETIC.  No capture of the live sheet is committed (the
   article is paywalled and agents do not fetch it with credentials).  Its
   headers are the verbatim ``Projected ...`` stat headers from the 2026-07-30
   production report plus ``Player`` / ``Position Rank``, and its rank codes
   follow the format documented in ``fetch_idpshow._parse_dataset``.  The
   shadow output exists precisely so the first real run can be inspected before
   anything reaches a snapshot.

2. OWNER GATE.  Real IDP Show records entering a BDVM snapshot change the values
   BDVM serves, which is the owner's decision.  With the switch OFF (default) the
   fetcher writes a shadow file and touches no snapshot; with it ON it merges as
   before.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.fetch_idpshow as rankings_fetcher
import scripts.fetch_idpshow_projections as fetcher
from src.bdvm import idpshow_projections as idp
from src.bdvm import projections as bdvm_projections
from src.bdvm.clay_projections import SOURCE_NAME as CLAY_SOURCE
from src.bdvm.idpshow_switch import MERGE_ENV_VAR, merge_into_snapshot_enabled
from src.bdvm.projections import ProjectionRecord, latest_snapshot_path, load_snapshot

# Captured before any test patches the module globals.
_REAL_SHADOW_DIR = idp.SHADOW_DIR
_REAL_SNAPSHOT_DIR = bdvm_projections.SNAPSHOT_DIR

_norm = lambda s: s.lower()  # noqa: E731

STAT_HEADERS = (
    "Projected Fantasy Points,Projected Total Snaps,Projected Solo Tackles,"
    "Projected Assists,Projected Sacks,Projected QB Hits,Projected TFL,"
    "Projected INT,Projected FR,Projected FF,Projected PD"
)

POSITION_RANK_CSV = (
    f"Player,Position Rank,Team,{STAT_HEADERS}\n"
    "Elite Backer,LB1,DET,285.5,1050,95,55,3.5,6,8,1,1,2,4\n"
    "Edge Monster,ED2,CLE,240.0,900,45,20,13.5,25,15,0,2,4,3\n"
    "Interior Guy,IDL7,NYJ,150.2,780,38,25,6,12,7,0,0,1,1\n"
    "Ball Hawk,S69,BAL,130.0,1000,70,30,0.5,1,3,4,1,1,8\n"
    "Corner Cat,CB12,KC,110.0,980,55,15,0.0,0,2,3,0,1,12\n"
    "Tackle Tom,DT46,LV,95.0,640,30,18,4,8,5,0,0,1,0\n"
    "Mystery Man,XX5,DAL,100.0,700,40,20,1,2,3,0,0,0,1\n"  # unrecognised code -> skipped
    "Number Guy,7,DAL,100.0,700,40,20,1,2,3,0,0,0,1\n"  # no letters -> skipped
    ",LB3,SEA,100.0,700,40,20,1,2,3,0,0,0,1\n"  # no name -> skipped
)

EXPECTED_POSITIONS = {
    "Elite Backer": "LB",
    "Edge Monster": "EDGE",
    "Interior Guy": "DT",
    "Ball Hawk": "S",
    "Corner Cat": "CB",
    "Tackle Tom": "DT",
}

NO_POSITION_CSV = f"Player,Team,{STAT_HEADERS}\nElite Backer,DET,285.5,1050,95,55,3.5,6,8,1,1,2,4\n"


class TestPositionRankLayout(unittest.TestCase):
    def test_sheet_with_only_a_position_rank_column_is_usable(self):
        rows, report = idp.parse_projection_csv(POSITION_RANK_CSV)
        self.assertTrue(report["usable"], report)
        self.assertEqual(report["positionSource"], "position_rank_code")
        self.assertEqual(len(report["statColumns"]), 9)
        self.assertEqual(report["rowCount"], 6)
        self.assertEqual(report["skippedRows"], 3)
        self.assertEqual({r["name"]: r["position"] for r in rows}, EXPECTED_POSITIONS)

    def test_report_names_exactly_what_stayed_unmapped(self):
        _rows, report = idp.parse_projection_csv(POSITION_RANK_CSV)
        # Position Rank is now the position source; Total Snaps is deliberately
        # not a scored category and must NOT be aliased onto tackles.
        self.assertEqual(report["unmappedColumns"], ["Projected Total Snaps"])
        self.assertIn("position_rank", report["mappedColumns"])
        self.assertEqual(report["headerColumns"][:3], ["Player", "Position Rank", "Team"])

    def test_stats_survive_the_position_rank_layout(self):
        rows, _report = idp.parse_projection_csv(POSITION_RANK_CSV)
        lb = next(r for r in rows if r["name"] == "Elite Backer")
        self.assertEqual(lb["stats"]["def_tackles_solo"], 95.0)
        self.assertEqual(lb["stats"]["def_sacks"], 3.5)
        self.assertEqual(lb["stats"]["def_pass_defended"], 4.0)
        self.assertEqual(lb["fpts"], 285.5)
        self.assertNotIn("def_tackles", lb["stats"])

    def test_header_spellings_and_code_shapes(self):
        for header in ("POSITION RANK", "Pos Rank", "Positional Rank", "position rank"):
            for code, expected in (("ED1", "EDGE"), ("lb 12", "LB"), ("DT46", "DT"), ("S-3", "S")):
                with self.subTest(header=header, code=code):
                    rows, report = idp.parse_projection_csv(
                        f"Player,{header},Solo Tackles,Sacks\nSomebody,{code},50,2\n"
                    )
                    self.assertTrue(report["usable"], report)
                    self.assertEqual(rows[0]["position"], expected)

    def test_an_explicit_position_column_wins_over_the_rank_code(self):
        rows, report = idp.parse_projection_csv(
            "Player,Pos,Position Rank,Solo Tackles,Sacks\nSomebody,LB,ED1,50,2\n"
        )
        self.assertEqual(report["positionSource"], "position_column")
        self.assertEqual(rows[0]["position"], "LB")

    def test_no_position_source_at_all_is_rejected_and_says_why(self):
        rows, report = idp.parse_projection_csv(NO_POSITION_CSV)
        self.assertEqual(rows, [])
        self.assertFalse(report["usable"])
        self.assertEqual(report["reason"], "not_a_projection_table")
        self.assertEqual(report["missingRoles"], ["position"])
        self.assertIn("Team", report["headerColumns"])  # the raw headers travel with the report

    def test_missing_roles_lists_every_absent_role(self):
        _rows, report = idp.parse_projection_csv("Question,Answer\nWho?,Unclear\n")
        self.assertEqual(report["missingRoles"], ["name", "position", "stats_or_points"])

    def test_pre_existing_layouts_are_unchanged(self):
        rows, report = idp.parse_projection_csv(
            "Player,Pos,Solo,Ast,TFL,Sacks,INT,PD,FF,FR,Pts\nBacker,LB,95,55,8,3.5,1,4,2,1,285\n"
        )
        self.assertEqual(report["positionSource"], "position_column")
        self.assertEqual(rows[0]["position"], "LB")


# The two IDP Show parsers read the SAME ``Position Rank`` code and emit different
# position vocabularies ON PURPOSE: the rankings fetcher normalises through
# ``_POS_NORM`` (ED->DE, IDL->DT, everything else as published) for the ranking
# registry, while BDVM maps to its true positions (TRUE_POSITION_MAP plus
# ED->EDGE, IDL->DT, DI->DT).  What must NOT differ is the MEANING.  So this
# test, not production code, folds both vocabularies onto three families.
_FAMILY = {
    # pass rushers and interior linemen
    "DE": "DL",
    "EDGE": "DL",
    "ED": "DL",
    "DT": "DL",
    "IDL": "DL",
    # off-ball linebackers
    "LB": "LB",
    "OLB": "LB",
    "ILB": "LB",
    "MLB": "LB",
    # defensive backs
    "S": "DB",
    "CB": "DB",
    "DB": "DB",
}

# code -> the family its leading letters name in the IDP Show's own vocabulary.
RANK_CODE_FAMILIES = {
    "ED1": "DL",
    "S69": "DB",
    "DT46": "DL",
    "IDL3": "DL",
    "CB7": "DB",
    "OLB2": "LB",
}


class TestPositionRankParityWithRankingsFetcher(unittest.TestCase):
    """``scripts/fetch_idpshow.py::_parse_dataset`` and the projections adapter parse
    the same ``Position Rank`` column.  Each carries its own copy of the rule
    (leading letters are the position, the rank digits are not), so a fix or a
    new label landing in one is silent drift in the other unless this fails."""

    def family(self, side: str, position: str, code: str) -> str:
        self.assertIn(
            position,
            _FAMILY,
            f"{side} parsed {code!r} to {position!r}, a label this test has no family for",
        )
        return _FAMILY[position]

    def rankings_position(self, code: str) -> str:
        csv_text = f"PLAYER,POSITION RANK,OVERALL\nSomebody,{code},1\n"
        rows = rankings_fetcher._parse_dataset(csv_text)
        self.assertEqual(len(rows), 1, code)
        return rows[0]["position"]

    def projections_position(self, code: str) -> str:
        csv_text = f"Player,Position Rank,Solo Tackles,Sacks\nSomebody,{code},50,2\n"
        rows, report = idp.parse_projection_csv(csv_text)
        self.assertTrue(report["usable"], report)
        self.assertEqual(report["positionSource"], "position_rank_code")
        self.assertEqual(len(rows), 1, code)
        return rows[0]["position"]

    def test_both_parsers_agree_on_what_each_code_means(self):
        for code, expected in RANK_CODE_FAMILIES.items():
            with self.subTest(code=code):
                ranking = self.family("rankings", self.rankings_position(code), code)
                projection = self.family("projections", self.projections_position(code), code)
                self.assertEqual(ranking, projection)
                self.assertEqual(projection, expected)

    def test_the_helper_and_the_csv_path_read_a_code_the_same_way(self):
        # ``_position_from_rank_code`` is what ``parse_projection_csv`` calls per row.
        for code in RANK_CODE_FAMILIES:
            with self.subTest(code=code):
                self.assertEqual(
                    idp._position_from_rank_code(code), self.projections_position(code)
                )


class TestMergeSwitch(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(merge_into_snapshot_enabled(environ={}))

    def test_truthy_values_activate(self):
        for value in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(value=value):
                self.assertTrue(merge_into_snapshot_enabled(environ={MERGE_ENV_VAR: value}))

    def test_anything_else_stays_off(self):
        for value in ("", "0", "false", "no", "off", "2", "enabled", "maybe"):
            with self.subTest(value=value):
                self.assertFalse(merge_into_snapshot_enabled(environ={MERGE_ENV_VAR: value}))

    def test_cli_flag_activates_without_the_env(self):
        self.assertTrue(merge_into_snapshot_enabled(cli_flag=True, environ={}))


class _FetcherHarness(unittest.TestCase):
    """Run ``fetch_idpshow_projections.main`` against temp BDVM + shadow dirs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.snapshot_dir = self.root / "projections"
        self.shadow_dir = self.root / "shadow"
        self.csv_path = self.root / "sheet.csv"
        self.csv_path.write_text(POSITION_RANK_CSV, encoding="utf-8")

    def seed_snapshot(self) -> Path:
        """Prior snapshot: two proxies the IDP Show would supersede, one Clay record
        for a player it also covers, and a proxy it does not cover."""
        common = {"season": 2026, "as_of": "2026-10-20", "games": 17.0}
        records = [
            ProjectionRecord(
                source="baselineProxy",
                player_key="elite backer",
                position="LB",
                fpg=9.0,
                is_proxy=True,
                **common,
            ),
            ProjectionRecord(
                source="baselineProxy",
                player_key="edge monster",
                position="EDGE",
                fpg=8.0,
                is_proxy=True,
                **common,
            ),
            ProjectionRecord(
                source="baselineProxy",
                player_key="not in sheet",
                position="LB",
                fpg=5.0,
                is_proxy=True,
                **common,
            ),
            ProjectionRecord(
                source=CLAY_SOURCE,
                player_key="elite backer",
                position="LB",
                stat_line={"def_sacks": 3.0},
                **common,
            ),
        ]
        return bdvm_projections.write_snapshot(
            records, season=2026, as_of="2026-10-20", base_dir=self.snapshot_dir
        )

    def snapshot_bytes(self) -> dict[str, bytes]:
        root = self.snapshot_dir
        if not root.exists():
            return {}
        return {
            str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
        }

    def run_main(self, *extra: str, csv_path: Path | None = None, env: dict | None = None):
        argv = [
            "fetch_idpshow_projections.py",
            "--season",
            "2026",
            "--csv",
            str(csv_path or self.csv_path),
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(idp, "SHADOW_DIR", self.shadow_dir),
            mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", self.snapshot_dir),
            mock.patch.dict(os.environ, env or {}),
            mock.patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            if MERGE_ENV_VAR not in (env or {}):
                os.environ.pop(MERGE_ENV_VAR, None)
            rc = fetcher.main()
        return rc, out.getvalue(), err.getvalue()

    def shadow_files(self, pattern: str = "idpshow_*.json") -> list[Path]:
        return sorted((self.shadow_dir / "2026").glob(pattern)) if self.shadow_dir.exists() else []


class TestShadowOutputWhileOwnerGateIsClosed(_FetcherHarness):
    def test_default_writes_a_shadow_file_and_changes_no_snapshot(self):
        self.seed_snapshot()
        before = self.snapshot_bytes()
        rc, out, _err = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("SHADOW MODE", out)
        self.assertIn("NOT merged", out)
        self.assertEqual(self.snapshot_bytes(), before, "a snapshot changed with the gate closed")
        (shadow,) = self.shadow_files()
        payload = json.loads(shadow.read_text(encoding="utf-8"))
        self.assertEqual(payload["kind"], "idpshow_projections_shadow")
        self.assertEqual(payload["mode"], "shadow")
        self.assertEqual(payload["status"], "parsed")
        self.assertEqual(payload["recordCount"], 6)
        self.assertFalse(payload["mergeSwitch"]["enabled"])
        self.assertIn("BDVM does not read", payload["notice"])
        self.assertEqual(payload["parseSummary"]["playerCount"], 6)
        self.assertTrue(all(r["source"] == idp.SOURCE_NAME for r in payload["records"]))
        self.assertTrue(all(r["isProxy"] is False for r in payload["records"]))

    def test_shadow_file_carries_a_read_only_merge_preview(self):
        self.seed_snapshot()
        self.run_main()
        (shadow,) = self.shadow_files()
        preview = json.loads(shadow.read_text(encoding="utf-8"))["mergePreview"]
        self.assertEqual(preview["priorRecords"], 4)
        self.assertEqual(preview["idpShowPlayers"], 6)
        self.assertEqual(preview["proxiesWouldSupersede"], 2)
        self.assertEqual(preview["playersAlsoCoveredByRealSource"], {CLAY_SOURCE: 1})
        self.assertEqual(preview["playersWithNoPriorRecord"], 4)

    def test_preview_with_no_prior_snapshot_says_so(self):
        self.run_main()
        (shadow,) = self.shadow_files()
        preview = json.loads(shadow.read_text(encoding="utf-8"))["mergePreview"]
        self.assertIsNone(preview["priorSnapshot"])
        self.assertEqual(preview["idpShowPlayers"], 6)
        self.assertEqual(self.snapshot_bytes(), {}, "no snapshot may be created in shadow mode")

    def test_bdvm_loader_ignores_the_shadow_file(self):
        seeded = self.seed_snapshot()
        _as_of, before = load_snapshot(seeded)
        self.run_main()
        with mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", self.snapshot_dir):
            latest = latest_snapshot_path(2026)
        self.assertEqual(latest, seeded)
        _as_of, after = load_snapshot(latest)
        self.assertEqual(after, before)
        self.assertNotIn(idp.SOURCE_NAME, {r.source for r in after})
        self.assertEqual(list(self.snapshot_dir.rglob("*idpshow*")), [])

    def test_the_real_shadow_tree_is_outside_every_loader_root(self):
        # Every BDVM reader opens projections_*.json under SNAPSHOT_DIR/<season>/.
        self.assertFalse(_REAL_SHADOW_DIR.is_relative_to(_REAL_SNAPSHOT_DIR))
        self.assertFalse(_REAL_SNAPSHOT_DIR.is_relative_to(_REAL_SHADOW_DIR))
        self.assertEqual(
            _REAL_SHADOW_DIR.parts[-4:], ("data", "bdvm", "shadow", "idpshow_projections")
        )

    def test_env_switch_merges_into_a_new_snapshot(self):
        seeded = self.seed_snapshot()
        before = self.snapshot_bytes()
        rc, out, _err = self.run_main(env={MERGE_ENV_VAR: "1"})
        self.assertEqual(rc, 0)
        self.assertNotIn("SHADOW MODE", out)
        self.assertEqual(self.shadow_files(), [])
        after = self.snapshot_bytes()
        self.assertEqual(len(after), len(before) + 1)
        key = str(seeded.relative_to(self.snapshot_dir))
        self.assertEqual(after[key], before[key], "the prior snapshot is immutable")
        with mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", self.snapshot_dir):
            _as_of, merged = load_snapshot(latest_snapshot_path(2026))
        idp_keys = {r.player_key for r in merged if r.source == idp.SOURCE_NAME}
        self.assertEqual(len(idp_keys), 6)
        proxies = {r.player_key for r in merged if r.is_proxy}
        self.assertEqual(proxies, {"not in sheet"})  # covered proxies superseded, uncovered kept

    def test_cli_flag_merges_too(self):
        rc, _out, _err = self.run_main("--merge-into-snapshot")
        self.assertEqual(rc, 0)
        self.assertEqual(self.shadow_files(), [])
        self.assertEqual(len(self.snapshot_bytes()), 1)

    def test_dry_run_writes_nothing_either_way(self):
        rc, out, _err = self.run_main("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("dry run", out)
        self.assertEqual(self.shadow_files(), [])
        self.assertEqual(self.snapshot_bytes(), {})

    def test_shadow_write_failure_is_a_hard_error_not_silence(self):
        with mock.patch.object(fetcher, "write_shadow_file", side_effect=OSError("disk full")):
            rc, _out, err = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("could not write the shadow file", err)

    def test_a_payload_that_cannot_be_encoded_is_the_same_documented_exit_2(self):
        # json.dump raises TypeError (unencodable value) or ValueError (circular
        # reference), not OSError.  Both used to escape as a traceback and an
        # undocumented exit code.
        for exc in (TypeError("not JSON serializable"), ValueError("Circular reference detected")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(fetcher, "write_shadow_file", side_effect=exc):
                    rc, _out, err = self.run_main()
                self.assertEqual(rc, 2)
                self.assertIn("could not write the shadow file", err)
                self.assertIn(str(exc), err)
        self.assertEqual(self.snapshot_bytes(), {})

    def test_an_unencodable_summary_raises_type_error_and_leaves_no_temp_file(self):
        # The realistic source of the failure above: write_shadow_file really does
        # raise TypeError, and cleans up after itself while doing it.
        with self.assertRaises(TypeError):
            idp.write_shadow_file(
                [],
                season=2026,
                as_of="2026-10-26",
                mode="shadow",
                status="parsed",
                parse_summary={"tables": {"t": object()}},
                base_dir=self.shadow_dir,
            )
        leftovers = [p for p in self.shadow_dir.rglob("*") if p.is_file()]
        self.assertEqual(leftovers, [])


class TestUnusableTableDiagnostics(_FetcherHarness):
    def setUp(self):
        super().setUp()
        self.csv_path.write_text(NO_POSITION_CSV, encoding="utf-8")

    def test_unusable_table_exits_1_names_the_missing_role_and_writes_nothing_to_a_snapshot(self):
        rc, _out, err = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("missingRoles=['position']", err)
        self.assertIn("headers=", err)
        self.assertEqual(self.snapshot_bytes(), {})

    def test_a_diagnostic_file_is_left_for_the_operator(self):
        self.run_main()
        (diag,) = self.shadow_files("idpshow_*_no_usable_table.json")
        payload = json.loads(diag.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "no_usable_table")
        self.assertEqual(payload["recordCount"], 0)
        self.assertIsNone(payload["mergePreview"])
        (table,) = payload["parseSummary"]["tables"].values()
        self.assertEqual(table["missingRoles"], ["position"])
        self.assertEqual(table["reason"], "not_a_projection_table")

    def test_a_failed_rerun_cannot_clobber_the_days_parsed_shadow(self):
        self.csv_path.write_text(POSITION_RANK_CSV, encoding="utf-8")
        self.run_main()
        (parsed,) = self.shadow_files("idpshow_????-??-??.json")
        parsed_bytes = parsed.read_bytes()
        self.csv_path.write_text(NO_POSITION_CSV, encoding="utf-8")
        self.run_main()
        self.assertEqual(parsed.read_bytes(), parsed_bytes)
        self.assertEqual(len(self.shadow_files("idpshow_*_no_usable_table.json")), 1)

    def test_diagnostic_failure_never_changes_the_exit_code(self):
        for exc in (
            OSError("read-only fs"),
            TypeError("not JSON serializable"),
            ValueError("Circular reference detected"),
        ):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(fetcher, "write_shadow_file", side_effect=exc):
                    rc, _out, err = self.run_main()
                self.assertEqual(rc, 1)
                self.assertIn("could not write parse diagnostic", err)


if __name__ == "__main__":
    unittest.main()
