# B4 §5 — every saturation point and tail assumption in the tree

Read-only trace at the B4 pin (`d1831d062`; integrated main `a89a07ea3`
plus two documentation-only commits). Nothing here changes production.

**Headline: there are FOUR independent `p ≤ 1.0` clamps on the percentile
coordinate, not two.** The finding and B1.2 both named two. A repair at
`rank_to_percentile` alone is silently undone by the second on the serving
path, and the third and fourth would keep the fit and the holdout flat past
`p = 1` regardless of what serving does — so a "fixed" board would be
scored against a still-saturated evaluator.

## The four clamps

| # | location | what it clamps | consequence if the others are missed |
|---|---|---|---|
| 1 | `src/canonical/player_valuation.py:170` | `return max(0.0, min(1.0, p))` in `rank_to_percentile` | the primary one; repairing only this is undone by #2 |
| 2 | `src/canonical/player_valuation.py:484` | `p = max(0.0, min(1.0, float(percentile)))` in `percentile_to_value` | re-clamps even when the caller supplies `p > 1`, so serving stays flat |
| 3 | `src/model_registry/holdout.py:168` | `9999.0 / (1.0 + (min(p, 1.0) / c) ** s)` in the deliberately-duplicated standalone `hill()` | challengers are **scored** on a saturated curve; a repaired board would be evaluated by a flat evaluator |
| 4 | `scripts/fit_hill_curve_percentile.py:261` | `p = max(0.0, min(1.0, float(p)))` in `_hill` | training coordinates are capped, so any refit re-learns the saturated shape |

Two further transcriptions of the same rule, which matter for consistency
rather than for serving:

* `scripts/backtest_legacy_rank_curve.py:148` — a local re-implementation of
  `rank_to_percentile` with its own clamp.
* `tests/api/test_percentile_reference_resolution.py:44` — a test-side copy
  of the production map, with its own clamp, that will pass or fail
  independently of the code it is meant to guard.

And one published declaration: `src/api/data_contract.py:9562-9563` serves
`p = clamp((rank-1)/(referenceN-1), 0, 1)` to the frontend inside
`methodology.formula`, with `referenceN` at `:9565`. Any policy change has
to update what the contract *says* as well as what it does.

## The stated policy, quoted

`rank_to_percentile` (`player_valuation.py:156-157`):

> Ranks past the reference population clamp to 1.0 and share the curve's
> tail — **deliberate top-N-board behavior, not an accident.**

`percentile_to_value` (`:458-462`):

> In the LIVE pipeline N is the fixed 500-rank combined-pool reference for
> every source — **ranks past 500 clamp to p=1.0 and share the curve's tail
> value.**

So the current behaviour is documented as intentional. B4's question is not
"was this a bug" but "does the stated policy still match what the site
serves" — and the site now publishes ranks to 740 with sources ranking to
899, which the policy's own phrase "top-N-board behavior" no longer
describes.

## What a change to `PERCENTILE_REFERENCE_N` does and does not reach

Reached automatically (via the alias and default args): the
`_PERCENTILE_REFERENCE_N` alias at `data_contract.py:5412`, the live
denominator resolver `_percentile_denom_for_source` at `:7031`, **the live
serving call site** `rank_to_percentile(float(eff_rank), reference_n=denom)`
at `:7799`, the stamped `referenceN` on all four `hillCurves` at `:5448`,
the published `methodology.formula` at `:9565`, and — through the default
argument — `holdout.py:154` and `fit_hill_curve_percentile.py:256`.

**Not reached**, and each is a place a partial repair leaks:

* all four clamps above;
* the hardcoded `[:400]` at `fit_hill_curve_percentile.py:385` and `:406`,
  which duplicates `FIT_TOP_N` rather than importing it (parity is enforced
  only by `tests/audit/test_b1_pin_coverage.py:140,147`);
* the rank→tier ladders at `data_contract.py:2075` (`rank <= 500 → 7`) and
  `:2079` (`rank <= 800 → 9`), which mirror both constants and read
  neither, plus their JS mirror at `frontend/lib/rankings-helpers.js:49,51`;
* `OVERALL_RANK_LIMIT` at `data_contract.py:64`.

## Board truncation — a separate boundary from the percentile one

`OVERALL_RANK_LIMIT = 800` (`data_contract.py:64`) has exactly four
behavioural uses: `:8325` (`total_ranked`), **`:8327`
(`row_normalized[:OVERALL_RANK_LIMIT]` — the board cut, where rows past it
lose both `canonicalConsensusRank` and `rankDerivedValue`)**, `:9527`
(methodology text) and `:9660` (published field). `KTC_RANK_LIMIT` and
`IDP_RANK_LIMIT` at `:66-67` have **no reads anywhere** — back-compat
aliases only.

`FIT_TOP_N = 400` (`holdout.py:87`) selects which observations are scored;
`:149`'s comment already records that it no longer decides the universe.

So there are three distinct depths in play — 400 (what is fit), 500 (where
the coordinate saturates) and 800 (what is published) — and only the middle
one is the subject of this finding.

## The second, independent percentile system — do not conflate

`sourceRankPercentileSpread` divides a source's raw rank by that source's
own ranked-row count (`data_contract.py:4289,4296`, pool size from
`:7286`), and clamps separately at `:4297`. It has nothing to do with
`PERCENTILE_REFERENCE_N` and must not be swept into a tail repair. Same for
`_disagreement_depth_allowance` (`:178`, saturates at 25% board depth),
the corridor's list-quantile `_percentile` (`:4895`), and
`idp_backbone.py:335`'s coverage weight (documented inert).

## The frontend already disagrees with the backend past rank 500

`frontend/components/graphs/HillCurveExplorer.jsx:35-42` re-evaluates the
Hill in **rank form** from the backend-stamped `midpoint = c·(referenceN−1)`
and **has no `p ≤ 1` clamp at all**. It clamps only the output to
`[1, 9999]` and the rank floor to 1. So the drawn curve keeps decaying past
rank 500 while the backend's actual contributions are flat there: the curve
and its own scatter points diverge past 500 **by construction**, today, on
the live page. That is a user-visible symptom of this finding that neither
the finding nor B1.2 recorded.

Two more frontend re-derivations with no upper rank bound:
`frontend/lib/value-history.js:344-353` hand-duplicates the rank-form
constants (`midpoint 65.4`, `slope 0.91`) and `:368-380`'s `rankFromValue`
can emit ranks past 800 uncapped.

Also relevant to any change at the 800 boundary:
`frontend/lib/dynasty-data.js:1401` assigns `computedConsensusRank = i + 1`
to rows the backend left unranked, and `:1005`/`:167` fall back to the
scraper composite when `rankDerivedValue` is absent — a silent scale switch
for every row past 800.

## Nine test files pin the current tail as intentional

These are not incidental; they assert the collapse as correct behaviour and
each would have to be re-decided by any repair:

* `tests/api/test_percentile_reference_resolution.py` — the M1 tripwire.
  `:84` `== 500`, `:85` `OVERALL_RANK_LIMIT == 800`, `:92` `gap <= 300`;
  `:50` asserts ranks {500, 600, 800, 1000} yield **one** value; `:75` pins
  the tail at 794.0.
* `tests/api/test_valuation_pipeline_stages.py:279-350` —
  `TestPercentileReferenceClamp`; `:311-346` drives 560 real rows through
  `_compute_unified_rankings` and asserts `deep_a == deep_b`.
* `tests/canonical/test_coordinate_equivalence.py:155-179` — asserts
  `{N, N+20, 700, 899, 5000}` all map to `1.0`, with the comment "the clamp
  is the mechanism under test", and that `N=500` **must** collapse its tail.
  This one is mine, from B1.2, and it is the sharpest example of a test that
  encodes the defect as an invariant.
* plus `test_percentile_coordinate_contract.py`, `test_ktc_reconciliation.py`,
  `test_hill_percentile_constants_tripwire.py`,
  `test_fitted_curve_bounds.py:13-14,229-245`,
  `test_refit_path_characterisation.py`, and
  `tests/audit/test_b1_2_reference_universe_evaluation.py:125`.

## Consequence for the repair

There is no one-line fix. A tail-policy change needs **one canonical owner**
that all four clamps defer to, rather than four independent interpretations
of the same rule — otherwise serving, fitting and scoring can disagree about
where the tail is, which is precisely the class of defect W30-F008 was.

Corroborating the served depth from an independent place in the tree:
`src/api/source_history.py:352` and its tests record that **the deepest rank
any source publishes is 903**, consistent with the 899 measured on this pin.
