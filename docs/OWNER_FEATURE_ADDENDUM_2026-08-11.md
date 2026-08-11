# Owner Feature Addendum — 2026-08-11

**Status:** BINDING OWNER-APPROVED PRODUCT / MODEL REQUIREMENTS.  
**Execution status:** durable scope record only. These requirements must be integrated into the authoritative master inventory/dependency plan at the appropriate reconciliation checkpoint. They do **not** authorize interruption of the currently isolated B2 IDP curve-routing pass.

This addendum records owner requirements that must not be lost between coding sessions. It complements `docs/OWNER_FEATURE_INVENTORY.md`, `docs/competitive/`, and `docs/OWNER_REQUESTED_TODO.md`.

---

## A. YouTube Dynasty Intelligence — extend Podcast Intelligence, do not duplicate it

**Tracking:** #782  
**Classification:** KEEP — NEW BUILD, staged with Podcast Intelligence  
**Likely phase:** E6 / intelligence after foundations

### Owner intent

Build a major dynasty-fantasy YouTube ingestion pipeline modeled on the Podcast Intelligence system.

- Research approximately **50 reputable dynasty fantasy football YouTube sources/channels** and ingest relevant current videos.
- Explicitly cross-reference the Podcast Intelligence source registry and **exclude / dedupe any YouTube source that is already represented as a podcast/show/analyst feed**.
- A podcast episode uploaded to YouTube is not a second independent opinion.
- The goal is a recurring source ecosystem, not a static one-time list of 50 individual videos.

### Shared downstream behavior

After canonical transcript/take extraction, YouTube intelligence should be eligible for the same appropriate downstream products as Podcast Intelligence:

- Consensus Edge / one bounded intelligence signal;
- Central Buy/Sell reconciliation where methodology permits;
- player-specific intelligence;
- selected-team intelligence;
- news/Analyst Pulse context;
- buy/sell analysis;
- personalized weekly team podcast/brief;
- other surfaces already approved to consume Podcast Intelligence.

### Canonical architecture

YouTube should reuse/extend the Podcast Intelligence foundations:

1. source/channel/show registry;
2. stable content IDs and publication times;
3. official/authorized transcript/caption/provider acquisition;
4. analyst/speaker identity;
5. structured actionable dynasty-take extraction;
6. NO SIGNAL as the common outcome when no actionable dynasty stance exists;
7. syndication/repost/clip deduplication;
8. analyst/network independence and correlation handling;
9. freshness/coverage/confidence;
10. one bounded downstream ranking/intelligence input rather than one weight per channel.

Missing or unavailable transcripts remain neutral/missing; they must not become zero/SELL.

---

## B. Universal Player Profile — one canonical player intelligence feed

**Tracking:** #783  
**Classification:** EXTEND existing 5.6 + 6.6 + 8.3/8.4 and future YouTube intelligence  
**Likely phase:** intelligence/profile work after canonical identity

Every Universal Player Profile should surface a useful, player-specific intelligence/news section built from canonical source data already ingested by the platform.

### Eligible sources

- Podcast Intelligence structured takes and source evidence;
- YouTube Dynasty Intelligence structured takes;
- Sleeper news;
- RotoWire;
- RotoBaller;
- every other canonical fantasy-news source already ingested;
- later Sharp / Insider / Consensus context where useful and clearly labeled.

### Presentation decision

The owner does **not** require one rigid rendering style. Choose the presentation that is most useful and legally/provenance-safe:

- short attributed excerpts where appropriate;
- source cards/headlines + summaries;
- one synthesized recent player-intelligence summary;
- or a hybrid.

The product goal is **one useful player-specific intelligence feed**, not raw article/transcript duplication.

### Required semantics

- factual news and analyst opinion remain visibly distinct;
- every item has source + as-of/publication time + provenance;
- synthesized summaries remain traceable to supporting items/takes;
- syndication/duplicate reports do not masquerade as independent corroboration;
- podcast/YouTube analyst independence carries through;
- missing evidence stays missing;
- copyrighted source material is summarized/linked/briefly excerpted rather than copied wholesale.

---

## C. Homepage Consensus Edge / Buy-Sell stock ticker

**Tracking:** #784  
**Classification:** REFINE/RECONCILE existing inventory items 4.2 + 4.3  
**Likely phase:** E2 after canonical Buy/Sell owner

Add a stock-market-style horizontally moving ticker on the homepage for actionable current buy/sell intelligence.

### Binding eligibility rule

- **BUY:** may include worthwhile targets from the broader relevant player universe.
- **SELL:** may include **only players currently rostered by the selected fantasy team**.
- The owner does not want SELL calls for assets the selected team does not own.

### Canonical-source rule

The ticker is a presentation surface, not a new algorithm.

- It must consume the canonical persisted/reconciled Buy/Sell output when 4.2 exists.
- Consensus Edge may be a major upstream input, but the frontend must not recompute Consensus Edge or maintain another threshold set.
- If the surface retains the product name **Consensus Edge ticker**, document clearly how the displayed verdict maps to the canonical Buy/Sell owner so there is no duplicated/circular signal logic.

### UX

- horizontal stock-ticker feel;
- player + BUY/SELL + concise context/score where defensible;
- tap/click to Universal Player Profile/intelligence detail;
- freshness/as-of state;
- touch/keyboard/screen-reader/reduced-motion support;
- no duplicate items from multiple upstream emitters.

---

## D. Tight-End Premium / two-TE valuation must be deeply validated, not assumed

**Tracking:** #785  
**Classification:** KEEP — FOUNDATIONAL VALUATION AUDIT/REPAIR  
**Likely phase:** Phase B / league-adjusted value quality after isolated B2 if not directly coupled

The owner is specifically concerned that tight ends may still be undervalued relative to a true two-TE / TE-premium environment and wants the entire methodology revalidated from current evidence.

### Important current-repo context

`src/league_intel/te_premium.py` already contains a much more sophisticated foundation than the original flat `1.15` approach:

- two mandatory TE starters are recognized as structural demand;
- source alignment and league demand are treated as separate axes;
- the repo has a measured KTC TE-premium curve rather than only a blanket factor;
- source-basis conversion is intended to be explicit/idempotent.

Therefore this requirement is **not permission to create a new TEP engine**. It is a request to prove the current canonical system is complete and correct, and to eliminate any stale bypasses/default factors that remain elsewhere.

### Required current-HEAD audit

1. **Actual league settings**
   - derive mandatory TE slots, FLEX/SF eligibility and scoring from the real league configuration;
   - quantify TE scoring relative to WR/RB under the exact scoring rules;
   - treat two mandatory TE starters as structural scarcity even if explicit TE scoring bonuses are small/absent.

2. **Every ranking/value source**
   - identify which version we ingest: base, TEP, TE++, or another adjusted board;
   - where the provider publishes both regular and TEP variants, measure the actual player/rank-dependent difference;
   - do not assume a flat premium if the provider's observed uplift is curved/nonlinear;
   - for sources without native TEP, document the conversion onto the league target basis.

3. **KTC as diagnostic market baseline**
   - re-measure current base→TE-premium behavior from fresh legitimate KTC inputs;
   - test elite, mid-tier, starter, TE2, fringe and deep ranges;
   - verify the current two-TE target-basis assumption and curve/floor/ceiling remain defensible;
   - do **not** force the site to equal KTC merely because KTC is higher.

4. **No double counting**
   - a source already on the target TEP basis must not receive another league premium;
   - source alignment and league demand remain separate concepts;
   - conversions must remain idempotent and provenance-aware.

5. **Cross-position calibration**
   - compare final TEs against WR/RB/QB and league-specific replacement/scarcity/realized scoring evidence;
   - determine whether our board systematically under- or over-values TEs relative to the league environment and independent source evidence.

6. **Whole-tree stale-factor audit**
   - search for `1.15`, old TEP flags, duplicate multipliers, UI/config defaults and any code path bypassing the canonical TEP owner;
   - justify, reconcile or eliminate every surviving factor.

### Success criterion

The target result is **evidence that our TE values are defensible for this exact two-TE league**, not an arbitrary upward adjustment and not blind parity with KTC.

If current behavior is already correct, prove it and leave it alone. If not, repair the canonical owner and remove conflicting/stale logic.

---

## E. Trade Simulator — value-weighted NFL-team exposure before/after

**Tracking:** #786  
**Classification:** EXTEND 1.3 roster-aware trade simulation + CE-05 Trade Desk + CE-06 Dynasty Portfolio exposure primitive  
**Likely phase:** decision products after canonical roster/value foundations

Add NFL-team exposure to **Simulate Impact** for proposed trades.

### Owner intent

This is informational context only. It should **not affect whether the system recommends the trade** unless a later explicit owner policy changes that.

### Required metric

Raw player count alone is insufficient because assets have different importance/value.

Primary display should be **canonical-value-weighted NFL-team exposure**:

`team exposure % = canonical value of rostered players on NFL team / canonical value of priced rostered players included in the exposure denominator`

Show before → after and percentage-point change.

Raw player-count exposure may be secondary context.

### Example presentation

- MIN 21.4% → 25.9% (+4.5 pp)
- KC 12.1% → 8.6% (-3.5 pp)

### Guardrails

- this is NFL-team concentration, not fantasy-team ownership;
- draft picks normally have no NFL-team exposure and should not be assigned artificially;
- missing/unpriced players remain explicit rather than silently becoming zero;
- intentional stacks or QB starter/backup handcuffs are descriptive, not automatically bad;
- the exposure display must not leak into trade grade, package adjustment, Team Strength or Buy/Sell scoring by default.

### Reuse

Build one reusable NFL-team exposure primitive that can also power CE-06 Dynasty Portfolio. Do not implement one formula on the Trade page and another in Portfolio.

---

# Integration / scope-control rules

1. These five requirements are **approved scope** and must not be forgotten.
2. Issues #782–#786 are the detailed tracking records.
3. The later master reconciliation must integrate them into `docs/OWNER_FEATURE_INVENTORY.md` / dependency graph rather than leaving this addendum orphaned.
4. Reuse canonical systems; do not create duplicate Podcast/YouTube intelligence engines, duplicate Buy/Sell engines, duplicate TEP models or duplicate exposure formulas.
5. Current foundational/B2 work remains the critical path. Do not start these items merely because this document was added.
6. Missing data remains different from zero everywhere.
7. Any source-derived intelligence requires provenance, freshness, coverage and anti-double-counting/independence semantics.
