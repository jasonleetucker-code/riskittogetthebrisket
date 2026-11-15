# 04. Proposed architecture

**Status:** proposal only. Nothing here is built or authorized. `docs/EXECUTION_PLAN.md` remains the sole implementation authority. Package names marked *proposed* do not exist.

**Design rule.** Every layer below already has an owner, except where a row says otherwise. The proposal adds one in-house family, feature-assembly code and shadow evaluators. It adds **no** second scorer, identity resolver, lineup solver, registry or archive.

## 1. The six layers

| layer | job | existing owner (reuse) | gap | proposed addition | never |
|---|---|---|---|---|---|
| **1. Evidence** | Capture sources as received, with rights and time | `src/source_archive/`, `src/ros/weekly_projection_archive.py`, `src/ros/game_day_live.py` pregame archive, `src/nfl_data/actuals_store.py`, `injury_history.py`, `src/ros/forecast_archive.py`, `src/history/`, `exports/archive/`, `config/projections/source_capability_census.json` | Odds archive; weather; PIT depth charts; rights status per use | Odds capture (authorization-pending); per-use rights field in the census | Scrape a barred source; backfill post-hoc data labelled PIT |
| **2. Canonical features and provenance** | Join on identity, derive features with a known-at time | `src/identity/resolution.py`, `src/identity/picks.py`, `src/model_registry/feature_dictionary.py` + `config/model_registry/feature_dictionary.json`, `src/nfl_data/usage_windows.py`, `opportunity_stats.py`, `src/ros/idp_opportunity/leakage.py` (`SeasonData`) | Feature dictionary holds 16 entries, all market and trade features; none for weekly production | *Proposed:* `src/ros/forecast_features/` assembling rows; each feature registered in the dictionary | A second name matcher; a feature without `knownAt` and missing semantics |
| **3. Statistical forecasting** | Volume, share, efficiency, availability, expected stat lines with distributions | Pattern in `src/ros/idp_opportunity/`; `src/ros/projection_observations.py` contract; `src/ros/projection_ensemble.py` | No offense model. No measured dispersion | *Proposed:* `src/ros/production_model/` publishing `ProjectionObservation` rows under family `brisketInternal` | A point total without a stat line; dynasty market as an input to a production forecast |
| **4. League scoring and simulation** | Score stat lines; simulate lineups | `src/league_intel/scorer.py::score_stat_line`, `src/nfl_data/first_down_rate.py`, `reception_shape_projection.py`, `src/ros/lineup.py`, `src/ros/game_day_sim.py`, `src/ros/playoff_sim.py`, `src/league_intel/sim_calibration.py::PointsModel` | Dispersion and correlation unmeasured | Calibrated marginals feeding the existing `draw_from_mean` | A second scorer; greedy lineups; a frontend lineup |
| **5. Decision intelligence** | Convert distributions into actions | `src/waivers/streaming_solver.py`, `src/waivers/advisor.py`, `src/trade/faab_engine.py`, `src/roster_intel/*`, `src/bestball/marginal.py`, `src/ros/game_day_sim.py` | Consumers read means only | Exceedance and regret outputs, reported beside the existing number | Silent execution; a page-local formula |
| **6. Evaluation and governance** | Score, compare, gate, monitor | `src/model_registry/projection_scorecard.py`, `game_day_calibration.py`, `evaluation_receipt.py`, `reproducible_evaluation.py`, `promotion_gates.py`, `size_controlled_gates.py`, `model_lab.py`, `learning_receipt.py`, `training_run.py` | No model family policy for production forecasts | Register a family through `promotion_gates.FamilyPromotionPolicy` | Self-promotion; retraining without a receipt |

## 2. Data flow

```text
licensed PIT evidence (layer 1)
  -> identity + feature rows with knownAt (layer 2)
  -> family forecasts: external families + brisketInternal (layer 3)
       output: Sleeper-vocabulary stat lines, availability, dispersion
  -> combine_ensemble (equal family, existing owner)
  -> score_stat_line under the league card (layer 4, sole scorer)
  -> exact solver / simulators (layer 4)
  -> decision outputs, separately named (layer 5)
  -> archive every forecast before kickoff; score after finals (layer 6)
```

## 3. Three concepts stay separate

| concept | what it means | existing field or owner | may feed | may not feed |
|---|---|---|---|---|
| **Market value** | What the asset trades for | `rankDerivedValue`, `src/sources/ktc_market.py` | Trades, pricing | Production model features for the dynasty lane; replaced by a forecast |
| **Football production** | Stat lines and league points | `ProjectionObservation.league_scored_fpg`, `weeklyPoints`, BDVM fundamentals | Lineup, Game Day, streaming | `rankDerivedValue`, dynasty source votes (`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` §3) |
| **Team-specific utility** | Effect on one roster | `src/roster_intel/best_ball_utility.py` BBLI, `src/bestball/marginal.py` | Private trade and roster advice | Public `/league` surfaces; canonical value |

A surface combining them shows each by name before any synthesis (`docs/MASTER_PRODUCT_PLAN.md` §3.3 signal independence).

## 4. Point-in-time guarantees

| guarantee | mechanism | existing | to add |
|---|---|---|---|
| A forecast uses only what was known before its cutoff | Feature `knownAt` compared to game kickoff | `feature_dictionary`; `lock_baseline_at_kickoff`; `leakage.py` | Enforcement in `forecast_features`: a row with `knownAt >= kickoff` raises |
| Vendor forecasts are the ones held then | Capture before kickoff; lock rule | `weekly_projection_archive.py`, kickoff lock, `dynasty-weekly-projection-capture` timer | Second family when authorized |
| Revised stats do not overwrite old labels | Pin file hash per run | Hashes in `scoring_parity_taxonomy.py` | Same in the training run receipt |
| No future selection for values | `src/history/asof.py` | Yes | Use it for any market feature |
| As-known injuries | `src/nfl_data/injury_history.py` | From its start date | Earlier seasons: labelled `report_unverified_pit`, separate cohort |
| Late-arriving data excluded | Publication lag per feature | Partial (`ftnLagDays`) | Lag table per feature in `06_FEATURE_INVENTORY.md` |
| Model artifacts reproducible | Code SHA, source hashes, feature manifest hash, card fingerprint | `training_run.py`, `reproducible_evaluation.py` | New family registration |
| Forecast was frozen before games | Commit-timestamped receipt | `freeze_receipts/` pattern in IDP study | Reuse |

Two clocks are stored for every observation: **event time** (the game) and **knowledge time** (when we could read it). Revisions create new knowledge-time rows and never edit old ones. This matches `src/history/store.py` (append-only, conflicts surfaced).

## 5. Artifact contract for a production forecast

Extends `ProjectionObservation`; nothing here replaces it.

| field | rule |
|---|---|
| `domain` | One of `weekly_player_statline`, `ros_statline`, `career_production` |
| `providerFamily` | `brisketInternal`, plus sub-model version |
| `evidenceClass` | `PROJECTION_MODEL`, clearly labelled ours |
| `statLine` | Sleeper keys only. Absent key means not projected, never zero |
| `availability` | `P(active)`, state vocabulary from `src/ros/availability.py` |
| `dispersion` | Quantiles or distribution parameters by category group |
| `knownAt`, `freezeTimestamp` | Required |
| `cardFingerprint` | `sf1:*`, or null with `league_scored_fpg` omitted |
| `codeSha`, `featureManifestHash`, `trainingManifestHash`, `sourceHashes` | Required |
| `calibrated` | False until the scorecard says otherwise |
| `promotes` | Constant `false` on every evaluation receipt |

## 6. Failure and missing behavior

| case | behavior |
|---|---|
| Missing projection | `unprojected`, never 0 (`weekly_league_projections.py` states) |
| Model has no features for a player | Abstain with a reason; the fallback is the shrunk baseline and is counted |
| Identity ambiguous | Refuse; never fuzzy-match into a forecast |
| Evidence stale past budget | Lose authority, stay readable |
| Rights unresolved for an input | Input is not admitted to the feature set for training |
| Source outage | Family absent from the combination; not zero-weighted silently; reported |

## 7. Why not two parallel systems

`src/ros/aggregate.py` (ranks) and `projection_ensemble.py` (points) are distinct concepts and stay so. The in-house family is one more row into the existing ensemble contract, the league scorer stays singular, and the simulators keep their owner. BDVM stays a separate fundamental-value concept that may later read this family, as it reads Clay today. The proposal adds a family; it does not replace a system.
