# Calculator Adaptive Learning / Continuous Model Improvement — 2026-09-26

**Status:** OWNER-DIRECTED PLANNING / RECONCILIATION — **the one Adaptive Learning plan.** Extended in place
on 2026-10-01 by the owner's *Adaptive Learning / Continuous Improvement Master Roadmap* (Part II, §16–§25).  
**Implementation authorization:** this file grants none. Since 2026-10-01, `docs/EXECUTION_PLAN.md` §0
"Adaptive Learning / Continuous Improvement — owner directive, 2026-10-01" authorizes the dependency-ready
foundation and roadmap units named in §23–§24. It does **not** authorize an unvalidated model to change a
production output; promotion keeps its P6 evidence gates.  
**Pinned planning baselines:** `d68e7a71ef9b07bb2216c47a729a6cf74c74a760` (Part I, 2026-09-26) ·
`13870a6d42f665c47cb38ee628757279ff0e0783` (Part II, 2026-10-01)  
**Primary governance owner:** existing `C10-ML-01` + P6 model/methodology acceptance profile.  
**Principle:** extend native owners; do not create a second ML/model/history/evaluation platform.

> **Reading order.** Part I (§1–§15) is the 2026-09-26 reconciliation and stays valid except where §17 marks a
> clause superseded. Part II (§16–§25) is the 2026-10-01 master roadmap: the shared learning receipt, the
> governance rules, the five roadmap areas with owners and dependencies, and the first foundation unit.

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

> **Status refresh 2026-10-01:** the table above is the 2026-09-26 snapshot. Current state per roadmap area —
> including Batch 3 (#1584–#1592), the merged pregame projection archive and the completed-trade ledger — is
> in §21.

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

> **Amended 2026-10-01 (§17 S3):** the versioned feature dictionary is now in-scope foundation work under
> `C10-ML-01` (unit AL-0, §23), not a "prove it is necessary first" proposal. The no-feature-store conclusion stands.

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

> **Superseded in part 2026-10-01 (§17 S1/S2).** The owner re-ordered priorities (Valuation Trust and
> completed-trade learning first; Game Day and playoff NEXT) and authorized the dependency-ready units. Lanes A–D
> below survive as content inside the Part II units: Lane A → AL-0; Lane B → AL-4a; Lane C → AL-3b; Lane D →
> AL-1c. Their acceptance list is folded into §23.

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

---

# Part II — Adaptive Learning / Continuous Improvement Master Roadmap (owner directive, 2026-10-01)

## 16. Directive provenance — and what was not received

- **Source:** owner directive in chat, 2026-10-01, titled *Calculator — Adaptive Learning / Continuous
  Improvement Master Roadmap*. Intake pointer: `docs/OWNER_REQUESTED_TODO.md`, entry "Added 2026-10-01 —
  Adaptive Learning / Continuous Improvement Master Roadmap".
- **Received:** the preamble and sections 1–8.
- **Truncated in delivery:** the message ended after the heading "9." **Sections 9 onward were not received.**
  Nothing in this record infers their content. They are tracked as *pending owner re-send*. Any of them may
  add, refine or override Part II; when re-sent they are reconciled here under the same rules.
- **Authority, in substance:** the directive is explicit owner authorization to *implement* the
  dependency-ready Adaptive Learning foundations and roadmap units. It is **not** blanket authorization for an
  unvalidated model to silently change production outputs. Methodology promotion keeps its existing evidence
  gates.

The directive's own definition, preserved:

> Calculator should preserve what information existed at a point in time, what it predicted, what it
> recommended, what action occurred or did not occur, what happened afterward, how accurate the
> prediction / recommendation / model / source was, and then use that accumulated evidence to improve future
> models through controlled champion/challenger evaluation.

Loop: `OBSERVE → PREDICT → RECOMMEND/DECIDE → OUTCOME → EVALUATE → LEARN → CHALLENGER → VALIDATE OUT OF
SAMPLE → PROMOTE IF BETTER → CONTINUE MONITORING`. It is a shared property of Calculator, not a trade-value
feature, and explicitly not "a neural network everywhere". Evidence that should accumulate: source histories,
projections, player outcomes, games, trades, bids, drafts, roster decisions, manager behavior, analyst
predictions, DFS contests, market movement, and rejected / non-actions where legitimately observable.

## 17. What Part II supersedes in Part I (and why)

Precedence: `docs/MASTER_PRODUCT_PLAN.md` §2 rule 1 (the most recent explicit owner instruction wins) and
`docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §4's practice of resolving on the dated, explicit
instruction. Superseded text stays in place for traceability.

| # | Part I clause (2026-09-26) | 2026-10-01 instruction | Disposition |
|---|---|---|---|
| S1 | Header + §12: "Implementation authorization: NONE"; first batch "NOT AUTHORIZED" | §1: explicit authorization to implement dependency-ready foundations and roadmap units | **Superseded.** Authority now lives in `EXECUTION_PLAN.md` §0 (2026-10-01 section). This file still grants nothing itself |
| S2 | Intake first-wave order: Game Day → projections → freshness → Power/playoff → FAAB | §4–§8: Valuation Trust/source learning NOW (highest), completed-trade/IDP NOW, BDVM+projection NOW/NEXT, Game Day NEXT, playoff/title NEXT | **Superseded.** Ordering in §22. Game Day remains the cleanest loop; it is NEXT, not dropped |
| S3 | §5/§11: feature dictionary is a "proposed sub-capability … if the first implementation proves it necessary" | §2: a versioned feature dictionary/manifest *is appropriate* | **Superseded.** In-scope AL-0 work under `C10-ML-01`; still no new manifest ID and still no feature store |
| S4 | §10 drift classes named loosely | §3: six named drift classes; drift triggers reevaluation, not retraining/promotion | **Refined**, not contradicted. §20 is the binding list |
| S5 | §3A deterministic list | Preamble: "facts and rules do not learn", enumerated | **Refined.** §18 is the binding list (adds source identity explicitly) |

Not superseded: R14 (private rejected/countered offers, considered-but-not-sent) stays a **CANDIDATE**. The
receipt's NON-ACTION kind (§19) represents only what is *legitimately observable* through an existing owner;
it does not authorize R14 capture. Sections 9+ might address this; until they are received, R14 is unchanged.

## 18. Invariant — facts and rules do not learn

Adaptive systems estimate **uncertain relationships around** these facts. They may never rewrite them. Each
fact keeps its deterministic owner, and a learned model is a *consumer* of that owner.

| Fact / rule | Deterministic owner (never a learned output) |
|---|---|
| Scoring arithmetic | `src/scoring/`, `src/nfl_data/realized_points.py`, `ProjectionRecord.resolve_fpg` |
| League settings | `src/api/league_registry.py`, `scoring_fingerprint()` (`src/league_comparison/sleeper_scoring.py`), C1-RET-04 scoring-card history |
| Player identity | `src/identity/resolution.py` (C1-ID-01) |
| Pick ownership / pick identity | `src/identity/picks.py` (C1-ID-02) |
| Lineup legality and assignment | `src/ros/lineup.py` (C2-U1) |
| Roster rules / capacity | `src/trade/roster_capacity.py` |
| Transaction legality | host of record (Sleeper) + `roster_intel/packages._check_legality` |
| Source identity / family | `_RANKING_SOURCES` + B10 families (`F-SRC-01`); `config/sources/source_lineage.json` (#1592) |
| Timestamps / known-at | `src/history/asof.py`, `src/sources/dataset_state.py` (three clocks) |
| Provenance | `src/history/provenance.py`, model-registry training fingerprints |
| Privacy boundaries | `MASTER_PRODUCT_PLAN.md` §5; `F-PRIV-01` |
| Unknown-vs-zero semantics | `MASTER_PRODUCT_PLAN.md` §3.2; `F-MISS-01` |

Structural rule for implementations: a learning-substrate module may *read* these owners. It may not write a
canonical value field (`CANONICAL_VALUE_FIELDS`), a league-config field, an identity mapping or a timestamp.
AL-0 pins this with an import/write-boundary test (§23, A7).

## 19. One shared learning substrate — the learning receipt

**Design rule.** No separate ML infrastructure per domain (Trade, FAAB, Game Day, DFS, …), no giant universal
table, no generic feature store. Observations stay in their native canonical stores. What is shared is a small
set of **common identifiers, contracts and evaluation receipts** that point *into* those stores.

### 19.1 The twelve receipt kinds and where each already lives

| Kind | Question it answers | Native owner today | Shared contract adds |
|---|---|---|---|
| OBSERVATION | What was actually known at time T? | `src/history/` (values/ranks/picks), `dataset_state` clocks, Game Day archive (C5-GD-02), pregame projection archive, `src/source_archive/` (C1-SRC-01), market-trade raw archive (#1586), analyst ledger (C6-ANA-01) | a typed **reference** `(store, key, knownAt, fidelity)`, never a copy. Fidelity uses the `asof.py` vocabulary (`exact` / `nearest-prior` / `partial` / `unavailable`) |
| FEATURES | Which versioned inputs did the model consume? | per-model code; Hill `trainingRun` pins (#1588) | the **versioned feature dictionary** (§19.3) + a per-run feature-manifest hash |
| PREDICTION | What did Calculator predict? | Game Day `generations.jsonl`, playoff/title sims, BDVM payloads (`modelVersion` + `paramSetId`), shadow ledgers | a stable `predictionId` minted by the producer, with `cutoff` and `target` |
| DECISION / RECOMMENDATION | What did Calculator recommend, if anything? | finder / suggestions / FAAB / Perfect Draft are **not preserved** (BRISKET_IDEAS §13 G8); FAAB shadow logging (`src/trade/faab_shadow.py`) | the reference kind is defined; capture is a later, separately sequenced unit per domain |
| ACTION | What actually occurred? | own-league transactions (`league_events.sqlite`, C1-RET-06; `acquisition.sqlite`, C1-ACQ-01), market trades (#1586), FAAB bid history | a reference to the host-of-record event id |
| NON-ACTION | What was declined / not selected, where legitimately observable? | failed FAAB claims (bid history), auction losing bids (room engine), a recommendation not taken (once G8 is captured) | explicit `observable: false` when it cannot be seen; never inferred. R14 private offers stay CANDIDATE |
| MODEL | Which exact model / config / version produced the result? | `src/model_registry/versioning.py` (Hill); BDVM `modelVersion`/`paramSetId`; Game Day generation layout version | generic `modelFamily` + `modelVersionId`, registry-backed |
| OUTCOME | What happened later? | realized scoring (`realized_points.py`), matchup finals + corrections, standings/champion, transactions, later boards | a reference + `outcomeRevision` (stat corrections are revisions, not overwrites) |
| EVALUATION | How did the prediction perform against its declared target? | Hill holdout scores, `src/backtesting/*`, `src/bdvm/backtest.py`, #1589 `evaluations.jsonl`, #1590 shadow outcomes | **the evaluation receipt** (§19.2), the main new artifact |
| CHALLENGER | What candidate is being tested against the champion? | `src/model_registry/` challenger records | the same lifecycle for non-Hill families |
| PROMOTION RECORD | Why did a candidate replace — or fail to replace — the champion? | `src/model_registry/promotion.py`, Hill Autopilot records, Batch 3 §N | one record shape for every family, rejections included (losers stay evidence) |
| DRIFT | Did source behavior, population, calibration, environment or performance change? | fragmented: source health / content staleness, schema checks, `identity_dual_read` | a typed drift receipt carrying one of the six classes (§20) |

### 19.2 The evaluation receipt (the first shared artifact)

Append-only, idempotent and conflict-surfacing, using the write discipline of `src/history/store.py` and
`src/robust_filter_shadow/ledger.py`. Minimum fields:

- `modelFamily`, `modelVersionId`, `role` (champion / challenger / baseline);
- `task`, declared `target`, `horizon`, and cohort keys (position, asset class, rank band, game state, …);
- `cutoff` and the point-in-time rule applied;
- `featureManifestHash` and input pins (code SHA, source hashes, snapshot hash, scoring fingerprint);
- prediction-set and outcome-set references, with `outcomeRevision`;
- `preregistrationHash`: metrics, gates and cohorts fixed before scoring;
- metrics, `n`, uncertainty (interval and method), coverage and missing counts (missing is counted, never 0);
- holdout design (chronological / league / player / source-family);
- `verdict` ∈ `champion_retained` · `challenger_better_pending_policy` · `inconclusive` · `insufficient_sample`.

A `challenger_better_pending_policy` verdict promotes **nothing**. Promotion is a separate PROMOTION RECORD,
written only by that family's approved policy (§20 rule 6).

### 19.3 Versioned feature dictionary — not a feature store

One definition per concept, versioned, so two models cannot silently define "ROS strength" or "source age"
differently. Precedent: `src/model_registry/training_manifest.py` on #1588, the single owner of Hill
trainers/holdouts, which fails tests when a hand-kept list diverges. Per feature, the dictionary records: name,
version, definition owner (a canonical module), unit, known-at rule, missing semantics, lineage/family, and
allowed consumers. A model's feature manifest that references an undefined feature, or redefines an existing
one, fails validation. The dictionary stores **definitions**, never values.

## 20. Permanent learning governance (binding on every adaptive system)

1. **Prospective / point-in-time.** A historical test uses only information knowable at its timestamp. No
   future leakage. Never rebuild an old prediction from today's inputs and call it historical truth (the C1-U4
   rule: never re-derive an old value with today's curve).
2. **Champion / challenger.** Production keeps a known champion; new methods run as challengers.
3. **Shadow first** where consequences are meaningful.
4. **Holdouts** fit the task: chronological, league, player, source-family or another defensible split. A
   shared-family member never sits on both sides (#1588 precedent).
5. **Uncertainty.** Report sample size and uncertainty. Sparse populations shrink toward broader priors or the
   champion.
6. **No silent self-promotion.** Automated training and evaluation are encouraged. Production promotion is
   governed by an explicit per-model-family policy. Hill Autopilot (`docs/valuation/HILL_AUTOPILOT_V2.md`) is a
   bounded example, not permission for any other algorithm. Batch 3 §N is the explicit policy for Batch 3
   methodology candidates. Any other family needs its own owner-approved policy before anything automatic.
7. **Drift triggers reevaluation, not promotion.** Drift opens an evaluation / challenger cycle. It never by
   itself justifies retraining into production or promoting.

| Drift class | Example signal | Existing partial owner | Response |
|---|---|---|---|
| Schema / data drift | fields, coverage, identity join rate, missingness | contract `structuralErrors`, `identity_dual_read.json`, source census (#1584) | reevaluate affected models; quarantine inputs that fail contracts |
| Source drift | publication cadence or methodology change; lineage change | `dataset_state`, content staleness (`config/source_staleness.json`), lineage sweep (#1592) | re-score source quality; recheck family assignment |
| Calibration drift | probability reliability shifts | none yet (AL-4a / AL-5b create it) | calibration challenger cycle |
| Performance drift | held-out error worsens | Hill holdout history; #1589 evaluations | evaluation cycle; never auto-retrain into production |
| Behavioral drift | league / manager tendencies change | FAAB history, sharp ledger | refit behavioral challengers in shadow |
| Season / regime drift | preseason vs in-season vs playoffs; NFL environment | partly encoded (BDVM in-season blend, Game Day states) | regime-split evaluation before pooling |

## 21. Roadmap areas — state, gaps, owners, in-flight work

Unit labels `AL-*` are **plan-local unit names, not new manifest IDs**. Every unit lives inside an existing
manifest row named in its table. Batch 3 units keep their own letters (A–O) and are *mapped*, not duplicated.

### 21.1 AL-1 — Valuation Trust / source learning · **NOW (highest priority)**

Owner: `C10-ML-01` + `F-SRC-01` + Batch 3 (`EXECUTION_PLAN.md` §0, "Valuation Trust Program — Batch 3");
`C6-FRESH-01` / #1423 for decay. Calculator must learn which dynasty sources add unique information, which lead
or lag, which are noisy, how they differ for offense / IDP / picks / rookies and across rank bands, which
families are correlated, which updates later prove useful, how utility decays with age, which sources explain
completed trades, and whether equal weighting still beats learned weighting. **Accuracy is never agreement
with KTC.**

| Item | What exists today | What is missing | Dependency |
|---|---|---|---|
| Source inventory | Batch 3 A source trust census, **merged #1584** (`src/sources/source_census.py`) | — | — |
| Lineage / correlation | #1592 (open): four lineage categories in `config/sources/source_lineage.json`; IDPTC offense measured republishing KTC on a lag | merge; feed lineage into holdouts and family caps | #1592 |
| Point-in-time panel + metrics | #1589 (open): `src/source_quality/` panel built from source-CSV commit history; lead/lag (β_gap, leave-family-out), stability, event response, walk-forward; equal-family champion **retained**; G2[PICK] marked structurally mis-specified | merge; a re-specified, preregistered pick target before pick cohorts count | #1589 |
| Outcomes evaluated | (1) leave-family-out market movement, (3) lead/lag, (4) stability, (5) event response: #1589. (6) future football performance as a SECONDARY diagnostic: realized points exist (`realized_points.py`) | (2) completed-transaction-implied prices, which need AL-2c | AL-2 |
| Hill substrate | #1588 (open): one training manifest, full pins, leak-free holdouts | merge; then the D2 clean rerun | #1588 |
| Sparse evidence | #1591 (open): censor-aware estimator, flag OFF, fails preregistered G2c; being extended with a state matrix + shadow recorder | stays shadow until a preregistered gate passes | #1591 |
| Robust filter | **merged #1590**: shadow ledger, verdict INCONCLUSIVE, stays shadowed | accumulation over time (Batch 3 O) | — |
| Utility decay vs age | cadence learned (`freshness.py`); content and fetch clocks separated | measured predictive decay by task / horizon (Part I candidate 3) | AL-0, #1589 panel |
| Base authority | `effective = base × freshness × health × coverage`, then the family cap; base = 1.0 by policy | an **evidence-based base-authority challenger**, shrunk toward equal-family weighting | #1589, AL-0, later AL-2c |

Units:
- **AL-1a** — register Batch 3 evaluator outputs (#1589 `evaluations.jsonl`, #1590 shadow ledger, #1591 shadow
  recorder) as evaluation receipts, with recurring accumulation (= Batch 3 O). After AL-0.
- **AL-1b** — evidence-based base-authority challenger: conservative reliability estimates, shrunk toward
  equal-family weights; leave-family-out; preregistered; shadow. Promotion only via Batch 3 §N.
- **AL-1c** — information-utility decay challenger (Part I Lane D / candidate 3). Shadow only.
- **AL-1d** — cohort reliability (offense / IDP / picks / rookies × rank band), once the sample supports it.

Never: wire the old realized-points-only `dynamic_source_weights` fitter into production. Batch 3 §N already
forbids it, and #1589 §1 shows it is inert, leaky and double-counting.

### 21.2 AL-2 — Completed-trade learning / IDP market · **NOW (after #1586)**

Owner: `C4-MTL-01` (ledger), `C4-MTL-02` (KTC lane), `C4-MTL-03` (comparables), `C1-ACQ-01` (own-league
history), `src/sharp/` (Sharp acquisition owner). Batch 3 Unit I + its two 2026-10-01 addenda.

| Item | What exists today | What is missing | Dependency |
|---|---|---|---|
| Inputs | #1586 (open): KTC Trade Database append-only raw archive (`src/sources/ktc_trades.py`, `src/trade/market_trade_archive.py`, 30-minute timer); Sharp-discovered Sleeper trades read from the existing intel ledger, with real league format saved by `src/sharp/discovery.py`; own-league history in C1-RET-06 / C1-ACQ-01 | merge; accumulated history (KTC exposes a rolling ~200-row window, so trades before #1586 are lost) | #1586 |
| Raw vs unique | raw observations kept apart from canonical underlying trades; `underlyingTradeId` | — | #1586 |
| Dedupe states | `MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §19: confirmed same-host / confirmed cross-source / probable / possible / distinct; platform + league_id + transaction_id when available; never dedupe on package equality | — (the directive's four states map onto these five; "confirmed duplicate" is split by evidence kind) | #1586 |
| Format capture | one fingerprint with 13 comparability axes (SF/1QB, teams, depth, TE, flex, scoring, IDP depth/slots/scoring, best-ball, …) | a coverage census per axis | #1586 |
| Dispositions | exactly one of NATIVE_COMPARABLE / VALIDATED_TRANSFORMABLE / TARGET_UNSUPPORTED vs `dynasty_main`; every non-native trade is TARGET_UNSUPPORTED until a translator validates | translators | AL-2b |
| Format translation | — | the evidence hierarchy: (1) same-provider paired formats; (2) actual cross-format completed trades; (3) BDVM / lineup / replacement structural prior; (4) exclude. **BDVM is not the universal conversion formula** | AL-2a; paired-format archive (BRISKET_IDEAS §13 G3, `C1-SRC-01`) |
| Latent price model | — | a shadow format-aware latent transaction-price model for `dynasty_main` (`transactionMarketValueGeneric` vs `transactionMarketValueTargetLeague`; native evidence dominates translated), especially for IDP | AL-2a, AL-2b |

Units:
- **AL-2a** — target-format evidence census, first and report-only: counts by disposition, format axis, month
  and position (IDP explicit); raw vs unique vs duplicate / probable / possible; which paired formats and
  cross-format trades exist to support translators. Acceptance: reproducible from pinned ledger state; unknown
  format counted as not comparable; no value written anywhere.
- **AL-2b** — format translator challengers, validated out of sample in the evidence-hierarchy order. A
  translator that fails stays out, and its trades stay TARGET_UNSUPPORTED.
- **AL-2c** — the shadow latent transaction-price model. It feeds AL-1 as outcome (2). It never rewrites
  canonical value before dedupe and topology are validated (Batch 3 §N).

### 21.3 AL-3 — BDVM + projection learning · **NOW (archive + evaluation) / NEXT (ensembles + component calibration)**

Owner: `C5-BDVM-01` (BDVM stays a separate named concept, never canonical market value), `C5-ROS-01` / #854
(projections), `C5-GD-02` (pregame archive). Batch 3 J1 (**merged #1585**) and J2 (wave 3).

| Item | What exists today | What is missing | Dependency |
|---|---|---|---|
| Pregame weekly archive | Sleeper weekly projections archived before kickoff, ahead of the raw-log prune (BRISKET_IDEAS §13 G1; PR #1525 merged 2026-09-29, `e1f4dce4c` + `882c4558a`; `pregame_projections.json.gz`, backed up under `data/game_day/`) | production observation of the archive UNVERIFIED here | — |
| Season / ROS snapshots | immutable dated snapshots in `data/bdvm/projections/` (Clay, IDP Show, proxy baseline) on the box | **not in the backup set** (G7); no per-source in-season ROS re-snapshot cadence | G7 |
| Raw stats + exact scoring | `ProjectionRecord` + `resolve_fpg`; `src/ros/projection_observations.py`; source vocabulary and per-player `unscoredKeys` (#1585) | per-stat-category scorecards | AL-0 |
| Evaluation harness | `src/bdvm/backtest.py` (rolling-origin folds, structural as-of refusal); `src/bdvm/actuals.py` | scorecards by provider × position × stat category × horizon × regime × family, then exact-league points contribution | AL-0 |
| Ensemble | `src/ros/projection_ensemble.py` (C5-PROJ-D); the capability census lists few live families | the equal independent-family **champion** first; then position / horizon / category / regime reliability challengers, only when the sample supports them, shrunk toward the champion | AL-3b |
| Component calibration | BDVM priors in `config/bdvm/params_v1.json` (one blanket "every number here is a STARTING PRIOR" comment) | a per-parameter **MEASURED / MECHANICAL / PRIOR** label (`MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §2 vocabulary); calibration of role security, survival / career horizon, durability, scheme stability, volatility, first-down rates, reception distance, IDP categories and projection uncertainty. A prior never becomes MEASURED because time passed | J2 |

Units: **AL-3a** archive completeness (verify every usable pregame / ROS projection is captured before the
event; close G7 for `data/bdvm/`); **AL-3b** projection scorecard against the equal-family champion; **AL-3c**
ensemble reliability challengers (sample-gated, shrunk); **AL-3d** BDVM component calibration and parameter
labels. AL-3d *is* Batch 3 J2 extended, not a second unit.

### 21.4 AL-4 — Game Day learning · **NEXT**

Owner: `C5-GD-01` / `C5-GD-02`; `src/ros/game_day_sim.py` (one simulation, two outcomes),
`src/ros/game_day_live.py` (versioned generations), `src/ros/game_day_archive.py` + `game_day_capture.py`
(`.github/workflows/game-day-capture.yml`).

| Item | What exists today | What is missing | Dependency |
|---|---|---|---|
| Prediction archive | append-only pregame captures; `generations.jsonl` keeps every superseded generation and is never pruned; backed up | a stable `predictionId` and model identity per generation, in receipt form | AL-0 |
| Outcomes | Sleeper finals + the post-final stat-correction path | the outcome join after the correction window, with `outcomeRevision` | AL-0 |
| Scorecard | none found in `src/` (no Brier / reliability / interval-coverage code outside `src/bdvm/backtest.py`) | Brier score, log loss where appropriate, reliability curves, MAE / bias, interval coverage; cohorts: pregame / early / halftime / late / Monday-late, favorite-underdog magnitude, remaining-player topology, stack / correlation situations | AL-0 |
| Challengers | — | calibration, variance, covariance, distribution shape, remaining-production model, all shadow | AL-4a |

Units: **AL-4a** calibration scorecard over existing generations (champion only); **AL-4b** shadow
challengers. "If Calculator says 70% hundreds of times, about 70% of similar predictions should happen." Never
replace the production model because one week looks better: promotion needs a preregistered gate over a
sufficient sample.

### 21.5 AL-5 — Playoff / title probability learning · **NEXT**

Owner: `C5-PLAY-01`, currently DUPLICATED (`src/ros/playoff_sim.py` + `src/ros/championship.py`, and
`src/public_league/playoff_odds.py`).

| Item | What exists today | What is missing | Dependency |
|---|---|---|---|
| Forecasts | `data/ros/sims/*.json`, rewritten every 2 h with `computedAt`, `n_simulations` and points-model fields | no model version, code SHA or input fingerprint on the payload | — |
| Archive | **accidental only:** the commit history of the runner-computed files (`latest_championship.json`: 1,212 commits since 2026-04-28); equality with the box-served payload UNVERIFIED | a designed point-in-time forecast archive with model identity | AL-5a |
| Evaluation | one small-sample measurement (weekly log loss 0.928 vs 0.693 for a coin flip, weeks 1–2; OWNER_REQUESTED_TODO 2026-09-26, D2) | season-end calibration ("a 20% team should win about 20% of the time"), pooled only across comparable rules; never "was the champion ranked first?" | AL-5a, AL-0 |
| Challengers | D2 (ROS strength counted twice) and D3 (median games) are recorded owner decisions | calibration challengers **before** rebuilding the simulation; D2 runs as a challenger scored by log loss / PIT | owner D2 / D3 |

Units: **AL-5a** point-in-time forecast archive (capture; the commit history is backfill evidence labelled
`nearest-prior` with an unknown model version, never `exact`); **AL-5b** season-end calibration evaluation;
**AL-5c** calibration challengers.

## 22. Sequencing (dependency graph)

```
#1588 (Hill substrate) ──► AL-0 (receipt + evaluation receipt + feature dictionary)
                               ├─► AL-1a (Batch 3 outputs as receipts) ─► AL-1b / AL-1c / AL-1d
                               ├─► AL-3b ─► AL-3c ; AL-3d (= J2)
                               ├─► AL-4a ─► AL-4b                         (NEXT)
                               └─► AL-5b ─► AL-5c                         (NEXT)
#1589, #1591, #1592 ──────────► AL-1b / AL-1d inputs
#1586 (ledger) ─► AL-2a (format census) ─► AL-2b (translators) ─► AL-2c (latent price, shadow) ─► AL-1 outcome (2)
AL-3a (archive completeness + G7 backup) ── no code dependency; dependency-ready now (own claim on deploy/backup/)
AL-5a (forecast archive) ── no AL-0 dependency; NEXT, perishable (commit history mitigates meanwhile)
```

Priority when units compete: AL-0 → AL-1 → AL-2 → AL-3 → AL-4 → AL-5. Units on disjoint files run in
parallel. `data_contract.py` keeps one writer at a time (Batch 3 rule); no AL unit needs it.

## 23. First foundation unit — AL-0: shared learning receipt + evaluation receipt

**Scope.** Extend `src/model_registry/` and `src/history/` (no new platform) with:
1. a versioned receipt contract for the twelve kinds (§19.1), where every kind either references a native store
   or is explicitly `unobserved` / `not_applicable`, never a fabricated value;
2. the evaluation receipt (§19.2) with an append-only, idempotent, conflict-surfacing store;
3. the versioned feature dictionary (§19.3) and its validator, seeded only with the features the first adapted
   producers consume;
4. generic `modelFamily` / `modelVersionId` / `predictionId` identifiers;
5. adapters for **two existing producers, without changing their outputs**: Hill `trainingRun` / holdout
   records (#1588) and one non-Hill producer (the merged #1590 robust-filter shadow ledger, or #1589
   evaluations).

Proposed paths (the implementer confirms them against live code): `src/model_registry/learning_receipt.py`,
`src/model_registry/evaluation_receipt.py`, `config/model_registry/feature_dictionary.json`, tests under
`tests/model_registry/`. The store lives under gitignored `data/` and **outside `data/ros/`**, because the
scheduled refresh force-adds `data/ros/` and would publish private receipts.

**Dependency.** #1588 merged: its claim covers `src/model_registry/`, and AL-0 consumes its `trainingRun` pins
and training-manifest precedent. The schema design and preregistration text may be drafted before then.

**Acceptance criteria.**
- A1 — point-in-time guard: a receipt refuses an observation or feature whose `knownAt` is after the
  prediction `cutoff`, and an outcome dated before its target event. Property-based test over random timestamps.
- A2 — append-only: an identical re-write is a no-op; a conflicting re-write is surfaced and never applied.
- A3 — missing is never zero: `n`, coverage and missing counts are explicit; an empty cohort yields
  `insufficient_sample`, not a 0 score.
- A4 — feature dictionary: a manifest that references an undefined feature, or redefines an existing one, fails.
- A5 — the verdict vocabulary is fixed; no code path in AL-0 writes a PROMOTION RECORD or moves a champion pointer.
- A6 — both producer adapters round-trip real committed evidence into receipts; the producers' own outputs are
  byte-identical before and after.
- A7 — boundary: an import/write test proves the learning modules cannot write `CANONICAL_VALUE_FIELDS`,
  league config, identity mappings or contract stamps; the served board hash is unchanged.
- A8 — a drift receipt carries one of the six §20 classes and triggers nothing automatically.
- A9 — the store is added to `deploy/backup/riskit-state-backup.sh` and the retention register in the same
  unit (the G7 lesson), or the unit states why it is rebuildable.
- A10 — reproducible from pinned inputs; L0/L1 green; planning gates green; independent review.

**Engineering applicability check** (`AI_INSTRUCTIONS.md`; `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`):

| Mechanism | Disposition |
|---|---|
| Captured replay fixtures / parser drift | `NOT_RELEVANT` — consumes existing stores, fetches nothing |
| Typed API schemas / OpenAPI | `DEFERRED_BY_AUTHORITY` — no endpoint in AL-0; a later Model Evidence surface (Lane 6) takes it on |
| Property-based tests | `APPLY_NOW` — the point-in-time guard and idempotency (A1, A2) |
| Architecture / import boundary | `APPLY_NOW` — A7 |
| Progressive typing | `APPLY_NOW` — new modules fully typed (dataclasses + `from __future__ import annotations`) |
| Durable state / migrations | `APPLY_NOW` — schema-versioned append-only store, backup + retention entry (A9) |
| Deployment identity / artifacts | `ALREADY_COVERED` — served build identity (#1543); receipts pin the code SHA |
| Tracing / SLOs / Web Vitals | `NOT_RELEVANT` — offline, not on a request path |
| CI structure / supply chain | `ALREADY_COVERED` — no new dependency; planning gates unchanged |
| Agent eval for a harness change | `NOT_RELEVANT` — not a harness change |
| Privacy (public/private boundary) | `APPLY_NOW` — receipts are private decision intelligence: stored outside `data/ros/`, never in a public payload |

## 24. Later units — acceptance in brief

| Unit | Priority | Acceptance in brief |
|---|---|---|
| AL-1a | NOW (after AL-0) | every Batch 3 evaluation artifact reproducible as receipts; accumulation scheduled; nothing promotes |
| AL-1b | NOW | preregistered; leave-family-out; shrinkage toward equal-family; beats the champion on held-out outcomes beyond noise, or the champion is retained; promotion only via Batch 3 §N |
| AL-1c | NOW | measured decay by task / horizon after ancestry and coverage controls; shadow only |
| AL-1d | NOW, sample-gated | cohort scores with `n` + intervals; sparse cohorts shrink; the pick target is re-specified before pick cohorts count |
| AL-2a | NOW (after #1586) | census reproducible; IDP counts explicit; unknown format not comparable; no value written |
| AL-2b | NOW → NEXT | each translator validated out of sample in the hierarchy order, or excluded |
| AL-2c | NEXT | shadow only; native dominates translated; generic and target-league values named separately; becomes AL-1 outcome (2) only after dedupe / topology validation |
| AL-3a | NOW | every usable pregame / ROS projection archived before the event; `data/bdvm/` backed up |
| AL-3b | NOW | raw-stat + exact-league scorecards by provider × position × category × horizon; equal-family champion |
| AL-3c | NEXT | reliability challengers only where the sample supports them; shrunk toward the champion |
| AL-3d (= J2) | NEXT | a MEASURED / MECHANICAL / PRIOR label on every BDVM parameter; components calibrated on outcomes |
| AL-4a | NEXT | Brier / log loss / reliability / MAE-bias / interval coverage by game state; champion only |
| AL-4b | NEXT | shadow challengers; no promotion on one week |
| AL-5a | NEXT (perishable) | every forecast archived with model identity and inputs; commit-history backfill labelled `nearest-prior` |
| AL-5b | NEXT | season-end calibration, pooled only across comparable rules |
| AL-5c | NEXT | calibration challengers before any simulation rebuild; D2 as a challenger |

## 25. Unresolved — Part II

- Sections 9+ of the directive were not received (pending owner re-send).
- No per-model-family automatic-promotion policy exists outside Hill Autopilot and Batch 3 §N. A family without
  one promotes only by explicit owner approval.
- The D2 / D3 playoff methodology decisions remain open (OWNER_REQUESTED_TODO 2026-09-26). The "league settings
  do not learn" invariant bears on D3 (median games are a league rule), but whether the median W/L enters
  seeding is still the owner's decision.
- Paired-format evidence for AL-2b depends on BRISKET_IDEAS §13 G3 (KTC unselected variants), which is not
  preserved today and is not authorized by this record.
- G8 (served recommendations) and R14 stay uncaptured / candidate, so DECISION and NON-ACTION receipts stay
  sparse until a separately authorized capture unit lands.
- Production observation of the pregame projection archive and of the backup set is UNVERIFIED in this
  planning unit.
