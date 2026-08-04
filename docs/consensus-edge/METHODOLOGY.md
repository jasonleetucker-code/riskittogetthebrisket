# Consensus Edge — methodology

**Status:** shadow / experimental as of 2026-08-04. The market-mispricing
component has an out-of-sample result; the composite does not exist yet
and will ship behind a flag defaulting OFF. Decisions and their reasoning
live in `DECISIONS.md` beside this file; this page is the short version.

## The problem

Six systems in this repo answer "is this player a buy?" — the Sharps
market signal, the `/edge` retail-vs-consensus rank gap, BDVM market
alpha, `frontend/lib/signal-engine.js`, `roster_intel/targets.py`, and a
never-wired `news/unified_signal_engine.py`. They measure different
things, disagree, and none had been checked against an outcome.

## Market Mispricing

The only component measured so far.

**Fair value** is the 21-source blend recomputed with the market anchor
removed, through the same `_compute_unified_rankings` the live board
uses — not a second ranker. Offense and IDP get separate boards because
they have different anchors and dropping both leaves no cross-market
scale; each row takes its value from the board that excluded its own
anchor, and the provenance is stamped per row.

Three ways the anchor leaked back in, all measured and closed:
correlated sources (`fantasyNavigatorSf` is KTC-derived — 440 rows), the
KTC-built rookie ladder (already guarded upstream, now pinned), and the
market-corridor clamp (101 IDP rows, mean shift 552). See ADR-002/3/4.

**Scoring** is `log(fair / market)`, then a robust z against a cohort of
position family × value tier. A raw point gap cannot be ranked across a
board — 500 points is noise on an elite QB and a doubling on a deep LB —
and the measured cohort sigmas confirm it: elite RB/WR/TE 0.035 against
high IDP 0.547, a 16× spread a single board-wide z would have flattened.
MAD rather than SD, because a handful of extreme gaps is what we are
hunting and they would inflate an SD enough to hide themselves.

Cohorts below 12 members fall back to position family alone, stamped as
`cohortLevel: "family"`. Without that, elite QBs (11 rows) scored nothing
on a superflex board.

Sign convention: **positive means underpriced**, i.e. a buy.

## Validation

Replay the board over committed git history (110 as-of dates,
2026-04-16 → 2026-08-03), score mispricing at an origin date, correlate
against cohort-excess market return over the following horizon.
Non-overlapping folds only.

| horizon | usable folds | mean rho | folds positive | beat market-value |
|---|---|---|---|---|
| 7d | 14 | +0.089 | 12/14 | 13/14 |
| 14d | 7 | +0.126 | 7/7 | 7/7 |
| 30d | 3 | +0.111 | 3/3 | 3/3 |

~680 players per fold. Beats the market-value benchmark in 23 of 24 folds
and a seeded random benchmark in 22 of 24.

Reproduce: `python scripts/run_consensus_edge_backtest.py --horizon-days 14`
(requires `git fetch --unshallow`; the script exits 2 on a shallow clone
rather than measuring a few days and calling it history). Raw
measurements are committed under `docs/measurements/`.

## What this does not establish

- **Market movement, not production.** The panel covers an offseason, so
  a realised-points target is unavailable rather than unmeasured. This
  signal predicts that a price will move — the right target for a trade,
  the wrong one for a start/sit call.
- **Today's model over past inputs.** Inputs cannot leak (every byte
  comes from a commit at or before the origin), but the pipeline is
  current. Valid for "would this have ranked players usefully?", not for
  "what did the site show that day?".
- **Modest effect.** rho ≈ 0.1 is a real edge, not a strong one.

## Components not yet validated

- **Sharp Flow** — the qualified-manager ledger lives in prod-only
  gitignored `data/intel/`, so it is unit-testable here and not
  empirically checkable. Known defects on `main` documented in the audit:
  no per-manager or per-league contribution cap, a percentile cohort
  recomputed live per request (so historical values are irreproducible),
  a dead `rosterQuality` term carrying 0.22 of the Sharp Score, and a
  quality-lookup key mismatch that silently gives cross-platform managers
  quality 1.0.
- **Opportunity/Risk** — no trusted forward-projection feed exists. Ships
  inert (contributing exactly 1.0) where unevidenced, mirroring
  `league_intel/adjustment.py`'s ABSENT tier.

Combining one measured component with two unmeasured ones and reporting a
single number would launder the unmeasured through the measured, so
components are reported separately.
