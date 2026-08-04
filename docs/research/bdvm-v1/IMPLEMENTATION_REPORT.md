# BDVM v1 Integration — Implementation Report

Living report required by the master integration prompt (§20).
Status date: **2026-07-27** (second pass — completion sweep).
Branch: `claude/fully-implemented-riu0zp`.

> **Second-pass addendum.** After the initial integration (sections
> below), the remaining-work items that are implementable without
> waiting for calendar time were implemented and live-verified:
>
> 1. **Structured event system (§7)** — closed 18-type ontology
>    (`config/bdvm/event_types_v1.json`), confidence/reliability/decay
>    scaling, speculation-widens-σ-only rule, reflected-event skip,
>    module-targeted impacts through `PlayerInput` event hooks
>    (`src/bdvm/events.py`; events load from `data/bdvm/events/<season>.json`).
> 2. **Player context** (`src/bdvm/context.py`) — nflverse id-map
>    (birth date → age fallback, overall draft pick → capital score,
>    rookie season → NFL season) + career loads (touches/targets/
>    dropbacks from weekly stats, defensive snaps from snap counts).
>    Live: 721 of 727 priced players context-enriched, 519 with real
>    draft capital, 718 with career loads.
> 3. **Reconstructed-baseline projections are LIVE** —
>    `scripts/bdvm_build_baseline.py` fetched 3 seasons of nflverse
>    weekly stats (2023–25, REG only), scored them under the league's
>    exact 141-key Sleeper scoring via the production realized-points
>    path, and wrote an immutable snapshot: **2,815 proxy projections**
>    (`src/bdvm/baseline.py`).  Rookie draft-slot priors (§8.3) are
>    implemented and verified on the 2025 class (205 drafted rookies);
>    the 2026 class activates when nflverse publishes 2026 draft data
>    (currently absent upstream — verified, not a code gap).
> 4. **First live board produced**: 727 players priced (322 IDP) from
>    the committed contract export — replacement levels QB 11.96 /
>    LB 8.60 / WR 6.48…, three visibly diverging currencies (e.g. the
>    top-projected 30-year-old QB is the #1 contender asset and a
>    rebuilder STRONG_SELL), 668 preseason ROS values, 48 picks priced.
> 5. **Preseason ROS completed** — nflverse schedule fetch with bye
>    weeks + fantasy-playoff weighting (`src/bdvm/schedule.py`), per
>    player per strategy profile; degrades to `None` without a schedule.
> 6. **Roster intelligence + double-positive trade scan**
>    (`src/bdvm/roster.py`; `GET /api/bdvm/roster`, `GET /api/bdvm/trades`)
>    — strategy capitals, league-relative contend/retool/rebuild
>    classification (absolute reference thresholds saturate under a
>    proxy baseline — documented judgment call), quick starter FPG
>    (authoritative lineup remains `src/ros/lineup.py` per ADR-004),
>    and a pruned 1-1/2-1/1-2 scan where each side must gain in ITS OWN
>    currency, gated by single-market fairness (mixed sides fall back
>    to model-clearing values, never raw KTC+IDPTC sums).  Live run:
>    228k candidates scanned in 1.8s → 40 double-positives with exactly
>    the expected shape (aging contender ships vets to young rebuilders).
> 7. **Phase-11 backtest harness** (`src/bdvm/backtest.py`) —
>    rolling-origin folds, structural as-of leakage guard, baselines
>    B0–B4, Spearman/MAE/RMSE/Brier/calibration-slope metrics, S(3)
>    calibration check, surplus-mode ablation comparator.  The harness
>    is complete and tested; the *measurements* still await calendar
>    time (historical projection snapshots + realized outcomes).
>
> Test count is now **182** in `tests/bdvm/`; the full repository suite
> passes (result pinned in the PR).  Still genuinely awaiting data (no
> code can conjure them): honest source-accuracy weights, 2026 rookie
> draft slots (upstream), market-momentum history, in-season ROS recent
> form, backtest measurements, and pick distributions fit from own
> history.

> **Third-pass addendum — first REAL projection source + a live-league
> scoring bug fix.**
>
> 1. **The IDP Show 2026 projections** (Jon Macri, ~900 IDPs) are wired
>    as BDVM's first non-proxy source: `src/bdvm/idpshow_projections.py`
>    (schema-tolerant alias-driven parser with an explicit parse
>    report; combined-tackle solo/assist split is a flagged 0.62/0.38
>    approximation, never silent) +
>    `scripts/fetch_idpshow_projections.py` (same authenticated
>    Datawrapper/Sheet pattern as the existing idpShow rankings
>    fetcher, plus `--csv` for a manually downloaded sheet).  The
>    article is paywalled and `idpshow_session.json` lives only on the
>    VPS, so the first authenticated pull happens there; the parser,
>    record building, league-scoring resolution, and snapshot merge are
>    fully tested offline.  Merge policy: real records supersede
>    reconstructed-baseline proxies for covered players only; re-runs
>    replace the source's own prior records wholesale.
> 2. **Production scoring fix (found by the adapter's tests):**
>    `realized_points.compute_weekly_points` only read the canonical
>    `idp_pd` scoring key, but the live league's dump publishes
>    passes-defended as `idp_pass_def` (5.32/event) — PD scored as ZERO
>    on the realized path for this league; likewise fumble recoveries
>    read a `def_`-prefixed column the nflverse-direct weekly file
>    doesn't carry.  Fixed additively (alias applied only when the
>    canonical key is absent — never double-counts; stat-column
>    fallback), pinned in `tests/nfl_data/test_realized_points.py`.
>    Impact is material: regenerated baseline positional means moved
>    CB 5.21→7.93, S 5.56→7.44, LB 6.68→7.54 PPG, and the live board's
>    DB/LB replacement levels rose accordingly.
>
> `tests/bdvm/` is now **194** tests (plus 4 new realized-points pins).

Status vocabulary used throughout: **implemented** (code + tests merged on this
branch), **reference-only** (frozen fixture, imported by nothing),
**scaffolded** (shape + tests exist, production inputs not wired),
**provisional** (implemented but resting on unvalidated priors or judgment-call
inputs), **blocked / awaiting data** (cannot proceed without a feed that does
not exist), **awaiting validation** (implemented; claims depend on Phase-11
backtesting that requires historical snapshots that only accumulate with time).

---

## 1. Executive summary

BDVM v1 is integrated as a new, feature-flagged, projection-driven
**fundamental** valuation engine (`src/bdvm/`, 15 modules) beside — never
inside — the existing market-consensus pipeline. The verified reference
implementation (Appendices A–F) is preserved under
`docs/research/bdvm-v1/reference/` and reproduces its embedded output
**token-for-token (956/956)**. The production engine reproduces every number in
the reference's worked examples (13 archetypes × 3 strategies, replacement
levels, probabilities, pick table, CES trade math) through the *production*
code path, pinned by `tests/bdvm/test_engine_parity.py`. 119 new tests cover
scoring, replacement monotonicity, dynasty math, market isolation, picks,
trades, service orchestration and endpoint gating; the full repository suite
passes untouched.

The single most important repository finding: **the platform has no
forward-looking statistical projections anywhere** (audit §13 below). Every
existing value is market-rank derived. BDVM v1 therefore ships with the full
projection ingestion layer (snapshot store, manual-CSV adapter, robust
consensus) plus the BDVM §8.3 *reconstructed baseline* proxy builder, and the
engine's missing-data behavior is honest: a player with no projection is
**unpriced with a reason**, and with no projection snapshot at all the API
returns `status="no_projection_snapshot"` rather than a fabricated board. The
feature flag `bdvm_engine` defaults OFF; production behavior is bit-identical
until it is flipped.

## 2. Repository findings

Full audit run 2026-07-27 (6 parallel audit passes over valuation, data
sources, server/API, trade/roster, scoring/league, tests/CI/frontend).
Headlines:

- Live values (`rankDerivedValue`) come exclusively from
  `src/api/data_contract.py::_compute_unified_rankings` — a blend of market
  ranks/values (21 sources) through fitted Hill curves. No stats, no
  projections, no aging, no survival.
- `projection` columns exist in the ROS pipeline and are **empty in 100% of
  rows**; `src/ros/aggregate.py` documents that the field is "CARRIED BUT NOT
  CONSUMED". `rosValue` is a log-rank index, not points.
- Real NFL stats exist (`src/nfl_data/`: nflverse weekly stats, snaps,
  opportunity), and `realized_points.compute_weekly_points` is the one
  production raw-stats→fantasy-points path (Sleeper scoring vocabulary,
  ADR-005/006). BDVM scoring reuses it verbatim.
- Age is on contract rows but sparse; birth date is nowhere; draft capital
  exists only in an **unwired** nflverse contracts parser (`src/playerctx`,
  "deliberately NOT wired into server.py") and an Adamidp PDF field.
- An exact legal-lineup optimizer already exists (`src/ros/lineup.py`,
  max-weight bipartite assignment) and `src/roster_intel/marginal.py` already
  computes leave-out marginal utility — BDVM does not duplicate them.
- Daily market snapshots effectively already exist: `exports/archive/` holds
  131 dated full-contract zips (4–6/day), plus per-scrape immutable trees under
  `data/raw/<source>/`. Weekly player-context snapshots have a systemd timer
  (`dynasty-playerctx-refresh.timer`, Tue 05:40 UTC).
- Extension seams: `src/api/feature_flags.py` registry;
  `GET /api/valuation/league-adjusted` as the overlay-endpoint precedent; all
  `/api/*` behind a private session gate.

## 3. Existing valuation architecture

One live path: scrape → `build_api_data_contract` → `_compute_unified_rankings`
→ `rankDerivedValue` stamps → `latest_contract_data` global → `GET /api/data`.
Percentile-vs-500 reference, Hill-curve conversion, value-direct voting for
`ktcSfTep`/`idpTradeCalc`, Hampel rejection, α-shrinkage for IDP/picks,
single-source haircut, IDP market-corridor clamp, pick tethering. Registry
parity with the frontend mirror is test-pinned; frontend has **no** ranking
engine (fail-fast materializer). BDVM plugs in beside this as a second value
concept; nothing in the live path was modified.

## 4. Existing market architecture

21-source registry (`_RANKING_SOURCES`); only `ktcSfTep` and `idpTradeCalc`
vote value-directly; everything else is a rank signal. **Critical trap
honored by BDVM:** rank-signal sources store a synthetic `999900 − rank×100`
encoding in `canonicalSiteValues` — BDVM's market layer reads *only*
value-signal sources (`src/bdvm/market.py::VALUE_MARKET_SOURCES`), pinned by
test. KTC and IDPTC are directly comparable (2026-07-26 study: median ratio
1.000); the market layer stamps `normalizationVersion: ktc-idptc-peer-v1` on
every comparison.

## 5. Existing IDP architecture

IDP is first-class in the market pipeline (IDPTC backbone, IDP Hill master,
IDP-only corridor clamp) but positions are platform groups (DL/LB/DB) — no
true-position taxonomy on the live contract. `data/player_map/` carries
supplemental position data; Sleeper `fantasy_positions` drives lineup
eligibility in `src/ros/lineup.py`.

## 6. Existing roster/trade architecture

Four engines (suggestions, finder, angle, waiver) + Monte Carlo simulate, all
reading `rankDerivedValue`; `roster_intel` computes profiles, five-state
windows, partner acceptance, Pareto packages; `ros` computes power/playoff/
championship sims. **No CES package math existed in production** (plain sums +
the KTC-VA port + relaxed-constraint consolidation) — BDVM adds true CES with
roster-spot cost (`src/bdvm/trade_math.py`) as the §3.13 *display* layer;
`roster_intel`'s real marginal utility remains the personalized layer.

## 7. Agent coordination

Working copy is the CCR container clone; branch `claude/fully-implemented-riu0zp`;
no other agents were active on it (scheduled refresh commits go to `main`).
No files owned by other workstreams were rewritten; changes to shared files are
additive only (`feature_flags.py`: one new key; `server.py`: one new route).

## 8. BDVM reference extraction and verification

`docs/research/bdvm-v1/reference/` holds Appendices A–F reconstructed from the
PDF (indentation restored; logic/constants verbatim). `python3 run_examples.py`
output matches the PDF-embedded Appendix C **956/956 tokens, 0 mismatches**,
including full-precision floats (`77200.44208318304`…). SHA-256 hashes in the
reference `README.md`. Guarded by `tests/bdvm/test_reference_parity.py`
(re-runs the fixture; forbids production imports of it). Three cosmetic
PDF-truncation completions are documented in the reference README, along with
one code-vs-prose discrepancy in the reference itself (the 9th positional
`RiskProfile` argument is `small_sample`, though §4.10's prose calls it
designation risk — the code's semantics are what generated Appendix C, verified
numerically).

## 9. Retain / adapt / replace / deprecate map

| Area | Verdict | Notes |
|---|---|---|
| `_compute_unified_rankings` + Hill pipeline | **retain** | market value concept; untouched |
| `realized_points.compute_weekly_points` | **retain + reuse** | BDVM scores projections through it |
| `src/ros/lineup.py`, `roster_intel/marginal.py` | **retain** | authoritative personalized layer (ADR-004) |
| league registry / resolver / feature flags | **retain + extend** | one new flag, one new route |
| `src/scoring` (delta/multiplier layer) | **retain (unrelated)** | not a stats→points engine; left alone |
| `src/ros` rank-index ROS | **retain, replace later** | BDVM `ros.py` math is the replacement candidate once weekly points inputs exist |
| `src/playerctx` | **adapt (future)** | the draft-capital/contract feed BDVM's risk profiles await |
| `config/weights/default_weights.json` | unchanged | historical doc only |
| Nothing deprecated or removed. | | |
| **New**: `src/bdvm/*`, `src/api/bdvm_api.py`, `config/bdvm/*`, `tests/bdvm/*` | **implemented** | |

## 10. Data availability and missing-data tiers

| Input | Availability | BDVM behavior |
|---|---|---|
| Statistical projections | **absent** (Tier C) | manual-CSV adapter + reconstructed-baseline proxy; unpriced otherwise |
| League scoring rules | live (`sleeper.scoringSettings`, 141 keys) | ground truth |
| Lineup slots | live (`sleeper.rosterPositions`) | ground truth; registry fallback |
| Age | contract rows, sparse | missing → `unpriced:missing_age` (never imputed) |
| Experience / rookie flag | live (`yearsExp`) | drives `nfl_season`, small-sample risk |
| True IDP position | partial | taken from projection source when true; platform-group fallback + widened σ + quality reason |
| Draft capital, contracts, injuries, snap shares, career load | parsed but unwired (`playerctx`/`nfl_data`) | neutral risk-profile priors, documented; mileage term inert at load=0 |
| Market values | live (KTC/IDPTC) | market layer only, after fundamentals |
| Alignment/pressure charting (Tier A) | absent | CB/S archetype modelling limited to priors; confidence reflects it |

## 11. Schema and migrations

No database exists (file-based platform); the reference `schema.sql` is
preserved as design reference. Implemented as files: versioned parameter sets
(`config/bdvm/params_v1.json`, content-hashed `param_set_id`), pick outcome
tables (`config/bdvm/pick_outcomes_v1.json`), projection snapshots
(`data/bdvm/projections/<season>/projections_<date>.json`, immutable), and
valuation snapshots (`data/bdvm/valuations/<league>/bdvm_valuation_<ts>.json`,
immutable, plus a `latest.json` pointer refreshed only after a successful
write). `data/` is gitignored, matching existing convention.

## 12. Services and interfaces

Prompt §16 contract → implementation: `ingestProjectionSnapshot` →
`projections.write_snapshot/load_manual_csv`; `buildProjectionConsensus` →
`projections.blend_consensus`; `scoreProjection` →
`scoring.score_stat_line_per_game`; `calculateReplacementLevels` →
`replacement.ReplacementEngine`; `calculateCurrentSeasonSurplus` →
`surplus.season_starter_value`; `calculateTrajectory/RoleAscension` →
`curves.*`; `calculateSurvivalPath` → `survival.survival_path`;
`calculateGamesPath` → inside `engine.season_path`;
`calculateDynastyDistribution/StrategyValues` → `engine.DynastyEngine`;
`calculateMarketConsensus/normalizeMarketValues/calculateMarketGap` →
`market.*`; `calculatePickDistribution` → `picks.pick_value`;
`evaluateTradePackage` → `trade_math.*`; `calculateRestOfSeasonValue` →
`ros.*` (scaffolded); `publishValuationSnapshot` →
`service._persist_valuation`. Roster/partner functions (`analyzeRoster`,
`profileTradePartner`, …) are **retained** in `src/roster_intel` rather than
duplicated.

## 13. Projection ingestion

Implemented; **awaiting data**. Equal base weights (no honest accuracy history
exists — §4.1), weighted trimmed mean at ≥5 sources, 35% single-source cap
(skipped when mathematically infeasible at n<3 — documented judgment call),
staleness downweight (>21 days → ×0.5) with per-source flags, σ_source stored
as disagreement. Raw stat lines preferred (nflverse column vocabulary, scored
under exact league rules); direct fpts accepted and flagged
`scoring_native=false`. Reconstructed-baseline proxy per §8.3 implemented as a
pure function of realized PPG history with shrinkage toward positional means
(worse-than-real-projection bias direction, flagged `is_proxy`).

## 14. Replacement methodology

Dynamic rank-based VORP: fixed slots + greedy flex allocation (FLEX,
WRRB_FLEX, REC_FLEX, SUPER_FLEX, IDP_FLEX) + waiver buffer per group; VOLS
retained as diagnostic; pool exhaustion flagged, never extrapolated. Buffers
are the model's most sensitive knob and live in the parameter set. Format
sensitivity proven by tests: Superflex deepens QB replacement; DT-required
vs combined-DL and CB/S-required vs merged-DB reprice materially; team count,
starter counts and buffers all move replacement monotonically. **No positional
multipliers exist anywhere in the package.**

## 15. Dynasty methodology

Exactly the Part-14 formula: asymmetric-Gaussian conditional age curves
(continuous QB pocket/dual blend supported), mileage-adjusted effective age
(increase-only, capped), bounded saturating ascension κ (forced 0 from year 4
absent a documented role change), discrete-time hazard survival on
chronological age (separation from the curve is test-pinned), σ model with
role/event/sample multipliers + √t drift, option-value season surplus with
`truncated` and `plain` ablation modes exposed end-to-end (engine → service →
API `surplusMode=`), strategy profiles (contender/balanced/rebuilder **+
risk-neutral λ=0**) inside the horizon sum, certainty-equivalent λ·0.35·Ψ,
stud-premium trade scaling with per-strategy anchors, 0–100 percentile score,
P20/P85 quantile paths (documented perfectly-correlated approximation — which
does NOT agree with Ψ's independent-season assumption; see §32),
additive horizon-share explanations with survival drag and 5-year trajectory.

## 16. IDP methodology

Same code path as offense throughout (projection → scoring → replacement →
curves/hazard/σ → market), per §3.9. True positions DT/EDGE/LB/CB/S have their
own curves/hazards/CVs; configurable group mappings support combined-DL/DB and
split formats; platform-group fallback (DL→EDGE, DB→S) widens σ ×1.10 and
lowers the quality score with an explicit reason. Designation-risk hazard
adjuster implemented; eligibility-*scenario* valuation (P(e)-weighted across
designations) is **scaffolded only** — no eligibility feed exists.
Sack/TD event-regression parameters are stored (`event_regression`) but not
yet applied to μ(t≥1) — **provisional**, requires per-player expected-sack
inputs that don't exist yet (Tier A data).

## 17. Market normalization

Implemented per §3.11/§3.12: fundamentals computed and returned with zero
market inputs (payload-level test strips all market values and asserts
bit-identical fundamentals); market anchors per market (KTC SF-TEP for
offense/picks, IDPTC for IDP) under the stamped peer normalization; dispersion
from contract stamps; liquidity `clip(1.0 − 1.6·dispersion, 0.2, 1.0)`
(sign corrected 2026-08-04 — it was `0.35 + 1.6·dispersion`, which made
disagreement *raise* liquidity while the same input *lowered* `tau_market`
eight lines below; the new base keeps a typical row at ≈0.68 where the old
form put it); gap,
α=gap×liquidity, λ-blends (0 fundamental / 0.25 display / 0.50 clearing), and
magnitude-ordered buy/hold/sell signals with reasons (persistence is an
optional strengthener — see §32). Momentum inputs
(30-day market history) are **awaiting data** (rank/source history files are
code-complete in `src/api/*_history.py` but empty on disk — backfill scripts
exist).

## 18. Roster methodology

Deliberately thin in BDVM: the platform already has the authoritative
personalized layer (exact lineup solver, group leave-out marginals, five-state
window). BDVM contributes the three strategy currencies + risk-neutral value
per player and the both-sides `evaluate_both_sides` double-positive check.
Wiring BDVM values into `roster_intel`'s ΔU machinery is the natural Phase-7
follow-up once projections exist — recorded as remaining work, not claimed.

## 19. Trade methodology

Two layers per §3.13. Display: CES `(Σv^θ)^{1/θ} − C_spot·overflow`, θ=1.20
(1.35 shallow), C_spot=120 — reproduces the reference consolidation example to
±1. Authoritative: both-rosters utility must come from actual marginal
utility; BDVM provides per-strategy currencies for it and never labels a trade
by adding displayed values (`evaluate_both_sides` prices each side in its own
currency).

## 20. Backtesting and leakage controls

Structural controls implemented now: as-of stamps on every projection record
and snapshot; immutable snapshot files; source staleness relative to snapshot
date; `trained_only_on_prior_seasons` semantics deferred with equal weights
(nothing to train on yet). Rolling-origin backtests, baselines B0–B4, the
option-value ablation *measurement* and calibration reports are **awaiting
data** — they require historical projection + outcome snapshots that only
accumulate forward. The ablation *machinery* (surplus modes) is implemented
and API-exposed so the comparison can run the day data exists. The existing
`src/model_registry` champion/challenger governance (human-run `promote` +
`apply`, ADR-008) is the promotion path BDVM parameter sets will use.

## 21. Jobs and cadence

No new scheduled jobs added. Market snapshots: already archived 4–6×/day
(`exports/archive/`). Player-context: weekly systemd timer exists. BDVM
valuation persistence is on-demand (`write_snapshot_files=True`) until a
projection feed justifies a nightly job — adding a cron for an engine whose
input feed is empty would burn CI for nothing.

## 22. Feature flags and migration

`bdvm_engine` (default **False**) in the central registry; env override
`RISKIT_FEATURE_BDVM_ENGINE=1`. Off: 503 `feature_disabled`; on with no
snapshot: honest `no_projection_snapshot` payload; on with snapshots: full
board. No existing route, contract field, or frontend behavior changes in
either state. Rollback = flip the flag (or revert the branch; no data
migrations exist).

## 23. Files changed

New: `src/bdvm/` (22 files — core engine plus `events.py`, `context.py`,
`baseline.py`, `schedule.py`, `roster.py`, `backtest.py`),
`src/api/bdvm_api.py`, `config/bdvm/` (3 files incl. the event ontology),
`scripts/bdvm_build_baseline.py`, `tests/bdvm/` (20 files),
`docs/research/bdvm-v1/` (2 PDFs, reference/ 7 files, this report).
Modified: `src/api/feature_flags.py` (+1 flag), `server.py` (+3 routes:
`/api/bdvm/values`, `/api/bdvm/roster`, `/api/bdvm/trades`),
`CLAUDE.md` (BDVM section). Nothing deleted.

## 24. Tests run and results

- `tests/bdvm/`: **119 passed** (reference fixture reproduction; engine parity
  vs Appendix C — 13 archetypes ×3 strategies ±1, replacement levels,
  probabilities; hand-scored scoring configs incl. TEP/6-pt/IDP stacking;
  replacement monotonicity + format sensitivity; aging/survival separation;
  ascension bounds; option-value behavior + ablation plumbing; market
  isolation + source hygiene + signals; CES trade math vs reference; pick
  table vs reference; end-to-end service; endpoint auth/flag gating).
- Full repository suite (`pytest tests/ -x -q -m "not livedata"`, the CI
  tier): **4,297 passed, 0 failed** (325 livedata-deselected) — no
  regressions anywhere in the existing platform.
- `ruff format --check` + `ruff check` clean on all new/modified files.

## 25. Performance findings

Engine cost is ~4 season-path evaluations per player per strategy set (plus 2
quantile paths); the 13-player parity suite values in <50 ms. A 900-player
board is estimated well under a second in a threadpool; results are cached per
(contract build, league, param set, snapshot, mode) in `bdvm_api`. No impact
on any existing endpoint (flag off = one dict lookup).

## 26. Missing credentials or proprietary data

No PFF/SIS/charting access (alignment, pressure, expected sacks, coverage) —
Tier A inputs absent; no projection-source subscription; no Sleeper
credentials needed beyond what exists. Nothing in this branch requires new
secrets.

## 27. Risks and limitations

Every Part-6 constant is an unvalidated prior. Risk profiles are neutral
defaults plus position priors until playerctx/nfl_data feeds are wired —
survival and σ are therefore coarser than the design intends. Career load is
0 for everyone (mileage inert). Quantile band approximation is conservative.
The reconstructed-baseline proxy will understate true accuracy. Confidence
outputs are labels, not calibrated probabilities (§12.3 policy followed).

## 28. Material judgment calls

1. Reused `compute_weekly_points` for projection scoring (per-game basis;
   threshold bonuses evaluated on mean lines — documented second-order gap).
2. Sleeper block preferred over registry rosterSettings (registry is
   known-stale; audit finding).
3. 35% source cap skipped when infeasible (n<3) rather than equalizing.
4. Platform-group fallback DL→EDGE, DB→S with σ widening + quality reason.
5. Event-volatility priors by position table in `service.py` (no per-player
   dependence data yet).
6. Unpriced-not-imputed for missing age/projection (spec §6.3 rule 4).
7. Picks valued as distributions only when the slot parses from the asset
   name; unparseable picks return `reason: unparseable_pick_name`.
8. Reference `RiskProfile` positional-argument quirk preserved and documented
   rather than "fixed" (the code generated the verified output).
9. `risk_neutral` added as a 4th strategy profile (prompt §4.10 requires λ=0
   output) — anchors are per-strategy so the reference three are unaffected.

## 29. Remaining work (updated after the completion sweep)

Done since the first pass: baseline projections live (item 1), context
wiring for draft capital + career loads (item 2, via nflverse rather
than playerctx — contracts/guarantees still pending), the event system
(item 3), preseason ROS schedule inputs (item 4 preseason half), the
BDVM-native roster analysis + double-positive scan (item 5's BDVM
half), and the full backtest harness (item 7's infrastructure).

Still open, in dependency order:

1. **Awaiting data (no code can close these):** honest source-accuracy
   weights (needs archived preseason projections + outcomes); 2026
   rookie draft slots (upstream nflverse gap — priors auto-activate);
   market-momentum/gap-persistence history (rank/source history files
   accumulate forward); backtest *measurements* + S(3) calibration +
   the option-value ablation verdict; pick distributions fit from own
   history (needs 2 years of snapshots).
2. Contract/guarantee signals into risk profiles (wire `playerctx`
   snapshots once `scripts/refresh_playerctx.py` output lands on disk).
3. In-season ROS recent-form blending (weekly realized points feed into
   `blend_ros_mu` once the season starts).
4. Feed BDVM currencies into `roster_intel`'s exact ΔU machinery (the
   authoritative personalized verdict; BDVM's own scan is the generic
   layer).
5. A scheduled job for weekly baseline refresh + valuation snapshots
   (deliberately not added while the flag is off; one systemd timer or
   workflow step when enabled in staging).
6. UI: none yet, deliberately (§15 — no UI work while value contracts
   are unstable).

## 30. Rollback plan

Flag off (default) → zero exposure. Full rollback = revert the branch; no
migrations, no data mutations, no changes to existing behavior. Valuation
snapshots are additive files under gitignored `data/`.

## 31. Exact next actions

1. Merge this branch (flag stays off).
2. Drop the first projection CSVs under `data/bdvm/projections/manual/2026/`
   (or run the baseline builder), `write_snapshot`, flip
   `RISKIT_FEATURE_BDVM_ENGINE=1` in staging, and review the first live board
   at `/api/bdvm/values`.
3. Start the ablation ledger the same week (`surplusMode=` comparisons stored
   with param_set_id).

## 32. Known divergence: the model carries TWO risk representations

Recorded by the sitewide math audit of 2026-08-04 (finding M5). This is
**not a bug report against the implementation** — the production engine
reproduces the frozen reference here exactly, and changing it would break
Appendix-C parity (`tests/bdvm/test_engine_parity.py`). It is a
specification-level divergence that anyone reading a BDVM number should
know about, and the thing to resolve when the Phase-10 simulation
replaces the closed forms.

BDVM prices uncertainty twice, in two mutually inconsistent ways:

1. **Ψ, the certainty-equivalent penalty** in
   `engine.py::_discounted_value`: `DV = Σ u·d^t·E[t] − λ·0.35·Ψ` with
   `Ψ = √Σ (d^t·σ_t·G_t·S_t)²`. The sum-of-squares says the seasons are
   **independent** draws.
2. **The P20/P85 band** in `engine.py::_range`: both quantile paths shift
   *every* season's mean by the same z, which says the seasons are
   **perfectly correlated** (and `_range`'s own docstring says so).

Measured on the 13 Appendix-C archetypes, balanced horizon: the
perfectly-correlated dispersion `Σ d^t·σ_t·G_t·S_t` is **1.41× to 2.57×**
Ψ (median 2.29×). The two representations therefore disagree about the
size of the risk they are pricing by more than a factor of two inside a
single `Valuation`.

The second half of the divergence is that they also **stack**. The p20
and p85 paths already ARE the downside and upside cases, and then
`_discounted_value` subtracts `λ·0.35·Ψ` from each of them as well —
uncertainty charged once by moving the mean and again by penalising the
spread around it. On the same 13 archetypes that second charge is worth,
as a share of the pre-penalty DV:

| strategy | λ | penalty share of DV (min / median / max) |
|---|---|---|
| contender | +0.20 | 2.5% / 3.8% / 7.2% |
| balanced | +0.10 | 1.1% / 1.6% / 3.2% |
| rebuilder | −0.10 | −1.2% / −1.8% / −5.2% (a BONUS, not a penalty) |
| risk_neutral | 0.00 | 0% (by construction — the ablation baseline) |

The share is `λ·0.35·Ψ / v`, so it grows without bound as DV → 0: the
audit measured 6.7% (balanced) and 14.2% (contender) on marginal
live-board players, above the archetype range above. And because the
rebuilder's λ is negative, the rebuilder's *floor* comes back **raised**
above its own p20 path (audit: 9.3%) — the risk term pays a rebuilder
for volatility on a path that was already the bad case.

Neither effect is currently corrected, deliberately: the reference
implementation does the same arithmetic and it is the acceptance fixture.
`risk_neutral` (λ=0) exists precisely so a consumer who does not want the
second charge can read a board without it.

What was NOT left alone, and is fixed (audit H6): the p20/p85 paths used
to price *truncated* surplus while the median priced *option* surplus, so
the band could come back inverted (measured floor 0 / median 41917 /
ceiling 0). Both now use the same surplus functional, which makes
floor ≤ median ≤ ceiling hold by construction rather than by luck.
