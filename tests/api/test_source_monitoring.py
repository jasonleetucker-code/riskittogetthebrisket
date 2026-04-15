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
    _DEFAULT_TOP50_COVERAGE_FLOORS,
    _PAYLOAD_SIZE_FLOOR_BYTES,
    _PICK_COUNT_FLOOR,
    _SOURCE_CSV_PATHS,
    TOLERABLE_PARTIAL_SOURCES,
    assert_payload_size_floor,
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


# ── Pick-count floor ─────────────────────────────────────────────────


class TestPickCountFloor(unittest.TestCase):
    def test_pick_count_floor_passes_on_live(self):
        """Live build has ≥100 picks (currently ~126)."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, report = result
        pa = contract.get("playersArray") or []
        pick_count = sum(
            1 for r in pa if isinstance(r, dict) and r.get("assetClass") == "pick"
        )
        self.assertGreaterEqual(
            pick_count,
            _PICK_COUNT_FLOOR,
            f"Live build should have ≥{_PICK_COUNT_FLOOR} picks, got {pick_count}",
        )
        # No pick_count_below_floor errors emitted.
        self.assertFalse(
            any(e.startswith("pick_count_below_floor:") for e in report["errors"]),
            f"Unexpected pick_count_below_floor error: {report['errors'][:5]}",
        )

    def test_pick_count_floor_fails_on_synthetic_drop(self):
        """Trimming picks below 100 flips contractHealth.ok to False."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        synthetic = copy.deepcopy(contract)
        players = synthetic.get("playersArray") or []
        # Keep only 50 picks; drop the rest.
        keep_picks = 50
        seen = 0
        new_players = []
        for r in players:
            if isinstance(r, dict) and r.get("assetClass") == "pick":
                if seen < keep_picks:
                    new_players.append(r)
                    seen += 1
                continue
            new_players.append(r)
        synthetic["playersArray"] = new_players
        report = validate_api_data_contract(synthetic)
        self.assertFalse(
            report["ok"],
            f"Expected ok=False after dropping picks, got errors={report['errors'][:5]}",
        )
        self.assertTrue(
            any(
                e.startswith("pick_count_below_floor:") for e in report["errors"]
            ),
            f"Expected pick_count_below_floor error, got {report['errors'][:5]}",
        )

    def test_missing_pickAnchors_is_error(self):
        """pickAnchors missing from the payload is an error on full builds."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        synthetic = copy.deepcopy(contract)
        synthetic.pop("pickAnchors", None)
        report = validate_api_data_contract(synthetic)
        self.assertTrue(
            any("pickAnchors" in e for e in report["errors"]),
            f"Expected pickAnchors error, got {report['errors'][:5]}",
        )


# ── Payload-size regression floor ───────────────────────────────────


class TestPayloadSizeFloor(unittest.TestCase):
    def test_payload_size_floor_passes_on_live(self):
        """Live contract serialises to ≥2MB."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, report = result
        size, ok = assert_payload_size_floor(contract)
        self.assertTrue(
            ok,
            f"Live payload below floor: {size} < {_PAYLOAD_SIZE_FLOOR_BYTES}",
        )
        # No payload_size_below_floor warning on healthy live.
        self.assertFalse(
            any(
                w.startswith("payload_size_below_floor:")
                for w in report["warnings"]
            ),
            f"Unexpected payload_size_below_floor warning: {report['warnings'][:5]}",
        )

    def test_payload_size_floor_fails_on_synthetic_shrink(self):
        """A stripped-down (but still full-size) contract trips the warning.

        The payload-size floor is gated on ``len(players_array) >= 250``
        so minimal-payload fixtures don't false-positive.  To exercise
        the floor we deep-copy the live contract, strip every heavy
        per-row field, and confirm the serialized size drops below 2MB
        while the player count is still ≥250.
        """
        import json as _json

        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        synthetic = copy.deepcopy(contract)
        # Shrink each row to its bare skeleton: drop every auxiliary
        # field (audits, source ranks, flags, canonicalSiteValues, …)
        # so the serialized payload collapses to ≪ 2MB.  Keep only the
        # 4 keys other validation blocks actually touch.
        for row in synthetic.get("playersArray") or []:
            if not isinstance(row, dict):
                continue
            row.clear()
            row["canonicalName"] = "X"
            row["displayName"] = "X"
            row["position"] = "RB"
            row["assetClass"] = "offense"
            row["values"] = {"overall": 1, "rawComposite": 1, "finalAdjusted": 1}
            row["canonicalSiteValues"] = {}
        # Purge heavy top-level blocks that would otherwise keep the
        # serialized size above the floor.
        for heavy_key in (
            "players",
            "pickAnchorsRaw",
            "coverageAudit",
            "poolAudit",
            "sleeper",
            "valueAuthority",
            "sites",
            "maxValues",
            "siteStats",
            "methodology",
            "anomalySummary",
            "validationSummary",
            "canonicalComparison",
            "dataFreshness",
        ):
            synthetic.pop(heavy_key, None)
        synthetic["players"] = {}
        synthetic["valueAuthority"] = {"coverage": {}}
        synthetic["sites"] = []
        synthetic["maxValues"] = {}
        # Sanity-check that the synthetic payload is actually below
        # the floor before running the validator.
        serialized = _json.dumps(synthetic).encode()
        self.assertLess(
            len(serialized),
            _PAYLOAD_SIZE_FLOOR_BYTES,
            f"Synthetic payload unexpectedly ≥{_PAYLOAD_SIZE_FLOOR_BYTES}: {len(serialized)}",
        )
        self.assertGreaterEqual(
            len(synthetic.get("playersArray") or []),
            250,
            "Synthetic payload needs ≥250 players so the floor block runs",
        )
        report = validate_api_data_contract(synthetic)
        warn_hits = [
            w for w in report["warnings"] if w.startswith("payload_size_below_floor:")
        ]
        self.assertEqual(
            len(warn_hits),
            1,
            f"Expected exactly one payload_size_below_floor warning, got {report['warnings'][:10]}",
        )
        self.assertIn(
            report["status"],
            ("degraded", "invalid"),
            f"Expected degraded/invalid status, got {report['status']}",
        )


# ── Top-50 per-source coverage ──────────────────────────────────────


class TestTop50Coverage(unittest.TestCase):
    def test_top50_offense_coverage_passes_on_live(self):
        """All 4 offense sources meet the top-50 offense coverage floor."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        _contract, report = result
        for src in _DEFAULT_TOP50_COVERAGE_FLOORS["offense"]:
            self.assertFalse(
                any(
                    w.startswith(f"top50_coverage_below_floor:offense:{src}:")
                    for w in report["warnings"]
                ),
                f"{src} below top-50 offense floor: {report['warnings']}",
            )

    def test_top50_idp_coverage_passes_on_live(self):
        """Both IDP sources meet the top-50 IDP coverage floor."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        _contract, report = result
        for src in _DEFAULT_TOP50_COVERAGE_FLOORS["idp"]:
            self.assertFalse(
                any(
                    w.startswith(f"top50_coverage_below_floor:idp:{src}:")
                    for w in report["warnings"]
                ),
                f"{src} below top-50 IDP floor: {report['warnings']}",
            )

    def test_top50_coverage_fails_on_synthetic_drop(self):
        """Zeroing out ktc in the top-50 offense slice trips a warning + degraded."""
        result = _get_live_contract()
        if result is None:
            self.skipTest("No live data")
        contract, _ = result
        synthetic = copy.deepcopy(contract)
        pa = synthetic.get("playersArray") or []
        # Replicate the same top-50-by-overall selection the validator uses.
        offense_rows = sorted(
            [r for r in pa if isinstance(r, dict) and r.get("assetClass") == "offense"],
            key=lambda r: -float((r.get("values") or {}).get("overall") or 0),
        )[:50]
        for r in offense_rows:
            vals = r.get("canonicalSiteValues")
            if isinstance(vals, dict) and "ktc" in vals:
                vals["ktc"] = 0
        report = validate_api_data_contract(synthetic)
        self.assertTrue(
            any(
                w.startswith("top50_coverage_below_floor:offense:ktc:")
                for w in report["warnings"]
            ),
            f"Expected top50_coverage_below_floor:offense:ktc warning, got {report['warnings'][:10]}",
        )
        self.assertIn(
            report["status"],
            ("degraded", "invalid"),
            f"Expected degraded/invalid status, got {report['status']}",
        )


# ── DLF schema probe ────────────────────────────────────────────────


class TestDlfSchemaProbe(unittest.TestCase):
    def test_dlf_schema_probe_catches_bad_header(self):
        """Pointing dlfSf at a CSV with a bogus header records a schema_mismatch."""
        import tempfile
        from src.api.data_contract import _enrich_from_source_csvs

        raw = _load_latest_raw()
        if raw is None:
            self.skipTest("No live data")

        with tempfile.TemporaryDirectory() as tmpdir:
            bogus = Path(tmpdir) / "dlf_bogus.csv"
            bogus.write_text(
                "totally,unrelated,columns\nfoo,bar,baz\n", encoding="utf-8"
            )
            # Use a relative path that resolves correctly from repo root.
            repo_root = Path(__file__).resolve().parents[2]
            try:
                rel = str(bogus.resolve().relative_to(repo_root))
            except ValueError:
                # tmpdir not under repo root — use absolute path and
                # monkey-patch the Path join by making cfg path absolute.
                rel = str(bogus.resolve())
            patched_paths = dict(_SOURCE_CSV_PATHS)
            patched_paths["dlfSf"] = {"path": rel, "signal": "rank"}
            with mock.patch(
                "src.api.data_contract._SOURCE_CSV_PATHS", patched_paths
            ):
                contract = build_api_data_contract(raw)
        parse_errors = contract.get("sourceParseErrors") or []
        schema_errors = [
            pe
            for pe in parse_errors
            if pe.get("source") == "dlfSf" and pe.get("error") == "schema_mismatch"
        ]
        self.assertGreaterEqual(
            len(schema_errors),
            1,
            f"Expected dlfSf schema_mismatch entry, got {parse_errors}",
        )


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
