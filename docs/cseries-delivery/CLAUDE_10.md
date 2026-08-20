# Claude 10 — C-Series Delivery Log

**Lane:** C4 (Market / Sharp / FAAB) + dependency-ready waiver- and draft-related C7, per
`docs/EXECUTION_PLAN.md`'s POST-V1 C-Series mass-build campaign lane table: "Claude 10 — C4 +
waiver/draft C7 | C4 Market / Sharp / FAAB · waiver- and draft-related C7". Boundary with Claude 8
(source acquisition, cross-position bridge), Claude 9 (C3 trade substrate / historical replay),
Claude 5 (Sharp CI truthfulness, Integration): not touched here.

**Merge posture:** Claude 5 is the sole shipping-tree authority. Slices are marked
`READY_FOR_INTEGRATION`/`FEATURE_GREEN` and handed off; independent bounded PRs are opened rather
than stacking on unmerged work, per "Build broadly. Integrate narrowly."

**PRs from this lane:**

| PR | branch | scope | status at last check |
|---|---|---|---|
| #961 | `claude/cseries-market-waiver-draft-2njtem` | `C4-WAIV-01`, `C4-MTL-01`, `C4-MTL-03` + read endpoints | `FEATURE_GREEN` — CI success after Claude 5's own reconciliation merge; **frozen** |
| #975 | `claude/cseries-draft-snapshot-timer` | `C7-DRAFT-02` | `FEATURE_GREEN` — CI success; **frozen** |
| (this branch) | `claude/cseries-faab-heat-metrics` | `C4-FAAB-01` prerequisite (trending-velocity metrics) | below |

Both #961 and #975 are frozen per instruction — no further pushes unless Integration reports a
causal (non-`main`-churn) problem. This unit is built fresh off current `main`, not stacked on
either.

---

## Phase 0 re-measurement (this session)

Re-measured the C4/C7 dependency graph directly against `origin/main` rather than trusting stale
manifest labels. Two findings worth recording so they aren't rediscovered:

1. **`C7-WAIV-01` is not unblocked by #961.** Its three deps are `C2-DROP-01` (roster
   dropability — `COMPLETE` on `main`), `C4-FAAB-01` (mine, backtest-blocked), `C3-CON-01`
   (recommendation constraints — **`ABSENT, 0% implemented`**, owned by Claude 9's C3 lane). Even
   a fully validated `C4-FAAB-01` leaves this blocked on another lane's absent prerequisite.
2. **A tempting `#961`-dependent idea was explicitly deferred, not built.** Enriching
   `waiver_ledger`/`market_trade_ledger` rows with an at-the-time canonical value (via the
   already-built `src/acquisition/basis.py::basis_for_holding`, itself wrapping
   `src/history/asof.py::value_known_before`) is a clean, already-defined-methodology unit — but
   those two ledger modules don't exist on `main` yet, only in the unmerged `#961`. Building it now
   means either touching frozen `#961` code or duplicating its modules — both wrong. Queued as the
   natural first follow-up once `#961` merges.

## `C4-FAAB-01` prerequisite — FAAB Market Heat trending-velocity metrics

**Not the full feature.** `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` §11 requires real
backtest validation before any bounded Market Heat modifier reaches a live recommendation. This
unit builds the deterministic, policy-free *input* that validation needs and stops there — no
coefficient is chosen, and nothing here is imported by `src.trade.faab_engine` or any recommend
path (structurally pinned, see below).

**What was reused rather than rebuilt, found by reading before writing:**
- Trending-add counts are **already** being captured into a real time series —
  `src.retention.evidence_store.observe_trending_snapshot`/`trending_series`, wired from
  `server.py`'s post-scrape warm worker on every ~2h scrape cycle (`C1-RET-05`, closed
  2026-08-16). What I first assumed was a capture gap is not one; this unit is a *reader* of an
  existing series, not a second collector.
- `scripts/faab_backtest.py`'s established, owner-endorsed shape (biased-but-honest, every caveat
  stated up front, exit codes 0/1/2, `--json`) — the new script follows the same conventions.

**New code:**
- **`src/trade/faab_heat_metrics.py`** — `trending_velocity(player_id, as_of_ms, windows_hours=
  (6,12,24,48))` computes, per window, the change in trending-add count between the nearest
  observation at-or-before `as_of_ms` and the nearest at-or-before `as_of_ms - window`. No
  lookahead by construction (both anchors are explicitly at-or-before, mirroring
  `src.history.asof`'s never-future rule). A window with no qualifying past observation returns
  `None` with an explicit reason, never a fabricated zero baseline — and a genuine zero trending
  count is a real observation, kept distinct from "no observation at all." When only a
  farther-back observation is available it resolves via nearest-prior (consistent with this
  repo's own established precedent — `src.history.asof` and `src/retention`'s own explicit "no
  magic gap threshold" design) but is labelled `fidelity: "nearest-prior"` with the real anchor
  exposed, never silently presented as a true N-hour reading.
- **`scripts/faab_heat_backtest.py`** — joins this league's real historical waiver claims
  (`src.trade.faab_history.load_bid_history`) to `trending_velocity` at each claim's own instant,
  and reports **descriptive statistics only**: sample size per window and a simple Pearson
  correlation, gated at `status: "insufficient_sample"` below n=10 — never a coefficient, never a
  "validated" claim. Given real trending capture only started 2026-08-16 (4 days of history as of
  today), every league is expected to report `insufficient_sample` right now — the correct,
  honest output, mirroring `backtest_perfect_draft.py score()`'s own `SKIPPED`-for-no-data
  precedent.

**Temporal-integrity finding, defended against without expanding scope:** `faab_history.py`'s
existing (pre-existing, not mine) `fetch_bid_history` stores
`int(tx.get("status_updated") or tx.get("created") or 0)` — a live `or 0` coercion of an unknown
transaction time into epoch zero. Not fixed here (out of this unit's file scope; would need its
own `coercion_baseline.json` entry removal and belongs with a dedicated repair). Instead, the new
script's `_created_at_ms` treats any `createdAt <= 0` as unknown and excludes the claim
(`undatedClaimsExcluded`), so the fabricated zero from that pre-existing defect can never leak
into a velocity join as a real 1970 instant. Also normalizes the ambiguous seconds-vs-milliseconds
Sleeper timestamp (same heuristic `src/acquisition/events.py::_normalise_ms` already applies to
this identical field pair) since this script is that field's first real consumer.

**Non-influence, structurally pinned:** `tests/trade/test_faab_heat_metrics_non_influence.py`
AST-scans `faab_engine.py`, `faab_recommender.py`, `faab_contention.py` and `server.py` for any
import of `faab_heat_metrics` or the backtest script (none found — measured, not assumed), plus
the reverse direction (the metrics module doesn't import the engine either).

**Deliberately NOT built:** any change to `faab_engine.py`/`faab_recommender.py`/the live
`/api/waiver/faab-recommend` response; a fix to `faab_history.py`'s own `or 0` (flagged, out of
scope); any UI; any new capture job (reads what's already captured).

### Verification

```
python3 scripts/check_decision_coercions.py
python3 -m pytest tests/trade/test_faab_heat_metrics.py tests/trade/test_faab_heat_backtest.py \
  tests/trade/test_faab_heat_metrics_non_influence.py tests/retention/ tests/trade/ -q
```
→ coercion gate clean; 128 passed on the new tests + `tests/retention/`; 754 passed across the
full `tests/trade/` sweep, 0 failed, 0 regressions. `ruff check` + `ruff format` clean.

### Adversarial cases covered

`trending_velocity`: no observations at all; observations only after `as_of_ms` (must be
ignored — lookahead guard); a window with no qualifying past observation; a narrow window reusing
a far-back nearest-prior observation (labelled, not silently presented as exact); an observation
exactly at a window boundary; duplicate `observed_at` rows; a genuine zero trending count (kept
distinct from no observation); unknown/empty player id.

`build_report`/backtest script: empty bid history; a claim with `createdAt == 0` (excluded,
counted); a claim whose player has zero trending observations (excluded from the join, not
silently dropped without a trace — counted in `totalClaims` but contributes to no window); a
sample below the correlation threshold; a sample exactly crossing the threshold; a claim missing
`bidPct`.

### Next candidates (not started this branch)

Once `#961` merges: the at-the-time value enrichment for `waiver_ledger`/`market_trade_ledger`
rows (queued above). `C4-SHARP-01/02` stay `PRODUCTION_ACCESS_BLOCKED` (diagnosed by a prior
lane-4 session, owned by Claude 5/prod). `C7-WAIV-01` stays blocked on Claude 9's `C3-CON-01`.
`C4-MTL-02` stays `EXTERNAL_PERMISSION_BLOCKED` (`F-EXT-01`).
