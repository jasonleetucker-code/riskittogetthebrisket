"""Regression coverage for the served-board source-coverage gate.

This is the runtime half of the silent-degraded-board defense (the
CI half is ``test_contract_coverage_watchdog``).  It pins:

* ``server._compute_served_source_coverage`` — the per-source player
  count cached at prime and exposed on ``/api/status``.
* ``evaluate_coverage_map`` parity — the live deploy-gate / health
  check feed the SERVED coverage map through the *same* decision core
  the CI watchdog uses, so the pre-merge and runtime gates can never
  disagree about what "a source is missing" means.
"""

from __future__ import annotations

import unittest

import server
from scripts.watchdog_contract_coverage import (
    _source_coverage,
    evaluate_coverage,
    evaluate_coverage_map,
)

_KEY = "otcffbSf"


class TestComputeServedSourceCoverage(unittest.TestCase):
    def test_counts_sourcerankmeta_membership(self):
        contract = {
            "playersArray": [
                {"sourceRankMeta": {_KEY: {}, "ktcSfTep": {}}},
                {"sourceRankMeta": {"ktcSfTep": {}}},
                {"no": "meta"},
            ]
        }
        self.assertEqual(
            server._compute_served_source_coverage(contract),
            {_KEY: 1, "ktcSfTep": 2},
        )

    def test_defensive_on_bad_shapes(self):
        self.assertEqual(server._compute_served_source_coverage(None), {})
        self.assertEqual(server._compute_served_source_coverage({}), {})
        self.assertEqual(server._compute_served_source_coverage({"playersArray": "nope"}), {})

    def test_degraded_board_yields_only_legacy_sources(self):
        # A 3-source legacy board: the gate must see exactly that.
        contract = {
            "playersArray": [
                {"sourceRankMeta": {"ktc": {}, "ktcSfTep": {}, "idpTradeCalc": {}}}
                for _ in range(50)
            ]
        }
        cov = server._compute_served_source_coverage(contract)
        self.assertEqual(set(cov), {"ktc", "ktcSfTep", "idpTradeCalc"})


class TestEvaluateCoverageMapParity(unittest.TestCase):
    """``evaluate_coverage_map`` must return exactly what
    ``evaluate_coverage`` returns for the same underlying coverage —
    that equivalence is what lets the runtime gate reuse the CI
    watchdog's decision core."""

    def setUp(self):
        import scripts.watchdog_contract_coverage as wcc

        self._orig = wcc._csv_nonempty
        wcc._csv_nonempty = lambda _k: True

    def tearDown(self):
        import scripts.watchdog_contract_coverage as wcc

        wcc._csv_nonempty = self._orig

    def test_map_path_equals_contract_path(self):
        contract = {"playersArray": [{"sourceRankMeta": {_KEY: {}}} for _ in range(40)]}
        freshness = {_KEY: {"ageHours": 0.0}}
        from_contract = evaluate_coverage(contract, freshness, {})
        from_map = evaluate_coverage_map(_source_coverage(contract), freshness, {})
        self.assertEqual(from_contract, from_map)

    def test_map_flags_absent_fresh_source(self):
        # Served map missing the fresh source entirely → violation.
        freshness = {_KEY: {"ageHours": 0.0}}
        violations, ok, _ = evaluate_coverage_map({}, freshness, {})
        self.assertIn((_KEY, 0), violations)
        self.assertNotIn(_KEY, [k for k, _ in ok])


if __name__ == "__main__":
    unittest.main()
