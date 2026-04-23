# Blend Parameter Backtest

Snapshot count: **10**
Runtime: **103.4s**

Stability metric: mean absolute change in ``canonicalConsensusRank`` across consecutive-day pairs for top-200 players present in both days.  Value-weighted variant weights each delta by the day-T rank-derived value.

Lower = more stable = probably better-calibrated.  The *relative* ordering across parameter values is the signal; absolute numbers depend on the specific date range and do not imply calibration error.

## _BLEND_MEAN_WEIGHT

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 0.5 | _BLEND_ROBUST_WEIGHT=0.5 | 11.424 | 7.487 |
| 0.55 | _BLEND_ROBUST_WEIGHT=0.45 | 12.902 | 8.187 ← least stable |
| 0.6 | _BLEND_ROBUST_WEIGHT=0.4 | 11.538 | 7.560 |
| 0.65 | _BLEND_ROBUST_WEIGHT=0.35 | 11.296 | 7.241 **← most stable** |
| 0.7 | _BLEND_ROBUST_WEIGHT=0.3 | 12.069 | 7.491 |
| 0.75 | _BLEND_ROBUST_WEIGHT=0.25 | 11.856 | 7.488 |

Spread (worst − best): **0.946** (relative: 13.1%)

## _VOLATILITY_COMPRESSION_FLOOR

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 0.86 |  | 11.536 | 7.557 |
| 0.88 |  | 11.536 | 7.557 |
| 0.9 |  | 11.536 | 7.557 |
| 0.92 |  | 11.538 | 7.560 |
| 0.94 |  | 11.508 | 7.553 **← most stable** |
| 0.96 |  | 11.590 | 7.602 ← least stable |

Spread (worst − best): **0.049** (relative: 0.6%)

## _VOLATILITY_COMPRESSION_CEIL

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 1.02 |  | 11.655 | 7.712 ← least stable |
| 1.04 |  | 11.536 | 7.566 |
| 1.06 |  | 11.538 | 7.560 **← most stable** |
| 1.08 |  | 11.538 | 7.560 |
| 1.1 |  | 11.538 | 7.560 |
| 1.12 |  | 11.538 | 7.560 |
| 1.14 |  | 11.538 | 7.560 |

Spread (worst − best): **0.152** (relative: 2.0%)

## RANKING_SOURCES[idpTradeCalc].weight

| value | extra | mean abs rank change | value-weighted rank change |
|------:|:------|---------------------:|---------------------------:|
| 1.0 |  | 12.687 | 8.736 ← least stable |
| 1.5 |  | 12.868 | 8.397 |
| 2.0 |  | 11.538 | 7.560 |
| 2.5 |  | 12.465 | 7.977 |
| 3.0 |  | 11.753 | 7.462 **← most stable** |

Spread (worst − best): **1.274** (relative: 17.1%)

