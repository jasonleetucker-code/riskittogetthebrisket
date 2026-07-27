"""Rookie-anchor pass — the PURE-LOGIC half, in the blocking gate.

Split out of ``test_pick_rookie_anchor.py`` for one reason: that module
is listed in ``_LIVEDATA_MODULES`` (tests/conftest.py), which marks
**every test in the file** ``livedata`` and drops it into CI's
non-blocking advisory tier.

That policy is right for the end-to-end class, which reads
``exports/latest/dynasty_data_*.json`` and fails on ordinary scrape
churn with no code defect. It was wrong for these ten, whose own class
docstring read *"Synthetic playersArray exercises — no live data
required"*. They are pure functions over hand-built rows, they cannot
be broken by a row-count dip, and they guard pipeline step 11 —
current-year pick tethering, which sets the value of all 72 slot picks
on the live board.

Measured 2026-07-27: ``pytest tests/api/test_pick_rookie_anchor.py -m
"not livedata"`` collected **15 deselected, 0 run**. So the backlog's
"pick tethering untested" was not quite right and worse than it sounds
— the tests exist, are good, and never gated anything. Same shape as
``test_anchor_curve_extrapolation_monotone`` (defect #2): a real test
that cannot fail a PR is a test nobody is running.

The module-granularity policy itself is sound and unchanged. This just
puts the two halves in the two modules the policy needs them in.
"""

from __future__ import annotations

import unittest
from typing import Any

from src.api.data_contract import _anchor_current_year_picks_to_rookies


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
        self.assertEqual(picks[0]["rankDerivedValue"], rookies[0]["rankDerivedValue"])
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

        merged_sorted = sorted(offense + idp, key=lambda r: -r["rankDerivedValue"])
        for i, pick in enumerate(picks):
            if i >= len(merged_sorted):
                continue
            self.assertEqual(
                pick["rankDerivedValue"],
                merged_sorted[i]["rankDerivedValue"],
                f"pick {pick['canonicalName']} should match merged " f"rookie #{i+1}",
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
        picks = [_make_pick(f"2026 Pick 1.{s:02d}", 80 + s, 5000 - s * 10) for s in range(1, 13)]
        before = [p["rankDerivedValue"] for p in picks]
        anchored = _anchor_current_year_picks_to_rookies(picks, 2026)
        self.assertEqual(anchored, 0)
        self.assertEqual([p["rankDerivedValue"] for p in picks], before)

    def test_unranked_pick_still_anchored(self) -> None:
        """Picks that fell off the Phase 4 OVERALL_RANK_LIMIT cap still
        get anchored when a corresponding rookie exists.

        The anchor is a proxy value for the rookie regardless of
        whether the pick row survived the global rank cap; the
        Phase 5 compact pass would clear the pick's rank anyway.
        Gating on ``canonicalConsensusRank`` left tail R4 picks
        unvalued whenever a curve retune tightened the cap.
        """
        rookies = [_make_rookie("R1", 1, 9000)]
        pick = _make_pick("2026 Pick 1.01", 0, 0)
        pick["canonicalConsensusRank"] = None
        players_array = rookies + [pick]

        anchored = _anchor_current_year_picks_to_rookies(players_array, 2026)
        self.assertEqual(anchored, 1)
        self.assertEqual(pick.get("rankDerivedValue"), 9000)
        self.assertEqual(pick.get("pickRookieAnchor"), "R1")

    def test_beyond_72_rookies_unused(self) -> None:
        # Only 60 rookies available; pick 6.01 (index 60) has no anchor.
        rookies = [_make_rookie(f"R{i}", i, 9000 - i * 10) for i in range(1, 61)]
        pick_601 = _make_pick("2026 Pick 6.01", 200, 2000)
        players_array = rookies + [pick_601]

        _anchor_current_year_picks_to_rookies(players_array, 2026)

        # idx = 5*12 + 0 = 60 which is >= len(rookies)=60, so untouched.
        self.assertEqual(pick_601["rankDerivedValue"], 2000)
        self.assertNotIn("pickRookieAnchor", pick_601)

    def test_tail_rookies_with_only_blended_value_included(self) -> None:
        """Deep rookies whose Hill-blend output survived beyond the
        top-``OVERALL_RANK_LIMIT`` cap (so they carry
        ``_blendedValueUncapped`` instead of ``rankDerivedValue``) must
        still participate in the tether pool.  Without this, rounds 5
        and 6 of the current-year pick board run out of tether targets
        around slot 53 and stamp ``rankDerivedValue=0`` on deep picks.
        """
        # 40 top-800 offense rookies + 35 tail rookies (only uncapped value).
        top_rookies = [_make_rookie(f"Top{i}", i, 9000 - i * 50) for i in range(1, 41)]
        tail_rookies: list[dict[str, Any]] = []
        for i in range(1, 36):
            r = _make_rookie(f"Tail{i}", 0, 0)
            r["canonicalConsensusRank"] = None
            r["_blendedValueUncapped"] = 1500 - i * 5  # strictly decreasing
            tail_rookies.append(r)
        picks = [
            _make_pick(f"2026 Pick {rnd}.{slot:02d}", 100 + rnd * 12 + slot, 100)
            for rnd in range(1, 7)
            for slot in range(1, 13)
        ]
        players_array = top_rookies + tail_rookies + picks

        anchored = _anchor_current_year_picks_to_rookies(players_array, 2026)

        # 40 top + 35 tail = 75 rookies → all 72 picks should tether.
        self.assertEqual(anchored, 72)
        # Slot 6.12 should be tethered (index 71); without tail rookies
        # it would be skipped.
        pick_612 = next(p for p in picks if p["canonicalName"] == "2026 Pick 6.12")
        self.assertIn("pickRookieAnchor", pick_612)
        self.assertGreater(int(pick_612["rankDerivedValue"]), 0)
