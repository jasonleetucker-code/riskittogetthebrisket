# Site-Wide Decision Intelligence Audit — Risk It To Get The Brisket

**Read-only audit.** No repository file was modified, created, deleted, committed or pushed
*during* the audit. Work was `git log`, file reads, and arithmetic reproductions in a scratch
directory outside the repository. This report and its companion registry were committed
afterwards, as documentation only — **no code path was changed, and all 173 Critical/High
findings below remain open.**

**Commit audited: `9c5d972f51a55d435030a56e76f023bf5eb9d1c7`** (branch
`claude/decision-intelligence-audit-wif47g`, working tree clean, 2026-08-04).

---

## Context

The operator asked for a complete, independent audit of every calculated output a user could
rely on to make a fantasy-football decision, to determine which numbers deserve to influence
real decisions and which merely look authoritative. Deliverable: this audit plus a remediation
plan, to be converted into a separate implementation prompt.

---

## 1. Executive Summary

| | Count |
|---|---|
| Decision-support systems inventoried | **807** (all 26 subsystem audits complete) |
| Formulas / models documented | **562** |
| Findings | **531** — **43 Critical, 130 High**, 201 Medium, 147 Low, 10 Informational |
| Largest root-cause category | **documentation mismatch (56)**, then weak methodology (33), incorrect math (29), missing data (25), runtime disconnect (24), missing validation (24) |
| System operational status | ~500 active+connected · ~110 partially connected · **broken/dormant/deprecated/mock ~80** · ~35 not verifiable |
| Safe as a primary decision tool | **1** — the raw retail market values themselves |
| Should not currently drive decisions | **~25 named systems** |

### Is the analytical architecture coherent?

**No — not at the decision layer.** There is a genuinely well-built spine: one canonical value
(`rankDerivedValue`), one blend path, a correctly-reasoned scoring-profile/league-key split,
a real and largely-held rule against a frontend ranking engine, and pockets of exemplary work
(`feature_flags._GATE_STATUS`, `sim_calibration.py`, BDVM's structural market isolation).

Around that spine the decision layer has grown without an authority model. **Four independent
BUY/SELL label families** run on the same players with four different threshold sets and no
reconciliation — two of them send email. **Three team-phase classifiers.** **Four
replacement-level implementations.** **Two playoff-odds engines and two power-ranking engines**,
switched by a user setting. The same player can read BUY on `/rankings`, SELL on `/bdvm`, and
HOLD in the Signals panel simultaneously, and nothing names which concept produced which verb.

### The seven systemic problems

1. **No output on this platform has been validated for accuracy.** Every tuned constant in the
   core blend was selected against a *stability* metric (day-to-day board churn). The repo's own
   α report says the metric "rewards stability… the optimum drifts toward using the anchor
   source alone… That's product-bad." Sharp Score has no backtest, holdout or calibration of any
   kind. BDVM's params are explicitly labelled unvalidated priors. **This caps confidence for
   nearly every derived output at ≤69.**

2. **The benchmark that grades the core curves is not independent of them.** All four
   "held-out" boards (FantasyCalc, OTCFFB, PFKDynasty, FantasyNavigator) are **registered live
   blend sources**, and the gate rewards exactly the value-decay property those boards were
   removed from the value-direct path for. **Caps confidence at 49.**

3. **Buy/sell direction is unreliable at the mechanism level.** `_compute_market_gap` averages
   *raw ordinals* across source pools spanning 50–900 deep. 47% of offense rows and 97% of pick
   rows flip sign under pool normalization; **36 of 36 tight ends are labelled SELL and zero
   BUY**, purely because the retail anchor is a TE-premium board and the consensus is not.

4. **Several flagship engines are silently degraded or inert.** The trade finder is still
   offense-only (the regression `CLAUDE.md` says was fixed) and its own IDP-blindness warning
   cannot fire. Trade suggestions sees 10–40% of a roster and returns nothing for 7 of 12 teams.
   The measured TE-premium curve is structurally unreachable from the UI. BDVM had **never run
   once** in production as of 2026-07-30.

5. **Missing data resolves to optimistic, neutral, or fabricated values instead of abstention.**
   Confidence is *raised* by missing sources. Unknown FAAB budget → $100. Unknown starter slots
   → "half the position group". Unpriced players → dropped from roster totals, or promoted into
   the Value column as raw scraper composites larger than legitimately-priced players.

6. **The monitoring that should catch all of this is itself broken.** The "scrape success rate
   < 50%" alert reads a key its input never contains. Blocked partial scrapes are recorded as
   successes. The partial-scrape guard divides by a `sites` dict with 2 entries, so it blocks
   only on total loss. Sharp's four diagnostic workflows `git add` a gitignored path and die
   before their verdict step — on every push to main, for 40 minutes each.

7. **Documentation asserts as settled fact several things the code contradicts** — 25 findings
   with root cause `documentation mismatch`, the single largest category.

---

## 2. Repository State

| Item | Value |
|---|---|
| Repository | `jasonleetucker-code/riskittogetthebrisket` |
| Branch / SHA | `claude/decision-intelligence-audit-wif47g` / `9c5d972f51a55d435030a56e76f023bf5eb9d1c7` |
| Commit | `chore(idpshow): automated refresh 2026-08-04T06:32:11Z` |
| Working tree | Clean (`git status --porcelain` → 0 lines) |
| History | 51 commits; base squash `c3bd7dc` (9,850 files, 2026-08-03 07:07 UTC) |

| Layer | Reality |
|---|---|
| Backend | FastAPI. `server.py` = **12,683 lines, 82 routes** |
| Scraper | `Dynasty Scraper.py` = 7,657 lines (production) |
| Engine | `src/` = **25 subsystems**, 774 files |
| Frontend | Next.js 15 — **39 pages**, 30 bridge routes, `frontend/lib/` = 15,358 lines |
| **Database** | **None.** No SQL, no ORM, no migrations. JSON files + a user KV store. *(The brief's SQL/view scope → not applicable.)* |
| Scheduling | 21 GitHub Actions workflows + 9 systemd timer pairs shipped |
| Testing | 378 pytest + 97 frontend files. **pytest not installed here** — suite not executable |

**`CLAUDE.md` is materially out of date**: documents `src/` as "~250 modules" across 12
directories, omitting 13 subsystems containing decision logic (`intel`, `sharp`, `ros`,
`roster_intel`, `public_league`, `league_comparison`, `news`, `nfl_data`, `playerctx`, `pool`,
`backtesting`, `platforms`, `maintenance`) and 15 of 39 frontend pages.

---

## 3. Coverage Statement

**Method:** structural sweep of every directory; concept grep across the full brief vocabulary;
live-data verification against the audited board, all 24 source CSVs, all 31 freshness stamps
and `git log` per data path; numerical reproduction of formulas in a scratch directory; and a
26-way parallel read-only subsystem fan-out.

**Completed: 26 of 26 subsystem audits.** Every subsystem in the repository was covered:

core valuation blend · non-blend contract layers · Hill curves + model registry · trade engines ·
BDVM · Sharp Tracker · `src/intel/` · `src/roster_intel/` + terminal + gameplan · **`src/ros/`** ·
**`src/league_intel/` overlay** · **`src/public_league/`** · **news/playerctx/nfl_data** ·
**scoring/backtesting/identity/pool/adapters/platforms/league_comparison** · **server.py inline
route logic** · **scraper ingestion + source registry** · draft/auction engine · frontend rankings
surface · trade calculator + retro-grading · team-level `/league` systems · waivers + FAAB · the
signal layer · remaining frontend surfaces · operational audit · testing audit · docs-vs-code
audit · constants and configuration registry.

Several agents rebuilt the live contract offline through the real entry point
(`build_api_data_contract` on `exports/latest/dynasty_data_2026-08-04.json`, 1,092 rows) and
measured against it rather than reasoning from code shape — that is the source of the 28.0%
Hampel-ejection rate, the 128/128 clamp count, the 33.3% confidence misclassification, the 53.7%
draft-capital figure and the 87% value-chain mismatch.

**Nothing remains unexamined** that the repository can answer. The residual gaps are environmental,
not coverage: no running server, no production filesystem, no `pytest`, and no historical data.

**Could NOT be inspected:**

| Area | Label |
|---|---|
| Test suite execution (`pytest` absent) | Not Verifiable from Repository |
| Production runtime state — `.gitignore:45` ignores `data/`, only `data/ros/` re-included | Requires Deployment Access |
| Live API responses (no running server) | Requires Live Data |
| Historical as-of reconstruction (no snapshot store exists) | Requires Historical Data |

**Honesty note:** absence of `data/bdvm/`, `data/intel/`, `data/playerctx/` from this clone is
**expected** and is not by itself evidence of breakage. Where I assert a production fact below,
it is sourced from repository evidence about production (e.g. `deploy/deploy.sh`'s measured
notes), not from the clone's file listing.

---

## 4. Critical Findings

Grouped by the decision they corrupt. Every one cites `file:line`; those marked **[reproduced]**
I re-ran numerically myself.

### 4.1 "Should I make this trade?"

**T-1 · The trade verdict's direction is undefined. [Critical]**
There is no single convention for what `sides[i].assets` means. The verdict label calls the side
with the *bigger pile* the winner; the flow math, stack lens, simulator hand-off, 3+-team meter
and side-card labels all treat a side's pile as what it **gives away**. `trade-logic.js:1392-1393`
(`result[i].given += value`) and `trade-sections.jsx:808` ("Giving") vs the meter's winner text.
Executed on the real module: `A=[9000] vs B=[6000]` → meter shows green on A and "Side A wins by
33%", while `computeSideFlows` on identical input returns `net_A = −3000`. **The headline verdict
can name the wrong winner.**

**T-2 · Fairness bands are absolute points on a board spanning two orders of magnitude. [Critical, reproduced]**
`trade-logic.js:1432` bands on raw `|gap|` (350/900/1800) with no normalization by trade size,
while the winner text beside it is a percentage.

| A | B | Gap | Gap % | **Verdict** | Text shown beside it |
|---|---|---|---|---|---|
| 420 | 80 | 340 | **81%** | **FAIR** | "Side A wins by 81%" |
| 9000 | 8650 | 350 | **4%** | **SLIGHT EDGE** | "Side A wins by 4%" |

Small trades judged far too leniently, large trades far too harshly — anti-correlated with real
fairness, and the contradiction is rendered in the same component. Reused for 3+-team trades
(`TradeMeter.jsx:127-130`).

**T-3 · Future picks are discounted against markets that price them upward. [Critical, reproduced]**
`config/weights/pick_year_discount.json` applies `1.00/0.82/0.66/0.53` by year offset
(`data_contract.py:6027`). But **both** ingested markets price the next class *above* the
imminent one:

```
ktcSfTep      2026 Early 1st 5595 | 2027 Early 1st 7061 | 2028 Early 1st 5122
idpTradeCalc  2026 Early 1st 5554 | 2027 Early 1st 7052 | 2028 Early 1st 5034
```

| Pick | Market avg | Factor | Published | **vs market** |
|---|---|---|---|---|
| 2027 Early 1st | 7056 | 0.82 | 5786 | **−18.0%** |
| 2028 Early 1st | 5078 | 0.66 | 3351 | **−34.0%** |

A user trading a 2027 first is told they *won* while surrendering ~1,270 points. Biases every
future-capital trade: **sell futures cheap, buy futures expensive.** The constants carry no
calibration evidence.

**T-4 · The trade finder is still offense-only — the regression `CLAUDE.md` says is fixed. [Critical]**
It receives no position data on the live path, so its per-market gate is inert while it reports
`marketTopNFilter: 150` as though a uniform gate ran. **T-5:** the explicit IDP-blindness warning
reads the same empty field, so the one safeguard designed to make this loud is disabled by the
defect it was written to catch.

**T-6 · The finder applies KTC's package Value Adjustment to the market side only. [Critical]**
Manufacturing arbitrage from a scale asymmetry. Its live top-5 were all "give Josh Allen, get
two elite QBs". **T-7:** its multi-piece guards run only in the give-more direction, and the
1-for-N direction — now **98% of output** — is unguarded. **T-8:** its arbitrage score is 93%
own-side gain / 7% opponent appeal, so it ranks lopsidedness, not arbitrage.

**T-9 · Trade suggestions analyses a roster it can see 10–40% of. [Critical]**
Returns zero suggestions for **7 of 12 live teams**, and tells the rest they have no depth
anywhere because 48 of 53 players are invisible to it.

**T-10 · Monte Carlo "win probability" is an invented ±15% band. [Critical]**
Exists on zero live rows and is uncalibrated. "Side A won 90% of 40,000 simulations" is a
restatement of "Side A is 20% ahead on value". **The frontend strips the disclaimer the backend
contract declares mandatory** and states the result exactly as the disclaimer forbids. Picks are
drawn 12% narrower than players (docstring asserts the opposite), biasing every pick trade.

**T-11 · Historical trade grades are pure hindsight. [High]**
`league-analysis.js:132,146` values every asset at *today's* board. A player who broke out after
the trade makes the acquirer look prescient. The as-of correction is a secondary badge with three
silent fallbacks. **T-12:** the public grader (`src/public_league/activity.py:118`) applies the
private grader's letter cuts to an alpha-exponentiated quantity the private path's own comment
forbids — a perfectly even 1×8000-for-2×4000 swap grades **A+ / D "Robbery"** on `/league` and
**A "Fair"** on `/trades`.

### 4.2 "Is this player a buy or a sell?"

**S-1 · `/edge` Buy/Sell direction flips on ~half the board. [Critical, reproduced]**
`_compute_market_gap` (`data_contract.py:2789-2796`) averages **raw ordinal ranks** across pools
spanning **50–900** deep, with no normalization. 47% of offense rows and 97% of pick rows flip
sign under pool normalization. I reproduced the mechanism: a 50-deep rookie board *cannot* emit a
rank worse than 50, so every rookie it covers is dragged into "experts love him → BUY".

**S-2 · 36 of 36 tight ends are labelled SELL; zero BUY. [Critical]**
The sole `is_retail` source (`ktcSfTep`) is a **TE-premium** board and the consensus is not. The
signal carries no player-specific information at TE or QB — it is a restatement of which scoring
format KTC publishes. A user acting on `/edge` is told to sell every tight end they own, every
day, forever.

**S-3 · `/edge` panels gate and rank on `sourceRankSpread`, not the gap they claim. [Critical]**
Sign from `marketGapDirection`, magnitude and sort order from max−min across *all* sources.
Live: Kenneth Walker renders "Buy +25 ranks" against a `marketGapMagnitude` of **0.6** — off by
40×. **S-4:** 38% of rows in `/edge`'s panels render as **HOLD** in the `/rankings` Edge column
for the same player in the same session (two independent thresholds: ≥10 ordinal ranks vs any
nonzero). **S-5:** four different thresholds turn one backend field into three contradictory
on-screen verdicts.

**S-6 · A single source dropping out silently re-ranks the board and publishes it as a real move. [Critical]**
`canonicalConsensusRank` blends whatever sources produced a row this cycle; `rankChange` diffs
against the previous build. Rows appear in "Risers — buy-low candidates", the ticker and
`/trending` with a per-source breakdown **purely because a fetcher failed**. Nothing distinguishes
this from a market move. **S-7:** the Hampel outlier filter can *manufacture* the gap `/edge` then
reports as BUY — a 76-rank buy signal on a player where 3 of 5 sources agree within 3 ranks.

**S-8 · `MoversPanel` inverts both trade verbs. [High]**
Labels risers "buy-low candidates" and fallers "sell-high candidates" — instructing the user to
buy what just went up and sell what just went down, on the terminal's most prominent widget.

**S-9 · SELL fires and emails on one day of movement while claiming a 30-day downtrend. [High]**
`computeWindowTrend` takes the earliest point *inside* the window rather than one windowDays old.
**S-10:** HOLD is returned for "no history at all" with the reason "Stable — no movement,
volatility, or news triggers" — asserting stability the system has no evidence for.
**S-11:** news polarity is a keyword coin-flip — **"released" and "waived" are stamped POSITIVE**
— and one item's impact is applied to *every* player it names.

**S-12 · Four independent BUY/SELL label families, no reconciliation, two of them email. [High]**

### 4.3 "How much should I bid?" / "Who should I add?"

**W-1 · The FAAB denominator counts draft picks as free agents. [Critical, reproduced]**
`server.py:4966-4978` filters the pool only by "is this name on a roster". Picks are never on a
Sleeper roster, so **every pick row counts as an available free agent** and the best pick
(~5574) sets `top_pool_value`. There is no `assetClass` filter. Measured: the desk recommends
**$12** standard where a free-agent-only denominator gives **$29** — every bid ~2.4× too low.

**W-2 · The bid is a value percentile with a dollar sign. [Critical, reproduced]**
`src/trade/waiver.py:91`: `aggressive_pct = 0.05 + 0.25 × (value / pool_max)`. Nothing references
weeks remaining, roster need, replacement level, or rival budgets. The identical player is worth
**$7 on a rich wire and $30 on a picked-over wire** — a 4.3× swing driven only by who else is
available. A thin wire should mean *save*; this says *spend*. Two missing-data hazards:
`top_value_in_pool` defaults to `None` → **maximum bid for everyone** (latent — both callers pass
it); and `waiver.py:195` assumes an **unknown remaining budget is a full $100**.

**W-3 · Two different FAAB figures for the same player on the same page, disagreeing by 75%. [High]**
The Best-moves column says $21; the bid desk says $12. The top row of that column always reads
$21/$30 by construction.

### 4.4 "How good is my team?"

**R-1 · Pick hoarders are ranked as the strongest contenders. [High]**
`league-analysis.js:1026-1028`: `totalValue` accumulates pick value, `depthValue = totalValue −
starterValue` carries it into the +0.2 depth term, and the explicit −0.1 penalty applies on top.
**Net coefficient on pick value is +0.1** — while the UI tells the user picks are penalised at
−10%. The most rebuild-shaped roster in the league ranks as the best contender.

**R-2 · The ROS buy/sell ladder sends every team from 60–100% playoff odds to neutral. [Critical, reproduced]**
`src/ros/direction.py:80-115` leaves *gaps*, and falls through to the catch-all:

```
playoff 0.00–0.15 -> Hold / Evaluate      <- a dead team told to hold
playoff 0.20–0.35 -> Selective Seller
playoff 0.40      -> Hold / Evaluate      <- dead band
playoff 0.45–0.55 -> Selective Buyer
playoff 0.60–1.00 -> Hold / Evaluate      <- EVERY strong team
```
A team at **100% playoff odds** gets the same advice as one at 0%. Live on two surfaces:
`/league` "Trade Deadline" tab and `RosTradeFitPanel` on `/trade`. Two of its four documented
inputs have **no effect** (`team_ros_strength_percentile` only formats a string;
`roster_age_profile` is always `{}`), so one of seven labels is unreachable.

**R-3 · Three incompatible team-phase definitions. [High]**
`roster_intel/window.py` (softmax, 5 states) · `ros/direction.py` (hard thresholds, defective) ·
`frontend/lib/team-phase.js` (2×2 median split). The frontend one is **relative to league
medians**, so exactly half the league is always "high value" by construction; low-value+older →
"Mixed" whose docstring reads *"you should probably reset"*. **The 'Rebuild' phase is unreachable
on live data** — strict `<` against a median of integer team-medians puts five of twelve tied
teams on the wrong side, killing `/phases`' headline trade-partner feature. It joins players **by
lowercased name only** and silently drops unpriced players from team totals.

**R-4 · Luck and Power rankings count in-progress weeks as finished games. [High]**
`metrics.is_scored` returns True for any roster with points > 0, so a team that played Thursday
is treated as final while its opponent sits at 0. The playoff-odds module guards this; `luck.py`
and `power.py` do not. With a 300-second snapshot TTL, **the verdict and rank visibly change
during Sunday afternoon and re-settle Monday night.**

**R-5 · Two playoff-odds engines and two power-ranking engines are both wired**, swapped by
`settings.useRosPlayoffOdds` / `useRosPowerRankings` (`public_contract.py:140-148`). Same league,
two different probabilities, no indication which is more trustworthy.

### 4.5 "What is this player worth?" (the core board)

**V-1 · The IDP board is IDPTradeCalc ±15% by construction. [Critical]**
Root cause found: **the IDP master curve is fit on sources that never use it and applied to
sources it was never fit on — the overlap is zero.** The fit assigns IDP scope to IDPTradeCalc's
IDP slice and DraftSharks-IDP; at runtime `_curve_for_source` tests `is_cross_market` first and
routes both to GLOBAL. Consequences, measured on the live board: the IDP master pays **48% of the
IDP market at the same rank**; the Hampel filter therefore ejects the designated IDP anchor on
**28.0%** of IDP rows; and the corridor clamp's hard `0.15` cap binds on **128 of 128 clamped
rows** (43.5% of ranked IDP), dragging values *upward* — i.e. **the clamp is repairing the scale
bug, not containing outliers.** Fixing the curve without revisiting the clamp will move the whole
IDP board.

**V-2 · The Hill-curve promotion gate is circular. [Critical]**
`src/model_registry/holdout.py:74-79` defines the holdout as FantasyCalc, OTCFFB, PFKDynasty and
FantasyNavigator — **all four are registered live blend sources** (`data_contract.py:1302, :1327,
…`). Worse, all four were moved *off* the value-direct path because their value curves decay
faster than the consensus, and **the gate rewards exactly that property**. Every "the new curve
generalizes better" claim means "the curve reproduces four boards whose ranks we already vote into
our own board". Only **2 of 8** production constants have any out-of-sample check, yet all eight
ship on that verdict; and `model_registry.py validate` performs the unpaired cross-snapshot
comparison the design explicitly forbids.

**V-3 · The Value column silently switches to the raw scraper composite. [Critical, reproduced]**
`dynasty-data.js:1008` — `full: Math.round(backendValue || rawValues.full)`. When the pipeline
declines to price a row it stamps `rankDerivedValue: null`, leaving `values.overall` holding the
**pre-pipeline scraper composite**, which is promoted into the same column with the same
formatting, band badge and sort key. 260 rows; **158 display a larger number than the deepest
genuinely-priced player.** Devin Bush — a rotational LB the pipeline refused to price — renders at
2,549, 3.4× the deepest real value.

**V-4 · The measured TE-premium curve is structurally unreachable. [Critical, reproduced]**
`SETTINGS_DEFAULTS.tepMultiplier = 1.15` (`useSettings.js:27`) is a **finite number**, and
`tepMultiplierIsCustomized` (`dynasty-data.js:893`) returns true for any finite value — so every
default session posts an explicit operator override, and (per `CLAUDE.md`) "an explicit operator
slider value bypasses the curve regardless." The ADR-015 curve — KTC's own measured uplift, built
*because* the flat 1.15 "sits below the entire observed range" — **never runs for any user.**
Understatement vs the curve: 3000→+10.8%, 2000→+17.8%, 1000→+34.8%, 600→+53.1%, 400→+72.4%,
200→+78.5%. `/settings` "Reset to default" writes the literal `1.15` where its sibling correctly
writes `null`, then reports the two states identically.

**V-5 · Confidence can be RAISED by missing data. [High]**
`data_contract.py:1893-1903` decides on `source_count >= 2` and `percentile_spread <= 0.08`,
where the spread is computed **only over sources that ranked the player** — uncovered sources drop
out of the statistic. A row covered by **2 of 16** eligible sources is labelled *"High —
multi-source, tight agreement"*. `softFallbackCount` is never an input. It also measures
percentile-*rank* agreement while sitting beside a *value*: 20 of 107 "high" rows have value
dispersion above 30%, and the row already carries the value-space statistic (`hillValueSpread`),
unconsulted.

**V-6 · 127 tiers on a 740-row board. [High]** Median boundary is an **8-point (0.45%) value
drop** — exactly what the docstring says must not be a boundary ("a 3-point drop from 312→313 is
not"). Users read noise as a value cliff.

**V-7 · Ranks past 500 collapse to one value. [High, reproduced]** `data_contract.py:7113` with a
constant denominator of 500. 443 live per-source votes carry zero ordering information
(`draftSharksIdp` 63.1% → all 1698; `idpShow` 58.9% → all 594). The repo's own backtest recommends
400; the code ships 500.

**V-8 · One user's slider overwrites everyone's movement arrows. [High]**
`_stamp_rank_changes(..., write_snapshot=not source_overrides)` (`:7903`) writes the shared
`data/snapshots/ranks_last.json` on any build without source overrides — **including TEP-only
override requests**. One user moving the TE slider rewrites every other user's "since the previous
scrape" arrows. Separately, `rankChange` is override-sensitive but absent from
`_DELTA_PLAYER_FIELDS`, so custom-weight users see the default board's arrows beside override ranks.

**V-9 · 216 players (20% of the board) carry client-invented ranks. [High]**
`buildRows` assigns `computedConsensusRank = i + 1` over the whole sorted array *including the 116
picks the backend deliberately left unranked*, then uses it as `r.rank`. The `#` column reads
738, 739, 740, `—`×44, then jumps to **857**. These feed `resolvedRank`, the rank sort, positional
ranks and eligibility gates.

**V-10 · The transparency panel doesn't reconcile. [High]**
`PlayerPopup`'s "Value chain — how we got N" models only the anchor and α-shrinkage stages, then
claims they explain `values.full`. **885 of 1,015 rows (87%) end on a different number**, median
|Δ| 282, p90 878. ~11 later stages are neither modelled nor disclosed. This is the product's
trust surface.

**V-11 · Publisher double-voting. [Medium, reproduced]** `fantasyProsSf + fantasyProsFitzmaurice`
overlap **totally** (298 rows); plus Flock ×2 (63), DLF ×2 (33+12). 21 registry sources resolve to
~**14 publishers**. FantasyPros gets double voice on the top ~300 offense players, and since ECR
is itself a consensus plausibly containing Fitzmaurice, one analyst may count three times.

**V-12 · 2029 picks are a re-discounted clone of 2028** rendered with a value, tier, confidence
bucket and draft-day projection, indistinguishable from a priced asset. **V-13 · The two-way boost**
(`:4894`) overrides the whole pipeline with an unweighted mean of incommensurable scales — live at
**+115%** on Travis Hunter, after the clamp, bypassing Hampel and α-shrinkage.

### 4.6 "Which manager should I target?" (Sharp / Intel)

**P-1 · `rosterQuality` — 22% of Sharp Score — is structurally zero for every manager.** The total
is **not renormalized**, so every score is depressed by up to 22 points against a 0–100 scale, and
`market.py:226` maps `quality = score/100` straight into `signal_strength`.

**P-2 · The cohort is self-reinforcing. [Critical, circularity]** Activity evidence is collected
only for managers who *already qualified*: qualifying grants activity data, up to 8 more points,
and immunity from the recency gate that only fires once you have movement data.

**P-3 · Trades between two cohort managers produce exactly zero directional signal while inflating
volume and confidence.** The failure mode worsens as cohort coverage improves.

**P-4 · Sharp Score has no validation of any kind** — no backtest, holdout or calibration. There
is no evidence a manager at 75 trades better than one at 55. **P-5:** `multiLeagueConsistency` —
the module's own "core anti-luck signal" — counts season-rows as independent leagues, and says
"independent" in user-facing text. **P-6:** unqualified FFPC "provisional" managers sit in the
default board at weight 0.55 under a column labelled "Sharp managers".

**I-1 · Intel `tradeCount` is inflated 2–6× [High]** by summing per-asset transaction counts; it
feeds `leads.activity_fit` and roster scoring. **I-2:** the documented roster-clog guard is inert,
so every rostered body counts as depth. **I-3:** positional need is an *ordinal within a roster*
summed into a *cross-manager* ranking. **I-4:** the value-match term is saturated for essentially
every lead, adding a constant +12 and discriminating between none. **I-5:** the lead score has no
error rate and no disclosed range, while rendering a no-evidence manager as an amber **33/100** —
a number ranking the people the user is about to negotiate with.

### 4.7 "What should I draft / bid at auction?"

**D-1 · Every bid recommendation ignores the user's remaining budget and roster slots. [Critical]**
`draft-logic.js:717-731` — `theoreticalMaxBid` reads only preDraft/aggression/budget-advantage/
inflation/phase, and `myWinningBid` caps against the richest *rival*. Neither reads `myRemaining`
or `mySlotsRemaining`. The module docstring designates this the headline figure; it is
**unimplementable by the user it is shown to.**

**D-2 · Inflation diverges hyperbolically at the end of every draft. [Critical]**
`inflation = remainingLeague / max(1, totalBudget − soldPreDraft)` mixes two accounting scales;
the denominator → 0 as the pool drafts out. Reproduced: **58.20 at pick 67, 96.33 at 69, 144.00 at
70, 287.00 at 71.** A user following the Enforce column would **bid $229 on a $1 dart** — the board
becomes dangerous exactly at the endgame when money is still live.

**D-3 · Sleeper-derived draft capital fabricates 52% of the board, and the 503 guard does not fire. [Critical]**
`draft_capital_fallback.py:96-99,175` builds picks for `current_season` *and* `+1`, but the contract
carries slot rows only for the current class — so every next-season pick falls through to a
hardcoded `{1: 7000, 2: 4000, 3: 2000, 4: 1200, 5: 700, 6: 300}` table. The guard
(`server.py:8154`) fires only when there is **no contract at all**. **D-4:** the same path assigns
draft slots by `roster_id`, so roster 1 is permanently credited with the 1.01 value irrespective
of standings.

**D-5 · "Next Best Targets" is a `preDraft` sort wearing an EV model's clothes. [High]**
`surplus = max(0, inflatedFair − myWinningBid)` is a monotone function of `preDraft` in both
regimes. Verified: at draft open it returns exactly the top-5 by `preDraft`, in order — under a
subtitle claiming "EV = (fair − winBid) × tag weight + scarcity boost".

**D-6 · Vendor "Market" dollars are inflated by row count. [High]** `server.py:7058-7068`
distributes the full $1200 across whatever list it receives, so a vendor covering 42 of 72 rookies
is scaled up ~72/42. All 42 KTC-covered rookies register as "KTC overrates us"; **zero** qualify
for "Best value on the board". The comment claims a pad the code does not perform.

**D-7 · "Best value on the board" renders backfill rows as green underrate signals** with a
malformed "−-6%" badge — **inverted for 100% of what a user currently sees.**

**D-8 · Per-team pick counts are clamped to 6**, contradicting the docstring three lines above, so
a team that traded for extra picks is modelled as if it had not.

### 4.8 Fundamental value (BDVM)

BDVM is **architecturally the most honest system in the repo** — market isolation enforced
structurally (`MarketIsolationError`), params explicitly labelled "STARTING PRIOR … NOT backtested
truth", unpriced players returned as `unpriced` with a reason. But:

**B-1 · It had never run once in production. [Critical]** `deploy/deploy.sh:670-682`, measured on
the live box 2026-07-30: the repo shipped **nine timer pairs and only two were installed**; *"The
BDVM refresh had never run once — `journalctl -u dynasty-bdvm-refresh` was empty and `data/bdvm/`
did not exist — so `/api/bdvm/*` served nothing while the deploy reported success every time.
Signal alerts, custom alerts, player context, sharp discovery and reception depth were equally
absent."* A deploy.sh fix landed 2026-07-30; whether these have run in the five days since is
**Not Verifiable from Repository**. `CLAUDE.md`'s "726 players priced" was written against a box
where it had never run.

**B-2 · BDVM's "exact league scoring" silently drops 6 active reception-band rules. [Critical]**
WR fundamentals ~15% understated, RB ~9%, QB 0% — every fundamental value, replacement level and
market gap biased against pass-catchers and in favour of quarterbacks.

**B-3 · `STRONG_BUY` is structurally unreachable** (`gap_persisted_days` never passed) while
`STRONG_SELL` fires on any negative alpha when `p_collapse_1y > 0.5`, bypassing the −900 threshold
— **the signal distribution is systematically bearish for reasons unrelated to mispricing**, and
it emails.

**B-4 · `liquidity` increases with market DISAGREEMENT** and multiplies the gap into alpha —
inverted semantics — and silently rescales every threshold by ~0.38, making documented cutoffs
~2.6× tighter than behaviour.

**B-5 · Rookie-pick values are a frozen prior table never anchored to the calibrated player
scale**, yet both are summed in one CES package by `/api/bdvm/trade-eval` (the "Fundamentals check"
panel on `/trade`). **B-6:** roster strategy capitals exclude picks entirely, so `nowFutureRatio =
contender/rebuilder capital` is computed with *all future draft capital deleted* — precisely the
quantity that defines a rebuilder. **B-7:** seven `params_v1.json` sections are never read; the
most consequential leaves single-source projections with **σ_source = 0**, understating
uncertainty exactly where it is largest.

**B-8 · Proxy disclosure is stripped on the pages that matter. [High]** Where no real projection
covers a player, "fundamental" is last season's realized PPG (`is_proxy=True`) — so the gap is
structurally *"the market knows things last year's box scores don't"*, a momentum-fade signal.
`/bdvm` badges this honestly; `buildBdvmIndex` (`frontend/lib/bdvm.js:192-205`) — the index feeding
the `/rankings` and `/draft` "Fund gap" columns — **omits `anyProxy` entirely**, while the tooltip
asserts "positive means the market underprices the player".

### 4.9 Operations and monitoring

**O-1 · The "scrape success rate < 50%" alert can never fire. [Critical]** It reads
`scrape_success_rate_24h`, a key produced only inside `get_status` and absent from the payload
`ops_alerts.check_and_alert` is actually called with. **O-2:** a blocked partial scrape calls
`_mark_scrape_success` and is recorded as a **success**, so the rate reads 100% while every scrape
is rejected. **Combined: there is no email path that fires on sustained ingestion failure.**

**O-3 · The "<50% of sites" partial-scrape guard is degenerate. [Critical]** It divides by
`result['sites']`, populated only by the legacy in-scraper `SITES` dict — which today has **exactly
2 entries** (KTC + IDPTradeCalc). So it blocks only on total loss: **if KTC dies and IDPTradeCalc
survives, the scrape publishes a board missing its own anchor.**

**O-4 · Four Sharp workflows `git add` a gitignored path** (`.gitignore:45`) and therefore always
fail at their reporting step — *before* the "Enforce healthy population" gate, which has **never
executed**. `verify-sharp-production.yml` triggers on every push to main and burns **40 minutes**
per run polling auth-gated endpoints **anonymously — 80/80 attempts return 401**, 79 times so far.

**O-5 · `apply_hardening.sh` is never invoked by automation**, so the liveness watchdog, uptime
probe and state-backup timers are manual-install-only — the same category as the BDVM timer that
had never run. **O-6:** the Sleeper freshness stamp is written by the scraper and **read by
nothing**, so a total Sleeper outage is invisible to every monitor while rosters of arbitrary age
serve as current. **O-7:** two independent backup systems exist; the health probe globs only one,
so one failing is a false alarm and the other failing is silent.

**O-8 · `/api/scaffold/*` has served 2026-04-20 data for 106 days. [Critical]** **Nothing writes
`raw_source_snapshot_*.json` any more** (only readers + a pruner remain), and
`build_identity_report` is called only by a test. The refresh workflow `git add -f`s both paths
every 2 hours, so the staging is live and the producer is dead. `_latest_file` has **no age
guard**, and the only freshness signal (`st_mtime`) is reset by every deploy — **it reads fresh
because the data is redeployed.** Identity-match quality, which underpins every join on the
platform, is measurable only from an April report.

**O-9 · Source freshness measures "our fetcher ran", not "the vendor published something new."**
`scheduled-refresh.yml:163-178` stamps `*_last_success` on fetch success "regardless of whether the
CSV content changed"; `config/source_staleness.json` documents this. A frozen vendor board is
indistinguishable from a live one forever. Observed: `footballGuys*` stamps **71.3 days** old, and
its CSV-rank restoration path is dormant (key set empty).

### 4.10 Rest-of-season projections and contender odds

**N-1 · Playoff and championship "odds" are structurally degenerate out of season. [Critical]**
Every team is **100% or 0%** — six teams at a 100% playoff chance and the rest at 0%, in August,
before a single 2026 game — cached, stamped `converged: true`, and served as current on every ROS
contender surface (`/league` → Championship, `/league` → Trade Deadline, the ROS Fit panel on
`/trade`).

**N-2 · A team missing from the sim is coerced to 0% odds and labelled "Seller". [Critical]**
Four to five of twelve managers are told *"Sell aging win-now players. Prioritize 2026/2027 picks"*
purely because they were **absent from an input file** — and the roster ranked **#1 in the league
on ROS strength (percentile 1.000)** is among them. Missing data does not merely degrade the
answer here; it produces a confident, inverted trade instruction about the best team in the league.

**N-3 · ROS sims hardcode 6 playoff spots and 2 byes** and never read the league's Sleeper
settings, so in any other bracket every probability and contender tier is computed against the
wrong structure. **N-4:** two independent Monte Carlos both publish "championship odds" and
disagree by up to 5 points; one page renders both, and the trade-deadline classifier gates on
whichever file it happens to read.

**N-5 · Rank scores are normalized against each source's own board size**, so an IDP-only board and
a 978-player board are blended as commensurable — a roster of top-of-the-IDP-board defenders scores
like a roster of elite offense, and that composite sets the projected reverse-standings draft order.

**N-6 · Adapter failure does NOT keep last-known-good values**, contrary to the doc, the CI comment
and the test docstring: if DraftSharks (~34% of an offense player's blend) fails one cycle, every
player it uniquely ranked drops out of `rosValue` entirely and `staleFlag` stays false.
**N-7:** `freshness_multiplier` and `staleFlag` are structurally unreachable — the timestamp
compared against "now" is always this run's own completion time, so the confidence field's 0.20
freshness term is a constant.

**N-8 · No historical validation, calibration or backtest exists for any ROS output** — not the
0.72/0.18/0.05/0.05 composite, the base weights, the 0.45/0.35/0.20 confidence split, the 18.0
volatility threshold, `ROS_BLEND` 0.20, the 1.10 variance bump, or the nine power-v2 weights.

### 4.11 The league-adjusted lens

**L-1 · `structuralScarcity` is computed from a log-rank index with an arbitrary zero. [Critical]**
Every factor moves when the ROS source universe changes size. Because picks are exempt (factor
1.0), the mean player factor *is* the level of the whole player-vs-pick reprice: **+2.5% offense /
+3.3% IDP at N=1085, but +0.5% at N=2000 and +5.5% at N=500 with identical player data.** The lens
silently reprices players against picks as a function of how many rows a source happened to publish.

**L-2 · The factor is NOT a function of position alone.** `CLAUDE.md` and `publish.py` both assert
this property; reception fit reorders WR/RB/TE against each other. The batch monotonicity guard
that reads as decorative is in fact load-bearing.

**L-3 · The adjusted contract scales only `rankDerivedValue`**, leaving `offenseOnlyRankDerivedValue`
and `values.*` at market — so `suggestions.py` compares adjusted IDP values against market offense
values in one search. **`CLAUDE.md`'s central justification for the entire overlay design — "every
engine reads exactly one value" — is false.**

**L-4 · `lineupScarcity` measures top-heaviness, not scarcity**, and applies the lift uniformly to
every player at the position *including replacement-level ones* — the exact inverse of the VORP
argument, which says a steep drop-off makes the elite player dearer and the marginal starter cheaper.

**L-5 · The TE++ target basis is a hardcoded constant that is wrong for `dynasty_new`.** A one-TE
league is served a board carrying a two-TE premium worth a median **+17%** in value and ~50 board
slots — documented, unmitigated, and it flows into every trade evaluation, waiver bid and draft
board for that league. **L-6:** `scoringFit`/`receptionFit` are measured against a Sleeper league
that is not in the registry, then cached per league key as if league-specific.

**L-7 · The rankings overlay is unreachable for the non-default league while the engines still
serve it** — a `dynasty_new` user with the toggle on sees a market-priced `/rankings` (silently, no
banner) and a league-adjusted terminal and simulator. That is precisely the split-board condition
the feature exists to prevent.

### 4.12 News can move a user-facing value

**E-1 · A keyword-matched RSS headline directly discounts a player value by up to 5%. [Critical]**
Reproduced from the module's own constants: `alert` + RB + age 30 + fresh news →
`4.0 × 1.20 × 1.20 × 1.0 = 5.76` → capped at **5.00%** → a 9,000 value renders as **8,550**. The
severity is not player-specific, and `info` severity means **no keyword matched at all** — i.e. an
ordinary neutral headline participates in the tiering.

**E-2 · `classify()` stamps `impact="positive"` on every WATCH item — including "released" and
"waived". [Critical]** A headline announcing a player was cut is scored as positive news and, with
any positive rank change, emits a **BUY** reading *"Positive news with rank rising"*. The same
defect silently kills `injury_impact`'s entire mid-grade watch tier, so a hamstring never fires.

**E-3 · A news headline raises a player's BDVM fundamental value through the sigma channel.** The
documented safety property covers the *mean*, not the *value*: `INJURY` carries `sigma_mult: 1.15`,
scale `0.45 × 0.6 = 0.27` on day 0 → effective `1.15^0.27 = 1.0405`, and because σ drives the
option-value surplus the fundamental goes **up +2.61%** on an injury report.

**E-4 · `/api/player/{id}/realized` never fetches defensive stats**, so the "Realized points" panel
is dark for **every IDP player** on an IDP platform, with no diagnostic distinguishing "no data"
from "never queried". When scoring settings are absent it emits a full array of **0.0-point weeks**
— an authoritative-looking zero rather than an absence.

### 4.13 Identity, source independence, and dead code

**Z-1 · `idpShow` and `idpTradeCalc` are the same board. [High]** Spearman **0.982–0.986** with
residual correlation **+0.986**. The IDP blend nominally has 5 sources (median 4 per row); two of
them are one signal. Because `idpTradeCalc` is *also* the α=0.10 anchor **and** the corridor-clamp
anchor, an IDPTC error is **corroborated by its own twin rather than corrected by it.** This is the
sharpest instance of the brief's "do not treat correlated sources as independent confirmation".

**Z-2 · A preserved last-known-good CSV mints a fresh "successful fetch" stamp. [Critical]** This is
the precise mechanism behind the freshness problem: if the IDPTradeCalc scrape dies, the board keeps
serving the frozen last-good board and `scripts/watchdog_freshness.py` prints **"ok: 22 sources"**.
IDPTradeCalc is the IDP backbone, the sole cross-market IDP anchor, and 90% of every IDP value under
α=0.10 shrinkage. **Z-3:** staleness is reporting-only — a source that has not updated in weeks
votes at full 1.0 weight, still counts toward `sourceCount` and the confidence bucket, and still
corroborates its neighbours.

**Z-4 · `identityConfidence: 1.00` means "has a Sleeper ID", not "matched correctly"** — and 85.8%
of live rows carry it, while the true per-source name-join miss rate on the same payload is **601 of
8,408**. **Z-5:** the unified mapper's fuzzy fallback accepts demonstrably different players at its
default threshold when `position` is omitted (it is optional), silently attaching one player's
Sleeper id, stats, injury status and news to another player's row at ~0.9 confidence.

**Z-6 · The entire `src/scoring` player-adjustment and archetype pipeline is imported and never
called** — ~600 lines of shrinkage, archetype priors, rule attribution and multiplier caps that
influence no number a user sees, while `CLAUDE.md`'s directory table presents it as a live subsystem.

**Z-7 · `docs/status/canonical-source-matrix.md` declares 8 live sources removed** and describes a
retired pipeline as current. The audit's own assessment: *"the single most misleading document in
the audited set"* — acting on it would break 15 live sources.

**Z-8 · The `/rankings` "updated Xm ago" timestamp measures contract-build time, not data-fetch
time.** The page reads seconds-old whenever the server rebuilds the payload, regardless of vendor
data age — a user cannot distinguish a 5-minute-old board from a 3-day-old one.

### 4.14 More on the public league

**U-1 · Public trade grades price unresolvable assets at 1.0**, so any historical trade containing a
retired or off-board player is publicly graded a ~100% fleecing, **with the losing manager named**.
**U-2:** weekly power rankings accumulate PPG and W-L across **all seasons** while labelled and
documented as season-to-date. **U-3:** a single 0.00-point roster-week silently removes that owner
from the all-play population, breaking the luck metric's pigeonhole identity and publishing a named
luck verdict off it.

### 4.15 The explanations themselves are wrong

`documentation mismatch` is the **single largest root-cause category (32 findings)**. That matters
here more than in a normal codebase, because on an analytics product the published methodology *is*
part of the deliverable — it is how a user decides whether to trust a number.

**X-1 · The `/rankings` methodology panel publishes a value formula whose constants exist nowhere
in the codebase. [High, reproduced]** Displayed vs live rank-form value: rank 25 → 6663 vs **7134**;
rank 50 → 4766 vs **5653**; rank 100 → 2959 vs **4068**; rank 200 → 1632 vs **2665**; rank 800 → 406
vs **931**. A user who checks the published formula against a displayed value will conclude the
board is wrong — or, worse, will "correct" for a discrepancy that does not exist.

**X-2 · The shipped `/api/data` contract describes a weighting formula the blend does not apply**,
and contradicts itself two fields later. It tells any consumer that shallow rookie lists are
down-weighted; all 21 sources vote at **weight 1.0**. Someone "restoring" the documented behaviour
would move 297 of 1,094 rows and 221 ranks.

**X-3 · The contract publishes the wrong confidence-bucket rule — it misclassifies a third of the
board.** `confidenceBucket` gates `/edge` eligibility, the single-source-risk screen and the
ConfidenceValueScatter, so an integrator reasoning from the contract's own published rule is wrong
on 33.3% of rows.

**X-4 · `docs/idp-ranking-model.md` is materially false — 0 of 740 rows match its published
formula.** Wrong curve, wrong constants, wrong blend, and it references a frontend module that does
not exist. This is the document someone opens *specifically* to check whether IDP numbers deserve
trust.

**X-5 · `/api/draft-capital`'s non-default-league board is 53.7% invented**, with no field marking
which values are real — while `CLAUDE.md`'s D-2 note asserts this exact case "is fixed" and "is the
case the 503 covers".

**X-6 · The Monte Carlo band producer has no caller.** Every asset gets a hardcoded ±15%, so a
rock-solid consensus QB1 and a wildly-disputed rookie are modelled as equally uncertain — while the
UI tells the user the number came from real source disagreement.

### 4.16 Testing integrity

**Q-1 · A 100%-synthetic test module for the core blend is exempted from the blocking CI gate by a
filename-matching rule. [High]** 33 tests covering `_compute_unified_rankings` — rank assignment,
value-direct voting, the single-source haircut, `OVERALL_RANK_LIMIT`, legacy-dict mirroring, IDP
integrity guardrails — **cannot fail a pull request.**

**Q-2 · Pipeline stage 11 — a genuine post-blend override of `rankDerivedValue` — has no test at
all.** If the two-way boost silently stopped firing, nothing would catch it.

**Q-3 · Sharp Score's entire weight vector is unpinned; every test is an inequality. [High]** You
could swap `winPct` and `championshipRate`, or set all five weights to 0.2, and the suite stays
green. Combined with P-4 (no validation of any kind) there is neither a correctness check nor an
accuracy check on the numbers driving that product.

**Q-4 · A regression test asserts the scale-mixing bug as correct behaviour.**
`frontend/__tests__/dynasty-data.test.js:307` ("falls back to finalAdjusted when displayValue is
missing") pins V-3 — the promotion of raw scraper composites into the Value column — as intended.
A test suite can hold a defect in place.

**What the tests are good at:** the source-registry parity test
(`tests/api/test_source_registry_parity.py`) genuinely works — the constants sweep verified the
21-source Python registry and the frontend mirror are **identical**, keys, order and weights, and
the KTC value-adjustment constants (10000 / 10041 / 5) match across all three modules that hold
them. Where a parity test exists, parity holds.

---

## 5. Cross-Cutting Patterns

1. **Missing data resolves to an optimistic, neutral or fabricated value instead of abstention** —
   the single most pervasive defect class in the codebase, appearing in **every** subsystem
   audited. V-5 (confidence *raised* by missing sources), **N-2 (absent from a file → 0% odds →
   "Seller", applied to the league's best roster)**, W-2 ($100 phantom budget), V-3 (unpriced →
   composite promoted above real values), D-3 (invented pick table), V-12 (cloned 2029), B-7
   (σ=0 for single-source), **U-1 (unresolvable asset priced at 1.0 → public "fleecing" verdict
   with a named manager)**, **E-4 (missing scoring settings → a full array of 0.0-point weeks)**,
   `scoring/replacement_level.py:218-220` (unknown slots → "half the position group").
2. **Absolute thresholds where relative are required (T-2) and relative where absolute are
   required (W-2).** Both produce confidently wrong labels.
3. **Ordinals averaged across incommensurable pools** — S-1, S-2, and the same root in V-1.
4. **Post-hoc clamps repairing upstream calibration bugs** (V-1), making the bug invisible and the
   clamp load-bearing.
5. **Validation optimizes stability, not accuracy** (§1.1) and the one automated gate is circular
   (V-2).
6. **Guards and warnings disabled by the very defect they were written to catch** — T-5, O-3, O-4,
   D-3.
7. **Dormant code presented as live capability.** `feature_flags._GATE_STATUS` is the model fix
   here: it classifies **7 of 13 flags** as UNREACHABLE/SCRIPT_ONLY/NO_GATE and
   `tests/api/test_feature_flag_reachability.py` re-measures it against the real import graph.

---

## 6. Confidence Scorecard

Sorted lowest first. Caps from the brief applied and named.

| System | Data | Math | Meth | Valid | Ops | Use | **Overall** | Grade | Usage | Primary limitation |
|---|---|---|---|---|---|---|---|---|---|---|
| `/api/scaffold/*` | 5 | 50 | 30 | 0 | 5 | 5 | **5** | Not trustworthy | **Do Not Use** | 106-day-stale; producers dead (O-8) |
| Sharp Score / Tracker | 15 | 45 | 55 | 0 | 10 | 10 | **9** | Not trustworthy | **Not Operational** | Never validated; 22% of score structurally 0; cohort circular (P-1..P-6) |
| BDVM (all surfaces) | 10 | 60 | 65 | 10 | 10 | 15 | **12** | Not trustworthy | **Not Operational** | Never ran in prod as of 2026-07-30 (B-1) |
| Auction "Win at" bid | 40 | 10 | 10 | 0 | 70 | 5 | **11** | Not trustworthy | **Do Not Use** | Ignores my budget; inflation diverges (D-1, D-2) |
| ROS buy/sell direction | 45 | 10 | 15 | 0 | 60 | 5 | **12** | Not trustworthy | **Do Not Use** | 60–100% odds → neutral (R-2) |
| Trade verdict | 55 | 15 | 15 | 0 | 80 | 10 | **15** | Not trustworthy | **Do Not Use** | Direction undefined; bands absolute (T-1, T-2) |
| `/edge` Buy/Sell | 60 | 15 | 10 | 0 | 85 | 5 | **15** | Not trustworthy | **Do Not Use** | Sign flips ~half; 36/36 TEs SELL (S-1..S-5) |
| Sleeper draft capital | 20 | 25 | 20 | 0 | 70 | 10 | **17** | Not trustworthy | **Do Not Use** | 52% invented; guard inert (D-3, D-4) |
| FAAB recommendation | 45 | 25 | 15 | 0 | 75 | 10 | **18** | Not trustworthy | **Do Not Use** | Picks in denominator; percentile-as-dollars (W-1, W-2) |
| Trade finder (arbitrage) | 50 | 25 | 20 | 0 | 75 | 10 | **19** | Not trustworthy | **Do Not Use** | Offense-only; one-sided VA (T-4..T-8) |
| Movers / risers-fallers | 45 | 40 | 15 | 0 | 80 | 10 | **19** | Not trustworthy | **Do Not Use** | Verbs inverted; fetcher failures published as moves (S-6, S-8) |
| Monte Carlo win prob. | 50 | 30 | 15 | 0 | 80 | 10 | **20** | Very low | **Do Not Use** | Invented ±15% band; disclaimer stripped (T-10) |
| Trade suggestions | 35 | 45 | 30 | 0 | 70 | 15 | **22** | Very low | **Do Not Use** | Sees 10–40% of roster (T-9) |
| Team phase (frontend) | 40 | 45 | 20 | 0 | 75 | 20 | **25** | Very low | **Do Not Use** | Rebuild unreachable; name-join (R-3) |
| Contender score | 50 | 20 | 25 | 0 | 80 | 20 | **25** | Very low | **Do Not Use** | Pick term nets +0.1 vs stated −10% (R-1) |
| Trade history grades | 55 | 40 | 20 | 0 | 80 | 15 | **25** | Very low | **Do Not Use** | Hindsight; public/private disagree (T-11, T-12) |
| Insider-trading leads | 40 | 40 | 25 | 0 | 65 | 20 | **27** | Very low | **Do Not Use** | No error rate; saturated terms (I-1..I-5) |
| IDP consensus values | 55 | 25 | 25 | 0 | 85 | 30 | **28** | Very low | **Do Not Use** *as consensus* | Is IDPTC ±15%; curve overlap zero (V-1) |
| Hill curves / registry | 60 | 55 | 40 | 15 | 80 | 35 | **29** | Very low | **Caution** | Circular holdout — **cap 49**; 2 of 8 constants checked (V-2) |
| Value column (unpriced rows) | 40 | 35 | 25 | 0 | 85 | 20 | **30** | Very low | **Do Not Use** | Composite promoted above real values (V-3) |
| Tier badges | 55 | 45 | 25 | 0 | 85 | 20 | **31** | Very low | **Caution** | 127 tiers, 0.45% median boundary (V-6) |
| Confidence bucket | 45 | 40 | 20 | 0 | 85 | 25 | **32** | Very low | **Do Not Use** | Raised by missing data (V-5) |
| Deep-board ranks (>500) | 50 | 40 | 25 | 0 | 85 | 20 | **32** | Very low | **Do Not Use** | Tail plateau (V-7) |
| TE values | 60 | 40 | 30 | 10 | 80 | 30 | **35** | Very low | **Caution** | Measured curve unreachable (V-4) |
| Luck / power rankings | 60 | 45 | 35 | 0 | 70 | 30 | **35** | Very low | **Caution** | In-progress weeks counted (R-4) |
| Future pick values | 70 | 25 | 20 | 0 | 80 | 15 | **22** | Very low | **Do Not Use** | −18%/−34% vs both markets (T-3) |
| ROS playoff / championship odds | 30 | 45 | 30 | 0 | 60 | 5 | **14** | Not trustworthy | **Do Not Use** | Degenerate out of season (100%/0%); missing team → "Seller" (N-1, N-2) |
| News impact on values | 30 | 30 | 15 | 0 | 70 | 5 | **13** | Not trustworthy | **Do Not Use** | "Released" scored positive; headline moves value ±5% (E-1, E-2) |
| League-adjusted lens | 45 | 35 | 30 | 20 | 60 | 25 | **30** | Very low | **Caution** | Scarcity zero is arbitrary; scales one field only (L-1, L-3) |
| Public trade grades / power / luck | 50 | 35 | 30 | 0 | 70 | 20 | **27** | Very low | **Do Not Use** | Unresolvable = 1.0 → named "fleecing"; multi-season totals (U-1, U-2) |
| `identityConfidence` | 40 | 50 | 20 | 0 | 75 | 15 | **25** | Very low | **Do Not Use** | Means "has an ID", not "matched"; 601/8408 miss rate (Z-4) |
| Playoff odds (in-season, v1 empirical) | 60 | 70 | 55 | 20 | 65 | 50 | **48** | Low | **Caution** | Two engines disagree; hardcoded 6/2 bracket (N-3, N-4, R-5) |
| Offense consensus (top ~300) | 75 | 65 | 55 | 15 | 85 | 60 | **55** | Low | **Supporting** | Double-voting (V-11); no accuracy validation |
| **Raw retail values (KTC / IDPTC)** | 85 | 95 | 80 | 40 | 85 | 75 | **74** | Good but limited | **Primary tool** | Frozen vendor boards indistinguishable from live (O-9) |

---

## 7. Safe / Caution / Do-Not-Use

**Safe as a primary tool (1):** the **raw per-source retail values** (KTC, IDPTradeCalc) as
displayed per-source — with one caveat now established: **you cannot tell from the platform whether
they are current** (Z-2). Every other defect in this audit is downstream of them.

**Use as supporting evidence (3):** top-300 offense consensus ordering · in-season v1 playoff odds
(real 10k-sim Monte Carlo on a genuinely calibrated points model — see §8) · source-spread
diagnostics read strictly as "how much do sources agree", never as confidence.

**Do not use until repaired (~30):** everything scoring <40 in §6 — the trade verdict, trade finder,
trade suggestions, Monte Carlo win probability, future pick values, `/edge` buy/sell, movers, FAAB,
the auction board, Sleeper draft capital, contender score, team phase, ROS direction, **ROS playoff
and championship odds**, **news-driven value adjustments**, trade-history grades, **public trade
grades / power / luck**, insider leads, Sharp Tracker, BDVM's gap columns, confidence badges, tier
badges, deep-board ranks, `identityConfidence`, and the scaffold surface.

---

## 8. Credit Where Due

Three pieces of work in this repo are of a standard the rest should be held to:

- **`src/api/feature_flags.py`** — `_GATE_STATUS` classifies every flag by whether its gate can
  actually execute, re-measured against the real import graph by
  `tests/api/test_feature_flag_reachability.py`. This is the pattern that should be extended to
  the entire analytics surface.
- **`src/league_intel/sim_calibration.py`** — replaced two magic constants (`rosValue / 2.7`
  "tuned by eye" and a CV table citing an unnamed dataset) with a calibration from real stat
  lines scored under this league's own settings, reconciled **1,415/1,415 player-weeks to within
  0.011**. This is the only genuine out-of-sample calibration found anywhere in the repository.
- **BDVM's market isolation** — a structural `MarketIsolationError` rather than a convention, with
  params honestly labelled as priors and unpriced players returned as `unpriced` with a reason.

---

## 9. Remediation Roadmap

Ordered by decision impact × breadth. **⭑ = fixes multiple tools at once.**

### Tier 0 — Hotfixes (specified with exact diffs in §10)
1. **T-2** trade verdict → relative bands.
2. **T-3** stop discounting pick years the vendors already price. ⭑
3. **R-2** exhaustive monotonic ROS ladder.

### Tier 1 — Stop actively inverted advice (all Small)
4. **T-1** define and enforce one give/receive convention across the trade surface. ⭑
5. **S-8** fix the inverted MoversPanel verbs.
6. **D-7** sign-guard the "Best value" backfill rows.
7. **W-1** add the `assetClass` filter to the FAAB pool.
8. **V-4** make `SETTINGS_DEFAULTS.tepMultiplier` `null`. **One-word change that activates a
   shipped, measured, flag-on improvement.** ⭑
9. **B-8** carry `anyProxy` through `buildBdvmIndex`.

### Tier 2 — Restore the safety net (nothing else is trustworthy until monitoring is) ⭑
10. **O-1/O-2** fix the ops alert key; stop recording blocked scrapes as successes.
11. **O-3** derive the partial-scrape guard from the real source registry, not the 2-entry legacy dict.
12. **O-8** restore the raw-source/identity producers **and add an age guard to `_latest_file`** so
    no endpoint can serve an unbounded-age artifact again.
13. **O-4/O-5** fix or delete the four Sharp workflows; invoke `apply_hardening.sh` from deploy.
14. **O-6** consume the Sleeper freshness stamp.
15. **O-9** add a content-hash freshness signal so a frozen vendor is distinguishable from a live one. ⭑
16. **Verify the 2026-07-30 timer fix actually installed the nine timers** (B-1) — until then BDVM,
    signal alerts, custom alerts, playerctx, sharp discovery and reception depth are all
    unconfirmed.

### Tier 3 — Correct the core valuation math
17. **V-1** re-fit the IDP master on the sources that actually use it, **then** re-derive the
    corridor clamp — in that order; expect the whole IDP board to move. *Large.*
18. **S-1/S-2** normalize market-gap by pool depth and compare like-for-like scoring bases. ⭑ (fixes
    `/edge`, `/rankings` Edge column, movers, and the IDP edge)
19. **V-3** never promote an unpriced row's composite into the Value column.
20. **V-5** make missing coverage *lower* confidence; use the value-space statistic the row already
    carries.
21. **V-7** raise or remove the tail clamp (the repo's own backtest says 400); or mark deep ranks
    unranked.
22. **V-11** collapse same-publisher sub-boards to one vote.
23. **V-6** re-derive tier boundaries against a value-magnitude criterion.
24. **V-8** never write the shared rank snapshot on an override build.

### Tier 4 — Consolidate duplicated concepts (one authority each) ⭑
25. Team phase → `roster_intel/window.py`. Replacement level → `league_intel/replacement.py`.
    BUY/SELL → one threshold module imported by both Python and JS. Playoff odds / power rankings
    → pick one engine. Trade grading → one implementation for `/trades` and `/league`.

### Tier 5 — Validation (the systemic gap)
26. **Build the historical snapshot store first** — as-of board values keyed by date. Nothing else
    in this tier is possible without it.
27. **V-2** replace the circular holdout with boards genuinely excluded from the blend, and score
    all eight constants rather than two.
28. **Replace the stability objective with an accuracy objective** — predict realized value change
    over a forward window, temporal split, against the brief's honest baselines (current market
    value; no-change; equal-weight blend; position average).
29. **Only then re-tune** α, percentile N, corridor band, pick discounts, Sharp weights, BDVM priors.
30. **Extend `_GATE_STATUS` to analytics** — a table, re-measured by a test, classifying every
    decision output as validated / unvalidated / dormant.

### Tier 6 — Retire what is dead, and stop describing it as live
31. `src/scoring`'s adjustment/archetype pipeline (imported, never called — Z-6); the FootballGuys
    restoration path; `stamp_bands_on_players` / `rank_history_band` / `ValueBandBadge`;
    `stamp_tiers_on_players`. Delete or wire — but remove them from `CLAUDE.md`'s directory table
    either way.
32. Correct or delete the four documents that would actively mislead a maintainer:
    `docs/status/canonical-source-matrix.md` (Z-7), `docs/idp-ranking-model.md` (X-4),
    `docs/backtest_methodology.md`, and `CLAUDE.md`'s structure section.

---

## 10. Hotfix Pack — exact minimal diffs

**Nothing below has been applied.** This audit remained read-only.

### Hotfix 1 — T-2 relative fairness bands

`frontend/lib/trade-logic.js:1432`:
```js
// AFTER
export const TRADE_NOISE_FLOOR = 150;   // below this, any gap is package noise

/** Verdict from the RELATIVE gap, with an absolute floor.
 *  Band edges are a stated product judgement, NOT calibrated (audit §1.1). */
export function meterVerdict(pctGap, absGap = Infinity) {
  if (absGap < TRADE_NOISE_FLOOR) return { label: "FAIR", level: "fair" };
  if (pctGap < 5)  return { label: "FAIR",        level: "fair" };
  if (pctGap < 15) return { label: "SLIGHT EDGE", level: "slight" };
  if (pctGap < 30) return { label: "UNFAIR",      level: "unfair" };
  return { label: "LOPSIDED", level: "lopsided" };
}
```
`frontend/components/trade/TradeMeter.jsx:40` (`pctGap` already exists at `:39`):
```js
- const verdict = meterVerdict(absGap);
+ const verdict = meterVerdict(pctGap, absGap);
```
`TradeMeter.jsx:130` (multi-team needs a relative basis):
```js
  const worst = Math.max(...nets.map((n) => Math.abs(n)));
+ const grossMoved = flowList.reduce((s, f) => s + (f.given || 0), 0);
+ const worstPct = grossMoved > 0 ? (worst / grossMoved) * 100 : 0;
- const verdict = meterVerdict(worst);
+ const verdict = meterVerdict(worstPct, worst);
```
Also replace the bare `350` literals at `:124`, `:137`, `:141` with `TRADE_NOISE_FLOOR`, and fix
the stale comment at `:127`. **Note:** this does not fix **T-1** (undefined direction), which is a
separate and larger change — ship T-1 first if both are in scope, or the corrected bands will
still be applied to a possibly-inverted winner.

**Test:** verdict identical for `(500,180)` and `(9000,3240)` (both 64%); `(9000,8650)` → FAIR;
`(420,80)` → LOPSIDED.

### Hotfix 2 — T-3 stop double-discounting priced pick years

`src/api/data_contract.py:6003-6033`. The module already tracks which pick rows are clones:
`_SYNTHETIC_FAR_FUTURE_PICK_NAMES` (populated in `_inject_far_future_pick_sources`, `:4154-4231`,
keyed by `_canonical_match_key`).

```python
  for value, row_idx in row_normalized:
      row = players_array[row_idx]
      if row.get("assetClass") == "pick":
+         # Vendors publish a real per-year price for near-future years,
+         # and that price ALREADY encodes the term structure (both
+         # markets price 2027 ABOVE 2026).  Multiplying a decay prior
+         # onto it double-counts in the wrong direction — audit T-3:
+         # 2027 firsts landed 18% and 2028 34% BELOW both markets.
+         # Only rows this pipeline synthesised by cloning a nearer
+         # year need the step-down.
+         is_synthetic = (
+             _canonical_match_key(row.get("canonicalName") or "")
+             in _SYNTHETIC_FAR_FUTURE_PICK_NAMES
+         )
+         if not is_synthetic:
+             out.append((value, row_idx))
+             continue
          year = _pick_year_from_name(row.get("canonicalName") or "")
          mult = _pick_year_discount_for(year, cfg, current_draft_year=cdy)
```
2027/2028 publish at blended market value; 2029 (a clone) keeps its step-down, so V-12 does not
regress. **Caveat for the commit:** V-12 remains open — for synthetic years the multiplier is still
an uncalibrated prior on a cloned price.

**Test:** with the real CSVs as fixtures, assert `2027 Early 1st` and `2028 Early 1st` track the
`ktcSfTep`/`idpTradeCalc` mean within tolerance, and `2029 Early 1st < 2028 Early 1st`.

### Hotfix 3 — R-2 exhaustive monotonic ROS ladder

`src/ros/direction.py:80-115` — replace the gapped chain with a total ordering on playoff odds,
championship odds selecting only *within* a band:

```python
if playoff_odds_pct >= 0.75:
    label, rec = ("Strong Buyer", "Prioritize lineup-anchor upgrades.  Pay up for "
                  "elite starters; avoid hoarding picks.") if championship_odds_pct >= 0.10 else \
                 ("Buyer", "A lock for the playoffs but not yet a title favourite — "
                  "buy the upgrade that raises your ceiling.")
elif playoff_odds_pct >= 0.60:
    label, rec = "Buyer", ("Buy if the cost is reasonable.  Target undervalued "
                           "starters that move your weekly ceiling.")
elif playoff_odds_pct >= 0.45:
    label, rec = "Selective Buyer", ("Target undervalued starters; avoid all-in moves "
                                     "until championship odds rise above 5%.")
elif playoff_odds_pct >= 0.35:
    label, rec = "Hold / Evaluate", ("Genuinely on the bubble.  Avoid extreme buy/sell "
                                     "unless an offer is clearly asymmetric.")
elif playoff_odds_pct >= 0.20:
    label, rec = "Selective Seller", ("Sell older short-term assets if strong offers "
                                      "arrive.  Hold the youth core.")
elif playoff_odds_pct >= 0.10:
    label, rec = "Seller", ("Sell aging win-now players.  Prioritize picks and "
                            "23-or-younger upside.")
else:
    label, rec = ("Strong Seller / Rebuilder", "Sell aging veterans aggressively for "
                  "picks + youth.") if age_heavy else \
                 ("Seller", "Sell win-now assets for picks + youth; the roster is "
                  "already young enough that a full teardown isn't needed.")
```
Also update the docstring at `:62-76`, which documents the defective overlapping spec and asserts
the fall-through is intentional. **Related (not fixed by this diff):** two of the four documented
inputs are inert — `team_ros_strength_percentile` only formats a string, and `roster_age_profile`
is always `{}` because `build_team_directions` is never called with `teams`, so `age_heavy` is
always False. Either wire them or delete them from the signature and docstring.

**Test (the important one):** enumerate `playoff ∈ [0,1]` step 0.01 × `championship ∈ [0,0.30]`
step 0.01; assert every cell yields a known label, the label is monotonically non-increasing on
the contend→rebuild axis as playoff odds fall, and `playoff = 1.00` never yields "Hold / Evaluate".

**Blast radius:** `src/ros/trade_deadline.py:21` → `rosTradeDeadline` → `/league` "Trade Deadline"
tab and `RosTradeFitPanel` on `/trade`. No other consumer.

---

## 11. Recommended Analytical Architecture

| Concept | Single authority | Note |
|---|---|---|
| Player identity | `src/identity/` **with a live report** | Currently unmeasurable (O-8). Ban name-only joins (R-3). |
| Raw market values | `CSVs/site_raw/*` via `_SOURCE_CSV_PATHS` | Add content-hash freshness (O-9). |
| Market consensus | `data_contract.py::_compute_unified_rankings` | The spine; fix V-1/V-5/V-7/V-11. |
| Fundamental value | `src/bdvm/` | Keep market isolation. Never merge into `rankDerivedValue`. |
| Projections (ROS) | `src/ros/` | Must declare horizon + data cutoff on every output. |
| Replacement level | `src/league_intel/replacement.py` | Retire the other three. |
| League adjustment | `src/league_intel/overlay.py` | Already correctly league-scoped. |
| Team phase | `src/roster_intel/window.py` | Retire the other two. |
| BUY/SELL labels | One threshold module, imported by Python **and** JS | Today: four families, four threshold sets. |
| Trade grading | One implementation | Today: `/trades` and `/league` disagree by design accident. |
| Playoff odds / power | Pick one engine | Today: two of each, settings-switched. |
| Risk / uncertainty | A shared `Unpriced` / `Unknown` type | Does not exist — root of pattern §5.1. |
| Historical snapshots | **Does not exist — build it** | Prerequisite for all validation. |

---

## 12. Final Verdict

**Trust right now:** the raw per-source retail values (KTC, IDPTradeCalc). That is the honest list.

**Supporting evidence only:** top-300 offense consensus ordering, ROS playoff odds, source-spread
diagnostics, and `/bdvm` if a snapshot exists.

**Ignore until repaired:** the trade verdict, trade finder, trade suggestions, Monte Carlo win
probability, future pick values, `/edge` buy/sell, movers, FAAB, the auction board, Sleeper draft
capital, contender score, team phase, ROS direction, trade-history grades, insider leads, Sharp
Tracker, BDVM's gap columns, confidence badges, tier badges, and deep-board ranks.

**Five highest-value repairs:**
1. **Stop missing data from becoming an answer.** One shared `Unknown` type that propagates to the
   UI. This single pattern is behind N-2 (the best roster told to sell), W-2, V-3, U-1, E-4, D-3,
   B-7 and V-5 — it is the highest-leverage change in this document.
2. **Relative trade-verdict bands *and* one give/receive convention** — the flagship feature can
   currently name the wrong winner.
3. **Stop discounting pick years the market already prices**, and normalize the market gap by pool
   depth — together these fix the trade calculator, the finder, suggestions, angles, the draft
   board, `/edge`, the rankings Edge column and movers.
4. **Repair the monitoring layer.** Today a preserved last-known-good CSV mints a fresh success
   stamp, blocked scrapes record as successes, and the ingestion alert reads a key that is never
   present — so **no alert fires when the data stops arriving.**
5. **Build the historical snapshot store**, so accuracy can be measured at all.

**How confident should you be in the site's decision intelligence today? Low.** The data plumbing
is genuinely strong — 21 registered sources, a 2-hour refresh, real architectural discipline in the
places listed in §8. But between those inputs and the user sits a decision layer where the flagship
verdict can name the wrong winner, the buy/sell signal flips sign on half the board, the bid
recommender divides by a draft pick, the auction board recommends $229 for a $1 player, a headline
saying a player was *waived* is scored as positive news, the league's best roster is told to sell
because it was missing from a file, and **no output has ever been checked against what actually
happened.**

Two structural facts deserve to outlive the individual findings. First, **the nominal source count
overstates the evidence**: 21 registry entries resolve to ~14 publishers, and two of the five IDP
sources are the same board at ρ≈0.98 — so the IDP anchor is corroborated by its own twin rather
than checked by it. Second, **the only automated quality gate in the repository grades the curves
against boards that are themselves inputs to the blend.** A system cannot validate itself, and this
one has been trying to.

**Trust the inputs. Do not yet trust the conclusions.** The most valuable thing this codebase could
build is not another model — it is the historical snapshot store and an accuracy objective, so the
next version of this audit can be answered with measurements instead of code reading.

---

## 13. Machine-readable output (see also Part B below for the remediation execution plan)

The complete structured result of all 26 subsystem audits — every system, formula, constant,
source and finding with `file:line` evidence — is at
``docs/audits/decision-intelligence-audit-2026-08-04.registry.json``
(807 systems, 562 formulas, 531 findings). It is the source for the registries summarized here and should be carried into the
implementation prompt rather than re-derived.

---
---

# PART B — Remediation Execution Plan: all 43 Critical + 130 High in one pass

## B0. Scope, shape, and the one structural warning

**Scope:** 173 findings (43 Critical, 130 High). Complexity mix as measured across the finding
set: **50 Small, 53 Medium, 25 low, 16 medium, 5 moderate, 3 trivial, 5 Large, 2 Architectural.**
So ~100 are genuinely small and only 7 are large-or-architectural. A single pass is feasible — but
only in the right order.

**The 173 collapse into 9 root changes plus a mechanical tail.** That is what makes this tractable;
fixing each finding individually would be ~173 diffs, most of them re-solving the same problem.

| Root change | Findings it closes | Why it is one change |
|---|---|---|
| **R1** `Unknown` type replacing fabricated defaults | ~45 | Every "missing → 0 / 1.0 / $100 / neutral / clone" is one missing type |
| **R2** Pool-normalized rank space | ~20 | Every cross-source rank comparison shares one bug |
| **R3** One threshold/label module | ~18 | Four BUY/SELL families, two grade scales, split /edge–/rankings bands |
| **R4** Consolidate duplicate authorities | ~25 | Phase ×3, replacement ×4, FAAB ×3, playoff ×2, power ×2, grading ×2 |
| **R5** Hill scale + clamp re-derivation | ~12 | Fit/apply overlap is zero; clamp masks it |
| **R6** Freshness and monitoring truth | ~15 | Stamp-on-preserved-CSV is the single upstream cause |
| **R7** Engine input plumbing | ~20 | Position data, roster coverage, league settings all missing at the boundary |
| **R8** Dead-code removal + flag honesty | ~12 | Same "advertised but unreachable" pattern |
| **R9** Documentation regenerated from code | ~56 (overlapping) | Mechanical once code is correct — must be **last** |

**The one structural warning.** Two changes are coupled: the corridor clamp is currently
*repairing* the Hill-curve scale defect (V-1 — 128/128 clamps bind at the hard cap, all pulling
values **up**). Re-fitting the curve without re-deriving the clamp in the same sequence moves the
IDP board twice, in opposite directions. **Phase 3 must run strictly serially with a measured gate
between each step.** Everything else can be parallelized.

**Assumption stated explicitly:** "one pass" = one branch, one continuous effort, merged as one
release — implemented as stacked commits per phase so a board move remains attributable to a cause.
Shipping all 173 as one unattributable diff is the only variant I would not recommend, and Phase 0
exists specifically so you don't have to.

---

## B1. Phase 0 — Make the pass measurable (blocking prerequisite)

Nothing else starts until this is green. Without it there is no way to distinguish a fix from a
regression across 173 changes.

| # | Work item | Files |
|---|---|---|
| 0.1 | **Golden-board harness.** Build the contract from a frozen input fixture (pin `exports/latest/dynasty_data_2026-08-04.json` + a copy of `CSVs/site_raw/*`) through the real entry point `build_api_data_contract`, and serialize every user-facing number (value, rank, tier, confidence, every label, every signal) to a canonical JSON. Commit the baseline. | new `scripts/golden_board.py`, `tests/fixtures/golden/` |
| 0.2 | **Board-diff reporter.** Given two golden files, report rows changed, \|Δvalue\| distribution (p50/p90/max), rank churn, and **label flips per surface**. This is the gate for every later phase. | new `scripts/board_diff.py` |
| 0.3 | **Un-exempt the CI gate.** A filename-matching rule currently excludes the 33 core-blend tests from the blocking gate (Q-1). Make all tests blocking. | `.github/workflows/pr-validation.yml` |
| 0.4 | **Delete the test that pins a bug.** `frontend/__tests__/dynasty-data.test.js:307` asserts the raw-composite fallback (V-3) as correct behaviour. It must be removed, not edited, or Phase 1.4 cannot land. | that file |
| 0.5 | **Install pytest in the audit/CI image** so the suite is actually runnable (it is not, in this environment). | `requirements-dev.txt`, CI image |

**Gate:** golden baseline committed; `board_diff` returns zero diff against itself; full suite runs
and its result is known (not assumed).

---

## B2. Phase 1 — R1: the `Unknown` type (largest multiplier, ~45 findings)

This is the highest-leverage change in the entire plan. One shared type, applied at ~14 sites,
closes the most pervasive defect class in the codebase — including the worst single finding (N-2:
the league's best roster told to sell because it was absent from a file).

**1.1 Define it.** `src/utils/unknown.py` + mirror `frontend/lib/unknown.js`. Contract:
- never coerces to `0`, `1.0`, `None`-as-zero, or any neutral;
- carries a machine-readable `reason`;
- is **contagious** through arithmetic — any aggregate containing an Unknown is Unknown or
  explicitly excludes it with a recorded count;
- serializes to the API as `null` **plus** a sibling `<field>Unknown: {reason}` so the frontend can
  render *why*, not just a dash.

**1.2 Apply at the named sites** (each is a specific audit finding):

| Site | Today | Becomes | Closes |
|---|---|---|---|
| `src/ros/*` team absent from sim | `0.0` odds → "Seller" | Unknown → **no recommendation** | **N-2, C-5 interaction** |
| `src/trade/waiver.py:195` | unknown budget → `100` | Unknown → refuse to size a bid | W-2 |
| `src/trade/waiver.py:80` | `top_value_in_pool=None` → max bid | required argument | W-2 latent |
| `src/scoring/replacement_level.py:218-220` | unknown slots → `len(group)//2` | Unknown | C-13 |
| `src/public_league/activity.py` | unresolvable asset → `1.0` | Unknown → grade withheld | U-1 |
| `server.py` realized-points | absent scoring → array of `0.0` | Unknown | E-4 |
| `src/api/draft_capital_fallback.py:96-99` | flat `{1:7000,...}` table | Unknown → 503 with reason | D-3, X-5 |
| `data_contract.py:4154-4231` | 2029 clone priced silently | `syntheticFrom: 2028` stamped + rendered | V-12 |
| `src/bdvm/` single-source | `σ_source = 0` | prior σ from params | B-7 |
| `data_contract.py:1893-1903` | missing sources **raise** confidence | missing sources **lower** confidence; `softFallbackCount` becomes an input | V-5 |
| `frontend/lib/team-phase.js` | unpriced dropped from team total | Unknown → team total flagged incomplete | C-6 |
| `src/ros/` fantasyProsRosIdp | 13 players silently score 0 | Unknown + surfaced | N-6 sibling |

**1.3 Kill the composite fallback.** `frontend/lib/dynasty-data.js:1008`
(`full: Math.round(backendValue || rawValues.full)`) → never promote a raw scraper composite into
the Value column. 260 rows affected, 158 currently rendering above the deepest genuinely-priced
player. **Closes V-3.** (Requires 0.4 first.)

**1.4 Render rule.** Unknown renders as `—` with a reason tooltip, **sorts last in every direction**,
and is excluded from every aggregate with the exclusion counted and shown.

**Gate:** `board_diff` vs baseline. Expect: 260 Value-column rows to change, confidence buckets to
move down on thinly-covered rows, and a set of recommendations to *disappear* rather than change.
Any recommendation that changes from one confident answer to a **different** confident answer is a
bug in this phase.

---

## B3. Phase 2 — R2/R3: shared primitives

**2.1 Pool-normalized rank space.** New `src/api/rank_space.py` + `frontend/lib/rank-space.js`.
Every cross-source rank comparison routes through it — raw ordinals from pools spanning 50–900 are
never compared again.
- `_compute_market_gap` (`data_contract.py:2789-2796`) — **and** split TE-premium vs non-TEP bases
  before comparing, or 36/36 TEs stay SELL. **Closes S-1, S-2.**
- ROS `team_strength.py:157` per-source board-size normalization. **Closes N-5.**
- Feeds Phase 3.1.

**2.2 One threshold module.** `config/thresholds.json` as the single source, with generated Python
and JS constants (parity test in CI, modelled on the existing
`tests/api/test_source_registry_parity.py`, which demonstrably works).
**Closes S-4, S-5, S-12, T-12, U-1 band half, and the /edge–/rankings disagreement.**

**2.3 One fairness function.** Relative bands + absolute noise floor (hotfix diff already specified
in §10). Used by `TradeMeter`, the waivers meter, `/trades`, and `/league`. **Closes T-2, U-1 grade
half, T-12.**

**2.4 One give/receive convention.** A typed `TradeSide { gives, receives }` replacing the untyped
`sides[i].assets`, enforced at every producer: `trade-logic.js`, `trade-sections.jsx`,
`MultiTradeFlow.jsx`, `/trades` share links, `/arbitrage` share links, the simulator hand-off.
**Closes T-1 and the share-link inversion.** *This is the single riskiest change in the plan* — the
two conventions are currently both correct-looking. Land it early, with the golden harness watching,
and add a property test asserting `given(A) == received(B)` for every generated trade.

**Gate:** `board_diff` should show **zero value change** and large **label** change. Any value
movement in this phase is a bug.

---

## B4. Phase 3 — R5: the value pipeline (STRICTLY SERIAL)

Each step re-measures before the next begins. This is the coupled region.

| Step | Change | Expected measurable outcome |
|---|---|---|
| **3.1** | Re-fit Hill masters on the sources that actually consume them. Root cause: the fit assigns IDP scope to IDPTradeCalc + DraftSharks-IDP, but `_curve_for_source` routes both to GLOBAL — **overlap is zero**. | IDP master vs IDP market median ratio moves from **0.48 → ~1.0** |
| **3.2** | Re-derive the corridor clamp against the corrected scale. | Clamp binding drops from **128/128 at the hard cap** to near-zero. **If it still binds on >10% of IDP rows, 3.1 is wrong — stop and re-fit.** |
| **3.3** | Re-measure Hampel. | `idpTradeCalc` ejection drops from **28.0% → <5%** |
| **3.4** | Pick-discount gate (hotfix §10.2) | 2027 firsts −18% → ~0%; 2028 −34% → ~0%; 2029 still discounted |
| **3.5** | `SETTINGS_DEFAULTS.tepMultiplier: 1.15 → null` | Mid/low-value TEs reprice **+10% to +78%**; ADR-015 curve becomes reachable |
| **3.6** | Percentile tail 500 → 400, or mark deep rows unranked | 443 zero-information votes resolved |
| **3.7** | Publisher dedup: collapse FantasyPros ×3, DLF ×4, Flock ×2, DraftSharks ×2 to one vote each; down-weight `idpShow` given ρ≈0.98 with `idpTradeCalc` | Effective source count becomes honest (21 → ~14, IDP 5 → ~4) |
| **3.8** | Two-way boost routed through the pipeline instead of overriding it | Travis Hunter's +115% override removed |
| **3.9** | Tier boundaries on value magnitude, not rolling-median gap ratio | 127 tiers → a defensible count |
| **3.10** | `_stamp_rank_changes`: never write the shared snapshot on override builds | One user's slider stops rewriting everyone's arrows |

**Gate after each step:** `board_diff`. **Expect a large, one-time, intended board move** — the IDP
half especially. Record the diff per step; that record is what makes the release explainable.

---

## B5. Phase 4 — R4: consolidate duplicate authorities (~25 findings)

For each: keep one, delete the others, make the survivors *presenters* of the authority.

| Concept | Keep | Delete / convert | Closes |
|---|---|---|---|
| Team phase | `src/roster_intel/window.py` (only one modelling uncertainty) | `frontend/lib/team-phase.js` classifier; `ros/direction.py` becomes a presenter | C-6, R-3, /phases-vs-/gameplan contradiction |
| Replacement level | `src/league_intel/replacement.py` | `bdvm/replacement.py`, `scoring/replacement_level.py`, `league_comparison/metrics.py` consume it | C-13 |
| FAAB | one implementation | the 3 divergent ones (bid desk, client hint column, waiver.py) | W-1, W-3 |
| Playoff odds | one engine | retire the other; remove the settings toggle | N-4, R-5 |
| Power rankings | one engine | retire the other | R-5, U-2 |
| Trade grading | one implementation | `/trades` and `/league` share it | T-12, U-1 |
| BUY/SELL | Phase 2.2 module | the 4 label families | S-12 |

---

## B6. Phase 5 — R7: engine correctness (the long tail, parallelizable)

Grouped by engine; all independent of each other once Phases 1–4 land.

**5.1 Trade finder** — plumb position data (T-4), re-enable the IDP warning (T-5), apply VA
symmetrically to both sides (T-6), guard the 1-for-N direction now producing 98% of output (T-7),
rebalance the 93/7 score (T-8), read blend count not scraper site count (finder confidence tier).

**5.2 Trade suggestions** — full roster visibility, currently 10–40% (T-9); league-aware lineups at
all nine hardcoded call sites; reconcile `giveTotal`/`receiveTotal`/`gap` (VA-adjusted vs not).

**5.3 Monte Carlo** — per-asset bands from real dispersion (`hillValueSpread` already exists on the
row) or **delete the feature**; restore the mandatory disclaimer; fix picks drawn 12% narrower
(T-10, X-6).

**5.4 Draft/auction** — budget- and slot-aware bid (D-1); fix the diverging inflation denominator
(D-2); Sleeper capital 503 + real slot mapping (D-3, D-4); vendor dollar row-count normalization
(D-6); sign guard on backfill rows (D-7); remove the 6-pick clamp (D-8); make "Next Best Targets"
either a real EV model or renamed (D-5).

**5.5 Waivers/FAAB** — `assetClass` filter on the pool (W-1, the ~2.4–2.6× understatement); anchor
the bid to replacement value not wire-relative share (W-2); collapse the position-calibration
1.12× spread (server-inline finding).

**5.6 ROS** — exhaustive monotonic ladder (hotfix §10.3, R-2); read the league's real bracket
instead of hardcoded 6/2 (N-3); genuine last-known-good on adapter failure (N-6); make
`freshness_multiplier`/`staleFlag` reachable (N-7); non-default leagues stop reading the default
league's strength file (ROS finding).

**5.7 League-adjusted lens** — fix the arbitrary log-rank zero so factors stop moving with source
universe size (L-1); scale **all** value fields not just `rankDerivedValue` (L-3); per-league TE
basis (L-5); make `lineupScarcity` a VORP argument rather than a uniform lift (L-4); gate the
overlay off for leagues whose contract isn't loaded (L-7).

**5.8 News** — fix polarity so "released"/"waived" are not positive (E-2); remove the direct ±5%
value discount or gate it behind explicit human confidence (E-1); close the sigma channel into BDVM
fundamentals (E-3); make `value_crosses` a real crossing test with memory (E-5, custom alerts).

**5.9 BDVM** — restore the 6 dropped reception-band rules (B-2, ~15% WR bias); make `STRONG_BUY`
reachable and `STRONG_SELL` respect its threshold (B-3); invert `liquidity` semantics (B-4); anchor
rookie-pick values to the calibrated scale (B-5); include picks in strategy capitals (B-6); carry
`anyProxy` into `buildBdvmIndex` (B-8, hotfix-sized).

**5.10 Sharp** — renormalize weights around the structurally-zero `rosterQuality` (P-1); break the
qualify→collect→qualify loop (P-2); handle cohort-internal trades (P-3); stop counting season-rows
as independent leagues (P-5); separate provisional FFPC managers from "Sharp managers" (P-6).

**5.11 Intel** — trade count per-trade not per-asset (I-1); activate the roster-clog guard (I-2);
give positional need magnitude (I-3); unsaturate the value-match term (I-4); publish a range and
an error rate or stop rendering a 0–100 score (I-5).

---

## B7. Phase 6 — R6: monitoring truth (~15 findings)

Do this *before* the release, not after: it is what tells you the release worked.

- **6.1** Stamp `*_last_success` only on a **real** fetch — a preserved last-known-good CSV must not
  mint a fresh stamp (**Z-2**, the upstream cause of the whole freshness class).
- **6.2** Add a **content hash** so a frozen vendor board is distinguishable from a live one (O-9).
- **6.3** Staleness **down-weights** a source instead of only reporting it (Z-3).
- **6.4** Fix the ops alert key that is never present (O-1); stop recording blocked scrapes as
  successes (O-2); derive the partial-scrape guard denominator from the real 21-source registry
  rather than the 2-entry legacy dict (O-3).
- **6.5** Fix or delete the four Sharp workflows that `git add` a gitignored path and burn 40
  minutes per push (O-4); invoke `apply_hardening.sh` from deploy (O-5); consume the Sleeper stamp
  (O-6); make the backup probe see both systems (O-7).
- **6.6** Restore the raw-source and identity producers, and **add an age guard to `_latest_file`**
  so no endpoint can serve an unbounded-age artifact again (O-8/C-4).
- **6.7** `/rankings` "updated Xm ago" reports **data-fetch** time, not contract-build time (Z-8).
- **6.8** Identity: make `identityConfidence` mean "matched", not "has an ID" (Z-4); require
  `position` in the fuzzy fallback or raise its threshold (Z-5).

---

## B8. Phase 7 — R8/R9: dead code, then documentation (must be last)

**7.1 Delete or wire, then remove from `CLAUDE.md`'s directory table either way:** the
`src/scoring` adjustment/archetype pipeline (~600 lines, imported and never called — Z-6);
`stamp_bands_on_players`; `rank_history_band`; `ValueBandBadge`; `stamp_tiers_on_players`; the
FootballGuys restoration path.

**7.2 Regenerate the explanations from code** — this is why docs come last:
- `/rankings` methodology panel generated from the live constants (X-1 — it currently publishes a
  curve that exists nowhere);
- `/api/data` self-description generated from `_RANKING_SOURCES` (X-2, X-3);
- delete or rewrite `docs/status/canonical-source-matrix.md` (Z-7), `docs/idp-ranking-model.md`
  (X-4, 0/740 rows match), `docs/backtest_methodology.md`, and `CLAUDE.md`'s structure section
  (13 missing subsystems, 15 missing pages).

**7.3 Extend the `_GATE_STATUS` pattern to analytics** — a table, re-measured by a test, classifying
every decision output as validated / unvalidated / dormant. This is the mechanism that stops
Findings X-* and Z-6 recurring, and the repo already proves it works for feature flags.

---

## B9. Phase 8 — close the systemic gap (starts in parallel, finishes after)

The 173 findings do not include "no output is validated" as a line item because it is the
*condition* the audit found. Fixing 173 bugs without this leaves the platform correct-by-inspection
and still unvalidated.

- **8.1** Historical snapshot store — as-of board values keyed by date. **Start on day 1**; it only
  records, so it blocks nothing and every day of delay is a day of lost data.
- **8.2** Replace the circular holdout with boards genuinely excluded from the blend (V-2), and
  score **all eight** production constants rather than two.
- **8.3** Replace the stability objective with an accuracy objective — realized value change over a
  forward window, temporal split, against the audit's honest baselines (current market value,
  no-change, equal-weight blend, position average).
- **8.4** Only then re-tune α, percentile N, corridor band, pick discounts, Sharp weights, BDVM
  priors.

---

## B10. Ordering constraints (the hard DAG)

```
Phase 0  ─────────────────────────────────────────────► blocks everything
Phase 1 (Unknown) ──────► blocks Phase 3, Phase 5
Phase 2.1 (rank space) ─► blocks Phase 3.1
Phase 3.1 → 3.2 → 3.3    STRICTLY SERIAL, measured gate between each
Phase 2.2/2.3/2.4 ──────► blocks Phase 4, Phase 5 label work
Phase 4 ────────────────► blocks Phase 5.2, 5.6, 5.7
Phase 6 ────────────────► before release (it verifies the release)
Phase 7 ────────────────► LAST (docs describe the finished code)
Phase 8.1 ──────────────► START DAY 1, parallel to everything
```

Phases 5.1–5.11 are mutually independent and are where parallelism pays.

---

## B11. Verification

**Per phase:** `scripts/board_diff.py` against the previous phase's golden file, with an explicit
expectation recorded *before* running it. A diff that does not match the expectation stops the
phase.

**Expected intended movements** (so they are not mistaken for regressions):
- Phase 1: 260 Value-column rows; confidence buckets fall on thin rows; some recommendations vanish.
- Phase 3.1–3.3: **large IDP repricing** — the headline movement of the release.
- Phase 3.4: 2027 picks +22%, 2028 +52% relative to today's published values.
- Phase 3.5: mid/low TEs +10% to +78%.
- Phase 2: labels change, **values must not**.

**Release gate — all must hold:**
1. Full suite green with the CI exemption removed (0.3).
2. `meterVerdict` property test: identical verdict for `(500,180)` and `(9000,3240)`.
3. Trade-side property test: `given(A) == received(B)` for every generated trade.
4. ROS enumeration test: no `(playoff, championship)` cell reaches a catch-all; label monotonic in
   playoff odds.
5. Corridor clamp binds on <10% of IDP rows.
6. No endpoint serves an artifact older than its configured max age.
7. Every "recommendation" surface can return **"insufficient evidence"** and at least one test
   proves it does.
8. Grep gate: zero remaining `|| 0`, `or 0.0`, `or 100`, `or 1.0` coercions on a decision path
   (enforced as a lint rule, not a review convention).

---

## B12. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase 3 moves the board more than expected and users notice | **High — it is intended** | Ship with a changelog naming the IDP repricing; keep the pre-release golden board queryable for a week |
| 2.4 (give/receive) inverts something not covered by tests | Medium | Property test + land it early with the harness watching; it is the riskiest single change |
| Re-fit (3.1) does not converge to ratio ≈1.0 | Medium | 3.2's binding rate is the tripwire; stop and re-fit rather than proceeding |
| Unknown propagation empties a surface entirely | Medium | Every surface needs an explicit empty state before Phase 1 lands, not after |
| Doc regeneration drifts again | Medium | 7.3 makes it test-enforced rather than convention |
| Scope creep from the 358 Medium/Low findings | High | Explicitly out of scope; re-run the audit after this pass |

**Not in scope:** the 358 Medium/Low/Informational findings. Several will be closed incidentally by
R1–R9; re-run the audit afterward rather than adding them now.

## B13. Honest assessment of "one pass"

This is a large program — roughly **60–80 files across backend and frontend**, and the two
Architectural items (8.1 historical store, 8.3 accuracy objective) are genuinely new subsystems
rather than fixes. Phases 0–7 are the 173 findings; Phase 8 is the reason they happened.

The plan is achievable in one pass **because** ~100 of the 173 are Small and cluster into 9 root
changes. The failure mode is not difficulty — it is doing Phase 3 out of order, or doing any of it
without Phase 0.
