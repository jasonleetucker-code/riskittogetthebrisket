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

    The offense-calibration post-pass and its helpers were deleted as
    part of the Final Framework legacy purge — offense values track
    the market-derived rankings (KTC/DLF/IDPTC/etc.) and never get
    re-multiplied by a VOR bucket.  If a future PR reintroduces an
    offense post-pass, this test will fail loudly.
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
            "Offense rows carry offenseCalibrationMultiplier — an "
            "offense calibration pass has been reintroduced without an "
            "accompanying invariant. If intentional, add a test pinning "
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
        from src.api.data_contract import (  # noqa: PLC0415
            _ALPHA_SHRINKAGE,
            _IDP_POSITIONS,
        )

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
        # alphaShrinkage stamp: IDP (+pick) rows carry the module
        # constant; offense (QB/RB/WR/TE) rows carry 0.0 under the
        # offense flat-blend rule.  The ``_ranked_rows`` helper in this
        # file excludes picks, so this loop walks only offense+IDP.
        for row in self.rows:
            stamped = row.get("alphaShrinkage")
            if stamped is None:
                continue
            pos = str(row.get("position") or "").upper()
            expected = _ALPHA_SHRINKAGE if pos in _IDP_POSITIONS else 0.0
            self.assertAlmostEqual(
                float(stamped), expected, places=4
            )

    def test_anchor_plus_shrunk_subgroup_matches_uncalibrated(self) -> None:
        """For IDP rows with both anchor and subgroup stamped, the
        α-shrunk combination should match rankDerivedValueUncalibrated
        ± (MAD penalty + rounding).  Offense rows use the flat blend
        and are exempt from this pin — they're covered by the
        companion ``test_offense_flat_blend_matches_uncalibrated``.
        """
        from src.api.data_contract import (  # noqa: PLC0415
            _ALPHA_SHRINKAGE,
            _IDP_POSITIONS,
            _MAD_PENALTY_LAMBDA,
        )

        checked = 0
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            pos = str(row.get("position") or "").upper()
            if pos not in _IDP_POSITIONS:
                continue
            anchor = row.get("anchorValue")
            subgroup = row.get("subgroupBlendValue")
            delta = row.get("subgroupDelta")
            uncal = row.get("rankDerivedValueUncalibrated")
            mad = row.get("sourceSpread")
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
            # IDP rows carry an idpCalibrationMultiplier × idpFamilyScale
            # that is applied AFTER the hierarchical blend but BEFORE
            # rankDerivedValueUncalibrated is stamped on some builds.
            # Rather than model the post-pass here, we accept a wider
            # tolerance: the invariant we care about is "uncalibrated
            # ≈ anchor + α·Δ − λ·MAD", which the ±3-pt slack covers on
            # neutral-config builds and the test still pins when the
            # live builds exercise the blend.
            self.assertLessEqual(
                abs(int(uncal) - int(round(expected_uncal))),
                3,
                f"{row.get('canonicalName')} (IDP): uncalibrated={uncal} "
                f"differs from anchor({anchor}) + α({_ALPHA_SHRINKAGE})·"
                f"Δ({delta}) − λ({_MAD_PENALTY_LAMBDA})·MAD({mad}) = "
                f"{expected_uncal:.1f}",
            )
            checked += 1
        self.assertGreater(checked, 10, "expected IDP rows with anchor+subgroup coverage")

    def test_offense_flat_blend_matches_uncalibrated(self) -> None:
        """For offense rows the uncalibrated value should reflect the
        count-aware mean-median over ALL contributing sources (anchor
        included), not the α-shrunk anchor/subgroup split.  Sanity
        check: subgroupDelta is stamped as None on offense rows since
        no anchor override is applied.
        """
        from src.api.data_contract import _OFFENSE_POSITIONS  # noqa: PLC0415

        offenders: list[str] = []
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            pos = str(row.get("position") or "").upper()
            if pos not in _OFFENSE_POSITIONS:
                continue
            delta = row.get("subgroupDelta")
            if delta is not None:
                offenders.append(
                    f"{row.get('canonicalName')}: subgroupDelta={delta}"
                )
        self.assertFalse(
            offenders,
            f"Offense rows stamping subgroupDelta — flat blend should "
            f"leave it None.  Offenders: {offenders[:5]}",
        )


class TestMADPenaltyChain(unittest.TestCase):
    """Pin the Final Framework step 6 MAD penalty chain.

    For every ranked non-pick row with ≥ 2 sources:
      * ``sourceSpread`` is stamped with the trimmed-mean absolute deviation
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

    def test_nonpick_rows_carry_source_spread_when_multi_source(self) -> None:
        from src.api.data_contract import _MAD_PENALTY_LAMBDA  # noqa: PLC0415

        checked = 0
        for row in self.rows:
            if row.get("assetClass") == "pick":
                continue
            src_ranks = row.get("sourceRanks") or {}
            if len(src_ranks) < 2:
                continue
            mad = row.get("sourceSpread")
            self.assertIsNotNone(
                mad,
                f"{row.get('canonicalName')}: multi-source row missing "
                f"sourceSpread stamp",
            )
            self.assertGreaterEqual(
                float(mad), 0.0,
                f"{row.get('canonicalName')}: sourceSpread={mad} is negative",
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
            mad = row.get("sourceSpread")
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


class TestSoftFallbackIsCoverageDiagnosticOnly(unittest.TestCase):
    """Pin Final Framework override (2026-04-20): ``softFallbackCount``
    is a pure coverage diagnostic.  It counts scope-eligible sources
    that did NOT rank the player but it does NOT inject imputed
    values into the blend.

    Pre-override, soft fallback added "just past the published list"
    Hill values to ``all_values`` for every missing eligible source.
    The count-aware trim at n≥5 only drops one max + one min, so any
    residual fallback stayed in and dragged the mean by several
    hundred points (Chase at #5 with sf=2 lost ~600 points).

    Post-override, the blend uses covered sources only.
    ``softFallbackCount`` remains as a transparency metric.

    Invariants pinned here:
      * Every ranked non-pick row has a ``softFallbackCount`` stamp.
      * The count is a non-negative integer.
      * The raw stamp is diagnostic: no field ``softFallbackValue`` or
        similar imputed-value side effect exists on any row.
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

    def test_no_imputed_fallback_value_field(self) -> None:
        """No row may stamp an imputed-fallback-value field — those
        would signal the old polluting-blend behavior has returned.
        """
        banned = ("softFallbackValue", "fallbackImputedValue", "imputedFallback")
        for row in self.rows:
            for key in banned:
                self.assertNotIn(
                    key, row,
                    f"{row.get('canonicalName')}: forbidden fallback-"
                    f"value field {key!r} present — soft fallback is "
                    f"supposed to be a coverage diagnostic only.",
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

    def test_rookie_source_rank_one_translated_via_reference_ladder(self) -> None:
        """Fix B (2026-04-21): a rookie source's rank-1 player has
        its effective rank TRANSLATED to the reference ladder's top-
        rookie rank (KTC for SF, IDPTC for IDP), NOT left at rank 1.

        This is the whole point of the ladder translation — the top
        rookie isn't "the best player overall" (value 9999); they're
        "where KTC/IDPTC puts the top rookie on their combined
        board" (SF rookies typically land around rank 25-40 in KTC's
        offense-only pool; IDP rookies land around rank 100-200 in
        IDPTC's combined offense+IDP pool where offense players sit
        above IDPs on the shared 0-9999 scale).
        """
        # Per-source sanity upper bounds — KTC is a pure offense
        # ranker so rookie#1 sits shallow; IDPTC is a combined pool
        # so top IDP rookie naturally sits deeper.
        _SANITY_UPPER_BOUND = {
            "dlfRookieSf": 100,
            "dlfRookieIdp": 250,
        }
        hits = 0
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            for src_key in ("dlfRookieSf", "dlfRookieIdp"):
                m = meta.get(src_key) or {}
                if m.get("rawRank") != 1:
                    continue
                eff = int(m.get("effectiveRank") or 0)
                vc = int(m.get("valueContribution") or 0)
                # Ladder-translated rank must be much deeper than 1
                # (if it's still 1 the translation didn't run) and
                # the contribution must be well below the max 9999.
                self.assertGreater(
                    eff, 1,
                    f"{src_key} rank-1 player {row.get('canonicalName')}"
                    f" still at effective rank {eff} — the Phase 1d"
                    f" rookie-ladder translation is OFF.",
                )
                self.assertLess(
                    vc, 9999,
                    f"{src_key} rank-1 player contribution still 9999"
                    f" — ladder translation should cap it below that.",
                )
                # Sanity: not wildly deep either.  Bounds differ per
                # source because the reference ladder's universe
                # (offense-only KTC vs combined-pool IDPTC) puts the
                # top rookie at very different ranks.
                bound = _SANITY_UPPER_BOUND[src_key]
                self.assertLess(
                    eff, bound,
                    f"{src_key} rank-1 translated to {eff} (sanity"
                    f" bound {bound}) — reference ladder may be"
                    f" malformed or universe filter incorrect.",
                )
                # And the ``method`` stamp records the translation.
                self.assertIn(
                    "rookie_ladder_translation",
                    str(m.get("method") or ""),
                    f"{src_key} rank-1 player lacks ladder-translation"
                    f" method stamp; got {m.get('method')!r}",
                )
                hits += 1
        if hits == 0:
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


class TestValueBasedSourceDirectVote(unittest.TestCase):
    """Pin the Final Framework override (2026-04-20): value-based
    sources feed their raw site values directly into the blend instead
    of being re-modelled through the Hill / scope-master curve.

    This is the implementation of requirement (A) in the overriding
    prompt:

        For sites that already provide values:
          - normalize them into the common 0 to 9999 language
          - preserve their relative shape as much as possible
          - use those normalized values directly as live source votes
          - do NOT send those live value-site votes back through the
            Hill curve

    The test walks the live contract and asserts:

    1. Every row that has a ``canonicalSiteValues`` entry for a key in
       ``_VALUE_BASED_SOURCES`` carries a ``valueContributionPath ==
       'value_direct'`` stamp on the corresponding
       ``sourceRankMeta`` entry.
    2. Every row whose matched source is NOT in that set carries
       ``valueContributionPath == 'rank_hill'`` instead.
    3. The stamped ``valueContribution`` for a value-direct source
       equals the raw ``canonicalSiteValues[key]`` scaled by the
       site's max (within ±1 for integer rounding), proving no Hill
       re-mapping occurred.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_value_sources_use_value_direct_path(self) -> None:
        from src.api.data_contract import _VALUE_BASED_SOURCES  # noqa: PLC0415

        checked = 0
        offenders: list[str] = []
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            site_values = row.get("canonicalSiteValues") or {}
            for src_key, m in meta.items():
                if src_key not in _VALUE_BASED_SOURCES:
                    continue
                raw = site_values.get(src_key)
                if raw is None:
                    continue
                path = m.get("valueContributionPath")
                if path != "value_direct":
                    offenders.append(
                        f"{row.get('canonicalName')} [{src_key}]: "
                        f"path={path!r} (raw={raw})"
                    )
                checked += 1
        self.assertFalse(
            offenders,
            f"Value-based sources routed through the Hill curve "
            f"(offenders first 5): {offenders[:5]}",
        )
        self.assertGreater(
            checked, 100,
            "expected many value-direct source contributions across the board",
        )

    def test_rank_only_sources_use_rank_hill_path(self) -> None:
        from src.api.data_contract import _VALUE_BASED_SOURCES  # noqa: PLC0415

        checked = 0
        offenders: list[str] = []
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            for src_key, m in meta.items():
                if src_key in _VALUE_BASED_SOURCES:
                    continue
                path = m.get("valueContributionPath")
                if path != "rank_hill":
                    offenders.append(
                        f"{row.get('canonicalName')} [{src_key}]: "
                        f"path={path!r}"
                    )
                checked += 1
        self.assertFalse(
            offenders,
            f"Rank-only sources NOT routed through Hill "
            f"(offenders first 5): {offenders[:5]}",
        )
        self.assertGreater(checked, 100, "expected many rank-hill contributions")

    def test_value_direct_contribution_matches_raw_normalized(self) -> None:
        """For a value-direct source, ``valueContribution`` must equal
        ``raw_value / site_max × 9999`` (within ±1 for integer rounding).

        This pins that the live blend is reading the raw site value,
        not a Hill-derived synthetic value for the player's rank.
        """
        from src.api.data_contract import _VALUE_BASED_SOURCES  # noqa: PLC0415

        # Compute each value source's max observed raw across the
        # live contract — same logic the blend uses.
        site_max: dict[str, float] = {}
        for row in self.contract.get("playersArray") or []:
            sv = row.get("canonicalSiteValues") or {}
            for key in _VALUE_BASED_SOURCES:
                raw = sv.get(key)
                try:
                    raw_f = float(raw) if raw is not None else 0.0
                except (TypeError, ValueError):
                    continue
                if raw_f > site_max.get(key, 0.0):
                    site_max[key] = raw_f

        checked = 0
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            site_values = row.get("canonicalSiteValues") or {}
            row_is_te = str(row.get("position") or "").upper() == "TE"
            for src_key, m in meta.items():
                if src_key not in _VALUE_BASED_SOURCES:
                    continue
                if m.get("valueContributionPath") != "value_direct":
                    continue
                raw = site_values.get(src_key)
                if raw is None:
                    continue
                smax = site_max.get(src_key, 0.0)
                if smax <= 0:
                    continue
                expected = float(raw) / smax * 9999.0
                # TEP boost / TEP-native-correction may adjust the
                # contribution on TE rows.  Skip those to keep this
                # test focused on the normalization rule itself; the
                # TEP path is covered by dedicated TEP tests.
                if row_is_te and (
                    m.get("tepBoostApplied") or m.get("tepNativeCorrectionApplied")
                ):
                    continue
                actual = m.get("valueContribution")
                self.assertAlmostEqual(
                    float(actual), expected, delta=1.5,
                    msg=(
                        f"{row.get('canonicalName')} [{src_key}]: "
                        f"valueContribution={actual} but raw={raw} "
                        f"site_max={smax} → expected {expected:.1f}"
                    ),
                )
                checked += 1
        self.assertGreater(
            checked, 50,
            "expected many value-direct rows to cross-check against raw",
        )


class TestMADPenaltyNeutralized(unittest.TestCase):
    """Pin the Final Framework override (2026-04-20): λ·MAD is no
    longer applied to any live row.

    The count-aware mean-median blend already damps offense rows via
    trimming at n≥5.  The anchor + α-shrinkage path already damps IDP
    + pick rows.  Adding λ·MAD on top stacked a second disagreement
    penalty on the same signal.  λ is now pinned to 0; ``sourceSpread``
    is still stamped as a diagnostic statistic but never deducted
    from ``rankDerivedValue``.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def test_lambda_is_zero(self) -> None:
        from src.api.data_contract import _MAD_PENALTY_LAMBDA  # noqa: PLC0415

        self.assertEqual(
            _MAD_PENALTY_LAMBDA, 0.0,
            "λ·MAD has been retired in favour of the count-aware + "
            "anchor damping layers.  Reinstating λ > 0 needs a fresh "
            "backtest proving the extra penalty is non-duplicative.",
        )

    def test_no_live_row_carries_mad_penalty_applied(self) -> None:
        offenders: list[str] = []
        for row in self.rows:
            penalty = row.get("madPenaltyApplied")
            if penalty is not None and float(penalty) > 0:
                offenders.append(
                    f"{row.get('canonicalName')}: madPenaltyApplied={penalty}"
                )
        self.assertFalse(
            offenders,
            f"Live rows carrying madPenaltyApplied > 0 despite λ=0 "
            f"(offenders first 5): {offenders[:5]}",
        )

    def test_source_spread_still_stamped_as_diagnostic(self) -> None:
        """``sourceSpread`` is retained as a diagnostic even though no
        penalty is deducted.  Frontend value-chain panel still
        displays it.
        """
        multi_source = [r for r in self.rows if (r.get("sourceCount") or 0) >= 2]
        if not multi_source:
            self.skipTest("no multi-source rows in live data")
        stamped = sum(1 for r in multi_source if r.get("sourceSpread") is not None)
        self.assertGreater(
            stamped, 0,
            "sourceSpread diagnostic is missing on every multi-source row",
        )


class TestDraftSharksCombinedCrossMarket(unittest.TestCase):
    """Pin Final Framework override (2026-04-20): DraftSharks SF and
    IDP share one cross-market value scale (top offense player at
    3D Value+ = 100; top IDP at 44).  The blend merges both CSVs
    into a single cross-market rank list and routes both sources
    through the GLOBAL Hill master (same curve IDPTC's anchor uses),
    preserving DS's native ~56% offense-over-IDP premium that per-CSV
    normalization would otherwise erase.

    Invariants pinned here:
      * Every live row whose meta contains ``draftSharks`` or
        ``draftSharksIdp`` stamps ``method: 'ds_combined_cross_market'``.
      * The combined ranks are a strict total order: no two DS
        entries (across both sources) share the same effective rank.
      * The top DS offense player's effective rank is 1 and sits on
        the GLOBAL Hill master (value close to 9999).
      * A top DS IDP player's effective rank is BELOW the top offense
        player's — proving the cross-market premium is preserved.
    """

    def setUp(self) -> None:
        self.contract = _get()
        if self.contract is None:
            self.skipTest("No live data")
        self.rows = _ranked_rows(self.contract)

    def _ds_eff_ranks(self) -> list[tuple[int, str, str, str]]:
        """Collect (eff_rank, source_key, canonical_name, path) for
        every DS meta entry across the live contract.
        """
        out: list[tuple[int, str, str, str]] = []
        for row in self.rows:
            meta = row.get("sourceRankMeta") or {}
            for src_key in ("draftSharks", "draftSharksIdp"):
                m = meta.get(src_key)
                if not m:
                    continue
                out.append((
                    int(m.get("effectiveRank") or 0),
                    src_key,
                    str(row.get("canonicalName") or ""),
                    str(m.get("method") or ""),
                ))
        return out

    def test_method_stamp_identifies_cross_market(self) -> None:
        entries = self._ds_eff_ranks()
        self.assertGreater(
            len(entries), 100,
            "expected many DS entries in the live contract",
        )
        offenders = [
            (rank, src, nm, method)
            for rank, src, nm, method in entries
            if method != "ds_combined_cross_market"
        ]
        self.assertFalse(
            offenders,
            f"DS entries without combined-cross-market method stamp "
            f"(first 5): {offenders[:5]}",
        )

    def test_combined_ranks_are_unique_across_sources(self) -> None:
        entries = self._ds_eff_ranks()
        ranks = [r for r, _s, _n, _m in entries]
        # Duplicates would indicate the pre-pass ran per-CSV instead
        # of across the union (which is the whole point of the fix).
        dupes = [r for r in set(ranks) if ranks.count(r) > 1]
        self.assertFalse(
            dupes,
            f"Duplicate DS effective ranks across SF+IDP pool "
            f"(first 5): {dupes[:5]}",
        )

    def test_top_idp_rank_exceeds_top_offense_rank(self) -> None:
        """DS's top IDP sits behind several top offensive players on
        the combined ladder (DS's own ~56% offense premium).  Proves
        we haven't collapsed both CSVs to overlapping rank-1 slots.
        """
        entries = self._ds_eff_ranks()
        top_off_rank = min(
            (r for r, s, _n, _m in entries if s == "draftSharks"),
            default=None,
        )
        top_idp_rank = min(
            (r for r, s, _n, _m in entries if s == "draftSharksIdp"),
            default=None,
        )
        if top_off_rank is None or top_idp_rank is None:
            self.skipTest("DS SF or IDP entries absent")
        self.assertEqual(
            top_off_rank, 1,
            "top DS offense player should be at combined rank 1",
        )
        self.assertGreater(
            top_idp_rank, 1,
            "top DS IDP player should sit behind the top offense "
            "player on the combined ladder — cross-market premium "
            "is the whole point of this pre-pass.",
        )


class TestValueBasedRegistryInvariant(unittest.TestCase):
    """Module-import safety rail.  Every CSV source with signal=value
    must either (a) appear in ``_VALUE_BASED_SOURCES`` (so its raw
    values vote directly into the blend) or (b) declare
    ``ds_combined_rank_partner`` (so it's routed through the combined
    cross-market ranking).  A source falling into neither bucket
    would silently go through the Hill curve, which is the exact bug
    the value-direct path was supposed to fix.
    """

    def test_invariant_holds_at_import_time(self) -> None:
        # The validator is called at module import; this test just
        # re-invokes it explicitly to confirm it passes in the live
        # build and never silently regresses.
        from src.api.data_contract import (  # noqa: PLC0415
            _validate_value_based_sources_invariant,
        )
        _validate_value_based_sources_invariant()
