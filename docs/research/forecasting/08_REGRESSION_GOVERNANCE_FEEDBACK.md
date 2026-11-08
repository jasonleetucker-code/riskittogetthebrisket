# 08. Regression, governance and the weekly accuracy feedback cycle

**Status:** proposal, 2026-11-08. Reuses `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`, `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §20 and `docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md`. It creates no parallel policy. **No automatic retraining or promotion for any production forecast.** The Hill Autopilot exception (`docs/valuation/HILL_AUTOPILOT_V2.md`) does not extend to this family.

## 1. Regression tests a future implementation must carry

| test | proves | failure it catches | existing pattern |
|---|---|---|---|
| Single scorer | Forecast points equal `score_stat_line` on the stat line | A second scorer | AST guards in `tests/lineup/test_single_owner.py` style |
| PIT guard | A feature with `knownAt >= kickoff` raises | Leakage | `src/ros/idp_opportunity/leakage.py` |
| Future-row invariance | Changing rows dated after the cutoff leaves the forecast byte-identical | Silent look-ahead | New property test |
| Determinism | Same inputs and seed give identical output | Hidden clock or unseeded RNG | `projection_scorecard.py` rule |
| Missing is never zero | An absent stat stays absent through scoring | Coercion | Existing scorecard rules |
| Share conservation | Team shares sum to one within tolerance | Over-allocation | New |
| Volume identity | Player stats sum to team stats within tolerance | Inconsistent lines | New |
| Margin-removal golden | Table in `05_` §9 reproduced exactly | Formula drift | New |
| Domain boundary | No new module writes canonical fields | Forecast contaminating dynasty value | `tests/api/test_canonical_ownership_protections.py` |
| Ancestry | A family overlapping another does not vote | Double counting | `projection_source_census.ancestry_overlaps` |
| Frozen study protected | New evaluation cannot read IDP prospective labels by name | Contaminated confirmation | New guard |
| Receipts inert | Every receipt has `promotes: false` | Self-promotion | `src/model_registry/evaluation_receipt.py` |
| Flag off is identical | With the flag off, outputs match the incumbent byte for byte | Regression | `playoff_ros_counted_once` pattern |
| Independent oracle | Hand-computed small cases for shrinkage, hurdle draws and CRPS | Function tested against itself | `docs/engineering/MATH_AUDIT_2026-11-08.md` standard |
| Hard-gate discipline | No test asserts a count over the live board | CI failures caused by data refresh | `CLAUDE.md`, "CI has two lanes" |

## 2. Versioning

| artifact | identifier | owner |
|---|---|---|
| Feature definition | `(name, version)`, hash, append-only lock | `src/model_registry/feature_dictionary.py` |
| Training set | Manifest hash, cutoffs, source hashes | `training_run.py` pattern |
| Model | Family, sub-model, parameters, `paramSetId` | `versioning.py`, registered family |
| Scoring identity | `sf1:*` fingerprint | `src/league_comparison/sleeper_scoring.py` |
| Forecast | `(family, model version, freezeTimestamp, target week)` | Archive |
| Evaluation | Receipt | `evaluation_receipt.py`, `receipt_store.py` |
| Preregistration | Git commit preceding results | Convention in `docs/research/` |

Changing a definition creates a new version. Cohorts of different versions are never pooled.

## 3. Weekly accuracy feedback cycle

The cycle updates **reports**, not coefficients.

| when (UTC) | step | owner | output |
|---|---|---|---|
| Tue, Thu, Sat, Sun before games | Capture provider pools | `dynasty-weekly-projection-capture` timer | Archive |
| Before first kickoff | Freeze in-house forecast (shadow) | *Proposed* shadow job | Freeze receipt |
| Tuesday 06:10 | BDVM refresh | `dynasty-bdvm-refresh` | Snapshots |
| Tuesday, after finals proven | Host stat dump, settled | `projection_scorecard` temporal guard | Realized rows |
| Tuesday or Wednesday 13:40 | Scorecards | `dynasty-forecast-calibration-ledger` | `data/learning/scorecards/` |
| Wednesday | Weekly accuracy digest for the owner | Proposed report over existing outputs | Private markdown or Model Lab |
| Season end | Refit as a **challenger** | Human-run | Evaluation receipt; owner review |

**Digest contents.** Error and bias by position, provider, and in-house arm; 50/80/90 coverage; biggest misses with reason (unprojected, injury, role, variance); coverage of defender-weeks; freshness; status of frozen studies, read from their own runners only.

## 4. Monitoring and degradation triggers

Applies to anything served later; the same checks run on shadow output now. Thresholds are proposals, each to be set from observed noise.

| signal | window | trigger | action |
|---|---|---|---|
| MAE vs the B3 baseline | Rolling 4 weeks by position | Worse by more than 0.25 pts/player-week | Owner notified; consider rollback |
| Bias | Rolling 4 weeks by position | Absolute above 0.75 pts/game | Investigate; serving caveat |
| 80% coverage | Rolling 4 weeks | Outside the exact acceptance region | Serve intervals with "uncalibrated" wording |
| Calibration slope | Rolling 8 weeks | Outside [0.8, 1.2] | Investigate |
| Coverage of players | Weekly | Drop above 10% vs trailing | Source or identity check |
| Feature freshness | Each run | Past lag budget | Feature absent, reported, never stale-served |
| Feature drift | Weekly | Population stability past a set bound | Report only |
| Unresolved identity | Each run | Above existing census level | Refuse affected rows |
| Scorer reconciliation | Weekly | Below the host-exact baseline | Block publish |
| Upstream schema change | Each fetch | Column set changes | Fail closed, alert (`src/api/source_health_alerts.py` pattern) |

A trigger creates a report. It never retrains and never switches models automatically.

## 5. Rollback

| layer | mechanism |
|---|---|
| Serving | Default-OFF feature flag per consumer. `RISKIT_FEATURE_<NAME>=0` and restart, because flag reads are cached per process |
| Family in the ensemble | Remove from the source tuple, or flag off; the combination falls back to remaining families and labels it |
| Model version | Champion pointer in the registry; rollback target recorded before promotion |
| Data | Append-only stores; nothing rewritten, so a rollback never loses evidence |
| Decision consumers | Keep the incumbent mean path alive until the new one has passed a full season |

## 6. Retraining policy

| rule | detail |
|---|---|
| No scheduled refits that serve | A refit produces a challenger and stops |
| Refit cadence | Off-season by default; in-season only under a preregistered rule |
| What may auto-update | Pure reporting, and measured quantities under a preregistered recipe with no parameter change in what is served |
| Temporal integrity | Refits use data through a stated cutoff |
| Promotion path | fit → backtest → validate → compare → human approval → promote → monitor → rollback (`CLAUDE.md`) |
| Rejected models | Kept as evidence, never deleted |

## 7. Governance responsibilities

| role | responsibility |
|---|---|
| Owner | Approves methodology, source spend, promotion, public wording |
| Implementation worker | One claimed unit, L0/L1, independent oracle, default-OFF flag |
| Independent reviewer | Can reject claims of predictive skill; tests leakage controls |
| Integration authority | Exact-tree CI; does not grant methodology approval |
| Scorecards | Deterministic judge of forecast accuracy |

Nothing in this document lifts the owner-reserved limits in `docs/EXECUTION_PLAN.md`, such as forecasting methodology changes, #1938, protected flags, frontend work in the current backend directive, Sleeper writes or spending.
