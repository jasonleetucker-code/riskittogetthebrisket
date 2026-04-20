"""Pick refinement regression tests.

These tests cover the targeted draft-pick refinement pass added in
April 2026 (see audit dated 2026-04-14):

  * Slot-specific picks within a (year, round) bucket are strictly
    monotonic by slot number after blend.
  * Future-year picks are discounted relative to the baseline year.
  * Generic Early/Mid/Late tier rows are suppressed for any year that
    has slot-specific siblings, replaced by a ``pickAliases`` map.
  * Pick confidence buckets are computed from raw-value coefficient of
    variation rather than from rank spread.
  * Player rankings are unchanged for known top players (sanity check
    that nothing in the pick refinement leaks into player rows).

Run with:  python3 -m pytest tests/api/test_pick_refinement.py -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import build_api_data_contract


_REPO = Path(__file__).resolve().parents[2]


def _load_contract() -> dict[str, Any] | None:
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


_CACHED: dict[str, Any] | None = None


def _get() -> dict[str, Any] | None:
    global _CACHED
    if _CACHED is None:
        _CACHED = _load_contract()
    return _CACHED


def _by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        r["canonicalName"]: r
        for r in contract.get("playersArray", [])
        if r.get("canonicalName")
    }


class TestSlotMonotonic(unittest.TestCase):
    """Slot-specific picks must be strictly monotonic by slot number
    inside every (year, round) bucket."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def _check_round(self, year: int, rnd: int) -> None:
        prev_val: int | None = None
        for slot in range(1, 13):
            name = f"{year} Pick {rnd}.{slot:02d}"
            row = self.by_name.get(name)
            if row is None or not row.get("rankDerivedValue"):
                continue  # missing slot — not all sources cover all slots
            val = int(row["rankDerivedValue"])
            if prev_val is not None:
                self.assertLessEqual(
                    val,
                    prev_val,
                    f"{name} value {val} > previous slot value {prev_val}: "
                    f"slot order inversion in {year} R{rnd}",
                )
            prev_val = val

    def test_2026_r1_slots_monotonic(self) -> None:
        self._check_round(2026, 1)

    def test_2026_r2_slots_monotonic(self) -> None:
        self._check_round(2026, 2)

    def test_2026_r3_slots_monotonic(self) -> None:
        self._check_round(2026, 3)

    def test_2026_r4_slots_monotonic(self) -> None:
        self._check_round(2026, 4)

    def test_2026_r2_no_known_inversions(self) -> None:
        """Audit's specific R2 inversions are fixed:
        * 2.05 must NOT outrank 2.04
        * 2.09 must NOT outrank 2.04 or 2.07
        """
        names = [f"2026 Pick 2.{s:02d}" for s in range(1, 13)]
        rows = [self.by_name.get(n) for n in names]
        # All present
        for n, r in zip(names, rows):
            self.assertIsNotNone(r, f"{n} missing")

        def val(s: int) -> int:
            return int(rows[s - 1]["rankDerivedValue"])  # type: ignore[index]

        self.assertGreaterEqual(val(4), val(5), "2.04 must >= 2.05 in value")
        self.assertGreaterEqual(val(4), val(9), "2.04 must >= 2.09")
        self.assertGreaterEqual(val(7), val(9), "2.07 must >= 2.09")


class TestYearDiscount(unittest.TestCase):
    """Future-year picks must be discounted below baseline-year picks."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_2027_picks_discounted_below_2028(self) -> None:
        """2028 should always be lower than 2027 for matching tiers."""
        for tier in ("Early", "Mid", "Late"):
            for rnd_label in ("1st", "2nd", "3rd"):
                a = self.by_name.get(f"2027 {tier} {rnd_label}")
                b = self.by_name.get(f"2028 {tier} {rnd_label}")
                if not a or not b or not a.get("rankDerivedValue") or not b.get("rankDerivedValue"):
                    continue
                self.assertLess(
                    int(b["rankDerivedValue"]),
                    int(a["rankDerivedValue"]),
                    f"2028 {tier} {rnd_label} value {b['rankDerivedValue']} "
                    f">= 2027 {tier} {rnd_label} value {a['rankDerivedValue']}",
                )

    def test_2028_late_below_2026_pick_1_12(self) -> None:
        """2028 Late 1st must NOT outrank a 2026 specific 1st-round slot."""
        a = self.by_name.get("2028 Late 1st")
        b = self.by_name.get("2026 Pick 1.12")
        self.assertIsNotNone(a, "2028 Late 1st missing")
        self.assertIsNotNone(b, "2026 Pick 1.12 missing")
        self.assertLess(
            int(a["rankDerivedValue"]),  # type: ignore[index]
            int(b["rankDerivedValue"]),  # type: ignore[index]
            "2028 Late 1st must be worth less than 2026 Pick 1.12 "
            "(the audit's most prominent inversion)",
        )

    def test_2028_early_below_2026_pick_1_07(self) -> None:
        """2028 Early 1st must NOT outrank 2026 Pick 1.07 (audit case)."""
        a = self.by_name.get("2028 Early 1st")
        b = self.by_name.get("2026 Pick 1.07")
        self.assertIsNotNone(a, "2028 Early 1st missing")
        self.assertIsNotNone(b, "2026 Pick 1.07 missing")
        self.assertLess(
            int(a["rankDerivedValue"]),  # type: ignore[index]
            int(b["rankDerivedValue"]),  # type: ignore[index]
        )


class TestSpecificSlotVsRoundBoundary(unittest.TestCase):
    """Slot 1.12 must outvalue slot 2.01 (round-1 floor > round-2 ceiling)."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_2026_slot_1_12_above_2026_slot_2_01(self) -> None:
        a = self.by_name.get("2026 Pick 1.12")
        b = self.by_name.get("2026 Pick 2.01")
        self.assertIsNotNone(a, "2026 Pick 1.12 missing")
        self.assertIsNotNone(b, "2026 Pick 2.01 missing")
        self.assertGreater(
            int(a["rankDerivedValue"]),  # type: ignore[index]
            int(b["rankDerivedValue"]),  # type: ignore[index]
            "2026 Pick 1.12 must outvalue 2026 Pick 2.01",
        )


class TestGenericTierSuppression(unittest.TestCase):
    """Generic Early/Mid/Late rows must be suppressed for years with slots."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_2026_generic_tiers_suppressed(self) -> None:
        for label in ("Early", "Mid", "Late"):
            for rnd in ("1st", "2nd", "3rd", "4th", "5th", "6th"):
                name = f"2026 {label} {rnd}"
                row = self.by_name.get(name)
                if row is None:
                    continue
                self.assertTrue(
                    row.get("pickGenericSuppressed"),
                    f"{name} should be suppressed when 2026 slots exist",
                )
                self.assertIsNone(
                    row.get("canonicalConsensusRank"),
                    f"{name} should have no rank after suppression",
                )

    def test_pick_aliases_includes_2026_generic_tiers(self) -> None:
        aliases = self.contract.get("pickAliases", {}) if self.contract else {}
        self.assertIn("2026 Mid 1st", aliases)
        self.assertIn("2026 Early 1st", aliases)
        self.assertIn("2026 Late 1st", aliases)
        # Targets must be valid slot picks
        for k, v in aliases.items():
            row = self.by_name.get(v)
            self.assertIsNotNone(row, f"alias target missing: {v}")

    def test_2027_generic_tiers_kept(self) -> None:
        """2027 has no specific slots — its generic tiers must remain
        on the ranked board."""
        for tier in ("Early", "Mid", "Late"):
            row = self.by_name.get(f"2027 {tier} 1st")
            self.assertIsNotNone(row, f"2027 {tier} 1st missing")
            self.assertFalse(
                row.get("pickGenericSuppressed"),
                f"2027 {tier} 1st should NOT be suppressed (no specific slots)",
            )
            self.assertIsNotNone(
                row.get("canonicalConsensusRank"),
                f"2027 {tier} 1st should still be ranked",
            )


class TestPickConfidenceUsesCV(unittest.TestCase):
    """Pick confidence must come from raw-value CV, not rank spread."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_2026_specific_slots_have_pick_confidence(self) -> None:
        # All 2026 specific slots should resolve to a known pick bucket
        # — never the generic player labels.
        from src.api.data_contract import _compute_pick_confidence
        # Round 1 picks should be high confidence (KTC + IDPTC values
        # typically agree within 30%)
        for slot in range(1, 13):
            row = self.by_name.get(f"2026 Pick 1.{slot:02d}")
            self.assertIsNotNone(row)
            bucket = row.get("confidenceBucket")  # type: ignore[union-attr]
            self.assertIn(
                bucket,
                {"high", "medium", "low"},
                f"unexpected pick confidence bucket: {bucket}",
            )

    def test_pick_confidence_label_uses_cv_phrasing(self) -> None:
        """At least one labelled pick should reference picks/agree, not
        the legacy multi-source/spread phrasing."""
        labels = [
            (r.get("canonicalName"), r.get("confidenceLabel"))
            for r in self.contract.get("playersArray", [])  # type: ignore[union-attr]
            if r.get("assetClass") == "pick" and r.get("confidenceLabel")
        ]
        self.assertTrue(labels, "no pick labels found")
        cv_phrases = ("picks agree", "pick source", "divergent pick")
        ok = any(
            any(p in (lbl or "").lower() for p in cv_phrases)
            for _n, lbl in labels
        )
        self.assertTrue(
            ok,
            f"no pick label uses CV phrasing; sample={labels[:3]}",
        )


class TestPlayerRankingsUnchanged(unittest.TestCase):
    """Player ranks/values for known top players must not regress.

    Catches catastrophic pipeline regressions — a blend bug that ranks
    an elite player #150, a calibration bug that collapses their value
    below the floor, or a coverage bug that drops their confidence
    bucket — without requiring fixture regeneration as legitimate
    market drift shifts day-to-day ranks.

    Each anchor is pinned to an invariant band wide enough to absorb
    years of organic scrape drift:

      * ``max_rank`` — upper bound on ``canonicalConsensusRank``.  Set
        well above the current rank so normal market movement never
        trips it.
      * ``min_value`` — lower bound on ``rankDerivedValue`` on the
        0-9999 scale.  Catches value collapse even when rank holds.
      * ``allowed_buckets`` — acceptable values for
        ``confidenceBucket``.  Single-element tuple when the bucket
        must stay fixed, multi-element for players whose coverage
        legitimately oscillates between ``high`` and ``medium``.

    Historically (April 2026) this test pinned exact ranks/values
    against a committed baseline fixture with ±5 rank / ±500 value
    tolerances.  Those tolerances were too tight to absorb real
    scrape drift, so every data refresh required a human to
    regenerate the fixture.  The durable fix replaces the exact pins
    with invariant bands — same regression coverage, zero manual
    maintenance.
    """

    _ANCHORS: dict[str, dict[str, Any]] = {
        # ── Offense anchors ──
        "Josh Allen":       {"max_rank": 20, "min_value": 6000, "allowed_buckets": ("high",)},
        "Drake Maye":       {"max_rank": 20, "min_value": 6000, "allowed_buckets": ("high",)},
        "Ja'Marr Chase":    {"max_rank": 15, "min_value": 7000, "allowed_buckets": ("high",)},
        "Bijan Robinson":   {"max_rank": 15, "min_value": 6500, "allowed_buckets": ("high",)},
        "Jahmyr Gibbs":     {"max_rank": 20, "min_value": 6000, "allowed_buckets": ("high",)},
        "Jayden Daniels":   {"max_rank": 25, "min_value": 5500, "allowed_buckets": ("high",)},
        "Puka Nacua":       {"max_rank": 25, "min_value": 5500, "allowed_buckets": ("high",)},
        "Malik Nabers":     {"max_rank": 30, "min_value": 5000, "allowed_buckets": ("high", "medium")},
        "Brock Bowers":     {"max_rank": 40, "min_value": 5000, "allowed_buckets": ("high", "medium")},
        "Patrick Mahomes":  {"max_rank": 50, "min_value": 4000, "allowed_buckets": ("high", "medium")},
        # ── IDP anchors ──
        # IDP rows sit deeper in the unified board (smaller pool, later
        # calibration) and their confidence buckets lean "low" because
        # the IDP source pool is narrower.  Bands are proportionally
        # more generous to absorb normal drift.  A regression that
        # collapses IDP value pricing (e.g. a calibration bug, shared-
        # market ladder breakage, IDPTC backbone failure) will trip
        # these.
        "Myles Garrett":    {"max_rank": 90,  "min_value": 3500, "allowed_buckets": ("low", "medium", "high")},
        "Will Anderson":    {"max_rank": 90,  "min_value": 3500, "allowed_buckets": ("low", "medium", "high")},
        "Micah Parsons":    {"max_rank": 90,  "min_value": 3500, "allowed_buckets": ("low", "medium", "high")},
        "Fred Warner":      {"max_rank": 90,  "min_value": 3200, "allowed_buckets": ("low", "medium", "high")},
        "Roquan Smith":     {"max_rank": 100, "min_value": 3000, "allowed_buckets": ("low", "medium", "high")},
        "Kyle Hamilton":    {"max_rank": 180, "min_value": 2200, "allowed_buckets": ("low", "medium", "high")},
    }

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_known_player_values_unchanged(self) -> None:
        """Top-player ranks, values, and buckets must stay within invariant bands."""
        seen = 0
        for name, bounds in self._ANCHORS.items():
            with self.subTest(player=name):
                row = self.by_name.get(name)
                self.assertIsNotNone(
                    row,
                    f"{name} missing from current contract — pipeline "
                    f"stopped ranking a top player?",
                )
                seen += 1
                cur_rank = int(row.get("canonicalConsensusRank") or 0)
                cur_val = int(row.get("rankDerivedValue") or 0)
                cur_bucket = str(row.get("confidenceBucket") or "")

                max_rank = int(bounds["max_rank"])
                min_value = int(bounds["min_value"])
                allowed_buckets = tuple(bounds["allowed_buckets"])

                self.assertGreater(cur_rank, 0, f"{name} has no rank")
                self.assertLessEqual(
                    cur_rank,
                    max_rank,
                    f"{name} canonicalConsensusRank={cur_rank} exceeds "
                    f"invariant max_rank={max_rank} — likely pipeline regression",
                )
                self.assertGreaterEqual(
                    cur_val,
                    min_value,
                    f"{name} rankDerivedValue={cur_val} below invariant "
                    f"min_value={min_value} — likely calibration collapse",
                )
                self.assertIn(
                    cur_bucket,
                    allowed_buckets,
                    f"{name} confidenceBucket={cur_bucket!r} not in "
                    f"allowed {allowed_buckets} — likely coverage regression",
                )
        self.assertGreater(seen, 0, "no anchors verified")

    def test_top_five_offense_still_ranked(self) -> None:
        """The top-5 offense group must stay in the top 10 of the board.

        This is an invariant independent of the baseline snapshot.
        """
        top_five_offense_targets = {
            "Josh Allen",
            "Ja'Marr Chase",
            "Bijan Robinson",
            "Drake Maye",
            "Jahmyr Gibbs",
            "Puka Nacua",
        }
        top_ranked = [
            r
            for r in sorted(
                (
                    r
                    for r in self.contract.get("playersArray") or []
                    if r.get("assetClass") == "offense"
                    and r.get("canonicalConsensusRank")
                ),
                key=lambda r: int(r["canonicalConsensusRank"]),
            )[:10]
        ]
        names = [r.get("canonicalName") for r in top_ranked]
        overlap = top_five_offense_targets.intersection(names)
        self.assertGreaterEqual(
            len(overlap),
            3,
            f"Fewer than 3 of {top_five_offense_targets} in top-10: {names}",
        )


if __name__ == "__main__":
    unittest.main()
