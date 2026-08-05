"""Pin the canonical board's as-of history store.

The store exists because no output on this platform has ever been
validated for accuracy, and the obstacle is mechanical: measuring
accuracy needs to know what the board said in the past, and nothing
recorded it.

These tests pin the three properties that make the record usable later,
each of which the consensus-edge store got wrong once and had to fix:

1. a re-run must not duplicate or destroy;
2. the pipeline version must be part of the key AND must actually
   change when the maths change;
3. the write path must never touch the outcome columns.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.snapshots import board_store


def _contract(**overrides):
    base = {
        "contractVersion": "2026-03-10.v2",
        "scrapeTimestamp": "2026-08-04T18:20:36",
        "hillCurves": {"idp": {"c": 0.083, "s": 1.11}, "offense": {"c": 0.11, "s": 0.72}},
        "playersArray": [
            {
                "displayName": "Josh Allen",
                "playerId": "4984",
                "position": "QB",
                "assetClass": "offense",
                "rankDerivedValue": 9988,
                "canonicalConsensusRank": 1,
                "canonicalTierId": 1,
                "confidenceBucket": "high",
                "sourceCount": 6,
                "isSingleSource": False,
                "marketGapDirection": "aligned",
                "marketGapMagnitude": 0.4,
                "rawSourceValues": {"ktcSfTep": 9983},
            },
            {
                "displayName": "Some Unpriced Guy",
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": None,
                "sourceCount": 1,
                "isSingleSource": True,
            },
        ],
    }
    base.update(overrides)
    return base


class TestWriteBoard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "board_history.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_records_the_canonical_board_fields(self) -> None:
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            row = conn.execute(
                "SELECT display_name, player_id, rank_derived_value, "
                "canonical_consensus_rank, canonical_tier_id, confidence_bucket, "
                "source_count, is_single_source, ktc_sf_tep, scraped_at "
                "FROM board_history WHERE canonical_consensus_rank = 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            (
                "Josh Allen",
                "4984",
                9988.0,
                1,
                1,
                "high",
                6,
                0,
                9983.0,
                "2026-08-04T18:20:36",
            ),
        )

    def test_unpriced_rows_are_recorded_as_null_not_zero(self) -> None:
        """An unpriced player is a row with no value, never a row worth 0.

        Recording zero would make a future accuracy study score the
        board as having confidently called a player worthless — the same
        substitution the audit's largest defect class is about.
        """
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            value = conn.execute(
                "SELECT rank_derived_value FROM board_history WHERE display_name = ?",
                ("Some Unpriced Guy",),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIsNone(value)

    def test_rerunning_a_day_replaces_rather_than_duplicates(self) -> None:
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        cov = board_store.coverage(self.db)
        self.assertEqual(cov["rows"], 2)
        self.assertEqual(cov["dates"], 1)

    def test_a_rerun_never_clears_an_outcome_label(self) -> None:
        """The write path owns its columns and no others.

        ``INSERT OR REPLACE`` is DELETE-then-INSERT in SQLite, so it
        nulls every column absent from the insert list — which is
        exactly the ``fwd_*`` columns. Re-running an already-labelled
        day would silently unlabel it. The consensus-edge store shipped
        that defect and had to fix it; this pins that this one does not.
        """
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "UPDATE board_history SET fwd_value_7d = 123.0 WHERE display_name = 'Josh Allen'"
            )
            conn.commit()
        finally:
            conn.close()

        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)

        conn = sqlite3.connect(str(self.db))
        try:
            label = conn.execute(
                "SELECT fwd_value_7d FROM board_history WHERE display_name = 'Josh Allen'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(label, 123.0)

    def test_different_days_accumulate(self) -> None:
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        board_store.write_board(_contract(), as_of="2026-08-05", path=self.db)
        cov = board_store.coverage(self.db)
        self.assertEqual(cov["dates"], 2)
        self.assertEqual(cov["rows"], 4)
        self.assertEqual(cov["firstDate"], "2026-08-04")
        self.assertEqual(cov["lastDate"], "2026-08-05")

    def test_empty_board_is_reported_not_raised(self) -> None:
        """A recording job must never take the process down."""
        result = board_store.write_board({"playersArray": []}, path=self.db)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["written"], 0)

    def test_rows_without_a_usable_key_are_counted_not_dropped_silently(self) -> None:
        contract = _contract(playersArray=[{"position": "WR", "rankDerivedValue": 500}])
        result = board_store.write_board(contract, as_of="2026-08-04", path=self.db)
        self.assertEqual(result["written"], 0)
        self.assertTrue(result["skipped"])


class TestPipelineVersion(unittest.TestCase):
    """The version must be part of the key AND must be able to change."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "board_history.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_version_carries_the_contract_shape(self) -> None:
        self.assertTrue(board_store.pipeline_version(_contract()).startswith("2026-03-10.v2+"))

    def test_a_hill_curve_refit_is_a_different_version(self) -> None:
        """Otherwise the C6 revaluation overwrites the board it replaces.

        contractVersion alone is the API SHAPE version — a re-fit moves
        every IDP value on the board and leaves that string untouched.
        Keying on it would file the before and after as the same claim.
        """
        before = board_store.pipeline_version(_contract())
        after = board_store.pipeline_version(
            _contract(hillCurves={"idp": {"c": 0.15, "s": 1.11}, "offense": {"c": 0.11, "s": 0.72}})
        )
        self.assertNotEqual(before, after)

    def test_both_versions_of_a_day_are_kept(self) -> None:
        board_store.write_board(_contract(), as_of="2026-08-04", path=self.db)
        board_store.write_board(
            _contract(hillCurves={"idp": {"c": 0.15}}), as_of="2026-08-04", path=self.db
        )
        cov = board_store.coverage(self.db)
        self.assertEqual(cov["dates"], 1)
        self.assertEqual(cov["rows"], 4)
        self.assertEqual(len(cov["versions"]), 2)

    def test_missing_curves_degrade_rather_than_raise(self) -> None:
        self.assertTrue(board_store.pipeline_version({}).endswith("+nohash"))


class TestNotADecisionPath(unittest.TestCase):
    """The store records evidence about the board; it never feeds it.

    A value read back into the board it records would make every
    measurement taken from it circular — the exact defect V-2 records
    for the Hill-curve promotion gate, whose four "held-out" boards are
    all live blend sources. Enforced structurally rather than by
    convention.
    """

    def test_no_production_module_imports_the_store(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        allowed = {
            repo / "src" / "snapshots" / "board_store.py",
            repo / "src" / "snapshots" / "__init__.py",
            repo / "scripts" / "snapshot_board.py",
        }
        offenders = []
        for path in list((repo / "src").rglob("*.py")) + [repo / "server.py"]:
            if path in allowed:
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "snapshots.board_store" in body or "from src.snapshots" in body:
                offenders.append(str(path.relative_to(repo)))
        self.assertEqual(
            offenders,
            [],
            "the as-of store must not be read by a decision path — " f"imported by: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
