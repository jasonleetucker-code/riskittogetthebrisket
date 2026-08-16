# C1-U4 — One Immutable As-Of Value/Provenance Ledger

**Status:** DELIVERED (this unit) — manifest rows `C1-HIST-01`, `C1-HIST-02`, `C1-HIST-03`
**Authorized:** 2026-08-16 at the C1-U3 owner checkpoint (`docs/EXECUTION_PLAN.md` §0/§2)
**Canonical owner:** `src/history/` — `keys.py`, `store.py`, `asof.py`, `record.py`, `backfill.py`, `migrate.py`, `provenance.py`
**Binding specs:** `docs/C_SERIES_SCOPE_MANIFEST.md` rows C1-HIST-01/02/03 ·
`docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md` §5/§6/§12 ·
`docs/TRADE_HISTORY_AGING_SPEC.md` §2.2/§4/§6/§7

This document is the design record the unit's checkpoint reviews: what exists, what it
means, what was measured, and what was deliberately not done.

---

## 1. The question this owner answers

> **What did we actually know / store / serve at or before time T?**

— and never the different question "what do we know today about the past." No code
path in `src/history` can select an observation dated after the requested time:
every SQL predicate is `<=`/`<` against the requested bound, and there is no API
accepting an undirected "nearest."

## 2. Pre-change census — the fragmented stores (complete)

Measured on `main` @ `46ec04a9` (census evidence: six-agent sweep, 2026-08-16; RED
reproductions in `tests/history/test_temporal_red.py`). **Five independent
historical/as-of decision owners existed**; the map's "4 fragmented stores" was
close (the fifth is the frontend aging helper, a consumer-side decision path):

| # | store / decision path | what it decided | measured defects | disposition |
|---|---|---|---|---|
| 1 | `data/rank_history.jsonl` (`src/api/rank_history.py`) | the only durable per-date canonical rank+value log | rank-GATED (all 72 current-year slot picks structurally excluded — RED-3); name-string keys, no platform id; same-date overwrite destroys evidence (RED-5); `load_history` mints values for rank-only entries from TODAY'S Hill constants, unflagged (RED-4); count-sliced windows | **RAW EVIDENCE + feed.** Recording continues (C1-RET-03 keys on it); contents migrated into the ledger (`migrate.migrate_rank_history` — recorded values only, reconstruction refused); its read paths are deferred consumers (§9) |
| 2 | `data/source_value_history.jsonl` (`src/api/source_history.py`) | per-source value series; its `blended` field doubled as a proxy canonical history | export-backfill overwrites live same-date entries (its own docstring contradicted); `blended` is a proxy quantity | **RAW EVIDENCE.** Per-source lane stays; its proxy-canonical read (terminal roster-at-date) is a deferred consumer (§9) |
| 3 | `data/snapshots/ranks_last.json` (`data_contract._stamp_rank_changes`) | the `rankChange` baseline | single-slot, unversioned, undated, bare-`canonicalName` keys; rewritten by every non-override build — server scrapes, startup priming, the two daily offline recorder scripts, and even a stock `/rankings` override body (W03-F010, P1); build N+1 diffed against build N's own output — 740 rows differed across two identical builds (B-audit residual H) — RED-1/RED-2 | **RETIRED.** Writer and reader deleted; the file is an orphan on prod (safe to remove; nothing reads it) |
| 4 | `data/board_history.sqlite` (`src/snapshots/board_store.py`, writer `scripts/snapshot_board.py`, daily 07:10 UTC timer) | records the canonical board incl. picks since ~2026-08-06; read surface deliberately `coverage()`-only | none in itself — the strongest existing substrate; but no read contract, so it answered nothing | **RAW EVIDENCE + feed.** Recording continues unchanged (C1-RET-02 keys on it); contents migrated in (`migrate.migrate_board_history`); charter posture in §10 |
| 5 | `frontend/lib/trade-retro-value.js` (the shipped "How It Aged" badge) | at-trade values per asset | selects the EARLIEST (future-of-trade) sample for pre-coverage trades; picks ALWAYS priced at current value; missing player history → current value; client Hill mirror recomputes historical values (W29-F004) | **DEFER → C3-U9** (`C3-REPLAY-01`/`C3-AGE-01` own this repair by manifest decomposition); defects already RED-listed in the aging spec §1/§12 |

Adjacent, confirmed NOT value-history owners (unchanged): `consensus_edge.sqlite`
(feature-scoped, its own versioned as-of store), `retention/evidence.sqlite`
(scoring cards — its `scoring_card_at` fidelity ladder is the in-repo precedent this
design follows), `league_events.sqlite` (raw transactions — the future join key for
trade replay), sharp roster spans, intel ledger, actuals, playerctx, ros, faab, bdvm.

Also retired in effect: `scripts/backfill_rank_history.py`'s approach (replaying
archives through TODAY'S `build_api_data_contract` and appending the result as
backdated history — the exact pattern replay spec §12 forbids). The script is left
in place as a historical artifact but the canonical backfill (`src/history/backfill.py`)
supersedes it and refuses that reconstruction; see §7. It was never wired to any
workflow and prod evidence (27 log lines vs 34 archive dates) indicates it never ran
on production.

## 3. Canonical record schema

`data/temporal_ledger.sqlite` (WAL), table `observations` — one row per
**observation**: a quantity claimed for one asset on one UTC date by one producer.

Identity (unique expression index; NULL instant coalesced so idempotence is real):
`(asset_key, lane, source_key, observed_date, COALESCE(observed_at,''), origin)`

Content: `value`, `rank`, `tier`, `confidence` (an observation carrying neither
value nor rank is rejected — it asserts nothing).

Identity evidence: `asset_class`, `display_name`, `position`, `player_id`.

Provenance: `origin`, `recorded_at`, `content_hash`, `pipeline_version`
(shape version + Hill-curve content hash — `src/history/provenance.py`, moved from
`board_store` which now delegates), `scope` (scoring fingerprint where known),
`observed_at`, `observed_at_zone`.

**Lanes** — an observation names WHICH quantity it is; the query layer never mixes
them:

* `canonical_board` — what the canonical pipeline served (`rankDerivedValue` /
  `canonicalConsensusRank` / tier / confidence). The only lane a canonical-value
  query reads.
* `source_value` — a vendor-published number (`ktc`, `ktcSfTep`, `idpTradeCalc`).
  Never a rank-signal synthetic encoding (`_canonicalSiteValues` is never read) —
  the same restriction, for the same reason, as `board_store._retail`.
* `scraper_blend` — the scraper's own composite (`_composite` / `_finalAdjusted`),
  a different named quantity retained as evidence, never served as canonical.

## 4. Asset-key namespace (players + picks, collision-free)

Three disjoint prefixes (`src/history/keys.py`):

* `player:<sleeperId>` — resolved platform identity (C1-U2 contract). Stable
  through team changes, display-name changes, position reclassification.
* `name:<canonical_player_key>` — explicit lower identity grade when no platform id
  exists that day (`resolve_canonical_name` + position group, the C1-U2
  collision-safe key). Writers count these; never silent.
* `mpick:<year>:r<N>[:s<slot>|:t<tier>]` — the C1-U3 market-pick reference,
  minted only by `src/identity/picks.parse_board_pick_name`. History NEVER keys a
  pick by display label. League picks (owned assets) are deliberately NOT a history
  namespace: sources price market refs; a consumer holding a league pick resolves it
  via `picks.market_resolution()` (pure function of state + clock) and queries the
  market ref — so ownership changes and the generic→exact slot transition never
  fork a series.

The bare-name collision class the retired cache allowed is unrepresentable
(RED-2 tombstone + `test_collision_keyed`). Measured on the real board: all 144
pick rows key uniquely; live contract recording resolves 0-unresolved; archive
backfill leaves 2,228 of 138k rows (~1.6%) at the explicit `name:`/`unknown`
grade (rows with neither `_sleeperId` nor a positions-map entry).

## 5. Timestamp semantics and timezone policy

* `observed_date` (UTC `YYYY-MM-DD`) — the producer's own date claim for the board
  day; the primary temporal key. Every feed is day-granular.
* `observed_at` — the scrape instant where known, recorded VERBATIM with
  `observed_at_zone`: `utc` for zone-qualified stamps, `naive` for the scraper's
  naive stamps (the recording hosts — CI runner, prod VPS — run UTC; the assumption
  is recorded, never silently normalized).
* `recorded_at` — ledger-write provenance; never a query key.
* Query inputs: dates, or timezone-AWARE datetimes (converted to UTC date); a naive
  datetime is refused (`ObservationError`), never guessed.

Two query modes, because "at or before date D" and "known before instant T" differ:

* `value_as_of(asset, date)` — day-granular; a same-date observation is `exact`.
* `value_known_before(asset, instant)` — instant-strict, for at-the-time analyses
  (C3-U9): only rows provably at-or-before the instant qualify (known
  `observed_at <= T`, or a strictly earlier UTC date). A same-day row with an
  unproven instant is EXCLUDED — conservatively missing, never optimistically
  contemporaneous.

## 6. As-of contract: fidelity, missing, ties, immutability

**Fidelity vocabulary** (the manifest's five labels, verbatim):

* `exact` — observation on the requested UTC date.
* `nearest-prior` — latest observation strictly before it, with `distanceDays`.
* `reconstructed` — **defined, never produced by this layer.** No approved
  reconstruction methodology exists; re-deriving old values through today's Hill
  constants is what aging spec §6 forbids. The label exists so a future
  owner-approved reconstruction has a name that is not `exact`.
* `partial` — multi-asset (batch) results with mixed coverage; never stamped on a
  single-asset result.
* `unavailable` — with a machine-readable reason: `before_history_boundary`
  (T < 2026-07-14, permanent), `no_prior_observation`, `outside_max_age`
  (caller-declared freshness budget exceeded; the nearest prior is still named).

**Missing is never zero, never today's value:** an unavailable result carries
`value: None` + the reason; nothing substitutes.

**Tie rule** (total order, replay-stable): latest `observed_date` → known instant
over unknown, latest first → origin priority (`live:server` >
`migration:board_history` > `migration:rank_history` > `backfill:archive`, unlisted
after, alphabetical) → `content_hash`.

**Immutability:** INSERT-only. Identical re-ingest = counted no-op (idempotent).
Same identity + different content = **surfaced conflict, never applied** — the
stored evidence stands (`test_conflicting_reingest_surfaced_never_applied`).
Corrections are explicit rows in `corrections` (reason mandatory; superseded row
retained, readable, skipped by selection). Reads never create the DB file.

**Permanent coverage boundary:** `HISTORY_FLOOR = 2026-07-14`, enforced at BOTH
ends — the write path rejects earlier-dated observations (a pre-boundary row could
only be fabricated) and the query layer answers earlier requests
`before_history_boundary` regardless of content. Gaps inside coverage are data:
`series()` returns observed dates only, no interpolation.

## 7. Backfill and migration (deterministic, idempotent)

`scripts/build_temporal_ledger.py` runs three ingest stages in fixed order:

1. **`exports/archive/` backfill** (`backfill.py`). The zips carry the RAW scraper
   payload only — W04-F009: 0 of 129 archives carry any canonical field — so the
   backfill records exactly what they prove: `source_value` (top-level `ktc` /
   `ktcSfTep` / `idpTradeCalc`, incl. all 126 pick rows per bundle) and
   `scraper_blend`. It deliberately does NOT replay payloads through today's
   pipeline; a canonical-value query for an archive-only date answers
   `unavailable`, which is the truth. One bundle per manifest-claimed date,
   same-day fallback newest-first.
   **Measured on this checkout:** 34/34 dates 2026-07-14→2026-08-16, 138,127
   observations (65,449 source_value + 72,678 scraper_blend; 15,582 pick rows),
   0 unresolved names, 0 conflicts, 9.6 s; rerun writes 0 with 138,127 counted
   duplicates.
2. **`board_history.sqlite` migration** — canonical rows incl. picks, with
   `player_id`, `contract_version` → `pipeline_version`, `scraped_at` →
   `observed_at`. Prod-only input (store absent in CI; stage skips with a reason).
3. **`rank_history.jsonl` migration** — recorded ranks always, recorded values
   only where a `values` block exists; **the read-time Hill reconstruction is
   refused by design** (RED-4's defect cannot enter the ledger). Names resolve to
   `player:` keys through the ledger's own id-bearing evidence
   (`(lower name, class) → player_id`; ambiguous → explicit `name:` grade,
   counted, never guessed) — which is why this stage runs last.

Production build = run the script once on the box (like
`fetch_league_scoring.py` on a cold deploy); the live recorder keeps it fresh
thereafter. All three stages are idempotent, so re-running after a partial failure
converges.

## 8. Live recording and rankChange (C1-HIST-02 / C1-HIST-03 GREEN)

* **Recording** (`record.py`, wired at the fresh-scrape promotion site in
  `server.py`, beside the existing appends, isolated try): one `canonical_board`
  observation per keyable row — **including the tethered slot picks the rank-gated
  log drops** (value present, rank NULL — first-class, closing C1-HIST-02) — plus
  `source_value` rows for the two value-direct retail anchors. Startup priming and
  override builds never record (same discipline as the existing appends). Measured
  on the real 2026-08-16 board: 2,224 observations, 0 unresolved, 280 empty
  (rows asserting neither value nor rank).
* **rankChange** (`data_contract._stamp_rank_changes`, rewritten): a DERIVED
  quantity — current rank minus the same asset's rank on the latest ledger date
  STRICTLY BEFORE the board's own date (`asof.previous_board_ranks`). Read-only on
  every build kind (override requests structurally cannot corrupt a baseline —
  closes W03-F010 as a side effect); rebuilds are idempotent; recording today's
  board cannot change today's comparator (strictly-before); no comparator → `None`,
  never 0; keys are the canonical namespace. Rollback
  `RISKIT_FEATURE_LEDGER_RANK_CHANGE=0` stamps `None` everywhere — a rollback must
  not resurrect the defect. Acceptance: back-to-back build determinism test
  (`TestRankChangeDeterministic`), replacing the measured 740-row divergence.
* **Semantics note for consumers** (news `rank_change` alerts, terminal movers,
  compact view, frontend arrows — all unchanged code): the stamp's horizon is now
  "since the previous BOARD DATE" instead of "since whatever process last rebuilt
  the contract." That is the repair, not a regression; `None` (no comparator) was
  already a handled state everywhere.

## 9. Consumers — migrated now vs deferred with record

**Migrated in this unit:** `data_contract._stamp_rank_changes` (the one consumer
whose repair IS a manifest row, C1-HIST-03).

**Deferred, recorded, with destination** (the manifest's own decomposition —
`C3-REPLAY-01`/`C3-AGE-01` name these repairs; C1-U4 is INFRA, no UI):

| consumer | current behavior | destination |
|---|---|---|
| `frontend/lib/trade-retro-value.js` | future-snapshot fallback, current-value picks/players, client Hill mirror | C3-U9 (at-the-time grades via `value_known_before` / `batch_as_of`) |
| `src/api/terminal.py` roster-at-date | correct ≤-selection but rank→value under today's curve for rank-only points | C3-U9 / C2-AGE-03 (re-point at ledger series) |
| `frontend/lib/value-history.js::computeTeamValueSeries` | ignores stamped `val`, reconverts ranks through the client curve mirror | C2-AGE-03 |
| `/api/movers`, `/api/data/rank-history`, sparkline stamps | pass through `load_history`'s unflagged reconstructed `val` points | follow-up: serve from ledger with per-point fidelity |
| CE `board_momentum_risk_axis` | fail-closed already; inherits reconstructed points | re-point when its feature wakes |

Until each migrates, its raw store keeps recording (retention rows require that),
but **no consumer may add a new interpretation of a raw history store** — new
historical reads go through `src/history`.

## 10. The board-store charter, resolved deliberately

`board_store`'s "no decision path may read this" is anti-circularity: a value fed
back into the live board would make the record a function of itself. That charter
is intact and still test-pinned — nothing in the live board path reads
`board_history.sqlite` or the ledger's canonical lane as an input to valuation.
What changed, deliberately: the temporal ledger is the canonical READ owner of
historical board records; `board_history.sqlite`'s contents reach consumers only
via the one-shot migration ingest into the ledger (an operator script reading the
file as raw evidence, not a live decision surface). `pipeline_version` moved to
`src/history/provenance.py` (pure contract labeller, no store read);
`board_store` delegates, keeping one implementation and the import pin untouched.

## 11. Durability / retention posture

The ledger is **deterministically rebuildable** from its feeds: git-tracked
archives + the nightly-backed-up `rank_history.jsonl.gz` and
`board_history.sqlite.gz` + ongoing recording (whose facts land in those backed-up
stores too). Loss of the ledger file is therefore recoverable by re-running
`build_temporal_ledger.py` — the deterministic build IS the restore path — so no
backup-topology change is required and none was made (C1-U1 stays closed; the only
provenance not reproduced by a rebuild is origin labels/instants on live rows,
which is cosmetic, not evidence). **Follow-up condition, recorded:** if a future
unit retires either legacy recorder, the ledger becomes primary evidence at that
moment and must join the backup set first.

Gitignored like all of `data/` (never force-added; contains no private data —
board values only).

## 12. Performance

Measured on this checkout (34 dates, 138k rows): full archive backfill 9.6 s
end-to-end; re-run (pure duplicate detection) similar; point as-of lookup and
`previous_board_ranks` are single-indexed queries (`idx_obs_asof`,
`idx_obs_date`) — the rankChange derivation adds one date-bounded query per
contract build (measured in the per-build noise; the build also LOST the
cache-file read/write). Nothing here runs per-request in a handler; the ledger's
consumers are build-time and offline (completion contract §8 satisfied).

## 13. RED → GREEN index

| RED (test_temporal_red.py) | defect | GREEN (test_temporal_ledger.py) |
|---|---|---|
| RED-1 (tombstone) | rankChange self-reference, 740-row build divergence | `TestRankChangeDeterministic::test_back_to_back_builds_identical`, `::test_recording_today_does_not_change_todays_comparator` |
| RED-2 (tombstone) | bare-name namespace collision | `::test_collision_keyed`; `TestPickHistoryFirstClass::test_namespaces_cannot_collide` |
| RED-3 (still passing — legacy store unchanged) | slot-pick values unrecoverable | `TestPickHistoryFirstClass::test_slot_pick_values_recorded_and_recoverable` |
| RED-4 (still passing) | today's-curve reconstruction indistinguishable from observation | `TestBackfillAndMigration::test_rank_history_migration_...` (reconstruction refused; rank-only days carry `value: None`) |
| RED-5 (still passing) | same-date rewrite destroys evidence | `TestReplayDeterminism::test_conflicting_reingest_surfaced_never_applied` |

Plus the C1-HIST-01 acceptance (`replay determinism test`):
`TestReplayDeterminism::test_same_inputs_same_ledger` and
`::test_answer_stable_after_later_builds`; never-future as an exhaustive property
(`TestAsOfFidelity::test_never_future_exhaustive`); valuation inertness as a full
double-build equality on a real archived payload (`TestValuationInertness`).

## 14. Downstream interfaces (substrate only — none of these features built)

* **C3-U9 replay / How It Aged:** `value_known_before` (instant-strict, never
  future, same-day-unproven excluded) + `batch_as_of` (per-asset fidelity + honest
  package coverage for the aging spec §5 gate) + market refs for picks via C1-U3
  `market_resolution`. Current Grade keeps reading the live board; At-the-Time
  reads the ledger; How It Aged is their difference under one methodology — the
  ledger supplies the time-scoped inputs, not the grading.
* **C5 backtesting:** leakage-safe by construction — a backtest queries
  `value_as_of(asset, prediction_date)`; evidence after the prediction timestamp is
  unselectable, and `reconstructed` (when it ever exists) is labelled, not laundered.
* **C9 history/storytelling:** `series()` with explicit `historyFloor` and
  preserved gaps — a chart gap is correct; a fabricated line is not.

## 15. What was deliberately NOT done

No valuation methodology change (double-build equality proves value/rank/tier
inertness). No trade grading, no UI, no projection work. `CANONICAL_V2` untouched;
C1-U3 not reopened; C1-U5/U6/U7/U8/U9 not started; IDP Guru remains out of scope.
`source_value_history`'s export-wins overwrite defect and
`exports/dynasty_export_latest.zip`'s zero-consumer status are recorded here as
unrelated follow-ups, not fixed. The `reconstructed` fidelity label is defined but
unproduced pending an owner-approved reconstruction methodology.
