# Claude 10 — C-Series Delivery Log

**Lane:** Market, Sharp, FAAB, Waiver & Draft Intelligence (C4 ownership + dependency-ready C7
waiver/draft consumers). Boundary with Claude 8 (new source acquisition, cross-position bridge
architecture, Dynasty Nerds / Dynasty Dealer / Draft Sharks bridge qualification, IDP Show /
Footballguys acquisition, source-family bridge semantics): not touched here.

**Branch:** `claude/cseries-market-waiver-draft-2njtem`

**Merge posture:** This lane does not merge its own work. Batches are marked
`READY_FOR_INTEGRATION` and handed to Claude 5 (Integration Authority / lane 5), per
`docs/EXECUTION_PLAN.md` §0.4a. This lane does not perform `main` reconciliation.

**Governing context read before starting:** `CLAUDE.md`, `docs/EXECUTION_PLAN.md` (current
authorization: the 2026-08-18 V1 Completion Sprint, six parallel lanes; lane 4 = Market/FAAB/
Analyst, whose continuation work beyond V1 is explicitly authorized to keep building —
"lane assignments deliberately extend past V1" — and is not V1-required), `docs/WORK_CLAIMS.md`,
`docs/C_SERIES_SCOPE_MANIFEST.md` §C4/§C7, `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1/§4.2
(confirms `C4-MTL-01/02/03`, `C4-FAAB-01`, `C4-WAIV-01` and `C7-WAIV-01` are lane-4/lane-2
POST-V1 continuation, not part of the V1 denominator), `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`,
`docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`.

**Sandbox constraint that shapes every unit below:** no live network egress and no production
access from this session. Units are chosen so verification is possible entirely from
deterministic tests over synthetic fixtures — no unit here claims a production-only artifact
(prod cohort counts, deployed timers firing, live-crawl coverage) as complete; where the manifest
marks something `PRODUCTION-PROOF`-gated (`C4-SHARP-01`, `C4-FAAB-02`, `C4-WAIV-01`'s live
population), that half stays explicitly open.

---

## Batch 1 — `READY_FOR_INTEGRATION`

**Units:** `C4-WAIV-01` (Waiver ledger), `C4-MTL-01` (Market Trade Ledger, own-league lane).

**Status:** implementation complete, deterministic tests green, `ruff` clean. Not yet reviewed
by Integration.

### What was built

Both units are pure **historical-projection** modules over the canonical acquisition ledger
(`src.acquisition`, C1-ACQ-01 / C1-U8, merged 2026-08-17) — never a second Sleeper collector, and
never a valuation input. C1-ACQ-01 already captures every asset movement (trades, waivers, free
agents, drafts) per league in `acquisition_events`; what was missing was a *ledger-shaped* read
layer over it for these two specific product concepts.

- **`src/trade/waiver_ledger.py`** (`C4-WAIV-01`) — `waiver_claims(league_key)` groups recorded
  `WAIVER`/`FREE_AGENT` transactions into one row per claim (added assets, dropped assets, FAAB
  bid, timestamp/fidelity, roster/owner), sorted oldest-first with undated claims leading (same
  convention as `acquisition.store.read_events`). `waiver_ledger_summary(league_key)` stamps
  counts only (total/waiver/FA claim counts, FAAB spent, zero-bid count, missing-bid count, date
  range) — never per-claim contents, mirroring `acquisition.store.coverage`'s privacy posture.

  **Why this doesn't duplicate two existing "waiver" surfaces:**
  `src.api.sleeper_overlay._build_waivers_block` is a live, on-demand, 365-day-window fetch for
  one `/api/data` display panel — ephemeral, keyed to display names, never persisted, and
  structurally incapable of answering "what happened ever." `src.trade.faab_history` fetches
  Sleeper directly and persists a narrower derived summary (bid amounts + zero-bid share only)
  for the FAAB market model's rival-bid distribution — a market-calibration question, not an
  asset-history one. This module answers a third question (the full per-claim history: who
  claimed whom, dropped whom, when, for how much) the way C1-ACQ-01's "one owner" rule requires:
  by projecting the ledger, not re-fetching Sleeper.

- **`src/trade/market_trade_ledger.py`** (`C4-MTL-01`, own-league lane only) — `market_trades
  (league_key)` groups recorded `TRADE`/`TRADE_AWAY` events into one row per transaction. Sides
  are represented as `teams: {rosterId: {received: [...], sent: [...]}}` rather than forced into
  an A/B pair, so a 3+-team trade is not flattened into a fictional two-party fiction (tested).
  Each row carries structured format metadata via the **existing** `TargetFormat.from_registry`
  reader (`src.trade.faab_comparability`) — no second scoring-card parser invented. `market_
  ledger_summary(league_key)` stamps counts (total/2-team/multi-team/undated, date range,
  source-family list).

  **Deliberately scoped to the own-league lane.** The spec's full vision (a broad cross-market
  ledger of *other* leagues' trades, for comps/liquidity/negotiation evidence) is `C4-MTL-02`
  (KTC trade-database ingestion) and is gated on `F-EXT-01` — a third-party permission grant this
  repository does not have captured. That lane is not attempted here. What ships instead is the
  same normalized-row *shape* the spec's §3 schema calls for, seeded from the one source lane
  already fully within reach and licensed by construction: our own leagues' own completed trades.
  When `C4-MTL-02` lands, its rows are meant to join this same shape. Cross-source dedup (spec
  §3's "unresolved-stays-unresolved") is correctly a non-problem with one source lane — the
  acquisition store's own primary key already makes re-ingestion idempotent — and is explicitly
  left unclaimed rather than half-built against a second source that doesn't exist yet to test
  against.

### Structural guard extended, not bypassed

`tests/acquisition/test_board_inertness.py::test_the_whole_src_tree_is_free_of_valuation_side_
consumers` asserts nothing outside `src/acquisition/` (plus scripts/) imports the acquisition
package, specifically to prevent private ownership history from ever becoming a canonical-value
input (the circularity the file's own docstring names). Both new modules are legitimate
exceptions — pure historical reads that never reach `rankDerivedValue` or any canonical value,
the same direction `src/history` already reads value history — so the guard was extended with
two **exact-path**, commented allowances rather than a blanket prefix relaxation, and a companion
assertion pins that neither allowed path is also on the canonical valuation-path list. A third
consumer still has to earn its own named line.

### Verification

```
python3 -m pytest tests/trade/test_waiver_ledger.py tests/trade/test_market_trade_ledger.py \
  tests/acquisition/ tests/trade/ -q
```
→ 855 passed, 0 failed (local, this session — `tests/acquisition/` 106 + `tests/trade/` incl. the
20 new tests). `ruff check` clean on every touched file. No existing test's assertions changed
except the one guard extension described above.

### Deliberately NOT claimed in this batch

- `C4-MTL-02` (external KTC trade-database ingestion) — permission-gated (`F-EXT-01`), not
  attempted.
- `C4-MTL-03` (comparable-trade matching) — depends on `C4-MTL-01`; next candidate once this
  batch integrates.
- `C4-FAAB-01` (FAAB Market Heat) — depends on `C4-MTL-01`; existing canonical FAAB owner
  (`src/trade/faab_engine.py`) is unmodified and un-extended this batch, per the no-new-FAAB-
  formula rule.
- Any *frontend* surfacing either ledger — `/api/*` read endpoints landed in Batch 3 below, but no
  `/waivers` or `/trades` UI panel consumes them yet. Both ship as canonical owner modules with
  tests only this pass — deliberately, so the read contract (field names, grouping rules, privacy
  posture) is settled and reviewed before a UI consumer locks against it.
- `C4-SHARP-01/02/03` (Sharp cohort/bootstrap/FFPC hardening) — real, in scope for this lane, not
  started this batch. `C4-SHARP-01` and part of `C4-SHARP-03`'s L2 measurement are
  production-proof-gated and cannot be closed from this sandbox regardless.
- `C4-SRC-01/02/03` (source-health) — the V1 sprint's lane table assigns general source-health
  semantics to lane 5 (Integration Authority); this lane's mandate carves out only source-health
  repairs *not* owned by Claude 8's acquisition project, which is a narrower claim than "all of
  C4-SRC-*". Not started; will pick up only the pieces that are clearly neither Claude 8's nor
  lane 5's if requested.
- `C7-WAIV-01` (Perfect Waivers) — explicitly deferred until `C4-FAAB-01` (one of its three
  listed deps) exists; premature to start against a dependency that isn't there.
- Any Claude-8-owned work (new source acquisition, cross-position bridge architecture, Dynasty
  Nerds / Dynasty Dealer / Draft Sharks bridge qualification, IDP Show / Footballguys
  acquisition, source-family bridge semantics).

### Mid-session correction: `C4-SHARP-*` is already diagnosed and blocked, not open work

Before starting a Sharp-hardening unit, found `docs/lane4/` — a prior lane-4 session's V1-sprint
working notes, already merged to `main` (2026-08-18, `e7e8c1893`). `docs/lane4/LANE4_V1_
RECONCILIATION.md` records that `V1-58`/`V1-59` (`C4-SHARP-01`/`C4-SHARP-02`) are **diagnosed and
BLOCKED on production access** — both need an authenticated admin session cookie for
`chaseupside.com`, held by the site owner, to observe the live `dynasty-sharp-discovery` →
`-records` → `-rosters` chain and the FFPC timeout/SQLite-lock behavior it referenced. The doc is
explicit that they are **not** to be closed with a synthetic cohort ("a manufactured population
would verify the manufacture") and assigns the blocker to Claude 5 (prod). `C4-SHARP-03` was
separately closed via #911 (merged 2026-08-19, already on `main`). So there was no undiscovered
Sharp-hardening gap left for this sandbox to fix — re-attempting it here would have duplicated a
diagnosis already on record. Recorded here rather than silently dropped, per this lane's mandate
to call out anything already blocked/covered.

## Batch 2 — in progress

**Unit:** `C4-MTL-03` (comparable-trade matching).

- **`src/trade/comparable_trades.py`** — `comparable_trades_for_asset(asset_id, target_league_key)`
  searches every OTHER active league's `market_trades()` (from Batch 1's `C4-MTL-01`) for trades
  touching the asset, classifies each against the target league's format via `TargetFormat`, and
  returns them newest-first. Implements 4 of the spec's 5 match tiers (`EXACT_NATIVE_COMPARABLE` /
  `NEAR_COMPARABLE` / `BROAD_MARKET_CONTEXT` / `UNSUPPORTED_UNVERIFIED`); the fifth
  (`NORMALIZED COMPARABLE`) is deliberately never emitted because it requires an actual
  cross-format value-conversion model that does not exist in this repository — fabricating that
  tier without the model would be exactly the false confidence the tier system exists to prevent.
  An unproven format dimension (e.g. TEP unknown on either side) fails closed to
  `UNSUPPORTED_UNVERIFIED` rather than defaulting to a weaker-but-assigned tier. 10 new tests: 6
  direct against the pure `_classify(target, source)` function (every tier, plus the "unknown ≠
  mismatch" invariant), 3 against the wiring (self-exclusion of the target league, asset
  filtering, newest-first sort with undated last), 1 empty-registry honesty check.

  Real limitation, stated rather than hidden: with only Batch 1's own-league population live, most
  real queries today will search at most 1-2 other leagues. The classification machinery is
  correct and complete against the spec regardless of population size, and grows automatically
  once `C4-MTL-02` exists.

### Verification (Batch 2)

```
python3 -m pytest tests/trade/test_comparable_trades.py tests/acquisition/ tests/trade/ -q
```
→ 865 passed. `ruff check` + `ruff format --check` clean.

## Batch 3 — read endpoints for the two Batch-1 ledgers

**Units:** minimal `GET` surfaces for `C4-WAIV-01` and `C4-MTL-01`, the follow-up Batch 1
explicitly deferred.

- **`GET /api/market/waivers`** and **`GET /api/market/trades`** — added to `server.py`
  immediately after the FAAB-recommend endpoint. Both follow `/api/draft/roster-context`'s
  established shape exactly: `_resolve_league_for_request` for league scoping (400
  `unknown_league`/`inactive_league`, 404 `no_leagues_configured`), no per-route auth check
  because — discovered while writing the first test, which came back 401 unauthenticated — auth
  on `/api/*` is enforced once, globally, by the `_private_api_gate` middleware rather than
  per-route; there is nothing for an individual private endpoint to add. Each returns
  `{leagueKey, summary, recent<Claims|Trades>, recent<...>Truncated}`, capped at
  `_MARKET_LEDGER_RECENT_LIMIT` (100) most-recent rows — a browsing endpoint, not an export, so an
  unbounded response was never on the table. Neither endpoint touches `latest_contract_data`;
  both read the acquisition ledger directly through Batch 1's modules.
- 8 new tests in `tests/api/test_market_ledger_endpoints.py`: default-league resolution, seeded
  data round-tripping through the real HTTP layer (not just the library functions Batch 1 already
  covers), unknown-league 400s, the recent-window truncation flag, and cross-league isolation at
  the HTTP boundary.

### Verification (Batch 3)

```
python3 -m pytest tests/api/test_market_ledger_endpoints.py tests/api/test_faab_recommend_endpoint.py \
  tests/api/test_league_registry.py tests/acquisition/ tests/trade/ -q
```
→ 922 passed, 0 failed. `ruff check` clean; `ruff format --diff` shows only one pre-existing,
unrelated hunk at `server.py:10535` (untouched by this diff, not introduced here).

## Batch 4 — decision-path coercion gate repair (real defect, caught by CI)

**Root cause, corrected.** Three consecutive pushes were reported here and on PR #961 as blocked
only by an unrelated, pre-existing `check_source_health.py` content-staleness warning. That
diagnosis was **wrong** — caught by Claude 5 (Integration) re-inspecting the actual per-step
`conclusion` values on the `Validate PR` job rather than trusting a tail-of-log read. The real
blocker was the **Decision-path coercion gate** (`scripts/check_decision_coercions.py`, no
`continue-on-error`), which correctly flagged three real defects:
`comparable_trades.py:151`, `market_trade_ledger.py:146` and `waiver_ledger.py:96` all used
`occurredAtMs or 0` as a sort-key fallback for a possibly-missing transaction timestamp — exactly
the "missing resolves to a fabricated number" anti-pattern the gate exists to block.
`check_source_health.py` *is* genuinely advisory (`continue-on-error: true` — its own non-zero
exit still prints loudly without failing the step), which is what made it look like the culprit in
a log tail; the mistake was not checking the per-step conclusion.

**Fix:** extracted `src/trade/ledger_sort.py` — two pure key functions
(`oldest_first_key`/`newest_first_key`) that partition rows into known/unknown-timestamp groups
via the leading tuple element, so a missing timestamp is only ever compared against another
missing timestamp (via `==`, never magnitude) and never substituted with a placeholder. Wired
into all three call sites (one-line change each). 8 new tests in `tests/trade/test_ledger_sort.py`
pin both invariants directly: the key's timestamp position is `None`, never `0`, for a missing
row; and the resulting sort order is byte-identical to the old (coercing) implementation for both
all-known and mixed known/unknown inputs. `python scripts/check_decision_coercions.py` went from
reporting the 3 new violations to clean. No published row field changed — `occurredAtMs` was
already correctly `None` in every output dict; the coercion only ever lived in the ephemeral
internal sort key.

Corrected on PR #961: the description and an earlier misattributing comment were both updated
with the real cause, crediting Claude 5's catch rather than silently rewriting the record.

### Verification (Batch 4)

```
python3 scripts/check_decision_coercions.py
python3 -m pytest tests/trade/ tests/api/ -q
```
→ coercion gate clean; full `tests/trade/` + `tests/api/` sweep green (see PR #961 for the exact
count at the verified commit).

### Next candidate batches (not started)

`C4-FAAB-01` (FAAB Market Heat) is next in strict dependency order, but is a materially different
kind of unit from Batches 1-2: it is an approved **extension of the live, 247-test-covered
canonical FAAB engine** (`src/trade/faab_engine.py`, read by `/api/faab/recommend` and the
waivers page for every league), not a new standalone module, and its own spec §11 requires
backtest validation (compare recommendations with/without the signal) that this sandbox cannot
produce without live Sleeper trending data and real bid outcomes. Attempting it here risks either
a half-validated change to a heavily-depended-on engine or an unverifiable claim of completeness —
worse than leaving it explicitly queued. Recommend it run with either live-data access or explicit
owner sign-off on a synthetic-backtest posture. A minimal read endpoint for the two Batch-1
ledgers remains a reasonable, fully-sandbox-buildable next unit. `C7-WAIV-01` (Perfect Waivers)
stays blocked on `C4-FAAB-01` plus two other-lane deps (`C2-DROP-01`, `C3-CON-01`), neither of
which exists yet.
