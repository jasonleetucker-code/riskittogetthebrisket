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
import re
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
        r["canonicalName"]: r for r in contract.get("playersArray", []) if r.get("canonicalName")
    }


_SLOT_NAME = re.compile(r"^(20\d{2}) Pick [1-6]\.\d{2}$")

#: Between one rookie draft and the next class's draft order no class is
#: slotted (C1-U6-D2): the board carries every year as tiers.  Slot-specific
#: assertions have nothing to assert then, and say so rather than fail.
_NO_SLOTTED_CLASS = (
    "no slotted class on the board — between drafts every year prices as tiers (C1-U6-D2)"
)


def _slotted_year(by_name: dict[str, dict[str, Any]]) -> int | None:
    """The class whose SLOT rows are on the board, derived — never a literal."""
    years = sorted({int(m.group(1)) for n in by_name for m in [_SLOT_NAME.match(n)] if m})
    return years[0] if years else None


_COVERS = re.compile(r"Covers (\d+) of (\d+) eligible evidence famil")
_WITHHELD = re.compile(r"(\d+) observed famil(?:y|ies) did not reach the value")


def _coverage_shortfall_is_withheld_only(row: dict[str, Any]) -> bool:
    """True when coverage would be HIGH counting withheld-but-observed families.

    Read from the confidence owner's own reasons so no gate logic is
    re-derived here; the share bar is the owner's ``EVIDENCE_SHARE_HIGH``.
    """
    from src.api.confidence import gate_parameter

    reasons = " | ".join(str(r) for r in (row.get("confidenceReasons") or ()))
    covers = _COVERS.search(reasons)
    withheld = _WITHHELD.search(reasons)
    if not covers or not withheld:
        return False
    covered, eligible = int(covers.group(1)), int(covers.group(2))
    observed = covered + int(withheld.group(1))
    return eligible > 0 and observed / eligible >= gate_parameter("EVIDENCE_SHARE_HIGH")


class TestSlotMonotonic(unittest.TestCase):
    """Slot-specific picks must be strictly monotonic by slot number
    inside every (year, round) bucket."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def _check_round(self, year: int, rnd: int, *, tolerance: int = 0) -> None:
        # Slot-to-slot monotonicity check within (year, round).
        # ``tolerance`` allows bounded inversions for deep rounds
        # (R3+), where pick values come from rookie anchors and the
        # framework's flatter Hill tail means rookies 37-48 (R4 slots)
        # can sit within a tight cluster — a 1-slot inversion of a
        # few points is a rookie-value tie, not a pipeline regression.
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
                    prev_val + tolerance,
                    f"{name} value {val} > previous slot value {prev_val} "
                    f"(tolerance {tolerance}): slot order inversion in "
                    f"{year} R{rnd}",
                )
            prev_val = val

    def _year(self) -> int:
        year = _slotted_year(self.by_name)
        if year is None:
            self.skipTest(_NO_SLOTTED_CLASS)
        return year

    def test_current_class_r1_slots_monotonic(self) -> None:
        self._check_round(self._year(), 1)

    def test_current_class_r2_slots_monotonic(self) -> None:
        self._check_round(self._year(), 2)

    def test_current_class_r3_slots_monotonic(self) -> None:
        self._check_round(self._year(), 3)

    def test_current_class_r4_slots_monotonic(self) -> None:
        # R4 pick slots anchor to rookies 37-48 where the rookie value
        # cluster sits in the Hill's flatter tail.  Allow a 100-point
        # tolerance for bounded inversions from rookie-value ties.
        self._check_round(self._year(), 4, tolerance=100)

    def test_current_class_r2_no_known_inversions(self) -> None:
        """Audit's specific R2 inversions are fixed:
        * 2.05 must NOT outrank 2.04
        * 2.09 must NOT outrank 2.04 or 2.07
        """
        names = [f"{self._year()} Pick 2.{s:02d}" for s in range(1, 13)]
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

    def test_future_tier_picks_track_the_market_that_prices_them(self) -> None:
        """Vendor-priced future tiers must not sit far below their market.

        REPLACES ``test_2028_late_below_2026_pick_1_12`` — a DELIBERATE
        REVERSAL of a prior decision, recorded here rather than deleted.

        The old test asserted 2028 Late 1st < 2026 Pick 1.12, calling the
        opposite "the audit's most prominent inversion", and the blanket
        future-year discount was what enforced it.  The 2026-08-04 audit
        (finding T-3/C-2) measured that enforcement against the markets
        the board ingests and found it inverted THEM::

            ktcSfTep   2026 Late 1st 3942   2028 Late 1st 4026
            ktcSfTep   2026 Early 1st 5605  2027 Early 1st 7061

        Both markets price an unknown future first ABOVE the matching
        current-year tier, because an unknown pick carries option value —
        a 2028 late first can become an early one if that roster
        collapses, while a known 2026 slot cannot.  Composing a decay
        prior on top published 2027 firsts 18% and 2028 firsts 34% below
        what both markets agreed.

        So the "inversion" was the market, and the discount was the
        overcorrection.  What is pinned now is the property that actually
        matters for a trade: a vendor-priced tier tracks its own market.

        If the product deliberately wants to be more conservative than
        the market on future capital, that is a legitimate stance — but
        it belongs in a calibrated, documented adjustment, not in a
        prior applied on top of a price that already encodes the year.
        """
        import csv
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        market: dict[str, float] = {}
        with open(repo / "CSVs" / "site_raw" / "ktcSfTep.csv", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2:
                    try:
                        market[row[0].strip()] = float(row[1])
                    except ValueError:
                        continue

        checked = 0
        for name in ("2027 Early 1st", "2027 Mid 1st", "2028 Early 1st", "2028 Late 1st"):
            got = self.by_name.get(name)
            mkt = market.get(name)
            if not got or not got.get("rankDerivedValue") or not mkt:
                continue
            checked += 1
            ratio = int(got["rankDerivedValue"]) / mkt
            self.assertGreater(
                ratio,
                0.85,
                f"{name} published {got['rankDerivedValue']} vs market {mkt:.0f} "
                f"(ratio {ratio:.2f}) — a vendor-priced year must not be "
                f"systematically marked down; see audit finding T-3",
            )
        self.assertGreater(checked, 0, "no vendor-priced future tiers found to check")

    def test_current_year_top_slots_still_outrank_far_future_tiers(self) -> None:
        """The part of the old ordering rule that survives, and should.

        ``test_2028_early_below_2026_pick_1_07`` asserted a 2028 Early
        1st sits below the 7th slot of the 2026 class.  That specific
        pairing was an artifact of the blanket discount (see the reversal
        note on ``test_future_tier_picks_track_the_market_that_prices_them``);
        the markets do not support it.

        What the markets DO support, and what a user would find alarming
        if it broke, is the top of the known class still leading: a 2026
        Pick 1.01 is a near-certain elite prospect and outvalues a
        speculative 2028 tier.  Pinning that instead keeps the guard
        against a runaway future-pick valuation without re-encoding the
        overcorrection.
        """
        year = _slotted_year(self.by_name)
        if year is None:
            self.skipTest(_NO_SLOTTED_CLASS)
        top = self.by_name.get(f"{year} Pick 1.01")
        far = self.by_name.get(f"{year + 2} Early 1st")
        if not top or not far:
            self.skipTest("pick rows not present on this board")
        if not top.get("rankDerivedValue") or not far.get("rankDerivedValue"):
            self.skipTest("pick rows unpriced on this board")
        self.assertLess(
            int(far["rankDerivedValue"]),
            int(top["rankDerivedValue"]),
            "a speculative two-years-out tier must not outvalue the 1.01 of the "
            "class that is about to be drafted",
        )


class TestSpecificSlotVsRoundBoundary(unittest.TestCase):
    """Slot 1.12 must outvalue slot 2.01 (round-1 floor > round-2 ceiling)."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_current_class_slot_1_12_above_slot_2_01(self) -> None:
        # Under the Final Framework's flatter Hill tail the 12th and
        # 13th rookies can land at identical integer values (picks
        # anchor to rookies, so ties on the rookie side propagate).
        # We assert weak monotonicity — 1.12 must never undervalue
        # 2.01 — rather than strict > which the old rank-Hill curve
        # guaranteed by construction.
        year = _slotted_year(self.by_name)
        if year is None:
            self.skipTest(_NO_SLOTTED_CLASS)
        a = self.by_name.get(f"{year} Pick 1.12")
        b = self.by_name.get(f"{year} Pick 2.01")
        self.assertIsNotNone(a, f"{year} Pick 1.12 missing")
        self.assertIsNotNone(b, f"{year} Pick 2.01 missing")
        self.assertGreaterEqual(
            int(a["rankDerivedValue"]),  # type: ignore[index]
            int(b["rankDerivedValue"]),  # type: ignore[index]
            f"{year} Pick 1.12 must weakly outvalue {year} Pick 2.01",
        )


class TestGenericTierSuppression(unittest.TestCase):
    """Generic Early/Mid/Late rows must be suppressed for years with slots."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_slotted_class_generic_tiers_suppressed(self) -> None:
        year = _slotted_year(self.by_name)
        if year is None:
            self.skipTest(_NO_SLOTTED_CLASS)
        for label in ("Early", "Mid", "Late"):
            for rnd in ("1st", "2nd", "3rd", "4th", "5th", "6th"):
                name = f"{year} {label} {rnd}"
                row = self.by_name.get(name)
                if row is None:
                    continue
                self.assertTrue(
                    row.get("pickGenericSuppressed"),
                    f"{name} should be suppressed when {year} slots exist",
                )
                self.assertIsNone(
                    row.get("canonicalConsensusRank"),
                    f"{name} should have no rank after suppression",
                )

    def test_pick_aliases_cover_exactly_the_slotted_class(self) -> None:
        aliases = self.contract.get("pickAliases", {}) if self.contract else {}
        year = _slotted_year(self.by_name)
        if year is None:
            # Nothing is slotted, so nothing may be aliased away.
            self.assertEqual(aliases, {}, "tiers aliased with no slot rows to alias to")
            return
        self.assertIn(f"{year} Mid 1st", aliases)
        self.assertIn(f"{year} Early 1st", aliases)
        self.assertIn(f"{year} Late 1st", aliases)
        # Targets must be valid slot picks
        for k, v in aliases.items():
            row = self.by_name.get(v)
            self.assertIsNotNone(row, f"alias target missing: {v}")

    def test_unslotted_years_keep_their_tiers(self) -> None:
        """Every year with no slot rows keeps its tiers on the ranked board —
        including the CURRENT class between drafts (C1-U6-D2)."""
        slotted = _slotted_year(self.by_name)
        tier_years = sorted(
            {int(n[:4]) for n in self.by_name if re.match(r"^20\d{2} (Early|Mid|Late) 1st$", n)}
        )
        checked = [y for y in tier_years if y != slotted]
        self.assertTrue(checked, "no unslotted tier year on the board")
        for year in checked:
            for tier in ("Early", "Mid", "Late"):
                row = self.by_name.get(f"{year} {tier} 1st")
                self.assertIsNotNone(row, f"{year} {tier} 1st missing")
                self.assertFalse(
                    row.get("pickGenericSuppressed"),
                    f"{year} {tier} 1st should NOT be suppressed (no specific slots)",
                )
                self.assertIsNotNone(
                    row.get("canonicalConsensusRank"),
                    f"{year} {tier} 1st should still be ranked",
                )

    def test_no_tether_outside_the_slotted_class(self) -> None:
        """A pick is tethered to rookies only inside the slotted class —
        never a tier year, never a class whose draft order is unknown."""
        slotted = _slotted_year(self.by_name)
        for name, row in self.by_name.items():
            prov = row.get("pickValueProvenance") or {}
            if isinstance(prov, dict) and prov.get("class") == "rookie_pool_tether":
                self.assertIsNotNone(_SLOT_NAME.match(name), f"{name} tethered but not a slot")
                self.assertEqual(
                    int(name[:4]), slotted, f"{name} tethered outside the slotted class"
                )


class TestPickConfidenceUsesCV(unittest.TestCase):
    """Pick confidence must come from raw-value CV, not rank spread."""

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)

    def test_slotted_class_picks_have_pick_confidence(self) -> None:
        # All slotted-class slots should resolve to a known pick bucket
        # — never the generic player labels.

        # Round 1 picks should be high confidence (KTC + IDPTC values
        # typically agree within 30%)
        year = _slotted_year(self.by_name)
        if year is None:
            self.skipTest(_NO_SLOTTED_CLASS)
        for slot in range(1, 13):
            row = self.by_name.get(f"{year} Pick 1.{slot:02d}")
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
        ok = any(any(p in (lbl or "").lower() for p in cv_phrases) for _n, lbl in labels)
        self.assertTrue(
            ok,
            f"no pick label uses CV phrasing; sample={labels[:3]}",
        )


#: ``sourceWeightState`` values (``data_contract._stamp_source_weight_state``)
#: under which a row's absolute rank/value is a statement about SOURCE HEALTH
#: — retained authority below the degraded threshold, or one source dominating
#: — rather than about our code.
_DEGRADED_WEIGHT_STATES = frozenset({"DEGRADED", "SEVERELY_DEGRADED"})

#: Same numerical slack the blend-integrity detector uses
#: (``_BLEND_HULL_QUANTIZATION_BELOW`` / ``…_ABOVE``): int-truncated value vs
#: int-rounded contribution stamps.  Precision, not policy.
_HULL_SLACK_BELOW = 1.5
_HULL_SLACK_ABOVE = 0.5


def _assert_value_inside_contributing_votes(
    case: unittest.TestCase, name: str, row: dict[str, Any]
) -> None:
    """Source-independent anchor invariant for a degraded-evidence row.

    Whatever subset of vendors answered the last scrape, a published value
    must lie inside the range of the votes that actually carried weight — a
    blend that leaves its own contributions' hull is a pipeline fault on any
    board.  It must also not be quarantined (a blend-integrity violation
    quarantines the row).
    """
    contributions = [
        float(m["valueContribution"])
        for m in (row.get("sourceRankMeta") or {}).values()
        if isinstance(m, dict)
        and m.get("valueContribution") is not None
        and float(m.get("appliedWeight") or 0.0) > 0.0
        and m.get("contributedToBlend") is not False
    ]
    case.assertTrue(
        contributions,
        f"{name}: sourceWeightState={row.get('sourceWeightState')!r} but no "
        f"weighted contribution is stamped — evidence lost, not merely degraded",
    )
    value = float(row.get("rankDerivedValue") or 0)
    lo, hi = min(contributions), max(contributions)
    case.assertTrue(
        lo - _HULL_SLACK_BELOW <= value <= hi + _HULL_SLACK_ABOVE,
        f"{name}: rankDerivedValue={value:.0f} outside its weighted votes "
        f"[{lo:.0f}, {hi:.0f}] — blend regression, not source health",
    )
    case.assertFalse(
        row.get("quarantined"),
        f"{name}: quarantined (anomalyFlags={row.get('anomalyFlags')})",
    )


#: Catastrophic floor for an IDP anchor on a DEGRADED / SEVERELY_DEGRADED row.
#: Evidence: replaying 19 data-refresh boards 2026-10-14..10-27 (each commit's
#: full tree), the worst any of the six IDP anchors reached was rank 213
#: (Kyle Hamilton) and value 2627 (Hamilton) -- all on degraded panels.  300 /
#: 1500 leave ~40% headroom on both sides of that range while still failing a
#: calibration collapse that shrinks every vote together (which the hull check
#: alone cannot see) or a blend that drops an elite defender off the
#: meaningful board.
_DEGRADED_IDP_MAX_RANK = 300
_DEGRADED_IDP_MIN_VALUE = 1500


def _source_reduced(meta: dict[str, Any]) -> bool:
    """True when this vote reached the blend at less than its base weight."""
    if meta.get("contributedToBlend") is False or meta.get("excludedReason"):
        return True
    base = float(meta.get("baseWeight") if meta.get("baseWeight") is not None else 1.0)
    return float(meta.get("appliedWeight") or 0.0) < base


def _assert_degradation_explained(
    case: unittest.TestCase,
    name: str,
    row: dict[str, Any],
    voting_status: dict[str, dict[str, Any]],
) -> None:
    """A degraded row must name WHY: every reduced / excluded / held source
    carries a stated reason, so a freshness, dataset-state or family-cap
    regression that degrades weights for no recorded cause still fails."""
    meta = row.get("sourceRankMeta") or {}
    reduced = [k for k, m in meta.items() if isinstance(m, dict) and _source_reduced(m)]
    # Observed by the row but not in its vote panel: held from voting.
    held = [k for k in (row.get("sourceOriginalRanks") or {}) if k not in meta]
    case.assertTrue(
        reduced or held,
        f"{name}: sourceWeightState={row.get('sourceWeightState')!r} but no "
        f"source is reduced, excluded or held -- unexplained degradation",
    )
    for key in reduced:
        if (meta.get(key) or {}).get("excludedReason"):
            continue
        entry = voting_status.get(key) or {}
        case.assertTrue(
            str(entry.get("reason") or "").strip()
            and (
                entry.get("voting") is False
                or float(entry.get("effectiveWeight") or 0.0)
                < float(entry.get("baseWeight") or 1.0)
            ),
            f"{name}: source {key!r} votes below base weight with no stated "
            f"reason in sourceVotingStatus ({entry!r})",
        )
    for key in held:
        entry = voting_status.get(key) or {}
        case.assertTrue(
            entry.get("voting") is False and str(entry.get("reason") or "").strip(),
            f"{name}: source {key!r} observed the row but is absent from its "
            f"vote panel with no stated non-voting reason ({entry!r})",
        )


def _voting_status_by_key(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = contract.get("sourceVotingStatus") or {}
    return {e["key"]: e for e in block.get("sources") or [] if isinstance(e, dict) and e.get("key")}


def _assert_anchor_bands(
    case: unittest.TestCase,
    name: str,
    row: dict[str, Any],
    bounds: dict[str, Any],
    voting_status: dict[str, dict[str, Any]],
) -> None:
    """The rank/value gate for one anchor (pinned by ``TestAnchorBandGate``)."""
    cur_rank = int(row.get("canonicalConsensusRank") or 0)
    cur_val = int(row.get("rankDerivedValue") or 0)
    case.assertGreater(cur_rank, 0, f"{name} has no rank")
    weight_state = str(row.get("sourceWeightState") or "")
    case.assertNotEqual(
        weight_state,
        "INSUFFICIENT_DATA",
        f"{name} has no voting evidence at all -- pipeline stopped pricing a top player?",
    )
    if weight_state in _DEGRADED_WEIGHT_STATES:
        # Only IDP anchors may take the degraded path.  The IDP panel is
        # thin (IDPTC, IDP Show, FantasyPros IDP, DraftSharks, DLF IDP) and
        # measurably degrades with vendor staleness; the offense panel has
        # ~14 families, so a degraded OFFENSE anchor is itself the signal of
        # a freshness / dataset_state / family-cap regression.
        case.assertTrue(
            bounds.get("idp"),
            f"{name}: offense anchor is {weight_state} (retainedAuthority="
            f"{row.get('retainedAuthority')}, dominant={row.get('dominantSource')}) "
            f"-- the offense panel should never degrade this far; suspect a "
            f"freshness / dataset_state / family-cap regression",
        )
        case.assertLessEqual(
            cur_rank,
            _DEGRADED_IDP_MAX_RANK,
            f"{name} canonicalConsensusRank={cur_rank} exceeds the degraded-panel "
            f"catastrophic floor {_DEGRADED_IDP_MAX_RANK}",
        )
        case.assertGreaterEqual(
            cur_val,
            _DEGRADED_IDP_MIN_VALUE,
            f"{name} rankDerivedValue={cur_val} below the degraded-panel "
            f"catastrophic floor {_DEGRADED_IDP_MIN_VALUE} -- calibration collapse?",
        )
        _assert_value_inside_contributing_votes(case, name, row)
        _assert_degradation_explained(case, name, row, voting_status)
        return
    case.assertLessEqual(
        cur_rank,
        int(bounds["max_rank"]),
        f"{name} canonicalConsensusRank={cur_rank} exceeds invariant "
        f"max_rank={bounds['max_rank']} on a NORMAL-weight panel -- likely "
        f"pipeline regression",
    )
    case.assertGreaterEqual(
        cur_val,
        int(bounds["min_value"]),
        f"{name} rankDerivedValue={cur_val} below invariant "
        f"min_value={bounds['min_value']} on a NORMAL-weight panel -- likely "
        f"calibration collapse",
    )


def _assert_bucket_explained_by_axes(
    case: unittest.TestCase, name: str, row: dict[str, Any]
) -> None:
    """B11: a published bucket is the WEAKEST of its five axes.

    Quarantine may only LOWER it further (``_validate_and_quarantine_rows``
    degrades to ``low``), never raise it.  So an unquarantined row's bucket
    equals the bottleneck axis, and a quarantined row's bucket is at or below
    it.  A bucket the axes cannot explain is a gate defect, whatever level it
    happens to read.
    """
    from src.api.confidence import AXES, CONFIDENCE_LEVELS  # noqa: PLC0415

    axes = row.get("confidenceAxes") or {}
    bucket = str(row.get("confidenceBucket") or "")
    case.assertEqual(
        set(axes),
        set(AXES),
        f"{name}: confidenceAxes={axes!r} does not carry the five B11 axes",
    )
    order = {lvl: i for i, lvl in enumerate(CONFIDENCE_LEVELS)}
    case.assertIn(bucket, order, f"{name}: unknown confidenceBucket {bucket!r}")
    weakest = min((axes[a] for a in AXES), key=lambda lvl: order[lvl])
    if row.get("quarantined"):
        case.assertLessEqual(
            order[bucket],
            order[weakest],
            f"{name}: quarantined row's bucket {bucket!r} exceeds its weakest axis {weakest!r}",
        )
    else:
        case.assertEqual(
            bucket,
            weakest,
            f"{name}: confidenceBucket={bucket!r} is not the weakest axis "
            f"({weakest!r}) of {axes!r}",
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
      * ``high_axes`` — B11 axes (``confidenceAxes``) that must stay
        ``high``.  This is where a coverage regression is caught; the
        bucket itself is the weakest axis and also moves with agreement
        and with withheld (stale) families, which it is meant to report.

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
        # The elite offense anchors used to pin ``allowed_buckets=("high",)``.
        # That pinned a LIVE-board outcome, not an invariant: under B11 the
        # bucket is the weakest of five axes, and since the 2026-10-07 owner
        # directive ("losing evidence never raises confidence") a withheld
        # family is seated in every share axis' denominator.  Measured on the
        # 2026-10-18 board: ``idpShowCombined`` was freshness-withheld on every
        # row, so Drake Maye / Jayden Daniels read agreement 10 of 14 families
        # (0.714 < EVIDENCE_SHARE_HIGH 0.75) -> "medium", with independence 13
        # families and coverage 13 of 14 both "high".  The bucket legitimately
        # moved; their evidence base did not.
        #
        # The intent the pin carried — catch a COVERAGE regression on a
        # top player — is kept exactly, and stated on the axes that measure
        # it: ``high_axes`` must stay "high" (>= 5 independent families,
        # >= 75% of eligible families covering).  A join / scrape regression
        # that strips a top player's sources still fails here; a market
        # disagreement or a stale family, which the bucket is SUPPOSED to
        # report, does not.  Every anchor's bucket must additionally be
        # explained by its axes (``_assert_bucket_explained_by_axes``).
        "Josh Allen": {
            "max_rank": 20,
            "min_value": 6000,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Drake Maye": {
            "max_rank": 20,
            "min_value": 6000,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Ja'Marr Chase": {
            "max_rank": 15,
            "min_value": 7000,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Bijan Robinson": {
            "max_rank": 15,
            "min_value": 6500,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Jahmyr Gibbs": {
            "max_rank": 20,
            "min_value": 6000,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Jayden Daniels": {
            "max_rank": 25,
            "min_value": 5500,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Puka Nacua": {
            "max_rank": 25,
            "min_value": 5500,
            "allowed_buckets": ("high", "medium"),
            "high_axes": ("independence", "coverage"),
        },
        "Malik Nabers": {"max_rank": 30, "min_value": 5000, "allowed_buckets": ("high", "medium")},
        "Brock Bowers": {"max_rank": 40, "min_value": 5000, "allowed_buckets": ("high", "medium")},
        "Patrick Mahomes": {
            "max_rank": 50,
            "min_value": 4000,
            "allowed_buckets": ("high", "medium"),
        },
        # ── IDP anchors ──
        # IDP rows sit deeper in the unified board (smaller pool, later
        # calibration) and their confidence buckets lean "low" because
        # the IDP source pool is narrower.  Bands are proportionally
        # more generous to absorb normal drift.  A regression that
        # collapses IDP value pricing (e.g. a calibration bug, shared-
        # market ladder breakage, IDPTC backbone failure) will trip
        # these.
        # IDP bands widened to absorb the Final Framework PR 3
        # structural shift (hierarchical anchor + α-shrunk subgroup).
        # IDP values now sit closer to the anchor's pricing than the
        # prior subgroup-dominant blend, which pushed some IDP anchors
        # 10-30 ranks deeper.  Bands still catch a real regression
        # (e.g. Garrett falling outside the top 150, value collapsing
        # below 2500).
        # Bands widened again after the 2026-04-20 multi-source
        # cross-market anchor shift (FG's combined-rank ordering
        # structurally underrates elite edge rushers — FG + DS both
        # put Parsons at rank ~300 on the combined ladder vs IDPTC's
        # ~65, which the count-aware mean-median can't fully absorb
        # when two of three anchor sources outlier in the same
        # direction).  A true pipeline regression still trips these
        # — Parsons cratering below rank 210 or his value falling
        # below 2800 would signal a real break.
        #
        # Widened again 2026-04-21 after the Hill scope masters were
        # refit to include yahooBoone + Fitzmaurice + DraftSharks as
        # training data.  Flatter GLOBAL (c 0.188 → 0.112) and IDP
        # (c 0.113 → 0.102) curves compress mid-pool value by ~10%
        # for elite IDPs like Parsons/Garrett who industry-consensus
        # rank below IDPTC's view of them.  Bands tracked to the new
        # neutral-calibration equilibrium.
        # Floor 3400 -> 3200 on 2026-10-25: with idpShowCombined freshness-
        # withheld (source health) Garrett priced 3381 on the
        # 20261025_120337 board; a calibration collapse is still far below
        # this (the bands above name 2500-2800 as the regression signal).
        "Myles Garrett": {
            "idp": True,
            "max_rank": 150,
            "min_value": 3200,
            "allowed_buckets": ("low", "medium", "high"),
        },
        "Will Anderson": {
            "idp": True,
            "max_rank": 120,
            "min_value": 3400,
            "allowed_buckets": ("low", "medium", "high"),
        },
        "Micah Parsons": {
            "idp": True,
            "max_rank": 210,
            "min_value": 2500,
            "allowed_buckets": ("low", "medium", "high"),
        },
        # Warner max_rank widened 150 → 165 on 2026-07-25 after the
        # weekly auto-refit (chore(calibration) 4b7d1545) resumed
        # following a month-long jam (see #522) and re-fit the scope
        # masters to a month of accumulated KTC drift in one step —
        # Warner tipped 150 → 152.  Same class as the 2026-04-21
        # entry above: an intentional curve refit, not a pipeline
        # regression.  Real headroom per the Roquan precedent rather
        # than a 2-rank chase; a genuine IDP-pricing break (Warner
        # cratering past 165 or value collapsing below 2800) still
        # trips.
        "Fred Warner": {
            "idp": True,
            "max_rank": 165,
            "min_value": 2800,
            "allowed_buckets": ("low", "medium", "high"),
        },
        # Roquan max_rank widened 160 → 175 on 2026-04-30 after a
        # routine scrape moved IDPTC's view of him 152 → 165.  That
        # small shift tipped the per-player Hampel outlier filter
        # (K=2.75 MADs, ``data_contract.py::_hampel_filter_per_player``)
        # over a threshold and rejected fantasyProsIdp's IDP-rank 8
        # call.  Same input source ranks; ~11-rank swing in consensus
        # depending on whether the most-bullish source survives
        # outlier rejection.  No upstream regression — Roquan is a
        # genuinely borderline Hampel case, so the band needed real
        # headroom rather than a 5-rank tweak.
        # 2026-05-16: widened 175 → 180.  The DraftSharks TEP
        # mis-flag fix (is_tep_premium False→True — DS is scraped
        # from the te-premium-superflex board, so its values already
        # bake in TE premium) correctly de-inflates DS TE values.
        # DS SF+IDP share one combined value ladder
        # (``ds_combined_rank_partner``), so de-inflating DS TEs
        # nudges DS-IDP players ~1 rank; Roquan (borderline Hampel,
        # above) tipped 175 → 176.  Real headroom, not a chase.
        "Roquan Smith": {
            "idp": True,
            "max_rank": 180,
            "min_value": 2300,
            "allowed_buckets": ("low", "medium", "high"),
        },
        "Kyle Hamilton": {
            "idp": True,
            "max_rank": 200,
            "min_value": 1800,
            "allowed_buckets": ("low", "medium", "high"),
        },
    }

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.by_name = _by_name(self.contract)
        self.voting_status = _voting_status_by_key(self.contract)

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
                cur_bucket = str(row.get("confidenceBucket") or "")
                allowed_buckets = tuple(bounds["allowed_buckets"])

                _assert_anchor_bands(self, name, row, bounds, self.voting_status)
                self.assertIn(
                    cur_bucket,
                    allowed_buckets,
                    f"{name} confidenceBucket={cur_bucket!r} not in "
                    f"allowed {allowed_buckets} — likely coverage regression",
                )
                axes = row.get("confidenceAxes") or {}
                for axis in bounds.get("high_axes", ()):
                    if axis == "coverage" and _coverage_shortfall_is_withheld_only(row):
                        # Source health, not a coverage regression: every
                        # missing eligible family OBSERVED the row and was
                        # withheld (stale/rejected).  Losing evidence lowers
                        # the axis by design (owner directive 2026-10-07); a
                        # join/scrape regression leaves families SILENT and
                        # still fails here.
                        continue
                    self.assertEqual(
                        axes.get(axis),
                        "high",
                        f"{name} confidenceAxes[{axis!r}]={axes.get(axis)!r} — "
                        f"likely coverage regression (reasons: "
                        f"{row.get('confidenceReasons')})",
                    )
                _assert_bucket_explained_by_axes(self, name, row)
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
                    if r.get("assetClass") == "offense" and r.get("canonicalConsensusRank")
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


class TestDegradedAnchorInvariant(unittest.TestCase):
    """Pins the source-independent half of the anchor check on synthetic rows."""

    @staticmethod
    def _row(value: int, *votes: tuple[int, float]) -> dict[str, Any]:
        meta = {
            f"s{i}": {"valueContribution": v, "appliedWeight": w} for i, (v, w) in enumerate(votes)
        }
        return {
            "rankDerivedValue": value,
            "sourceWeightState": "SEVERELY_DEGRADED",
            "sourceRankMeta": meta,
            "quarantined": False,
        }

    def test_value_inside_weighted_votes_passes(self) -> None:
        _assert_value_inside_contributing_votes(
            self, "x", self._row(2920, (5399, 0.34), (3677, 0.22), (1897, 0.93))
        )

    def test_zero_weight_vote_does_not_widen_the_hull(self) -> None:
        with self.assertRaises(AssertionError):
            _assert_value_inside_contributing_votes(
                self, "x", self._row(4100, (3600, 0.5), (2000, 0.9), (4184, 0.0))
            )

    def test_value_outside_votes_fails(self) -> None:
        with self.assertRaises(AssertionError):
            _assert_value_inside_contributing_votes(
                self, "x", self._row(1200, (5399, 0.34), (1897, 0.93))
            )

    def test_no_weighted_vote_fails(self) -> None:
        with self.assertRaises(AssertionError):
            _assert_value_inside_contributing_votes(self, "x", self._row(2000, (2000, 0.0)))

    def test_quarantined_row_fails(self) -> None:
        row = self._row(2920, (5399, 0.34), (1897, 0.93))
        row["quarantined"] = True
        with self.assertRaises(AssertionError):
            _assert_value_inside_contributing_votes(self, "x", row)

    def test_contributed_to_blend_false_does_not_widen_the_hull(self) -> None:
        row = self._row(4100, (3600, 0.5), (2000, 0.9))
        row["sourceRankMeta"]["s2"] = {
            "valueContribution": 4184,
            "appliedWeight": 0.7,
            "contributedToBlend": False,
        }
        with self.assertRaises(AssertionError):
            _assert_value_inside_contributing_votes(self, "x", row)


class TestAnchorBandGate(unittest.TestCase):
    """Pins the gate itself: an ``if True:`` exemption, an offense exemption or
    a dropped catastrophic floor must fail one of these."""

    _IDP = {"idp": True, "max_rank": 150, "min_value": 3200}
    _OFF = {"max_rank": 20, "min_value": 6000}
    _STATUS = {
        "tc": {
            "key": "tc",
            "voting": True,
            "baseWeight": 1.0,
            "effectiveWeight": 0.34,
            "reason": "Last genuine update 16 days ago: votes at 34%.",
        },
        "sh": {
            "key": "sh",
            "voting": False,
            "baseWeight": 1.0,
            "effectiveWeight": 0.0,
            "reason": "Last genuinely updated 68 days ago.",
        },
        "ds": {
            "key": "ds",
            "voting": True,
            "baseWeight": 1.0,
            "effectiveWeight": 0.93,
            "reason": "Last genuine update less than a day ago: votes at 93%.",
        },
        "dlf": {
            "key": "dlf",
            "voting": False,
            "baseWeight": 1.0,
            "effectiveWeight": 0.0,
            "reason": "Held from voting by an owner decision.",
        },
    }

    @staticmethod
    def _row(rank: int, value: int, state: str, **meta_over: Any) -> dict[str, Any]:
        meta = {
            "tc": {"valueContribution": 5399, "appliedWeight": 0.34, "baseWeight": 1.0},
            "sh": {
                "valueContribution": 4184,
                "appliedWeight": 0.0,
                "baseWeight": 1.0,
                "contributedToBlend": False,
                "excludedReason": "freshness_or_health_zero_weight",
            },
            "ds": {"valueContribution": 1897, "appliedWeight": 0.93, "baseWeight": 1.0},
        }
        meta.update(meta_over)
        return {
            "canonicalConsensusRank": rank,
            "rankDerivedValue": value,
            "sourceWeightState": state,
            "sourceRankMeta": meta,
            "sourceOriginalRanks": {"tc": 68, "sh": 89, "ds": 92, "dlf": 26},
            "quarantined": False,
        }

    def _gate(self, row: dict[str, Any], bounds: dict[str, Any], status=None) -> None:
        _assert_anchor_bands(self, "x", row, bounds, self._STATUS if status is None else status)

    def test_normal_row_inside_bands_passes(self) -> None:
        self._gate(self._row(10, 7000, "NORMAL"), self._OFF)

    def test_normal_row_past_max_rank_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 7000, "NORMAL"), self._OFF)

    def test_normal_idp_row_past_max_rank_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 3300, "NORMAL"), self._IDP)

    def test_normal_row_below_min_value_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._gate(self._row(10, 5000, "NORMAL"), self._OFF)

    def test_degraded_offense_anchor_fails(self) -> None:
        for state in ("DEGRADED", "SEVERELY_DEGRADED"):
            with self.subTest(state=state), self.assertRaises(AssertionError):
                self._gate(self._row(10, 2920, state), self._OFF)

    def test_insufficient_data_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 2920, "INSUFFICIENT_DATA"), self._IDP)

    def test_degraded_idp_today_passes(self) -> None:
        # The 2026-10-27 Garrett row, abridged.
        self._gate(self._row(180, 2920, "SEVERELY_DEGRADED"), self._IDP)

    def test_degraded_idp_past_catastrophic_rank_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._gate(self._row(_DEGRADED_IDP_MAX_RANK + 1, 2920, "SEVERELY_DEGRADED"), self._IDP)

    def test_degraded_idp_calibration_collapse_fails(self) -> None:
        # Every vote shrank together: inside the hull, below the floor.
        row = self._row(
            200,
            1100,
            "SEVERELY_DEGRADED",
            tc={"valueContribution": 1300, "appliedWeight": 0.34, "baseWeight": 1.0},
            ds={"valueContribution": 1000, "appliedWeight": 0.93, "baseWeight": 1.0},
        )
        with self.assertRaises(AssertionError):
            self._gate(row, self._IDP)

    def test_reduced_source_without_stated_reason_fails(self) -> None:
        status = dict(self._STATUS)
        status["tc"] = {**status["tc"], "reason": ""}
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 2920, "SEVERELY_DEGRADED"), self._IDP, status)

    def test_reduced_source_reported_at_full_weight_fails(self) -> None:
        status = dict(self._STATUS)
        status["tc"] = {**status["tc"], "effectiveWeight": 1.0}
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 2920, "SEVERELY_DEGRADED"), self._IDP, status)

    def test_held_source_without_non_voting_reason_fails(self) -> None:
        status = dict(self._STATUS)
        status["dlf"] = {**status["dlf"], "voting": True}
        with self.assertRaises(AssertionError):
            self._gate(self._row(180, 2920, "SEVERELY_DEGRADED"), self._IDP, status)

    def test_degraded_with_nothing_reduced_fails(self) -> None:
        row = self._row(
            180,
            2920,
            "SEVERELY_DEGRADED",
            tc={"valueContribution": 5399, "appliedWeight": 1.0, "baseWeight": 1.0},
            sh={"valueContribution": 4184, "appliedWeight": 1.0, "baseWeight": 1.0},
            ds={"valueContribution": 1897, "appliedWeight": 1.0, "baseWeight": 1.0},
        )
        row["sourceOriginalRanks"] = {"tc": 68, "sh": 89, "ds": 92}
        with self.assertRaises(AssertionError):
            self._gate(row, self._IDP)


if __name__ == "__main__":
    unittest.main()
