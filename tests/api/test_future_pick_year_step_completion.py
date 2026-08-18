"""The future-pick horizon guarantee must not depend on which vendor
keys survived in the raw scrape JSON.

INCIDENT (2026-08-18T17:11Z refresh, reproduced on pristine ``main``).
``scripts/validate_api_contract.py --lane structural`` — the BLOCKING
pull-request gate — reported 20 errors::

    pick_completeness_census:2029 Early 2nd:missing_or_unpriced
    pick_completeness_census:2029 Round 2:missing_or_unpriced
    ... (every tier and generic grade, rounds 2 through 6)

turning every open pull request red at once.

WHAT WAS ACTUALLY BROKEN.  Not the evidence.  At that commit BOTH vendor
pick boards were complete on disk — 36 ``ktcSfTep`` rows and 84
``idpTradeCalc`` rows, covering every 2028 tier through round 4.  What
thinned out was the scrape's *in-JSON* per-source pick values, and that
is the only population ``_inject_far_future_pick_sources`` can see: it
clones the template year's raw entry, so a synthetic far-future row can
only ever vote on the in-JSON sources.  ``ktcSfTep``'s pick values reach
a row through the CSV enrichment instead, and the CSVs correctly carry
no far-future year with which to enrich a synthetic row.  With the
in-JSON side thinned, the 2029 rows in rounds 2-6 had NO voting source
at all and blended to ``None`` — on a board whose evidence was intact.

The round-step rung could not repair it either: ``derivedRoundModel``
configures steps only for the vendor-uncovered rounds (5-6), so rounds
2-4 had no rung, and rounds 5-6 then found their round-4 basis missing.

THE REPAIR is a year-step rung in ``_complete_future_pick_values``,
anchored on the CANONICAL BOARD value of the nearest priced earlier
future year rather than on whichever raw keys survived — same
``derivedYearModel`` family, same measured per-(tier, round) step,
compounded across the gap.

These tests are deterministic unit tests over the completion owner: no
network, no live board, no absolute counts.  They assert the invariant
(*every* valid cell), and each one proves it inspected a non-empty set
before asserting anything about it.
"""

from __future__ import annotations

import unittest

from src.api.confidence import CONFIDENCE_BASES
from src.api.data_contract import (
    _complete_future_pick_values,
    _load_pick_year_discount,
    _round_suffix,
    _year_step_for,
)

TIERS = ("Early", "Mid", "Late")
VENDOR_ROUNDS = (1, 2, 3, 4)  # the rounds both pick markets publish
ALL_ROUNDS = (1, 2, 3, 4, 5, 6)


def _tier_name(year: int, tier: str, rnd: int) -> str:
    return f"{year} {tier} {_round_suffix(rnd)}"


def _pick_row(name: str, value: float | None) -> dict:
    """A pick row carrying only what the completion owner reads."""
    return {
        "assetClass": "pick",
        "canonicalName": name,
        "displayName": name,
        "rankDerivedValue": value,
    }


def _board(
    current_year: int,
    priced: dict[str, float],
    *,
    unpriced: list[str],
) -> tuple[list[dict], dict]:
    """Build a pick-only ``playersArray`` plus its legacy mirror."""
    rows = [_pick_row(n, v) for n, v in priced.items()]
    rows += [_pick_row(n, None) for n in unpriced]
    legacy = {r["canonicalName"]: dict(r) for r in rows}
    return rows, legacy


def _healthy_template_year(year: int, base: float = 4000.0) -> dict[str, float]:
    """A fully priced vendor-covered year: 3 tiers x rounds 1-4."""
    out: dict[str, float] = {}
    for t_i, tier in enumerate(TIERS):
        for rnd in VENDOR_ROUNDS:
            # strictly decreasing across tiers and across rounds
            out[_tier_name(year, tier, rnd)] = round(base * (0.9**t_i) * (0.65 ** (rnd - 1)), 1)
    return out


def _by_name(rows: list[dict]) -> dict[str, dict]:
    return {str(r.get("canonicalName")): r for r in rows}


def _value(rows: list[dict], name: str):
    row = _by_name(rows).get(name)
    return None if row is None else row.get("rankDerivedValue")


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


class TestYearStepCompletion(unittest.TestCase):
    """The incident, reproduced at the owner and pinned green."""

    def test_reproduces_incident_shape_and_completes_every_cell(self):
        """RED shape: template year priced, far-future rows exist but the
        blend gave them nothing.  Every valid cell must come back finite.
        """
        current = 2026
        horizon_year = current + 3
        priced = _healthy_template_year(current + 2)  # 2028, vendor-covered
        # Every 2029 tier row exists (the injection created them) but the
        # blend priced none of them — the measured incident state.
        unpriced = [_tier_name(horizon_year, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        self.assertTrue(unpriced, "non-vacuity: the RED set must be non-empty")
        for name in unpriced:
            self.assertIsNone(_value(rows, name), f"{name} must start unpriced")

        _complete_future_pick_values(rows, legacy, current)

        for name in unpriced:
            self.assertTrue(
                _finite(_value(rows, name)),
                f"{name} left unpriced after completion",
            )
        # ...and the generic grade for every round.
        for rnd in ALL_ROUNDS:
            generic = f"{horizon_year} Round {rnd}"
            self.assertTrue(
                _finite(_value(rows, generic)),
                f"{generic} left unpriced after completion",
            )

    def test_derived_value_equals_the_approved_model(self):
        """The number is reproducible from the config, not invented."""
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        cfg = _load_pick_year_discount()
        checked = 0
        for tier in TIERS:
            for rnd in VENDOR_ROUNDS:
                basis = priced[_tier_name(template, tier, rnd)]
                expected = int(round(basis * _year_step_for(tier, rnd, cfg) ** (target - template)))
                self.assertEqual(
                    _value(rows, _tier_name(target, tier, rnd)),
                    expected,
                    f"{_tier_name(target, tier, rnd)} is not basis x yearStep",
                )
                checked += 1
        self.assertEqual(checked, len(TIERS) * len(VENDOR_ROUNDS))

    def test_multi_year_gap_compounds_the_step(self):
        """A two-year gap is ``step ** 2``, not ``step``."""
        current = 2026
        template, target = current + 1, current + 3  # 2027 -> 2029, gap 2
        priced = _healthy_template_year(template)
        unpriced = [
            _tier_name(y, t, r) for y in (current + 2, target) for t in TIERS for r in ALL_ROUNDS
        ]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        cfg = _load_pick_year_discount()
        # 2028 fills from 2027 (gap 1); 2029 then fills from 2028 (gap 1),
        # so the compounded product must equal step**2 off the template.
        for tier in TIERS:
            for rnd in VENDOR_ROUNDS:
                basis = priced[_tier_name(template, tier, rnd)]
                step = _year_step_for(tier, rnd, cfg)
                mid = int(round(basis * step))
                self.assertEqual(_value(rows, _tier_name(current + 2, tier, rnd)), mid)
                self.assertEqual(
                    _value(rows, _tier_name(target, tier, rnd)), int(round(mid * step))
                )

    def test_direct_evidence_outranks_derivation(self):
        """A row that already carries a value is never touched."""
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        # A *directly priced* far-future row, deliberately far off the model.
        direct_name = _tier_name(target, "Early", 2)
        priced[direct_name] = 12.0
        unpriced = [
            _tier_name(target, t, r)
            for t in TIERS
            for r in ALL_ROUNDS
            if _tier_name(target, t, r) != direct_name
        ]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        self.assertEqual(_value(rows, direct_name), 12.0, "direct evidence was overwritten")
        row = _by_name(rows)[direct_name]
        self.assertEqual(
            (row.get("pickValueProvenance") or {}).get("class"),
            "direct_market_blend",
            "a directly priced row must not be relabelled as derived",
        )
        # non-vacuity: the surrounding cells DID derive.
        self.assertTrue(_finite(_value(rows, _tier_name(target, "Mid", 2))))

    def test_no_future_basis_stays_unavailable_and_never_zero(self):
        """MISSING IS NEVER ZERO.  With no earlier *future* year priced,
        the row keeps no value and says why."""
        current = 2026
        target = current + 3
        # Only the CURRENT draft year is priced.  Its rows are
        # rookie-pool-tethered slot picks — a different quantity — and a
        # vendor-priced year takes no year discount, so it may not be a
        # basis.  Nothing else exists to step from.
        priced = _healthy_template_year(current)
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        for name in unpriced:
            value = _value(rows, name)
            self.assertIsNone(value, f"{name} must stay unpriced, got {value!r}")
            self.assertNotEqual(value, 0, f"{name} became zero-as-missing")
            prov = _by_name(rows)[name].get("pickValueProvenance") or {}
            self.assertEqual(prov.get("class"), "unavailable", f"{name} provenance: {prov}")
            self.assertTrue(prov.get("reason"), f"{name} unavailable with no reason")

    def test_current_year_is_never_used_as_a_basis(self):
        """Explicitly: the current draft year cannot leak into a future
        year's derivation even when it is the only priced year."""
        current = 2026
        priced = _healthy_template_year(current)
        first_future = _tier_name(current + 1, "Early", 1)
        rows, legacy = _board(current, priced, unpriced=[first_future])

        _complete_future_pick_values(rows, legacy, current)

        self.assertIsNone(_value(rows, first_future))
        prov = _by_name(rows)[first_future].get("pickValueProvenance") or {}
        self.assertEqual(prov.get("class"), "unavailable")


class TestProvenanceAndOrdering(unittest.TestCase):
    def test_every_derived_row_carries_distinguishable_provenance(self):
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        seen_year, seen_round = 0, 0
        for name in unpriced:
            row = _by_name(rows)[name]
            prov = row.get("pickValueProvenance") or {}
            self.assertIn(
                prov.get("class"),
                {"derived_year_step", "derived_round_step"},
                f"{name} derived without a derivation class: {prov}",
            )
            self.assertEqual(prov.get("classification"), "PRIOR", f"{name}: {prov}")
            self.assertTrue(prov.get("basis"), f"{name} names no basis: {prov}")
            self.assertTrue(prov.get("family"), f"{name} names no family: {prov}")
            if prov["class"] == "derived_year_step":
                seen_year += 1
                # The board-anchored rung must be distinguishable from
                # the injection-time derivation of the SAME family.
                self.assertEqual(prov.get("appliedTo"), "canonical_board_value", f"{name}")
                self.assertEqual(prov.get("basisYear"), template, f"{name}")
            else:
                seen_round += 1
            self.assertIn(row.get("confidenceBasis"), CONFIDENCE_BASES, f"{name}")
        self.assertTrue(seen_year, "non-vacuity: no year-step derivation exercised")
        self.assertTrue(seen_round, "non-vacuity: no round-step derivation exercised")

    def test_derived_year_step_is_a_registered_confidence_basis(self):
        self.assertIn("derived_year_step", CONFIDENCE_BASES)

    def test_tier_ordering_survives_the_year_step(self):
        """An earlier pick must stay worth more than a later one — the
        census' companion ``pick_tier_ordering`` check."""
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        checked = 0
        for rnd in ALL_ROUNDS:
            early, mid, late = (_value(rows, _tier_name(target, t, rnd)) for t in TIERS)
            self.assertTrue(
                early > mid > late,
                f"round {rnd} tier ordering inverted: {early} / {mid} / {late}",
            )
            checked += 1
        self.assertEqual(checked, len(ALL_ROUNDS))

    def test_generic_grade_is_the_mean_of_its_three_tiers(self):
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        for rnd in ALL_ROUNDS:
            tiers = [_value(rows, _tier_name(target, t, rnd)) for t in TIERS]
            self.assertEqual(
                _value(rows, f"{target} Round {rnd}"),
                int(round(sum(tiers) / 3)),
            )


class TestGenericAcrossTheClock(unittest.TestCase):
    """The repair may not be keyed to 2029, or to any literal year."""

    def test_horizon_self_rolls_for_any_current_year(self):
        cfg = _load_pick_year_discount()
        horizon = int(cfg.get("horizonYears") or 3)
        exercised = 0
        for current in (2026, 2027, 2030, 2044):
            template = current + horizon - 1
            target = current + horizon
            priced = _healthy_template_year(template)
            unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
            rows, legacy = _board(current, priced, unpriced=unpriced)

            _complete_future_pick_values(rows, legacy, current)

            for name in unpriced:
                self.assertTrue(
                    _finite(_value(rows, name)),
                    f"current_year={current}: {name} left unpriced",
                )
                exercised += 1
        self.assertEqual(exercised, 4 * len(TIERS) * len(ALL_ROUNDS))

    def test_source_family_loss_does_not_erase_unrelated_derived_rows(self):
        """Losing coverage for one round must not take the others with it."""
        current = 2026
        template, target = current + 2, current + 3
        priced = _healthy_template_year(template)
        # Simulate a vendor dropping round 3 for the template year too:
        # that column has no basis anywhere, the rest still derive.
        for tier in TIERS:
            priced.pop(_tier_name(template, tier, 3))
        unpriced = [_tier_name(target, t, r) for t in TIERS for r in ALL_ROUNDS]
        unpriced += [_tier_name(template, t, 3) for t in TIERS]
        rows, legacy = _board(current, priced, unpriced=unpriced)

        _complete_future_pick_values(rows, legacy, current)

        survived = 0
        for tier in TIERS:
            for rnd in (1, 2, 4):
                self.assertTrue(
                    _finite(_value(rows, _tier_name(target, tier, rnd))),
                    f"{_tier_name(target, tier, rnd)} was erased by an unrelated gap",
                )
                survived += 1
            # The genuinely evidence-free column refuses, and never as 0.
            for year in (template, target):
                self.assertIsNone(_value(rows, _tier_name(year, tier, 3)))
        self.assertEqual(survived, len(TIERS) * 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
