# League-specific projection, scarcity and dynasty challengers — 2026-10-19

**Status: EVALUATION PLAN (not an approved model promotion).** Linked to `docs/audits/LEAGUE_RULES_VALUE_AUDIT_2026-10-19.md` and `docs/research/LEAGUE_PROJECTION_DATA_ACQUISITION_2026-10-19.md`. Protect the canonical market-consensus board pending demonstrated incremental accuracy, valid scale mapping, and explicit model-governance authorization.

## Four separate estimates, four targets

| Estimate | Meaning | Training/validation target | May change `rankDerivedValue` today? |
|---|---|---|---|
| Market dynasty price | What participating dynasty markets collectively ask/pay | Contemporaneous independent trade/market evidence, temporal holds | Existing production owner ONLY |
| League-scored seasonal forecast | Expected distribution of player fantasy outcomes under exact rules | Future host-awarded weekly points and calibrated distribution | **No** |
| League intrinsic multiyear utility | Marginal replacement-adjusted *multi-season* contributions given league format, age, retention | Held-out multiyear realizations and lineup impact | **No; shadow candidate** |
| Roster/manager conditional utility | Marginal team/manager value considering teammates, bye/variance, availability, competitive window | Held-out incremental team points, playoff/championship outcomes, decisions | **No; strategy display only** |

Uncertainty is material: scarcity estimates from incomplete rosters or a 0–100 ranking index should not receive an invented precise dollar/9999 conversion.

## Proposed challenger formulation (subject to evidence)

1. **Event-resolved exact score:** generate expected category counts `E[count_k]`; where Sleeper directly awards stat keys, `E[fantasy_pts] = Σ rate_k × E[stat_k]`. For threshold/derived keys calculate the expected *event count* directly, not `bonus(E[yards])`. Correlated defensive events must share a joint event model even if expectation is linearly additive.
2. **Weekly joint distribution:** forecast `P(active)`, usage and event outcomes. Preserve within-player/week correlations and team-game covariates. Simulate each calendar week and re-solve the exact optimal lineup via `src/ros/lineup.py`; compare marginal expected lineups **with and without** the player, with admissible roster replacement. Never compare a season-long average to best-ball outcome.
3. **Scarcity:** measure waivers/rostered supply and endogenous slot allocation from current league inputs, but calibrate structural priors across dated roster snapshots and held-out host weeks. Avoid letting one stale superstar determine all position factors.
4. **Multiyear utility:** forecast age- and position-conditional availability/production and roster replacement for years 1–N with explicit horizon/discount uncertainty; evaluate across several seasons, not only weekly accuracy. Treat future rookie picks via prospect outcome distributions, not guaranteed starter value.
5. **Market mapping:** compare forecast utility with contemporary market prior. If creating a candidate canonical price, calibrate from independent historical evidence using a monotone bounded scale transform (e.g. jointly fitted rank→bounded value map) rather than multiplying `rankDerivedValue` by scalar >1. Avoid adding Superflex and TE demand where those inputs already express it.
6. **Decisions:** trade and waiver actions consume market price, projected league utility and roster-specific impact as explicitly named, separate fields; avoid changing other engines by overwriting one `rankDerivedValue` alias.

### Counterfactual / metamorphic suite

- **Roster:** add a second SFLEX and keep pool fixed → marginal value of viable QBs should not systematically *decrease*; remove required TEs → structural TE replacement advantage should not systematically *increase*; changing deep bench size should affect the waiver pool but not scoring points.
- **Scoring:** increase QB-hit rate keeping other variables fixed → projected point contribution of hit-producing defenders is nondecreasing; increasing completion bonus with identical stat lines should raise corresponding QB totals by exact extra completions × rate difference.
- **Best ball:** identical mean with different variance → weekly lineup selection probabilities may differ; simulation must not infer weekly variance from ordinal `rosValue` as if it were PPG.
- **Cross-league:** `dynasty_main` (IDP) and `dynasty_new` (non-IDP) must not share a scoring/profile fingerprint or projected-point cache if rules differ.
- **Temporal:** historical trades/matchups are evaluated with historical rules and pre-event information only.
- **Source ancestry:** two republishers of the same projection model do not count as two independent ensemble votes.
- **Missingness:** unknown defensive stat columns or forecast for a player never become zero by default; a stale snapshot should not masquerade as live.

## Validation protocol

| Challenger | Baseline | Holdout evidence | Appropriate metrics | Promotion gate |
|---|---|---|---|---|
| Exact league points | Existing host/Sleeper & existing projection resolver | Chronologically frozen predictions vs real player-week award | MAE, RMSE, calibration, coverage by scoring key and position | Reconcile host 2026 scored sample first |
| Multi-source ensemble | Best single valid family and existing `src/ros/aggregate.py` (distinct rank product) | Rolling past weeks; no forecast revisions after kickoff | Error, calibration, interval score, incremental source contribution | Rights and source-family independence verified |
| Best ball | Current `src/roster_intel/best_ball_utility.py` (independent draws/full-season proxy) | Dated roster snapshots + actual weekly outcomes | Optimal lineup delta, start probabilities, week/team error | Respect bye, availability and injury missing-state |
| Replacement scarcity | `src/league_intel/replacement.py` current mean-index route | Real weekly host starts and complete position supply | Threshold stability, demand by FLEX/SFLEX, waiver substitute accuracy | No arbitrary multiplier on 9999 scale |
| Dynasty intrinsic | Canonical consensus and independent trade-price benchmark | Multi-season *as-of* holdout with rules snapshot | Calibration of outcomes and stable decision utility; value-rank calibration | Longitudinal evidence sufficient; owner decision |
| Trade decisions | Canonical trade eval | Historical trades with known context and no look-ahead | Marginal roster win/projection benefit, reliability bins | No automatic canonization based only on backtest MAE |

No single short-season projected-point win proves better dynasty values. Long-term uncertainty and competitive timing must be displayed.

## Ranked execution plan

| Priority | Work | Acceptance & dependence | Boundaries |
|---|---|---|---|
| **P0** | Current Sleeper snapshot + fingerprint/drift; verify 2026 awarded score and aliases | Read-only live GET; reconcile 2026 host-awarded sample; registry parity test | Fail closed if host unavailable; no inferred 2026 score claims |
| **P0** | Production consumer provenance trace | Complete route-by-route table with actual effective config, scenario deltas, authoritative file/line and evidence state | No credit for unused `leagueConfig` parameters |
| **P1** | Exact-rule coverage and anomaly tests | Unknown/nonzero stat keys reported; position+IDP/K/return golden set | Don't break existing source voting or tests |
| **P1** | Best-ball and replacement shadow replay | Measured projected-vs-actual FLEX demand and week-level lineup deltas | No scalar-only value promotion |
| **P2** | Test pre-existing Fantasy Nerds/SportsDataIO keyed weekly adapter activation | Legal/credential posture, actual fields, timestamps, snapshot hash, coverage and holdout result | Never disclose credentials or silently turn on sources |
| **P2** | Add high-value missing raw categories through authorized providers | PBP/event/schema coverage and distinct source ancestry | Raw-stat projection separate from rank-only |
| **P3** | Independent category-specific offense/IDP probabilistic model | Cross-validation with at least one full held-out season where available; uncertainty & calibration by position | Keep behind experimental flag |
| **P3** | Scoring and best-ball challenger architecture | Clear schema boundaries: market / exact PPG / league marginal / roster marginal | No overwrite of `rankDerivedValue` |
| **P4** | Multi-year league intrinsic dynasty-price conversion | As-of snapshots spanning multiple seasons, non-leakage, learned bounded mapping | Owner must approve promotion after evidence |

## Concrete follow-up tasks for implementation agents

A. Query actual current Sleeper `/v1/league/{id}`, attach timestamped response fingerprint, and compare to dated canonical snapshot. The initial audit environment could not connect to Sleeper; do not call the archived snapshot current.

B. Audit `src/scoring/scoring_delta.py` vs `src/league_intel/scorer.py`: one is a feature delta model with a finite rule table and one is exact raw stat scorer; determine whether any **production** consumer incorrectly assumes the former scores all Sleeper keys. Check route reachability before declaring a bug.

C. Build a route test manifest across Rankings, Second Opinions, War Room, Finder, trade history, power rankings, matchup, waivers/FAAB, picks and draft. Report each production effective config, as-of basis, test result, and exception.

D. Prioritize projection flags and coverage in `config/projections/source_capability_census.json`. A live source entry does not prove a live observation today. Bring a licensing/access receipt with each new production candidate.

E. Evaluate IDP current scoring anomalies (TFL, hits, PD, return stats, hybrid positions) with *future-free* player-weeks.

F. Create shadow model receipts for event category inputs, joint weekly distribution, exact lineup solving and multi-year utility. No arbitrary fake forecasts.

G. Keep current canonical source-consensus owner while evaluating challenger methods. Use isolated worktrees, focused tests, required PR checks and existing autonomous routine merge policy. New canonical valuation requires separate explicit authorization.

## Deliverables status (2026-10-19)

- Initial evidence-based settings/valuation trace: **created**, incomplete consumer-wide sign-off.
- Initial source research: **created**, licensing/coverage checks outstanding.
- Mathematical alternatives and evaluation gates: **documented**, unimplemented.
- Read-only drift/fingerprint utility and unit tests: **initial PR** (not proof of live host connectivity).
- Live configuration, 2026 scoring reconciliation, full propagation sensitivity suite, challenger holdouts, deployed verification: **NOT DONE**.

Do not mark this project DONE until these last items have evidence links. Avoid conflicting with open PRs including source-voting, season projections, War Room or prior parallel-development docs.
