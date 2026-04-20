# Blend Parameter Backtest

Snapshot count: **25**
Runtime: **330.2s**

Stability metric: mean absolute change in ``canonicalConsensusRank`` across consecutive-day pairs for top-200 players present in both days.  Value-weighted variant weights each delta by the day-T rank-derived value.

Lower = more stable = probably better-calibrated.  The *relative* ordering across parameter values is the signal; absolute numbers depend on the specific date range and do not imply calibration error.

## _BLEND_MEAN_WEIGHT

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 0.5 | _BLEND_ROBUST_WEIGHT=0.5 | 19.583 | 13.438 |
| 0.55 | _BLEND_ROBUST_WEIGHT=0.45 | 19.636 | 13.526 ← least stable |
| 0.6 | _BLEND_ROBUST_WEIGHT=0.4 | 18.593 | 12.849 |
| 0.65 | _BLEND_ROBUST_WEIGHT=0.35 | 18.475 | 12.635 |
| 0.7 | _BLEND_ROBUST_WEIGHT=0.3 | 17.541 | 12.218 **← most stable** |
| 0.75 | _BLEND_ROBUST_WEIGHT=0.25 | 18.057 | 12.570 |

Spread (worst − best): **1.307** (relative: 10.7%)

## _VOLATILITY_COMPRESSION_FLOOR

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 0.86 |  | 18.583 | 12.843 **← most stable** |
| 0.88 |  | 18.583 | 12.843 |
| 0.9 |  | 18.583 | 12.843 |
| 0.92 |  | 18.593 | 12.849 |
| 0.94 |  | 18.586 | 12.866 |
| 0.96 |  | 18.694 | 12.942 ← least stable |

Spread (worst − best): **0.099** (relative: 0.8%)

## _VOLATILITY_COMPRESSION_CEIL

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 1.02 |  | 18.698 | 13.059 ← least stable |
| 1.04 |  | 18.594 | 12.865 |
| 1.06 |  | 18.593 | 12.849 **← most stable** |
| 1.08 |  | 18.593 | 12.849 |
| 1.1 |  | 18.593 | 12.849 |
| 1.12 |  | 18.593 | 12.849 |
| 1.14 |  | 18.593 | 12.849 |

Spread (worst − best): **0.209** (relative: 1.6%)

## RANKING_SOURCES[idpTradeCalc].weight

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 1.0 |  | 19.686 | 14.060 ← least stable |
| 1.5 |  | 19.225 | 13.495 |
| 2.0 |  | 18.593 | 12.849 |
| 2.5 |  | 18.867 | 12.736 |
| 3.0 |  | 17.598 | 12.115 **← most stable** |

Spread (worst − best): **1.945** (relative: 16.1%)

