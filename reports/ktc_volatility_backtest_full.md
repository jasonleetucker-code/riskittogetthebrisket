# KTC Volatility Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- Hill constants: midpoint=48.44, slope=1.149
- Pinned ranks: [1, 5, 12, 24, 50, 100, 150, 200, 300, 400]

Measures how much KTC's curve drifts day-to-day at the ranks pinned in `tests/canonical/test_ktc_reconciliation.py`. The `pct_diff` column is `(ours − ktc) / ktc × 100`; `ours` is deterministic, so all observed spread comes from KTC scrape drift.  **The `max dod` column is the statistic the ±tolerance band must absorb** — it's the largest consecutive-day jump in pct_diff observed across the history.

## Per-rank drift summary

| rank | n | ktc min | ktc max | ktc stdev | pct_diff min | pct_diff max | pct_diff stdev | max dod | p95 dod |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 25 | 9991 | 9999 | 2.6 | +0.00% | +0.08% | 0.03pp | 0.08pp | 0.06pp |
| 5 | 25 | 9568 | 9689 | 31.2 | -2.36% | -1.13% | 0.32pp | 0.36pp | 0.31pp |
| 12 | 25 | 7693 | 7794 | 24.5 | +8.53% | +9.96% | 0.35pp | 0.55pp | 0.40pp |
| 24 | 25 | 6743 | 6819 | 19.8 | +2.90% | +4.06% | 0.30pp | 0.64pp | 0.41pp |
| 50 | 25 | 5370 | 5413 | 11.9 | -8.24% | -7.50% | 0.20pp | 0.43pp | 0.40pp |
| 100 | 25 | 3873 | 3942 | 15.7 | -22.50% | -21.12% | 0.31pp | 1.04pp | 0.74pp |
| 150 | 25 | 3069 | 3122 | 14.5 | -30.91% | -29.72% | 0.33pp | 0.92pp | 0.79pp |
| 200 | 25 | 2632 | 2814 | 65.5 | -41.44% | -37.39% | 1.47pp | 2.30pp | 1.45pp |
| 300 | 25 | 1867 | 2101 | 107.2 | -47.64% | -41.08% | 3.00pp | 5.98pp | 0.28pp |
| 400 | 25 | 1231 | 1418 | 84.9 | -42.52% | -33.79% | 3.96pp | 8.36pp | 0.36pp |

## Aggregate drift across all pinned ranks

- Observations (day-over-day pct_diff deltas): **240**
- Max observed: **8.36pp**
- 99th percentile: **1.98pp**
- 95th percentile: **0.62pp**
- 90th percentile: **0.40pp**
- Median: **0.10pp**

## Tolerance-band sizing guidance

The `pct_diff` band in `PINNED_DELTAS` is a static center + ±DELTA_TOLERANCE_PP. The tolerance must be ≥ the max day-over-day jump observed in this history or a data refresh will break CI.  Safe sizing rules:

- **Strict (catches regressions earliest):** ceil(max_dod) + 1pp = 9pp
- **Balanced (absorbs 99% of drift):** ceil(p99) + 1pp = 2pp
- **Lax (absorbs 95% of drift, tolerates rare CI break):** ceil(p95) + 1pp = 1pp

Current tolerance **±5.0pp** covers the p99 drift (1.98pp) but NOT the max observed (8.36pp).  Expect ~1% of daily refreshes to break CI unless widened to **±9pp**.

## Per-rank day-over-day trace

Top few largest day-over-day pct_diff jumps, per rank.  Useful for spotting the specific dates KTC methodology appears to have shifted.

### rank 1

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-03-28 | 2026-03-29 | +0.08% | +0.00% | -0.08pp |
| 2026-03-23 | 2026-03-24 | +0.07% | +0.01% | -0.06pp |
| 2026-03-25 | 2026-03-26 | +0.00% | +0.06% | +0.06pp |

### rank 5

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-14 | 2026-04-15 | -1.13% | -1.49% | -0.36pp |
| 2026-04-11 | 2026-04-12 | -1.78% | -1.47% | +0.31pp |
| 2026-04-12 | 2026-04-13 | -1.47% | -1.17% | +0.30pp |

### rank 12

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-13 | 2026-04-14 | +9.52% | +8.97% | -0.55pp |
| 2026-04-14 | 2026-04-15 | +8.97% | +8.53% | -0.43pp |
| 2026-04-01 | 2026-04-02 | +9.70% | +9.46% | -0.24pp |

### rank 24

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-14 | 2026-04-15 | +3.42% | +4.06% | +0.64pp |
| 2026-04-15 | 2026-04-16 | +4.06% | +3.63% | -0.43pp |
| 2026-04-09 | 2026-04-10 | +3.30% | +3.60% | +0.31pp |

### rank 50

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-04 | 2026-04-05 | -7.76% | -8.19% | -0.43pp |
| 2026-04-08 | 2026-04-09 | -7.92% | -7.50% | +0.41pp |
| 2026-04-02 | 2026-04-03 | -8.12% | -7.76% | +0.36pp |

### rank 100

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-13 | 2026-04-14 | -21.47% | -22.50% | -1.04pp |
| 2026-03-24 | 2026-03-25 | -22.44% | -21.67% | +0.78pp |
| 2026-04-11 | 2026-04-12 | -21.12% | -21.67% | -0.55pp |

### rank 150

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-07 | 2026-04-08 | -30.75% | -29.83% | +0.92pp |
| 2026-03-31 | 2026-04-01 | -29.99% | -30.82% | -0.83pp |
| 2026-03-27 | 2026-03-28 | -30.28% | -29.72% | +0.57pp |

### rank 200

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-07 | 2026-04-08 | -40.20% | -37.91% | +2.30pp |
| 2026-03-27 | 2026-03-28 | -41.44% | -39.94% | +1.49pp |
| 2026-03-25 | 2026-03-26 | -39.81% | -41.04% | -1.23pp |

### rank 300

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-07 | 2026-04-08 | -47.32% | -41.33% | +5.98pp |
| 2026-04-10 | 2026-04-11 | -41.36% | -41.08% | +0.28pp |
| 2026-04-12 | 2026-04-13 | -41.18% | -41.46% | -0.28pp |

### rank 400

| prev date | curr date | prev pct | curr pct | Δ |
|---|---|---:|---:|---:|
| 2026-04-07 | 2026-04-08 | -42.16% | -33.79% | +8.36pp |
| 2026-04-12 | 2026-04-13 | -34.06% | -34.43% | -0.37pp |
| 2026-03-29 | 2026-03-30 | -42.48% | -42.20% | +0.29pp |
