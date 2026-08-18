"""C1-ID-01 CI gate: the canonical owner is the ONLY player-identity decider.

Before the cutover this file asserted that the legacy inline CSV-join
cascade and the canonical engine's transcription agreed on every
decision.  That gate passed — 24,024 of 24,024 live decisions, plus
2,016 of 2,016 production scrape decisions over a full refresh cycle —
and the legacy cascade was then deleted.

What replaces it is the invariant the deletion bought: there is no
second decider and no fallback left that could override the owner.  A
test that only checked "the join still produces rows" would pass with a
resurrected private cascade, so the structural assertions below are the
load-bearing half.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO / "Dynasty Scraper.py"
CONTRACT_PATH = REPO / "src" / "api" / "data_contract.py"


class TestContractJoinIsOwnedByTheEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boards = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
        if not boards:
            raise unittest.SkipTest("no committed live board to build from")
        from src.api.data_contract import build_api_data_contract

        raw = json.loads(boards[0].read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):
            cls.contract = build_api_data_contract(raw)

    def test_contract_stamps_the_owner_that_decided_its_joins(self):
        summary = self.contract.get("identityJoin")
        self.assertIsInstance(summary, dict, "contract build must stamp identityJoin")
        self.assertEqual(
            summary["decidedBy"],
            "src.identity.resolution.match_row_to_source_entry",
            "the CSV join must be decided by the canonical owner",
        )
        self.assertTrue(summary["legacyCascadeRetired"])
        # NON-VACUITY, not a floor (audit 2026-08-17, §3d).
        #
        # This asserted ``decisions > 1000``.  ``decisions`` counts the
        # identity-join decisions made while building the contract, which
        # is a direct function of how many source rows the last scrape
        # produced — so a KTC-class outage collapses the population and
        # fails this test with ``src/identity/resolution.py``
        # BYTE-IDENTICAL.  In the blocking lane, under ``-x``, that
        # aborts the whole suite and blocks every open PR over a vendor
        # timeout.  It is exactly the mechanism
        # ``docs/ops/STABILIZATION_2026-08-16.md`` §3d was written for,
        # and exactly the shape already repaired in
        # ``tests/history/test_temporal_ledger.py`` and
        # ``tests/api/test_draftsharks_negative_values.py``.
        #
        # What the assertion is FOR is proving the loop below is not
        # vacuous — that the join ran at all rather than being
        # short-circuited to nothing.  ``> 0`` proves that and is
        # independent of board size.  The load-bearing assertion in this
        # test is ``decidedBy`` above: it names the owner, and no source
        # outage can change it.
        self.assertGreater(
            summary["decisions"],
            0,
            "the join made no decisions at all — did it get short-circuited?",
        )
        self.assertGreater(summary["matched"], 0, "the join matched nothing at all")

    def test_the_inline_cascade_cannot_come_back_unnoticed(self):
        """Structural: the contract module must not regain a private
        position-aware key cascade.  The engine builds those keys; a
        second builder in the row loop is the drift this unit retired."""
        text = CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "_legacy_join_key",
            text,
            "data_contract.py has regained a legacy join-key variable — the "
            "join's one owner is src/identity/resolution.match_row_to_source_entry",
        )
        self.assertIn(
            "match_row_to_source_entry(",
            text,
            "data_contract.py no longer calls the canonical join owner",
        )


class TestScraperIdentityIsOwnedByTheEngine(unittest.TestCase):
    """The scraper's run()-scope ladder is deleted, not flagged off.

    Text assertions on purpose: importing the scraper executes it.
    """

    def setUp(self):
        self.text = SCRAPER_PATH.read_text(encoding="utf-8")

    def test_the_legacy_ladder_is_gone(self):
        self.assertNotIn(
            "_resolve_sleeper_identity_legacy",
            self.text,
            "the retired legacy Sleeper-identity ladder is back in the scraper",
        )

    def test_no_cutover_flag_can_route_around_the_owner(self):
        """The flag existed only to make the dual-read window reversible.
        With the legacy path deleted there is nothing to fall back TO, so
        a surviving branch on it would be a lie about what can happen."""
        self.assertNotIn(
            "cutover_active",
            self.text,
            "the scraper still branches on the cutover flag, implying a "
            "fallback that no longer exists",
        )

    def test_identity_is_resolved_through_the_owner(self):
        self.assertIn(
            "_identity_resolution.resolve_scraper_attach_v1(",
            self.text,
            "the scraper no longer resolves identity through the canonical owner",
        )

    def test_the_scraper_defines_no_private_identity_ladder(self):
        """No local re-implementation of the candidate ladder: the
        scraper may index the directory for its own use, but the
        DECISION must come from the owner."""
        self.assertIsNone(
            re.search(r"^\s*def _pick_best_candidate\(", self.text, re.M),
            "the scraper has regained a private candidate-selection function",
        )


if __name__ == "__main__":
    unittest.main()
