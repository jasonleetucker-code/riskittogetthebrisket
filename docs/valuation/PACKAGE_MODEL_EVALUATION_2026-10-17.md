# Package-model evaluation — KTC incumbent vs GEOM q=0.78 challenger (2026-10-17)

**Status:** EVIDENCE MEMO — shadow evaluation only. **No model is promoted by this document.**
KTC (`ktc_2026_04`) remains the production package model. Promoting any challenger is a separate
owner authorization on held-out evidence (owner package 2026-10-17, recorded in
`docs/OWNER_REQUESTED_TODO.md`).

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. The question

The owner asked whether the trade calculator's Value Adjustment structurally sides with the star (the
fewer-piece package) or with the bigger package, and whether the proposed challenger (GEOM, q=0.78)
fixes that without creating a different systematic bias.

**Short answer:**

* **KTC sides with the consolidation / star side almost always when raw values are close.** On the
  owner's 100,000-case sample it picks the fewer-piece side in 77.15% of unequal-count trades and the
  side holding the single best asset in 87.82%. In 1-for-4 trades the figure is 99.4%.
* **KTC is also mathematically unsafe.** Adding a positive asset to a side can make that side's
  verdict *worse*: 4,751 / 4,811 times in 60,000 seeded cases (add to A / add to B), plus 1,040 when an
  existing asset is raised. It is also not scale invariant (26,430 / 60,000). Side swap and
  permutation are clean.
* **GEOM_78 removes every mathematical defect we test for** (0 failures on all seven properties,
  through the production dispatch as well as the reference formula) and is much less star-biased on
  ordinary 1–4-piece trades (54.07% fewer-piece wins).
* **GEOM_78 is NOT less star-biased on deep packages.** When one stud is traded for 6–12 lesser pieces
  drawn from the lower half of the board, GEOM_78 sides with the stud 99.77% of the time — as often as
  KTC (98.97%). Its weights sum to at most 1/(1−0.78) ≈ 4.5 of the top asset, so depth saturates.
  Only HYBRID_50 is near-balanced there (50.64%).
* **Real-trade evidence available in this repository is too small to decide.** On our own league's
  completed trades priced point-in-time, the incumbent agrees better with what managers accepted when
  KTC's own prices are used, and GEOM agrees better when IDP Trade Calculator prices are used. Neither
  sample (15 and 21 trades) can carry a promotion.

Recommendation in §8.

## 2. Method and provenance

All synthetic numbers come from `scripts/package_model_benchmark.mjs`, which imports the actual
repository functions: `ktcAdjustPackage` (incumbent), `packageAdjustPair` (the sitewide dispatch, both
models) and `geomPackageUtility`. Nothing is re-ported. The script also asserts that the production
dispatch equals the reference functions on every case: **0 mismatches in 530,000 cases** for both
models.

Evidence files (committed): `docs/valuation/evidence/package_model_2026-10-17/`

* `benchmark.json` — every run, every model, by shape, by raw-gap bin, stress suite, named cases;
* `bias_matrix.csv` — one row per (run, model);
* `trade_residuals.json` — own-league completed-trade residuals (§6).

Sources (sha256 in `benchmark.json`):

| source | rows used |
|---|---|
| `CSVs/site_raw/ktcCrowdSfTep.csv` @ main `0f903d17b` | 490 |
| `CSVs/site_raw/idpTradeCalc.csv` @ main `0f903d17b` | full-roster population (offense + IDP + picks) |

Verdict rule (owner's): even when within 1% of the larger evaluated package. Raw-gap filter: at most
30% of the larger raw package unless the run says otherwise.

**Limits.** Synthetic value arrays are formula stress, not trades. The cases are paired (every model
sees the same arrays), not independent samples. No real-trade outcome target was available here
(§6–§7).

## 3. Reproduction of the owner's audit (seed 20261017, 100,000 cases)

Reproduced to the published decimal:

| model | fewer-piece side wins | more-piece side wins | higher single asset wins | agrees with KTC |
|---|---:|---:|---:|---:|
| KTC incumbent | **77.15%** | 21.29% | **87.82%** | 100% |
| RAW | 33.32% | 63.94% | 57.64% | 68.78% |
| GEOM_75 | 57.54% | 38.87% | 73.86% | 84.71% |
| **GEOM_78** | **54.07%** | **42.19%** | 71.57% | 82.47% |
| GEOM_80 | 51.92% | 44.57% | 70.15% | 81.07% |
| GEOM_85 | 46.74% | 49.94% | 66.70% | 77.67% |
| LP_1.50 | 72.91% | 23.99% | 82.63% | 93.49% |
| HYBRID_50 | 49.24% | 47.42% | 67.85% | 78.86% |

GEOM_78's higher-single-asset figure is 71.57% here against 71.33% in the owner's follow-up run. The
owner's audit itself notes that run counted exact-max ties differently; every other cell matches.

Per shape (fewer-piece side wins):

| shape | KTC | GEOM_78 | HYBRID_50 |
|---|---:|---:|---:|
| 1v2 | 76.88% | 50.67% | 52.90% |
| 1v3 | 93.70% | 55.59% | 53.86% |
| 1v4 | **99.43%** | 62.28% | 51.77% |
| 2v3 | 62.99% | 51.11% | 47.82% |
| 2v4 | 73.14% | 54.24% | 44.08% |
| 3v4 | 56.76% | 50.54% | 45.04% |

## 4. Extension — 430,000 further cases

| run | cases | KTC fewer | GEOM_78 fewer | HYBRID_50 fewer | KTC hi-asset | GEOM_78 hi-asset |
|---|---:|---:|---:|---:|---:|---:|
| new seed 20261018 | 100,000 | 77.03% | 53.78% | 48.84% | 87.64% | 71.35% |
| new seed 20261019 | 100,000 | 77.25% | 53.92% | 49.05% | 87.77% | 71.40% |
| new seed 20261020 | 100,000 | 76.89% | 53.51% | 48.55% | 87.87% | 71.49% |
| full roster (IDPTC values, offense + IDP + picks) | 50,000 | 77.84% | 56.12% | 51.26% | 87.60% | 72.45% |
| deep packages (1v10, 2v10, 3v12, 5v10, 1v6, 2v8; depth from the lower half) | 30,000 | 98.97% | **99.77%** | 50.64% | 98.97% | 99.77% |
| near ties (raw gap ≤ 5%) | 25,000 | 95.41% | 95.14% | 93.69% | 92.83% | 87.35% |
| large gaps (raw gap 30–60%) | 25,000 | 13.63% | 11.69% | 11.69% | 82.13% | 80.97% |

The headline rates are stable across seeds (±0.4 pt) and carry over to a full-roster value population.

**q sensitivity (seed 20261018, standard shapes, fewer-piece wins):** GEOM_70 63.0% · 75 57.2% ·
78 53.8% · 80 51.5% · 85 46.2% · 90 41.5%. The parameter moves the balance smoothly. That is exactly
why "54/42 looks balanced" is not evidence for 0.78 (owner's own caution): any q between about 0.80 and
0.85 crosses 50%.

## 5. Bias matrix — does any model always side with one structure?

| dimension | KTC | GEOM_78 | HYBRID_50 |
|---|---|---|---|
| **A/B position** (swap A and B) | 0 failures in every run | 0 | 0 |
| **fewer vs more pieces, near-balanced 1–4-piece trades** | 77% fewer | 54% fewer | 49% fewer |
| **side with the single best asset** | 88% | 72% | 68% |
| **near raw tie (≤5%)** | 95% fewer | 95% fewer | 94% fewer |
| **deep stud-for-depth** | 99% stud | **99.8% stud** | 51% stud |
| **raw winner overturned** (owner 100k) | 27.8% of cases (1,514 toward the bigger package; 26,328 toward the smaller) | 11.8% (463 / 11,347) | 8.2% (112 / 8,079) |
| raw winner overturned, by raw gap | 0–5%: 31.8% · 5–10%: 37.4% · 10–20%: 29.9% · 20–30%: 20.5% | 27.2% · 24.5% · 11.3% · 0.9% | 22.7% · 19.1% · 5.9% · 0.0% |
| **large raw gaps (30–60%)** | follows raw 98.6% | follows raw 100% | follows raw 100% |

Read plainly:

* **No model has a positional (A/B) bias.**
* **Every concentration-sensitive model, KTC included, favors fewer pieces when raw totals are nearly
  equal.** That is the intended consolidation premium, not by itself a defect.
* **KTC's distinguishing problem is how far the premium reaches.** It overturns a raw lead of 20–30%
  in one case in five. GEOM_78 almost never does at that distance (0.9%), and HYBRID_50 never does.
* **GEOM_78's distinguishing problem is depth.** It discounts the 6th–12th pieces so steeply that a
  deep package almost never beats a stud. HYBRID_50 does not have this problem, but it is
  correspondingly weaker on 1-for-3 / 1-for-4 consolidation.

## 6. Stress suite (seed 98231, 60,000 cases)

Procedure (in `benchmark.json` → `stress.definition`):

* each side has 1–4 values drawn uniformly from 500–9,999;
* an added asset is 1–3,000; a raise to one existing B asset is 1–2,000;
* the scale factor alternates between ×0.5 and ×2;
* integer-rounded outputs get 1 point of slack.

| property | KTC | GEOM_78 (dispatch) | GEOM_78 | HYBRID_50 | LP_1.50 |
|---|---:|---:|---:|---:|---:|
| adding to A must not worsen A | **4,751** | 0 | 0 | 0 | 0 |
| adding to B must not worsen B | **4,811** | 0 | 0 | 0 | 0 |
| raising a B asset must not worsen B | **1,040** | 0 | 0 | 0 | 0 |
| swap negates gap | 0 | 0 | 0 | 0 | 0 |
| permutation invariant | 0 | 0 | 0 | 0 | 0 |
| positive scaling scales gap | **26,430** | 0 | 0 | 0 | 0 |
| 1v1 equals raw | 0 | 0 | 0 | 0 | 0 |

The owner's published counts were 4,758 / 4,726 / 1,008 from an unpublished sampling procedure. These
are the same order and come from the procedure stated above.

Named, exact cases (pinned in `tests/valuation_math/test_package_model.py` as `KNOWN_DEFECT` for the
incumbent):

| A | B | raw gap | KTC adjusted gap | GEOM_78 adjusted gap |
|---|---|---:|---:|---:|
| 7200 | 6000 | +1200 | +1200 | +1200 |
| 7200 | 6000 + 1 | +1199 | **+3908** | +1199 |
| 7200 | 6000 + 500 | +700 | **+3600** | +810 |
| 9000 | 8500 + 1 | +499 | **+2259** | +499 |
| 8200 | 5500 + 4900 | −2200 | **+1436** | −1122 |
| 9000 | 12 × 2000 | −15000 | −594 | +370 |
| 9000 | 12 × 2500 | −21000 | −4500 | −1787 |

## 7. Real completed trades available in this repository

`src/trade/market_trade_eval.py` is the right harness: point-in-time boards, a look-ahead guard and
identity-proven trade groups. It now accepts `model_id` so the shadow challenger can be graded on
identical trades (`residual_report(..., model_id="geom_q078_v1")`; the report stamps `packageModel`).
**Its archive (`data/intel`) is box-local and is not in this container, so that evaluation could not
be run here.** That is a blocker for the owner's promotion evidence, not something this memo
substitutes for.

What could be run: `scripts/package_model_trade_residuals.py` over our own league's completed trades
(`data/sleeper_last_good.json`, a 365-day window, 106 trades). Each trade is priced from the vendor CSV
archived in `exports/archive/` strictly before it, at most 7 days earlier. These are observed vendor
numbers, never re-derived with today's curve, and coverage is all-or-nothing.

| | KTC SF TE++ prices | IDP Trade Calculator prices |
|---|---:|---:|
| trades graded | 15 | 21 |
| excluded: an asset unpriced that day | 22 | 16 |
| predate the archive (2026-07-14) | 66 | 66 |
| not two-team | 3 | 3 |
| mean \|residual\| raw | 0.158 | 0.140 |
| mean \|residual\| KTC | **0.073** | 0.138 |
| mean \|residual\| GEOM_78 | 0.087 | **0.094** |
| GEOM closer to "even" than KTC | 3 of 15 | 12 of 21 |

A residual measures disagreement with a trade both managers accepted. It is not accuracy:

* completed trades are a selected sample (rejected offers are unobserved);
* these are two leagues' managers only;
* KTC's VA was built for KTC's own value scale, so it is expected to fit KTC-priced trades.

The two price sources disagree on which model fits better, on samples far too small to separate them.
**Inconclusive by construction.**

## 8. Recommendation

1. **Keep KTC as the production model** (owner rule). Nothing here authorizes promotion.
2. **The incumbent's nonmonotonicity and scale dependence are real, reproducible defects** — independent
   of any taste about consolidation. Adding a positive asset to your side should never make your side
   look worse. That is a correctness argument for replacing KTC with *some* monotone model. It is not
   an argument for GEOM_78 specifically.
3. **GEOM_78 is not yet the right replacement as specified.** It fixes the math and tempers the star
   preference on ordinary trades. But it reproduces KTC's verdict on deep stud-for-depth packages, the
   exact case the owner asked about ("does it always side with the star?"). Before an owner decision,
   compare on held-out evidence at least GEOM_78, GEOM_80–85 and HYBRID_50. All are monotone and scale
   invariant, and they differ mainly in how depth saturates.
4. **Evidence that would support a promotion decision:**
   * run `market_trade_eval.residual_report` on the box with `model_id` set to each candidate, over
     identity-proven, point-in-time Sharp / KTC trade groups;
   * report residuals per shape (especially 1vN with N ≥ 4), using a preregistered target, with a
     chronological holdout;
   * the precedent is the Hill Autopilot's independent-validation gate (`HILL_AUTOPILOT_V2.md` gate
     7).
   The dispatch already makes the switch a one-line config change in `config/trade/package_model.json`.
   Rollback is the same line.
5. **The ±200 aging band and the 3% fairness band** were calibrated on KTC-adjusted numbers. Either is
   re-checked if the active model changes.

## 9. Reproduce

```bash
node scripts/package_model_benchmark.mjs              # ~30 s; writes benchmark.json + bias_matrix.csv
node scripts/package_model_benchmark.mjs --quick      # smoke run
python scripts/package_model_trade_residuals.py       # own-league completed trades
```
