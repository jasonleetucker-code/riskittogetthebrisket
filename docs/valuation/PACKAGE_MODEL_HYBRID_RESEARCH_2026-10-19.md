# Hybrid Value Adjustment research — averaging ours with KTC's, and the alternatives (2026-10-19)

**Status:** RESEARCH MEMO. **Nothing is promoted or changed in production.** `geom_q078_v1` (q = 0.78)
stays the authoritative package Value Adjustment, and `ktc_2026_04` stays the read-only comparator and
rollback. This is also owner decision D8 of 2026-10-18 (`docs/owner/OWNER_DECISION_CLOSEOUT_2026-10-18.md`).

Directive: `docs/owner/HYBRID_VALUE_ADJUSTMENT_RESEARCH_2026-10-19.md` (verbatim). Builds on
`PACKAGE_MODEL_EVALUATION_2026-10-17.md` and `PACKAGE_MODEL_OWNER_ACTIVATION_2026-10-17.md`; it does not
repeat them.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

**Phase 2 follows:** `PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md` (market evidence, large packages, Trade Finder replay). This Phase 1 memo is preserved unchanged below.

## Owner summary

| Question | Answer |
|---|---|
| **A. Average ours with KTC's (50/50)?** | **No.** It brings back KTC's defects: adding a player can hurt the side that receives him, and adding a 1-point asset can swing the result by 1,874 points. On our own league's completed trades it also fits worse than our model alone. |
| **B. A weighted average?** | **No.** Every weight from 75/25 to 25/75 fails the same mandatory test. More KTC means more failures and a worse fit on real trades. 75/25 is the least bad, and it is still worse than 100% geometric. |
| **C. Another hybrid that is better?** | **None is demonstrably better.** Several hybrids are mathematically sound. The "depth floor" version (`FGEOM_70_20`) is almost identical to ours in practice: it changed 1 of 38 Trade History grades and none of the deep-trade winners. HYBRID_50 gives depth real weight, but it fits real trades worse and lets a pile of bench players beat a star. |
| **D. Ordinary 1-for-3 and 2-for-3** | **Ours (q = 0.78)** is the most defensible. KTC and the blends call 1-for-3 trades "lopsided" when raw value is within 8%. Weaker models (q = 0.85, HYBRID_50) give almost no consolidation premium. |
| **E. Very large packages** | **No model is right by evidence.** We have three real deep trades. Our model, KTC and every blend side with the stud in essentially every near-balanced 1-for-6 / 1-for-10 here. HYBRID_50 is the only one near 50/50, and it gets there by treating ten bench players as worth a star. |
| **F. Supported by real trades?** | **Only weakly, and not toward a hybrid.** On 38 completed own-league trades priced on Chase Upside values, every KTC blend fit worse than ours. The fit kept improving as q fell all the way to 0.2, where only each side's best player counts. A target with no sensible best value cannot choose q (§6). |
| **H. Recommendation** | **Keep `geom_q078_v1` unchanged.** Do not average with KTC. Do not register a new challenger now. The next real evidence is the production-box trade archive; this PR adds a mode that grades every candidate on it (§8). |
| **I. Retain q = 0.78?** | **Yes**, unchanged. |
| **J. What changes in production** | **Nothing.** §9 lists exactly what *would* change if you later approve a different model. |

## 1. What was tested, on what values

**Values.** Every model runs on the same **canonical Chase Upside board** (`rankDerivedValue`), built by
the live pipeline (`build_api_data_contract`) from the committed raw payload
`exports/latest/dynasty_data_2026-10-19.json`. That gives 1,029 priced assets: 488 offense, 397 IDP and
144 picks. Code SHA and payload hash are in `research.json → board`. **KTC's formula is applied to our
values; KeepTradeCut's own player values are never used.**

**Candidates** (`scripts/package_model_hybrid_research.py`; all in research code, none in the production
dispatch):

| name | what it is |
|---|---|
| `GEOM_78` | the incumbent, through the production dispatch |
| `KTC` | `ktc_2026_04` through the production dispatch, on our values |
| `BLEND_Gxx_Kyy` | **your idea**: `blendedGap = w·geometricGap + (1−w)·ktcGap`, w = 75 / 60 / 50 / 40 / 25%. It is ONE signed gap over identical raw values, shown as ONE positive-only adjustment to the side that gains, `|blendedGap − rawGap|`. It never stacks two bonuses (pinned by test). |
| `GEOM_60 … GEOM_90` | geometric alternatives (q = 0.60–0.90) |
| `HYBRID_50` | the earlier challenger: 0.5 × raw + 0.5 × L1.5 norm. **Not** a KTC/geometric average. |
| `LP_150` | L1.5 norm |
| `FGEOM_q_f` | **new — geometric with a depth floor**: piece *i* is weighted `f + (1−f)·q^(i−1)`, so every extra piece keeps at least *f* of its value. It is the same as mixing raw and geometric utilities, which is the mathematically valid way to "average" two monotone models. Grid q ∈ {0.60…0.78}, f ∈ {0.10…0.30}. |
| `ZIPF_a` | **new — power weights** `i^−a` (a = 0.5 / 0.75 / 1.0). Depth never saturates. |

Roster fit, lineup value, forced drops and positional scarcity are **not** in any of these. They already
have owners (`roster_capacity`, the lineup solver, the canonical value), and folding them in here would
count them twice.

## 2. Mathematical properties (owner §4), 20,000 seeded cases

Values come from the canonical board plus the uniform 500–9,999 range the 2026-10-17 memo used. Sides have
1–6 pieces. Rounded production outputs get 1 point of slack.

| model | adding an asset hurts the adder (A / B) | raising an asset hurts its side (A / B) | not scale-consistent | largest swing from adding a **1-point** asset |
|---|---:|---:|---:|---:|
| GEOM_78 (ours) | 0 / 0 | 0 / 0 | 0 | 1 |
| KTC | **945 / 865** | **382 / 356** | **8,229** | **3,746** |
| BLEND 75/25 | **207 / 174** | **52 / 58** | **7,581** | **937** |
| BLEND 60/40 | **353 / 314** | **94 / 105** | **7,879** | **1,499** |
| BLEND 50/50 | **459 / 385** | **134 / 149** | **7,996** | **1,874** |
| BLEND 40/60 | **569 / 494** | **176 / 186** | **8,068** | **2,248** |
| BLEND 25/75 | **722 / 612** | **242 / 251** | **8,149** | **2,810** |
| GEOM_70, GEOM_85, HYBRID_50, LP_150, FGEOM_*, ZIPF_* | 0 / 0 | 0 / 0 | 0 | ≤ 1 |

Side swap, reordering and 1-for-1 = raw pass for every model. Missing / unpriced assets are excluded and
counted, never priced at zero, in every path. Offense, IDP and picks use one formula.

**Your mandatory case**, `A = [7200]` vs `B = [6000]`, then B adds a 1-point asset:

| | B = [6000] | B = [6000, 1] | what happened to B |
|---|---:|---:|---|
| GEOM_78 | A by 1,200 | A by 1,199 | B improved by 1 ✔ |
| KTC | A by 1,200 | A by **3,908** | B got **2,708 worse** ✘ |
| BLEND 75/25 | A by 1,200 | A by **1,876** | **676 worse** ✘ |
| BLEND 50/50 | A by 1,200 | A by **2,554** | **1,354 worse** ✘ |
| BLEND 25/75 | A by 1,200 | A by **3,231** | **2,031 worse** ✘ |

This is structural, not a sampling accident. A blend inherits *w_KTC* × every KTC jump. So any non-zero
KTC weight fails the mandatory property, and no weight fixes it. Pinned in
`tests/scripts/test_package_model_hybrid_research.py`.

Other named cases (adjusted gap, + = A ahead):

| A | B | raw | GEOM_78 | KTC | BLEND 50/50 | HYBRID_50 | FGEOM_70_20 |
|---|---|---:|---:|---:|---:|---:|---:|
| 8200 | 5500 + 4900 | −2,200 | −1,122 | **+1,436** | +157 | −1,131 | −1,024 |
| 9000 | 12 × 2000 | −15,000 | +370 | −594 | −112 | −8,242 | −1,060 |
| 9000 | 12 × 2500 | −21,000 | −1,787 | −4,500 | −3,144 | −12,552 | −3,574 |

## 3. Real players (canonical values, 2026-10-19)

"Gap" is the adjusted lead of the star side. Levels come from the one fairness-band owner
(`fairness_bands_v1`: fair < 3.5%, slight < 9%, unfair < 18%, lopsided above).

| trade | raw | GEOM_78 (ours) | KTC | BLEND 50/50 | BLEND 75/25 | HYBRID_50 | FGEOM_70_20 |
|---|---:|---|---|---|---|---|---|
| **1-for-2:** Jahmyr Gibbs (9,869) for Bo Nix (5,412) + DeVonta Smith (4,922) | −465 | +618 slight | +4,824 **lopsided** | +2,721 lopsided | +1,670 unfair | +599 slight | +716 slight |
| **1-for-3:** Gibbs for Jadarian Price (4,137) + Jake Ferguson (3,552) + Pat Freiermuth (2,957) | −777 | +1,162 unfair | +6,120 **lopsided** | +3,641 lopsided | +2,402 lopsided | +838 slight | +1,282 unfair |
| **2-for-3:** Gibbs + Nico Collins (6,459) for De'Von Achane (5,918) + Tucker Kraft (5,399) + Tee Higgins (4,903) | +108 | +1,795 unfair | +5,391 **lopsided** | +3,593 lopsided | +2,694 unfair | +973 slight | +1,854 unfair |
| **IDP 1-for-3:** Carson Schwesinger (6,246) for Nate Landman (2,244) + Donovan Ezeiruaku (2,059) + Malaki Starks (1,941) | +2 | +1,215 unfair | +3,869 **lopsided** | +2,542 lopsided | +1,878 lopsided | +957 unfair | +1,288 unfair |
| **1-for-6:** Gibbs for six ~1,775 players (Tremble, Sarratt, K. Allen, N. Gray, Tracy, Claiborne) | −781 | +3,615 lopsided | +7,304 lopsided | +5,460 lopsided | +4,537 lopsided | +1,614 unfair | +3,560 lopsided |
| **1-for-10:** Gibbs for ten ~1,100 players (Slayton, Goodson, Lance, Pickett, …) | −1,052 | +5,279 lopsided | +7,539 lopsided | +6,409 lopsided | +5,844 lopsided | +1,874 unfair | +4,823 lopsided |

How to read this:

* **KTC's formula is extreme on our values.** It was built around KTC's own value scale. On ours it moves the median ordinary trade by **34.8% of the larger side**; ours moves it
  by 12.2% (§4). So a 50/50 blend is not "halfway to something familiar". It moves every star trade to
  "lopsided".
* Ours gives Gibbs a real but moderate premium over three solid starters. On the 1-for-2 it calls the trade
  slightly favouring Gibbs even though the two starters total 465 more.
* On 1-for-6 and 1-for-10 every model except HYBRID_50 says the star wins by a lot. HYBRID_50 still sides
  with Gibbs, but it rates ten players at ~1,100 each (players nobody would start) as worth about 81% of
  him. In the 9000-vs-12 × 2000 case it says the pile wins by 8,242.

## 4. Bias by trade structure (owner §5–§6)

The full grid: 17 shapes (1v1 … 5v10) × 9 populations (random offense, superstar, mid-tier, bench depth,
IDP-only, full-roster mixed, picks, low-value padding, similar values) × 3 raw-gap windows, 400 cases per
cell where attainable. That is 163,912 trades per model across 412 cells. Which side is "A" is randomised. **These are synthetic
stress tests, not accuracy.** A balanced win percentage is not evidence of being right.

Near-balanced trades (raw gap ≤ 30%). "Ordinary" = 1v2, 1v3, 1v4, 2v3, 2v4, 3v4. "Deep" = 1v6, 1v10, 2v6,
2v10, 3v6, 4v6, 5v10.

| model | ordinary: fewer pieces wins | ordinary: raw leader reversed | ordinary: median move (% of larger side) | deep: fewer pieces wins | same fairness level as ours (ordinary / deep) |
|---|---:|---:|---:|---:|---:|
| RAW | 40.3% | 0% | 0% | 26.6% | 33.5% / 28.7% |
| **GEOM_78 (ours)** | **64.6%** | **21.7%** | **12.2%** | **91.0%** | 100% / 100% |
| KTC | 84.0% | 41.6% | 34.8% | 90.7% | 38.7% / 53.4% |
| BLEND 75/25 | 74.4% | 31.9% | 17.4% | 91.1% | 65.0% / 75.9% |
| BLEND 50/50 | 78.5% | 36.1% | 23.0% | 90.8% | 48.7% / 62.5% |
| BLEND 25/75 | 81.8% | 39.4% | 28.9% | 90.7% | 41.7% / 56.4% |
| GEOM_85 | 57.0% | 13.9% | 8.6% | 79.2% | 70.8% / 50.5% |
| HYBRID_50 | 58.2% | 15.1% | 9.4% | 53.2% | 71.4% / 27.4% |
| FGEOM_70_20 | 65.8% | 23.0% | 12.7% | 88.9% | 95.4% / 87.1% |

By shape (fewer-piece side wins, near-balanced):

| shape | GEOM_78 | KTC | BLEND 50/50 | BLEND 75/25 | GEOM_85 | HYBRID_50 | FGEOM_70_20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1v2 | 53.5 | 79.1 | 68.7 | 61.9 | 48.4 | 55.4 | 54.4 |
| 1v3 | 60.1 | 94.5 | 81.7 | 72.5 | 52.4 | 58.1 | 62.4 |
| 1v4 | 72.9 | 100 | 99.6 | 98.8 | 55.7 | 58.6 | 75.7 |
| 2v3 | 65.6 | 76.0 | 72.6 | 69.6 | 61.2 | 60.4 | 66.2 |
| 2v4 | 64.2 | 76.5 | 72.8 | 69.9 | 57.4 | 54.6 | 64.8 |
| 1v6 | 100 | 100 | 100 | 100 | 73.4 | 55.3 | 100 |
| 1v10 | 100 | 100 | 100 | 100 | 100 | 54.4 | 100 |
| 5v10 | 97.1 | 84.3 | 87.1 | 90.4 | 80.4 | 50.9 | 87.4 |

Findings:

* **Blending pushes ordinary trades toward the star; it does nothing for deep ones.** In the deep shapes
  every KTC blend is ~91% stud, the same as ours. So averaging buys none of the depth balance you were
  looking for. It only adds star bias where we were already moderate (1-for-4: 73% → 99.6%).
* **Ours is the middle of the sound models on ordinary trades**, with a clear but limited consolidation
  premium. It reverses a near-balanced raw leader about one time in five; KTC does it about two in five.
* **No sound model separates "deep" from "ordinary" for free.** In a sorted-weight model the same weight
  sequence sets both: weights 2–4 govern 1-for-2…1-for-4 and weights 6–10 govern deep packages. Giving the
  10th piece meaningful weight (HYBRID_50) also flattens 1-for-3 / 1-for-4. Keeping the 1-for-3 premium
  (GEOM_78, FGEOM) keeps deep trades stud-favoured. The depth floor in FGEOM is too small to change any
  near-balanced deep winner. A floor large enough to change them behaves like HYBRID_50.
* **Similar-value and superstar populations** are ~95–100% fewer-pieces for every concentration model,
  KTC included. When two players of value *v* go for one of 2*v*, consolidating is the intended premium.
* **Positional and population behaviour is consistent**: IDP-only, picks and full-roster mixed follow the
  same ordering as offense (by-scenario table in `research.json`).

## 5. Impact on the canonical consumers

All consumers read the one dispatch (`package_model.py` / `trade-logic.js::packageAdjustPair`), so a
model's effect on them is its change in fairness classification and leader:

| | BLEND 50/50 | BLEND 75/25 | HYBRID_50 | FGEOM_70_20 |
|---|---:|---:|---:|---:|
| Trade History (38 real own-league trades): grade changes vs ours | **13** | 7 | 8 | 1 |
| Calculator / Second Opinions / Finder fairness band, ordinary shapes: same level as ours | 48.7% | 65.0% | 71.4% | 95.4% |
| same, deep shapes | 62.5% | 75.9% | 27.4% | 87.1% |

A 50/50 blend would regrade about **half** of all ordinary package trades across the calculator, Second
Opinions, Finder scoring and Trade History. It would also need the provisional 3.5 / 9 / 18% fairness bands re-validated, because they were
re-derived for the geometric model (owner decision 3, 2026-10-18). The Finder itself was not re-run per model
(UNRESOLVED below); its scoring uses the same dispatch, so the band-change rates above are the expected
size of the effect.

## 6. Real completed trades (owner §6)

**Sample.** Own-league completed trades in `data/sleeper_last_good.json`: 107 trades. Each one is priced on
the canonical board **reconstructed** from the raw payload archived *strictly before* the trade (at most 7
days earlier). The inputs are point-in-time; the pipeline is today's code, so values are labelled
`reconstructed`, never "observed". Graded: **38**. Excluded and counted: 65 before the archive starts
(2026-07-14), 3 multi-team, 1 with an asset the board did not price (never priced as 0). Of the 38, 29 have
more than one piece on a side. Every graded trade is listed in `research.json → trades.multiPieceTrades`.

**Residual** = adjusted gap ÷ mean adjusted side. Both managers accepted, so the trade cleared at "even"
for them. Smaller residual = closer agreement.

| model | mean \|residual\|, 29 multi-piece trades | vs ours, paired bootstrap 95% CI | better / worse than ours, per trade |
|---|---:|---|---:|
| RAW | 0.303 | +0.126 [+0.092, +0.163] | 3 / 26 |
| **GEOM_78 (ours)** | **0.177** | — | — |
| KTC | 0.258 | +0.081 [+0.039, +0.119] | 7 / 22 |
| BLEND 75/25 | 0.192 | +0.015 [+0.001, +0.028] | 10 / 19 |
| BLEND 60/40 | 0.204 | +0.027 [+0.008, +0.046] | 10 / 19 |
| BLEND 50/50 | 0.213 | +0.036 [+0.013, +0.058] | 10 / 19 |
| BLEND 40/60 | 0.221 | +0.044 [+0.016, +0.070] | 8 / 21 |
| BLEND 25/75 | 0.234 | +0.057 [+0.024, +0.089] | 7 / 22 |
| HYBRID_50 | 0.204 | +0.027 [+0.010, +0.049] | 9 / 20 |
| GEOM_85 | 0.209 | +0.032 [+0.024, +0.041] | 3 / 26 |
| FGEOM_70_20 | 0.174 | −0.004 [−0.006, −0.000] | 23 / 6 |
| GEOM_70 | 0.150 | −0.027 [−0.037, −0.018] | 23 / 6 |
| LP_150 | 0.122 | −0.055 [−0.080, −0.030] | 23 / 6 |
| ZIPF_100 | 0.116 | −0.061 [−0.091, −0.034] | 22 / 7 |

Chronological holdout: each family picks its best member on the earlier 17 multi-piece trades and is
scored on the later 12. Incumbent 0.186. Geometric family picks q = 0.60 → 0.131. Blends pick 75/25 →
0.190. HYBRID/L-norm → 0.114. Floored → `FGEOM_60_10` 0.140. Power → `ZIPF_100` 0.112.

**What this does and does not show.**

1. **It is consistent evidence against averaging with KTC.** Every blend fits accepted trades worse than
   ours, and monotonically worse as the KTC share rises. KTC does not just add a premium; on our values it
   overshoots, pushing trades past even (e.g. Bucky Irving + George Pickens for Chris Olave + Garrett
   Wilson: raw −0.147, KTC −0.323).
2. **It cannot choose q, so it cannot justify any other candidate.** The fit keeps improving as the
   discount gets steeper, with **no turning point**: q = 0.9 → 0.237, 0.8 → 0.185, 0.7 → 0.150,
   0.6 → 0.131, 0.5 → 0.117, 0.4 → 0.109, 0.3 → 0.104, **0.2 → 0.098**
   (`trades.residualByQExtended`). At q = 0.2 the second-best piece is worth 20% and the third 4%: a model
   in which only each side's headliner matters. That says managers in this league trade headliner for
   headliner, which any steep-enough model rewards. It is not a calibration of q. The holdout "winners"
   above are the steepest members of each family for the same reason.
3. **The noise floor is high.** 1-for-1 trades, which no package model touches, average **0.206** off even
   (`trades.oneForOneNoiseFloor`). Our board disagrees with what these managers accepted by about 20% per
   trade regardless of package math. Part of any "steeper fits better" signal may come from our value curve
   being flatter than how these managers value stars. If so, the fix belongs in the canonical value, not
   the package model, and putting it here would double-count it.
4. One league, ~12 managers, 29 multi-piece trades, three deep (2v5, 3v6, 5v9). An accepted trade is not
   proof the adjustment was right; rejected offers are never seen.

This agrees with D8 (2026-10-18): no recalibration from a few accepted trades.

## 7. Recommendation

1. **Keep `geom_q078_v1` with q = 0.78 unchanged.** It passes every property and sits in the middle of the
   sound models on ordinary trades. On the only real-trade evidence available it is not beaten by any
   candidate that keeps a reasonable shape.
2. **Do not average with KTC, at any weight.** Every weight brings back the add-an-asset defect and
   discontinuities of up to 937–2,810 points from a 1-point asset. It adds star bias on ordinary trades,
   adds no depth balance on deep trades, and fits completed trades worse.
3. **Do not activate HYBRID_50.** Its depth balance comes from treating bench piles as near-equal to stars,
   and it fits completed trades worse.
4. **Do not register a new production challenger now.** `FGEOM_70_20` is the only sound hybrid that is
   never worse, and in practice it is indistinguishable from ours (1 of 38 grades, 95% identical fairness
   bands, no deep winner changed). Registering it would add a code path without a decision it could change.
   Every candidate stays runnable in the research harness.
5. **Next evidence, if you want to revisit depth:** run
   `python scripts/package_model_hybrid_research.py --market-ledger` **on the production box**. It grades
   every candidate on the Sharp / KTC market-trade ledger with the existing eligibility owner
   (proven-unique, dynasty, superflex, no look-ahead). Each trade is priced on the archived board dated
   strictly before it, and only aggregates are published. Read it with §6's caveat: residual-to-even has no
   interior optimum in q. A decision needs a preregistered target that does not reward collapsing to "best
   player only", for example matched packages of the same assets traded in different shapes.

## 8. Reproduce

```bash
python scripts/package_model_hybrid_research.py            # ~5 min; writes research.json + matrix_cells.csv
python scripts/package_model_hybrid_research.py --quick    # ~1 min smoke run
python scripts/package_model_hybrid_research.py --market-ledger   # box only: adds the market-trade ledger
python -m pytest tests/scripts/test_package_model_hybrid_research.py
```

Evidence: `docs/valuation/evidence/package_model_hybrid_2026-10-19/`
* `research.json` — board provenance, model registry, property failures (with KTC examples), named cases,
  worked player examples, matrix aggregates by window / shape group / shape / population, completed-trade
  residuals, holdout, bootstrap and Trade History grade changes;
* `matrix_cells.csv` — every attainable cell × 19 report models × 8 metrics. Some cells cannot be sampled
  (e.g. a similar-values trade with a 30–60% raw gap, or a 1-for-10 near-tie of bench pieces); they are
  listed in `research.json → matrix.aggregates.unattainableCells`.

## 9. If you later approve a different model — exactly what changes

Nothing here is authorized. For any replacement:

* `config/trade/package_model.json` `"active"` and `frontend/lib/trade-logic.js::ACTIVE_PACKAGE_MODEL_ID`
  change together (one PR; pinned by `tests/valuation_math/test_package_model.py`). The model is registered
  in both `PACKAGE_MODELS` tables, with JS/Python parity cases added to
  `tests/fixtures/package_model_parity_cases.json`.
* Every package verdict moves at once: the calculator meter and YES/NO input, Second Opinions per-source
  opinions, Trade Finder / suggestions / angles scoring, Monte Carlo, Trade History current grades and
  public `/league` grades. §5 gives the expected share that changes level.
* The provisional fairness bands (`config/trade/fairness_bands.json`, re-derived for the geometric model)
  and the ±200 aging band would be re-validated.
* Trade History stamps `packageModel` and already refuses cross-model aging comparisons; old snapshots keep
  their model label.
* Rollback stays one line back to `geom_q078_v1`; `ktc_2026_04` remains the comparator. PR #1826's
  side-by-side comparison is unaffected: it compares the active model with `ktc_2026_04` by id.

## Completion result

* `STATUS: DONE` (research and recommendation; no challenger implemented, by recommendation).
* `ACCEPTANCE:` the owner's averaging idea at 5 weights on identical canonical values; the mandatory
  `[7200]` vs `[6000, 1]` case; mathematically consistent alternatives; the §4 properties; the §5 shapes
  and populations; completed trades with a chronological holdout; a plain-English report A–J; production
  unchanged.
* `EVIDENCE:` `research.json` / `matrix_cells.csv` from the committed script at the stamped code SHA;
  `tests/scripts/test_package_model_hybrid_research.py`, plus the existing
  `tests/valuation_math` suite still green.
* `UNRESOLVED:` (1) the production-box market-trade ledger run (`--market-ledger`) has not been executed;
  that data is not in this container. (2) Trade Finder was not re-run end-to-end per model; impact is
  estimated from band-change rates through the same dispatch. (3) Own-league values are reconstructed
  with today's pipeline over point-in-time raw inputs, not the values served on the trade date.
* `BLOCKERS:` none for the recommendation. The box run needs box access.
* `NEXT_ACTION:` owner decision on the recommendation. Optionally, run `--market-ledger` on the box.

## Addendum (2026-10-21): `fairness_bands_v2` re-measurement

The fairness levels in this memo were classified on the retired `fairness_bands_v1` denominator. They are
re-measured on `fairness_bands_v2` in `PACKAGE_MODEL_PHASES_1_3_V2_REMEASURE_2026-10-21.md` (§4.1). The
recorded v1 numbers reproduce exactly, except the Trade Finder replays (see its §3). **The KEEP recommendation does not change.** This memo and its evidence
are preserved as recorded.
