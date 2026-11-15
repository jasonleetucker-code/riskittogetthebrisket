# ROS horizon ordering and prospective confirmation: preregistration

**Status:** PREREGISTERED, RESEARCH ONLY. It is not a model promotion and it changes no value, ranking, flag or
team-strength formula.
**Date:** 2026-11-01, recorded before any Week 9 game kicks off (Week 9 first kickoff: 2026-11-05 ET).
**Authority:** owner decision D4 (2026-11-01). That decision accepts the ROS scale diagnosis and does **not** promote a
new model. It authorizes:

- the frozen Week 8 confirmation (PR #2035);
- prospective confirmation on further weeks;
- a preregistered evaluation of ROS-horizon cross-position ordering;
- a separate `rosPointsPerWeek` shadow field behind a default-OFF flag, only if the evidence justifies it.

It does **not** authorize replacing `rosValue`, changing dynasty prices, altering team-strength formulas or promoting
CR.
**Parents:** `ROS_SCALE_CALIBRATION_PREREGISTRATION_2026-10-28.md` (the original study),
`ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md`, and `ROS_WEEK8_CONFIRMATION_RUNBOOK_2026-11-01.md` together with its
results file.

## 0. What this document cannot do

**The original G3 stays FAILED.** G3 was preregistered on 2026-10-28 as single-week cross-group pair ordering
(ΔConc CI lower > 0), pooled over weeks 5–7. CR scored −0.0060, CG −0.0007 and CF −0.0056. No analysis here re-scores,
re-defines, re-pools or supersedes that gate. The 2026-10-28 verdict (`DOES_NOT_PASS` for CG, CF and CR) is final for
that study.

The gate in §3 is a **new** research gate, `H1`. A pass on `H1` is new evidence that the owner may weigh. It does not
turn G3 into a pass, and it does not by itself justify any live change.

## 1. Model freeze (prospective)

1. Before the first kickoff of each prospective week *w* ≥ 9, the frozen artifact is
   `docs/league-intelligence/evidence/ros_scale_calibration/fits_week8_frozen.json`. It was fitted on weeks 1–7 and
   committed in `0726dbd09` at 2026-10-28T15:34Z. The pinned Git blob is
   `cbed086e21deca852f8db9abf3ef1de26656158d`.
2. **No refit** is allowed during the prospective window. Weeks 8 onward are evaluation-only, so an outcome can never
   reach a coefficient that is later scored against that same outcome.
3. Per-week freeze receipt: before kickoff of week *w*, a commit on a research branch must record:
   - *w*;
   - the frozen-fit blob SHA;
   - the scoring-card fingerprint;
   - the code SHA of `scripts/ros_scale_calibration_study.py` and the confirmation runner;
   - the as-of snapshot that `snapshot_before(first_kickoff(w))` will select. If that snapshot is not on disk yet,
     record the selection rule.

   The commit timestamp is the evidence. A week with no pre-kickoff receipt is **excluded** from the prospective pool
   and listed as excluded. It is never back-filled.
4. A refit, a changed card or a changed population rule starts a **new** preregistration. It never amends this one.

## 2. Prospective accuracy confirmation (P1, reported)

Same models (C0, CG, CF, CR, F), same population (`in_population`), same metrics M1/M2 as the original §4. The pool is
every receipted, finalized week from 8 onward. Report pooled and per-week:

- MAE;
- ΔMAE vs C0 (player-cluster bootstrap, B = 2,000, seed 20261028);
- the group ratios R_OFF and R_IDP;
- D = R_IDP / R_OFF with CI.

**Confirmation criterion (reported, not a promotion gate):** CR's out-of-sample advantage counts as *confirmed* when
both of these hold on the prospective pool:

- pooled ΔMAE(C0 − CR) has CI lower bound > 0;
- |D_CR − 1| ≤ 0.10.

It counts as *not confirmed* when ΔMAE's CI upper bound is < 0 or D_CR falls outside [0.90, 1.10]. Otherwise it is
*inconclusive*. These are the conditions §7 of the original preregistration set for "only after the week-8
confirmation".

## 3. New research gate H1: ROS-horizon cross-position ordering

**Question:** does a challenger order offense players against IDP players better than C0 does, judged by how many
points each player scores over the rest of the season rather than in one week?

- **Origin weeks:** each receipted prospective week *h* ∈ {8, 9, …} for which at least two later finalized weeks
  exist.
- **Prediction:** μ_X for each player in `P_h` (the as-of population at origin *h*), from the frozen fits.
- **Target:** the realized mean points per appeared week over weeks *h* … *H*. *H* is the last finalized week at
  evaluation time, capped at week 14 (the last regular-season week in `dynasty_main`). A player needs at least 2
  appearances in that window.
- **Pairs:** all (OFF, IDP) pairs within an origin week with no tie in realized mean. Pairs are pooled over origins.
- **Statistic:** ΔConc_ROS = Conc_ROS(X) − Conc_ROS(C0). The CI is a 95 % player-cluster percentile bootstrap
  (B = 2,000, seed 20261101). Clusters are players: one resample draws whole players, so all of a player's pairs and
  origins move together.
- **Minimum sample:** ≥ 1,000 valid pairs and ≥ 3 origin weeks. Below that floor, H1 reads `INSUFFICIENT`, which is
  not a pass.
- **H1 passes** for challenger X when ΔConc_ROS CI lower > 0.
- **Multiplicity:** three challengers are tested (CG, CF, CR). H1 is reported per challenger with no correction, but
  only **CR** was named as the candidate in the 2026-10-28 results (§7.2). A pass for CG or CF alone is reported as
  exploratory.

Overlapping windows from adjacent origins are correlated. The player-cluster bootstrap absorbs this within each
player. The result must also report the per-origin ΔConc_ROS values, so that a single origin cannot carry the
pooled number unseen.

**Disclosed prior information:** the retrospective weeks 5–7 ROS-horizon concordance (C0 0.673, CR 0.698, 86,529
pairs) is known. That information motivates this gate. Those weeks are **not** in H1's sample: H1 uses prospective
origins only.

## 4. What results would justify (and what they would not)

| outcome | justifies |
|---|---|
| P1 confirmed and H1 passes for CR | an owner proposal for a `rosPointsPerWeek` **shadow** field: a separate field behind a new default-OFF flag, with no consumer reading it. Any consumer change, a change to `rosValue` or to team strength, or a CR promotion needs a separate owner-approved methodology decision. |
| P1 confirmed, H1 fails or is INSUFFICIENT | report only; continue collecting weeks; no field |
| P1 not confirmed or inconclusive | report only; no field |
| anything | **G3 (2026-10-28) remains FAILED** |

## 5. Outputs

- Evidence: `docs/league-intelligence/evidence/ros_scale_calibration/prospective_week<w>.json` (P1, per week) and
  `ros_horizon_h1.json` (H1, written once the minimum sample is reached).
- Results: one markdown file per evaluation date. It reports every model, every per-origin number, exclusions and
  deviations.
- No live board, flag, cache or consumer is written.

## 6. Deviations

Any deviation from this document, such as a missing receipt, a scoring-card change, a population change or a data
outage, is listed in the results file with its effect. It is never absorbed silently.
