"""Mike Clay guide adapter: parsing, records, shared merge policy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.bdvm import clay_projections as clay
from src.bdvm import projections as bdvm_projections
from src.bdvm.idpshow_projections import SOURCE_NAME as IDPSHOW_SOURCE
from src.bdvm.projections import ProjectionRecord, load_snapshot, write_snapshot

_norm = lambda s: s.lower()  # noqa: E731

# Real lines from the 2026 guide's team pages (pdftotext -layout),
# including the side-by-side offense+defense layout, totals rows that
# must be skipped, and a fringe all-zero offense row.
TEAM_PAGE = """
                                                                  2026 Arizona Cardinals Projections
               OFFENSE                               PASSING                    RUSHING           RECEIVING             PPR                                      DEFENSE
  Pos             Player           Gm    Att    Comp Yds TD      INT   Sk   Att Yds TD      Tgt   Rec   Yd    TD    Pts     Rk      Pos               Player              Snap  Tkl   Sack INT FF Rk
  QB          Jacoby Brissett      17    517     327 3359 15      9    40    47    210 1     0      0    0     0   200      29       DI           Walter Nolen             653  46     4.1 0.0   25
   RB         Jeremiyah Love       17     0       0    0    0     0    0    255 1129 7      86     65 489      2   279      9        DI             Roy Lopez              556  43     2.9 0.0   56
QB Total                           34    605     381 3949 18      11   46    55    242 2     0      0    0     0   236 131       DI Total                                2579 191     11.5 0.0 688
  WR         Marvin Harrison Jr.   17     0       0    0    0     0    0     0      0   0   126    69 956      5   194      33      ED             Josh Sweat              492  30     8.2 0.1   47
  WR            Jalen Brooks       17     0       0    0    0     0    0     0      0   0    0      0    0     0     0     182   ED Total                                2183 142     18.6 0.7 415
   TE          Trey McBride        17     0       0    0    0     0    0     0      0   0   155   112 1068     6   252      1       LB            Mack Wilson              963 116     1.3 1.6   25
 Total                             238   605     381 3949 18      11   46   407 1756 12     573   381 3949    18   1330 1147        CB            Will Johnson           1017   61     0.1 1.8   36
                                                                                                                                     S            Budda Baker            1017 118      1.5 1.3   5
"""

POSITIONAL_TAIL = """
                     Quarterback Projections
    Quarterback        Team    Pos Rk FF Pt   G    P Att   Comp   P Yds   P TD   INT   Sk   Carry Ru Yds Ru TD
       Josh Allen       BUF       1    369    17   509      340   3945     26     12   36    116   579    12
"""


def _many_offense_rows(n=60):
    """The usability gate needs a realistic row count."""
    return "\n".join(
        f"  WR          Filler Player{i}      17     0       0    0    0     0    0     0      0   0   30     20 300      2    60      {i}"
        for i in range(n)
    )


class TestParsing(unittest.TestCase):
    def test_team_page_rows_parse_and_totals_skip(self):
        text = TEAM_PAGE + _many_offense_rows()
        rows, report = clay.parse_clay_text(text)
        self.assertTrue(report["usable"])
        by_name = {r["name"]: r for r in rows}
        # Offense: QB with pass+rush; RB with rush+receive; WR receive-only
        qb = by_name["Jacoby Brissett"]
        self.assertEqual(qb["position"], "QB")
        self.assertEqual(qb["stats"]["passing_yards"], 3359.0)
        self.assertEqual(qb["stats"]["interceptions"], 9.0)
        self.assertEqual(qb["stats"]["carries"], 47.0)
        rb = by_name["Jeremiyah Love"]
        self.assertEqual(rb["stats"]["rushing_yards"], 1129.0)
        self.assertEqual(rb["stats"]["receptions"], 65.0)
        self.assertNotIn("passing_yards", rb["stats"])  # zeros dropped
        # Defense: combined tackles split, positions mapped
        nolen = by_name["Walter Nolen"]
        self.assertEqual(nolen["position"], "DT")
        self.assertAlmostEqual(nolen["stats"]["def_tackles_solo"], 46 * 0.62)
        self.assertAlmostEqual(nolen["stats"]["def_sacks"], 4.1)
        self.assertEqual(by_name["Josh Sweat"]["position"], "EDGE")
        self.assertEqual(by_name["Budda Baker"]["position"], "S")
        # Totals rows never become players
        self.assertNotIn("Total", by_name)
        for name in by_name:
            self.assertNotIn("Total", name)

    def test_positional_pages_are_excluded(self):
        text = TEAM_PAGE + _many_offense_rows() + POSITIONAL_TAIL
        rows, _ = clay.parse_clay_text(text)
        # Josh Allen appears only in the positional region → not parsed
        self.assertNotIn("Josh Allen", {r["name"] for r in rows})

    def test_updated_stamp_and_approximations_reported(self):
        text = "Updated:                     7/25/2026\n" + TEAM_PAGE + _many_offense_rows()
        _rows, report = clay.parse_clay_text(text)
        self.assertEqual(report["guideUpdated"], "7/25/2026")
        self.assertIn("tackle_split_solo_share_0.62", report["approximations"])
        self.assertIn("forced_fumbles_unavailable_in_extraction", report["approximations"])

    def test_thin_text_is_unusable(self):
        rows, report = clay.parse_clay_text(TEAM_PAGE)  # only a handful of rows
        self.assertFalse(report["usable"])
        self.assertEqual(rows, [])


class TestRecords(unittest.TestCase):
    def test_zero_stat_fringe_rows_are_skipped(self):
        text = TEAM_PAGE + _many_offense_rows()
        rows, _ = clay.parse_clay_text(text)
        records, _summary = clay.records_from_rows(
            rows, season=2026, as_of="2026-07-28", name_normalizer=_norm
        )
        keys = {r.player_key for r in records}
        self.assertNotIn("jalen brooks", keys)  # all-zero projection → honestly absent
        self.assertIn("jacoby brissett", keys)

    def test_records_score_under_league_rules(self):
        text = TEAM_PAGE + _many_offense_rows()
        rows, _ = clay.parse_clay_text(text)
        records, _summary = clay.records_from_rows(
            rows, season=2026, as_of="2026-07-28", name_normalizer=_norm
        )
        by_key = {r.player_key: r for r in records}
        qb = by_key["jacoby brissett"]
        league = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "rush_yd": 0.1, "rush_td": 6.0}
        fpg, native = qb.resolve_fpg(league)
        expected = (3359 * 0.04 + 15 * 4.0 + 9 * -2.0 + 210 * 0.1 + 1 * 6.0) / 17.0
        self.assertTrue(native)
        self.assertAlmostEqual(fpg, expected, places=6)
        self.assertFalse(qb.is_proxy)

    def test_two_way_player_combines_offense_and_defense(self):
        """Travis Hunter: WR row + CB row under one name → ONE record
        whose stat line is the union, scoring as the SUM — his actual
        value in an IDP league.  The record must keep the DEFENSIVE
        position: the scoring gate lets an IDP position score offense
        keys (a defender's receptions count) while a WR position would
        gate the IDP keys off."""
        rows = [
            {
                "name": "Travis Hunter",
                "position": "WR",
                "games": 17.0,
                "stats": {"targets": 100.0, "receptions": 70.0, "receiving_yards": 900.0},
            },
            {
                "name": "Travis Hunter",
                "position": "CB",
                "games": 17.0,
                "stats": {"def_tackles_solo": 30.0, "def_interceptions": 2.0},
            },
        ]
        records, summary = clay.records_from_rows(
            rows, season=2026, as_of="2026-07-28", name_normalizer=_norm
        )
        self.assertEqual(summary["twoWayCombined"], ["travis hunter"])
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.position, "CB")
        self.assertEqual(rec.stat_line["receptions"], 70.0)
        self.assertEqual(rec.stat_line["def_interceptions"], 2.0)
        league = {"rec": 1.0, "idp_int": 4.0}
        fpg, native = rec.resolve_fpg(league)
        self.assertTrue(native)
        # both halves score: (70 rec × 1.0 + 2 INT × 4.0) / 17 games
        self.assertAlmostEqual(fpg, (70.0 + 8.0) / 17.0, places=6)

    def test_same_side_name_collision_drops_both(self):
        """Byron Murphy the CB vs Byron Murphy the DT — two different
        players this source cannot tell apart.  Dropped, never
        averaged into a chimera."""
        rows = [
            {
                "name": "Byron Murphy",
                "position": "CB",
                "games": 17.0,
                "stats": {"def_tackles_solo": 40.0},
            },
            {
                "name": "Byron Murphy",
                "position": "DT",
                "games": 17.0,
                "stats": {"def_tackles_solo": 30.0, "def_sacks": 5.0},
            },
        ]
        records, summary = clay.records_from_rows(
            rows, season=2026, as_of="2026-07-28", name_normalizer=_norm
        )
        self.assertEqual(records, [])
        self.assertEqual(summary["ambiguousSameNameDropped"], ["byron murphy"])


class TestSharedMergePolicy(unittest.TestCase):
    def _rec(self, key, source, *, proxy=False, pos="LB"):
        return ProjectionRecord(
            source=source,
            player_key=key,
            position=pos,
            season=2026,
            as_of="2026-07-27",
            games=17.0,
            fpg=10.0,
            scoring_native=True,
            is_proxy=proxy,
        )

    def test_clay_supersedes_proxies_but_coexists_with_idpshow(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with mock.patch.object(bdvm_projections, "SNAPSHOT_DIR", base):
                write_snapshot(
                    [
                        self._rec("shared lb", IDPSHOW_SOURCE),
                        self._rec("shared lb", "reconstructedBaseline", proxy=True),
                        self._rec("offense wr", "reconstructedBaseline", proxy=True, pos="WR"),
                    ],
                    season=2026,
                    as_of="2026-07-27",
                )
                _path, summary = clay.merge_into_snapshot(
                    [
                        self._rec("shared lb", clay.SOURCE_NAME),
                        self._rec("offense wr", clay.SOURCE_NAME, pos="WR"),
                    ],
                    season=2026,
                    as_of="2026-07-28",
                )
                self.assertEqual(summary["proxiesSuperseded"], 2)
                latest = bdvm_projections.latest_snapshot_path(2026)
                _as_of, records = load_snapshot(latest)
                by = {(r.player_key, r.source) for r in records}
                # two-source consensus for the shared defender
                self.assertIn(("shared lb", IDPSHOW_SOURCE), by)
                self.assertIn(("shared lb", clay.SOURCE_NAME), by)
                self.assertNotIn(("shared lb", "reconstructedBaseline"), by)
                self.assertNotIn(("offense wr", "reconstructedBaseline"), by)

    def test_zero_records_refuses(self):
        with self.assertRaises(clay.ClayParseError):
            clay.merge_into_snapshot([], season=2026, as_of="2026-07-28")


if __name__ == "__main__":
    unittest.main()
