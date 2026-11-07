# W13-F003 methodology proposal: BDVM signal saturation

**Activation status: NOT ACTIVATED.** This is a research proposal. No production formula, weight,
threshold, parameter or feature flag is changed. `src/bdvm/*`, `config/bdvm/*` and every served
path are untouched, and BDVM still never touches `rankDerivedValue`.

| | |
|---|---|
| Finding | W13-F003 (P1, OPEN per `docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md`) |
| Authority | Owner directive 2026-11-07 (`docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md` §3): investigate, propose, test and compare. Do not activate. MD-59 in `docs/OWNER_REQUESTED_TODO.md` |
| Study script | `scripts/research/bdvm_saturation_study.py` (offline, deterministic, does not import `src/bdvm`) |
| Pins | `tests/scripts/test_bdvm_saturation_study.py` |
| Evidence | `docs/valuation/evidence/w13-f003-bdvm-saturation-2026-11-07/` (`study_report.json`, `players.csv`) |
| Existing regression | `tests/bdvm/test_audit_w13_f003_regression.py` (strict xfail). Unchanged, and it stays xfail because production is unchanged |

## 0. Summary

* **Cause.** The saturation is a **scale artefact, not a market fact.** The gap subtracts two
  numbers on different scales. BDVM's served value is `9800 x (DV/DVmax)^1.2`. It is anchored at
  one point (the board maximum) and, because DV is surplus over replacement, it falls to zero at
  replacement level. The market curve is much flatter and never falls below about 474. Split the gap
  into a part that depends only on BDVM's own rank (the curve-shape part) and a part that measures
  ranking disagreement. The curve-shape part is negative on **676 of 676** rows and **on its own
  produces 675 STRONG_SELLs**. The ranking-disagreement part is centred: its median is −49.5. The
  incumbent alpha has a rank correlation of **−0.75** with the market price itself, so STRONG_SELL
  mostly encodes "this asset is expensive". Liquidity plays no part: setting every liquidity to 1.0
  moves the STRONG_SELL count from 570 to 571.
* **The spec's own calibration step was never run.** BDVM spec §6.6 sets γ = 1.20 as a prior and
  says to "calibrate so your model's top-30 spacing matches market spacing". On the pinned board
  that calibration gives **γ\* = 0.545**.
* **Candidates.** I tested five corrections against the incumbent on identical inputs. Two
  rank-quantile maps (C2 pooled, C3 per market) remove the artefact: STRONG_SELL falls from 570 to
  224 or 213. Refitting γ (C1) overshoots into a BUY bias. Percentile thresholds (C4) force a
  balanced split but keep the price-tier ordering, so their signals point the wrong way. The
  uncertainty-band candidate (C5) maps BDVM's own p20/p85 band onto the market scale and calls
  BUY/SELL only when the market sits outside it. It abstains on 78% of rows, including 95 of the 115
  thin-sample rows.
* **Predictive evaluation (T6 of the BDVM spec, shortened to 30/60/90 days).** **No candidate shows
  positive skill at predicting later market movement, and neither does the incumbent.** The
  incumbent's continuous score is *anti*-predictive at 30 and 60 days: Spearman −0.208, 95% CI
  [−0.282, −0.138] at 30 days. C2 and C5 are measurably less anti-predictive. On the paired
  bootstrap, C2 minus C0 at 30 days is [+0.046, +0.125] and C5 minus C0 is [+0.062, +0.215]. After
  controlling for market rank, every candidate is within noise of zero. This is one cross-section of
  proxy-only fundamentals over 95 days. That is not enough to activate anything.
* **Recommendation.** Do not activate any candidate. Reject C1 and C4 with reasons (§6). Send
  **C5, with C2 as its ablation and C0 as control**, to an owner-approved **shadow** evaluation with
  a preregistered T6 test (§13). Separately, the owner decides what the currently served incumbent
  labels and alerts should do while this finding is open (§14, decision B).

## 1. Current formula and meaning

Live path: `src/bdvm/service.py` → `market.market_comparison` → `market.buy_hold_sell`, served by
`GET /api/bdvm/values` behind `bdvm_engine` (default ON).

```
DV_s(i)   = risk-adjusted discounted fantasy surplus over replacement           (engine.py::_discounted_value)
anchor_s  = max_i DV_s(i) / (9800/10000)^(1/γ)        γ = scale.stud_gamma = 1.20 (engine.py::calibrate)
TV_s(i)   = 10000 · (DV_s(i)/anchor_s)^γ  =  9800 · (DV_s(i)/max DV_s)^γ        (below the 9900 knee)
gap(i)    = TV_balanced(i) − market(i)                                           (market.py:256)
alpha(i)  = round(gap(i) · liquidity(i), 1)
liquidity = clip(1.0 − 1.6·marketDispersionCV, 0.2, 1.0); unmeasured → 0.2 for the scale, gate fails closed
signal    = STRONG_BUY  alpha > +900 and measured liquidity > 0.5
            BUY         alpha > +400
            HOLD        −400 ≤ alpha ≤ +400
            SELL        alpha < −400
            STRONG_SELL alpha < −900, or alpha < −400 and P(collapse_1y) > 0.5
            NO_MARKET   no anchor (KTC Market → ktcSfTep → ktc for offense; idpTradeCalc for IDP)
```

Thresholds: `config/bdvm/params_v1.json` `market.signal_thresholds`, which are labelled priors
(spec §6.6 and Appendix: "signal = STRONG BUY if alpha > +900 …").

**Intended meaning** (spec §5.10, CLAUDE.md BDVM section, and the /rankings tooltip): a positive gap
means the market underprices the player relative to fundamentals, and alpha is the realisable part
of that gap. That reading only holds if `TV_model` and `TV_market` are on the same scale. The spec
assumes they are and says how to make them so (calibrate γ against market spacing). The
implementation ships the uncalibrated prior.

## 2. Defect evidence, reproduced on pinned inputs

The only reproducible BDVM board is the audit's frozen run,
`docs/master-site-audit/evidence/W13/engine-live-run.json`
(sha256 `820e3cdc…f9f4a3e`, asOf 2026-08-04T22:18Z, contract 2026-08-04T20:12Z,
`params_v1:01af672b2aff`). `data/bdvm/projections/` is box-local and gitignored. No other board is
committed, and I fetched nothing from the network. The study re-derives the incumbent ladder
independently. The test feeds the same rows through the **production** `market_comparison` +
`buy_hold_sell` and gets identical labels on every one of the 676 rows:

| | STRONG_SELL | SELL | HOLD | BUY | STRONG_BUY | NO_MARKET |
|---|---|---|---|---|---|---|
| recorded run = production ladder today = study C0 | **570** | 13 | 69 | 14 | 10 | 23 |

On the 676 market-anchored rows: served TV median 511.6 vs market median 1914.5; gap median −1228.8
(p10 −2796.6, p90 −184.4); 92.6% of gaps are negative. STRONG_SELL share is 0.843 of anchored rows
and 0.815 of the 699 priced rows. This matches the audit exactly.

## 3. Diagnosis: where the saturation comes from

### 3.1 Splitting the gap into curve shape and ranking disagreement

Let `Q(i)` be the market value at TV(i)'s own mid-rank percentile within the same 676 assets (the C2
map, §5). Then `gap = [TV − Q] + [Q − M]`:

* **shape = TV − Q** depends only on BDVM's own rank. It is the difference between BDVM's value
  curve and the market's value curve at that rank, which is a units and curve artefact.
* **rank = Q − M** is the ranking disagreement, expressed in market units.

| component | median | share negative | variance | ladder applied to this component alone |
|---|---|---|---|---|
| shape | **−1315.8** | **100%** | 284,546 | **675 STRONG_SELL**, 1 HOLD |
| rank | −49.5 | 53.6% | 1,552,850 | = candidate C2 (224 STRONG_SELL / 131 STRONG_BUY) |

The one-sidedness comes entirely from the shape part. The player-specific content is in the rank
part, which is centred but large: rank correlation between TV and market is only **0.591**.

### 3.2 Two curve defects, at the top and at the bottom

* **Top of the board: an uncalibrated stud exponent.** Ratio to the #1 asset at ranks 1–10:

  | rank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | BDVM DV | 1.000 | 0.763 | 0.753 | 0.749 | 0.729 | 0.715 | 0.714 | 0.688 | 0.678 | 0.666 |
  | market | 1.000 | 0.999 | 0.998 | 0.998 | 0.992 | 0.925 | 0.920 | 0.893 | 0.888 | 0.794 |
  | served TV (γ = 1.2) | 1.000 | 0.723 | 0.711 | 0.706 | 0.684 | 0.669 | 0.667 | 0.638 | 0.627 | 0.614 |

  BDVM's raw DV already spreads the top wider than the market does, and γ = 1.2 > 1 stretches it
  further. Only the single board maximum (Drake Maye, TV 9800) reads BUY in the top 10. Bijan
  Robinson (market 9999, TV 6538) is STRONG_SELL by 3,461 points. Least-squares spacing calibration
  per spec §6.6 gives γ\* = **0.545** on the top 30, 0.605 on the top 50, 0.631 on the top 100 and
  0.595 on all rows. A convex γ is the wrong side of 1 for matching this market.
* **Bottom of the board: different replacement origins.** DV is surplus over replacement, so TV → 0
  at replacement. 125 anchored rows have TV < 100 and 17 have DV = 0. The market prices the same
  assets at 474 or more, because the KTC top-500 and IDPTC top-900 floors reflect option value and
  roster utility. No power transform can map 0 to 474, so the bottom tier shows a structural gap of
  roughly −market. By market decile, the median TV/market ratio is 0.51 in the top decile and
  0.09–0.24 in deciles 3–10.
* **The thresholds are absolute points on a convex scale.** ±400/±900 is 47% of the median asset but
  9% of a 9999 asset. To bring the incumbent under 50% STRONG_SELL, the strong-sell bar would have to
  sit near the board's median alpha (−1178.7). Threshold sensitivity for C0 at ×0.5 / ×1 / ×1.5 /
  ×2 / ×3 gives 598 / 570 / 502 / 417 / 269 STRONG_SELL. Even tripling the thresholds leaves 40%
  STRONG_SELL, because the offset sits in the level, not the tails.

### 3.3 Liquidity is not the cause

All 676 anchored rows have measured liquidity, median 0.968 and minimum 0.60. With every liquidity
forced to 1.0 the incumbent reads 571 STRONG_SELL, against 570. The `strong_buy_min_liquidity` gate
(0.5) is decorative on this board, as `market.py` already notes.

### 3.4 Position and asset class (incumbent)

| group | market | n | median TV | median market | ρ(TV, market) | C0 STRONG_SELL |
|---|---|---|---|---|---|---|
| QB | KTC | 56 | 2027 | 2675 | 0.70 | 32 (57%) |
| RB | KTC | 103 | 523 | 2267 | 0.80 | 98 (95%) |
| WR | KTC | 148 | 291 | 2081 | 0.83 | 147 (99%) |
| TE | KTC | 61 | 574 | 2819 | 0.77 | 57 (93%) |
| DL | IDPTC | 79 | 623 | 1288 | 0.55 | 53 (67%) |
| LB | IDPTC | 127 | 184 | 1425 | 0.66 | 121 (95%) |
| DB | IDPTC | 102 | 642 | 1226 | 0.35 | 62 (61%) |

Offense agrees with KTC on order (ρ 0.70–0.83) and disagrees on level. IDP agrees less with IDPTC
(ρ 0.35–0.66).

### 3.5 Sensitivity to missing and stale inputs

* **Every one of the 676 rows is proxy-backed**: a single source, `reconstructedBaseline`, which is
  2025 realized PPG under dynasty_main scoring. Every row carries `confidenceLabel: low`. The
  incumbent ladder ignores this.
* **115 rows carry `small_nfl_sample`.** Under C0, 85 of them read STRONG_SELL. Under C2, 38 read
  STRONG_BUY: thin-sample players shrunk toward a positional mean (for example backup QBs Quinn Ewers
  and Riley Leonard) become "underpriced". Under C5, 95 of 115 read HOLD.
* **Injury-shortened 2025 seasons drive the largest negative rank gaps** under every candidate
  (Justin Jefferson, Malik Nabers, Mike Evans, Fred Warner, Micah Parsons). Last season's box score
  is stale information that the market has already discounted. `frontend/lib/bdvm.js` already
  describes proxy-backed gaps as "a momentum-fade signal rather than fundamental analysis". No
  signal-layer change can fix stale fundamentals. Only real projection sources can.
* **W13-F001 is a confounder** (reception yardage bands dropped). At the time of the frozen run it
  understated WR fundamentals by 19.7%, TE by 22.0% and RB by 8.1%
  (`docs/master-site-audit/evidence/W13/reception-band-omission.txt`). It is now PENDING_REAUDIT.
  Position-level sells on WR and TE in any candidate are partly this defect.

## 4. Rejected framings, and why balance is not the target

The owner's warning ("a one-sided market may warrant one-sided results") applies here. Within one
relative-value board (both scales top out near 9800–9999), "every asset below the top is overpriced"
is not a per-player statement. It describes the *curve*: the market's single-asset values are flatter
than BDVM's (BDVM bakes a stud premium into single assets; KTC applies consolidation through its
separate package adjustment). That is board-level information, and it should be reported once as a
board statistic (γ\* vs γ, or the curve-shape distribution) rather than stamped on 570 players as a
sell. One-sidedness that comes from **rank** disagreement is kept by every candidate below. For
example, under C2, 73 of 148 WRs and 54 of 127 LBs remain STRONG_SELL while 30 of 56 QBs read
STRONG_BUY. No candidate was chosen or tuned for a balanced split. C4, the one that forces balance,
is rejected (§6).

## 5. Candidates (all computed independently of the production functions)

Every candidate uses only same-day inputs (fundamentals and market as of 2026-08-04). Nothing is
fitted on outcomes.

| id | correction | formula |
|---|---|---|
| C0 | incumbent | as §1 |
| C1 | **scale-aware parametric calibration** (spec §6.6) | `TV' = 9800·(DV/DVmax)^γ*`, γ\* = OLS-through-origin slope of log market spacing on log DV spacing over the rank-matched top 30 (0.5452); same ladder |
| C2 | **pooled rank-quantile map** | `TV'(i) = Q_M((rank_i(TV) − ½)/n)`, where `Q_M` is the empirical quantile of the same n assets' market values (order statistic k at (k+½)/n, linear between); offense and IDP pooled; same ladder on `alpha' = (TV' − M)·liquidity` |
| C3 | per-market rank-quantile map | C2 applied separately to KTC-anchored (offense) and IDPTC-anchored (IDP) assets |
| C4 | **distribution-aware thresholds** | incumbent alpha; labels by fixed shares 10/15/50/15/10 (SS/S/H/B/SB) |
| C5 | **uncertainty-band thresholds** on the C2 scale | `L = Φ(range.floor_p20)`, `H = Φ(range.ceiling_p85)`, where Φ is the C2 map extended piecewise-linearly to any TV and clamped at the board ends; BUY if `M < L`, SELL if `M > H`, else HOLD (no STRONG states) |

## 6. Independently computed expected results

Oracles (`tests/scripts/test_bdvm_saturation_study.py`): the C0 labels equal production row for
row. The C2 and C3 maps equal a brute-force pure-Python computation (count-based mid-rank plus
manual interpolation) within 1e-6. The C2 labels equal the **production** ladder fed the oracle's
mapped values. γ\* equals a 12,001-point grid search within 2e-4.

| | STRONG_SELL | SELL | HOLD | BUY | STRONG_BUY | STRONG_SELL share | actionable share |
|---|---|---|---|---|---|---|---|
| C0 incumbent | 570 | 13 | 69 | 14 | 10 | 0.843 | 0.898 |
| C1 γ\* = 0.545 | 155 | 9 | 196 | 105 | 211 | 0.229 | 0.710 |
| C2 pooled map | 224 | 18 | 225 | 78 | 131 | 0.331 | 0.667 |
| C3 per-market map | 213 | 11 | 244 | 99 | 109 | 0.315 | 0.639 |
| C4 percentile | 68 | 101 | 338 | 101 | 68 | 0.101 | 0.500 |
| C5 band | — | 67 | 526 | 83 | — | 0 | 0.222 |

* **C1 rejected.** A single exponent cannot fit both the top spacing and the body. With γ\* = 0.545
  the median TV' is 2563, above the market median of 1914, so the bias flips to BUY (211
  STRONG_BUY; DB reads 66 of 102 STRONG_BUY). It would also change BDVM's served trade values
  everywhere (trade-eval, roster capitals, double-positive scan, Fund column), which is a far larger
  blast radius than the defect.
* **C4 rejected.** It keeps the incumbent ordering, which is the price tier (ρ = −0.75), so its
  "strongest sells" are the most expensive assets. On outcomes it points the wrong way: at 30 days
  its STRONG_SELL rows *gained* +1.6% relative, its long-short spread is −2.8% and its hit rate is
  0.379, the worst of all candidates.
* C2 and C3 differ only in whether offense-vs-IDP level disagreement is kept (§8).

## 7. Before/after player impacts

All 676 rows are in `players.csv` (served TV, mapped TV', alpha and label per candidate, C5 band).
The C0→C2 transition matrix: every incumbent STRONG_BUY stays STRONG_BUY. 68 of 69 incumbent HOLDs
become STRONG_BUY, because a row whose served TV equals its market price is one BDVM ranks far above
the market. Of the 570 incumbent STRONG_SELLs: 224 stay, 225 become HOLD, 18 SELL, 75 BUY and 28
STRONG_BUY.

| player | pos | market | served TV | C0 | C2 TV' | C2 | C5 band [L, H] | C5 |
|---|---|---|---|---|---|---|---|---|
| Bijan Robinson | RB | 9999 | 6538 | STRONG_SELL (−3461) | 9199 | SELL (−800) | [4626, 9999] | HOLD |
| Josh Allen | QB | 9983 | 5093 | STRONG_SELL (−4891) | 7519 | STRONG_SELL (−2464) | [3332, 9999] | HOLD |
| Ja'Marr Chase | WR | 9982 | 3657 | STRONG_SELL (−6325) | 5963 | STRONG_SELL (−4019) | [2968, 9997] | HOLD |
| Drake Maye | QB | 9199 | 9800 | BUY (+574) | 9999 | BUY (+764) | [5555, 9999] | HOLD |
| Puka Nacua | WR | 8929 | 6702 | STRONG_SELL (−2190) | 9924 | STRONG_BUY (+978) | [4806, 9999] | HOLD |
| Caleb Williams | QB | 7937 | 6968 | STRONG_SELL (−926) | 9983 | STRONG_BUY (+1955) | [4244, 9999] | HOLD |
| Justin Jefferson | WR | 7563 | 932 | STRONG_SELL (−6318) | 2582 | STRONG_SELL (−4746) | [1240, 5504] | SELL |
| Malik Nabers | WR | 7338 | 1041 | STRONG_SELL (−5992) | 2680 | STRONG_SELL (−4433) | [1251, 5606] | SELL |
| Micah Parsons | LB | 5419 | 674 | STRONG_SELL (−4745) | 1997 | STRONG_SELL (−3422) | [1225, 4770] | SELL |
| Will Anderson | DL | 5963 | 5045 | STRONG_SELL (−918) | 7427 | STRONG_BUY (+1464) | [3397, 9999] | HOLD |
| Quinn Ewers (thin sample) | QB | 1667 | 4257 | STRONG_BUY (+2309) | 6444 | STRONG_BUY (+4260) | [2679, 9999] | BUY |

Read with §3.5. The largest remaining sells under C2 and C5 are injury-shortened 2025 seasons, and
the thin-sample BUYs are a proxy shrinkage artefact. Those are fundamental-input defects that persist
under every signal-layer candidate.

## 8. Position and league-format impacts

| group | C0 SS/S/H/B/SB | C2 SS/S/H/B/SB | C3 SS/S/H/B/SB | C5 S/H/B |
|---|---|---|---|---|
| QB | 32/1/14/6/3 | 10/1/7/8/30 | 9/0/6/7/34 | 0/43/13 |
| RB | 98/0/5/0/0 | 42/3/37/10/11 | 30/1/38/22/12 | 10/83/10 |
| WR | 147/1/0/0/0 | 73/2/64/7/2 | 55/5/63/19/6 | 21/120/7 |
| TE | 57/1/2/0/1 | 31/7/16/1/6 | 27/1/24/3/6 | 11/49/1 |
| DL | 53/6/13/5/2 | 8/1/18/23/29 | 13/3/28/19/16 | 2/57/20 |
| LB | 121/1/5/0/0 | 54/4/52/8/9 | 69/1/47/7/3 | 22/103/2 |
| DB | 62/3/30/3/4 | 6/0/31/21/44 | 10/0/38/22/32 | 1/71/30 |

* **Exact league scoring is preserved.** The fundamentals are untouched. Candidates change only how
  a finished fundamental is compared with a price.
* **Superflex.** BDVM's flex-aware replacement and dynasty_main's QB scoring put QBs higher relative
  to the board than KTC SF-TEP does. Every candidate that removes the artefact shows QB as the
  most-bought offense group. This is a format signal BDVM is designed to express. It is unverified.
* **TE premium.** The KTC anchor is a TE++ market, while dynasty_main's card grants no TE premium
  (`bonus_rec_te 0.0`, LI-7 / ADR-009). BDVM discounting TEs is therefore format-consistent, but it
  is confounded with W13-F001 (TE −22.0%).
* **WR** sells are confounded with W13-F001 (−19.7%) and should not be read until that finding's
  re-audit lands.
* **IDP.** Under the pooled map BDVM reads DL and DB as underpriced and LB as overpriced against
  IDPTC. C3 removes any offense-vs-IDP level disagreement (IDP STRONG_BUY 82 → 51, STRONG_SELL
  68 → 92). Pooling (C2/C5) keeps cross-market format information, and the KTC↔IDPTC peer study
  (median ratio 1.000) supports putting them on one scale. IDP rank agreement is weakest (DB
  ρ = 0.35), so IDP labels deserve the least trust under any candidate.
* **Other leagues.** A map is computed per league board, because each league's BDVM board is its own
  scoring. Only dynasty_main is in the owner's scope. No 2026 rookies were priced in the frozen run
  (212 rows were `no_projection`), so rookies are untested.

## 9. Historical predictive evaluation (spec T6, shortened)

**Design.** The signal date is 2026-08-04, the recorded run. The outcome is the relative market
change `log(end/start)` minus that source's median. `start` is the market value the signal saw.
`end` is the same source (ktcSfTep or idpTradeCalc) in the first committed archive on or after +30,
+60 and +90 days (`dynasty_export_20260903_225148`, `…20261003_214933`, `…20261102_015256`). Players
who dropped out of the top-N snapshot are censored at that file's minimum (22–25 rows), and a
complete-case variant is reported. Metrics: Spearman of score vs outcome; partial Spearman
controlling for market rank (to separate "the gap knows something" from "expensive assets behaved
differently"); hit rate and long-short spread on actionable labels; paired bootstrap with 2,000
resamples over players.

Baselines: −market value scores −0.220 / −0.145 / −0.044 at 30 / 60 / 90 days (expensive assets held
value better in a KTC market that drifted −2.9% / −6.2% / −8.5%). Served TV alone scores
+0.138 / +0.063 / +0.028.

| h | cand | Spearman | partial (given market rank) | offense | IDP | hit rate | long−short |
|---|---|---|---|---|---|---|---|
| 30 | C0 | **−0.208** | −0.067 | −0.350 | 0.028 | 0.476 | −0.007 |
| 30 | C2 | −0.122 | −0.031 | −0.242 | 0.074 | 0.426 | −0.013 |
| 30 | C3 | −0.119 | −0.039 | −0.222 | 0.051 | 0.424 | −0.000 |
| 30 | C5 | −0.070 | **+0.013** | −0.153 | 0.043 | 0.400 | −0.029 |
| 60 | C0 | −0.158 | −0.077 | −0.228 | 0.022 | 0.475 | −0.049 |
| 60 | C2 | −0.101 | −0.043 | −0.153 | 0.061 | 0.421 | −0.015 |
| 60 | C5 | −0.052 | +0.002 | −0.110 | 0.059 | 0.440 | −0.010 |
| 90 | C0 | −0.045 | −0.019 | −0.084 | 0.078 | 0.489 | −0.004 |
| 90 | C2 | −0.012 | +0.008 | −0.023 | 0.074 | 0.492 | +0.013 |
| 90 | C3 | +0.021 | +0.041 | −0.014 | 0.105 | 0.509 | +0.049 |
| 90 | C5 | +0.012 | +0.030 | −0.007 | 0.059 | 0.480 | +0.057 |

C1 and C4 are in `study_report.json`. C4 has the same score as C0, so it has the same correlations
and worse label metrics.

Paired bootstrap, 95% CIs:

| h | C0 Spearman | C2 − C0 Spearman | C5 − C0 Spearman | C0 partial | C2 − C0 partial | C5 − C0 partial |
|---|---|---|---|---|---|---|
| 30 | [−0.282, −0.138] | [+0.046, +0.125] | [+0.062, +0.215] | [−0.137, +0.001] | [+0.006, +0.067] | [−0.005, +0.163] |
| 60 | [−0.227, −0.084] | [+0.019, +0.098] | [+0.031, +0.182] | [−0.149, −0.003] | [+0.002, +0.067] | [+0.000, +0.159] |
| 90 | [−0.119, +0.030] | [−0.005, +0.071] | [−0.013, +0.125] | [−0.087, +0.056] | [−0.003, +0.056] | [−0.029, +0.123] |

**Reading.**

1. The incumbent's continuous score is significantly anti-predictive of relative market movement at
   30 and 60 days. Most of that is its price-tier loading.
2. C2 and C5 are significantly less anti-predictive than C0 at 30 and 60 days.
3. No candidate's own interval excludes zero on the positive side. Hit rates are at or below 0.5,
   and the complete-case results agree in sign.

**Positive predictive skill is not demonstrated for any option, the incumbent included.**

**Why this evaluation is insufficient, precisely.**

* One signal date, so one cross-section. Players share common shocks (position-wide moves, the
  season start), so the effective sample is smaller than 676.
* The horizon is ≤ 95 days. Spec T6 asks for market value 12 months later and expects about 6 months
  of snapshots before T6 is testable.
* The fundamentals are 100% proxy, single source and one season back. Market movement tests only
  the market half of T6. The football half (spec T3/T4: realized VOR and finishes) needs realized
  2026 fantasy points under dynasty_main scoring, which are not committed (nflverse weekly data is
  box-local).
* The served offense anchor is now KTC Market (`ktcCrowdTradesSfTep`). The outcome deliberately
  stays on `ktcSfTep` to match what this signal saw.

**Data that would enable a decision:**

1. A persisted, point-in-time BDVM board history: inputs, gap and every candidate label, daily or
   at least weekly. Today the audit's 2026-08-04 run is the only frozen board.
2. At least 6 signal dates spaced at least 14 days apart, with 90- and 180-day outcomes (12-month
   outcomes for the full T6).
3. Real projection sources (Clay / IDP Show) in the frozen snapshots, and the W13-F001 re-audit.
4. Realized-points snapshots for the football half.

## 10. Confidence, calibration and uncertainty implications

* BDVM labels are not calibrated probabilities (spec §12.3 policy), and none of the candidates makes
  them so. All 676 rows have `confidenceLabel: low`. The incumbent ladder ignores that.
* C5 is the only candidate whose actionable rate is set by the model's own stated uncertainty rather
  than by fixed points. It abstains where the band is wide, which includes most thin-sample rows. The
  band is a documented approximation ("perfectly correlated seasons", `engine.py::_range`), wider
  than independent draws, so C5 errs toward abstaining.
* C5 cannot issue a SELL on a top asset whose mapped ceiling clamps at the board maximum, because the
  market cannot exceed 9999. This is acceptable because BDVM's own band then contains the price, but
  it should be stated on any surface.
* C2 and C5 express the gap in market units at BDVM's rank, so the gap stops depending on γ and the
  9800 anchor.
* The board-level shape disagreement (γ\* vs γ, or the curve-shape median) should be surfaced as one
  statistic. That is the second half of the audit's `requiredRepair`.

## 11. Downstream consumer effects (if a candidate were ever activated)

| consumer | reads | C2 | C5 | C1 (rejected) |
|---|---|---|---|---|
| `/bdvm` board (`frontend/lib/bdvm.js` rows) | `market.gap`, `signal`, `signal.reason` | gap re-based to market units at BDVM rank; labels change on 441 rows | gap as C2; three-state labels on 640 changed rows (STRONG_* tones unused) | gap and labels change |
| `/rankings` and `/draft` Fund-gap column (`buildBdvmIndex`) | `gap`, `marketValue`, `fundamental`, `signal`, `anyProxy` | tooltip semantics must change; the `fundamental` column (served TV) is unchanged | same | the fundamental column changes too |
| BDVM signal alerts (`src/api/bdvm_signal_alerts.py`, actionable = SB/B/S/SS) | label transitions | **216 rows** move into a different actionable state → alert flood unless the alert state is re-seeded (namespace bump) | **139 rows** | 314 rows |
| W12-F006 cross-detector precedence (owner decision A) | BDVM alerts as a secondary detector | unchanged mechanism; fewer conflicting directions expected | same | — |
| Signal reconciler (`src/signals/reconciler.py`, `bdvm_market_signal`) | label direction | directions change | same | same |
| Trade-eval panel (`POST /api/bdvm/trade-eval`, `BdvmTradePanel`) | CES package value on `tradeValue` | **unchanged** | **unchanged** | changes |
| Roster capitals, double-positive trade scan | `tradeValue` | unchanged | unchanged | changes |
| `marketAdjusted` / `tradeClearing` λ-blends | `fund_balanced`, market | unchanged. They mix the same two scales, which is a related follow-up and out of scope here | unchanged | changes |
| Canonical board `rankDerivedValue` | — | never touched | never touched | never touched |

## 12. Rollback

Nothing is activated, so there is nothing to roll back. The study is removable by deleting
`scripts/research/bdvm_saturation_study.py`, its test and the evidence directory. A future shadow
would be a separate box-local job and store, deletable without touching served paths. A future
activation (a separate owner decision) would need: a flag-gated signal method
(`RISKIT_FEATURE_…=0` + restart), a new param-set id so payloads say which method produced a label,
and an alert-state namespace bump in both directions so neither switching on nor rolling back floods
users.

## 13. Recommendation

1. **Activate nothing.** No candidate has demonstrated predictive skill. The incumbent is
   demonstrably anti-predictive at 30 and 60 days on this one cross-section, but that alone does not
   prove any replacement is right.
2. **Reject C1** (it overshoots, and its blast radius is every BDVM trade value) **and C4** (forced
   balance, wrong-direction signals).
3. **Send C5 (C2's pooled map plus BDVM's own p20/p85 band) to an owner-approved shadow evaluation,
   with C2 as the ablation and C0 as control.** Rationale, not balance:
   * the C2 map removes exactly the component (§3.1) that alone produces 675 of 676 STRONG_SELLs;
   * it keeps BDVM's ordering, served trade values and cross-position / cross-market format
     disagreement;
   * C5 bases its thresholds on the model's stated uncertainty instead of absolute points, and
     abstains on 95 of 115 thin-sample rows;
   * it is the least anti-predictive option at every horizon.

   Preregistered success criteria for any later activation request:
   * partial Spearman (given market rank) > 0, with a 95% CI excluding 0, pooled over at least 6
     signal dates at 90 and 180 days;
   * actionable hit rate > 0.5, with a CI excluding 0.5;
   * no position group's hit rate below 0.45;
   * measured after the W13-F001 re-audit and with real projection sources in the snapshots.
4. **Fix the inputs before reading positions.** W13-F001, the proxy shrinkage target for thin samples
   (positional mean of starters), and stale injury seasons are fundamental-input defects. No signal
   layer can correct them.

## 14. Owner decisions requested

* **Decision A (this proposal).** Approve or decline a **shadow** evaluation of C5, with C2 and C0
  computed beside it. Never served, never alerted. It needs a box-local, point-in-time BDVM board
  history and the preregistered criteria in §13, and would come back to the owner before any
  activation. It requires an implementation unit in `docs/EXECUTION_PLAN.md`.
* **Decision B (independent of A, owner-only because it changes served output).** What the currently
  served incumbent labels should do while W13-F003 is open:
  * (B1) status quo;
  * (B2) add a board-level saturation disclosure on `/bdvm` and in the Fund-gap tooltips;
  * (B3) hold the actionable labels (show the gap only) and pause BDVM signal alerts until a candidate
    passes.

  The evidence (§3.1 ρ = −0.75 price-tier loading; §9 anti-predictive at 30 and 60 days) supports at
  least B2. B3 is defensible. I have implemented neither.

## 15. Limitations

* One frozen, proxy-only, preseason board from the audit container. It was built from one season of
  nflverse data, while production uses three seasons plus Clay / IDP Show where available. Whether
  **today's** board saturates cannot be measured offline. The curve-shape cause depends only on the
  two value distributions (top-only anchor, γ > 1, replacement-origin DV against a floored market),
  so the cause should survive better projections, but the magnitude will move.
* Outcomes are market prices, not football results. Censoring at the top-N floor understates the
  declines of the cheapest assets.
* KTC and IDPTC values were joined by canonical name normalization. 18–21 KTC and 4–6 IDPTC rows were
  absent at each horizon and treated as censored.
* `config/bdvm/params_v1.json` may have changed outside the market section since the audit's
  `params_v1:01af672b2aff`. The thresholds and scale constants the study reads are unchanged.
* C5's band inherits the engine's documented range approximation.

## 16. Reproduction

```bash
python scripts/research/bdvm_saturation_study.py \
  --out docs/valuation/evidence/w13-f003-bdvm-saturation-2026-11-07/study_report.json \
  --players-csv docs/valuation/evidence/w13-f003-bdvm-saturation-2026-11-07/players.csv
python -m pytest tests/scripts/test_bdvm_saturation_study.py tests/bdvm/test_audit_w13_f003_regression.py -q
```

Deterministic: two runs are byte-identical (bootstrap seed 20261107 + horizon days). Input hashes are
recorded in `study_report.json`. Evidence: sha256 `820e3cdc0232bf34b0fdd622756bc4431df3575c76fa0b8af53af49bfb9f4a3e`.
Params: `df89c0c4d9b38e69d9165bb90d9c095eb35ef094cf80b67fd22998b2426d5600`. Outcome archives:
`b99386d3…22bf03` (+30), `11247102…9e` (+60), `207c5b3d…22b` (+90).

Engineering applicability check:
* APPLY_NOW: independent oracles, pinned fixtures and input provenance (done).
* ALREADY_COVERED: the W13-F003 strict-xfail regression.
* DEFERRED_BY_AUTHORITY: persisted BDVM board history, any typed contract or label change, alert
  re-seeding.
