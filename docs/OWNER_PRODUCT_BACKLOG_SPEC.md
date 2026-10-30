# Risk It To Get The Brisket — Owner Product Backlog Specification

**Status:** AUTHORITATIVE PRODUCT-SPEC COMPANION TO `docs/OWNER_FEATURE_INVENTORY.md`  
**Owner direction captured through:** 2026-08-12  
**Purpose:** Preserve not merely *what* the owner wants built, but *what the feature is supposed to mean*, its methodology, canonical dependencies, public/private posture, non-scope, missing-data behavior, validation requirements, and already-resolved owner decisions.

> `OWNER_FEATURE_INVENTORY.md` remains the scope/status inventory. This document is the detailed implementation intent. A one-line inventory entry must never be treated as permission to invent methodology that is specified here.

---

## 0. HOW CLAUDE MUST USE THIS DOCUMENT

**2026-10-30 owner-intake extension — Future First episodes 50–55:** The proposed private Roster Construction tab, selected-team positional league rankings (realized starter points separately from dynasty-value rank), player weekly start/average-starter/counterfactual history, roster efficiency, league meta, offensive/IDP role opportunity, contender/rebuilder roadmaps, draft/auction/waiver planning and Next Move recommendations are detailed in the **existing** canonical `docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md` §§9–20. Intake: `docs/OWNER_REQUESTED_TODO.md` FFBB-1–8; inventory row 1.8; Master Product Plan §4.1. That extension **adds research/planning ideas**, not automatic model promotion or production implementation authority. Current standalone player value, exact lineup, trade verdict, waiver/FAAB and draft-order owners retain precedence, and the owner has not authorized the final Claude prompt.

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

Owner overlay: Minnesota Vikings are effectively untouchable for the owner's roster *(Reconciled 2026-08-14: the precise rule is user + fantasy-league scoped, applies to the **outgoing** side of automatically generated packages only, leaves MIN players valid as incoming targets, and changes no canonical value. Binding spec: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`.)*; do not recommend trading Vikings merely for diversification. Intentional starting-QB + primary-backup handcuffs are purposeful exposure and should not be flagged as accidental concentration.

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

## 2.3 Best Trade to Send Each Team

**KEEP — NEW BUILD. PRIVATE DECISION INTELLIGENCE.** For every other team in the selected league, generate and display **exactly one best trade to send that opponent**.

This is a specialized consumer of the same canonical package-generation, valuation, roster-impact and external-market comparison infrastructure used elsewhere. It must **not** create a second trade finder, second value model or page-local package algorithm.

### Hard qualification rules

A candidate trade qualifies only when **all** of the following are true:

1. ~~**Players only.** No draft picks may appear on either side.~~ **SUPERSEDED 2026-08-14 by #841.** **Current rule:** draft picks are legal when both teams' strategic positions make them mutually beneficial. Never generic equalizer filler, never cosmetic, never used to make raw totals line up; a player-only offer stays preferred when it is the best mutual trade. Spec: `docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_ADDENDUM_2026-08-14.md`.
2. ~~**Equal player counts.** The number of players sent must equal the number received: 1-for-1, 2-for-2, 3-for-3, etc. No unequal-count consolidation packages qualify~~ **SUPERSEDED 2026-08-14 by #841/#842.** **Current rule:** `abs(players_A − players_B) <= 1`, with **picks excluded from the count**. 1v1, 2v1, 1v2, 3v2 and 2v3 qualify; 3v1, 1v3, 4v2 and 2v4 do not. Spec: `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md` for this feature.
3. **Canonical win for us.** From the selected user's/team's perspective, the site's canonical trade calculator/decision economics must grade the trade as a win. A merely even or losing canonical result does not qualify.
4. **Externally defensible for them.** The opponent must grade **even or better** on at least one approved external market calculator: **KeepTradeCut (KTC)** or **IDP Trade Calculator**.
5. **Whole-package native coverage.** An external calculator counts only when it can meaningfully/native-value every asset in the proposed package. Missing, unsupported, imputed-through-our-own-values, or partially covered assets may not be treated as an external win/even result.
6. **One result per opponent.** Return the single highest-ranked qualifying trade for each other team. If no candidate satisfies the hard rules with adequate data/coverage, explicitly show **No qualifying trade found** rather than weakening the constraints or fabricating approval.

### What “best” means

Do **not** simply maximize the discrepancy between our calculator and an external calculator. Among qualifying candidates, rank for a strong, plausible, mutually defensible offer using a transparent multi-factor objective that includes:

- improvement to our real roster after the trade: Team Strength, starting-lineup impact, weakness fixed/created, replacement/displacement and asset quality;
- magnitude/confidence of our canonical edge;
- opponent roster fit: whether the incoming players address their actual needs and come from positions where we can reasonably deal;
- opponent external-market acceptability: how comfortably KTC or IDP Trade Calculator says they are even/winning, with source and margin shown;
- plausibility / trade shape, avoiding absurd calculator-only exploits;
- dynasty asset quality, liquidity and tier preservation when otherwise close;
- untouchable/excluded-player controls and other explicit owner overlays.

The feature should prefer **the best trade we would actually want to send and they could rationally accept**, not the mathematically largest exploit.

### UX / explanation

For each opponent show at minimum:

- opponent/team;
- players we send;
- players we receive;
- canonical result for us and margin;
- which external calculator qualifies the opponent, their result/margin there, and coverage status;
- concise **Why this helps us** explanation;
- concise **Why they may accept** explanation based on their roster and the qualifying external market view;
- key roster-impact facts where material;
- confidence/coverage and any important caveat.

The league view should make it easy to scan all opponents and may sort by **Best Opportunity**, but must still preserve one result per opponent.

### Recommendation vs execution

This feature recommends/drafts an offer only. It must never silently send trades. Any future send action must go through the canonical league-action gateway with explicit user confirmation.

**Method status:** OWNER-DECIDED PRODUCT REQUIREMENT; EXACT RANKING WEIGHTS REQUIRE VALIDATION AGAINST PLAUSIBILITY/ROSTER-IMPACT EXAMPLES BEFORE PRODUCTION.

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

- Minnesota Vikings players are effectively untouchable for the owner's roster. *(Reconciled 2026-08-14: the precise rule is user + fantasy-league scoped, applies to the **outgoing** side of automatically generated packages only, leaves MIN players valid as incoming targets, and changes no canonical value. Binding spec: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`.)*
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


---

# 21. THREE-WEEK AGENT-READY FEATURE CONTRACT REGISTER — 2026-10-30 (MP3W-1…8)

**Purpose:** turn an owner idea into *observable, reproducible behavior* and a safe engineering handoff. This register is a **crosswalk and acceptance overlay over existing approved specifications**, not new valuations, new implementation authority, or a blanket reprioritization. See `docs/MASTER_PRODUCT_PLAN.md` §12 (dependency graph), `docs/BRISKET_IDEAS.md` §§15–16 (mandatory contract and orchestration), `docs/OWNER_REQUESTED_TODO.md` MP3W-1…8 (intake), and `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md` for 88 dated IDs. For any disputed semantics use the **newest actual owner decision**, especially the October 18–29 held/paused decisions.

An implementation agent must produce **an evidence-linked current-state diff before coding**: what inputs/endpoints and tests already work; what is partial/dormant/broken; what exact additional behavior is needed; which canonical owner has the edit; and what observed acceptance result closes it. Do not implement an entire feature again because this register describes the desired end-state.

## 21.1 Detailed contracts by shared product family

### FC-01 — Selected-team Roster Construction (FFBB-1/2; P1 future UX)
**Question:** Which teams actually got the most *optimal weekly starter points* at each position, how do those ranks compare with their *dynasty asset value* ranks, and where does my lineup fail despite nominal depth?
**Inputs:** selected authenticated league, team, eligible weeks, actual historical roster membership and transaction times, league scoring/starting rules, player identity/positions, weekly actuals, the exact legal global lineup solution, independent canonical snapshot values, optional as-of market history.
**Outputs:** seven QB/RB/WR/TE/DL/LB/DB rows with position's scored starter-point total, league rank/denominator, dynasty roster-value total and **different** rank, lineup appearances, unique contributing players, gap, confidence/staleness; week and player drilldown; FLEX/SF/IDP-FLEX attribution without duplication. Historical starts while owned vs counterfactual would-have-started and empirical average-starter qualification explicitly separate.
**Method and example:** take the host's exact 17-week eligibility and best-ball solver for the selected league, no hypothetical TE premium. In a hypothetical league with 12 teams, a team's TE group may rank 12th in **actual weekly legal starter points** but 2nd in **current dynasty value** because of a valuable injured prospect: that is a present-vs-future gap, not a reason to change TE player price. This example is illustrative, NOT observed data. For a player who ran up points while no longer rostered, historical owned-team realized points exclude those weeks; the counterfactual question must say it is hypothetical.
**UX:** mobile-first private dashboard; selected team and date/season; comparison with other teams, league median and role of FLEX; sortable group and player detail; plain-English reasons. Backend computes; UI never reassigns starters.
**Negative acceptance:** scoring rank and dynasty rank must not share a mislabeled denominator; no player can be counted twice by FLEX; in leagues with two mandatory TEs or 3 DL+3 LB+3 DB all slots must be counted; historical roster switches apply on the correct effective week; unavailable actuals or values say `INSUFFICIENT`, never zero. Design and calibration details: #1173 addendum §§9–20. **Stage:** new UX over mixed existing foundations, NOT authorized by this three-week capture alone.

### FC-02 — Weekly best-ball opportunity + roster utility (FFBB-2, #1173, C2/C5)
**Question:** How many realistic **incremental optimal lineup points** does a player/roster spot provide, with injuries, flex overlap, byes and availability?
**Inputs:** exact scoring, role/opportunity distributions per QB/RB/WR/TE/DL/LB/DB, weekly as-of lineup eligibility, roster membership, candidate replacement, FAAB/availability context.
**Outputs:** historical actual optimized entries, future LEP with calibration, usable scoring, conditional marginal weekly delta, spike-week overlap, coverage/insurance degradation, per-week/ROS/pick-horizon bounds, optional roster-slot shadow value. Separate **standalone canonical dynasty value** from team-conditional utility.
**Algorithm:** re-run the canonical lineup solver once per real/scenario week; compare R vs legal R' including required drops. Derive position/flex allocations from solved lineups rather than independent per-position counts. A WR scoring 16 fantasy points in week 5 might still **not** enter a stacked roster's WR or FLEX slots; '12 points' is not a league-independent lineup threshold.
**Acceptance:** synthetic cases prove one flex overlap, 2TE, superflex, IDP three-each, injury replacement, zero gains for dominated additions, profitable cheap replacement, and no free slot when FAAB/unavailable. Chronological holdout verifies predictive calibration and avoids leakage. **Stage:** partially existing/research; no shadow-challenger promotion by intake.

### FC-03 — Draft, market, trade and counter-meta decision surfaces (Oct 14–26, RIT, IDPM, FFBB)
**Question:** What feasible trade or startup pick/auction/waiver allocation should this manager choose given market cost, counterpart needs, legal capacity, value over time and actual weekly gains?
**Inputs:** actual ownership (no phantom pick), protected players, locks, typed draft assets, manager/posture, historical trade comparables with format/age, current canonical values, KTC adjustment **advisory**, roster marginal before/after, bid budget, auction draft board, current market supply. Market observation and analytically derived value must not be fused into an unlabelled number.
**Outputs:** candidate, why manager might accept, public/private qualification, per-side raw equity, market VA and Chase-side lens separately, relevant roster-score change, risk and pick effects, forced-drop and roster-slot costs, user-facing next step or **NO ACTION**, confidence and actual trading status.
**Contract:** Trade Finder/Suggestions/Golden Upgrades/Package Builder must consume one package legality/constraints owner. Best Trade/Manager Scout only recommend actual counterpart-owned assets. `geom_q078_v1` remains unchanged until separately approved; the private verdict comes only from the canonical decision owner. Public advisor evaluates 2–4 sides through the shared engine but returns **FAIR TRADE / NOT FAIR / UNABLE TO DETERMINE** with **no private numbers or advice**, and is not enabled by this document. In startup trades, evaluate later-round swaps as whole packages rather than pretending a 15th and 20th pick have identical marginal effects.
**Acceptance:** protected outgoing player never proposed; multi-team 3-/4-way pick routes conserved; final roster legal after drops; the same input produces consistent private verdicts across calculators; public private-value leak tests; no counterfeit comps; package gain passes genuine minimum-impact and fairness policy without conflating them. **Stage:** many RIT items merged but partial/held production verification. Detailed owners: Oct 14/18 trade directives, Oct 19 league decision engine, Oct 20 Advisor/n-team, Oct 21 LVA, Oct 26 IDPM, `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`.

### FC-04 — Cross-position IDP valuation vs opportunity (Oct 25/28, IDPV/NC-A/FFBB)
**Question:** Are top IDPs fairly valued *relative to offensive players* in this exact league, or is a discrepancy explained by supply, scarcity, scoring, best-ball usage, or market convention?
**Inputs:** actual 12-team/21-start composition where applicable; all defensive scoring categories (including TFL, pass defense, sack and first-down nuances), historical point distributions, weekly IDP stats, healthy/available status, selected scoring fingerprint, IDPTC and other independent sources with lineage/freshness.
**Outputs:** served-board baseline, verified empirical replacement distribution, league-relative shortage, per-position marginal ROS point potential, independent market trade-price evidence, calibrated **shadow** cross-position fair-value hypotheses, uncertainty, offense/IDP over-/under-valuation scenarios and action recommendation *only when authorized*. Show position class and temporal basis.
**Acceptance:** replay actual Sleeper awarded scoring; no manufactured 9-IDP x an arbitrary multiplier; compare DL/LB/DB and offense on the same projected scoring scale and exact lineup solver; temporal holdout and sensitivity tests (TFL/pass-defense weight sweeps, variable IDP starter demand); show where hypotheses fail. Do not equate observed IDPTC price with true value, alter canonical board, stop valid sources voting for disagreement, or restore TE++ by implication. **Stage:** research/shadow; owner approval required for live changes. Authority: `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`, NC-A, LI-5.

### FC-05 — Weekly IDP Streaming / Waiver Advisor (Oct 28–29 IST)
**Question:** Given a selected Sleeper team, **what legal adds/drops improve this and next weeks' optimized roster points** without unnecessarily discarding valuable dynasty assets?
**Inputs:** league ID and user-owned roster, weekly offense/IDP stat projections, source date/licensing/coverage, exact scoring, waivers and FAAB, injury/role/contingent snaps, roster locks, user dynasty-loss budget default zero, schedule and playoff weeks.
**Outputs:** legal ranked add/drop *packages* (not merely name rankings), projected lineup gain, multiweek and playoff risk, protected/conditional/churn classes with explicit reasons, affordable recommended FAAB/bid uncertainty, **0–7 streaming slots only when optimal**, explicit **NO TRANSACTION**.
**Method:** reuse `src/ros/lineup.py` and existing `src/waivers/streaming.py`/drop assessment/FAAB owners; no age-only 'safe to drop' rule. Statline projections scored under exact league rules; a 23-year-old future asset and a 30-year-old one-week streamer have different dynasty costs even if the veteran scores more this week. Point-in-time benchmarks include the anonymized Brent/Brenthany strategy.
**Acceptance:** ten required IST scenarios, cost budget, exact legal capacity, protected assets, source outages, playoff window, no-action and no accidental write; independent review/green exact-head CI and private signed-in activation gates. Existing IST work already owns this lane; **do not assign a competing new agent**. Full verbatim binding scope: `docs/owner/IDP_STREAMING_DIRECTIVE_2026-10-29.md` and execution §0; **Stage:** already authorized with active claims.

### FC-06 — Contender, rebuild, franchise portfolio and next move (FFBB-5/6/7)
**Question:** Should this team push, retool, hold or rebuild, and which *realistic* transaction improves its championship odds or future viable coverage?
**Inputs:** record and median-game context, weekly optimized points and variance, projected remaining strength, calibrated postseason odds where genuinely available, age/availability profile, liquid youth/picks, pick-origin forecast under actual written draft-order rules, season timing, realistic trade-market activity and waivers.
**Outputs:** roster health vs luck/record, injury fragility, projected contribution by year, transparent competitive posture, target year to field legal productive starters, conditional sell/buy/tier-up/tier-down candidates, affordable backup QB/RB contingent stashes, waiver-to-trade value flywheel, held 2027/2028+ draft-capital reserve, NO ACTION and honest uncertainty.
**Method:** same canonical posture and lineup simulation as Trade and Waivers. A 'productive struggle' build is a candidate strategy, not a mandate. A rebuilding team's low-scoring option asset may have trade upside but no near-term weekly points; a contender has a different shadow price for an injured veteran. Low-volume league requires liquidity evidence; hypothetical 2nd-round-pick buyers are not assumed.
**Acceptance:** compare before/after independent value, attainable weekly production and playoff probabilities **separately**, preserve future dynasty market opportunity cost and pick origin; no claim of a precise championship percentage from an uncalibrated model, no automatic tanking, no unapproved assumption that `dynasty_main` uses Max PF. **Stage:** planning/shadow, depends on FC-02/03 and calibrated existing postseason simulation. Reference: #1173 §§15–17, `docs/picks/DRAFT_ORDER_RULE.md`.

### FC-07 — Source identity, freshness, weighted voting, and independent validation (Oct 19–29)
**Question:** Which sources are independently valid, fresh, properly matched, authorized and worthy of their calibrated vote without an outlier filter silencing legitimate disagreement?
**Inputs:** source permissions, raw feeds, identity and canonical IDs, source lineage, dates, rank-to-value conversions, dynasty vs redraft, source family/coverage and time-varying thresholds, recorded historic truth.
**Outputs:** per-source explanation `used / stale / held / quarantined / unavailable`, reason and timestamp, lineage confidence, approval gates, corresponding source contribution and board delta if authoritatively applicable; provenance and no zero for absent feeds.
**Method:** weekly projection feed licensing is **not** implicit permission to vote in dynasty value; DLF IDP, D4, outlier integrity V2/V2.1, Signals IDP and freshness schedule retain separate hold/owner decision rules. Consensus agreement across independent providers does **not** mean one is a duplicated descendant without evidence.
**Acceptance:** adversarial wrong-player/rookie/rank-direction tests, disjoint source lineage and true data corruption tests, reinstating valid independent votes only behind authorized flags, proof of no silent source exclusion from agreement/disagreement, source/board snapshots before/after, chronological validation. **Stage:** multiple shadow gates held, NC-B bugs authorized; not automatic live changes. References: Oct 19 voting, Oct 20 IV2/IV21 owner directives, Oct 28 NC-B, `docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`.

### FC-08 — Exact league/draft/auction correctness (Oct 17–18 and related)
**Question:** Do lineups, scoring, rules, rookie draft dollar ledger and picks reflect the *same actual specific league* at the correct time, including rollover, auction and dual TE/IDP constraints?
**Inputs:** current/season-linked Sleeper settings, league-ID chain, scoring fingerprint, draft-year/round/slot/pick owner, annual cash budget; start lineup requirements and rule effective dates.
**Outputs:** season-stamped settings profile; reconciled and legally ordered draft selections; `dynasty_main` rookie value/dollar allocation summing to exactly **$1,200 per draft year** where binding; as-of draft capital, resolved/unknown draft slot, rookie auction cap and explicit incomplete statuses.
**Acceptance:** 12 teams / 72 draft picks where that draft-year setup applies, no unapproved `dynasty_new` assumption; do not use Max PF as `dynasty_main` draft-order policy; keep the documented unsettled median-game rule question visible; deterministic sum and rollover tests, owner permissions and immutable history evidence. **Stage:** mixed implemented/partial; refer to execution Oct 17–18, `docs/picks/DRAFT_ORDER_RULE.md` and RIT league/draft rows.

### FC-09 — Trade screenshot and transparency UX (Oct 15/18/19)
**Question:** Can a user import a long/full-page screenshot from any trade calculator with no manual cropping, see exactly who sends what, and get fast, understandable dual-lens analysis without ads/navigation included?
**Inputs:** uploaded image, pixel evidence, current source UI content, image/text parser reliability, trade side labels, OCR confidence, source attribution and user confirmation on ambiguous results.
**Outputs:** correctly assigned player/pick sides, omission of irrelevant page content, review dialog on unresolved ambiguity, Chase Upside and KTC Value Adjustments in labeled side-by-side compact form, plain-English verdict with three primary drivers, correct too-close/too-much-loss/multiple-cut explanations.
**Acceptance:** full-page KTC example Jaxson Dart vs De'Von Achane, rotated/cropped/long images, wrong-side and false-ad traps; no unapproved paid OCR service; a real authenticated phone screenshot E2E and measured warm/cold War Room response budgets. **Stage:** mostly merged, real screenshot and authenticated production tests not fully proven in Oct 25 RIT. References: C3-IMPORT-IMAGE, War Room/Trade Calculator directive, RIT-027/028/029.

### FC-10 — Public/private surface and MCP read-only connector (Oct 19–25)
**Question:** Can the user safely access their private Chase Upside rankings, league, Sleeper rosters and existing trade results in ChatGPT, while public advisors share **logic** but not sensitive values?
**Inputs:** authorized owner identity/session, site scope, tool arguments, canonical league/roster/identity, current private feature flags, freshness/coverage.
**Outputs:** the five initial owner-only read-only capabilities with source timestamps, citations/provenance/confidence and explicit unknown states, shared with the site's existing analytics. Public fairness only contains permitted classification and no private value details.
**Acceptance:** negative ID/access tests, read-only enforcement, 401/403 isolation, no uncontrolled token/log exposure, no write gateway or public promotion without separate authorization; integration/version contract tests with the exact main API. **Stage:** scoped PR/review only; no implicit connect/publish/merge. Reference: Oct 25 MCP execution intake and `docs/ops/CHATGPT_MCP_SETUP.md` where available.

### FC-11 — Reliable product completion and safe parallel release (Oct 18–29)
**Question:** Is the experience **actually verified live and useful**, not merely code-present, and can multiple independent agents build compatible work faster?
**Inputs:** claimed file/branch graph, exact main/PR SHA, versioned contract, per-feature/backend/UI acceptance, deterministic data snapshots, L0–L3 tests, release gate, authenticated real user path and deployment fingerprint.
**Outputs:** current capability stage, unit-level GREEN/RED, observed production parity, measured latency, remaining blockers, separate model/launch owner decision and rollback plan; Integration-owned reviewed/green routine PR merge decisions.
**Acceptance:** multi-team tests across projects, no published private data or secrets, realistic full User flow/phone WebKit, no stale 2026-10-25 break asserted as 2026-10-30 truth, independent review not self-certification; no forced flag activation. **Stage:** continuous existing process with open reliability items; refs `docs/AGENT_OPERATING_SYSTEM.md`, `ASSISTANT_COORDINATION.md`, NC-C and RIT-073/078.

## 21.2 Standard implementation state and claim discipline

**Product scope decision** is different from **implementation lifecycle**. A spec may be owner-approved while backend is merged, UI partial, feature flag OFF, production stale, or acceptance unverified. Track these independently. Recommendation engine and market price always remain separate. If a child spec/date contradicts another, apply the repository's later explicit owner decision and annotate which text is superseded; do not silently inherit a 2026-10-19 public ACCEPT/DECLINE wording contradicted by 2026-10-20 fairness-only or a DLF voting rule contradicted by the 2026-10-20 hold. 'Propose experiment' is not 'activate experiment'. External source permissions are scoped; paid APIs prohibited without approval.

# 22. THREE-WEEK ZERO-LOSS RECONCILIATION — WHAT IS PRESENT VS OPEN

**Window requested:** 2026-10-09 through 2026-10-30. **Evidence:** recoverable app-development conversations, the current owner intake, GitHub current planning documents, Oct 25's dated 88-row `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md`, October 19–29 owner directives, PR #2026 (Future First research), and available merged/flag metadata. No claim that every old Oct 9–10 chat was individually replayed or every logged-in production endpoint was independently verified in this planning-only audit. **Classification:** `CAPTURED_EXISTING`, `SPEC_DETAIL_ADDED`, `NEEDS_CURRENT_STATUS_AUDIT`, `HELD_OWNER_GATE`, `PAUSED`, `PROPOSAL_ONLY`, or `UNKNOWN_SOURCE_NOT_RETRIEVED`. This is not a new 88-item denominator.

| Owner request / dated cluster | Durable source and traceability | Resolution of this audit |
|---|---|---|
| Oct 9–13 early partial conversations, where recoverable; Oct 14–18 Trade Finder, Package Builder, Golden Upgrades, manager-scout, limits/meaningful filters | RIT-001…014; Oct 14 and Oct 18 trade directives | **CAPTURED_EXISTING**, detailed FC-03. Do not reopen completed code; independent live coverage quality remains to verify |
| Oct 15 universal screenshot from any calculator, entire mobile screenshot (ignore ads/nav/Insights), ambiguous review | RIT screenshot rows; `C3-IMPORT-IMAGE`, current Trade Calculator instructions | **CAPTURED_EXISTING**, FC-09; real phone screenshot path still needs status/evidence |
| Oct 17–18 draft-dollar allocation, 2027–29 automation, pick-owner/rollover, league scope vs dynasty_new | execution Oct 17/18 and RIT draft/league rows; recorded draft-order rule | **CAPTURED_EXISTING**, FC-08; do not blend league scopes or assume Max PF |
| Oct 18–19 private trade verdict, dual KTC/Chase VA, compact plain-English War Room, speed | Oct 18–19 decisions, RIT-015+ | **CAPTURED_EXISTING**, FC-03/09; verify production rather than treating test-only proof as delivered |
| Oct 18 pause DFS and League Tycoon; no scope/spend/start | Intake, execution and RIT-085/086 | **PAUSED**, do not silently schedule work or infer DFS contest planning authorizes site feature work |
| Oct 19–21 source voting, freshness, DLF / Signals, outlier V2/V2.1 / D4, low-value forced-drop, fairness `geom_q078_v1`, public/private Advisor, 2–4 teams | 2026-10-19/20/21 intake, verbatim directives, RIT-017…041 and related owner gate rows | **CAPTURED_EXISTING**, FC-03/04/07; many **HELD_OWNER_GATE**, don't flip them |
| Oct 21 unlisted waiver comparison (fixed formula, no drop suggestion) | WWC-1…4, RIT waiver rows | **CAPTURED_EXISTING**; separate simple no-login unlisted value-comparison feature from authenticated advanced Waiver Advisor; never extend unlisted page into advice without new authority |
| Oct 25 88 requirement track inventory and release health | Exact 88 row statuses in `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md` | **CAPTURED_EXISTING**; 56 code/test verified is NOT necessarily 56 production verified. Review stale statuses as of latest HEAD |
| Oct 25 read-only platform research / source/promotion-readiness audit | RPA-1/2, existing audits and evidence | **CAPTURED_EXISTING**; no production/source changes from audit |
| Oct 25 independent IDP valuation, scoring parity and replacement/cross-position fairness | IDPV-1… etc, `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` | **CAPTURED_EXISTING**, FC-04; chronologically validate challenger, owner gate for live value |
| Oct 25 owner-only read-only ChatGPT MCP | execution Oct 25, intake MCP section, PR #1921 successor | **CAPTURED_EXISTING**, FC-10; read-only, no auto publish/merge/deploy/credential actions |
| Oct 26 IDPTC vs own-league trade prices, buy/sell/draft/auction, historical as-of IDP valuations | IDPM-1…11, 2026-10-26 directive | **CAPTURED_EXISTING**, FC-03/04; market context non-voting, before archive history boundary explicitly unknown |
| Oct 27 league source comparison / IDP sources and provider investigation | source permissions / IDPM and Oct 28/29 intake; established provider data | **SPEC_DETAIL_ADDED** via FC-04/05/07; consider coverage gaps as research, not new voting/purchases |
| Oct 28 IDP/offense weekly ROS comparability, source authority, Trade Advisor/waiver readiness and E2E | NC-A…E, 2026-10-28 directive | **CAPTURED_EXISTING**, FC-04/05/07/11; newer completed PRs may have superseded old Oct 25 status |
| Oct 28–29 IDP weekly stat-line sources, safe-to-drop, streaming/no-transaction, weekly playoff horizon, Brent benchmark | IST-1…12, 2026-10-29 verbatim directive | **CAPTURED_EXISTING**, FC-05; **authorized ongoing**, not merely a future idea |
| Oct 29–30 Future First six episodes 50–55 / Roster Construction and derived 44 RC working concepts | FFBB-1…8, #1173 addendum §§9–20, PR #2026 | **SPEC_DETAIL_ADDED**, FC-01/02/06; not authorized as code by intake |
| Oct 30 master-plan completeness, every idea logged, shared foundations and synchronized multi-agent execution | MP3W-1…8, master plan §12, `docs/BRISKET_IDEAS.md` §§15–16 | **SPEC_DETAIL_ADDED**; standing future owner-intake policy, subject to existing execution gates |

**High-impact still-unfinished or held examples as of the Oct 25 audit (recheck now):** RIT-007 competitive posture/held forced drop, RIT-012 real market ledger with staleness concern, RIT-019/020 multi-team Lane E, RIT-027/028 authentic production and screenshot test, RIT-031/037 dormant replacement/forced-drop, RIT-034/041 scoring parity/approval, RIT-035/036/039 league shadow-model holdouts, RIT-072/073 source/box units, RIT-078 E2E red, RIT-084 claim tracker, RIT-087 review. Owner-only decisions list in original audit §5 (source activation, public Advisor permissions and launch, Q2 holdout, source freshness, DLF and outlier V2, Signals, paid feeds, production secrets, paused domains) remains authoritative. RIT-088 is explicitly a **proposal**, not an approved feature. An October 25 broken status is **not** asserted still broken on October 30 without fresh evidence.

**Unresolved evidence:** This audit was not supplied with a complete searchable export of every app-related October 9–10 user message. The RIT inventory begins October 11 and later owner directives cover the rest. Do not call the window exhaustively replayed or claim unlocated original conversations contained no ideas. Future periodic audits should compare conversation intake with durable records, record any source gaps and reopen only genuine differences. In the absence of all chat evidence, status remains `UNKNOWN_SOURCE_NOT_RETRIEVED` instead of fabricating a requirement.

**Completion of planning capture** means: owner intake rows MP3W and FFBB point to the detailed feature-spec registry; the master plan maps unique canonical owners, prerequisites, execution waves and hold gates; existing 88 RIT tracks stay incorporated by their precise IDs; stale/completed/paused status is never silently overwritten; the user can trace any idea from intake to a spec and to implementation evidence once later approved. This documentation capture itself is NOT code completion, no new scheduled run, and no authority for the final Claude implementation prompt unless separately requested.


---

# 23. THREE-MONTH SOURCE-PRESERVATION SPECIFICATION — 2026-10-30

**Historical exact-intent index:** `docs/owner/CHASE_UPSIDE_90_DAY_CONVERSATION_AUDIT_2026-10-30.md` §§1–5. The 72 recovered R-IDs and 88 separately reconciled RIT-IDs are not new feature tickets; consult their original owner specs rather than treating this cross-reference as implementation. This section augments FC-01…11 with details found in July–October discussions which generic labels could omit.

| Exact owner decision / user experience | Implementation-ready pass/fail rule; canonical path | Stage |
|---|---|---|
| **Product name and PSI Direction A** | User-facing platform called **Chase Upside**. Preserve editorial/tabular, high information density without generic AI cards/glass/pills/gradients, deliberate accessibility and responsive behavior; test old/new page parity, no big-bang UI fork. `docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` and Lane 6 | PERMANENT DIRECTION, route progress mixed |
| **Public League + global team** | Authenticated mobile/desktop one-click `/league`; independent private War Room and public League Museum. Canonical globally selected fantasy team across Game Day, ticker and roster tools; actual NFL kickoff order retained; section-only Sleeper sync with freshness/status/cooldown. R-08/11/12/67/69/70 | PARTIAL OR MIXED; current browser proof needed |
| **Podcast/YouTube/Analyst and Upside Report** | Source feed reset to owner's explicitly chosen inventory; ~50 candidate YouTube sources deduped across podcast IDs; attributed factual evidence vs analyst take; freshness expiry without deleting transcripts; unified Player Profile/Buy-Sell. A selected-roster 10–20-minute brief ends with **five important takeaways**; weekly mobile report has shareable graphics and archive. R-05/06/07/15/18/32/33; #782/#783 | STAGED / NOT A NEW MEDIA-SCRAPER AUTHORIZATION |
| **Market buy/sell and roster exposure** | SELL ticker candidates are **only on globally selected fantasy team's roster**; BUY may be global. NFL-team exposure before/after trade must use **canonical market-value-weighted** roster values, counts secondary and informational only. #784/#786 | Existing owner specs; consumer test still required |
| **Individual special teams & exact scoring** | `kr_yd`, `pr_yd` and supported individual `st_*` points go to relevant player, not DST; use actual league scorer/weekly exact lineup. TE2 ≠ automatic TE premium; superflex + 9 IDP only where configured. #802, score specs | Cross-product scoring correctness; use current evidence |
| **Duplicate generic draft picks** | Two `2027 Mid 1st` tokens persist as TWO distinct assets through addition/removal, VA, source opinions, 3–4-team transfer, save/share/history and team-specific effects; neither secretly becomes a specific owned pick unless resolved. R-10 | Old owner requirement; current-state verification |
| **Second Opinions hybrid fallback** | External vendor's **normalized source-native** inputs for covered assets + direct exact Chase canonical fallback for each missing IDP/rookie/pick, single active VA, each fallback labeled `HYBRID ESTIMATE`; vendor row does **not** count as fully independent source majority. R-40; Oct 17 owner prompt | Detailed contract present; verify actual status |
| **Roster-neutral headline package pricing** | Same player/pick package + same scoring/valuation format must yield the SAME headline equity/active Value Adjustment if a user selects a totally different roster or no roster. Roster-fit / forced-drop / best-ball utility belong to separately labeled outputs, trade decision context may consume them without feeding price. Oct 17 final owner decision, sitewide version dispatch for /trade, /trades, /league | Critical override on FC-02/03; regression/test as separately authorized |
| **Rookie auction AUC** | 12 seats; six nomination opportunities, max 12 open lots, $0 legal bids/wins, whole-dollar proxy, owner-supplied points-for order, 8AM–9PM ET active hours, custom budgets, mocks. **$50 available leading $45 = $5 spendable**; no double charge/concurrent overspend. Native Web Push/inbox, optional verified email, no external app/VPN/SMS; real iOS/Android proof, not merely service acceptance. Unconfirmed official clock/tie/withdrawal/outage policies remain proposals. `docs/auction/ROOKIE_AUCTION_ROOM.md`; AUC-001/002 | Mock readiness and transport code previously reported merged; official launch OWNER-HELD |
| **League Tycoon 100/44 capture** | Original fully detailed proposal from **open PR #1755** was not yet integrated in main. Standalone preservation `docs/owner/LEAGUE_TYCOON_DEFERRED_IDEAS_PRESERVED_2026-10-16.md` contains every mechanism and all 44 future candidate ideas, proposed phase/contract/cap/migration gates. **No code unless owner explicitly says start.** | PARKED; do not add to current C completion denominator |
| **Oct 29 failed saved login** | Owner reports formerly accepted saved login now rejected without deliberate change. Preserve `UNREPRODUCED`; auth owner should inspect sanitized 401/403/network/deploy/sessions, autofill/cookies and current auth state. No guessed password, credentials in logs, public user information or account mutation during planning audit. | NEWLY CAPTURED USER-REPORTED SYMPTOM; NOT VERIFIED DEFECT |
| **Market Edge Lab adjacent project** | Sportsbook/odds/venue comparisons, Kalshi benchmark, chronological archive belong to separate `market-edge-lab` and distinct deployment/auth, with Gate 4 owner boundaries; do NOT silently merge into paused Chase Upside DFS or trade prices. | CROSS-REPO PROVENANCE ONLY |

**No-detail-loss gate:** Each implementation ticket must point to both a brief 3MA source row and **full original spec** or documented `SPEC_GAP` (user wording if recoverable, inputs, exact behavior, numeric constraints, acceptance and authorization). A feature may require **zero code** if it already passes current-HEAD tests and user-visible acceptance. Date and evidence source are mandatory; no current status from a stale 2026-09-10 or 2026-10-25 report without checking the latest build.

**Raw-chat coverage:** ChatGPT conversation search is not a full downloadable account history; the earlier 72-cluster and later 88-track audits plus partial intervening conversations form a **high-coverage recoverable** audit, not a literal message census. Record `RAW_CHAT_NOT_RETRIEVED` for unresolved historical gaps. Do not publish original private chat messages or sensitive project/user data in this public GitHub repository.
