# Best-ball sim points model: calibrated vs fallback, results (RPA-LGI-008)

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served, every output carries `promotes: false`, and
`data/league_intel/` was never written.

**Provenance:**

| item | value |
|---|---|
| preregistration | `docs/league-intelligence/SIM_CALIBRATION_PREREGISTRATION_2026-10-26.md`, commit `d86f30238`, pushed before any model was fitted |
| script | `scripts/sim_calibration_study.py` |
| evidence-run code SHA | `e6d2eb4a4` (clean tree) |
| script sha256 | `ed1651db…` |
| card | `sf1:9e51824690d091f9` (live `dynasty_main`) |
| network calls | 17: the 2025 league's matchups 1–17; everything else came from the cache |
| evidence | `evidence/sim_calibration/evaluation.json` |
| candidate | `evidence/sim_calibration/candidate_sim_points_model.json`, sha256 `cee877c2…` |

## Verdict: `CANDIDATE_DOES_NOT_BEAT_FALLBACK`

The candidate fails SC-G1, SC-G3, SC-G4 and SC-G5. Under preregistration §7, there is **no promotion request**.
Production keeps serving what it serves today.

The candidate is **less wrong than the fallback on most measures**:

- log score;
- PIT shape;
- coverage;
- team-week CRPS.

It is still not calibrated. **The fallback that production runs on today is badly miscalibrated.** Its simulated
best-ball team totals sit 109 points below what teams actually scored, and 0 of 24 team-weeks fall inside its 80%
interval.

| gate | result | key numbers (C = candidate, F = fallback; holdout 2026 weeks 5–6) |
|---|---|---|
| SC-G1 coverage | **FAIL** | 6 of 7 gated families outside the band; RB is the only one inside. Pooled C 80% / 95% coverage 0.782 / 0.850 (F 0.433 / 0.609). |
| SC-G2 log score | **PASS** | Pooled ΔLS +17.39 [+11.23, +24.98], 957 player-weeks, 579 players. No family significantly worse. |
| SC-G3 CRPS | **FAIL** | Pooled ΔCRPS −0.216 [−0.553, +0.114] (C slightly worse, not significant). **LB significantly worse**: −2.14 [−3.18, −1.10]. |
| SC-G4 PIT | **FAIL** | C's KS D is 0.126 to 0.249 in every gated family, against a 0.08 limit. Pooled D: C 0.128 < F 0.362, so the relative half passes. |
| SC-G5 team-week | **FAIL** | C 80% / 95% coverage 0.333 / 0.625, mean bias +115.8. F 0.000 / 0.083, bias −108.9. CRPS C 85.7 < F 95.4, so the relative half passes. |

Gated families (n ≥ 50): QB 64, RB 122, WR 181, TE 90, DL 133, LB 161, DB 170. K (n = 36) is reported, not gated.

## What the fallback constants get wrong, by position (holdout)

The fallback has two parameters: `rosValuePerPoint` 2.7, and CVs of QB .32, RB .55, WR .60, TE .65, DL .55,
LB .45 and DB .50 (CB/DE/DT .55, K default .55).

| family | realized mean | F predicted mean | realized / predicted | F 80% / 95% coverage | F PIT coverage 80 / 95 | F KS D |
|---|---|---|---|---|---|---|
| QB | 17.91 | 9.62 | **1.86** | 0.234 / 0.375 | 0.234 / 0.375 | 0.485 |
| RB | 10.95 | 7.36 | 1.49 | 0.475 / 0.631 | 0.475 / 0.615 | 0.365 |
| WR | 10.87 | 6.33 | 1.72 | 0.436 / 0.646 | 0.420 / 0.608 | 0.370 |
| TE | 7.81 | 4.43 | 1.76 | 0.456 / 0.678 | 0.433 / 0.611 | 0.334 |
| K | 9.00 | 2.24 | **4.02** | 0.194 / 0.306 | 0.167 / 0.222 | 0.704 |
| DL | 9.99 | 6.63 | 1.51 | 0.444 / 0.669 | 0.444 / 0.647 | 0.336 |
| LB | 10.98 | 9.75 | 1.13 | 0.453 / 0.627 | 0.453 / 0.627 | 0.306 |
| DB | 11.30 | 6.34 | 1.78 | 0.482 / 0.606 | 0.476 / 0.606 | 0.377 |
| pooled | 10.96 | 6.97 | 1.57 | 0.433 / 0.609 | 0.425 / 0.587 | 0.362 |

1. **The mean is far too low.** Dividing by 2.7 under-predicts weekly points by a factor of 1.13 (LB) to 1.86 (QB),
   and by 4.0 for kickers. The fitted through-origin scale is **1.476** (R² 0.33, n = 615 players). The fit-window
   ratios (D6) give the same direction: F under-predicts every family by 1.34x to 1.83x, and K by 4.29x.
2. **The variance is far too narrow, worst at QB.** Below is each family's spread under three definitions:
   - the fallback constant;
   - the within-player CV measured in the fit window (D2: each player-season's own weeks, at least 4 weeks);
   - the pooled CV that `build_calibration` measures.

   | family | fallback | within-player | pooled |
   |---|---|---|---|
   | QB | 0.32 | 0.66 | 0.75 |
   | RB | 0.55 | 0.67 | 0.87 |
   | WR | 0.60 | 0.72 | 0.89 |
   | TE | 0.65 | 0.77 | 0.92 |
   | DL | 0.55 | 0.77 | 0.96 |
   | LB | 0.45 | 0.57 | 0.69 |
   | DB | 0.50 | 0.59 | 0.71 |
   | K | 0.55 | 0.45 | 0.50 |

   Draft PR #1941 (since merged) measured DL .73, DB .65 and QB .57 in-sample. Those figures sit beside the
   within-player numbers here.
3. **Team totals are the compound failure.**
   - Mean bias is **−108.9 points** a team-week. The realized mean is 337.0 (range 205.7 to 461.2).
   - Every one of the 24 realized totals sits above the 90th percentile of the fallback's simulated distribution.
   - So the fallback's playoff odds, Game Day and best-ball marginal utility are all drawn from team distributions
     that are too low and much too narrow. The size depends on how availability is handled: about 109 points under
     the primary oracle filter, about 74 with no filter (D4). Production's availability calendar sits between the
     two, and was not replayed here.

   The bias is roughly common to every team, so rankings and head-to-head odds may be less damaged than the
   absolute numbers. **That was not measured here.**

## What the candidate gets wrong

1. **One cross-position scale does not fit.** In the holdout, C over-predicts LB by 62% (predicted 17.84 against
   realized 10.98), RB by 23% and DL by 21%, and under-predicts K by 2.2x.

   In the fit window the same `k` was almost exactly right for LB (ratio 1.00). From the fit window to the holdout,
   the mean predicted points of rostered LBs rose the most of any family (12.12 to 17.84), while their realized
   points fell (12.13 to 10.98).

   rosValue is a rank-derived 0–100 composite, and its cross-position scale is not stable across snapshots. A likely
   but **unverified** cause is that in-season IDP sources entered the aggregate. A single `rosValuePerPoint` cannot
   track that, and the LB miss is what makes SC-G3 fail.
2. **`build_calibration`'s CV is the wrong statistic for this sim.**
   - It is `pstdev / mean` pooled over every player-week at a position, so it includes **between-player** spread.
   - The sim already gives each player his own mean, so it needs the within-player (residual) spread.
   - The pooled CVs run 0.69 to 0.96, against 0.57 to 0.77 within-player.
   - Best ball keeps the best scorers. Over-wide per-player draws therefore inflate the simulated lineup total
     (an order-statistic effect): **+115.8 points** a team-week, even though the pooled player-level mean bias is
     only +1.78.
3. **Shape.** PIT KS D is 0.13 to 0.25 in every family. Exact-content PIT 95% coverage is 0.83 to 0.91, so the
   tails remain under-covered.

## Descriptive analyses (preregistered §8, never gated)

- **D3, raw-path parity.** `score_stat_line(raw host row, raw card)` equals the host-native points on all 9,708 fit
  rows (max |Δ| 0.0). A future writer passing raw Sleeper lines straight into `build_calibration` would score
  correctly on this data.
- **D4, team-week without the availability filter.** Every priced rostered player is drawn, including those who did
  not play:
  - C bias +196.0, 80% coverage 0.042;
  - F bias −73.7, 80% coverage 0.292;
  - F CRPS 63.0 < C 158.6.

  Production's availability calendar sits between this and the primary oracle filter. Removing it makes F look
  better only because drawing players who did not play cancels part of F's mean deficit.
- **D5, exclusion census.** Excluded and counted, never scored 0:

  | | player-weeks |
  |---|---|
  | appeared | 10,720 |
  | no stat line | 1,566 |
  | stat row but no appearance | 1,068 |
  | unknown position | 0 (after deviation 1) |
  | holdout, no point-in-time rosValue (unpriced) | 55 (week 5: 26, week 6: 29) |
  | scale fit, unpriced | 126 |

- **Realized cross-check.** The exact solve over host-native points reproduces Sleeper's awarded best-ball total on
  23 of 24 team-weeks within 0.01. The 24th is off by 0.0111, which is consistent with the 2-decimal rounding of
  21 starters.

## Deviations from the preregistration (disclosed)

**1. Population vocabulary (fixed before the evidence run).**

- §1(b) listed the positions as "QB, RB, WR, TE, K, DL, LB or DB". The Sleeper directory also says CB, DE, DT, NT
  or FB for about 68 rostered player-weeks a week, and the sim draws those players under that raw key
  (`cv_for("CB")`).
- A low-precision smoke run surfaced it: unknown-position counts of about 68 a week, and a realized cross-check of
  1 of 24.
- The fix decides eligibility on the lineup family (`lineup_position`, then `fantasy_positions`) and keeps CV keys
  raw, so the candidate's `byPosition` uses the keys the sim actually asks for (CB, DE and DT are measured; FB and
  SS fall below the 30-sample floor and keep the fallback CV). After the fix the cross-check is 23 of 24.
- Only census, cross-check, family n and fit-window outputs were read from the smoke run, not any holdout metric.
  Commit `e6d2eb4a4`.

**2. A defect in the preregistered coverage metric (the gate was applied literally).**

- The prediction is censored at 0. When the lower bound of the "central" interval censors, the interval also holds
  the point mass at 0. That happens at CV > 0.51 for the 95% interval and CV > 0.78 for the 80% one.
- The interval's true content is then `P(Y ≤ hi)`: **0.975 for the "95%" interval**, and up to 0.90 for the "80%"
  one. A perfectly calibrated high-CV model would therefore fail SC-G1's 80% band.
- SC-G1 was **applied as written**. Two post-hoc, non-gating diagnostics are added beside it: the model-implied
  content, and coverage of the exact-content PIT intervals.
- **The defect does not change the verdict.** On PIT coverage C still under-covers at 95% in six of seven gated
  families (0.829 to 0.876; RB 0.910). SC-G3, SC-G4 and SC-G5 fail on their own.
- A future preregistration should gate PIT-interval coverage.

**3. D2 "own weeks" is read per player-season**, so a season-to-season mean shift is not counted as weekly
volatility.

**4.** The prereg cited #1931 and #1941 as drafts. Both have since merged. That changes nothing here.

## What remains for an owner decision

Promotion is owner-only, and this study requests none.

1. **No candidate in hand is promotable.** Writing this candidate to `data/league_intel/sim_points_model.json` would
   replace a 109-point under-prediction of team totals with a 116-point over-prediction. It is better on log score
   and PIT, worse on LB CRPS.
2. **The served fallback is itself measured as badly miscalibrated:** team totals about 109 points low, 0 of 24
   team-weeks inside the 80% interval. Whether surfaces fed by it (playoff odds, Game Day, best-ball marginal
   utility, the forecast archive) need a caveat or a priority fix is the owner's call.
3. **A fix is a methodology change to the points-model owner** (`src/league_intel/sim_calibration.py`), not a
   parameter write. The evidence points at three changes, each a new candidate needing its own preregistered
   evaluation:
   - a per-family scale, or a point-projection mean through `draw_from_mean` instead of one cross-position
     `rosValuePerPoint`;
   - a within-player (residual) CV instead of the pooled CV;
   - gating on PIT coverage.

   This lane has no authority to change the owner.
4. **The week-7 confirmation** (preregistration §2) only matters for a promotion request, and there is none. The
   script supports it once DAL at PHI is final:
   `--frozen-candidate …/candidate_sim_points_model.json --expect-sha256 cee877c2… --eval-weeks 7 --out-name evaluation_week7.json`.

## Reproduce

```
python scripts/sim_calibration_study.py --offline
python -m pytest -p no:cacheprovider tests/league_intel/test_sim_calibration_study.py
```

`--offline` needs `data/idp_accuracy/cache/` populated. Without `--offline`, missing bodies are fetched with a
throttled public GET. The candidate file's `generatedAt` comes from `build_calibration`'s clock, so a re-run
produces the same parameters under a new sha256.

## UNRESOLVED

- **Two holdout weeks only.** The team-week evidence is n = 24, with no season-level outcome.
- **Positions and eligibility come from today's Sleeper directory**, not a dated one.
- **Availability in the primary team-week test is an oracle** (players who appeared). Point-in-time injury states are
  not archived.
- **2025 stat lines are rescored under the 2026 card**, and the 2025 roster pool is the 10-team 2025 league.
- **Whether the fallback's level bias moves relative standings or odds** was not measured.
