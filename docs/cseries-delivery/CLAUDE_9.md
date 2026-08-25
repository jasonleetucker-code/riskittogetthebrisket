# Claude 9 — C3 Trade Substrate + Historical Trade Replay: delivery ledger

Owner lane: C3 Trade Substrate, historical trade replay/grading, trade topology
substrate, KTC VA, trade-package substrate, trade-capacity integration,
as-of-safe trade history evaluation, plus directly-dependent C7 trade decision
products. Does not merge its own PRs — Claude 5 is sole Integration Authority.

## PR #962 — C3 substrate consolidation (5 units)

Status: `READY_FOR_INTEGRATION`, **frozen** as of the V1-97 assignment. Not
touched by any work recorded below unless Claude 5 requests a change or a
causal defect is demonstrated in it. Head: `08c89e1f3f023e7f90b1c2921e8de126e9752225`.
Units: KTC VA consolidation (`src/valuation_math/ktc_va_core.py`), trade-simulate
roster capacity wiring, doc repair (`C_SERIES_SCOPE_MANIFEST.md` /
`C_SERIES_EXECUTION_MAP.md`), package-generator `TradeConstraints` wiring.

## V1-97 / C3-REPLAY-01 — Public Activity Feed Hindsight-Leak Fix

Branch: `claude/v1-97-activity-hindsight-fix`, forked from `origin/main` @
`7c826f9c2c89591855a45f2c9cfcdcf7f6e2f5fd` — **not** stacked on #962.

### Phase 0/1 — surface resolution (before any code)

A prior session on this lane had found genuine ambiguity between two candidate
surfaces for V1-97 without resolving it. This session resolved it conclusively
via three parallel research traces plus direct reads of the relevant source:

- **Surface A — public `/league` Activity tab's trade-grade badge — is the
  confirmed, live defect.** `src/api/public_activity_valuation.py::build_valuation_from_contract`
  built one valuation callable from `latest_contract_data` (today's canonical
  board) with no date parameter anywhere. `src/public_league/activity.py::_apply_trade_grades`
  applied that one callable to every trade in the feed regardless of the
  trade's own `createdAt` (present on every trade record, already used for
  sorting, never used for valuation). Zero temporal-correctness test coverage
  existed on this path.
- **Surface B — private `/trades` "How It Aged" feature — is NOT the leak.**
  `frontend/lib/trade-retro-value.js` was re-verified line-for-line: all four
  documented anti-hindsight rules are genuinely enforced (never-future
  observation via `pointAt`, missing≠current substitution, picks never priced
  at today's number, incomplete totals refused rather than compared). The
  manifest's "divergent Hill form" complaint about this surface is also now
  factually false — `value-history.js::valueFromRank` and the backend's
  `rank_to_value` are mathematically identical, guarded by an existing parity
  test. Surface B's real remaining issue is sourcing from legacy
  `data/rank_history.jsonl` instead of the canonical `src.history` ledger — a
  genuine architecture-debt item (its own docstring says so), but not a
  hindsight-leak bug, and explicitly out of scope for this unit.

### Implementation

1. **`src/history/asof.py`** — new `batch_known_before(requests, ...)`: the
   batched, instant-strict sibling of `value_known_before`. Groups
   `(asset_key, instant)` requests by distinct key, fetches each key's
   candidates once, re-applies the same instant-strict selection
   (`_instant_at_or_before` / `_select_best`) per request in memory — a key
   repeated across N requests costs one SQL round trip, not N. Results are
   positionally aligned to input order (repeats preserved). Every instant is
   validated tz-aware before any connection opens.
2. **`src/api/public_activity_valuation.py`** — new `asset_history_key`
   (maps a public trade-side asset dict to its `src.history.keys` key —
   `player:<sleeperId>` / `name:<canonical>::<GROUP>` for players,
   `mpick:<year>:r<N>` generic grade for picks), `trade_instant_from_created_at`
   (Sleeper epoch-ms `createdAt` → tz-aware UTC instant; missing/zero/negative/
   non-numeric → `None`, never "now"), and `build_asof_valuation` (batches every
   `(asset, instant)` pair in a feed through one `asof.batch_known_before` call,
   returns a pure in-memory resolver; `None` means no admissible historical
   observation — never coerced to `0.0`). `build_valuation_from_contract` is
   left in place, unused by the live path.
3. **`src/public_league/activity.py`** — `build_section`'s `valuation` param
   became `valuation_factory` (a factory, since batching needs every
   `(asset, instant)` pair up front, only knowable after every trade is
   normalized). `_apply_trade_grades` resolves each side independently against
   the trade's own instant; a side with any unresolvable asset gets the new
   `_unavailable_grade` sentinel (`{grade: null, color: null, label:
   "Insufficient historical evidence", available: false, reason,
   missingAssets}`) instead of a grade computed from a partial total. One
   side's missing evidence never poisons a sibling side in the same trade.
   `public_contract.py::_build_activity_section` forwards the (now
   factory-shaped) `activity_valuation` kwarg under the renamed parameter.
4. **`server.py`** — `_build_public_activity_valuation()`'s body swapped from
   `build_valuation_from_contract(latest_contract_data)` to the ledger-backed
   factory; every one of its 5+ call sites passes the return value through
   opaquely (confirmed by direct read), so this is the ONLY server.py change —
   zero call-site edits. `None`-degrade gate moved from "contract missing" to
   "ledger file does not exist" (the same graceful-degradation contract, a
   more accurate signal for the new architecture). The old per-generation memo
   was removed — it cached an O(playersArray) contract parse that no longer
   happens; the factory does no work until called with a request list.
5. **`frontend/app/league/sections/activity.jsx`** — `TradeCard` branches on
   `side.grade?.available === false`, rendering a muted, titled chip instead
   of the letter/color badge (which would otherwise render a blank,
   uncolored grade for the new sentinel — a rendering bug, not an honest
   "unknown"). Only frontend file touched; `frontend/lib/activity-feed.js`'s
   separate `grades` projection already spreads `...s.grade` verbatim and is
   not currently rendered anywhere, so it needed no change.

### Known, flagged consequence — not a reason to withhold the fix

`src/history`'s pre-2026-07-14 floor is permanent by design (C1-U4). Any trade
before that date has zero possible ledger coverage, ever — so most historical
trades on the public activity feed will lose their grade badge entirely,
replaced by the honest "Insufficient historical evidence" state, rather than
continuing to show a wrong-but-present number. This is the correct fix — a
present-but-wrong number is worse than an honest absence — but it is a large,
visible behavior change to a live public page. Flagged here explicitly per the
assignment; Claude 5 / the product owner should see it before merge.

### Tests

- `tests/history/test_batch_known_before.py` (18 tests) — exact/nearest-prior/
  unavailable fidelity, never-future exhaustive property, instant-strict
  same-day exclusion, negative-UTC-offset correctness, naive-instant refusal,
  same-day tie determinism, positional-order preservation with repeated keys,
  one-fetch-per-distinct-key (mocked spy), summary aggregate, max-age budget.
- `tests/api/test_public_activity_asof_valuation.py` (23 tests) — `asset_history_key`,
  `trade_instant_from_created_at`, `build_asof_valuation` in isolation: T0/T1/T2
  selection, board-moves-after-the-trade invariance, only-future/no-observation
  degrade to `None`, missing/naive instants, pick generic-grade keys (valid +
  out-of-range), same-day tie, timezone boundary, and a case with NO live board
  data anywhere in the test — the strongest proof the resolver is genuinely
  decoupled from any current source.
- `tests/public_league/test_activity_asof_grading.py` (7 tests) — the wiring
  layer against a real temporal ledger: a normally-resolvable trade, the
  board-moved invariant at this layer, missing-evidence → honest unavailable
  side, unparseable `createdAt` → every side unavailable, a 3-team trade
  proving one side's missing evidence doesn't poison a sibling, and
  `valuation_factory` called exactly once per feed build with every trade's
  assets batched into one request list.
- `tests/public_league/test_public_contract.py` / `test_trade_grade_parity.py` —
  existing grading-math coverage (band table, VA engine, NaN sanitization,
  multi-team independence, the shared JS/Python parity fixture) updated to the
  new `(asset, instant) -> float | None` resolver shape via a small
  `_const_valuation_factory` test helper; zero grading-math assertions changed.
- `frontend/__tests__/components/TradeCard.test.jsx` (3 tests) — the
  unavailable-state render branch, mutation-proved against the pre-fix JSX.

RED-before/GREEN-after verified by checking out the pre-fix files from
`origin/main` and confirming import failures (the right kind of RED — the new
functions genuinely don't exist yet), then restoring and confirming GREEN.
Two hand-applied mutations confirmed caught: falling back to `datetime.now()`
on a bad/missing `createdAt` (caught by 7 subtests), and coercing a missing
historical value to `0.0` instead of `None` (caught by 4 tests, including the
board-moved and timezone-boundary tests).

### Status

`V1_97_STATUS: FEATURE_GREEN`. Full regression sweep and PR creation recorded
in this branch's PR description. **Not marked `VERIFIED` — Claude 5 owns that
promotion.**
