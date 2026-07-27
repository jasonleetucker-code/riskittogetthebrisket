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
    DEFAULT_SOFT_ESCALATION_HOURS,
    is_soft_source,
    load_soft_escalation_hours,
    load_soft_sources,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestClassifyFreshness(unittest.TestCase):
    THRESHOLDS = {"idpShow": 24.0, "ktc": 24.0}

    def test_soft_stale_source_is_non_fatal(self):
        # Age was 103.0 here until 2026-07-27, when soft-flagging gained
        # a 72h escalation cap — at 103h this source is now correctly
        # fatal, so the old value no longer tests what this case is
        # about.  Moved inside the soft window; escalation has its own
        # class below.
        freshness = {"idpShow": {"ageHours": 30.0, "lastFetched": "x"}}
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


class TestSoftIsADelayNotAnExemption(unittest.TestCase):
    """The 2026-07-27 fix.

    Soft-flagging was unbounded, so a source could die permanently and
    CI would never say so — a lapsed cookie and a dead vendor looked
    identical forever.  Soft now buys time, not silence.
    """

    SOFT = {"idpShow"}
    THRESHOLDS = {"idpShow": 24.0}

    def _classify(self, age, escalate=DEFAULT_SOFT_ESCALATION_HOURS):
        return classify_freshness(
            {"idpShow": {"ageHours": age, "lastFetched": "2026-07-01T00:00:00+00:00"}},
            self.THRESHOLDS,
            self.SOFT,
            escalate,
        )

    def test_within_threshold_is_fresh(self):
        hard, soft, fresh = self._classify(12.0)
        self.assertEqual([], hard)
        self.assertEqual([], soft)
        self.assertEqual(1, len(fresh))

    def test_just_past_threshold_stays_soft(self):
        """A re-mint is a chore. Do not turn the run red for it."""
        hard, soft, _ = self._classify(30.0)
        self.assertEqual([], hard)
        self.assertEqual(1, len(soft))

    def test_past_escalation_hard_fails(self):
        """Three days in, nobody is coming. Treat it as an outage."""
        hard, soft, _ = self._classify(73.0)
        self.assertEqual(1, len(hard), "soft source must escalate past the cap")
        self.assertEqual([], soft)

    def test_escalation_boundary_is_exclusive(self):
        hard, soft, _ = self._classify(DEFAULT_SOFT_ESCALATION_HOURS)
        self.assertEqual([], hard, "exactly at the cap is not yet escalated")
        self.assertEqual(1, len(soft))

    def test_non_positive_escalation_restores_unbounded_soft(self):
        """Opting out is allowed — but it must be written down."""
        hard, soft, _ = self._classify(10_000.0, escalate=0)
        self.assertEqual([], hard)
        self.assertEqual(1, len(soft))

    def test_a_hard_source_is_unaffected_by_the_cap(self):
        hard, soft, _ = classify_freshness(
            {"ktc": {"ageHours": 30.0, "lastFetched": ""}},
            {"ktc": 24.0},
            self.SOFT,
            DEFAULT_SOFT_ESCALATION_HOURS,
        )
        self.assertEqual(1, len(hard))
        self.assertEqual([], soft)


class TestEscalationConfig(unittest.TestCase):
    def test_shipped_config_sets_an_escalation_cap(self):
        hours = load_soft_escalation_hours(_REPO_ROOT / "config" / "source_staleness.json")
        self.assertGreater(hours, 0, "an unbounded soft flag means the source is unmonitored")

    def test_missing_config_falls_back_to_the_default(self):
        self.assertEqual(
            DEFAULT_SOFT_ESCALATION_HOURS,
            load_soft_escalation_hours(_REPO_ROOT / "config" / "does_not_exist.json"),
        )


if __name__ == "__main__":
    unittest.main()
