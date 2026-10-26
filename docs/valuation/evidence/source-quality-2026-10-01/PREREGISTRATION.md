# Preregistration — leakage-safe source-quality evaluation and source-weight challengers

**Batch 3 Units B + C** (`docs/EXECUTION_PLAN.md` → "Valuation Trust Program — Batch 3").
Committed in its own commit BEFORE any candidate score or any real-data quality metric is
generated. The result artifact records this file's sha256 and commit; the evaluator
(`scripts/source_quality_eval.py`) refuses to score candidates when this file is missing,
uncommitted or modified.

Evaluator code frozen for this run at commit `3230b8364` (`src/source_quality/`,
`scripts/source_quality_eval.py`). Any later change to that code is disclosed in the result
(`pins.sourceQualityChangedSincePrereg`).

Status of every candidate: **SHADOW**. Nothing here changes a production weight, flag or
value. A candidate that meets every gate is eligible for independent review and, only then,
the model-registry / feature-flag promotion path with a before/after board, rollback and an
ongoing shadow comparison (Section N). Near-ties keep the incumbent. Gates are never lowered.

## 0. Disclosed exploratory work done before this document

1. **Data readiness** (counts only): the git history of `CSVs/site_raw/*.csv` for the 21
   census-eligible sources — distinct published versions, first/last dates, median rows (§3).
2. **Code tests on synthetic panels** with a known lead/lag structure (no real data).
3. **One override-path smoke** on the latest payload with an ARBITRARY, non-learned weight
   (`dlf` × 1.1) to exercise the impact code. It showed that changing any offense family's
   weight moves current-year slot picks through the rookie-pool tether. That observation
   shaped the picks rule in G2 below (market-priced pick rows, not tethered ones). It is not a
   candidate score and no learned weight existed at the time.

No lead/lag, stability, agreement or candidate statistic on real data had been computed when
this file was committed.

## 1. Audit: the existing dynamic-weights path (not activated, not wired)

`src/backtesting/dynamic_weights.py` + `scripts/refit_source_weights.py` +
`src/backtesting/correlation.py`, behind the `dynamic_source_weights` feature flag.

What it does: for each source keep only the **most recent** rank per player
(`_load_source_ranks`), Spearman-correlate it with **season realized fantasy points**
(`score_source`), require 40 common players, map rho through a shifted softmax
`exp(max(0, rho + 1))` with a 0.05 floor, EWMA-smooth (alpha 0.25) against the prior weights
file, and auto-approve unless any source drifts more than 15 %.

What it actually is in production: **inert.** The flag defaults off and gates nothing —
`src/api/feature_flags.py` classifies it `NO_GATE` and notes `harness.py` "calls itself
'flag-gated … implicitly', which is an accurate description of not being flag-gated". No
code in `src/api/data_contract.py` reads `config/weights/dynamic_source_weights.json`; its
inputs (`data/source_rank_history.jsonl`, `data/realized_points_history.jsonl`) do not exist
in this checkout.

Why it is insufficient (and must not be activated — Section N forbids it in this batch):

| defect | consequence |
|---|---|
| uses the most recent rank, not the rank published BEFORE the outcome | leaks the future: a rank published after the games is scored against those games |
| one target: season realized points | equates dynasty value with one season's production; a 22-year-old rookie and a 30-year-old with the same season score identically (fundamental foresight is a secondary diagnostic, never the definition) |
| no leave-family-out | correlated sources (KTC Crowd, Fantasy Navigator) are each rewarded for the same evidence; no family handling at all |
| per-SOURCE weights | a provider publishing three boards can triple its authority |
| softmax of rho with no uncertainty | no standard error, no shrinkage; 40 players can move a weight |
| one-period fit, no out-of-sample test, no bootstrap | in-sample fit presented as accuracy |
| auto-approval on a drift threshold | self-promotion; violates champion ≠ challenger |
| weights sum to 1 across sources | collides with the live architecture, where base weight multiplies freshness × health × coverage and the family cap applies after |

## 2. Central question

> When source S says X at time T, how informative is that evidence about what we are trying
> to estimate, compared with the other evidence available at T?

Point-in-time only. No future information in any feature or training observation.

## 3. Data (as published, point in time)

* **Evidence**: every committed version of each eligible source's own CSV, from
  `git log -- CSVs/site_raw`. A version is *known at* its committer time (an upper bound on
  when it existed — conservative). One version per UTC day (the last), lossless for a daily
  grid. A version whose parsed content repeats its predecessor is dropped (nothing new was
  learned). The temporal ledger (`--ledger`, production box only; it holds only the 4
  value-direct keys) is accepted as an optional extra source of versions; this run uses the
  repository history.
* **Never reconstructed**: observations are parsed from the committed bytes. No archived board
  is rebuilt with today's Hill curve, pipeline or identity resolver and called historical. The
  only rebuild in this unit is the pipeline-space impact (§8), labelled as a counterfactual on
  ONE day's inputs.
* **Eligibility = the census** (`docs/sources/census/CENSUS_2026-10-01.json`): VOTING, game type
  verified DYNASTY (unverified fails closed), out-of-sample data prerequisites met. 21 sources,
  14 families of which 13 have evaluable history (idpShow's only voter, `idpShowCombined`,
  has one archived version and is excluded). Excluded: idpShowCombined (single version), ktc,
  ktcSfTep (game type not verified dynasty), ktcCrowdTradesSfTep (benchmark; KTC Market is never
  a target), dlfValuesSfTep, dlfValuesSfTepPicks, draftSharksRosIdp, draftSharksRosSf (redraft),
  idpShow, signalsDynasty, signalsIdpDynasty.
* **Scale**: rank within universe (OFFENSE / IDP / PICK), ties averaged, compared as
  `-log(rank)`. Rookie-only boards (dlfRookieSf, dlfRookieIdp, flockFantasySfRookies) are not on
  the overall scale and contribute no evidence in this version (declared).
* **Identity**: deterministic `resolve_canonical_name` + universe. A multi-universe source
  without a position column (IDP Trade Calculator) is classified per date by co-observation in
  single-universe sources at that same date; names seen in both universes (AMBIGUOUS) or neither
  (UNCLASSIFIED) are withheld and counted.
* **Family score**: the MEAN of its members present (never the sum).

Readiness (exploratory, counts only):

| source | family | universes | versions | first | last | median rows |
|---|---|---|---|---|---|---|
| dlfSf | dlf | OFFENSE | 45 | 2026-04-21 | 2026-09-30 | 281 |
| dlfIdp | dlf | IDP | 23 | 2026-04-16 | 2026-09-24 | 172 |
| draftSharks | draftSharks | OFFENSE | 99 | 2026-04-19 | 2026-09-30 | 447 |
| draftSharksIdp | draftSharks | IDP | 56 | 2026-04-19 | 2026-09-30 | 409 |
| dynastyDaddySf | dynastyDaddySf | OFFENSE | 168 | 2026-04-16 | 2026-09-30 | 365 |
| dynastyNerdsSfTep | dynastyNerdsSfTep | OFFENSE | 8 | 2026-04-16 | 2026-09-11 | 294 |
| fantasyCalc | fantasyCalc | OFFENSE | 141 | 2026-05-13 | 2026-09-30 | 398 |
| fantasyNavigatorSf | ktcCrowd | OFFENSE | 10 | 2026-07-26 | 2026-09-29 | 768 |
| ktcCrowdSfTep | ktcCrowd | OFFENSE, PICK | 22 | 2026-09-09 | 2026-09-30 | 500 |
| ktcTradesSfTep | ktcTrades | OFFENSE, PICK | 22 | 2026-09-09 | 2026-09-30 | 500 |
| fantasyProsSf | fantasyPros | OFFENSE | 63 | 2026-04-16 | 2026-09-30 | 540 |
| fantasyProsFitzmaurice | fantasyPros | OFFENSE | 9 | 2026-04-21 | 2026-09-01 | 299 |
| fantasyProsIdp | fantasyPros | IDP | 9 | 2026-04-16 | 2026-09-23 | 195 |
| flockFantasySf | flockFantasy | OFFENSE | 138 | 2026-04-17 | 2026-09-30 | 437 |
| idpTradeCalc | idpTradeCalc | OFFENSE, IDP, PICK | 25 | 2026-04-16 | 2026-09-23 | 900 |
| otcffbSf | otcffbSf | OFFENSE | 128 | 2026-05-15 | 2026-09-29 | 451 |
| pfkDynasty | pfkDynasty | OFFENSE | 26 | 2026-07-26 | 2026-09-30 | 496 |
| yahooBoone | yahooBoone | OFFENSE | 9 | 2026-04-19 | 2026-09-03 | 440 |
| (rookie-only, not scored) dlfRookieSf / dlfRookieIdp / flockFantasySfRookies | | | 47 / 21 / 77 | | | |

**Span: 2026-04-16 → 2026-09-30 = 168 days.** The KTC families exist only from 2026-09-09
(ktcCrowd from 2026-07-26 through Fantasy Navigator). IDP has 4 families.

## 4. Horizons (frozen)

Lookback for "a move" k = 7 days. Horizons h ∈ {**7, 21, 42**} days (short / medium / long).
With k = 7 the 42-day horizon leaves origins 2026-04-23 → 2026-08-19 (~118 days); anything
longer would leave too few independent blocks. **Primary horizon for every challenger gate:
21 days.**

## 5. Targets (leave-the-evaluated-family-out)

* Every target excludes the evaluated family (B10 family via `correlation_group_for`, as
  recorded in the census).
* **Lead/lag** is cross-fitted: the other families are split into halves A and B (8 seeded
  random splits, pooled); predictor `g = X_F(T) − C_A(T)`; target `C_B(T+h) − C_B(T)`; controls
  `C_A(T) − C_B(T)` and `C_B(T) − C_B(T−k)`; OLS demeaned within origin date. β_gap = share of
  F's disagreement the independent market closes within h. Because `g` contains no B noise,
  regression to the mean in the target cannot manufacture lead.
* **KTC dependence**: every lead estimate at the primary horizon is repeated with targets
  excluding `{ktcCrowd, ktcTrades}` and with targets excluding every family sharing a recorded
  lineage relation (proven/measured/suspected) with a KTC key; and with targets excluding the
  evaluated family's OWN recorded lineage partners. KTC Market is never a target.
* **Challenger target**: for each held-out family G, a board blended from the OTHER families'
  observations at T is scored against G's own published board at T+h. G is never in the
  predictor, so no family can be rewarded for predicting itself.

## 6. Metrics (each answers one question)

1. MARKET LEAD/LAG — β_gap (§5), per family × universe × horizon.
2. STABILITY/NOISE — self-reversal `−Σ Δ1Δ2 / Σ Δ1²` over moved cells (Δ1 = own k-day move,
   Δ2 = own next-h move); move confirmation (slope of the LFO consensus' next-h move on Δ1,
   controlling for the consensus' own k-day move); abandoned-move rate (moves ≥ log 1.25 that
   the family reverses by ≥ half while the consensus does not follow by ≥ half).
3. EVENT RESPONSIVENESS — events: 7-day LFO consensus moves at or above that universe's 98th
   percentile, one per asset per 14 days; timing = day the family first covers half the event
   move vs the day the consensus does, from a baseline 14 days before the event end, followed
   14 days after. Capture rate + mean lead days when captured. Always read beside the
   abandoned-move rate.
4. FUTURE INDEPENDENT-MARKET AGREEMENT — `|X_F(T) − C_{−F}(T+h)|` minus the mean of that
   quantity over every family on the same cell (peers on exactly the players F covers). This
   is agreement with future independent evidence; it is NEVER called accuracy.
5. TRANSACTION FIT — not computable: the Unit I completed-trade ledger (deduplicated,
   topology-validated) does not exist on this branch. Seam: `metrics.transaction_fit`.
6. FUNDAMENTAL FORESIGHT — secondary diagnostic only, never the definition of value; not run:
   the 2026 season has ≤ 4 completed weeks and nflverse weekly stats are not cached here.
   Seam: `--realized`.

**Freshness separation.** Base quality is measured only on dates when the family's freshest
member version is at most `max(7 days, 2 × expected cadence)` old. Staleness is the freshness
factor's job; judging base quality on stale observations would collapse "fresh" and
"historically informative" into one number. The unconditioned lead is reported as a
sensitivity.

**Uncertainty.** Every estimate: seeded (20261001) date-block bootstrap, 14-day blocks,
400 replicates, only origins with evidence; point, SE, 90 % CI, block count.

## 7. Candidates (predeclared, small)

Architecture unchanged: **BASE** × freshness × health × coverage, then the family cap. Every
candidate changes ONLY the base factor, at FAMILY level, copied to every registered member
(the production cap is the largest member base weight present, so a family's authority equals
its family weight however many products it publishes).

Shared mapping from a family quality estimate (point q, SE s, training blocks b):
`z = (q − mean q)/sd q`; `τ² = max(0, var q − mean s²)`; `B = τ²/(τ² + s²)`;
`w = 1 + clip(0.10 · B · z, −0.25, +0.25)`. A family with fewer than 4 training blocks, fewer
than 3 usable families, or τ² = 0 → every weight 1.0 (the champion).

* **Champion** — equal authority among independent eligible families (every base weight 1.0;
  the live registry).
* **C1 conservative reliability** — q = future independent-market agreement (metric 4) at h = 21,
  inverse-variance pooled over OFFENSE and IDP.
* **C2 asset-class-aware reliability** — C1 computed separately per universe; offense-only keys
  take the offense family weight, IDP-only keys the IDP weight, a key covering both the pooled
  weight. **Runs only if** every one of ≥ 4 families per universe has ≥ 200 freshness-eligible
  cells and ≥ 6 evidence blocks at h = 21 on the full window (counts only). Horizon-awareness is
  NOT a servable candidate (one board serves every horizon); horizon-specific estimates are
  reported as diagnostics. Picks are never stratified (insufficient).
* **C3 lead/lag-aware authority** — q = β_gap (metric 1) at h = 21, pooled over universes.

Never tuned toward KTC Market. No candidate is promoted by this unit.

## 8. Evaluation

**Harness space (primary, gating).** Purged walk-forward: folds start 2026-06-01 and every
14 days after; a fold tests its 14 origins (only origins with T + 21 ≤ 2026-09-30); weights for
the fold are learned from a matrix cut at the day before the fold, so every training target
window closed before the fold began. For each test origin, universe and held-out family G:
predictor = weighted mean of the other families' `-log(rank)` (champion: unweighted), present
for ≥ 2 families; target = G's board at T + 21. Metric: mean absolute log-rank error (MALE),
paired champion vs candidate on identical cells. Δ = champion MALE − candidate MALE
(> 0 = candidate closer to independent future evidence).

Strata: OFFENSE, IDP; elite / core / depth by the champion board's rank at T (offense ≤ 36 /
37–150 / > 150; IDP ≤ 24 / 25–100 / > 100); sparse (≤ 3 families in the predictor); rookies
(on a rookie-only board as of T); in-season (origins ≥ 2026-09-10). Target variants: all
targets; no KTC targets; no KTC-lineage targets. Picks: not evaluated (§9).

**Pipeline space (impact, not a score).** The latest payload rebuilt through today's canonical
pipeline via `value_replay.build({"weights": …})` → `source_overrides` → `_compute_unified_rankings`,
once per candidate (final weights learned on the whole window, purged). Reported: rows changed
by group, rank-band moves, top-24 changes, largest moves, market-priced and tethered pick rows,
sparse rows, rookies, family vote-share concentration and row HHI, and the board change when
each family disappears (champion vs candidate). It is also checked that an all-1.0 override
reproduces the champion board byte-for-byte.

## 9. Promotion gates (derived from the declared target and the observed baseline variance)

For each candidate, on the primary horizon:

* **G1 aggregate** — Δ > 0, its 90 % CI lower bound > 0, AND Δ ≥ SE of the champion's own MALE
  (the gain must exceed the sampling noise of the baseline metric itself).
* **G2 broad improvement** — for each REQUIRED stratum {OFFENSE, IDP, elite, sparse}: evaluable
  (≥ 200 cells and ≥ 4 blocks) and 90 % CI lower bound of Δ ≥ −SE(champion MALE in that stratum).
  Other strata (core, depth, rookie, in-season) are judged the same way when evaluable and
  otherwise reported only. **Picks**: pick markets cannot be evaluated (KTC pick families from
  2026-09-09 only; IDP Trade Calculator pick rows unmoved since July), so a candidate passes the
  picks requirement only if it changes NO market-priced pick row (provenance
  `direct_market_blend`, `derived_year_step`, `derived_round_step`, `derived_uniform_tier_ev`)
  on the latest board; otherwise picks are missing evidence.
* **G3 KTC / lineage sensitivity** — G1's CI lower bound > 0 also with no-KTC targets and with
  no-KTC-lineage targets.
* **G4 structural** — every weight finite, within [0.75, 1.25], family-level (enforced by
  construction and by tests; a violation is a refusal, not a result).
* **G5 sample adequacy** — ≥ 6 out-of-sample date blocks in the aggregate.

Disposition: any evaluable gate failed → `DOES_NOT_MEET_PREREGISTERED_GATE`; otherwise any
gate unevaluable → `INSUFFICIENT_EVIDENCE` (with the exact missing evidence); otherwise
`MEETS_PREREGISTERED_GATE`. Equal weights remaining preferable is a successful result.

## 10. Known limitations, declared before results

* 168 days of history; the KTC families have 3 weeks; most of the window is the offseason and
  the NFL draft; the test window (June → early September) is preseason-heavy.
* Harness space blends with a weighted MEAN of log-ranks, not the production Hill / trimmed
  mean-median; it measures the information in the weights, the pipeline impact is reported
  separately.
* Future independent-market agreement rewards centrality as well as foresight; C3 and the
  lead metric exist to separate "central" from "early".
* Commit time bounds availability from above; same-day vendor timing finer than a day is not
  resolved.
* Rookie-only boards and picks are not evaluated; transaction fit and fundamental foresight are
  missing evidence.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
