"""Unit tests for scripts/fetch_fantasypros_offense.py.

Covers:
  * ecrData schema probe (missing / malformed JSON payloads)
  * Player parsing with position filtering
  * End-to-end fixture build: ``--from-file`` with a tiny HTML blob
  * Exit-code behaviour for schema regressions and row-count floors
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import fetch_fantasypros_offense as fp


def _wrap_html(data_obj: dict) -> str:
    return (
        "<html><body><script>var ecrData = "
        f"{json.dumps(data_obj)};</script></body></html>"
    )


def _make_players(
    *entries: tuple[int, str, str, str],
) -> list[dict]:
    """entries = (rank, name, pos_id, team)."""
    return [
        {
            "player_name": n,
            "rank_ecr": r,
            "pos_rank": f"{pid}{r}",
            "player_position_id": pid,
            "player_team_id": tm,
        }
        for (r, n, pid, tm) in entries
    ]


class TestExtractEcrDataSchemaProbe(unittest.TestCase):
    def test_valid_payload_returns_dict(self):
        html = _wrap_html({"players": [], "count": 0})
        out = fp._extract_ecr_data(html)
        self.assertIn("players", out)

    def test_missing_players_raises_schema_error(self):
        html = _wrap_html({"count": 0})
        with self.assertRaises(fp.FantasyProsOffenseSchemaError):
            fp._extract_ecr_data(html)

    def test_no_marker_raises_schema_error(self):
        with self.assertRaises(fp.FantasyProsOffenseSchemaError):
            fp._extract_ecr_data("<html><body>no ecrData here</body></html>")


class TestParsePlayersPositionFilter(unittest.TestCase):
    def test_only_offense_positions_kept(self):
        data = {
            "players": _make_players(
                (1, "Patrick Mahomes", "QB", "KC"),
                (2, "Saquon Barkley", "RB", "PHI"),
                (3, "CeeDee Lamb", "WR", "DAL"),
                (4, "Travis Kelce", "TE", "KC"),
                (5, "Nick Bosa", "DE", "SF"),
                (6, "T.J. Watt", "LB", "PIT"),
                (7, "Sauce Gardner", "CB", "NYJ"),
            ),
        }
        rows = fp._parse_players(data)
        # Only QB/RB/WR/TE should pass through.
        self.assertEqual(len(rows), 4)
        positions = {r["position"] for r in rows}
        self.assertEqual(positions, {"QB", "RB", "WR", "TE"})

    def test_empty_players_returns_empty(self):
        data = {"players": []}
        self.assertEqual(fp._parse_players(data), [])

    def test_rows_sorted_by_rank(self):
        data = {
            "players": _make_players(
                (3, "Third", "WR", "DAL"),
                (1, "First", "QB", "KC"),
                (2, "Second", "RB", "PHI"),
            ),
        }
        rows = fp._parse_players(data)
        ranks = [r["rank"] for r in rows]
        self.assertEqual(ranks, [1, 2, 3])


class TestFromFileEndToEnd(unittest.TestCase):
    def test_from_file_writes_csv(self):
        players = _make_players(
            (1, "Patrick Mahomes", "QB", "KC"),
            (2, "Saquon Barkley", "RB", "PHI"),
            (3, "CeeDee Lamb", "WR", "DAL"),
            (4, "Travis Kelce", "TE", "KC"),
            (5, "Ja'Marr Chase", "WR", "CIN"),
        )
        html = _wrap_html({"players": players})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "superflex.html"
            html_path.write_text(html, encoding="utf-8")
            dest = tmp / "out.csv"

            # Lower floor for test fixture.
            orig_floor = fp._FP_ROW_COUNT_FLOOR
            fp._FP_ROW_COUNT_FLOOR = 1
            try:
                rc = fp.main(
                    ["--from-file", str(html_path), "--dest", str(dest)]
                )
            finally:
                fp._FP_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertTrue(dest.exists())

            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 5)
            names = {r["name"] for r in rows}
            self.assertIn("Patrick Mahomes", names)
            self.assertIn("Ja'Marr Chase", names)
            # Verify CSV columns.
            self.assertIn("Rank", rows[0])
            self.assertIn("position", rows[0])
            self.assertIn("team", rows[0])
            self.assertEqual(rows[0]["Rank"], "1")
            self.assertEqual(rows[0]["position"], "QB")

    def test_idp_positions_filtered_out(self):
        """IDP positions on a superflex page should be silently dropped."""
        players = _make_players(
            (1, "Patrick Mahomes", "QB", "KC"),
            (2, "Nick Bosa", "DE", "SF"),
            (3, "CeeDee Lamb", "WR", "DAL"),
        )
        html = _wrap_html({"players": players})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "superflex.html"
            html_path.write_text(html, encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = fp._FP_ROW_COUNT_FLOOR
            fp._FP_ROW_COUNT_FLOOR = 1
            try:
                rc = fp.main(
                    ["--from-file", str(html_path), "--dest", str(dest)]
                )
            finally:
                fp._FP_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(dest.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            names = {r["name"] for r in rows}
            self.assertNotIn("Nick Bosa", names)


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_missing_players_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bad_html = _wrap_html({"count": 0})  # no 'players' key
            html_path = tmp / "bad.html"
            html_path.write_text(bad_html, encoding="utf-8")
            dest = tmp / "out.csv"
            rc = fp.main(["--from-file", str(html_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())

    def test_main_exits_2_on_row_count_floor_violation(self):
        # 2 players — below the default 150-row floor.
        players = _make_players(
            (1, "Patrick Mahomes", "QB", "KC"),
            (2, "Saquon Barkley", "RB", "PHI"),
        )
        html = _wrap_html({"players": players})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "small.html"
            html_path.write_text(html, encoding="utf-8")
            dest = tmp / "out.csv"
            # Use default floor (150) so this trips.
            rc = fp.main(["--from-file", str(html_path), "--dest", str(dest)])
            self.assertEqual(rc, 2)

    def test_main_exits_1_on_no_ecr_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "empty.html"
            html_path.write_text("<html><body>nothing</body></html>", encoding="utf-8")
            dest = tmp / "out.csv"
            rc = fp.main(["--from-file", str(html_path), "--dest", str(dest)])
            # exit=2 for schema regression (ecrData marker not found)
            self.assertEqual(rc, 2)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write_csv(self):
        players = _make_players(
            (1, "Patrick Mahomes", "QB", "KC"),
            (2, "Saquon Barkley", "RB", "PHI"),
            (3, "CeeDee Lamb", "WR", "DAL"),
        )
        html = _wrap_html({"players": players})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_path = tmp / "superflex.html"
            html_path.write_text(html, encoding="utf-8")
            dest = tmp / "out.csv"

            orig_floor = fp._FP_ROW_COUNT_FLOOR
            fp._FP_ROW_COUNT_FLOOR = 1
            try:
                rc = fp.main(
                    [
                        "--from-file",
                        str(html_path),
                        "--dest",
                        str(dest),
                        "--dry-run",
                    ]
                )
            finally:
                fp._FP_ROW_COUNT_FLOOR = orig_floor

            self.assertEqual(rc, 0)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
