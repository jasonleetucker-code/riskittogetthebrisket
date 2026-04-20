# MAD λ Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- λ grid: [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0]
- Chain under test: `center = (trimmed_mean + trimmed_median)/2`, `final = center − λ·MAD`, where MAD is the trimmed-mean absolute deviation of per-source Hill-curve values.

## Stability by λ

| λ | mean abs rank change | Δ vs λ=0 | value-weighted rank change | Δ vs λ=0 |
|---:|---:|---:|---:|---:|
| 0.00 | 4.575 | +0.000 | 4.881 | +0.000 |
| 0.05 | 4.600 | +0.025 | 4.760 | -0.121 |
| 0.10 | 4.619 | +0.045 | 4.666 | -0.214 |
| 0.20 | 4.251 | -0.324 | 4.304 | -0.577 |
| 0.30 | 4.004 | -0.571 | 4.026 | -0.855 |
| 0.50 | 3.419 | -1.156 | 3.654 ← best | -1.226 |
| 0.70 | 3.403 ← best | -1.172 | 3.705 | -1.176 |
| 1.00 | 3.626 | -0.949 | 4.001 | -0.879 |
| 1.50 | 4.191 | -0.384 | 4.581 | -0.299 |
| 2.00 | 4.479 | -0.096 | 4.762 | -0.119 |

## Recommendation

**Promote λ = 0.50** (best on value-weighted metric, +25.13% vs λ=0).  Best on unweighted metric was λ = 0.70 (+25.62%).  If the two agree, the choice is obvious; if they disagree, prefer the value-weighted optimum because top-of-board stability matters more than long-tail rank jitter.
