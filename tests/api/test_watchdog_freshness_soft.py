"""Regression coverage for the soft-source freshness policy.

Pins the mitigation for the operator-hit incident: ``idpShow``
authenticates with a browser-minted cookie that lapses periodically,
and a single expiring cookie was turning every 2h scheduled-refresh
run red and opening a failure issue each cycle (#439–#447).  Soft
sources must still be *reported* (so the outage is never hidden) but
must NOT hard-fail the workflow.

Tests the pure decision core ``classify_freshness`` plus the
config-backed ``load_soft_sources`` / ``is_soft_source`` helpers, and
asserts the shipped ``config/source_staleness.json`` actually flags
``idpShow`` soft so the policy is wired end-to-end.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.watchdog_freshness import classify_freshness
from src.api.source_health_alerts import (
    is_soft_source,
    load_soft_sources,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestClassifyFreshness(unittest.TestCase):
    THRESHOLDS = {"idpShow": 24.0, "ktc": 24.0}

    def test_soft_stale_source_is_non_fatal(self):
        freshness = {"idpShow": {"ageHours": 103.0, "lastFetched": "x"}}
        hard, soft, fresh = classify_freshness(freshness, self.THRESHOLDS, {"idpShow"})
        self.assertEqual(hard, [])
        self.assertEqual([s[0] for s in soft], ["idpShow"])
        self.assertEqual(fresh, [])

    def test_non_soft_stale_source_is_fatal(self):
        freshness = {"ktc": {"ageHours": 50.0, "lastFetched": "x"}}
        hard, soft, fresh = classify_freshness(freshness, self.THRESHOLDS, {"idpShow"})
        self.assertEqual([s[0] for s in hard], ["ktc"])
        self.assertEqual(soft, [])

    def test_fresh_soft_source_is_just_fresh(self):
        freshness = {"idpShow": {"ageHours": 1.0, "lastFetched": "x"}}
        hard, soft, fresh = classify_freshness(freshness, self.THRESHOLDS, {"idpShow"})
        self.assertEqual(hard, [])
        self.assertEqual(soft, [])
        self.assertEqual([s[0] for s in fresh], ["idpShow"])

    def test_empty_soft_set_means_all_stale_is_fatal(self):
        freshness = {"idpShow": {"ageHours": 103.0, "lastFetched": "x"}}
        hard, soft, _ = classify_freshness(freshness, self.THRESHOLDS, set())
        self.assertEqual([s[0] for s in hard], ["idpShow"])
        self.assertEqual(soft, [])


class TestSoftSourceConfig(unittest.TestCase):
    def test_shipped_config_flags_idpshow_soft(self):
        soft = load_soft_sources()
        self.assertIn("idpShow", soft)

    def test_is_soft_source_exact_and_vendor_prefix(self):
        soft = {"idpShow", "fantasyPros"}
        self.assertTrue(is_soft_source("idpShow", soft))  # exact
        self.assertTrue(is_soft_source("fantasyProsSf", soft))  # prefix
        self.assertTrue(is_soft_source("fantasyProsIdp", soft))  # prefix
        self.assertFalse(is_soft_source("ktc", soft))
        # Word-boundary: a shared leading substring must not match
        # unless the next char starts a new camel segment.
        self.assertFalse(is_soft_source("idpshowlower", soft))

    def test_missing_config_yields_empty_set(self):
        self.assertEqual(
            load_soft_sources(_REPO_ROOT / "config" / "does_not_exist.json"),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
