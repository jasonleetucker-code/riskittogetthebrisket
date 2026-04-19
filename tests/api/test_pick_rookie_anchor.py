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
    _anchor_current_year_picks_to_rookies,
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


class TestAnchorPassCore(unittest.TestCase):
    """Synthetic playersArray exercises — no live data required."""

    def test_1_01_matches_top_rookie(self) -> None:
        rookies = [_make_rookie(f"Rookie {i}", i, 10000 - i * 10) for i in range(1, 13)]
        picks = [
            _make_pick(f"2026 Pick 1.{slot:02d}", 80 + slot, 6000 - slot * 50)
            for slot in range(1, 13)
        ]
        players_array = rookies + picks

        anchored = _anchor_current_year_picks_to_rookies(players_array, 2026)
        self.assertEqual(anchored, 12)
        self.assertEqual(
            picks[0]["rankDerivedValue"], rookies[0]["rankDerivedValue"]
        )
        self.assertEqual(picks[0]["pickRookieAnchor"], "Rookie 1")

    def test_slot_mapping_is_monotonic(self) -> None:
        rookies = [_make_rookie(f"R{i}", i, 20000 - i * 7) for i in range(1, 80)]
        picks = []
        for rnd in range(1, 7):
            for slot in range(1, 13):
                picks.append(
                    _make_pick(
                        f"2026 Pick {rnd}.{slot:02d}",
                        100 + (rnd - 1) * 12 + slot,
                        500 - rnd * 10 - slot,
                    )
                )
        players_array = rookies + picks

        anchored = _anchor_current_year_picks_to_rookies(players_array, 2026)
        self.assertEqual(anchored, 72)

        # Walk picks in slot order; values must strictly decrease
        # because the rookie list is strictly decreasing.
        prev_val: int | None = None
        for rnd in range(1, 7):
            for slot in range(1, 13):
                name = f"2026 Pick {rnd}.{slot:02d}"
                row = next(p for p in picks if p["canonicalName"] == name)
                val = row["rankDerivedValue"]
                if prev_val is not None:
                    self.assertLess(val, prev_val, f"{name}: {val} >= prev {prev_val}")
                prev_val = val

    def test_offense_idp_rookies_merge(self) -> None:
        offense = [_make_rookie(f"OffRook {i}", i, 9000 - i * 20) for i in range(1, 6)]
        idp = [_make_rookie(f"IdpRook {i}", 30 + i, 8900 - i * 20) for i in range(1, 6)]
        # Interleave by value: off1=8980, idp1=8880, off2=8960, idp2=8860, ...
        picks = [_make_pick(f"2026 Pick 1.{s:02d}", 80 + s, 100) for s in range(1, 8)]
        players_array = offense + idp + picks

        _anchor_current_year_picks_to_rookies(players_array, 2026)

        merged_sorted = sorted(
            offense + idp, key=lambda r: -r["rankDerivedValue"]
        )
        for i, pick in enumerate(picks):
            if i >= len(merged_sorted):
                continue
            self.assertEqual(
                pick["rankDerivedValue"],
                merged_sorted[i]["rankDerivedValue"],
                f"pick {pick['canonicalName']} should match merged "
                f"rookie #{i+1}",
            )

    def test_wrong_year_untouched(self) -> None:
        rookies = [_make_rookie(f"R{i}", i, 9000 - i * 10) for i in range(1, 4)]
        pick_2027 = _make_pick("2027 Pick 1.01", 50, 4200)
        pick_2026 = _make_pick("2026 Pick 1.01", 51, 4100)
        players_array = rookies + [pick_2026, pick_2027]

        _anchor_current_year_picks_to_rookies(players_array, 2026)

        self.assertEqual(pick_2027["rankDerivedValue"], 4200)  # untouched
        self.assertEqual(pick_2026["rankDerivedValue"], 8990)  # top rookie

    def test_generic_tier_rows_untouched(self) -> None:
        rookies = [_make_rookie(f"R{i}", i, 9000 - i * 10) for i in range(1, 4)]
        tier_pick = _make_pick("2026 Early 1st", 40, 5500)
        players_array = rookies + [tier_pick]

        _anchor_current_year_picks_to_rookies(players_array, 2026)

        # Generic tier rows (Early/Mid/Late) don't parse as slot picks
        # and are left alone.
        self.assertEqual(tier_pick["rankDerivedValue"], 5500)
        self.assertNotIn("pickRookieAnchor", tier_pick)

    def test_no_rookies_is_noop(self) -> None:
        picks = [
            _make_pick(f"2026 Pick 1.{s:02d}", 80 + s, 5000 - s * 10)
            for s in range(1, 13)
        ]
        before = [p["rankDerivedValue"] for p in picks]
        anchored = _anchor_current_year_picks_to_rookies(picks, 2026)
        self.assertEqual(anchored, 0)
        self.assertEqual([p["rankDerivedValue"] for p in picks], before)

    def test_unranked_pick_skipped(self) -> None:
        rookies = [_make_rookie("R1", 1, 9000)]
        pick = _make_pick("2026 Pick 1.01", 0, 0)
        pick["canonicalConsensusRank"] = None
        players_array = rookies + [pick]

        anchored = _anchor_current_year_picks_to_rookies(players_array, 2026)
        self.assertEqual(anchored, 0)
        self.assertNotIn("pickRookieAnchor", pick)

    def test_beyond_72_rookies_unused(self) -> None:
        # Only 60 rookies available; pick 6.01 (index 60) has no anchor.
        rookies = [_make_rookie(f"R{i}", i, 9000 - i * 10) for i in range(1, 61)]
        pick_601 = _make_pick("2026 Pick 6.01", 200, 2000)
        players_array = rookies + [pick_601]

        _anchor_current_year_picks_to_rookies(players_array, 2026)

        # idx = 5*12 + 0 = 60 which is >= len(rookies)=60, so untouched.
        self.assertEqual(pick_601["rankDerivedValue"], 2000)
        self.assertNotIn("pickRookieAnchor", pick_601)


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
        self.assertEqual(
            pick_101.get("rankDerivedValue"), rookies[0]["rankDerivedValue"]
        )
        self.assertEqual(
            pick_101.get("pickRookieAnchor"), rookies[0]["canonicalName"]
        )

    def test_2026_slot_picks_have_null_canonical_rank(self) -> None:
        """2026 slot picks are proxies for their anchor rookie; they
        carry the rookie's rankDerivedValue but NOT a merged-board
        rank so players aren't pushed down a slot by each pick row."""
        rows = self.contract["playersArray"]
        slot_picks = [
            r for r in rows
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
            p for p in slot_picks
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
        ranked = [
            r for r in self.contract["playersArray"]
            if r.get("canonicalConsensusRank")
        ]
        offenders = [
            r for r in ranked
            if r.get("assetClass") == "pick"
            and isinstance(r.get("canonicalName"), str)
            and r["canonicalName"].startswith("2026 Pick ")
        ]
        self.assertEqual(
            offenders, [],
            f"2026 slot picks still hold ranks: "
            f"{[r.get('canonicalName') for r in offenders[:3]]}",
        )

    def test_coherence_preserved_after_anchor(self) -> None:
        ranked = sorted(
            [
                r
                for r in self.contract["playersArray"]
                if r.get("canonicalConsensusRank")
            ],
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
                mismatches.append(
                    f"{row.get('canonicalName')}: array={arr_rank} legacy={leg_rank}"
                )
                if len(mismatches) >= 5:
                    break
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
