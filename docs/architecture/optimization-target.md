# Value Engine Optimization Target

Codified from the 2026-04-20 pipeline audit, Deliverable 3.

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

- `tests/canonical/test_ktc_reconciliation.py` (14 tests, tiered bands)
- `tests/canonical/test_canonical_single_curve.py` (6 tests)
- `tests/api/test_single_curve_live.py` (8 tests)
- `tests/idp_calibration/test_family_scale_once_only.py` (2 tests)
- `tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged`
  (offense + IDP anchor bands)

is the executable definition of "target met."
