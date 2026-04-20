"""Single-curve invariants on the live rankings pipeline.

Pins the structural claim that the live path
(``src/api/data_contract.py::_compute_unified_rankings``) applies
exactly one Hill curve + at most one calibration multiplier to
produce ``rankDerivedValue``.  No hidden second curve, no accidental
double-calibration, no mystery remap.

The chain, as of the Final Framework transition PR 1:

    rankDerivedValueUncalibrated  (trimmed mean-median of per-source
                                    Hill values, post-TEP)
        × (idpCalibrationMultiplier × idpFamilyScale)   (IDP rows only)
        = rankDerivedValue

The prior volatility compression + monotonicity-cap post-pass has
been removed outright.  ``preVolatilityValue`` and
``volatilityCompressionApplied`` are no longer stamped.

These tests are invariant-band style (PR #154): they assert the
structural chain holds for today's snapshot, not specific values.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    _DISPLAY_SCALE_MAX,
    build_api_data_contract,
)


_REPO = Path(__file__).resolve().parents[2]
_IDP_POSITIONS = {"DL", "LB", "DB"}
_OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}


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


def _ranked_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r
        for r in contract.get("playersArray") or []
        if r.get("canonicalConsensusRank") and r.get("assetClass") != "pick"
    ]


class TestOffenseHasNoCalibrationLayer(unittest.TestCase):
    """Live offense rows must NOT carry IDP-calibration fields.

    ``_apply_offense_calibration_post_pass`` is intentionally commented
    out at ``src/api/data_contract.py::_compute_unified_rankings``
    (around line 5021).  Re-enabling it without a new invariant test
    would silently restack a second curve on top of the Hill blend.
    This test exists to catch that regression.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")

    def test_offense_rows_have_no_offense_calibration_multiplier(self) -> None:
        offending: list[str] = []
        for row in _ranked_rows(self.contract):
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            if "offenseCalibrationMultiplier" in row:
                offending.append(
                    f"{row.get('canonicalName')}: "
                    f"{row['offenseCalibrationMultiplier']}"
                )
        self.assertFalse(
            offending,
            "Offense rows carry offenseCalibrationMultiplier — "
            "_apply_offense_calibration_post_pass was re-enabled without "
            "an accompanying invariant. If intentional, add a test pinning "
            "the offense chain, then delete this assertion. Offenders: "
            f"{offending[:5]}",
        )


class TestVolatilityPassIsRemoved(unittest.TestCase):
    """No row should carry the stamps the removed volatility pass left.

    If ``_apply_volatility_compression_post_pass`` or an analogous
    second remap is ever re-added without a principled λ / α choice,
    this test will catch the re-introduction of the old stamps and
    fail loudly.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")

    def test_no_row_carries_prevolatility_stamp(self) -> None:
        offending = [
            r.get("canonicalName")
            for r in _ranked_rows(self.contract)
            if "preVolatilityValue" in r
        ]
        self.assertFalse(
            offending,
            f"{len(offending)} row(s) carry the removed "
            f"preVolatilityValue stamp: {offending[:5]}",
        )

    def test_no_row_carries_volatility_fraction_stamp(self) -> None:
        offending = [
            r.get("canonicalName")
            for r in _ranked_rows(self.contract)
            if "volatilityCompressionApplied" in r
        ]
        self.assertFalse(
            offending,
            f"{len(offending)} row(s) carry the removed "
            f"volatilityCompressionApplied stamp: {offending[:5]}",
        )


class TestValueChain(unittest.TestCase):
    """``rankDerivedValue`` is derived from exactly one Hill blend
    and at most one calibration multiplier.

    For offense rows (no live calibration): ``rankDerivedValue`` must
    equal ``rankDerivedValueUncalibrated`` exactly.

    For IDP rows with an active promoted calibration config:
    ``rankDerivedValue`` must equal
    ``rankDerivedValueUncalibrated × idpCalibrationMultiplier × idpFamilyScale``
    applied exactly once.

    For IDP rows without an active config (default test env —
    ``tests/conftest.py`` redirects the config path): same as offense,
    strict equality.

    The deeper invariant under an active config is also exercised in
    ``tests/idp_calibration/test_family_scale_once_only.py``.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_offense_final_equals_uncalibrated(self) -> None:
        checked = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            uncal = row.get("rankDerivedValueUncalibrated")
            final = row.get("rankDerivedValue")
            if uncal is None or final is None:
                continue
            self.assertEqual(
                int(final),
                int(uncal),
                f"{row.get('canonicalName')} offense row has "
                f"rankDerivedValue={final} != "
                f"rankDerivedValueUncalibrated={uncal}. "
                f"Either offense calibration was re-enabled, or a new "
                f"mystery multiplier was inserted after the blend.",
            )
            checked += 1
        self.assertGreater(checked, 50, "expected many offense anchors")

    def test_idp_final_is_one_time_calibration_fold(self) -> None:
        """IDP chain.

        When calibration is active, ``rankDerivedValue`` equals
        ``uncalibrated × (bucket × family_scale)`` applied exactly once.

        When calibration is neutral (fields absent), final equals
        uncalibrated.
        """
        checked = 0
        for row in self.rows:
            pos = str(row.get("position") or "").upper()
            if pos not in _IDP_POSITIONS:
                continue
            uncal = row.get("rankDerivedValueUncalibrated")
            final = row.get("rankDerivedValue")
            if uncal is None or final is None:
                continue
            bucket = row.get("idpCalibrationMultiplier")
            family = row.get("idpFamilyScale")
            if bucket is not None and family is not None:
                expected = int(round(float(uncal) * float(bucket) * float(family)))
                self.assertLessEqual(
                    abs(int(final) - expected),
                    2,
                    f"{row.get('canonicalName')} IDP (calibrated): "
                    f"rankDerivedValue={final} != round("
                    f"uncal={uncal} × bucket={bucket} × "
                    f"family={family}) = {expected}.  family_scale may "
                    f"have been double-applied, or a new IDP multiplier "
                    f"was introduced.",
                )
            else:
                self.assertEqual(
                    int(final),
                    int(uncal),
                    f"{row.get('canonicalName')} IDP (no calibration): "
                    f"rankDerivedValue={final} != uncalibrated={uncal}. "
                    f"A new IDP post-pass was added between Hill blend "
                    f"and final.",
                )
            checked += 1
        self.assertGreater(checked, 30, "expected many IDP anchors")


class TestHierarchicalAnchorChain(unittest.TestCase):
    """Pin the Final Framework PR 3 hierarchical anchor + α chain.

    For every multi-source ranked non-pick row, at least one of
    ``anchorValue`` or ``subgroupBlendValue`` must be stamped.  When
    both are present, the uncalibrated value should equal
    ``anchor + α·(subgroup − anchor) − λ·MAD`` (clamped non-negative),
    allowing a few points of integer-rounding slack at each stage.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_every_ranked_row_has_baseline_contribution(self) -> None:
        from src.api.data_contract import _ALPHA_SHRINKAGE  # noqa: PLC0415

        offenders: list[str] = []
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            anchor = row.get("anchorValue")
            subgroup = row.get("subgroupBlendValue")
            if anchor is None and subgroup is None:
                offenders.append(str(row.get("canonicalName") or ""))
        self.assertFalse(
            offenders,
            f"Ranked non-pick rows with no anchor or subgroup "
            f"contribution (should be impossible for ranked rows): "
            f"{offenders[:5]}",
        )
        # alphaShrinkage stamp should match the module constant.
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            stamped = row.get("alphaShrinkage")
            if stamped is None:
                continue
            self.assertAlmostEqual(
                float(stamped), _ALPHA_SHRINKAGE, places=4
            )

    def test_anchor_plus_shrunk_subgroup_matches_uncalibrated(self) -> None:
        """When both anchor and subgroup are stamped, their α-shrunk
        combination should match rankDerivedValueUncalibrated ± (MAD
        penalty + rounding).
        """
        from src.api.data_contract import (  # noqa: PLC0415
            _ALPHA_SHRINKAGE,
            _MAD_PENALTY_LAMBDA,
        )

        checked = 0
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            anchor = row.get("anchorValue")
            subgroup = row.get("subgroupBlendValue")
            delta = row.get("subgroupDelta")
            uncal = row.get("rankDerivedValueUncalibrated")
            mad = row.get("sourceMAD")
            if (
                anchor is None
                or subgroup is None
                or delta is None
                or uncal is None
            ):
                continue
            # Expected center BEFORE MAD penalty.
            expected_center = float(anchor) + _ALPHA_SHRINKAGE * float(delta)
            expected_penalty = 0.0
            if mad is not None:
                expected_penalty = min(
                    expected_center, _MAD_PENALTY_LAMBDA * float(mad)
                )
            expected_uncal = max(0.0, expected_center - expected_penalty)
            self.assertLessEqual(
                abs(int(uncal) - int(round(expected_uncal))),
                3,
                f"{row.get('canonicalName')}: uncalibrated={uncal} "
                f"differs from anchor({anchor}) + α({_ALPHA_SHRINKAGE})·"
                f"Δ({delta}) − λ({_MAD_PENALTY_LAMBDA})·MAD({mad}) = "
                f"{expected_uncal:.1f}",
            )
            checked += 1
        self.assertGreater(checked, 50, "expected many hierarchically-covered rows")


class TestMADPenaltyChain(unittest.TestCase):
    """Pin the Final Framework step 6 MAD penalty chain.

    For every ranked non-pick row with ≥ 2 sources:
      * ``sourceMAD`` is stamped with the trimmed-mean absolute deviation
        of the per-source Hill-curve values.
      * When λ = _MAD_PENALTY_LAMBDA > 0, ``madPenaltyApplied`` is
        stamped with the subtracted penalty, and the penalty is
        exactly ``min(center, λ · MAD)``.

    Picks are intentionally exempt (see comment at the penalty site
    for why), so their ``madPenaltyApplied`` is always ``None``.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_nonpick_rows_carry_source_mad_when_multi_source(self) -> None:
        from src.api.data_contract import _MAD_PENALTY_LAMBDA  # noqa: PLC0415

        checked = 0
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            src_ranks = row.get("sourceRanks") or {}
            if len(src_ranks) < 2:
                continue
            mad = row.get("sourceMAD")
            self.assertIsNotNone(
                mad,
                f"{row.get('canonicalName')}: multi-source row missing "
                f"sourceMAD stamp",
            )
            self.assertGreaterEqual(
                float(mad), 0.0,
                f"{row.get('canonicalName')}: sourceMAD={mad} is negative",
            )
            checked += 1
        self.assertGreater(checked, 50, "expected many multi-source rows")

        if _MAD_PENALTY_LAMBDA <= 0:
            return  # nothing further to pin when the feature is a no-op

        # When λ > 0, mad_penalty == min(center, λ · MAD) and
        # final == center - penalty.  We can't recompute center directly
        # without the raw contributions, but we CAN verify that
        # penalty ≤ λ · MAD (the clamp never adds value, only caps it)
        # and that final ≤ uncalibrated (the penalty is always a
        # reduction, never a boost).
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            mad = row.get("sourceMAD")
            penalty = row.get("madPenaltyApplied")
            if mad is None or penalty is None:
                continue
            expected_max = _MAD_PENALTY_LAMBDA * float(mad)
            self.assertLessEqual(
                float(penalty),
                expected_max + 1.0,
                f"{row.get('canonicalName')}: madPenaltyApplied={penalty} "
                f"exceeds λ·MAD = {expected_max:.2f}",
            )

    def test_picks_never_get_mad_penalty(self) -> None:
        """Pick rows must have madPenaltyApplied == None regardless of λ."""
        offenders: list[str] = []
        for row in _ranked_rows(self.contract):
            if row.get("assetClass") != "pick":
                continue
            if row.get("madPenaltyApplied") not in (None, 0):
                offenders.append(
                    f"{row.get('canonicalName')}: "
                    f"{row['madPenaltyApplied']}"
                )
        self.assertFalse(
            offenders,
            f"Pick rows carrying MAD penalty (should be exempt): "
            f"{offenders[:5]}",
        )


class TestSoftFallback(unittest.TestCase):
    """Pin Final Framework step 9: soft fallback for unranked players.

    Every ranked non-pick row must carry a ``softFallbackCount`` field
    (an integer ≥ 0).  The count represents the number of active
    sources that could have ranked the player but didn't, contributing
    a "just past the published list" imputed value to the blend.

    Sanity bounds:
      - softFallbackCount is always ≥ 0.
      - When _SOFT_FALLBACK_ENABLED is True, most ranked rows have at
        least one fallback source (there are 16 active sources and
        very few players are covered by all 16).
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_soft_fallback_count_stamped(self) -> None:
        missing: list[str] = []
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            if "softFallbackCount" not in row:
                missing.append(str(row.get("canonicalName") or ""))
        self.assertFalse(
            missing,
            f"Ranked non-pick rows without softFallbackCount: "
            f"{missing[:5]}",
        )

    def test_soft_fallback_count_nonnegative(self) -> None:
        for row in self.rows:
            sfc = row.get("softFallbackCount")
            if sfc is None:
                continue
            self.assertGreaterEqual(
                int(sfc), 0,
                f"{row.get('canonicalName')}: negative softFallbackCount",
            )

    def test_fallback_provides_broad_coverage(self) -> None:
        """With 16 active sources, most ranked players should see at
        least one fallback contribution — very few are covered by
        every source."""
        from src.api.data_contract import _SOFT_FALLBACK_ENABLED  # noqa: PLC0415
        if not _SOFT_FALLBACK_ENABLED:
            self.skipTest("soft fallback disabled")
        sf_counts = [
            int(r.get("softFallbackCount") or 0)
            for r in self.rows
            if r.get("assetClass") != "pick"
        ]
        if not sf_counts:
            self.skipTest("no non-pick ranked rows")
        with_fallback = sum(1 for c in sf_counts if c > 0)
        pct = 100.0 * with_fallback / len(sf_counts)
        self.assertGreater(
            pct, 50.0,
            f"Expected >50% of ranked rows to have at least one "
            f"fallback contribution; got {pct:.1f}%",
        )


class TestScopeMasterRouting(unittest.TestCase):
    """Pin the updated-framework scope-master routing.

    Each source's contribution uses its SCOPE-appropriate master
    curve, not the row's position family:
      - anchor (IDPTC, dual-scope) → GLOBAL master
      - offense-scope sources      → OFFENSE master
      - IDP-scope sources          → IDP master

    The per-source ``sourceRankMeta[*].valueContribution`` should
    therefore reflect V(p) under each source's scope curve.  We
    sanity-check that:
      1. The anchor's valueContribution for a top player is
         consistent with the GLOBAL master's V(p=0) ≈ 9999.
      2. Offense-scope and IDP-scope sources produce different V(p)
         at the same effective rank (because they use different
         Hill constants).
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_anchor_top_rank_contribution_near_max(self) -> None:
        # Find the anchor's rank-1 player.  Their anchor valueContribution
        # should be ≈ 9999 regardless of which scope curve is in play
        # (all Hill curves pin p=0 to 9999).
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            anchor_meta = meta.get("idpTradeCalc") or {}
            if anchor_meta.get("rawRank") == 1:
                v = anchor_meta.get("valueContribution")
                self.assertIsNotNone(v)
                # Allow a tiny slack for rounding + TEP boost (TEs may
                # exceed 9999 post-boost).
                self.assertGreater(int(v), 9000)
                return
        self.skipTest("no anchor rank-1 player in snapshot")

    def test_offense_and_idp_masters_differ(self) -> None:
        """With different scope masters in play, two sources at the
        same effective rank but different scopes should produce
        different V values on the same player (absent TEP, absent
        fallback).
        """
        from src.canonical.player_valuation import (  # noqa: PLC0415
            HILL_PERCENTILE_C,
            HILL_PERCENTILE_S,
            IDP_HILL_PERCENTILE_C,
            IDP_HILL_PERCENTILE_S,
            percentile_to_value,
        )
        # Sanity — the two master curves produce different V at
        # typical mid-pack percentile.
        p = 0.1
        off_v = int(
            percentile_to_value(
                p, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S
            )
        )
        idp_v = int(
            percentile_to_value(
                p, midpoint=IDP_HILL_PERCENTILE_C, slope=IDP_HILL_PERCENTILE_S
            )
        )
        self.assertNotEqual(
            off_v, idp_v,
            f"Offense and IDP master curves produce identical V at p={p}: "
            f"{off_v}.  Framework-update requires distinct scope curves."
        )


class TestRookieScopeRouting(unittest.TestCase):
    """Framework steps 5-6 (rookie scope): rookie-only sources use
    the ROOKIE master curve with their native pool size N_j, not a
    ladder-translated rank against the OFFENSE / IDP master.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_rookie_source_rank_one_gets_max_value(self) -> None:
        """A rookie source's rank-1 player should have V=9999 from
        the ROOKIE master (p=0).  Under the old ladder-translation
        this value was the OFFENSE-master-mapped reference-source
        rank and therefore less than 9999.
        """
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            for src_key in ("dlfRookieSf", "dlfRookieIdp"):
                m = meta.get(src_key) or {}
                if m.get("rawRank") != 1:
                    continue
                # Rookie rank 1 now maps to p=0 → V=9999 under ROOKIE
                # master.  Ladder is off.
                self.assertEqual(
                    m.get("effectiveRank"),
                    1,
                    f"{src_key} rank-1 player "
                    f"{row.get('canonicalName')} has eff_rank "
                    f"{m.get('effectiveRank')} != 1 — rookie-ladder "
                    f"translation should be OFF.",
                )
                self.assertEqual(
                    int(m.get("valueContribution") or 0),
                    9999,
                    f"{src_key} rank-1 V="
                    f"{m.get('valueContribution')} != 9999 — ROOKIE "
                    f"master should map p=0 → 9999.",
                )
                return
        self.skipTest("no rookie rank-1 player in snapshot")

    def test_rookie_master_differs_from_offense_and_idp(self) -> None:
        from src.canonical.player_valuation import (  # noqa: PLC0415
            HILL_PERCENTILE_C,
            HILL_PERCENTILE_S,
            HILL_ROOKIE_PERCENTILE_C,
            HILL_ROOKIE_PERCENTILE_S,
            IDP_HILL_PERCENTILE_C,
            IDP_HILL_PERCENTILE_S,
            percentile_to_value,
        )
        p = 0.3
        off_v = int(percentile_to_value(
            p, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S
        ))
        idp_v = int(percentile_to_value(
            p, midpoint=IDP_HILL_PERCENTILE_C, slope=IDP_HILL_PERCENTILE_S
        ))
        rook_v = int(percentile_to_value(
            p,
            midpoint=HILL_ROOKIE_PERCENTILE_C,
            slope=HILL_ROOKIE_PERCENTILE_S,
        ))
        # All three masters must produce distinct V at p=0.3.
        self.assertNotEqual(rook_v, off_v)
        self.assertNotEqual(rook_v, idp_v)


class TestNoSecondHillCurve(unittest.TestCase):
    """No live row can carry values consistent with a second Hill remap.

    A second Hill application after calibration would collapse the
    dynamic range (two compound S-curves stack into something much
    flatter).  We sanity-check that top-of-board values are spread
    widely enough to be inconsistent with a hidden second curve.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_top_50_value_range_is_wide(self) -> None:
        offense = sorted(
            (
                r
                for r in self.rows
                if str(r.get("position") or "").upper() in _OFFENSE_POSITIONS
            ),
            key=lambda r: int(r["canonicalConsensusRank"]),
        )[:50]
        if len(offense) < 50:
            self.skipTest("fewer than 50 offense rows ranked")
        top = int(offense[0]["rankDerivedValue"])
        bottom = int(offense[-1]["rankDerivedValue"])
        spread = top - bottom
        # Single Hill curve with our constants: rank 1 ≈ 9999, rank 50
        # ≈ 5000.  A second curve would compress this below ~3000.
        # 2500 is a forgiving floor — a real second-curve regression
        # would drop it far below that.
        self.assertGreater(
            spread,
            2500,
            f"Top-50 offense value spread collapsed to {spread} "
            f"({top}..{bottom}). A second Hill remap may have been "
            f"introduced; investigate calibration passes.",
        )

    def test_no_value_exceeds_display_scale(self) -> None:
        """rankDerivedValue must stay within the display scale."""
        offenders: list[tuple[str, int]] = []
        for row in self.rows:
            final = row.get("rankDerivedValue")
            if final is None:
                continue
            try:
                v = int(final)
            except (TypeError, ValueError):
                continue
            if v > _DISPLAY_SCALE_MAX:
                offenders.append((str(row.get("canonicalName") or ""), v))
        self.assertFalse(
            offenders,
            f"Rows above _DISPLAY_SCALE_MAX={_DISPLAY_SCALE_MAX}: "
            f"{offenders[:5]}",
        )
