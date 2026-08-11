# Dynasty Daddy Competitive Feature Audit

**Audit date:** 2026-08-11  
**Competitor:** Dynasty Daddy  
**Status:** OWNER-REQUESTED COMPETITIVE RESEARCH — authoritative input to future product planning, **not** authorization to interrupt current foundational/B2 work.

## 1. Purpose and research standard

The owner requested the same kind of detailed competitive review previously performed for OTC Fantasy and Play For Keeps: identify publicly/officially documented Dynasty Daddy capabilities, determine which are useful for Risk It To Get The Brisket, reconcile them against capabilities already approved in `docs/OWNER_FEATURE_INVENTORY.md`, and record worthwhile additions without cloning competitor implementation.

This audit uses public Dynasty Daddy pages and Dynasty Daddy's own public feature announcements / Patreon feature feed. Login-only or member-only implementation details are **not** guessed. Where only a feature title is publicly documented, this audit records the existence of the feature but does not invent its internal methodology.

### Public/official sources reviewed

- Dynasty Daddy current home/tool directory (Power Rankings, Trade Calculator, Playoff Calculator, Player Rankings, Mock Drafts, Trade Finder, Bulk Trades, League Format, Trade Database, Standings, Fantasy Portfolio, Player Comparison, Fantasy Wrapped, ADP Daddy).
- Dynasty Daddy current Waiver Wire page.
- Dynasty Daddy current Trade Database page.
- Current Dynasty Daddy player-detail / fantasy-ranking pages.
- Dynasty Daddy help page for League Infused Values.
- Dynasty Daddy's official Season 4 feature summary.
- Dynasty Daddy's official feature-feed / Patreon sitemap through 2026-08-10.
- Official Dynasty Daddy posts describing League Format / Utilization, Captured WAR, Start/Sit, schedule-aware flex optimization, Manage Waivers, Live Sync Drafts, Fantasy Redzone, Fantasy Wrapped, League Legacy, portfolio exposure charts and related feature updates.

This is intended to be exhaustive for **publicly discoverable and officially documented functionality**. It is not a claim to know undocumented authenticated-only behavior.

---

## 2. Executive conclusion

Dynasty Daddy is strongest in a slightly different area than OTC Fantasy or Play For Keeps. The most valuable lessons are not another trade calculator or another set of rankings. They are:

1. **league-scoring-specific research** — the League Format / utilization / WAR style dashboard;
2. **transaction lineage** — Trade Trees and all-time trade history;
3. **broad waiver-market evidence** — real claims, winning FAAB and ranges;
4. **lineup workflow** — projection-based start/sit with schedule-aware flex handling, weather and waiver alternatives;
5. **multi-league portfolio utility** — stacks, NFL-team exposure and cross-league player availability;
6. **direct league actions** — waivers, trade block and other writeback through a unified action boundary;
7. **historical league/team storytelling** — all-time records / legacy and season recap;
8. **game-day aggregation** — one live dashboard across leagues;
9. **richer player research** — multi-season stats, roster/start rates through time, market history and creator/sharp holdings.

Most of these should **extend capabilities already approved** in §12 of `OWNER_FEATURE_INVENTORY.md`. Only a small number justify new canonical product entries.

The recommended product principle remains:

> **Do not copy Dynasty Daddy. Reuse our deeper canonical identity, value, roster, trade, history, market and intelligence systems to deliver the same class of useful workflow where it fits — then exceed it with provenance, confidence, roster-awareness and cross-signal decision intelligence.**

---

# 3. Full public feature inventory and disposition

## 3.1 Power Rankings

### Dynasty Daddy capability

Public materials describe overall and starter-value Power Rankings, team tiers, roster-construction views, chart sorting and newer Power Rankings charts.

### Our mapping

- Existing inventory item **6.2 Power Rankings** already exists but is duplicated and must be consolidated.
- Canonical **Team Strength** remains a separate product and may be one input; it must not be collapsed into Power Rankings.

### Recommendation

**COVERED / EXTEND EXISTING.**

Worth borrowing as UX requirements after consolidation:

- roster-slot composition visualizations;
- positional-value composition charts;
- sortable historical/team comparison charts;
- saved research views/presets after the underlying metric owner is stable.

Do **not** create another power-ranking engine.

---

## 3.2 Trade Calculator

### Dynasty Daddy capability

League-synced rosters, multiple fantasy markets, league-specific values and trade comparison workflows.

### Our mapping

Existing Trade Calculator + canonical value + KTC advisory parity + future Trade Desk already cover the product class.

### Recommendation

**COVERED.**

One worthwhile extension from Dynasty Daddy's historical feature feed is a **post-trade league-impact view**: after a proposed trade, optionally show how Team Strength, Power Ranking / playoff probability and positional weakness change if those downstream models are defensible. This belongs in roster-aware trade simulation / CE-05 Trade Desk, not a second simulator.

---

## 3.3 Playoff Calculator / season simulation

### Dynasty Daddy capability

Publicly advertises 10,000-season simulation using schedule, historical Elo and starting lineup to estimate matchup/season probabilities.

### Our mapping

Existing **6.1 Playoff Odds** is duplicated and scheduled for consolidation.

### Recommendation

**COVERED / METHOD RESEARCH ONLY.**

After our one canonical playoff engine exists, evaluate defensible inputs such as schedule strength and lineup strength. Do not adopt competitor methodology merely because it exists.

---

## 3.4 Player Rankings / market values

### Dynasty Daddy capability

Daily rankings and trade values, multiple fantasy-market comparisons, trend data, pick equivalents and ADP-derived values.

### Our mapping

Our canonical rankings/value pipeline is deeper and already under foundational repair. KTC stays the owner-requested offensive baseline source and our canonical model is separate.

### Recommendation

**COVERED. DO NOT CREATE A SECOND VALUE ENGINE.**

Dynasty Daddy's presentation reinforces requirements for the Universal Player Profile: current value, rank, position rank, pick-equivalent band, trends, source/market comparisons and historical values.

---

## 3.5 League Infused Values

### Dynasty Daddy capability

Public help documentation describes trade values adjusted to league roster construction and scoring.

### Our mapping

League-adjusted canonical player values already belong to our value architecture and league-config system.

### Recommendation

**COVERED / TRANSPARENCY BENCHMARK.**

Do not build a parallel "league infused" value engine. Improve explanation of **why** our league-adjusted value differs from the raw market and expose league-setting provenance/confidence.

---

## 3.6 Trade Finder

### Dynasty Daddy capability

Generates plausible/fair trades from real rosters; its feature feed records continuing Trade Finder upgrades.

### Our mapping

**2.3 Trade Finder** + Trade Suggestions + Package Builder + Golden Upgrades.

### Recommendation

**COVERED / OUR PLAN SHOULD BE STRONGER.**

Our differentiator should be roster-aware marginal impact, Team Strength/Weakness, stable pick identity, manager fit, real comps and independent market/model disagreement — not just equal-value package generation.

---

## 3.7 Bulk Trades

### Dynasty Daddy capability

Public home copy says users can queue many Sleeper offers using up to four assets and patterns such as pick round, equal-value player or FAAB. The 2026 feature feed includes a bulk-trade generator, FAAB support and multi-asset/player-for-player deals.

### Our mapping

- CE-15 Portfolio Trade Campaign.
- CE-11 Sleeper Action Gateway.
- canonical Package Builder / Trade Finder.

### Recommendation

**EXTEND EXISTING CE-15 / CE-11.**

Useful ideas:

- pattern-based candidate generation;
- player-for-player / multi-asset / pick-round / FAAB constraints;
- review queue before send;
- explicit per-league cooldown and duplicate protection.

Binding safety difference: **no default mass spam and no silent AI sends.** Human review remains required.

---

## 3.8 Trade Database / real trade market

### Dynasty Daddy capability

The current public Trade Database says it searches more than four million trades from more than two million real leagues and refreshes every three hours. Dynasty Daddy also publishes individual picks in trade history and has expanded trade-history views.

### Our mapping

CE-01 Market Trade Ledger / Trade Database.

### Recommendation

**COVERED / HIGH PRIORITY.**

Dynasty Daddy validates CE-01's value. Ours should add contemporaneous value provenance, stable pick identity, league-format filters, package comps, outcome tracking and separation between broad-market behavior and Sharp behavior.

---

## 3.9 Trade Trees / all-time transaction lineage

### Dynasty Daddy capability

Official feature materials describe Trade Trees as a way to visualize a team's past trades, and the current feature feed advertises viewing every trade from league history.

### Our mapping

No explicit equivalent currently exists. We have prerequisites:

- acquisition/holding-period history;
- stable pick identity;
- public league trade history;
- future market trade ledger.

### Recommendation

**ADD — NEW CANONICAL PRODUCT: CE-18 Trade Trees / Asset Lineage.**

See implementation addendum.

---

## 3.10 League Format Tool / Utilization Tool

### Dynasty Daddy capability

This is one of Dynasty Daddy's best differentiators. Official posts describe a league-scoring-specific analytics dashboard with:

- historical season/week selection;
- custom filters;
- reorderable/searchable columns;
- charts and chart search/highlighting;
- saved presets/views;
- WoRP/WAR/VoRP;
- target share;
- rush share;
- routes and target-per-route style usage;
- air yards / aDOT;
- quality/spike weeks;
- utilization/opportunity metrics;
- a broad range of passing, rushing, receiving and IDP statistics;
- multi-year positional WAR/WoRP distribution views.

### Our mapping

We already approved:

- CE-08 Projections & Stats Hub;
- CE-09 Replacement Value / PAR / WAR;
- canonical scoring correctness;
- league settings;
- Universal Player Profile.

But we do **not** currently have one explicit user-facing research surface answering:

> "What does this league's exact scoring/roster format make scarce, valuable, startable and productive?"

### Recommendation

**ADD — NEW SURFACE: CE-17 League Format / Utilization Lab.**

It must consume CE-08/CE-09 and canonical scoring/settings rather than reimplement stats or WAR.

---

## 3.11 Captured WAR / startability-adjusted production

### Dynasty Daddy capability

Dynasty Daddy's public Captured WAR description says it changes the replacement/startability lens by incorporating historical start percentages, trying to distinguish production that managers actually captured in lineups from points scored on benches.

### Our mapping

CE-09 already covers league-specific PAR/WAR/replacement value.

### Recommendation

**EXTEND CE-09 — EVIDENCE-GATED RESEARCH VARIANT, NOT A NEW CANONICAL VALUE.**

Research our own **startability-adjusted realized contribution** metric using lineup/start history and realized scoring. Do not copy Dynasty Daddy's formula. It should answer a useful question separate from dynasty market value:

- Did the player create points above replacement?
- Was the production predictably/startably available to the manager?
- How much value did the roster actually capture?

Require validation before surfacing it as WAR.

---

## 3.12 Start/Sit

### Dynasty Daddy capability

Official posts describe:

- pulling real league scoring settings;
- top projection inputs;
- optimal lineups;
- projection-accuracy tracking;
- an "aggressive" mode;
- waiver-wire players included as alternatives;
- weather/dome/rain context;
- schedule-aware lineup assignment that protects later FLEX flexibility by placing earlier-game players into position-exclusive slots where appropriate.

### Our mapping

CE-12 Lineup Intelligence already exists as approved scope, with `src/ros/lineup.py` as a foundation.

### Recommendation

**STRONGLY EXTEND CE-12.**

Add requirements:

1. max-projection lineup as the canonical baseline;
2. schedule-aware FLEX slot optimization as a second assignment constraint that must not override materially better projections;
3. waiver/free-agent alternatives when an available player materially improves the starting lineup;
4. weather/game-status context;
5. projection-source provenance and projection-accuracy scorecard;
6. optional ceiling/aggressive mode only if a defensible ceiling model exists;
7. later lineup writeback only through CE-11 Action Gateway.

---

## 3.13 Waiver Wire market tracker

### Dynasty Daddy capability

The current Waiver Wire page tracks winning bids from the past week across more than two million leagues, with format filters, claim counts, estimated FAAB, ranges and charts.

### Our mapping

Our existing FAAB engine is a recommendation model. Sharp ledger is a different population. Perfect Waivers will be an optimizer. None is a canonical **broad-market waiver-price ledger**.

### Recommendation

**ADD — NEW FOUNDATION/SURFACE: CE-19 Waiver Market / FAAB Market Ledger.**

This must remain separate from the canonical FAAB recommendation engine. Broad-market winning bids are evidence/context, not the answer to "what should I bid in this league?"

---

## 3.14 Manage Waivers / writeback

### Dynasty Daddy capability

Official 2026 post says users can create claims, choose a drop, choose a bid, and modify/withdraw pending waivers directly from Dynasty Daddy.

### Our mapping

- Perfect Waivers;
- FAAB recommendation engine;
- CE-11 Sleeper Action Gateway.

### Recommendation

**EXTEND CE-11.**

The action gateway should eventually support previewed, authenticated, auditable waiver create/update/withdraw operations after Perfect Waivers produces the recommendation. Recommendation plane and mutation plane remain separate.

---

## 3.15 Fantasy Mock Drafts / Live Sync Drafts

### Dynasty Daddy capability

Current/public materials describe mock drafting, league draft-board import, tiering/filtering, and 2026 live sync that tracks selected players from Sleeper mocks or an active connected draft and updates best available.

### Our mapping

- existing Perfect Draft optimizer;
- CE-13 Draft Room;
- CE-07 Market ADP.

### Recommendation

**STRONGLY EXTEND CE-13.**

The Draft Room should include:

- active Sleeper draft sync;
- live picked/available state;
- tier board;
- our Personal Rankings Overlay;
- Market ADP;
- player profiles;
- Team Weakness;
- Perfect Draft recommendation;
- pick-trade analysis and real trade comps.

Perfect Draft remains the optimizer; live sync is a workspace layer around it.

---

## 3.16 Fantasy Portfolio

### Dynasty Daddy capability

Public materials describe cross-league player exposure. 2026 updates add positional stacks, NFL-team exposure charts and the ability to see where a player is available in other linked leagues.

### Our mapping

CE-06 Dynasty Portfolio / Exposure.

### Recommendation

**STRONGLY EXTEND CE-06.**

Explicitly require:

- player exposure;
- value-weighted exposure;
- NFL-team exposure;
- position exposure;
- age exposure;
- contender/rebuilder exposure;
- QB/pass-catcher and other stack exposure;
- future-pick exposure;
- cross-league availability / free-agent opportunities;
- sortable linked leagues / preferred ordering;
- drill-through to the specific league/team.

Portfolio is descriptive by default. It should not auto-declare diversification "bad" without user policy.

---

## 3.17 Verified Portfolios / creator holdings

### Dynasty Daddy capability

Current player pages show verified fantasy analysts/creators, number of shares, percentage of portfolio and recent Add/Reduce activity.

### Our mapping

- Sharp Tracker;
- Sharp Roster Percentage;
- manager-level concentration;
- Insider Trading;
- Universal Player Profile.

### Recommendation

**COVERED / EXTEND PRESENTATION.**

On the Universal Player Profile, expose canonical Sharp ownership/activity with manager/network independence and sample size. Do not copy Dynasty Daddy's creator list or treat branding as proof of sharpness; use our verified cohort methodology.

---

## 3.18 Player detail / comparison / multi-season research

### Dynasty Daddy capability

Current player pages publicly expose age, experience, rank, position rank, college, PPG, pick-equivalent value, platform roster/start percentages, 30-day trade-value change, market/trade/points/ADP/profile views, 1M/3M/6M histories, adjacent overall/positional assets and Verified Portfolios. The 2026 feature feed also lists multi-season stats and historical rostered/started percentages.

### Our mapping

Universal Player Profile + CE-08 + CE-07 + CE-01 + Sharp + Podcast + News.

### Recommendation

**STRONGLY EXTEND UNIVERSAL PLAYER PROFILE.**

Competitor-parity floor should include:

- current canonical value/rank/tier/confidence;
- pick-equivalent band;
- 1M/3M/6M/1Y/all-time value history where data exists;
- ADP history;
- realized multi-season stats;
- platform roster/start history;
- adjacent overall + position assets;
- real trade comps;
- Sharp/verified cohort ownership and activity;
- roster context;
- acquisition/holding history;
- podcast/news/BDVM context.

Missing history must remain missing — never reconstructed from current values without provenance.

---

## 3.19 Player Watchlist

### Dynasty Daddy capability

Official feature feed records a Player Watchlist feature.

### Our mapping

Not explicit today, but naturally belongs to:

- CE-04 Dynasty Command Center;
- Universal Player Profile;
- CE-14A Personal Rankings Overlay;
- notifications.

### Recommendation

**ADD AS A REQUIREMENT INSIDE CE-04, NOT A NEW ENGINE.**

A user can Watch/Target a player, optionally set reasons/thresholds, and Command Center can surface material value/ADP/news/Sharp/availability changes. Do not turn watching into noisy alerts; use canonical dedupe/cooldowns.

---

## 3.20 Fantasy Redzone

### Dynasty Daddy capability

Official public announcement describes one dashboard across synced leagues with live play-by-play, filters, "Your Players," matchup tracking and a news/highlight/injury/social feed.

### Our mapping

We have CE-04 Command Center, CE-12 Lineup Intelligence, CE-08 Stats and news infrastructure, but no explicit **live game-day multi-league surface**.

### Recommendation

**ADD AS OPTIONAL/FUTURE: CE-20 Game Day Command Center.**

This is lower priority than core dynasty decision products but worth preserving. Our version should focus on actionable fantasy context rather than social-feed imitation:

- all starting players across linked leagues;
- live fantasy scoring/projection delta;
- all active matchups;
- injuries/status changes;
- game-start/lock status;
- high-impact plays for rostered/target players;
- lineup decision context before lock;
- no separate stats engine.

---

## 3.21 Fantasy Wrapped / season recap

### Dynasty Daddy capability

The 2025 public announcement describes a season recap with global league/team comparisons, percentile-style comparisons, rare roster facts and animated/shareable pages.

### Our mapping

- public league/history surfaces;
- franchise history;
- CE-10 Share Renderer;
- future historical analytics.

### Recommendation

**ADD AS OPTIONAL/FUTURE: CE-21 Dynasty Season Recap / Wrapped.**

This is not a generic League Media/CMS product. It is a generated analytical recap from canonical league history. It can cover:

- best/worst trades;
- biggest value gains/losses;
- best waiver adds;
- draft hits/misses;
- luck/lineup efficiency if defensible;
- championships/playoff run;
- league percentile comparisons only where benchmark population is legitimate;
- shareable cards via CE-10.

No fake songs/personality gimmicks are required.

---

## 3.22 League Legacy / Team Legacy

### Dynasty Daddy capability

Official 2026 League Legacy post describes all-time multi-year league history, legacy leaderboard, longest win streaks, playoff wins and head-to-head records. Its 2026 feature feed also lists a separate Team Legacy page.

### Our mapping

- 6.3 Franchise / ownership history;
- 6.4 Public league pages;
- existing rivalries/records/history work.

### Recommendation

**EXTEND EXISTING 6.3 / 6.4, NO NEW ENGINE.**

Explicit parity/quality requirements:

- all-time head-to-head by franchise identity, not current owner string;
- regular season vs playoffs;
- playoff wins/titles/runner-ups;
- longest streaks;
- season-by-season finish;
- trades/drafts/waivers where history exists;
- owner changes preserve franchise lineage;
- team/franchise legacy page;
- shareable legacy cards through CE-10.

This directly reinforces why franchise identity must not erase historical teams.

---

## 3.23 Standings / league dashboard

### Dynasty Daddy capability

League standings, head-to-head information, transactions and current/all-time views.

### Our mapping

Existing public league surface already has standings, franchises, rivalries and history.

### Recommendation

**COVERED / EXTEND WITH LEGACY REQUIREMENTS ABOVE.**

---

## 3.24 Manager Tendencies

### Dynasty Daddy capability

Dynasty Daddy's official feature feed on 2026-08-10 lists a "Revamped Team Pages w/ Manager Tendencies" feature. Public indexed detail was not available at audit time, so this audit does not assert its methodology.

### Our mapping

CE-03 Manager Scout / Manager Intelligence already exists and is intended to analyze fantasy behavior only.

### Recommendation

**STRONG CONFIRMATION OF CE-03.**

Manager tendencies should eventually appear directly on team/trade surfaces, but use our own defensible behavior features, sample sizes and confidence. No psychological or real-world profiling.

---

## 3.25 Trade Block / nickname / platform writeback

### Dynasty Daddy capability

Official feature materials document Sleeper trade-block integration and other writeback/integration features; the public Patreon page describes a player-level trade-block modal.

### Our mapping

CE-11 Sleeper Action Gateway + CE-05 Trade Desk + manager/team surfaces.

### Recommendation

**EXTEND CE-11.**

Potential supported actions after auth/security work:

- set/remove trade block;
- send/respond to trade;
- waiver create/update/withdraw;
- lineup writeback;
- supported nickname/team metadata writeback where useful.

Every mutation requires auth, authorization, preview, idempotency/audit and visible errors. Recommendation never implies permission to execute.

---

## 3.26 Share Team

### Dynasty Daddy capability

Official 2026 feature feed lists "Share your Fantasy Team."

### Our mapping

CE-10 Share Renderer / Team Cards already approved.

### Recommendation

**COVERED / CONFIRMS CE-10.**

Support normal and anonymous team-share modes with stable links/cards; never leak league/private information in anonymous mode.

---

## 3.27 Custom presets / saved research views

### Dynasty Daddy capability

Official posts document saved custom presets for Power Rankings and League Format dashboards.

### Our mapping

No explicit cross-product saved-view capability.

### Recommendation

**ADD AS A CROSS-CUTTING UX REQUIREMENT, NOT A NEW PRODUCT.**

After tables/charts stabilize, allow owner/user to save named filter/column/chart presets for research-heavy surfaces such as CE-17, Rankings, Power Rankings, Trade Database and Market Pulse.

---

## 3.28 Custom rankings import

### Dynasty Daddy capability

Official feature feed documents a custom rankings import beta.

### Our mapping

CE-14A Personal Rankings Overlay is the better canonical product.

### Recommendation

**EXTEND CE-14A.**

Support manual reorder plus optional CSV/import mapping into a **private personal rank layer**. It must never mutate canonical site values/ranks.

---

## 3.29 Manual leagues / broad platform support

### Dynasty Daddy capability

Public materials show support for Sleeper, ESPN, Yahoo, MFL, Fleaflicker, Fantrax and FFPC, plus manual league creation.

### Our mapping

Current product is Sleeper-centric; future CE architecture is intended to remain multi-league capable.

### Recommendation

**ARCHITECTURAL COMPATIBILITY, NOT CURRENT BUILD PRIORITY.**

Do not rewrite the current app into a universal fantasy host during foundational phases. New canonical identities/interfaces should avoid unnecessary Sleeper-only assumptions where practical.

---

## 3.30 Fantasy Cheat Sheet

### Dynasty Daddy capability

Club materials list a fantasy cheat-sheet tool.

### Our mapping

Rankings + Personal Rankings + Watchlist + player profile + ADP can provide a stronger customizable research sheet.

### Recommendation

**NO NEW ENGINE.** Consider a compact saved/exportable ranking view after CE-14A/CE-17.

---

# 4. Features explicitly NOT recommended for our current product scope

These are real Dynasty Daddy capabilities or experiments, but they do not improve the core dynasty decision-intelligence thesis enough to justify product scope now:

- daily trivia / Wordle / Connections / lineup mini-games;
- badges, profile gamification and verified-checkmark cosmetics as a product goal;
- Dynasty Daddy Radio / generic media feed;
- generic article CMS;
- generic Discord bot;
- native Android app before the mobile web app is excellent;
- Madden fantasy-market values;
- a broad best-ball product vertical (best-ball ADP may remain an optional market input only);
- duplicating Dynasty Daddy's proprietary value algorithms;
- copying creator lists, branding, copy, protected APIs or private implementation details;
- monetization/subscription features merely because the competitor has a Club tier.

---

# 5. Net-new approved competitive additions from this audit

These are the features that add enough product value to be preserved as future scope beyond the existing OTC/PFK inventory:

| ID | Feature | Classification | Why it earns a separate entry |
|---|---|---|---|
| **CE-17** | **League Format / Utilization Lab** | KEEP — NEW SURFACE | Distinct league-scoring research workspace over stats, utilization and replacement-value primitives; not currently represented as one product. |
| **CE-18** | **Trade Trees / Asset Lineage** | KEEP — NEW BUILD | Distinct transaction/acquisition lineage visualization with strong value for dynasty history and trade evaluation. |
| **CE-19** | **Waiver Market / FAAB Market Ledger** | KEEP — NEW BUILD | Broad-market waiver pricing is a separate evidence population from our recommendation model and Sharp ledger. |
| **CE-20** | **Game Day Command Center** | KEEP — OPTIONAL / FUTURE | Useful multi-league live surface, but lower priority than dynasty decision foundations. |
| **CE-21** | **Dynasty Season Recap / Wrapped** | KEEP — OPTIONAL / FUTURE | Useful shareable analytical recap built from canonical history; not a generic media/CMS product. |

Detailed dependency/ownership rules are recorded in `COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md`.

---

# 6. Existing approved items strengthened by Dynasty Daddy

The audit also adds binding future requirements to existing approved scope:

- **CE-03 Manager Scout:** manager tendencies on team/trade surfaces; fantasy behavior only, sample/confidence-aware.
- **CE-04 Command Center:** add Watchlist/Target list and threshold-aware opportunity monitoring.
- **CE-05 Trade Desk / 1.3 trade simulation:** optional post-trade league impact (Team Strength / weaknesses / Power Ranking / playoff odds when defensible).
- **CE-06 Dynasty Portfolio:** stacks, NFL-team exposure, cross-league availability, league ordering.
- **CE-08 Projections & Stats:** multi-season stats, platform roster/start histories, projection-accuracy scorecard.
- **CE-09 PAR/WAR:** research a startability-adjusted realized-contribution variant; evidence-gated and separate from dynasty value.
- **CE-10 Share Renderer:** shareable/anonymous team and later legacy/recap cards.
- **CE-11 Action Gateway:** waiver create/update/withdraw, trade block, and supported platform writeback after security/auth readiness.
- **CE-12 Lineup Intelligence:** schedule-aware FLEX optimization, weather/status, waiver alternatives, projection provenance/accuracy, defensible ceiling mode.
- **CE-13 Draft Room:** live draft sync, best-available tracking and tier board around Perfect Draft.
- **CE-14A Personal Rankings:** custom ranking import into a private overlay.
- **CE-15 Portfolio Trade Campaign:** pattern-based multi-asset/pick/FAAB package generation, still human-reviewed/no-spam.
- **6.3 / 6.4 History/Public League:** explicit League Legacy + Team Legacy requirements.
- **6.6 Universal Player Profile:** multi-season stats, roster/start history, pick equivalents, adjacent assets, time-series market views and Sharp holdings/activity.

---

# 7. Duplicate-risk map

The following separations are binding:

1. **CE-17 League Format Lab != CE-08 stats engine != CE-09 WAR engine.** CE-17 is a surface/query layer consuming the canonical underlying metrics.
2. **CE-18 Trade Trees != CE-01 broad market trade ledger.** CE-18 is league/team asset lineage; CE-01 is market-wide comparable trade evidence. They may share canonical transaction schemas where sensible.
3. **CE-19 broad Waiver Market != canonical FAAB recommendation != Sharp event ledger.** Market observation, recommendation and elite-manager behavior are different populations.
4. **CE-20 Game Day != CE-04 Dynasty Command Center.** CE-04 is action/decision priority; CE-20 is live scoring/game-day situational awareness. Shared events, separate presentation.
5. **CE-21 Recap != League Media/CMS.** It is generated analytics over canonical history and remains compatible with the owner's decision to remove generic League Media from this engagement.
6. **League Infused competitor values != our canonical league-adjusted value.** No second value engine.
7. **Captured-WAR-like analysis != canonical dynasty value.** It is realized/startability performance research only.

---

# 8. Priority relative to the existing CE roadmap

Foundational dependency order still wins. Dynasty Daddy findings do not interrupt Phase B/C correctness work.

Recommended placement once dependencies are ready:

### High-value additions to existing work

- CE-12 lineup enhancements should ship with Lineup Intelligence rather than later bolt-ons.
- CE-13 live sync should ship with Draft Room.
- CE-06 portfolio exposure/availability should ship with Portfolio.
- CE-03 manager-tendency presentation should ship with Manager Scout.
- CE-11 waiver/trade-block actions should ship only after the Action Gateway is secure.

### New capability priority

**Tier 2-ish after data foundations:** CE-17 League Format / Utilization Lab, CE-19 Waiver Market.  
**Tier 2/3 after history/identity:** CE-18 Trade Trees / Asset Lineage.  
**Tier 5 optional:** CE-20 Game Day Command Center, CE-21 Dynasty Season Recap.

Dependencies override these labels.

---

# 9. Competitive product thesis after Dynasty Daddy

The updated product thesis is:

> **OTC execution + Play For Keeps market/manager scouting + Dynasty Daddy league-format/workflow/history utility + our deeper canonical roster-aware decision engine.**

The goal is not feature-count parity. The goal is to identify the best user jobs competitors solve, then solve those jobs on top of one coherent truth architecture.
