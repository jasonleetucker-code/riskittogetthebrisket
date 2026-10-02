# Calculator Adaptive Learning / Continuous Model Improvement — 2026-09-26

**Status:** OWNER-DIRECTED PLANNING / RECONCILIATION — **the one Adaptive Learning plan.** Extended in place
on 2026-10-01 by the owner's *Adaptive Learning / Continuous Improvement Master Roadmap* (Part II, §16–§25),
and again the same day by the full re-send of that directive's sections 9–31 (Part III, §26–§38).  
**Implementation authorization:** this file grants none. Since 2026-10-01, `docs/EXECUTION_PLAN.md` §0
"Adaptive Learning / Continuous Improvement — owner directive, 2026-10-01" authorizes the dependency-ready
foundation and roadmap units named in §23–§24. It does **not** authorize an unvalidated model to change a
production output; promotion keeps its P6 evidence gates. *(Superseded in place: Part I's header read
"Implementation authorization: NONE" — see §17 S1.)*  
**Pinned planning baselines:** `d68e7a71ef9b07bb2216c47a729a6cf74c74a760` (Part I, 2026-09-26) ·
`13870a6d42f665c47cb38ee628757279ff0e0783` (Part II, 2026-10-01)  
**Primary governance owner:** existing `C10-ML-01` + P6 model/methodology acceptance profile.  
**Principle:** extend native owners; do not create a second ML/model/history/evaluation platform.

> **Reading order.** Part I (§1–§15) is the 2026-09-26 reconciliation and stays valid except where §17 marks a
> clause superseded. Part II (§16–§25) is the 2026-10-01 master roadmap: the shared learning receipt, the
> governance rules, the five roadmap areas with owners and dependencies, and the first foundation unit.
> Part III (§26–§38) reconciles directive sections 9–31: the remaining domains mapped to their native owners,
> the Wave 1–4 roadmap order, per-family learning cadence, rejected-challenger retention, explanation and test
> requirements, authority, the Model Lab contract, the four-closed-loop completion standard, the campaign
> sequencing from the continuation instructions, and the extended perishable-evidence audit.

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

The only plausible shared gap is a feature-definition/evaluation receipt manifest. Keep it as a proposed sub-capability under `C10-ML-01` until the first implementation batch proves a separate native row is necessary. **[Superseded 2026-10-01 — §17 S3: the versioned feature dictionary is now in AL-0 scope; still no feature store.]**

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
  - **RESOLVED 2026-10-01 (later the same day):** the owner re-sent the directive in full. Sections 1–8 are
    identical to what Part II records; sections 9–31 and binding continuation instructions are reconciled in
    **Part III (§26–§38)** below. The original marker above is kept for traceability.
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
*Update 2026-10-01 (Part III §27, §35):* §13 of the re-send says rejected / countered / expired offers are
needed for calibrated acceptance probability **"when legitimately available"**, and §28 does not list private
offer capture among the authorized work. R14 therefore stays a **CANDIDATE**; nothing changed.

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
| Source identity / family | `_RANKING_SOURCES` + B10 families (`F-SRC-01`); `config/sources/source_lineage.json` (created by #1584; lineage categories extended by #1592) |
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
- A9 — the store is added to `deploy/backup/riskit-state-backup.sh` and the retention register (the G7
  lesson), or the unit states why it is rebuildable. AL-3a is the serial owner of `deploy/backup/`: AL-0's
  backup line lands through AL-3a's claim when it is active, or after it, never concurrently.
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

- Sections 9+ of the directive were not received (pending owner re-send). **RESOLVED 2026-10-01:** received
  and reconciled in Part III; Part III §38 carries the current unresolved list.
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

---

# Part III — Directive sections 9–31 and continuation instructions (owner re-send, 2026-10-01)

## 26. Provenance and precedence of the re-send

- **Source:** the owner re-sent the full *Calculator — Adaptive Learning / Continuous Improvement Master
  Roadmap* in chat on 2026-10-01, after #1593 had recorded sections 1–8 from the truncated first delivery.
  Sections 1–8 in the re-send are identical in substance to Part II, so Part II stands unchanged. Sections
  9–31 and the accompanying **continuation instructions** (operational, binding for this campaign) are new.
  Intake pointer: `docs/OWNER_REQUESTED_TODO.md`, entry "Added 2026-10-01 — Adaptive Learning master roadmap,
  sections 9–31 + continuation instructions (owner re-send)".
- **Precedence:** `MASTER_PRODUCT_PLAN.md` §2 rule 1 (the most recent explicit owner instruction wins) and the
  dated-instruction practice of `C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §4. Where Part III and Part II
  disagree, Part III wins; §35 lists every such case. Superseded text stays in place.
- **Authority:** §28 of the directive (recorded in §32 below) authorizes planning reconciliation, required
  archive/capture work, shared learning receipts, evaluation infrastructure, shadow challengers, scorecards,
  drift monitoring, domain evaluation loops and dependency-ready roadmap units. It authorizes no autonomous
  league action, no hidden recommendation change, no self-promotion outside approved gates and no new paid
  data. `docs/EXECUTION_PLAN.md` §0 remains the only authorization record; this file grants nothing itself.
- **Vision, preserved:** Calculator should accumulate *experience*, not merely features. Every week, game,
  projection, trade, bid, draft, source update and settled decision should let it evaluate its own
  assumptions. The goal is not an opaque AI that changes numbers on its own but a continuously measured,
  evidence-driven Calculator that gets harder to fool as it gathers real outcomes, built once and shared by
  every eligible system.

## 27. Domain map — directive sections 9–20

Every domain maps to an existing canonical owner. None gets its own ML stack: each consumes the AL-0 receipt
(§19) and its native store. Unit labels are plan-local (no new manifest IDs); the wave is from §28 below.

| § | Domain and the directive's binding constraints | Canonical owner (code · manifest row) | What exists today | Gaps named by this reconciliation | Wave · unit |
|---|---|---|---|---|---|
| 9 | **Power Rankings.** Two separate objectives: DESCRIPTIVE (who has been strongest) and PREDICTIVE (which components forecast). Never optimize the public ranking for prediction and destroy its narrative contract. Evaluate points, all-play, record, recent form, roster strength, health, schedule/luck components against future outcomes | `src/ros/power_v2.py` + `src/public_league/power.py` (**DUPLICATED**, `C5-POW-01`); snapshots `src/ros/power_snapshots.py` → `data/ros/power_snapshots/` | immutable weekly publications (git-tracked) | no component-vs-future-outcome evaluation; two engines must consolidate before a learned forward-looking contribution has one place to land; the descriptive contract is not written down as a test | Wave 2 · **AL-7** (validation only; consolidation stays `C5-POW-01`) |
| 10 | **Future draft picks.** Replace early/mid/late with a calibrated distribution (P(early/mid/late), preferably the slot distribution); preserve team strength, points, all-play, record, roster quality, age, depth, injuries, remaining schedule, ownership and draft rules at each timestamp; evaluate prospectively; learn the empirical annual discount curve instead of a fixed discount | `src/ros/pick_projection.py` (`C1-PICK-03`, PARTIAL — point estimate); pick identity `src/identity/picks.py`; values `src/api/pick_value_resolution.py`; year step `config/weights/pick_year_discount.json::derivedYearModel` (PRIOR) | point forecast; vendor year-step PRIOR | no point-in-time forecast archive (§36); no slot-distribution model; the discount curve is a PRIOR extrapolation, never fit to realized outcomes | Wave 2 · **AL-6** (capture half is Wave 1, §36) |
| 11 | **FAAB / waiver market.** Learn the league's economics: clearing-price distributions, aggressiveness, positional and timing premiums, budget-state effects, manager aggressiveness. Hierarchical: manager → league → broader prior; sparse managers shrink. Never turn unseen losing bids into zero. Keep the four populations separate (own league, Sharp leagues, external market, platform trending) | `src/trade/faab_engine.py` (`F-FAAB-01`, `C4-FAAB-01`); history `scripts/fetch_faab_history.py` / `src/trade/faab_history.py` (`C4-FAAB-02`); crowd `src/trade/faab_comparability.py` (`C1-RET-01`); shadow log `src/trade/faab_shadow.py` | zero-inflated lognormal rivals fitted to league history; crowd and own-league kept apart; backtest script | recommendation-at-decision-time archive (G8); losing-bid observability is host-limited (§36); no hierarchical manager layer | Wave 3 · **AL-8** |
| 12 | **Rookie auction.** Before each sale: projected price, tier, budgets, nominations, needs, values, market sources, stage; after: clearing price. Learn price curves, position/tier premiums, nomination-order and scarcity effects, budget pressure, manager tendencies. Eventually show fundamental estimate, expected clearing price, range, pressure, confidence | Perfect Draft `src/draft/` + `frontend/lib/perfect-draft.js` (`C7-DRAFT-03`); pre-auction snapshot `scripts/backtest_perfect_draft.py --record-snapshot` (`C7-DRAFT-02`, manual); room engine `src/auction/` (store `data/auction/auction.sqlite`); Sleeper `metadata.amount` (`src/public_league/draft.py`) | room command log + awards persisted and backed up; realized Sleeper prices readable | the pre-sale state (board + roster context + plan) is captured only by hand (G5); backtest BLOCKED (exit 2) until it is | Wave 3 · **AL-9** (capture half before the 2027 auction, §36) |
| 13 | **Sharp Score / Manager Scout.** The hand-set Sharp Score weights are the champion, not assumed optimal; test whether its characteristics predict future useful outcomes (performance, roster-value development, trade outcomes, consistency, titles, longevity), cautious about causality; challenger methodologies. Manager Scout learns behavior (picks vs youth, contend/rebuild, consolidation, depth, position demand, moving elite QBs / IDPs, FAAB aggression, acceptance when observable). Sparse managers shrink heavily. Accepted trades alone cannot calibrate an acceptance probability | Sharp `src/sharp/score.py` + `config/sharp/scoring_v2.json` + `src/sharp/cohort.py` (`C4-SHARP-01`); evidence `src/sharp/platform_records.py`, `data/intel/ledger.sqlite3`; Manager Scout `src/intel/` (`C6-MGR-01`, ABSENT) | daily cohort snapshots (`data/sharp/cohort/`), records/rosters/activity crawls | no evaluation of Sharp characteristics vs later outcomes; no behavioral model; rejected/countered offers are not legitimately observable for other leagues (R14 stays CANDIDATE for our own) | Wave 3 · **AL-10** (Sharp Score validation), **AL-11** (Manager Scout behavior) |
| 14 | **Trade recommendations.** No single "who won" label. Archive the decision-time state (canonical values, transaction-market estimate, BDVM, roster marginal impact, contend/rebuild state, alternatives, recommendation, confidence); evaluate later on explicit dimensions (market value, realized scoring, lineup contribution, roster improvement, liquidity, picks, competitive path). Never train a model to reproduce future canonical values | `src/trade/finder.py`, `src/trade/suggestions.py`, `src/trade/angle.py`, `src/trade/trade_simulator.py`; decision contract `C7-DESK-01` (ABSENT); history `C3-REPLAY-01` / `C3-AGE-01` | nothing preserved at decision time (G8) | the decision-time archive is the whole gap; outcomes exist (temporal ledger, realized points, rosters) | Wave 3 · **AL-13** (capture half is Wave 1, §36) |
| 15 | **Roster utility / team strength.** The lineup solver stays deterministic. Learn distributions around future contribution: replacement value, starter displacement, depth insurance, injury resilience, scarcity, age effects, concentration risk. Improve Team Strength / Weakness and roster marginal impact without a new player-value engine | `src/ros/lineup.py` (`C2-LINE-01`, deterministic, never learns); strength `src/roster_intel/strength.py` (`C2-STR-01`), weakness `C2-WEAK-01`, replacement `C2-REPL-01` (DUPLICATED), simulation `C2-SIM-01` | exact solver; measured endogenous starters (`league_intel/replacement.py`) | roster snapshots + projections exist only partly point-in-time (Game Day pregame for rostered players); no distribution model; `C2-REPL-01` consolidation precedes | Wave 3 · **AL-12** |
| 16 | **Player development / role transition.** Preserve snaps, routes, targets, carries, aDOT, air yards, first downs, pass-rush opportunity, depth chart, injuries, transactions, age, draft capital, team context. Point-in-time models for breakout, role expansion/loss, starter probability, decline, career survival, evaluated against future usage. May support BDVM; must never become market-price observations | `src/playerctx/` (`C1-RET-08` weekly history); nflverse stats/PBP/depth charts (`src/nfl_data/`, `dynasty-pbp-weekly`, `dynasty-depth-charts-refresh`, `dynasty-reception-depth`); profile `C6-UPP-01`; BDVM `C5-BDVM-01` | weekly playerctx snapshots (backed up); nflverse is an external historical archive | point-in-time depth-chart state is overwritten daily (§36); no role model | Wave 4 · **AL-14** |
| 17 | **Analyst / podcast / news reliability.** Add outcome resolution to the point-in-time ledger. Reliability by analyst × claim type × position × horizon × team × event type; no universal analyst score; calibration and sample size; content lineage so syndicated statements are one information event | `src/analyst/` (`C6-ANA-01`); take freshness `C6-FRESH-01`; podcast/YouTube/X `C6-POD-01` / `C6-YT-01` / `C6-X-01` | store + as-of + claim/stance code | no scheduled producer (nothing accumulates, §36); no outcome resolution; content-lineage dedupe is specified but absent | Wave 4 · **AL-15** |
| 18 | **DFS.** Do **not** create another DFS learning system: complete `docs/dfs/ROADMAP.md` Phase H. Per slate preserve source + ensemble projections, projected and actual ownership, salary, lineup distributions, correlation, duplication estimate, optimizer recommendation, contest, entries, scoring, placements, payouts. Evaluate sources, ownership, distributions, correlation, field, duplication, stacks, portfolio, late swap, contest selection, entry count. Never optimize on ROI from a few slates; chronological contest holdouts | `src/dfs/` Phase H harness — `pit.py` (point-in-time ledger, MOD-01), `backtest.py` (MOD-09), `metrics.py` (MOD-10), champion/challenger gates (MOD-11), `settlement.py`, `results.py` | harness built; **zero settled contests** (ROADMAP Phase H "HARNESS BUILT, NO DATA") | settled-contest evidence (actual ownership, placements, payouts) does not exist; slate-level raw inputs partly overwritten (§36) | Wave 4 · **AL-16** = a pointer to DFS Phase H, not a new unit or system |
| 19 | **Alerts.** Learn ACTIONABILITY, not engagement; never optimize for clicks. Preserve alert, reason, urgency, deadline, whether action occurred, outcome. Objective: fewer, better alerts | Edge Alerts `C7-ALERT-01` (ABSENT) over `C6-SIG-01`; existing emitters `src/api/bdvm_signal_alerts.py`, signal-alerts and custom-alerts sweeps | per-user alert state in `user_kv` (latest state, not an event log) | no alert-event archive with action/outcome join | Wave 4 · **AL-17** |
| 20 | **Adaptive source acquisition.** Learn when each source changes, event-triggered patterns, information per fetch, request cost, failure/rate-limit behavior, downstream value of freshness; schedule intelligently. Critical deadlines impose safe maximum ages; a learned schedule may never miss required freshness through overconfidence | freshness `src/sources/freshness.py` + `config/sources/freshness_v1.json`; clocks `src/sources/dataset_state.py`; content staleness `config/source_staleness.json`; watchdog `scripts/watchdog_freshness*`; timers `deploy/systemd/` | cadence-relative freshness; content vs fetch clocks separated; source-CSV git history doubles as a change log | per-fetch change/no-change log is not persisted as one series (§36); no learned scheduler; maximum-age floors are not written as a contract a scheduler must satisfy | Wave 4 · **AL-18** |

Wave 4 item 24 — **personalized models** — is **AL-19**, gated on explicit, resettable per-user evidence; nothing
personal is learned from implicit behavior.

## 28. Roadmap order — Waves 1–4 (directive §23)

The order serves the owner's current priority: **make Calculator's trade values as trustworthy as possible.**
Parallelize perishable capture and independent domain work where safe; serialize shared canonical owners.
Existing AL labels from #1593 are kept wherever they map; new labels continue the series.

| Wave | Directive item | Unit label(s) | Native owner | Status at reconciliation (2026-10-01) |
|---|---|---|---|---|
| **1 — NOW** | 1. Valuation Trust / source-quality learning | AL-1a–d | Batch 3 (`F-SRC-01`, `C6-FRESH-01`) | #1584/#1589/#1590/#1591/#1592 merged; equal-family champion retained; AL-1a waits on AL-0 |
| 1 | 2. Completed-trade ledger + KTC + Sharp/Sleeper IDP transaction market | AL-2 ops (first production capture + censuses), AL-2a (done, #1595), AL-2a′ BROAD_CONTEXT, AL-2a″ IDP inventory | `C4-MTL-01/02`, `C1-ACQ-01`, `src/sharp/` | #1586 merged but **not yet running in production** (box serves `ed48d54ab`, §36) |
| 1 | 3. Format-aware trade normalization | AL-2b0 translator readiness table, AL-2b (≤ 1 preregistered shadow translator), AL-2c (latent price, shadow) | `C4-MTL-03` | AL-2b0 after the accumulated census |
| 1 | 4. Perishable-evidence capture gaps required by Wave 1 | AL-P1 … AL-P8 (§36.3, ranked) | each stream's existing owner | audited in §36; none implemented by this planning PR |
| 1 | 5. Shared receipts / model-registry extensions | AL-0 (#1597, in round-two review), **AL-0b Model Lab backend contract** (§33) | `src/model_registry/` + `src/history/` (`C10-ML-01`) | AL-0 open, unmerged |
| 1 | 6. BDVM / projection point-in-time archive + evaluation foundation | AL-3a (archive completeness + `data/bdvm/` backup), AL-3b (scorecard vs equal-family champion) | `C5-BDVM-01`, `C5-ROS-01`, `C5-GD-02` | pregame archive merged (#1525); AL-3a/3b not started |
| **2 — NEXT** | 7. Projection-family evaluation + learned ensemble challengers | AL-3c | `C5-ROS-01` | after AL-3b |
| 2 | 8. BDVM parameter / stat-model calibration | AL-3d (= Batch 3 J2) | `C5-BDVM-01` | after AL-3b |
| 2 | 9. Game Day calibration | AL-4a / AL-4b | `C5-GD-01/02` | after AL-0 |
| 2 | 10. Playoff / title calibration | AL-5a / AL-5b / AL-5c | `C5-PLAY-01` | AL-5a capture moves into Wave 1 item 4 as AL-P6 (§36.3); 5b/5c NEXT |
| 2 | 11. Future-pick probability model | AL-6 | `C1-PICK-03` | capture half AL-P4 in Wave 1 |
| 2 | 12. Power predictive-component validation | AL-7 | `C5-POW-01` | — |
| **3 — NEXT/LATER** | 13. FAAB clearing-price learning | AL-8 | `C4-FAAB-01/02` | — |
| 3 | 14. Rookie auction learning | AL-9 | `C7-DRAFT-02/03` | capture half before the 2027 auction |
| 3 | 15. Sharp Score validation | AL-10 | `C4-SHARP-01` | — |
| 3 | 16. Manager Scout behavioral learning | AL-11 | `C6-MGR-01` | — |
| 3 | 17. Roster utility distributions | AL-12 | `C2-STR-01`, `C2-REPL-01` | — |
| 3 | 18. Trade recommendation evaluation | AL-13 | `C7-DESK-01` | capture half AL-P5 in Wave 1 |
| **4 — LATER** | 19. Player development / role transitions | AL-14 | `C6-UPP-01`, `C1-RET-08` | — |
| 4 | 20. Analyst intelligence reliability | AL-15 | `C6-ANA-01` | — |
| 4 | 21. Full DFS Phase H learning once settlement data exists | AL-16 → `docs/dfs/ROADMAP.md` Phase H | `src/dfs/` | — |
| 4 | 22. Alert actionability learning | AL-17 | `C7-ALERT-01` | — |
| 4 | 23. Adaptive acquisition scheduling | AL-18 | freshness owners | — |
| 4 | 24. Personalized models (explicit, resettable evidence only) | AL-19 | — | — |

**Reconciling the #1593 AL-0…AL-5 labels.** AL-0 stays the first foundation unit and is Wave 1 item 5. AL-1 is
Wave 1 item 1. AL-2 spans Wave 1 items 2 and 3. AL-3a/AL-3b are Wave 1 item 6; AL-3c/AL-3d are Wave 2 items 7 and
8. AL-4 and AL-5 stay NEXT (Wave 2 items 9 and 10), except the AL-5a forecast *capture*, which the audit (§36)
moves forward because playoff forecasts are perishable. Part II §22's priority order AL-0 → AL-1 → AL-2 → AL-3
→ AL-4 → AL-5 is unchanged.

## 29. Automatic learning cadence per model family (directive §24)

**Rule.** Do not retrain because a clock fired. A family evaluates, or refits a challenger, only when one of
these holds: enough new observations accumulated; a new settlement cohort exists; drift was detected (§20);
the season regime changed; or a material methodology candidate is ready. Observation and settlement can be
scheduled; evaluation and refit are *triggered*. **Promotion authority is never a cadence.**

| Model family | Observation cadence (existing owner) | Outcome settlement | Evaluation trigger | Challenger refit trigger | Drift check | Promotion authority |
|---|---|---|---|---|---|---|
| Source quality / weights (AL-1) | every board scrape, 2 h (temporal ledger; source-CSV git history) | rolling, per horizon (future board, completed trades once AL-2c exists) | new horizon cohort settled | material candidate or source drift | each scrape: content staleness + lineage sweep | Batch 3 §N |
| Hill masters | each material market refresh (~2 h) | dynasty holdout boards (`src/model_registry/holdout.py`) — necessary, not sufficient (§35 T9) | every refit | material refresh | holdout history | **Hill Autopilot** (OFFENSE only) + human `promote`/`apply`; automatic promotion `AUTO_PROMOTION_BLOCKED: no_independent_validation_target` until a preregistered independent target exists (§35 T9) |
| Sparse evidence (E) / robust filter (F) | 2× daily shadow (`dynasty-sparse-evidence-shadow` 08,20:05 UTC; `dynasty-joint-filter-shadow` 07,19:55 UTC) | later boards | preregistered sample reached | candidate ready | per run | Batch 3 §N |
| Completed-trade translators / latent price (AL-2b/2c) | KTC capture every 30 min (`dynasty-ktc-trades`, :07/:37); ledger daily (`dynasty-market-trade-ledger`, 08:52 UTC) | subsequent completed trades in the target format | ≥ 1 complete window turnover with no gap, then each new target-format holdout cohort | axis becomes identifiable | per capture: window overlap / turnover / gap flag | Batch 3 §N; never rewrites canonical value before dedupe + topology validate |
| Projections (AL-3) | pre-kickoff archive (Game Day collector); weekly BDVM snapshot (Tue) | weekly realized points after the stat-correction window | weekly settlement cohort | sample-gated per position × category | weekly coverage/ancestry | owner approval (no family policy yet) |
| BDVM components (AL-3d) | weekly snapshot | season / horizon outcomes | seasonal cohort | candidate ready | per snapshot | owner approval |
| Game Day (AL-4) | every generation (live collector, per minute in windows) | finals + correction window | weekly | sample-gated by game state | weekly reliability | owner approval |
| Playoff / title (AL-5) | every 2 h sim (once archived, AL-P6) | season end | season end (in-season: reliability only) | before any simulation rebuild | weekly | owner approval; D2/D3 open |
| Future picks (AL-6) | weekly forecast (once archived, AL-P4) | actual draft slot after the season | season end | season end | weekly | owner approval |
| Power predictive components (AL-7) | weekly publication | following weeks' outcomes | season / half-season | candidate ready | weekly | owner approval; descriptive contract untouchable |
| FAAB (AL-8) | daily history + 3-hourly crowd | weekly waiver run | settlement cohort | sample-gated per manager | weekly behavioral | owner approval |
| Rookie auction (AL-9) | per sale (room log / Sleeper) | the sale itself | per auction | per auction | per auction | owner approval |
| Sharp Score (AL-10) / Manager Scout (AL-11) | daily crawls + cohort snapshot | season outcomes, later roster value | season end | season end | monthly behavioral | owner approval |
| Roster utility (AL-12) / trade rec (AL-13) | weekly rosters; per served recommendation (once AL-P5 lands) | weeks → seasons | settlement cohort per horizon | candidate ready | weekly | owner approval |
| Player development (AL-14) | weekly playerctx + nflverse | following weeks' usage | weekly / seasonal | candidate ready | regime (preseason / in-season) | owner approval |
| Analyst (AL-15) | per claim (once a producer exists) | horizon-dependent resolution | per resolved cohort | — | per source | owner approval |
| DFS Phase H (AL-16) | per slate | contest settlement | chronological contest cohort | sample-gated | per slate | Phase H gates (MOD-11) |
| Alerts (AL-17) | per alert | action / outcome window | monthly | candidate ready | monthly | owner approval |
| Acquisition scheduling (AL-18) | per fetch | next fetches | monthly | candidate ready | per run | owner approval; maximum-age floors are hard constraints |

Families without an explicit policy promote only by explicit owner approval (§20 rule 6).

## 30. Rejected challengers are retained evidence (directive §25)

Never delete a failed model's evidence because it lost. Every challenger keeps: candidate config; training /
input fingerprint; evaluation results (with `n`, intervals and preregistration hash); **why it failed**; and
which cohorts it helped or hurt. This is what stops the system rediscovering the same bad idea six months later.

- **Mechanism:** the AL-0 evaluation receipt (§19.2) plus a PROMOTION RECORD whose disposition may be
  `rejected` or `retained_champion`. The store is append-only (A2); there is no delete path. Rejection reasons
  and per-cohort deltas are first-class fields, not prose.
- **Precedents already on `main`:** Hill challenger records in `config/model_registry/`; Batch 3 evidence
  directories under `docs/valuation/evidence/` (#1589 equal-family champion retained; #1590 INCONCLUSIVE; #1591
  flag OFF, fails preregistered G2c; #1598 D2 evidence only). AL-1a back-fills these as receipts.
- **Acceptance (folded into AL-0 / AL-1a):** a test proves no code path deletes or overwrites a challenger
  receipt; the Model Lab (§33) lists rejected challengers beside running ones.

## 31. Explanation and user trust (directive §26)

When a learned model eventually changes a user-facing recommendation, the user must be able to see why — never
"unexplained AI magic". Examples the owner gave, kept as the target register:

- "FantasyCalc currently receives slightly lower influence here because this observation is old and its recent
  incremental predictive evidence for this population is weak."
- "IDP Show receives increased projection influence for LB tackle forecasts because its held-out error has
  been lower over the validated sample."
- "Transaction value confidence is low: only 3 target-comparable IDP trades exist; 14 additional trades
  required format transformation."
- "Game Day 71% is calibrated from 486 comparable archived states."

Requirement: every promoted learned influence carries machine-readable reasons (the evidence class, sample
size, holdout window, cohort and evaluation cutoff) from its receipts, so the explanation is generated from
evidence rather than written by hand. The display belongs to **Lane 6** where user-facing confidence,
provenance and explanation already live; no new surface ships until the contract is stable. Development
metrics are not shown to ordinary league users without a product reason (§33).

## 32. Testing, authority and implementation style (directive §27–§29)

**Tests (§27) — a standing checklist for every AL unit.** Each PR states, per item, `APPLY` (with the test) or
`N/A` (with the reason): point-in-time integrity; no future leakage; deterministic replay; input / model
fingerprints; missingness; sparse samples; corrupted observations; duplicate evidence; correlated evidence;
source lineage; format mismatch; regime change; rollback; champion / challenger isolation; promotion gates.
**A random train/test split is prohibited wherever temporal ordering matters** — holdouts are chronological,
league, player, source-family or contest-chronological (§20 rule 4). AL-0's A1–A10 already cover the first
five; the rest bind the domain units that consume it.

**Authority (§28).**

| Authorized | Not authorized |
|---|---|
| planning reconciliation | autonomous trades |
| required archive / capture work | autonomous waiver claims or drops |
| shared learning receipts | autonomous DFS entries |
| evaluation infrastructure | hidden recommendation changes |
| shadow challengers, scorecards, drift monitoring | self-promotion of a model outside its approved gate |
| domain-specific evaluation loops | spending on new paid data or services without separate authorization |
| dependency-ready units in the §28 roadmap | — |

Objective correctness fixes merge after normal gates. **Learned numerical methodology changes require the
existing P6 / model-registry acceptance process.**

**Style (§29).** No whole-roadmap PR. First the reconciled execution map (this Part), then dependency-ready Wave 1
units in small coherent PRs, grouped as: FOUNDATION (shared receipt / evaluation / registry extension);
VALUATION (source quality + completed trades + translation); PROJECTIONS / BDVM (prediction archive +
evaluation); INTEGRATION (connect the foundation to each native owner); UI / LANE 6 (explanation, provenance,
status wherever the contract is stable). Independent mathematical review for material learned-model changes;
security / privacy review for behavioral or private evidence; personal-league and private data stay private.

## 33. Model Lab — backend contract (directive §22) · unit AL-0b

A **backend / internal contract first**, not a public UI. It answers, per model family: MODEL (champion
version); CHALLENGERS (running candidates); DATA (training / evaluation window); SAMPLE SIZE; LAST EVALUATED;
METRICS; CALIBRATION; DRIFT; PROMOTION STATUS; ROLLBACK VERSION; DATA QUALITY / COVERAGE.

- **Scope:** a read-only, typed view assembled from AL-0 receipts and `src/model_registry/` — no new store, no
  second registry. Missing fields are explicit (`unobserved`, `insufficient_sample`), never 0.
- **Exposure:** private / admin. It may later back an owner-facing admin page; ordinary league users do not see
  development metrics without a clear product reason. User-facing confidence / provenance stays Lane 6.
- **Depends on:** AL-0 merged. **Acceptance:** every family with at least one receipt appears with all eleven
  fields populated or explicitly unobserved; rejected challengers listed (§30); the import / write boundary of
  A7 holds; the payload is never served on a public route.

## 34. Completion standard — four closed loops (directive §30)

"Adaptive Learning" is **not** implemented because a planning document exists. The roadmap foundation is
complete only when at least the first real closed feedback loops exist in code, on actual data where enough
exists (synthetic fixtures prove mechanics only). Wave 1 acceptance must demonstrate all four. State of each
stage at this reconciliation, from code and production:

| Loop | Stage | State 2026-10-01 | Closing unit |
|---|---|---|---|
| **SOURCE** | historical source observation | EXISTS — temporal ledger + source-CSV git history | — |
| | future evaluation target | EXISTS — #1589 leave-family-out / lead-lag targets | — |
| | source scorecard | EXISTS (report) — #1589 evaluator | AL-1a (as receipts) |
| | challenger weighting | EXISTS (shadow) — #1589 weight challengers | AL-1b |
| | held-out comparison | EXISTS — #1589 walk-forward | — |
| | promotion / rejection record | **MISSING** as a durable registry disposition | AL-0 + AL-1a |
| **TRADE** | raw completed trades | CODE MERGED (#1586); **not capturing in production** (box at `ed48d54ab`) | AL-2 ops (deploy + first capture) |
| | deduplicated underlying transactions | CODE MERGED (#1586 §19 groups) | — |
| | format classification / translation | classification MERGED (three dispositions; BROAD_CONTEXT pending); translation **MISSING** | AL-2a′, AL-2b0, AL-2b |
| | target-league transaction estimate | **MISSING** | AL-2c |
| | comparison with subsequent evidence | **MISSING** | AL-2c + AL-1 outcome (2) |
| **PROJECTION** | pregame projection | PARTIAL — our ensemble's pregame estimates for rostered players exist from Week 1 (`data/game_day/predictions/2026/*/week_N/*_pregame.json`, backed up); raw Sleeper weekly projections only from Week 3, and Week 3 itself may be partial (its directory was created 2026-09-25 23:20 UTC, after the Week 3 Thursday game; unverified) — §36 | AL-3a |
| | actual game result | EXISTS — `src/nfl_data/realized_points.py` | — |
| | source / stat-category error | **MISSING** | AL-3b |
| | challenger ensemble | **MISSING** | AL-3c |
| | held-out comparison | **MISSING** | AL-3c |
| **MODEL GOVERNANCE** | model version | EXISTS for Hill (`src/model_registry/versioning.py`); partial elsewhere (BDVM `modelVersion`/`paramSetId`) | AL-0 |
| | evaluation | EXISTS for Hill (#1588 holdouts) | AL-0 |
| | challenger | EXISTS for Hill | AL-0 |
| | registry disposition | EXISTS for Hill only | AL-0 |
| | reproducible rollback | EXISTS for Hill (`scripts/model_registry.py`) | AL-0 / AL-0b |

**Verdict:** no loop is closed in code for a non-Hill family today. The Hill governance loop is the only closed
loop, and only for Hill. Wave 1 is complete when SOURCE, TRADE, PROJECTION and GOVERNANCE each run end to end on
real data, with the gaps above closed and evidenced.

## 35. What Part III supersedes or refines

| # | Earlier clause | 2026-10-01 re-send / continuation | Disposition |
|---|---|---|---|
| T1 | Part II §21.2 and the 2026-10-01 Batch 3 addendum (intake): "exactly one of NATIVE_COMPARABLE / VALIDATED_TRANSFORMABLE / TARGET_UNSUPPORTED"; "every non-native trade is TARGET_UNSUPPORTED until a translator validates" | Continuation: **four** dispositions — NATIVE_COMPARABLE; VALIDATED_TRANSFORMABLE (none merely because the class exists); **BROAD_CONTEXT** (verified dynasty, trustworthy identity and topology, a material format dimension differs / is unknown / untranslated; `targetPriceAuthority = 0`); TARGET_UNSUPPORTED narrowed to **hard insufficiency** (redraft; keeper for the current dynasty lane; unknown / unverified dynasty; unusable transaction identity; analysis-blocking unresolved assets; invalid topology; other hard integrity failure) | **Superseded.** Implemented as its own PR (AL-2a′) after the bootstrap census; until then the code emits three and the census labels the gap. Regression: the former #1595 verified-dynasty-candidate population maps to BROAD_CONTEXT unless another hard failure applies. No canonical value change. **Superseded further by T8** (BROAD_CONTEXT sub-kinds; strict NATIVE timing) |
| T2 | Part II §21.1 AL-1a: "register Batch 3 evaluator outputs (#1589, #1590, #1591) as receipts" | AL-1a wires prospective receipts to the sparse-evidence shadow, robust-filter shadow, source-quality evaluator, Hill refits, translator experiments and latent-price experiments; then projection-family evaluation and Game Day calibration. No promotion in AL-1a | **Refined** (wider producer list, same unit) |
| T3 | Part II §21.5 / §22: AL-5a forecast archive is NEXT, "commit history mitigates meanwhile" | §21 lists playoff probabilities as high-priority perishable evidence: capture first | **Refined.** AL-5a capture moves into Wave 1 as AL-P6 (§36.3); AL-5b/5c stay NEXT |
| T4 | Part II §22: AL-3b "NOW" | Wave 1 item 6 = archive **and evaluation foundation**; item 7 (Wave 2) = learned ensemble challengers | **Consistent.** AL-3b (scorecard vs equal-family champion) stays Wave 1; AL-3c is Wave 2 |
| T5 | Part II §14: "autonomous roster transactions" listed as not decided | §28: autonomous trades, waiver claims / drops and DFS entries are explicitly **not authorized** | **Refined** (now explicit) |
| T6 | Part II §17 note on R14 | §13 needs rejected / countered / expired offers "when legitimately available"; §28 does not authorize private-offer capture | **Unchanged** — R14 stays CANDIDATE |
| T7 | #1598 (D2) recorded OTC as an ancestry-safe holdout | Continuation: D2 stays evidence only; no promotion of c3 / repaired constants / H1–H3 / DLF native spacing from OTC alone; if OTC is not ancestry-safe, do **not** rewrite #1598 — mark its external-validity limitation and stop treating OTC as a valid sole promotion target (#1599 re-measures) | **Recorded.** Hill-vs-trade evaluation later, on the populated ledger, with no evidence reuse; package residuals only where topology permits. **Refined by T9 / T10**: #1599 found OTC not ancestry-safe; that exclusion stands, and automatic promotion now needs an independent target |
| T8 | T1 four dispositions; the Sharp / own-league format-capture BRACKET (#1607): exact only when a capture at or before the trade is confirmed by a later same-hash observation; season-final / post-trade captures capped at TARGET_UNSUPPORTED "→ BROAD_CONTEXT when that tier lands" | **Owner methodology decision 2 (A + D), 2026-10-01:** keep strict point-in-time NATIVE_COMPARABLE; BROAD_CONTEXT has two sub-kinds — **timing-limited** (verified dynasty; later/final season settings match the target on all observed material axes; nothing brackets the format at transaction time; reason stamped, e.g. `season_final_settings`, `post_trade_capture`, `format_unconfirmed_at_trade`, `all_observed_axes_match_target`; never implies exactness) and **format mismatch** (known target-format differences, no validated translator); TARGET_UNSUPPORTED = redraft, keeper for the current dynasty lane, unverified dynasty state, unusable identity / topology, other hard integrity failure. Season-final or post-trade captures never make a trade NATIVE; scoring-only before/after evidence is not enough while roster structure / team count stay temporally unproven | **Recorded (§35.1).** Implemented by AL-2a′ on `claude/broad-context-disposition`. `targetPriceAuthority = 0` until a translator validates; no canonical value change |
| T9 | Hill Autopilot promoted OFFENSE automatically on the dependent-board holdout gates (`docs/valuation/HILL_AUTOPILOT_V2.md`); §20.6 / §29 named it the bounded automatic-promotion example | **Owner methodology decision 1 (A), 2026-10-01:** automatic OFFENSE promotion requires at least one genuinely independent validation target; the board gates stay required (necessary, not sufficient); with no eligible target: `AUTO_PROMOTION_BLOCKED: no_independent_validation_target`. Fitting, evaluation, persistence counting, shadow runs and evidence accumulation continue. A future target is preregistered and does not derive materially from the training families | **Recorded (§35.1).** Implemented on `claude/hill-autopilot-independent-gate`. No fake target to restore promotion; manual / model-governance review stays separate |
| T10 | #1599's category rule (MEASURED ≥ +0.30 and ≥ 90% snapshots positive; SUSPECTED +0.10 to +0.30 and ≥ 75%), declared after its data were seen | **Owner methodology decision 3, 2026-10-01:** those thresholds and labels are descriptive history, never prospective methodology; the next dependence classification is preregistered before its result set is examined (multiple cutoffs, distinct-version consistency, effective sample size, uncertainty interval, estimator floor, rank vs spacing, autocorrelation). OTC's +0.45 / 21-of-21 dependence on KTC stays sufficient for exclusion; Fitzmaurice / Nerds labels stay descriptive; fail closed when independence is not established | **Recorded (§35.1).** `lineage-policy/v1` preregistered; #1599 artifacts immutable |

### 35.1 Owner methodology decisions — final (2026-10-01)

The owner closed three open methodology questions. They are final for the current Calculator valuation /
adaptive-learning program. Intake: `docs/OWNER_REQUESTED_TODO.md`, "Owner methodology decisions — final". Recording
them changes no canonical player value.

**Decision 1 — Hill Autopilot needs an independent validation target (T9).**

- Automatic OFFENSE Hill promotion requires at least one **genuinely independent validation target**.
- The existing dependent-board holdout gates stay and may stay required. They are **necessary, not sufficient**.
- With no eligible independent target, the Autopilot verdict is
  `AUTO_PROMOTION_BLOCKED: no_independent_validation_target`.
- Research does not stop. Challenger fitting, evaluation, persistence counting, shadow runs and evidence
  accumulation continue normally. The board gates are neither weakened nor removed.
- A future independent target must be **preregistered** and must not derive materially from the same training
  families. No fake target may be created to restore automatic promotion.
- **Leading candidate: the completed-trade ledger (AL-2)**, with two caveats:
  - KTC Trade Database evidence alone is **not** automatically independent validation for a KTC-trained curve
    (KTC-platform trades are in-sample for KTC Trades; #1599 said the same).
  - Prefer deduplicated, format-qualified transaction evidence with independent provenance, especially
    Sharp/Sleeper observations. A target that mixes dependent and independent provenance must say how
    independence is treated, per provenance class. It is never called independent as a whole.
- Manual / model-governance review stays separate from unattended Autopilot promotion. This decision closes the
  automatic-promotion loophole only.
- Today no board is an ancestry-safe holdout (#1599). The Autopilot is therefore expected to report the blocked
  verdict until a preregistered target exists.

**Decision 2 — strict NATIVE timing plus BROAD_CONTEXT (T8).**

- NATIVE_COMPARABLE keeps the strict point-in-time rule. A pre-trade (in-force) capture plus a later same-format
  confirmation must bracket the transaction under the canonical timing contract.
- A season-final or post-trade capture does not prove the format held all season:
  - completed-season final settings never make an old trade NATIVE retroactively;
  - a matching post-trade capture never makes an earlier trade NATIVE;
  - scoring-only before/after evidence is not enough while roster structure, team count and other axes stay
    temporally unproven.
- **BROAD_CONTEXT, timing-limited:** a verified dynasty trade whose later/final season settings match the target
  on every observed material axis, but with no valid evidence bracketing the format at transaction time. The reason
  is stamped (for example `season_final_settings`, `post_trade_capture`, `format_unconfirmed_at_trade`,
  `all_observed_axes_match_target`), and exactness is never implied.
- **BROAD_CONTEXT, format mismatch:** a verified dynasty transaction with known target-format differences and no
  validated translator.
- **TARGET_UNSUPPORTED:** redraft, keeper for the current dynasty target lane, unverified dynasty state, unusable
  identity or topology, or another hard integrity failure.
- The approximately 2026-era trades that match `dynasty_main`'s current axes without a predating or bracketing
  capture stay usable as clearly labelled BROAD_CONTEXT, not NATIVE.
- Unchanged from T1: `targetPriceAuthority = 0` until a translator validates; no VALIDATED_TRANSFORMABLE merely
  because the class exists; the former #1595 verified-dynasty-candidate population maps to BROAD_CONTEXT unless
  another hard failure applies.

**Decision 3 — lineage dependence thresholds (T10).**

- #1599's thresholds and labels (`docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md`) are **descriptive
  historical output**. #1599 is not rewritten, and its two artifacts stay immutable.
- They are **not** prospective methodology. The next prospective dependence classification runs under
  `lineage-policy/v1` (`docs/sources/lineage_policy/LINEAGE_DEPENDENCE_POLICY_v1_PREREGISTRATION.md`). It was
  preregistered in its own commit (`94e16c4f1a986ecc3045d1b4702ce6efe0d8cc05`) before any result set was examined
  under it, and its normative block is hash-pinned by `tests/sources/test_lineage_policy_v1_preregistration.py`.
- The policy evaluates magnitude above an explicitly estimated leave-pair-out floor, consistency across distinct
  source versions (never snapshots), an AR(1)-adjusted effective sample size, a block-bootstrap interval, and rank
  and spacing dependence separately. It reports a sensitivity grid that is never decisive. It never treats an
  unproven pair as independent.
- No current conclusion changes. OTC's ~+0.45 / 21-of-21 dependence on KTC stays sufficient: OTC is never an
  independent KTC-family holdout. The Fitzmaurice and Dynasty Nerds labels stay descriptive. Hill exclusion and
  promotion safety fail closed whenever independence is not established.

## 36. Perishable-evidence audit — extended (directive §21)

"Before building sophisticated models, audit whether their required historical evidence is being preserved. If
something will disappear, CAPTURE FIRST." The durable audit record is `docs/BRISKET_IDEAS.md` §13 (2026-09-29),
**extended in place by §13.4** with this pass. Summary here; method, evidence and the full table there.

### 36.1 Production facts (read-only box check, 2026-10-01)

- The box serves `ed48d54ab` (#1589). #1586's `dynasty-ktc-trades` / `dynasty-market-trade-ledger` timers and
  #1591's `dynasty-sparse-evidence-shadow` are **not installed**; `data/market_trades/` does not exist. The KTC
  Trade Database is therefore **not being captured in production**.
- The nightly root backup (`riskit-state-backup.service`) runs a **stale root-owned copy** of the backup script
  that lacks the acquisition, auction and `game_day` lines; those streams are protected today only by the
  post-deploy generation. `temporal_ledger.sqlite` (1.49 GB), `consensus_edge.sqlite`, `data/bdvm/` and
  `data/dfs/` are in no generation.
- The Game Day collector's first NFL week directory is Week 3 (created 2026-09-26): Sleeper pregame weekly
  projections for 2026 Weeks 1–2 were never captured.

### 36.2 Verdicts (full evidence: `docs/BRISKET_IDEAS.md` §13.4)

| Stream | Verdict | Owner | Gap |
|---|---|---|---|
| Pregame projections — Sleeper weekly | PARTIAL | `src/ros/game_day_live.py` (#1525) | Weeks 1–2 lost; first archive build (Week-8 prune) not yet observed |
| Pregame projections — BDVM season snapshots | AT_RISK | `scripts/refresh_bdvm_projections.py` | not backed up |
| KTC Trade Database | AT_RISK | `src/sources/ktc_trades.py`, `src/trade/market_trade_archive.py` (#1586) | not running in production; not in backup |
| Sharp / Sleeper trades | PARTIAL | `src/intel/ledger.py`, `src/sharp/` | 400-day prune; tar of a live WAL database |
| Source boards / change clocks | PRESERVED | `CSVs/site_raw`, `src/sources/dataset_state.py` | history lives in version control only |
| KTC unselected format variants | NOT_CAPTURED | `src/source_archive/` | no scheduled caller (G3) |
| Game Day predictions | PRESERVED | `src/ros/game_day_archive.py`, live generations | nightly backup copy stale |
| Playoff / title probabilities | PARTIAL | `src/ros/scrape.py` → `data/ros/sims/` | overwritten; commit-only history; no model identity |
| Power snapshots | PRESERVED | `src/ros/power_snapshots.py` | — |
| FAAB losing bids | PRESERVED (failed claims) / NOT_OBSERVABLE (rival bids) | `src/trade/faab_history.py` | host-limited; never imputed |
| Rookie auction sales | PARTIAL | `src/auction/store.py`, `src/public_league/draft.py` | pre-sale state manual (G5) |
| Pick forecasts | NOT_CAPTURED | `src/ros/pick_projection.py` | computed per request; team-strength input overwritten |
| Recommendations | NOT_CAPTURED | finder / suggestions / angle / FAAB / Perfect Draft | nothing persisted at decision time (G8) |
| Analyst claims | NOT_CAPTURED | `src/analyst/` | no producer |
| DFS projections / salaries | AT_RISK | `src/dfs/auto/refresh.py` | not backed up |
| DFS ownership / settlements | NOT_CAPTURED / NOT_OBSERVABLE | `src/dfs/results.py` | owner upload only; Phase H has no data |

### 36.3 Ranked Wave 1 capture units

Authorized as Wave 1 item 4; **not implemented by this planning PR**. Exact scope per unit in
`docs/BRISKET_IDEAS.md` §13.4.

1. **AL-P1** — KTC Trade DB production capture: finish the deploy chain, verify the timers, record the first
   capture, back up `data/market_trades/archive.sqlite`.
2. **AL-P2** — Backup coverage (G7 widened): market-trade archive, Consensus Edge, `data/bdvm`, `data/dfs`,
   shadow ledgers, `data/learning`, the temporal ledger (or a written rebuild rationale), online intel backup;
   reinstall the stale root copy and prove the nightly generation. Serial owner of `deploy/backup/` (= AL-3a's
   backup half).
3. **AL-P3** — KTC unselected format variants into `src/source_archive/` (paired-format evidence for AL-2b).
4. **AL-P4** — Pick forecast + team-strength weekly snapshot (feeds AL-6).
5. **AL-P5** — Recommendation / decision receipts at serve time (after AL-0; feeds AL-8, AL-9, AL-13).
6. **AL-P6** — Playoff / title dated forecast archive with model identity (= AL-5a capture).
7. **AL-P7** — Sharp trade retention past the 400-day prune.
8. **AL-P8** — Projection archive completeness verification (= AL-3a archive half).

Outside Wave 1: analyst claims (AL-15), DFS settlements (Phase H), G4 injury / news, G5 draft-time state
(before the 2027 auction), G6 league settings.

## 37. Campaign sequencing — continuation instructions (binding for this campaign)

Recorded as current sequencing in `docs/EXECUTION_PLAN.md` §0. In order, with parallel lanes where files do not
collide:

1. **Deploy verification.** Finish the deploy chain; verify the served SHA, health, and the ledger / KTC /
   sparse-shadow timers from actual `systemctl` state. *(At reconciliation the box served `ed48d54ab` — #1589 —
   and `dynasty-ktc-trades`, `dynasty-market-trade-ledger` and `dynasty-sparse-evidence-shadow` were not
   installed; `dynasty-joint-filter-shadow` was installed and had not yet fired.)*
2. **First KTC production capture.** Record raw / new / known / resolution / unresolved / format coverage. No
   canonical value change.
3. **Bootstrap census**, labelled **"BOOTSTRAP / INITIAL COVERAGE"**. No translator is fit from it.
4. **Collector age ≠ market sparsity.** Per capture, track cumulative unique KTC trade ids, window overlap and
   turnover; flag coverage gaps.
5. **Accumulated census**, labelled **"ACCUMULATED COVERAGE — POST WINDOW TURNOVER"**, using identical census
   code, after at least one complete observed window turnover with no gap. The earliest census usable for AL-2b
   identifiability.
6. **BROAD_CONTEXT PR (AL-2a′)** after the bootstrap census, with the owner's exact four-disposition definitions
   (§35 T1) and the regression test. No canonical value change. *Refined by owner decision 2 (§35 T8 / §35.1):
   timing-limited and format-mismatch sub-kinds with reason stamps; strict NATIVE timing kept. In progress on
   `claude/broad-context-disposition`.*
7. **IDP market inventory (AL-2a″)** reported separately in every accumulated census.
8. **Translator readiness table (AL-2b0)** per axis — 1QB↔SF, 1TE↔2TE, TE scoring edge, team count, roster
   depth, total IDP starter depth, DL/LB/DB structure, selected IDP scoring families — reporting one-axis-
   different unique trades, distinct leagues, asset overlap with target-format observations, time coverage,
   target-format holdout sample and confounding; each axis classified **READY_FOR_PREREGISTERED_TEST /
   PROMISING_BUT_CONFOUNDED / INSUFFICIENT_SAMPLE / NOT_IDENTIFIABLE**. No subjective score.
9. **At most ONE shadow translator (AL-2b)**, only if an axis is identifiable; preregistered; compares A exclude /
   B naive / C candidate; success only on real held-out target-like trades, **never against current Calculator
   values**. BDVM ratio only as a tested structural prior carrying coverage and uncertainty.
10. **AL-0 (#1597)** merges only after round-two review approves: store path restricted to `data/learning` with
    explicit test injection; the feature lock compares against a real prior baseline and fails closed;
    conflicting inserts surface; correction chains acyclic, latest = latest valid revision; artifact `knownAt`
    passes the temporal guard. No production writer yet.
11. **AL-1a order** after AL-0: prospective receipts for sparse-evidence shadow, robust-filter shadow,
    source-quality evaluator, Hill refits, translator experiments, latent-price experiments; then
    projection-family evaluation, then Game Day calibration. No promotion in AL-1a.

Standing: #1594 (deploy drift-reinstall) merged 2026-10-01 — **a deviation from the owner instruction** not to
close it until its drift-reinstall invariant is green: it merged on green Linux CI drift tests, before the
invariant was observed on the box. It must be observed green on the box at the next deploy, not assumed. D2 (#1598) stays evidence only (§35 T7).

**Champion — unchanged:** equal-family base authority; `freshness × health × coverage`; family caps; the current
Hill champion; the current outlier filter; the current 0.30 sparse retention.

## 38. Unresolved — Part III

- The four Wave 1 loops (§34) are open; only Hill's governance loop is closed.
- Production lags `main`: the box served `ed48d54ab` at reconciliation, so #1586's KTC capture has not started
  and every KTC Trade Database window that rolls out before it does is lost (§36).
- BROAD_CONTEXT (§35 T1) is a recorded owner definition, not yet code.
- No per-family promotion policy exists outside Hill Autopilot and Batch 3 §N; every other family promotes only
  by explicit owner approval.
- FAAB losing bids for rivals and other leagues' rejected / countered offers are host-limited (NOT_OBSERVABLE);
  never imputed.
- `C5-POW-01`, `C5-PLAY-01` and `C2-REPL-01` remain DUPLICATED; their learned units (AL-7, AL-5, AL-12) land on
  the consolidated owner, not on either duplicate.
- The capture units AL-P1…AL-P8 (§36.3) are authorized as Wave 1 work but not implemented by this planning PR.
- Hill automatic OFFENSE promotion is blocked until a preregistered independent validation target exists (§35.1,
  T9). No such target is preregistered yet; the completed-trade ledger needs per-provenance independence
  treatment (KTC-platform trades are not independent of a KTC-trained curve) and is not yet capturing in production.
- Decisions 1 and 2 are recorded but their code units (`claude/hill-autopilot-independent-gate`,
  `claude/broad-context-disposition`) are not merged.
- `lineage-policy/v1` is preregistered, not implemented: the instrument extensions (detrended rank residual,
  version-blocking, simulated floor, validation suite) and the v1 category vocabulary are a separate reviewed
  unit, and each application needs its own run preregistration.
