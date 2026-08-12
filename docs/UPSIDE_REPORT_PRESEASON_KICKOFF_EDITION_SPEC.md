# Chase Upside — Upside Report Preseason / Kickoff Edition

**Status:** OWNER-APPROVED UPSIDE REPORT ADDENDUM  
**Owner direction captured:** 2026-08-12  
**Canonical parent:** `docs/UPSIDE_REPORT_WEEKLY_SHOWCASE_SPEC.md`  
**Product family:** Public League Experience + Upside Report + Power Rankings + Awards/Honors + Game Day + Share Renderer  
**Implementation status:** Planned. This is a special edition of The Upside Report, not a separate product or duplicate engine.

---

## 1. OWNER REQUIREMENT

Chase Upside must publish a polished **Preseason / Kickoff Edition of The Upside Report on the Tuesday before Week 1** (or the equivalent last practical pre-Week-1 publishing window if the host season calendar requires adjustment).

The league should not have to wait for one completed fantasy week before The Upside Report becomes useful.

This edition should combine:

- preseason / season-opening league intelligence;
- Week 1 outlook and matchup predictions;
- objective preseason Power Rankings;
- selective awards forecasts, especially an MVP forecast/watch;
- offseason and roster-change storylines;
- other deterministic, public-safe observations that are genuinely interesting before games have been played.

Its purpose is to build league excitement, establish a documented preseason baseline, and create a set of predictions that will be fun to revisit after the season.

---

## 2. THIS IS NOT THE WEEK 1 POSTGAME REPORT

The archive must contain **both**:

1. **Kickoff Edition / Preseason Report** — published before Week 1 begins; and
2. **Week 1 Upside Report** — published after Week 1 is finalized, using the normal post-week Interestingness Engine and weekly award logic.

The preseason report must never be overwritten by the Week 1 postgame report.

Suggested archive shape:

`Upside Report → 2026 → Kickoff Edition → Week 1 → Week 2 ... → Playoffs → Championship`

The Kickoff Edition becomes the immutable preseason baseline used for later movement and prediction-retrospective features.

---

## 3. CORE PRESEASON MODULES

The exact composition should remain adaptive, but the default Kickoff Edition should strongly consider the following.

### A. Preseason / Week 1 Power Rankings

Publish all league teams in the canonical Weekly Power Rankings order as the **Preseason Power Rankings / Week 1 entering rankings**.

This is the baseline against which Week 1's completed-report rank movement is measured.

Do not show fake up/down arrows before a prior snapshot exists. Label every team as establishing its preseason baseline; after Week 1, normal movement can be calculated against it.

The preseason Power model must obey `MISSING IS NEVER ZERO`:

- no actual record yet does not mean a zero record component;
- no season all-play sample does not mean zero all-play quality;
- no realized weekly VORP/PAR does not mean zero team quality.

The canonical Power owner should use an explicitly preseason-capable composition, priors/shrinkage, or available forward-looking inputs rather than forcing unavailable in-season components into zero-valued placeholders. Preserve model/version/confidence metadata.

### B. MVP Forecast / Preseason MVP Watch

Include a compact **Preseason MVP Forecast** when the canonical Awards/Honors and projection systems can support it defensibly.

This is a forecast, **not the official in-season MVP standings**. Before games are played, actual MVP eligibility requirements such as playoff position and winning record cannot yet be satisfied.

Preferred presentation:

- Top 3 likely MVP candidates;
- projected/forecast basis such as expected realized-lineup VORP or the eventual canonical award forecast signal;
- team context where relevant;
- confidence / uncertainty;
- concise reason the player enters the season as a candidate.

Do not manufacture exact award probabilities until the forecasting methodology is validated. A ranked preseason watchlist is preferable to fake precision.

Other award forecasts may appear only when they add real value. The Kickoff Edition should not duplicate the full Awards page.

### C. Week 1 Matchup Outlook

If the canonical Game Day / projection system is ready and the Week 1 schedule is known, include public-safe Week 1 outlooks such as:

- Win Matchup %;
- Beat League Median % when enabled;
- Game to Watch;
- closest projected matchup;
- upset watch where evidence supports it;
- highest projected combined-scoring matchup;
- one concise deterministic storyline per matchup.

These are pregame forecasts and must be archived with their model/version/timestamp so later evaluation is honest.

### D. Offseason / Opening-Day Storylines

Generate candidate public-safe preseason stories from structured evidence, potentially including:

- biggest offseason roster improvement;
- biggest offseason roster decline;
- most consequential trade/acquisition since the prior season ended;
- strongest projected position room;
- most balanced roster;
- roster with the widest credible range of outcomes / most uncertainty;
- rookie or new-acquisition impact watch;
- franchise attempting to extend or break a historical streak;
- rivalry or rematch context for Week 1;
- notable roster construction differences;
- league-wide scoring/projection environment;
- other historically or analytically interesting season-opening facts.

Do not force any category when the supporting data is weak.

### E. Season Storylines / Things to Watch

Use deterministic candidate facts to select roughly 3–5 genuinely interesting season-long questions.

Examples of the *shape* of a storyline:

- Can last year's dominant team remain the league's strongest roster?
- Is a major offseason rebuild already projected to move into the top half?
- Is an elite player entering the season on a historically strong MVP/VORP projection?
- Is a franchise entering Week 1 with a meaningful rivalry or multi-season streak on the line?

The LLM may make these readable and fun, but the underlying claim must come from structured evidence.

---

## 4. OPTIONAL PREDICTION LEDGER / "RECEIPTS"

A major reason to preserve the Kickoff Edition is to make the season retrospective more fun.

Where Chase Upside publishes explicit preseason forecasts, preserve them in a structured **Prediction Ledger** with:

- prediction ID/type;
- subject/team/player;
- exact statement or machine-readable outcome definition;
- probability/rank/forecast value if one legitimately exists;
- model/version/input snapshot;
- publication timestamp;
- later resolved outcome;
- correct/incorrect/partial/unresolved classification where appropriate.

Potential preseason predictions include:

- Power Ranking order;
- MVP forecast leaders;
- Week 1 matchup probabilities;
- selected data-backed season storylines;
- other explicitly labeled forecasts.

At season end, The Upside Report / Yearbook may include a **Preseason Receipts** section showing what Chase Upside got right, what it missed, and where uncertainty was appropriately high.

Do not retroactively rewrite the preseason prediction after new information arrives.

---

## 5. WHAT NOT TO DO

The Kickoff Edition should not become a generic fantasy-magazine prediction dump.

Avoid:

- a mandatory champion pick merely for entertainment;
- presenting Power Ranking #1 as a championship prediction;
- fake precision from tiny/no in-season samples;
- zero-filling unavailable actual-season metrics;
- official MVP-race language before actual eligibility/performance exists;
- duplicated Power, Awards, Game Day or projection formulas;
- a full standings table when there are no standings yet;
- arbitrary hot takes generated by the LLM without structured support;
- private roster/trade/Sharp/Insider decision intelligence on a public report.

A champion forecast may exist elsewhere in the product if later owner-approved and methodologically justified, but it is **not required for the Kickoff Edition**.

---

## 6. PUBLICATION TIMING / INPUT FREEZE

Target publication is **Tuesday before Week 1**.

The generation job should run after the latest practical preseason roster/projection/news refresh while leaving enough time for validation and sharing before the first NFL game.

Materialize an immutable/versioned Kickoff Edition from a pinned input snapshot including, where relevant:

- league rosters;
- Week 1 schedule;
- exact scoring and lineup configuration;
- canonical player identity;
- current ROS/current-season projections;
- preseason Power inputs;
- approved Awards forecast inputs;
- offseason transaction history;
- public-safe historical league context;
- current injury/availability inputs where canonically supported;
- model/methodology versions and source timestamps.

Later roster/news changes may justify a clearly labeled correction or refreshed pre-kickoff version only under an explicit versioning policy; never silently mutate the historical artifact after games begin.

---

## 7. SHARE EXPERIENCE

The Kickoff Edition should receive the same mobile-first webpage + share graphic treatment as normal Upside Reports.

A strong preseason share card might contain:

- `THE UPSIDE REPORT — KICKOFF EDITION`;
- Top 3 preseason Power Rankings;
- preseason MVP favorite/watch leader;
- Week 1 Game to Watch;
- 1–2 strong season-opening storylines;
- link/CTA to the full report.

The full report may show all 12 Power Rankings and all Week 1 matchup outlooks without overcrowding the teaser graphic.

---

## 8. FACT ENGINE VS AI

The same rule as every Upside Report applies:

> **AI writes the story; canonical systems establish the facts and forecasts.**

Power order, projected outcomes, roster changes, award forecast inputs, matchup probabilities and historical facts must come from canonical structured systems.

The LLM may synthesize the opening narrative, explain why a matchup is compelling, or phrase the season storylines. It must not invent rankings, probabilities, transactions, projections or historical claims.

---

## 9. YEAR-END RETROSPECTIVE CONNECTION

The Kickoff Edition should be explicitly revisited in the season-ending Yearbook / Wrapped experience.

Useful retrospective questions include:

- How much did each team move from preseason Power Rank to final competitive strength?
- Which preseason MVP candidates remained in the race?
- Which team most exceeded preseason expectations?
- Which team most underperformed them?
- Which Week 1 predictions were correct?
- Which preseason storylines became real season-defining narratives?
- What did Chase Upside get wrong?

The goal is not to pretend the forecasts were perfect; preserving the misses is part of what makes the archive credible and fun.

---

## 10. ACCEPTANCE / ROADMAP RULE

The Upside Report feature is not complete unless it supports a **pre-Week-1 Kickoff Edition** in addition to completed-week reports.

Acceptance should verify:

- a Kickoff Edition can be generated with zero completed games;
- unavailable in-season metrics remain missing rather than zero;
- preseason Power Rankings use the canonical Power owner and establish the Week 1 movement baseline;
- MVP forecast is clearly separated from official MVP standings/eligibility;
- Week 1 probabilities consume canonical Game Day logic where available;
- preseason artifact is immutable/versioned and archived separately from Week 1 postgame;
- share asset works on mobile;
- year-end retrospective can resolve stored preseason predictions without lookahead contamination;
- report loads from materialized data within the global performance standard.

**APPROVED — REQUIRED PART OF THE UPSIDE REPORT ROADMAP.**