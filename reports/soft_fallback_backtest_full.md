# Soft-Fallback Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- Distance grid: [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
- Chain under test: Framework step 9 soft fallback adds an imputed contribution from scope-eligible sources that didn't rank the player.  Fallback rank = pool + round(pool × distance).

## Stability

| setting | mean abs rank change | value-weighted rank change |
|:---|---:|---:|
| disabled (pre-PR-4 behavior) | 2.881 | 3.038 |
| distance=0.00 | 0.882 ← best UW | 0.648 ← best VW |
| distance=0.10 | 0.888 | 0.652 |
| distance=0.20 | 0.935 | 0.682 |
| distance=0.30 | 1.021 | 0.736 |
| distance=0.50 | 0.987 | 0.718 |
| distance=0.75 | 0.998 | 0.728 |
| distance=1.00 | 0.942 | 0.683 |

## Recommendation

Promote **distance = 0.00** (+78.67% vs disabled, best on the value-weighted metric).  Best on unweighted metric was distance = 0.00.
