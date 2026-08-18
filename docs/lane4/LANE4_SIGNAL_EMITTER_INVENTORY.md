# Lane 4 — Buy/Sell/Stash emitter inventory

**Measured:** 2026-08-18, at `main` (`debf342`).
**Method:** import-graph grep across `src/`, `server.py`, `scripts/`; counts are
non-self modules referencing each emitter. Counts are a reachability signal,
not a call-frequency measure.
**Purpose:** the evidence base for a future Central Buy/Sell Reconciliation
unit. **No code changes were made from this document.** Reconciling these
needs an owner decision and touches the UI lane's surfaces.

---

## 1. The emitters

| module | emits | production consumers (non-self modules importing it) |
|---|---|---|
| `src/api/terminal.py` | terminal signal cards | 6 |
| `src/api/signal_alerts.py` | the daily alert sweep (BUY/SELL notifications) | 3 |
| `src/api/bdvm_signal_alerts.py` | BDVM STRONG_BUY…STRONG_SELL alerts | live — `server.py:12923`, inside the daily sweep |
| `src/consensus_edge/` | Consensus Edge verdicts incl. `WITHHELD` | 10 |
| `src/bdvm/market.py` | fundamental-vs-market gap signals | 3 |
| `src/intel/leads.py` | intel leads | 1 |
| `src/ros/tags.py` | ROS tags | 1 |
| `src/trade/suggestions.py` | sell-high / buy-low / consolidation trades | live |
| `src/trade/finder.py` | KTC arbitrage (board-vs-market) | live |
| `src/news/unified_signal_engine.py` | **claims to be the reconciler** | **0 — see §2** |

## 2. The reconciler that exists and is not wired

`src/news/unified_signal_engine.py` opens:

> "Unified signal engine — single entry point for every BUY/SELL/HOLD decision
> emitted to users."

It is imported by **nothing in production**. The only references anywhere are
its own test (`tests/news/test_unified_signal_engine.py`) and a prose mention
in `src/consensus_edge/__init__.py:7`. `src/api/feature_flags.py:91` carries a
comment recording that a flag *reported True for it* while nothing called it.

Consequence worth naming: `src/news/usage_signals.py` (snap/target/carry
z-scores) is consumed **only** by that dead engine, an audit script, and tests.
The usage-spike signal therefore does not reach any user surface today.

This is the audit's "six emitters, no reconciler" finding, located precisely: a
reconciler was written, tested, and never connected.

## 3. What a reconciliation unit has to decide (not decided here)

1. **Category vocabulary.** `STASH / SPECULATIVE BUY` is an owner-approved
   distinct category — deep waiver targets, end-of-bench, speculative dynasty
   bets. It must not inflate into a high-confidence acquisition target. No
   emitter above models it as a separate type today.
2. **Precedence.** Consensus Edge already returns `WITHHELD` ahead of every
   other branch for a quarantined row; a reconciler must not re-open a
   withheld verdict.
3. **Correlation.** Several emitters descend from the same board
   (`rankDerivedValue`) — value drift, Consensus Edge and the BDVM gap are not
   three independent votes. Same lineage problem as the FAAB market lane.
4. **Cooldown ownership.** `signal_alerts` and `bdvm_signal_alerts` keep
   *separate* `user_kv` namespaces deliberately (different label sets). A
   reconciler that merges them must not collapse that.

## 4. Recommended sequencing

Reconciliation should follow the Consensus Edge inventory (correlated-source
families, #804), because "how many independent opinions does this signal
represent" is the same question in both, and answering it twice would create
exactly the second owner the reconciler exists to remove.
