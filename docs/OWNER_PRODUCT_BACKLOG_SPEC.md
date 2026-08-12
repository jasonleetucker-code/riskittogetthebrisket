# Risk It To Get The Brisket — Owner Product Backlog Specification

**Status:** AUTHORITATIVE PRODUCT-SPEC COMPANION TO `docs/OWNER_FEATURE_INVENTORY.md`  
**Owner direction captured through:** 2026-08-12  
**Purpose:** Preserve not merely *what* the owner wants built, but *what the feature is supposed to mean*, its methodology, canonical dependencies, public/private posture, non-scope, missing-data behavior, validation requirements, and already-resolved owner decisions.

> `OWNER_FEATURE_INVENTORY.md` remains the scope/status inventory. This document is the detailed implementation intent. A one-line inventory entry must never be treated as permission to invent methodology that is specified here.

---

## 0. HOW CLAUDE MUST USE THIS DOCUMENT

Before implementing any material product/backlog item, Claude must read the relevant section here plus the current canonical architecture/audit documents and inspect the live repository.

For every material feature, preserve these fields:

1. **Goal / user question** — what problem the feature answers.
2. **Status / phase** — approved now, future, evidence-gated, removed, etc.
3. **Public/private posture** — public, private, or public-safe/private-intelligence split.
4. **Canonical owners/dependencies** — existing systems that must be consumed rather than reimplemented.
5. **Methodology** — formulas/logic already decided.
6. **Data/provenance** — authoritative inputs and timestamps.
7. **Missing-data behavior** — missing is never zero.
8. **Independence/deduplication** — avoid pseudo-consensus/double counting.
9. **UX behavior** — decisions already made by owner.
10. **Edge cases** — multi-team trades, reacquisition, historical identity, etc.
11. **Non-scope** — what must not be silently added.
12. **Validation** — RED→GREEN for defects; pinned-input evaluation for models; historical replay where relevant.
13. **Method status** — FINAL/OWNER-DECIDED, INVESTIGATION REQUIRED, or FUTURE/EVIDENCE-GATED.

### Global invariants

- **ONE CONCEPT, ONE CANONICAL OWNER.** Pages consume canonical systems; pages do not independently recalculate them.
- **MISSING IS NEVER ZERO.** No source, no projection, no FAAB history, no trade comp, no analyst coverage, no pick forecast, etc. must remain explicitly unavailable/insufficient rather than becoming `0`.
- **Signal independence matters.** Do not count the same underlying observations multiple times through different surfaces.
- **Champion ≠ challenger.** Model evaluation never authorizes production promotion by itself.
- **Pinned inputs for experiments.** Record code SHA, source hashes, snapshot hash, model version and timestamp.
- **Explain important conclusions.** Recommendations should expose the material reasons rather than magic scores.
- **Progressive disclosure.** Rich information should not become visual chaos.
- **Recommendations and execution are separate.** No AI-generated league action may silently execute.

---

# 1. CANONICAL TRADE DECISION SYSTEM

## 1.1 Trade Calculator / multi-team reliability

**Goal:** Correctly model proposed 2-team and 3+ team trades using canonical asset values and routing.

**Owner decisions:** Multi-team trades are required and must never be simplified away. Regression coverage must include normal two-team trades; 3+ team player-only trades; 3+ team pick trades; explicit pick destinations; fallback destinations; and routing semantics. Preserve the historical `/trade` `defaultDestination` failure as a regression scenario.

**Canonical dependencies:** player identity, pick identity, canonical value, league settings, package methodology, trade routing.

**Method status:** OWNER-DECIDED PRODUCT REQUIREMENT.

## 1.2 KTC Value Adjustment vs canonical trade methodology

Exact KTC-style Value Adjustment remains available as an **ADVISORY / KTC PARITY METRIC** answering roughly: “What would KTC’s consolidation methodology say?”

It is **not** the site's canonical trade conclusion.

Canonical trade analysis may use canonical raw value, roster marginal impact, Team Strength/Weakness, replacement level, lineup effects, positional scarcity, competitive window, pick forecast, market comps, Sharp/Analyst/manager context and simulation — but must guard against correlation/double counting.

Do not invent a proprietary scalar package adjustment merely to have one. Any proprietary challenger requires a defined target, evidence, benchmark against exact KTC parity and contemporaneous market behavior, and owner approval.

**Method status:** KTC PARITY FINAL; PROPRIETARY PACKAGE PREMIUM EVIDENCE-GATED.

## 1.3 Analyze Trade

**Goal:** Add assets → press **ANALYZE TRADE** → receive an explainable final decision layer.

Potential result states: **MAKE THE TRADE**, **DECLINE**, or a clearly defined close/uncertain state when evidence is genuinely mixed.

Inputs may include canonical values, package economics, KTC advisory adjustment, Team Strength/Weakness impact, roster fit, Monte Carlo, future-pick effects, second opinions, market comps, Sharp context, Analyst Consensus, and manager context when available.

**Critical rule:** This is not a naïve average of unrelated scores. Define correlation groups and avoid counting one underlying market/source multiple times.

Explain the conclusion in concrete terms, e.g. package-adjusted equity, Team Strength delta, weakness fixed/created, comparable-trade evidence, pick effects and confidence.

**Private only:** This is front-office intelligence.

## 1.4 Second Opinions

Keep detailed provider/source results but add a compact summary such as **Side A wins 6–2**. This supplements rather than replaces source detail. Missing providers are unavailable, not losses/ties.

## 1.5 Monte Carlo audit

Before changing the simulation, define the exact probabilistic quantity it is intended to estimate. Audit current inputs and whether it simply favors raw-value/point totals. Determine whether package adjustment, roster context or new scoring/value architecture belong in the simulation *only if they are part of the quantity being simulated*. Do not inject every trade signal and create a circular vote.

**Method status:** INVESTIGATION REQUIRED — DO NOT INVENT A FORMULA.

## 1.6 NFL-team exposure in Simulate Impact

Show value-weighted NFL franchise exposure **Before → After**, e.g. `MIN 18.2% → 22.4%`. It is informational, not an automatic trade penalty.

Owner overlay: Minnesota Vikings are effectively untouchable for the owner's roster; do not recommend trading Vikings merely for diversification. Intentional starting-QB + primary-backup handcuffs are purposeful exposure and should not be flagged as accidental concentration.

## 1.7 Manual value overrides

Manual player-value edits in Trade Calculator are session/analysis conveniences only and must never mutate canonical database values.

Presentation must be visually indistinguishable from ordinary values: no yellow highlight or obvious “edited” marker during trade presentation.

Provide an easy **Reset Values** control. If an overridden asset is removed and later re-added, it should return to canonical/default value unless explicit future product evidence supports another behavior.

## 1.8 Acquisition History / holding-period returns / cost basis

Track each holding period separately, including reacquisition.

For every acquisition preserve where possible:
- player/pick identity;
- acquisition method (trade, rookie draft, waiver/FA, etc.);
- acquisition date;
- canonical site value at acquisition;
- relevant historical KTC/external market value at acquisition;
- package cost / allocation methodology for multi-asset trades;
- provenance state: RECORDED / HISTORICAL SNAPSHOT / RECONSTRUCTED / UNAVAILABLE;
- current canonical/market value;
- absolute and percentage gain/loss.

Never use a future snapshot as historical truth.

**Analyze Trade addendum:** Every outgoing player should have a compact **Your Cost Basis** line/section showing acquisition value, current value, gain/loss, percentage return, date/method and historical market context where available.

Cost basis is **informational**. Do not penalize a rational sale merely because the manager is below acquisition cost; avoid sunk-cost logic.

---

# 2. SHARED PACKAGE / TRADE GENERATION

## 2.1 Golden Upgrades

**KEEP as a distinct user-facing surface**, but never a second valuation/package/trade engine. It consumes canonical values, ownership, package generation, package adjustment, roster-impact simulation, Team Strength/Weakness, market data and confidence.

## 2.2 Package Builder

**KEEP — NEW BUILD.** Must use the same canonical package-generation engine as Trade Finder, Trade Suggestions and Golden Upgrades.

Return-position filters/constraints are applied *during generation*, not as a post-filter. Support QB/RB/WR/TE/DL-EDGE/LB/DB/PICKS and intentional multi-selection. Respect ownership, selected team, untouchables/exclusions, unpriced state, pick identity, league settings and roster impact.

---

# 3. PICK IDENTITY & PICK FORECAST (CE-02)

Future draft picks are first-class assets with stable season + round + original owner + current owner identity.

Separate:
- **generic pick market value**, and
- **specific expected pick value**.

## Pick Forecast / Pick Projector

**Approved roadmap feature; private decision intelligence.** The existing/simple public projector must not be mistaken for the final CE-02 design.

For a specific future pick, produce a calibrated probability distribution, e.g.:
- 1.01–1.04: 34%
- 1.05–1.08: 48%
- 1.09–1.12: 18%
- expected slot: 1.06
- confidence + material drivers.

Inputs should use defensible team-strength/outcome information without leaking future results or assuming an unknown pick is late. Historical calibration/backtesting is required.

Public `/league` may show **factual pick ownership** only. Pick probabilities, expected canonical value, internal valuation, effective auction power and trade simulator intelligence are private.

**Method status:** PRODUCT APPROVED; FORECAST MODEL REQUIRES EMPIRICAL VALIDATION.

---

# 4. ANALYST INTELLIGENCE — PODCAST + YOUTUBE

Build one canonical **Analyst Intelligence** subsystem over podcast and YouTube transcripts.

## Extraction taxonomy

Extract only actionable dynasty opinions:
- STRONG BUY
- BUY
- CONDITIONAL BUY
- HOLD / CONTEXTUAL
- CONDITIONAL SELL
- SELL
- STRONG SELL
- NO SIGNAL

**NO SIGNAL should be common.** Ordinary discussion or praise is not a Buy.

Preserve:
- player identity;
- analyst identity;
- show/channel/network;
- episode/video;
- timestamp/date;
- exact provenance;
- extraction confidence;
- price context;
- exact pick/player cost when explicitly stated;
- reasoning/context;
- whether opinion is conditional.

## Deduplication / independence

Podcast + YouTube are not two automatic votes. Collapse duplicated uploads, syndicated feeds, network reposts, aliases and repeated underlying opinions so one take cannot create false consensus.

Exclude YouTube material already represented by the podcast ingestion pipeline.

## Seven-day Analyst Consensus

For each player aggregate a trailing seven-day consensus into:

**Direction score:** `-1.00` maximum Sell → `0.00` neutral → `+1.00` maximum Buy.

**Separate sample/confidence state:**
- INSUFFICIENT SAMPLE
- EARLY SIGNAL
- MODERATE CONSENSUS
- STRONG CONSENSUS

A single emphatic take may have extreme direction but low sample confidence. Direction and confidence must never be collapsed into one number.

Raw mention count may be displayed as **attention**, but must not drive Buy/Sell direction.

Do not activate analyst-specific reliability weights until enough historical validation exists.

Store historical consensus snapshots for 30/60/90/180/365-day backtesting and later evaluate whether analysts lead market movement, which call types are predictive, and whether reliability differs by analyst/position/player type.

## Downstream use

Analyst Intelligence contributes **once**, modestly and boundedly, to Consensus Edge. It also powers Podcast/YouTube Buy-Sell surfaces, Universal Player Profiles, selected-team intelligence, Command Center and related intelligence UI.

Missing transcript/source coverage = unavailable/insufficient coverage, never neutral or negative sentiment.

**Method status:** PRODUCT/TAXONOMY/BOUNDED-SIGNAL ARCHITECTURE APPROVED; EXACT PRODUCTION SCORE CALIBRATION REQUIRES VALIDATION.

---

# 5. CONSENSUS EDGE / BUY-SELL

Consensus Edge is the explainable synthesis layer, not permission to double-count every available number.

For every candidate component ask:
- What observations generated it?
- Does another component contain the same observations?
- Which correlation group owns it?
- sample size?
- freshness?
- coverage?
- missing behavior?

Distinct conceptual populations include broad Market Trade Ledger, curated Sharp Ledger, Insider/league-manager behavior, Analyst Intelligence, KTC retail/crowd signal, BDVM fundamentals and the canonical model conclusion.

Homepage ticker owner rule:
- **BUY:** may include relevant players generally.
- **SELL:** only players currently rostered by the selected user's/team's roster.

---

# 6. MARKET TRADE LEDGER / REAL TRADE MARKET VALUE (CE-01)

Build a normalized broad-market database of real completed dynasty trades, separate from the curated Sharp ledger.

Use it for historical comps, player/pick trade history, Most Traded, Market Pulse, acquisition pricing and eventually an independent Real Trade Market Value signal.

Do **not** infer market value by simply averaging “assets received.” Future valuation candidates may include pairwise preference models, latent-value graphs, robust regression, Bayesian estimation, package-adjusted inference, recency weighting and format normalization.

Any Real Trade Market Value model must be backtested, confidence/sample aware, source-independent where possible and documented. The Trade Database does not need to wait for the valuation model.

---

# 7. MANAGER SCOUT / INSIDER (CE-03)

Analyze fantasy behavior only — never real-world personal profiling.

Potential dimensions: trade frequency, future-pick activity, consolidation behavior, youth/veteran preference, positional preference, package sizes, cross-league ownership and recent buy/sell behavior.

Keep broad Market, Sharp behavior and specific league-manager/Insider behavior separate.

**Private only.** Do not publish opponent-facing Buyer/Seller recommendations or negotiation tendencies on `/league`.

---

# 8. UNIVERSAL PLAYER PROFILE

Every player click should ultimately route to one canonical profile.

Private/authenticated profile sections may include:
- Identity: player, NFL team, position, age/status.
- Canonical valuation: value, overall/position rank, tier, confidence.
- Market: KTC, Real Trade Market, ADP, trends, comps.
- Fundamentals: BDVM, projections, stats, PAR.
- Roster context: league owner, selected-team ownership, Team Strength/Weakness impact.
- Acquisition: method/date/value/current value/return/holding periods.
- Sharp: roster percentage, transactions, concentration.
- Insider: relevant league-manager activity.
- Analysts: structured podcast/YouTube takes + consensus.
- News: canonical fantasy-news feed.

Factual news and analyst opinion must remain distinguishable.

### Public-safe player profile

Public pages may show identity, league ownership journey, production for franchises, draft origin, memorable performances and public-safe news. Do **not** expose canonical value, market edge, BDVM conclusions, Sharps, Analyst Buy/Sell or roster-fit intelligence publicly.

---

# 9. PUBLIC LEAGUE EXPERIENCE v3

## Governing product split

> **Public `/league` = League Museum + Sports Network + Game Day.**  
> **Private authenticated app = Front Office + War Room.**

Every existing and future feature must explicitly declare: PUBLIC, PRIVATE, or PUBLIC-SAFE/PRIVATE-INTELLIGENCE SPLIT.

### Canonical public-information classes

1. **FACTUAL — public:** scores, standings, completed trades, factual pick ownership, rosters.
2. **RETROSPECTIVE — public:** records, rivalry history, awards, historical realized production.
3. **BROADCAST-DERIVED — public-safe:** sanitized Power ranking, luck/streaks, matchup stories, public playoff/championship probabilities when methodology does not expose proprietary decision internals.
4. **DECISION INTELLIGENCE — private:** values, edges, Buy/Sell, weaknesses, trade advice, pick forecasts, manager tendencies, internal roster-strength details.

A blocked-field-name list is only a secondary defense. Semantic classification is the canonical boundary.

## Privatize / remove from public intelligence

- detailed ROS Strength and proprietary roster-strength internals;
- Trade Deadline Buyer/Seller/Strong Buyer/Strong Seller recommendations;
- Pick Forecast/Projector probabilities;
- proprietary Draft Capital dollar values/effective-auction-power/trade simulator;
- private Power methodology details;
- other recommendations, values, weaknesses or opponent-facing decision intelligence.

Public replacements may show factual trade activity, deadline countdown, most active trader, completed trades, pick ownership and sanitized sports-media rankings.

## Historical truth gate

Before expanding historical storytelling, establish complete reconstructable league history, retired-franchise treatment, correct “all-time” semantics, season-window labels, unplayed-season award behavior, article freshness and public simulation season correctness. Do not call a truncated window “all-time.”

## Information architecture

Consolidate the current flat public navigation toward six hubs:
1. **Home** — headlines, Game of the Week, standings pulse, champion, rivalry, record chase, recent transactions.
2. **Game Day** — scoreboard, previews, recaps, weekly pages, live public Game Day.
3. **League** — standings, public Power, playoff/championship odds, luck, streaks.
4. **Franchises** — team cards, franchise identities, trophies, NFL DNA.
5. **History** — champions, records, rivalries, Hall of Fame, Player Journeys, archives.
6. **Transactions** — completed trades, draft history, factual pick ownership, transaction timeline.

## Franchise identity / Franchise Passport

Each franchise should feel like a sports franchise page, not a raw stats dump. Include public-safe items such as titles, runner-up finishes, career W/L, points, playoff appearances, current streak, archrival, best/worst seasons, greatest games, franchise records, historical team names, transaction/draft history, trophy case, Ring of Honor, signature players, Player Journeys and NFL DNA.

Do not foreground implementation identifiers such as raw Owner ID/league ID.

## Rivalries

Make rivalries a flagship public feature. Support named rivalries, complete H2H timeline, regular/playoff series, points/margins, closest game, biggest blowout, streaks, highest combined score, championship meetings, next meeting and objective Rivalry MVP where data supports it.

Create shareable **Rivalry Receipts**.

## League storytelling backlog

Approved concepts:
- **Brisket Wrapped** season recap;
- Season Yearbooks;
- League Hall of Fame (managers + players, realized accomplishments only);
- Franchise Ring of Honor;
- Championship Path;
- On This Day in Brisket History;
- This Week in League History;
- Milestone Watch;
- expanded Record Chase;
- Trade Trees;
- Draft Class Reunion;
- objective/fun League Cast labels based on transparent history, not private Manager Scout intelligence;
- Game of the Week;
- postgame win-probability timeline;
- Bad Beat / Miracle Win cards;
- League RedZone-style live feed;
- public Pick'em where humans predict weekly winners and the private model does not reveal its picks.

## Public Draft broadcast

Public-safe draft mode may show live draft board, previous picks, franchise cards, ticker, pick announcements and historical trivia. Do not expose private target recommendations, internal values or Pick Forecast intelligence.

## Share Renderer integration (CE-10)

Create public-safe reusable cards for Franchise Cards, Rivalry Receipts, matchup cards, records, Player Journeys, championship cards, Wrapped moments and bad beats. Private fields must not be available to the public renderer.

## Workstream order

P0 public/private boundary → P1 historical truth → P2 information architecture → P3 Franchise/Rivalry → P4 storytelling → P5 Game Day → P6 sharing.

---

# 10. AWARDS & HONORS v2 — “BRISKET HONORS”

**Approved public feature.** Awards are objective/data-derived; no subjective voting is required.

2026 is the first season in which awards are a live league institution. Owner explicitly approves retroactively calculating **2024 and 2025** awards using the same inaugural Awards Methodology v2 chosen for 2026. These are official retroactive historical awards.

## 10.1 Canonical player-award metric: Realized Lineup VORP

Concept:

`Realized Lineup VORP = Σ over actual fantasy starts (player fantasy points − positional replacement expectation for that starting opportunity)`

Rules:
- only weeks in which the player actually enters the fantasy lineup count toward the award;
- bench production contributes zero award value because it did not affect the fantasy matchup;
- negative VORP remains negative — do not floor at zero;
- award contribution uses starter-only production;
- replacement baseline should come from the broader available player-production pool, not only fantasy-started players, to avoid favorable-start selection bias;
- replacement methodology must be season/scoring/lineup specific and consume the canonical replacement-level owner rather than hard-coded awards-only QB/RB/WR/TE/IDP cutoffs;
- derive/validate effective starter demand using actual league configuration and, where useful, measured season-specific starter utilization across FLEX/SF/IDP-flex positions;
- test reasonable replacement bands/cutoffs for robustness before finalizing methodology.

## 10.2 Flagship player awards

Use regular-season Realized Lineup VORP unless otherwise specified:
- League MVP — offense or defense, highest VORP;
- Offensive Player of the Year;
- Defensive Player of the Year;
- Offensive Rookie of the Year;
- Defensive Rookie of the Year;
- QB of the Year;
- RB of the Year;
- WR of the Year;
- TE of the Year;
- Kicker of the Year if league scoring/data supports it;
- DL/EDGE of the Year;
- LB of the Year;
- DB of the Year.

Position awards should use VORP rather than raw starter points so positional replacement scarcity is treated consistently.

## 10.3 Postseason awards

- **Postseason MVP:** highest playoff-only Realized Lineup VORP across eligible fantasy playoff participants.
- **Championship MVP:** highest championship-week Realized Lineup VORP on the champion's qualifying lineup.

Do not conflate the two.

## 10.4 Team awards

- **Best Offense:** total Realized Lineup VORP from the franchise's offensive QB/RB/WR/TE starts during the regular season.
- **Best Defense:** total Realized Lineup VORP from DL/EDGE/LB/DB starts during the regular season.

Show raw points as supporting context, but VORP determines the winner.

## 10.5 Manager of the Year vs GM/Executive of the Year

These must be meaningfully distinct. The same manager may fairly win both, but they must not be duplicate formulas.

### Manager of the Year — competitive/on-field management

Initial methodology to validate:
- **30% All-Play Performance** — normalized all-play winning percentage / schedule-independent competitive performance;
- **25% Team Realized Lineup VORP** — value actually produced by weekly lineups;
- **20% Final/Playoff Performance** — postseason advancement/final finish without automatically awarding the champion;
- **15% Weekly Performance Consistency** — sustained competitive quality;
- **10% Close-Game / High-Leverage Performance** — objective close/high-impact outcomes with minimum-sample safeguards.

Trade success and waiver acquisition value do **not** enter MOTY.

### GM / Executive of the Year — roster construction

Initial methodology to validate:
- **30% Trade Acquisition Value Added** — post-acquisition realized lineup value attributable to acquired players relative to defensibly allocated acquisition cost;
- **25% Waiver/FA Value Added** — Lineup VORP after waiver/free-agent acquisition, with FAAB efficiency only where reliable history exists;
- **20% Draft Value Added** — rookie-draft realized value relative to draft capital/selection slot with minimum-data rules;
- **15% Net Roster Improvement From Acquisitions** — improvement attributable to manager-controlled roster moves rather than merely inherited players improving;
- **10% Acquisition Efficiency / Depth Creation** — useful starts and above-replacement production created per defensible acquisition opportunity/cost.

**Important:** These percentages are an initial specification, not immutable arbitrary constants. Replay 2024/2025, measure MOTY-vs-GMOTY correlation, inspect component correlation/double counting and test reasonable nearby weights. If the two awards are nearly the same score under different names, refine before inaugural finalization.

Conceptual firewall:
- **Manager of the Year = how well the team performed competitively.**
- **GM of the Year = how much value roster-building decisions created.**

## 10.6 All-Brisket teams

Automatically name **All-Brisket First Team** and **Second Team** using Realized Lineup VORP and the league's actual lineup/position structure. This is the league's objective All-Pro equivalent.

## 10.7 Award races

For flagship awards show top five throughout the season. Include rank, player/franchise, VORP and presentation-only race context such as weekly movement, gap to leader and recent VORP trend where data supports it. Trend presentation must not change the award formula.

Archive the final top five for every award, not just the winner.

## 10.8 Player and franchise trophy cabinets

Player Journey/Profile should show career honors: MVPs, position awards, OPOY/DPOY, postseason/championship MVPs, All-Brisket selections, etc.

Franchise pages should aggregate player honors earned *for that franchise* plus manager/team awards.

### Traded-player attribution

Do not award franchise credit merely to the player's last owner. Attribute qualifying award VORP by franchise/holding period. The player owns the individual award; franchise trophy credit should primarily follow where the award-winning production was actually generated, with secondary ownership history visible when useful.

## 10.9 Additional objective honors

Secondary League Honors may include, when data supports them:
- Draft Class of the Year;
- Best Draft Pick;
- Waiver Acquisition of the Year;
- Trade Acquisition of the Year;
- Most Improved Player with minimum participation requirements;
- Ironman;
- Giant Killer using a defined opponent-quality threshold;
- Clutch Performer using a fixed close-game/high-leverage definition.

Do not create awards such as “Comeback Player” unless the data truly measures the underlying concept.

## 10.10 Award ledger / methodology versioning

Create a canonical Award Ledger preserving season, award key, winner, top-five finalists, VORP/metric, franchise credit, methodology version, scoring-config fingerprint, input coverage and finalized timestamp.

For the inaugural system, backfill 2024/2025 with the approved 2026 methodology. Future methodology changes should be explicit/versioned rather than accidental consequences of changing a helper function.

## 10.11 Coverage gates

Awards require sufficient player scoring, starter attribution, position resolution and week coverage. Missing historical scoring must not silently become zero. If a season lacks defensible coverage, mark the award unavailable/insufficient rather than fabricating a winner.

**Method status:** PRODUCT DIRECTION OWNER-APPROVED; REALIZED LINEUP VORP PRINCIPLES OWNER-APPROVED; REPLACEMENT CALIBRATION + MOTY/GMOTY WEIGHTS REQUIRE HISTORICAL VALIDATION BEFORE INAUGURAL FINALIZATION.

---

# 11. GAME DAY HUB / GAME DAY CONSOLE

Approved future product concept for mobile + desktop, designed to be worth leaving open while watching NFL games.

Public-safe Game Day may include current matchup score, projected final, public win probability, live player scoring, relevant play-by-play, roster-player events, injury/news alerts, current best-ball lineup, players threatening to enter it, scoring-event explanations, remaining-player leverage, swing players, playoff implications, league scoreboard and public fantasy alerts.

### Best-ball requirement

Do not model a nominal starting slot as permanently finished merely because someone has already scored. Model:

**current best-ball optimal lineup + remaining players' probability distributions**.

Additional bench players may still replace current best-ball scores.

### Projection challenge

The league uses unusual scoring. Providers may not directly project every scored statistic (first downs, distance bonuses, etc.). Never pretend unavailable projected statistics are directly supplied. Translate available projections into league-scoring distributions using validated derived/historical conditional models where necessary.

Goal: improve weekly projection/live win probability specifically for this league.

Private Game Day may contain personalized actionable strategy; public Game Day remains sports-broadcast information.

**Method status:** PRODUCT APPROVED; PROJECTION/WIN-PROBABILITY MODEL REQUIRES VALIDATION.

---

# 12. TIGHT END PREMIUM METHODOLOGY REVIEW

Major future methodology review. Do not use a blanket multiplier such as ~1.15 without evidence.

Must consider actual league scoring, two required TE starters, flex eligibility, replacement scarcity, TE scoring relative to other positions, source-specific standard vs TEP rankings/curves, sources without TEP, KeepTradeCut TEP++, and whether uplift varies along the TE rank curve.

The owner's observation that KTC TEP++ values TEs somewhat higher than the current site is a diagnostic clue, not proof that KTC is correct.

**Method status:** INVESTIGATION REQUIRED — DO NOT INVENT A CONSTANT.

---

# 13. COMMAND CENTER / TRADE DESK / PORTFOLIO / ADP / STATS / PAR / LINEUPS / DRAFT ROOM

## CE-04 Dynasty Command Center

Action-oriented authenticated homepage answering **What actually needs my attention?** Candidate cards: incoming trade, waiver opportunity, lineup opportunity, injury, market move, Sharp signal, Insider signal, pick movement, Consensus Edge, Analyst/news signal. Rank by importance, not chronology. Private.

## CE-05 Trade Desk

Unified Incoming / Outgoing / Past Offers / Completed. Each offer eventually receives full decision intelligence. Private.

## CE-06 Dynasty Portfolio

Cross-league exposure with value-weighted team/position/window/pick concentration. Private.

## CE-07 Market ADP

Canonical time-series foundation for rookie ADP, startup ADP and optional best-ball ADP. Preserve format/source/time provenance.

## CE-08 Projections & Stats Hub

Canonical projections and realized stats with scoring-aware translation and provenance.

## CE-09 Replacement Value / PAR

One canonical replacement/PAR owner. Awards, roster intelligence and other pages consume it; they do not define their own replacement cutoffs.

## CE-11 Sleeper Action Gateway

One canonical mutation gateway for send/accept/reject/counter/withdraw trade, set lineup, IR, waiver actions and possible draft actions. Require auth, authorization, explicit league/team, preview, confirmation where appropriate, idempotency, error handling and audit trail. Recommendations never silently execute.

## CE-12 Lineup Intelligence

Potential modes: Max Projection, Ceiling, Floor, Underdog, Favorite, Injury Contingency. Only expose modes supported by actual data. Start with expected projection if that is the only defensible mode.

## CE-13 Draft Room

Private intelligence + optional public broadcast split. Public broadcast must not expose private targets/values.

## CE-14 Market Pulse

Use canonical market time series / Market Trade Ledger to explain meaningful market movement without inventing precision.

## CE-14A Personal Rankings Overlay

Owner/user-specific ranking overlay remains separate from canonical site ranking.

## CE-15 Portfolio Trade Campaign

Future. Do not implement automatic bulk trade spam.

## CE-16 Trade Polls

Optional/future; must not become a required dependency for canonical decisions.

---

# 14. ADMIN / ACCESS

## Admin runtime defect

Track and fix production `Can't find variable: fmtPassExpiry` as a real runtime defect, not mobile polish.

## Temporary password generator

Must work end-to-end: generate temporary password, configurable validity duration/hours, reliable expiration and actual friend access. Verify behavior, not merely UI existence.

---

# 15. PERFORMANCE / MOBILE

Performance and mobile are product requirements across rankings, Trade Calculator including 3-team layouts, Team Strength/Weakness, Golden Upgrades, Waivers, Perfect Waivers/Draft, Consensus Edge, BDVM, Analyst Intelligence, Sharp/Insider, Player Profile, acquisition history and public pages.

Use caching/SWR/windowing/pagination and compact payloads where appropriate. Never sacrifice player-name readability merely to fit a table.

---

# 16. LONG-TERM X/TWITTER ANALYST INTELLIGENCE

Potentially track a large reputable dynasty-analyst universe and extract structured intelligence, but API/data cost makes this **LONG-TERM / FUTURE ONLY** for the current private/small product. Do not build now. Preserve it in the roadmap in case scale later justifies the cost.

---

# 17. REMOVED / NOT APPROVED

Do not resurrect without a new owner decision:
- Fantasy Schedule Generator — REMOVED / NOT APPLICABLE.
- Full dispersal-draft system — not currently approved.
- Standalone rookie-WR model merely because a competitor has one — not approved.
- Generic best-ball product suite — not approved.
- Generic article/media CMS — not the strategy.
- Social-network/community platform — not approved.
- Automatic bulk trade spam — not approved.
- Competitor design/branding copies — never.
- Money / Constitution / League Media — removed/deferred from the current engagement; do not treat as current obligation.

---

# 18. OWNER-SPECIFIC STRATEGY OVERLAYS

These personalize recommendations; they do not redefine global player value.

- Minnesota Vikings players are effectively untouchable for the owner's roster.
- The owner intentionally pairs an NFL starting QB with that team's primary backup. Do not recommend breaking that handcuff solely for diversification.

---

# 19. REQUIRED IMPLEMENTATION PROMPT / CHECKPOINT STYLE

When a backlog item becomes active, Claude should normally be instructed in this order:

**investigate → reproduce → establish RED when it is an executable defect → identify canonical owner/root cause → minimally repair → GREEN → measure downstream effects → broader gates → exact-head CI → STOP for owner review.**

For exploratory/modeling work, do not fabricate a RED test. Define success criteria before selecting the candidate whose output looks nicest.

Every final checkpoint should state:
- exact scope completed;
- methodology used;
- files changed;
- before/after measurements;
- downstream effects;
- tests/gates;
- PR + exact head SHA;
- residuals/known limitations;
- whether any production-policy decision still requires owner approval;
- explicit stop condition.

A green suite is not sufficient proof that methodology is correct.

---

# 20. CURRENT EXECUTION GUARDRAIL

The detailed backlog does **not** authorize jumping ahead of the active foundation/audit program. Foundation correctness takes priority over attractive future features.

At the time this document was created, B4/W30-F023 had been accepted with tail boundary 904 and PR #805 authorized to merge after stale evidence-harness defaults were repaired. Subsequent work must follow the owner's current checkpoint authorization rather than treating this backlog as permission to start any feature opportunistically.
