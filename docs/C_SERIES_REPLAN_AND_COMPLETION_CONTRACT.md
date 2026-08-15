# Chase Upside — C-Series Replan, Execution, Deployment & Completion Contract

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from PR #816 by the post-B master
> reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). Body unchanged. Two corrections of fact:
>
> 1. **§3's B→C entry gate is SATISFIED, not pending.** B11 merged (#832/#833/#834, merge `d50de55`) and the
>    bounded B-Series Completion Audit merged PASS (#837, merge `79f47ff`, 20/20 executable checks). Steps 1–7 of
>    §3 were executed by this reconciliation. **Steps 8–9 — owner review and explicit approval — remain
>    outstanding and are the only thing standing between here and C1 authorization.**
> 2. **§5's C0 phase is being executed by this reconciliation itself**, and §4's Scope Census requirement is
>    discharged by `docs/C_SERIES_SCOPE_MANIFEST.md` + `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`.
>
> §8's performance budgets are superseded in one direction only: `docs/GLOBAL_PERFORMANCE_STANDARD.md` (PR #809,
> also now on `main`) adds a **cold/uncached ≤3 s** tier this contract omits. Both are canonical; take the union.
>
> The reserved completion phrase in §15 remains reserved and is NOT claimed anywhere by this reconciliation.


**Status:** BINDING OWNER CONTRACT FOR THE POST-B C-SERIES  
**Recorded:** 2026-08-13  
**Applies when:** the B-series completion gate has passed  
**Companions:** `MASTER_PRODUCT_PLAN.md`, `EXECUTION_PLAN.md`, `OWNER_FEATURE_INVENTORY.md`, `OWNER_PRODUCT_BACKLOG_SPEC.md`, `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`, `OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md`, `OWNER_REQUESTED_TODO_SPEC_INDEX.md`, and all later explicit owner addenda.

> This document does **not** authorize starting C before the B→C hard gate. It defines how the C-series must be replanned, implemented, deployed, and proven complete once that gate is reached.

---

# 1. OWNER OUTCOME

The C-series is not complete merely because a roadmap was executed, code was merged, pages render, or tests are green.

The intended end state is:

> **Every owner-approved Chase Upside feature and product capability discussed before C completion is implemented at its correct architectural layer, connected to real canonical data, reachable to the intended user, deployed to production, performant, mobile/desktop capable where applicable, protected by tests and observability, and verified end to end strongly enough to use with confidence.**

The C-series must optimize **both** correctness and total delivery efficiency. The fastest acceptable plan is the one that builds shared foundations once, unlocks many consumers, parallelizes genuinely independent work, avoids duplicate engines, and does not create expensive rework by polishing unstable surfaces too early.

There is no default permission to silently defer an approved feature because it is difficult, large, inconvenient, or discovered late. If a requirement is genuinely blocked by unavailable data, licensing, credentials, or evidence, C cannot be declared complete unless the owner explicitly accepts that exception or changes the product requirement.

---

# 2. DOCUMENT PRECEDENCE FOR C

For C-series scope and behavior, use this order when records disagree:

1. most recent explicit owner instruction;
2. `MASTER_PRODUCT_PLAN.md`;
3. this C-series contract for C-specific planning/execution/completion rules;
4. detailed owner feature specifications and later addenda;
5. `OWNER_PRODUCT_BACKLOG_SPEC.md`;
6. `OWNER_FEATURE_INVENTORY.md`;
7. current approved C execution plan once created after B;
8. current canonical ADRs / architecture records;
9. verified repository/runtime evidence for implementation status;
10. historical planning captures, competitor research, old roadmaps, and old PR prose.

A stale implementation, old roadmap row, old screenshot, or old test expectation cannot override a newer owner decision.

## Explicit conflict resolutions already decided

### Every valid pick through 2029 must have value

The newer owner requirement supersedes older wording that allowed valid 2028/2029 picks to remain unpriced indefinitely.

By C completion, **every valid league-supported draft-pick asset through the 2029 rookie class must have a finite, non-missing canonical Chase Upside value**.

- Missing source evidence is never represented as zero.
- Unknown exact slot is not permission to drop the asset. Use a documented generic/future-pick valuation or distribution with provenance and uncertainty until the exact slot is known.
- When a slot becomes known, transition the same owned-pick identity safely to exact-slot valuation without double counting or creating a second asset.
- Exact-slot and generic representations must resolve consistently through canonical ownership.
- Mobile, desktop, APIs, exports, rankings, trade tools, ownership, history, and downstream engines must agree on the same canonical pick value.

### Player MVP eligibility

The later Player Impact / Fantasy WAR / MVP decision supersedes older wording that imposed a hard playoff-field + >.500 eligibility gate on **player MVP**.

Player MVP has **no hard playoff-field or >.500 eligibility requirement**. Team success may be contextual/tie-break evidence. Manager of the Year may retain appropriately validated team-success eligibility. GM/Executive and player performance awards remain conceptually separate.

---

# 3. B→C ENTRY GATE

After B11 and the bounded B-Series Completion Audit:

1. **STOP.**
2. Do not begin old C1.
3. Enter **Plan Mode only**.
4. Re-read current `main`, production state, all canonical planning/spec records, open/merged planning PRs, owner to-dos, and every owner addition made during B.
5. Reconcile what is actually complete, partial, stale, duplicated, missing, or superseded.
6. Build the C dependency graph from the state that exists **then**.
7. Produce the proposed canonical C-Series Execution Plan.
8. Jason + ChatGPT review it.
9. Only explicit owner approval authorizes implementation.

The purpose of this gate is not ceremony. It prevents a stale pre-B sequence from forcing late rework after B changed the architecture.

---

# 4. C-SERIES SCOPE CENSUS — ZERO-LOSS REQUIREMENT

Before C1 is authorized, create and commit a **C-Series Scope Manifest** with one row for every approved feature/capability.

The manifest must reconcile at least:

- `MASTER_PRODUCT_PLAN.md`;
- `OWNER_FEATURE_INVENTORY.md`;
- `OWNER_PRODUCT_BACKLOG_SPEC.md`;
- `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`;
- `OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md`;
- `OWNER_REQUESTED_TODO.md` and `OWNER_REQUESTED_TODO_SPEC_INDEX.md`;
- `PLAYER_IMPACT_WAR_MVP_SPEC.md`;
- `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`;
- Premium Sports Intelligence design records;
- detailed approved source/market/playoff/Game Day/history/AI specs currently captured on planning branches, after reconciling them into canonical records;
- CE-01–CE-21 and approved competitor-derived additions after mapping them to canonical owners;
- every later owner-approved feature/addendum created before C completion;
- current repository features that already exist but require repair, consolidation, migration, reachability, or production proof.

For every row record:

```text
feature_id
feature / user outcome
canonical owner
current status
required final status
spec source
hard dependencies
shared foundations
implementation phase
parallel lane
migration/backfill required
public/private boundary
desktop/mobile requirement
performance budget
validation/backtest requirement
production verification requirement
rollout/rollback
completion evidence
```

**No approved feature may disappear because it was absent from one older roadmap.** The census is a union-and-reconcile exercise, not a copy of any single document.

---

# 5. DEPENDENCY-FIRST ORDERING RULE

The final C plan must be ordered by dependency and rework minimization, not by which page is most exciting to build.

Use this general dependency spine unless current post-B evidence supports a better ordering. The final Plan Mode pass may split, merge, or rename phases, but it may not violate the dependencies below without documenting why.

## C0 — Truth freeze, scope manifest, and dependency graph

Before product implementation:

- reconcile current production/repo truth;
- generate the exhaustive C scope manifest;
- identify canonical owners and duplicate engines;
- mark which existing features are retain / repair / consolidate / replace / remove-by-owner-decision;
- map data migrations, history gaps, one-shot snapshots, credentials, and licensing blockers;
- define PR boundaries and parallel work lanes;
- define completion evidence before implementation begins.

This phase prevents “almost done” from being discovered at the end.

## C1 — Canonical asset, pick, history, and provenance foundations

Build/finish shared primitives that many later products depend on:

- stable real player/pick identity and ownership;
- **complete canonical draft-pick valuation through 2029**;
- exact-slot and future-generic pick transition rules;
- immutable value/history snapshots with league/scoring/methodology provenance;
- acquisition/holding-period history;
- canonical transaction/event ledger and asset lineage primitives;
- historical value-at-time lookup needed for trade history, cost basis, market comps, and aging;
- freshness/version/build diagnostics needed to prove which data/code a client is using;
- missing/stale/degraded states that fail honestly rather than becoming zero.

Do not build separate history stores for every downstream feature.

## C2 — Canonical roster, lineup, replacement, and impact foundations

Consolidate the shared roster mathematics before building many recommendation products:

- exact league-aware lineup/best-ball assignment;
- replacement/PAR/VORP primitives;
- canonical Team Strength;
- canonical Team Weakness / Need Priority;
- roster displacement/promotion logic;
- Dropability / cut-candidate ownership;
- before/after roster application primitive;
- Player Impact building blocks required by VORP, WAR/xWAR/WAB, Game Changer, Awards, and Upside Report.

A later page may display these concepts differently; it must not recalculate them independently.

## C3 — Canonical trade substrate

Once assets and roster math are stable, consolidate the transaction decision stack:

- one package-generation engine;
- exact KTC Value Adjustment as a clearly labelled market/consolidation lens;
- canonical raw asset equity separate from Value Adjustment;
- two-team and 3+ team ownership/destination correctness;
- generic pick quantities versus unique owned-pick rules;
- before→apply→rerank→after roster simulation;
- one Analyze Trade decision contract;
- Trade Finder / Suggestions / Golden Upgrades / Package Builder as consumers;
- trade equalizer math using the active post-VA gap without double applying VA;
- share/persistence contract for trades.

Do not let Trade Finder, Calculator, Package Builder, Golden Upgrades, and 3-team trade each grow their own package/value rules.

## C4 — Market, transaction, manager, Sharp, and waiver evidence ledgers

Build reusable evidence stores before higher-level intelligence consumes them:

- Market Trade Ledger / real accepted trades;
- comparable-trade matching metadata;
- market liquidity/depth;
- Trade History: Current Grade / At-the-Time Grade / How It Aged;
- manager transaction/acquisition behavior evidence;
- Sharp canonical cohort + transactions + roster percentage;
- waiver/FAAB market ledger;
- source-family/provenance/dedupe rules across overlapping observations.

These are evidence layers. A single trade, bid, or manager action must not overwrite canonical value by itself.

## C5 — Seasonal projection, probability, and performance engines

On top of correct scoring/lineup/history foundations:

- ROS/current-season projection consolidation;
- canonical Playoff Predictor;
- league-median-aware standings simulation where configured;
- Game Day matchup + Beat Median probabilities from coherent league-week simulation;
- canonical Weekly Power Rankings;
- Player Impact: Realized Lineup VORP, WAR, xWAR, Wins Above Bench, Game Changer;
- contender/rebuilder/current-window context;
- archived predictions for calibration and no-lookahead evaluation.

Power, standings, Team Strength, playoff probability, and dynasty value are distinct concepts and must remain distinct.

## C6 — Analyst, news, Podcast, YouTube, Consensus, and Manager intelligence

After canonical identity/evidence/freshness rules exist:

- podcast registry/discovery/transcripts/take extraction;
- YouTube dynasty intelligence using the same analyst/take architecture;
- analyst identity and same-thesis cross-platform dedupe;
- stance taxonomy including STASH / SPECULATIVE BUY distinctions;
- event/type-aware freshness and historical inactive takes;
- roster-aware Consensus Edge;
- one central Buy/Sell decision owner;
- Sharp / Insider / Manager Scout consumers;
- selected-team and player intelligence briefs;
- source-family dedupe so one thesis is not counted multiple times.

Do not process transcripts synchronously on interactive page requests.

## C7 — Decision products and mature workflows

Once their canonical services are stable, finish the major private front-office products:

- mature Trade Calculator and Trade Desk;
- Trade Finder / Suggestions / Package Builder / Golden Upgrades;
- Perfect Waivers / FAAB / Dropability;
- Perfect Draft / Draft Room;
- canonical Pick Forecast / owned future-pick projection;
- Universal Player Profile;
- Command Center;
- Portfolio / roster exposure;
- Compare / Personal Rankings / Lineup IQ / other approved CE consumers;
- alerts/push/personalized feed where approved.

The detailed Trade Calculator / real-trade / analytics additions in `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` are required scope, not optional polish.

## C8 — Premium Sports Intelligence production migration

Design migration is integrated with stable functionality, not bolted on at the end and not allowed to destabilize foundations.

No-regret design-system preparation may run in parallel earlier. The production rollout should remain incremental and use stable shared contracts:

1. design-system foundation / application shell where prerequisites are met;
2. Rankings as the first production reference route;
3. Universal Player Profile;
4. Trade / Trade Desk;
5. roster / market / Sharp / intelligence surfaces;
6. draft / waivers / Game Day / league surfaces;
7. remaining application routes.

Every migrated route must preserve functionality, speed, responsive behavior, accessibility, loading/stale/error states, and canonical data ownership. No big-bang reskin.

## C9 — Public league, storytelling, awards, sharing, and season products

Build public/entertainment layers only on verified canonical facts:

- Public League Experience v3;
- authenticated League navigation + safe public/private boundary;
- manual Sleeper sync/freshness UX;
- Game Day public-safe experiences;
- The Upside Report;
- Awards & Honors;
- Weekly/season archives;
- Trade Trees / Asset Lineage presentation;
- Dynasty Season Recap / Wrapped / Yearbooks;
- records/rivalries/player journeys/franchise history;
- Share Renderer;
- About / FAQ / Contact / support surfaces;
- optional non-intrusive monetization only after product usability is protected.

Historical truth and privacy boundaries come before visual storytelling.

## C10 — Site-wide closure / confidence pass

Do not declare C complete until the full scope manifest is closed with production evidence.

---

# 6. PARALLELISM — FAST WITHOUT CREATING REWORK

The final plan should run multiple lanes where their contracts do not collide.

Good parallel work:

- data/source research while a predecessor PR is in CI;
- historical backfill preparation after schema/identity contracts are fixed;
- design-system primitives that do not change business logic while backend foundations stabilize;
- independent ingestion adapters behind stable schemas;
- read-only validation/backtest harnesses before the production change that will use them;
- public presentation work only after its factual APIs are stable.

Bad parallel work:

- two agents inventing separate canonical owners for the same concept;
- building UIs against temporary contracts another agent is about to replace;
- parallel schema migrations touching the same history/identity tables without one migration owner;
- duplicate trade/package/lineup/value engines built by different workstreams;
- large design migration while core route behavior is being rewritten underneath it.

Use explicit work claims/owned-file boundaries where parallel agents operate. Shared canonical files get one owner at a time.

---

# 7. PR / MERGE / DEPLOYMENT PROTOCOL

“One coordinated C-series” does **not** mean one giant PR.

Each milestone should be a coherent, independently reviewable and revertible unit.

For every value-, data-, history-, scoring-, probability-, recommendation-, security-, or migration-sensitive milestone:

1. establish the pre-change truth and pin inputs where needed;
2. create RED coverage or an equivalent failing proof for the defect/missing contract;
3. implement through the canonical owner;
4. run focused tests while iterating;
5. run required broader regression gates;
6. run methodology backtests/calibration when the change makes a methodological claim;
7. measure data/value/rank/decision blast radius before merge;
8. validate CI on the **exact head SHA**;
9. merge only that validated head or revalidate after any change;
10. deploy through the normal production path;
11. run production smoke/E2E/data-contract verification proportional to risk;
12. verify mobile and desktop for relevant user-facing workflows;
13. verify observability/freshness/jobs after schema/background-work changes;
14. record rollback/revert path and completion evidence in the C ledger;
15. only then allow dependent milestones to treat the capability as complete.

Automated data-refresh commits advancing `main` are not automatically blockers; inspect source overlap rather than stopping ceremonially.

Use CI/deploy waiting time for read-only reconnaissance or non-overlapping next-phase preparation.

---

# 8. PERFORMANCE IS A DONE CRITERION

A functionally correct feature that is too slow to use is not complete.

Apply the repository-wide performance standard to every C feature. At minimum:

- warm/cached first useful data should generally be available in about **1 second or less**;
- normal production p95 should target **2 seconds or less** where architecture permits;
- **5 seconds is an absolute useful-state failure ceiling** for normal supported interactive workflows, not a target;
- repeatable expensive work belongs off the request path;
- precompute/materialize/cache where safe;
- do not clear useful content during background refresh;
- stale-while-refresh / last-known-good is preferred where safe and honest;
- no synchronous transcript processing, large market rebuild, Sharp cohort rebuild, historical reconstruction, or expensive simulation on a normal page click when it can be prepared ahead of time.

Performance must be measured on representative production-scale data, not inferred from unit-test speed.

---

# 9. FEATURE-LEVEL DEFINITION OF DONE

Every material feature must satisfy all applicable items below before its manifest row may become **DONE**:

## Architecture / truth

- one canonical owner;
- no conflicting live implementation;
- source-to-screen lineage documented/provable;
- identity and units correct;
- missing ≠ zero;
- provenance/freshness/methodology version available where material;
- public/private boundary correct;
- no local/device state can silently rewrite canonical truth.

## Product behavior

- complete intended workflow, not a static card;
- real production data, not mock/reference data;
- all approved controls/actions actually affect the intended system;
- empty, missing, stale, partial, unavailable, error, and retry behavior defined;
- links/navigation make the feature reachable;
- desktop and mobile capability parity where the workflow is supported on both;
- touch/keyboard/accessibility behavior appropriate to the surface;
- sharing/export/persistence behavior correct where specified.

## Methodology

- formula/model target clearly defined;
- no unsupported double counting/circularity;
- candidate methodology validated where evidence is required;
- uncertainty/confidence honest;
- no model self-promotion without the governed champion/challenger process;
- historical/no-lookahead tests where future prediction is claimed.

## Engineering

- focused tests;
- regression tests for the actual failure mode;
- cross-surface parity tests where shared truth is expected;
- broad suite green;
- exact-head CI green;
- no new lint/coercion/audit drift;
- performance budget met;
- logs/metrics/health for background jobs and critical data flows;
- safe migration/backfill and rollback.

## Production proof

- deployed revision identified;
- route/API health verified;
- required background jobs/timers confirmed;
- real-data behavior verified;
- authenticated browser flow verified when auth is required;
- mobile viewport verified for mobile-supported features;
- no known P0/P1 defect contradicts the completion claim.

---

# 10. HARD PICK-VALUE ACCEPTANCE GATE THROUGH 2029

C cannot complete while any valid supported pick through 2029 is missing a canonical value.

Required automated census:

```text
for every supported league
for every season from current rookie class through 2029
for every supported round
for every real owned pick
for every exact slot when known
for every generic/future representation when slot is unknown
    canonical value exists
    value is finite
    value is not zero-as-missing
    identity is stable
    provenance/method is stamped
    rankings == trade == API == export == ownership == mobile == desktop
```

The tests must distinguish “real zero” from unavailable; a valid draft asset should not use zero as an unavailable sentinel.

Package/Value Adjustment may change the **trade evaluation**, but must never mutate the pick's canonical value.

---

# 11. TRADE-CALCULATOR / REAL-TRADE END-STATE GATE

Before the mature Trade Calculator can be called complete, every requirement in `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` must be classified as:

- **IMPLEMENTED + DEPLOYED + VERIFIED**, or
- **EXPLICITLY REPLACED BY A SUPERIOR CHASE UPSIDE IMPLEMENTATION** with the owner-approved reason recorded.

“Not copied from KTC” is not a valid reason to omit a useful workflow. Chase Upside should adopt strong observable product concepts while using its own canonical data, calculations, branding, and Premium Sports Intelligence UI.

At minimum the mature calculator must have:

- two-sided asset builder;
- canonical player/pick values;
- all supported picks through 2029;
- explicit raw totals versus Value Adjustment;
- clear favored side and amount needed to even;
- player/pick equalizer suggestions;
- shareable trade URLs;
- recent accepted trades;
- searchable Dynasty Trade Database;
- comparable trades with format context;
- total value exchanged visualization;
- historical multi-asset trends;
- Quick Facts;
- dispersion and historical value-span analysis;
- riser/faller context;
- explainers;
- mobile/desktop parity;
- canonical-value parity tests.

---

# 12. PREMIUM SPORTS INTELLIGENCE PRESERVATION RULE

Direction A / Premium Sports Intelligence remains the permanent visual north star unless the owner explicitly changes it.

C implementation must not accidentally produce a second incompatible visual system because features were built before their final migration. During C:

- new reusable components should be compatible with the Premium direction where practical;
- unstable workflows may remain on temporary presentation until their contracts are stable;
- do not spend major effort polishing UI that will immediately be replaced;
- do not delay correctness foundations just to finish a reskin;
- once the migration gate is met, move production incrementally and verify every route.

The end of C should not leave major user-facing features stranded on an abandoned visual architecture unless the owner explicitly accepts a later migration phase.

---

# 13. C-SERIES COMPLETION AUDIT

After the last planned C implementation phase, run a dedicated **C-Series Completion Audit**. It is not optional.

## 13.1 Scope closure

- regenerate the C Scope Manifest from all canonical owner records and later addenda;
- prove every approved row is closed;
- compare planned scope versus routes/APIs/jobs/components actually deployed;
- inventory any unlisted user-facing feature discovered during C;
- ensure no approved feature is only on an unmerged branch, in mock/reference code, or hidden behind a dead flag.

## 13.2 Canonical-truth audit

Verify site-wide parity for:

- player identity;
- player value;
- picks/ownership/value through 2029;
- league/scoring configuration;
- Team Strength/Weakness;
- lineup/replacement/impact;
- trade package/VA/simulation;
- history/value-at-time;
- projections/probabilities;
- Buy/Sell/Consensus/Sharp/Analyst outputs.

## 13.3 Browser / workflow matrix

Exercise the real authenticated application on desktop and true mobile widths across the major routes and workflows, including populated/empty/stale/error states.

At minimum cover:

- Rankings;
- Universal Player Profile;
- Trade Calculator / Trade Desk / 3+ team;
- Trade Finder / Suggestions / Package Builder;
- Waivers / FAAB / Perfect Waivers;
- Draft / Perfect Draft / pick tools;
- Team/Roster intelligence;
- Market / Sharp / Insider / Analyst Intelligence;
- Playoff / Power / Game Day;
- Command Center / Portfolio;
- authenticated League navigation;
- public League surfaces;
- Upside Report / Awards / history / sharing.

## 13.4 Data / background jobs

Verify all required scrapers, imports, history writers, snapshotters, materializers, queues/timers/workflows, retention, last-known-good behavior, and freshness alerts are live and observable.

## 13.5 Performance

Measure representative route/useful-state latency and critical interaction p95s. A route that violates the global standard remains defective even if functionally correct.

## 13.6 Security / privacy / auth

Re-run public/private exposure tests, auth/session behavior, mutation authorization, secrets/credential boundaries, export privacy, and public League redaction.

## 13.7 Final regression

Run all blocking backend/frontend/contract/lint/audit/E2E gates on the final exact head and then run production verification on the deployed merge.

---

# 14. NO-SILENT-DEFERRAL RULE

At C completion there must be **zero** approved features in an ambiguous state such as:

- “planned later”;
- “mostly done”;
- “backend exists but no UI”;
- “page exists but engine is disconnected”;
- “works on desktop only” when mobile parity is required;
- “tests pass but production not checked”;
- “mocked/scaffolded”;
- “flagged off” without an explicit owner-approved reason;
- “unpriced” for a valid supported pick through 2029;
- “waiting for another phase” when C is that final phase.

A genuine external blocker must be brought to the owner as a concrete decision **before** C can be declared complete.

---

# 15. FINAL COMPLETION PHRASE

Claude may state the following only after every gate above has passed and the final production evidence is recorded:

> **`C-SERIES COMPLETE — EVERY APPROVED FEATURE DEPLOYED, PRODUCTION-VERIFIED, AND READY FOR CONFIDENT USE`**

If any approved feature is still missing, partial, disconnected, unverified, materially slow, mobile-incomplete where required, using mock data, carrying contradictory canonical truth, or dependent on an unresolved blocker, **do not use that phrase**. State the exact remaining blocker instead.
