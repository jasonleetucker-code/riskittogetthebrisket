# Chase Upside — The Upside Report Weekly Showcase

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** OWNER-APPROVED ROADMAP FEATURE  
**Owner direction captured:** 2026-08-12  
**Product family:** Public League Experience + weekly narratives + Game Day + Awards/Honors + Share Renderer  
**Implementation status:** Existing weekly-recap and per-matchup narrative foundations exist; this specification upgrades and unifies them into the canonical weekly league showpiece.

---

## 1. PRODUCT GOAL

Every completed fantasy week should automatically produce a polished, mobile-first **Upside Report** that answers a different question from Sleeper's ordinary recap:

> **What was actually interesting about this week in our league?**

The product is not a standings dump, a list of final scores, or six generic AI recaps stapled together. It is the weekly editorial/showcase layer for Chase Upside: the most notable performances, outcomes, transactions, historical oddities, probability changes and league narratives, backed by deterministic data and explained in an engaging fantasy-football voice.

The report should become something league members expect and want to open each week.

---

## 2. CANONICAL OUTPUTS

Each completed week should have four connected outputs:

1. **Share graphic / link-preview card** — a compact mobile-friendly teaser containing the week's strongest 5–7 highlights.
2. **Full Upside Report page** — the canonical mobile-first weekly report with richer facts, context, awards, league movement and links into deeper content.
3. **Individual matchup stories** — existing/future AI-generated matchup recaps remain separate long-form articles and are linked from the weekly report.
4. **Permanent archive** — every completed report remains available by season/week and eventually feeds a season yearbook / Wrapped product.

The graphic is the trailer; the webpage is the complete episode.

Suggested public URL family:

`/league/week/{season}/{week}`

The existing route may be evolved rather than duplicated if it remains the correct canonical owner.

---

## 3. BUILD ON EXISTING SYSTEMS — DO NOT CREATE DUPLICATES

The Upside Report must consume or extend existing canonical owners rather than create competing implementations for:

- completed weekly matchup data;
- existing weekly recap/superlative infrastructure;
- AI matchup narratives;
- exact league scoring;
- best-ball lineup assignment;
- canonical replacement level / PAR / VORP;
- Game Day and matchup probability history;
- Playoff Predictor;
- Awards/Honors races;
- transaction/acquisition history;
- franchise/rivalry/history records;
- Share Renderer;
- public/private semantic boundary.

**ONE CONCEPT, ONE CANONICAL OWNER.** The report is a presentation/storytelling consumer, not another scoring, award, playoff, market or roster engine.

---

## 4. THE INTERESTINGNESS ENGINE

The defining feature is a deterministic **Interestingness Engine**.

Do not hard-code a fixed grid of 15 weekly boxes that must always be filled. After each completed week, Chase Upside should generate a broad candidate set of factual observations and rank/select the ones genuinely worth presenting.

Candidate-interest scoring should consider dimensions such as:

- **rarity** — how unusual is this relative to league history/current season?
- **magnitude** — how large was the performance/change/margin?
- **consequence** — did it materially affect a matchup, playoff odds, seeding or record chase?
- **historical context** — franchise/league record, percentile, streak or rivalry significance;
- **novelty** — avoid repeating effectively the same fact every week;
- **human relevance** — would a league member reasonably find this worth opening or sharing?

Exact weighting is an implementation/model decision that should be validated against historical weeks rather than invented arbitrarily.

The engine should be capable of producing dozens of candidate facts and selecting roughly 5–8 primary stories for the public report/share surface.

**Critical rule:** if a category produced nothing meaningful, omit it. Do not manufacture a Waiver Move of the Week, Rookie of the Week, rivalry note or other superlative merely to fill space.

---

## 5. CANDIDATE WEEKLY STORIES / SUPERLATIVES

The candidate library should support, when data genuinely qualifies:

- Offensive Player of the Week;
- Defensive Player of the Week;
- Game Changer / Matchup Swing Player;
- Team of the Week;
- Waiver Move of the Week;
- GM Move of the Week / immediate acquisition impact;
- Game of the Week;
- Biggest Upset;
- Bad Beat;
- Escape Artist / lowest-quality score that still won;
- Would've Beaten Everyone Else / elite losing score;
- Carry Job;
- Total Team Effort / unusually balanced scoring;
- Position Room of the Week;
- IDP Wrecking Crew;
- Rookie of the Week when genuinely notable;
- Fantasy Moment of the Week tied to a real NFL event;
- Historical Oddity;
- League Record or Franchise Record;
- Streak Watch;
- Rivalry/Revenge note;
- Playoff Mover;
- Seeding Chaos;
- Clinched / Eliminated / Bye Race late in season;
- Monday Night Miracle / Heartbreak when timestamped Game Day probability history supports it;
- record chase / milestone movement;
- other future data-backed candidate types that pass the same deterministic-interest rules.

This is a candidate pool, not a requirement that every item appear every week.

---

## 6. WEEKLY OFFENSIVE / DEFENSIVE PLAYER OF THE WEEK

Do **not** make these raw-high-score awards. Sleeper already exposes raw scoring leaders and the point of Chase Upside is to add league-specific intelligence.

The preferred concept is **weekly value above a league-wide positional/replacement baseline under the league's exact scoring and lineup structure**.

Conceptually:

`Weekly Player Impact = actual weekly fantasy production − canonical weekly replacement expectation for the player's eligible position/slot context`

This should consume the canonical replacement/PAR/VORP owner. Do not create an awards-only replacement table.

Principles:

- evaluate offense and IDP separately for OPOW and DPOW;
- raw points remain visible as supporting context;
- winning the fantasy matchup is **not** an eligibility requirement;
- the player's manager's roster depth should not decide who was objectively the best player performance of the week;
- exact methodology should be validated against historical weeks and the eventual canonical PAR/VORP implementation.

If the canonical Awards/Honors owner ultimately exposes a directly reusable weekly Realized Lineup VORP calculation, the Upside Report should consume it rather than reproduce the formula.

---

## 7. GAME CHANGER — ROSTER-SPECIFIC MARGINAL IMPACT

Keep this concept distinct from Player of the Week.

For a roster-specific **Game Changer**, recompute the team's canonical best-ball result without the candidate player and solve the lineup again.

Conceptually:

`Marginal Lineup Impact = actual team score − optimal team score with that player removed`

This answers a different question:

> How much did this player actually matter to this manager's result?

Where factual, the report may say things such as:

- `+18.4 lineup points over the next-best alternative`;
- `matchup margin: 7.2`;
- **without this player, the manager loses**.

Do not use naïve `player points > margin` logic because best-ball replacement/displacement matters.

---

## 8. WAIVER MOVE OF THE WEEK

Winning the matchup is **not** required.

Eligibility should require a qualifying waiver/free-agent acquisition in the relevant acquisition window and meaningful subsequent contribution.

Primary evaluation should use actual roster impact / counted best-ball contribution, not merely the acquired player's raw points.

Useful context may include:

- acquisition date;
- FAAB cost when available;
- weekly fantasy points;
- marginal lineup impact;
- matchup margin;
- whether the move actually flipped the matchup result.

If it flipped the result, add a special **MATCHUP WINNER** designation. If no acquisition produced meaningful value, do not award the category that week.

---

## 9. GAME OF THE WEEK / OUTCOME STORIES

Game of the Week should not automatically mean the smallest margin.

Potential inputs include:

- closeness;
- combined scoring quality;
- pregame upset magnitude;
- live win-probability swings when archived;
- playoff/seeding consequence;
- rivalry significance;
- historical rarity;
- extraordinary individual performances.

Other outcome stories should remain analytically distinct:

- **Biggest Upset:** preferably lowest defensible pregame Chase Upside win probability that resulted in a win;
- **Bad Beat:** strong all-play/league-relative performance that lost because of opponent draw;
- **Escape Artist:** weak league-relative performance that nevertheless won;
- **Would've Beaten Everyone Else:** high-scoring loser whose score would have defeated nearly/all other teams.

Definitions require objective thresholds/sample rules; avoid subjective LLM classification.

---

## 10. REAL NFL EVENT → FANTASY CONSEQUENCE

Where the existing matchup-narrative/news pipeline can support the facts, surface concise connections between real NFL events and fantasy outcomes.

Example shape:

> A player's real NFL breakout produced X fantasy points / Y marginal lineup impact in a fantasy matchup decided by Z.

The LLM may explain the connection, but every underlying statistic, scoring result, margin and event supplied to it must come from verified structured data/provenance.

---

## 11. PLAYOFF / SEASON-PROGRESSION MODULES

The report should evolve with the season rather than show the same modules every week.

### Early season

Prioritize weekly performances, scoring environment, surprising results, acquisitions, franchise/history records and emerging trends. Avoid making a Week 1 playoff bracket the centerpiece.

### Midseason

Introduce meaningful playoff probability movement, contender separation, bye race and seeding changes when the canonical Playoff Predictor has enough information to be useful.

### Stretch run

Prominently support:

- Make Playoffs % movement;
- Earn Bye % movement where applicable;
- championship-probability movement where useful;
- current playoff bracket / projected first-round matchups;
- first team out;
- clinching/elimination scenarios;
- bye race;
- result-driven seeding chaos.

All percentages must consume the canonical Playoff Predictor and preserve the exact requested league's standings/postseason rules.

---

## 12. MVP RACE IN THE WEEKLY REPORT

The dedicated Awards/Honors experience remains the full source for all award races. The Upside Report should **not reproduce every award race every week**.

Owner-approved weekly treatment:

- include a compact **MVP Race / MVP Watch** module when it is editorially useful;
- typically show only the top 3 on the weekly report/share surface;
- expose current rank, player, franchise, canonical award metric/VORP, gap to leader and movement where supported;
- link to the full Awards/Honors page for the complete top five and every other award race;
- consume the canonical League MVP race/eligibility logic rather than calculate a second race;
- presentation movement/recent trend must not alter the underlying award formula.

The module is **adaptive rather than mandatory**. Early in the season it may be omitted or labeled `Early MVP Watch`; later in the regular season it becomes more prominent, especially after meaningful leaderboard movement. The Interestingness Engine may surface it more strongly when the lead changes, the gap collapses, a candidate becomes newly eligible/ineligible, or a historic pace develops.

This preserves the excitement of the MVP race without turning the weekly report into a duplicate Awards page.

---

## 13. FULL REPORT INFORMATION ARCHITECTURE

A strong default hierarchy:

1. **Hero / Week headline** — one dominant factual narrative.
2. **This Week in 30 Seconds** — 5–7 strongest selected facts for mobile scanning.
3. **Weekly player awards** — OPOW/DPOW when available.
4. **Game Changer / transaction impact / other standout selected story.**
5. **League movement** — playoff race, record chase, MVP watch or other season-state module selected adaptively.
6. **Around the League** — every matchup with score, one-liner and link to full AI matchup recap.
7. **More from the week** — lower-priority interesting facts, trades and historical notes.

Do not force every section to exist every week. The structure should feel consistent while the actual stories change.

---

## 14. SHARE GRAPHIC / LINK PREVIEW

Every report should generate a public-safe share asset through the canonical Share Renderer.

Design goals:

- optimized primarily for phone viewing and league chat;
- approximately 4:5/portrait-friendly rather than a screenshot of a desktop webpage;
- Chase Upside visual identity;
- Week/season clearly visible;
- one hero headline plus roughly 4–6 compact supporting facts;
- enough information to be useful without tapping;
- strong call-to-action/link into the full report;
- OpenGraph/social preview support where technically appropriate.

Do not expose private decision-intelligence fields through the share renderer.

---

## 15. MATCHUP STORIES

The weekly report is the league-level editorial layer. Existing/future AI matchup recaps remain the detailed game stories.

Each matchup row/card should be able to link to its long-form recap.

The AI matchup recap may use verified Sleeper/fantasy facts, NFL news/results and other approved inputs to explain why real football events mattered to the fantasy result.

Do not embed six full long-form stories directly into the top-level report.

---

## 16. ARCHIVE / YEARBOOK

Reports are permanent historical artifacts.

Suggested hierarchy:

`Upside Report → 2026 → Week 1 ... Week 14 → Playoffs → Championship`

When a season ends, its reports collapse into a season archive rather than disappearing.

Historical reports must remain temporally honest:

- preserve the week-end facts/models/values/probabilities that were actually available then where relevant;
- do not silently recompute old reports using today's playoff model, current dynasty values or future information;
- record generation/finalization timestamps and methodology versions for calculated modules.

The weekly archive should become a major input to the approved Season Yearbook / Dynasty Season Recap / Wrapped product.

Potential automatically derived season-review material includes weekly award leaders, biggest upset, best waiver acquisition, closest game, biggest blowout, highest losing score, worst bad beat, records, playoff journey and championship story.

---

## 17. FACT ENGINE VS AI WRITING

**AI writes the story; canonical systems establish the facts.**

Deterministic/canonical systems should calculate and preserve:

- scores;
- lineup assignments;
- replacement/PAR/VORP;
- margins;
- probability changes;
- transactions;
- acquisition impact;
- historical ranks/percentiles/records;
- award races;
- playoff movement;
- candidate-interest facts.

The LLM may select wording, explain context, connect verified facts and produce engaging narrative prose. It must not independently invent or calculate whether a performance was historically rare, whether a waiver claim flipped a matchup, or whether a playoff probability moved by a claimed amount.

Structured brief/provenance is the contract.

---

## 18. PUBLIC / PRIVATE BOUNDARY

**Primary posture: PUBLIC / SHAREABLE LEAGUE EXPERIENCE.**

Allowed public content includes completed scores, factual transactions, retrospective records, public-safe matchup narratives, realized production, approved Honors/award race output and public-safe playoff probabilities.

Do not leak private canonical values, trade recommendations, Manager Scout/Insider tendencies, private roster weaknesses, Pick Forecast decision intelligence, Sharp/private market intelligence or other War Room outputs merely because they could make an interesting story.

Every candidate fact must pass the semantic public/private classifier before publication/rendering.

---

## 19. PERFORMANCE / GENERATION ARCHITECTURE

The Upside Report must follow the global Chase Upside performance standard.

Expensive weekly computation and LLM generation happen **off the interactive request path** after a week is finalized/scored.

Preferred lifecycle:

`finalize weekly inputs → compute deterministic candidate facts → rank interestingness → generate/validate narrative → materialize immutable/versioned weekly artifact → render/share quickly`

The report request should read a compact materialized artifact rather than recomputing league history, playoff simulation, VORP and AI prose on click.

Valid last-known/finalized artifacts remain available even if later refresh/generation jobs fail.

---

## 20. VALIDATION / ACCEPTANCE

Before declaring the feature complete:

- replay multiple historical weeks with different shapes: blowout week, close-game week, quiet week, trade-heavy week, waiver-impact week, playoff-race week, postseason week;
- verify candidate facts against source data;
- prove omitted categories really omit rather than emit fake/zero awards;
- prove best-ball displacement for Game Changer/waiver impact;
- validate OPOW/DPOW against canonical replacement/VORP methodology;
- verify public/private filtering;
- verify old weekly artifacts do not drift when current models/data change;
- test mobile/report/share rendering;
- test share asset/OpenGraph behavior;
- prove report loads within the global performance budget from materialized data;
- audit AI text for factual grounding against the structured brief.

---

## 21. ROADMAP DECISION

**APPROVED — ADD TO TODO / PRODUCT ROADMAP.**

Treat this as an upgrade/unification of the existing weekly recap + matchup narrative + Public League Experience + Honors + Game Day + Share Renderer architecture, not as a disconnected new subsystem.

Suggested roadmap family: **Public League Experience v3 / Storytelling + Game Day + Share Renderer**, with canonical dependencies on realized-scoring correctness, replacement/PAR/VORP, playoff probabilities, award races and historical truth.
