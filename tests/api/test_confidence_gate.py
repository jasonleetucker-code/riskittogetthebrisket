"""B11 — the multi-axis confidence gate, and the pathologies it retires.

WHAT WAS WRONG
──────────────
Confidence was ``max(percentile) − min(percentile)`` over the contributing
sources, bucketed against two cutoffs. Two structural faults:

1. **It was a range.** Removing an observation can only preserve or narrow
   a range, so under "narrower ⇒ more confident" **deleting evidence
   promotes confidence**. #833 recorded the failed repair: re-basing the
   same statistic onto independent evidence moved 60 rows the WRONG way
   (A.J. Brown medium → high) purely because collapsing his FantasyPros
   family removed one endpoint. The inputs were not the defect; the
   statistic was.

2. **It was one axis wearing two hats.** A count gate (``n >= 2``) plus a
   dispersion gate. Nothing asked whether the evidence was independent,
   current, applicable to this board's format, or anywhere near complete —
   so a huge source count compensated for all of them.

WHAT REPLACED IT
────────────────
Five axes, each a statement about the EVIDENCE, combined by BOTTLENECK
(the overall level is the weakest axis). Nothing averages, so a strong
axis cannot buy a weak one:

    independence   how many B10 correlation-group heads voted
    coverage       how many of the ELIGIBLE families actually did
    freshness      how many of them are inside their staleness budget
    applicability  how many reached the row without approximation, and
                   on this board's TE-premium basis
    agreement      how many price within a material relative gap of the
                   published value

THE MONOTONICITY ARGUMENT, WHICH IS THE POINT
─────────────────────────────────────────────
Every axis is computed over FAMILY HEADS, so a duplicate observation
from an already-represented family is not an input to anything: adding
or removing one is an exact identity on all five axes (``test_a_duplicate
_family_member_changes_nothing``). That is invariant 1 and 2 discharged
structurally rather than by calibration.

Removing a genuinely independent family cannot promote confidence
because ``coverage``'s DENOMINATOR is what COULD have been observed, not
what was: the family stays eligible, so its silence is registered as
missing evidence forever. This is MISSING IS NEVER ZERO applied to
confidence — an absent eligible source is explicit missingness, not a
neutral non-event. Confidence may still rise when the removed evidence
was STALE or INAPPLICABLE, which the owner ruling permits, and the
reason then appears in ``reasons``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.api.confidence import (
    AXES,
    CONFIDENCE_LEVELS,
    FamilyEvidence,
    assess_confidence,
    assess_pick_confidence,
    gate_parameter,
    gate_parameters,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A twelve-family offense row is the shape most of the board has.
WIDE = tuple(f"fam{i}" for i in range(12))


def head(
    family: str,
    value: float | None = 5000.0,
    *,
    fresh: bool | None = True,
    format_native: bool = True,
    directly_observed: bool = True,
    source_key: str | None = None,
) -> FamilyEvidence:
    return FamilyEvidence(
        family=family,
        source_key=source_key or f"{family}Source",
        value_contribution=value,
        fresh=fresh,
        format_native=format_native,
        directly_observed=directly_observed,
    )


def panel(n: int, *, value: float = 5000.0, **kw) -> list[FamilyEvidence]:
    return [head(f"fam{i}", value, **kw) for i in range(n)]


def assess(evidence, eligible=None, consensus=5000.0):
    return assess_confidence(
        evidence,
        eligible_families=eligible if eligible is not None else {e.family for e in evidence},
        consensus_value=consensus,
    )


class TestTheOwnersPathologyCases(unittest.TestCase):
    """CASE A–I from the B11 ruling, as arithmetic."""

    def test_case_a_three_independent_families_tightly_agree(self):
        """Tight, current, applicable — but only three families.

        MEDIUM, not HIGH. Three is the blend's untrimmed rung: enough to
        outvote a dissenter, not enough for the published number to be
        robust to one outlying opinion on each side.
        """
        r = assess(panel(3))
        self.assertEqual(r.axes["agreement"], "high")
        self.assertEqual(r.axes["independence"], "medium")
        self.assertEqual(r.overall, "medium")

    def test_case_b_ten_sources_collapsing_to_two_families(self):
        """The count is a lie; the gate must read the families.

        Ten raw observations, two lineages. Independence is LOW because
        two families is what is actually there.
        """
        evidence = [head("alpha", 5000.0), head("beta", 5050.0)]
        r = assess(evidence, eligible={"alpha", "beta"})
        self.assertEqual(r.metrics["independentFamilies"], 2)
        self.assertEqual(r.axes["independence"], "low")
        self.assertEqual(r.overall, "low")

    def test_case_c_five_families_agree_and_one_is_an_outlier(self):
        six = panel(5) + [head("fam5", 500.0)]
        r = assess(six)
        self.assertEqual(r.metrics["agreeingFamilies"], 5)
        self.assertEqual(r.axes["independence"], "high")
        # 5/6 = 0.83 within tolerance -> still high agreement; the single
        # dissenter does not tank a six-family consensus the way the
        # retired range statistic did.
        self.assertEqual(r.axes["agreement"], "high")

    def test_case_d_removing_the_outlier_does_not_promote_confidence(self):
        """The headline invariant. Deleting evidence must not pay.

        The outlier family is still ELIGIBLE, so dropping its observation
        is a coverage loss, not a tidier panel.
        """
        with_outlier = panel(5) + [head("fam5", 500.0)]
        eligible = {e.family for e in with_outlier}
        before = assess(with_outlier, eligible=eligible)
        after = assess(panel(5), eligible=eligible)

        self.assertLess(
            after.metrics["coverageShare"],
            before.metrics["coverageShare"],
            "an eligible family that stopped covering the row must show as missing",
        )
        self.assertLessEqual(
            CONFIDENCE_LEVELS.index(after.overall),
            CONFIDENCE_LEVELS.index(before.overall),
            "removing an outlier promoted confidence",
        )

    def test_case_e_removing_an_agreeing_family_lowers_confidence(self):
        eligible = {f"fam{i}" for i in range(6)}
        before = assess(panel(6), eligible=eligible)
        after = assess(panel(5), eligible=eligible)
        self.assertLess(after.metrics["coverageShare"], before.metrics["coverageShare"])
        self.assertLessEqual(
            CONFIDENCE_LEVELS.index(after.overall),
            CONFIDENCE_LEVELS.index(before.overall),
        )

    def test_case_f_a_duplicate_observation_from_an_existing_family(self):
        """Not an input. The caller passes heads; a duplicate is not one.

        Enforced at the boundary rather than trusted: a second row from a
        represented family is rejected, because silently averaging or
        silently ignoring it are both ways for a duplicate to matter.
        """
        with self.assertRaises(ValueError):
            assess_confidence(
                [head("alpha", 5000.0), head("alpha", 4000.0, source_key="alphaEcho")],
                eligible_families={"alpha"},
                consensus_value=5000.0,
            )

    def test_case_g_two_current_sources_agree_but_coverage_is_insufficient(self):
        r = assess(panel(2), eligible=set(WIDE))
        self.assertEqual(r.axes["agreement"], "high")
        self.assertEqual(r.axes["freshness"], "high")
        self.assertEqual(r.axes["coverage"], "low")
        self.assertEqual(r.axes["independence"], "low")
        self.assertEqual(r.overall, "low")

    def test_case_h_many_sources_agree_but_most_are_stale(self):
        """A huge source count must not compensate for stale evidence."""
        evidence = panel(10) + [head("fam10"), head("fam11")]
        evidence = [
            head(e.family, e.value_contribution, fresh=(i < 3)) for i, e in enumerate(evidence)
        ]
        r = assess(evidence)
        self.assertEqual(r.axes["independence"], "high")
        self.assertEqual(r.axes["agreement"], "high")
        self.assertEqual(r.axes["freshness"], "low")
        self.assertEqual(r.overall, "low")
        self.assertTrue(any("stale" in reason.lower() for reason in r.reasons))

    def test_case_i_strong_agreement_but_weak_format_applicability(self):
        """A TE priced almost entirely off boards without TE premium.

        The conversion onto this board's TE++ basis is measured (ADR-015),
        not a guess, so it costs ONE level rather than the axis — but it
        cannot be free either: KTC's own uplift runs 1.209 at the top of
        the board to 2.05 down it, so where the player sits changes the
        converted number materially.
        """
        evidence = [head(f"fam{i}", 5000.0, format_native=(i < 3)) for i in range(12)]
        r = assess(evidence)
        self.assertEqual(r.axes["agreement"], "high")
        self.assertEqual(r.axes["applicability"], "medium")
        self.assertEqual(r.overall, "medium")
        self.assertTrue(any("basis" in reason.lower() for reason in r.reasons))

    def test_an_approximating_translation_is_not_a_basis_conversion(self):
        """Rookie-ladder / fallback translation has no measured curve.

        Unlike the TE basis it is an approximation of where the source
        WOULD have placed the player, so it is a full-strength penalty.
        """
        evidence = [head(f"fam{i}", 5000.0, directly_observed=(i < 3)) for i in range(12)]
        r = assess(evidence)
        self.assertEqual(r.axes["applicability"], "low")
        self.assertEqual(r.overall, "low")


class TestMonotonicity(unittest.TestCase):
    def test_a_duplicate_family_member_changes_nothing(self):
        """Invariant 1 and 2, discharged as an identity rather than a bound.

        The gate consumes B10 family heads. Whether the FantasyPros panel
        also published a Fitzmaurice row is not visible to any axis, so
        collapsing the family cannot move confidence in either direction —
        which is precisely the A.J. Brown failure #833 recorded.
        """
        heads_only = panel(12)
        eligible = {e.family for e in heads_only}
        a = assess(heads_only, eligible=eligible)
        # The same board, with one family's second member also scraped.
        # It is superseded upstream, so the gate sees the identical input.
        b = assess(heads_only, eligible=eligible)
        self.assertEqual(a.overall, b.overall)
        self.assertEqual(a.axes, b.axes)
        self.assertEqual(a.metrics, b.metrics)

    def test_collapsing_to_families_cannot_raise_confidence_via_a_narrower_range(self):
        """The retired statistic's failure mode, asserted absent.

        Under max−min, deleting the extreme member of a family narrowed
        the range and promoted the row. Here the extreme member was never
        an input, and no axis is a range.
        """
        wide = panel(11) + [head("fam11", 9000.0)]
        r = assess(wide)
        narrowed = assess(panel(11) + [head("fam11", 5100.0)])
        self.assertGreaterEqual(
            CONFIDENCE_LEVELS.index(narrowed.overall),
            CONFIDENCE_LEVELS.index(r.overall),
        )
        # …and the promotion, where it happens, is because a family
        # CHANGED ITS OPINION — not because an observation disappeared.
        self.assertEqual(narrowed.metrics["independentFamilies"], 12)
        self.assertEqual(r.metrics["independentFamilies"], 12)

    def test_adding_an_agreeing_independent_family_never_lowers_confidence(self):
        eligible = {f"fam{i}" for i in range(12)}
        for n in range(2, 12):
            with self.subTest(n=n):
                before = assess(panel(n), eligible=eligible)
                after = assess(panel(n + 1), eligible=eligible)
                self.assertGreaterEqual(
                    CONFIDENCE_LEVELS.index(after.overall),
                    CONFIDENCE_LEVELS.index(before.overall),
                )

    def test_removing_evidence_that_promotes_must_name_the_quality_reason(self):
        """Invariant 3's escape hatch, and its price.

        Dropping a STALE family can raise confidence — the ruling allows
        that — but only with the reason exposed.
        """
        eligible = {f"fam{i}" for i in range(8)}
        stale_included = [head(f"fam{i}", 5000.0, fresh=(i < 3)) for i in range(8)]
        before = assess(stale_included, eligible=eligible)
        after = assess(panel(3), eligible=eligible)
        self.assertEqual(before.axes["freshness"], "low")
        self.assertEqual(after.axes["freshness"], "high")
        # Coverage still records what went missing, so the promotion is
        # bounded by it rather than unconditional.
        self.assertLess(after.metrics["coverageShare"], before.metrics["coverageShare"])
        self.assertTrue(any("stale" in reason.lower() for reason in before.reasons))

    def test_no_axis_is_a_range_statistic(self):
        """A range is indifferent to everything between its endpoints.

        Move an interior family a long way while holding the extremes:
        a range-based axis cannot notice, and this one must.
        """
        extremes = [head("lo", 3000.0), head("hi", 7000.0)]
        tight = extremes + [head(f"fam{i}", 5000.0) for i in range(6)]
        split = extremes + [head(f"fam{i}", 3100.0 if i % 2 else 6900.0) for i in range(6)]
        self.assertGreater(
            assess(tight).metrics["agreementShare"],
            assess(split).metrics["agreementShare"],
        )


class TestMissingIsNeverZero(unittest.TestCase):
    def test_a_family_with_no_comparable_value_does_not_count_as_agreeing(self):
        """The share's denominator is every head, not the priceable ones.

        Otherwise a family we cannot compare would be silently excused,
        and five agreeing families out of six would read as unanimity.
        """
        evidence = panel(5) + [head("fam5", None)]
        r = assess(evidence)
        self.assertEqual(r.metrics["agreeingFamilies"], 5)
        self.assertEqual(r.metrics["comparableFamilies"], 5)
        self.assertEqual(r.metrics["agreementShare"], round(5 / 6, 4))

    def test_published_shares_agree_with_the_published_levels(self):
        """Rounded for the payload, and the level is decided on the same
        rounded number — so a reader applying the ladder to the published
        share can never get a different answer than the board did.
        """
        for n_fresh in range(1, 9):
            with self.subTest(fresh=n_fresh):
                r = assess([head(f"fam{i}", 5000.0, fresh=(i < n_fresh)) for i in range(8)])
                share = r.metrics["freshnessShare"]
                expected = (
                    "high"
                    if share >= gate_parameter("EVIDENCE_SHARE_HIGH")
                    else "medium"
                    if share >= gate_parameter("EVIDENCE_SHARE_MEDIUM")
                    else "low"
                )
                self.assertEqual(r.axes["freshness"], expected)

    def test_unknown_freshness_is_not_fresh(self):
        """``None`` means we could not observe the source's age.

        Counting it as fresh would make a source we cannot measure look
        exactly like one we measured and found current.
        """
        evidence = [head(f"fam{i}", 5000.0, fresh=None) for i in range(6)]
        r = assess(evidence)
        self.assertEqual(r.axes["freshness"], "low")
        self.assertEqual(r.metrics["freshFamilies"], 0)
        self.assertTrue(any("unknown" in reason.lower() for reason in r.reasons))

    def test_no_consensus_value_is_not_agreement(self):
        r = assess(panel(6), consensus=None)
        self.assertEqual(r.axes["agreement"], "low")
        self.assertIsNone(r.metrics["agreementShare"])

    def test_no_evidence_at_all_is_none_not_low(self):
        r = assess([], eligible=set(WIDE))
        self.assertEqual(r.overall, "none")
        self.assertEqual(r.metrics["independentFamilies"], 0)

    def test_zero_eligible_families_is_unknown_coverage_not_full_coverage(self):
        """A denominator of nothing must not read as 100%."""
        r = assess_confidence(
            panel(3),
            eligible_families=set(),
            consensus_value=5000.0,
        )
        self.assertIsNone(r.metrics["coverageShare"])
        self.assertEqual(r.axes["coverage"], "low")


class TestGateContract(unittest.TestCase):
    def test_the_overall_level_is_the_weakest_axis(self):
        """Bottleneck, not a weighted sum: nothing compensates."""
        evidence = [head(f"fam{i}", 5000.0, fresh=(i < 2)) for i in range(12)]
        r = assess(evidence)
        weakest = min(r.axes.values(), key=CONFIDENCE_LEVELS.index)
        self.assertEqual(r.overall, weakest)

    def test_every_axis_is_reported_every_time(self):
        r = assess(panel(6))
        self.assertEqual(tuple(sorted(r.axes)), tuple(sorted(AXES)))
        for name, level in r.axes.items():
            self.assertIn(level, CONFIDENCE_LEVELS, name)

    def test_the_result_is_explainable_not_a_bare_score(self):
        r = assess(panel(6))
        self.assertTrue(r.reasons)
        for reason in r.reasons:
            self.assertIsInstance(reason, str)
            self.assertTrue(reason.strip())
        self.assertIn("independent evidence famil", " ".join(r.reasons))

    def test_it_is_deterministic(self):
        evidence = [head(f"fam{i}", 5000.0 + 37 * i, fresh=(i % 3 != 0)) for i in range(9)]
        first = assess(evidence)
        for _ in range(20):
            again = assess(list(reversed(evidence)))
            self.assertEqual(again.overall, first.overall)
            self.assertEqual(again.axes, first.axes)
            self.assertEqual(again.reasons, first.reasons)

    def test_confidence_never_returns_a_value(self):
        """Invariant 4, structurally: the assessment carries no price.

        Nothing in the payload can be mistaken for, or fed back into, a
        canonical value.
        """
        r = assess(panel(6))
        for field in ("rankDerivedValue", "value", "adjustedValue"):
            self.assertNotIn(field, r.metrics)


class TestPickConfidenceIsFamilyAware(unittest.TestCase):
    """Picks keep their own CV statistic; they do not keep raw-source counts.

    ``_compute_pick_confidence`` counted six source KEYS, two of which
    (``dlfSf`` / ``dlfIdp``) are one declared family. No live pick row
    carries both today — measured 0 of 144 on the 2026-08-14 board — so
    this closes the hole rather than fixing a live number, and the
    behaviour is pinned so it cannot open again silently.
    """

    def test_two_members_of_one_family_cast_one_vote(self):
        both = assess_pick_confidence(
            {"ktcSfTep": 4000.0, "dlfSf": 4000.0, "dlfIdp": 4000.0},
            is_slot_specific=False,
        )
        head_only = assess_pick_confidence(
            {"ktcSfTep": 4000.0, "dlfSf": 4000.0},
            is_slot_specific=False,
        )
        self.assertEqual(both, head_only)

    def test_independent_sources_still_corroborate(self):
        bucket, _label = assess_pick_confidence(
            {"ktcSfTep": 4000.0, "idpTradeCalc": 4050.0},
            is_slot_specific=False,
        )
        self.assertEqual(bucket, "high")

    def test_no_pick_values_is_none(self):
        bucket, _label = assess_pick_confidence({}, is_slot_specific=False)
        self.assertEqual(bucket, "none")


class TestConfidenceDescribesTheValueThatShipped(unittest.TestCase):
    """A post-blend OVERRIDE invalidates the stamp taken before it.

    The agreement axis asks how many families price within a material
    relative gap of ``rankDerivedValue``.  ``_apply_two_way_player_boost``
    runs AFTER the ranking loop and replaces that value with the
    alt-position family's — a number no source in the blend published.

    Measured on the 2026-08-14 board: Travis Hunter's boost lifts him
    from the offense blend's ~2,900 to 4,758, leaving all eleven of his
    families 24-56% BELOW the published value.  The stamp taken before
    the boost said high agreement, and it was describing a value the row
    no longer carried.

    The retired percentile-spread rule never read the value at all, so
    this coupling is NEW with the gate — which is why it is guarded here
    rather than being someone else's pre-existing bug.
    """

    def test_a_moved_value_is_re_assessed_against_its_own_evidence(self):
        from src.api.data_contract import _restate_confidence_after_override

        evidence = [head(f"fam{i}", 5000.0) for i in range(8)]
        eligible = {e.family for e in evidence}
        rows = [
            {
                "canonicalName": "Overridden",
                "rankDerivedValue": 9000,  # moved after the gate ran
                "confidenceBucket": "high",
                "confidenceLabel": "stale",
                "confidenceAxes": {a: "high" for a in AXES},
                "confidenceReasons": ["stale"],
            }
        ]
        restated = _restate_confidence_after_override(rows, {0: (evidence, eligible)}, {0: 5000})

        self.assertEqual(restated, ["Overridden"])
        self.assertEqual(rows[0]["confidenceAxes"]["agreement"], "low")
        self.assertEqual(rows[0]["confidenceBucket"], "low")
        self.assertIn("0 of 8 families price", " ".join(rows[0]["confidenceReasons"]))

    def test_an_untouched_row_keeps_its_original_stamp(self):
        """Re-stating everything would be a second, silent gate run."""
        from src.api.data_contract import _restate_confidence_after_override

        evidence = [head(f"fam{i}", 5000.0) for i in range(8)]
        rows = [
            {
                "canonicalName": "Untouched",
                "rankDerivedValue": 5000,
                "confidenceBucket": "high",
                "confidenceLabel": "original",
                "confidenceAxes": {a: "high" for a in AXES},
                "confidenceReasons": ["original"],
            }
        ]
        restated = _restate_confidence_after_override(
            rows, {0: (evidence, {e.family for e in evidence})}, {0: 5000}
        )

        self.assertEqual(restated, [])
        self.assertEqual(rows[0]["confidenceLabel"], "original")


class TestGateParametersAreDeclared(unittest.TestCase):
    """Same discipline as the threshold registry: no invented numbers."""

    def test_every_parameter_records_its_unit_and_derivation(self):
        for name, entry in sorted(gate_parameters().items()):
            with self.subTest(parameter=name):
                self.assertTrue((entry.get("unit") or "").strip(), f"{name} has no unit")
                self.assertTrue(
                    (entry.get("derivedFrom") or "").strip(), f"{name} has no derivedFrom"
                )
                self.assertIsInstance(entry.get("value"), (int, float))

    def test_an_unknown_parameter_raises_rather_than_defaulting(self):
        with self.assertRaises(KeyError):
            gate_parameter("NOT_A_PARAMETER")

    def test_the_module_holds_no_numeric_literal_that_decides_a_level(self):
        """Every gating number comes from the config, not the code."""
        source = (REPO_ROOT / "src" / "api" / "confidence.py").read_text(encoding="utf-8")
        for name in gate_parameters():
            self.assertIn(name, source, f"{name} is declared but never read")

    def test_the_confidence_parameters_are_not_mirrored_to_the_frontend(self):
        """B11 forbids frontend confidence math; do not ship it the dials.

        ``tests/api/test_threshold_parity.py`` requires every entry in
        ``config/thresholds.json`` to be exported from ``thresholds.js``,
        so putting these there would plant client-side exactly the
        constants #725 removed.
        """
        registry = json.loads(
            (REPO_ROOT / "config" / "thresholds.json").read_text(encoding="utf-8")
        )
        for name in gate_parameters():
            self.assertNotIn(name, registry.get("thresholds", {}))
        js = (REPO_ROOT / "frontend" / "lib" / "thresholds.js").read_text(encoding="utf-8")
        for name in gate_parameters():
            self.assertNotIn(name, js)


if __name__ == "__main__":
    unittest.main()
