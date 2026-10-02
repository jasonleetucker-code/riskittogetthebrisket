"""Unit tests for scripts/fetch_fantasypros_idp.py.

Covers:
  * ecrData schema probe (missing / malformed JSON payloads)
  * Anchor-curve monotone construction
  * Piecewise-linear interpolation + extrapolation
  * Hill curve value formula byte match
  * End-to-end fixture build: ``--from-dir`` with tiny HTML blobs
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

from scripts import fetch_fantasypros_idp as fp


def _wrap_html(data_obj: dict) -> str:
    return "<html><body><script>var ecrData = " f"{json.dumps(data_obj)};</script></body></html>"


def _make_players(*entries: tuple[int, str, str, str]) -> list[dict]:
    """entries = (rank, name, pos_rank, pos_id)."""
    return [
        {
            "player_name": n,
            "rank_ecr": r,
            "pos_rank": pr,
            "player_position_id": pid,
            "player_team_id": "TST",
        }
        for (r, n, pr, pid) in entries
    ]


class TestExtractEcrDataSchemaProbe(unittest.TestCase):
    def test_valid_payload_returns_dict(self):
        html = _wrap_html({"players": [], "count": 0})
        out = fp._extract_ecr_data(html)
        self.assertIn("players", out)

    def test_missing_players_raises_schema_error(self):
        html = _wrap_html({"count": 0})
        with self.assertRaises(fp.FantasyProsSchemaError):
            fp._extract_ecr_data(html)

    def test_no_marker_raises_schema_error(self):
        with self.assertRaises(fp.FantasyProsSchemaError):
            fp._extract_ecr_data("<html><body>no ecrData here</body></html>")


class TestHillFormulaExact(unittest.TestCase):
    def test_hill_formula_byte_match(self):
        # These are the byte-exact values every other source uses.
        cases = {
            1: 9999,
            2: 9849,
            3: 9684,
            10: 8544,
            45: 5062,
            100: 2959,
            200: 1632,
        }
        for rank, expected in cases.items():
            self.assertEqual(
                fp._hill_curve_value(rank),
                expected,
                f"rank={rank}",
            )


class TestAnchorCurveConstruction(unittest.TestCase):
    def test_monotone_anchors_accepted(self):
        combined = {
            "A": {"rank": 1},
            "B": {"rank": 3},
            "C": {"rank": 5},
        }
        individual = [
            {"rank": 1, "name": "A"},
            {"rank": 2, "name": "B"},
            {"rank": 3, "name": "C"},
        ]
        anchors = fp._build_anchor_curve(individual, combined)
        self.assertEqual(anchors, [(1, 1), (2, 3), (3, 5)])

    def test_non_monotone_anchor_dropped(self):
        # B has combined rank 3, C has combined rank 2 — C would
        # invert the curve, so it must be dropped.
        combined = {
            "A": {"rank": 1},
            "B": {"rank": 3},
            "C": {"rank": 2},
        }
        individual = [
            {"rank": 1, "name": "A"},
            {"rank": 2, "name": "B"},
            {"rank": 3, "name": "C"},
        ]
        anchors = fp._build_anchor_curve(individual, combined)
        self.assertEqual(anchors, [(1, 1), (2, 3)])

    def test_non_overlapping_players_skipped(self):
        combined = {"A": {"rank": 1}}
        individual = [
            {"rank": 1, "name": "A"},
            {"rank": 2, "name": "Z"},  # not in combined
        ]
        anchors = fp._build_anchor_curve(individual, combined)
        self.assertEqual(anchors, [(1, 1)])


class TestInterpolation(unittest.TestCase):
    def test_exact_anchor_hit(self):
        anchors = [(1, 1), (5, 10), (10, 25)]
        self.assertEqual(fp._interpolate(5.0, anchors), 10.0)
        self.assertEqual(fp._interpolate(10.0, anchors), 25.0)

    def test_between_anchors_linear(self):
        anchors = [(1, 1), (5, 10)]
        # midpoint between (1,1) and (5,10) should be (3, 5.5)
        self.assertAlmostEqual(fp._interpolate(3.0, anchors), 5.5)

    def test_below_first_anchor_pinned(self):
        anchors = [(5, 10), (10, 25)]
        self.assertEqual(fp._interpolate(1.0, anchors), 10.0)

    def test_extrapolation_monotone_and_capped(self):
        anchors = [(1, 1), (2, 2), (3, 3)]
        # extrapolate to 100 — should be monotone and capped at 600
        y = fp._interpolate(100.0, anchors)
        self.assertGreater(y, 3)
        self.assertLessEqual(y, fp._EXTRAPOLATION_CAP)

    def test_empty_anchors_fallback(self):
        self.assertEqual(fp._interpolate(42.0, []), 42.0)


class TestBuildRowsFromFixture(unittest.TestCase):
    def test_from_dir_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Combined board: 3 players across 2 families.
            combined_html = _wrap_html(
                {
                    "players": _make_players(
                        (1, "Top DL", "DE1", "DE"),
                        (2, "Top LB", "LB1", "LB"),
                        (3, "Top S", "S1", "S"),
                    )
                }
            )
            # DL board: repeats top DL + one extension.
            dl_html = _wrap_html(
                {
                    "players": _make_players(
                        (1, "Top DL", "DE1", "DE"),
                        (2, "Ext DL", "DE2", "DE"),
                    )
                }
            )
            lb_html = _wrap_html(
                {
                    "players": _make_players(
                        (1, "Top LB", "LB1", "LB"),
                        (2, "Ext LB", "LB2", "LB"),
                    )
                }
            )
            db_html = _wrap_html(
                {
                    "players": _make_players(
                        (1, "Top S", "S1", "S"),
                        (2, "Ext S", "S2", "S"),
                    )
                }
            )
            (tmp / "combined.html").write_text(combined_html)
            (tmp / "dl.html").write_text(dl_html)
            (tmp / "lb.html").write_text(lb_html)
            (tmp / "db.html").write_text(db_html)

            dest = tmp / "out.csv"
            # Bypass row-count floors on the tiny test fixture
            # (input floors + the written-total floor added in A2).
            orig_combined = fp._FP_COMBINED_ROW_FLOOR
            orig_individual = fp._FP_INDIVIDUAL_ROW_FLOOR
            orig_written = fp._FP_WRITTEN_ROW_FLOOR
            fp._FP_COMBINED_ROW_FLOOR = 1
            fp._FP_INDIVIDUAL_ROW_FLOOR = 1
            fp._FP_WRITTEN_ROW_FLOOR = 1
            try:
                rc = fp.main(
                    [
                        "--from-dir",
                        str(tmp),
                        "--dest",
                        str(dest),
                    ]
                )
            finally:
                fp._FP_COMBINED_ROW_FLOOR = orig_combined
                fp._FP_INDIVIDUAL_ROW_FLOOR = orig_individual
                fp._FP_WRITTEN_ROW_FLOOR = orig_written
            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())
            import csv

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            names = {r["name"]: r for r in rows}
            # All 3 combined + 3 extension = 6 total rows.
            self.assertEqual(len(rows), 6)
            self.assertEqual(names["Top DL"]["derivationMethod"], "direct_combined")
            self.assertEqual(names["Ext DL"]["derivationMethod"], "anchored_from_individual")
            self.assertEqual(names["Top DL"]["family"], "DL")
            # Combined family wins for the three direct rows.
            self.assertEqual(names["Top LB"]["family"], "LB")
            self.assertEqual(names["Top S"]["family"], "DB")
            # Anchored extensions inherit their individual-page family.
            self.assertEqual(names["Ext DL"]["family"], "DL")
            self.assertEqual(names["Ext LB"]["family"], "LB")
            self.assertEqual(names["Ext S"]["family"], "DB")


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_missing_players_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bad = _wrap_html({"count": 0})  # no 'players' key
            for fname in ("combined.html", "dl.html", "lb.html", "db.html"):
                (tmp / fname).write_text(bad)
            dest = tmp / "out.csv"
            rc = fp.main(["--from-dir", str(tmp), "--dest", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())

    def test_main_exits_2_on_row_count_floor_violation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # 1 player on combined — below the 50-row floor.
            combined = _wrap_html({"players": _make_players((1, "Solo", "DE1", "DE"))})
            fam = _wrap_html({"players": _make_players((1, "Solo", "DE1", "DE"))})
            (tmp / "combined.html").write_text(combined)
            (tmp / "dl.html").write_text(fam)
            (tmp / "lb.html").write_text(fam)
            (tmp / "db.html").write_text(fam)
            dest = tmp / "out.csv"
            # Use default floors (combined=50, individual=25) so this trips.
            rc = fp.main(["--from-dir", str(tmp), "--dest", str(dest)])
            self.assertEqual(rc, 2)


# PENDING (Batch 3 Unit G review, 2026-10-01).  The duplicate is a real
# defect, but de-duplicating in the fetcher is NOT freshness-neutral, so the
# fix is deferred and these tests stay as strict xfails until it lands:
#
# * ``dataset_integrity.parse_board`` keys the second occurrence of a name as
#   ``name#2``.  Dropping those rows (15 of 299 on the 2026-09-30 board, 5%)
#   clears ``broadChange`` (minRows 5, minFraction 0.02), so the first fetch
#   after the fix would log a BROAD publication the vendor never made: it
#   resets ``lastBroadDatasetChangeAt``, raises the source's freshness weight
#   and writes a false event into its cadence/style history.  Stale would
#   read as current.  The dataset-state owner has no representation-change
#   marker to absorb a one-time parser change, and adding one would change
#   its semantics for every source.
# * Display metadata also moves: ``data_contract._select_fp_meta`` would stamp
#   the kept row's family/rank (e.g. Dallas Turner LB/89) on rows that today
#   carry DL/118, and ``sourceAudit.ambiguous`` flips to false.
#
# Recorded as ``fantasypros-idp-dual-family-duplicates`` (open) in
# ``config/sources/source_lineage.json``.  Remove the markers in the patch
# that lands the fix together with a freshness-neutral mechanism.
_PENDING_DEDUPE = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "pending: FantasyPros IDP dual-family dedupe deferred -- dropping the "
        "name#2 rows would log a false broad change and reset the freshness clock "
        "(fantasypros-idp-dual-family-duplicates)"
    ),
)


class TestOneObservationPerPlayer(unittest.TestCase):
    """Batch 3 Unit G integrity sweep (2026-10-01).

    FantasyPros lists dual-eligible edge rushers on BOTH the DL and the LB
    positional pages.  A player absent from the combined page is emitted
    once per family page with two different effective ranks -- 15 such
    duplicates on the 2026-09-30 board (16 on 2026-09-23; e.g. Dallas
    Turner: LB page -> 89, DL page -> 118).  One board should carry one
    observation per player.  The contract already serves the better
    effective rank (its highest-value pick), so the duplicate does not
    change a vote today -- see the PENDING note above for why the fix is
    deferred.
    """

    def _row(self, name, rank, pos_id):
        return {"name": name, "rank": rank, "pos_id": pos_id, "team": "TST"}

    @_PENDING_DEDUPE
    def test_dual_listed_player_emitted_once_with_best_rank(self):
        combined = [self._row(f"C{i}", i, "LB") for i in range(1, 6)]
        lb_rows = [self._row(f"C{i}", i, "LB") for i in range(1, 6)]
        lb_rows.append(self._row("Edge Guy", 6, "DE"))
        dl_rows = [
            self._row("C1", 1, "LB"),
            self._row("C5", 2, "LB"),
            self._row("Edge Guy", 9, "DE"),
        ]
        family_rows = {"LB": lb_rows, "DL": dl_rows}
        rows, _anchors = fp._build_rows(combined, family_rows)
        edge = [r for r in rows if r["name"] == "Edge Guy"]
        self.assertEqual(len(edge), 1, edge)
        by_name = {r["name"]: r for r in combined}
        best = min(
            fp._interpolate(6.0, fp._build_anchor_curve(lb_rows, by_name)),
            fp._interpolate(9.0, fp._build_anchor_curve(dl_rows, by_name)),
        )
        self.assertEqual(edge[0]["effectiveRank"], int(round(best)))

    @_PENDING_DEDUPE
    def test_no_name_appears_twice(self):
        combined = [self._row("A", 1, "LB"), self._row("B", 2, "DE")]
        family_rows = {
            "LB": [self._row("A", 1, "LB"), self._row("X", 2, "DE")],
            "DL": [self._row("B", 1, "DE"), self._row("X", 2, "DE")],
        }
        rows, _ = fp._build_rows(combined, family_rows)
        names = [r["name"] for r in rows]
        self.assertEqual(len(names), len(set(names)), names)


if __name__ == "__main__":
    unittest.main()
