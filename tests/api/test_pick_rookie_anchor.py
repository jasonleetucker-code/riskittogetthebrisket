"""Rookie anchor pass tests.

When the slotted class's slot-specific picks are present alongside rookies, each pick
should inherit the ``rankDerivedValue`` of the corresponding merged
offense+IDP rookie (pick 1.01 <-> rookie #1, pick 1.02 <-> rookie #2,
and so on through all 72 slots in 6 rounds * 12 slots).

The pass runs inside ``_compute_unified_rankings`` after
``_reassign_pick_slot_order`` and ``_suppress_generic_pick_tiers``.
It only mutates ``rankDerivedValue`` (and stamps
``pickRookieAnchor``); the compact-ranks pass that follows re-sorts
the board by value so coherence is preserved.

Run with:  python3 -m pytest tests/api/test_pick_rookie_anchor.py -v
"""

from __future__ import annotations

import re
import unittest
from typing import Any

from src.api.data_contract import assert_ranking_coherence
from tests.archive_fixtures import has_published_slot_class, newest_complete_contract


# ── TestAnchorPassCore lives in test_pick_rookie_anchor_core.py ──
#
# The synthetic pure-logic class is in its own module; this one is the
# end-to-end check through the real contract build.
#
# It used to be a ``livedata`` module that read ``exports/latest`` and hard-coded
# the literal ``2026``.  Both were wrong: the class named in the literal was
# drafted, so five of the six tests skipped forever and checked nothing, and
# the one that ran read whatever today's scrape happened to be.  The slotted
# class is now DERIVED from the board (the class whose ``<year> Pick N.NN``
# rows are present -- the tether population) and the board is the newest
# archived scrape the contract's own source-health definition calls complete,
# taken from the phase in which a vendor publishes slot prices
# (``has_published_slot_class``).  Hard gate: a provider that does not answer
# cannot fail it.

_SLOT_NAME = re.compile(r"^(20\d{2}) Pick [1-6]\.\d{2}$")


def _slotted_year(rows: list[dict[str, Any]]) -> int | None:
    years = sorted(
        {
            int(m.group(1))
            for r in rows
            if r.get("assetClass") == "pick"
            for m in [_SLOT_NAME.match(str(r.get("canonicalName") or ""))]
            if m
        }
    )
    return years[0] if years else None


class TestAnchorEndToEnd(unittest.TestCase):
    """Verify the anchor flows end-to-end through the real contract
    build on a complete archived scrape that carries a slotted class."""

    def setUp(self) -> None:
        contract, _name = newest_complete_contract(require=has_published_slot_class)
        if contract is None:
            self.skipTest("No complete archived board with a published slot class")
        self.contract = contract
        self.year = _slotted_year(contract["playersArray"])
        if self.year is None:
            self.skipTest("No slot picks on the board -- between drafts (C1-U6-D2)")
        self.prefix = f"{self.year} Pick "
        self.slot_picks = [
            r
            for r in contract["playersArray"]
            if r.get("assetClass") == "pick"
            and isinstance(r.get("canonicalName"), str)
            and r["canonicalName"].startswith(self.prefix)
        ]

    def test_slot_1_01_matches_top_rookie_value(self) -> None:
        rows = self.contract["playersArray"]
        rookies = sorted(
            [
                r
                for r in rows
                if r.get("assetClass") != "pick"
                and bool(r.get("rookie"))
                and (r.get("rankDerivedValue") or 0) > 0
            ],
            key=lambda r: -int(r["rankDerivedValue"]),
        )
        if not rookies:
            self.skipTest("No rookies in contract")

        pick_101 = next(
            (r for r in rows if r.get("canonicalName") == f"{self.year} Pick 1.01"),
            None,
        )
        self.assertIsNotNone(pick_101, f"{self.year} Pick 1.01 missing from a slotted class")
        self.assertEqual(pick_101.get("rankDerivedValue"), rookies[0]["rankDerivedValue"])
        self.assertEqual(pick_101.get("pickRookieAnchor"), rookies[0]["canonicalName"])

    def test_slot_picks_have_null_canonical_rank(self) -> None:
        """Slot picks are proxies for their anchor rookie; they carry the
        rookie's rankDerivedValue but NOT a merged-board rank so players
        aren't pushed down a slot by each pick row."""
        for pick in self.slot_picks:
            self.assertIsNone(
                pick.get("canonicalConsensusRank"),
                f"{pick.get('canonicalName')} still carries a rank "
                f"(got {pick.get('canonicalConsensusRank')}) -- slot picks "
                "must be un-ranked so they don't push other rows down.",
            )
        # At least one pick should carry an anchored value -- verifies
        # that un-ranking happens AFTER the rookie anchor step, not
        # instead of it. (Some deep rookie slots may have no rookie
        # match; skipping to a pick that does is sufficient.)
        anchored = [
            p
            for p in self.slot_picks
            if p.get("rankDerivedValue") and int(p.get("rankDerivedValue")) > 0
        ]
        self.assertTrue(
            anchored,
            f"No {self.year} slot pick carries a positive rankDerivedValue -- "
            "anchor step appears broken after the un-rank change.",
        )

    def test_no_slot_pick_consumes_a_rank_slot(self) -> None:
        """Slot picks of the slotted class should be ENTIRELY absent from the
        ranked board -- no pick like ``<year> Pick 1.01`` should hold a
        canonicalConsensusRank. Other pick types (tier-generic rows,
        other years' tiers) may still hold ranks and are checked separately."""
        offenders = [
            r
            for r in self.contract["playersArray"]
            if r.get("canonicalConsensusRank") and r in self.slot_picks
        ]
        self.assertEqual(
            offenders,
            [],
            f"{self.year} slot picks still hold ranks: "
            f"{[r.get('canonicalName') for r in offenders[:3]]}",
        )

    def test_all_72_slotted_class_picks_tethered(self) -> None:
        """Every slot-specific pick of the slotted class (6 rounds x 12 slots =
        72) must be anchored to a distinct rookie via
        ``_anchor_current_year_picks_to_rookies``.  The tether pool
        draws from BOTH offense and IDP rookies, including tail
        rookies that fell off the Phase 4 cap.
        """
        picks = self.slot_picks
        if len(picks) < 72:
            self.skipTest(f"Only {len(picks)} {self.year} slot picks in contract")
        untethered = [p.get("canonicalName") for p in picks if not p.get("pickRookieAnchor")]
        self.assertEqual(
            untethered,
            [],
            f"{self.year} slot picks still untethered: {untethered[:5]}.  "
            f"The combined offense+IDP rookie pool (including tail "
            f"rookies with _blendedValueUncapped) should cover all "
            f"72 picks.",
        )

    def test_coherence_preserved_after_anchor(self) -> None:
        ranked = sorted(
            [r for r in self.contract["playersArray"] if r.get("canonicalConsensusRank")],
            key=lambda r: int(r["canonicalConsensusRank"]),
        )
        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], "\n".join(errors[:5]))

    def test_legacy_dict_mirror_matches_players_array(self) -> None:
        # The runtime view strips playersArray and the frontend reads
        # ``_canonicalConsensusRank`` from the legacy players dict.  When
        # the compact-ranks pass re-sorts by rankDerivedValue after the
        # anchor, non-pick rows can shift -- the mirror must keep up or
        # the rankings board shows stale / duplicate ranks.
        legacy = self.contract.get("players") or {}
        mismatches: list[str] = []
        for row in self.contract["playersArray"]:
            legacy_ref = row.get("legacyRef")
            if not legacy_ref or legacy_ref not in legacy:
                continue
            arr_rank = row.get("canonicalConsensusRank")
            leg_rank = legacy[legacy_ref].get("_canonicalConsensusRank")
            if arr_rank != leg_rank:
                mismatches.append(f"{row.get('canonicalName')}: array={arr_rank} legacy={leg_rank}")
                if len(mismatches) >= 5:
                    break
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
