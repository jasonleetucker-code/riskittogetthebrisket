# α × λ Joint Backtest

- Snapshot count: **25**
- Date range: **2026-03-23 → 2026-04-16**
- α grid: [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]
- λ grid: [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]
- Metric: **value-weighted rank change** (lower = more stable)

**Caveat**: this metric rewards stability.  The stability optimum drifts toward α=0 and λ=0 — "use the anchor source alone, ignore the 15 other sources."  That's product-bad because the blend is supposed to reflect multi-source consensus.  Pick a joint point that's **near** the stability frontier but still preserves meaningful subgroup signal (α ≥ ~0.05) and some volatility damping (λ ≥ ~0.05).

## Heatmap (rows = α, cols = λ)

| α \ λ | 0.00 | 0.05 | 0.10 | 0.20 | 0.30 | 0.50 |
|---:|---:|---:|---:|---:|---:|---:|
| **0.00** | 0.149 ★ | 0.207 | 0.243 | 0.340 | 0.410 | 0.660 |
| **0.05** | 0.239 | 0.221 | 0.245 | 0.298 | 0.417 | 0.673 |
| **0.10** | 0.332 | 0.299 | 0.299 | 0.316 | 0.406 | 0.589 |
| **0.20** | 0.526 | 0.476 | 0.468 | 0.449 | 0.468 | 0.633 |
| **0.30** | 0.717 | 0.695 | 0.670 | 0.603 | 0.593 | 0.652 |
| **0.50** | 1.548 | 1.485 | 1.386 | 1.299 | 1.180 | 1.005 |

Stability-optimal cell: α=0.0, λ=0.0 (VW=0.149)

## Near-optimal non-degenerate cells (within 20% of optimum)

| α | λ | VW | % worse than optimum |
|---:|---:|---:|---:|
