# Percentile Reference N Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- N grid: [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
- Chain under test: `p = (effective_rank − 1) / (N − 1)`, fed into the Hill curve with current (c, s) constants.

## Stability by N

| N | mean abs rank change | value-weighted rank change |
|---:|---:|---:|
| 100 | 4.348 | 3.380 |
| 200 | 1.952 | 1.126 |
| 300 | 0.563 | 0.336 |
| 400 | 0.405 | 0.293 ← best VW |
| 500 | 0.402 | 0.299 |
| 600 | 0.412 | 0.316 |
| 700 | 0.405 | 0.319 |
| 800 | 0.386 | 0.313 |
| 900 | 0.373 | 0.326 |
| 1000 | 0.373 ← best UW | 0.321 |

## Recommendation

**Promote N=400**  (+2.01% vs N=500 on the value-weighted metric).  Best on the unweighted metric was N=1000.
