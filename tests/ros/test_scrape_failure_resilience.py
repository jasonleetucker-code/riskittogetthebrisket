"""Failure-resilience tests for the orchestrator.

When an adapter crashes or returns failed status, the orchestrator
MUST keep yesterday's CSV on disk so the aggregate continues to use
the last-known-good values.  A bad scrape never erases data.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ros import scrape
from src.ros.scrape import _csv_path, _has_valid_cache, _write_csv


class TestScrapeResilience(unittest.TestCase):
    def setUp(self):
        # Scratch CSV under a per-test temp ROS root.  This used to be
        # written into the REAL ``data/ros/sources/`` (a tracked directory)
        # and deleted in tearDown -- a crash between the two left it there,
        # and the suite had no business writing that tree at all.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(scrape, "ROS_DATA_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._test_key = "_isolation_test_source"
        self._csv = _csv_path(self._test_key)

    def test_existing_csv_preserved_when_adapter_returns_no_rows(self):
        # Seed yesterday's CSV.
        seed_rows = [
            {
                "canonicalName": "Josh Allen",
                "sourceName": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "rank": 1,
                "total_ranked": 100,
                "projection": "",
            }
        ]
        written = _write_csv(self._test_key, seed_rows)
        self.assertEqual(written, 1)
        self.assertTrue(self._csv.exists())

        # Adapter returns no rows — _write_csv should NOT touch the file.
        keep_count = _write_csv(self._test_key, [])
        self.assertEqual(keep_count, 0)
        self.assertTrue(self._csv.exists(), "CSV must persist after empty-rows write")
        # Confirm contents intact.
        with self._csv.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonicalName"], "Josh Allen")

    def test_has_valid_cache_reports_correct_state(self):
        self.assertFalse(_has_valid_cache(self._test_key))
        _write_csv(
            self._test_key,
            [
                {
                    "canonicalName": "Test Player",
                    "sourceName": "Test Player",
                    "position": "QB",
                    "team": "??",
                    "rank": 1,
                    "total_ranked": 1,
                    "projection": "",
                }
            ],
        )
        self.assertTrue(_has_valid_cache(self._test_key))


if __name__ == "__main__":
    unittest.main()
