# Risk It To Get The Brisket — Master Product Plan

**Status:** CANONICAL FRONT DOOR FOR PRODUCT DIRECTION  
**Owner direction reconciled through:** 2026-08-12  
**Purpose:** Give every future Claude/ChatGPT/Codex session one place to answer: *What are we building? What are we not building? What does each feature mean? What is private vs public? What comes next? Which document wins if records disagree?*

> **Start here for every material product, roadmap, architecture, or implementation-planning task.**
>
> This file is the single front door. It does not duplicate every audit artifact or implementation detail. It tells you which subordinate record is canonical for each question and prevents old capture documents from becoming competing roadmaps.

---

# 1. PRODUCT NORTH STAR

Risk It To Get The Brisket is not merely a dynasty calculator. It is intended to become a deeply integrated, explainable, league-aware **dynasty decision-intelligence platform**.

The private product should increasingly answer:

1. **What is happening?**
2. **Why does it matter?**
3. **What should I do?**
4. **What happens to my roster if I do it?**
5. **What has the real dynasty market paid?**
6. **What are strong managers doing?**
7. **What does this league manager tend to do?**
8. **What do analysts, news, projections, and fundamentals say?**
9. **Can I execute the action from the app safely?**

The public league product has a different mission:

> **Public `/league` = League Museum + Sports Network + Game Day.**  
> **Private authenticated app = Front Office + War Room.**

Public pages should maximize league history, identity, rivalry, live-game entertainment, records, awards, storytelling, and shareability **without exposing competitive decision intelligence**.

---

# 2. DOCUMENT HIERARCHY — WHICH RECORD ANSWERS WHICH QUESTION

The product plan is intentionally split by responsibility. Multiple documents are acceptable; multiple competing sources of truth are not.

| Question | Canonical record |
|---|---|
| What is the overall product direction and which document wins? | **`docs/MASTER_PRODUCT_PLAN.md`** (this file) |
| What features exist, are planned, removed, defective, or evidence-gated? | **`docs/OWNER_FEATURE_INVENTORY.md`** |
| What does an approved feature actually mean; what UX/methodology/public-private behavior was decided? | **`docs/OWNER_PRODUCT_BACKLOG_SPEC.md`** plus the detailed reconciled requirements in this file |
| What is the current authorized execution sequence/checkpoint? | **`docs/EXECUTION_PLAN.md`** |
| What are the canonical owners/system boundaries and technical invariants? | **`docs/ARCHITECTURE_HANDOFF.md`**, current ADRs, and live code evidence |
| What defects were measured and what evidence supports them? | **`docs/master-site-audit/`** |
| What competitor ideas/research informed approved scope? | **`docs/competitive/`** — research input only, never an independent execution roadmap |
| Who is editing what right now? | **`docs/WORK_CLAIMS.md`** |

## Precedence when records conflict

Use this order:

1. **Most recent explicit owner instruction.**
2. **This `MASTER_PRODUCT_PLAN.md`.**
3. **`OWNER_PRODUCT_BACKLOG_SPEC.md` for intended feature behavior/methodology.**
4. **`OWNER_FEATURE_INVENTORY.md` for feature existence/status/classification/dependency.**
5. **Current canonical ADR/architecture decisions.**
6. **`EXECUTION_PLAN.md` for sequencing and current authorization.**
7. **Verified audit evidence/findings for defect facts.**
8. **Older addenda, capture lists, checkpoints, roadmaps, and session handoffs.**
9. **Existing implementation behavior.**

Important nuance: live code or executable evidence may prove a *status statement* stale. Existing code does **not** override a newer owner product decision merely because that is how the site currently behaves.

---

# 3. GLOBAL PRODUCT / MODEL INVARIANTS

These apply to every future feature unless an explicit later owner decision supersedes them.

## 3.1 One concept, one canonical owner

Pages and features consume canonical systems; they do not independently reimplement them.

Canonical ownership is required for at least:

- player identity;
- pick identity;
- league settings/scoring identity;
- canonical player value;
- canonical pick value;
- historical value snapshots;
- Team Strength;
- Team Weakness / Need Priority;
- replacement level / PAR;
- package generation;
- package/market adjustment semantics;
- trade simulation;
- trade decision synthesis;
- acquisition history;
- projections;
- realized scoring;
- ADP;
- broad-market transactions;
- Sharp transactions/cohort;
- Analyst Intelligence;
- manager intelligence;
- public-information classification;
- league actions/mutations;
- share rendering;
- confidence/coverage;
- provenance.

If a canonical owner is defective, repair it. Do not create a page-local workaround that becomes a second owner.

## 3.2 Missing is never zero

No FAAB history ≠ $0. No projection ≠ 0 points. No trade comps ≠ zero market value. No Sharp activity ≠ dislike. No analyst take ≠ neutral/sell. Unobserved manager behavior ≠ never. Unknown pick forecast ≠ late pick. Missing historical value ≠ today's value. Unresolved player identity ≠ best fuzzy guess.

Every decision surface must preserve explicit missing/insufficient/unsupported/stale/unavailable states.

## 3.3 Signal lineage / independence

A body of evidence normally affects a final conclusion **once**. KTC, a consensus that contains KTC, Monte Carlo centered on canonical value, and an edge score derived from the same board are correlated descendants — not four independent votes.

Before adding any signal, identify:

- observation population;
- overlap with existing signals;
- correlation group;
- sample size;
- freshness;
- coverage;
- missing behavior;
- provenance.

## 3.4 Champion is not challenger

Evaluation is not production activation. Fit → backtest → validate → compare → owner/human approval → promote/apply → monitor → rollback. No model or weight silently self-promotes.

## 3.5 Pinned inputs for methodological comparisons

Record code SHA, source hashes, board/snapshot hash, model version, scoring configuration, and timestamp. Do not compare outputs across refreshed inputs and attribute the difference to code.

## 3.6 Recommendation and execution are separate

AI/model recommendations must never silently execute league actions. Mutations require canonical auth/authorization, explicit league/team, appropriate preview/confirmation, idempotency, error handling, and an audit trail.

## 3.7 Owner overlays are not global value rules

- Minnesota Vikings players are effectively untouchable for the owner's personalized recommendations.
- Starting-QB + primary-backup QB handcuffs are intentional and should not be broken solely for diversification.

These personalize decisions. They do not change canonical league-wide player values.

---

# 4. MASTER FEATURE MAP

`OWNER_FEATURE_INVENTORY.md` remains the exhaustive row-level ledger. This section defines the unified product families so isolated ideas cannot drift into parallel systems.

## 4.1 Canonical roster intelligence

### Team Strength

**Goal:** one canonical answer to “How strong is this dynasty roster?” based on the meaningful upper roster, not a raw sum of every bench asset.

Owner-approved initial roster-value groups:

- QB: top 3
- RB: top 3
- WR: top 5
- TE: top 3
- DL/EDGE: top 5
- LB: top 5
- DB: top 5

Use canonical league-adjusted player values and the league's real positional model. Team Strength is dynasty roster strength; it is **not** Power Ranking, Playoff Odds, or ROS production.

**Method status:** product definition approved; implementation must prove/consolidate competing existing strength notions before becoming canonical.

### Team Weakness / Need Priority

One canonical starting-slot weakness model. Existing owner thresholds include:

- QB1 Top 12; QB2 another Top 24;
- RB1 Top 12; RB2 Top 24;
- WR1 Top 12; WR2 Top 24; WR3 Top 36;
- TE1 Top 12; TE2 Top 24;
- IDP thresholds derive from required slots × league size;
- FLEX/Superflex thresholds derive from actual league configuration and must avoid double counting already allocated players.

Need Priority must agree with the canonical lineup/assignment solve. An `urgentNeed` flag that contradicts the actual roster solve is a defect, not an alternate opinion.

### Roster-aware trade simulation

Apply a proposed transaction to real before/after rosters, rerank/reassign, and expose:

- positional promotions/displacements;
- Team Strength before/after;
- weaknesses fixed;
- weaknesses created;
- meaningful lineup/depth changes;
- value-weighted NFL-team exposure before/after (informational only).

Do not reduce this to outgoing-value minus incoming-value.

### Dropability / cut candidates

FLEX/Superflex make droppability set-dependent. Use the canonical lineup/matching/displacement machinery rather than naïve per-position counts. A candidate is droppable only after accounting for the remaining roster's ability to fill required/flex slots.

### Untouchable / excluded-player control

One user-level exclusion mechanism consumed by Trade Finder, Suggestions, Package Builder, Golden Upgrades, waiver/drop optimizers, and relevant draft tools. Do not implement per-page exclusion lists.

---

## 4.2 Trade decision system

Detailed canonical requirements live in `OWNER_PRODUCT_BACKLOG_SPEC.md` §§1–2.

The unified architecture is:

**canonical asset values** + **exact KTC Value Adjustment as an advisory market-consolidation lens** + **canonical before→apply→rerank→after roster marginal impact** + **future independent evidence** → **one Analyze Trade decision owner**.

Required products include:

- two-team and 3+ team Trade Calculator reliability;
- exact KTC-parity Value Adjustment, visibly secondary/advisory;
- Analyze Trade;
- Second Opinions tally;
- Monte Carlo re-audit before treating its percentage as meaningful;
- Golden Upgrades as a consumer, not a second engine;
- Package Builder using the shared package-generation engine;
- Trade Finder and Trade Suggestions repairs/consolidation;
- multi-team draft-pick destination correctness;
- trade equalizer suggestions ranked by **post-active-Value-Adjustment gap**, without double-applying VA;
- acquisition/holding-period history;
- **Your Cost Basis** on outgoing assets;
- value-weighted NFL-team exposure before/after.

Cost basis is informational and must not introduce sunk-cost bias.

---

## 4.3 Picks / draft assets

Future picks are first-class assets with stable season + round + original owner + current owner identity.

Keep separate:

- generic market value of a round/year pick;
- specific pick forecast/distribution;
- current ownership;
- historical acquisition/lineage;
- market comps.

CE-02 Pick Forecast is private decision intelligence. Public `/league` may show factual pick ownership but not internal projection distributions/expected values.

Far-future picks (including 2028/2029 where configured) remain explicitly unpriced if defensible valuation does not exist; never convert missing to zero.

---

## 4.4 Waivers / FAAB / rookie draft

### FAAB

Preserve the conceptual separation already established:

- **objective ceiling:** what the player is worth in league-budget terms;
- **recommended bid:** what this specific team should bid given balance, roster/drop side, timing, and market-clearing evidence.

One canonical FAAB engine. Do not recreate bidding math in the frontend. Historical own-league bids and broader crowd/market bids are different populations and remain distinct. Zero-dollar claims are real observations; missing history is not zero.

### Perfect Waivers

Build a whole-roster optimizer answering “Which *combination* of adds and drops should I make?” rather than ranking free agents independently. Reuse canonical dropability/lineup matching, Team Strength/Weakness, canonical player values, and FAAB. Include an explicit stop rule when no additional transaction improves the roster enough to justify it.

### Perfect Draft

Keep the existing combination/budget optimizer and its matching/displacement foundations. Preserve the requirement for a pre-auction snapshot so future backtesting is actually possible. A manager's recommended maximum bid can never exceed remaining budget. Do not reintroduce per-team rookie-slot assumptions that the auction format does not have.

---

## 4.5 Market / Sharp / Analyst / Manager intelligence

Keep the populations distinct:

- **KTC / retail crowd** — broad retail/crowd market;
- **Market Trade Ledger (CE-01)** — real broad-market completed transactions;
- **Sharp Ledger / Sharp cohort** — curated high-skill manager behavior;
- **Insider / Manager Scout (CE-03)** — specific league-manager behavior;
- **Analyst Intelligence** — structured opinions from podcast + YouTube (future X only if economics justify it);
- **BDVM** — independent fundamentals/projections;
- **Canonical** — the site's conclusion.

### Sharp systems

Sharp Tracker and Sharp Roster Percentage must share the same canonical Sharp cohort. Roster % denominator rules, source coverage, sample size, freshness, and deduplication must remain explicit. The 7/14/30-day views must not double-count the same transaction/observation merely because it appears in multiple windows.

### Analyst Intelligence

Detailed taxonomy, cross-platform dedupe, price context, direction-vs-confidence separation, event/type-aware freshness, historical validation, and bounded Consensus Edge use are in `OWNER_PRODUCT_BACKLOG_SPEC.md` §4.

Important reconciliation from owner capture records:

- transcript retention and signal validity are separate;
- a ~7-day discovery window is not universal 7-day voting permission;
- injury/pregame/game-specific takes may expire immediately when the underlying event occurs or assumptions change;
- no universal Sunday reset; use the affected player's actual event timeline;
- older intelligence can remain visible as historical context after it stops voting;
- freshness modifies a signal and does not become another vote.

### Central Buy/Sell

One canonical reconciled verdict owner. Existing page/ticker/feature emitters must ultimately consume it rather than maintain independent threshold sets. Homepage rule: BUY may be global; SELL only players on the selected fantasy roster.

---

## 4.6 Universal Player Profile

Detailed spec: `OWNER_PRODUCT_BACKLOG_SPEC.md` §8.

Every player click should converge on one canonical profile with progressive disclosure across identity, canonical value/rank/tier/confidence, market, BDVM/fundamentals, projections/stats/PAR, roster context, acquisition/holding periods, Sharp, Insider, Analyst Intelligence, and factual news.

Public-safe player pages expose league journey/history and facts but not private decision intelligence.

---

## 4.7 Public League Experience v3

Detailed spec: `OWNER_PRODUCT_BACKLOG_SPEC.md` §§9–10.

The public league experience must actively **remove/privatize** edge as well as add entertainment.

Private examples:

- detailed ROS/team-strength internals;
- Buyer/Seller Trade Deadline recommendations;
- Pick Forecast probabilities/expected values;
- proprietary Draft Capital dollar valuation/effective auction power/trade simulator;
- manager tendencies/exploitation intelligence;
- Buy/Sell, roster weaknesses, trade targets, canonical edge conclusions.

Public-safe examples:

- standings, scores, rosters, factual pick ownership;
- completed trades/draft history;
- sanitized Power, Luck, Streaks, public playoff/championship odds;
- Franchise Passports;
- Rivalries and Rivalry Receipts;
- Player Journeys;
- records/milestones;
- Hall of Fame / Ring of Honor;
- Championship Paths;
- Brisket Wrapped / Season Yearbooks;
- On This Day / This Week in League History;
- Trade Trees;
- Draft Class Reunions;
- Game of the Week;
- Bad Beat / Miracle Win cards;
- public Pick'em;
- public-safe Draft broadcast;
- public Game Day / League RedZone-style experience;
- shareable cards.

Historical truth comes before historical glitter: retired franchises, complete reconstructable seasons, “all-time” semantics, scoring/ownership coverage, and season labels must be correct first.

### Brisket Honors / Awards & Honors v2

Use **Realized Lineup VORP** for player awards: only actual fantasy starts contribute; bench production contributes zero award value; negative VORP remains negative; replacement baseline comes from the broader available player pool through one canonical season/format-specific replacement owner.

Awards include MVP, OPOY, DPOY, OROY, DROY, positional awards, Postseason MVP, Championship MVP, Best Offense, Best Defense, All-Brisket First/Second Team, top-five award races, player/franchise trophy cabinets, and objective secondary honors where data supports them.

2024 and 2025 are explicitly approved for retroactive inaugural awards using the same methodology adopted for the first live 2026 awards.

Manager of the Year and GM/Executive of the Year must remain conceptually distinct and historically tested before inaugural finalization. Detailed initial formulas and validation requirements live in `OWNER_PRODUCT_BACKLOG_SPEC.md` §10.5.

---

## 4.8 Game Day

CE-20 is approved, not vague optional scope.

One canonical best-ball-aware matchup projection/win-probability engine should power private and public-safe views. A provisionally filled best-ball slot is not final while remaining roster outcomes can displace it. Exact custom scoring matters; unsupported projected scoring components remain uncertain or are estimated only via defensible historical conditional models.

Archive pregame/in-game predictions and measure calibration/error without leakage. Start with a useful low-cost V1; paid second-by-second data is optional only if usage justifies cost.

Private Game Day may include personalized actionable intelligence. Public Game Day remains broadcast/entertainment information.

---

## 4.9 Competitive expansion — unified CE roadmap

Approved concepts from OTC Fantasy, Play For Keeps, and Dynasty Daddy are one roadmap, not three independent competitor roadmaps.

- **CE-01** Market Trade Ledger / Trade Database
- **CE-02** Pick Forecast
- **CE-03** Manager Scout
- **CE-04** Dynasty Command Center
- **CE-05** Trade Desk
- **CE-06** Dynasty Portfolio
- **CE-07** Market ADP
- **CE-08** Projections & Stats Hub
- **CE-09** Replacement Value / PAR
- **CE-10** Share Renderer / Team Cards
- **CE-11** Sleeper Action Gateway
- **CE-12** Lineup Intelligence
- **CE-13** Draft Room
- **CE-14** Market Pulse
- **CE-14A** Personal Rankings Overlay
- **CE-15** Portfolio Trade Campaign — no automatic bulk spam
- **CE-16** Trade Polls — optional/future
- **CE-17** League Format / Utilization Lab
- **CE-18** Trade Trees / Asset Lineage
- **CE-19** Waiver Market / FAAB Market Ledger
- **CE-20** Game Day Command Center
- **CE-21** Dynasty Season Recap / Wrapped

Dynasty Daddy-derived enrichments to CE-03/04/06/09/11/12/13/14A/15 and Universal Player Profile remain approved, but must extend existing canonical owners rather than become competitor-copy engines.

Competitor research identifies useful user jobs. Never copy branding/design architecture or use unauthorized/private APIs/content.

---

## 4.10 Valuation / scoring / confidence foundations

### Canonical individual value scale

Final canonical individual player and draft-pick values are a **1–9999 product scale**. Raw provider values remain in their native units. Intermediate math and multi-asset/team/portfolio aggregates may exceed 9999. Do not solve out-of-range individual values with a blind clamp that creates elite ties or hides a scaling defect.

### TE premium

Two mandatory TE starters and unusual scoring require evidence, not a blanket 1.15 multiplier. Audit actual scoring, flex demand, replacement scarcity, TE production, every source's basis, KTC TEP++ behavior, and player/rank-dependent uplift where data exists. Native TEP/TE++ inputs must not receive duplicate premium adjustments.

### Realized scoring

One exact-scoring owner. Every nonzero league scoring rule must be either supported/mapped or explicitly reported as uncovered. Missing scoring categories must not silently become zero. Player special teams (`kr_yd`, `pr_yd`, supported `st_*`) belong to the individual player where the host rules do; distinguish them from DST `def_*` scoring.

### League scoring-profile identity

Scoring-profile identity must be derived/validated from actual host scoring configuration, not merely a hand-authored label. Requested-league Sleeper payloads must never combine one league's teams with another league's scoring settings/roster positions and then claim data readiness.

### Confidence

Confidence, coverage, source count, disagreement, freshness, quarantine/anomaly state, and missingness are separate concepts. A player must not become “more confident” because sources disappeared. Any final confidence buckets require empirical validation and honest coverage semantics.

### Source independence

Leave-one-out and lineage-aware comparisons are required where a source is compared with a consensus that may contain that same source. Do not praise agreement created by self-inclusion.

### Historical value snapshots / provenance

Persist model/version/as-of/config provenance and historical board snapshots so acquisition value, backtests, model comparisons, and analyst/market validation can reconstruct what was known at the time. Never backfill a past value using a future snapshot while presenting it as contemporaneous truth.

---

## 4.11 Additional owner-requested requirements reconciled from capture files

These are not separate roadmaps anymore; they are part of this master plan:

- **Admin:** fix `fmtPassExpiry` runtime crash; make temporary-password access work end-to-end with owner-selected validity hours and fail-closed expiry/revocation.
- **Trade manual overrides:** visually silent; one top-level Reset Values; removal clears temporary override; canonical truth unchanged.
- **Trade equalizer:** candidate closeness uses the same active post-VA package math shown by the calculator.
- **Establish The Run dynasty source:** research is preserved but **PAUSED**; do not buy access or implement until owner explicitly resumes it.
- **Individual special teams scoring:** player return/special-teams production must be correctly attributed and backtested.
- **League-specific player fit / college translation:** complete validated NFL player-specific scoring-fit work first; then investigate prospect translation from statistical profiles without directly converting raw college fantasy points into dynasty value. Use shrinkage/stability/OOS validation and keep scoring fit separate from scarcity/market value.
- **X/Twitter Analyst Intelligence:** future/cost-gated only; official/authorized API, no scraping.

---

# 5. PUBLIC / PRIVATE GOVERNANCE

Every material feature must declare one of:

- **PUBLIC**
- **PRIVATE**
- **PUBLIC-SAFE / PRIVATE-INTELLIGENCE SPLIT**

Public classification is semantic, not a field-name game.

Canonical classes:

1. **FACTUAL:** public — scores, standings, rosters, completed transactions, factual pick ownership.
2. **RETROSPECTIVE:** public — records, awards, rivalry history, realized production.
3. **BROADCAST-DERIVED:** potentially public-safe — sanitized Power, luck/streaks, matchup stories, public probabilities.
4. **DECISION INTELLIGENCE:** private — proprietary values, edges, targets, weaknesses, Buy/Sell, pick forecasts, manager tendencies, negotiation/trade recommendations.

A denylist of suspicious JSON keys is a useful secondary defense. It is not the policy.

---

# 6. EXPLICIT REMOVED / REJECTED / PAUSED SCOPE

Do not resurrect without a new owner decision:

- Fantasy Schedule Generator — removed / not applicable.
- Full dispersal-draft system — not approved.
- Standalone rookie-WR model just because a competitor offers one — not approved.
- Generic best-ball suite — not approved; Game Day's best-ball modeling is league-specific.
- Generic article/media CMS — not strategy.
- Social-network/community platform — not approved.
- Automatic bulk trade spam — not approved.
- Competitor branding/design copies — never.
- Money / Constitution / generic League Media — removed/deferred from the current engagement.

Paused, preserve but do not act:

- Establish The Run paid dynasty source until owner explicitly resumes.
- Large X analyst feed until cost/value economics justify it.

---

# 7. CURRENT EXECUTION VS LONG-TERM SCOPE

The fact that a feature appears in this plan **does not authorize immediate implementation**.

Current sequencing and owner checkpoints live in `docs/EXECUTION_PLAN.md`.

Foundation correctness precedes attractive product expansion. A future feature may be read now so current architecture does not contradict it, but it may not be started until its dependencies and owner authorization are satisfied.

---

# 8. HISTORICAL / CAPTURE DOCUMENT GOVERNANCE

The following kinds of documents remain useful evidence/history but are **not independent future-scope authorities** after this reconciliation:

- `UNIMPLEMENTED_BACKLOG.md`;
- `docs/master-site-audit/NEXT_STEPS.md`;
- `docs/master-site-audit/REPAIR_ROADMAP.md`;
- date-stamped branch/session disposition/handoff records;
- `docs/OWNER_REQUESTED_TODO.md`;
- `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md`;
- `docs/SCOPE_COORDINATION_2026-08-11.md`;
- competitor checkpoint/TODO files.

Their durable owner requirements have been reconciled into this plan, `OWNER_FEATURE_INVENTORY.md`, and/or `OWNER_PRODUCT_BACKLOG_SPEC.md`. Their historical measurements may still be valuable. If one contains a requirement that appears missing from the canonical plan, treat that as **documentation drift to reconcile**, not permission to implement directly from the old file.

`docs/master-site-audit/` remains authoritative for its *measured historical evidence* at the pinned commit/input it names. It is not the current product roadmap.

---

# 9. NEW-IDEA INTAKE RULE — PREVENT FUTURE DRIFT

When the owner introduces a new idea or changes an existing one:

1. identify whether it extends an existing canonical feature or creates a truly new concept;
2. record the owner decision in the appropriate existing detailed spec rather than creating another permanent standalone roadmap;
3. update `OWNER_FEATURE_INVENTORY.md` status/dependencies when necessary;
4. update this master plan only when the feature family, precedence, public/private rule, removed scope, or major owner direction changes;
5. update `EXECUTION_PLAN.md` only when sequencing/authorization changes;
6. temporary/date-stamped capture documents must be reconciled into the canonical records before being considered closed;
7. do not let a competitor research document become a parallel backlog.

A useful idea is not “saved” merely because it exists somewhere in `docs/`. It is saved when it is represented in the canonical plan/spec/inventory hierarchy.

---

# 10. IMPLEMENTATION DISCIPLINE

When a backlog item becomes active:

**investigate → reproduce → RED when executable defect → identify canonical owner/root cause → minimal canonical repair/build → GREEN → measure downstream effects → broad gates → exact-head CI → owner checkpoint → STOP.**

For exploratory/modeling work, define the target and validation criteria before selecting a candidate. Do not invent a RED test or a convenient coefficient just to satisfy process.

Every material checkpoint should report:

- exact scope;
- methodology;
- files changed;
- before/after measurements;
- downstream effects;
- tests/gates;
- PR and exact head SHA;
- residuals/limitations;
- production-policy decisions still requiring owner approval;
- explicit stop condition.

A green test suite proves implementation consistency. It does not by itself prove product methodology is correct.

---

# 11. RECONCILIATION STATUS — 2026-08-12

This master pass intentionally reconciles the previously competing planning streams:

- owner feature inventory;
- detailed owner product backlog specification;
- owner-requested TODO list;
- owner feature addendum;
- scope-coordination capture;
- OTC Fantasy / Play For Keeps competitive scope;
- Dynasty Daddy CE-17–CE-21 addendum/enrichments;
- older unimplemented backlog;
- master-site-audit repair roadmap / next-steps snapshots;
- recent Public League v3, Acquisition Cost Basis, Analyst Intelligence, Game Day, and Brisket Honors decisions.

The canonical future direction is now **Master Plan → Feature Inventory + Detailed Backlog Spec → Architecture → Execution authorization**.

Do not create another “master list” beside this one. Extend this hierarchy instead.