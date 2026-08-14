# League-aware valuation: evaluated for canonical promotion, rejected

**Decision: C — no trustworthy league-aware canonical method yet.**
**Date:** 2026-08-14 · **Branch:** `claude/canonical-value-uniformity` · **PR:** #822

This record exists so nobody re-derives it in six months. It is not a verdict on
league-aware valuation as a product goal — that goal stands. It is a verdict on
*this implementation* and on *today's evidence*.

## Why the question was asked

A report that player values differed between mobile and desktop. The cause was
architectural: `valuationMode` lived in `next_settings_v2` in **localStorage,
never server-synced**, and the lens it selected **overwrote `rankDerivedValue`
in place**. One account on two devices, two numbers for one player, under one
field name, with nothing in the payload naming which was which.

The owner's response was to ask the larger question: if league-aware valuation
can be proven better, it should *become* canonical and the toggle should go.

## Correction to the record

The figure **9,991 → 12,489** circulated during the investigation as the
league-adjusted value for Josh Allen. **It was never a production measurement.**
It came from applying the documented ±25% cap to 9,991 — a worst-case bound —
and a CI fixture then used `1.25` to reproduce that arithmetic. CI proved the
*mechanism* (canonical is overwritten; the result can leave the scale), not a
live value.

Measured from the captured live overlay (`evidence/W29/league-adjusted-overlay.json`,
709 rows, **7 distinct factors**):

| position | live factor | effect |
|---|---|---|
| DL | 1.097760 | +9.8% |
| RB | 1.041554 | +4.2% |
| WR | 1.026798 | +2.7% |
| **QB** | **1.018366** | **Josh Allen 9,991 → ~10,175** |
| TE | 1.011595 | +1.2% |
| TE (alt) | 0.979705 | −2.0% |

Finding **W07-F008** independently records Josh Allen at **10,171**. The ±25%
cap has never bound on live data. The defect was real; its magnitude was
overstated.

## What "My League" actually computes

```
top            = max rosValue among players CURRENTLY ROSTERED at that position
starter        = median over teams of each team's lowest-rosValue STARTED player
lineupScarcity = clamp01(1 - starter / top)
factor         = 1.0 + (lineupScarcity - 0.5) * 0.20
```

**Used:** starting-lineup slots — only as a *selector* deciding who counts as
started — SFLEX/FLEX endogenously, IDP starter slots, current roster occupancy,
the starter replacement tier. IDP *scoring* enters as a separate `scoringFit`
axis, not scarcity.

**Not used, despite the feature name:** team count (no arithmetic term), roster
size, TE premium (deliberately absent), offensive scoring, bench depth, taxi,
IR, projected scoring, age.

## Why it was rejected

1. **Current roster state, not durable structure.** `top` is the single
   highest-`rosValue` player rostered *today*. One trade, waiver claim or ROS
   re-rank moves the factor for every player at that position. League structure
   is durable; manager behaviour is not.
2. **The input is an ordinal index.** `rosValue` is a 0-100 *logarithmic rank*
   index — "not points, and not projection-aware" — yet it sets the multiplier
   on a 0-9999 dynasty board.
3. **`reference_lineup_scarcity = 0.5` is a bare constant**, never derived,
   never overridden, and it alone decides the *sign* of every adjustment.
4. **Per-position only.** 709 live rows carry 7 distinct factors; 5 of 8
   positions receive a pure scalar, which is untestable within position by
   construction (Spearman is invariant to monotone transforms).
5. **It leaves the canonical scale.** 9999 is the Hill *asymptote* —
   `V(p) = 9999 / (1 + (p/c)^s)` is mathematically bounded by it — so a
   multiplicative factor on a saturating percentile-transformed quantity is not
   a valid ratio operation. Values above 9999 are evidence the design is wrong,
   not that the ceiling should rise.
6. **No staleness detection** on the roster snapshot: an unchanged stale file is
   a perfect cache hit, served indefinitely as current league state.
7. **No double-count guard.** `tePremium` is ABSENT *by design* with a pinned
   invariant test, because the anchor is already KTC's TE++ board.
   `structuralScarcity` has no equivalent guard — while every offense-bearing
   source is already a Superflex board.

## Double-counting map

**All 18 offense-bearing sources are Superflex boards**, proven at the fetch
layer (SF URLs, `numQbs=2`, `?format=sf`, explicit 2QB columns). Zero 1QB boards
vote; 1QB columns are explicitly discarded. The board's basis is `tepp`
(`_BOARD_TE_BASIS`), anchored on `ktcSfTep`, with every non-TEP TE contribution
moved onto it by the single permitted mover `convert_te_value`.

So **the canonical value already prices Superflex and TE premium**. No SF
multiplier exists anywhere in the value path. `structuralScarcity` is the
unguarded path where such a double count *would* enter.

Note also: the canonical board is **not** "market-only". The TE-premium
multiplier is auto-derived from the league's own Sleeper `bonus_rec_te` and
applied value-level inside the blend. "Market vs My League" was never a clean
dichotomy.

## Why the evidence bar could not be met

| artifact | state |
|---|---|
| `board_history.sqlite` (production) | **exists and is healthy** — 8,749 rows, 8 days, 2026-08-06→08-13, timer enabled + active |
| the same file in a fresh clone | absent — `data/` is gitignored |
| `exports/archive/` (153 bundles) | carries the **legacy composite only** — no `rankDerivedValue` anywhere |
| league config recorded beside a value | **nothing, in any artifact** |

A dynasty-horizon backtest is not possible (no multi-season outcome definition,
no board history predating an observable season). A forward test is not possible
before ~Dec 2026. A league-aware comparison is hardest of the three: it needs
board history *and* league config together.

The existing `backtest_adjusted_board.py` is honest and well-caveated, but it
has no age term while dynasty value is multi-season, and it requests the overlay
for `dynasty_main` while measuring `scoringFit`/`receptionFit` and the
realized-points target against a Sleeper league ID **not in the registry** —
already filed as a High finding.

## What changed as a result

- The overlay no longer writes `rankDerivedValue` or its aliases. It emits
  `experimentalLeagueAdjustedValue` / `…Rank` / `…Tier`.
- `_valuation_scoped_contract` — the single place the lens reached an engine —
  no longer applies it. The request is *ignored*, not refused, so a stored
  `leagueAdjusted` converges silently.
- `readValuationMode()` always answers `market`, making persisted settings inert
  with no migration step.
- The Market / My league control is removed from `/rankings`.

## What would reopen this

Board history is accumulating now, and it already records the canonical value
and the methodology version. What it does **not** record is `league_key` or a
scoring fingerprint — a narrow, forward-only, additive schema change. With those
plus a season of elapsed outcomes, the A/B/C question becomes answerable on
evidence rather than on theory.
