# C6-SIG-01 — ONE Central Buy/Sell reconciler (backend half)

**Manifest row:** `C6-SIG-01` (`docs/C_SERIES_SCOPE_MANIFEST.md` §C6).
**Evidence base:** `docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md`.
**Status:** backend owner + private endpoint implemented; UI consumption is a
named follow-up (`C6-SIG-02` homepage ticker, `C7-ALERT-01` Edge Alerts).

## What it is

| piece | owner |
|---|---|
| synthesis (dedup, lineage, conflict, withheld, unobserved) | `src/signals/reconciler.py::reconcile` |
| emitter registry (domain, lineage group, ancestors, label translation) | `src/signals/reconciler.py::EMITTERS` |
| reading each emitter through its own owner | `src/signals/collect.py` |
| private endpoint | `GET /api/signals/reconciled` in `server.py` |

## The methodology boundary

The reconciler is **dedup and lineage only**. It publishes each emitter's
verdict side by side and never produces a number of its own:

* no numeric blend, average, vote count or cross-emitter weight — pinned
  structurally: `src/signals/reconciler.py` contains no arithmetic operator
  (`tests/signals/test_reconciler.py`);
* exact duplicates (same emitter, same label) and same-lineage restatements
  (same correlation group, same direction) collapse into the lineage root and
  are listed under `collapsed` with the reason;
* agreeing verdicts from different lineages are kept, with any shared ancestry
  published (`agreement.<dir>.sharedAncestry`, `independent: false`) so two
  descendants of one body of evidence never read as two independent opinions.
  Ancestry is the transitive closure over ONE declared lineage DAG
  (`reconciler.LINEAGE_PARENTS`), never a per-emitter list;
* a BUY and a SELL produce state `conflict` naming both sides — never averaged,
  never resolved (`resolution: not_resolved_by_reconciler`);
* a quarantined canonical row, or a Consensus Edge `Withheld` verdict, makes the
  player `withheld`; every other verdict stays listed underneath;
* an emitter that did not run is `unobserved` with its reason (flag off, status,
  exception, no team) — never neutral. A player outside what an emitter
  evaluated (off the selected roster for the terminal engine; past the Sharp
  board's 500-asset limit when it truncated) is `out_of_scope` for it; one the
  owner explicitly refused to price (BDVM `unpriced`) is `declined` with the
  owner's reason; only an emitter that evaluated the player and said nothing
  is `silent`.

## Lineage — what is and is not independent

`value_market_sources` is one correlation family: KTC Crowd, KTC Trades, KTC
Market (KTC's own Crowd+Trades, derived from the other two) and idpTradeCalc.

| emitter | lineage group | descends from (closure) |
|---|---|---|
| terminal signal | `canonical_board_history` | `canonical_board` → `value_market_sources`, `expert_rank_sources`; `news_feed` |
| BDVM market signal | `bdvm_fundamental_vs_market` | `bdvm_projections`, `value_market_sources` |
| Consensus Edge | `consensus_edge_composite` | `canonical_board` (→ …), `value_market_sources`, `sharp_cohort_movements`, `player_context` |
| Sharp market | `sharp_cohort_movements` | — |

So the terminal engine's value drift, Consensus Edge and the BDVM gap are
**not** independent votes (lane-4 inventory §3.3), and agreement between any
two of them is published with `independent: false`.

**BDVM's verdict is partly market-derived.** Its fundamentals take no market
input, but the gap that sets the BUY/SELL direction is fundamentals against the
value-signal market (`src/bdvm/market.py`), the same anchors Consensus Edge's
mispricing compares against (`src/consensus_edge/fair_value.py`
`MARKET_ANCHOR_BY_ASSET_CLASS`).

## Identity placement

Every emitter row is placed on the canonical asset key and carries its
`placement` basis: `player_id` first; `emitter_key` where the emitter's own key
IS the contract's exact `displayName` (Consensus Edge `playerKey`); then
`exact_name` / `canonical_name`, labelled `name_fallback:*` when an emitter key
was present but did not resolve. Rosters resolve by the team's `playerIds`
(`rosterPlacement: player_id`); display names are a labelled fallback for a
team without ids. Ambiguous / unresolved rows are listed, never guessed.

## Consumer rules that are NOT the reconciler's

C6-SIG-02's "BUY may be global; **SELL only for the selected team's roster**"
is a presentation rule and is the CONSUMER's job. The reconciler publishes
every verdict it observed for every player in scope, SELLs on other teams'
players included, and filters nothing by direction.

## Emitters

Collected: `terminal_signal`, `bdvm_market_signal`, `consensus_edge` (only while
its own `consensus_edge` flag is on), `sharp_market` (unlabelled — it publishes
no verdict). Declared restatements, not collected: `signal_alerts`,
`frontend_signal_engine`, `bdvm_signal_alerts`. Declared out of scope (not a
per-player verdict): `ros_tags`, `intel_leads`, `trade_suggestions`,
`trade_finder`.

## Retired

`src/news/unified_signal_engine.py` (self-described "single entry point for
every BUY/SELL/HOLD decision", zero production importers) and its only test
were deleted by this unit. `src/news/usage_signals.py` lost its only non-test,
non-audit consumer and stays flag-OFF and unwired; whether to wire or retire it
is a separate decision.

## Owner decisions this unit deliberately did not make

1. Whether a conflict should resolve to anything, and how.
2. How much (if at all) a lineage should count relative to another.
3. A `STASH / SPECULATIVE BUY` category (inventory §3.1) — no emitter models it.
4. Mapping the Sharp market's signed strength to Buy/Sell (a threshold choice).
5. Staleness budgets for the BDVM projection leg and the Sharp crawl — reported
   as `unknown`, never `fresh`.
