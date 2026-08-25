"""The blend-integrity detector, and the corridor it replaced.

Replaces ``test_market_corridor_clamp.py`` (738 lines) and
``test_market_corridor_characterization.py`` (364 lines). Those pinned the
behaviour of a mechanism that no longer exists; they were removed rather
than adapted, because a test that asserts "the clamp still clamps" cannot
be made meaningful once the clamp is gone.

What replaced it, and why (#794/#795/#796):

* the corridor's **anchor was a voter** in the blend it corrected — on
  539 of 539 clamped rows across 17 independent historical days;
* its **band was a P90 of the board it policed**, so it clamped a fixed
  ~9% whether the board was healthy or 10x broken;
* its **confidence bands were ordered backwards** (HIGH permitted MORE
  disagreement than MEDIUM);
* and it **caught nothing upstream did not already handle**: injecting
  anomalies at the source CSVs and rebuilding, it fired on 0 of 6
  victims in every scenario.

The replacement asserts a structural invariant instead: a weighted blend
cannot lie outside the range of its own contributions. Market
disagreement can never violate that; only a pipeline fault can. And when
it is violated the row is **flagged, not corrected** — coercing an
impossible value to a plausible one hides the fault.

Not correcting the value is only half of abstention, though. The other
half is that the value must stop counting as an ordinary available
canonical number, which is what ``TestTheViolationActuallyAbstains``
covers. Detection that stamps metadata and then lets the impossible value
flow onward unchanged is diagnostics, not fail-closed behaviour.

Both halves reuse mechanisms the platform already has — the row-level
``anomalyFlags``/``quarantined`` channel and the contract validator's
hard-error path — rather than a new missing-state system invented for one
detector.
"""

from __future__ import annotations

import unittest

from src.api import data_contract as dc


IDP = ("DL", "LB", "DB")


def _row(name: str, position: str, **sites):
    if position == "PICK":
        asset_class = "pick"
    elif position in IDP:
        asset_class = "idp"
    else:
        asset_class = "offense"
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": asset_class,
        "canonicalSiteValues": dict(sites),
        "values": {"overall": 0, "rawComposite": None, "finalAdjusted": None, "displayValue": None},
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": False,
    }


class TestTheCorridorIsGone(unittest.TestCase):
    """The removal is pinned, not merely un-tested.

    A deleted mechanism that nothing asserts the absence of tends to grow
    back — and this one would grow back as a second value-setting vote for
    a source that already voted.
    """

    def test_no_corridor_entry_points_survive(self):
        for name in (
            "_apply_market_corridor_clamp",
            "_market_anchor_for_row",
            "_market_anchor_value_for_row",
            "_MARKET_ANCHOR_BY_ASSET_CLASS",
            "_MARKET_ANCHOR_FALLBACKS",
            "_MARKET_CORRIDOR_PERCENTILE",
            "_MARKET_CORRIDOR_MIN_BUCKET_N",
            "_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS",
        ):
            self.assertFalse(hasattr(dc, name), f"{name} came back")

    def test_no_self_derived_band_remains(self):
        """The #795 mechanism specifically: a threshold read off the board.

        Checked as source text because the defect is not any single
        symbol — it is the *pattern* of deriving an enforcement threshold
        from the distribution being enforced.
        """
        import inspect

        src = inspect.getsource(dc._detect_blend_integrity_violations)
        for banned in ("percentile", "P90", "bucket_bands", "confidenceBucket"):
            self.assertNotIn(
                banned.lower(),
                src.lower().split('"""')[-1],
                f"{banned} reappeared in the detector body",
            )

    def test_the_epsilon_is_precision_not_policy(self):
        """It must stay far below anything that could act as a band."""
        self.assertLess(dc._BLEND_HULL_EPSILON, 1e-6)


class TestHealthyDisagreementIsNeverCoerced(unittest.TestCase):
    """The property the corridor violated ~9% of the time, every board."""

    def test_violent_disagreement_passes_through_untouched(self):
        rows = [_row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)]
        # One source screaming, four disagreeing — real market disagreement.
        rows.append(
            _row(
                "Contested LB",
                "LB",
                idpTradeCalc=9000,
                idpShow=999900,
                dlfIdp=100,
                fantasyProsIdp=200,
                draftSharksIdp=1,
            )
        )
        for i in range(40):
            rows.append(
                _row(f"F{i:03d}", "LB", idpTradeCalc=4000 - i * 10, dlfIdp=999900 - i * 100)
            )
        dc._compute_unified_rankings(rows, {})
        target = next(r for r in rows if r["canonicalName"] == "Contested LB")
        self.assertIsNone(
            target.get("marketCorridorClamp"),
            "a disagreement row was clamped; the corridor is supposed to be gone",
        )
        self.assertIsNone(
            target.get("blendIntegrityViolation"),
            "disagreement was reported as a pipeline-integrity failure",
        )

    def test_no_row_on_a_synthetic_board_is_value_altered(self):
        rows = [_row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)]
        for i in range(60):
            rows.append(
                _row(
                    f"P{i:03d}",
                    "DB",
                    idpTradeCalc=5000 - i * 50,
                    dlfIdp=999900 - i * 100,
                    idpShow=999900 - i * 120,
                )
            )
        dc._compute_unified_rankings(rows, {})
        altered = [r["canonicalName"] for r in rows if r.get("marketCorridorClamp")]
        self.assertEqual(altered, [])


class TestTheInvariantDetectsImpossibility(unittest.TestCase):
    """Out-of-hull is flagged, and the value is left alone."""

    def _detect(self, value, contributions):
        row = {
            "displayName": "X",
            "canonicalConsensusRank": 10,
            "rankDerivedValue": value,
            "sourceRankMeta": {k: {"valueContribution": v} for k, v in contributions.items()},
        }
        dc._detect_blend_integrity_violations([row], {})
        return row

    def test_value_above_the_hull_is_detected(self):
        row = self._detect(9000, {"a": 1000, "b": 2000})
        stamp = row.get("blendIntegrityViolation")
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp["direction"], "above")
        self.assertEqual(stamp["contributionMax"], 2000)

    def test_value_below_the_hull_is_detected(self):
        row = self._detect(100, {"a": 1000, "b": 2000})
        self.assertEqual(row["blendIntegrityViolation"]["direction"], "below")

    def test_detection_does_not_alter_the_value(self):
        """The whole point of ABSTAIN over CLAMP."""
        row = self._detect(9000, {"a": 1000, "b": 2000})
        self.assertEqual(row["rankDerivedValue"], 9000)
        self.assertIs(row["blendIntegrityViolation"]["valueAltered"], False)

    def test_a_value_inside_the_hull_is_not_flagged(self):
        row = self._detect(1500, {"a": 1000, "b": 2000})
        self.assertIsNone(row.get("blendIntegrityViolation"))

    def test_the_hull_boundary_is_inclusive(self):
        for v in (1000, 2000):
            row = self._detect(v, {"a": 1000, "b": 2000})
            self.assertIsNone(row.get("blendIntegrityViolation"), f"boundary {v} flagged")


class TestQuantizationSkewIsNotViolation(unittest.TestCase):
    """The 2026-08-25 "2027 Mid 2nd" false positive, pinned.

    The two quantities the detector compares are integers quantized from
    floats by DIFFERENT rules: ``rankDerivedValue`` is ``int(norm_val)``
    (truncation — up to 1.0 below the float blend), while each
    ``valueContribution`` stamp is ``int(round(value))`` (within 0.5
    either way). A blend genuinely inside its float hull can therefore
    publish up to 1.5 below the stamped minimum and up to 0.5 above the
    stamped maximum — and when the stamped hull is under a unit wide,
    the old float-epsilon check manufactured a violation out of pure
    rounding. Measured live: ktc voted 3459 x 9999/9997 = 3459.692,
    idpTradeCalc voted 3460.0, the blend was ~3459.85 (inside), the
    published truncation was 3459, and both stamps rounded to 3460 —
    flagged "below" a hull the blend never left, quarantining the row
    and turning the structural CI lane red on every open PR. The
    2026-08-22 "2027 Late 1st" transient (#1063) was the same class.
    """

    def _detect(self, value, contributions):
        row = {
            "displayName": "X",
            "canonicalConsensusRank": 134,
            "rankDerivedValue": value,
            "sourceRankMeta": {k: {"valueContribution": v} for k, v in contributions.items()},
        }
        dc._detect_blend_integrity_violations([row], {})
        return row

    def test_the_live_incident_shape_is_not_flagged(self):
        """Truncated value one below a degenerate rounded hull."""
        row = self._detect(3459, {"ktcSfTep": 3460, "idpTradeCalc": 3460})
        self.assertIsNone(row.get("blendIntegrityViolation"))

    def test_truncation_skew_below_a_narrow_hull_is_not_flagged(self):
        """Same skew on a hull one unit wide."""
        row = self._detect(3459, {"a": 3460, "b": 3461})
        self.assertIsNone(row.get("blendIntegrityViolation"))

    def test_below_beyond_the_quantization_bound_still_fires(self):
        """Two whole units below the stamped floor cannot be rounding."""
        row = self._detect(3458, {"a": 3460, "b": 3460})
        self.assertEqual(row["blendIntegrityViolation"]["direction"], "below")

    def test_above_beyond_the_quantization_bound_still_fires(self):
        """Truncation never raises: one unit above the stamped ceiling
        is already impossible, and must still be detected."""
        row = self._detect(3461, {"a": 3460, "b": 3460})
        self.assertEqual(row["blendIntegrityViolation"]["direction"], "above")

    def test_the_allowance_is_quantization_scale_not_a_band(self):
        """Both allowances must stay below 2 units on a 1-9999 scale —
        wide enough for integer quantization, structurally too narrow to
        act as the corridor's policy band."""
        self.assertLessEqual(dc._BLEND_HULL_QUANTIZATION_BELOW, 1.5)
        self.assertLessEqual(dc._BLEND_HULL_QUANTIZATION_ABOVE, 0.5)


class TestMissingEvidenceStaysExplicit(unittest.TestCase):
    """ "Missing" is not "violating" — a hull needs two points."""

    def test_single_contribution_rows_are_skipped(self):
        row = {
            "displayName": "Thin",
            "canonicalConsensusRank": 5,
            "rankDerivedValue": 9999,
            "sourceRankMeta": {"a": {"valueContribution": 100}},
        }
        dc._detect_blend_integrity_violations([row], {})
        self.assertIsNone(row.get("blendIntegrityViolation"))

    def test_rows_with_no_contributions_are_skipped(self):
        row = {
            "displayName": "Empty",
            "canonicalConsensusRank": 5,
            "rankDerivedValue": 500,
            "sourceRankMeta": {},
        }
        dc._detect_blend_integrity_violations([row], {})
        self.assertIsNone(row.get("blendIntegrityViolation"))

    def test_unranked_rows_are_skipped(self):
        row = {
            "displayName": "Unranked",
            "canonicalConsensusRank": None,
            "rankDerivedValue": 9000,
            "sourceRankMeta": {"a": {"valueContribution": 10}, "b": {"valueContribution": 20}},
        }
        dc._detect_blend_integrity_violations([row], {})
        self.assertIsNone(row.get("blendIntegrityViolation"))


class TestConfidenceCannotAlterEnforcement(unittest.TestCase):
    """#796: the buckets were ordered backwards and must not gate anything."""

    def test_bucket_does_not_change_the_outcome(self):
        seen = set()
        for bucket in ("high", "medium", "low", None, "nonsense"):
            row = {
                "displayName": "X",
                "canonicalConsensusRank": 10,
                "confidenceBucket": bucket,
                "rankDerivedValue": 9000,
                "sourceRankMeta": {
                    "a": {"valueContribution": 1000},
                    "b": {"valueContribution": 2000},
                },
            }
            dc._detect_blend_integrity_violations([row], {})
            seen.add(bool(row.get("blendIntegrityViolation")))
        self.assertEqual(seen, {True}, "confidence bucket changed enforcement")


class TestNoCollateralImpact(unittest.TestCase):
    """Offense and picks were never in scope and still are not."""

    def test_offense_and_picks_are_detected_on_the_same_terms(self):
        """Not exempted by asset class — the invariant is universal.

        The corridor exempted offense explicitly. A structural invariant
        has no reason to: an impossible offense value is just as
        impossible. What keeps offense quiet is that its blends are not
        broken, not that a guard skips it.
        """
        rows = []
        for name, pos in (("O", "WR"), ("P", "PICK"), ("D", "DB")):
            rows.append(
                {
                    "displayName": name,
                    "assetClass": "offense"
                    if pos == "WR"
                    else ("pick" if pos == "PICK" else "idp"),
                    "canonicalConsensusRank": 10,
                    "rankDerivedValue": 9000,
                    "sourceRankMeta": {
                        "a": {"valueContribution": 1000},
                        "b": {"valueContribution": 2000},
                    },
                }
            )
        dc._detect_blend_integrity_violations(rows, {})
        self.assertEqual([bool(r.get("blendIntegrityViolation")) for r in rows], [True, True, True])


class TestTheViolationActuallyAbstains(unittest.TestCase):
    """Detection has to *do* something, or it is diagnostics wearing a hat.

    A value proven structurally impossible must not keep counting as an
    ordinary canonical value merely because we declined to clamp it. The
    abstention is expressed through the two fail-closed mechanisms this
    codebase already has, not a third one written for this detector:

    * **row level** — ``anomalyFlags`` → ``_QUARANTINE_FLAGS`` →
      ``quarantined = True`` + degraded ``confidenceBucket``, which the
      Consensus Edge scorer, BDVM and the /edge board already honour;
    * **build level** — an *error* from ``validate_api_data_contract``,
      which is what the existing ``scripts/validate_api_contract.py`` CI
      gate exits non-zero on.
    """

    def _violated_row(self):
        row = {
            "displayName": "Impossible DB",
            "canonicalName": "Impossible DB",
            "position": "DB",
            "assetClass": "idp",
            "canonicalConsensusRank": 10,
            "rankDerivedValue": 9000,
            "confidenceBucket": "high",
            "canonicalSiteValues": {"idpTradeCalc": 1000, "dlfIdp": 2000},
            "anomalyFlags": [],
            "sourceRankMeta": {
                "idpTradeCalc": {"valueContribution": 1000},
                "dlfIdp": {"valueContribution": 2000},
            },
        }
        dc._detect_blend_integrity_violations([row], {})
        return row

    def test_the_violation_is_recorded_as_an_anomaly_flag(self):
        """The stamp alone is invisible to every existing consumer.

        ``blendIntegrityViolation`` is a new key nothing reads. The
        anomaly-flag channel is the one the platform already routes on.
        """
        row = self._violated_row()
        self.assertIn("blend_integrity_violation", row.get("anomalyFlags") or [])

    def test_the_flag_is_quarantine_level(self):
        self.assertIn("blend_integrity_violation", dc._QUARANTINE_FLAGS)

    def test_the_row_is_quarantined_and_degraded_by_the_existing_pass(self):
        """End-to-end through the real quarantine pass, not a stub."""
        row = self._violated_row()
        dc._validate_and_quarantine_rows([row])
        self.assertTrue(row.get("quarantined"), "impossible value stayed un-quarantined")
        self.assertEqual(row.get("confidenceBucket"), "low")

    def test_the_value_is_still_not_coerced(self):
        """Abstention is not a licence to substitute a plausible number."""
        row = self._violated_row()
        dc._validate_and_quarantine_rows([row])
        self.assertEqual(row["rankDerivedValue"], 9000)
        self.assertIs(row["blendIntegrityViolation"]["valueAltered"], False)

    def test_a_representative_decision_engine_withholds(self):
        """Consensus Edge is row-level, so prove the row-level path lands.

        ``classify`` puts the quarantine branch ahead of every other
        consideration, so this is the actual production behaviour for a
        quarantined row rather than a re-implementation of it.
        """
        from src.consensus_edge import score as score_mod

        row = self._violated_row()
        dc._validate_and_quarantine_rows([row])
        label = score_mod.classify(
            80.0,
            90.0,
            {"conflicted": False},
            {},
            has_market_price=True,
            quarantined=bool(row.get("quarantined")),
        )
        self.assertEqual(label["label"], score_mod.WITHHELD)

    def test_healthy_disagreement_is_neither_flagged_nor_quarantined(self):
        """The false-positive side of the same mechanism."""
        row = {
            "displayName": "Contested DB",
            "canonicalName": "Contested DB",
            "position": "DB",
            "assetClass": "idp",
            "canonicalConsensusRank": 10,
            "rankDerivedValue": 1500,
            "confidenceBucket": "high",
            "canonicalSiteValues": {"idpTradeCalc": 100, "dlfIdp": 9000},
            "anomalyFlags": [],
            "sourceRankMeta": {
                "idpTradeCalc": {"valueContribution": 100},
                "dlfIdp": {"valueContribution": 9000},
            },
        }
        dc._detect_blend_integrity_violations([row], {})
        dc._validate_and_quarantine_rows([row])
        self.assertNotIn("blend_integrity_violation", row.get("anomalyFlags") or [])
        self.assertFalse(row.get("quarantined"))
        self.assertEqual(row.get("confidenceBucket"), "high")


class TestTheDocumentedOrderingIsTrue(unittest.TestCase):
    """The comment above the call site describes an order. Pin it.

    It previously claimed the detector ran "after all value-moving
    passes", which was false — the two-way boost and the Phase 5 pick
    passes both follow it. The corrected comment is load-bearing, because
    the reason for the placement is that the hull invariant describes a
    *blend*, and those later stages replace the blended value with a
    number computed from a different population.
    """

    def test_detection_precedes_the_override_passes(self):
        import inspect

        src = inspect.getsource(dc._compute_unified_rankings)
        detect = src.index("_detect_blend_integrity_violations(")
        boost = src.index("_apply_two_way_player_boost(")
        self.assertLess(detect, boost, "detector moved after the two-way override")

    def test_the_stale_after_all_passes_claim_is_not_asserted(self):
        """The phrase survives only inside the sentence retracting it.

        A blunt ``assertNotIn`` fails on the correction itself, which is
        how this test first behaved — the wrong shape for a guard whose
        job is to stop the *claim* coming back, not the words.
        """
        import inspect

        for line in inspect.getsource(dc._compute_unified_rankings).splitlines():
            if "after all value-moving passes" in line:
                self.assertIn(
                    "used to claim",
                    line,
                    f"the retracted ordering claim was re-asserted: {line.strip()}",
                )


class TestTheBuildRefusesAnImpossibleBoard(unittest.TestCase):
    """Build-level half: the existing contract validator, not a new one."""

    def _payload(self, *, violated: bool):
        row = {
            "displayName": "X",
            "canonicalName": "X",
            "position": "DB",
            "assetClass": "idp",
            "canonicalConsensusRank": 1,
            "rankDerivedValue": 9000,
        }
        if violated:
            row["blendIntegrityViolation"] = {
                "detected": True,
                "reason": "blend_outside_contribution_hull",
                "value": 9000,
                "contributionMin": 1000,
                "contributionMax": 2000,
                "direction": "above",
                "valueAltered": False,
                "sourceCount": 2,
            }
        return {"playersArray": [row]}

    def test_a_violated_board_is_an_error_not_a_warning(self):
        """Compare the two reports rather than asserting ``ok`` is False.

        A skeletal payload fails validation for a dozen unrelated
        structural reasons, so ``ok is False`` on the violated payload
        would pass whether or not this feature exists. The *delta*
        between clean and violated is the only part that isolates it.
        """
        clean = dc.validate_api_data_contract(self._payload(violated=False))
        violated = dc.validate_api_data_contract(self._payload(violated=True))

        new_errors = set(violated["errors"]) - set(clean["errors"])
        self.assertTrue(
            any("blend" in e.lower() for e in new_errors),
            f"violation added no blend-integrity error; delta was {new_errors or 'empty'}",
        )
        self.assertFalse(violated["ok"])
        # And it must be an ERROR, not a warning — the CI contract gate
        # (`scripts/validate_api_contract.py`) exits non-zero on `ok`
        # alone and ignores warnings entirely.
        new_warnings = set(violated["warnings"]) - set(clean["warnings"])
        self.assertFalse(
            any("blend" in w.lower() for w in new_warnings),
            "blend integrity was reported as a warning, which the CI gate ignores",
        )

    def test_a_clean_board_raises_no_blend_error(self):
        report = dc.validate_api_data_contract(self._payload(violated=False))
        self.assertFalse([e for e in report["errors"] if "blend" in e.lower()])


class TestTailPolicyCompatibility(unittest.TestCase):
    """The B4 tail repair and this detector must not interact."""

    def test_detector_is_independent_of_the_tail_boundary(self):
        from src.canonical import tail_policy

        prev = tail_policy.TAIL_SATURATION_RANK
        results = []
        try:
            for boundary in (None, 903):
                tail_policy.TAIL_SATURATION_RANK = boundary
                row = {
                    "displayName": "X",
                    "canonicalConsensusRank": 10,
                    "rankDerivedValue": 9000,
                    "sourceRankMeta": {
                        "a": {"valueContribution": 1000},
                        "b": {"valueContribution": 2000},
                    },
                }
                dc._detect_blend_integrity_violations([row], {})
                results.append(row.get("blendIntegrityViolation", {}).get("direction"))
        finally:
            tail_policy.TAIL_SATURATION_RANK = prev
        self.assertEqual(results, ["above", "above"])


if __name__ == "__main__":
    unittest.main()
