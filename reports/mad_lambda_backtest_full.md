# MAD λ Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- λ grid: [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0]
- Chain under test: `center = (trimmed_mean + trimmed_median)/2`, `final = center − λ·MAD`, where MAD is the trimmed-mean absolute deviation of per-source Hill-curve values.

## Stability by λ

| λ | mean abs rank change | Δ vs λ=0 | value-weighted rank change | Δ vs λ=0 |
|---:|---:|---:|---:|---:|
| 0.00 | 0.203 ← best | +0.000 | 0.149 ← best | +0.000 |
| 0.05 | 0.284 | +0.081 | 0.207 | +0.057 |
| 0.10 | 0.346 | +0.143 | 0.243 | +0.094 |
| 0.20 | 0.495 | +0.293 | 0.340 | +0.191 |
| 0.30 | 0.599 | +0.397 | 0.410 | +0.261 |
| 0.50 | 1.007 | +0.805 | 0.660 | +0.511 |
| 0.70 | 1.463 | +1.261 | 0.945 | +0.796 |
| 1.00 | 1.861 | +1.658 | 1.229 | +1.079 |
| 1.50 | 2.124 | +1.921 | 1.486 | +1.337 |
| 2.00 | 2.117 | +1.915 | 1.511 | +1.361 |

## Recommendation

**Keep λ = 0.0.**  MAD penalty does not improve stability on this snapshot range — the Final Framework step 6 is an identity no-op and can be removed.  Consider whether a different optimization target (e.g. KTC alignment) would favour a non-zero λ before committing to remove the feature.
