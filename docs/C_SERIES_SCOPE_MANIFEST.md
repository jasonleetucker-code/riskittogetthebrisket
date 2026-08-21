# C-Series Scope Manifest

**Status:** CANONICAL ACTIVE — the exhaustive implementation/disposition census for the C-Series
**Created:** 2026-08-14 by the post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`)
**Discharges:** `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §4 (Zero-Loss Scope Census)
**Companion:** `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` — the source-entry → manifest-row proof
**Authorization:** THIS FILE AUTHORIZES NOTHING. `docs/EXECUTION_PLAN.md` alone answers "what may I build now?"

---

# 1. How to read this file

This is a **census**, not a queue and not a permission slip. A row here means "this capability is real scope and
this is where it lands"; it does not mean the work may begin.

## 1.1 Why the row count is what it is

The reconciliation enumerated **≈926 raw requirement entries across twelve independent source families
(A–L)** at census time. Two further cohorts of the **E** family arrived while the reconciliation was being
written — **E2** (#838, ≈54 units) and **E3** (the six 2026-08-14 trade addenda #839–#843, ≈202 distinct
units) — bringing the combined population to **≈1,182**. E2 and E3 are subdivisions of E, not new families,
so the family count stays twelve; the counting convention is stated once in
`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §2 and enforced by `scripts/check_planning_integrity.py`.

After de-duplication the population collapses to **≈357 distinct capability identities** plus **≈425
constraint / methodology / validation units** that are binding but are not themselves capabilities (owner
decisions 1–65, the global invariants, the completion contract's definition-of-done, the performance
ceilings).

Neither audit's headline number survives contact with that census. One reported "154 source entries, 154 mapped,
0 unmapped"; the other reported eight at-risk clusters. **The second is closer, and both undercount the source
population by a factor of six** — because the first counted a *sample* of source entries rather than enumerating
them, and neither unioned `UNIMPLEMENTED_BACKLOG.md`, `docs/status/*`, or `docs/ROADMAP-competitor-parity.md`.

<!-- MANIFEST-ROW-COUNT: 163 -->
This manifest carries **163 rows** — 142 C-phase rows, 14 completed foundations and 7 explicit out-of-scope rows,
with 3 of them aggregates that enumerate their members inline (`C7-CE-01` names 16 CE surfaces; `C10-CLOSE-*`
and `C1-RET-*` are individually listed). Rows are at *capability* grain: where a source enumerates many small members
of one capability — the 104-ledger's calculator-workflow tier is the main case — the row **names its members
explicitly by source id** so nothing hides inside an aggregate.
`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` proves the mapping entry by entry.

## 1.2 Field definitions

Every row carries all of the fields the completion contract §4 requires. Nine of them are **cross-cutting and
identical across large groups of rows**, so they are defined once as **acceptance profiles** (§3) and referenced
by name, with per-row overrides where a row genuinely differs. A profile reference is the field, not a way of
omitting it. Writing "p95 ≤ 2 s, mobile parity required, WCAG AA, missing-is-never-zero, private, unit+integration
+E2E, deployed behind a flag, verified on production" into every row would make the manifest unreadable and
would not make it more true.

Per-row fields:

| field | meaning |
|---|---|
| `id` | stable manifest identifier. Never reused, never renumbered. |
| `capability` | the owner-facing outcome, in the owner's language |
| `owner` | the canonical owner — the module/service that owns this concept (§2) |
| `status` | current implementation truth, from the taxonomy in §1.3 |
| `final` | required final state |
| `disposition` | from the taxonomy in §1.4 |
| `deps` | hard dependencies — manifest ids that must complete first |
| `source` | provenance — where the requirement is written down |
| `prof` | acceptance profile (§3) |
| `phase` | C0–C10 |
| `lane` | parallel lane within the phase (§4 of `EXECUTION_PLAN.md`) |
| `flag` | blocker / owner-decision state; blank means neither |
| `evidence` | what proves it done |

`public/private`, `data dependencies`, `external dependencies`, `history/backfill`, `migration`, `performance`,
`mobile`, `accessibility`, `missing/degraded behavior`, `security/privacy`, `test`, `deployment` and
`production-proof` are carried by `prof` plus any row-level override in the `final` column.

## 1.3 Status taxonomy

| status | meaning |
|---|---|
| `COMPLETE` | complete for its declared current scope. May still require expansion in C — the `final` column says so. |
| `PARTIAL` | exists and works, but does not meet its required final state |
| `DISCONNECTED` | implemented and correct, but no production consumer reaches it |
| `DUPLICATED` | more than one implementation of one concept |
| `WRONG-OWNER` | a consumer reimplements a concept that has a canonical owner |
| `MIGRATION` | exists, but must move to a different owner or surface |
| `PERF-INCOMPLETE` | functionally correct, misses its performance budget |
| `PROOF-REQUIRED` | code-complete and deployed, but production behaviour is unverified |
| `ABSENT` | approved, zero implementation |

**A row may be `COMPLETE` and still carry C work.** That is not a contradiction and the two facts are recorded
separately, exactly as the mission requires.

## 1.4 Disposition taxonomy

`IMPLEMENT` · `REPAIR` · `CONSOLIDATE` · `MIGRATE` · `BACKFILL` · `UX/PERF` · `PRODUCTION-PROOF` ·
`COMPLETE-ALREADY` · `PART-OF-OTHER` · `SUPERSEDED` · `OWNER-REJECTED` · `EXTERNAL-BLOCKER` · `OWNER-DECISION` ·
`NOT-PRODUCT-SCOPE`

---

# 2. Canonical-owner map

The governing invariant, restated from `CLAUDE.md`: **one concept, one canonical owner; pages and features
consume canonical systems and never reimplement them.** This table is the current truth, measured. `HOLDS` means
the invariant is satisfied today.

| concept | canonical owner | state | manifest row |
|---|---|---|---|
| Player identity | `src/identity/resolution.py` + `src/identity/name_primitives.py` (**created 2026-08-16**, C1-U2) | ~~3 independent matchers~~ → one owner; both legacy ladders **deleted**, production gate green at both sites with zero divergence. `CANONICAL_V2` implemented but deliberately NOT served (`docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` §9) | `C1-ID-01` |
| Pick identity | `src/identity/picks.py` (**created 2026-08-16**, C1-U3) | ~~7 representations, no end-to-end id~~ → one owner. The census measured **39** deduplicated definition sites, not 7 (`docs/identity/C1_ID_02_CENSUS.md`); league-pick identity and market-pick refs are separate concepts, consumers adapted byte-inert (board 0/1093). Deferred with record: the intel-ledger re-key, the frontend lookup grammar (held in lockstep by a parity test) | `C1-ID-02` |
| Per-source pick boards | `src/picks/site_pick_map.py` (**created 2026-08-17**, C1-U6-D1) | One vendor's published pick rows → canonical keys. Reports EVIDENCE only: it does not blend, discount, or derive an unpublished year. Four paths that forced a value for a year no source published are deleted — the fabrication self-authenticated, making the approved derivation dormant. `Dynasty Scraper.py` is an ADAPTER. Guarded by `tests/picks/test_single_owner.py` | `C1-PICK-01` |
| League / scoring identity | `league_registry.leagues_share_scoring` via `scoring_fingerprint` | HOLDS (B6) | `F-SCORE-01` |
| Canonical player value | `data_contract._compute_unified_rankings` → `rankDerivedValue` | HOLDS (B9a) | `F-VAL-01` |
| Canonical pick value | same pipeline (derive → blend → tether → complete) + `pick_value_resolution` | HOLDS for 2026–2029, completeness census enforced at build | `C1-PICK-01` |
| Confidence | `src/api/confidence.py` | HOLDS (B11) | `F-CONF-01` |
| Source independence / provenance | `_RANKING_SOURCES` correlation groups | HOLDS (B10) — 21 keys → 13 families | `F-SRC-01` |
| Historical value / as-of evidence | `src/history/` immutable temporal ledger (**created 2026-08-16**, C1-U4) | ~~4 fragmented stores, 1 with no history at all~~ → one as-of owner; raw stores demoted to evidence feeds (`docs/history/C1_U4_TEMPORAL_LEDGER.md` §2) | `C1-HIST-01` |
| Lineup / slot assignment | `src/ros/lineup.py` | **CONSOLIDATED (C2-U1)** — re-measured at HEAD as **3** competing greedy fills, **all 3 in production** (not 6/2: the frontend's three call sites were already one, and BDVM's engine went live when its flag defaulted on). Plus **6** private slot-eligibility tables and **5** duplicate slot-demand derivations, four of the tables found by the structural guard rather than by the census | `C2-LINE-01` |
| Replacement level / PAR | *(to be consolidated)* | **5 implementations** | `C2-REPL-01` |
| Team Strength | `src/roster_intel/strength.py` (**CORRECTED 2026-08-20** — built by lane 1's `#914`; self-declared sole owner, consumed by `roster_intelligence.py`/`simulation.py`/`age_portfolio.py`. NOT `src/ros/team_strength.py`, which this row previously pointed to — that module is a legitimately distinct ROS 0-100 production composite, still validly imported elsewhere, not a competing Team Strength notion) | owner built — whether all "4 competing notions" have actually been retired in its favor was **not** independently re-audited when this row was corrected; do not read this as `COMPLETE` | `C2-STR-01` |
| Team Weakness / Need Priority | derived from Team Strength + league lineup rules | **≥5 need definitions** | `C2-WEAK-01` |
| Dropability / displacement | `src/draft/displacement.py` | HOLDS | `C2-DROP-01` |
| Roster simulation (exact before/after) | `src/roster_intel/simulation.py` (**CORRECTED 2026-08-20** — built by lane 1; its own docstring opens "Exact before → apply → re-solve → after roster simulation (C2-SIM-01)") | **built, and composed correctly by this lane's `src/trade/roster_capacity.py::simulate_final_legal_roster` (`C3-CAP-01`)**, proven by `tests/trade/test_trade_consumes_roster.py` (9-property structural proof). `team_impact.project_starters` no longer reimplements the lineup either (consumes `src.ros.lineup.assign_lineup` since C2-U1). `/api/trade/simulate` now surfaces the composition (this lane, 2026-08-20) | `C2-SIM-01` |
| Package generation | `src/packages/construction.py` (**CORRECTED 2026-08-20** — shared mechanics substrate: `PackageShape`, `topology_is_allowed`, `enumerate_packages`/`enumerate_sides`, `package_key`) | **3 of 4 generators already consume it** — `finder.py` and `angle.py` fully, `roster_intel/packages.py` only for identity (no capacity/constraint integration yet). `suggestions.py` is the one true holdout, hand-rolling small fixed 1v1/2v1 shapes with deep, already-tuned product logic that must not be silently changed | `C3-PKG-01` |
| Value Adjustment | `src/trade/ktc_va.py` (private-side) + `src/valuation_math/ktc_va_core.py` (shared stdlib-only algorithmic core, new) + `src/public_league/trade_grading.py` (public-side; structurally forced to stay a separate wrapper by the public/private import boundary — see that module's docstring) | **CONSOLIDATED (this lane, `C3-VA-01`, 2026-08-20)** — the import-time monkeypatch and the banker's-rounding divergence were already retired by an earlier, undocumented pass before this correction; the one remaining genuine duplicate (`trade_grading.py`'s standalone algorithm port) now wraps the shared core, guarded by a mutation-tested single-owner AST scan (`tests/valuation_math/test_single_owner.py`). JS side (`frontend/lib/trade-logic.js`) was already single-owner with dead V2/V12/V13 code removed | `C3-VA-01` |
| Whole-package market coverage | `src/league_intel/cross_market.py` | **CORRECTED 2026-08-20 — WIRED, not disconnected.** Consumed by `src/trade/angle.py`, `src/api/gameplan.py` and `src/roster_intel/packages.py`; guarded by an AST test (`tests/league_intel/test_cross_market.py`) that fails if `angle.py` ever sums per-asset market values again | `C3-XMKT-01` |
| Recommendation constraints | *(to be created)* one user+league constraint service | ABSENT | `C3-CON-01` |
| Trade decision synthesis | *(to be created)* Analyze Trade / Trade Desk contract | ABSENT | `C7-DESK-01` |
| FAAB | `src/trade/faab_engine.py` | HOLDS | `F-FAAB-01` |
| Waiver optimization | *(to be created)* one waiver service | ABSENT (greedy client slate today) | `C7-WAIV-01` |
| Acquisition history / cost basis | `src/acquisition/` (**created 2026-08-17**, C1-U8) | ~~ABSENT — zero fields, zero tables~~ → a private per-league event ledger with holding periods and cost basis (`value_known_before`, never `value_as_of`). Both capture gaps closed at the source. PRIVATE class; no route, no decision path reads it | `C1-ACQ-01` |
| Real market trades | *(to be created)* CE-01 canonical ledger | ABSENT | `C4-MTL-01` |
| Sharp cohort | `src/sharp/cohort.py` | HOLDS in code; production population unproven | `C4-SHARP-01` |
| Manager intelligence | `src/intel/*` substrate | HOLDS as substrate; Manager Scout absent | `C6-MGR-01` |
| Analyst intelligence | *(to be created)* claim/evidence ledger | ABSENT — no ingestion, no credentials | `C6-ANA-01` |
| Central Buy/Sell | *(to be created)* one reconciler | **≥6 emitters, no reconciler; one dead module claims ownership** | `C6-SIG-01` |
| Projections (ROS) | `src/ros/*` adapters | HOLDS | `F-ROS-01` |
| Realized scoring | `src/nfl_data/realized_points.py` | HOLDS (B7) | `F-SCORE-02` |
| Public / private classification | `frontend/lib/public-routes.js` + B8 exposure policy | HOLDS | `F-PRIV-01` |
| Share rendering | *(to be created)* CE-10 canonical renderer | 4 ad-hoc opengraph routes | `C9-SHARE-01` |
| Power rankings | *(to be consolidated)* | **2 engines** | `C5-POW-01` |
| Playoff probability | *(to be consolidated)* | **2 engines** | `C5-PLAY-01` |
| League mutations | *(to be created)* CE-11 Action Gateway | ABSENT; Sleeper integration is read-only | `C7-GATE-01` |

---

# 3. Acceptance profiles

Each profile fixes performance, mobile, accessibility, missing-data, security, test, deployment and
production-proof requirements for the rows that reference it. Numbers come from
`docs/GLOBAL_PERFORMANCE_STANDARD.md` and `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §8 — the union of the
two, which is the former plus the latter's ceiling.

**Universal, in every profile — these are not negotiable per row:**
missing / insufficient / stale / unavailable states are explicit and never rendered as zero; provenance and
freshness travel with every published number; a canonical value has exactly one owner; recommendation never
executes; the public/private boundary is enforced by the B8 exposure policy owner.

| profile | applies to | performance | mobile | a11y | security | tests | deployment | production proof |
|---|---|---|---|---|---|---|---|---|
| **P1 — interactive decision surface** | user-facing pages that drive a decision (`/trade`, `/rankings`, `/draft`, `/waivers`, Trade Desk, Best Trade) | warm ≤1 s · cold ≤3 s · p95 ≤2 s · **5 s is a failure ceiling, not a target** · local interaction <250 ms · ack <100 ms | full functional parity, not a narrowed subset | keyboard-complete, focus visible, screen-reader names on every control, WCAG AA contrast | private; league-scoped; no cross-league leakage | unit + integration + Playwright E2E | behind a feature flag with a named rollback env var | verified on production with real league data, in a real browser, on a phone |
| **P2 — backend engine / service** | canonical owners with no direct UI | request-path work bounded; no crawling, no unbounded combinatorics, no league-wide rebuild in a handler | n/a | n/a | league-scoped; auth enforced at the route | unit + integration + a parity harness vs the implementation it replaces | flagged; zero-diff harness before cutover | verified against a live contract build |
| **P3 — ingestion / retention job** | collectors, crawlers, snapshot writers | bounded per-source rate; async only | n/a | n/a | credentials from env, never committed; per-source authorization recorded | unit + a fixture-replay test | systemd timer or workflow, with a freshness watchdog | **artifact observed on production**, not merely "the timer is installed" |
| **P4 — public surface** | `/league` and anything anonymous | p95 ≤2 s; paginated or materialized, never a monolithic payload | full parity | WCAG AA | **public** — factual/retrospective only, per B8 | unit + integration + public E2E | standard | anonymous production fetch verified |
| **P5 — planning / governance** | documents and validators | n/a | n/a | n/a | n/a | `scripts/check_planning_integrity.py` | merged | owner approval recorded |
| **P6 — model / methodology** | anything that changes a published number | build-time budget stated and measured | n/a | n/a | n/a | backtest + calibration + pinned-input provenance | **champion/challenger; nothing self-promotes** | promotion is a human action with a recorded decision |

---

# 4. The manifest

> Legend for `flag`: `BLOCK-C` = blocks C1 authorization · `EXT` = external blocker · `OD-nn` = owner decision
> required (§6) · `RET` = irreversible-evidence-retention item, start early · blank = neither.

## C0 — Truth freeze, scope manifest, dependency graph

*Owner-facing outcome: a fresh session can determine what we are building, why, where each concept is owned, what
exists, what is next, and exactly when C implementation becomes authorized — without reconstructing months of
history.*

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C0-GOV-01` | One authorization record that matches merged reality | `docs/EXECUTION_PLAN.md` | PARTIAL — stale and self-contradictory | Post-B rewrite; B closed; C gate stated | REPAIR | — | audit both | P5 | gov | — | this PR |
| `C0-GOV-02` | One CE identifier namespace | `docs/CE_REGISTRY.md` | ABSENT — 2 contradictory registries | Single registry, CI-enforced | IMPLEMENT | — | D3 | P5 | gov | — | `check_planning_integrity.py` |
| `C0-GOV-03` | Zero-loss scope census | this file | ABSENT | Every source entry mapped; the declared row total agrees with the measured one | IMPLEMENT | — | contract §4 | P5 | gov | — | traceability doc + `check_planning_integrity.py` |
| `C0-GOV-04` | Source→manifest traceability proof | `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` | ABSENT | Every source entry resolves | IMPLEMENT | `C0-GOV-03` | contract §4 | P5 | gov | — | 0 unexplained unmapped |
| `C0-GOV-05` | One intake mechanism for new owner instructions | `docs/PLANNING_DOCUMENT_STATUS.md` | **INVERTED** — 65 binding decisions live in a doc the index calls superseded | The intake ledger is reclassified ACTIVE, with a defined reconciliation workflow | REPAIR | — | D7 | P5 | gov | — | this PR |
| `C0-GOV-06` | Governance index names every planning document | `docs/PLANNING_DOCUMENT_STATUS.md` | PARTIAL — 2 binding 08-14 specs unregistered; 3 findable roadmaps unnamed | Complete classification | REPAIR | — | D7 | P5 | gov | — | this PR |
| `C0-GOV-07` | Planning-integrity validation in CI | `scripts/check_planning_integrity.py` | ABSENT | Unique ids, unique CE, no unmapped, every OD has a state | IMPLEMENT | `C0-GOV-03` | mission §19 | P5 | gov | — | green CI |
| `C0-GOV-08` | Operating-doc status prose stops contradicting the plan | `CLAUDE.md`, `docs/ARCHITECTURE_HANDOFF.md`, `docs/WORK_CLAIMS.md`, `PRODUCT_PLAN.md` | PARTIAL — handoff pinned at B3 "Phase B is NOT started" | Consistent with merged reality | REPAIR | — | both audits | P5 | gov | — | this PR |
| `C0-GOV-09` | Durable owner intent promoted off unmerged branches | 25 promoted specs | ABSENT from `main` | On `main`, staleness corrected | MIGRATE | — | D5/D6 | P5 | gov | — | this PR |
| `C0-PERF-01` | Performance baselines captured before feature work | `docs/GLOBAL_PERFORMANCE_STANDARD.md` | ABSENT — budgets exist, baselines do not | p95 baselines for `/rankings`, `/trade`, `/league`, sharp pages, mobile | IMPLEMENT | — | #809 | P1 | perf | — | recorded measurements |
| `C0-PSI-01` | Premium design no-regret prep + token-direction conflict resolved | `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` | CONFLICT — live tokens drifted deeper into the terminal direction the north star supersedes | Reuse-vs-replace audit done; token direction decided | IMPLEMENT | — | #809 | P5 | psi | `OD-05` | audit recorded |

## C1 — Canonical asset, pick, history and provenance foundations

*Owner-facing outcome: every asset has one stable identity, every value has a date and a provenance, and the
evidence future features need is being retained from today rather than reconstructed never.*

**C1 contains the only work in the entire plan that gets harder every day it is deferred.** Rows flagged `RET`
are collecting evidence that cannot be recovered later at any price.

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C1-RET-01` | KTC crowd-FAAB rolling window is durably retained | `scripts/fetch_crowd_faab.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: recording on production (`ok`, 2 accumulator files, 1,128 deduped entries), restored and verified from backup (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Retained + backed up | REPAIR | — | audit 2 §19 | P3 | ret | `RET` | artifact on prod, in backup |
| `C1-RET-02` | Canonical board history is provably recording | `src/snapshots/board_store.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: proven recording on production (`ok`, 10,934 observations across 10 dates) and observable off-host via the read-only `Scoring Snapshot Diagnostics` workflow (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Observable + backed up | PRODUCTION-PROOF | — | audit 2 §19 | P3 | ret | `RET` | the read-only `Scoring Snapshot Diagnostics` workflow reports whether the recorder is scheduled — the only way to answer this from outside the prod host |
| `C1-RET-03` | `rank_history.jsonl` stall is detectable | `src/api/rank_history.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: watchdog `ok` (27 snapshots, missingDays=0, staleDays=1) (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Monitored + backed up | REPAIR | — | audit 2 §19 | P3 | ret | `RET` | watchdog alert |
| `C1-RET-04` | Scoring card at a date | `league_registry.write_scoring_snapshot` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: append-only history recorded before the overwrite (`ok`, 90 observations of 2 distinct cards across 2 leagues) (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Append-only history keyed by (league, observed_at) | IMPLEMENT | `C1-HIST-01` | audit 2 §19 | P3 | ret | `RET` | history rows exist |
| `C1-RET-05` | Sleeper trending adds are recorded | `src/adapters/sleeper_trending.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: persisted time series (`ok`, 4,500 observations across 45 snapshots) (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Persisted time series | IMPLEMENT | `C1-HIST-01` | audit 2 §19 | P3 | ret | `RET` | series exists |
| `C1-RET-06` | Own-league trade events are captured before the window drops them | `src/api/sleeper_overlay.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE: durable PRIVATE event ledger with a stable `transactionId` (`ok`, 288 transactions / 288 trades across 4 leagues). ~~**Waiver and free-agent transactions are fetched by `_build_waivers_block` and still recorded nowhere**~~ — CLOSED by C1-U8 (2026-08-17): both builders now flush through one shared `_flush_transaction_ledger`, ahead of the window cutoff and the `seen` dedupe, and `league_key`/`season` are supplied (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Durable event ledger with a stable key | IMPLEMENT | `C1-ACQ-01` | audit 2 §19 | P3 | ret | `RET` | ledger rows |
| `C1-RET-07` | Per-source raw ingest + identity reports resume | scraper / `scripts/identity_resolve.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — **STALE, honestly labelled and NOT weakened.** Collection has **not** resumed and the producer is not in the tree; the surface is honestly labelled and the strict `ALL` watchdog still exits **2** because of this stream (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Collection resumed or the surface honestly labelled | REPAIR | — | audit 2 §19 | P3 | ret | `RET` | fresh artifacts |
| `C1-RET-08` | `playerctx` history actually lands | `scripts/refresh_playerctx.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U1) — COMPLETE and **off-box**: 2 snapshots, both published to `origin/main` as `7730677eb` (merge `47d7d243`, deploy run 31869441040 SUCCESS; final watchdog run 31916149679)** | Snapshots landing | REPAIR | — | audit 2 §19 | P3 | ret | `RET` | committed snapshots |
| `C1-ID-01` | One player-identity owner | `src/identity/resolution.py` | **CLOSED 2026-08-16 (C1-U2, merge `b0c2f36`, deploy run 31921280237)** — canonical owner created; the scraper's run()-scope ladder and the contract's inline join cascade are **deleted** along with the cutover flag, so no fallback can override the owner. Staged dual-read → compare → cut over → retire; production gate passed at both sites with **zero divergence** (scraper 2,016/2,016 over a full refresh cycle; contract 24,024/24,024) and a before/after rebuild moved 0 of 1,092 board entries. `CANONICAL_V2` is implemented and measured but **deliberately not served** — it is not yet a strict improvement (first-name-variant class + no-position call sites); that is a separate authorized unit, and the gap is measured every cycle as `v2WouldChange`. Record `docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` | Scraper and data-contract matching become adapters | CONSOLIDATE | — | inventory 7.x | P2 | id | — | parity harness |
| `C1-ID-02` | One pick identity, end to end | `src/identity/picks.py` | **CLOSED at the owner checkpoint 2026-08-16** (PR #867 merge `22ce424f`) — canonical owner created; census measured 97 records / 39 deduplicated definition sites (not 7; see `docs/identity/C1_ID_02_CENSUS.md`); six RED classes reproduced on real data and closed; consumers adapted byte-inert (board 0/1093); `assetId` stamped on pickDetails; intel-ledger re-key deferred to `C1-ACQ-01/03` with the collision documented at the owner | One canonical pick id carrying ownership and lineage | IMPLEMENT | `C1-ID-01` | ledger 90/91, TC-20/21 | P2 | id | — | no collapse in the trade surface |
| `C1-PICK-01` | Every valid pick through 2029 has a finite canonical value | `_compute_unified_rankings` + `src/api/pick_value_resolution.py` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U6, PR #871 merge `ce8a8341a`, exact-head run 31965928453 SUCCESS; all eleven follow-ups disposed by `docs/ops/STABILIZATION_2026-08-16.md`)** — five RED classes reproduced on the live payload and closed (`tests/api/test_pick_completeness_red.py` → `test_pick_completeness.py`): the verbatim-clone×0.53 composition (audit V-12/C-11) replaced by the measured per-cell vendor year-step at injection (challenger table: 1.4-1.7% holdout MAPE vs the incumbent's 36.7-38.3%; classification stays PRIOR — the 2-out→3-out extrapolation is untestable today); future rounds 5-6 derived from the canonical rookie-ladder round step; rank-less GENERIC-grade rows per future year×round (uniform-tier EV); off-cap pick values stamped; `pickValueProvenance` on every pick row; build-census ERROR gate in `validate_api_data_contract`; the dormant second pricer in `src/canonical/calibration.py` deleted; draft-capital future seasons + simulator roster-pick labels resolve canonically. 162 pick rows, 100% of valid refs finite. Record `docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` | Automated census passes: value exists, finite, not zero-as-missing, identity stable, provenance stamped, and rankings == trade == API == export == ownership == mobile == desktop | IMPLEMENT | `C1-ID-02` | contract §10, T-NEW-15 | P6 | pick | — | census green |
| `C1-PICK-02` | Generic ↔ exact-slot transition without a second asset | `market_resolution` (C1-U3) + `pick_value_resolution` (C1-U6) | **CLOSED at the owner checkpoint 2026-08-16 (C1-U6, PR #871 merge `ce8a8341a`, exact-head run 31965928453 SUCCESS; all eleven follow-ups disposed by `docs/ops/STABILIZATION_2026-08-16.md`)** — one `LeaguePickIdentity` resolves finite at every basis (unknown-slot→generic, tier-from-slot, exact-slot) with the identity constant and no second asset minted; valuation echoes the ref verbatim (never fabricates slot/tier); transition test `tests/api/test_pick_completeness.py::TestGenericExactSlotTransition` | Same identity survives the transition | IMPLEMENT | `C1-ID-02` | TC-20/21/22 | P2 | pick | — | transition test |
| `C1-PICK-03` | Owned-pick outcome distribution, not a point estimate | `src/ros/pick_projection.py` | PARTIAL — point estimate from present strength / reverse standings | Calibrated distribution from real league order rules | IMPLEMENT | `C2-STR-01` | CE-02 | P6 | pick | — | calibration |
| `C1-HIST-01` | One immutable as-of value/provenance ledger | `src/history/` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U4, PR #869 merge `8b6a9987`)** — canonical owner created (`store`/`asof`/`keys`/`record`/`backfill`/`migrate`); five fragmented as-of decision paths measured (not 4; the fifth is `trade-retro-value.js`, deferred to C3-U9 per this manifest's own decomposition); five-label fidelity contract live (`reconstructed` defined, deliberately unproduced — no approved methodology); never-future structural; 2026-07-14 floor enforced at write AND query; archive backfill 34/34 dates, 138,127 observations, idempotent; replay-determinism + never-future property tests green; full record `docs/history/C1_U4_TEMPORAL_LEDGER.md` | One contract; fidelity labels `exact` / `nearest-prior` / `reconstructed` / `partial` / `unavailable` | IMPLEMENT | `C1-ID-01` | replay spec §6, aging spec | P2 | hist | — | replay determinism test |
| `C1-HIST-02` | Historical pick values are first-class | `src/history/` (was: structurally absent) | **CLOSED at the owner checkpoint 2026-08-16 (C1-U4, PR #869 merge `8b6a9987`)** — pick observations keyed by C1-U3 `mpick:*` identity; the 72 rank-less slot-pick rows (measured live) now record with value and NULL rank on every fresh scrape; archived vendor pick prices (126 pick entries per bundle) backfilled per date to 2026-07-14; RED pinned (`test_temporal_red.py::TestRed3`), GREEN proven on real data | Pick values recorded per date | IMPLEMENT | `C1-HIST-01`, `C1-ID-02` | aging spec | P2 | hist | — | rows exist |
| `C1-HIST-03` | Board-history `rankChange` is deterministic | `data_contract._stamp_rank_changes` | **CLOSED at the owner checkpoint 2026-08-16 (C1-U4, PR #869 merge `8b6a9987`)** — REPAIRED via the manifest's first offered shape (derived from the dated log): comparator is the ledger's latest board date strictly before the board's own date; read-only on every build (closes W03-F010 as a side effect); canonical-namespace keys (collision unrepresentable); no comparator → `None`, never 0; `ranks_last.json` writer+reader deleted; back-to-back determinism test green (was: 740-row divergence, B residual (a)) | Derived from the dated log, or written only on fresh-scrape promotion; collision-keyed | REPAIR | `C1-HIST-01` | B residual (a) | P2 | hist | — | back-to-back build determinism test |
| `C1-ACQ-01` | Acquisition history / cost basis | `src/acquisition/` | **DELIVERED — `CLOSED-PENDING-PROD` (C1-U8, 2026-08-17).** Was ABSENT: zero fields, zero tables. Now a private per-league event ledger with holding periods and cost basis (`value_known_before`, never `value_as_of`), plus the two capture gaps closed at the source — `_build_waivers_block` recorded nothing, and `record_transactions` was called with `league_key`/`season` unset. Evidence: `docs/acquisition/C1_U8_ACQUISITION_LEDGER.md`; production checklist §8 | Per-league transaction/event ledger with lineage | IMPLEMENT | `C1-ID-01`, `C1-HIST-01` | inventory 7.11, ledger 77–88 | P2 | hist | — | ledger rows |
| `C1-ACQ-02` | Historical roster reconstruction | `src/acquisition/roster.py` | **DELIVERED — `CLOSED-PENDING-PROD` (C1-U8, 2026-08-17).** `roster_at()` answers membership at an instant with `exact` / `partial` / `unavailable` fidelity in the same vocabulary `src/history/asof.py` uses. `unavailable` is distinct from an empty roster by construction. Library function, no route — the privacy boundary stays trivially true | Roster at a date, with fidelity labels | IMPLEMENT | `C1-ACQ-01` | replay spec §10 | P2 | hist | — | reconstruction test |
| `C1-ACQ-03` | Pick lineage / trade trees (CE-18) | `src/acquisition/holdings.py` | **DELIVERED — `CLOSED-PENDING-PROD` (C1-U8, 2026-08-17).** Full hop chain keyed on `LeaguePickIdentity.canonical_id`, so it survives transfer and slot realization. The intel-ledger re-key stays DEFERRED with its measurement (`asset_movements` = 0 rows on the measuring box, so safety is unprovable from it) | Full chain | IMPLEMENT | `C1-ID-02`, `C1-ACQ-01` | CE-18 | P2 | hist | — | chain test |
| `C1-CONF-01` | Confidence naming defects renamed before new consumers exist | `src/api/confidence.py` | **DELIVERED 2026-08-17 (C1-U5), CLOSED-PENDING-PROD** — all five RED classes reproduced on the live payload and closed (`tests/api/test_confidence_naming_red.py`, now inverted to a regression guard). `CONFIDENCE_LEVELS` still exactly four (bottleneck preserved, calibration policy §7); the orthogonal `confidenceBasis` closed set separates the four states `"none"` covered; `validate_api_data_contract` ERRORS on any priced row without a valid basis, so the hole is closed and not merely the rows that fell through it; `_anchor_current_year_picks_to_rookies` stamps its own verdict, scoped to rows nothing assessed so the 48 picks the dispersion rule judged keep theirs; `_compute_pick_confidence` moved to the owner and the circular import deleted; `identityResolutionConfidence`/`...Method` and `marketBreadthAgreementIndex` (+ the breadth and agreement halves the scraper discarded) dual-written behind a three-way-pinned `meta.deprecations` block. Board measured before/after: **0 values moved, 24 buckets none->low**, all 2026 round-5/6 slot picks. Record `docs/confidence/C1_U5_CONFIDENCE_NAMING.md` | Accurate names; aliases for existing consumers; **no methodology change** | REPAIR | — | B residuals (b)(c)(d) | P2 | id | — | rename test + consumer census |
| `C1-SRC-01` | Multi-format dynasty source archive | `src/source_archive/` | **DELIVERED — `CLOSED-PENDING-PROD` (C1-U9, 2026-08-17).** Append-only store for source-native format variants, keyed `(provider, endpoint, format_key, run_id, captured_date)` so one scrape cycle's variants are PAIRED evidence. KTC's four TEP states archive as ONE provider family — proven not to change the independent-family set. Archive eligibility and production eligibility are separate sets, enforced structurally: `data_contract` does not import the archive | Source-native 1QB/SF/TEP/IDP variants preserved; KTC's four calibration states counted as ONE opinion | IMPLEMENT | `C1-HIST-01` | #809 | P3 | src | — | archive + registry |
| `C1-SRC-02` | Game type proven per feed, fails closed on `UNKNOWN` | `_RANKING_SOURCES` | **CORRECTED then DELIVERED (C1-U9, 2026-08-17).** Previously recorded COMPLETE; verification found **no `game_type` field, no fail-closed path and no test** — the dynasty-only property held for the 21 registered sources only because each was hand-verified in a COMMENT, which a new entry could silently violate. Now a closed `GAME_TYPES` vocabulary, a per-source `game_type` + `game_type_evidence` on all 21, and `_validate_source_game_types_invariant` raising at IMPORT on absent/unknown/non-dynasty/unevidenced. Includes the spec §16-item-8 regression fixture (a trusted provider's REDRAFT endpoint is refused) | Explicit per-endpoint proof | COMPLETE-ALREADY | — | `CLAUDE.md` | P2 | src | — | existing tests |

## C2 — Canonical roster, lineup, replacement and impact foundations

*Owner-facing outcome: one answer to "how good is this roster, where is it weak, and what changes if I do X" —
the same answer on every surface.*

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C2-LINE-01` | One lineup/slot assignment | `src/ros/lineup.py` | **CLOSED-PENDING-PROD (C2-U1)** — measured at HEAD: **3** competing engines, all serving production (`starter-slots.js` on /terminal + /rosters, `team_impact.py` on `/api/trade/simulate`, `bdvm/roster.py` on `/api/bdvm/roster`); all retired. Owner verified against Sleeper's own awarded lineups **10/10** and repaired (missing-objective coercion; a WR/RB flex that accepted tight ends) | Every consumer calls the exact solver; the frontend renders a server-stamped lineup and computes none | CONSOLIDATE | — | `docs/lineup/C2_U1_CANONICAL_LINEUP.md` | P2 | roster | — | board + confidence inertness 0/1111; brute-force and host-truth parity |
| `C2-REPL-01` | One replacement level / PAR (CE-09) | *(consolidate)* | DUPLICATED — 5 implementations in 3 units | One service; domain views are consumers | CONSOLIDATE | `C2-LINE-01` | CE-09 | P2 | roster | — | parity |
| `C2-STR-01` | Canonical Team Strength | `src/roster_intel/strength.py` (**CORRECTED 2026-08-20** — owner cell previously named `src/ros/team_strength.py`, a legitimately distinct ROS 0-100 production composite, not this concept's owner; the real owner was built by lane 1's `#914`) | PARTIAL — owner exists and is self-declared sole (consumed by `roster_intelligence.py`/`simulation.py`/`age_portfolio.py`); whether the "4 competing notions" this row was opened on have all been retired in its favor was **not** independently re-audited in this correction, so the status is left `PARTIAL` rather than flipped to `COMPLETE` | One service; position-count thresholds and Top-N slots per spec; **must agree with the canonical lineup solve** | IMPLEMENT | `C2-LINE-01`, `C2-REPL-01` | inventory 1.1, MPP §4.1 | P2 | roster | — | cross-surface parity |
| `C2-WEAK-01` | Canonical Team Weakness / Need Priority | derived from `C2-STR-01` | DUPLICATED — ≥5 need definitions; `roster_intel`'s `urgentNeed` contradicts the lineup solve | Derived only from Team Strength + league lineup rules | IMPLEMENT | `C2-STR-01` | inventory 1.2 | P2 | roster | — | contradiction test |
| `C2-CORE-01` | Canonical Meaningful Roster Core (#839) | `C2-STR-01` | ABSENT — hard-coded QB3/RB3/WR5/TE3/DL5/LB5/DB5 selection and raw full-roster sums today | ONE site-wide roster-core selector for every whole-team dynasty value/strength claim, derived from league config: **`ceil(1.5 × real starter demand)` per position**, with **Superflex counted as real QB demand** (a 1QB + 1SF league has 2 QB-demand starters, so 3 meaningful QBs) and regular/IDP FLEX resolved as the highest-valued remaining eligible depth after dedicated position cores. No page-local top-N rules, no raw full-roster sums | IMPLEMENT | `C2-STR-01`, `C1-ID-01` | #839 (2026-08-14 addendum; promoted to `OWNER_FEATURE_INVENTORY` 1.7 + `OWNER_REQUESTED_TODO_SPEC_INDEX` T-NEW-19 — **not** intake decisions 47–49, which are #829's Weekly Report Studio decisions; see `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §6.1), ledger row 106. **AMENDED 2026-08-18 by owner addendum #899 (ordering):** FLEX is an ASSIGNMENT RULE, not a sortable Team Strength position. Actual starter assignment comes FIRST — dedicated slots, then each actual FLEX/SF/IDP-FLEX starter slot from the highest-valued remaining legally eligible players — and every actual starter is removed from the pools BEFORE reserve selection. Reserve demand is then `ceil(M × slots) − slots` per dedicated position, and `ceil(M × actual FLEX slots) − actual FLEX slots` for FLEX. `M` stays the 1.5× V1 champion/PRIOR with its §4.3 challenger pass — this changes WHEN a player leaves the pool, not the multiplier. Every player counts at most once; reuse the canonical exact assignment machinery (`src/ros/lineup.py`), never per-position greedy lists. No FLEX column required. See `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` | P2 | roster | — | one selector, every consumer; league-config derivation test; FLEX starters assigned before reserves; no player counted twice |
| `C2-SIM-01` | Exact before→apply→re-solve→after roster simulation | `src/roster_intel/simulation.py` (**CORRECTED 2026-08-20** — built by lane 1; its own docstring opens "Exact before → apply → re-solve → after roster simulation (C2-SIM-01)") | PARTIAL, not WRONG-OWNER — the primitive is built and composed correctly by `src/trade/roster_capacity.py::simulate_final_legal_roster` (`C3-CAP-01`), proven by `tests/trade/test_trade_consumes_roster.py` (9-property structural proof, P1-P9). `team_impact.project_starters` no longer reimplements the lineup (consumes `src.ros.lineup.assign_lineup` since C2-U1). `/api/trade/simulate` now surfaces the composition (this lane, 2026-08-20) | Promotions/displacements and need changes as separate roster information, never a value subtraction | IMPLEMENT | `C2-LINE-01`, `C2-STR-01` | owner decision 26 | P2 | roster | — | displacement test |
| `C2-DROP-01` | Dropability / cut candidates | `src/draft/displacement.py` | COMPLETE | Consumes the shared replacement owner | CONSOLIDATE | `C2-REPL-01` | inventory 1.4 | P2 | roster | — | parity |
| `C2-GP-01` | `roster_intel` / `/api/gameplan` reaches a user or is retired | `src/roster_intel/` | **DISCONNECTED** — substantial partner/package/need logic, zero frontend consumers | Adapted into the canonical substrate, or retired with its logic absorbed | MIGRATE | `C2-STR-01`, `C3-PKG-01` | W20-F001 | P1 | roster | — | reachable or removed |
| `C2-AGE-01` | Roster age-value portfolio | `C2-STR-01` | ABSENT | Value-Weighted Core Age over the canonical **meaningful** Team Strength group (a full-roster version is secondary context only, so low-value young bench players cannot make a roster look young); age-value distribution per player and per band; per-position-group profiles for QB/RB/WR/TE/DL-EDGE/LB/DB with league rank, percentile and difference from median. **Missing age stays missing; picks are excluded from age math, never treated as age zero.** Explicitly does NOT create a second age-adjusted valuation — canonical value already embeds age | IMPLEMENT | `C2-STR-01`, `C1-ID-01` | `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` (#838) | P2 | roster | — | league-relative parity + missing-age test |
| `C2-AGE-02` | Young Core Index | `C2-AGE-01` | ABSENT | A 0–100 **league-relative roster-construction index**, not a player-value model: youth normalized **per position** so QB and RB age expectations differ, weighted by canonical value within the meaningful core, then league-percentiled. Component breakdown exposed; **validated against real league examples before it is treated as canonical**. Plus overall and per-position "youngest valuable room" leaderboards | IMPLEMENT | `C2-AGE-01` | #838 addendum §5–6 | P6 | roster | — | validation against intuitive league examples |
| `C2-AGE-03` | Age/value history and trend views | `C1-HIST-01` | ABSENT | Roster-window movement over time; before/after a trade; Young Core Index trend. **Downstream of snapshot foundations and must not block the current-state feature** | IMPLEMENT | `C1-HIST-01`, `C2-AGE-01` | #838 addendum, future extension | P2 | hist | — | trend reconstruction |
| `C2-EXP-01` | Value-weighted NFL-team exposure before/after (CE-06) | `C2-SIM-01` | ABSENT | Descriptive only; must not influence trade grade | IMPLEMENT | `C2-SIM-01` | #786, decision 12 | P1 | roster | — | non-influence test |

## C3 — Canonical trade substrate

*Owner-facing outcome: one engine generates packages, one applies your rules, one grades them — and every trade
surface uses all three.*

**This is where the recommendation-constraint owner lives, and that placement is a deliberate divergence from the
completion contract's spine.** `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` requires
constraints applied *during candidate generation, before scoring* and consumed by eight named surfaces. A
constraint owner built alongside the decision products it constrains would arrive after several of its consumers.

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C3-PKG-01` | ONE shared package generator | `src/packages/construction.py` (**CORRECTED 2026-08-20** — a real shared mechanics substrate: `PackageShape`, `topology_is_allowed`, `enumerate_packages`/`enumerate_sides`, `package_key`) | PARTIAL, not the prior "4 independent generators" — `finder.py` and `angle.py` fully consume the substrate; `roster_intel/packages.py` (disconnected — no frontend caller) consumes only the identity helper, keeping a duplicate `_check_legality` and zero `constraints.py`/`roster_capacity.py` integration; `suggestions.py` (the live `/api/trade/suggestions` endpoint) is the one true holdout with hand-rolled fixed 1v1/2v1 shapes carrying deep, already-tuned product logic (including an in-code-flagged deferred owner decision) that must not be silently changed by a mechanical migration | One engine; every surface a consumer | CONSOLIDATE | `C2-SIM-01` | audit both | P2 | trade | — | zero-diff on finder + suggestions |
| `C3-VA-01` | ONE Value Adjustment per runtime, with parity proof | `src/trade/ktc_va.py` (private) + `src/valuation_math/ktc_va_core.py` (shared stdlib-only core, new) + `src/public_league/trade_grading.py` (public; structurally forced to stay a separate thin wrapper by the public/private import boundary) + `frontend/lib/trade-logic.js` | **COMPLETE (this lane, 2026-08-20)** — re-measured at HEAD rather than trusted: 2 of the "5 implementations" (the finder's import-time monkeypatch, a second Python port in `market_value_adjustment.py`) were already retired by an earlier, undocumented pass; the JS side was already single-owner with V2/V12/V13 dead code already removed. The one genuine survivor — a third standalone Python port in `trade_grading.py`, structurally forced by the public/private boundary — now wraps the extracted shared core instead of re-deriving the algorithm, closing the duplicate while respecting the boundary. Guarded by a mutation-tested single-owner AST scan (`tests/valuation_math/test_single_owner.py`) | One Python port, one JS port, parity-tested; monkeypatch deleted; dead V12/V13 exports removed | CONSOLIDATE | — | audit both, W30-F005 | P2 | trade | — | parity fixture ±0 |
| `C3-VA-02` | KTC VA stays an explicit, labelled market lens | `C3-VA-01` | COMPLETE | Never relabelled canonical value or roster impact; KTC's non-monotonic behaviour preserved in parity mode | COMPLETE-ALREADY | — | decisions 22/28/29/30/31 | P2 | trade | — | existing parity test |
| `C3-CON-01` | ONE recommendation-constraint owner | *(new)* user+league service | **ABSENT — 0% implemented, no mechanism of any kind** | Persistent untouchables; NFL-team outgoing protection; LOCK; EXCLUDE; applied during generation; fail-closed | IMPLEMENT | `C3-PKG-01` | #835 spec | P2 | trade | — | 8 consumers, 1 owner |
| `C3-CON-02` | Persistent personal protection (user + league scoped) | `C3-CON-01` | ABSENT | Individual untouchables + NFL-team protection; **outgoing only**; incoming still valid; dynamic current-team identity; **canonical values unchanged**; other users unaffected | IMPLEMENT | `C3-CON-01` | #835 §2–3, ledger 103 | P2 | trade | — | Jason+league MIN test |
| `C3-CON-03` | Generated-package LOCK / EXCLUDE refinement | `C3-CON-01` | ABSENT | Mutually exclusive per player; multiple allowed; immediate regeneration; persists until cleared; temporary ≠ permanent; persistent outranks temporary; parent hard rules never weaken | IMPLEMENT | `C3-CON-01` | #835 §5–6, ledger 104 | P1 | trade | — | 9 acceptance tests in the spec |
| `C3-XMKT-01` | Whole-package native market coverage | `src/league_intel/cross_market.py` | **COMPLETE — CORRECTED 2026-08-20.** Re-measured at HEAD rather than trusted: this row's "DISCONNECTED... `angle.py` not rewired" predates the actual wiring. `value_package`/`compare_packages` are consumed by `src/trade/angle.py`, `src/api/gameplan.py` and `src/roster_intel/packages.py`; guarded by an AST test (`tests/league_intel/test_cross_market.py`) that fails if `angle.py` ever sums per-asset market values again | Wired as the canonical owner; every package evaluated entirely within one market that covers every asset | CONSOLIDATE | `C3-PKG-01` | WS-J F-1 | P2 | trade | — | `angle.py` rewired |
| `C3-EQ-01` | Equalizers rank on the post-VA gap | `C3-PKG-01` | DUPLICATED + WRONG-OWNER — `findBalancers` exists twice with divergent rules (JS fires at 350 / returns 5 / one-sided band; Python at 256 / returns 2 / direction-aware); the JS copy is a frontend engine | One owner; post-VA gap; no double application | CONSOLIDATE | `C3-VA-01` | #800, decision 41 | P2 | trade | — | single owner, parity |
| `C3-CTX-01` | **Use Team Context** — one shared toggle, ON by default (#842) | *(new)* shared control | ABSENT | ON consumes the full team-aware stack (rosters/ownership, Team Strength/Weakness, Meaningful Roster Core, Age-Value/Young Core, Competitive Posture, playoff/bye/championship counterfactuals, season timing, pick ownership/forecast, needs and fit). OFF is **Asset-Only** and must not consume any team-specific evidence — but still uses canonical league-format-aware asset value, package/VA math, external evidence, intrinsic age, pick value, uncertainty, liquidity and hard user constraints. **League TEP/Superflex/IDP/scoring stays in canonical asset value: OFF removes team context, not league-format valuation.** Never silently switch ON to OFF when context is missing — mark the affected dimensions unavailable/degraded | IMPLEMENT | `C2-STR-01`, `C2-CORE-01` | #842, `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md` | P1 | trade | — | ON/OFF evidence-isolation test |
| `C3-CAP-01` | Roster capacity / forced-drop trade analysis (#843) | `C2-SIM-01` | ABSENT | With context ON, evaluate against the **final legal post-trade roster**, not the intermediate over-limit state: `before → apply → capacity/overage → required legal cleanup → apply optimal cleanup → rerun roster intelligence → evaluate`. Forced-drop cost uses canonical dropability and the true final roster marginal effect, **never `package delta − lowest raw player value`**. Picks do not consume an active spot. Clean fit imposes no forced-drop cost. When cleanup options are close, preserve the uncertainty rather than asserting one drop | IMPLEMENT | `C2-SIM-01`, `C2-DROP-01`, `C3-CTX-01` | #843 | P2 | trade | — | overage/cleanup arithmetic tests |
| `C3-TOPO-01` | Generated-trade topology constraint | `src/packages/construction.py::topology_is_allowed` + `enumerate_packages` (**CORRECTED 2026-08-20**) | PARTIAL, not ABSENT — split into two genuinely different claims that this row's single status was conflating. **The MECHANISM is built and rigorously tested**: `topology_is_allowed` implements `abs(players_A − players_B) <= 1` with picks excluded from the count exactly as specified, and `tests/packages/test_construction.py::test_the_manifest_topology_table_verbatim` pins the full 9-cell table from this row's own `final` column verbatim (1v1/2v1/1v2/3v2/2v3 allowed, 3v1/1v3/4v2/2v4 disallowed), plus a dedicated pair of tests proving the pick-exclusion rule both directions and `enumerate_packages`'s own enforcement + refusal reporting. This satisfies the row's "topology test" evidence column at the substrate level. **The PRODUCT capability does not** — no live generator's configured shape set currently reaches 3-a-side: `finder.py` is hard-capped at `PackageShape(1,1)`/`PackageShape(2,1)`/`PackageShape(1,2)` (verified by reading its shape list directly), and `angle.py`'s `enumerate_sides` fixes one side while the other's size is caller-driven (`target_sizes` derived from a caller-supplied `offer_size`/`desired_size`, not a hardcoded cap) — whether any real caller ever actually reaches a 3v2 shape through it was not audited here. So 3v2/2v3 packages are never *violated* (the mechanism would correctly reject an illegal shape if attempted), but they are also never *offered* by anything a user can reach today. Closing this row for real means wiring the already-tested mechanism's larger shapes into at least one live generator — a PRODUCT capability change to a live search space, not a verification-only unit | `abs(players_A − players_B) <= 1`; picks excluded from the count. 1v1, 2v1, 1v2, 3v2, 2v3 allowed; 3v1, 1v3, 4v2, 2v4 disallowed. **Supersedes the exact-equal-player-count rule** | IMPLEMENT | `C3-PKG-01` | #841/#842 supersession | P2 | trade | — | topology test |
| `C3-CALC-01` | Trade Calculator maturity | `frontend/app/trade/` | PARTIAL — 2–5 sides, KTC import, unpriced honesty all work; Analyze Trade, real-trade evidence, comparable trades, historical fidelity absent | TC-01…TC-30 end-state gate | IMPLEMENT | `C3-PKG-01`, `C4-MTL-01` | `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` | P1 | trade | — | TC-30 acceptance gate |
| `C3-CALC-02` | Manual override UX: visually silent, one global reset | `frontend/app/trade/` | ABSENT | No per-player badge; top-level Reset Values; removal clears the override; canonical truth unchanged | IMPLEMENT | — | #781, decisions 3–7 | P1 | trade | — | UX test |
| `C3-CALC-03` | Second Opinions one-glance tally | `src/api/second_opinions` | PARTIAL — basis contract done (B, #828); aggregate tally UI absent | "Side A 5 · Side B 3 · Even 1 · 2 incomplete"; imputation is never an independent vote | IMPLEMENT | — | #791, decision 23 | P1 | trade | — | tally test |
| `C3-MC-01` | Monte Carlo revalidation | `src/trade/monte_carlo.py` | PARTIAL — synthetic ±15% bands; correlation matrix disconnected; 2-team only, silently | Revalidated per the 10-item list; win % is not presented as a real-life probability | REPAIR | `C3-VA-01` | #790, decision 21 | P6 | trade | — | revalidation closed |
| `C3-REPLAY-01` | Historical Trade Replay / As-Of | `C1-HIST-01` | **WRONG SEMANTICS IN PRODUCTION** — current values for missing history, earliest-known for pre-coverage trades, current pick values; a divergent Hill form back-derives old values | Three separate lenses; strict no-future-information; fidelity labels | IMPLEMENT | `C1-HIST-01`, `C1-ACQ-02` | `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md`, ledger 101 | P1 | trade | — | no-hindsight test |
| `C3-AGE-01` | Trade History "How It Aged" | `C3-REPLAY-01` | PARTIAL — interim methodology (fixed ±200, current-value fallbacks) | Same trade methodology on both timestamps; ±200 replaced with evidence | REPAIR | `C1-HIST-02` | `docs/TRADE_HISTORY_AGING_SPEC.md` | P1 | trade | — | aging test |

## C4 — Market, transaction, manager, Sharp and waiver evidence ledgers

*Owner-facing outcome: what the wider market actually did, recorded once, with provenance — and provably running
in production rather than merely deployed.*

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C4-MTL-01` | Market Trade Ledger / Trade Database (CE-01) | *(new)* | ABSENT | Normalized multi-lane ledger; format metadata; cross-source dedup with unresolved-stays-unresolved | IMPLEMENT | `C1-ID-01`, `C1-ACQ-01` | `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` | P2 | mkt | — | ledger + dedup test |
| `C4-MTL-02` | KTC Trade Database ingestion lane | `C4-MTL-01` | ABSENT — **FUTURE, NOT PRODUCTION.** The broken producer was retired 2026-08-18 (zero consumers: the trade list reached only `len()` for a status count). Live shape measured that day so C4-U3 need not rediscover it: inline `var trades` on `/dynasty/trade-database`, a 200-entry rolling window, no XHR/fetch/htmx, `?sf=`/`?tep=` do NOT filter server-side; row keys `id` / `date` / `teamOne` / `teamTwo` / `settings`; sides carry `place` + `playerIds`; settings carry `id` / `teams` / `qBs` / `ppr` / `tep` / `is2TE` / `passTDPoints` / `leagueStartingLineup.position[]`. Identity is solved — `src/sources/ktc_identity.parse_ktc_identity` classifies **all 259 distinct references** (508 player refs, 299 picks, 1 FAAB amount, 0 unresolved) | Ingested within the granted permission scope, KTC-labelled provenance | IMPLEMENT | `C4-MTL-01`, `F-EXT-01` | spec §19.2 | P3 | mkt | `EXT` `OD-01` | grant artifact captured |
| `C4-MTL-03` | Comparable-trade matching | `C4-MTL-01` | ABSENT | Indexed, format-aware, recency-aware; no naive raw-trade averaging into canonical value | IMPLEMENT | `C4-MTL-01` | spec | P2 | mkt | — | latency + relevance |
| `C4-KTC-01` | KTC playerID → identity: one owner | `src/sources/ktc_identity.py` | **REPAIRED 2026-08-18.** Owner prefers `allPlayerSearchValues` (~1,997 entries) over `playersArray` (500 entries); measured on identical live HTML the live producer keeps **200/200** claims vs 150/200 and names **124/200** drops vs 94. Picks classified (vendor `position: RDP` + three observed label shapes), FAAB amounts classified, `-1` named as the no-drop sentinel; id collisions fail closed; **no `Player#<id>` fabrication anywhere**. The scraper's dead crowd producers were retired rather than repaired (see `C4-MTL-02`), so `KTC_ID_TO_NAME` / `KTC_CROWD_DATA` / `ktcIdMap` are deleted. Known deferred second derivation: `scrape_ktc` Strategy 2 still builds its own id→name map to join the value-history API — board-affecting, pinned by `tests/sources/test_ktc_identity.py::KNOWN_DEFERRED_DERIVATIONS`, needs its own measured unit | Joinable names | REPAIR | `C1-ID-01` | W05-F005 | P3 | mkt | — | join rate: 200/200 · board inertness 0/0/0/0 |
| `C4-FAAB-01` | FAAB Market Heat + normalized external evidence (CE-19) | `src/trade/faab_engine.py` | ABSENT (extension) | Bounded ~10% heat cap; four populations stay separate; percent-of-**original**-budget normalization; $0 bids are real, missing budgets are not | IMPLEMENT | `C4-MTL-01` | `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`, decisions 56–65 | P2 | mkt | — | backtest |
| `C4-FAAB-02` | FAAB bid history collection is scheduled | `scripts/fetch_faab_history.py` | PARTIAL — **no timer; a manual prod step**; cold deploys run on priors | Timer + freshness | REPAIR | — | audit both | P3 | mkt | `RET` | artifact on prod |
| `C4-SHARP-01` | Sharp cohort is proven populated in production | `src/sharp/cohort.py` | **PROOF-REQUIRED** — code complete, 580 tests green, timers deployed; tracked verification artifacts end at 502/401/"unverifiable_unauthenticated"; the roster board self-declares "not yet activated in production" | Verified live population | PRODUCTION-PROOF | — | audit both | P3 | sharp | — | live cohort count |
| `C4-SHARP-02` | Sharp bootstrap stops failing | `src/intel/platform_ledger.py` | PARTIAL — FFPC timeouts + SQLite locking | Stable | REPAIR | — | audit 1 §5 | P3 | sharp | — | green runs |
| `C4-SHARP-03` | FFPC roster lane is real or honestly empty | `src/platforms/ffpc/` | PARTIAL — roster URL is a fixture, contributes zero rosters | Real feed or an explicit zero-coverage state | REPAIR | — | methodology doc | P3 | sharp | `EXT` | coverage stamp |
| `C4-INS-01` | Insider Trading / cross-league | `src/intel/` | COMPLETE | Consumes the canonical ledger | CONSOLIDATE | `C1-ACQ-01` | inventory 4.8 | P1 | sharp | — | parity |
| `C4-WAIV-01` | Waiver ledger | `C4-FAAB-01` | ABSENT | Per-league waiver event history | IMPLEMENT | `C1-ACQ-01` | CE-19 | P2 | mkt | — | ledger rows |
| `C4-SRC-01` | DraftSharks staleness resolved | `scripts/fetch_draftsharks.py` | **BROKEN** — ~219 h stale against a 24 h threshold; session absent on prod; the watchdog is red every 2 h while 9-day-old values still vote in every blend | Re-minted, degraded honestly, or retired | REPAIR | — | both audits | P3 | src | `OD-04` | fresh stamps |
| `C4-SRC-02` | Partial source runs stop reporting as healthy | `data_contract` source health | PARTIAL — `total_sources: 2` while the payload carries 21 keys, and the contract calls the run "healthy" | Freshness, coverage and degraded state are honest and distinct | REPAIR | — | both audits | P2 | src | — | health contract test |
| `C4-SRC-03` | FootballGuys ghost stamps removed | `data/scrape_state/` | PARTIAL — orphaned stamps from 2026-05-24, no fetcher | Removed or restored | REPAIR | — | audit 2 §5 | P3 | src | — | clean state |

## C5 — Seasonal projection, probability and performance engines

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C5-POW-01` | One weekly power-rankings engine | *(consolidate)* | DUPLICATED — `src/public_league/power.py` and `src/ros/power_v2.py` | One engine, public and private views | CONSOLIDATE | `C2-STR-01` | `docs/CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` | P2 | season | — | parity |
| `C5-PLAY-01` | One playoff-probability engine | *(consolidate)* | DUPLICATED — 2 engines | One simulation substrate | CONSOLIDATE | `C2-LINE-01` | `docs/PLAYOFF_PREDICTOR_SPEC.md` | P6 | season | — | calibration |
| `C5-GD-01` | Game Day Command Center (CE-20) | *(new)* | ABSENT | Beat-median from one joint league-week simulation; best-ball aware; exact league scoring; low-cost V1 | IMPLEMENT | `C5-PLAY-01` | `docs/GAME_DAY_PROBABILITY_SPEC.md`, decisions 14–20 | P1 | season | — | Brier / reliability |
| `C5-GD-02` | Prediction archive without temporal leakage | `C1-HIST-01` | ABSENT | Pregame + in-game snapshots archived | IMPLEMENT | `C1-HIST-01` | decision 17 | P3 | season | `RET` | archive rows |
| `C5-WAR-01` | Player Impact / Fantasy WAR / VORP / WAB | *(new)* | ABSENT | Realized Lineup VORP, WAR, xWAR, Wins Above Bench, Game Changer Points | IMPLEMENT | `C2-REPL-01`, `C1-HIST-01` | `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` | P6 | season | — | validation §12 |
| `C5-ROS-01` | Redraft / ROS seasonal intelligence lane | `src/ros/` | PARTIAL | Verified seasonal evidence, **kept separate from canonical dynasty valuation** | IMPLEMENT | `C1-SRC-01` | `docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` | P2 | season | — | lane-separation test |
| `C5-BDVM-01` | BDVM fundamentals | `src/bdvm/` | COMPLETE for declared scope | Stays a second, named concept; never merged into `rankDerivedValue` | COMPLETE-ALREADY | — | `CLAUDE.md` | P6 | season | — | existing parity fixture |
| `C5-FIT-01` | League-specific player fit / college translation | `src/scoring/` | ABSENT | Player-specific only where evidence supports it; shrinkage/OOS; scoring fit stays separate from scarcity | IMPLEMENT | `F-SCORE-02` | #803, decisions 44–46 | P6 | season | — | OOS validation |
| `C5-ST-01` | Player special-teams scoring | `src/nfl_data/realized_points.py` | PARTIAL | `kr_yd`/`pr_yd`/`st_*` credited to the player; `def_*` stays DST; explicit UNSCORABLE | REPAIR | `F-SCORE-02` | #802, decision 43 | P6 | season | — | 2025 backtest |

## C6 — Analyst, news, Podcast, YouTube, Consensus and Manager intelligence

*This phase is greenfield infrastructure. It is the only phase whose external access does not exist today.*

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C6-ANA-01` | Analyst claim/evidence ledger | *(new)* | ABSENT — **zero ingestion code, zero credentials, zero transcription tooling** | Normalized claims with identity, provenance, dedupe | IMPLEMENT | `C1-ID-01` | inventory §5 | P3 | intel | `OD-03` | ledger rows |
| `C6-POD-01` | Podcast Intelligence | `C6-ANA-01` | ABSENT | ~50 sources; canonical analyst identity | IMPLEMENT | `C6-ANA-01` | inventory 5.1–5.7 | P3 | intel | `OD-03` | coverage |
| `C6-YT-01` | YouTube Analyst Intelligence | `C6-ANA-01` | ABSENT | ~50 sources; **deduped against podcasts by analyst/content identity** so one opinion is not two votes | IMPLEMENT | `C6-POD-01` | #782, decision 8 | P3 | intel | `OD-03` `EXT` | dedupe test |
| `C6-X-01` | X / Twitter analyst feed | `C6-ANA-01` | ABSENT | Official API only, no scraping | IMPLEMENT | `C6-ANA-01` | #788, decision 13 | P3 | intel | `OD-03` **cost-gated** | owner cost approval |
| `C6-FRESH-01` | Take freshness / decay / supersession | `C6-ANA-01` | ABSENT | Type-aware, event-aware, season-aware; no universal weekly reset; freshness modifies, never votes | IMPLEMENT | `C6-ANA-01` | decisions 33–40 | P6 | intel | — | decay tests |
| `C6-SIG-01` | ONE Central Buy/Sell reconciler | *(new)* | DUPLICATED — **≥6 emitters, no reconciler**; `unified_signal_engine.py` claims sole ownership in its docstring and has zero callers | One synthesis owner over labelled domain signals; no double counting | CONSOLIDATE | `C6-ANA-01` | inventory 4.2 | P2 | intel | — | lineage test |
| `C6-SIG-02` | Homepage ticker consumes canonical output | `C6-SIG-01` | ABSENT | BUY may be global; **SELL only for the selected team's roster**; presentation only | IMPLEMENT | `C6-SIG-01` | #784, decision 10 | P1 | intel | — | rule test |
| `C6-MGR-01` | Manager Scout (CE-03) | `src/intel/` | ABSENT (substrate exists) | Derived from canonical transaction/waiver/lineup history; no parallel transaction store | IMPLEMENT | `C1-ACQ-01`, `C4-MTL-01` | CE-03 | P2 | intel | — | tendency tests |
| `C6-UPP-01` | Universal Player Profile expansion | `C6-ANA-01` | PARTIAL | One canonical player intelligence feed; fact vs opinion; freshness; selective quotation | IMPLEMENT | `C6-ANA-01` | #783, decision 9 | P1 | intel | — | profile parity |
| `C6-EDGE-01` | Consensus Edge | `src/consensus_edge/` | PARTIAL — flag default OFF after its own ship-gate said don't ship | Independence-resolved; freshness applied after dedupe | REPAIR | `C6-FRESH-01` | inventory 4.1 | P6 | intel | — | ship gate passed |

## C7 — Decision products and mature workflows

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C7-BEST-TRADE` | **Best Trade to Send Each Team** | `C3-PKG-01` + `C3-CON-01` + `C3-XMKT-01` + `C7-POST-01` | ABSENT — zero hits repo-wide | Exactly one qualifying trade per opponent; canonical WIN for us; opponent EVEN-or-better on KTC **or** IDPTC with whole-package native coverage; **no imputed approval**; honest no-result; ranked for mutual defensibility, not maximum exploit; recommendation only. **Topology superseded 2026-08-14 (#841/#842): the `no draft picks` and exact-equal-player-count rules are WITHDRAWN.** Picks are valid when posture makes them mutually beneficial, never as filler; player counts may differ by at most one (`abs(A−B) <= 1`) and picks do not count as players. A pick-inclusive package needs a defined external-qualification path before shipping — a source that cannot natively evaluate the full package is marked incomplete, never treated as approval | IMPLEMENT | `C3-PKG-01`, `C3-CON-01`, `C3-XMKT-01`, `C2-STR-01`, `C7-POST-01`, `C1-PICK-01` | #835 §1, ledger 102, **#841/#842 supersession** | P1 | decide | see below | hard rules tested incl. the superseded topology |
| `C7-POST-01` | Competitive Posture (#840) | *(new)* | ABSENT | Classify each team's strategic position — PUSH / RETOOL / REBUILD / HOLD — from canonical evidence (Team Strength, Meaningful Roster Core, age/value construction, playoff and championship probability, season timing, pick ownership). Consumed by Analyze Trade and the posture-aware generator; explained, never asserted | IMPLEMENT | `C2-STR-01`, `C2-AGE-02`, `C5-PLAY-01` | #840, `docs/trade/ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md` | P6 | decide | — | posture classification validated against real league states |
| `C7-PICKGEN-01` | Posture-aware pick generation (#841) | `C3-PKG-01` | ABSENT | Picks enter generated packages when both teams' strategic positions make them mutually beneficial — a PUSH team sending future capital for production that fills a real weakness and materially moves championship odds; a REBUILD team receiving owned picks, youth and liquidity. **Never generic equalizer filler, never inserted cosmetically, never to make raw totals line up.** Offer only picks actually owned; prefer exact slot when known, else the canonical future representation with its distribution; a team that does not own its own pick is not credited with improving it by getting worse; respect the league's real draft-order mechanics; never recommend lineup manipulation. A player-only offer stays preferred when it is the best mutual trade | IMPLEMENT | `C7-POST-01`, `C1-PICK-01`, `C1-PICK-03`, `C3-PKG-01` | #841 | P6 | decide | — | acceptance examples in the addendum |
| `C7-GOLD-01` | Golden Upgrades | `C3-PKG-01` | ABSENT | Consumer of the shared generator + constraint owner | IMPLEMENT | `C3-PKG-01`, `C3-CON-01` | inventory 2.5 | P1 | decide | — | acceptance |
| `C7-PKGB-01` | Package Builder | `C3-PKG-01` | ABSENT | Consumer; no page-local engine | IMPLEMENT | `C3-PKG-01`, `C3-CON-01` | inventory 2.6 | P1 | decide | — | acceptance |
| `C7-DESK-01` | Analyze Trade + Trade Desk (CE-05) | *(new)* decision contract | ABSENT | MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS with confidence and reasons; **synthesis by unique information, not by weighting every visible panel** | IMPLEMENT | `C3-CALC-01`, `C2-SIM-01`, `C4-MTL-03` | #792, decisions 24–27 | P1 | decide | — | no-double-count test |
| `C7-GATE-01` | Sleeper Action Gateway (CE-11) | *(new)* | ABSENT — Sleeper integration is read-only; zero write paths exist | Authenticated, previewed, confirmed, idempotent, audited. **Never silent.** | IMPLEMENT | `C7-DESK-01` | CE-11 | P1 | decide | `OD-02` | see OD-02 |
| `C7-WAIV-01` | Perfect Waivers | *(new)* | ABSENT — today a greedy client slate | One optimizer over availability, dropability, need, protection, market evidence; **the correct answer is the matching problem** | IMPLEMENT | `C2-DROP-01`, `C4-FAAB-01`, `C3-CON-01` | inventory 3.3/3.4 | P1 | decide | — | matching test |
| `C7-DRAFT-01` | Perfect Draft | `src/draft/` | COMPLETE for declared scope | Becomes a consumer of canonical pick identity/valuation; backtest unblocked when a pre-draft snapshot exists | CONSOLIDATE | `C1-PICK-01` | `docs/perfect-draft.md` | P1 | decide | — | parity |
| `C7-DRAFT-02` | Pre-auction immutable snapshot | `C1-HIST-01` | PARTIAL — `--record-snapshot` exists, must be run before an auction | Captured automatically | IMPLEMENT | `C1-HIST-01` | appendix C1 | P3 | decide | `RET` | snapshot exists |
| `C7-ALERT-01` | Edge Alerts | `C6-SIG-01` | ABSENT | Materiality threshold, dedupe/cooldown, freshness, actionability | IMPLEMENT | `C6-SIG-01` | `docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md` §4 | P1 | decide | — | anti-spam test |
| `C7-AI-01` | Ask Brisket | `C6-ANA-01` + canonical services | ABSENT as a product; **orphan code exists** (`src/api/chat.py`) with no planning record | Retrieval/orchestration over canonical evidence; the model never recomputes a canonical quantity | IMPLEMENT | `C7-DESK-01` | `docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md` §2 | P1 | decide | `OD-03` | grounding test |
| `C7-AI-02` | Roster Path Optimizer | canonical services | ABSENT | Sequences of actions toward an explicit objective; consumes existing owners | IMPLEMENT | `C7-DESK-01`, `C5-PLAY-01` | spec §3 | P1 | decide | — | acceptance |
| `C7-AI-03` | Trade Liquidity & Market Depth | `C4-MTL-01` | ABSENT | Advisory only; **liquidity never changes canonical value** | IMPLEMENT | `C4-MTL-01`, `C6-MGR-01` | spec §5 | P1 | decide | — | non-influence test |
| `C7-AI-04` | Negotiation Coach | `C7-DESK-01` | ABSENT | No automatic offers; no real-world profiling | IMPLEMENT | `C7-DESK-01`, `C6-MGR-01` | spec §6 | P1 | decide | — | acceptance |
| `C7-AI-05` | League Truth | `C5-POW-01` | ABSENT | Record vs underlying performance, without collapsing distinct metrics into one number | IMPLEMENT | `C5-POW-01` | spec §7 | P1/P4 | decide | — | metric separation |
| `C7-AGE-01` | Age & Value / Roster Window on every team profile | `C2-AGE-02` | ABSENT | Compact module on each team profile/home page: Young Core Index + league rank, value-weighted core age, compact age-value chart, position rows with league percentile, flags where the roster is old relative to the league, and expansion into the detailed league comparison view | IMPLEMENT | `C2-AGE-02` | #838 addendum, team-profile UX | P1 | decide | — | per-surface acceptance incl. mobile |
| `C7-CMD-01` | Dynasty Command Center (CE-04) / Portfolio (CE-06) | `C2-STR-01` | ABSENT | Consumer surfaces | IMPLEMENT | `C2-STR-01`, `C7-DESK-01` | CE-04/06 | P1 | decide | — | acceptance |
| `C7-CE-01` | Remaining CE consumer surfaces | per `docs/CE_REGISTRY.md` | ABSENT | CE-07 Market ADP · CE-08 Projections & Stats Hub · CE-12 Lineup Intelligence · CE-13 Draft Room · CE-14 Market Pulse · CE-14A Personal Rankings Overlay · CE-15 Portfolio Trade Campaign · CE-16 Trade Polls · CE-17 League Format/Utilization Lab · CE-22 starter-relevance filter · CE-23 roster-age windows · CE-24 league longevity · CE-25 compare multi-select · CE-26 cross-league view · CE-27 keeper/privacy mechanics · CE-29 push (exists) | IMPLEMENT | phase-dependent | `docs/CE_REGISTRY.md` | P1 | decide | — | per-surface acceptance |

### `C7-BEST-TRADE` — the external-approval question, resolved

Both audits classified Best Trade's external gate as an external blocker. **Measured against the code, it is not
one, and the reason matters for the plan.**

There is no external whole-package grading endpoint at KTC or IDPTC, and there never was one to lose. What the
repository has instead is **a bit-for-bit port of KTC's own package algorithm** (`src/trade/ktc_va.py`, a verbatim
translation of `frontend/lib/trade-logic.js`, itself a verbatim port of `keeptradecut.com/js/site.min.js`'s
`processV`/`reverseAdjust`/`adjustPackage`), parity-tested against real captures from the site. Grading a package
"on KTC" means running KTC's algorithm over KTC's published per-player values — which is what the site itself
does in the browser.

So the requirement decomposes into two things the repo can satisfy:

1. **Native coverage of every asset in the package** on the chosen market — `src/league_intel/cross_market.py`
   already implements exactly this, with measured evidence, and is now **wired** (`C3-XMKT-01`, corrected
   2026-08-20 — see the manifest row above).
2. **Faithful application of that market's package algorithm** — `C3-VA-01`, **now consolidated to one Python
   owner + one JS owner** (corrected 2026-08-20 — see the manifest row above).

The spec's prohibition on "imputed-through-our-own-values" approval bites on **coverage**, not on arithmetic: an
asset the external board does not price cannot be given a value from our board and then counted as external
approval. Running the market's own published algorithm over the market's own published values is not imputation.

What *is* genuinely open is narrower and is tracked separately: KTC data use rests on an owner-reported permission
whose grant artifact is not in the repository (`F-EXT-01`, `OD-01`), and **IDPTC has no authorization record of any
kind**. Those gate the *ingestion*, which is already live and long-standing — not the feature's arithmetic.

## C8 — Premium Sports Intelligence production migration

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C8-PSI-01` | Design primitives, tokens, shell, breakpoints, focus states | `frontend/components/ds/` | PARTIAL — 24 ds components, token contract test, per-page bundle budgets, a11y ratchet; **no axe-core**; live tokens contradict the north star | No-regret primitives landed; token direction resolved | IMPLEMENT | `C0-PSI-01` | `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` | P1 | psi | `OD-05` | token contract |
| `C8-PSI-02` | Reference route migration (Rankings first) | `frontend/app/rankings/` | ABSENT | One route migrated behind a rollback boundary | MIGRATE | `C8-PSI-01`, `C0-PERF-01` | north star §5 | P1 | psi | — | per-route parity + perf |
| `C8-PSI-03` | Route-by-route migration | frontend | ABSENT | Every route; `/league`, sharp/market and admin/tools are still on legacy | MIGRATE | `C8-PSI-02` | north star | P1 | psi | — | per-route proof |
| `C8-PERF-01` | Mobile payload is smaller than desktop | `/api/data` compact view | **INVERTED** — the mobile view is +13% larger (W26-F001) | Route-specific fields, virtualization, progressive disclosure | UX/PERF | `C0-PERF-01` | W26-F001 | P1 | perf | — | measured |
| `C8-PERF-02` | Non-data routes stop fetching the contract | frontend | PARTIAL — `/login`, `/more` fetch the multi-MB contract (open PR #759) | Route-scoped fetching | UX/PERF | — | #759 | P1 | perf | — | measured |
| `C8-PERF-03` | Rankings board windowing | `frontend/app/rankings/` | PARTIAL — 22 FPS at scale; a corrected harness proves windowing reaches 59.5 FPS (open PR #760) | Windowed | UX/PERF | `C0-PERF-01` | #760 | P1 | perf | — | FPS harness |
| `C8-PERF-04` | Sharp Tracker load time | sharp pages | **PERF-INCOMPLETE** — measured cache-defeating architecture (client `no-store` + cache-buster vs backend SWR) | Within budget | UX/PERF | `C0-PERF-01` | `docs/SHARP_INSIDER_EXPERIENCE_PERFORMANCE_SPEC.md` | P1 | perf | — | measured |
| `C8-PERF-05` | Public league payload | `/api/public/league` | **PERF-INCOMPLETE** — ~2.1 MB, 14.8 s observed | Paginated/materialized | UX/PERF | `C0-PERF-01` | audit 1 §5 | P4 | perf | — | measured |
| `C8-A11Y-01` | Accessibility instrumentation | frontend | PARTIAL — structural ratchet exists, no axe-core | Automated a11y checks per route | IMPLEMENT | `C8-PSI-01` | audit 2 §21 | P1 | psi | — | axe in CI |

## C9 — Public league, storytelling, awards, sharing and season products

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C9-AWARD-01` | Awards do not exist before games are played | `src/public_league/awards.py` | **WRONG** — the live 2026 payload manufactures eight awards with zero games: a 0–0 crown, a zero-point leader, a zero-VORP MVP | Eligibility gates; suppressed or explicitly labelled | REPAIR | — | audit 1 §5 | P4 | public | — | zero-games test |
| `C9-AWARD-02` | Brisket Honors v2 | `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` | ABSENT | **Player MVP has no playoff/>.500 gate**; MOTY may retain a validated team-success rule | IMPLEMENT | `C5-WAR-01` | #809 + `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §7 | P4 | public | — | eligibility tests |
| `C9-HIST-01` | Historical franchise continuity | `src/public_league/identity.py` | **WRONG** — 2024 declares ten teams and carries eight standings rows; retired-owner mappings hard-coded | Continuity repaired before any awards/WAR backfill | REPAIR | `C1-ACQ-02` | audit 1 §5 | P4 | public | — | continuity test |
| `C9-HIST-02` | `PUBLIC_MAX_SEASONS` truncation | `src/public_league/` | PARTIAL — "all-time" truncates as seasons accumulate | Paginated archives | REPAIR | — | audit 1 §20 | P4 | public | — | archive test |
| `C9-SHARE-01` | Canonical Share Renderer (CE-10) | *(new)* | ABSENT — 4 ad-hoc opengraph routes | One renderer over privacy-classified view models | IMPLEMENT | `F-PRIV-01` | CE-10 | P4 | public | — | renderer tests |
| `C9-WRS-01` | Weekly Report Studio | *(new)* | ABSENT | **Manual External AI is the default; zero site-side LLM calls in that mode**; one pregame + one postgame package per week; provider-neutral versioned schema; API modes share the pipeline; Automatic API disabled by default | IMPLEMENT | `C9-SHARE-01`, `C5-POW-01` | #829, decisions 47–55 | P4 | public | — | validator + fail-closed import |
| `C9-UR-01` | The Upside Report (weekly) | `C9-WRS-01` | ABSENT | Per `docs/UPSIDE_REPORT_WEEKLY_SHOWCASE_SPEC.md` | IMPLEMENT | `C9-WRS-01` | #809, T-NEW-07 | P4 | public | — | acceptance |
| `C9-UR-02` | Upside Report Preseason / Kickoff Edition | `C9-UR-01` | ABSENT | **Published the Tuesday before Week 1**; becomes the immutable preseason baseline for later movement and retrospectives; generable with zero completed games | IMPLEMENT | `C9-UR-01`, `C1-HIST-01` | `docs/UPSIDE_REPORT_PRESEASON_KICKOFF_EDITION_SPEC.md` | P4 | public | `RET` | baseline artifact |
| `C9-V3-01` | Public League Experience v3 | `src/public_league/` | PARTIAL — 29 modules live on the old UX | Six hubs, Franchise Passport, storytelling | IMPLEMENT | `C9-HIST-01`, `C8-PSI-03` | inventory §6 | P4 | public | — | acceptance |
| `C9-RECAP-01` | Dynasty Season Recap / Wrapped (CE-21) | `C9-UR-01` | ABSENT | — | IMPLEMENT | `C9-UR-01` | CE-21 | P4 | public | — | acceptance |
| `C9-TRUTH-01` | League Truth public view | `C7-AI-05` | ABSENT | Public shows factual/retrospective metrics only | IMPLEMENT | `C7-AI-05`, `F-PRIV-01` | #809 spec §7 | P4 | public | — | boundary test |

## C10 — Site-wide closure / confidence pass

| id | capability | owner | status | final | disposition | deps | source | prof | lane | flag | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C10-CLOSE-01` | Zero-loss re-audit against this manifest | this file | ABSENT | Every row closed or explicitly owner-accepted | IMPLEMENT | all | contract §13.1 | P5 | close | — | re-audit |
| `C10-CLOSE-02` | Duplicate owners retired | §2 | ABSENT | Every `DUPLICATED` row resolved | IMPLEMENT | all | contract §13.2 | P5 | close | — | owner map clean |
| `C10-CLOSE-03` | Browser / workflow matrix | — | ABSENT | Per contract §13.3 | IMPLEMENT | all | contract | P1 | close | — | matrix |
| `C10-CLOSE-04` | Background jobs and data proven | — | ABSENT | Per contract §13.4 | IMPLEMENT | all | contract | P3 | close | — | artifacts |
| `C10-CLOSE-05` | Performance gates met everywhere | `docs/GLOBAL_PERFORMANCE_STANDARD.md` | ABSENT | Per contract §13.5 | IMPLEMENT | all | contract | P1 | close | — | measurements |
| `C10-CLOSE-06` | Security / privacy / auth pass | `F-PRIV-01` | ABSENT | Per contract §13.6 | IMPLEMENT | all | contract | P5 | close | — | audit |
| `C10-CLOSE-07` | Final regression | — | ABSENT | Per contract §13.7 | IMPLEMENT | all | contract | P1 | close | — | green |
| `C10-ML-01` | Adaptive source weighting stays off until validated | `src/model_registry/` | ABSENT by design | Champion/challenger; nothing self-promotes | IMPLEMENT | all | appendix D5 | P6 | close | — | promotion record |

## F — Foundations already complete (recorded so they cannot be re-litigated or silently regressed)

| id | capability | owner | status | final | disposition | source | prof | evidence |
|---|---|---|---|---|---|---|---|---|
| `F-VAL-01` | One canonical player value, 1–9999, enforced | `_compute_unified_rankings` | COMPLETE (B9a) | Unchanged | COMPLETE-ALREADY | B ledger | P6 | `test_canonical_value_scale_contract.py` |
| `F-VAL-02` | No second canonical board | `data_contract` | COMPLETE (B9a) | Unchanged | COMPLETE-ALREADY | B ledger | P6 | `test_one_canonical_value_per_asset.py` |
| `F-VAL-03` | `valuation_mode` withdrawn, ignored, stamped | `server.py` | COMPLETE | Do not re-thread | COMPLETE-ALREADY | #822 | P6 | `test_canonical_value_invariance.py` |
| `F-CONF-01` | Five-axis confidence, weakest axis wins | `src/api/confidence.py` | COMPLETE (B11) | Naming defects only (`C1-CONF-01`) | COMPLETE-ALREADY | B ledger | P6 | `test_confidence_gate.py` (35 tests) |
| `F-SRC-01` | Provider families, one vote each | `_RANKING_SOURCES` | COMPLETE (B10) — 21 keys → 13 families | Unchanged | COMPLETE-ALREADY | B ledger | P6 | family tests |
| `F-SCORE-01` | Factual scoring identity, fails closed | `league_registry` | COMPLETE (B6) | Unchanged | COMPLETE-ALREADY | B ledger | P2 | B6 evidence |
| `F-SCORE-02` | Realized scoring | `src/nfl_data/realized_points.py` | COMPLETE (B7) | Special teams open (`C5-ST-01`) | COMPLETE-ALREADY | B ledger | P6 | B7 evidence |
| `F-PRIV-01` | Public/private boundary on both channels | B8 exposure policy | COMPLETE (B8) | Every new surface consumes it | COMPLETE-ALREADY | B ledger | P4 | B8 evidence |
| `F-MISS-01` | Missing is never zero, on display | display owners | COMPLETE (#836) | Every new surface | COMPLETE-ALREADY | B ledger | P1 | #836 tests |
| `F-FAAB-01` | One FAAB engine | `src/trade/faab_engine.py` | COMPLETE | Extended by `C4-FAAB-01` | COMPLETE-ALREADY | `docs/faab-model.md` | P2 | 247 tests |
| `F-ROS-01` | ROS projections | `src/ros/` | COMPLETE | Doc refresh | COMPLETE-ALREADY | `docs/ros-engine.md` | P2 | existing |
| `F-EXT-01` | KTC data-use permission record | `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §19.2 | PARTIAL — owner-reported; the grant artifact (evidence, contact, scope, method, rate, attribution, redistribution, revocation) is **not in the repository** | Artifact captured | OWNER-DECISION | #809 | P5 | `OD-01` |
| `F-EXT-02` | IDPTC authorization | — | **ABSENT — no record of any kind**, while IDPTC is the sole IDP market anchor and a co-equal approval authority in the Best Trade spec | Recorded or the dependency re-scoped | OWNER-DECISION | audit 2 | P5 | `OD-01` |
| `F-EXT-03` | Credentialed / paywall-adjacent source posture | DLF, DraftSharks, IDP Show, Flock | PARTIAL — 7 source keys behind credentials, zero recorded authorization; the repo's one written terms posture is applied to FFPC alone | Consistent posture | OWNER-DECISION | audit 2 §23 | P5 | `OD-01` |

## X — Explicitly out of scope (recorded so they are not silently re-added)

| id | capability | disposition | source |
|---|---|---|---|
| `X-01` | Schedule generator | OWNER-REJECTED | inventory §0 |
| `X-02` | Money / dues / Constitution / League Media | OWNER-REJECTED | inventory §0 |
| `X-03` | Establish The Run paid source | OWNER-PAUSED — research preserved; do not purchase or implement until the owner resumes | #801, decision 42 |
| `X-04` | Canonical Data Mode offline build | SUPERSEDED — retired; the live contract is the single source of truth | `CLAUDE.md` |
| `X-05` | League-aware valuation overlay as canonical | OWNER-REJECTED — seven measured defects; may not own a canonical field | `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md` |
| `X-06` | `src/api/opportunity_stats.py` usage-signal engine | SUPERSEDED — the live replacement is `src/consensus_edge/opportunity.py` | audit 2 cluster 8b |
| `X-07` | "Link any Sleeper account" general onboarding | NOT-PRODUCT-SCOPE today — recorded as a long-horizon goal in a historical file, never owner-approved | `OD-07` |

---

# 5. Counts

| measure | count |
|---|---|
| Raw source entries enumerated (twelve families A–L, at census time) | ≈926 |
| Later cohorts E2 + E3 (subdivisions of family E) | ≈256 |
| Combined raw population | ≈1,182 |
| Distinct capability identities after de-duplication | ≈357 |
| Binding constraint / methodology / validation units (not capabilities) | ≈425 |
| **Manifest rows** | **163** (142 C-phase · 14 completed foundations · 7 out-of-scope; 3 of the 142 are aggregates that enumerate their members inline) |
| Rows carrying a phase, a disposition and completion evidence | 157 |
| **Unmapped** | **0** |
| Duplicate clusters resolved | 4 (CE namespace · ledger 102–104 ≡ #835 · Best Trade dual record · Trade Trees dual identity) |
| Explicitly superseded owner rules | 6 (2028/2029 unpriced posture · player-MVP eligibility gate · `unified_signal_engine` ownership claim · Best Trade `no draft picks` · Best Trade exact-equal-player-count · **fixed meaningful-core positional caps, superseded by #839's `ceil(1.5 × real starter demand)`** — see `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §4.1) |
| Owner-rejected / paused / not-scope rows | 7 (`X-01`…`X-07`) |
| External blockers | 3 (`F-EXT-01`, `F-EXT-02`, `F-EXT-03` — all one owner decision, `OD-01`) |
| Owner decisions required | 7 (§6) |
| Rows flagged `BLOCK-C` | **0** |
| Rows flagged `RET` (irreversible evidence) | **12** — `C1-RET-01`…`C1-RET-08` (phase C1, the authorized C1A tranche) plus `C4-FAAB-02`, `C5-GD-02`, `C7-DRAFT-02`, `C9-UR-02`, which are flagged so collection starts as early as their phase allows but are **not** part of the C1A tranche |

---

# 6. Owner decisions required

Recorded here; stated in full in `docs/POST_B_RECONCILIATION_2026-08-14.md` §29 with options, recommended
default, consequences, and whether each blocks C1.

| id | question | blocks C1? |
|---|---|---|
| `OD-01` | External source authorization: capture the KTC grant artifact, obtain or forgo an IDPTC record, and set one posture for the credentialed sources | **No** |
| `OD-02` | Is authenticated trade submission (CE-11) required for C completion, or an approved later capability? | **No** |
| `OD-03` | Analyst Intelligence cost posture — podcast/YouTube infrastructure and any paid transcription/API spend | **No** |
| `OD-04` | DraftSharks: re-mint, accept degradation, or retire | **No** |
| `OD-05` | Premium token direction — the live terminal drift versus the north star | **No** |
| `OD-06` | CE-28 user feedback/polling: approve as scope, or drop | **No** |
| `OD-07` | "Link any Sleeper account" onboarding: approve as scope, or drop | **No** |

**None of the seven blocks C1.** Each is either about a later phase or about an external artifact that does not
gate foundation work.
