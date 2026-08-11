# Competitive Expansion Addendum — Dynasty Daddy

**Owner status:** APPROVED FUTURE PRODUCT SCOPE derived from the 2026-08-11 Dynasty Daddy competitive audit.  
**Execution status:** PLANNING ONLY. Do **not** interrupt current B2/foundational correctness work and do not begin production implementation merely because this file exists.

This file is an authoritative companion to `docs/OWNER_FEATURE_INVENTORY.md` §12 (OTC Fantasy + Play For Keeps competitive expansion) and `docs/competitive/DYNASTY_DADDY_FEATURE_AUDIT.md`.

When the competitive reconciliation pass is eventually performed, the entries below must be integrated into the master owner inventory / dependency plan without silently deleting or weakening them. Existing canonical owners win over creating parallel engines.

---

## 1. Existing CE entries — binding Dynasty Daddy enrichments

### CE-03 — Manager Scout / Manager Intelligence

Add future requirements:

- manager-tendency presentation directly on team and trade surfaces;
- fantasy-behavior features only;
- sample size, coverage, confidence and recency;
- historical trade/pick/roster-construction tendencies where canonical transaction history supports them;
- no psychological profiling or real-world enrichment.

Dynasty Daddy's 2026 feature feed documents manager-tendency team pages; the implementation methodology here must be ours.

### CE-04 — Dynasty Command Center

Add **Watchlist / Target List** behavior as a consumer of the canonical event feed:

- user can watch/target a player;
- optional owner note/reason;
- optional threshold conditions for value/ADP/availability/news/Sharp movement;
- deduped actionable updates rather than notification spam;
- no new ranking/value engine.

### CE-05 — Trade Desk + 1.3 roster-aware trade simulation

Add an optional **league-impact simulation** after the core before/after roster impact is correct:

- Team Strength before/after;
- positional-strength/weakness impact;
- Power Ranking movement only through the one canonical Power Rankings engine;
- playoff-odds movement only through the one canonical playoff engine;
- clear provenance that these are downstream consequences, not part of raw trade value.

### CE-06 — Dynasty Portfolio / Exposure

Add explicit requirements:

- value-weighted player exposure;
- position exposure;
- NFL-team exposure;
- age exposure;
- contender/rebuilder exposure;
- QB/pass-catcher and other stack exposure;
- pick exposure by year/round;
- cross-league player availability / free-agent opportunity view;
- sortable/reorderable linked leagues;
- drill-through to league/team context.

Descriptive by default; do not force diversification judgments absent owner policy.

### CE-08 — Projections & Stats Hub

Add:

- multi-season player statistics;
- historical rostered/start percentages where legitimately sourced;
- projection-source provenance;
- projection-accuracy scorecard over time;
- support the inputs required by CE-12, CE-17 and CE-09 without duplicating scoring logic.

### CE-09 — Replacement Value / PAR / WAR

Add an **evidence-gated research variant** for startability-adjusted realized contribution:

- use our own methodology;
- ask how much above-replacement production was actually predictable/startable and captured in lineups;
- keep it distinct from canonical dynasty market value;
- require leakage-safe validation and documented assumptions before calling it WAR or using it in decisions.

### CE-10 — Share Renderer / Team Cards

Explicitly support:

- normal Team Card;
- Anonymous Team Card;
- stable share link where appropriate;
- later Team Legacy / League Legacy cards;
- later CE-21 season-recap cards;
- privacy-safe redaction in anonymous mode.

### CE-11 — Sleeper Action Gateway

Future supported mutation classes may include, after auth/security readiness:

- send/respond to trades;
- lineup writeback;
- waiver claim creation;
- waiver bid/drop modification;
- pending-waiver withdrawal;
- trade-block add/remove;
- supported team/nickname metadata writeback when useful;
- draft actions only where platform API semantics are safe and explicit.

All writes require preview, authorization, audit, idempotency and visible errors. Recommendation never equals permission to execute.

### CE-12 — Lineup Intelligence

Add the following to the eventual feature contract:

1. max-projection lineup baseline;
2. schedule-aware FLEX-slot optimization that preserves late-game flexibility without overriding materially superior projections;
3. waiver/free-agent alternatives when available players improve the real starting lineup;
4. weather / dome / game-status context;
5. projection provenance + historical accuracy;
6. ceiling/aggressive mode only if a defensible ceiling model exists;
7. optional future writeback through CE-11 only.

### CE-13 — Draft Room

Add:

- live active-draft synchronization;
- picked/available state updated during the draft;
- tier board;
- best available from canonical/personal rankings;
- Market ADP;
- Universal Player Profile drill-through;
- Team Weakness context;
- Perfect Draft optimizer output;
- pick-trade analysis and real trade comps.

Perfect Draft remains the optimizer. Draft Room is the workspace.

### CE-14A — Personal Rankings Overlay

Add optional import support:

- CSV/manual ranking import;
- mapping/validation to canonical player identity;
- private user ordering only;
- never overwrite canonical site ranks or values.

### CE-15 — Portfolio Trade Campaign

Add pattern-based candidate generation where useful:

- player-for-player;
- multi-asset;
- pick-round constraints;
- equal-market-value constraints;
- FAAB as a supported asset where league/platform semantics allow it.

Still require human review, cooldowns and duplicate protection. No mass-spam default.

### Existing 6.3 / 6.4 — Franchise history + Public League

Add explicit League/Team Legacy parity requirements:

- multi-year franchise identity;
- owner changes do not erase the franchise;
- all-time W/L and head-to-head;
- regular-season vs playoff splits;
- titles / finals / playoff wins;
- longest streaks;
- season-by-season finishes;
- all-time transaction/draft views where data exists;
- team/franchise legacy page;
- shareable history cards through CE-10.

### Existing 6.6 — Universal Player Profile

Add a competitor-parity floor:

- age / experience / team / position / college as available;
- canonical value, overall rank, position rank, tier and confidence;
- pick-equivalent value band;
- historical value views (1M/3M/6M/1Y/all-time only when real history exists);
- ADP history;
- multi-season realized stats;
- rostered/start percentages and history where legitimately sourced;
- adjacent overall assets + positional assets + picks;
- real trade comps;
- Sharp cohort ownership/activity with independence and sample metadata;
- roster context;
- acquisition/holding-period history;
- BDVM / Podcast / News / Consensus context.

Missing history remains missing unless explicitly reconstructed with provenance.

---

# 2. Net-new approved CE entries

## CE-17 — League Format / Utilization Lab

**Classification:** KEEP — NEW SURFACE  
**Priority:** high-value Tier 2-ish after scoring/stats/replacement foundations  
**Dependencies:** canonical scoring settings/correctness, CE-08 Projections & Stats, CE-09 replacement metrics, canonical identity

### User job

Answer:

> What does this exact league's scoring and roster format make productive, scarce, startable and strategically important?

### Scope

- season and week filters;
- multi-season comparisons;
- offensive + IDP stat research;
- utilization/opportunity metrics;
- target/rush/route/air-yard style metrics where sourced;
- quality-start / spike-week / consistency distributions;
- PAR/WAR/WoRP-like outputs from CE-09;
- positional distribution views;
- team/player search and highlighting;
- sortable/reorderable columns;
- configurable charts;
- custom filters;
- saved named presets/views.

### Guardrails

- CE-17 owns the **research surface**, not the data engines;
- no second scoring implementation;
- no second WAR implementation;
- every metric carries source/as-of and missing state;
- user-defined views alter presentation only, not underlying truth.

---

## CE-18 — Trade Trees / Asset Lineage

**Classification:** KEEP — NEW BUILD  
**Priority:** Tier 2/3 after stable history/identity  
**Dependencies:** stable pick identity, acquisition/holding-period history, canonical league transaction history; CE-01 may supply market context later

### User job

Answer:

> How did this player/pick/team asset get here, what was exchanged along the way, and what did those branches turn into?

### Scope

- league-local trade tree by franchise;
- player/pick acquisition lineage;
- pick transformations through original/current owner identity;
- multi-incoming/multi-outgoing package preservation;
- re-acquisitions create separate holding periods;
- transaction date and contemporaneous value provenance;
- optional realized/current outcome view separated from trade-day judgment;
- drill from player profile, franchise history and Trade Desk;
- shareable lineage card later via CE-10.

### Guardrails

- Trade Trees != CE-01 broad-market Trade Database;
- today's values must not masquerade as historical values;
- provenance: RECORDED / HISTORICAL SNAPSHOT / RECONSTRUCTED / UNAVAILABLE;
- never collapse multi-asset cost basis into one player's acquisition value.

---

## CE-19 — Waiver Market / FAAB Market Ledger

**Classification:** KEEP — NEW BUILD  
**Priority:** Tier 2-ish; can materially improve FAAB context once transaction ingestion is trustworthy  
**Dependencies:** canonical player identity, league-format metadata, broad transaction ingestion, FAAB budget normalization

### User job

Answer:

> What is the broad market actually paying/claiming for this waiver player right now, and how does that compare with our recommendation for this league?

### Scope

- recent broad-market claims/adds;
- winning FAAB amounts;
- normalized percentage of starting budget / available budget where defensible;
- bid distribution / robust range;
- claim count/sample size;
- dynasty vs redraft separation;
- 1QB vs SF / scoring-format filters where available;
- recency windows;
- player history;
- Market Pulse integration;
- FAAB page market-context panel.

### Guardrails

- broad market != Sharp ledger;
- market price != recommended bid;
- no evidence != zero bid;
- exclude/label leagues whose FAAB semantics are incompatible;
- never double count one transaction through multiple ingestion feeds.

---

## CE-20 — Game Day Command Center

**Classification:** KEEP — OPTIONAL / FUTURE  
**Priority:** Tier 5 / after core dynasty decision products and multi-league foundations  
**Dependencies:** multi-league ownership, CE-08 stats/projections, CE-12 lineup intelligence, news/status events

### User job

One live view for all relevant fantasy action without flipping between league apps.

### Scope

- all active starters across linked leagues;
- live scoring and projection deltas;
- matchup status;
- rostered/target-player big-play feed;
- injuries/status changes;
- game start/lock status;
- pre-lock lineup warnings;
- filter by league/team/player;
- optional news/highlight context where rights/data access permit.

### Guardrails

- no new scoring engine;
- CE-20 != CE-04 Dynasty Command Center: game-day situational awareness vs strategic action prioritization;
- no social-network build required.

---

## CE-21 — Dynasty Season Recap / Wrapped

**Classification:** KEEP — OPTIONAL / FUTURE  
**Priority:** Tier 5 / after history and share infrastructure  
**Dependencies:** franchise/league history, acquisition/trade/draft/waiver history, CE-10 Share Renderer

### User job

Generate a data-rich end-of-season league/team recap from canonical history.

### Scope

- season result/playoff run;
- best/worst trades using contemporaneous and current views kept separate;
- best waiver additions;
- draft hits/misses;
- largest value rises/falls;
- lineup efficiency/luck only if methodology is defensible;
- rare or unusual roster facts;
- all-time/season context;
- benchmark percentile only against a legitimate comparison population;
- shareable cards/pages.

### Guardrails

- CE-21 != generic League Media/CMS, which remains removed;
- no fake global percentile without benchmark data;
- no need to reproduce competitor gimmicks such as song matching;
- analytics first, entertainment second.

---

# 3. Canonical owner / duplicate-risk map

| Capability | Canonical owner | Must NOT become |
|---|---|---|
| League Format Lab | CE-17 surface over CE-08/09 | second stats/scoring/WAR engine |
| Trade Trees | league transaction + acquisition lineage | CE-01 market-wide trade ledger clone |
| Waiver Market | CE-19 broad-market ledger | FAAB recommendation or Sharp ledger |
| Game Day | CE-20 presentation over stats/ownership | another scoring/projection engine |
| Season Recap | CE-21 presentation over history | generic CMS/media platform |
| Manager tendencies | CE-03 | psychological/personal profiling |
| Portfolio availability | CE-06 | waiver optimizer |
| Start/Sit | CE-12 | duplicate lineup solver |
| Live Draft | CE-13 | duplicate Perfect Draft optimizer |
| League-infused value | canonical value architecture | second competitor-style value system |

---

# 4. Research/view infrastructure requirement

Dynasty Daddy's saved presets are useful. Add a cross-cutting future UX primitive:

**Saved Research Views**

A saved view may store:

- filters;
- column order/visibility;
- sort;
- selected chart metrics;
- display preferences.

Candidate consumers:

- CE-17 League Format Lab;
- Rankings;
- Power Rankings;
- CE-01 Trade Database;
- CE-14 Market Pulse;
- CE-08 Stats Hub.

Saved views must never mutate canonical values/metrics.

---

# 5. Explicitly not added by this audit

Do not add the following merely for Dynasty Daddy parity:

- trivia/Wordle/Connections/lineup mini-games;
- badges/verified-checkmark gamification as a product goal;
- generic creator radio/media feed;
- generic articles/CMS;
- Discord bot;
- native Android app before mobile web quality is excellent;
- Madden fantasy market;
- generic best-ball product vertical;
- competitor-proprietary value algorithms;
- Patreon/subscription/billing parity;
- competitor branding, copy, private APIs or protected implementation details.

---

# 6. Execution/staging

This addendum **does not change the current critical path**.

Current/foundational correctness work continues first. When CE planning/implementation begins, dependencies decide order.

Recommended integration sequence:

1. Preserve and finish canonical identity/value/scoring/history/trade foundations.
2. Complete the pending comprehensive competitive reconciliation for OTC/PFK + Dynasty Daddy.
3. Merge the enrichments above into the owner feature inventory / dependency graph.
4. Build reusable foundations before pages.
5. Implement CE items only when their prerequisites are trustworthy.
6. Keep all competitor-derived signals/surfaces separate from canonical truth unless their methodology explicitly earns a bounded role.

**Do not begin CE-17 through CE-21 during B2.**

---

# 7. Updated competitive thesis

> **OTC execution + Play For Keeps market/manager scouting + Dynasty Daddy league-format/workflow/history utility + our deeper canonical roster-aware decision engine.**

This is the planning target. Feature parity is not the target; coherent decision intelligence is.
