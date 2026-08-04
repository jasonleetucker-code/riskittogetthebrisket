"""Persistence must actually persist, idempotently, without destroying history.

The audit found the previous implementation had no persistence at all —
no table, no writer, no INSERT — while the task list recorded the
snapshot store as complete. These tests exist so that claim is checkable
rather than asserted.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.consensus_edge import snapshot


def _board(model="ce.test.v1", params="abc123", n=3, score=50.0):
    return {
        "status": "ok",
        "modelVersion": model,
        "paramSetId": params,
        "contractScrapedAt": "2026-08-04T00:00:00",
        "inputs": {"hoursStale": 6.0},
        "players": [
            {
                "playerKey": f"Player {i}",
                "displayName": f"Player {i}",
                "position": "WR" if i % 2 else "LB",
                "assetClass": "offense" if i % 2 else "idp",
                "score": score + i,
                "label": "Buy",
                "labelReason": None,
                "qualified": True,
                "confidence": 60.0,
                "components": {"mispricing": 0.5, "sharpFlow": None, "opportunity": None},
                "componentsAbsent": ["opportunity", "sharpFlow"],
                "confidenceFactors": {"coverage": 0.33, "reliability": 1.0, "freshness": 0.9},
                "mispricing": {"pctGap": 0.2},
                "fairValue": 1200.0,
                "marketValue": 1000.0,
                "anchorKey": "ktcSfTep",
                "unpricedReason": None,
                "conflict": {"conflicted": False},
            }
            for i in range(n)
        ],
    }


class _TempDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ce.sqlite"

    def tearDown(self):
        self._tmp.cleanup()


class TestWriting(_TempDB):
    def test_a_board_is_written(self):
        result = snapshot.write_board(_board(n=5), as_of="2026-08-04", path=self.db)
        self.assertEqual(result["written"], 5)
        self.assertTrue(self.db.exists())

    def test_coverage_reports_what_was_stored(self):
        snapshot.write_board(_board(n=4), as_of="2026-08-04", path=self.db)
        cov = snapshot.coverage(self.db)
        self.assertTrue(cov["exists"])
        self.assertEqual(cov["rows"], 4)
        self.assertEqual(cov["distinctDates"], 1)
        self.assertEqual(cov["firstDate"], "2026-08-04")

    def test_coverage_on_a_missing_store_says_so(self):
        cov = snapshot.coverage(Path(self._tmp.name) / "nope.sqlite")
        self.assertFalse(cov["exists"])
        self.assertEqual(cov["snapshots"], 0)

    def test_a_board_that_did_not_build_is_not_written(self):
        result = snapshot.write_board({"status": "no_contract"}, path=self.db)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["written"], 0)


class TestIdempotency(_TempDB):
    def test_rerunning_the_same_day_does_not_duplicate(self):
        snapshot.write_board(_board(n=3), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(n=3), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["rows"], 3)

    def test_rerunning_updates_the_values(self):
        snapshot.write_board(_board(n=1, score=10.0), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(n=1, score=90.0), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 90.0)

    def test_separate_dates_accumulate(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-03", path=self.db)
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["distinctDates"], 2)


class TestHistoryIsNotRewritten(_TempDB):
    """A different model's rows are that model's record, not ours.

    Overwriting them would destroy the only evidence of what the older
    model said — which is exactly what a promotion decision needs to
    compare against.
    """

    def test_a_new_model_version_does_not_overwrite_the_old_one(self):
        snapshot.write_board(_board(model="ce.v1", score=10.0), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(model="ce.v2", score=90.0), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        versions = {r["model_version"] for r in rows}
        self.assertEqual(versions, {"ce.v1", "ce.v2"})

    def test_a_new_param_set_does_not_overwrite_the_old_one(self):
        snapshot.write_board(_board(params="p1"), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(params="p2"), as_of="2026-08-04", path=self.db)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertEqual({r["param_set_id"] for r in rows}, {"p1", "p2"})

    def test_both_versions_are_reported_in_coverage(self):
        snapshot.write_board(_board(model="ce.v1"), as_of="2026-08-04", path=self.db)
        snapshot.write_board(_board(model="ce.v2"), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["modelVersions"], ["ce.v1", "ce.v2"])


class TestOutcomeLabelling(_TempDB):
    def test_outcomes_start_unlabelled(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        self.assertEqual(snapshot.coverage(self.db)["rowsWithOutcomeLabels"], 0)

    def test_a_matured_horizon_gets_labelled(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        # market 1000 -> 1100 over 14 days = +10%
        result = snapshot.label_outcomes(
            horizon_days=14,
            prices_by_date={"2026-08-15": {"Player 0": 1100.0}},
            path=self.db,
        )
        self.assertEqual(result["updated"], 1)
        rows = snapshot.history_for_player("Player 0", path=self.db)
        self.assertAlmostEqual(rows[0]["fwd_market_14d"], 0.1, places=6)

    def test_an_unmatured_horizon_is_left_alone(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        result = snapshot.label_outcomes(horizon_days=14, prices_by_date={}, path=self.db)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(snapshot.coverage(self.db)["rowsWithOutcomeLabels"], 0)

    def test_labelling_is_idempotent(self):
        snapshot.write_board(_board(n=1), as_of="2026-08-01", path=self.db)
        prices = {"2026-08-15": {"Player 0": 1100.0}}
        snapshot.label_outcomes(horizon_days=14, prices_by_date=prices, path=self.db)
        again = snapshot.label_outcomes(horizon_days=14, prices_by_date=prices, path=self.db)
        self.assertEqual(again["updated"], 0, "an already-labelled row was relabelled")

    def test_an_unsupported_horizon_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            snapshot.label_outcomes(horizon_days=99, prices_by_date={}, path=self.db)


class TestProvenanceIsStored(_TempDB):
    def test_every_row_carries_model_and_param_versions(self):
        snapshot.write_board(_board(n=2), as_of="2026-08-04", path=self.db)
        for row in snapshot.history_for_player("Player 0", path=self.db):
            self.assertTrue(row["model_version"])
            self.assertTrue(row["param_set_id"])

    def test_input_staleness_is_recorded(self):
        # Without it a stored row cannot be reproduced: the same board on
        # the same day with staler data is a different claim.
        snapshot.write_board(_board(n=1), as_of="2026-08-04", path=self.db)
        conn = snapshot.connect(self.db)
        try:
            value = conn.execute("SELECT hours_stale FROM board_snapshots").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(value, 6.0)


class TestRealBoardRoundTrip(unittest.TestCase):
    """A real board, not a fixture, survives the round trip."""

    def test_a_real_board_can_be_written_and_read(self):
        import json
        import zipfile

        repo = Path(__file__).resolve().parents[2]
        zips = sorted((repo / "exports" / "archive").glob("dynasty_export_*.zip"))
        if not zips:
            self.skipTest("no archived payload")
        with zipfile.ZipFile(zips[-1]) as zf:
            names = [n for n in zf.namelist() if n.startswith("dynasty_data_")]
            raw = json.loads(zf.read(names[0]))

        from src.consensus_edge import service

        board = service.build_board(raw, hours_stale=service.resolve_hours_stale(raw))
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ce.sqlite"
            result = snapshot.write_board(board, as_of=date(2026, 8, 4), path=db)
            self.assertGreater(result["written"], 100)
            cov = snapshot.coverage(db)
            self.assertEqual(cov["rows"], result["written"])


if __name__ == "__main__":
    unittest.main()
