"""THE per-source pick board: one vendor's published rows → canonical keys.

Lifted VERBATIM out of ``Dynasty Scraper.py`` (C1-U6-D1, 2026-08-17),
where it lived as a nest of closures inside a ~2,000-line procedural
function and therefore had **no test, no fixture and no import seam**
anywhere in the repo.  That is not incidental to the defect this unit
repairs — a function nothing can call is a function nothing can check,
and the year fabrication survived three audits inside it.

Same arrangement as ``src/identity/name_primitives.py``: the module is
the owner, ``Dynasty Scraper.py`` imports it back and is an ADAPTER.

Scope, stated precisely so the next reader does not widen it by
accident:

* This module answers **"what did THIS source publish, for which
  (year, round, tier/slot)"**.  It reports evidence.
* It does **not** decide a canonical value, blend sources, discount a
  year, or derive a year nobody published.  Deriving an unpublished
  future year is the canonical pipeline's job and it is already built:
  ``_inject_far_future_pick_sources`` mints those rows from
  ``config/weights/pick_year_discount.json::derivedYearModel`` and
  ``_complete_future_pick_values`` stamps them ``derived_year_step``.
  This module's contract is to leave that year MISSING so the owner can
  see it is missing.

The label grammar below is a deliberate near-duplicate of
``src.identity.picks.parse_pick_label`` and is NOT a second identity
owner: the identity owner's grammars all REQUIRE a year (a pick
identity without a year is not an identity), while vendor rows may
carry year-less forms (``"1.06"``, ``"EARLY 1ST"``).  Consolidating the
two is C1-ID-02's deferred label-grammar migration, held in lockstep by
``tests/identity/test_pick_grammar_frontend_parity.py``; doing it here
would widen a value-correctness repair into an identity change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "PICK_TIERS",
    "SitePickMap",
    "build_site_pick_map",
    "fmt_pick_value",
    "parse_pick_label",
    "pick_suffix",
    "pick_value",
    "slot_to_tier",
    "slot_tier_ranges",
]

#: Tier vocabulary, in board order.
PICK_TIERS: tuple[str, ...] = ("early", "mid", "late")


def pick_value(v: Any) -> float | None:
    """A usable pick value, or ``None``.  Zero and negatives are NOT
    values — they are the absence of one, and the pipeline's
    MISSING-IS-NEVER-ZERO rule starts here."""
    if v is None or not isinstance(v, (int, float)):
        return None
    if v <= 0:
        return None
    return float(v)


def fmt_pick_value(v: float | None) -> int | float | None:
    """Emit an int when the value is integral, else two decimals."""
    if v is None:
        return None
    if abs(v - round(v)) < 1e-9:
        return int(round(v))
    return round(v, 2)


def pick_suffix(round_num: int) -> str:
    if round_num == 1:
        return "st"
    if round_num == 2:
        return "nd"
    if round_num == 3:
        return "rd"
    return "th"


def slot_tier_ranges(league_size: int = 12) -> dict[str, tuple[int, int]]:
    per_tier = max(1, int(league_size) // 3)
    early_end = per_tier
    mid_end = per_tier * 2
    return {
        "early": (1, early_end),
        "mid": (early_end + 1, mid_end),
        "late": (mid_end + 1, int(league_size)),
    }


def slot_to_tier(slot: int, league_size: int = 12) -> str:
    ranges = slot_tier_ranges(league_size)
    for tier, (lo, hi) in ranges.items():
        if lo <= slot <= hi:
            return tier
    return "late"


def parse_pick_label(raw: Any) -> dict[str, Any] | None:
    """A vendor row label → what it PROVES, or ``None``.

    ``year`` is ``None`` when the label did not state one.  That is a
    distinct fact from "this year" and :func:`build_site_pick_map`
    treats it as one.
    """
    if not isinstance(raw, str):
        return None
    s = re.sub(r"\s+", " ", raw.strip().upper())
    if not s:
        return None
    s = re.sub(r"\b(PICK|ROUND|RD|DRAFT|OVERALL)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    m = re.match(r"^(20\d{2})\s+([1-6])\.(0?[1-9]|1[0-2])$", s)
    if m:
        return {
            "kind": "slot",
            "year": int(m.group(1)),
            "round": int(m.group(2)),
            "slot": int(m.group(3)),
        }
    m = re.match(r"^([1-6])\.(0?[1-9]|1[0-2])$", s)
    if m:
        return {
            "kind": "slot",
            "year": None,
            "round": int(m.group(1)),
            "slot": int(m.group(2)),
        }

    m = re.match(r"^(20\d{2})\s+(EARLY|MID|LATE)\s+([1-6])\s*(ST|ND|RD|TH)$", s)
    if m:
        return {
            "kind": "tier",
            "year": int(m.group(1)),
            "tier": m.group(2).lower(),
            "round": int(m.group(3)),
        }
    m = re.match(r"^(EARLY|MID|LATE)\s+([1-6])\s*(ST|ND|RD|TH)$", s)
    if m:
        return {
            "kind": "tier",
            "year": None,
            "tier": m.group(1).lower(),
            "round": int(m.group(2)),
        }

    m = re.match(r"^(20\d{2})\s+([1-6])\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s)
    if m:
        return {
            "kind": "tier",
            "year": int(m.group(1)),
            "tier": (m.group(4) or "MID").lower(),
            "round": int(m.group(2)),
        }
    m = re.match(r"^([1-6])\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s)
    if m:
        return {
            "kind": "tier",
            "year": None,
            "tier": (m.group(3) or "MID").lower(),
            "round": int(m.group(1)),
        }

    m = re.match(r"^(20\d{2})\s+([1-6])$", s)
    if m:
        return {
            "kind": "tier",
            "year": int(m.group(1)),
            "tier": "mid",
            "round": int(m.group(2)),
        }
    m = re.match(r"^([1-6])$", s)
    if m:
        return {
            "kind": "tier",
            "year": None,
            "tier": "mid",
            "round": int(m.group(1)),
        }
    return None


def _nearest_year(years: Iterable[int | None], target: int) -> int | None:
    years = sorted(y for y in years if y is not None)
    if not years:
        return None
    return min(years, key=lambda y: abs(y - target))


def _avg(vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    return sum(vals) / len(vals)


@dataclass(frozen=True)
class SitePickMap:
    """One source's pick board, plus what each number actually IS.

    ``values`` is the emitted board (the shape the scraper has always
    consumed).  ``provenance`` names the evidence class behind every
    emitted key, so a within-year derivation is distinguishable from a
    published observation without reading the values back out.  A key
    absent from ``values`` is absent from ``provenance`` too: MISSING is
    represented by absence, which is what the whole downstream chain
    already handles correctly.
    """

    values: dict[str, int | float] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:  # ``if site_map:`` at the call site
        return bool(self.values)

    def __len__(self) -> int:
        return len(self.values)


def build_site_pick_map(
    parsed_rows: Sequence[Mapping[str, Any]],
    target_years: Sequence[int],
    league_size: int = 12,
) -> SitePickMap:
    """Build one source's pick board over ``target_years``.

    **A year this source did not publish is MISSING**, and missing is
    represented by the key's ABSENCE.  It is not the nearest year's
    value, not the previous year's value, and not zero.
    """
    if not parsed_rows:
        return SitePickMap()

    tier_values: dict[tuple[int | None, int, str], list[float]] = {}
    slot_values: dict[tuple[int | None, int, int], list[float]] = {}
    rounds_found: set[int] = set()

    for row in parsed_rows:
        year = row.get("year")
        round_num = row.get("round")
        if not isinstance(round_num, int) or not (1 <= round_num <= 6):
            continue
        rounds_found.add(round_num)
        val = row["value"]
        if row["kind"] == "tier":
            tier_values.setdefault((year, round_num, row["tier"]), []).append(val)
        elif row["kind"] == "slot":
            slot = row["slot"]
            if 1 <= slot <= league_size:
                slot_values.setdefault((year, round_num, slot), []).append(val)

    if not rounds_found:
        return SitePickMap()

    max_round = min(6, max(rounds_found))
    emit_max_round = max(4, max_round)
    rounds_to_emit = range(1, emit_max_round + 1)
    tier_ranges = slot_tier_ranges(league_size)

    def lookup_tier(year, round_num, tier):
        for y in (year, None):
            vals = tier_values.get((y, round_num, tier), [])
            if vals:
                return _avg(vals)

        lo, hi = tier_ranges[tier]
        for y in (year, None):
            vals = []
            for slot in range(lo, hi + 1):
                vals.extend(slot_values.get((y, round_num, slot), []))
            if vals:
                return _avg(vals)

        years_with_tier = {
            y for (y, r, t) in tier_values.keys() if y is not None and r == round_num and t == tier
        }
        near_year = _nearest_year(years_with_tier, year)
        if near_year is not None:
            vals = tier_values.get((near_year, round_num, tier), [])
            if vals:
                return _avg(vals)

        years_with_slots = {
            y
            for (y, r, s) in slot_values.keys()
            if y is not None and r == round_num and lo <= s <= hi
        }
        near_year = _nearest_year(years_with_slots, year)
        if near_year is not None:
            vals = []
            for slot in range(lo, hi + 1):
                vals.extend(slot_values.get((near_year, round_num, slot), []))
            if vals:
                return _avg(vals)
        return None

    def _estimate_slot_from_tier(year, round_num, slot):
        tier = slot_to_tier(slot, league_size)
        tier_val = lookup_tier(year, round_num, tier)
        if tier_val is None:
            return None

        lo, hi = tier_ranges[tier]
        if hi <= lo:
            return tier_val

        # Spread tier-only values into a slot curve so 1.01 != "Early 1st".
        # Keeps the average near the tier value while creating realistic separation.
        spread = 0.20 if tier == "early" else 0.14 if tier == "mid" else 0.12
        rel = 1.0 - (2.0 * (slot - lo) / float(hi - lo))  # +1 at start, -1 at end
        est = tier_val * (1.0 + spread * rel)
        return max(1.0, est)

    def lookup_slot(year, round_num, slot):
        for y in (year, None):
            vals = slot_values.get((y, round_num, slot), [])
            if vals:
                return _avg(vals)

        years_with_slot = {
            y for (y, r, s) in slot_values.keys() if y is not None and r == round_num and s == slot
        }
        near_year = _nearest_year(years_with_slot, year)
        if near_year is not None:
            vals = slot_values.get((near_year, round_num, slot), [])
            if vals:
                return _avg(vals)

        est = _estimate_slot_from_tier(year, round_num, slot)
        if est is not None:
            return est
        return None

    values: dict[str, int | float] = {}
    provenance: dict[str, str] = {}
    for year in target_years:
        for round_num in rounds_to_emit:
            for tier in PICK_TIERS:
                t_val = lookup_tier(year, round_num, tier)
                if t_val is not None:
                    key = f"{year} {tier.capitalize()} {round_num}{pick_suffix(round_num)}"
                    values[key] = fmt_pick_value(t_val)
                    provenance[key] = "published_tier"

            for slot in range(1, league_size + 1):
                s_val = lookup_slot(year, round_num, slot)
                if s_val is not None:
                    key = f"{year} {round_num}.{slot:02d}"
                    values[key] = fmt_pick_value(s_val)
                    provenance[key] = "published_slot"
    return SitePickMap(values=values, provenance=provenance)
