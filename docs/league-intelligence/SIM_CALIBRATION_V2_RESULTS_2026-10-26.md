# Best-ball sim points model, v2 challenger: results

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served. Every output carries `promotes: false`.
`data/league_intel/` was never written. The challenger file uses a schema the production loader refuses
(`productionLoaderSource: "fallback-constants"`, recorded in the evidence).

**Provenance:**

| item | value |
|---|---|
| preregistration | `docs/league-intelligence/SIM_CALIBRATION_V2_PREREGISTRATION_2026-10-26.md`, commit `ad8ab042f`. It was committed alone and pushed at 2026-10-26T17:32:25Z, before the script existed. |
| script | `scripts/sim_calibration_v2_study.py`, commit `8bd4e8b41` (17:39:42Z) |
| evidence run | code SHA `8bd4e8b41`, clean tree (`studyCodeDirty: false`). Generated at 17:50:58Z. The prereg commit is an ancestor (`isAncestorOfCodeSha: true`). |
| card | `sf1:9e51824690d091f9` (live `dynasty_main`) |
| inputs | v1's 49 cached bodies, sha256-identical to v1's evidence. 0 network calls. Same three rosValue snapshots. |
| comparator V1 | v1's frozen candidate, sha256 `cee877c2…` (verified) |
| challenger V2 | `evidence/sim_calibration_v2/challenger_v2_points_model.json`, sha256 `421b7eda23771276a16295a63e016756df9600560a3b735257e4f9e3363f65b9` |
| evidence | `evidence/sim_calibration_v2/evaluation_v2.json` |
| base | PR #1963 (v1), **not merged** at the time of writing |

**Holdout used:** 2026 weeks 5–6, the same as v1. Week 7 was **not** used: at run time 13 of its 14 games were final
in the schedule body. The run clock was 17:50Z, and DAL at PHI kicks off at 00:15Z on 2026-10-27. Per preregistration
§2, week 7 is deferred.

**The data path is proven unchanged.** V2-D6 compared 285 fields of the v2 run's F and V1 numbers against v1's
published `evaluation.json`, and **all 285 match**. The fields cover:

- player level, pooled and per family, including the V1 − F bootstrap intervals;
- team-week metrics and D4;
- the census;
- the realized cross-check;
- the pooled scale, 1.4764.

## Verdict: `CHALLENGER_DOES_NOT_BEAT_FALLBACK`

V2 fails SC-G1, SC-G3, SC-G4 and SC-G5. Under preregistration §7 there is **no owner request**. Production keeps
serving what it serves today.

| gate | result | key numbers (V2 = challenger, F = fallback, V1 = v1 candidate; holdout weeks 5–6) |
|---|---|---|
| SC-G1 coverage (PIT) | **FAIL** | All 7 gated families fall outside the band. Pooled PIT coverage 80 / 95: V2 0.674 / 0.820, V1 0.749 / 0.837, F 0.425 / 0.587. |
| SC-G2 log score | **PASS** | Pooled ΔLS (V2 − F) +16.58 [+10.55, +24.09], 957 player-weeks, 579 players. No gated family is significantly worse. |
| SC-G3 CRPS | **FAIL** | Pooled ΔCRPS (F − V2) −0.373 [−0.759, +0.0004]. **LB is significantly worse**, at −3.33 [−4.69, −1.99]. |
| SC-G4 PIT | **FAIL** | V2's KS D runs from 0.152 (QB) to 0.329 (LB) against a 0.08 limit. Pooled D: V2 0.137 < F 0.362, so the relative half passes. |
| SC-G5 team-week | **FAIL** | V2 80% / 95% coverage 0.250 / 0.542, mean bias **+112.6**. F: 0.000 / 0.083, bias −108.9. CRPS: V2 85.72 < F 95.37, so the relative half passes. |

Gated families (n ≥ 50): QB 64, RB 122, WR 181, TE 90, DL 133, LB 161, DB 170. K (n = 36) is reported, not gated.
The literal v1 SC-G1, on censored-interval coverage, also fails in all 7 families (non-gating).

**This is not a strict-gate artifact.** Preregistration §6.1 disclosed, before looking, that a perfectly calibrated
model passes SC-G4 only about 2% of the time at these family sizes. The size-aware reading (V2-D2, never gated) shows
V2's failures are real:

- **KS D.** It exceeds its own 95% critical value in 6 of 7 families. QB is the exception: D 0.152 against a critical
  0.167, p = 0.094.
- **PIT coverage.** PIT coverage 95 lies below the exact binomial 95% range in **all 7** families. PIT coverage 80
  lies below it in 5 of 7. TE and DL are inside at 80, but not at 95.

## The challenger that was fitted

| family | own `k` (scale-fit n, players) | `cv` (within-player) | fallback `k` / CV | V1 `k` / CV (raw key) |
|---|---|---|---|---|
| QB | 1.454 (37) | 0.662 | 2.7 / 0.32 | 1.476 / 0.752 |
| RB | 1.919 (86) | 0.665 | 2.7 / 0.55 | 1.476 / 0.875 |
| WR | 1.626 (125) | 0.717 | 2.7 / 0.60 | 1.476 / 0.890 |
| TE | 1.285 (59) | 0.766 | 2.7 / 0.65 | 1.476 / 0.925 |
| K | 0.600 (20) | 0.454 | 2.7 / 0.55 | 1.476 / 0.502 |
| DL | 1.359 (84) | 0.766 | 2.7 / 0.55 | 1.476 / 0.964 (DE .924, DT .819) |
| LB | 1.311 (93) | 0.571 | 2.7 / 0.45 | 1.476 / 0.686 |
| DB | 1.304 (111) | 0.589 | 2.7 / 0.50 | 1.476 / 0.708 (CB .669) |

Every family cleared the 30 player-week floor, so no family took the pooled scale. The raw-position table is
`{FB: RB}`, as the preregistration expected.

Within-family R² of the owner's through-origin fit:

- negative for every IDP family (DL −0.08, LB −0.11, DB −0.27) and for K (−0.52);
- QB 0.11, TE 0.28, WR 0.46, RB 0.65.

## What V2 fixes

**Offense means are now calibrated.** Holdout realized/predicted:

- QB **1.00**, against 1.86 for F and 1.02 for V1;
- RB **1.06**, against 1.49 (F) and 0.81 (V1);
- WR **1.03**, against 1.72 (F) and 0.94 (V1).

V2 is significantly better than V1 on RB and WR CRPS: +0.63 [+0.15, +1.13] and +0.27 [+0.11, +0.42].

**K is fixed.** Realized/predicted is 0.89, against 4.02 for F and 2.20 for V1. Against V1, ΔLS is +11.3 [+4.6, +19.7].

## What V2 gets wrong

### 1. The IDP means are worse, and the cause is two named a priori risks compounding

Holdout realized/predicted:

| family | V2 | V1 | F |
|---|---|---|---|
| LB | 0.546 (over by 83%) | 0.616 | 1.13 |
| DL | 0.757 | 0.823 | 1.51 |
| DB | 0.861 | 0.975 | 1.78 |
| TE | 0.838 | 0.963 | 1.76 |

Two descriptive analyses, both declared before looking, decompose the miss:

- **V2-D3, regression direction (fit window only).** The owner's fit regresses rosValue on noisy 4-week means, then
  inverts the fit to predict points. That over-predicts in the fit window itself:

  | estimator | fit-window realized/predicted |
  |---|---|
  | owner's inverse fit (V2's) | 0.81–0.95, lowest at DL 0.81, DB 0.87, TE 0.85, LB 0.89 |
  | ratio estimator `Σr/Σȳ` | **0.99–1.04 in every family** |
  | forward fit | 1.11–1.29 (over-corrects) |

  The attenuation is largest where the within-family R² is lowest, which is the IDP families.
- **V2-D5, snapshot drift (inputs only).** For the same evaluated players, mean as-of rosValue over mean preseason
  rosValue is:
  - LB **1.61** in week 5 and **1.60** in week 6;
  - DL 1.28 and 1.28;
  - DB 1.21 and 1.31;
  - offense 0.93 to 1.05.

  A scale fitted on the preseason snapshot cannot follow this.

The two compound. For LB, the fit-window ratio 0.888 divided by the drift of about 1.60 gives about 0.55. That matches
the observed 0.546. The same arithmetic gives DL 0.81 / 1.28 ≈ 0.63 and DB 0.87 / 1.26 ≈ 0.69. Those land below the
observed 0.76 and 0.86, so drift is not the whole IDP story for DL and DB. The direction is right and the size is
approximate.

v1 had the same drift. What it hid there was a pooled `k` that happened to sit higher than the IDP families' own
inverse-fit `k` (1.476 against 1.30 to 1.36). Per-family fitting removed that accidental cushion.

### 2. σ is too narrow at player level

The within-player CV measures week-to-week spread around a player's own mean. The predictive also carries the error in
`r / k_f`.

- **Fit-window residual CV (V2-D7) runs 0.61 to 0.89**, against a within-player CV of 0.45 to 0.77.
- The gap is largest at LB (0.79 against 0.57) and DB (0.78 against 0.59).
- In the holdout, V2 under-covers in every family. Pooled PIT coverage is 0.674 at 80 and 0.820 at 95.

This is the third a priori risk named in preregistration §3.4.

### 3. Team-week totals are still about 113 points high

- Mean bias is **+112.6** a team-week, against V1's +115.8 and F's −108.9.
- 80% coverage is 0.25 and 95% coverage is 0.54.
- CRPS 85.72 is essentially V1's 85.71.

Narrowing the CV removed part of v1's order-statistic inflation. The IDP and TE over-prediction, in 11 of 21 starting
slots, put it back.

D4, without the availability filter, is worse still: V2 bias +185.2, CRPS 152.4. F scores CRPS 63.0 there, again only
because drawing players who did not play offsets part of F's deficit.

### 4. Overall, V2 is worse than V1

| comparison | pooled V2 − V1 | 95% CI |
|---|---|---|
| ΔLS | −0.82 | [−1.54, −0.14] |
| ΔCRPS | −0.16 | [−0.27, −0.03] |

V2 wins on RB, WR and K. It loses on DL, LB, DB and TE CRPS (LB −1.19 [−1.52, −0.87]).

## Deviations from the preregistration (disclosed)

None of substance. Gates, split, inputs, seeds and methods ran as written. Minor items:

1. The prereg's header said it was written at "about 17:40Z". The commit time is 17:32:25Z.
2. Each model's summary gained a reported `meanPredictedSigma` field. It is descriptive only, and no gate reads it.
3. The week-7 finality check read v1's cached schedule body. That body was fetched earlier on 2026-10-26 and shows 13
   of 14 games final. A fresh body would say the same, because the run preceded DAL at PHI's kickoff.

## What remains for an owner decision

Promotion is owner-only, and **this study requests none**.

1. **Neither candidate in hand is promotable**, and the served fallback is still measured as badly miscalibrated:
   - team totals about 109 points low;
   - 0 of 24 team-weeks inside its 80% interval;
   - the offense means are off by 1.5x to 1.9x.

   Whether the surfaces fed by it (playoff odds, Game Day, best-ball marginal utility, the forecast archive) need a
   caveat or a priority fix is the owner's call. That was already open after v1.
2. **What a v3 would need, from v2's evidence.** This lane is not authorized to change the points-model owner
   (`src/league_intel/sim_calibration.py`), and each change below is a new candidate with its own preregistration:
   - a mean-calibrated scale estimator per family (the ratio estimator is 0.99–1.04 in the fit window), in place of
     the inverted rosValue-on-points fit;
   - handling of rosValue snapshot drift for IDP: fit the scale on each week's as-of snapshot, or re-anchor per
     snapshot;
   - a predictive σ that includes mean-prediction error (the residual CV), not the within-player CV alone.
3. **The gates.** As written, SC-G4 is passed by a perfectly calibrated model about 2% of the time at these family
   sizes, and SC-G1 about 27% of the time. A future preregistration could size-control them, for example D against
   the family's critical value, or binomial-range coverage. That is a methodology decision for the owner.
   **v2's own failures do not depend on it**: V2 fails the size-aware reading too.
4. **Week 7.** Only matters for a request, and there is none. It needs a schedule body fetched after DAL at PHI is
   final. The cache is write-once and holds the 13-of-14 body. The run would be:
   `--frozen-challenger …/challenger_v2_points_model.json --expect-sha256 421b7eda… --eval-weeks 7 --out-name evaluation_v2_week7.json`.

## Reproduce

```
python scripts/sim_calibration_v2_study.py --offline
python -m pytest -p no:cacheprovider tests/league_intel/test_sim_calibration_v2_study.py tests/league_intel/test_sim_calibration_study.py
```

`--offline` needs `data/idp_accuracy/cache/` populated with v1's bodies. The run takes about 11 minutes, almost all of
it the 2,000-draw team-week sims for three models, with D4.

## UNRESOLVED

- **Two holdout weeks only**, as in v1. Team-week n = 24, with no season-level outcome.
- **Positions come from today's Sleeper directory.** Team-week availability is the oracle filter. 2025 lines are
  rescored under the 2026 card. All three are inherited from v1.
- **The cause of the IDP snapshot drift is not established.** In-season IDP sources entering the rosValue aggregate
  is plausible but unverified.
- **Whether the fallback's level bias moves relative standings or odds** is still not measured.
