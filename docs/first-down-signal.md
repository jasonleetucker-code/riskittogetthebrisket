# First downs: what they're worth, and what they're not

This league pays a first-down bonus — **1.00 for RB/WR/TE, 0.67 for QB**.
Two separate questions got asked about that, and they got opposite
answers. Both are recorded here so neither gets re-litigated.

| question | answer |
|---|---|
| Are first downs scored at all? | **Yes** — since PR #609. |
| Should there be a first-down *valuation axis* on the market board? | **No.** Measured; the signal beyond yards is too small to price. |
| Does anything currently *lose* first-down points? | **Yes** — BDVM's projection path. Fixed here. |

Reproduce anything below with `src/nfl_data/first_down_rate.py`'s
`fit_first_downs_per_yard` over `fetch_weekly_stats([2023, 2024, 2025])`.

## 1. First downs are scored

`realized_points.py` sums `passing_first_downs` + `rushing_first_downs`
+ `receiving_first_downs` and applies the position-scoped
`bonus_fd_{qb,rb,wr,te}` rate. That landed in #609 as one of seven live
scoring rules the engine had been silently ignoring.

Nothing to do. Realized scoring is exact, because play-by-play-derived
nflverse columns carry the real counts.

## 2. There should NOT be a first-down valuation axis

The hypothesis worth testing: *a player who converts more first downs
than his yardage predicts is worth more in this league.*

It fails three ways in sequence.

### 2a. Yards already explains almost all of it

Fit through the origin, 2023–25 regular seasons, 200+ total yards:

| pos | n | first downs per yard | R² | yards per first down |
|---|---|---|---|---|
| QB | 186 | 0.04998 | **0.9896** | 20.0 |
| RB | 241 | 0.04964 | 0.9417 | 20.1 |
| WR | 355 | 0.04715 | 0.9382 | 21.2 |
| TE | 142 | 0.05090 | 0.9105 | 19.6 |

All four positions are **one first down per twenty yards**, within 8% of
each other, and the constants drift only 2.0–4.8% across the three
seasons.

Practically: paying 1.00 per first down is almost exactly equivalent to
raising `rec_yd`/`rush_yd` from 0.10 to ~0.147. It's a near-uniform
scale on yardage, and a rank-ordered board is largely invariant to that.

### 2b. The residual is only stable for two positions, and weakly

Year-over-year correlation of the *residual* — first downs above/below
what yards predicts, per touch, 40+ touch players:

| pos | 2023→2024 | 2024→2025 | read |
|---|---|---|---|
| QB | +0.068 | +0.068 | **noise** — consistently ~zero |
| TE | +0.056 | −0.023 | **noise** — flips sign |
| RB | +0.242 | +0.368 | weak, replicated |
| WR | +0.315 | +0.387 | weak, replicated |

RB and WR replicate with the same sign and similar magnitude across two
independent season pairs, so something is there. But r ≈ 0.3 against the
reception-band shape's r ≈ 0.72–0.77 is a different class of signal.

### 2c. And the predictable part is worth about two points a season

2025 residual spread, converted to points at this league's rates:

| pos | n | residual sd (first downs) | p10..p90 | points sd | as % of a season |
|---|---|---|---|---|---|
| QB | 61 | 7.74 | −8.9 .. +7.1 | 5.18 | 2.35% |
| RB | 79 | 6.59 | −8.0 .. +7.3 | 6.59 | 4.28% |
| WR | 60 | 5.16 | −6.4 .. +6.7 | 5.16 | 3.27% |
| TE | 30 | 3.76 | −4.6 .. +5.8 | 3.76 | 3.20% |

Extremes are real but modest — Kareem Hunt **+24.6 points** above what
his yardage predicted in 2025, James Cook **−13.0**.

The number that decides it: only `r` of that spread is predictable, so
the expected forward tilt is `0.3 × 6.6 ≈ 2.0 points` for a back —
about **1.3% of a season**. The reception-band tilt, by comparison,
moves players ±20%.

**Verdict: not worth an axis.** Building one would be pricing a 1.3%
expected effect on top of a consensus blend whose own noise is larger,
and 90%+ of what it appeared to add would be yardage the board already
has.

## 3. What DID need fixing: BDVM's projection path

BDVM deliberately scores projected stat lines through the same
`compute_weekly_points` as realized ones — one scorer, one card. Right
design, one leak: **the scorer reads first downs from columns, and no
projection source publishes them.** Mike Clay's guide emits attempts,
completions, yards, receptions and touchdowns
(`src/bdvm/clay_projections.py`), which is typical.

Measured on realistic season lines under this card:

| pos | as the source emits it | with first downs | understated by |
|---|---|---|---|
| QB (4,200 pass + 320 rush) | 344.5 | 495.6 | **30.5%** |
| RB (1,150 rush + 400 rec) | 246.0 | 317.6 | 22.5% |
| WR (1,250 rec) | 180.6 | 236.3 | 23.6% |
| TE (820 rec) | 124.2 | 164.9 | 24.6% |

Two things make this worse than a scale error:

- **It's uneven** — 1.44× for a QB against 1.29× for a back. BDVM
  produces *relative* value, so a uniform error would cancel; this one
  survives, and it reprices superflex's central QB-vs-skill question.
- **It's mixed.** The reconstructed baseline is scored from **realized**
  weekly rows, which DO carry the columns. So inside one snapshot a
  Clay-covered player sat ~24% below an otherwise identical player still
  on the proxy — and nothing errored, because both numbers look ordinary.

### The fix, and why it's measurement rather than invention

`src/nfl_data/first_down_rate.py` imputes first downs from yards at the
measured per-position rate, and `src/bdvm/projections.py` opts in at the
single projection call site.

The choice was never "impute or stay pure." It was between a number
right to within R² = 0.91–0.99 and a *guaranteed* 22–30% error that
differs by position. But it's only honest if it's labelled, hence
`ProjectionRecord.first_downs_imputed`.

Four refusals, each test-pinned:

- **Never touches a line that already has first downs**, including a
  present-but-zero column — a source emitting 0 is telling us he had
  none. The double-count guard is structural, not a rule to remember.
- **Never guesses an unmeasured position.** Only QB/RB/WR/TE were fitted.
- **Never runs on realized stats.** Those have real columns.
- **Through the origin.** Zero yards must mean zero first downs; a fitted
  intercept (+1.2 WR, +4.2 TE on the same data) hands free first downs
  to a player projected for almost nothing.

A league that doesn't pay first downs needs no gate — the scorer
multiplies by 0.0. Pinned anyway, so nobody adds one.

## What would change these answers

- **§2 could flip with more seasons.** RB/WR replicate at r ≈ 0.3 on two
  transitions. Five seasons would say whether that's a real 3% edge or
  regression toward zero. It is not currently worth building on.
- **A source that publishes first downs makes §3 moot for its players** —
  the imputation stands down automatically, per the first refusal above.
- **Richer play-by-play framings are unexplored**: conversion rate on
  third and fourth down, first downs in short yardage. Those are
  different quantities than the season aggregate used here, and §2's
  null does not rule them out — it only rules out the aggregate.
