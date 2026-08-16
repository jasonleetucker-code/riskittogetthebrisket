"""Numeric stage tests for the live valuation pipeline.

``src/api/data_contract.py::_compute_unified_rankings`` is the single
code path that decides every live player value (CLAUDE.md "Live Value
Pipeline", 12 stages).  Its individual helpers — the Hampel filter and
``count_aware_mean_median_blend`` — already have unit tests
(``test_hampel_filter.py``, ``test_count_aware_blend.py``), and the
whole-board behaviour is asserted in ``test_data_contract.py`` /
``test_single_curve_live.py``.

The gap this module closes: **both of those whole-board modules are in
``_LIVEDATA_MODULES``** (tests/conftest.py), so CI's
``-m "not livedata"`` gate deselects them.  Before this file, the
stage arithmetic below — the single-source haircut, α-shrinkage
routing, the percentile clamp and the pick-year discount — had **no
CI-blocking test at all**.  A refactor that changed any of these
constants would go green in CI and silently reprice the entire board.

Every assertion here is an exact number with the arithmetic worked out
in a comment.  These are pure-logic tests over synthetic rows: no
network, no live exports, no ``livedata`` marker.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.api import data_contract as dc


IDP_POSITIONS = ("DL", "LB", "DB")


def _row(name: str, position: str, **sites: Any) -> dict[str, Any]:
    """Minimal synthetic player row in ``playersArray`` shape.

    Mirrors the fixture helper in ``test_single_source_resolution.py``
    so both modules stress the same entry point the same way.
    """
    if position == "PICK":
        asset_class = "pick"
    elif position in IDP_POSITIONS:
        asset_class = "idp"
    else:
        asset_class = "offense"
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": asset_class,
        "canonicalSiteValues": dict(sites),
        "values": {
            "overall": 0,
            "rawComposite": None,
            "finalAdjusted": None,
            "displayValue": None,
        },
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": False,
    }


def _anchor_qb() -> dict[str, Any]:
    """A top-of-board offense row.

    Both value-direct sources publish on a ``raw / site_max × 9999``
    scale, so pinning one row at 9999 in both fixes the site maxima and
    makes every other row's value-direct contribution exactly its own
    raw number.  Without this the maxima float with the fixture.
    """
    return _row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["canonicalName"]: r for r in rows}


# ── Stage 9: single-source haircut ───────────────────────────────────


class TestSingleSourceHaircut:
    """Non-pick rows resting on ONE post-Hampel source keep 30%.

    ``_SINGLE_SOURCE_VALUE_RETENTION = 0.30`` (CLAUDE.md stage 9).
    """

    def test_retention_constant_is_030(self):
        assert dc._SINGLE_SOURCE_VALUE_RETENTION == 0.30

    def test_offense_single_source_keeps_exactly_30_percent(self):
        """Solo row votes 5000 value-direct; haircut → 5000 × 0.30 = 1500."""
        rows = [
            _row("Solo Guy", "WR", ktcSfTep=5000),
            _row("Duo Guy", "WR", ktcSfTep=5000, idpTradeCalc=5000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)

        # Duo Guy: two sources agree at 5000 → n=2 mean → 5000, no haircut.
        assert got["Duo Guy"]["rankDerivedValue"] == 5000
        assert got["Duo Guy"].get("singleSourceValuePenaltyApplied") is not True

        # Solo Guy: identical raw 5000, one source → 5000 × 0.30 = 1500.
        assert got["Solo Guy"]["rankDerivedValue"] == 1500
        assert got["Solo Guy"]["singleSourceValuePenaltyApplied"] is True

    def test_haircut_also_rewrites_the_uncapped_blend_stamp(self):
        """``_blendedValueUncapped`` must carry the haircut too.

        The rookie-anchor pass falls back to this field for rookies past
        ``OVERALL_RANK_LIMIT``; leaving it unpenalised would let an
        unranked single-source rookie price picks at full value.
        """
        rows = [_row("Solo Guy", "WR", ktcSfTep=5000), _anchor_qb()]
        dc._compute_unified_rankings(rows, {})
        solo = _by_name(rows)["Solo Guy"]
        assert solo["_blendedValueUncapped"] == 1500

    def test_pick_rows_are_exempt_from_the_haircut(self):
        """Picks are excluded by the ``not row_is_pick`` guard.

        A pick and an offense row with the same lone 4000 vote must
        diverge: pick keeps 4000, offense drops to 4000 × 0.30 = 1200.
        """
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year} Pick 2.05", "PICK", ktcSfTep=4000),
            _row("Solo WR", "WR", ktcSfTep=4000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)

        assert got[f"{year} Pick 2.05"]["rankDerivedValue"] == 4000
        assert got[f"{year} Pick 2.05"].get("singleSourceValuePenaltyApplied") is not True
        assert got["Solo WR"]["rankDerivedValue"] == 1200
        assert got["Solo WR"]["singleSourceValuePenaltyApplied"] is True


# ── Stage 6: hierarchical anchor + α-shrinkage ───────────────────────


class TestAlphaShrinkageRouting:
    """α=0.10 applies to IDP and picks ONLY; offense blends flat.

    center = anchor + α·(subgroup_center − anchor)   [IDP, picks]
    center = count_aware_mean_median(all_values)     [offense]
    """

    def test_alpha_constant_is_010(self):
        assert dc._ALPHA_SHRINKAGE == 0.10

    def test_idp_row_combines_anchor_and_subgroup_at_alpha(self):
        """IDP: rdv must equal anchor + 0.10 × subgroupDelta, exactly."""
        rows = [
            _row("Def Guy", "LB", idpTradeCalc=6000, dlfIdp=900000),
            _row("Anchor LB", "LB", idpTradeCalc=8000, dlfIdp=950000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        defguy = _by_name(rows)["Def Guy"]

        anchor = defguy["anchorValue"]
        delta = defguy["subgroupDelta"]
        assert anchor is not None and delta is not None
        assert defguy["alphaShrinkage"] == 0.10

        # The stamped diagnostics must reconstruct the stamped value.
        expected = int(round(anchor + 0.10 * delta))
        assert defguy["rankDerivedValue"] == pytest.approx(expected, abs=1)

        # And the subgroup must actually be pulled 90% of the way back
        # to the anchor — not averaged in as a peer.
        subgroup = defguy["subgroupBlendValue"]
        assert subgroup is not None
        assert abs(defguy["rankDerivedValue"] - anchor) < abs(subgroup - anchor) / 2

    def test_offense_row_is_flat_blended_with_zero_alpha_stamp(self):
        """Offense must NOT shrink toward the cross-market anchor.

        Two value-direct sources disagreeing 9000 vs 3000 blend flat to
        the n=2 mean 6000 — not to 9000 + 0.1×(3000−9000) = 8400.
        """
        rows = [
            _row("Split Guy", "WR", ktcSfTep=9000, idpTradeCalc=3000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        split = _by_name(rows)["Split Guy"]

        assert split["alphaShrinkage"] == 0.0
        assert split["rankDerivedValue"] == 6000

    def test_pick_rows_use_the_hierarchical_path(self):
        """Picks carry the live α stamp, like IDP (CLAUDE.md stage 6)."""
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        pick = _by_name(rows)[f"{year} Pick 1.01"]
        assert pick["alphaShrinkage"] == 0.10


# ── Stage 4: which sources vote value-direct vs via the Hill curve ───


class TestValueDirectSourceMembership:
    """``_VALUE_BASED_SOURCES`` decides *how* a source votes.

    Members bypass the Hill curve entirely and vote
    ``raw / site_max × 9999``; everyone else votes
    rank → percentile → Hill.  Adding a key to this frozenset silently
    switches that source's whole contribution mechanism.

    Before this test the membership was referenced only in
    ``test_single_curve_live.py`` and ``test_data_contract.py`` — both
    ``livedata``, both deselected by CI's ``-m "not livedata"`` — plus
    ``tests/ros/test_isolation.py``, which snapshots the set to detect
    import-time mutation rather than asserting its contents.
    """

    def test_exactly_two_sources_vote_value_direct(self):
        assert dc._VALUE_BASED_SOURCES == frozenset({"ktcSfTep", "idpTradeCalc"})

    def test_value_direct_voting_is_linear_in_the_raw_value(self):
        """Demonstrate the consequence, so the assertion above has teeth.

        ``ktcSfTep`` is value-direct: contribution is
        ``raw / site_max × 9999``, i.e. LINEAR in the published number.
        With ``_anchor_qb`` pinning ``site_max`` at 9999, a row at half
        the scale contributes exactly half.

        Both rows below rest on KTC alone, so both take the 0.30
        haircut and the ratio between them survives it:
            5000 / 9999 × 9999 × 0.30 = 1500
            2500 / 9999 × 9999 × 0.30 =  750
        """
        rows = [
            _row("Half KTC", "WR", ktcSfTep=5000),
            _row("Quarter KTC", "WR", ktcSfTep=2500),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)
        assert got["Half KTC"]["rankDerivedValue"] == 1500
        assert got["Quarter KTC"]["rankDerivedValue"] == 750

    def test_rank_voting_is_not_linear_in_the_ordinal(self):
        """The contrast case: a rank source goes through the Hill curve.

        Ranks 1 and 2 out of a 500-row reference are a hair apart on the
        curve, nothing like the 2:1 gap the value-direct path produces
        for a 2:1 raw-value gap.  This is why membership of
        ``_VALUE_BASED_SOURCES`` is load-bearing rather than cosmetic.
        """
        rows = [
            _row("Rank One", "WR", dlfSf=999800, idpTradeCalc=4000),
            _row("Rank Two", "WR", dlfSf=999700, idpTradeCalc=4000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)
        one = got["Rank One"]["rankDerivedValue"]
        two = got["Rank Two"]["rankDerivedValue"]
        assert one > two  # the curve does decay...
        assert two > one * 0.9  # ...but nowhere near linearly


# ── Stage 2: percentile clamp past the fixed reference pool ──────────


class TestPercentileReferenceClamp:
    """Ranks past ``_PERCENTILE_REFERENCE_N`` clamp to the curve tail.

    Deliberate top-500-board behaviour (CLAUDE.md stage 2).  The clamp
    is what stops a rank-signal source from driving p > 1.0 into the
    Hill curve, where it would keep producing ever-smaller values and
    silently re-order the deep board.
    """

    def test_reference_n_is_500(self):
        assert dc._PERCENTILE_REFERENCE_N == 500

    def test_every_routed_curve_shares_the_same_reference_denominator(self):
        """All routed scope curves normalise against the same N.

        If one scope's reference drifted, two sources covering the same
        player would place him at different percentiles for the same
        rank — a silent, position-dependent repricing.
        """
        block = dc._build_hill_curves_block()
        routed = {k: v for k, v in block.items() if v.get("routed")}
        assert set(routed) == {"global", "offense", "idp"}
        for key, entry in routed.items():
            assert entry["referenceN"] == dc._PERCENTILE_REFERENCE_N, key

    def test_rookie_master_is_fit_only_and_not_routed(self):
        """CLAUDE.md stage 5: "the ROOKIE master is refit tooling only".

        Rookie-only sources ladder-translate into combined-pool space
        before curve selection, so routing the ROOKIE curve would
        double-apply the rookie adjustment.
        """
        assert dc._build_hill_curves_block()["rookie"]["routed"] is False

    def test_pipeline_resolves_past_the_reference_and_flattens_at_the_boundary(self):
        """Drive real rows through the pipeline, not a re-implementation.

        **Re-decided by W30-F023.** This test asserted the opposite: that
        ranks past ``_PERCENTILE_REFERENCE_N`` all receive the *same*
        contribution, "the deep board flattens instead of continuing to
        decay". That was an accurate description of the pipeline and it was
        the defect — the saturation point was the coordinate unit rather
        than the edge of observed evidence, so 421 of 5,143 rank-Hill
        observations across 254 served rows collapsed onto one number.

        The tail is now owned by ``tail_policy`` and saturates at rank 904.
        So the pipeline must (a) keep resolving between the reference
        population and the boundary, and (b) flatten past it. Both are
        asserted, because dropping (b) would let an unbounded
        extrapolation pass.

        Constructed so the rank source is the ONLY differentiator: every
        row carries an identical second source, so any spread left in the
        tail can only have come from the rank source.
        """
        from src.canonical.tail_policy import TAIL_SATURATION_RANK

        n = dc._PERCENTILE_REFERENCE_N
        # Deep enough to reach PAST the boundary, so both halves of the
        # policy are observable in one run.
        total = TAIL_SATURATION_RANK + 60

        rows = [_anchor_qb()]
        for i in range(total):
            # dlfSf is rank-encoded (999900 − rank×100): descending
            # values mean descending ranks, 1..total.
            rows.append(
                _row(
                    f"P{i:04d}",
                    "WR",
                    dlfSf=999900 - (i + 1) * 100,
                    idpTradeCalc=4000,
                )
            )
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)

        # Read the pre-cap blend: it is stamped on EVERY contributing
        # row, whereas ``rankDerivedValue`` is only stamped inside
        # ``OVERALL_RANK_LIMIT`` (800) and would make this assertion
        # depend on the rank cap rather than on the tail policy.
        def blended(rank: int) -> int:
            return got[f"P{rank - 1:04d}"]["_blendedValueUncapped"]

        # (a) between the reference population and the boundary the board
        #     must keep resolving — this is the W30-F023 repair.
        assert blended(n + 10) > blended(n + 200) > blended(TAIL_SATURATION_RANK - 5), (
            "ranks between the reference population and the tail boundary "
            "collapsed — W30-F023 has regressed"
        )

        # (b) past the boundary it must flatten — the policy is bounded,
        #     not an unbounded extrapolation into ranks nothing published.
        assert blended(TAIL_SATURATION_RANK + 5) == blended(total), (
            "ranks past the tail boundary kept decaying — the coordinate is "
            "resolving depths no source has ever published"
        )

        # A row inside the reference must still be worth strictly more than
        # a deep one, otherwise (a) could hold vacuously.
        assert blended(10) > blended(n + 10)


# ── Stage 12: multiplicative future-year pick discount ───────────────


class TestPickYearDiscountThroughTheBlend:
    """``_apply_pick_year_discount_to_blend`` runs pre-sort on picks.

    Since C1-U6 the year-step is applied AT INJECTION to the cloned
    source values (``_year_step_for``, unit-tested in
    ``test_current_draft_year.py``); the pre-sort pass is STAMP-ONLY.
    What these tests pin off the livedata path is that no value is
    multiplied in the blend stage — for vendor years because they are
    exempt (T-3/C-2), for synthesised years because the derivation
    already happened upstream — while the audit stamp still lands on
    synthesised rows.
    """

    def test_vendor_priced_future_years_are_NOT_discounted(self):
        """A future year the vendors priced must pass through untouched.

        CHANGED 2026-08-04, audit finding T-3/C-2.  This test previously
        asserted 7000 → 5740 → 4620 for offsets 0/1/2, i.e. the config
        factors applied to every future year.  That is the defect: these
        rows carry a real per-slot vendor price, and both ingested
        markets price the NEXT class ABOVE the imminent one (ktcSfTep
        2026 Early 1st 5595 vs 2027 7061).  Composing a decay prior onto
        a price that already encodes the year published 2027 firsts 18%
        and 2028 firsts 34% below what both markets agreed.

        Rows reach the discount stage un-cloned here — exactly like a
        vendor-priced year on the live board — so none may be stepped
        down.  The synthesised case is asserted in the next test.
        """
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _row(f"{year + 1} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _row(f"{year + 2} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)

        assert got[f"{year} Pick 1.01"]["rankDerivedValue"] == 7000
        assert got[f"{year + 1} Pick 1.01"]["rankDerivedValue"] == 7000
        assert got[f"{year + 2} Pick 1.01"]["rankDerivedValue"] == 7000

    def test_synthesised_far_future_values_arrive_pre_stepped(self):
        """A synthesised year's values are stepped at INJECTION, so the
        blend must publish them AS GIVEN — multiplying again in the
        blend stage would double-count the derivation (the retired
        composition applied offset factors here on top of the clone).
        The 7000 below plays the part of an already-stepped source
        value; it must come through at exactly 7000.
        """
        year = dc.current_rookie_draft_year()
        name = f"{year + 2} Pick 1.01"
        rows = [
            _row(name, "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        prev = dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES
        prev_der = dc._SYNTHETIC_PICK_DERIVATIONS
        dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES = {dc._canonical_match_key(name)}
        dc._SYNTHETIC_PICK_DERIVATIONS = {
            dc._canonical_match_key(name): {
                "factor": 0.7138,
                "basisYear": year + 1,
                "basisName": f"{year + 1} Pick 1.01",
                "family": "measured_vendor_year_step_v1",
                "classification": "PRIOR",
            }
        }
        try:
            dc._compute_unified_rankings(rows, {})
        finally:
            dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES = prev
            dc._SYNTHETIC_PICK_DERIVATIONS = prev_der

        assert _by_name(rows)[name]["rankDerivedValue"] == 7000

    def test_current_year_pick_carries_no_discount_stamp(self):
        """offset 0 → multiplier 1.0 → the row is left untouched."""
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        assert _by_name(rows)[f"{year} Pick 1.01"].get("pickYearDiscount") is None

    def test_discount_is_stamped_for_audit_on_discounted_picks(self):
        """The audit stamp appears only where a discount was really applied.

        Post-T-3 that means a SYNTHESISED year; a vendor-priced year
        carries no stamp because it takes no discount.
        """
        year = dc.current_rookie_draft_year()
        name = f"{year + 1} Pick 1.01"
        rows = [
            _row(name, "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        prev = dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES
        prev_der = dc._SYNTHETIC_PICK_DERIVATIONS
        dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES = {dc._canonical_match_key(name)}
        dc._SYNTHETIC_PICK_DERIVATIONS = {
            dc._canonical_match_key(name): {
                "factor": 0.8407,
                "basisYear": year,
                "basisName": f"{year} Pick 1.01",
                "family": "measured_vendor_year_step_v1",
                "classification": "PRIOR",
            }
        }
        try:
            dc._compute_unified_rankings(rows, {})
        finally:
            dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES = prev
            dc._SYNTHETIC_PICK_DERIVATIONS = prev_der
        assert _by_name(rows)[name]["pickYearDiscount"] == 0.8407

    def test_vendor_priced_future_year_carries_no_discount_stamp(self):
        """The complement: no discount applied means no stamp to explain."""
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year + 1} Pick 1.01", "PICK", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        assert _by_name(rows)[f"{year + 1} Pick 1.01"].get("pickYearDiscount") is None

    def test_players_are_never_year_discounted(self):
        """The discount is gated to ``assetClass == 'pick'``.

        A player row whose name happens to start with a future year
        must keep its full value.
        """
        year = dc.current_rookie_draft_year()
        rows = [
            _row(f"{year + 1} Guy", "WR", ktcSfTep=7000, idpTradeCalc=7000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)[f"{year + 1} Guy"]
        assert got["rankDerivedValue"] == 7000
        assert got.get("pickYearDiscount") is None


# ── Stage 8 (retired): λ·MAD penalty must stay off ───────────────────


class TestMadPenaltyStaysRetired:
    """``_MAD_PENALTY_LAMBDA = 0.0`` since 2026-04-20.

    ``sourceSpread`` is a pure diagnostic.  If λ is ever switched back
    on by accident, every high-disagreement player silently loses
    value — so pin both the constant and the observable consequence.
    """

    def test_lambda_is_zero(self):
        assert dc._MAD_PENALTY_LAMBDA == 0.0

    def test_high_disagreement_row_is_not_penalised(self):
        """Sources split 9000/3000 → flat mean 6000, no MAD deduction.

        ``sourceSpread`` is still stamped (diagnostic), but must not
        have moved the value.
        """
        rows = [
            _row("Split Guy", "WR", ktcSfTep=9000, idpTradeCalc=3000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        split = _by_name(rows)["Split Guy"]

        assert split["rankDerivedValue"] == 6000
        assert split["sourceSpread"] == 3000.0  # diagnostic only
        assert split["madPenaltyApplied"] is None


# ── Retired passes must stay retired (CI-blocking versions) ──────────


def _synthetic_contract() -> dict[str, Any]:
    """A contract built from a synthetic payload — no live exports."""
    positions = ["QB", "RB", "WR", "TE", "LB", "DL", "DB"]
    players: dict[str, Any] = {}
    for i in range(40):
        value = 9500 - i * 200
        players[f"Player {i:03d}"] = {
            "position": positions[i % len(positions)],
            "team": "FA",
            "_sites": 2,
            "_canonicalSiteValues": {"ktcSfTep": value, "idpTradeCalc": value},
        }
    return dc.build_api_data_contract({"players": players})


class TestRetiredPassesStayRetired:
    """Guards against silently reviving a deleted value-moving pass.

    Equivalents of these live in ``test_single_curve_live.py``
    (``TestOffenseHasNoCalibrationLayer``, ``TestVolatilityPassIsRemoved``,
    ``TestValueChain``) and ``src/api/data_contract.py`` cites them in a
    source comment as the thing that "fails if that reference ever
    starts mutating live values".

    They cannot do that job.  That module is in ``_LIVEDATA_MODULES``,
    so CI's ``-m "not livedata"`` deselects it — and even when
    selected each guard calls ``skipTest`` unless a live export is on
    disk.  Two independent reasons it never runs in CI.

    These versions build the contract from a synthetic payload, so
    they run everywhere, every time.  Keep both: the livedata copies
    additionally check the real board.
    """

    RETIRED_STAMPS = (
        # IDP calibration post-pass (retired; see "Phase 4c: removed").
        "rankDerivedValueUncalibrated",
        "canonicalConsensusRankUncalibrated",
        "idpCalibrationMultiplier",
        "idpFamilyScale",
        "idpCalibrationPositionRank",
        # Volatility compression pass (retired).
        "preVolatilityValue",
        "volatilityCompressionApplied",
        # Offense calibration — deliberately never applied to live values.
        "offenseCalibrationMultiplier",
    )

    def test_no_row_carries_a_retired_pass_stamp(self):
        contract = _synthetic_contract()
        rows = contract.get("playersArray") or []
        assert rows, "fixture produced no rows — the guard would be vacuous"

        offenders: list[str] = []
        for row in rows:
            for stamp in self.RETIRED_STAMPS:
                if row.get(stamp) is not None:
                    offenders.append(f"{row.get('displayName')}::{stamp}={row[stamp]}")
        assert (
            not offenders
        ), f"a retired value-moving pass appears to have been revived: {offenders[:5]}"

    def test_idp_calibration_config_and_helper_are_really_gone(self):
        """CLAUDE.md still documents stage 10 as
        ``_apply_idp_calibration_post_pass`` reading
        ``config/idp_calibration.json``.  Neither exists — the pass was
        retired ("Phase 4c: removed").  Pin that so the docs and the
        code cannot drift further apart unnoticed.

        If a calibration pass is ever genuinely reintroduced, this test
        should be deleted in the same PR that adds tests for the new
        chain — not quietly amended.
        """
        assert not hasattr(dc, "_apply_idp_calibration_post_pass")

        from pathlib import Path

        repo_root = Path(dc.__file__).resolve().parents[2]
        assert not (repo_root / "config" / "idp_calibration.json").exists()

    def test_the_market_corridor_clamp_is_retired_too(self):
        """Stage 10 is now DETECTION, not containment.

        This test used to assert the opposite — that the corridor "must
        stay callable" as "the one containment pass the live pipeline
        still runs". It is re-decided from measured evidence, not
        amended quietly: the corridor's anchor was itself a voter in the
        blend it corrected (539 of 539 clamped rows across 17
        independent historical days), its band was a P90 of the board it
        policed so it clamped a fixed ~9% regardless of board health, and
        injecting anomalies at the source CSVs it fired on 0 of 6 victims
        in every scenario — upstream Hampel filtering, the count-aware
        blend and the declared-range check had already absorbed them.

        What replaced it changes no value at all, so stage 10 no longer
        contains anything (#794/#795/#796).
        """
        assert not hasattr(dc, "_apply_market_corridor_clamp")
        assert not hasattr(dc, "_market_anchor_for_row")
        assert callable(getattr(dc, "_detect_blend_integrity_violations", None))
