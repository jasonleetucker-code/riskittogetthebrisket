# C6-SIG-01 / C6-SIG-02 — Central Buy/Sell Reconciler + market-ticker contract

**Status:** shipped, backend/data-only, additive. Owner: `src/signals/`.
**Depends on:** nothing new (reads `src/api/data_contract.py`,
`src/bdvm/market.py`, `src/sharp/market.py` read-only).
**Precedes:** `C7-ALERT-01` (Edge Alerts), the frontend migration of the
existing 16 emitters (owned by a separate lane), `C6-EDGE-01` (Consensus
Edge repair, which would fill the reserved `consensus_edge_composite`
slot).

This is the evidence base + design record for the unit, in the style of
`docs/lineup/C2_U1_CANONICAL_LINEUP.md` and `docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md`
(the census this unit's design was built from — read that first).

## What changed

* New package `src/signals/` (`reconciler.py`, `families.py`,
  `movement.py`) + `config/signals/reconciler_v1.json`.
* Additive `movementWindows` field on every `/api/data` row (7d/30d,
  ledger-sourced, gated by `signal_reconciler_movement_windows`).
* New `GET /api/signals/market-ticker` endpoint (gated by
  `signal_reconciler_market_ticker`).
* Deleted `src/news/unified_signal_engine.py` + its test — 352 lines,
  docstring claimed sole BUY/SELL/HOLD ownership, **zero production
  callers** (confirmed by import-graph grep before and after; see
  `docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md` §2).
* `src/consensus_edge/__init__.py`'s docstring, which named the dead
  module, updated to say it was deleted here rather than left stale.

## Correlation-family taxonomy (the "no double counting" decision)

Three families wired live in v1:

| family | source | independence |
|---|---|---|
| `board_consensus_gap` | `data_contract._compute_market_gap` (already-computed contract field, read only) | Self-referential decomposition of the board's own inputs against itself — real signal, declared correlated with anything else board-descended |
| `bdvm_fundamental` | `src.bdvm.market.buy_hold_sell` | Genuinely independent fundamental signal; shares a KTC/IDPTC **anchor** with `board_consensus_gap` sometimes — declared via `sharedAnchors` in provenance, never silently collapsed |
| `sharp_transaction` | `src.sharp.market.market_payload` (**read-only** — nothing here writes to `src/sharp/`) | Fully independent — real manager transaction behavior, no valuation math |
| `consensus_edge_composite` | *(reserved)* | Interface slot only, zero ingestion — CE stays flag-off (ADR-023's ship gate still says don't ship) |

`rankChange` / `movementWindows` is deliberately **not** an evidence
family — it's descriptive ticker content, not a vote, so a mover cannot
be double-counted as "two families agree" when both derive from the
same board.

`src/api/terminal.py::_evaluate_signal` (the terminal rule engine,
mirrored in the frontend by `signal-engine.js`) is **not** wired as an
input. Its `trend7`/`trend30`/volatility axis is board-descended (would
double-count against `board_consensus_gap`), while its
`alertCount`/`neg`/`pos` axis is genuinely independent (news/injury) —
decomposing that split is real follow-up work, not solved here.
`tests/signals/test_reconciler_red.py::test_reconciler_is_allowed_to_diverge_from_terminal_evaluate_signal`
pins that the two are ALLOWED to disagree, so a future contributor
doesn't "fix" the divergence by accident before that decomposition
actually lands.

## Vocabulary: reused, not reinvented

`src/analyst/stance.py` already **is** the owner-approved canonical
vocabulary (`docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` §4.16),
including the structural guarantee "STASH cannot merge into conviction
BUY". The reconciler imports `Stance` and `Direction` from there rather
than declaring a second, parallel enum for the same categories — this
was a mid-build correction: the first draft of `reconciler.py` defined
its own `Verdict`/`Direction` Literal types, and `src/analyst/__init__.py`'s
own docstring (which exists specifically to warn about
`unified_signal_engine.py` claiming a vocabulary and drifting from it)
made the duplication obvious on re-read. Fixed before merge, not after.

`Verdict` has **eleven** reachable-in-principle values: the nine
`Stance` members, plus two reconciler-only meta-states that are not
analyst stances at all — `CONFLICTED` and `WITHHELD` describe whether a
stance could be formed, not what it says. A third meta-state,
`INSUFFICIENT_EVIDENCE`, is deliberately **not** `Stance.NO_SIGNAL`:
that value's own docstring means "we looked and there is no call here"
(a confident negative), while zero firing families is closer to true
absence — nobody looked at all.

**Reachable in v1** (verified by `tests/signals/test_reconciler.py`):
`STRONG_BUY`, `BUY`, `STASH`, `HOLD`, `SELL`, `STRONG_SELL`,
`CONFLICTED`, `INSUFFICIENT_EVIDENCE`, `WITHHELD`.
**Reserved, unreachable in v1:** `Stance.CONDITIONAL_BUY` /
`CONDITIONAL_SELL` — need roster/price context that belongs to the
Trade Intelligence lane, not this reconciler.

**Open item, flagged for explicit owner sign-off rather than picked
silently:** `CONFLICTED` is not one of the owner's nine `Stance` values.
It was added because the alternative — silently averaging opposed
evidence into a false `HOLD` — is the named top-line anti-pattern
`src/consensus_edge/score.py`'s own docstring warns against, and
`consensus_edge` already treats `Conflicted` as first-class. Recommend
keeping it; it is not currently ratified in the §4.16 vocabulary.

**WITHHELD precedence, preserved even though CE isn't a live input
yet:** `reconcile_row`'s precedence puts a quarantined row's `WITHHELD`
verdict first, matching `consensus_edge.score.classify`'s own ordering
("a quarantined identity beats everything"). When CE is wired as a
family in a future unit, its own `WITHHELD` reason becomes an
*additional* trigger of this same branch — zero rewrite required.

## Open items (named, not resolved here)

1. **BDVM's `leagueKey` dependence.** BDVM's fundamental value is
   genuinely roster-count-derived (`src/bdvm/service.py`), and the
   ticker endpoint computes it once against the platform's
   registry-resolved DEFAULT league, publishing it as shared evidence —
   the same convention already used for the shared TEP anchor. Whether
   this materially differs across the platform's live leagues is
   **unmeasured**. Recommend: measure BDVM's `signal` output across both
   live leagues before treating this as settled.
2. **Magnitude calibration is a PRIOR, not a fit.** Every threshold in
   `config/signals/reconciler_v1.json` is derived by relationship to an
   existing, already-measured number (confidence.py's share ladder,
   BDVM's own ladder distinction) rather than fit against a live-board
   distribution of reconciler outputs — because no such distribution
   exists yet (this is the first thing to compute it). Revisit once the
   endpoint has run against production boards for a while.
3. **`terminal.py::_evaluate_signal` decomposition** — splitting its
   board-descended half from its news-independent half so the whole
   rule engine, not just a bounded subset, can be reconciled. Named in
   §"Correlation-family taxonomy" above.
4. **Notification-layer duplication** — `signal_alerts.py`,
   `bdvm_signal_alerts.py`, and `custom_alerts.py` remain three
   independent cooldown systems that can each alert on the same player
   the same day (`docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md` §3.4).
   Not touched here.
5. **`src/sharp/roster_percentage.py`** — same cohort as
   `market_payload`, deliberately not double-read as a second family in
   v1.

## Mutation verification performed (not a permanent test-suite fixture — a build-time check, recorded here)

Three branches in `src/signals/reconciler.py` and one in
`src/signals/movement.py` were manually mutated, confirmed RED against
the relevant test, then reverted (working tree confirmed clean via
`git diff` after each):

1. Bypassing the quarantine-first precedence check (`is_quarantined = quarantined` → `= False`) →
   `test_quarantined_row_never_downgrades_to_plain_verdict` failed (STRONG_BUY published instead of WITHHELD).
2. Widening the CONFLICTED condition from `and` to `or` →
   `test_conflict_requires_both_sides_above_material_floor` failed (a
   single sub-material dissenter manufactured a false CONFLICTED).
3. Replacing the zero-evidence branch's `INSUFFICIENT_EVIDENCE` with
   `Stance.HOLD` → `test_no_eligible_families_never_reports_neutral`
   failed (a fake neutral verdict published for a player nothing had an
   opinion on).
4. Removing `movement.py`'s early-unavailable-return guard →
   `test_gap_inside_window_is_unavailable_not_zero` failed on
   `asOfDate` (the guard's ONLY independently observable effect in the
   zero-observation case is which date gets echoed back — this was
   found by the first mutation attempt passing unexpectedly, which is
   recorded here rather than quietly strengthened without a trace: the
   original test only checked `fidelity`/`deltaRank`/`deltaValue`, all
   of which happen to come out identical via `value_as_of`'s own
   fallback path; `asOfDate` was the one field the guard is actually
   load-bearing for).
