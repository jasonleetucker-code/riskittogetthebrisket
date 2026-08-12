# Chase Upside — Canonical Weekly Power Rankings

**Status:** OWNER-APPROVED ROADMAP FEATURE / CONSOLIDATION  
**Owner direction captured:** 2026-08-12  
**Product family:** Public League Experience + Upside Report + ROS Intelligence + Awards/History  
**Implementation status:** Two existing power-ranking engines exist (`src/public_league/power.py` and `src/ros/power_v2.py`). Neither is the final canonical methodology. This specification defines the product target and requires eventual consolidation into one canonical owner.

---

## 1. PRODUCT QUESTION

The Chase Upside Power Rankings answer:

> **Which teams are actually strongest right now, independent of schedule luck, while still respecting what they have accomplished and what their current roster is likely to do next?**

This is not a standings table, points-scored sort, dynasty-roster-value ranking, or playoff-odds ranking.

A team with a bad record but excellent underlying performance may reasonably rank above its standings position, but a last-place team should not jump near the top merely because of one inflated scoring statistic. The model must balance forward-looking strength, demonstrated current-season performance, recent form, schedule-independent results, realized above-replacement production, and actual competitive record.

Power Rankings are objective/data-derived. No manual editor ranking or LLM opinion determines rank.

---

## 2. CONCEPTUAL FIREWALL

Keep these products distinct:

- **Team Strength:** dynasty roster/asset strength and construction.
- **Power Rankings:** current-season competitive strength — who is strongest *right now*.
- **Playoff Predictor:** probability of making playoffs/earning a bye/winning the title, which legitimately includes schedule, standings and bracket path.
- **Standings:** what has officially happened.

Do not let future schedule strength inflate a team's Power Ranking merely because that team has an easier path. Easier schedule belongs in playoff probability, not intrinsic team power.

Do not use dynasty market value as a major Power Ranking input. Young/pick-heavy rebuilding teams can have enormous dynasty value while being poor current-season fantasy teams.

---

## 3. EXISTING ENGINES — CONSOLIDATE, DO NOT ADD A THIRD PERMANENT ENGINE

Current repository evidence shows two competing approaches:

1. `src/public_league/power.py`: 50% season/career PPG percentile + 25% last-three scoring percentile + 25% all-play share.
2. `src/ros/power_v2.py`: ROS strength plus PPG, recent scoring, actual record, all-play, streak, future schedule, health and luck-regression components.

The final product must replace/retire the competing user-facing methodologies after validation rather than leave multiple unexplained "Power" rankings.

Specific issues to repair in canonicalization include:

- current-season power must not be contaminated by career/cross-season PPG accumulation;
- all-play must be an actual season/rolling measure, not merely the most recent week's all-play share while labeled more broadly;
- future schedule is excluded from the Power score;
- standalone luck/streak/health factors must not double-count information already represented by all-play, recent performance or current ROS projections;
- missing inputs renormalize honestly rather than becoming zero.

---

## 4. TARGET VARIABLE — DEFINE ACCURACY BEFORE WEIGHTS

The model should be validated against a schedule-neutral future-performance target rather than tuned until rankings "look right."

Preferred validation target:

> **Near-term neutral-opponent competitive strength:** how well the team performs against the league as a whole over the next 1–3 scored weeks, measured primarily through future all-play outcomes / neutral-opponent win probability under the league's exact scoring and best-ball rules.

Backtesting should compare candidate rankings against future all-play performance and/or calibrated neutral-opponent win probability using rolling-origin, no-lookahead evaluation.

Do not tune against end-of-season standings or championships; that would incorrectly reward schedule/bracket luck and turn Power Rankings into a second Playoff Predictor.

---

## 5. INITIAL INTERPRETABLE CHAMPION CANDIDATE

The following is the preferred **starting champion candidate**, not an immutable owner-mandated weight set. Replay historical weeks and validate nearby alternatives before inaugural finalization.

### A. 40% — Forward-Looking ROS Competitive Strength

Use the canonical ROS/current-season projection layer and exact league scoring to produce schedule-neutral projected weekly score distributions for the roster's canonical best-ball lineup.

Preferred derived metric: expected all-play win rate / neutral-opponent win probability over the near-term ROS horizon.

This naturally incorporates current player quality, role/projections, availability and best-ball depth. If injuries/availability already alter the ROS distribution, do **not** add a second standalone health penalty.

### B. 20% — Season-to-Date All-Play Performance

Cumulative schedule-independent performance against every league team each scored week.

This prevents an easy/hard H2H schedule from dominating the ranking and rewards teams that consistently score well enough to beat most of the league.

Use current-season only.

### C. 15% — Recent Form

Use a rolling **last four scored weeks** when available, preferably exponentially weighted so the latest week matters somewhat more without allowing one spike week to dominate.

Preferred input is recent all-play performance and/or standardized weekly scoring relative to that week's league scoring environment.

Do not make a separate "winning streak" score unless historical validation proves incremental predictive value beyond recent form and actual record.

### D. 15% — Team Realized Lineup VORP / PAR

Yes, there is a useful team-level analogue of player VORP.

Consume the canonical replacement/PAR/VORP system and sum realized above-replacement production from the team's actual canonical best-ball lineup assignments across the current season.

This measures how much meaningful weekly production the roster produced above league-specific replacement expectations rather than treating every raw point identically across positions.

Use the same replacement-level owner as Awards/Honors; do not create a Power-only VORP formula.

### E. 10% — Official Competitive Record

Use the league's real official standings semantics. If league-median results are part of the official record, preserve those semantics exactly and avoid double counting them elsewhere.

Record receives meaningful but minority weight: wins matter, but schedule luck must not overwhelm evidence that a team is genuinely strong or weak.

### Initial candidate formula

`Power Index = 100 × (0.40 ROS + 0.20 Season All-Play + 0.15 Recent Form + 0.15 Team Realized VORP/PAR + 0.10 Official Record)`

Each input must be normalized/calibrated to a comparable league-relative scale before combination.

Again: this is the initial transparent champion to backtest, not permission to hard-code arbitrary weights forever.

---

## 6. WHY RAW PPG IS NOT A SEPARATE HEAVY INPUT

Points per game, total points and rolling points should be prominently displayed because they are intuitive and useful.

However, season all-play, recent form and team realized VORP/PAR are all strongly derived from scoring production. Adding a large independent PPG weight can count the same information multiple times.

Treat season PPG / recent PPG as:

- visible explanatory statistics;
- candidate challenger inputs;
- possible small incremental model inputs **only if historical out-of-sample testing proves they add predictive information after the core components**.

Do not add them simply because they are familiar.

---

## 7. EARLY-SEASON / MISSING-DATA BEHAVIOR

Preseason and early weeks require evidence-aware handling.

- Before games are played, rankings may rely almost entirely on forward-looking ROS competitive strength and should show lower confidence.
- Missing observed components are unavailable, not zero; available weights renormalize.
- Early season all-play/record/recent metrics should be shrunk toward league average or otherwise sample-size adjusted so Week 1 does not create false certainty.
- As current-season evidence accumulates, observed-performance components naturally gain reliability.

Do not import prior-season raw PPG into the current-season ranking simply to fill missing weeks.

---

## 8. WHAT SHOULD NOT ENTER THE CORE POWER SCORE BY DEFAULT

Exclude unless future evidence demonstrates incremental predictive value:

- dynasty roster market value;
- future schedule ease/difficulty;
- playoff probability;
- draft-pick capital;
- trade activity itself;
- subjective AI/editor opinion;
- standalone luck score when all-play already captures schedule luck;
- standalone winning/losing streak when recent form already captures current performance;
- standalone health penalty when current projections/ROS distributions already incorporate availability.

These may be displayed as context without changing rank.

---

## 9. WEEKLY SNAPSHOT / MOVEMENT

After every completed scored week, materialize an immutable/versioned Power Ranking snapshot.

For every team preserve:

- rank;
- Power Index;
- prior-week rank;
- rank delta;
- prior-week Power Index;
- index delta;
- component values;
- official record;
- season PPG;
- recent-four scoring/all-play;
- season all-play record/share;
- ROS neutral-opponent strength;
- Team Realized Lineup VORP/PAR;
- input coverage/confidence;
- methodology version;
- scoring-config fingerprint;
- finalized timestamp.

Historical weekly rankings must not silently change when today's model/data changes. If methodology is intentionally revised, preserve versioned historical output or clearly distinguish reconstructed rankings from originally published rankings.

---

## 10. UI / UX

### Dedicated Power Rankings page

Show all league teams with a compact, highly scannable table/list:

`Rank | Δ | Team | Power | Record | All-Play | Last 4 | ROS Strength | Team VORP/PAR`

Movement presentation:

- green upward arrow + number of positions gained;
- red downward arrow + number of positions lost;
- neutral marker for unchanged;
- optionally show Power Index delta separately from rank delta.

Each team should expose a concise **Why this rank** explanation using deterministic components, e.g.:

> `#2 ROS strength · #1 last-4 all-play · 4-3 record is the main drag.`

Do not let the LLM invent the explanation.

Useful secondary features:

- rank-history chart across the season;
- Power Index history;
- biggest riser / biggest faller;
- weeks spent at #1;
- component breakdown on tap/click;
- methodology explainer.

### Weekly Upside Report integration

The Upside Report should include the new weekly Power Rankings as a recurring league-state module.

Preferred treatment:

- full report may show the complete 12-team ranking because the league is small enough to scan;
- emphasize movement since last week;
- highlight **Biggest Riser**, **Biggest Faller**, and a new #1 when applicable;
- share graphic usually shows only the top 3–5 and/or the most interesting movement rather than squeezing all teams onto the image;
- the Interestingness Engine may elevate an unusual movement as a primary weekly story.

Example:

`1. Michaela 84.6 —`
`2. Jason 81.3 ▲2`
`3. Roy 77.9 ▼1`

A major movement should have a factual reason such as a huge recent all-play week, injury-driven ROS change, or several weeks of sustained above-replacement production.

---

## 11. PUBLIC / PRIVATE POSTURE

**PUBLIC / SHAREABLE**, using only public-safe competitive outputs.

Expose the ranking, sanitized components, records, scoring/all-play context, public-safe ROS competition strength and realized production context.

Do not expose private dynasty values, internal trade recommendations, Team Weakness details, Manager Scout/Insider intelligence, Sharp intelligence or proprietary decision recommendations through the public ranking.

The public methodology may explain conceptual component families without exposing sensitive private decision internals.

---

## 12. VALIDATION / MODEL GOVERNANCE

Before promoting the canonical formula:

1. Replay every reconstructable historical regular-season week, especially 2024/2025 and available 2026 data.
2. Compare against simple baselines: official record, PPG, season all-play, existing v1, existing ROS v2.
3. Use rolling-origin/no-lookahead evaluation.
4. Primary accuracy tests should include rank correlation with next-week / next-3-week all-play performance and, if probability output is modeled, Brier/log-loss/calibration for neutral-opponent outcomes.
5. Measure sensitivity to nearby weight choices and avoid a fragile formula where tiny weight changes radically reorder teams.
6. Inspect early-season behavior separately from mid/late-season behavior.
7. Confirm injuries/projection changes enter exactly once.
8. Confirm schedule does not leak into Power score.
9. Confirm current-season metrics contain no prior-season/career contamination.
10. Archive champion/challenger versions and require owner approval before production promotion.

A future learned challenger (regularized regression, Bayesian model, gradient boosting, etc.) may be evaluated against the transparent champion, but it does not silently replace the production formula merely because it scores better in-sample.

---

## 13. RELATIONSHIP TO UPSIDE REPORT / AWARDS / HISTORY

Power Rankings feed:

- weekly Upside Report;
- public League hub;
- Game Day context;
- historical league archive;
- season yearbook / Wrapped facts such as peak rank, weeks at #1, biggest rise/fall.

Power Rankings do **not** determine league awards by default. Awards consume their own approved canonical methodology. A Power Ranking may be narrative context for an award race but must not become an unapproved hidden award input.

---

## 14. ROADMAP DECISION

**APPROVED — ADD TO TODO / PRODUCT ROADMAP.**

Treat this as **canonical consolidation/upgrade of the existing Power Ranking implementations**, not a third permanent ranking engine.

Implementation should occur only after the canonical scoring/league-config/ROS/replacement dependencies needed for trustworthy inputs are ready. Until then, preserve this specification and do not opportunistically rewrite the current engines during unrelated work.
