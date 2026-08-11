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
