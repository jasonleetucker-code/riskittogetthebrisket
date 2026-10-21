# Package Value Adjustment — Phase 2: large packages, depth vs filler, market evidence, Trade Finder replay (2026-10-19)

**Status: RESEARCH.** Nothing is promoted or changed in production. `geom_q078_v1` (q = 0.78) stays the
authoritative package model, and `ktc_2026_04` stays the read-only comparator. No base value, source weight,
dispatch, config, Trade Finder behaviour or Value Adjustment integration point was modified.

* Phase 1 (`PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md`) is preserved unchanged.
* Phase 2 candidates, criteria and the decision rule were frozen **before any result** in
  `evidence/package_model_phase2_2026-10-19/PREREGISTRATION.md`. That file has one disclosed amendment (the
  orientation fix, §A.2).

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

> **Phase 3 (2026-10-20):** see `PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md`.
> - 18,690 production-ledger trades replicate every finding below.
> - The value-level gradient (§A.4) is explained as a fixed ~2,000-point level effect, not a package-shape
>   effect.
> - This memo is otherwise preserved unchanged.

## Executive summary

| Your question | Answer |
|---|---|
| **1. Is our model undervaluing legitimate depth in large trades?** | **No — the evidence points the other way.** On 1,121 real external dynasty trades priced at the time they happened, the side that consolidated (received fewer pieces) still gave up *more* than our model says it should. That holds even where every incoming piece was a genuine contributor. Managers discount depth **more** steeply than q = 0.78 does, not less. |
| **2. Does it protect against a pile of mediocre players for a star?** | **Yes.** Six filler pieces (each ~5% of a star) never come close: Gibbs vs six ~500-value players is "lopsided" by 7,834 under our model. The incumbent produced **zero** fair-rated "star for a pile" recommendations across every replayed Trade Finder surface. The two depth-friendlier challengers produced 1 and 2. |
| **3. Does any alternative improve Trade Finder recommendations?** | **No.** KTC and the 50/50 blend replace 70–97% of recommendations, mostly with trades our own board rates lopsided. The depth-friendly candidates (EFD_78, HYBRID_50) replace 17–37% and begin surfacing star-for-pile packages. The depth-floor variant changes 5–14% with no measurable quality gain. |
| **4. Keep q = 0.78?** | **Yes — KEEP.** No alternative fixes a demonstrated weakness. The one measurable miscalibration runs *against* adding depth credit, every depth-friendlier challenger moves further from the market, and you asked that q not be re-estimated from accepted trades. |

## A. Market-trade results

### A.1 Data access

* **The production archive was not reachable.** `data/market_trades/*.sqlite` and `data/intel/ledger.sqlite3`
  are box-local and gitignored.
* **No workflow could run the scorer there.** No GitHub workflow runs an arbitrary read-only script on the box.
  Each one copies a fixed, checked-in script. Shipping a new one means changing a checked-in workflow and
  dispatching a production job, which is a production action I did not take without your approval.
* **The documented box command** is:

  ```
  python scripts/package_model_phase2_research.py --market-ledger
  ```

  It reads the canonical ledger read-only and writes aggregates only.
* **What I ran instead (read-only).** I rebuilt the same lanes the box collects, **from the same public
  sources, inside this research container**, using the repository's own collectors, normalizer, deduplicator,
  format capture and eligibility owner. Nothing touched production, its stores or its timers.
  * **KTC Trade Database:** the public page's rolling 200-trade window (`src/sources/ktc_trades.collect`).
  * **Sharp-discovery Sleeper lane:** `scripts/discover_sharp_graph.py`, then
    `scripts/crawl_sharp_transactions.py`, over Sleeper's public API from the committed
    `config/sharp/discovery_seeds.json`.
    * 612 managers, 927 leagues, 418 Sharp-eligible dynasty leagues; 2,924 API calls.
    * 104,034 transactions seen; 1,105 two-party trades in 316 leagues.
    * Format captured for all 316 trade-bearing leagues.
  * **Ledger:** `market_trade_report.build_ledger` (dedupe across lanes), then the Phase 2 pricing
    (`market_rows_from_groups`).
* **Pricing rule.** Each trade is priced on the canonical board **archived strictly before its date**
  (≤ 7 days), through `market_trade_eval.BoardIndex`. A trade with any asset that board could not price is
  excluded, never priced at 0.
* **Coverage is narrower than the box archive.** The crawler's own backfill policy is 30 days, so the
  sample spans **2026-09-19 → 2026-10-19**. Widening that window in-process was refused by this session's
  permission policy, and I did not work around it. The production ledger holds the longer history.

### A.2 Data quality audit

| check | result |
|---|---|
| groups built | 1,304 (200 KTC + 1,105 Sleeper; one cross-source match merged) |
| duplicates | 1,303 `CONFIRMED_UNIQUE`, 1 `PROBABLE_DUPLICATE` (a KTC row matching a Sleeper trade — counted once) |
| multi-team trades | 2 found, **excluded** (never collapsed into two-team) |
| one-sided records | 20 excluded |
| look-ahead | none possible: the board must be dated strictly before the trade; 30 boards used |
| missing historical values | 6 trades excluded (an asset the point-in-time board did not price) |
| format | 155 non-superflex / unknown-QB trades **excluded** (our board is superflex; grading 1QB trades on it would measure the format) |
| **graded** | **1,121** — Sleeper Sharp 981, KTC database 140 |
| concentration | 406 leagues; the largest league is **1.5%** of the sample, the top five **5.9%**. Capping each league at 3 trades (n = 810) gives the same ordering: deep bin GEOM_78 −0.153, EFD_78 −0.233, HYBRID_50 −0.262 |
| circularity | 116 of the 140 KTC rows are flagged as consumed by KTC Trades values, which vote in our board. Each trade is priced on a board from **before** it, so no trade grades itself. Results are reported per source, and the Sleeper lane (not KTC-derived) carries the conclusion alone |
| IDP / TEP | 17 IDP-league trades (too few — reported, not used for decisions); 870 TE-premium |

**Orientation fix (Amendment 1).** The preregistration first oriented trades by "side holding the best
asset". That makes every 1-for-1 residual positive by construction, a winner's-curse bias. It was found on
the first own-league computation and fixed *before* any market or Trade Finder result. Trades are now
oriented by **piece count**, which carries no value noise.

### A.3 What the archive can and cannot tell us

* **Can:** where real trades *clear*. The target is the **mean signed residual** per structure bin:
  `(consolidating side − deep side) / mean`, on adjusted totals. 0 = the model prices package structure the
  way the market clears; negative = the market charges the deep side more than the model does.
* **Cannot:** whether any trade was *fair*. Accepted trades are a selected sample (rejections are unseen),
  and a lopsided trade can still be accepted. The model was **not** fitted to these trades. q stays 0.78.

### A.4 Results (n, mean signed residual, bootstrap 95% CI)

| model | 1-for-2 / 1-for-3 (n = 396) | ordinary unequal (n = 175) | **deep, 5+ pieces (n = 57)** | deep — later 40% only (n = 28) |
|---|---|---|---|---|
| RAW (no adjustment) | −0.471 | −0.304 | −0.449 [−0.529, −0.366] | −0.509 |
| **GEOM_78 (ours)** | **−0.311** | **−0.145** | **−0.142 [−0.184, −0.104]** | **−0.153 [−0.221, −0.095]** |
| KTC | −0.298 | −0.168 | −0.155 | −0.167 |
| BLEND 50/50 | −0.304 | −0.156 | −0.147 | −0.158 |
| FGEOM_70_20 | −0.299 | −0.141 | −0.146 | −0.159 |
| GEOM_85 | −0.358 | −0.188 | −0.210 | −0.230 |
| HYBRID_50 | −0.311 | −0.189 | −0.258 | −0.290 |
| **EFD_78 (new challenger)** | −0.298 | −0.173 | **−0.228 [−0.273, −0.185]** | −0.256 |
| LP_150 (sensitivity baseline) | −0.171 | −0.087 | −0.101 | −0.113 |

Plain English:

* In real trades, the manager who takes **fewer** pieces gives **more** canonical value than any of these
  models says is fair. Raw totals miss by 30–50%. Our geometric model removes between one third (1-for-2/3) and two thirds (deep packages) of that gap.
* **Every depth-friendlier model moves further from the market:**
  * deep bin: EFD_78 −0.23, HYBRID_50 −0.26, GEOM_85 −0.21, against our −0.14;
  * the same ordering holds in every slice — Sleeper only, KTC only, with and without picks, TE premium.
* **Genuine depth gets no relief.** Where *every* piece of the deep side is at least 40% of the consolidated
  asset (n = 462), the consolidating side is still −0.284 behind under our model. The market charges genuine
  depth more steeply than q = 0.78 does, not less.
* **It is not roster size.** Under our model: −0.23 in leagues with ≤ 25 roster spots, −0.27 at 26–32,
  −0.23 at 33–40, −0.22 above 40. Replacement-level cost does not explain it.
* **It is not specific to our board.** Priced on KTC Market's *own* values (212 trades with full KTC
  coverage), the shortfall is the same: −0.32 for 1-for-2/3 and −0.14 for ordinary trades under our model.
* **Part of it scales with value, which no package formula can produce.** The shortfall depends on the
  consolidated asset's value:

  | consolidated asset's value | below 3,000 | 3,000–5,000 | 5,000–7,000 | 7,000+ |
  |---|---:|---:|---:|---:|
  | mean signed residual | −0.455 | −0.275 | −0.172 | −0.146 |

  A scale-invariant package model cannot create a value-level effect. Whatever causes this gradient lies
  outside the package formula: low-end values running rich on value scales generally (it persists on KTC's
  scale), or a per-piece cost managers apply that does not track roster size. That is a valuation-owner
  question, not a package-model one. **No change is proposed or authorized here.**
* **The incumbent does show a demonstrated miscalibration** under the preregistered rule: its deep-bin CI
  excludes 0 on the held-out later period. But it runs in the direction of **too little** consolidation
  credit, the opposite of the concern. The only preregistered challenger, EFD_78, makes it worse.
  * LP_150 sits closest to 0, but it was not a preregistered challenger and is far more star-leaning on
    ordinary trades (Phase 1 §4).
  * Promoting it would be fitting q to accepted trades, which you ruled out.

Own league (38 graded trades, reconstructed boards; 9 / 10 / 3 trades in the three bins): far too small to
decide anything. It points the same way: GEOM_78 −0.36 / −0.05 / −0.09, against EFD_78 −0.34 / −0.08 /
−0.19 (`phase2.json → ownLeagueCalibration`).

## B. Why large packages favour the superstar

### B.1 The mechanism, exactly

Our model sorts each side best-first and counts piece *k* at `0.78^(k−1)` of its value. The weights are
1, .78, .61, .47, .37, .29, .22, .17, .14, .11 and never sum above 4.55. Consequences:

1. **A package of n equal pieces is worth `T × (1 − 0.78^n) / (n × 0.22)`** of its raw total T: 89% at 2,
   72% at 4, 59% at 6, 42% at 10. To equal one star, an even six-piece package needs **1.70×** the star's raw
   value, and an even ten-piece package **2.40×** (break-even table below).
2. **Phase 1 sampled 1-for-6 / 1-for-10 only where raw totals were within 30%.** That caps the package at
   1.43× the star. Below 1.70× an even package cannot win, so the star "won" ~91–100% of the time. **That
   figure measures the sampling window, not a fixed bias toward stars.** Six genuine starters with ~1.8× the
   star's raw value are judged even (Gibbs vs six ~2,950 players: −556, *fair*, §C).
3. **The discount depends on rank, not value.** The 6th piece keeps 29% of its value whether it is a starter
   or a 1-point filler. Filler is protected only because it has little value to begin with.

Raw multiple of the star a 1-for-n package needs to **equal** the star. r = ratio between consecutive
pieces: 1.00 = even depth, 0.15 = one headliner plus filler.

| model | n = 2 (even / headliner) | n = 4 | n = 6 | n = 10 |
|---|---|---|---|---|
| **GEOM_78** | 1.12 / 1.03 | 1.40 / 1.04 | **1.70** / 1.04 | **2.40** / 1.04 |
| EFD_78 | 1.12 / 1.06 | 1.26 / 1.08 | 1.35 / 1.08 | 1.47 / 1.08 |
| HYBRID_50 | 1.12 / 1.05 | 1.23 / 1.06 | 1.29 / 1.06 | 1.37 / 1.06 |
| FGEOM_70_20 | 1.14 / 1.03 | 1.42 / 1.04 | 1.69 / 1.04 | 2.18 / 1.04 |
| KTC (at a 9,000 star) | 1.38 / 1.11 | 1.95 / 1.13 | 2.22 / 1.13 | 2.50 / 1.13 |

### B.2 Is that appropriate?

Your eight questions, answered from the controlled matrix and the market evidence:

1. **Does it distinguish genuine depth from filler?** Only through their values. It applies the same
   *percentage* haircut by position, so filler is protected because it is worth little, not because it is
   discounted harder.
2. **Asset values vs asset count?** Both matter. For a fixed total, our model (like every candidate) credits
   a concentrated package more than an even one: 1.04× vs 1.70× break-even at n = 6.
3. **Are useful secondary players discounted too aggressively?** By the market evidence, **no**. Accepted
   trades show managers discount them *more*.
4. **Do very low-value players keep too much influence?** No. A 2%-of-star piece adds 52 points as the 6th
   piece and 19 as the 10th. A 1-point piece adds 0.3 and 0.1.
5. **Does a near-worthless 6th / 7th / 10th piece move fairness?** No. It cannot add more than its own value
   (property-tested), and in practice adds a fraction of it.
6. **Even vs concentrated packages?** Concentrated packages win for the same raw total. That is the intended
   consolidation premium, and every sound model shares it.
7. **Several genuine starters for one elite player?** Judged sensibly (real examples, §C):
   * three ~3,900 starters (raw 1.2× Gibbs): Gibbs "slight";
   * four ~3,250 (1.32×): "slight";
   * six ~2,950 (1.8×): "fair";
   * ten ~2,170 (2.2×): "fair".
8. **Picks, IDP, mixed?** Same formula (scale-invariant), same behaviour:
   * Gibbs for three firsts (raw 1.21×) is "fair";
   * Schwesinger for four IDP starters (1.32×) is "slight";
   * six IDP filler is "lopsided".

**Conclusion:** the ~91% superstar figure is the arithmetic of near-balanced sampling, not a defect. Where
depth is genuinely bigger, it wins under our model. The real-trade evidence says the market is stricter
still.

## C. Depth vs filler, controlled

### C.1 Synthetic, star = 9,000

"Star lead" = adjusted gap in the star's favour.

| package | raw | effective pieces | GEOM_78 | EFD_78 | HYBRID_50 | KTC |
|---|---:|---:|---|---|---|---|
| six starters (30% each) | 16,200 | 6.0 | −509 fair | −2,986 lopsided | −3,558 lopsided | +3,552 unfair |
| six bench (20% each) | 10,800 | 6.0 | +2,661 lopsided | +1,009 slight | +628 slight | +6,120 lopsided |
| six filler (5% each) | 2,700 | 6.0 | +7,415 lopsided | +7,002 lopsided | +6,907 lopsided | +8,477 lopsided |
| 2 starters + 4 filler | 10,800 | 3.3 | +206 fair | +162 fair | −121 fair | +4,233 lopsided |
| near-star + 5 filler | 10,800 | 2.1 | −685 slight | −570 slight | −845 slight | +186 fair |
| ten starters (25% each) | 22,500 | 10.0 | −375 fair | −6,278 lopsided | −7,472 lopsided | −14 fair |
| ten filler (5% each) | 4,500 | 10.0 | +7,125 lopsided | +5,944 lopsided | +5,706 lopsided | +8,170 lopsided |

### C.2 Real canonical players, 2026-10-19

Star is Jahmyr Gibbs (9,869).

| Gibbs for … | raw | GEOM_78 | EFD_78 | HYBRID_50 | KTC |
|---|---:|---|---|---|---|
| six ~2,950 starters (Freiermuth, Corum, Raridon, Worthy, A. Williams, Montgomery) | 17,719 | −556 fair | −3,241 lopsided | −3,866 lopsided | +4,174 lopsided |
| six ~1,775 bench (Tremble, Sarratt, K. Allen, N. Gray, Tracy, Claiborne) | 10,650 | +3,615 lopsided | +1,989 unfair | +1,614 unfair | +7,304 lopsided |
| six ~500 filler (Duvernay, Homer, McAlister, J. Wilson, Z. White, Wester) | 3,241 | +7,834 lopsided | +7,463 lopsided | +7,349 lopsided | +9,257 lopsided |
| three ~3,900 starters (Concepcion, Darnold, Mayfield) | 11,814 | +439 slight | +47 fair | −134 fair | +5,401 lopsided |
| four ~3,250 (Pierce, Monangai, Downs, O. Cooper) | 13,035 | +516 slight | −456 fair | −754 slight | +5,443 lopsided |
| ten ~2,170 (Rodgers, Vele, T. Johnson, Engram, Singleton, M. Jones, …) | 21,727 | +768 fair | −4,884 lopsided | −6,037 lopsided | +2,812 unfair |
| D. Smith + C.J. Stroud + four filler | 11,828 | +136 fair | +164 fair | −136 fair | +5,727 lopsided |
| three firsts (1.12, 2.01, 2029 Mid 1st) | 11,932 | +344 fair | −51 fair | −234 fair | +5,333 lopsided |
| two seconds + two starters | 12,646 | +642 slight | −154 fair | −443 slight | +5,679 lopsided |
| IDP: Schwesinger (6,246) for four ~2,050 IDP starters | 8,235 | +330 slight | −277 fair | −465 slight | +3,389 lopsided |
| IDP: Schwesinger for six ~400 IDP filler | 2,435 | +4,787 lopsided | +4,444 lopsided | +4,358 lopsided | +5,799 lopsided |
| offense + IDP depth (DeJean, Oluokun, Coleman, Bell, Okonkwo) | 14,627 | +309 fair | −1,292 slight | −1,723 unfair | +5,094 lopsided |

How to read it:

* **Filler.** Every sound model protects the star decisively against filler, and the incumbent most
  strongly.
* **Genuine depth.** The models differ on large packages of real starters:
  * Ours calls six or ten genuine starters with 1.8–2.2× Gibbs's raw value roughly **even**.
  * EFD_78 and HYBRID_50 call the same trades **lopsided for the depth side**.
  * The market evidence (§A.4) says real managers lean the *other* way from EFD and HYBRID.

### C.3 Asymmetric shapes

Star = 9,000. Gap shown for A, the fewer-pieces side.

| shape | raw A / B | GEOM_78 | EFD_78 | HYBRID_50 | KTC |
|---|---|---|---|---|---|
| 2v3 | 12,600 / 13,500 | +884 slight | +196 fair | +92 fair | +3,739 lopsided |
| 2v5 useful | 12,600 / 15,750 | +1,624 unfair | −590 slight | −950 slight | +5,685 lopsided |
| 2v5 filler-heavy | 12,600 / 13,500 | +690 slight | +416 fair | +178 fair | +4,391 lopsided |
| 3v6 useful | 18,000 / 21,600 | +2,724 unfair | −809 slight | −1,289 slight | +6,740 lopsided |
| 4v8 useful | 22,500 / 28,800 | +3,811 unfair | −2,170 slight | −2,962 unfair | +7,117 lopsided |
| 4v8 filler-heavy | 22,500 / 23,400 | +1,324 slight | +404 fair | −9 fair | +3,773 unfair |

## D. Alternative models

| model | formula | maths (all §4 properties + the 1-point bound + split + concentration continuity) | strength | weakness |
|---|---|---|---|---|
| **GEOM_78** (incumbent) | `Σ 0.78^(k−1) v_(k)` | **pass** (0 failures / 4,000 + Phase 1's 20,000) | simple; firm consolidation premium; closest to the market in the deep bin among non-LP candidates (in the 1-for-2/3 bin EFD, KTC and FGEOM are ~0.01 closer — inside noise) | rank-only discount; saturates at 4.55× the top piece |
| **EFD_78** (new, preregistered) | `(Σ v^p)^(1/p)`, p = 1/log2(1.78) = 1.2021, i.e. `T · N_eff^(1/p−1)` | **pass** | value-aware: filler gets a heavier haircut, genuine depth a lighter one; same two-piece premium as ours; explainable as "effective number of pieces" | moves away from where real trades clear (deep −0.23 vs −0.14); calls six genuine starters lopsided against a superstar; Trade Finder surfaces a star-for-pile it never did before |
| FGEOM_70_20 | weights `0.2 + 0.8·0.7^(k−1)` | pass | nearly identical to ours | buys nothing measurable |
| HYBRID_50 | `0.5Σv + 0.5‖v‖₁.₅` | pass | most depth-balanced | furthest from the market among sound models; pile-friendly |
| KTC / blends | Phase 1 | **fail**: add-an-asset 52–79 per 4,000 cases; split helps the splitter 15–35; concentration jumps 13–89 | — | disqualified (mandatory property) |

No model was tuned after the preregistration. EFD's sensitivity members (p = 1.15 / 1.30) bracket it and
change no conclusion (`phase2.json`).

## E. Trade Finder replay

**Method.** Each candidate was installed in-process only, by replacing
`package_model._geom_pair` — the one function every active-model Value Adjustment call reaches. It was always
restored, and production files and the live server were never touched (test-pinned). The same board
(2026-10-19), the same 12 teams against all opponents and the same settings were replayed. Team context was off,
because roster capacity is box-local.

| surface | what was replayed |
|---|---|
| Package Scan | the `/arbitrage` default request (equal-count, discovery top 250 / most impactful) |
| Finder, all shapes | the same request with unequal shapes allowed |
| Best Offers | one best offer per opponent |
| Star builder | Package Builder asked to acquire each opponent's best player |

Golden Upgrades is 1-for-1, where every sound model adds 0, so it was not replayed.

**Model vs search effects.** `packageEnumeration` was identical across all six models on every surface, so
every difference below is a **scoring** difference, not candidate generation.

**Structural fact.** The generators never propose deep packages: the Finder topology rule allows at most one
player of difference, and Package Builder allows at most 3 assets per side. Large-package behaviour therefore
reaches users through the **calculator, Trade History and Second Opinions**, not through recommendations.

**Results.** Counts are against the incumbent. "Star-for-pile" = a fair/slight-rated trade in which the star
side receives 3+ pieces, none ≥ 50% of the star (preregistered).

| surface (incumbent trades) | model | replaced (appear = disappear) | mean top-10 overlap | star-for-pile added | incumbent's sensible-depth trades lost | user's raw gain: appeared / disappeared |
|---|---|---:|---:|---:|---:|---|
| Finder, all shapes (480) | EFD_78 | 117 | 0.68 | **1** | 10 | +1,028 / +1,395 |
| | HYBRID_50 | 82 | 0.76 | **2** | 6 | +1,140 / +1,343 |
| | FGEOM_70_20 | 36 | 0.83 | 0 | 1 | +863 / +1,493 |
| | BLEND 50/50 | 426 | 0.08 | 0 | 21 | +1,050 / +1,144 |
| | KTC | 463 | 0.03 | 0 | 29 | +1,668 / +1,177 |
| Package Scan (480) | EFD / HYBRID / FGEOM / BLEND / KTC | 91 / 89 / 28 / 340 / 425 | 0.72 / 0.73 / 0.88 / 0.20 / 0.13 | 0 | 72 / 69 / 25 / 300 / 378 | — |
| Best Offers (132) | EFD / HYBRID / FGEOM / BLEND / KTC | 27 / 23 / 7 / 85 / 108 | 0.78 / 0.83 / 0.93 / 0.33 / 0.14 | 0 | 17 / 16 / 4 / 58 / 76 | KTC: −253 / +2,601 |
| Star builder (660) | EFD / HYBRID / FGEOM / BLEND / KTC | 241 / 219 / 65 / 494 / 564 | 0.60 / 0.67 / 0.88 / 0.23 / 0.16 | 0 | 55 / 53 / 15 / 103 / 133 | KTC: −191 / +1,439 |

"User's raw gain" is the canonical value the user receives minus what they send, which is the finder's own
board edge. Under KTC and the blends, the recommendations that replace ours give the user *less* on our own
board: on average −253 and −191, against +2,601 and +1,439 for the ones they displace.

The incumbent produced **0** star-for-pile recommendations on every surface. The new one under the
depth-friendlier models: **Cam Skattebo (4,233) + Denzel Boston (4,203) + Sam Darnold (3,988) → Josh Allen
(9,963) + Terrel Bernard (2,462)**, rated only "slight". Which trades appear and disappear is listed per model
and surface in `phase2.json → finder.examples`.

**Is any model better?** The preregistered C6 rule says a challenger may neither add star-for-pile
recommendations nor drop sensible multi-starter trades the incumbent keeps.

* EFD_78 and HYBRID_50 do both.
* KTC and the blends rewrite the Finder almost completely, hand the user a worse board edge, and fail the
  mathematics.
* FGEOM drops a few sensible-depth trades and reorders others, with no quality signal in its favour.

**No candidate improves the recommendations.** On the second question, whether the incumbent wrongly rejects
sensible depth: every candidate that keeps trades the incumbent drops also drops sensible-depth trades the
incumbent keeps. No pattern of systematic rejection by the incumbent shows up.

## F. Scorecard

✔ pass · ✘ fail · ≈ no difference · — not evidence either way.

| criterion | GEOM_78 | EFD_78 | FGEOM_70_20 | HYBRID_50 | KTC / blends |
|---|---|---|---|---|---|
| C1 mathematics | ✔ | ✔ | ✔ | ✔ | ✘ |
| C2 ordinary trades (market) | −0.31 / −0.15 | −0.30 / −0.17 | −0.30 / −0.14 | −0.31 / −0.19 | −0.30 / −0.16 |
| C3 large packages (market deep bin) | −0.14 (closest) | −0.23 ✘ | −0.15 ≈ | −0.26 ✘ | −0.15 |
| C4 depth vs filler | filler protected; genuine depth near even at ~1.8× | depth favoured | ≈ ours | depth favoured | star always |
| C5 held-out period | consistent | worse | ≈ | worse | ≈ |
| C6 Trade Finder | 0 star-for-pile | +1 star-for-pile, −10…72 sensible-depth ✘ | 0 star-for-pile; −1…25 sensible-depth ✘ (minor) | +2, −6…69 ✘ | rewrites 70–97%; worse user edge |
| C7 stability | smooth | smooth | smooth | smooth | jumps |
| C8 explainability | high | medium | medium | medium | low |
| C9 risk | none (in production) | full regrade | low but pointless | full regrade | full regrade |

## G. Production impact if a different model were ever approved

Unchanged from Phase 1 §9:

* `config/trade/package_model.json` and `frontend/lib/trade-logic.js::ACTIVE_PACKAGE_MODEL_ID` would change
  together.
* The model would be registered in both `PACKAGE_MODELS` tables, with parity cases added to
  `tests/fixtures/package_model_parity_cases.json`.
* Every active-model consumer would move at once:
  * calculator meter and decision input;
  * Second Opinions;
  * Trade Finder scoring and discovery ordering (`finder_value_adjustment`, `discovery.candidate_metrics`);
  * Best Offers;
  * Package Builder;
  * suggestions, angle and Monte Carlo;
  * Trade History current grades and public `/league` grades.
* The provisional fairness bands and the ±200 aging band would be re-validated.
* `cross_market.py` stays on KTC by design.
* Trade History stamps `packageModel` and refuses cross-model aging.

## H. Recommendation

**KEEP — retain `geom_q078_v1` with q = 0.78 unchanged.** No alternative demonstrates a meaningful,
reproducible improvement.

* The only measurable miscalibration runs against giving depth more credit.
* Every depth-friendlier challenger is further from where real trades clear and starts recommending
  star-for-pile trades.
* KTC and its blends remain mathematically disqualified.

Two observations for separate, future owner decisions. **Neither is authorized or implemented here.**

1. Real trades clear with an even larger consolidation premium than q = 0.78 gives. That is not grounds to
   change q:
   * you ruled out re-estimating q from accepted trades;
   * the curve confound below is unresolved.
2. Part of that shortfall scales with asset value (−0.46 below 3,000 vs −0.15 above 7,000), which no package
   formula can produce. It persists on KTC's own value scale. Whether low-end values run rich relative to
   where trades clear is a question for the value pipeline, with this evidence.

## I. Verification and outstanding work

* **Commands run (this container):**

  ```
  python scripts/package_model_phase2_research.py --finder \
      --local-ktc-archive <scratch>/archive_frozen.sqlite \
      --local-intel-ledger data/intel/ledger.sqlite3 \
      --player-directory <scratch>/players_nfl.json
  ```

  Collectors: `src/sources/ktc_trades.collect`, `scripts/discover_sharp_graph.py --budget 3000 --generations 2`,
  `scripts/crawl_sharp_transactions.py --budget 12000 --format-budget 600 --own-league-format-budget 0`.
* **Tests:** locally, `pytest tests/scripts/test_package_model_phase2_research.py tests/scripts/test_package_model_hybrid_research.py tests/valuation_math tests/docs tests/scripts/test_check_work_claims.py tests/trade/test_finder_value_adjustment.py tests/trade/test_finder_va_is_not_bypassable.py`
  → 294 passed; `bash scripts/format_python_changes.sh` green; planning integrity OK.
* **CI:** PR #1833 Validate PR passed on the Phase 1 head `8c4dedee` (run 39227729779). The Phase 2 head is
  validated by the push that carries it — see the PR.
* **Evidence:** `evidence/package_model_phase2_2026-10-19/phase2.json` — aggregates only, no other league's
  trade contents. The collected public stores are not committed (privacy rule: counts, never contents).
  Re-running the collectors later gives a different window.
* **Completed:** controlled matrix; properties; real-player examples; own-league calibration; public-market
  sample (1,121 trades) with audit, splits, holdout and the value-curve diagnostic; full Trade Finder replay
  (4 surfaces × 12 teams × 6 models).
* **Not completed:**
  * (1) the production-box ledger run (`--market-ledger`) — box access needed;
  * (2) trades before 2026-09-19 — crawler window; widening it was refused by permission policy;
  * (3) Trade Finder with team context on — box-local roster capacity;
  * (4) the KTC-Market value-basis control covers 212 trades (915 lacked full KTC coverage, mostly IDP or
    picks), so it is indicative;
  * (5) the value-curve hypothesis is an observation, not tested methodology.

UNRESOLVED: items (1)–(5) above; none blocks the KEEP recommendation.

## Addendum (2026-10-21): `fairness_bands_v2` re-measurement

The fairness levels in this memo were classified on the retired `fairness_bands_v1` denominator. They are
re-measured on `fairness_bands_v2` in `PACKAGE_MODEL_PHASES_1_3_V2_REMEASURE_2026-10-21.md` (§4.2). The
recorded v1 numbers reproduce exactly. **The KEEP recommendation does not change.** This memo and its evidence
are preserved as recorded.
