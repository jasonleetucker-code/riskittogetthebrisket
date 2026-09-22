# Chase Upside — Canonical Weekly Power Rankings

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** OWNER-APPROVED ROADMAP FEATURE / CONSOLIDATION  
**Owner direction captured:** 2026-08-12  
**Product family:** Public League Experience + Upside Report + ROS Intelligence + Awards/History  
**Implementation status:** Canonical implementation active in `src/ros/power_v2.py` (2026-09-08 branch/PR #1295). The legacy `src/public_league/power.py` engine is retired. `results_only` remains a diagnostic lens inside the same engine; the old `forward_looking` query value is compatibility-only and resolves to the canonical blend. Official weekly history is owned by `src/ros/power_snapshots.py`. **2026-09-16 (owner directive):** the `/league` Power page serves ONE ranking — the lens toggle, the diagnostic week selector and the results-only trend chart are removed from the page (§10), and the rank-history chart reads the official publications. Owner-attested baseline weeks and the single sanctioned movement restatement are defined in §9. **2026-09-22 (owner directive): the forward/results blend is REBALANCED** — the prior 0.40/0.60 target and 4-game evidence time constant gave ROS strength too much influence relative to demonstrated performance, especially early in the season (measured: at 2 games played the blend split ~63% forward / ~37% results, the inverse of the owner's stated ~60-65% demonstrated / ~35-40% forward target for that point in the season). New target 0.30/0.70, evidence tau 4→2 games, `all_play` raised 0.20→0.30 (tied with `team_ros_strength` for the largest individual weight), and a new within-bucket discount stops `recent` claiming separate credit for evidence `all_play` already prices in while its trailing window is still the entire season-to-date sample. Full rationale, real-board validation and the exact new curve: §5, §7.1, and `src/ros/power_v2.py`'s module docstring.

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

**REBALANCED 2026-09-22 (owner directive).** The original 0.40/0.20/0.15/0.15/0.10 vector gave forward-looking ROS strength too much influence relative to demonstrated performance — measured on the live board, at 2 games played the blend split ~63% forward / ~37% results, the inverse of the owner's stated philosophy that demonstrated performance should carry roughly 60-65% of the weight at that point in the season. This is a full replacement of the target vector below, not a tuning pass on top of it; §12's validation is satisfied by the real-board comparison and sensitivity check recorded in the PR that made this change (`docs/WORK_CLAIMS.md`), not the full historical rolling-origin backtest — that remains valuable future work, named explicitly rather than silently skipped.

### A. 30% — Forward-Looking ROS Competitive Strength

*(was 40%)*

Use the canonical ROS/current-season projection layer and exact league scoring to produce schedule-neutral projected weekly score distributions for the roster's canonical best-ball lineup.

Preferred derived metric: expected all-play win rate / neutral-opponent win probability over the near-term ROS horizon.

This naturally incorporates current player quality, role/projections, availability and best-ball depth. If injuries/availability already alter the ROS distribution, do **not** add a second standalone health penalty.

Tied with all-play (below) as the largest individual weight — no single results component may outweigh the comprehensive roster projection on its own; the shift toward demonstrated performance comes from the AGGREGATE results bucket (four components) outweighing this one forward-looking input, not from any one results signal individually exceeding it.

### B. 30% — Season-to-Date All-Play Performance

*(was 20%)*

Cumulative schedule-independent performance against every league team each scored week.

This prevents an easy/hard H2H schedule from dominating the ranking and rewards teams that consistently score well enough to beat most of the league.

Use current-season only.

Raised to the largest results weight because it is the one genuinely schedule-independent, season-long measure of scoring quality this formula has. §6 explains why a separate raw-PPG weight was rejected in favor of raising this one instead — they are correlated because both derive from the same weekly scoring, and weighting both would double-count it.

### C. 15% — Recent Form

*(absolute weight unchanged; see the redundancy correction below)*

Use a rolling **last four scored weeks** when available, preferably exponentially weighted so the latest week matters somewhat more without allowing one spike week to dominate.

Preferred input is recent all-play performance and/or standardized weekly scoring relative to that week's league scoring environment.

Do not make a separate "winning streak" score unless historical validation proves incremental predictive value beyond recent form and actual record.

**Redundancy correction (2026-09-22).** While `games_played <= 4` (the recent-form window), the trailing buffer IS the entire season-to-date sample — not a subset of it — so it carries no distinct information beyond what All-Play (B) already prices from the same games, and contributes no weight of its own until the window genuinely diverges from the full season past week 4. See `src/ros/power_v2.py::_recent_distinctness`. This is a reallocation *within* the results bucket only; it does not change the forward/results split in §7.

### D. 15% — Team Realized Lineup VORP / PAR

Yes, there is a useful team-level analogue of player VORP.

Consume the canonical replacement/PAR/VORP system and sum realized above-replacement production from the team's actual canonical best-ball lineup assignments across the current season.

This measures how much meaningful weekly production the roster produced above league-specific replacement expectations rather than treating every raw point identically across positions.

Use the same replacement-level owner as Awards/Honors; do not create a Power-only VORP formula.

### E. 10% — Official Competitive Record

*(absolute weight unchanged; its share of the results bucket falls from 16.7% to 14.3% as the bucket grows around it — see below)*

Use the league's real official standings semantics. If league-median results are part of the official record, preserve those semantics exactly and avoid double counting them elsewhere.

Record receives meaningful but minority weight: wins matter, but schedule luck must not overwhelm evidence that a team is genuinely strong or weak. Held flat in absolute terms deliberately (2026-09-22) — record already has the built-in check against matchup luck that this whole model provides (all-play, above), so de-emphasis comes from growing the results bucket around it, not from cutting it directly.

### Initial candidate formula

`Power Index = 100 × (0.30 ROS + 0.30 Season All-Play + 0.15 Recent Form + 0.15 Team Realized VORP/PAR + 0.10 Official Record)`

*(was `0.40 ROS + 0.20 Season All-Play + 0.15 Recent Form + 0.15 Team Realized VORP/PAR + 0.10 Official Record`, until the 2026-09-22 rebalance.)*

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

`results_evidence = 1 - exp(-g / 2)`

**REBALANCED 2026-09-22.** The time constant was 4 games, matching the recent-form horizon — the two were coupled "by coincidence of sharing the same number," not because they answer the same question. They are now deliberately decoupled (`_RESULTS_EVIDENCE_TAU_GAMES` vs `_RECENT_WINDOW` in `src/ros/power_v2.py`): 2 games is how fast the forward/results MASS split shifts; 4 games remains how many trailing weeks count as recent form. In canonical mode the raw forward/results target budgets are 0.30 and 0.70 (was 0.40/0.60); the results budget is multiplied by `results_evidence`, then the surviving forward/results masses are renormalized to 100%.

With ROS available, that produces approximately:

| scored games | forward-looking | observed results |
|---:|---:|---:|
| 0 | 100.0% | 0.0% |
| 1 | 52.1% | 47.9% |
| 2 | 40.4% | 59.6% |
| 4 | 33.1% | 66.9% |
| 8 | 30.4% | 69.6% |
| 14 | 30.0% | 70.0% |

*(was 100.0/75.1/62.9/51.3/43.5/40.7% forward at g=0/1/2/4/8/14, floored at 40%, before the 2026-09-22 rebalance.)*

This makes even Week 1 already close to an even split rather than deliberately keeping results minor, and the g=2 point — the owner's own stated "this early point of the season" reference — lands at the boundary of their stated 60-65% demonstrated / 35-40% forward-looking target by construction of round, independently-explainable constants (0.30/0.70 target, tau=2), not by curve-fitting to hit that percentage exactly. It approaches the new 30/70 long-run blend smoothly, floored at 30% forward rather than 40%.

Missing inputs are unavailable, not zero. Missing result components are renormalized **inside the results bucket** so a missing result dependency cannot accidentally make the model more forward-looking than intended. Today the canonical weekly realized-lineup VORP/PAR owner is not dependency-ready; its 15% target share is therefore explicitly reported missing and redistributed among the legitimate observed-results components. The season-aggregate Awards approximation is not substituted.

Do not import prior-season PPG or back-fill historical ROS values merely to fill missing data.

### 7.1 `g` counts COMPLETED league weeks, and only those (PRIOR-A03-F03, closed 2026-09-19)

"Scored current-season games" above means weeks `metrics.final_regular_season_weeks`
returns, never every week with a nonzero score. An in-progress week must contribute to
`g` for nobody -- not for the observed-results components (`recent`, `all_play`,
`wl_record`), and not for the raw `pointsPerGame`/`recentAvg` diagnostics either.

The distinction was not academic. A week in progress has SOME rosters with a
Thursday-night partial score and others still at a literal `0.0` because nobody on
them has played yet. Filtering per roster-entry on "is this nonzero" (the pre-fix
behavior) counted the partial as a completed game for whoever had one and dropped the
week entirely for whoever did not -- so different owners' `g` diverged inside one
table, and `pointsPerGame` silently became `(week1 + thursday_partial) / 2` for some
rows while staying `week1 / 1` for others. Measured live, 2026-09-19: eight of twelve
rows in `dynasty_main` carried a denominator the other four did not.

`final_regular_season_weeks(season)` admits a week on either of two independent
proofs -- the host's own `settings.last_scored_leg` clock, or every roster in the week
reporting a real score at the league's full roster count -- because each closes the
other's failure mode: only the host clock can admit a week where a roster genuinely
scored `0.0`, and only data completeness can admit a finished week whose clock stamp
lags a refresh cycle. An in-progress week fails both. Every payload now stamps
`countedWeeks` (which weeks contributed) and each row's `gamesUsed` /
`recentGamesUsed`, so a denominator can never again diverge invisibly; `blend`
additionally carries `scoredGamesMax` and `scoredGamesDiverged` for the same reason.

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

Historical official snapshots never silently change when today's model/data changes.

### Owner-attested baseline weeks (2026-09-16)

A week whose publication was missed cannot be recomputed later: the ROS strength
that produced it has moved on, and back-dating today's value into that week is
forbidden above. What *is* recoverable is the ORDER the site displayed, when the
owner attests to it from the published card.

`power_snapshots.record_attested_snapshot` publishes exactly that, and nothing
more:

- rows carry rank, owner and team name. `powerScore` is `null`, every component
  is `null`, and `componentRanks` is empty — the attestation records where the
  teams stood, not what the engine scored them, and a missing score stays
  missing rather than being interpolated from a neighbouring week;
- `scoringConfigFingerprint` is `null`, because we did not run the scoring
  configuration and may not claim to know it;
- the snapshot is stamped `rankSource: "owner_attested_published_card"`.
  Engine publications are stamped `rankSource: "canonical_engine"`; a snapshot
  written before that field existed carries no key, and absent means engine;
- create-once applies unchanged — an attested week can never overwrite a
  published one;
- the hand-authored input lives in `config/power/attested/` and is applied by
  `scripts/publish_power_week_zero.py`, which resolves display names to owner
  ids against an already-published week and refuses any name that does not
  match exactly one owner.

Publishing a baseline changes what its SUCCESSOR can know about itself. A week
published while its predecessor was missing froze `priorRank`/`rankDelta` as
`null`, and that `null` stops being true the moment the predecessor exists.
`power_snapshots.restate_movement` is the only sanctioned edit to a published
week, and it is narrow by construction: movement is recomputed from the two
frozen snapshots alone, a `null` may become a number but a number may never
become a *different* number, every other field is compared key by key and the
write is refused if any of them would move, and the change is recorded in a
`restatements` audit entry rather than applied silently. Re-running is a no-op.

Applied once, to 2026: `dynasty_main` Week 0 was published from the owner's
screenshot on 2026-09-16 and Week 1's movement restated against it (Collin and
Ed up one, Jason and Ty down one, eight unchanged). `dynasty_new` has no
attested baseline, so its Week 1 card correctly reads NEW and its first real
movement arrives with Week 2.

The results-only chart may reconstruct retrospective results because those
inputs are historical; it is explicitly labeled diagnostic, never back-fills
today's ROS strength into past weeks, and since 2026-09-16 it is not rendered on
the Power page at all (see §10).

## 10. UI / UX

### One ranking on the page (owner directive, 2026-09-16)

The page serves the canonical ranking and nothing else. The `Canonical` /
`Results only` lens toggle, the week dropdown of `· diagnostic` results-only
reconstructions, and the results-only "Power score over time" chart are all
**removed from `/league` → Power**. Three orderings on one page is what made a
diagnostic read as a competing answer, and left the share card able to disagree
with the surface it sat on.

`lens=results_only` survives in the ENGINE as the analytical diagnostic §3
retains, reachable at `/api/public/league/rosPower?lens=results_only`. It is not
something the page offers.

The rank-history chart now reads `officialHistory` — the immutable weekly
publications for the current season, projected to `{week, preseason, rankSource,
ranking:[{ownerId, rank, powerScore}]}`. It plots RANK rather than Power Index,
because an attested baseline week carries an order and no score, and plotting
the score would silently drop the baseline off the chart. Fewer than two
published weeks renders an explicit "history begins once a second week is
published" state, never a one-point chart.

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

Two distinctions the card must preserve, because a screenshot carries no
tooltip:

- **"did not move" is not "nothing to compare with."** A row with a prior rank
  and a zero delta shows `—`; a row with no prior rank at all shows `NEW`. The
  test is per ROW, not per card, so a manager who joined after the baseline week
  reads NEW while everyone around them shows real arrows.
- **the card names the week the arrows are measured against** (`vs preseason`,
  `vs Week 3`), taken from the published history rather than inferred from the
  week number — a league whose baseline was never published must not claim one.

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
