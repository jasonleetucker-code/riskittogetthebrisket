# Per-touch efficiency: measured, and already priced

The proposal: value players partly on **points per touch** rather than
only on season or per-game totals — the fantasy analogue of EPA/play.

The decomposition is sound and it's the same one the reception-band work
already validated:

```
season points  =  touches      x   points per touch
                  (volume)         (efficiency)
```

Two questions had to be answered before building anything: **is
efficiency a stable player trait**, and **is it already in the market
price**. The answers are *partly* and *yes*.

## Per TOUCH, not per opportunity — the distinction matters

The first pass measured points per *opportunity* (`attempts + carries +
targets`). That was the wrong denominator, and it understated the
signal, because a target that goes incomplete is charged against the
receiver even though catch rate is largely a fact about his quarterback.

Points per **touch** (`carries + receptions`) strips catch rate out and
asks only "what happens when he gets the ball". Year-over-year
correlation, mean of the 2023→24 and 2024→25 pairs:

| pos | per opportunity | **per touch** | change |
|---|---|---|---|
| QB | +0.408 | **+0.714** | +0.306 |
| WR | +0.325 | **+0.564** | +0.240 |
| RB | +0.318 | +0.338 | +0.019 |
| TE | +0.492 | +0.452 | −0.040 |

WR efficiency is a **substantially** more stable trait than the
opportunity-denominated figure suggested — 0.56, not 0.27. RB barely
moves, which is expected: a back's touches and his opportunities are
nearly the same set. QB's +0.714 sits on n=15 and should not be leaned
on.

So efficiency is real and reasonably sticky, at least for receivers.
That is not what kills the idea.

## What kills it: the market has already priced it

The decisive test isn't "is efficiency stable" — it's "does knowing it
tell us anything the board doesn't already say". If the market prices
efficiency, then among players with **similar volume and similar age**
the efficient ones should already carry higher values.

Regress log(value) on log(touches) + age, take the residual, correlate
it with 2025 points per touch:

| pos | n | our board, raw | our board, after volume+age | KTC market, after volume+age |
|---|---|---|---|---|
| WR | 59 | +0.411 | **+0.658** | **+0.652** |
| TE | 28 | +0.235 | +0.491 | +0.508 |
| QB | 21 | −0.039 | +0.399 | +0.432 |
| RB | 69 | +0.256 | +0.267 | +0.274 |

Two things to read off this.

**The market prices efficiency, strongly.** After stripping out volume
and age — the two things a dynasty value obviously tracks — what's left
of a receiver's market value still correlates at **+0.65** with how many
points he scores per touch. That is not a market ignoring efficiency.
It is a market that has already absorbed it.

**Our board and KTC agree almost exactly** (WR 0.658 vs 0.652, TE 0.491
vs 0.508, RB 0.267 vs 0.274, QB 0.399 vs 0.432). Our blend inherits the
market's efficiency pricing and adds nothing of its own on this axis —
so there is no gap between the two boards for an efficiency term to
close.

The one position where the market is relatively indifferent is **RB
(+0.27)** — and RB per-touch efficiency is also the least stable trait
of the four (+0.338). The market's indifference there looks correct
rather than exploitable.

## Volume is still the larger half

Share of the 2025 log-points spread, per position:

| pos | volume | efficiency |
|---|---|---|
| RB | 88% | 12% |
| QB | 81% | 19% |
| WR | 71% | 29% |
| TE | 58% | 42% |

**Tight end remains the exception worth watching.** TE volume is the
least stable of any position (r = 0.276 — target share swings wildly
year to year) while efficiency carries 42% of the spread. That is the
second independent probe pointing at TE; the adjusted-board backtest
found TE was the only position where the reception-band tilt improved
ordering in every framing (`docs/adjusted-board-backtest.md`). Sample is
the blocker: n = 20–28 per pair.

Touchdown regression is real but modest, and is *not* why efficiency is
unstable. Zeroing every `*_td` rule and re-scoring improves stability
for QB (+0.083), WR (+0.063) and TE (+0.043) — but not RB (−0.021).
Goal-line work is stickier than the folklore suggests.

## The league-specific per-touch terms are small

Efficiency could still earn an axis on the part of it the market
*cannot* see: this card's per-attempt terms, `pass_cmp` +0.15,
`pass_inc` −0.22, `rush_att` +0.08. Scoring 2025 with and without them:

| pos | mean contribution | as % of a season | spread |
|---|---|---|---|
| RB | +14.5 pts | 6.8% | 4.1% .. 9.3% |
| QB | +10.2 pts | 2.9% | −0.4% .. 5.5% |
| WR | +0.3 pts | 0.2% | −0.1% .. 0.9% |

**RB's 6.8% is not efficiency at all.** `rush_att` pays 0.08 per carry
regardless of outcome — a volume term wearing per-touch clothes, and
workload already captures it.

### The QB completion-rate term, isolated — and declined

An earlier draft of this document named QB completion-rate scoring as
"the one term that is both stable and genuinely unpriced". **That was
wrong, and it was wrong because it conflated two measurements**: an
ex-touchdown stability figure for QB efficiency *overall* (r = 0.597)
and a points figure for the combined per-play terms *including*
``rush_att``. Neither was about ``pass_cmp`` / ``pass_inc``.

Isolating those two keys alone — 2025, 36 QBs with 200+ attempts —
fails on all three counts a new axis has to clear.

**1. The prize is small.** The term spans **−2.9 to +22.7 points** over
a whole season, which is −1.5% to +4.3% of a QB's points:

```
Drake Maye      +22.7   (72.0% completions)
Mac Jones       +10.8   (69.6%)
Brock Purdy     +10.4   (69.4%)
   ...
Caleb Williams   -2.9   (58.1%)
Shedeur Sanders  -2.2   (56.6%)
J.J. McCarthy    -1.7   (57.6%)
```

**2. It does not replicate.** Year-over-year correlation of the term
per attempt — identical to completion percentage's, since the term is a
linear function of it:

| pair | n | r |
|---|---|---|
| 2023→2024 | 26 | +0.428 |
| 2024→2025 | 27 | **+0.159** |

One pair moderate, the next essentially zero. Compare the measurements
that *did* justify building something: reception band shape 0.767 /
0.718, per-touch WR efficiency 0.558 / 0.571. Those replicate; this
does not, and n ≈ 26 is as large as the sample will ever get — there
are only ~32 starting quarterbacks.

**3. And it is partly priced anyway.** Residual board value after
volume and age, against the completion term: **+0.194** on our board,
**+0.273** on KTC.

Multiply through — a spread of a few points, times a stability that
averages ~0.29 and swings between 0.43 and 0.16, minus the share the
market already holds — and the exploitable edge is on the order of **one
point per season**. Not worth an axis, and not worth the risk of
shipping a tilt fitted on 26 quarterbacks.

## Verdict

**Do not build a per-touch efficiency axis.** Not because efficiency is
noise — for receivers it is a genuine trait at r ≈ 0.56 — but because
the market residual test says it is **already in the price** at r ≈ 0.65
for WR and ≈ 0.50 for TE, and our board tracks KTC almost exactly there.
An axis would re-state information the board already carries, which is
the same reason the first-down axis was declined
(`docs/first-down-signal.md`).

What remains genuinely unpriced is small: the league-specific per-touch
terms are 2.9% of a QB's season and 0.2% of a WR's — and the QB half of
that, isolated below, neither replicates nor is fully unpriced.

**What is worth pursuing instead**, in order:

1. **Tight end.** Two independent probes now point there. Volume is
   least informative and efficiency most, and the market prices TE
   efficiency less completely than WR (0.508 vs 0.652). Blocked on
   sample — a fifth season roughly doubles the power.
2. **Not QB completion rate.** Measured and declined — see above. It
   does not replicate across season pairs, the sample cannot grow past
   ~32 quarterbacks, and the market already holds part of it.
3. **Nothing for RB and WR.** WR efficiency is stable but fully priced;
   RB efficiency is neither. Effort belongs on projecting opportunity.

## Caveat on the pricing test

The board is current and the efficiency is realized 2025, so the market
had every chance to see what it is being scored against. That is exactly
right for the question asked — *has the market absorbed this* — and
exactly wrong for a different one it must not be read as: it does **not**
show the market predicted 2025 efficiency in advance. Establishing that
needs board snapshots taken before a season — and **those are already
being kept**, in `data/rank_history.jsonl`, daily, with values, for three
years (`src/api/rank_history.py`). Re-running this residual test against
a pre-season snapshot rather than the live board is the version that
would answer the predictive question.

## Reproduce

The probes live in the session scratchpad rather than the repo, since
neither produced a shipped constant. Both are short: score every
player-week under the real card via `compute_weekly_points`, aggregate
to season totals, and either correlate across season pairs or
residualise the live board's values against volume and age. Re-run when
a new season lands — particularly for TE, where the whole question is
sample size.
