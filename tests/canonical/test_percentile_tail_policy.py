"""W30-F023 — the percentile tail must not collapse live evidence.

**RED as written.** Every assertion in ``TestDistinctEvidenceMustStayDistinct``
and ``TestTheFallbackPathTakesTheTailPolicy`` fails at the B4 pin. They
describe the defect, not a chosen repair.

The defect, stated once: ``rank_to_percentile`` saturates ``p`` at 1.0 once
the rank passes ``PERCENTILE_REFERENCE_N`` (500), so every deeper rank
receives an identical percentile and therefore an identical contribution
from that source. Measured on the pinned board
(``docs/master-site-audit/evidence/W30/b4_tail_report.json``): 421 of 5,146
rank-Hill observations sit past 500, touching **254 board rows, all 254 of
them served** — 34.3% of the 740 rows the board publishes, concentrated in
IDP (DB 79.8%, DL/EDGE 75.2%, LB 53.8% of served rows in bucket).

Two things these tests are deliberately careful about.

**They are policy-agnostic.** B4 has not selected a tail policy yet. A test
that asserted "``p`` may exceed 1.0" would presuppose the continuous
candidate and would fail under a bounded one that rescales the coordinate
instead; a test that asserted a specific boundary would presuppose the
bounded candidate. So what is asserted is the *observable* property both
must satisfy and the current behaviour does not: **two ranks a source
genuinely distinguishes must not be priced identically.** Only the
"change nothing" candidate fails these, which is correct — if B4 concludes
no repair is warranted, these tests are withdrawn with the conclusion, not
quietly kept.

**They call the real canonical functions.** Never a local re-implementation
of the Hill form. A copied formula here would pass while production stayed
saturated — which is exactly how
``tests/api/test_percentile_reference_resolution.py:44`` came to hold its
own copy of the production map.

The boundary numbers come from the B4 pin and are *live evidence depths*,
not constants to be tuned:

* deepest rank-Hill effective rank consumed by a SERVED row: **877**
  (``idpShow``), which is past ``OVERALL_RANK_LIMIT`` (800) — so the board
  limit is not a defensible saturation point for the source-coordinate
  domain. Different domains.
* deepest translated effective rank on any path: 899.

See ``docs/master-site-audit/evidence/W30/B4_TAIL_TRACE.md`` for the full
trace, including the four independent clamps this file's structural test
exists to collapse into one owner.
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
#: measured on the B4 pin. Evidence really does exist this far down: it is
#: ``idpShow``'s deepest contribution to a published row.
DEEPEST_SERVED_RANK_HILL = 877

#: Ranks the pin proves carry genuine, distinct live evidence past the
#: saturation point. Every one of these is inside some source's real
#: coverage on the pinned board.
LIVE_DEEP_RANKS = (501, 572, 620, 661, 684, 730, 877)


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
    """RED. Distinct live ranks currently price identically."""

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
    """RED. ``percentile_to_value`` re-decides the tail independently.

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

    Today the owner emits exactly 1.0 for every deep rank, so the second
    branch is taken and fails. That failure IS the defect.
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


class TestTheFallbackPathTakesTheTailPolicy:
    """RED. A value-direct source that falls back must get the tail too.

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

    def _deep_rows(self, *, out_of_range: bool) -> list[dict]:
        """Rows where ``idpTradeCalc`` is forced onto the fallback branch.

        ``_VALUE_SOURCE_DECLARED_MAX['idpTradeCalc']`` is 9999, so a value
        above it is out of declared range (D-1 policy B) and takes the
        same fallback a missing value takes. Enough rows are generated to
        push ranks past the saturation point.
        """
        total = PERCENTILE_REFERENCE_N + 120
        rows = [_row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)]
        for i in range(total):
            raw = 999900 - (i + 1) * 100
            rows.append(
                _row(
                    f"D{i:04d}",
                    "LB",
                    idpTradeCalc=(raw if out_of_range else raw / 100.0),
                    dlfSf=999900 - (i + 1) * 100,
                )
            )
        return rows

    def test_the_fallback_branch_is_actually_reached_by_this_fixture(self):
        """Guard: prove the fixture takes the Hill path before asserting on it.

        Without this the two tests below could pass vacuously against the
        value-direct path and claim to cover a branch they never entered.
        """
        rows = self._deep_rows(out_of_range=True)
        dc._compute_unified_rankings(rows, {})
        paths = {
            (r.get("sourceRankMeta") or {}).get("idpTradeCalc", {}).get("valueContributionPath")
            for r in rows[1:]
            if (r.get("sourceRankMeta") or {}).get("idpTradeCalc")
        }
        assert paths == {"rank_hill"}, f"fixture did not reach the fallback branch: {paths}"

    def test_deep_fallback_ranks_do_not_collapse(self):
        """The defect, on the dormant branch."""
        rows = self._deep_rows(out_of_range=True)
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
