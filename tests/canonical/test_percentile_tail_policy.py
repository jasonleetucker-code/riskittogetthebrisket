"""W30-F023 — the percentile tail must not collapse live evidence.

**Status: FIXED.** ``tail_policy.TAIL_SATURATION_RANK`` is ``904`` and
these are ordinary regressions. They were ``xfail(strict=True)`` while the
repair was blocked on the B3 market corridor; #799 removed the corridor
(merge ``52d48b6e5``, resolving #794/#795/#796), so the dependency is gone
and the markers came off deliberately rather than by a suite quietly
turning green — which is what ``strict=True`` was there to force.

The defect, stated once: ``rank_to_percentile`` saturated ``p`` at 1.0 once
the rank passed ``PERCENTILE_REFERENCE_N`` (500), so every deeper rank
received an identical percentile and therefore an identical contribution
from that source. Measured on the B4-final pin
(``docs/master-site-audit/evidence/W30/b4f_reproduce.json``, board
2026-08-12): 421 of 5,143 rank-Hill observations sat past 500, touching
**254 board rows, all 254 of them served** — 34.32% of the 740 rows the
board publishes, concentrated in IDP (DL/EDGE 97 rows, DB 87, LB 49).

Three things these tests are deliberately careful about.

**They are policy-agnostic except where the boundary is pinned once.**
What is asserted is the *observable* property every viable candidate
satisfies and the old behaviour did not: **two ranks a source genuinely
distinguishes must not be priced identically.** A test asserting "``p``
may exceed 1.0" would presuppose the continuous shape and fail under a
bounded policy that rescales the coordinate instead. The specific
boundary is pinned in exactly one place —
``TestTheOwnerIsSingle.test_the_boundary_is_the_measured_depth`` — rather
than spread across every assertion.

**They call the real canonical functions.** Never a local
re-implementation of the Hill form. A copied formula here would pass while
production stayed saturated — which is exactly how
``tests/api/test_percentile_reference_resolution.py:44`` came to hold its
own copy of the production map.

**The depths are live evidence, not tunable constants.** They come from
the B4-final pin and the 17-day historical replay
(``b4f_boundary.json``, ``b4f_historical_sensitivity.json``):

* deepest rank-Hill effective rank on the current board: **876**
  (``idpShow``), past ``OVERALL_RANK_LIMIT`` (800) — so the board limit is
  not a defensible saturation point for the source-coordinate domain.
  Different domains.
* deepest effective rank ever observed across retained evidence: **904**
  (``idpTradeCalc``, 2026-07-28), which is where the boundary sits.

Note the boundary covers *value-direct* ranks even though value-direct
sources do not normally traverse the curve. That is not slack: the
value-direct fallback is live code (a suppressed source, an out-of-range
value or a missing value routes the row to the Hill path), so a boundary
set at the deepest rank-Hill rank alone would re-saturate the band above
it the moment that branch takes traffic.

See ``docs/master-site-audit/evidence/W30/B4F_TAIL_FINAL.md`` for the
decision and ``B4_TAIL_DECISION.md`` for the superseded blocked
experiment, which is preserved unchanged.
"""

from __future__ import annotations

import pytest

from src.api import data_contract as dc
from src.canonical.player_valuation import (
    PERCENTILE_REFERENCE_N,
    percentile_to_value,
    rank_to_percentile,
)
from src.canonical.rank_coordinates import (
    RANK_POOL_IDP,
    RANK_POOL_SHARED_MARKET,
    curve_for_pool,
)


#: Deepest rank-Hill effective rank consumed by a row the board SERVES,
#: measured on the B4-final pin. Evidence really does exist this far down:
#: it is ``idpShow``'s deepest contribution to a published row.
DEEPEST_SERVED_RANK_HILL = 876

#: The applied boundary. Deepest effective rank across ALL retained
#: evidence — ``idpTradeCalc`` on 2026-07-28 in the 17-day replay.
MEASURED_BOUNDARY = 904

#: Ranks the pin proves carry genuine, distinct live evidence past the
#: saturation point. Every one of these is some source's deepest rank-Hill
#: coordinate on the current board, so a policy that cannot separate them
#: is collapsing evidence that exists.
LIVE_DEEP_RANKS = (501, 572, 619, 624, 660, 683, 729, 876)


def _contribution(rank: float, pool: str = RANK_POOL_SHARED_MARKET) -> int:
    """A source's live contribution for ``rank``, through the real path.

    ``rank_to_percentile`` then ``percentile_to_value`` with the master
    that prices the pool — the same two calls
    ``data_contract._compute_unified_rankings`` makes at its serving site
    (``data_contract.py:7799`` and the ``percentile_to_value`` branches
    below it). Assembling it here rather than importing a helper keeps the
    test honest about which functions it is actually exercising.
    """
    c, s = curve_for_pool(pool)
    p = rank_to_percentile(float(rank))
    return percentile_to_value(p, midpoint=c, slope=s)


class TestDistinctEvidenceMustStayDistinct:
    """Distinct live ranks must price differently. Was the defect; now green.

    Every assertion here failed under ``TAIL_SATURATION_RANK = None`` and
    passes under the measured boundary. The RED evidence is recorded in
    ``b4f_reproduce.json``; re-establish it any time by setting the owner's
    constant back to ``None``, which is what ``_saturated`` below does.
    """

    @staticmethod
    def _saturated(rank: float) -> int:
        """The same contribution under the PRE-repair policy.

        Used to assert the tests have teeth: an assertion that passes
        under both policies is not testing the repair.
        """
        from src.canonical import tail_policy

        prev = tail_policy.TAIL_SATURATION_RANK
        tail_policy.TAIL_SATURATION_RANK = None
        try:
            return _contribution(rank)
        finally:
            tail_policy.TAIL_SATURATION_RANK = prev

    def test_the_repair_is_what_makes_these_pass(self):
        """RED -> GREEN, asserted in one place rather than assumed.

        Under the old policy ranks 501 and 876 priced identically. If that
        ever stops being true the rest of this class stops being evidence
        of anything, so it is checked explicitly instead of trusted.
        """
        assert self._saturated(501) == self._saturated(DEEPEST_SERVED_RANK_HILL), (
            "the pre-repair policy no longer collapses these ranks, so these "
            "tests would pass with or without the repair"
        )
        assert _contribution(501) != _contribution(DEEPEST_SERVED_RANK_HILL)

    def test_rank_500_and_501_are_not_one_number(self):
        """The saturation point itself — one rank apart, both real."""
        assert _contribution(500) != _contribution(501)

    def test_rank_500_and_800_are_not_one_number(self):
        """Across the whole published board, not just at the boundary.

        800 is ``OVERALL_RANK_LIMIT``. Chosen because it is the widest
        span a reader could reasonably expect the board to distinguish;
        the collapse is not a boundary rounding artifact.
        """
        assert _contribution(500) != _contribution(800)

    def test_every_live_deep_rank_prices_differently(self):
        """The general claim: 7 real depths, 7 distinct contributions.

        These are not invented coordinates. Each is a deepest-rank-Hill
        rank recorded for a source on the pinned board, so a policy that
        cannot separate them is collapsing evidence that exists.
        """
        got = [_contribution(r) for r in LIVE_DEEP_RANKS]
        assert len(set(got)) == len(LIVE_DEEP_RANKS), (
            f"{len(LIVE_DEEP_RANKS)} distinct live ranks collapsed onto "
            f"{len(set(got))} distinct value(s): {sorted(set(got))}"
        )

    def test_the_deep_range_is_strictly_decreasing(self):
        """Deeper must be worth strictly less, not equal.

        Monotone-non-increasing is what the defect already satisfies, so
        the assertion has to be strict to have any content. It is also
        the property that makes the repair safe in the other direction:
        a deeper rank must never become worth MORE.
        """
        ranks = list(range(PERCENTILE_REFERENCE_N, DEEPEST_SERVED_RANK_HILL + 1, 25))
        got = [_contribution(r) for r in ranks]
        for (r_a, v_a), (r_b, v_b) in zip(zip(ranks, got), zip(ranks[1:], got[1:])):
            assert v_a > v_b, f"rank {r_a} ({v_a}) must be worth strictly more than {r_b} ({v_b})"

    def test_distinct_deep_idp_ranks_do_not_collapse_on_the_idp_master(self):
        """The same claim on the IDP master, not only the GLOBAL one.

        The measured blast radius is overwhelmingly IDP, and IDP ranks
        reach both masters — translated ones land in the shared-market
        pool (B2/W02-F001), untranslated ones stay IDP-local. A repair
        that fixed one pool and not the other would leave the same defect
        wearing a different curve.
        """
        got = [_contribution(r, RANK_POOL_IDP) for r in LIVE_DEEP_RANKS]
        assert len(set(got)) == len(LIVE_DEEP_RANKS)


class TestThereIsOneTailOwnerNotFour:
    """``percentile_to_value`` used to re-decide the tail independently.

    The trap this file exists to catch: a repair applied at
    ``rank_to_percentile`` alone is silently undone, because
    ``percentile_to_value`` clamps its input a second time
    (``player_valuation.py:484``) and so imposes its own tail regardless
    of what the coordinate owner decided.

    The assertion is written as an exclusive-or over the two shapes a
    repair could take, so it presupposes neither:

    * a *continuous* policy leaves the owner emitting ``p > 1`` — and then
      ``percentile_to_value`` must honour it rather than flattening it;
    * a *bounded* policy rescales so the owner never emits ``p > 1`` — and
      then distinctness must already hold at the owner's own output.

    The shipped policy is bounded-at-904 expressed as a coordinate
    ceiling, so the owner DOES emit ``p > 1`` for ranks past
    ``PERCENTILE_REFERENCE_N`` and the first branch is the live one. Both
    are kept because the assertion must not presuppose the shape.
    """

    def test_percentile_to_value_defers_to_the_coordinate_owner(self):
        c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)
        at_n = rank_to_percentile(float(PERCENTILE_REFERENCE_N))
        at_deep = rank_to_percentile(float(DEEPEST_SERVED_RANK_HILL))

        if at_deep > 1.0:
            # Continuous-shaped owner: the second clamp must not re-flatten it.
            assert percentile_to_value(at_deep, midpoint=c, slope=s) != percentile_to_value(
                1.0, midpoint=c, slope=s
            ), "percentile_to_value re-clamped a coordinate the owner deliberately left past 1.0"
        else:
            # Bounded-shaped owner: distinctness must hold at its output.
            assert at_deep != at_n, (
                "the coordinate owner maps rank "
                f"{PERCENTILE_REFERENCE_N} and rank {DEEPEST_SERVED_RANK_HILL} onto the "
                f"identical coordinate {at_deep} — distinct evidence, one number"
            )

    def test_the_owner_is_consulted_by_fitting_and_scoring_too(self):
        """Serving, fitting and holdout scoring must share one tail.

        Not a style point. If the fit and the holdout keep their own
        clamps, a repaired board is scored by a still-saturated evaluator
        and any refit re-learns the saturated shape — the W30-F008 defect
        class, in which training and serving disagreed about a coordinate.
        """
        from scripts.fit_hill_curve_percentile import _hill
        from src.model_registry.holdout import hill as holdout_hill

        c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)
        deep = rank_to_percentile(float(DEEPEST_SERVED_RANK_HILL))
        at_n = rank_to_percentile(float(PERCENTILE_REFERENCE_N))

        assert holdout_hill(deep, c, s) != holdout_hill(at_n, c, s), (
            "the holdout scorer flattens the tail independently, so it would "
            "grade a repaired curve against a saturated one"
        )
        assert _hill(deep, c, s) != _hill(at_n, c, s), (
            "the fit flattens the tail independently, so a refit would "
            "re-learn the saturated shape"
        )


class TestTheOwnerIsSingle:
    """GREEN, and the actual B4 deliverable.

    The four clamps — ``rank_to_percentile``, ``percentile_to_value``, the
    holdout scorer's standalone ``hill()`` and the fit's ``_hill`` — each
    stated the tail rule for itself. Four transcriptions of one rule is
    how serving and training come to disagree about a coordinate, which is
    what W30-F008 was.

    These tests do not assert WHERE the tail is; that is the blocked half.
    They assert that there is exactly one place that decides, by moving the
    owner's constant and requiring all four to move with it. That property
    holds today and is what makes the eventual one-constant flip safe.
    """

    @staticmethod
    def _sample(boundary):
        """Values from all four sites under one declared boundary."""
        from scripts.fit_hill_curve_percentile import _hill
        from src.canonical import tail_policy
        from src.model_registry.holdout import hill as holdout_hill

        c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)
        prev = tail_policy.TAIL_SATURATION_RANK
        tail_policy.TAIL_SATURATION_RANK = boundary
        try:
            p = rank_to_percentile(float(DEEPEST_SERVED_RANK_HILL))
            return {
                "rank_to_percentile": p,
                "percentile_to_value": percentile_to_value(p, midpoint=c, slope=s),
                "holdout_hill": round(holdout_hill(p, c, s), 6),
                "fit_hill": round(_hill(p, c, s), 6),
            }
        finally:
            tail_policy.TAIL_SATURATION_RANK = prev

    def test_every_site_follows_the_owner(self):
        """Move the owner's boundary; all four sites must move together.

        A site that kept its own ``min(1.0, p)`` would be pinned to the
        saturated answer here while the others moved — which is exactly
        the failure mode, and exactly what this catches.
        """
        at_none = self._sample(None)
        at_boundary = self._sample(MEASURED_BOUNDARY)
        assert at_none["rank_to_percentile"] == 1.0
        assert at_boundary["rank_to_percentile"] > 1.0
        for site in ("percentile_to_value", "holdout_hill", "fit_hill"):
            assert at_boundary[site] != at_none[site], (
                f"{site} did not follow the tail owner — it is still deciding "
                "the tail for itself"
            )

    def test_serving_fitting_and_scoring_agree_with_each_other(self):
        """Same coordinate, same curve, same number from all three.

        The evaluator and the fit must grade the shape production serves.
        Asserted under BOTH boundaries so it cannot be an accident of the
        current one.
        """
        for boundary in (None, MEASURED_BOUNDARY):
            got = self._sample(boundary)
            assert got["percentile_to_value"] == round(got["holdout_hill"]), boundary
            assert round(got["holdout_hill"], 6) == round(got["fit_hill"], 6), boundary

    def test_the_boundary_is_the_measured_depth(self):
        """The one place the shipped boundary is pinned.

        904 is the deepest effective rank observed across all retained
        evidence (``idpTradeCalc``, 2026-07-28, in the 17-day replay). It
        is NOT a round number, a headroom margin, or the 903 an earlier
        round selected from a source comment — that value had no
        executable definition and was refuted by the replay, which found a
        rank one deeper.

        Moving it is a production value change and must be a deliberate
        act with fresh measurement behind it:
        ``b4f_historical.py --depths``.
        """
        from src.canonical.tail_policy import TAIL_SATURATION_RANK

        assert TAIL_SATURATION_RANK == MEASURED_BOUNDARY

    def test_the_boundary_covers_every_observed_rank(self):
        """It must not re-saturate a depth the evidence has actually seen.

        This is the property 903 failed. Read from the recorded replay
        rather than restated, so the assertion tracks the evidence instead
        of a number someone typed twice.
        """
        import json
        from pathlib import Path

        replay = (
            Path(__file__).resolve().parents[2]
            / "docs/master-site-audit/evidence/W30/b4f_historical_sensitivity.json"
        )
        if not replay.is_file():  # pragma: no cover - evidence pruned
            pytest.skip("historical replay evidence not present")
        payload = json.loads(replay.read_text())
        deepest = max(float(d["deepestEffectiveRank"]) for d in payload["days"])
        assert MEASURED_BOUNDARY >= deepest, (
            f"boundary {MEASURED_BOUNDARY} is shallower than the deepest observed "
            f"rank {deepest} — it would re-saturate real evidence"
        )

    def test_unset_is_exactly_the_pre_b4_rule(self):
        """``None`` must still reproduce ``min(1.0, p)`` in every universe.

        Not only at the live N=500. The old clamp was relative to the
        caller's declared universe, so a boundary expressed as an absolute
        RANK would silently change behaviour for any caller passing its
        own ``reference_n`` — the fit and holdout tooling do. The ``None``
        path is no longer what production runs, but it is still the
        documented meaning of ``None`` and the fallback every caller gets
        if the boundary is ever cleared.
        """
        from src.canonical import tail_policy

        prev = tail_policy.TAIL_SATURATION_RANK
        tail_policy.TAIL_SATURATION_RANK = None
        try:
            for reference_n in (2, 100, 370, 500, 800, 5000):
                for rank in (1, 2, reference_n // 2, reference_n, reference_n + 1, 99999):
                    expected = max(0.0, min(1.0, (float(rank) - 1.0) / float(reference_n - 1)))
                    assert rank_to_percentile(rank, reference_n=reference_n) == pytest.approx(
                        expected
                    ), (reference_n, rank)
        finally:
            tail_policy.TAIL_SATURATION_RANK = prev


class TestTheFittedHeadIsUntouched:
    """GREEN now, and must stay green. A tail repair is not a refit.

    B4's standing constraint: preserve the curve through the region it was
    fitted to represent. These pin the head so a "tail" change that
    actually reshapes ranks 1..500 cannot pass as one.
    """

    @pytest.mark.parametrize("rank", [1, 2, 10, 50, 100, 200, 300, 400, 499, 500])
    def test_ranks_inside_the_reference_population_are_unchanged(self, rank):
        """Exact values, recomputed from the champion constants.

        Deliberately not hardcoded integers: the champion is registry v2
        and a promotion would legitimately move these. What must not move
        them is a tail-policy change, and comparing against the live curve
        evaluated at the CURRENT coordinate is what makes that specific.
        """
        c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)
        p = (float(rank) - 1.0) / float(PERCENTILE_REFERENCE_N - 1)
        expected = 9999 if p == 0.0 else max(1, min(9999, round(9999.0 / (1.0 + (p / c) ** s))))
        assert _contribution(rank) == expected

    def test_rank_one_is_still_the_top_of_the_scale(self):
        assert _contribution(1) == 9999

    def test_the_head_is_strictly_decreasing(self):
        ranks = list(range(1, PERCENTILE_REFERENCE_N + 1, 20))
        got = [_contribution(r) for r in ranks]
        assert got == sorted(got, reverse=True)
        assert len(set(got)) == len(got)


def _deep_fallback_rows() -> list[dict]:
    """Rows where ``idpTradeCalc`` is forced onto the value-direct fallback.

    ``_VALUE_SOURCE_DECLARED_MAX['idpTradeCalc']`` is 9999, so values above
    it are out of declared range (D-1 policy B); past the 2% escalation
    fraction the whole source is suppressed (policy C). Either way every
    row takes the Hill path and therefore the tail policy. Enough rows are
    generated to push effective ranks well past the saturation point.
    """
    total = PERCENTILE_REFERENCE_N + 120
    rows = [_row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)]
    for i in range(total):
        raw = 999900 - (i + 1) * 100
        rows.append(_row(f"D{i:04d}", "LB", idpTradeCalc=raw, dlfSf=raw))
    return rows


class TestTheFallbackFixtureReallyEntersTheDormantBranch:
    """GREEN guard for the blocked class below.

    Without it, the blocked fallback assertion could pass vacuously
    against the value-direct path and claim to cover a branch it never
    entered. This is also the test that surfaced the
    ``valueContributionPath`` defect: the stamp was re-derived rather than
    recorded, so it reported ``value_direct`` for 621 rows the pipeline
    had just priced with the Hill curve.
    """

    def test_the_fallback_branch_is_actually_reached_by_this_fixture(self):
        rows = _deep_fallback_rows()
        dc._compute_unified_rankings(rows, {})
        metas = [
            (r.get("sourceRankMeta") or {}).get("idpTradeCalc")
            for r in rows[1:]
            if (r.get("sourceRankMeta") or {}).get("idpTradeCalc")
        ]
        assert metas, "fixture stamped no idpTradeCalc meta at all"
        assert {m.get("valueContributionPath") for m in metas} == {"rank_hill"}
        assert {m.get("valueDirectFallbackReason") for m in metas} == {"source_suppressed"}


class TestTheFallbackPathTakesTheTailPolicy:
    """A value-direct source that falls back must get the tail too.

    ``_VALUE_BASED_SOURCES`` normally bypass the Hill curve entirely — on
    the pinned board ``idpTradeCalc`` is value-direct on all 779 of its
    observations and contributes **zero** saturated rank-Hill values, which
    is what the B4 correction established. But the fallback branch at
    ``data_contract.py`` (value suppressed, out of declared range, or
    missing) routes those rows through ``percentile_to_value`` — and
    therefore through the tail policy.

    **Fallback traffic is zero on this pin.** That is precisely why this is
    a test rather than an observation: it is a live production branch with
    no live exercise, so nothing but a regression can hold it to the
    policy. A repair that reached only the rank-only sources would leave a
    second, dormant saturation that appears the day a site changes scale.
    """

    def test_deep_fallback_ranks_do_not_collapse(self):
        """The defect, on the dormant branch."""
        rows = _deep_fallback_rows()
        dc._compute_unified_rankings(rows, {})
        by_name = {r["canonicalName"]: r for r in rows}

        # ``_blendedValueUncapped`` is stamped on every contributing row,
        # whereas ``rankDerivedValue`` is only stamped inside
        # ``OVERALL_RANK_LIMIT`` — reading the capped field would make this
        # depend on the board cut rather than on the tail policy.
        deep_a = by_name[f"D{PERCENTILE_REFERENCE_N + 10:04d}"]["_blendedValueUncapped"]
        deep_b = by_name[f"D{PERCENTILE_REFERENCE_N + 110:04d}"]["_blendedValueUncapped"]
        assert deep_a != deep_b, (
            "two ranks 100 apart on the value-direct FALLBACK path priced "
            f"identically ({deep_a}) — the dormant branch saturates too"
        )


def _row(name: str, position: str, **sites) -> dict:
    """Synthetic ``playersArray`` row.

    Same shape as the helper in ``tests/api/test_valuation_pipeline_stages.py``
    so both modules stress the pipeline entry point identically.
    """
    if position == "PICK":
        asset_class = "pick"
    elif position in ("DL", "LB", "DB"):
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
