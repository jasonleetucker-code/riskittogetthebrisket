# Best-ball sim points model, v3 challenger: results and downstream impact

**Status:** `RESEARCH_EVIDENCE_NOT_FOR_PROMOTION`. Nothing is served, every output carries `promotes: false`,
`data/league_intel/` was never written, no owner module was edited, and the production loader refuses every V3 file
(`productionLoaderSource: "fallback-constants"` for all four, recorded in the evidence).

| item | value |
|---|---|
| preregistration | `SIM_CALIBRATION_V3_PREREGISTRATION_2026-10-27.md`, commit `c52ff4d7f` (touches only that file), committed 2026-10-27T09:10:03Z, before the script existed |
| script | `scripts/sim_calibration_v3_study.py`, commit `75c620679`; evidence run on that SHA, clean tree, prereg is an ancestor |
| inputs | v1's 49 cached bodies (sha256-verified against v2's receipts, 49/49) plus 3 network calls: Sleeper 2026 week-7 stats and matchups, a fresh nflverse schedule (week 7 14/14 final). As-of snapshots per week are listed in `evaluation_v3.json` |
| card | `sf1:9e51824690d091f9` |
| evidence | `evidence/sim_calibration_v3/evaluation_v3.json`, `downstream_c2.json`, `challenger_v3_week{5,6,7,8}.json` |

## Verdict on the primary holdout (2026 week 7): `V3_DOES_NOT_BEAT_FALLBACK`

V3 fails SC-G1, SC-G4, V3-G6 and V3-G9. Under preregistration §7 there is **no owner request**.

| gate | week 7 | key numbers (V3 vs F; 477 player-weeks, 12 team-weeks) |
|---|---|---|
| SC-G1 PIT coverage | **FAIL** | WR, DL, DB above the 80% band (0.88, 0.91, 0.87); RB 0.80, LB 0.82 inside. Pooled 0.860 / 0.966 (F 0.444 / 0.618) |
| SC-G2 log score | **PASS** | ΔLS (V3 − F) +15.85 [+7.73, +27.68]; no family significantly worse |
| SC-G3 CRPS | **PASS** | ΔCRPS (F − V3) +0.98 [+0.67, +1.28]; no family significantly worse |
| SC-G4 KS | **FAIL** | D 0.18–0.26 in RB, WR, DL (LB 0.12, DB 0.13); pooled D 0.078 vs F 0.324 |
| SC-G5 team-week | **PASS** | coverage 0.75 / 0.917, CRPS 25.0 vs F 81.3 |
| V3-G6 bias | **FAIL (underpowered)** | bias +9.6 points, CI [−14.7, +30.7]: point estimate inside ±30, upper bound 0.7 over |
| V3-G7 team-week PIT | **PASS** | KS D 0.195 vs critical 0.376 |
| V3-G8 win probability | **PASS** | all-play Brier 0.125 vs F 0.138 (< 0.25) |
| V3-G9 family means | **FAIL** | RB 1.33 [1.13, 1.55] (V3 under-predicts), DL 0.77 [0.59, 0.95] (over-predicts), WR 0.91 [0.77, 1.05] (underpowered) |

**Sample size, disclosed in advance and computed now.** At week 7's gated family sizes (RB 56, WR 95, DL 69, LB 74,
DB 91), a perfectly calibrated model passes SC-G4 **0.2%** of the time and SC-G1 16% (committed OC script, 20,000
reps). SC-G4 failing is not informative on its own. v2's size-aware reading still finds real misfit: KS D exceeds its
95% critical value in RB, WR and DL; PIT coverage 80 is outside the binomial range in WR and DL (over-covered: σ too
wide there). V3-G9's RB and DL failures are real level errors, not width.

**Development weeks 5–6 (disclosed contamination, never gated):** the same table passes SC-G2, SC-G3, SC-G5, V3-G6
(bias +3.1 [−12.9, +18.3]), V3-G7 and V3-G8, and fails SC-G1, SC-G4 and V3-G9 (all four V3-G9 families
underpowered).

## What V3 fixed, against F and V2

| | F (served) | V2 | **V3** |
|---|---|---|---|
| team-week bias, week 7 | −94.0 | +130.6 | **+9.6** |
| team-week bias, weeks 5–6 | −108.9 | +112.6 | **+3.1** |
| team-week 80% / 95% coverage, week 7 | 0.08 / 0.17 | 0.17 / 0.33 | **0.75 / 0.92** |
| team-week CRPS, week 7 | 81.3 | 105.1 | **25.0** |
| pooled realized / predicted mean, week 7 | 1.44 | 0.75 | **0.99** |
| pooled PIT coverage 80 / 95, week 7 | 0.44 / 0.62 | 0.69 / 0.86 | **0.86 / 0.97** |
| LB realized / predicted, week 7 | 1.16 | 0.56 | **1.00** |

V3 also beats V2 at player level: ΔLS +5.5 [+2.0, +10.2], ΔCRPS +1.49 [+1.08, +1.93] (week 7).

**Which component did the work (ablations, reported only):**

- **Forward mean fit (the inversion fix) did most of it.** V3-noAnchor (forward fit on raw as-of rosValue, no
  re-anchoring) is nearly as good: week-7 bias +18.1, pooled ratio 0.97. The as-of pairing alone absorbs most of the
  IDP step because weeks 2–6 already use post-step snapshots.
- **Re-anchoring** halved week-7 team bias (+18.1 → +9.6) but **hurt RB** (1.22 → 1.33) and TE (0.98 → 1.09). The week-7 RB
  pool anchor jumped 19.8 → 23.4 while points did not: the anchor is sensitive to who is in the pool (bye weeks change
  pool composition), not only to snapshot scale. V3-asofAnchor (anchor over every priced rostered player, not only
  those who appeared — a post-hoc sensitivity, see deviations) is the same within noise (bias +10.0, RB 1.30).
- **Shocks** are small: τ_R ≈ 0.09, τ_L ≈ 0.02 (week-7 fit). V3-noShock has the same coverage and CRPS within 0.05.
  Same-roster pairs on the same NFL team carry τ² ≈ 0.017, about twice the roster-wide 0.008 (V3-D4): stacking is the
  correlation that exists, and V3 does not model it.
- **Prediction-error spread** is wide: fitted total CV 0.74 (LB) to the 1.20 clamp (TE, K), against within-player
  CV 0.45–0.77. At week 7 it is now too wide in WR and DL (over-coverage) while LB and DB are close.

## IDP snapshot drift: cause found (inputs only)

The v2 drift is a **step**, not a trend: between snapshots `2026-09-16T18-32-01` and `2026-09-16T21-49-09` the
`draftSharksRosSf` contributor's IDP ranks switched from an overall-list basis (best LB rank 47) to a within-position
basis (best LB rank 1, score 100), lifting the LB family by about 1.45x, DL 1.29x and DB 1.29x. A smaller offensive
step lands in the week-7 snapshot as `fantasyProsRosSf` coverage rises from 374 to 536 players. This is an aggregate
input issue, outside this lane (`src/ros/` aggregation owner); V3 tolerates it by fitting each week against its own
snapshot.

## C2 — does the fallback's absolute bias change relative answers? Measured.

**1. Within-week win probabilities: absolute level alone changes nothing; the variance does.** F\* (F with every mean
scaled by the oracle constant B = 1.453 that removes its level bias) gives all-play win probabilities identical to F's
(max |ΔP| 0.001 over 66 week-7 pairs, Brier 0.13811 vs 0.13812). F's team-week coverage stays poor after the rescale
(0.58 / 0.75), because its spread is too narrow. V3 moves win probabilities materially (mean |ΔP| 0.10, max 0.31)
and is better calibrated: in F's top reliability bin, predicted 0.97 against 0.87 realized; V3's is 0.93 against
0.93. V3 also reorders team strength slightly (Kendall τ of team means vs F: 0.91 in week 7).

**2. Playoff qualification and championship (today's state, production `simulate_playoff_odds` through the D11
harness, 20,000 sims, incumbent arm as served).**

| model | max \|Δ playoff odds\| vs F | max \|Δ title odds\| vs F |
|---|---|---|
| F\* (absolute level fixed) | 0.0000 | 0.0001 |
| V2 | 0.0011 | 0.022 |
| V3-marginal (weeks 1–7 fit, no shocks) | 0.0001 | **0.101** |

The level bias does not move playoff or title odds at all. Playoff odds barely move under any model because after
week 7 they are already at 0 or 1 for every team in this harness. Title odds do move under V3, by up to 10 points
(14 points in the corrected arm), concentrated in the two leading teams (F 0.44 / 0.56, V3 0.53 / 0.46). Kendall τ
values in the evidence are tau-a and are depressed by ties at 0 and 1.

**3. Trade marginal-utility ordering (production `best_ball_utility.evaluate_trade_utility`, drop-one BBLI for the
top 12 players on each of 12 week-7 rosters, 400 draws).** In production, BBLI means come from the ROS ensemble; only
the points model's **variance** enters, so the fallback's 2.7 scale never reaches BBLI.

- Variance only (same means, F's CVs vs V3's spread): Kendall τ 0.89 on average (min 0.79), top-3 overlap 2.9 of 3.
  The fallback's narrow CVs change BBLI ordering a little, not a lot.
- Full model (rosValue / 2.7 with F's CVs vs V3's means and spread): τ 0.57 (min 0.24), top-3 overlap 1.7. This is the
  relevant contrast for surfaces that draw from rosValue means: the playoff presim and `simulate_trade_impact`.

**Reading.** An absolute bias does not imply a probability bias, and here it does not cause one: a uniform level error
cancels in every relative answer. What does change relative answers is the **per-family relative error** (F
over-scales QB by 1.97x and LB by only 1.16x) and the **spread**. Those are the parts V3 changes.

## C3 — how failed or unverified calibration should be shown to users (design only, nothing activated)

1. **One owner of the calibration state:** a read-only descriptor beside the points model
   (`src/league_intel/sim_calibration.py`), for example `calibrationState: unverified | failed | verified` with a
   pointer to the preregistration and results. `fallback-constants` maps to `failed` (v1 measured it). Surfaces read
   the descriptor and never infer it.
2. **Label by what the error affects, from C2's measurements, not one blanket warning.**
   - Absolute numbers (projected weekly points, team totals): "uncalibrated estimate", with no interval language
     while the state is not `verified` (F's 80% intervals covered 1 of 12 week-7 team-weeks).
   - Win, playoff and title probabilities: published, with a short provisional label. C2 shows they are insensitive
     to the level bias and sensitive to spread and relative family scales by up to 10 title points.
   - Trade BBLI: no extra caveat; its means do not come from this model, and its ordering is fairly stable to the
     variance change (τ ≈ 0.89).
3. **A failed calibration is never shown as missing or zero.** Odds stay published; the label carries the state.
4. **Public `/league`:** a factual caveat only ("the weekly score model is not yet validated against this league's
   results"). Gate tables and challenger numbers stay in private evidence.
5. **Activation** would need a default-OFF flag added by the coordinator (this lane adds none) and an owner decision
   on wording.

## Deviations and disclosures

1. **Smoke run before the primary run.** `--dev-only` evaluated weeks 5–6 at 100 draws before the evidence run, to
   catch bugs. Weeks 5–6 were already disclosed as contaminated. The script was committed unchanged after the smoke
   (`75c620679`); week 7 was first read by the evidence run.
2. **V3-asofAnchor is post-hoc.** The preregistered anchor averages over players who appeared, which conditions on
   availability in the evaluated week. The as-of-clean anchor (every priced rostered player) was added as a
   sensitivity, never gated. It agrees with V3 within noise.
3. **C2-b V3-marginal uses the as-of-clean anchor**, because no appeared pool exists for future weeks.
4. **C2-b Kendall τ is tau-a**, depressed by tied 0/1 odds. The |Δ| columns carry the finding.
5. **SC-G5 is computed by v2's function**, verbatim. V3-G6 to G9 are additional, as preregistered.

## What remains for an owner decision

1. **Nothing is promotable.** The served fallback remains measured as miscalibrated: −94 to −109 team points, and
   0–1 of 12–24 team-weeks inside its 80% interval.
2. **V3 is the first candidate whose team-week level, coverage and win probabilities are close to calibrated.** Its
   failures are RB and DL family levels plus over-wide WR and DL spread. A v4 would need its own preregistration, for
   example: a pool anchor robust to bye-week composition, a per-family spread with a mean-dependent shape, and NFL-team
   stacking.
3. **Week 8 confirmation:** frozen `challenger_v3_week8.json` (sha256
   `8a5fd16a15240bcbd15dff70eeeac24b5aebaa30e8c1b0130d87997ad698facb`) once week 8 is final. It matters only if a
   request is ever made.
4. **Gate sizing.** SC-G4 is passed by a perfect model 0.2% of the time at week-7 sizes. Size-controlled gates remain
   the owner methodology decision v2 already raised.
5. **The IDP rank-basis change in `draftSharksRosSf`** belongs to the ROS aggregation owner.
6. **The C2 surface caveats** (C3) are an owner product decision.

## Reproduce

```
python scripts/sim_calibration_v3_study.py evaluate --offline     # ~25 min; needs the cached bodies
python scripts/sim_calibration_v3_study.py downstream             # C2-b needs the public Sleeper API
python -m pytest -p no:cacheprovider tests/league_intel/test_sim_calibration_v3_study.py
```

## UNRESOLVED

- **One clean holdout week**: 12 team-weeks and 477 player-weeks. Week 8 is not final.
- **Inherited caveats**: oracle availability for team-week pools; positions from today's Sleeper directory; NFL team
  from today's directory for V3-D4.
- **C2-b harness weekly means look over-dispersed**: per-team presim means range 117 to 507 under F, against realized
  team-weeks of roughly 200 to 460. This is the production harness on `latest.json`, recorded as-is and not
  investigated here. Playoff odds being 0/1 after week 7 may follow from it.
- **The anchor's sensitivity to pool composition** (RB, week 7) is measured but not resolved.
