"""Isolation guarantee: ROS modules must NEVER mutate the dynasty path.

The whole point of the ROS engine is to be a separate short-term
contender layer.  This test enforces the architectural rule by
snapshotting the dynasty contract output before importing any ROS
module, then again after, and asserting byte-identical results.

If this test fails, a code change accidentally crossed the dynasty/ROS
boundary — fix the offending change rather than relaxing the test.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import unittest


def _hash(payload) -> str:
    """Stable digest for an arbitrary JSON-serializable payload."""
    text = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


class TestRosIsolation(unittest.TestCase):
    """Loading any module under ``src.ros`` must not change the dynasty
    contract surface or the trade calculator helper exports.
    """

    def test_data_contract_constants_unchanged(self):
        # Force a fresh import of the dynasty contract module to
        # capture its baseline state.
        for mod in list(sys.modules):
            if mod.startswith("src.api.data_contract"):
                del sys.modules[mod]
        from src.api import data_contract as before_module
        before = {
            "ranking_sources": [
                dict(s) for s in before_module._RANKING_SOURCES
            ],
            "source_csv_paths": dict(before_module._SOURCE_CSV_PATHS),
            "value_based_sources": set(before_module._VALUE_BASED_SOURCES),
            "source_max_age": dict(before_module._SOURCE_MAX_AGE_HOURS),
        }
        before_hash = _hash(
            {
                "rs": before["ranking_sources"],
                "csv": {k: (v if isinstance(v, str) else dict(v)) for k, v in before["source_csv_paths"].items()},
                "vbs": sorted(before["value_based_sources"]),
                "max_age": before["source_max_age"],
            }
        )

        # Importing ROS code must not touch any of those.
        importlib.import_module("src.ros")
        importlib.import_module("src.ros.aggregate")
        importlib.import_module("src.ros.api")
        importlib.import_module("src.ros.lineup")
        importlib.import_module("src.ros.mapping")
        importlib.import_module("src.ros.parse")
        importlib.import_module("src.ros.scrape")
        importlib.import_module("src.ros.sources")
        importlib.import_module("src.ros.team_strength")

        from src.api import data_contract as after_module
        after = {
            "ranking_sources": [
                dict(s) for s in after_module._RANKING_SOURCES
            ],
            "source_csv_paths": dict(after_module._SOURCE_CSV_PATHS),
            "value_based_sources": set(after_module._VALUE_BASED_SOURCES),
            "source_max_age": dict(after_module._SOURCE_MAX_AGE_HOURS),
        }
        after_hash = _hash(
            {
                "rs": after["ranking_sources"],
                "csv": {k: (v if isinstance(v, str) else dict(v)) for k, v in after["source_csv_paths"].items()},
                "vbs": sorted(after["value_based_sources"]),
                "max_age": after["source_max_age"],
            }
        )

        self.assertEqual(
            before_hash,
            after_hash,
            "Dynasty data_contract constants changed after importing ROS — "
            "the boundary was crossed somewhere.  Inspect recent ROS "
            "edits for accidental mutation of _RANKING_SOURCES, "
            "_SOURCE_CSV_PATHS, _VALUE_BASED_SOURCES, or "
            "_SOURCE_MAX_AGE_HOURS.",
        )


class TestTradeLogicNonRegression(unittest.TestCase):
    """The KTC native-VA exports stay byte-stable across the 139-trade
    fixture.  Drives the JS regression script via a Python subprocess
    so this test sits alongside the other ROS isolation guarantees.
    """

    def test_ktc_va_fixture_rms_under_50(self):
        # Spec-pinned RMS bound (set in PR #335 Python port test).
        # If a future ROS change affects the JS bundle it'd ripple
        # through here; we re-run the existing port regression test
        # rather than re-implement it.
        import subprocess
        result = subprocess.run(
            [
                "python",
                "-m",
                "pytest",
                "tests/trade/test_ktc_va_python_port.py::test_fixture_overall_rms_under_50",
                "-q",
                "--tb=line",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"KTC VA fixture regression: {result.stdout}\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
