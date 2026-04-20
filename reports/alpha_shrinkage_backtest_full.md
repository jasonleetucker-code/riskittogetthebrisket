# α Shrinkage Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- α grid: [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
- Chain under test: `Final = Anchor + α·(SubgroupBlend − Anchor)` where Anchor is IDPTC's percentile-Hill value and SubgroupBlend is the unweighted trimmed mean-median of the other sources' percentile-Hill values.

## Stability by α

| α | mean abs rank change | value-weighted rank change |
|---:|---:|---:|
| 0.00 | 0.346 ← best | 0.243 ← best |
| 0.10 | 0.402 | 0.299 |
| 0.20 | 0.580 | 0.468 |
| 0.30 | 0.877 | 0.670 |
| 0.40 | 1.445 | 1.065 |
| 0.50 | 1.852 | 1.386 |
| 0.60 | 2.356 | 1.833 |
| 0.70 | 3.164 | 2.557 |
| 0.80 | 3.943 | 3.268 |
| 0.90 | 5.203 | 4.474 |
| 1.00 | 5.997 | 5.363 |

## Recommendation

Promote **α = 0.00**  (best on value-weighted metric).  Best on unweighted metric was α = 0.00.  If they agree, the choice is obvious; if not, prefer the value-weighted optimum because top-of-board stability matters more than long-tail rank jitter.
