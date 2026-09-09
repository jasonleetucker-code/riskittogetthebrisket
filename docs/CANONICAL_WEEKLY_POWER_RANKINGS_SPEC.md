# Chase Upside — Canonical Weekly Power Rankings

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** OWNER-APPROVED ROADMAP FEATURE / CONSOLIDATION  
**Owner direction captured:** 2026-08-12  
**Product family:** Public League Experience + Upside Report + ROS Intelligence + Awards/History  
**Implementation status:** Canonical implementation active in `src/ros/power_v2.py` (2026-09-08 branch/PR #1295). The legacy `src/public_league/power.py` engine is retired. `results_only` remains a diagnostic lens inside the same engine; the old `forward_looking` query value is compatibility-only and resolves to the canonical blend. Official weekly history is owned by `src/ros/power_snapshots.py`.

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

## 3. CANONICAL OWNER — ONE ENGINE, ONE LEAGUE-FACING ANSWER

The consolidation is complete: `src/ros/power_v2.py` is the only Power Ranking engine.

The public/default answer is `lens=canonical` and combines current forward-looking ROS strength with observed current-season performance. `lens=results_only` is retained only as an analytical diagnostic over the same observed components. The historical `forward_looking` query string is accepted as a compatibility alias and executes the canonical blend; it is not a second methodology.

The canonical implementation preserves the repairs this specification required:

- current-season power is not contaminated by career/cross-season PPG accumulation;
- all-play is season-to-date, not merely the latest week's share;
- future schedule is excluded from the Power score;
- standalone luck/streak/health terms are not independently weighted;
- PPG remains visible but is not a separate weighted core input;
- missing inputs remain missing and weights renormalize rather than becoming zero;
- exact-score ties use standard competition ranking (for example 1, 1, 3), with owner id used only for deterministic display order inside the tied rank.

## 4. TARGET VARIABLE — DEFINE ACCURACY BEFORE WEIGHTS

The model should be validated against a schedule-neutral future-performance target rather than tuned until rankings "look right."

Preferred validation target:

> **Near-term neutral-opponent competitive strength:** how well the team performs against the league as a whole over the next 1–3 scored weeks, measured primarily through future all-play outcomes / neutral-opponent win probability under the league's exact scoring and best-ball rules.

Backtesting should compare candidate rankings against future all-play performance and/or calibrated neutral-opponent win probability using rolling-origin, no-lookahead evaluation.

Do not tune against end-of-season standings or championships; that would incorrectly reward schedule/bracket luck and turn Power Rankings into a second Playoff Predictor.

---

## 5. INITIAL INTERPRETABLE CHAMPION CANDIDATE

The following is the current transparent canonical target vector. It originated as the owner-approved champion candidate and is now implemented as the production methodology. Future challengers may still be evaluated under §12, but they do not silently replace this version.

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

The implementation uses a smooth evidence curve rather than arbitrary week-number cliffs.

For `g` scored current-season games:

`results_evidence = 1 - exp(-g / 4)`

The four-game time constant matches the recent-form horizon. In canonical mode the raw forward/results target budgets are 0.40 and 0.60; the results budget is multiplied by `results_evidence`, then the surviving forward/results masses are renormalized to 100%.

With ROS available, that produces approximately:

| scored games | forward-looking | observed results |
|---:|---:|---:|
| 0 | 100.0% | 0.0% |
| 1 | 75.1% | 24.9% |
| 2 | 62.9% | 37.1% |
| 4 | 51.3% | 48.7% |
| 8 | 43.5% | 56.5% |
| 14 | 40.7% | 59.3% |

This makes Week 1 meaningful without letting one game dominate, and it approaches the intended 40/60 long-run blend smoothly.

Missing inputs are unavailable, not zero. Missing result components are renormalized **inside the results bucket** so a missing result dependency cannot accidentally make the model more forward-looking than intended. Today the canonical weekly realized-lineup VORP/PAR owner is not dependency-ready; its 15% target share is therefore explicitly reported missing and redistributed among the legitimate observed-results components. The season-aggregate Awards approximation is not substituted.

Do not import prior-season PPG or back-fill historical ROS values merely to fill missing data.

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

After every completed scored week, materialize one immutable/versioned official Power Ranking snapshot under the existing ROS refresh/persistence path.

Publication rules:

- a snapshot is eligible only after Sleeper's NFL clock has advanced beyond the scored week;
- the target week must contain a complete scored H2H matchup set for every current roster owner;
- only the immediately completed host week may be finalized — if publication was missed, today's ROS strength is **not** back-dated into an older week;
- publication is atomic and create-once; same-week recalculation cannot rewrite an official snapshot;
- snapshots are public-safe and never persist private player-value, lineup-depth, weakness, trade, or manager-intelligence decomposition;
- every snapshot carries `methodologyVersion`, `scoringConfigFingerprint`, `finalizedAt`, the blend/weight basis and the published ranking rows.

Movement always compares the current official ranking with **exactly Week N-1** from the same season:

`rankDelta = previousOfficialRank - currentRank`

Therefore rank 5 → rank 2 is `+3` / ▲3; rank 1 → rank 4 is `-3` / ▼3. Week 1 or a genuinely missing prior official snapshot has no fabricated delta.

For every team preserve the public-safe facts needed to reproduce the published weekly view: rank, Power Index, prior rank/delta, prior Power Index/delta, sanitized component values, official record, PPG/recent display facts, season all-play, public-safe ROS percentile, methodology version, scoring fingerprint and finalized timestamp.

Historical official snapshots never silently change when today's model/data changes. The results-only chart may reconstruct retrospective results because those inputs are historical; it is explicitly labeled diagnostic and never back-fills today's ROS strength into past weeks.

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
- the dedicated **League Power Rankings** share card shows all 12 teams in one phone-screenshot-first surface, limited to rank + team/owner + official week-to-week movement;
- the Interestingness Engine may elevate an unusual movement as a primary weekly story.

Example share treatment:

`1. MaKayla ▲2`
`2. Jason —`
`3. Roy ▼1`

The share card deliberately omits Power score, record, formulas, projections and explanatory analytics; those remain on the detailed Power page.

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
