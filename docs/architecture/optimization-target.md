# Value Engine Optimization Target

Codified from the 2026-04-20 pipeline audit, Deliverable 3.

> **Note (2026-04-20 forward).**  Several specific mechanisms cited
> in the "What this framework looks like in production" section
> below — λ·MAD, soft-fallback value injection, Hill re-mapping of
> value-based sources' live votes — have since been overridden.  See
> `docs/architecture/live-value-pipeline-trace.md` Phase 3 for the
> authoritative live behaviour and
> `docs/architecture/final-framework-transition.md` for the
> "Post-framework overrides" summary.  The **optimization target**
> ("market consensus fit" + the per-rank KTC tolerance bands) is
> unchanged; only the machinery that pursues it has been simplified.

## The declared target

**Market consensus fit.**  Our values should track KeepTradeCut and the
other retail value sources within a stated tolerance at every rank tier.

## Why this target

Four candidates were considered.  Only this one is both measurable
today and product-appropriate for a trade calculator.

| Target | Measurable today? | Product fit |
|---|---|---|
| Market consensus fit | yes (25-day KTC snapshot history in `data/`) | trades happen in the retail market, so our values need to be speakable against it |
| Historical trade calibration / backtest | no (no labeled trade corpus exists) | ideal theoretical target but dataset missing |
| Projections-based VOR | no (`src/league/` is a placeholder; scarcity/replacement removed) | requires infra we don't have |
| Anchored hybrid | no (needs A + C first) | premature — compose one target at a time |

## What "market consensus fit" means, precisely

Three tiers:

1. **Top of board (ranks 1-50)**: our Hill curve values should track KTC
   within ±2 percentage points.  KTC is very stable here (max observed
   daily drift 0.64pp across 25 snapshots — see
   `reports/ktc_volatility_backtest_full.md`), so we can afford a tight
   band and should catch regressions early.
2. **Mid-board (ranks 100-150)**: ±3pp.  Moderate drift (max 1.04pp).
3. **Deep tail (ranks 200-400)**: ±10pp.  KTC actively re-shapes this
   region; occasional 8+pp structural jumps are normal (the 2026-04-07 →
   2026-04-08 event).  The band absorbs typical drift but still catches
   our-curve regressions.

These bands are pinned in `tests/canonical/test_ktc_reconciliation.py`
and re-derivable via `scripts/backtest_ktc_volatility.py`.

## Why NOT to over-fit KTC

KTC is one source among many.  Our values blend KTC with IDPTC,
DynastyNerds, DynastyDaddy, DLF, FantasyPros, FootballGuys, Flock,
Yahoo/Boone, and DraftSharks.  If we chase KTC exactly we lose the
benefit of the broader market.

**The target is "market consensus," not "KTC exactly."**  KTC's known
systematic biases (deeper rookies priced lower than expert consensus,
for instance) should NOT be reproduced in our output.  The tolerance
bands above permit deliberate divergence where the blend
demonstrably knows better than KTC alone.

## What this target is NOT optimizing for

- **Predictive accuracy** on future trades — that would require a
  labeled trade corpus we don't have.
- **Individual user satisfaction** — user preferences vary; the target
  is aggregate market fit.
- **Alignment with any single non-KTC source** — KTC is the retail
  authority and has the cleanest daily-drift profile.  Other sources
  are inputs to the blend, not targets.
- **Short-horizon trade value** — our values are dynasty (long-horizon).

## Consequences for open work

Changes to the live value engine should be evaluated against this
target.  Specifically:

- **R-H1 (Hill curve refit)**: should optimize the fit against KTC +
  the other value-based sources at the pinned tolerance tiers.  Accept
  that the fit will be conservative toward the deep tail until a
  better-grounded target is available.
- **R-V1 (volatility constants refit)**: should not drift top-of-board
  values away from KTC more than ±1pp from the current state.  Anything
  more is a deliberate change, not a tuning optimization.
- **R-V3 (trim heuristic refit)**: same principle — local robustness
  improvements are OK; systemic drift away from KTC at ranks 1-50
  requires a documented product reason.

## When to change this target

This target is the right first thing to optimize for.  It is not the
only thing the system could be optimized for forever.

A shift to a different target is warranted when any of these become
true:

1. A labeled trade corpus exists (→ pivot to target B).
2. League-specific projections and replacement machinery exist
   (→ pivot to target C or D).
3. KTC ceases to be the retail authority users actually trade against.

None of these are true today.  Re-evaluate annually or when the user
says the system's outputs feel systematically off.

## How to know the target is being met

A green CI run on:

- `tests/canonical/test_ktc_reconciliation.py` (tiered bands)
- `tests/canonical/test_canonical_single_curve.py`
- `tests/api/test_single_curve_live.py` (chain identity + soft fallback)
- `tests/idp_calibration/test_family_scale_once_only.py`
- `tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged`
  (offense + IDP anchor bands)

is the executable definition of "target met."

## Update — 2026-04-20: Final Framework transition complete

The value engine now matches the user-specified Final Framework end-to-end
(see `docs/architecture/live-value-pipeline-trace.md` for the full chain).
Four PRs delivered the transition:

1. PR #158 — trimmed mean-median blend; removed 8 hand-tuned
   volatility constants.
2. PR #159 — MAD volatility penalty with backtested λ.
3. PR #160 — percentile-input Hill + hierarchical anchor (IDPTC) + α.
4. PR #161 — soft fallback for unranked (step 9).
5. Follow-up — joint α × λ re-validation; promoted **α=0.10, λ=0.10**
   (see `reports/alpha_lambda_joint_backtest_full.md`).

### Important finding from the joint validation

The stability-optimal point of the α × λ landscape is **α=0, λ=0** —
i.e., "use IDPTC alone, ignore the 15 other sources."  This optimum is
**product-degenerate**: it violates the market-consensus-fit target
declared in this document because the board would reflect a single
source's opinion, not multi-source consensus.

The chosen operating point (α=0.10, λ=0.10) is the cheapest
non-degenerate joint cell.  It sits ~2× worse on the VW rank-stability
metric than the degenerate optimum, but preserves 10% subgroup voice
so all 15 non-anchor sources still shape the final value through the
α-shrunk delta.

**This is the right product trade-off**: users trading against the
retail market (KTC-anchored) benefit from a blend that sees every
major source's opinion while still being anchored to a single shared
scale.  α=0 would deliver IDPTC's board with a different logo.
