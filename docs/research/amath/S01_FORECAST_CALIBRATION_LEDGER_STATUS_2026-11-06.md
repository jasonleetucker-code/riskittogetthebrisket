# AMATH-S01 / CW-15 — Forecast Calibration Ledger: status (2026-11-06)

Scope: research / scorecard layer only. Nothing here changes a published value, probability or label.
Sources: `docs/research/amath/SITEWIDE_MASTER_2026-11-01.md` (AMATH-S01, POC-B, finding 9),
`docs/research/amath/evidence/sitewide_opportunities_merged.json`, `docs/EXECUTION_PLAN.md` (AL-3b, AL-4a), live code.

## 1. Status table — every surface that publishes a probability or interval

| Surface | Scored against outcomes? | Schedule | Ledger / store | Calibration state published today |
|---|---|---|---|---|
| Weekly projections (point) | AL-3b `projection_scorecard` (point error by cohort; no interval) | **NOW weekly** (this PR: `dynasty-forecast-calibration-ledger.timer`, Tue/Wed, final weeks only). Previously merged-unscheduled (RPA-LGI-004). | Inputs `data/projections/weekly_archive/` (pregame vintages, week 8+); output `data/learning/scorecards/projection_scorecard_<league>.json` (box-local) | None to users |
| ROS value / projections | Scale study script only (`ros_scale_calibration_study.py`), manual; no recurring scorer | Not scheduled | none recurring | None |
| Playoff / championship odds | **No.** `forecast_archive` is capture-only (AL-P6); no evaluator | Capture runs at each ROS refresh + `archive_ros_forecasts` in deploy; scoring not scheduled | `data/forecast_archive/forecasts-YYYY-MM.jsonl` (append-only, gitignored) | Binary disclosure string only (`frontend/lib/odds-disclosure.js`): "not yet calibrated" |
| Game Day win / beat-median probability | AL-4a `game_day_calibration` (Brier etc. vs host finals) | **NOW weekly** (same timer). Collector `game-day-live` already runs every minute. | `data/game_day/live/**/generations.jsonl` in; `data/learning/scorecards/game_day_calibration.json` out | **None shown** on Game Day outputs; runs on fallback CV constants (RPA-F-021) |
| Confidence buckets (HIGH/MED/LOW) | **No.** `config/confidence/gate_v1.json` thresholds are stated PRIORS; no reliability test vs later revision (AMATH D1: weak) | n/a | per-row historical stamps absent from raw archives | Bucket label only; not outcome-calibrated |
| Trade Monte Carlo win rate | No (synthetic flat ±15% band; AMATH-S12) | n/a | none | Hidden per owner decision; remains uncalibrated |
| Sim calibration gates SC-G1..G5 | Study-time gates, fixed thresholds | manual studies | `docs/league-intelligence/evidence/sim_calibration*` | Pass/fail in study docs |

Not yet delivered (stopping where evidence stops): a single `calibrationState` descriptor read by every probability surface,
reliability of confidence buckets (needs per-date replay rebuilds via `src/api/value_replay.py`), and the playoff-odds evaluator
over `forecast_archive`. These need owner authorization (S01 is RESEARCH ONLY in `OWNER_REQUESTED_TODO.md`) and, for the
descriptor, a UI change — out of scope for this PR.

## 2. What was scheduled

`scripts/run_forecast_calibration_ledger.py` + `deploy/systemd/dynasty-forecast-calibration-ledger.{service,timer}.template`,
wired through `install_simple_timer` in `deploy/install-systemd-service.sh`.
- Runs the existing AL-4a and AL-3b scripts unchanged (no new metrics), AL-3b per active league with `--fetch-realized`.
- Tue/Wed 13:40 UTC, `Persistent=true`.
- Refuses unless Sleeper's own state shows a finalized week (`projection_scorecard.host_week_final`); unreadable state = refuse (exit 1).
- Idempotent per week via `data/learning/scorecards/ledger_runs.json` marker; marker advances only if both scorecards succeed.
- Outputs only under gitignored `data/learning/scorecards/`. Tests: `tests/deploy/test_forecast_calibration_ledger_timer.py`.
- Caveat: the pregame archive began week 8 (RPA-COL-020), so early scorecards will report `insufficient_sample`; read them as such.

## 3. Size-controlled gates

Defect (AMATH-S01 / SIM_CALIBRATION_V3): fixed thresholds (`G4_MAX_KS_D = 0.08`, `G1_COV80 = (0.75, 0.85)`, `G1_COV95 = (0.90, 1.0)` in
`scripts/sim_calibration_study.py`) ignore n, so a perfect model fails them at family sizes 56–95.
Implemented in `src/model_registry/size_controlled_gates.py` (imported by no production path): exact Kolmogorov critical value and exact
Binomial coverage acceptance region per family, family-wise level split by Šidák so a perfectly calibrated model passes the whole set with
probability ≥ 0.90 (the audit's admission bar).
Simulation (iid-uniform PITs, family sizes 24/40/56/64/80/95/95, 20,000 reps, seed 20261106): pass rate **0.939**, type-I error **0.061**
(≤ 0.10 nominal; conservative because of Binomial discreteness and within-family dependence). The fixed KS bound rejects the same perfect
model in more than half of runs (test). Tests: `tests/model_registry/test_size_controlled_gates.py`.
Ambiguity left open, documented, not resolved: within-player week dependence (iid assumed), and which gates beyond SC-G1/G4 to re-size —
the existing promotion gates are untouched; adopting any size-controlled gate for a study is an owner methodology decision.
