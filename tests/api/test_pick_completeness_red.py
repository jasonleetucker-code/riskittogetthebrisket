"""C1-U6 RED: valid picks through 2029 without a finite canonical value.

The C1-U6 execution-map RED is "a valid 2029 pick with no finite
canonical value".  Reproduced here through the ACTUAL production
consumer path — ``build_api_data_contract`` on the newest scraper
export, the same call ``server.py`` makes — plus the adjacent real
defect classes the census measured on the 2026-08-16 board:

RED-1  (cap truncation) — synthetic 2029 tier rows that DID vote
       (idpTradeCalc clone) and DID receive the year discount stamp
       sorted below the value-stamping cutoff and published
       ``rankDerivedValue: None``.  Measured: 2029 Mid 3rd, Late 3rd,
       Early 4th, Mid 4th, Late 4th — while their 2028 template rows
       are finite (e.g. 2028 Early 4th = 1632).

RED-2  (no voting source for future rounds 5-6) — every 2027/2028/2029
       Early/Mid/Late 5th/6th row has zero voting sources: KTC and
       IDPTC publish future tiers for rounds 1-4 only, and the raw
       payload's ``ktc`` key on those rows is the scraper's own model
       composite (retired from voting 2026-04-28).  18 valid league
       picks (the leagues draft 6 rounds) publish no value.

RED-3  (uncalibrated year discount on a cloned price) — audit
       V-12/C-11, named in ``_apply_pick_year_discount_to_blend``'s own
       docstring: 2029 = clone(2028) x 0.53, where 0.53 is the
       offset-3 entry of a hand-authored decay curve.  The market's own
       observable one-year step between two unknown classes
       (2028/2027, both vendors, 34 archive dates, rounds 1-4) is
       median 0.841 (KTC 0.855, IDPTC 0.837) — the incumbent is ~37%
       more pessimistic than every observed cell (range 0.71-0.90).

RED-4  (clone presents the template year's vendor values verbatim) —
       a 2029 row's ``canonicalSiteValues.ktc``/``idpTradeCalc`` carry
       2028's numbers unchanged, so market-anchor consumers (angle's
       ktc fallback) read an UNDISCOUNTED anchor against a discounted
       model value — manufactured "arbitrage" on far-future picks.

RED-5  (no generic-grade value) — ``market_resolution`` answers an
       unknown slot with the GENERIC grade (C1-U3, frozen), but the
       board publishes no generic-grade row and no resolver exists, so
       the honest representation of every unrealized future league pick
       has no canonical value at all.

STATUS: CLOSED.  Every class above was reproduced on the live payload
before the repair (evidence: ``docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md``
§RED); the GREEN counterparts live in ``test_pick_completeness.py``.
These tests now assert the defect classes are UNREPRESENTABLE, in the
same style as ``tests/identity/test_pick_identity_red.py`` /
``tests/history/test_temporal_red.py``.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import build_api_data_contract
from src.identity.picks import parse_board_tier_name

_REPO = Path(__file__).resolve().parents[2]

_contract_cache: dict[str, Any] | None = None


def _load_contract() -> dict[str, Any] | None:
    global _contract_cache
    if _contract_cache is not None:
        return _contract_cache
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    _contract_cache = build_api_data_contract(raw)
    return _contract_cache


def _pick_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in contract.get("playersArray", []) if r.get("assetClass") == "pick"]


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0


class TestRed1CapTruncationUnrepresentable(unittest.TestCase):
    """A pick row that voted must publish its value even when it sorts
    past ``OVERALL_RANK_LIMIT`` — the cap is a RANK concept.  Before the
    repair, 5 voted 2029 rows (Mid/Late 3rd, Early/Mid/Late 4th)
    published ``rankDerivedValue: None`` with the discount stamp already
    on the row."""

    def test_every_voted_pick_row_publishes_a_finite_value(self) -> None:
        contract = _load_contract()
        if contract is None:
            self.skipTest("no scraper export available")
        offenders = [
            r.get("canonicalName")
            for r in _pick_rows(contract)
            if r.get("sourceRanks")
            and not r.get("pickGenericSuppressed")
            and not _finite(r.get("rankDerivedValue"))
        ]
        self.assertEqual(
            offenders,
            [],
            f"voted pick rows published without a finite value: {offenders}",
        )


class TestRed2FutureDeepRoundsUnrepresentable(unittest.TestCase):
    """Future-year rounds 5-6 have no vendor evidence (KTC/IDPTC stop at
    round 4), yet the leagues draft 6 rounds — a valid league pick must
    still price, via the explicitly-PRIOR round-step derivation, never
    as ``None`` and never as ``0``."""

    def test_future_tier_rows_all_rounds_have_finite_values(self) -> None:
        contract = _load_contract()
        if contract is None:
            self.skipTest("no scraper export available")
        offenders = []
        for r in _pick_rows(contract):
            parsed = parse_board_tier_name(r.get("canonicalName") or "")
            if parsed is None:
                continue
            if r.get("pickGenericSuppressed"):
                continue  # current-year tiers alias to slot rows
            if not _finite(r.get("rankDerivedValue")):
                offenders.append(r.get("canonicalName"))
        self.assertEqual(
            offenders,
            [],
            f"future tier rows without a finite canonical value: {offenders}",
        )


class TestRed3UncalibratedCloneDiscountRetired(unittest.TestCase):
    """The 0.53 offset-3 multiplier on a cloned 2028 price is retired.
    Synthetic far-future values now derive per measured vendor year-step
    cells (config ``derivedYearModel``, classification PRIOR with the
    extrapolation assumption named), so a 2029 tier value must sit at
    its basis row x the configured cell step — never x 0.53."""

    def test_derived_2029_value_uses_measured_year_step(self) -> None:
        contract = _load_contract()
        if contract is None:
            self.skipTest("no scraper export available")
        rows = {r.get("canonicalName"): r for r in _pick_rows(contract)}
        r29 = rows.get("2029 Early 1st")
        r28 = rows.get("2028 Early 1st")
        if not (r29 and r28 and _finite(r28.get("rankDerivedValue"))):
            self.skipTest("2029/2028 Early 1st not on this board")
        self.assertTrue(_finite(r29.get("rankDerivedValue")))
        ratio = float(r29["rankDerivedValue"]) / float(r28["rankDerivedValue"])
        # Measured vendor year-step cells span 0.71-0.90; the retired
        # incumbent (0.53 on the clone) sits far outside.  The blend of
        # a single-source clone differs from the 2-source template blend
        # by ~1-2%, so allow that slack around the configured band.
        self.assertGreater(
            ratio, 0.65, f"2029/2028 ratio {ratio:.3f} — incumbent 0.53 resurrected?"
        )
        self.assertLess(ratio, 0.95, f"2029/2028 ratio {ratio:.3f} — year step lost entirely?")


class TestRed4CloneAnchorAsymmetryUnrepresentable(unittest.TestCase):
    """A synthetic-year row's per-source display values must carry the
    SAME derivation as its model value — never the template year's
    numbers verbatim (which handed market-anchor consumers an
    undiscounted anchor against a discounted model value)."""

    def test_synthetic_year_site_values_are_stepped(self) -> None:
        contract = _load_contract()
        if contract is None:
            self.skipTest("no scraper export available")
        rows = {r.get("canonicalName"): r for r in _pick_rows(contract)}
        r29 = rows.get("2029 Early 1st")
        r28 = rows.get("2028 Early 1st")
        if not (r29 and r28):
            self.skipTest("2029/2028 Early 1st not on this board")
        v29 = (r29.get("canonicalSiteValues") or {}).get("idpTradeCalc")
        v28 = (r28.get("canonicalSiteValues") or {}).get("idpTradeCalc")
        if not (_finite(v29) and _finite(v28)):
            self.skipTest("idpTradeCalc values absent")
        self.assertLess(
            float(v29),
            float(v28) * 0.999,
            "2029 clone carries 2028's vendor value verbatim — the "
            "market-anchor asymmetry (RED-4) is back",
        )


class TestRed5GenericGradeHasCanonicalValue(unittest.TestCase):
    """``market_resolution`` answers an unknown slot with the GENERIC
    grade; the board must therefore publish a finite canonical value for
    the generic grade of every future year/round (the honest
    representation of an unrealized league pick)."""

    def test_future_generic_rows_exist_and_price(self) -> None:
        contract = _load_contract()
        if contract is None:
            self.skipTest("no scraper export available")
        rows = {r.get("canonicalName"): r for r in _pick_rows(contract)}
        # Established from the board's own current draft year rather
        # than a literal, so the test rolls with the data.
        years = sorted(
            {parse_board_tier_name(n)[0] for n in rows if parse_board_tier_name(n) is not None}
        )
        current = min(years) if years else None
        if current is None:
            self.skipTest("no tier rows on this board")
        future_years = [y for y in years if y > current]
        self.assertTrue(future_years, "no future tier years on the board")
        offenders = []
        for year in future_years:
            for rnd in range(1, 7):
                name = f"{year} Round {rnd}"
                row = rows.get(name)
                if row is None or not _finite(row.get("rankDerivedValue")):
                    offenders.append(name)
        self.assertEqual(offenders, [], f"generic-grade rows missing or unpriced: {offenders}")


if __name__ == "__main__":
    unittest.main()
