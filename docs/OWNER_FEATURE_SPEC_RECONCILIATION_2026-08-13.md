# Chase Upside — Owner Feature Specification Reconciliation

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` from PR #816 by the post-B master reconciliation
> (`docs/POST_B_RECONCILIATION_2026-08-14.md`). Two changes were made to the branch text, both recorded here:
>
> 1. **§10's CE list was replaced** by a reconciled mapping table. It had assigned CE-01…CE-21 to different
>    capabilities than the canonical registry (18 of 22 collided). No capability was dropped — see the table in
>    §10 and `docs/CE_REGISTRY.md`.
> 2. This amendment block was added. **Nothing else was altered or deleted.**
>
> **Every statement in this document that treats B6, B7, B9, B9a, B9b, B10 or B11 as active, next,
> queued, open or pending is STALE and must not be acted on.** Verified truth on `main`: B6 (#810,
> `5c699af`), B7 (#820), B8 (#821), B9a+B9b (#824), B10-T2 (#825), B10-T3a (#827), B10-T3b (#831),
> B11 (#832/#833/#834) are all merged ancestors of `HEAD`, and the B-Series Completion Audit passed
> (#837, `79f47ff`, 20/20 executable checks). `docs/EXECUTION_PLAN.md` is the only authorization record.
>
> Its §13 instruction "Do not merge #809 merely because this file references it" is **satisfied differently than
> it anticipated**: #809 was not merged. Its durable specifications were promoted onto current `main` by this
> reconciliation, and the audit confirmed this branch is **not** a superset of #809 — the AI Front Office family,
> the Upside Report Kickoff Edition, the KTC permission record, the Sharp Insider performance spec, the global
> performance standard and the Redraft/ROS lane appear nowhere in this branch's authored documents.


**Status:** BINDING OWNER-INTENT / FEATURE-SPEC REGISTRY  
**Date:** 2026-08-13  
**Scope:** current product + partial product + approved future product + durable owner to-do  
**Implementation effect:** documentation only; this file does **not** authorize beginning a feature out of sequence

> Product name: **Chase Upside**. Historical repository identifiers may still use `Risk It To Get The Brisket` / `Brisket`; those are legacy code/document identifiers, not the current product identity.

---

# 1. WHY THIS FILE EXISTS

The repository already has several good planning layers:

- `docs/OWNER_FEATURE_INVENTORY.md` — broad inventory of what exists, what is partial, what is planned, and what is broken.
- `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` — detailed owner intent for many product areas.
- `docs/OWNER_REQUESTED_TODO.md` — durable owner-requested work queue.
- `docs/EXECUTION_PLAN.md` — canonical sequencing / authorization record.
- `docs/MASTER_PRODUCT_PLAN.md` — long-range product direction.
- `docs/master-site-audit/FEATURE_STATUS_MATRIX.md` — observed implementation/evidence status.

Those files are complementary, not interchangeable. The problem this reconciliation solves is **specification drift**: some newer owner decisions are more detailed than the older canonical docs, and a short to-do label such as “Pick Forecast” or “Power Rankings” is not enough to reproduce the intended product later.

This file therefore has two jobs:

1. establish a **specification-depth contract** that every feature must satisfy before implementation; and
2. reconcile the current and planned feature set so a future Claude Code session does not have to rediscover or reinterpret owner intent.

If a feature appears in the inventory but its detailed behavior is not repeated here, the linked canonical spec remains binding. If this file records a **newer explicit owner decision**, that newer decision wins until the canonical long-form spec is updated to absorb it.

This file must never be used to skip the sequencing/authorization rules in `docs/EXECUTION_PLAN.md`.

---

# 2. PRODUCT NORTH STAR

Chase Upside is not merely a rankings site, trade calculator, or league dashboard. It is intended to become an integrated, explainable, roster-aware **dynasty fantasy football decision-intelligence platform**.

For an important player, roster, league, trade, waiver move, draft choice, or weekly decision, the product should progressively answer:

1. **What is happening?**
2. **Why is it happening?**
3. **What does the market think?**
4. **What do strong managers / analysts / current information imply?**
5. **How does this specific league change the answer?**
6. **How does this specific roster change the answer?**
7. **What should the user actually do next?**
8. **Can Chase Upside help execute or track that action?**

A useful shorthand is:

> KTC tells the user what the market thinks a player is worth. Chase Upside should tell the user whether **this user, with this roster, in this league** should buy, sell, hold, start, trade for, trade away, stash, claim, bid on, or target that player.

The product quality order is:

**Correctness → reliability → performance → explainability → presentation.**

---

# 3. SPECIFICATION-DEPTH CONTRACT — REQUIRED FOR EVERY FEATURE

A one-line backlog item is **not** an implementation specification. Before any material feature is implemented or materially rewritten, Claude must be able to identify all of the following. If a field is genuinely not applicable, say so explicitly rather than silently omitting it.

| Required field | What must be known |
|---|---|
| User question / outcome | What user decision or workflow this feature improves. |
| Current state | Existing, partial, broken, planned, superseded, or removed. |
| Canonical owner | The one service/module/data contract that owns the underlying truth. |
| Inputs | Source data, league context, roster context, model inputs, timestamps, user preferences. |
| Outputs / contract | Stable shape and semantics exposed to consumers. |
| Method | Deterministic rules, formulas, model, simulation, aggregation, or workflow. |
| Identity / provenance | How players, teams, leagues, picks, analysts, sources, transactions, and model versions are identified. |
| Uncertainty / confidence | How missing evidence, disagreement, model uncertainty, and forecast horizon are represented. |
| Freshness / historical semantics | What “current” means; what is immutable; what can expire; what must never be rewritten. |
| Missing/degraded behavior | Never silently manufacture zero, certainty, compatibility, or freshness from missing data. |
| UI/UX | Primary user surface, interaction model, mobile behavior, language, and progressive disclosure. |
| Performance | Cached/warm/cold targets, background-vs-request work, payload and interaction expectations. |
| Dependencies | Foundations required first and canonical systems reused. |
| Non-scope | Adjacent work that must not be opportunistically mixed into the same change. |
| Tests / backtests | RED→GREEN cases, invariants, historical/OOS tests, calibration where relevant. |
| Production verification | What must be observed in the running product before the feature is called done. |
| Done criteria | A concrete exit condition, not “code exists” or “tests pass.” |

### Global implementation rules

- **One canonical owner per concept.** Do not create parallel engines that can disagree on player identity, values, league configuration, Team Strength, pick projection, trade recommendations, power rankings, scoring, or intelligence signals.
- **Missing is not zero.** Unavailable, stale, unsupported, partial, or unproven data must retain that state.
- **Facts and opinions stay distinct.** News/factual status is not an analyst vote; repeated/syndicated opinions are not independent votes.
- **Historical truth is immutable/versioned.** Trade-time values, weekly reports, award snapshots, model versions, and historical rankings must not be silently rewritten by today’s model.
- **Reuse canonical descendants.** If a panel is derived from canonical value, it does not become an independent vote merely because it appears in another UI panel.
- **Expensive work belongs in background/materialization paths.** Request-time work should be fast and bounded.
- **Last-known-good is a product behavior.** A slow or failed refresh should not blank useful previously-valid data when LKG/SWR is defensible.
- **Owner approval governs model promotion.** Challengers may be trained/backtested, but production model changes require evidence and explicit promotion.

### Performance baseline

Unless a feature has a stricter contract:

- warm/cached first useful state: **≤1 s** target;
- normal production p95: **≤2 s** where reasonable;
- preferred cold useful state: **≤3 s**;
- **≤5 s** is an absolute useful-state failure ceiling, not a target;
- local interaction response: **<250 ms**;
- immediate acknowledgement/loading state: **<100 ms**;
- never hide a >5 s operation behind an indefinite spinner;
- architecture preference: **acquire → normalize → background expensive work → materialize/index/cache → serve fast → refresh asynchronously**.

---

# 4. CURRENT / PARTIAL PRODUCT — CANONICAL INTENT AND REQUIRED END STATE

This section covers product capabilities Chase Upside already has in some form. “Existing” does not mean “finished”; production behavior must match the intended contract.

## 4.1 Canonical player identity

**User outcome:** every surface refers to the same real player and no ghost/near-name row is created simply because sources disagree on spelling, punctuation, suffixes, IDs, or aliases.

**Canonical behavior:** one player identity layer resolves provider IDs and normalized aliases; downstream systems consume canonical IDs rather than inventing their own matching logic. Sleeper IDs and strong provider IDs outrank fuzzy name guesses. Unsupported/unresolved rows stay explicit instead of being force-merged.

**Existing state:** B5 completed substantial identity repair. Continue to treat that layer as canonical rather than adding per-feature alias maps.

**Done standard:** no important feature needs its own player-matching heuristic; identity failures are observable and repairable; a correction propagates to rankings, rosters, market, intelligence, trades, history, and player profiles.

## 4.2 Canonical player valuation / rankings

**User outcome:** one trustworthy dynasty value and rank, with source provenance and league-aware context, feeds the rest of the application.

**Intent:** canonical value is an aggregation/normalization product, not a disguised copy of one vendor. Preserve source-native observations, provenance, freshness, coverage, and explicit missingness. The canonical 1–9999 semantics, source independence, anti-circularity, confidence, and league fit are foundation work rather than UI tricks.

**Current/queued foundation:** B9–B11 own the remaining value-scale, independence, and confidence semantics. Do not build feature-local alternative canonical values in the meantime.

**Consumers:** Rankings, UPP, Team Strength/Weakness, Trade Calculator, Trade Finder, waiver/drop logic, draft/pick value, Consensus Edge, portfolio/exposure, AI explanations, and historical snapshots.

## 4.3 Rankings page

**User outcome:** quickly inspect/filter the board without waiting tens of seconds or downloading the entire universe.

**Required end state:** canonical ranking/value rows, explicit freshness/confidence/provenance, scalable filters, stable pagination (50-row page target), responsive mobile behavior, fast cached loads, and no “0” substitutions for unavailable source values.

**Premium migration:** Rankings is intended to be the **first production reference route** for the Premium Sports Intelligence design migration after its prerequisites are satisfied.

## 4.4 League configuration / scoring identity

**User outcome:** every league-aware answer uses the requested league’s actual rules rather than a hand-authored profile label or another league’s Sleeper configuration.

**Canonical behavior:** scoring identity is derived/validated from actual league configuration. A requested league can be declared compatible only from evidence. A cross-league overlay may not mix requested-league teams with another league’s scoring/roster/settings and claim readiness.

**Current state:** B6 / PR #810 is the active implementation lineage. W18-F003 realized-points scoring is deliberately separate B7 scope.

## 4.5 Realized scoring

**User outcome:** historical points, PAR/VORP, weekly impact, awards, power rankings, and Game Day use the league’s real scoring instead of silently omitting nonstandard rules.

**Required behavior:** every nonzero league scoring key must either be correctly mapped or explicitly declared unsupported/uncoverable. Reception-distance rules, renamed nflverse fields, kicking, individual kick/punt-return scoring, IDP, first downs, and other custom categories must not silently become zero.

**Boundary:** individual player special-teams statistics (`kr_yd`, `pr_yd`, supported `st_*`) stay distinct from DST `def_*` scoring.

**Foundation owner:** B7.

## 4.6 Team Strength

**User question:** “How strong is this dynasty roster as an asset portfolio, by position and overall?”

**Intent:** a canonical roster-strength model, not standings and not current-season Power Rankings. Position-group depth must respect league roster/scoring settings. Current owner thresholds: QB/RB/TE top 3; WR/DL/LB/DB top 5 for group-quality views, with more exact starter/depth methodology established in the C-series plan.

**Consumers:** Team Weakness, Trade Simulator marginal impact, Trade Finder, Golden Upgrades, portfolio, selected-team recommendations, future-pick outlook, roster-aware AI.

**Do not conflate with:** current-season Power Rankings or playoff odds.

## 4.7 Team Weakness

**User question:** “Where is this roster actually vulnerable relative to what this league requires?”

**Intent:** derive weaknesses from canonical Team Strength + league lineup requirements, not arbitrary frontend labels.

Known slot thresholds to preserve into the C redesign:

- QB1 top 12; QB2 top 24;
- RB1 top 12; RB2 top 24;
- WR1 top 12; WR2 top 24; WR3 top 36;
- TE1 top 12; TE2 top 24;
- flex thresholds derived from canonical league configuration without double-counting QBs.

IDP/flex methodology must be completed from actual lineup/scoring semantics.

## 4.8 Trade Calculator

**User outcome:** evaluate a trade using canonical market value while understanding package/consolidation effects, uncertainty, external disagreement, and roster impact.

**Existing pieces to preserve/reconcile:** canonical raw values, exact KTC-style Value Adjustment as a market-parity lens, Monte Carlo uncertainty view, external Second Opinions, temporary manual value edits, roster-aware analysis, and future Analyze Trade decision contract.

**Binding rules:**

- temporary manual edits are local/silent and never mutate canonical truth;
- removing an edited player clears that temporary override;
- global Reset Values restores canonical values;
- KTC Value Adjustment remains a trusted market-consolidation benchmark and must not be silently replaced;
- do not invent “Our VA” just to have one;
- Monte Carlo is an uncertainty lens, not a literal probability that the real-world trade “succeeds”;
- equalizer suggestions rank by the **same active post-adjustment gap** displayed by the calculator, not raw sums;
- one future Analyze Trade owner should serve `/trade` and Trade Desk.

### Generic-pick quantity correctness — binding new requirement

Generic hypothetical archetypes such as `2027 Mid 1st` must support **unlimited quantity on either side**. Preferred UI is a quantity control such as `−  3  +` / `×3`, not duplicate visual rows.

Quantity must flow through:

- raw value;
- active package/VA calculation;
- fairness/gap;
- Monte Carlo where applicable;
- roster/pick impact;
- Analyze Trade/AI explanations;
- three-team trade logic;
- save/share serialization;
- every downstream trade contract.

Removing one decrements quantity. **Actual individually owned league picks remain unique and may not be duplicated.**

## 4.9 Trade Finder / Trade Suggestions / Golden Upgrades / Package Builder

**User outcome:** move from “what is this player worth?” to executable actions in this league.

**Intent:** candidate generation must use the same canonical values, ownership, Team Strength/Weakness, roster marginal impact, package methodology, and availability constraints as the calculator. No independent recommendation formula per page.

- **Trade Finder:** locate league counterparts/assets that create plausible mutually useful structures.
- **Trade Suggestions:** generate concrete deal structures, not generic player lists.
- **Golden Upgrades:** find consolidation moves where replacing multiple lesser assets with a stronger asset improves the user’s roster construction at defensible cost.
- **Package Builder:** compose executable packages while preserving actual ownership and unique pick identity.

All recommendations should explain **why this team/asset pair** is relevant rather than only showing value parity.

## 4.10 Roster-aware trade marginal impact

**User outcome:** “What does my roster look like after this exact trade?”

**Method:** canonical before → apply transaction → rerank/recompute → after. Measure starter/depth promotions, displacements, positional needs, concentration, and pick inventory changes. Do not approximate this as incoming raw value minus outgoing raw value.

This is a major genuinely incremental trade-information dimension and should remain distinct from source/value votes.

## 4.11 NFL-team exposure / portfolio concentration

**User outcome:** understand concentration risk/opportunity by NFL franchise.

**Binding behavior:** use **canonical-value-weighted exposure** as the primary measure, with raw player counts secondary. Picks have no NFL-team exposure. Missing value remains missing. Trade before/after exposure is descriptive unless a later owner-approved decision explicitly allows it to affect recommendation grades.

## 4.12 Three-team trades

**User outcome:** model and eventually build valid three-team structures when two-team paths cannot solve needs.

**Requirements:** canonical asset identity/ownership, side-specific inflow/outflow, no duplicated real pick, package math applied correctly per receiving/losing side, serialization/shareability, and clear explanation of why all three participants could rationally accept.

## 4.13 Waivers / FAAB / Perfect Waivers / Dropability

**User outcome:** “Who should I add, what should I bid, and who can I safely cut?”

**Canonical behavior:** combine availability, canonical value, team need, projected role/scoring fit, roster depth, replacement cost, budget, league transaction rules, and current intelligence. Missing projection/value cannot silently become zero.

- **FAAB recommendation:** recommended range/amount with rationale and remaining-budget awareness.
- **FAAB context / market ledger:** compare league spending, bid history, owner behavior, and market price where available.
- **Perfect Waivers:** optimize adds + corresponding drops as a roster change, not independent lists.
- **Dropability:** explicit expendability score/tiers using roster context and replacement value; do not recommend dropping an intentional QB handcuff or protected asset merely because standalone rank is low when owner/league policy says otherwise.
- **Expanded drop candidates:** enough candidates to make the add actionable, while respecting protected/untouchable logic.

## 4.14 Perfect Draft / Draft Room

**User outcome:** make pick/auction decisions in context of remaining roster needs, board value, market, and budget.

**Requirements:** one canonical value/league-config owner, budget-aware bidding, draft-capital/pick identity, current availability, roster marginal impact, and pre-draft/pre-auction immutable snapshots for later evaluation.

A recommendation must never exceed remaining auction budget or rely on a stale availability state without saying so.

## 4.15 Draft Capital / Pick Projector

**Current state:** the product already has draft-capital/pick projection concepts. The current simple projector is useful context but **must eventually be superseded by the canonical owned-pick projection engine in §6.1**, not allowed to coexist as a conflicting second answer.

Draft-capital views should show owned assets, provenance, current valuation, projected landing/range where defensible, and historical/trade context.

## 4.16 Consensus Edge / Buy-Sell intelligence

**User outcome:** “Where is the strongest actionable disagreement/opportunity right now?”

**Intent:** one central recommendation/intelligence engine that synthesizes independent information while preserving lineage, confidence, price/context conditions, and roster applicability.

Recommendation vocabulary must distinguish conviction from speculation. Canonical stance categories include:

- STRONG BUY
- BUY
- CONDITIONAL BUY
- **STASH / SPECULATIVE BUY**
- HOLD / CONTEXTUAL
- CONDITIONAL SELL
- SELL
- STRONG SELL
- NO SIGNAL / INSUFFICIENT SIGNAL

For analyst extraction, subtype labels such as `BUY / SELL / HOLD / FADE / BREAKOUT / SLEEPER / STASH / INSUFFICIENT_SIGNAL` may be used where they preserve source meaning. `STASH` must not create false consensus with true conviction BUY calls. `SLEEPER` is an undervalued player with a meaningful upside/start case, not merely any deep bench name.

Preserve context such as:

- “buy only if cheap”;
- “sell for a 2027 second”;
- “buy now, sell after an early spike”;
- contender vs rebuilder;
- injury/role/depth-chart contingencies.

Repeated takes from the same analyst/thesis lineage must not become independent votes.

## 4.17 Homepage Consensus Edge ticker

**User outcome:** ambient one-glance opportunities without opening a full intelligence page.

**Rules:** presentation only; consumes canonical Consensus Edge output. BUY items may be global. **SELL items must only be players rostered by the selected fantasy team.** The ticker never invents its own signal algorithm.

Premium redesign should make it feel like restrained sports-market tape, not a decorative SaaS carousel.

## 4.18 Sharp Tracker / Sharp Roster Percentage / Sharp Ledger / Insider Trading

**User outcome:** understand what historically strong/high-signal managers are doing before the broader market catches up.

**Shared canonical sharp pool:** Buy/Sell Tracker, Sharp Roster %, Insider, and related manager behavior views must use the same manager/source identity pool rather than recomputing their own “sharp” universes.

- **Sharp Tracker:** transactions/behavior from selected sharp-manager universe.
- **Sharp Roster %:** top rostered players across that same pool, with rank/name/position/NFL team/count/%.
- **Manager concentration:** distinguish broad sharp ownership from one-manager concentration.
- **Sharp Ledger:** auditable time-series of sharp buys/sells/ownership changes.
- **Insider Trading:** league-specific overlap/ownership behavior from the same canonical identity layer.

7/14/30-day windows must not double-count the same underlying action merely because it appears in multiple windows.

## 4.19 Podcast Intelligence

**User outcome:** turn long-form expert content into attributable, fresh, deduped dynasty signals and useful player/team context.

**Pipeline:** source registry → episode discovery → transcript/authorized text → canonical analyst/source/content identity → take extraction → stance/context/freshness → independence/dedupe → Consensus Edge / UPP / selected-team brief / personalized audio or written report.

Transcript retention and voting validity are different. Historical source material may remain for provenance while its current recommendation weight expires.

Freshness must be:

- **take-type-aware** (injury, role, game-specific, postgame usage, buy/sell/value, durable thesis, historical/background);
- **event-aware** (game, injury update, transaction, depth-chart change, inactive/active status can supersede immediately);
- **season-aware** (faster decay in volatile periods, slower in genuinely quiet offseason periods);
- player/team-event based, **not** a universal Sunday/Monday reset.

Discovery window is not voting window.

## 4.20 YouTube Analyst Intelligence — planned extension

**User outcome:** capture high-quality dynasty analysis that exists on YouTube without allowing the same analyst/show to vote twice through podcast + video syndication.

**Scope:** target roughly 50 reputable dynasty-focused YouTube sources/videos, excluding duplicate representation already captured through Podcast Intelligence when the content is materially the same.

**Architecture:** reuse canonical analyst identity, content identity, transcript normalization, take taxonomy, provenance, freshness, supersession, independence, Consensus Edge, UPP, and personalized selected-team intelligence. Do **not** build a parallel “YouTube signals” scoring engine.

## 4.21 Future X analyst feed — cost-gated

Preserve a future large curated analyst feed (roughly 500 analyst/source identities) using the official/authorized API only. Do not scrape or incur disproportionate recurring cost while the product is small/private. Re-evaluate economics and policy before implementation. Cross-media analyst identity/dedupe is mandatory.

## 4.22 Universal Player Profile (UPP)

**User outcome:** one player page answers value, trend, league fit, roster relevance, news, analyst intelligence, market behavior, historical context, and actionable implications.

**Canonical feed:** combine canonical rankings/value, source rank/value history, roster/league context, facts/news, analyst opinions, podcast/YouTube intelligence, sharp behavior, transaction/trade context, projections/performance, and future recommendation output without duplicating truth owners.

**News/intelligence presentation:** concise attributed excerpts, summaries, or hybrid. Preserve fact vs opinion, provenance, timestamp/freshness, and dedupe. Do not republish full copyrighted articles/transcripts.

**Premium migration:** UPP is intended to be the **second production reference route** after Rankings.

## 4.23 News → player intelligence / notification hygiene

Facts such as injury, transaction, depth-chart, suspension, active/inactive, role change, or meaningful usage must update the canonical player-intelligence state and may supersede stale analyst takes.

Notification systems should notify on meaningful actionable changes, not every source duplicate. Syndicated copies collapse to one factual event lineage.

## 4.24 Public League Experience

**User outcome:** a rich public league hub for standings, rosters, transactions, history, draft capital, matchup context, power, playoffs, team assignments, stories/reports, and selected public intelligence.

**Principle:** public output is useful but must respect privacy/redaction boundaries. Public pages should consume canonical league snapshots and independent derived services, not rebuild league truth in the frontend.

Removed/retired concepts such as public money/constitution content should stay removed unless explicitly reauthorized.

## 4.25 Sleeper manual sync / league freshness — binding new requirement

The public `/league` snapshot has its own refresh lifecycle and should expose it honestly.

Add a prominent **Sync Sleeper / Refresh League Data** action that:

- uses the existing public-league forced-refresh path (`?refresh=1`) rather than triggering the global scraper;
- re-fetches the current section without a full page reload;
- exposes `Syncing`, `Updated`, and `Failed` states;
- preserves last-known-good data on refresh failure;
- displays `Last synced` / `Updated X ago` from canonical `generatedAt` metadata;
- uses roughly a 30–60 second client cooldown/debounce plus server-side dedupe;
- refreshes the canonical snapshot that feeds trades, rosters, picks, waivers, etc.;
- updates current section/shared freshness while leaving other sections lazy until needed;
- can later be complemented by a lightweight automatic transaction sync every few minutes;
- survives the Premium Sports Intelligence shell.

## 4.26 Authenticated → public League navigation — binding new requirement

Signing in must **add capability, not hide the public league experience**.

Authenticated desktop and mobile navigation must expose a persistent top-level **League** action that routes to canonical `/league` in one action while preserving the session. Do not require logout, browser back, manually typing a URL, or going through Settings. Do not create a second authenticated copy of the League surface. Preserve this behavior in the Premium shell.

## 4.27 `teamAssignment` — missing-data-as-zero correctness defect

Observed behavior: the public League `teamAssignment` section can return HTTP 200 with `assignments: []` when `snapshot.current_season` is missing/empty, and scheduled E2E has intermittently observed 0 before the live section later self-recovers to 12.

**Binding correction:** missing/degraded snapshot state must not masquerade as a legitimate zero-assignment league. The section contract needs an explicit unavailable/degraded/not-ready state (or an appropriate section-level failure contract) while preserving last-known-good where defensible. Tests must distinguish legitimate zero from missing season/roster input.

This is a separate production correctness defect, not part of the closed FD incident.

## 4.28 Playoff Predictor

**User question:** “What are my actual playoff odds from here?”

Use current standings/results, future schedule, league playoff rules, empirical scoring distributions, and canonical current-strength inputs in simulation. Keep schedule-dependent playoff probability separate from schedule-independent Power Rankings and dynasty-asset Team Strength.

Archive enough inputs/versioning to evaluate calibration and avoid lookahead.

## 4.29 Franchise history / Acquisition History / asset lineage

**User outcome:** understand how a roster was built, what was acquired/sold, and how asset value evolved.

One canonical transaction/acquisition-history layer should power franchise history, trade history, Trade Trees / Asset Lineage, manager behavior, GMOTY context, and current-vs-acquisition value views.

Identity must survive player renames/provider changes and pick ownership transfers. Historical facts are immutable; current valuation is a separate overlay.

## 4.30 BDVM / fundamentals / projections

BDVM and other projection/fundamental systems should provide **incremental football-performance evidence**, not merely re-express canonical market value. Expensive model work belongs in background/materialized paths. Missing projections/fundamentals remain explicit. Any use in Consensus Edge/rankings must preserve lineage so value-derived and model-derived evidence are not double-counted.

## 4.31 Admin / human review / temporary access

Admin tooling is part of production correctness, not disposable internal UI.

- repair the `fmtPassExpiry` crash;
- preserve the existing temporary-password/pass concept rather than creating a duplicate auth system;
- allow owner-selected validity duration in hours;
- prove generated credentials work end to end;
- expiry/revocation fail closed;
- human-review surfaces for source/model exceptions must preserve audit trail and provenance.

## 4.32 Compare / selected-team personalization / personal rankings

Player Compare and future CE-07 multi-select should compare canonical facts/values/fit rather than copy values into a separate store. Selected-team personalization should influence recommendations/surfaces through explicit roster/league context, not silently mutate global canonical rankings. Future personal rankings/tuning must remain a user preference layer unless deliberately promoted into a validated model input.

## 4.33 Push / personalized campaign-feed

Push and CE-20-style personalized feeds should be event/action-driven and deduped by canonical event/signal lineage. The system should surface changes that materially affect the selected team, watchlist, trade targets, lineup/waiver decisions, or league—not spam every scrape/source update.

---

# 5. PREMIUM SPORTS INTELLIGENCE — PERMANENT VISUAL NORTH STAR

Canonical owner decision:

> **Chase Upside will migrate to the Premium Sports Intelligence visual system represented by Direction A of the Chase Upside Design Lab. This is the permanent design north star unless Jason explicitly changes the decision later.**

Reference prototype: `https://chase-upside-design-lab.qcv6rxwgqc.chatgpt.site/`

## Desired feel

- premium professional sports intelligence;
- editorial / front-office / data-first;
- dense but calm;
- strong typography and hierarchy;
- thin rules/dividers;
- minimal radius;
- little/no decorative shadow;
- disciplined color;
- fast and information-forward.

## Explicit anti-patterns

Do **not** migrate into:

- nested rounded-card stacks;
- excessive pills/radii;
- generic shadcn/SaaS dashboard appearance;
- glassmorphism;
- AI gradients/glows;
- generic icon soup;
- one-card-per-number tiling;
- giant empty whitespace;
- desktop table rows turned into giant mobile-style cards;
- superficial recoloring of existing structure.

## Migration gate

The migration begins only when:

1. the reliability incident is closed — **satisfied as of 2026-08-13**;
2. B6 is merged and production-verified;
3. reusable-vs-replace audit is complete;
4. core data contracts needed by the target route are stable.

Rankings is the first production reference route; UPP is second. The first migration implementation phase should establish foundations/tokens/shell/structural grammar rather than opportunistically redesigning every route at once.

At the correct checkpoint, the execution record should say:

> **Chase Upside has reached the point where the next Premium Sports Intelligence migration phase should begin.**

---

# 6. NEW / EXPANDED PRODUCT SPECS THAT MUST NOT BE LOST

## 6.1 Canonical Owned Future Pick Projection & Valuation Engine

This is a major canonical system, not a cosmetic upgrade to the existing Pick Projector.

### User questions

- Where is this **specific owned pick** likely to land?
- What is it worth **today** under uncertainty?
- What was it projected/worth **when it was traded**?
- How has its outlook/value changed?
- Can I actually trade this real pick in my league?

### Canonical pick identity

A real league pick is identified by:

`{leagueKey, season, round, originalRosterId/originalFranchise, currentOwnerRosterId}`

The projected landing follows the **original franchise whose finish determines the pick**, not the current holder. UI examples should look like `Michaela's 2027 1st`, optionally with `currently held by Eric` where useful.

Actual picks are unique assets. Generic hypothetical pick archetypes remain separate and may have quantity.

### Forecast contract — distribution, not a label

The engine must forecast a **probability distribution across draft slots**, not merely stamp `Early/Mid/Late` or one falsely precise pick number.

Core valuation:

`ProjectedPickValue = Σ_slot P(slot | team, year, league rules, current state) × CanonicalValue(year, round, slot)`

The existing canonical future-year discount belongs inside canonical slot valuation and is applied **exactly once**. The projection layer must never add a second horizon discount or create a separate “projector value scale.”

### Nearest/upcoming draft

Use the league’s actual canonical draft-order rules, including the configured criterion (standings, Max PF, etc.), remaining schedule, playoff/consolation rules, empirical scoring distribution, and canonical current-season strength. Use Monte Carlo to produce a slot distribution. If the order is already fixed, use the actual slot.

Never assume all leagues use reverse standings.

### Future years

Do not freeze today’s ROS ranking for 2028/2029. Build horizon-specific future competitive strength from defensible inputs such as:

- projected starter quality;
- depth;
- dynasty roster durability;
- player ages and position age curves;
- known draft capital arriving before the target season;
- roster concentration/holes;
- projected performance/availability.

Raw total roster market value alone is not sufficient.

Known future capital can influence a later roster outlook, but self-referential pick valuation must be controlled with an explicit exclusion/iterative methodology and tested for stability.

As horizon increases, shrink expected finish toward league mean and widen the distribution.

### UI / confidence

Far-out picks should emphasize distributional truth, e.g.:

`Mid 1st · median 1.06 · 80% range 1.02–1.11 · Early 24% / Mid 52% / Late 24% · Low confidence`

Do not present a 2029 exact-slot estimate with fake certainty. Confidence should ultimately be empirically calibrated by horizon, not an arbitrary cap masquerading as measurement.

### Canonical slot value curve

Use the existing canonical pick valuation authority. If exact future slot rows do not exist, derive/interpolate a **monotonic exact-slot curve** per year/round from canonical early/mid/late anchors, current-year rookie/slot shape, and market level while preserving the existing year/round level and future-year discount.

### Trade Calculator integration

When league context is known:

- offer real assets such as `Michaela's 2027 1st`;
- show projected tier/slot distribution, expected canonical value, range/confidence;
- only assets actually owned by the selected team are executable;
- actual picks remain unique;
- generic picks remain available for hypothetical/non-league calculations;
- the same expected canonical value flows into package math, fairness, roster impact, Analyze Trade, three-team trades, save/share, and downstream recommendations.

### Trade History integration

Every new pick transaction should preserve an immutable/versioned **trade-time projection snapshot**:

- distribution;
- expected slot/tier;
- expected canonical value;
- confidence;
- model version;
- timestamp/input version.

Separately show the current projection/value so the user can see evolution, e.g.:

`Eric 2028 1st — At trade: projected 1.08 · 4,250 | Today: projected 1.03 · 5,900 | +1,650`

Never rewrite the historical trade-time snapshot. For old transactions without temporally-valid inputs, say `Trade-time projection unavailable`; never backfill today’s projection and label it historical.

### Validation

Start storing immutable weekly team-input and pick-projection snapshots as early as practical. Use rolling-origin evaluation by horizon:

- slot MAE;
- early/mid/late accuracy;
- probability calibration / Brier / log loss;
- expected-value error;
- prediction-interval coverage.

Tune next-draft / ~2-year / 3+-year horizons separately if evidence supports it. Historical reconstruction may be used only where temporally valid inputs exist; no lookahead or invented old market/team state.

Model evolution follows challenger → backtest/OOS validation → stability review → owner approval → promotion → monitor/rollback.

### One canonical service

This engine should ultimately feed:

- Pick Projector;
- Draft Capital;
- Trade Calculator;
- Trade History;
- roster asset values;
- future Team Strength inputs where methodologically valid;
- AI trade analysis;
- recommendation systems.

It should **supersede the current simplistic projector**, not coexist with it as a conflicting second answer.

## 6.2 The Upside Report

Canonical name: **The Upside Report**.

### Product question

> **What was actually interesting about this week in our league?**

This is not a generic scoreboard recap and not an AI hallucination layer over raw stats.

### Outputs

- compact/shareable weekly card;
- full mobile-first report;
- matchup stories;
- archive of immutable/versioned weekly artifacts.

### Interestingness Engine

A deterministic engine should choose roughly **5–8 genuinely interesting items**, adapting to the week/season rather than forcing every award category every week.

Candidate concepts include:

- Game of the Week — not merely smallest margin;
- Biggest Upset — ideally the lowest defensible pregame win probability among winners;
- Bad Beat — a strong relative/all-play performance that still lost;
- Escape Artist — a weak relative performance that still won;
- Game Changer;
- waiver impact;
- notable player/team/roster events.

### Weekly Player Impact

`actual points − canonical positional replacement expectation for that starting opportunity`

This is context-aware impact, not raw fantasy points.

### Game Changer

`team score − optimal score without that player`

Compute via an exact best-ball re-solve. Do not approximate with “player points minus next bench score” if lineup constraints make that wrong.

### Waiver impact

Use actual counted/marginal lineup delta from the acquired player. A waiver can be meaningful even if the team lost; add a special badge if the move actually flipped the result.

### AI role

Deterministic systems own facts, rankings, deltas, winners, categories, and numbers. AI writes the narrative/explanation from those facts. Public output must not leak private intelligence.

### Historical behavior

Weekly artifacts are immutable/versioned with LKG. The archive must be temporally honest: do not regenerate 2026 Week 3 using a 2028 model and present it as what the system knew then unless explicitly labeled as a retrospective rerun.

MVP/race references should adapt to season timing; do not manufacture a meaningful “top five MVP race” in a week where the sample is too thin. Top 3 is the preferred weekly maximum when meaningful.

## 6.3 Canonical Weekly Power Rankings

### Product question

> **Who is strongest right now this season, independent of schedule luck, while still respecting actual accomplishment and near-term output?**

### Firewall between concepts

- **Team Strength** = dynasty asset/roster strength.
- **Power Rankings** = current-season team strength/performance.
- **Playoff Predictor** = playoff odds using future schedule.
- **Standings** = official outcomes.

Power Rankings must not become another dynasty value leaderboard and must not bake in future schedule.

### Canonical engine consolidation

The repo currently has multiple power concepts (`src/public_league/power.py` and `src/ros/power_v2.py`). C-series planning should consolidate into one canonical engine rather than introduce a third.

### Proposed starting model to validate

`100 × (0.40 ROS + 0.20 Season All-Play + 0.15 Recent Form + 0.15 Team Realized VORP/PAR + 0.10 Official Record)`

This is a **candidate methodology**, not permission to skip validation. Early season should renormalize/shrink available components rather than fill gaps with prior-year raw PPG as if it were current evidence.

### UI

Preferred dense table grammar:

`Rank | Δ | Team | Power | Record | All-Play | Last 4 | ROS Strength | Team VORP/PAR`

### Validation

Rolling-origin backtest against 1–3 week future all-play / scoring performance. Compare current v1/v2 and simple baselines. No lookahead. Evaluate stability and whether each component adds predictive information rather than merely making rankings feel plausible.

## 6.4 Awards & Honors

### Goal

Create objective, reproducible institutional league honors rather than subjective AI awards.

2026 is the first live institutional season. Retro 2024/2025 honors should use the same methodology only where historical inputs support it; do not fabricate unavailable inputs.

### Realized Lineup VORP

For actual starts/counted lineup opportunities:

`player points − positional replacement expectation for that starting opportunity`

Bench/non-counted output is zero for lineup-realized award value. Negative value remains negative.

### Planned honors

- MVP;
- OPOY;
- DPOY;
- OROY;
- DROY;
- positional honors;
- postseason/championship MVP;
- Best Offense / Best Defense via realized lineup VORP;
- Manager of the Year (MOTY);
- General Manager of the Year (GMOTY);
- All-League teams;
- top-five award races where sample/season timing supports them.

### Eligibility

MVP and MOTY: current/final playoff field + >.500 requirement. GMOTY and OPOY do not inherit that eligibility rule by default.

MOTY and GMOTY must remain conceptually distinct: weekly/season management and competitive overperformance versus roster-building/acquisition/transaction quality.

## 6.5 Market Trade Ledger / Real Trade Market Value

**Goal:** learn what the actual dynasty market is paying from observed trades without confusing one noisy trade with canonical truth.

Normalize real transactions into player/pick/package identities, league format/context, timestamps, values at transaction time, and package topology. Preserve source/privacy rules. Use enough sample/context before deriving a market-value signal. The ledger can inform price context, comparable trades, package methodology validation, and future manager behavior, but it should not overwrite canonical value from one trade.

## 6.6 Manager Scout

**Goal:** answer how a specific league manager behaves and what kind of deal is likely to work with them.

Build from canonical transaction/acquisition history, buy/sell frequency, positional tendencies, package/consolidation behavior, pick usage, FAAB behavior, trade counterpart history, and actual league evidence. Keep descriptive behavioral evidence separate from unsupported psychological claims. Show sample size/time window and avoid presenting thin history as stable personality.

## 6.7 Command Center / Trade Desk / Portfolio

These are orchestration surfaces, not new truth engines.

- **Command Center:** selected-team “what should I do now?” surface using canonical needs, market, waivers, trade targets, news/intelligence, calendar/game state.
- **Trade Desk:** one place to source/find/build/analyze/track trades using the canonical trade-decision contract.
- **Portfolio:** dynasty asset allocation/exposure view across players, picks, age windows, position groups, NFL teams, value concentration, and future flexibility.

Each should compose canonical services and explanations rather than duplicate their algorithms.

## 6.8 Game Day Command Center (CE-20)

**User outcome:** a Sunday/weekly live companion that understands this league better than a generic scoreboard.

### Core requirements

- exact custom league scoring;
- exact best-ball lineup semantics;
- calibrated pregame and live final-score distributions;
- best-ball-aware win probability;
- selected-team matchup/event/news context;
- leverage/rooting guidance;
- mobile + desktop/TV-friendly experience.

A filled best-ball slot is not “done” while another eligible rostered player can still displace it.

Unprojected custom-scoring components (first downs, reception-distance bands, return yards, complex IDP/ST events) must be estimated with defensible historical/conditional models or remain explicitly uncertain—never silently zero.

### Validation

Archive pregame/in-game prediction snapshots and evaluate:

- final-score error;
- best-ball lineup accuracy;
- win-probability calibration/Brier/reliability;
- temporal leakage.

### Cost policy

V1 should be useful with existing/legitimate low-cost projections, scoring, matchup, news/status, and our own simulation. Paid second-by-second play-by-play is a later enhancement only if usage justifies recurring cost.

## 6.9 Share Renderer

One canonical renderer/export system should create high-quality share cards/images for The Upside Report, trades, rankings, awards, player profiles, records, and other selected surfaces. It consumes authoritative display contracts; it does not recompute values/scores in rendering code. Preserve privacy/redaction and Premium Sports Intelligence visual grammar.

## 6.10 PAR / Stats / ADP / Utilization Lab

These statistical products should expose incremental performance/context evidence with clear denominator/window/provenance. PAR/VORP and utilization inputs must use league scoring/role semantics where relevant. ADP/source observations remain source-native before normalization. Do not convert a football statistic directly into dynasty value without an explicit validated bridge.

## 6.11 League Format / Utilization Lab

Expose how this league’s format changes replacement levels, starter demand, position scarcity, scoring opportunities, and roster construction. Reuse canonical league configuration and realized/projection systems. This can inform Team Strength/Weakness and explanations, but format context is not an excuse for a hidden arbitrary player-value multiplier.

## 6.12 Trade Trees / Asset Lineage

Trace what an asset became across trades, picks, drafted players, subsequent flips, and current holdings. Use immutable transaction/acquisition history and stable pick identity. Separate historical value-at-time from today’s value. Never rewrite lineage because a pick changed owners.

## 6.13 Waiver Market / FAAB Market Ledger

Persist league waiver claims/bids, winning/losing bids where available, timing, player identity, budget context, and subsequent roster impact. Use as price/context evidence for FAAB recommendations and manager behavior; do not treat one owner’s overbid as canonical price.

## 6.14 Dynasty Season Recap / Wrapped

A season-level deterministic recap composed from canonical standings, all-play/performance, transactions, awards, Upside Reports, records, roster/value evolution, draft/waiver/trade impact, and historical snapshots. AI may narrate verified facts; deterministic systems own the numbers/categories. Preserve an immutable season artifact once finalized.

---

# 7. ML / MODEL GOVERNANCE — APPLIES ACROSS FEATURES

No production model should silently self-promote.

Canonical lifecycle:

**collect → provenance/history → train challenger → backtest → out-of-sample validate → compare with production → stability/calibration review → owner approval → promote → monitor → rollback if needed**

Maintain a stable production model independently from challengers. Model version, input snapshot/version, and evaluation window should be available for historical reconstruction where material.

This applies especially to:

- canonical value normalization/weighting;
- Hill/value-curve changes;
- adaptive source weighting;
- future-pick projection;
- playoff/power/game-day simulations;
- scoring-fit/prospect translation;
- confidence models;
- recommendation synthesis where learned weights are proposed.

---

# 8. B → C HARD REPLAN GATE — BINDING OWNER DECISION

The current execution plan intentionally names the C-series only at a shorthand level. **That shorthand must not automatically become an implementation queue.**

After B11 is completed/accepted:

1. **STOP. Do not begin C1.**
2. Put Claude Code into **Plan Mode only**.
3. Re-read the actual current repository, production contracts, this reconciliation, the owner inventory, backlog spec, open/merged planning docs, and all owner-requested to-dos.
4. Build a fresh dependency graph of **every current, partial, planned, and newly discussed feature**.
5. Completely **rewrite the C-series execution plan from the product/repo state that exists then**.
6. For every material C feature/phase, satisfy the full Specification-Depth Contract in §3.
7. Identify:
   - prerequisites;
   - shared root causes that should be combined;
   - concerns that must remain separate;
   - parallelizable work;
   - duplicate engines to consolidate/retire;
   - canonical ownership/data contracts;
   - PR boundaries sized for meaningful review;
   - RED→GREEN / backtest / production gates;
   - migration/backfill requirements;
   - performance budgets;
   - rollout/rollback behavior.
8. Explicitly place all newer owner features—including the canonical owned future-pick engine, stable owned-pick identity/history, trade-time value snapshots, generic-pick quantities, Sleeper sync/freshness, Premium Sports Intelligence migration, The Upside Report, Power Rankings, Awards, Analyst Intelligence expansion, Market Trade Ledger, Manager Scout, Game Day, Trade Trees, FAAB Market Ledger, Share Renderer, and other additions made before B ends—into the dependency graph in detail.
9. Produce a single proposed **C-Series Execution Plan**.
10. Jason + ChatGPT review that proposed plan and may reorder, combine, split, add requirements, or reject methodology.
11. Only after explicit owner approval may Claude implement C1.

**There is no automatic B11 → C1 transition.**

The purpose is efficiency: do the dependency/architecture thinking once at the C boundary so implementation does not repeatedly discover late that a “feature” actually depended on three unbuilt canonical foundations.

---

# 9. RECONCILIATED FEATURE REGISTRY / SPEC OWNERS

The table below is a coverage crosswalk, not a priority order.

| Feature family | Current/planned state | Binding spec/intent owner |
|---|---|---|
| Player identity | Existing/foundation repaired | `OWNER_PRODUCT_BACKLOG_SPEC` + B5 evidence + this §4.1 |
| Canonical rankings/value | Existing + B9–B11 foundation pending | `EXECUTION_PLAN`, backlog spec, this §4.2 |
| League config/scoring identity | B6 open/implemented lineage | `EXECUTION_PLAN` + PR #810 + this §4.4 |
| Realized scoring | B7 queued | `EXECUTION_PLAN` + owner ST to-do + this §4.5 |
| Team Strength | Existing/partial; canonical C foundation | backlog spec + this §4.6 |
| Team Weakness | Existing/partial; canonical C foundation | backlog spec + this §4.7 |
| Trade Calculator | Existing/active | backlog spec + owner to-do + this §4.8 |
| Generic pick quantities | Planned correctness | **this §4.8** |
| Roster trade impact | Existing/partial | backlog spec + this §4.10 |
| Trade Finder/Suggestions/Golden Upgrades/Package Builder | Existing/partial/planned | backlog spec + this §4.9 |
| NFL-team exposure | Planned | owner to-do + this §4.11 |
| 3-team trades | Planned/partial | backlog spec + this §4.12 |
| Waivers/FAAB/Dropability/Perfect Waivers | Existing/partial | backlog spec + this §4.13 |
| Perfect Draft / Draft Room | Existing/partial/planned | inventory/backlog + this §4.14 |
| Draft Capital / current projector | Existing/partial | inventory + this §4.15 |
| Canonical owned pick projection/value | **New major planned canonical system** | **this §6.1** |
| Consensus Edge | Existing/partial | backlog spec + this §4.16 |
| Consensus ticker | Planned/partial | owner to-do + this §4.17 |
| Sharp systems | Existing/partial | backlog spec + this §4.18 |
| Podcast Intelligence | Existing/partial | backlog spec + this §4.19 |
| YouTube Intelligence | Planned | owner to-do + this §4.20 |
| X analyst feed | Long-term cost-gated | owner to-do + this §4.21 |
| UPP | Existing/expanding | backlog + this §4.22 |
| News/player intelligence | Existing/partial | backlog + this §4.23 |
| Public League Experience | Existing/expanding | inventory/backlog + this §4.24 |
| Sleeper manual sync/freshness | **New planned UX/correctness** | **this §4.25** |
| Authenticated League nav | **New planned UX** | **this §4.26** |
| teamAssignment missing-as-zero | **Observed correctness defect** | **this §4.27** |
| Playoff Predictor | Existing | inventory + this §4.28 |
| Weekly Power Rankings | Existing competing engines; rewrite planned | **this §6.3** |
| Franchise/Acquisition history | Existing/partial + C foundation | inventory/backlog + this §4.29 |
| BDVM/fundamentals | Existing/partial | inventory/backlog + this §4.30 |
| Admin/temp access | Existing defects | owner to-do + this §4.31 |
| Compare/personalization | Existing/partial/planned | inventory + this §4.32 |
| Push/personalized feed | Partial/planned | inventory + this §4.33 |
| Premium Sports Intelligence | Approved permanent visual direction | **this §5** + #809 candidate design docs |
| The Upside Report | Approved planned product | **this §6.2** + #809 candidate spec |
| Awards & Honors | Approved planned product | **this §6.4** + #809 candidate spec |
| Market Trade Ledger | Planned | **this §6.5** |
| Manager Scout | Planned | **this §6.6** |
| Command Center / Trade Desk / Portfolio | Planned | **this §6.7** |
| Game Day Command Center | Planned/dependency-gated | owner to-do + **this §6.8** |
| Share Renderer | Planned | inventory + **this §6.9** |
| PAR/Stats/ADP/Utilization | Existing/partial/planned | inventory + **this §6.10** |
| League Format / Utilization Lab | Planned | addendum/inventory + **this §6.11** |
| Trade Trees / Asset Lineage | Planned | addendum/inventory + **this §6.12** |
| Waiver/FAAB Market Ledger | Planned | addendum/inventory + **this §6.13** |
| Season Recap / Wrapped | Planned | addendum/inventory + **this §6.14** |
| ML lifecycle/adaptive weighting | Planned/foundation | inventory/backlog + **this §7** |
| B→C replan gate | **Binding future execution gate** | **this §8** + `EXECUTION_PLAN` |

---

# 10. COMPETITIVE / CE BACKLOG — PRESERVE BUT RECONCILE THROUGH CANONICAL OWNERS

The existing approved CE inventory remains part of the product plan and must be brought into the C rewrite rather than implemented as isolated competitor-copy pages:

> **IDENTIFIER RECONCILIATION — 2026-08-14.** The list that stood here assigned CE-01…CE-21 to *different
> capabilities* than the canonical registry — 18 of 22 identifiers meant two different things, and this branch's
> own §6.8 used the canonical meaning of CE-20 while this list used another. One identifier may not mean two
> capabilities, so the list has been replaced by the mapping below. **No capability was dropped**: every entry
> either resolves to its canonical identifier or received a newly minted one (CE-22…CE-29).
> `docs/CE_REGISTRY.md` is now the single canonical registry.

| capability (as this branch named it) | tag used here | canonical identifier |
|---|---|---|
| roster-age windows | CE-01 | **CE-23** (newly minted) |
| league longevity / history | CE-02 | **CE-24** (newly minted) |
| manager buy/sell frequency | CE-03 | **CE-03** Manager Scout (a metric within it) |
| future picks as trade assets | CE-04 | **CE-02** Pick Forecast |
| trade-taxable constraints / Trade Desk | CE-05 | **CE-05** Trade Desk |
| teammate/portfolio comparison and exposure | CE-06 | **CE-06** Dynasty Portfolio / Exposure |
| compare multi-select | CE-07 | **CE-25** (newly minted) |
| push | CE-08 | **CE-29** (newly minted) |
| three-team trades | CE-09 | Trade Calculator multi-team — already live, no CE id (`OWNER_PRODUCT_BACKLOG_SPEC.md` §1.1) |
| cross-league trade / portfolio view | CE-10 | **CE-26** (newly minted) |
| league keeper / privacy mechanics | CE-11 | **CE-27** (newly minted) |
| comparable-user strategy signals | CE-12 | **CE-03** Manager Scout |
| starter-relevance filter | CE-13 | **CE-22** (newly minted) |
| individualized rankings / tuning | CE-14 | **CE-14A** Personal Rankings Overlay |
| user feedback / polling | CE-14A | **CE-28** (newly minted) — **NOT owner-approved**; see `docs/CE_REGISTRY.md` |
| LINEUP IQ | CE-15 | **CE-12** Lineup Intelligence |
| DRAFT ROOM | CE-16 | **CE-13** Draft Room |
| Market Pulse / League Format & Utilization additions | CE-17 | **CE-14** Market Pulse + **CE-17** League Format / Utilization Lab |
| PAR / Stats | CE-18 | **CE-09** Replacement Value / PAR + **CE-08** Projections & Stats Hub |
| Personal Rankings | CE-19 | **CE-14A** Personal Rankings Overlay |
| personalized campaign/feed | CE-20 | **CE-15** Portfolio Trade Campaign |
| Game Day Command Center lineage | CE-20 | **CE-20** Game Day Command Center (agrees with this branch's own §6.8) |
| Share Renderer | CE-21 | **CE-10** Share Renderer / Team Cards |
- approved Dynasty Daddy-derived extensions: League Format / Utilization Lab, Trade Trees / Asset Lineage, Waiver Market / FAAB Market Ledger, Game Day, Dynasty Season Recap / Wrapped.

The C replan must map each CE item to an existing canonical owner where possible and explicitly retire/merge duplicate conceptual engines.

---

# 11. CURRENT OPERATIONAL FOLLOW-UPS — NOT PRODUCT FOUNDATION PHASES

## 11.1 Closed FD/resilience incident

Official status:

> **PRODUCTION INCIDENT CLOSED — RUNTIME RESILIENCE CONTROLS VERIFIED; FD ACCUMULATION SOURCE UNRESOLVED AND MONITORED**

Do not reopen the broad incident without new evidence.

## 11.2 Narrow deployment-gate `infinity` false-negative follow-up

Production observed `NextElapseUSecMonotonic=infinity` while the watchdog oneshot service was genuinely executing. The current verifier rejects `infinity` and retries only 5 × 1 s, so a healthy deploy can false-fail depending on timing.

Required narrow contract:

- finite future monotonic next activation → pass;
- `infinity` may pass **only** when live systemd evidence proves the healthcheck service is actively executing **and** the recurring monotonic timer schedule remains configured;
- `infinity` + inactive/failed service → fail;
- `infinity` + no live recurring schedule → fail;
- empty/zero next activation while nothing is executing → fail;
- `LastTriggerUSec` alone is never sufficient;
- prefer live properties such as `TimersMonotonic`, service `ActiveState`/`SubState`, and timer state over simply sleeping for the 90-second oneshot timeout.

Keep this change narrow and production-verify it before resuming B6. It is **post-incident deployment reliability**, not a new product phase.

---

# 12. GOVERNANCE / HOW CLAUDE SHOULD USE THIS FILE

When asked to implement or plan a feature:

1. locate the feature in `OWNER_FEATURE_INVENTORY.md`;
2. locate any detailed existing spec in `OWNER_PRODUCT_BACKLOG_SPEC.md`, product-specific docs, and this reconciliation;
3. check `OWNER_REQUESTED_TODO.md` for later binding owner decisions;
4. check `EXECUTION_PLAN.md` for whether the work is actually authorized now;
5. inspect current code/production behavior — repository intent is not production truth;
6. reconcile contradictions before coding;
7. state which canonical service owns the truth and which old/duplicate path will be retired or delegated;
8. write RED evidence for the actual bad contract before the repair when fixing correctness;
9. preserve missing/degraded/historical states;
10. stop for owner review at the phase checkpoint specified in the execution plan.

If a future owner conversation adds a material feature or materially changes intended behavior, update the detailed spec layer rather than merely adding a one-line to-do.

---

# 13. #809 STATUS / DESIGN-PLANNING REFERENCE

PR #809 contains valuable **docs-only candidate planning material**, including the Premium Sports Intelligence direction and detailed candidate specs for The Upside Report, Weekly Power Rankings, Awards & Honors, and source-family normalization.

Those concepts are intentionally restated here so the owner intent is not dependent on an unmerged branch.

**Do not merge #809 merely because this file references it.** #809 remains subject to explicit owner authorization and should be reconciled/cleaned when its material is promoted into canonical main documentation.
