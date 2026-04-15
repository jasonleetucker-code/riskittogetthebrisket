"""Source monitoring regression tests.

Covers the hardening pass that added per-source CSV mtimes,
row-count floors, parse-error surfacing, and partial-run cross-wiring
to contractHealth.

Run with: python3 -m pytest tests/api/test_source_monitoring.py -v
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from src.api.data_contract import (
    _DEFAULT_SOURCE_ROW_FLOORS,
    _SOURCE_CSV_PATHS,
    TOLERABLE_PARTIAL_SOURCES,
    build_api_data_contract,
    validate_api_data_contract,
)


def _load_latest_raw() -> dict[str, Any] | None:
    data_path = Path(__file__).resolve().parents[2] / "exports" / "latest"
    json_files = sorted(data_path.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        return json.load(f)


_CACHED_CONTRACT: tuple[dict[str, Any], dict[str, Any]] | None = None


def _get_live_contract() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Build the contract once and cache it for the test suite."""
    global _CACHED_CONTRACT
    if _CACHED_CONTRACT is not None:
        return _CACHED_CONTRACT
    raw = _load_latest_raw()
    if raw is None:
        return None
    contract = build_api_data_contract(raw)
    report = validate_api_data_contract(contract)
    _CACHED_CONTRACT = (contract, report)
    return _CACHED_CONTRACT


# ── sourceTimestamps ───────────────────────────────────────────────────


class TestSourceTimestamps(unittest.TestCase):
    def test_sourceTimestamps_populated_for_all_csv_sources(self):
        """Every CSV source in _SOURCE_CSV_PATHS has an entry with an ISO
        mtime or an explicit ``missing`` staleness (never an empty string)."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        ts = contract.get("dataFreshness", {}).get("sourceTimestamps")
        self.assertIsInstance(ts, dict)
        for key in _SOURCE_CSV_PATHS:
            self.assertIn(key, ts, f"missing entry: {key}")
            entry = ts[key]
            self.assertIsInstance(entry, dict)
            # mtime is either None (file missing) or a non-empty ISO string;
            # never the legacy empty-string "".
            mtime = entry.get("mtime")
            self.assertTrue(
                mtime is None or (isinstance(mtime, str) and mtime != ""),
                f"{key} mtime must be None or non-empty ISO, got: {mtime!r}",
            )
            self.assertIn("staleness", entry)
            self.assertIn("maxAgeHours", entry)

    def test_sourceTimestamps_includes_staleness_flag(self):
        """Every entry has a staleness flag and the majority of sources are
        fresh on a real live build."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        ts = contract.get("dataFreshness", {}).get("sourceTimestamps") or {}
        fresh = sum(1 for v in ts.values() if v.get("staleness") == "fresh")
        self.assertGreaterEqual(
            fresh, 3, f"At least 3/5 sources should be fresh, got {fresh}: {ts}"
        )


# ── Row-count floors ─────────────────────────────────────────────────


class TestRowCountFloors(unittest.TestCase):
    def test_per_source_row_count_floors_pass_on_live(self):
        """Every source clears its floor on the live build."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, report = result
        self.assertNotIn("errors", []) if False else None  # no-op
        # Check that no source_missing error is reported.
        for err in report.get("errors", []):
            self.assertFalse(
                err.startswith("source_missing:"),
                f"Unexpected source_missing error: {err}",
            )
        # Count non-zero canonicalSiteValues per source in the live board.
        players_array = contract.get("playersArray") or []
        counts: dict[str, int] = {k: 0 for k in _DEFAULT_SOURCE_ROW_FLOORS}
        for row in players_array:
            vals = row.get("canonicalSiteValues") or {}
            for key in counts:
                v = vals.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    counts[key] += 1
        for src, floor in _DEFAULT_SOURCE_ROW_FLOORS.items():
            self.assertGreaterEqual(
                counts[src],
                floor,
                f"{src} has {counts[src]} rows, below floor {floor}",
            )

    def test_row_count_floor_fails_on_synthetic_drop(self):
        """Dropping ktc values on a synthetic copy flips contractHealth.ok."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        synthetic = copy.deepcopy(contract)
        for row in synthetic.get("playersArray") or []:
            vals = row.get("canonicalSiteValues")
            if isinstance(vals, dict) and "ktc" in vals:
                vals["ktc"] = 0
        report = validate_api_data_contract(synthetic)
        self.assertFalse(
            report["ok"],
            f"Expected ok=False after dropping ktc, got {report['ok']} "
            f"errors={report['errors'][:5]}",
        )
        self.assertTrue(
            any(e.startswith("source_missing:ktc") for e in report["errors"]),
            f"Expected source_missing:ktc in errors, got {report['errors'][:5]}",
        )


# ── Parse errors ─────────────────────────────────────────────────────


class TestParseErrors(unittest.TestCase):
    def test_parse_errors_surfaced(self):
        """Pointing a CSV path at a missing file surfaces a parse error and
        flips contractHealth.status to degraded."""
        raw = _load_latest_raw()
        if raw is None:
            self.skipTest("No live data")

        bogus_paths = dict(_SOURCE_CSV_PATHS)
        bogus_paths["ktc"] = "exports/latest/site_raw/nonexistent-ktc.csv"
        with mock.patch(
            "src.api.data_contract._SOURCE_CSV_PATHS", bogus_paths
        ):
            contract = build_api_data_contract(raw)
        parse_errors = contract.get("sourceParseErrors")
        self.assertIsInstance(parse_errors, list)
        self.assertGreaterEqual(len(parse_errors), 1)
        self.assertTrue(
            any(pe.get("source") == "ktc" for pe in parse_errors),
            f"Expected ktc in parse_errors, got {parse_errors}",
        )
        report = validate_api_data_contract(contract)
        # Status should be degraded OR invalid (invalid if the missing CSV
        # also caused the row-count floor check to fail).
        self.assertIn(
            report["status"],
            ("degraded", "invalid"),
            f"Expected degraded/invalid status, got {report['status']}",
        )


# ── Partial run cross-wire ───────────────────────────────────────────


class TestPartialRunCrossWire(unittest.TestCase):
    def _minimal_payload_with_partial(
        self, partial_sources: list[str]
    ) -> dict[str, Any]:
        """Build a minimal payload that passes the other validators but
        carries a partial-run marker in settings.sourceRunSummary."""
        return {
            "contractVersion": "test",
            "generatedAt": "2026-04-14T00:00:00+00:00",
            "players": {},
            "playersArray": [],
            "valueAuthority": {"coverage": {}},
            "sites": [],
            "maxValues": {},
            "settings": {
                "sourceRunSummary": {
                    "overallStatus": "partial",
                    "partialRun": True,
                    "partialSources": partial_sources,
                }
            },
        }

    def test_partial_run_with_critical_source_flips_health(self):
        """A critical partial source (bare ``KTC``) flips ok to False."""
        payload = self._minimal_payload_with_partial(["KTC"])
        report = validate_api_data_contract(payload)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("partial_run_critical:KTC" in e for e in report["errors"]),
            f"Expected partial_run_critical:KTC, got {report['errors']}",
        )

    def test_partial_run_with_tolerable_source_warns_but_ok(self):
        """KTC_TradeDB / KTC_WaiverDB stay as warnings, not errors."""
        payload = self._minimal_payload_with_partial(
            ["KTC_TradeDB", "KTC_WaiverDB"]
        )
        report = validate_api_data_contract(payload)
        self.assertTrue(
            report["ok"],
            f"Tolerable partials should not flip ok. errors={report['errors']}",
        )
        tolerable_warnings = [
            w for w in report["warnings"] if "partial_run_tolerable" in w
        ]
        self.assertEqual(len(tolerable_warnings), 2)

    def test_tolerable_allowlist_covers_known_ktc_subendpoints(self):
        self.assertIn("KTC_TradeDB", TOLERABLE_PARTIAL_SOURCES)
        self.assertIn("KTC_WaiverDB", TOLERABLE_PARTIAL_SOURCES)


# ── Launch readiness still passes ────────────────────────────────────


class TestLaunchReadinessStillPasses(unittest.TestCase):
    def test_launch_readiness_gates_still_pass(self):
        """Running the existing launch readiness gates on the live build
        still succeeds after the monitoring hardening pass.  This test
        delegates to unittest's loader so individual gate failures surface
        cleanly."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")

        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName("tests.api.test_launch_readiness")
        runner = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w"))
        result_obj = runner.run(suite)
        self.assertTrue(
            result_obj.wasSuccessful(),
            f"Launch readiness failures: {result_obj.failures + result_obj.errors}",
        )


if __name__ == "__main__":
    unittest.main()
