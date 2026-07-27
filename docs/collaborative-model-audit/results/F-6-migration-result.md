# F-6 migration — measured result

**Date:** 2026-07-27 · **Branch:** `claude/fantasy-football-audit-53l3g7`
**Payload:** `exports/latest/dynasty_data_2026-07-27.json`, held constant across both runs
**Artifacts:** `finder_before.json`, `finder_after.json` (this directory)
**Reproduce:** `python scripts/audit/finder_migration_snapshot.py --diff finder_before.json finder_after.json`

## What changed

`src/trade/finder.py` now values assets off `rankDerivedValue` — the canonical board
`/rankings` shows and every sibling engine reads — instead of `_finalAdjusted`, a
verbatim deep copy of the raw scraper composite.

Thresholds were **re-derived**, not ported. See below.

## Independent reproduction of PR #567's measurement

Recomputed from scratch on a fresh payload before touching any code:

| | PR #567 (2026-07-26) | this audit (2026-07-27) |
|---|---|---|
| paired assets | 803 | **803** |
| median board/composite ratio `k` | 0.880 | **0.875** (p10 0.775, p90 1.056) |
| assets clearing `MIN_ASSET_VALUE` with no board value | 194 | **189** at the old gate of 800 |

The small deltas are one day of market drift. The prior measurement reproduces.

## Threshold re-derivation

Porting the constants unchanged would have tightened every absolute gate by ~14%,
because the board sits below the composite (`k` = 0.875). Scaled by `k` and rounded:

| constant | was | now | why |
|---|---|---|---|
| `MIN_ASSET_VALUE` | 800 | **700** | board scale |
| `JUNK_THRESHOLD` | 400 | **350** | board scale |
| `ELITE_THRESHOLD` | 7500 | **6600** | board scale |
| `MAX_BOARD_LOSS` | −200 | **−175** | board scale |
| `MIN_MARKET_VALUE` | 500 | **500** | **unchanged** — gates retail market values, which this migration does not touch |

**Percentile-matching was tried first and rejected.** It is degenerate at the low end:
`MIN_ASSET_VALUE` = 800 sits at the 99.25th percentile of the paired pool and
`JUNK_THRESHOLD` = 400 at the 100th, so percentile equivalence maps both onto ~900 and
collapses two gates that exist to do different jobs. It also conflates the scale change
with a population change — the composite prices 1077 assets, the board 812.

## Measured effect — and a correction to F-6's own prediction

F-6 said: *"It moves every number `/api/trade/finder` emits."* Across all 12 teams:

| | before | after |
|---|---|---|
| total trades | 436 | 435 |
| median trades/team | 40 | 40 |
| asset pool size | 150 | 150 |
| median `boardDelta` | 1047 | 1030 (ratio 0.984) |
| median `arbitrageScore` | 21.65 | 21.28 |
| **top-1 recommendation changed** | — | **0 of 12 teams** |
| top-5 slots identical | — | 45 of 60 |

**The levels move a little; the ordering barely moves at all.** The prediction is
half right — values do change — but the implied blast radius did not materialise, and
the reason is structural rather than lucky:

1. The dominant score term is `board_gain_norm = board_delta / give_model`, a **ratio**.
   A near-uniform rescale of both numerator and denominator cancels.
2. `ρ = 0.9626` between the two value paths means the rescale *is* near-uniform.
3. The pool is capped at `MARKET_TOP_N_FILTER = 150` per market, and the two boards
   agree best among top assets — the disagreement lives in the tail, which never
   enters the pool.

So this is a **coherence fix, not a behaviour change**. That is a better outcome than
the doc feared, and it is worth stating plainly rather than letting the small diff imply
the migration was unnecessary: before the change, the engine's "our board says X"
referred to a board no user could see. It now refers to the one they can.

## The cost, surfaced rather than absorbed

**202 assets** carry a scraper value above the new `MIN_ASSET_VALUE` but no
`rankDerivedValue` at all, so they leave the finder's universe. (189 at the old gate of
800; the count rises because the gate moved down.)

They are **unpriced, not worthless** — assets the canonical board declines to rank. The
engine now reports them in `metadata.assetsUnpricedByBoard` and emits a warning, because
a silently shorter list reads as "nothing available" rather than "not priced".

`metadata.valueSource` stamps which scale produced a given run (`rankDerivedValue` or
`rawComposite`), so this can never again be ambiguous from the outside.

## What this does NOT establish

Both values descend from the same scrape, so agreement between them is not independent
corroboration that either is right. There is no ground truth for what a dynasty asset is
worth. The reason to prefer the post-migration numbers is that they are the numbers the
product shows — not that they are measurably more accurate.
