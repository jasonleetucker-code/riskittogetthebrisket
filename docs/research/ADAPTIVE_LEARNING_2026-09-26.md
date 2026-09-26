# Calculator Adaptive Learning / Continuous Model Improvement — 2026-09-26

**Status:** OWNER-DIRECTED PLANNING / RECONCILIATION ONLY  
**Implementation authorization:** NONE — `docs/EXECUTION_PLAN.md` remains the implementation authority.  
**Pinned planning baseline:** `d68e7a71ef9b07bb2216c47a729a6cf74c74a760`  
**Primary governance owner:** existing `C10-ML-01` + P6 model/methodology acceptance profile.  
**Principle:** extend native owners; do not create a second ML/model/history/evaluation platform.

## 1. Owner-language definition

“Self-learning Calculator” should mean:

> Calculator preserves what it knew, what it predicted, what it recommended, what was done or declined, and what later happened; eligible models can then train/evaluate challengers on that point-in-time evidence, while production changes occur only through explicit, reproducible promotion gates.

This is broader than neural-network “machine learning.” It includes calibration, statistical learning, parameter estimation, Bayesian or hierarchical updates, time-series models, supervised learning, behavioral models and carefully bounded online learning. The desired loop is:

`observe → predict → act/decline → outcome → evaluate → challenger → promote only if better`.

Deterministic facts/rules stay deterministic.

## 2. Current repository foundations — this is not greenfield

| Foundation | Current owner/evidence | Maturity | What exists now | What it does not yet provide |
|---|---|---|---|---|
| Point-in-time history/as-of | `C1-HIST-01`, `src/history/*` | STRONG substrate | append-only temporal records, as-of ownership, provenance, known-time semantics | one universal observation/prediction/decision/outcome schema for every model |
| Model registry | `C10-ML-01`, `src/model_registry/*` | STRONG for Hill; generic primitives | champion/challenger/rejected/retired versions, training fingerprints, holdout evidence, promotion, rollback, scope gate | broad registration of non-Hill models and shared task scorecards |
| Hill Autopilot | `src/model_registry/autopilot.py`, `config/model_registry/*` | MATURE bounded example | deterministic automatic-promotion gates, forward persistence, leave-one-market-out, bootstrap robustness, row health, parameter stability, rollback | proof that the same policy/metrics fit unrelated models |
| P6 methodology policy | `docs/C_SERIES_SCOPE_MANIFEST.md`, `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` | BINDING | backtest/calibration/pinned provenance, champion/challenger, recorded promotion, rollback | feature-local adoption still incomplete |
| Backtesting utilities | `src/backtesting/*`, `scripts/backtest_*.py` | PARTIAL / fragmented | source correlation, proposed dynamic weights, trade backtest harness, multiple domain backtests | one task-aware evaluation workbench; some older harnesses use proxy targets and are not universal truth |
| Source freshness | `C6-FRESH-01`, `src/sources/freshness.py`, #1423 | PARTIAL adaptive behavior | learns normal publication cadence from actual content-change intervals; separates fetch/content clocks; freshness/coverage/health factors | empirical learning of predictive utility decay by task/horizon/regime |
| Projection system | `C5-ROS-01`, #854, `config/projections/source_capability_census.json` | PARTIAL | typed weekly adapters, exact-league rescoring paths, ancestry/capability census, simple family ensemble concepts | mature multi-family weekly/ROS archive + prospective accuracy scorecards |
| Game Day archive / capture | `C5-GD-02`, `src/ros/game_day_archive.py`, current Game Day generation/capture code | STRONG capture foundation | pregame/in-game point-in-time evidence, deployed Game Day generations, live collector | accumulated calibration scorecards and learned challengers for distributions/covariance |
| Analyst ledger | `C6-ANA-01`, `src/analyst/*`, merged #1437 | STRONG persistence foundation | append-only claims/stances, as-of queries | analyst outcome scoring and task-aware reliability model |
| Acquisition / league history | `C1-ACQ-01`, market/FAAB/waiver native owners | PARTIAL | private acquisition history and several market/history foundations | complete prospective rejected-offer/losing-bid/non-action evidence |
| Power / playoff | `C5-POW-01`, `C5-PLAY-01` | PRODUCT EXISTS / VALIDATION GAP | production rankings/odds and historical concepts | unified rolling-origin validation/calibration before adaptive challengers |
| Manager / trade intelligence | `C6-MGR-01`, `C7-DESK-01`, `C4-MTL-01` | PARTIAL / planned | manager substrate, trade owners, accepted-event evidence | enough prospective rejected/countered/expired-offer data for calibrated acceptance modeling |
| Adaptive learning governance | `C10-ML-01` | EXISTING NATIVE UMBRELLA | “adaptive source weighting stays off until validated”; champion/challenger; no silent self-promotion | broadened owner direction across all eligible model families |

### Key conclusion

Do **not** build a new “ML platform.” The needed architecture is an extension/convergence of the existing history store, model registry, P6 evaluation policy, domain archives and native decision owners.

## 3. Deterministic vs learnable vs behavioral

### A. Deterministic — never self-learn the rule

- fantasy scoring arithmetic and rule versions;
- league configuration and roster limits;
- canonical player/pick identity;
- asset ownership;
- lineup eligibility;
- exact legal lineup assignment;
- transaction legality;
- source/provenance identity;
- event/knowledge timestamps;
- public/private boundaries;
- missing/unknown/zero semantics.

Learning may estimate inputs **to** these rules, but may not rewrite the rules themselves.

### B. Learnable with strong prospective evidence

- weekly/ROS projection combination and calibration;
- Game Day remaining-production distributions;
- source/task reliability;
- empirical freshness decay;
- playoff/title probability calibration;
- Power predictive components;
- future-pick distributions;
- player role/usage transitions;
- roster-utility distributions;
- trade uncertainty;
- FAAB demand / clearing behavior;
- analyst accuracy by claim type/horizon.

### C. Personalized / behavioral, sample-size guarded

- manager asset preferences;
- consolidation vs depth tendencies;
- willingness to move picks;
- FAAB aggressiveness;
- positional demand;
- league-specific market quirks;
- owner risk/liquidity preferences, only with explicit/resettable personalization.

Sparse observations must shrink toward league/broad priors. Descriptive tendencies must not masquerade as calibrated acceptance probabilities.

## 4. Learnability matrix

| Capability | Class | Learning target | Evidence needed | Current archive/readiness | Risk | Native owner |
|---|---|---|---|---|---|---|
| Dynasty value / Hill mapping | Learnable methodology, market target | mapping/generalization across independent market families | point-in-time native boards + holdouts | strongest current champion/challenger implementation | circular market targets | `C10-ML-01`, `F-VAL-01`, Hill registry |
| Source weighting | Learnable, gated | incremental task value after ancestry/freshness/coverage | source snapshots + outcomes | partial; dynamic-weight utilities exist | correlated inputs / self-confirmation | `C10-ML-01`, `F-SRC-01` |
| Freshness | Learnable parameter/policy | utility decay vs content age by task/horizon/regime | change clocks + downstream errors | cadence is already learned; utility decay is not | false causal inference from update cadence | `C6-FRESH-01`, #1423 |
| Weekly projections | Learnable | source/ensemble point/distribution accuracy by position | pre-kickoff predictions + realized exact-league points | source/census foundation present; archive/eval incomplete | leakage, missing scoring fields | `C5-ROS-01`, #854 |
| ROS projections | Learnable | horizon-matched forecast error/calibration | timestamped ROS forecasts + remaining-season outcomes | partial | horizon mixing | `C5-ROS-01` |
| Game Day | Learnable | probability calibration, score error, interval coverage, lineup accuracy, covariance challengers | deployed generation archive + final results/corrections | high readiness now | overfit sparse game states | `C5-GD-01`, `C5-GD-02` |
| Playoff/title odds | Learnable calibration | probability reliability and model comparison | dated forecasts + eventual outcomes | model exists; validation gap | small sample / season leakage | `C5-PLAY-01` |
| Power Rankings | Mixed descriptive/predictive | predictive component and current-story consistency separately | weekly snapshots + future results | strong product, validation gap | optimizing prediction can violate descriptive intent | `C5-POW-01` |
| Future picks | Learnable distribution | actual slot distribution under league draft rules | point-in-time team state + eventual pick slot | partial foundations | endogenous strength / rule changes | `C1-PICK-03`, seasonal owners |
| FAAB | Behavioral/statistical | league/context bid distribution, demand, owner aggressiveness | original budgets, visible bids, winning/losing visibility, roster need | market layer planned; prospective history critical | censored bids | `C4-FAAB-01`, `C4-FAAB-02`, `C4-WAIV-01` |
| Trade recommendation | Learnable evaluation, not one target | process utility/regret by objective, not “winner” hindsight | saved recommendation + alternatives + roster/objective + later outcomes | decision contract still evolving | target definition / hindsight | `C7-DESK-01`, `C3-REPLAY-01` |
| Manager Scout | Behavioral | preference/tendency and eventually acceptance likelihood | accepted + rejected + countered + expired offers | accepted history insufficient alone | sparse/selected data | `C6-MGR-01`, R14 candidate |
| Competitive posture | Learnable/calibratable classification | probabilistic posture evidence, transition calibration | point-in-time team state + later path | owner-approved model direction | arbitrary thresholding | `C7-POST-01` |
| Roster utility | Learnable distributions around deterministic lineup solve | weekly marginal lineup contribution/insurance | projections/outcomes + exact roster snapshots | exact lineup foundation strong | double counting / injury assumptions | #1173 / roster owners |
| Analyst intelligence | Behavioral/forecast evaluation | accuracy by claim type/horizon, supersession value | dated atomic claims + outcomes | persistence/as-of foundation exists | ambiguous claims / repeated lineage | `C6-ANA-01` |
| Player role/development | Learnable | role-up/down and future usage distributions | snaps/routes/touches/depth/injury/context history | data foundations partial | nonstationarity / causal overclaim | player-intel + `C5-FIT-01` |
| Notifications | Contextual/bandit candidate later | usefulness/timing/actionability | alert, action, dismissal, deadline outcome | product scope exists | optimizing engagement over decisions | `C7-ALERT-01` |
| Acquisition scheduling | Adaptive decision policy | information gain per cost/deadline | source-change history + decision sensitivity + costs | #1423 foundation planned | missed critical refreshes | #1423 / R66 extension |

## 5. Shared architecture mapping

The repository should converge on the following conceptual loop without necessarily creating nine new services.

| Concept | Existing canonical home / direction |
|---|---|
| Observation | `src/history/*`, source dataset state, projection observations, analyst ledger, Game Day captures |
| Feature | existing canonical domain owners; **gap:** no explicit shared feature dictionary/registry found |
| Prediction | domain model output + immutable generation IDs (Game Day, projections, playoff, etc.) |
| Decision | native decision owners such as `C7-DESK-01`, FAAB/waiver, alerts; **gap:** prospective private non-action journal remains candidate scope |
| Outcome | realized scoring/results, transactions, bids, draft results, corrections |
| Evaluation | P6 policy + `src/backtesting/*` + domain backtests; needs common task-aware receipts |
| Challenger | `src/model_registry/*` already provides reusable version lifecycle |
| Promotion | existing model registry/P6 gates; Hill autopilot is the bounded automatic example |
| Drift | fragmented source/schema/rank-form checks; no unified model-performance drift owner yet |
| Rollback | model registry already supports former-champion rollback; domain integrations need to use it |

### Feature-registry conclusion

A broad new “feature store” is not justified yet. What is missing is a **versioned feature dictionary/manifest** for learned models so concepts cannot be locally redefined. Treat that as an extension under `C10-ML-01` at implementation time, not a new data platform.

## 6. Archive now — perishable evidence

Prioritize capture before sophisticated modeling:

1. **Game Day predictions/generations** before and during games: probabilities, projected finals, ranges, lineup probabilities, leverage, model/input versions and cutoffs.
2. **Weekly/ROS source projections** before kickoff/source replacement, preserving raw stats, exact-league rescoring, ancestry, source time and coverage.
3. **Playoff/title and Power snapshots** before future outcomes.
4. **Future-pick slot distributions** with team/rule state and ownership.
5. **FAAB/waiver evidence** with original/current budgets, visibility/censoring, bids/claims and roster context.
6. **Market trades / manager behavior** with format/date/context.
7. **Analyst atomic claims** with publication/known time and supersession.
8. **Trade/waiver/draft recommendations and alternatives** before action.
9. **Private rejected/countered/expired offers and considered-but-not-sent decisions** only through the already-admitted R14 candidate if/when separately authorized.
10. **Model evaluation and rejected challenger records** — losers remain evidence.

No retroactive reconstruction may be labelled exact when the observation was never captured.

## 7. First adaptive-learning candidates

### Candidate 1 — Game Day calibration scorecard

**Why now:** Game Day is deployed, its collector runs continuously, and it already has a prediction-archive owner.

**Champion:** current production Game Day model/distributions.

**First evaluation:** Brier/reliability for matchup and median probabilities, final-score MAE/bias, interval coverage, final best-ball lineup accuracy, results by game state/time remaining.

**Challengers later:** covariance/role-state models only after the baseline is measured.

**Promotion:** P6 + model registry; no automatic promotion initially.

**User value:** trustworthy “how calibrated is this?” evidence and better future live distributions.

### Candidate 2 — Projection-family evaluation and ensemble challenger

**Why now:** #854 already requires archive-first, exact-league rescoring, ancestry and simple independent-family baselines.

**Champion:** simple family-level mean/median/robust baseline appropriate to horizon.

**Challenger:** position/horizon-specific reliability weighting only after sufficient prospective history.

**Evaluation:** MAE/RMSE/bias/rank, coverage/calibration, injury handling, source family ablations, rolling-origin splits.

**User value:** better Game Day/ROS inputs and an honest “which sources add signal for this task?” view.

### Candidate 3 — Freshness utility challenger

**Why now:** Calculator already learns normal source cadence from real change history.

**Champion:** current cadence-relative freshness policy.

**Challenger:** shadow-only task/horizon/season-regime decay learned from downstream predictive degradation.

**Evaluation:** does age-aware weighting improve held-out task outcomes after ancestry/coverage controls?

**User value:** stale sources lose influence based on measured usefulness rather than arbitrary TTLs.

### Candidate 4 — Power / playoff calibration lab

**Why now:** production models and snapshots exist; research explicitly recommended validation instead of another rewrite.

**Champion:** current canonical methodology after consolidation.

**Challengers:** calibration layer or predictive component changes, not wholesale formula churn.

**Evaluation:** rolling-origin future outcomes + separate descriptive-consistency score for Power.

**User value:** probability/ranking claims become measurable without sacrificing the intended “current story” role of Power.

### Candidate 5 — FAAB demand / league-behavior learning

**Why later than 1–4:** winning bids are censored and complete prospective bid/decision evidence is still thinner.

**Champion:** existing canonical FAAB engine/market normalization.

**Challenger:** hierarchical league/manager demand model with shrinkage.

**Evaluation:** bid-range/clearing evidence where visible; never treat unseen losing bids as zero.

**User value:** league-specific bid ranges and competition estimates.

## 8. Longer-term opportunities that need more history

- calibrated Manager Scout trade-acceptance likelihood;
- robust trade recommendation regret/process scoring;
- future-pick slot distributions with endogenous roster effects;
- player role-transition / breakout-decline models;
- joint NFL role/covariance model for Game Day;
- personalized risk/liquidity preference learning;
- value-of-information and action-aware research scheduling;
- bounded contextual-bandit experiments for notification timing or acquisition scheduling.

**Reinforcement learning is not a near-term priority.** No autonomous trade/waiver/drop actions are authorized.

## 9. Automatic vs owner-gated behavior

### Safe to automate when implemented

- archival capture;
- deterministic evaluation;
- challenger refits in shadow mode;
- drift alerts;
- scorecard updates;
- candidate generation that cannot alter production output.

### Production promotion

Default rule: **gated**.

Automatic promotion is allowed only when an owner-approved deterministic policy exists for that exact model family, with fail-closed gates and rollback. Hill Autopilot is an existing approved exception/example, not a blanket permission for every model.

### Always owner/model-policy gated initially

- dynasty source/model weights;
- Game Day model replacement;
- projection ensemble weighting promotion;
- trade recommendation utility changes;
- manager/behavioral model influence;
- FAAB policy changes;
- posture methodology;
- paid/new-source activation.

## 10. Drift

Do not create one vague “drift score.” Track distinct classes:

- **data/schema drift:** fields, coverage, identity, missingness;
- **source drift:** publication cadence or methodology change;
- **calibration drift:** probability reliability shifts;
- **performance drift:** held-out error worsens;
- **behavior drift:** league/manager tendencies change;
- **regime drift:** season phase/NFL environment changes.

Drift opens an investigation/challenger cycle; it does not blindly retrain/promote production.

## 11. Native Calculator Ideas reconciliation

No new standalone “ML backlog” and no new manifest ID is required at intake time.

### Governance umbrella

- `C10-ML-01` — broaden owner intent from adaptive source weighting to **Adaptive Learning / Continuous Model Improvement governance** while preserving its existing “validated champion/challenger, no silent self-promotion” semantics.
- P6 acceptance profile remains the binding model/methodology gate.

### Existing native owners extended

- `C1-HIST-01` / retention rows — point-in-time observation substrate.
- `C5-GD-02` — Game Day prediction archive/evaluation evidence.
- `C5-ROS-01` / #854 — projection archive, evaluation and ensemble challengers.
- `C5-PLAY-01` — probability calibration.
- `C5-POW-01` — rolling-origin predictive validation + descriptive consistency.
- `C6-FRESH-01` / #1423 — learned cadence, later empirical utility decay and action-aware scheduling.
- `C4-FAAB-01/02`, `C4-WAIV-01` — FAAB/waiver behavioral evidence.
- `C6-MGR-01` — manager tendencies; calibrated acceptance waits for prospective non-action/rejection evidence.
- `C6-ANA-01` — analyst claim outcome evaluation.
- `C7-DESK-01` / `C3-REPLAY-01` — decision/recommendation evaluation without hindsight leakage.
- `C7-POST-01` — calibrated/probabilistic posture.
- `C7-ALERT-01` — later contextual alert/action learning.

### Existing research candidate dependency

R14 private decision/offer journal remains a **candidate**, not implementation-authorized scope. It is the clean prospective path for rejected/countered/expired offer and non-action evidence needed before strong Manager Scout/trade-acceptance learning.

### No new native owner created now

The only plausible shared gap is a feature-definition/evaluation receipt manifest. Keep it as a proposed sub-capability under `C10-ML-01` until the first implementation batch proves a separate native row is necessary.

## 12. Recommended first implementation batch — NOT AUTHORIZED BY THIS RECORD

### Batch: Adaptive Learning Evidence & Evaluation Spine

**Goal:** make existing predictions objectively scoreable before building sophisticated ML.

#### Lane A — prediction/evaluation contract
Extend existing history/model-registry owners with a small task-aware evaluation receipt:
- model/task/version;
- feature/input manifest/hash;
- forecast cutoff;
- prediction IDs;
- outcome IDs/revisions;
- metric set;
- cohort/horizon/position;
- sample count;
- score;
- missing/coverage state.

No feature store, no training service, no production weight change.

#### Lane B — Game Day calibration
Consume existing Game Day archives/generations and realized finals:
- Brier/reliability;
- projected-final MAE/bias;
- interval coverage;
- best-ball lineup accuracy;
- cohort by pregame/live/halftime/time-remaining.

Current model remains champion. Challengers shadow only.

#### Lane C — weekly projection scorecard
Start/verify immutable pre-kickoff source/ensemble archive and evaluate exact-league points by source family/position. Establish the simple champion baseline required by #854.

#### Lane D — freshness shadow analysis
Measure error vs content age by source/task/horizon. Produce a shadow challenger report only. **No production source-weight changes.**

#### Lane 6
At planning time PR #1453 is the active Game Day phone/PSI cleanup stream. If it has finished before this batch starts, include a small PSI progressive-disclosure **Model Evidence** surface only when measured data exist (sample count, last evaluation cutoff, calibration/coverage). Never expose raw debugging or unvalidated “accuracy” claims.

### Acceptance

- exact point-in-time inputs;
- no future leakage;
- simple champion preserved;
- rejected challengers retained;
- metrics task-appropriate;
- source ancestry respected;
- missing never zero;
- no runtime recommendation changes;
- no paid/new source activation;
- reproducible evaluation from pinned inputs;
- model registry can record challenger evidence and rollback metadata;
- production-facing UI, if any, only reports measured evidence.

## 13. Operating burden

| System | Capture | Train/evaluate | Runtime burden | Main failure mode | Rollback |
|---|---|---|---|---|---|
| Game Day calibration | existing minute/generation archive + finals | weekly / after correction window | low offline | sparse state cohorts | keep champion |
| Projection evaluation | pre-kickoff + ROS cadence | weekly + rolling-origin seasonal | medium offline | coverage/ancestry gaps | simple family baseline |
| Freshness challenger | existing change clocks + model errors | periodic, not per request | low/medium offline | confounding age with source quality | current freshness policy |
| Power/playoff validation | weekly snapshots | weekly/seasonal | low | small sample / target confusion | current methodology |
| FAAB behavior | every visible claim/bid + budgets | weekly/in-season | low/medium | censoring / sparse manager samples | canonical FAAB rules |

## 14. Owner decisions still separate

This record does **not** decide:

- R40 vs R44 / OD-06;
- activation/purchase of SportsDataIO, Fantasy Nerds or other paid/default-off sources;
- promotion of DLF Values;
- #1428 chart palette;
- any new automatic-promotion policy beyond already approved Hill Autopilot;
- autonomous roster transactions;
- private decision/offer journal implementation (R14 remains candidate until separately authorized).

## 15. Durable owner directive

> **Adaptive Learning / Continuous Model Improvement:** Wherever Calculator makes a probabilistic, predictive, weighting, behavioral or decision-model judgment that can validly improve from accumulated point-in-time evidence, preserve observations, predictions, decisions/non-decisions and outcomes and support disciplined continuous learning. Use simple baselines, champion/challenger models, leakage-safe evaluation, drift detection, explicit uncertainty, source ancestry and strict promotion/rollback rules. Deterministic league rules, scoring, identity, legality and historical facts remain deterministic. Begin with prospective evidence capture, evaluation and shadow challengers. Production models do not autonomously self-modify except through an explicitly owner-approved deterministic promotion policy for that model family.
