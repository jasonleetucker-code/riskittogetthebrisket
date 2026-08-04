"""Invariants that stop the composite from lying.

Most of these assert a REFUSAL. A buy/sell score is easy to produce and
easy to produce badly, and every failure mode it has is a quiet one — a
number that looks reasonable and means something other than what the
reader assumes. These tests pin the specific ways it must decline.
"""

from __future__ import annotations

import math
import unittest

from src.consensus_edge import mispricing, opportunity, params as params_mod, score, sharp_flow

P = params_mod.load()


class TestCompositeMissingData(unittest.TestCase):
    def test_an_absent_component_is_dropped_not_zeroed(self):
        # A player with no sharp data must not be scored as though
        # qualified managers had looked and felt neutral.
        both = score.composite({"mispricing": 0.6, "sharpFlow": 0.6}, P)["score"]
        one = score.composite({"mispricing": 0.6, "sharpFlow": None}, P)["score"]
        self.assertAlmostEqual(both, one, places=6)

    def test_absent_components_are_named(self):
        out = score.composite({"mispricing": 0.5, "sharpFlow": None, "opportunity": None}, P)
        self.assertEqual(out["componentsAbsent"], ["opportunity", "sharpFlow"])

    def test_weights_renormalise_to_one_over_present_components(self):
        out = score.composite({"mispricing": 0.5, "sharpFlow": 0.5, "opportunity": None}, P)
        self.assertAlmostEqual(sum(out["effectiveWeights"].values()), 1.0, places=9)

    def test_no_core_component_yields_no_score(self):
        out = score.composite({"mispricing": None, "sharpFlow": None, "opportunity": 0.9}, P)
        self.assertIsNone(out["score"])
        self.assertIn("core", out["reason"])

    def test_no_components_at_all_yields_no_score(self):
        out = score.composite({"mispricing": None, "sharpFlow": None}, P)
        self.assertIsNone(out["score"])


class TestCompositeBounds(unittest.TestCase):
    def test_score_stays_within_plus_minus_one_hundred(self):
        for value in (-5.0, -1.0, 0.0, 1.0, 5.0):
            out = score.composite({"mispricing": value, "sharpFlow": value}, P)
            self.assertGreaterEqual(out["score"], -100.0)
            self.assertLessEqual(out["score"], 100.0)

    def test_more_favourable_evidence_never_lowers_the_score(self):
        previous = None
        for value in (-1.0, -0.5, 0.0, 0.5, 1.0):
            current = score.composite({"mispricing": value}, P)["score"]
            if previous is not None:
                self.assertGreaterEqual(current, previous)
            previous = current


class TestConflict(unittest.TestCase):
    def test_strong_opposing_evidence_is_conflicted_not_neutral(self):
        components = {"mispricing": 0.8, "sharpFlow": -0.8}
        conflict = score.detect_conflict(components, P)
        self.assertTrue(conflict["conflicted"])
        composite = score.composite(components, P)["score"]
        label = score.classify(composite, 90.0, conflict, P)
        self.assertEqual(label["label"], score.CONFLICTED)

    def test_agreement_is_not_conflict(self):
        self.assertFalse(
            score.detect_conflict({"mispricing": 0.8, "sharpFlow": 0.7}, P)["conflicted"]
        )

    def test_weak_disagreement_is_not_conflict(self):
        self.assertFalse(
            score.detect_conflict({"mispricing": 0.1, "sharpFlow": -0.1}, P)["conflicted"]
        )

    def test_conflict_names_which_side_each_component_took(self):
        conflict = score.detect_conflict({"mispricing": 0.9, "sharpFlow": -0.9}, P)
        self.assertEqual(conflict["opposing"]["positive"], ["mispricing"])
        self.assertEqual(conflict["opposing"]["negative"], ["sharpFlow"])


class TestConfidence(unittest.TestCase):
    def _conf(self, **kw):
        base = dict(
            params=P,
            components_present=3,
            components_possible=3,
            cohort_level="specific",
            source_count=6,
            hours_stale=0.0,
        )
        base.update(kw)
        return score.confidence(**base)["score"]

    def test_confidence_is_bounded(self):
        self.assertGreaterEqual(self._conf(), 0.0)
        self.assertLessEqual(self._conf(), 100.0)

    def test_missing_components_cannot_raise_confidence(self):
        full = self._conf(components_present=3)
        partial = self._conf(components_present=1)
        self.assertLess(partial, full)

    def test_stale_data_lowers_confidence(self):
        self.assertLess(self._conf(hours_stale=96.0), self._conf(hours_stale=0.0))

    def test_unknown_staleness_is_treated_as_stale_not_fresh(self):
        self.assertLess(self._conf(hours_stale=None), self._conf(hours_stale=0.0))

    def test_a_coarser_cohort_lowers_confidence(self):
        self.assertLess(self._conf(cohort_level="family"), self._conf(cohort_level="specific"))

    def test_one_zeroed_factor_collapses_the_whole_score(self):
        # Geometric mean: confidence is a conjunction, and three strong
        # factors must not hide one absent one.
        self.assertAlmostEqual(self._conf(components_present=0), 0.0, places=9)


class TestClassificationRefusals(unittest.TestCase):
    def _clean(self):
        return score.detect_conflict({"mispricing": 0.1}, P)

    def test_low_confidence_yields_insufficient_evidence(self):
        out = score.classify(80.0, 10.0, self._clean(), P)
        self.assertEqual(out["label"], score.INSUFFICIENT)

    def test_no_score_yields_insufficient_evidence(self):
        self.assertEqual(score.classify(None, 90.0, self._clean(), P)["label"], score.INSUFFICIENT)

    def test_missing_market_price_is_its_own_state(self):
        out = score.classify(80.0, 90.0, self._clean(), P, has_market_price=False)
        self.assertEqual(out["label"], score.NO_MARKET_PRICE)

    def test_quarantine_beats_everything(self):
        out = score.classify(90.0, 99.0, self._clean(), P, quarantined=True)
        self.assertEqual(out["label"], score.WITHHELD)

    def test_strong_label_requires_high_confidence(self):
        strong = score.classify(80.0, 95.0, self._clean(), P)
        weak = score.classify(80.0, 55.0, self._clean(), P)
        self.assertEqual(strong["label"], score.STRONG_BUY)
        self.assertEqual(weak["label"], score.BUY)
        self.assertIn("confidence", weak["reason"])

    def test_sell_side_mirrors_the_buy_side(self):
        self.assertEqual(score.classify(-80.0, 95.0, self._clean(), P)["label"], score.STRONG_SELL)
        self.assertEqual(score.classify(-45.0, 60.0, self._clean(), P)["label"], score.SELL)


class TestSharpFlow(unittest.TestCase):
    def _mv(self, manager, league, is_buy, age_days=0.0, quality=1.0):
        now = 1_800_000_000_000
        return sharp_flow.Movement(
            asset_key="p",
            manager_key=manager,
            league_key=league,
            is_buy=is_buy,
            timestamp_ms=int(now - age_days * 86_400_000),
            manager_quality=quality,
        )

    def _agg(self, movements):
        return sharp_flow.aggregate_asset(movements, P, now_ms=1_800_000_000_000)

    def test_no_ledger_is_reported_not_zeroed(self):
        out = sharp_flow.sharp_flow_index(None, P)
        self.assertEqual(out["status"], sharp_flow.STATUS_NO_LEDGER)
        self.assertEqual(out["assets"], {})

    def test_an_empty_ledger_is_different_from_no_ledger(self):
        out = sharp_flow.sharp_flow_index({}, P)
        self.assertEqual(out["status"], sharp_flow.STATUS_OK)

    def test_unanimous_buying_is_positive(self):
        out = self._agg([self._mv(f"m{i}", f"l{i}", True) for i in range(8)])
        self.assertGreater(out["direction"], 0)

    def test_unanimous_selling_is_negative(self):
        out = self._agg([self._mv(f"m{i}", f"l{i}", False) for i in range(8)])
        self.assertLess(out["direction"], 0)

    def test_thin_evidence_refuses_a_direction(self):
        out = self._agg([self._mv("m1", "l1", True)])
        self.assertIsNone(out["direction"])
        self.assertEqual(out["reason"], sharp_flow.UNSCORED_BELOW_MIN_SAMPLE)

    def test_one_manager_cannot_dominate(self):
        # Eight buys from one manager vs three sells from three others.
        # Uncapped this is a decisive buy; capped it must be tempered.
        crowd = [self._mv(f"m{i}", f"l{i}", False) for i in range(3)]
        hoarder = [self._mv("whale", f"lw{i}", True) for i in range(8)]
        out = self._agg(crowd + hoarder)
        self.assertLessEqual(out["topManagerShare"], 1.0, "share diagnostic should be reported")
        uncapped_ratio = 8 / 11
        self.assertLess(
            out["weightedBuys"] / (out["weightedBuys"] + out["weightedSells"]),
            uncapped_ratio,
            "a single manager's eight observations were not capped",
        )

    def test_recent_evidence_outweighs_old_evidence(self):
        fresh = self._agg([self._mv(f"m{i}", f"l{i}", True, age_days=0) for i in range(6)])
        stale = self._agg([self._mv(f"m{i}", f"l{i}", True, age_days=120) for i in range(6)])
        self.assertGreater(fresh["effectiveSample"], stale["effectiveSample"])

    def test_direction_stays_within_bounds(self):
        for n in (3, 10, 50):
            out = self._agg([self._mv(f"m{i}", f"l{i}", True) for i in range(n)])
            self.assertGreaterEqual(out["direction"], -1.0)
            self.assertLessEqual(out["direction"], 1.0)

    def test_price_awareness_is_advertised_as_absent(self):
        out = self._agg([self._mv(f"m{i}", f"l{i}", True) for i in range(5)])
        self.assertFalse(out["priceAware"], "an acquisition is not evidence of a good price")

    def test_more_evidence_narrows_the_credible_interval(self):
        few = self._agg([self._mv(f"m{i}", f"l{i}", True) for i in range(4)])
        many = self._agg([self._mv(f"m{i}", f"l{i}", True) for i in range(40)])
        self.assertLess(
            many["credibleHigh"] - many["credibleLow"],
            few["credibleHigh"] - few["credibleLow"],
        )


class TestOpportunityInertness(unittest.TestCase):
    def test_no_evidence_yields_none_not_zero(self):
        out = opportunity.assess(rank_history=None)
        self.assertIsNone(out["score"])
        self.assertEqual(out["reason"], opportunity.UNSCORED_NO_EVIDENCE)

    def test_absent_axes_are_named(self):
        self.assertIn("rankMomentum", opportunity.assess(rank_history=None)["absentAxes"])

    def test_evidence_produces_a_score(self):
        history = [{"rankDerivedValue": v} for v in (1000, 1100, 1200)]
        self.assertIsNotNone(opportunity.assess(rank_history=history)["score"])


class TestMispricingSaturation(unittest.TestCase):
    """The tail must stay ordered.

    A hard clamp put 23 of 699 live rows on exactly the same score, and
    among the clipped buys the underlying gaps ran +20% to +229%. The
    published top-20 was an arbitrary tie-break.
    """

    def test_extreme_rows_remain_distinguishable(self):
        cohorts = {"QB|mid": {"n": 50, "median": 0.0, "sigma": 0.1, "usable": True, "reason": None}}
        a = mispricing.score_entry(
            {"fairValue": 2000.0, "marketValue": 1000.0, "position": "QB"}, cohorts
        )
        b = mispricing.score_entry(
            {"fairValue": 4000.0, "marketValue": 1000.0, "position": "QB"}, cohorts
        )
        self.assertNotAlmostEqual(a["score"], b["score"], places=6)
        self.assertLess(a["score"], b["score"])

    def test_score_is_still_bounded(self):
        # sigma 0.01 is absurdly tight on purpose: it drives z into the
        # hundreds, which is where an unbounded score would blow up.
        cohorts = {
            "QB|mid": {"n": 50, "median": 0.0, "sigma": 0.01, "usable": True, "reason": None}
        }
        out = mispricing.score_entry(
            {"fairValue": 9999.0, "marketValue": 2000.0, "position": "QB"}, cohorts
        )
        self.assertIsNotNone(out["score"], f"unscored: {out['reason']}")
        # tanh saturates to exactly 1.0 in float past roughly 18 sigma,
        # so the bound is inclusive. Ordering is preserved well below
        # that — the largest z measured on a live board was 12.3, which
        # maps to 0.9995 and stays distinct from its neighbours.
        self.assertLessEqual(abs(out["score"]), 1.0)

    def test_the_raw_z_is_reported_unsaturated(self):
        cohorts = {"QB|mid": {"n": 50, "median": 0.0, "sigma": 0.1, "usable": True, "reason": None}}
        out = mispricing.score_entry(
            {"fairValue": 4000.0, "marketValue": 1000.0, "position": "QB"}, cohorts
        )
        self.assertGreater(out["z"], mispricing.Z_SCALE)
        self.assertAlmostEqual(out["score"], math.tanh(out["z"] / mispricing.Z_SCALE), places=9)


class TestParams(unittest.TestCase):
    def test_param_set_id_is_stable(self):
        self.assertEqual(params_mod.load()["paramSetId"], params_mod.load()["paramSetId"])

    def test_comments_do_not_affect_the_id(self):
        # The id must describe the VALUES; a prose edit that churned it
        # would make two identical parameter sets look different.
        stripped = params_mod._strip_comments({"a": 1, "_comment": "x"})
        self.assertEqual(stripped, {"a": 1})

    def test_composite_weights_are_declared(self):
        weights = params_mod.load()["composite"]["weights"]
        self.assertIn("mispricing", weights)
        self.assertGreater(weights["mispricing"], 0)


class TestComponentValidationHonesty(unittest.TestCase):
    def test_only_mispricing_claims_validation(self):
        validated = {k for k, v in score.COMPONENT_VALIDATION.items() if v["validated"]}
        self.assertEqual(validated, {"mispricing"})

    def test_every_component_states_its_evidence_or_lack_of_it(self):
        for name, meta in score.COMPONENT_VALIDATION.items():
            self.assertTrue(meta.get("note"), f"{name} has no validation note")


if __name__ == "__main__":
    unittest.main()


class TestVersionParity(unittest.TestCase):
    """Two copies of the version must not drift.

    ``MODEL_VERSION`` is a module literal and ``params_v1.json`` carries
    its own ``modelVersion``. Nothing asserted they agreed, so a bump in
    one would silently leave stored snapshot rows tagged with a version
    that no longer described them — and the snapshot store keys on both.
    """

    def test_model_version_matches_the_parameter_file(self):
        from src.consensus_edge import MODEL_VERSION

        self.assertEqual(
            MODEL_VERSION,
            params_mod.load().get("modelVersion"),
            "src/consensus_edge/__init__.py::MODEL_VERSION and "
            "config/consensus_edge/params_v1.json::modelVersion disagree",
        )

    def test_param_set_id_is_a_content_hash_of_the_values(self):
        # Editing a value must produce a new id, or a stored result
        # cannot be attributed to the params that made it.
        import json
        import tempfile
        from pathlib import Path

        base = params_mod.load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "params.json"
            edited = json.loads(json.dumps(base))
            edited.pop("paramSetId", None)
            edited["composite"]["weights"]["mispricing"] = 0.99
            path.write_text(json.dumps(edited))
            self.assertNotEqual(params_mod.load(path)["paramSetId"], base["paramSetId"])
