"""Rookie anchor pass tests.

When slot-specific 2026 picks are present alongside rookies, each pick
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

import json
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    assert_ranking_coherence,
    build_api_data_contract,
)


_REPO = Path(__file__).resolve().parents[2]


def _make_rookie(name: str, rank: int, value: int) -> dict[str, Any]:
    return {
        "canonicalName": name,
        "assetClass": "player",
        "rookie": True,
        "canonicalConsensusRank": rank,
        "rankDerivedValue": value,
    }


def _make_pick(name: str, rank: int, value: int) -> dict[str, Any]:
    return {
        "canonicalName": name,
        "assetClass": "pick",
        "rookie": False,
        "canonicalConsensusRank": rank,
        "rankDerivedValue": value,
    }


# ── TestAnchorPassCore lives in test_pick_rookie_anchor_core.py ──
#
# This module is listed in _LIVEDATA_MODULES (tests/conftest.py), so
# every test in it is marked ``livedata`` and runs in CI's
# NON-BLOCKING advisory tier.  That is correct for the end-to-end
# class below, which reads exports/latest/ and fails on ordinary
# scrape churn.  It was wrong for the synthetic pure-logic class,
# which guarded pipeline step 11 while being unable to fail a PR.
#
# Do not move those tests back here without removing this module
# from _LIVEDATA_MODULES first.


class TestAnchorEndToEnd(unittest.TestCase):
    """Verify the anchor flows end-to-end through the real contract
    build when a live scraper export is available."""

    def setUp(self) -> None:
        data_dir = _REPO / "exports" / "latest"
        json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
        if not json_files:
            self.skipTest("No live scraper export available")
        with json_files[0].open() as f:
            raw = json.load(f)
        self.contract = build_api_data_contract(raw)

    def test_2026_1_01_matches_top_rookie_value(self) -> None:
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
            (r for r in rows if r.get("canonicalName") == "2026 Pick 1.01"),
            None,
        )
        if pick_101 is None:
            self.skipTest("No 2026 Pick 1.01 in contract")
        self.assertEqual(pick_101.get("rankDerivedValue"), rookies[0]["rankDerivedValue"])
        self.assertEqual(pick_101.get("pickRookieAnchor"), rookies[0]["canonicalName"])

    def test_2026_slot_picks_have_null_canonical_rank(self) -> None:
        """2026 slot picks are proxies for their anchor rookie; they
        carry the rookie's rankDerivedValue but NOT a merged-board
        rank so players aren't pushed down a slot by each pick row."""
        rows = self.contract["playersArray"]
        slot_picks = [
            r
            for r in rows
            if r.get("assetClass") == "pick"
            and isinstance(r.get("canonicalName"), str)
            and r["canonicalName"].startswith("2026 Pick ")
        ]
        if not slot_picks:
            self.skipTest("No 2026 slot picks in contract")
        for pick in slot_picks:
            self.assertIsNone(
                pick.get("canonicalConsensusRank"),
                f"{pick.get('canonicalName')} still carries a rank "
                f"(got {pick.get('canonicalConsensusRank')}) — 2026 slot picks "
                "must be un-ranked so they don't push other rows down.",
            )
        # At least one pick should carry an anchored value — verifies
        # that un-ranking happens AFTER the rookie anchor step, not
        # instead of it. (Some deep rookie slots may have no rookie
        # match; skipping to a pick that does is sufficient.)
        anchored = [
            p
            for p in slot_picks
            if p.get("rankDerivedValue") and int(p.get("rankDerivedValue")) > 0
        ]
        self.assertTrue(
            anchored,
            "No 2026 slot pick carries a positive rankDerivedValue — "
            "anchor step appears broken after the un-rank change.",
        )

    def test_no_2026_slot_pick_consumes_a_rank_slot(self) -> None:
        """2026 slot picks should be ENTIRELY absent from the ranked
        board — no pick like ``2026 Pick 1.01`` should hold a
        canonicalConsensusRank. Other pick types (tier-generic
        ``2026 Early 1st``, ``2027 Pick 1.01``) may still hold ranks
        and are checked separately."""
        ranked = [r for r in self.contract["playersArray"] if r.get("canonicalConsensusRank")]
        offenders = [
            r
            for r in ranked
            if r.get("assetClass") == "pick"
            and isinstance(r.get("canonicalName"), str)
            and r["canonicalName"].startswith("2026 Pick ")
        ]
        self.assertEqual(
            offenders,
            [],
            f"2026 slot picks still hold ranks: "
            f"{[r.get('canonicalName') for r in offenders[:3]]}",
        )

    def test_all_72_current_year_picks_tethered(self) -> None:
        """Every 2026 slot-specific pick (6 rounds × 12 slots = 72)
        must be anchored to a distinct rookie via
        ``_anchor_current_year_picks_to_rookies``.  The tether pool
        draws from BOTH offense and IDP rookies, including tail
        rookies that fell off the Phase 4 cap.
        """
        rows = self.contract["playersArray"]
        picks = [
            r
            for r in rows
            if r.get("assetClass") == "pick"
            and isinstance(r.get("canonicalName"), str)
            and r["canonicalName"].startswith("2026 Pick ")
        ]
        if len(picks) < 72:
            self.skipTest(f"Only {len(picks)} 2026 slot picks in contract")
        untethered = [p.get("canonicalName") for p in picks if not p.get("pickRookieAnchor")]
        self.assertEqual(
            untethered,
            [],
            f"2026 slot picks still untethered: {untethered[:5]}.  "
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
        # anchor, non-pick rows can shift — the mirror must keep up or
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
