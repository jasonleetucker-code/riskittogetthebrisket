# α Shrinkage Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- α grid: [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
- Chain under test: `Final = Anchor + α·(SubgroupBlend − Anchor)` where Anchor is IDPTC's percentile-Hill value and SubgroupBlend is the unweighted trimmed mean-median of the other sources' percentile-Hill values.

## Stability by α

| α | mean abs rank change | value-weighted rank change |
|---:|---:|---:|
| 0.00 | 3.038 | 3.057 |
| 0.10 | 2.988 | 3.043 |
| 0.20 | 2.912 | 3.052 |
| 0.30 | 2.881 ← best | 3.038 ← best |
| 0.40 | 3.169 | 3.260 |
| 0.50 | 3.594 | 3.675 |
| 0.60 | 4.148 | 4.236 |
| 0.70 | 4.799 | 4.959 |
| 0.80 | 5.169 | 5.436 |
| 0.90 | 5.390 | 5.826 |
| 1.00 | 5.834 | 6.278 |

## Recommendation

Promote **α = 0.30**  (best on value-weighted metric).  Best on unweighted metric was α = 0.30.  If they agree, the choice is obvious; if not, prefer the value-weighted optimum because top-of-board stability matters more than long-tail rank jitter.
