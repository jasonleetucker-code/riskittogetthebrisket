"""Regression coverage for ``scripts/watchdog_contract_coverage.py``.

Pins the watchdog's purpose: a registered ranking source that is
*fresh* (CSV fetched within threshold) yet absent from the built
contract must be reported, while stale or empty-CSV sources must NOT
be (those belong to the freshness watchdog / fetcher).

This is the exact regression the operator hit: ``otcffbSf`` was
fetched and committed but covered zero players in the served board,
with no error anywhere.  These tests fail if that silent path ever
reopens.

The decision core ``evaluate_coverage`` is pure, so the tests drive
it with synthetic contracts / freshness and monkeypatch the single
filesystem touch (``_csv_nonempty``) for determinism.  ``thresholds``
is left empty so ``resolve_threshold`` returns its 24h default; an
``ageHours`` of 0 is therefore unambiguously fresh and 9999 stale.
"""
from __future__ import annotations

import unittest

from scripts import watchdog_contract_coverage as wcc

# A real key from the ranking registry — the one the operator's
# incident was about.
_KEY = "otcffbSf"


def _contract_with_coverage(key: str, n_covered: int, n_total: int = 50) -> dict:
    """Synthetic contract: ``n_covered`` rows carry ``key`` in
    ``sourceRankMeta``; the remaining rows carry an unrelated key so
    the board is non-trivial."""
    rows = []
    for i in range(n_total):
        meta = {key: {"effectiveRank": i + 1}} if i < n_covered else {"ktcSfTep": {}}
        rows.append({"sourceRankMeta": meta})
    return {"playersArray": rows}


class TestEvaluateCoverage(unittest.TestCase):
    def setUp(self):
        # Default: pretend every CSV is non-empty so the test isolates
        # the coverage dimension.  Individual tests override.
        self._orig = wcc._csv_nonempty
        wcc._csv_nonempty = lambda _k: True

    def tearDown(self):
        wcc._csv_nonempty = self._orig

    def test_fresh_source_absent_is_a_violation(self):
        contract = _contract_with_coverage(_KEY, 0)
        freshness = {_KEY: {"ageHours": 0.0}}
        violations, ok, skipped = wcc.evaluate_coverage(
            contract, freshness, {}
        )
        self.assertIn((_KEY, 0), violations)
        self.assertNotIn(_KEY, [k for k, _ in ok])

    def test_fresh_source_below_floor_is_a_violation(self):
        contract = _contract_with_coverage(_KEY, wcc._MIN_COVERAGE - 1)
        freshness = {_KEY: {"ageHours": 1.0}}
        violations, _ok, _sk = wcc.evaluate_coverage(contract, freshness, {})
        self.assertEqual(
            [v for v in violations if v[0] == _KEY],
            [(_KEY, wcc._MIN_COVERAGE - 1)],
        )

    def test_fresh_source_well_covered_is_ok(self):
        contract = _contract_with_coverage(_KEY, 40)
        freshness = {_KEY: {"ageHours": 0.0}}
        violations, ok, _sk = wcc.evaluate_coverage(contract, freshness, {})
        self.assertNotIn(_KEY, [k for k, _ in violations])
        self.assertIn((_KEY, 40), ok)

    def test_stale_absent_source_is_skipped_not_a_violation(self):
        # Stale → the freshness watchdog owns it; this guard must stay
        # silent to avoid double-reporting the same outage.
        contract = _contract_with_coverage(_KEY, 0)
        freshness = {_KEY: {"ageHours": 9999.0}}
        violations, _ok, skipped = wcc.evaluate_coverage(
            contract, freshness, {}
        )
        self.assertNotIn(_KEY, [k for k, _ in violations])
        self.assertIn(_KEY, skipped)

    def test_empty_csv_source_is_skipped_not_a_violation(self):
        # A genuinely empty CSV has nothing to land — not a coverage
        # regression.
        wcc._csv_nonempty = lambda _k: False
        contract = _contract_with_coverage(_KEY, 0)
        freshness = {_KEY: {"ageHours": 0.0}}
        violations, _ok, skipped = wcc.evaluate_coverage(
            contract, freshness, {}
        )
        self.assertNotIn(_KEY, [k for k, _ in violations])
        self.assertIn(_KEY, skipped)

    def test_unknown_source_not_in_freshness_is_skipped(self):
        # No freshness entry → can't assert it should be present.
        contract = _contract_with_coverage(_KEY, 0)
        violations, _ok, skipped = wcc.evaluate_coverage(contract, {}, {})
        self.assertEqual(violations, [])
        self.assertIn(_KEY, skipped)


class TestFindLatestExport(unittest.TestCase):
    """exports/latest must win over a repo-root snapshot even when the
    root file has a newer name — strict precedence, mirroring the
    server's lookup order (Codex PR #444 P2)."""

    def test_exports_latest_takes_strict_precedence(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            latest = root / "exports" / "latest"
            latest.mkdir(parents=True)
            # Root snapshot has a LEXICALLY-NEWER name than the
            # exports/latest artifact; a global-max picker would
            # wrongly choose it.
            (root / "dynasty_data_2999-12-31.json").write_text("{}")
            chosen_path = latest / "dynasty_data_2026-05-15.json"
            chosen_path.write_text("{}")

            orig = wcc._REPO_ROOT
            wcc._REPO_ROOT = root
            try:
                got = wcc._find_latest_export()
            finally:
                wcc._REPO_ROOT = orig
            self.assertEqual(got, chosen_path)

    def test_repo_root_fallback_when_exports_latest_empty(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "exports" / "latest").mkdir(parents=True)  # empty
            fallback = root / "dynasty_data_2026-05-15.json"
            fallback.write_text("{}")

            orig = wcc._REPO_ROOT
            wcc._REPO_ROOT = root
            try:
                got = wcc._find_latest_export()
            finally:
                wcc._REPO_ROOT = orig
            self.assertEqual(got, fallback)


if __name__ == "__main__":
    unittest.main()
