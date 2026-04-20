# Final Framework Transition — Status: COMPLETE

Record of the four-PR transition from the pre-2026-04-20 value engine
(accumulated hand-tuned constants) to the user-specified Final
Framework (principled, backtested, multi-source with hierarchical
structure).  See `docs/architecture/live-value-pipeline-trace.md` for
the authoritative live-path description.

## The framework, as specified

1. Common internal 0-9999 value scale.
2. Normalize every source by relative rank: `p = (r-1)/(N-1)`.
3. Use a fitted Hill curve to convert percentile → value.
4. Use value-based sources to teach the curve.
5. Trimmed mean-median blend: `(trimmed_mean + trimmed_median) / 2`.
6. Volatility as a MAD penalty: `F = C − λ·MAD`.
7. Hierarchical anchor: one trusted combined offense+defense source
   sets the global baseline.
8. Subgroup adjustments with shrinkage: `Final = Anchor + α·Subgroup`.
9. Soft fallback for unranked players (not "dead last", just below
   each source's published list).

## The PRs that delivered it

| # | PR | What landed | Backtested constants |
|---|---|---|---|
| 1 | #158 | Trimmed mean-median blend; removed the ±8% z-score volatility stack (`_VOLATILITY_*`) and the 75-point monotonicity cap (`_MONOTONICITY_*`); retired the 70/30 weighted+robust convex combo (`_BLEND_*`). 8 hand-tuned constants removed. | — (structural) |
| 2 | #159 | MAD volatility penalty (framework step 6). | λ (initial) |
| 3 | #160 | Percentile-input Hill (framework steps 2-3); fitted new (c, s) for offense and IDP; hierarchical anchor flag (`is_anchor=True` for IDPTC); subgroup + α shrinkage combine (framework steps 7-8). | HILL_PERCENTILE_C/S, IDP_HILL_PERCENTILE_C/S, α (initial) |
| 4 | #161 | Soft fallback for scope-eligible unranked players (framework step 9). | _SOFT_FALLBACK_DISTANCE |
| — | follow-up | 2D α × λ joint backtest; re-promoted both constants. | **α=0.10, λ=0.10** (joint-optimal non-degenerate) |

## Final pipeline identity

```
For each source S that ranks player P:
    V_S = percentile_to_value((rank_S − 1) / (REF_N − 1))
    with Hill constants (c, s) = S's SCOPE master:
        - is_anchor    → GLOBAL master
        - offense scope → OFFENSE master
        - IDP scope     → IDP master

For each source S that does NOT rank P but whose scope admits P's position:
    fallback_rank = pool_size_S + round(pool_size_S × 0.0)   # framework step 9
    V_S = percentile_to_value((fallback_rank − 1) / (REF_N − 1))

anchor_V    = V from the anchor source (IDPTC)
subgroup_Vs = values from every non-anchor source
subgroup_blend = trimmed_mean_median(subgroup_Vs)             # framework step 5

center = anchor_V + α · (subgroup_blend − anchor_V)           # framework steps 7-8
MAD    = mean(|v − trimmed_mean| for v in trimmed(all V_S))
rankDerivedValueUncalibrated = center − λ · MAD               # framework step 6
    (= center for picks; pick-tier MAD is structurally
     non-uncertainty and exempted)

× (idpCalibrationMultiplier × idpFamilyScale)   (IDP rows only, if a
                                                  promoted config is present)
= rankDerivedValue
```

## Final constant values

| Name | Value | Source of truth |
|---|---|---|
| `_PERCENTILE_REFERENCE_N` | 500 | KTC's native pool size (design choice; +2% gain at N=400 not worth re-baselining, per `reports/percentile_reference_n_backtest_full.md`) |
| `HILL_GLOBAL_PERCENTILE_C` | 0.1880 | `fit_hill_curve_percentile.py` (IDPTC combined pool) |
| `HILL_GLOBAL_PERCENTILE_S` | 0.780 | same |
| `HILL_PERCENTILE_C` (offense) | 0.1100 | `fit_hill_curve_percentile.py` (mean of KTC + DD + DN per-source fits) |
| `HILL_PERCENTILE_S` (offense) | 1.210 | same |
| `IDP_HILL_PERCENTILE_C` | 0.1130 | `fit_hill_curve_percentile.py --universe idp` |
| `IDP_HILL_PERCENTILE_S` | 0.850 | same |
| `_ALPHA_SHRINKAGE` | 0.10 | `reports/alpha_lambda_joint_backtest_full.md` |
| `_MAD_PENALTY_LAMBDA` | 0.10 | `reports/alpha_lambda_joint_backtest_full.md` |
| `_SOFT_FALLBACK_ENABLED` | True | — |
| `_SOFT_FALLBACK_DISTANCE` | 0.00 | `reports/soft_fallback_backtest_full.md` |

Every tunable is now either:
- fitted from market data (Hill constants), or
- backtested against 25-day snapshot stability, or
- a design choice with a principled justification (reference N,
  anchor designation).

## What the framework buys us

Compared to the pre-2026-04-20 engine:

- **8 hand-tuned constants removed** (the ±8% volatility stack and
  the 75pt monotonicity cap).
- **Every remaining tunable is backtested or fit** — no "feels right"
  values anywhere in the live value path.
- **Simpler pipeline** — one Hill curve, one α combine, one MAD
  penalty, one calibration.  No multi-step z-score remaps, no
  monotonicity caps, no boost-clamp gymnastics.
- **79% stability improvement** on value-weighted rank change across
  consecutive daily snapshots (measured vs the pre-soft-fallback
  baseline, the largest single win of the arc).
- **Product-consistent**: the engine now matches the exact math
  specified by the operator.  Users trading against the retail market
  see a principled anchored consensus rather than an opaque
  multi-heuristic stack.

## What the framework does NOT fix

- KTC alignment: the engine targets market consensus, not KTC-exact.
  The tiered KTC reconciliation bands (±2-10pp) still hold.
- Historical trade accuracy: no labeled trade corpus exists.
  Optimization target remains "market consensus fit."
- IDP scoring-league specificity: IDP calibration (when an operator
  promotes a config via the calibration lab) still runs as a
  post-pass; that dimension is separate from the framework work.

## Backtest harnesses that exist today

| Harness | Measures | Output |
|---|---|---|
| `scripts/backtest_ktc_volatility.py` | KTC drift at pinned ranks | `reports/ktc_volatility_backtest_full.md` |
| `scripts/backtest_mad_lambda.py` | λ sensitivity (1D) | `reports/mad_lambda_backtest_full.md` |
| `scripts/backtest_alpha_shrinkage.py` | α sensitivity (1D) | `reports/alpha_shrinkage_backtest_full.md` |
| `scripts/backtest_soft_fallback.py` | Soft fallback distance sweep | `reports/soft_fallback_backtest_full.md` |
| `scripts/backtest_alpha_lambda_joint.py` | α × λ 2D sweep | `reports/alpha_lambda_joint_backtest_full.md` |
| `scripts/fit_hill_curve_percentile.py` | Percentile Hill fit | stdout only |
| `scripts/fit_hill_curve_from_market.py` | Legacy rank-based Hill fit | stdout only |

Re-run any of these after a data-schema change or on request.
