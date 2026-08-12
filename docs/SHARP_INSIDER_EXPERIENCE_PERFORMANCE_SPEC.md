# Sharp Tracker + Insider Intelligence — Performance & Decision-Workflow Specification

**Status:** CANONICAL DETAILED PRODUCT / UX / PERFORMANCE SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** Sharp Intelligence / Insider Trading / Manager Intelligence / Trade Leads  
**Execution posture:** OWNER-APPROVED PRODUCT REQUIREMENT; implementation must follow `docs/EXECUTION_PLAN.md` and must not interrupt an already-authorized foundation pass unless the owner explicitly reprioritizes it.  
**Competitor posture:** absorb useful concepts from Play For Keeps and other products; do not copy branding, proprietary architecture, text, or private methodology.

---

## 1. Owner intent

The Sharp/Insider experience must feel fast, immediate and actionable rather than like a batch-analysis tool exposed through a webpage.

The current owner-observed Sharp Tracker can take **multiple minutes, sometimes upwards of five minutes, to populate**. That is a product defect, not an acceptable consequence of sophisticated analysis.

The owner establishes the following global rule:

> **No interactive feature should make a user wait more than five seconds for a useful state.**

Five seconds is an **absolute failure ceiling**, not the performance target. A feature that routinely finishes in 4.8 seconds still fails the intended experience.

Sharp intelligence must also support a coherent decision path:

**Who are the strongest managers? → What are they buying/selling? → Which of my actual league-mates has demonstrated interest in this asset elsewhere? → Does that manager need this position in my selected league? → What does that manager own that I could realistically ask for? → What offer should I make?**

This workflow should reuse canonical Brisket systems rather than create page-local valuation, roster-need, manager, trade-package or market engines.

---

## 2. Existing Brisket foundations to preserve

This specification deepens existing systems rather than replacing them.

Current product/code already separates:

- **Sharp Tracker** — global market behavior from a qualified manager cohort;
- **Sharp Roster Percentage** — ownership concentration across the same intended Sharp population;
- **Sharp People** — manager-centric Sharp surfaces;
- **Insider Trading** — league-scoped intelligence about what managers in the selected league have done in other tracked leagues;
- underlying transaction/movement receipts;
- automated, curated, provisional and other explicitly labeled qualification methods;
- configurable Sharp Score v2 methodology;
- source/platform provenance and coverage.

The finished experience should consolidate these into a connected workflow without merging concepts that have different populations.

**Sharp cohort behavior is not the same evidence population as the selected league's manager behavior.** They may inform one decision, but they remain separately named signals with lineage.

---

## 3. Performance contract — the five-second rule

### 3.1 Hard user-facing ceiling

For every normal interactive production surface:

- the UI must acknowledge an interaction immediately;
- useful content should normally appear far faster than five seconds;
- **no indefinite spinner is allowed**;
- by five seconds, the surface must show one of:
  - current result;
  - a valid last-known-good/stale-while-revalidate result with freshness disclosed;
  - a safe partial result whose missing portions are explicit;
  - an explicit unavailable/error state with retry behavior.

The system must never hide five minutes of backend work behind a loading state.

### 3.2 Performance targets

These are product targets to validate on realistic production-shaped data, not excuses to fabricate green synthetic numbers:

- **interaction acknowledgement:** effectively immediate; target <100 ms for local feedback;
- **warm/cached first useful data:** target <=1 second;
- **normal p95 first useful data:** target <=2 seconds where the architecture permits;
- **cold/uncached but supported path:** target <=3 seconds where reasonable;
- **absolute useful-state deadline:** <=5 seconds;
- filter/sort/window changes over already-loaded data should be local/sub-second when the result can be derived safely client-side;
- server-backed filter changes should be designed around indexed/precomputed slices rather than rebuilding the Sharp universe.

If measurements show a specific surface cannot meet these targets without changing its architecture, change the architecture rather than weakening the target silently.

### 3.3 Measure the right things

Performance acceptance must include production-shaped instrumentation for:

- navigation → first meaningful shell;
- navigation → first useful data;
- navigation → complete primary view;
- API p50 / p95 / p99;
- payload size;
- server compute time;
- cache hit/miss state;
- browser render/hydration time;
- mobile device behavior;
- warm and cold process/cache cases;
- stale-while-revalidate behavior;
- filter/sort/drill-down latency.

Do not report a server-function microbenchmark as page latency, and do not report a cached path as proof of cold-path behavior without naming it.

### 3.4 Performance regression gates

Add repeatable performance probes/budgets for the high-value interactive surfaces, including Sharp Tracker and Insider Trading.

A future PR that materially regresses those budgets must fail or require an explicit reviewed budget decision; performance cannot be allowed to drift back to minutes after a one-time optimization pass.

---

## 4. Measured/current Sharp architecture contradiction to repair

The current Sharp Tracker client explicitly defeats caching:

- appends a timestamp cache-buster to requests;
- uses `cache: "no-store"`;
- sends no-cache/no-store request headers;
- retries requests up to three times;
- independently loads cohort and market data;
- automatically refreshes both every 60 seconds.

The current Next bridge for `/api/sharp/market` likewise forces dynamic/no-store behavior and allows a 20-second proxy timeout; the cohort bridge allows a 15-second timeout.

At the same time, the FastAPI Sharp market endpoint explicitly advertises short-lived caching with `private, max-age=120, stale-while-revalidate=300`.

This is an architectural contradiction: one layer declares the result reusable while the next layers deliberately prevent reuse.

### Required repair direction

Do not merely shorten a timeout while leaving the expensive request architecture intact.

Investigate and repair the full path:

1. request fan-out;
2. cache busting;
3. frontend/bridge/backend cache-policy disagreement;
4. synchronous cohort scoring/reconstruction on user requests;
5. synchronous market aggregation on user requests;
6. repeated disk parsing / ledger scans / manager scoring;
7. auto-refresh behavior that can create unnecessary recomputation or request stampedes;
8. duplicate work across Sharp Tracker, Roster %, Sharp People and Insider surfaces;
9. payload/render cost;
10. cold-start and lock/contention behavior.

The default architecture should be **materialize/refresh expensive intelligence off the request path, then serve a compact indexed snapshot quickly**.

User requests are consumers of prepared intelligence, not triggers for crawling the Sleeper graph or rebuilding the Sharp cohort.

---

## 5. Canonical fast-serving architecture

The exact storage technology is implementation-dependent, but the ownership model is not.

### 5.1 Background production

Scheduled/background jobs may perform expensive work such as:

- graph discovery;
- transaction acquisition;
- record reconstruction;
- Sharp Score evaluation;
- roster-quality calculation;
- cohort membership/versioning;
- multi-window buy/sell aggregation;
- Sharp Roster % aggregation;
- manager/player indexes;
- Insider cross-league movement indexes.

They should write versioned/materialized outputs with timestamps, input hashes and methodology versions.

### 5.2 Request path

The normal request path should primarily:

- authenticate/authorize;
- resolve requested league/user/filter;
- read an indexed/materialized snapshot;
- apply cheap filtering/sorting/pagination;
- join small league-specific context where needed;
- return freshness/coverage metadata.

It should **not** rebuild the manager universe to answer a page view.

### 5.3 Stale-while-revalidate

When a valid previous snapshot exists:

- serve it immediately;
- disclose age/freshness where material;
- refresh in the background;
- atomically replace the snapshot when the new one succeeds;
- never erase the last known good snapshot merely because one refresh failed.

Stale data and missing data are different states.

### 5.4 Cache key correctness

Caches/materializations must include every dimension that changes the result, such as appropriate combinations of:

- Sharp methodology/cohort version;
- source dataset/version;
- time window;
- qualification population;
- platform/source filter;
- asset type;
- selected league for league-specific intelligence;
- canonical player/manager identity version where material.

Do not use a stale cache to manufacture cross-population equivalence.

---

## 6. Sharp cohort — concept to preserve and improve

Play For Keeps' public explanation highlights three intuitive dimensions: active dynasty-league breadth, roster value, and winning. Brisket already has a richer Sharp Score v2 and should **not** replace it with those three bullets merely for parity.

The intended Brisket methodology remains evidence-driven and versioned, including concepts such as:

- multi-league dynasty breadth;
- sustained performance/winning;
- playoff/championship results where defensible;
- multi-league consistency;
- longevity;
- continued activity;
- uncertainty/confidence;
- roster/portfolio quality relative to each league's context;
- explicit qualification gates and reasons.

### 6.1 Finish the roster-quality evidence lane

The current Sharp Score documentation says the roster-quality component is designed but not populated by the current record builder.

That is a real future requirement: populate it from canonical roster/value evidence with league-relative normalization and provenance, then validate whether it improves identification of genuinely strong managers.

Do not count missing roster-quality evidence as zero.

### 6.2 Do not target a competitor's cohort size

Do not choose `~1,500` Sharps because another product displays that number.

Cohort size should emerge from:

- observed population;
- data coverage;
- minimum evidence gates;
- score/confidence methodology;
- validation of whether cohort behavior predicts useful future outcomes.

The UI can show the actual funnel transparently, e.g. observed → record-bearing → evaluable → qualified → super/high-confidence.

### 6.3 Cohort tiers

Preserve explicit provenance/tiering rather than flattening every person into one vote. Potential named populations include:

- automated Sharp Score qualifiers;
- Super/High-Confidence Sharps;
- curated dynasty-industry Sharps;
- curated high-stakes managers;
- provisional observations that are visible but not allowed to masquerade as qualified Sharp evidence.

Multiple qualifications for one manager do not create multiple managers or multiple votes.

---

## 7. Sharp Tracker — finished global market surface

The global Sharp Tracker should make it easy to answer:

- Who are qualified Sharps?
- What are they buying?
- What are they selling?
- What behavior is persistent rather than one noisy trade?
- How many unique managers and leagues support the signal?
- How recent is it?
- Does the signal differ by format/source where supported?

Core views should include:

- buys;
- sells;
- net flow;
- transaction volume;
- unique Sharp managers;
- unique leagues;
- velocity/change in activity;
- signal direction/strength;
- confidence/sample depth;
- source/platform provenance;
- last activity/freshness;
- 48h / 7d / 14d / 30d / 90d or empirically justified windows;
- player drill-down into underlying transactions/movements;
- links to Universal Player Profile;
- links to Sharp Roster % and related market evidence.

### 7.1 Persistent buying/selling

"Consistent buying is signal; consistent selling is signal" is useful framing, but the implementation must distinguish:

- one manager trading a player repeatedly;
- many unique managers independently acquiring the player;
- the same underlying transaction observed through multiple sources;
- one league creating multiple movement rows for one trade;
- repeated windows showing the same transaction.

The same event never becomes multiple independent votes.

### 7.2 Format context

Where the source evidence supports it, Sharp behavior should eventually expose/condition on material league-format context rather than implying all dynasty trades are equivalent:

- 1QB / Superflex / 2QB;
- TE premium / TE starter demand;
- team count;
- lineup depth;
- IDP state/structure;
- best-ball/managed where material.

This must use the same format/provenance architecture as the Market Trade Ledger, not a Sharp-only formatter.

---

## 8. Insider Trading — finished league-specific decision workflow

Insider Trading is **not** another Sharp Tracker. Its population is the managers in the user's selected league.

The finished workflow should support both **SELL** and **BUY** journeys.

### 8.1 Step A — selected league is explicit

All league-specific values, roster needs, owners, draft capital and trade leads must resolve from the selected league.

League settings control the relevant positions and roster context. Never hard-code only QB/RB/WR/TE when the selected league includes Superflex, multiple TE demand or IDP.

### 8.2 Step B — show the user's needs first

Before selecting a trade target, show the user's canonical positional/roster strengths and weaknesses.

Use the canonical Team Strength/Weakness / replacement / PAR methodology when those systems are production-ready.

Possible display:

- position rank within league;
- STRONG / MID / NEED or the approved Brisket language;
- depth/starter sufficiency;
- optional contender-window context.

For IDP leagues, include DL/EDGE, LB, DB and any other canonical league position group rather than omitting half the roster.

### 8.3 Step C — choose player to sell or search player to buy

**Sell mode:** roster grouped by position with current values and compact chips showing whether selected-league managers have bought/sold that player elsewhere.

**Buy mode:** search any player and/or browse league managers/rosters, then identify the current owner in the selected league.

A BUY/SELL chip must represent an actual tracked observation with recency/sample provenance, not inferred preference.

### 8.4 Step D — Insider Report / receipts

For the selected player, show the real matching transactions made by current league-mates in other tracked leagues, newest first.

Where source data permits, each result should include:

- manager;
- bought/sold direction;
- date/recency;
- league/source provenance;
- the **full trade package**, not merely one movement row;
- material format metadata;
- value-at-time/current-value context when historically defensible;
- confidence/coverage.

This should progressively migrate from movement-only evidence to the canonical Market Trade Ledger transaction/package identity where available.

### 8.5 Step E — combine demonstrated behavior with current need

For each current league-mate, show separately:

- **PROVEN INTEREST:** observed buying/holding/selling history for this player or relevant asset archetype;
- **CURRENT NEED:** the manager's canonical positional/roster need in this selected league.

The intersection is a stronger lead than either signal alone.

Do not convert "bought once" + "needs RB" into certainty. Preserve recency, count, confidence and explanatory text.

### 8.6 Step F — manager drill-down

Tapping/clicking a manager should open their selected-league scouting view with:

- current roster;
- positional strengths/needs;
- draft picks;
- roster age/window where useful;
- surplus/shortage positions;
- Manager Scout tendencies;
- relevant historical transactions;
- players/picks they own that could plausibly return for the selected asset.

### 8.7 Step G — Similar Value / Possible Return Finder

Provide a canonical return-finder using the site's value/package engine, not a page-local +/- percentage filter.

It can show:

- similarly valued assets owned by that manager;
- grouped by position/asset class;
- picks and players;
- package combinations when one-for-one value does not fit;
- consolidation/package adjustment;
- KTC Value Adjustment as an advisory market lens where approved;
- real comparable-trade evidence from Market Trade Ledger;
- roster-fit impact for both teams.

Badges/labels may convey concepts such as:

- demonstrated buyer of your player;
- current positional need;
- both signals present;
- frequent trader / preferred asset type from Manager Scout.

Do not copy competitor iconography or badge names verbatim if Brisket has better product language.

### 8.8 Step H — hand off to execution intelligence

A strong lead should be actionable in one or two taps:

- open Trade Desk / Package Builder;
- prefill counterparty and selected asset;
- suggest realistic opening/fair/walk-away packages through Negotiation Coach;
- show recent comparable trades;
- show roster impact;
- show canonical value/equity;
- show relevant league and manager evidence.

Insider Trading discovers **who to call**. Trade Desk/Negotiation Coach helps determine **what to offer**. Do not rebuild negotiation logic inside the Insider page.

---

## 9. Buying workflow requirements

The BUY path is not the SELL path with labels reversed.

When researching a target:

1. resolve the current owner in the selected league;
2. show that owner's needs and surplus;
3. show whether that owner has historically bought/sold the target or relevant comparable assets elsewhere;
4. show the user's assets that satisfy that owner's needs;
5. show realistic packages from the canonical package engine;
6. let the user pivot among players on that owner's roster without losing the counterparty context;
7. preserve a clear route back to the original target.

This supports the practical question:

> "What does this specific manager tend to accept, and what do I own that solves their current problem?"

---

## 10. Guided onboarding / "How it works"

The screenshots demonstrate that this intelligence can be complex enough to benefit from progressive onboarding.

Brisket should support:

- a concise **How it works** explainer;
- an optional interactive guided tour over the real interface;
- Skip / Back / Next;
- replay from help;
- do not force the tour on repeat visits;
- never block the real page from loading while the tour renders;
- explain the distinction among observations, inferences and recommendations.

The tour should teach the decision workflow, not become the workflow.

---

## 11. Data lineage and anti-double-counting

Required lineage examples:

- Sharp transaction → Sharp buy/sell aggregate;
- same Sharp transaction → Market Trade Ledger if eligible;
- same transaction observed through KTC and Sleeper → one underlying market trade;
- selected league-mate's transaction → Insider evidence;
- Sharp cohort status of that same manager → separate manager qualification attribute;
- roster need → canonical Team Strength/Weakness evidence;
- possible returns → canonical values/package engine.

A transaction may legitimately appear on multiple **surfaces**, but it remains one underlying event.

Do not interpret:

- one raw movement;
- one full trade;
- one Sharp aggregate;
- one Insider lead;
- one KTC observation of that same trade

as five independent confirmations.

---

## 12. Missing / insufficient evidence

- no recent Sharp trades != SELL;
- no Insider history != manager has no interest;
- no external-league match != manager never traded the player;
- no current need != manager will refuse the player;
- no trade package detail != a one-for-one trade;
- no roster-quality evidence != zero roster quality;
- stale snapshot != current truth;
- empty result caused by unsupported source coverage must be distinguishable from a verified zero.

Every actionable badge/metric needs appropriate sample count, freshness, coverage and provenance.

---

## 13. Privacy boundary

Global aggregate Sharp intelligence may be public-safe where its underlying data rights permit.

League-specific Insider Trading, manager tendencies, trade leads, negotiation targets, roster weaknesses and personalized recommended packages are **private decision intelligence** unless an explicit public product decision says otherwise.

Do not expose a user's private front-office edge through the public `/league` experience merely because the raw transactions themselves are public host data.

---

## 14. Required implementation investigation before repair

When this performance repair is authorized, do not begin by guessing at a cache TTL.

Instrument and report the actual critical path for:

- `/market/sharp-tracker` cold page;
- warm page;
- `/api/sharp/cohort`;
- `/api/sharp/market`;
- Sharp Roster %;
- Insider Trading board;
- player/member drilldown;
- trade lead request.

For each, measure:

- browser timing;
- frontend bridge timing;
- backend timing;
- time spent loading/parsing ledger files;
- manager-record construction;
- Sharp scoring;
- market aggregation;
- network/source calls, if any;
- lock waits;
- cache behavior;
- payload bytes;
- render cost.

Then establish the largest measured contributors and repair root causes in descending order.

The current cache-busting/no-store contradiction is already a specific known item to reproduce, but it must not be assumed to explain the entire multi-minute delay without measurement.

---

## 15. Acceptance tests for the fast experience

The finished repair needs executable/browser evidence that:

1. the normal Sharp page serves a useful result within the approved performance budget;
2. warm/cached requests are substantially faster than cold recomputation;
3. changing sort/window/source does not rebuild the entire data universe unnecessarily;
4. a background refresh cannot block a user request for minutes;
5. one failed refresh does not erase the last-known-good view;
6. concurrent users do not trigger duplicate expensive rebuilds (request stampede);
7. auto-refresh does not continuously bypass caches;
8. stale/missing states render honestly;
9. payload size and DOM/render cost remain within measured budgets;
10. mobile behavior meets the same five-second useful-state ceiling;
11. Sharp / Roster % / Insider surfaces that claim the same cohort use the same canonical cohort owner/version;
12. no 7d/14d/30d double counting occurs when windows are compared or summarized.

---

## 16. Product status

**Five-second maximum useful-state rule:** OWNER-APPROVED GLOBAL PRODUCT REQUIREMENT.  
**Sharp Tracker multi-minute latency:** HIGH-PRIORITY PRODUCT DEFECT.  
**Fast materialized/off-request-path architecture:** APPROVED DIRECTION; exact implementation must be measurement-driven.  
**PFK-like Sharp → Insider → manager roster → possible return workflow:** OWNER-APPROVED CONCEPT, to be implemented using Brisket canonical systems rather than copied UI/architecture.  
**Finish Sharp Score roster-quality lane:** APPROVED FUTURE METHODOLOGY REQUIREMENT; validation required before changing qualification behavior.  
**Competitor cohort size/thresholds:** NOT adopted.  
**Guided tour:** APPROVED UX DIRECTION, subordinate to speed and core functionality.  
**New production work during an unrelated foundation phase:** NOT AUTHORIZED by this spec alone.
