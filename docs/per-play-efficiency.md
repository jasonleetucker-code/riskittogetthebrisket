# Per-play efficiency: measured, and mostly not worth pricing

The proposal: value players partly on **points per play** rather than
only on season or per-game totals — the fantasy analogue of EPA/play.

The decomposition is sound and it's the same one the reception-band work
already validated:

```
season points  =  opportunities   x   points per opportunity
                  (volume)            (efficiency)
```

The question is which half is a **stable player trait**, because only a
stable half is worth carrying forward into a value. Measured under this
league's exact card — not generic PPR — over 2023–25, players with 50+
opportunities in both seasons of a pair.

## Volume is the stable half. Except at tight end.

Year-over-year correlation, mean of the 2023→24 and 2024→25 pairs:

| pos | volume r | efficiency r | efficiency ex-TD r | share of points spread (2025) |
|---|---|---|---|---|
| QB | 0.533 | 0.514 | **0.597** | 81% volume / 19% efficiency |
| RB | 0.552 | 0.318 | 0.297 | 88% / 12% |
| WR | 0.555 | 0.267 | 0.330 | 71% / 29% |
| TE | **0.276** | **0.492** | **0.535** | 58% / 42% |

Three things fall out.

**1. For RB and WR, volume wins twice.** It is roughly twice as stable
(0.55 against 0.27–0.32) *and* it accounts for 71–88% of the spread in
season points. This replicates the standard fantasy finding on this
league's card rather than assuming it. Any efficiency term must be a
tilt on top of volume, never a substitute for it.

**2. Tight end is the exception, and it is a real one.** TE volume is
the least stable of any position (0.276 — a tight end's target share
swings wildly year to year) while TE efficiency is the *second most*
stable (0.492), and efficiency accounts for 42% of the spread. So at TE,
"how good is he per target" carries more usable information than "how
many targets did he get."

That is the **second independent measurement pointing at TE**. The
adjusted-board backtest found TE was the only position where the
reception-band tilt improved ordering across every framing
(`docs/adjusted-board-backtest.md`). Two different probes, same
position. Not conclusive on its own — TE has the smallest sample of any
position here (n=20–21 per pair) — but it is the most promising open
lead in the valuation work.

**3. Touchdown regression is real but modest here.** Stripping every
`*_td` rule from the card and re-scoring improves efficiency stability
for QB (+0.083), WR (+0.063) and TE (+0.043) — but *not* RB (−0.021).
Goal-line work is stickier than the folklore suggests. Nowhere is TD
noise the main reason efficiency is unstable.

## The league-specific per-play terms are small

Efficiency only earns a valuation axis where the market board has not
already priced it. Market boards price yards per catch and touchdown
rate — analysts watch those. What they *cannot* see is this card's
per-attempt terms: `pass_cmp` +0.15, `pass_inc` −0.22, `rush_att` +0.08.

Scoring 2025 with and without those three keys:

| pos | mean contribution | as % of a season | spread across players |
|---|---|---|---|
| QB | +10.2 pts | 2.9% | −0.4% .. 5.5% |
| RB | +14.5 pts | 6.8% | 4.1% .. 9.3% |
| WR | +0.3 pts | 0.2% | −0.1% .. 0.9% |

And the per-opportunity contribution rate is a moderately stable trait
— QB r = +0.564 / +0.281, RB +0.545 / +0.551, WR +0.932 / +0.728 (the
WR figure is stable and irrelevant; it sits on a term worth 0.2% of a
season).

The QB term is genuine efficiency — a completion-percentage tax. 2025
extremes, over the whole season:

```
Drake Maye        +31.0 pts over 596 plays   (0.052/play)
Josh Allen        +25.8 pts over 572 plays   (0.045/play)
Mac Jones         +13.7 pts over 325 plays   (0.042/play)
Shedeur Sanders    -0.6 pts over 233 plays  (-0.003/play)
```

**RB's 6.8% is not efficiency at all.** `rush_att` pays 0.08 per carry
regardless of outcome, so it is a volume term wearing per-play clothes —
it says carries are worth slightly more here, which workload already
captures.

## Verdict

**Do not build a general per-play efficiency axis.** The split is
unfavourable in both directions at once: the part of efficiency that is
*large* (yards per catch, TD rate) is exactly what the market board
already prices, and the part that is *league-specific* is small — 2.9%
for a QB, 0.2% for a WR. RB's apparently-large 6.8% is volume.

An axis built on this would spend most of its movement re-stating
yardage the board already has, which is the same failure the first-down
axis was declined for (`docs/first-down-signal.md`).

**What is worth pursuing instead**, in order:

1. **Tight end efficiency.** Two independent measurements now point
   there — this one, and the reception-band tilt in the backtest. TE is
   the position where volume is least informative and efficiency most.
   The blocker is sample: n≈20 per season pair. A fifth season roughly
   doubles the power.
2. **QB completion-rate scoring, if anywhere.** The most stable
   efficiency measure found (ex-TD r = 0.597), genuinely invisible to a
   generic market board, and worth up to ~31 points a season. Small, but
   it is the one term that is both stable and unpriced.
3. **Nothing for RB and WR.** Volume is more stable and explains 71–88%
   of the outcome. Effort there belongs on projecting opportunity, not
   on rating efficiency.

## Reproduce

The probes live in the session scratchpad rather than the repo, because
neither produced a shipped constant. Both are short: score every
player-week under the real card via `compute_weekly_points`, aggregate
to season totals with `attempts + carries + targets` as opportunities,
and correlate across season pairs. Re-run after any new season lands —
particularly for TE, where the whole question is sample size.
