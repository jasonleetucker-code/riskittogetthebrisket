"""Invariants that stop the composite from lying.

Most of these assert a REFUSAL. A buy/sell score is easy to produce and
easy to produce badly, and every failure mode it has is a quiet one — a
number that looks reasonable and means something other than what the
reader assumes. These tests pin the specific ways it must decline.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

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
        absent = opportunity.assess(rank_history=None)["absentAxes"]
        self.assertIn("snapTrend", absent)
        self.assertIn("boardMomentumRisk", absent)

    def test_evidence_produces_a_score(self):
        # ``val`` is what ``rank_history.load_history`` emits. This
        # fixture previously said ``rankDerivedValue`` — a key that
        # producer has never written — so the axis returned ABSENT here
        # too, and the test passed only because ``assertIsNotNone`` was
        # never reached with a real shape. Direction is asserted in
        # ``test_opportunity_wiring.py``; this stays a liveness check.
        history = [
            {"date": "2026-07-0%d" % (i + 1), "rank": 1, "val": v}
            for i, v in enumerate((1200, 1100, 1000))
        ]
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
    def test_a_validated_component_has_a_positive_outcome_behind_it(self):
        """This asserted ``validated == {"mispricing"}``.

        That was a statement about which component happened to have a
        result, not about what ``validated`` means, and it went stale the
        moment mispricing's rho was re-measured on the scale-repaired
        board and came back a null (ADR-021 / ADR-023). Today the set is
        EMPTY, and hardcoding that would go stale the same way in the
        other direction.

        The invariant that actually matters: ``validated`` is the field
        driving the UI's badge, so it may only be True where the outcome
        is positive and the measurement that says so exists on disk.
        """
        for name, meta in score.COMPONENT_VALIDATION.items():
            if not meta.get("validated"):
                continue
            self.assertTrue(meta.get("measured"), f"{name} claims validated but not measured")
            self.assertEqual(
                meta.get("outcome"),
                "positive",
                f"{name} claims validated on a {meta.get('outcome')!r} outcome",
            )

    def test_a_measured_null_never_reads_as_validated(self):
        # The case that motivated splitting the two fields, now true of
        # two components rather than one.
        for name, meta in score.COMPONENT_VALIDATION.items():
            if meta.get("outcome") != "null":
                continue
            self.assertTrue(meta.get("measured"), name)
            self.assertFalse(meta.get("validated"), f"{name}: a null result is not a validation")
            self.assertTrue(meta.get("evidence"), f"{name}: a measured null must cite its file")

    def test_every_component_states_its_evidence_or_lack_of_it(self):
        for name, meta in score.COMPONENT_VALIDATION.items():
            self.assertTrue(meta.get("note"), f"{name} has no validation note")

    def test_measured_and_validated_are_separate_claims(self):
        """A null result is measured, not validated.

        `validated` drives the UI's "unvalidated" badge, so a component
        measured and found NOT to help must keep it False — otherwise a
        negative result reads to a user as a positive one. Opportunity
        is exactly that case and is the reason the two fields exist.
        """
        opportunity = score.COMPONENT_VALIDATION["opportunity"]
        self.assertTrue(opportunity["measured"])
        self.assertFalse(opportunity["validated"])
        self.assertEqual(opportunity["outcome"], "null")
        self.assertTrue(opportunity["evidence"], "a measured null must cite its measurement")

    def test_a_measured_component_cites_a_measurement_that_exists(self):
        repo = Path(__file__).resolve().parents[2]
        for name, meta in score.COMPONENT_VALIDATION.items():
            if not meta.get("measured"):
                self.assertIsNone(meta.get("evidence"), f"{name} cites evidence but is unmeasured")
                continue
            self.assertTrue(
                (repo / meta["evidence"]).exists(), f"{name}: {meta['evidence']} missing"
            )


class TestZeroWeightComponentsAreInert(unittest.TestCase):
    """A measured-and-rejected component must not act through side doors.

    Setting a weight to zero stops a component contributing to the
    SCORE. It does not, on its own, stop it contributing to coverage
    (and so to confidence, and so to which labels are reachable) or to
    conflict detection (which suppresses directional calls). Both were
    live paths by which a signal we decided is non-predictive would
    still have steered output.
    """

    ZEROED = {
        "composite": {
            "weights": {"mispricing": 0.5, "sharpFlow": 0.3, "opportunity": 0.0},
            "requireCoreComponent": True,
            "coreComponents": ["mispricing", "sharpFlow"],
        },
        "conflict": {"minMagnitude": 0.5},
    }

    def test_a_zero_weight_component_does_not_count_as_present(self):
        out = score.composite(
            {"mispricing": 0.5, "sharpFlow": None, "opportunity": 0.9}, self.ZEROED
        )
        self.assertEqual(out["componentsPresent"], ["mispricing"])
        self.assertEqual(out["componentsZeroWeight"], ["opportunity"])

    def test_a_zero_weight_component_is_not_reported_as_absent(self):
        # Absent means "no data". This component has data we chose not
        # to act on; calling that absent would hide a real measurement.
        out = score.composite(
            {"mispricing": 0.5, "sharpFlow": None, "opportunity": 0.9}, self.ZEROED
        )
        self.assertEqual(out["componentsAbsent"], ["sharpFlow"])

    def test_the_score_is_identical_with_and_without_it(self):
        with_it = score.composite(
            {"mispricing": 0.5, "sharpFlow": None, "opportunity": 0.9}, self.ZEROED
        )
        without = score.composite(
            {"mispricing": 0.5, "sharpFlow": None, "opportunity": None}, self.ZEROED
        )
        self.assertEqual(with_it["score"], without["score"])
        self.assertEqual(with_it["effectiveWeights"], without["effectiveWeights"])

    def test_it_cannot_trigger_a_conflict(self):
        # Opposing a core component at full strength must not suppress
        # the directional call when the opposition carries no weight.
        conflict = score.detect_conflict(
            {"mispricing": 0.8, "sharpFlow": None, "opportunity": -0.9}, self.ZEROED
        )
        self.assertFalse(conflict["conflicted"])

    def test_a_weighted_component_still_triggers_a_conflict(self):
        conflict = score.detect_conflict(
            {"mispricing": 0.8, "sharpFlow": -0.9, "opportunity": None}, self.ZEROED
        )
        self.assertTrue(conflict["conflicted"])

    def test_only_zero_weight_evidence_yields_no_score(self):
        out = score.composite(
            {"mispricing": None, "sharpFlow": None, "opportunity": 0.9}, self.ZEROED
        )
        self.assertIsNone(out["score"])

    def test_the_core_refusal_still_names_the_core_problem(self):
        # Ordering matters: "no core component" is a statement about the
        # KIND of evidence and holds whatever the weights are. Reporting
        # "everything carries zero weight" here would describe a
        # symptom rather than the defect.
        out = score.composite(
            {"mispricing": None, "sharpFlow": None, "opportunity": 0.9}, self.ZEROED
        )
        self.assertIn("core", out["reason"])


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


class TestScoringFitIsInertWhenUnmeasured(unittest.TestCase):
    """League scoring must contribute exactly nothing when unmeasured.

    Consensus Edge claimed custom-league scoring adjustments while
    importing nothing from the scoring packages. Now that it does, the
    load-bearing property is the opposite one: an axis that cannot be
    measured must apply exactly 1.0 and say so, never a partial or
    guessed effect.
    """

    def test_an_unmeasured_board_is_a_no_op(self):
        from src.consensus_edge import scoring_fit as ce_scoring_fit

        board = ce_scoring_fit.ScoringFitBoard()
        fit = board.for_player("Anyone", "WR")
        self.assertEqual(fit.multiplier, 1.0)
        self.assertEqual(fit.level, ce_scoring_fit.LEVEL_ABSENT)
        self.assertFalse(board.active)

    def test_an_unknown_position_never_inherits_another_positions_tilt(self):
        # Applying an IDP tilt to a wide receiver is the failure this
        # guards; an unknown position must be a no-op.
        from src.consensus_edge import scoring_fit as ce_scoring_fit

        board = ce_scoring_fit.ScoringFitBoard(by_position={"LB": 1.4})
        self.assertEqual(board.for_player("Someone", "WR").multiplier, 1.0)
        self.assertEqual(board.for_player("Someone", None).multiplier, 1.0)

    def test_player_level_wins_over_position_level(self):
        from src.consensus_edge import scoring_fit as ce_scoring_fit

        board = ce_scoring_fit.ScoringFitBoard(
            by_player={"A": ce_scoring_fit.PlayerScoringFit(1.2, ce_scoring_fit.LEVEL_PLAYER)},
            by_position={"WR": 1.5},
        )
        fit = board.for_player("A", "WR")
        self.assertEqual(fit.multiplier, 1.2)
        self.assertEqual(fit.level, ce_scoring_fit.LEVEL_PLAYER)

    def test_the_live_measurement_reports_its_refusals(self):
        from src.consensus_edge import scoring_fit as ce_scoring_fit

        board = ce_scoring_fit.measure(season=2026, refresh=True)
        # Whatever the environment, every axis is either measured or
        # named as absent with a reason — never silently missing.
        named = set(board.measured_axes) | set(board.absent_axes)
        self.assertIn("idpPositionFit", named)
        self.assertIn("receptionDepthFit", named)
        for axis in board.absent_axes:
            self.assertTrue(board.reasons.get(axis), f"{axis} absent with no reason")

    def test_scoring_fit_is_not_a_composite_component(self):
        # It enters inside fair value. If it ever became a fourth
        # component the same effect would be counted twice.
        from src.consensus_edge import service as ce_service

        params = params_mod.load()
        self.assertNotIn("scoringFit", (params.get("composite") or {}).get("weights") or {})
        self.assertNotIn("scoringFit", ce_service.DIRECTIONAL_LABELS)
