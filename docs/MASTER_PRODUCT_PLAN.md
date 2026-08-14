# Chase Upside — Master Product Plan

**Status:** CANONICAL FRONT DOOR FOR LONG-RANGE PRODUCT DIRECTION  
**Owner direction synchronized through:** 2026-08-14  
**Current product name:** **Chase Upside**  
**Repository/history note:** `riskittogetthebrisket`, “Risk It To Get The Brisket”, and “Brisket” remain valid legacy repository/league/history identifiers where the code or historical record requires them.

> Start here for every material product, roadmap, feature, architecture-direction, or implementation-planning task.  
> **Use `docs/EXECUTION_PLAN.md` for what is authorized now. This file does not itself authorize starting a phase.**

---

# 1. PRODUCT NORTH STAR

Chase Upside is an integrated, explainable, roster-aware **dynasty fantasy-football decision-intelligence platform** — not merely a rankings page, trade calculator, or league dashboard.

For an important player, roster, league, trade, waiver move, draft choice, or weekly decision, the product should progressively answer:

1. What is happening?
2. Why is it happening?
3. What does the dynasty market think?
4. What do strong managers, analysts, news, projections, and fundamentals imply?
5. How does this exact league change the answer?
6. How does this exact roster change the answer?
7. What should the user actually do next?
8. Can Chase Upside help execute, track, explain, or revisit that action safely?

A useful shorthand:

> KTC tells the user what the market thinks an asset is worth. Chase Upside should tell the user whether **this user, with this roster, in this league** should buy, sell, hold, stash, claim, bid, draft, target, trade away, or otherwise act on that asset — and why.

The product-quality order is:

**Correctness → reliability → performance → explainability → presentation.**

Public and private products have different missions:

- **Authenticated/private Chase Upside:** Front Office + War Room + decision intelligence.
- **Public `/league`:** League Museum + Sports Network + Game Day — factual, retrospective, competitive, entertaining, shareable, but without leaking proprietary decision intelligence.

---

# 2. AUTHORITY / DOCUMENT PRECEDENCE

Multiple documents are useful only when each has one job. They must not become competing roadmaps.

## 2.1 Core authority

| Question | Canonical record |
|---|---|
| Where do I start? | `PRODUCT_PLAN.md` |
| What is the long-range product direction and which policy wins? | **`docs/MASTER_PRODUCT_PLAN.md`** (this file) |
| What work / phase is authorized now? | **`docs/EXECUTION_PLAN.md` — only current sequencing/authorization record** |
| Which planning records are active, supplemental, evidence, or historical? | `docs/PLANNING_DOCUMENT_STATUS.md` |
| How was the planning layer synchronized? | `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md` |
| What is the exhaustive discussion-derived feature coverage ledger? | `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` |
| What does newer owner intent require in detail? | `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` + Appendix + feature-specific binding specs |
| What older detailed feature intent remains active where not superseded? | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| What compact owner requests remain durable? | `docs/OWNER_REQUESTED_TODO.md` + `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` |
| How must the eventual C-series be replanned, executed, deployed, and closed? | `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` |
| What are technical operating rules? | `CLAUDE.md`, current ADRs, live code, architecture records |
| What was measured at a pinned historical state? | `docs/master-site-audit/` and other evidence records |

## 2.2 Precedence when records conflict

Use this order for **product intent and direction**:

1. most recent explicit owner instruction;
2. this Master Product Plan;
3. binding current feature-specific owner specs / reconciliation / later owner addenda;
4. `OWNER_PRODUCT_BACKLOG_SPEC.md` where not superseded;
5. approved C-Series Execution Plan once one is created after the B→C gate;
6. current ADRs/architecture decisions for implementation mechanics;
7. dated inventories, evidence, research, old roadmaps, old session captures, and PR prose.

Use **`EXECUTION_PLAN.md` alone** to answer “what may we implement next?” A long-range feature being approved does not authorize beginning it.

Verified repository/runtime evidence controls what is **actually implemented**. It may prove a status sentence stale, but existing behavior does not silently override newer owner intent merely because the code currently behaves that way.

---

# 3. GLOBAL PRODUCT / MODEL INVARIANTS

These apply across the product unless a later explicit owner decision supersedes them.

## 3.1 One concept, one canonical owner

Pages are consumers. They do not create local alternative truths for player identity, asset value, pick identity/value, league configuration, realized scoring, Team Strength, Team Weakness, lineup assignment, replacement/PAR/VORP, package generation, trade simulation, projection/probability, history, Analyst Intelligence, Sharp cohort, manager evidence, or confidence.

If a canonical owner is defective, repair or replace that owner deliberately. Do not make a page-local workaround that quietly becomes a second engine.

## 3.2 Missing is never zero

Unavailable, stale, unsupported, partial, unpriced, unproven, or unobserved is not zero and not certainty. The product must preserve explicit missing/degraded states.

Examples: no projection ≠ 0 points; no trade comps ≠ $0 market value; no analyst take ≠ HOLD; unknown scoring compatibility ≠ compatible; missing assignment data ≠ an empty legitimate lineup; missing historical value ≠ today's value.

## 3.3 Provenance, freshness, confidence, and independence are first-class

Every meaningful signal should be able to say what population it represents, when it was observed, how much coverage exists, what source/family produced it, and whether another displayed signal is merely a descendant of the same evidence.

Repeated, syndicated, cross-platform, or derived copies of one thesis do not become independent votes.

## 3.4 Facts and opinions remain distinct

News/factual status is not an analyst recommendation. Market behavior is not a projection. A simulator centered on canonical value is not an independent valuation source. Descriptive roster exposure is not automatically a trade penalty.

## 3.5 Historical truth is immutable/versioned

Trade-time values, acquisition history, weekly reports, prediction snapshots, award seasons, model versions, and historical rankings must be reconstructable from the methodology/input state that produced them. Today's model must not silently rewrite yesterday's fact.

## 3.6 Expensive work belongs off the interactive path

Prefer:

**acquire → normalize → background expensive work → materialize/index/cache → serve fast → refresh asynchronously**.

Last-known-good/stale-while-revalidate behavior is a product feature when it is defensible. Slow or failed refreshes should not unnecessarily blank valid prior data.

## 3.7 Model promotion is human-governed

**collect → provenance/history → train challenger → backtest → out-of-sample validate → compare with production → stability/calibration review → explicit approval → promote → monitor → rollback**.

No production model or weight silently self-promotes.

## 3.8 Recommendations and execution are separate

An AI/model recommendation never silently mutates the league. Mutations require the canonical authorization path, explicit league/team context, appropriate preview/confirmation, idempotency/error handling, and an audit trail.

---

# 4. BINDING CONFLICT RESOLUTIONS

These are explicitly synchronized so older documents cannot accidentally reverse them.

## 4.1 One canonical player-value methodology today

PR #822 evaluated the existing league-aware valuation lens and **rejected it as canonical** under the outcome-evidence bar. Current production therefore has **one canonical player-value methodology**. Experimental league-adjusted outputs may remain as research/diagnostic artifacts, but they may not overwrite canonical value, rank, or tier and there is no user-selectable “Market vs My League” canonical basis.

This is not a permanent rejection of league-aware valuation as a product goal. A future replacement must earn promotion through evidence and the human-governed model lifecycle.

## 4.2 Every valid supported pick through 2029 must have value by C completion

Older wording that allowed valid 2028/2029 picks to remain indefinitely unpriced is superseded.

By C completion, **every valid league-supported draft-pick asset through the 2029 rookie class must have a finite, non-missing canonical Chase Upside value**.

Unknown exact slot is handled with a documented generic/future-pick value or probability distribution with uncertainty/provenance. When the exact slot becomes known, the same stable owned-pick identity transitions to exact-slot valuation without duplicate assets or double counting. Mobile, desktop, APIs, exports, Rankings, Trade, ownership, and history must agree.

Missing source evidence still must never be represented as zero.

## 4.3 Player MVP has no hard playoff / >.500 eligibility gate

The later Player Impact / Fantasy WAR / MVP specification supersedes older player-MVP eligibility wording. Player MVP has **no hard playoff-field or >.500 requirement**. Team success may be context/tie-break evidence. Manager of the Year may use appropriately validated team-success eligibility. Player, manager, and GM/executive awards remain conceptually distinct.

## 4.4 Exact KTC Value Adjustment is an advisory market lens

Exact KTC-style Value Adjustment remains a trusted market/consolidation lens and may preserve real KTC non-monotonic behavior in parity mode. It is **not canonical player value**, not Team Strength, and not roster marginal impact.

Do not invent “Our VA” merely to have one. A proprietary package scalar must have a defined target and prove incremental information beyond raw canonical equity + KTC VA + before→apply→rerank→after roster impact.

## 4.5 Team Strength, Power Rankings, Playoff Predictor, and Standings are different truths

- **Team Strength:** dynasty roster/asset strength.
- **Power Rankings:** current-season team quality/performance.
- **Playoff Predictor:** future playoff/championship probabilities using schedule and uncertainty.
- **Standings:** official realized outcomes.

None may quietly substitute for another.

## 4.6 Product name

The product is **Chase Upside**. Legacy repository, league, infrastructure, historical artifact, and code identifiers should not be blindly renamed when their identity is operational or historical.

---

# 5. CURRENT FOUNDATION PROGRAM

`EXECUTION_PLAN.md` owns authorization; this is only the synchronized high-level dependency state.

As of this synchronization:

- **B4** percentile-tail saturation — complete/accepted (#805).
- **B5** canonical player identity — complete/accepted (#806).
- **B6** league/scoring identity correctness — merged/verified (#810; operational verification #819).
- **B7** realized-scoring correctness — merged (#820).
- **B8** public/private distribution boundary — merged (#821).
- **Out-of-band canonical-value correction** — #822 merged; one canonical value methodology restored and the unvalidated league lens withdrawn from canonical serving.
- Remaining Fast Lane dependency order: **B9a → B9b → B10 → B11**.
- After B11: **STOP. No automatic C1.** Apply the hard B→C replan gate in `EXECUTION_PLAN.md` and `C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`.

---

# 6. FEATURE SCOPE / PRODUCT FAMILIES

This file deliberately does not duplicate the exhaustive feature ledger. The full union is `OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` plus the active detailed specs classified by `PLANNING_DOCUMENT_STATUS.md`.

Every approved feature must be mapped to one of the canonical product families below or explicitly identified as a new family during reconciliation.

## 6.1 Canonical asset / valuation foundation

Player identity; stable pick identity; canonical player/pick value; source-native observations; normalization; scoring/league identity; provenance/freshness/confidence; value/history snapshots; acquisition/cost-basis/asset lineage; source independence and anti-circularity.

## 6.2 Roster / lineup / player-impact foundation

Exact best-ball/lineup assignment; replacement; PAR/VORP; Team Strength; Team Weakness; roster displacement; Dropability; before/after roster application; Player Impact including Realized Lineup VORP, WAR, xWAR, Wins Above Bench, and Game Changer primitives.

## 6.3 Trade decision system

Trade Calculator; two-team and 3+ team correctness; raw value vs exact KTC VA; Analyze Trade; Second Opinions; Monte Carlo uncertainty; equalizers/amount-to-even; Trade Finder; Suggestions; Package Builder; Golden Upgrades; Trade Desk; shareable trades; real-trade database/comparables; market evidence and trade history/aging.

Binding detailed expansion: `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`.

## 6.4 Waiver / FAAB / rookie-draft system

FAAB objective ceiling vs recommended bid; own-league and broader market evidence; Perfect Waivers; roster-aware drops; protected/untouchable assets and intentional QB handcuff policy; Perfect Draft / Draft Room; stable real picks and complete future-pick valuation.

## 6.5 Market / Sharp / Analyst / Manager intelligence

Retail market, real-trade market, Sharp cohort/transactions/roster %, specific-manager evidence, Podcast/YouTube Analyst Intelligence, news/facts, central Buy/Sell, Consensus Edge, source-family/thesis dedupe, stance/freshness/context semantics, and future X ingestion only when justified.

## 6.6 Universal Player Profile

One progressively disclosed player truth surface composed from canonical identity/value, source provenance, history, market, fundamentals, projections/stats/PAR/impact, roster context, Sharp/manager/analyst intelligence, news, acquisition history, and public-safe historical content.

## 6.7 Seasonal competition / simulation

ROS/current-season projection, Playoff Predictor, Weekly Power Rankings, Game Day Command Center, current-window context, standings/league-median simulation, pregame/live probability, calibration archives, and exact custom scoring/best-ball semantics.

## 6.8 Public League Experience

Public League v3, league history/longevity, Franchise Passports, rivalries, records, Player Journeys, trade/draft history, public-safe power/playoff/game-day, Upside Report, Awards & Honors, Hall/Ring, yearbooks/wrapped, public draft/game broadcast, sharing — while protecting proprietary decision intelligence.

## 6.9 Front-office orchestration / presentation

Command Center, Trade Desk, Portfolio, personalized feed/push, Compare/personal rankings, Share Renderer, Premium Sports Intelligence visual system, responsive/mobile parity, accessibility, and consistent fast-loading contracts.

## 6.10 Model / continuous-improvement infrastructure

Human-governed challenger lifecycle, archival/backtest datasets, no-lookahead validation, adaptive weighting only after evidence, calibration, model-version provenance, performance/observability, deployment verification, and rollback.

---

# 7. PERSONALIZATION VS GLOBAL TRUTH

User/team policies — such as protected assets, intentional starting-QB + primary-backup handcuffs, team-specific trade-away preferences, selected-team context, or personal rankings — belong in explicit personalization/action layers.

They do not silently rewrite the global canonical market value. A personalized recommendation may say “do not move this player” while the player's canonical value remains unchanged.

---

# 8. PERFORMANCE / UX BASELINE

Unless a stricter feature contract exists:

- warm/cached first useful state: **≤1 s** target;
- normal production p95: **≤2 s** where reasonable;
- preferred cold useful state: **≤3 s**;
- **≤5 s** is an absolute useful-state failure ceiling, not a target;
- local interaction response: **<250 ms**;
- visible acknowledgement/loading state: **<100 ms**;
- no indefinite spinner hiding a long operation;
- mobile and desktop must consume the same canonical truth and methodology.

Premium Sports Intelligence is the approved visual north star, but UI migration must not get ahead of unstable contracts or delay correctness foundations. Build reusable components so the final migration does not require reimplementing business logic.

---

# 9. C-SERIES END STATE

C is not “the roadmap was executed.” C is complete only when the exhaustive post-B C Scope Manifest is closed under the standards in `C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`.

Every owner-approved capability must be implemented at the correct architectural layer, connected to real canonical data, reachable to the intended user, deployed, performant, mobile/desktop capable where required, observable, reversible, and production-verified strongly enough for confident use.

There are no silent “later” buckets at C completion. A genuine external blocker requires an explicit owner disposition before C can be declared complete.

The reserved completion phrase may be used only after the final audit passes:

> **`C-SERIES COMPLETE — EVERY APPROVED FEATURE DEPLOYED, PRODUCTION-VERIFIED, AND READY FOR CONFIDENT USE`**

---

# 10. MAINTENANCE RULE

When owner intent materially changes:

1. update the detailed canonical spec that owns the behavior;
2. update the owner feature/backlog ledger if scope/status changes;
3. update this Master Product Plan only when long-range direction, precedence, product families, or a global invariant changes;
4. update `EXECUTION_PLAN.md` only when current authorization/sequence changes;
5. update `PRODUCT_DIRECTION_SYNC_MANIFEST.md` when a new planning/direction record is introduced or reclassified;
6. preserve historical evidence rather than rewriting it to pretend it always agreed.

A one-line TODO, stale inventory row, competitor screenshot, old roadmap, old PR description, or current implementation quirk cannot independently redefine Chase Upside.
