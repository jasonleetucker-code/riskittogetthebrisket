"""Failure-resilience tests for the orchestrator.

When an adapter crashes or returns failed status, the orchestrator
MUST keep yesterday's CSV on disk so the aggregate continues to use
the last-known-good values.  A bad scrape never erases data.
"""
from __future__ import annotations

import csv
import importlib
import json
import unittest
from pathlib import Path

from src.ros import ROS_DATA_DIR
from src.ros.scrape import _csv_path, _has_valid_cache, _write_csv


class TestScrapeResilience(unittest.TestCase):
    def setUp(self):
        # Use a per-test-class scratch CSV so we don't disturb real
        # production scrape outputs.  Test asserts work on a known
        # source key that won't conflict with production registry.
        self._test_key = "_isolation_test_source"
        self._csv = _csv_path(self._test_key)
        # Clean any leftover from a previous run.
        if self._csv.exists():
            self._csv.unlink()

    def tearDown(self):
        if self._csv.exists():
            self._csv.unlink()

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
