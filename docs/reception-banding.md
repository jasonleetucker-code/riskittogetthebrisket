# Reception-distance banding

How this league's banded reception scoring is measured, projected, and
applied — and which parts are measured versus assumed.

## The scoring

`dynasty_main` does not pay a flat PPR. It bands receptions by yards
gained. Per-catch total (`rec` + the band key), against the comparison
league's flat card:

| band | this league | baseline | ratio |
|---|---|---|---|
| 0–4 yd | 0.25 | 0.75 | **0.33x** |
| 5–9 yd | 0.50 | 0.75 | 0.67x |
| 10–19 yd | 0.75 | 0.75 | 1.00x |
| 20–29 yd | 1.00 | 0.75 | 1.33x |
| 30–39 yd | 1.25 | 0.75 | 1.67x |
| 40+ yd | 2.00 | 0.75 | **2.67x** |

An 8x spread. Every ranking source prices a flat rate, so the market
structurally cannot see this.

## Where catches actually fall

Measured over 11,217 receptions, 2025:

| band | share |
|---|---|
| 0–4 | 22.5% |
| 5–9 | 34.1% |
| 10–19 | 29.6% |
| 20–29 | 8.8% |
| 30–39 | 3.0% |
| 40+ | 2.0% |

Catch-weighted value per reception: **0.6148 here vs 0.7500 baseline**.

Note this is *not* the same as the unweighted band-table average. Real
receptions skew short, so the typical catch is worth less than the
middle band suggests.

## Quote the tilt, never the 8x

The 8x is per-catch. Receptions are only 17–33% of a skill player's
points, so the composed effect on player VALUE is far smaller. Measured
over 199 receivers with 20+ catches, 2025:

```
tilt   median 1.000   p10 0.942   p90 1.042   min 0.765   max 1.098
```

Coherent at the extremes rather than random — checkdown backs and
short-area tight ends down (Jerome Ford 0.765), deep threats up (Alec
Pierce 1.098).

Anyone sizing a trade off "8x" will be wrong by an order of magnitude.

## Tilt is measured; level is assumed

The per-player *tilt* and the shared *level* have completely different
epistemic status, and they are reported separately for that reason.

A flat baseline scales every player by the same constant, so:

| assumed market PPR | median ratio | p10 | p90 | **p90/p10** |
|---|---|---|---|---|
| 0.50 | 1.239 | 0.978 | 1.466 | **1.498** |
| 0.75 | 0.826 | 0.652 | 0.977 | **1.498** |
| 1.00 | 0.619 | 0.489 | 0.733 | **1.498** |

**The spread is identical to three decimals. The level swings 2x and
changes sign.** At 0.5 PPR the receiving corps marks up 24%; at 1.0 it
marks down 38%.

The baseline is one Sleeper league that happens to pay 0.75/catch.
Nothing establishes that this is what dynasty boards price on.

So `reception_fit` applies the tilt and holds the level out
(`level_multiplier`, `levelApplied: false`). Acting on a number whose
sign you cannot establish is worse than not acting.

**Open work:** measure what reception rate dynasty boards actually price
on. Until then the level stays reported and unapplied.

## Projecting it forward

No projection source publishes banded receptions, and probably none ever
will. The decomposition that makes it tractable:

```
projected banded points
    = projected receptions        (ordinary projection sources)
    x expected points per catch   (src/nfl_data/reception_shape_projection.py)
```

The second factor is a player **trait**, not a forecast of events, and
it is stable:

| | n | r | beats league-mean by |
|---|---|---|---|
| 2023 → 2024 | 123 | 0.767 | 52.6% of squared error |
| 2024 → 2025 | 128 | 0.718 | 44.3% of squared error |

r ≈ 0.72–0.77 is high for a year-over-year fantasy metric; most sit
between 0.3 and 0.5.

### Shrinkage

r is high, not 1.0. A 20-catch shape across six bands has empty cells by
chance, so a raw observed shape would hand the largest adjustments to
the players whose shapes are least known — the failure the IDP
per-player attempt was refused for.

Shrunk toward the player's **position** mean (not the league mean — an
RB's distribution is a different distribution, not a noisy draw from the
WR one), weighted by sample size: `w = n / (n + K)`.

`K` is fitted, scored on held-out next-season per-catch value:

| K | 2023→2024 | 2024→2025 | sum |
|---|---|---|---|
| 0 (own shape) | 0.005413 | 0.005977 | 0.011390 |
| 20 | 0.004144 | 0.004305 | 0.008449 |
| **40** | **0.004010** | **0.004087** | **0.008097** |
| 60 | 0.004024 | 0.004077 | 0.008101 |
| ∞ (position mean) | 0.004905 | 0.004927 | 0.009832 |

**Shrinkage beats both endpoints on both pairs** — 26% better than
trusting the player, 18% better than ignoring him. That result is what
justifies the method; had it beaten neither, the constant would be
decoration.

The optimum is flat between ~30 and 60, so the exact value is not
load-bearing.

## Status

| piece | state |
|---|---|
| Band extraction from play-by-play | done — `reception_depth.py`, 2023/2024/2025 on disk |
| Historical scoring | exact |
| Per-player tilt | done, flag **ON** (opt-in league-adjusted lens only) |
| Shared level | measured, **not applied** — needs the market-rate question answered |
| Shape projection + fitted shrinkage | done — `reception_shape_projection.py` |
| Wiring projection into forward rankings | **open** — needs a reception-volume projection source |

The last row is the remaining gap. Mike Clay's offense projections
(PR #610) supply reception volume, which is the missing half.
