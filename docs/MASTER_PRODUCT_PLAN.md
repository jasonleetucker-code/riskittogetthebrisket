# Risk It To Get The Brisket — Master Product Plan

## Continuous UI convergence — owner decision, 2026-09-24 (#1421)

UI policy: ALWAYS_PARALLEL_UNTIL_UI_COMPLETE

Calculator Ideas is the entire remaining completion portfolio, including UI, not just
recent intake. Backend completion without user-facing completion is not product
completion. Track capability and UI evidence as two dimensions of one product, not
separate products or new denominator rows. Keep existing Lane 6 active beside model/
feature/data work. A route blocker redirects the UI lane to another safe task.
Every substantial batch includes UI or names its adequately staffed active claim/PR.
Use `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` and `docs/ui/UI_PARALLEL_LEDGER.md`; implementation authority remains EXECUTION_PLAN.md.

**Status:** CANONICAL FRONT DOOR FOR PRODUCT DIRECTION  
**Owner direction reconciled through:** 2026-09-24 for owner-intake/parallel-work process; product-direction body retains its existing dated decisions  
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
| How do I add an owner idea / see how it should be grouped or parallelized? | **`docs/BRISKET_IDEAS.md`** front door → `docs/OWNER_REQUESTED_TODO.md` live intake ledger. This is process/navigation, not implementation authority. |
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

## 3.8 Adaptive learning is permanent; facts and rules do not learn

Owner directive 2026-10-01. Calculator preserves what it knew, predicted, recommended, did or did not do, and
what happened afterward, and improves its models from that point-in-time evidence through champion/challenger
evaluation (§3.4, P6). This is a shared capability over the existing history, model-registry and domain
archives, not a separate ML platform per feature and not a generic feature store.

Adaptive systems never rewrite: scoring arithmetic, league settings, player identity, pick ownership, lineup
legality, roster rules, transaction legality, source identity, timestamps, provenance, privacy boundaries, or
unknown-vs-zero semantics. They estimate uncertain relationships around those facts. Drift triggers
reevaluation, never automatic retraining or promotion. Detailed plan, owners and units:
`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` Part II; authorization: `docs/EXECUTION_PLAN.md` §0.

Owner re-send 2026-10-01 (directive §21–§30), binding on every adaptive system: **capture perishable evidence
first** — modeling can wait, irrecoverable evidence cannot; **rejected challengers are retained evidence**, never
deleted; a learned influence that changes a user-facing recommendation carries evidence-generated reasons
(sample size, holdout, cohort), never unexplained "AI"; **random train/test splits are prohibited where time
ordering matters**; and Adaptive Learning counts as implemented only when the SOURCE, TRADE, PROJECTION and
MODEL GOVERNANCE feedback loops are closed in code on real data. Autonomous trades, waiver moves and DFS entries
are not authorized. Plan Part III (§26–§38).

---

# 4. MASTER FEATURE MAP

`OWNER_FEATURE_INVENTORY.md` remains the exhaustive row-level ledger. This section defines the unified product families so isolated ideas cannot drift into parallel systems.

## 4.1 Canonical roster intelligence

**Owner planning extension — Future First Dynasty Best Ball six-episode research (2026-10-30, FFBB-1–8).**
A private **Roster Construction** team-selection tab should compare each team's *realized optimized starter points and league ranking by QB/RB/WR/TE/DL/LB/DB* against separate *canonical dynasty-value rankings* and position-by-position forward scoring readiness. Add player historical optimal appearances while owned, explicitly labeled counterfactual would-have-started weeks, empirical league-average starter qualification, marginal lineup points, false-depth/insurance metrics and transparent position/flex attribution. Apply exact league rules (including two TE, Superflex and nine IDP starters where configured), not podcast benchmark point thresholds. Offense and IDP positions share the canonical exact lineup, replacement, roster value and projection owners. FLEX is assigned globally, not an additional sortable ranking.

The extension connects a **league-meta/market-supply**, **transaction/roster repair**, **contender readiness**, **rebuild exit / asset flywheel**, and explanatory **The Next Move (including NO ACTION)** experience. New analytical models, contingent assets, market/liquidity/sell windows, draft/auction, waiver calendars, future picks, portfolio aging, role projections, and decision-quality audit are researched as dependent capabilities rather than competing product engines. Preserve canonical player market values as distinct from roster-specific weekly lineup utility and playoff probabilities; keep historical as-of and uncertainty explicit. The binding existing #1173 best-ball utility contract is extended for planning detail in `docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md` §§9–20. Intake `docs/OWNER_REQUESTED_TODO.md` FFBB-1–8; inventory 1.8; planning overlay on C2/C3/C4/C5/C7 and current IDP waiver work. **Intake is not implementation authorization:** `docs/EXECUTION_PLAN.md` remains unchanged; user has not yet requested the final Claude implementation prompt.

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

> **SUPERSEDED 2026-08-14 by owner addendum #839.** The fixed caps above were approved as an
> **initial** definition and, per the Method status line below, were never canonical. #839 is an
> explicit later owner decision that names them and replaces them with one league-config-derived
> selector: **`ceil(1.5 × real starter demand)`** per position, **Superflex counted as real QB
> demand** (added to QB demand *before* the 1.5×), and regular offensive / IDP FLEX each creating
> **`ceil(1.5 × real flex slots)`** from the highest-valued remaining legally eligible players after
> the dedicated cores, with **each player counted at most once**.
>
> The caps are retained here as historical context, not deleted — they record owner intent
> faithfully at a lower resolution. The successor ships as a **V1 champion labelled PRIOR** and
> carries the `MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §4.3 challenger pass (1.25× / 1.50× /
> 1.75× / a data-derived cutoff) before it may be frozen as canonical methodology.
>
> Canonical records: `OWNER_FEATURE_INVENTORY.md` row 1.7 · `OWNER_REQUESTED_TODO_SPEC_INDEX.md`
> T-NEW-19 · manifest `C2-CORE-01`. Full provenance and the evidence that #839 is a direct owner
> decision rather than a calibration recommendation:
> `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §4.1.

> **AMENDED 2026-08-18 by owner addendum #899 — ordering, not magnitude.** #839's selector above
> fills FLEX *"after the dedicated cores"*. That ordering is superseded. **FLEX is an assignment
> rule that decides which players enter the meaningful-roster value pool; it is not a separate
> sortable Team Strength position.**
>
> The canonical order is **actual starter assignment first, reserve/depth second**:
>
> 1. solve the **actual starting lineup** from real league configuration — dedicated QB/RB/WR/TE
>    slots, ordinary offensive FLEX, Superflex, and IDP/IDP FLEX where present;
> 2. assign dedicated starters to dedicated slots;
> 3. fill each **actual FLEX starter slot from the highest-valued remaining legally eligible
>    players** (if RB3 and WR4 are the two best remaining in a 2-FLEX league, they are FLEX
>    starters — **not** positional depth);
> 4. **remove every actual starter, FLEX starters included**, from the remaining pools;
> 5. only then apply the multiplier to **reserve** demand.
>
> Reserve demand per dedicated position is `ceil(M × dedicated starter slots) − dedicated starter
> slots`; FLEX reserve demand is `ceil(M × actual FLEX starter slots) − actual FLEX starter
> slots`, selected globally from the highest-valued remaining legally eligible players **after**
> dedicated and FLEX starters are removed. `M` remains the **1.5× V1 champion/PRIOR** and keeps
> the §4.3 challenger pass — this amendment changes *when* players leave the pool, not the
> multiplier.
>
> **Every player counts at most once** across dedicated starter, FLEX starter, dedicated reserve
> and FLEX reserve. Superflex stays separate from ordinary RB/WR/TE FLEX; IDP FLEX behaves
> analogously with its own eligibility pool. Implement by reusing the canonical exact
> lineup/assignment machinery (`src/ros/lineup.py`), **never** independent per-position greedy
> lists, which can double-count.
>
> **No FLEX column is required.** Sortable position groups stay QB / RB / WR / TE / DL / LB / DB.
>
> Canonical record: `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` (issue
> #899). Tracking/specification only while the audit freeze is active — it does not by itself
> authorize forward C2 implementation.

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

### Roster age-value portfolio / Young Core Index

League-relative age/value intelligence on every team profile: value-weighted core age over the canonical
**meaningful** roster group, an age-value distribution, per-position-group profiles with league rank and
percentile, and a 0–100 **roster-construction** index answering who owns the strongest concentration of
meaningful young talent.

**This describes roster construction; it does not alter player value.** Canonical dynasty value already embeds
age and market expectations — do not create a second age-adjusted valuation. Missing age stays missing, and
picks are excluded from age math rather than treated as age zero. Youth must be normalized per position and
weighted by canonical value, so a roster full of low-value youth cannot dominate the index.

Sequenced **after/with** the Team Strength and Team Weakness foundations it consumes. Binding requirement:
`docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` (#838).

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
- **Best Trade to Send Each Team** — for every other team in the selected league, exactly one best mutually
  defensible offer: a canonical win for the selected team, and even
  or better for the opponent on KTC or IDP Trade Calculator with complete native coverage of every asset.
  Missing, unsupported or imputed external coverage can never manufacture qualification. Ranked for real
  roster benefit and mutual defensibility rather than the largest calculator discrepancy; honest no-result
  state when nothing qualifies; recommendation only, never a silent send. Persistent user+league outgoing
  protection and generated-package LOCK/EXCLUDE refinement are part of the same contract and are consumed by
  every generated-trade surface through ONE canonical constraint owner. **Topology, per the newer 2026-08-14
  decisions (#841/#842):** draft picks are legal when both teams' strategic positions make them mutually
  beneficial — never as filler — and player counts may differ by at most one
  (`abs(players_A − players_B) <= 1`), with picks excluded from that count. The earlier `players only` and
  exact-equal-count rules are withdrawn. Binding specs:
  `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`,
  `docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_ADDENDUM_2026-08-14.md`,
  `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`;
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

**SUPERSEDED 2026-08-14.** This sentence allowed valid 2028/2029 picks to remain unpriced indefinitely. The newer owner requirement is that **every valid league-supported draft-pick asset through the 2029 rookie class must carry a finite, non-missing canonical value** by C completion — see `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §2 and §10, and manifest row `C1-PICK-01`. MISSING IS NEVER ZERO is unchanged and is not the thing being superseded: the replacement for an unpriced pick is a documented generic/future valuation carrying provenance and uncertainty, never a zero and never a dropped asset. Unknown exact slot is not permission to drop the asset.

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

> **`docs/CE_REGISTRY.md` is the canonical CE registry as of 2026-08-14.** The list below mirrors it and
> loses to it on any disagreement. The registry now runs **CE-01…CE-29**: CE-22…CE-29 were minted to resolve an
> identifier collision in which 18 of 22 ids named two different capabilities.

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

---

# 12. OWNER THREE-WEEK IDEA RECONCILIATION AND COORDINATED BUILD MAP — 2026-10-30

**Direct owner instruction MP3W-1…8.** This section is the **authoritative roadmap routing and dependency graph** for the Oct 9–30 intake audit, **not** a competing detailed specification, implementation authorization or completion denominator. The exact build contract for a capability is the corresponding `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §21 plus the named dated feature-specific spec/owner directive and the live canonical implementation owner. All new product ideas must be recorded in `docs/OWNER_REQUESTED_TODO.md`. **Never ask the user to remember which roadmap to update.**

## 12.1 What an agent must be able to determine

For any item, an independent agent without access to chat must discover: **(1)** the exact user-visible question and user/persona; **(2)** the selected league and exact scoring/position/waiver rules; **(3)** required input fields and source-of-truth/staleness/permission semantics; **(4)** canonical module/API owner and whether the change is new, repair, extension, or already implemented; **(5)** calculations and expected output fields, including examples and negative/no-action cases; **(6)** UI state and public/private boundary; **(7)** lifecycle stage and active flags; **(8)** dependencies and shared contracts; **(9)** representative acceptance scenarios and measurable benchmarks; **(10)** authorized vs deferred/owner-only changes and the next smallest safe work unit. If any are missing, complete the **specification** or label the gap; do not invent methodology to close it.

A label such as “roster intelligence”, “IDP pricing” or “better trades” **fails** the feature-definition standard. For example, the Roster Construction tab is specifically: select a league and team; compute **realized points from that team's legal weekly optimized starters by actual QB/RB/WR/TE/DL/LB/DB position**; rank that position against other league teams; independently rank the same position's **canonical dynasty market/model value**; drill into weekly historical actual start count, counterfactual starts, empirical league-relative starter threshold, optimal lineup point contribution, injury insurance, redundant points, and what-if trade/waiver impact; do not count a FLEX-assigned player twice. Its complete formulas, UI, missingness and acceptance are in the original #1173 addendum **§§9–20**.

## 12.2 Three-week canonical project routing (Oct 9–30, 2026)

| Family / user-facing promise | Detailed existing owner record | Shared foundations, downstream consumers | Working disposition / proof needed |
|---|---|---|---|
| **Roster Construction & best-ball contribution:** actual positional lineup points vs separate dynasty values; start rates and counterfactuals; false depth, 2TE/SF/9-IDP when configured | #1173 `docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md` §§9–20; intake FFBB-1…8; inventory 1.8 | league scorer + as-of rosters + C2 exact lineup, C2 replacement, C5 projections → private roster tab, Trade/War Room, Waiver Advisor | New selected-team UX; underlying capabilities partial. Plan P1, **not implementation-authorized by this intake** |
| **Trade Finder / Best Offers / Package Builder:** identify *attainable* meaningful trades with ownership, manager needs, untouchable/LOCK, honest roster capacity and draft-pick constraints | `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md` RIT-001…014; original Oct 14–18 trade-discovery directives; C3/C7 specs | canonical identity/picks, roster simulation, market comps and posture → suggestion products, Trade Desk, Manager Scout | Many code/test-verified Oct 25, **not automatically production-verified**; remaining coverage and forced-drop gates as RIT details |
| **Private Trade Calculator and War Room:** YES/NO/TOO CLOSE/INSUFFICIENT EVIDENCE, per-side context, explain 3 major reasons, Chase/KTC Value Adjustment side by side, screenshot import, readable mobile performance | RIT-015 onward; `docs/owner/LEAGUE_INTELLIGENCE_TRADE_DECISION_ENGINE_2026-10-19.md`, trade completion/War Room directives; `docs/OWNER_REQUESTED_TODO.md` 2026-10-19…21 | one `trade_decision.decide()` owner, #1173 roster utility, KTC **advisory**, historical comps, privacy/performance gates | Existing mixed stages; determine exact remaining test/review/prod evidence, don't claim all complete |
| **2–4-team trades & public Brisket Trade Advisor:** one server calculation, per-team fairness, public FAIR TRADE/NOT FAIR/UNABLE TO DETERMINE **without exposing proprietary numeric values** | `docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md`, `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`, OD-F family | same private engine, roster legality, admission/rate limiting and private-public projection | Partly merged/held; public flag and consequential release gates owner-reserved; no alternate public math |
| **IDP independent values / cross-position utility:** tell whether DL/LB/DB players are underpriced relative to offense without forcing agreement with IDPTC; league-scored replacement, best-ball usefulness and multi-season demand | `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`, IDPV family, LI-5, NC-A, #1173 | canonical scoring, point-in-time history, source truth → separately calibrated shadow benchmarks → trade/strength/advisory use only after approval | Shadow/research; **not** permission to change canonical IDP values or absolute ceilings |
| **IDP acquisition, selling, drafts & market:** as-of true trade prices, league maturity/format, IDPTC comparison, maximum reasonable offer, role alternatives and rookie/auction demand | `docs/owner/IDP_MARKET_ACQUISITION_DIRECTIVE_2026-10-26.md`, IDPM-1…11 | Sleeper league-history chain, time-stamped value archive, canonical trade ledger, replacement & roster simulation → Trade Desk/draft/auction | Read-only history and shadow proposals authorized per execution plan; market source is **non-voting** |
| **Weekly IDP projections, dynasty-protected churn and Waiver Advisor:** exact weekly stat categories, safe drops, 0–7 stream slots, legal lineup gains, FAAB, multiweek/playoffs, explicit no-transaction | `docs/owner/IDP_STREAMING_DIRECTIVE_2026-10-29.md`, IST-1…12, `docs/EXECUTION_PLAN.md` 2026-10-29 | existing projections + canonical lineup → streaming composer & dynastic protections → private UI and pinned backtest | **Authorized implementation** with active parallel workers; activation only upon mandated review/CI/acceptance |
| **Valuation sources/freshness/lineage:** usable independent votes, source integrity, DLF / Signals gates, corrected timestamps, no false confidence or missing-as-zero | 2026-10-19 universal votes, `docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md`, V2.1, NC-B; source/voting records | source adapters → lineage, identity, normalization, outlier policy → canonical board; must not silently alter source votes | DLF IDP, D4, V2/V2.1, freshness schedule and Signals IDP activation still owner-held unless new decision |
| **Source/calibration/model learning:** weekly and dynasty separation, independent holdouts, off/IDP ROS comparability, no double counting, champion vs challenger | `docs/owner/NEXT_CYCLE_IDP_CALIBRATION_DIRECTIVE_2026-10-28.md`, `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md` RIT-035…039, adaptive learning/spec governance | exact scorer + archived actuals + model registry → shadow evaluations → owner decision package | Some shadow infrastructure merged, activation and model promotion blocked pending evidence/decision |
| **League scoring, schedule, Power and pick intelligence:** accurate Sleeper league fingerprints, future draft slots from the **recorded actual league rule**, $1,200 per dynasty_main rookie draft-year dollar allocation, rollover | `docs/picks/DRAFT_ORDER_RULE.md`, `docs/EXECUTION_PLAN.md` 2026-10-17/18, RIT league-model/draft rows, Schedule Intelligence owner directive | league config/snapshots → exact scoring/lineup, valuation/pick/auction and projections → dashboards | Mix of live, partial and owner questions; `dynasty_new` excluded where owner said; **do not silently replace rule with Max PF** |
| **UX, evidence, privacy and operational completion:** PSI visual design, faster War Room, authenticated survival, deployment freshness, scheduled E2E, no secret exposure and source licensing | RIT-073/078 and RPA, NC-C/D/E, Oct 18–21 release directives; `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md` | every model/product lane → coherent Lane 6 UI + exact-head tests, independent review, production verification | Some Oct 25 production defects reported; **reverify current** evidence, do not assume old failing unit still broken |
| **Owner-only read-only ChatGPT MCP surface:** tools for rankings, identity, selected league, rosters and trade analysis; no chat API duplication | `docs/EXECUTION_PLAN.md` 2026-10-25, `docs/OWNER_REQUESTED_TODO.md` MCP entry, PR #1921 successor | reuse same identity, auth, provenance and private analytics owners, no write gateway | Initial scoped PR, no automatic publishing/credentials/merge/activation authority |
| **Paused or rejected** | Oct 18 DFS / League Tycoon pause and owner dispositions; RIT-085/086/088; product §6 | keep preservation/documentation of prior work, do not schedule workers | **PAUSED / PROPOSAL ONLY**, not implementation tasks |

**Audit truth note:** The 88-item RIT reconciliation is a **historical verified as-of 2026-10-25** classification, not proof of current production state. It includes 56 code/test verified, 3 merged-production-unverified, 9 dormant behind flags, 7 partial, 2 awaiting review, 4 dependency blocked, 2 paused, 1 superseded, 2 broken, 1 unverifiable and 1 unstarted proposal. The actual detailed per-ID source-to-code-to-status map remains in that record; **do not recopy 88 descriptions into multiple conflicting roadmaps**. Recoverable conversation evidence and dated directives extend the review to Oct 9–30, but the entire original chat corpus for Oct 9–10 was not independently replayed. Unknown missing conversation evidence remains a gap, never an assertion that no other ideas existed.

## 12.3 Dependency graph and shared foundations

```text
       Source rights + identity + provenance + point-in-time archival
                         |
            League-config identity / exact scoring
                         |
     +-------------------+----------------------+
     |                   |                      |
 Canonical market    Weekly/ROS projections   Realized actuals + as-of rosters
 value & picks       (offense + IDP)          and transaction ledger
     |                   |                      |
     +-------------------+----------------------+
                         |
       EXACT global legal lineup / availability / FLEX solver
                         |
         Replacement, roster marginal utility, insurance
                         |
     +---------------+-------------+---------------+
     |               |             |               |
  Trade &          Waiver/FAAB    Draft/auction   Team window/
  market analysis  IDP streaming  & pick assets   future portfolio
     +---------------+-------------+---------------+
                         |
             Single aligned private decision outputs
                         |
     Roster Construction / Trade Desk / Waiver UI / Next Move
                         |
              independent acceptance + release gates
```

**Contract rules:** market value ≠ weekly expected points ≠ roster-conditional marginal utility ≠ public fairness ≠ playoff/title odds. They may be presented side-by-side but must not be averaged or counted as independent votes when they share inputs. Reuse existing owners, never establish a parallel scoring, valuation, trade-decision, lineup, waiver or provenance engine. Optional chart, coaching, or podcast insights may consume results; they do not own calculations. Preserve the existing `dynasty_main` draft-order rule, all actual league scoring settings and private/public boundaries.

## 12.4 Coordinated multi-agent execution, only after checking authorization

1. **Evidence / current-state pass (small coordinator unit):** pull latest main, check open PRs, claims, approved/held flags, source freshness, tests and released versions. Mark each row `CODE_PRESENT`, `MERGED`, `FLAG_OFF`, `PROD_VERIFIED`, `PARTIAL`, `BLOCKED`, `RESEARCH`, `PAUSED` or `UNKNOWN`; keep code and UX statuses separate.
2. **One shared contract-owner lane (SERIAL):** canonical schema/league identity, exact scoring, historical attribution, lineup and player-identity interoperability. Freeze versioned input/output contracts; other agents may write consumers against those contracts but cannot redefine the underlying semantics or edit the same files concurrently.
3. **Parallel independent research lanes (SAFE):** (A) position-specific RB/WR/TE/QB/IDP opportunity and weekly projection backtests; (B) transaction/market/as-of trade-history evidence; (C) dynasty/age/availability/model-calibration challengers; (D) pick/draft/auction/FAAB market analysis. Each has isolated outputs and no automatic live influence. Existing IST W1/W2/W3 and NC/IDPM claims win over new assignments; do not duplicate them.
4. **Parallel presentation lane (SAFE when contract-stable):** PSI-consistent private Roster Construction diagnostics and readable Trade/Waiver cards using server-provided results. Mock contract fixtures may support early UI work; route wiring happens only once the relevant backend contract is verified. Keep accessibility, mobile and WebKit parity.
5. **Decision integration lane (SERIAL at shared owners):** integrate *independent evidence* through existing one Trade verdict owner, exact before/after simulation, one waiver optimizer and competitive posture; preserve legal moves, dynasty locks, budget, 2–4 team trade support, no-action and public fairness-only boundary.
6. **Independent validation / Integration Authority:** controlled synthetic cases first, chronological historical holdouts, exact scoring parity and user-facing league examples, L0/L1 in worker branches, L2 at integration, L3 at release, role-qualified independent review, version/flags/provenance, rollback and staged production checks. Routine reviewed/green **authorized** PRs follow existing standing integration policy. Owner-only activation, spending, security, model/source promotion, product-scope changes and paused areas are **not** auto-approved.

A missing dependency blocks only the affected unit; reassign independent workers to other ready components. A plan does not assign extra resources, override `docs/WORK_CLAIMS.md`, edit open workstreams, or authorize implementation. Every coherent wave produces exactly one shared foundation and *consumers* of it, not multiple competing substitutes.

## 12.5 Agent-ready feature-definition and zero-loss guarantee

The mandatory input template, status machine, reconciliation / dedup procedure and 3-lane evidence test are in `docs/BRISKET_IDEAS.md` §§15–16. For exact product-level behavior and negative acceptance examples, use `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §§21–22 and subordinate owner specs. A new owner idea must be **logged in the live intake ledger AND resolved to one detailed canonical specification** in the same capture; if the exact behavior remains ambiguous, record `SPEC_GAP` and keep it owner-review pending. An idea is never “done” because someone mentioned it in chat, wrote a single descriptive line, or produced code that has not been acceptance-verified.

