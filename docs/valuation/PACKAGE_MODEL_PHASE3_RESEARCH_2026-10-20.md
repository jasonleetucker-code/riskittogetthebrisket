# Package Value Adjustment — Phase 3: the production market ledger, LP_150, and the value-level question (2026-10-20)

**Status: RESEARCH — complete, pending only the optional prospective re-run (§9.4).**

The preregistered Phase 3 production run (`scripts/package_model_phase3_research.py --box`, pinned commit
`d7a881bc`, run by the owner on 2026-10-20) is in `evidence/package_model_phase3_2026-10-20/production_phase3_run_2026-10-20.json`:
- 18,690 graded trades from 11,565 leagues;
- the read-only guard refused 0 writes;
- aggregates only.

- Nothing is promoted or changed in production. `geom_q078_v1` (q = 0.78) stays the authoritative package
  model.
- No canonical value, source weight, dispatch, config, fairness band, Trade Finder, Trade History, War Room,
  Second Opinions or Trade Advisor behaviour was touched.

Directive: `docs/owner/HYBRID_VALUE_ADJUSTMENT_RESEARCH_PHASE3_2026-10-20.md`.

Earlier records, preserved unchanged:
- Phase 1: `PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md`.
- Phase 2: `PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md`, plus its preregistration.

Evidence: `evidence/package_model_phase3_2026-10-20/`.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Contents

1. Validation of the production report
2. What 18,031 trades say: replication of Phase 2
3. What these results do and do not demonstrate
4. LP_150 and the stronger-consolidation family
5. Data biases: IDP, picks, source, period, league dependence
6. Value curve or package formula?
7. Mandatory properties
8. Decision replay
9. Challenger status and the preregistered protocol
10. Owner report: the fifteen questions
11. Recommendation
12. Verification and outstanding work

## 1. Validation of the production report

**The file.** It is your production run, committed byte-for-byte as
`evidence/package_model_phase3_2026-10-20/production_ledger_run_2026-10-20.json`.
- sha256 `9a7c55a6…f431`.
- It passes `assert_aggregate_only`.
- It contains no 9+-digit run and no `player:` / `mpick:` / `utrade:` / `@` string.

| # | check | result |
|---|---|---|
| 1 | complete and structurally valid | **Pass.** Every count reconciles. 28,715 groups = Σ dedupe states = Σ team counts = Σ topologies. 28,715 = 18,031 graded + 10,684 excluded, where the exclusion reasons sum exactly. The bins sum to 18,031. The earlier-60% period has exactly int(0.6 × 18,031) = 10,818 trades. The by-date counts sum to 18,031. |
| 2 | the evaluated script is the intended one | **Pass.** `researchScript` names `package_model_phase2_research.py --market-ledger-only`. The output's key structure is identical to my rehearsal of the pinned commit `d1c9e5e9`; the only differences are data-dependent (sections whose size gate was or was not met). Your command verified the sha256 of all three scripts before running. The report does not carry the script hash itself, so this check rests on the schema plus your checksum step. |
| 3 | every trade priced on a board strictly before it | **Pass, by construction.** `price_market_groups` takes the latest archived board with `board_date < trade_date`. `residual_eligible` then refuses any board after the trade (`board_after_trade_lookahead`) or with an unknown date. 544 trades had no such board within 7 days and were excluded. |
| 4 | 7-day maximum board age | **Pass.** It is enforced twice: in board selection (`(td − b).days <= 7`) and in `residual_eligible` (`board_older_than_max_lag`). |
| 5 | unpriced assets excluded, never zero | **Pass.** Pricing is all-or-nothing per trade. 1,371 trades with any unpriced asset were excluded (15,889 on the KTC-market basis, where IDP and many picks have no KTC price). `BoardIndex.values` returns no key for a missing value, never 0. |
| 6 | duplicates and ambiguous cross-source records | **Pass.** Duplicate observations are merged into one group: 6 `CONFIRMED_DUPLICATE` and 36 `PROBABLE_DUPLICATE` groups each count once. `POSSIBLE_OVERLAP` (29) and `UNRESOLVED` are excluded; 18 of the 29 overlaps were excluded for that reason and the rest for an earlier one. |
| 7 | non-superflex and unknown-QB trades excluded | **Pass.** 6,789 trades were excluded as `board_basis_superflex_mismatch_or_unknown`. Eligibility requires `superflex is True`, so unknown fails closed. |
| 8 | league concentration | **Pass.** 11,188 leagues; the largest is 0.2% of trades and the top five are 0.6%. With at most 3 trades per league (n = 16,098) every bin moves by ≤ 0.004. |
| 9 | identical inputs and population across models | **Pass.** One row set is priced once, and every model is scored on the same rows. The exception is the KTC-market-basis control, a different and smaller population (3,513 trades, offense and picks only), which is labelled as such. |
| 10 | no exposed private identifiers | **Pass.** The aggregate check passes, and a manual scan finds no league, user, roster, transaction or asset ids. The only hashes are the public code commit and the ledger's build time. |

**The 270 refused network calls.** They come from one caller, `data_contract._resolve_league_context`. That
function fetches Sleeper `total_rosters` and `scoring_settings.bonus_rec_te` for the registry league, three
times per board build (90 boards × 3 = 270).
- **What the fallback does.** Refused, it falls back to `{roster_count: 12, bonus_rec_te: 0.0}`. The live
  answer today is `{12, 0.0}`, fetched at 2026-10-20. With `bonus_rec_te = 0` the TE-premium branch takes its
  default path either way, and the rookie-pick anchor uses 12 either way. So the code path is identical.
- **Full audit.** The new `scripts/package_model_offline_parity_audit.py` rebuilt **every archived board from
  2026-07-14 to 2026-10-18** (138 boards over 96 dates, a superset of the 90 used), with the fallback context
  and with the live context. **0 of 136,558 canonical values changed** (`offline_parity_audit.json`).
- **Power check.** Pinning a *different* context (the 2025 season-league: 10 rosters, `bonus_rec_te` 0.35)
  changes 8,370 values, almost all pick rows, by up to 721 points. So the audit can see a difference when one
  exists.
- **Conclusion.** The earlier 30-board check is superseded by this full one. The guard's refusals did not
  change any value, league context or conclusion.
- **One caveat, inherent to the design.** Boards are rebuilt from archived raw source data with **today's**
  pipeline code (`4475df47`), not the code that served them at the time. That is right for comparing package
  models on one consistent value scale. It means "the board at the time" is "today's methodology applied to
  that day's source inputs".

## 2. What 18,031 trades say: replication of Phase 2

Mean signed residual. The fewer-pieces side comes first, so negative means the market gave the consolidating
side more credit than the model does. The bracket is the bootstrap 95% CI. J is the worst unequal bin.

| model | 1-for-2/3 (n 5,887) | ordinary (n 3,389) | deep 5+ (n 1,233) | J | equal (n 7,522) | J earlier 60% | J later 40% |
|---|---|---|---|---|---|---|---|
| RAW | −0.460 [−0.465, −0.454] | −0.302 [−0.309, −0.294] | −0.441 [−0.457, −0.425] | 0.460 | +0.014 | 0.461 | 0.457 |
| **GEOM_78** | **−0.301** [−0.306, −0.296] | **−0.135** [−0.140, −0.130] | **−0.127** [−0.135, −0.119] | **0.301** | +0.013 | 0.303 | 0.298 |
| KTC | −0.280 [−0.288, −0.271] | −0.133 [−0.142, −0.124] | −0.140 [−0.153, −0.126] | 0.280 | +0.015 | 0.286 | 0.270 |
| BLEND G75/K25 | −0.295 | −0.133 | −0.129 | 0.295 | +0.014 | 0.298 | 0.290 |
| BLEND G50/K50 | −0.289 [−0.296, −0.283] | −0.133 [−0.140, −0.126] | −0.132 [−0.142, −0.122] | 0.289 | +0.014 | 0.294 | 0.283 |
| BLEND G25/K75 | −0.284 | −0.133 | −0.135 | 0.284 | +0.014 | 0.289 | 0.276 |
| FGEOM_70_20 | −0.289 | −0.130 | −0.132 | 0.289 | +0.013 | 0.292 | 0.286 |
| HYBRID_50 | −0.301 | −0.182 | −0.251 | 0.301 | +0.013 | 0.303 | 0.298 |
| GEOM_85 | −0.348 | −0.179 | −0.196 | 0.348 | +0.013 | 0.350 | 0.345 |
| EFD_78 | −0.288 | −0.167 | −0.221 | 0.288 | +0.013 | 0.290 | 0.286 |
| EFD_115 | −0.322 | −0.192 | −0.260 | 0.322 | +0.013 | 0.324 | 0.320 |
| EFD_130 | −0.236 | −0.129 | −0.165 | 0.236 | +0.013 | 0.238 | 0.234 |
| **LP_150** | **−0.162** [−0.166, −0.158] | **−0.077** [−0.081, −0.073] | **−0.094** [−0.100, −0.089] | **0.162** | +0.013 | 0.164 | 0.159 |

These are your seven headline numbers, verified to four decimals. The CIs above treat trades as independent;
league-clustered intervals are part of the box run (§9).

**Phase 2 sample (1,121 reconstructed trades) against the production ledger (18,031):**

| finding | Phase 2 sample | production ledger | status |
|---|---|---|---|
| every model leaves the consolidating side short in every unequal bin | yes | yes, all 13 models, every bin, both periods | **replicated, now very precise** |
| GEOM_78 deep bin | −0.142 [−0.184, −0.104] | −0.127 [−0.135, −0.119] | **replicated** (CI width 0.08 → 0.016) |
| depth-friendlier models are further from the market (EFD_78, HYBRID_50, GEOM_85) | yes | yes, in every split | **replicated** |
| KTC and the blends ≈ GEOM_78 on calibration | yes | yes (J 0.280–0.295 vs 0.301) | **replicated**, and they still fail monotonicity (§7) |
| LP_150 closest to 0 | yes (−0.171 / −0.087 / −0.101) | yes (−0.162 / −0.077 / −0.094) | **replicated** |
| the shortfall persists on KTC's own value scale | 212 trades | 3,513 trades: GEOM_78 −0.289 / −0.118 / −0.102, LP_150 −0.153 / −0.070 / −0.078 | **strengthened** |
| the shortfall grows as value falls | single-side binning | yes, with noise-balanced binning: GEOM_78 1-for-N −0.35 at level 2,000–3,999 vs −0.18 at 6,000–7,999 (§6.1) | **replicated, and explained (§6)** |
| earlier 60% vs later 40% | consistent | J moves ≤ 0.016 for every model | **strengthened** |
| one league or source dominating | not tested at scale | no: largest league 0.2%, league cap leaves bins within 0.004, both sources agree | **new, strong** |

## 3. What these results do and do not demonstrate

**Demonstrated, to high precision.** Real dynasty trades clear with the side that receives *fewer* pieces
giving up more canonical value than any of our package models says is fair:
- about 30% of a side in 1-for-2/1-for-3 trades under GEOM_78;
- about 13% in ordinary and deep trades.

That holds:
- in both independent source families: KTC trade database −0.297 / −0.133 / −0.128, Sharp Sleeper
  −0.313 / −0.141 / −0.123;
- in both time regimes;
- across TEP levels;
- with and without picks;
- in IDP-format leagues;
- on KTC's own value scale;
- with leagues capped at 3 trades each.

**Not demonstrated: that a model fitting these trades better gives better advice.** Completed trades are a
selected sample: rejected offers are invisible, and a trade happens because two managers disagreed in
opposite directions. Five confounds stay in play, and none of them is a package-formula effect:
- **Market inefficiency and conventional wisdom.** "The side getting the best player wins" is a widely held
  heuristic. If managers over-pay for stars, a model that copies them copies the mistake.
- **Value-scale error.** If low-value assets run rich on our scale, every depth side looks bigger than the
  market treats it. LP_p is *mathematically identical* to "value the assets on a v^p curve, then add them up",
  so a better LP fit cannot, on its own, tell a package effect from a curve effect. §6 separates them.
- **Roster and lineup economics.** Receiving more pieces costs roster spots and rarely adds starts. Those are
  team-context effects our trade engine prices elsewhere (roster capacity / forced drops, lineup). Folding them
  into the package formula would count them twice.
- **Picks.** 80.3% of graded trades (14,474) and 96% of deep trades include a pick. Player-only trades show a
  smaller shortfall under GEOM_78 (−0.247 / −0.098 / −0.087), and under KTC smaller still (−0.181 in
  1-for-2/3). How picks are valued matters (§5B).
- **Source circularity.** KTC Trades is a voting source in the canonical board, built from KTC trade-database
  trades. Those KTC uses in its value-from-trades flag (`vft` = True, 11,177) do sit closer to 0 under GEOM_78
  (J 0.284) than those it did not use (J 0.370). But the Sharp Sleeper lane, which no voting source consumes,
  shows the same shortfall (J 0.313). Circularity does not create the shortfall. If anything it shrinks it
  slightly, and KTC's own filter on lopsided trades is the likelier cause.

## 4. LP_150 and the stronger-consolidation family

### 4.1 What LP_150 is

`U = (Σ v^1.5)^(2/3)`.
- **Properties.** It is monotone, positively homogeneous, order-invariant and anti-symmetric. 1-for-1 is raw,
  and by Minkowski's inequality an added asset adds at most its own value. It passes every mandatory property
  (§7).
- **Three facts drive its behaviour:**
  - **Value-aware discount.** The k-th piece's weight depends on its size relative to the others, not its rank.
    A piece 10% of the star's size adds about 2% of its own value.
  - **Two equal pieces are worth 2^(2/3) = 1.587×** one piece, against 1.78× under GEOM_78. A stronger premium
    for small depth.
  - **n equal pieces are worth n^(2/3)× one piece, and that grows without limit.** Under GEOM_78 it saturates at
    1/(1 − 0.78) = 4.55×. For **ten equal pieces LP_150 gives 4.64× against GEOM_78's 3.98×**. LP_150 is *more*
    generous than the incumbent to very deep *even* packages, and harsher to small and uneven ones.

**Consolidation premium, measured** (`local.json → B_consolidationPremium`). Raw multiple an even n-piece
package needs to equal one 9,000 star, and the weight a model credits a second piece by its size relative to the
first:

| model | n=2 | n=3 | n=4 | n=6 | n=10 | 2nd-piece weight at relative size 0.1 / 0.3 / 0.5 / 0.8 / 1.0 |
|---|---|---|---|---|---|---|
| **GEOM_78** | 1.12 | 1.26 | 1.40 | 1.70 | 2.40 | 0.78 at every size (rank only) |
| LP_150 | 1.26 | 1.44 | 1.59 | 1.82 | 2.15 | .21 / .36 / .45 / .54 / .59 |
| LP_175 | 1.35 | 1.60 | 1.81 | 2.16 | 2.68 | .10 / .23 / .32 / .43 / .49 |
| LP_200 | 1.41 | 1.73 | 2.00 | 2.45 | 3.16 | — |
| GP_078_150 | 1.36 | 1.68 | 1.98 | 2.59 | 3.86 | — |
| KTC | 1.38 | 1.52 | 1.95 | 2.22 | 2.50 | not monotone |
| VG_078_2000 (diagnostic) | 1.32 | 1.64 | 1.98 | 2.66 | 4.09 | 0 / .20 / .43 / .56 / .61 |

LP_150 differs from GEOM_78 in two ways, and only one of them is an improvement.

- **The improvement: it discounts by piece *size*.** GEOM_78 credits the k-th piece q^(k−1) of its value whether
  it is a starter or filler. LP_150 credits a piece 10% the star's size at 21% of its value, against GEOM's 78%.
  That is the clearest qualitative gain in this study (§8). The diagnostic VG model shares it.
- **The cost: it also charges much more for genuine starters.** Two equal pieces must total 1.26× a 9,000 star
  under LP_150, against 1.12× under GEOM_78 and 1.35× under LP_175. LP_175 and stronger add more of this cost and
  nothing new (§8).

### 4.2 The family: how strong a consolidation premium do the trades "want"?

Exploratory, on the research container's own sample (1,078 trades; mostly Sharp Sleeper, overlapping the box
ledger). This is not production evidence:
- the pooled calibration loss J **keeps improving as consolidation strengthens**, all the way past LP_150 to
  LP_250 / LP_300 and GP_090_250 (J ≈ 0.02–0.03);
- for scale: LP_250 values two equal pieces at **1.32×** one piece, and ten 3,000-value starters at about 7,500,
  below a single 9,000 star.

The production Phase 3 run (18,690 trades) shows the same shape:
- J falls from 0.161 (LP_150) through 0.103 (LP_175) and 0.064 (LP_200) to its minimum, 0.018, at LP_250;
- it then rises again (LP_300 0.036, LP_400 0.053).

A target that rewards ever more extreme superstar preference is a warning sign. The calibration target
measures where trades **clear**, and §6 shows a large part of that is a value-*level* effect that no
homogeneous formula can represent. The preregistered box run therefore selects a candidate **twice** (§9):
- pooled (S1);
- within trades whose noise-balanced value level is ≥ 6,000 (S2), where a level effect is smallest.

It also flags any candidate that over-credits consolidation among elite trades (C6).

## 5. Data biases

**A. IDP.**
- **Format.** 276 graded trades (1.5%) come from IDP-format leagues: 85 / 57 / 14 / 120 across the four bins.
  That is only 14 deep trades. GEOM_78 there is −0.338 / −0.157 / −0.139, with wide CIs.
- **Assets (Phase 3 run).** 138 of 18,690 trades contain an IDP asset: 133 mixed offense/IDP and 5 IDP-only.
  - **By position:** DB 98, LB 41, DL 20.
  - **Deep trades:** 12, all mixed.
  - **Direction:** the same as offense. Mixed trades under GEOM_78 are −0.42 / −0.19 / −0.10, and under the
    level diagnostic VG_085_2000 −0.08 / −0.05 / −0.03. With n of 12–39 per bin, that is direction only.
- **Read:** the market evidence is overwhelmingly about offense and picks. **No package-model conclusion
  extends to IDP-heavy trades in our league without qualification.**

**B. Picks.**
- 14,474 graded trades include a pick (80.3%) and 3,557 are player-only. In the deep bin 1,187 of 1,233 include
  a pick, so only 46 deep trades are all players.
- GEOM_78 player-only: −0.247 / −0.098 / −0.087. With picks: −0.312 / −0.139 / −0.128.
- So picks deepen the shortfall, but do not create it.
- **Phase 3 run (18,690).**

  | slice | n | GEOM_78 (1-for-N / ordinary / deep) | VG_085_2000 |
  |---|---:|---|---|
  | player-only | 3,683 | −0.25 / −0.10 / −0.09 | +0.02 / +0.01 / +0.01 |
  | mixed | 14,926 | −0.31 / −0.14 / −0.13 | −0.01 / −0.00 / −0.00 |
  | pick-only | 81 | −0.33 / −0.24 / −0.38 | too few |
  | 2+ picks | 7,443 | −0.32 / −0.15 / −0.13 | −0.01 / −0.01 / −0.00 |
  | deep, all players | 80 | deep −0.08 | +0.02 |
  | deep, pick-dominated | 660 | deep −0.15 | −0.01 |

  By the share of the depth side that is picks, GEOM_78's 1-for-N shortfall runs from −0.25 (0%) to −0.33
  (>75%), while VG stays between +0.02 and −0.03.
- **Read:** picks are not mispriced as a class. Picks deepen the shortfall only because pick-heavy packages are
  made of lower-value pieces, and the same value-level rule (§6) explains them.

**C. Source.**

| source | trades | GEOM_78 (1vN / ordinary / deep) |
|---|---:|---|
| KTC trade database | 13,124 | −0.297 / −0.133 / −0.128 |
| Sharp Sleeper | 4,879 | −0.313 / −0.141 / −0.123 |
| own league | 27 | too few to report |
| overlap of both | 1 | — |

- Same picture in both sources.
- KTC vendor flag: used in VFT 11,177, not used 1,948, unknown (Sharp) 4,906. See §3.
- Source-separated agreement is **robustness** evidence, not independent validation: both sources are priced
  on boards that include KTC.

**D. Period.** The weekly counts run 263–689 per week through 2026-09-07, then 27 and 7, then 2,523, 5,192 and
5,406. Two causes:
- **The October jump is a collector deployment, not a market change.** The KTC trade-database collector
  (`dynasty-ktc-trades`, #1586, merged 2026-10-01) was not installed on the box before about 2026-10-01
  (`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §36.1). It reads a rolling ~200-row window every 30 minutes
  and has no backfill.
- **The mid-September hole is most likely an in-season crawl gap in the Sleeper lane** (plausible, not
  confirmed on the box):
  - once the NFL week passed 2, `_weeks_to_fetch` reads only the current week's transactions;
  - with 600 calls per run across thousands of leagues, most in-season week buckets are never revisited
    (`src/intel/crawler.py`, `src/sharp/transactions.py`).
- **So the population before 2026-09-14 is almost all Sharp Sleeper (offseason and preseason) and the
  population from 2026-09-28 is mostly KTC (in season).**
- The production report's chronological split and source split both agree.
- In the Phase 3 run the week-balanced means, where every week counts equally, are −0.31 / −0.14 / −0.12 for
  GEOM_78, essentially the pooled values.
- The four source × regime cells with data all agree (KTC from 09-28: −0.30 / −0.13 / −0.13; Sharp before
  09-28: −0.31 / −0.14 / −0.12).
- **No single ingestion regime decides anything.**

**E. League dependence.**
- The Phase 3 run has league-clustered bootstrap intervals throughout: leagues are resampled, 400 reps.
- They are about as narrow as the trade-level ones. For example, GEOM_78's full-population 1-for-N residual is
  −0.300 [−0.305, −0.296], clustered.
- With 11,565 leagues and the largest at 0.2% of trades, league dependence does not move any conclusion.

## 6. Value curve or package formula?

**The question.** Are low-value assets priced too high by the canonical scale, or does the package formula
discount them wrongly? A homogeneous package model gives the same *relative* answer at every value level. So:
- if the shortfall changes with value *level*, that part is not a package effect;
- if it is constant in relative terms, it is.

**Two corrections to Phase 2's method:**
- Phase 2 binned by the consolidated asset's own value. That selects on that asset's measurement error, a
  regression-to-the-mean artifact that steepens any gradient. Phase 3 bins by a **noise-balanced level**: the
  mean of both sides' best asset.
- Phase 3 adds a **joint decomposition** `VG_q_c = Σ q^i max(0, v_i − c)`:
  - q is a package-shape effect;
  - c is a fixed per-piece level, i.e. what a received asset must be worth before it adds anything.

  `VG` with c > 0 is not homogeneous, so it can never be a package formula. Its job is to say how much of the
  residual is shape and how much is level.

**Exploratory, container sample (1,078 trades).**

Noise-balanced level tiers. The gradient survives the noise correction:

| level (mean of both best assets) | GEOM_78 (1vN / ordinary / deep) | LP_150 |
|---|---|---|
| 2,000–3,999 (n 475) | −0.364 / −0.175 / −0.220 | −0.222 / −0.121 / −0.177 |
| 4,000–5,999 (n 332) | −0.264 / −0.147 / −0.151 | −0.126 / −0.087 / −0.117 |
| 6,000–7,999 (n 170) | −0.221 / −0.093 / −0.102 | −0.084 / −0.041 / −0.070 |

Joint decomposition:
- **Best fit: q = 0.78–0.85 with c ≈ 2,000 (J 0.012–0.016).** That is better than *any* homogeneous model,
  including LP_250 (0.029).
- For every q from 0.50 to 1.00 the best c lies between 1,250 and 2,500.
- The c = 0 column ("shape only") is far worse at every q.

Implied market weight of the second piece in a 1-for-2 trade, `(a − b1) / b2`. GEOM_78 implies 0.78:

| second piece's absolute size | median implied weight |
|---|---:|
| 1,000–1,999 | 0.07 |
| 2,000–3,499 | 0.16 |
| 3,500–4,999 | 0.32 |

The credit rises with the piece's *absolute* size.

**What that would mean if the box run confirms it** (preregistered rule R1):
- The market prices trades as if every received asset first had to clear a fixed level of about 2,000 points.
  About 2,000 is roughly the end of a 12-team superflex starter pool: `dynasty_main`'s all-in starter line is
  rank 240, value 2,341, in the FAAB engine.
- Above that level the market applies a package shape **close to the incumbent's q = 0.78**.
- That is a *replacement-level / value-curve* effect, not a package-shape effect.
- It belongs where the trade engine already models replacement level and roster spots: team context, roster
  capacity and forced drops, and lineup value. If it belongs anywhere else, it is a valuation-owner question
  about how the canonical curve treats sub-replacement assets.
- Putting it into the package formula would distort elite trades (homogeneous LP must over-reach to fit the
  low levels) and **double-count** what team context already charges.

Phase 2 found the residual does *not* track roster size. The box run tests whether c tracks **league size**
(R3).

### 6.1 Production results (Phase 3 run, 18,690 trades)

**1. The level gradient is real, and homogeneous formulas cannot remove it.**

Mean signed residual (1-for-N / ordinary / deep) by noise-balanced level, the mean of both sides' best asset:

| level | n | GEOM_78 | LP_150 | GP_078_150 | LP_250 | **VG_085_2000** |
|---|---:|---|---|---|---|---|
| below 2,000 | 837 | −0.49 | −0.33 | −0.26 | −0.17 | **−0.01** |
| 2,000–3,999 | 7,445 | −0.35 / −0.18 / −0.25 | −0.21 / −0.12 / −0.19 | −0.15 / −0.06 / −0.08 | −0.06 / −0.02 / −0.04 | **+0.01 / +0.02 / −0.00** |
| 4,000–5,999 | 6,646 | −0.27 / −0.14 / −0.14 | −0.14 / −0.08 / −0.10 | −0.08 / −0.03 / −0.03 | +0.00 / +0.00 / −0.00 | **−0.03 / −0.01 / +0.00** |
| 6,000–7,999 | 3,160 | −0.18 / −0.10 / −0.11 | −0.05 / −0.04 / −0.08 | +0.00 / +0.01 / +0.01 | **+0.08 / +0.05 / +0.04** | **+0.01 / +0.01 / +0.00** |
| 8,000+ | 602 | −0.23 / −0.13 / −0.10 | −0.09 / −0.07 / −0.08 | −0.04 / −0.02 / −0.01 | +0.04 / +0.02 / +0.01 | **−0.07 / −0.05 / −0.04** |

- Every homogeneous formula shows the same trend with level. The only way to flatten it is to make the formula
  strong enough to over-credit elite trades, which is what LP_250 does at 6,000–7,999.
- A single fixed level does not have that problem. VG_085_2000 sits within ±0.03 of zero at every level up to
  8,000. Above 8,000 it is −0.07 / −0.05 / −0.04, against −0.23 / −0.13 / −0.10 for GEOM_78.

**2. The joint decomposition gives one answer everywhere.**

`VG_q_c = Σ q^i max(0, v_i − c)`.

| population | best fit | J | the c = 0 column at the same q (shape only) | best homogeneous model |
|---|---|---|---|---|
| discovery (9,306) | q 0.85, c 2,000 | 0.009 | 0.350 | LP_250, 0.019 |
| **confirmation (9,384, held out)** | **q 0.85, c 2,000** | **0.006** | 0.344 | LP_250, 0.018 |
| elite level ≥ 6,000 (discovery) | q 0.85, c 2,000 | 0.006 | 0.241 | GP_078_150, 0.011 |
| leagues ≤ 10 / 11–12 / 13–14 teams | c 2,000 / 2,000 / 2,000 (q 0.80 / 0.85 / 0.75) | 0.007 / 0.005 / 0.006 | — | — |
| KTC trade database / Sharp Sleeper | c 2,000 / 2,000 | 0.005 / 0.010 | — | — |
| player-only trades | q 0.85, c 1,750 | 0.008 | — | — |
| **KTC's own value scale** (3,639) | c 2,000–2,500 (q 0.75 J 0.011; q 1.00 J 0.011) | 0.011 | — | LP_250, 0.013 |

At the incumbent's q = 0.78, the best level is c = 2,000 in every population (J 0.014 on discovery, 0.015 on
confirmation).

**3. Out-of-target corroboration.**
- Equal-count trades carry no piece-count signal and never entered the calibration target J. On them, VG_085_2000
  still fits best: mean |residual| 0.143, against GEOM_78 0.164, LP_150 0.159 and LP_250 0.155.
- VG's residual is also flat across every shape from 1-for-2 to 3-for-5+ (−0.04 to +0.01), pick share, month,
  source, TEP level and league size.

**4. The market's implied weight on a second piece in 1-for-2 trades** (n = 4,631):

| second piece's absolute size | median implied weight | GEOM_78 implies |
|---|---:|---:|
| 1,000–1,999 | 0.13 | 0.78 |
| 2,000–3,499 | 0.17 | 0.78 |
| 3,500–4,999 | 0.32 | 0.78 |
| 5,000+ | 0.30 | 0.78 |

The weight rises with the piece's *absolute* value, as a level effect predicts and a rank-only discount cannot.

### 6.2 What this means: the answer to the central question

**The apparent improvement from LP_150 is a value-level effect, not a weakness in the package shape.**
- **What the market does.** Completed trades behave as if every received asset first loses a fixed ~2,000 points,
  so assets below that count for almost nothing as trade currency. The remainder is then combined with a
  geometric package shape of q ≈ 0.80–0.85, close to our 0.78.
- **Why LP_150 looks better.** A homogeneous formula can only imitate a fixed level by discounting all small
  pieces relative to large ones. LP_150 does that partly; LP_250 does it fully and then over-credits elite
  trades.

**Replacement level or value curve?** (Preregistered rule R3 was *not* corroborated.)
- **Not this league's replacement level.** The level does **not** fall with league size, roster size (Phase 2),
  source or TEP. It is about 2,000 everywhere, and about the same on KTC's own scale. A level set by each league's
  starter pool would move with league size.
- **What it looks like instead.** A market-wide convention on dynasty value scales: KTC's and ours both price
  sub-~2,000 assets above what managers accept as trade currency.
- **What the data cannot tell apart.** Completed trades cannot distinguish (a) "the value scales run rich at the
  low end" from (b) "managers apply a fixed per-piece discount to fringe assets". Either way it is a property of
  how low-value assets are valued in trades, not of how packages combine.

**What it does not license:**
- changing canonical player values;
- changing the package formula;
- adding a level term to the live trade engine;
- double-counting the roster-spot and replacement costs that team context already charges (roster capacity /
  forced drops, lineup).

A level-aware *trade-currency* layer is a separate design question with its own owner decision (§11).

## 7. Mandatory properties

| candidate | add-asset monotone | raise-value monotone | order | swap | homogeneous | 1-for-1 raw | 1-point rule | `[7200]` vs `[6000, 1]` | eligible |
|---|---|---|---|---|---|---|---|---|---|
| GEOM_78 (incumbent) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **yes** |
| GEOM_q / LP_p / GP_q_g (every grid member) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes |
| EFD_78 / 115 / 130 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes (Phase 2) |
| KTC; KTC/GEOM blends | ✗ (Phase 1) | — | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ (B 676–2,031 worse) | **no**, whatever its fit |
| HYBRID_50, FGEOM_70_20 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes |
| VG_q_c / VOR_c (diagnostic) | ✓ (weak) | ✓ | ✓ | ✓ | **✗** | **✗** | ✓ | ✓ | **no**: a level effect, not a package formula |

The family rows are pinned by `tests/scripts/test_package_model_phase3_research.py`: 56 family members × 250
random trades, plus the mandatory case.

The local audit (`local.json → A_properties`) ran 4,000 seeded trades over nine properties plus the mandatory
case:
- **Homogeneous candidates** (LP_125 to LP_250, GP_078_150, GP_090_175): **0 failures**.
- **GEOM_78 (production dispatch):** 0 failures. Its only quirk is the dispatch's whole-point rounding: adding
  0.01 can move the gap by up to 0.99.
- **KTC: 2,425 failures.**
  - By property: add-asset 316, raise-value 122, homogeneity 1,636, one-point 178, continuity 142, unbundling 31.
  - Adding 0.01 can move its gap by up to 3,588.
  - The mandatory case gives 3,908.
- **VG_078_1500 / VG_078_2000:** fail homogeneity and the 1-for-1 identity, as expected for a level diagnostic.

## 8. Decision replay

This replay is local and context-free (`scripts/package_model_phase3_local.py` → `local.json`).
- **Board and engines:** the 2026-10-19 canonical board, run through the production engines.
- **Isolation:** each candidate was installed in-process only, and production was restored after every model.
- **No team context:** roster capacity is box-local.
- **Same candidate trades for every model:** every difference below comes from scoring.

### 8.1 Real players (canonical values, 2026-10-19)

Gaps are from the star side's point of view: positive favours the star, negative favours the package.

| trade | GEOM_78 | LP_150 | LP_175 | KTC |
|---|---|---|---|---|
| Jalen Hurts (5,956) vs Emeka Egbuka (5,198); raw +758 | unfair | unfair | unfair | — |
| … + Isaiah Hodgins (895) added to the Egbuka side | **+60, fair** (78% of the filler credited) | +513, slight | +623, unfair | +1,784, lopsided |
| … + four fillers instead (3,608 raw) | **−1,263, unfair the *other* way** (2,021 credited) | −201, fair (959 credited) | — | — |
| Jahmyr Gibbs (9,870) vs DeVonta Smith + Tee Higgins | +1,090, Gibbs | +2,043, Gibbs | — | — |
| … + four ~1,000 fillers added to the package | **−657, package edges it** | +1,115, Gibbs | — | — |
| Gibbs vs Bryce Young + Tucker Kraft (5,409 each; raw 10,818) | +242, **fair** | +1,284, **unfair** | +1,832, unfair | +4,263, lopsided |
| Gibbs vs six ~2,950 starters (raw 1.8×) | −557, fair | +119, even | +1,648, slight | — |
| Garrett Wilson (6,516) vs Jake Ferguson + Travis Kelce (7,031) | +254, fair | +935, unfair | — | — |
| **IDP:** Carson Schwesinger (6,223) vs Zack Baun + Micah Parsons (6,810) | +155, fair | +818, unfair | — | +2,298, lopsided |
| **Picks:** Jeremiyah Love (7,313) vs 2027 Pick 1.10 + 2028 Late 1st | −115, fair | +695, slight | +1,118, unfair | — |

Flag counts across the full example set:

| flag | GEOM_78 | LP_125 | LP_150 | LP_175 | LP_200 / LP_250 / GP / KTC |
|---|---|---|---|---|---|
| a superstar beats legitimate starters by a large margin (of 9 cases) | 0 | 0 | 6 | 6 | 9 each |
| a decisive verdict on a raw near-even trade (within 10%) | 1 | — | 6 | 6 | — |
| filler alone tips the verdict | 1 | 1 | 0 | 0 | 0 |

**What this shows: GEOM_78 has one genuine weakness — filler can tip a near-even verdict.**
- Phase 2's statement that "a pile of filler never comes close" is true for a star against filler only. The
  Finder still makes no star-for-pile recommendations.
- But a rank-only discount credits a 900-point sweetener at 78% of its value, and four of them can flip a correct
  "unfair" into "unfair the other way".
- That conflicts with your rule that a filler player should not manufacture fairness.
- It is also where the market evidence (§6, a small second piece earns about 0.07–0.16 of its value) is most
  clearly against GEOM_78.

**LP_150 fixes the filler case, but it calls 2-for-1s of genuine starters unfair to the package side.**
- Examples: Gibbs vs Young + Kraft, Wilson vs Ferguson + Kelce, and the IDP and pick cases.
- It does this in 6 of 9 near-even cases.
- That breaks your other rule: several legitimate starters should still have significant value.

### 8.2 Fairness levels on 2,000 fixed trades (raw gap ≤ 25%; 943 equal-count)

| model | level changed vs GEOM_78 | favoured side flipped |
|---|---:|---:|
| LP_125 | 511 | 71 |
| LP_150 | 520 | 57 |
| LP_175 | 680 | 125 |
| LP_200 | 821 | 174 |
| LP_250 | 907 | 228 |
| GP_078_150 / GP_090_175 | 795 / 796 | 171 / 170 |
| KTC | 1,227 | 155 |

- On unequal-count trades, LP_150 moves the verdict toward the fewer-pieces side 688 times and away 369 times.
  LP_175: 856 vs 199.
- A switch to LP_150 would change about a quarter of all displayed fairness levels.

### 8.3 Trade Finder (12 teams)

Overlap is top-10 overlap with GEOM_78, and dropped trades are GEOM_78's depth trades the model no longer
recommends. Both are given per surface in the order package scan / all shapes / best offers / star builder.

| model | overlap with GEOM_78 | GEOM_78 depth trades dropped |
|---|---|---|
| LP_125 | .78 / .50 / .68 / .49 | — |
| LP_150 | .55 / .12 / .22 / .27 | 75 / 12 / 73 / 116 |
| LP_175 | .30 / .05 / .13 / .18 | 146 / 22 / 82 / 134 |
| LP_200 | .22 / .02 / .09 / .09 | — |
| KTC | .13 / .03 / .15 / .15 | — |

User's board edge from the recommendations each model adds:

| model | best offers | star builder |
|---|---|---|
| GEOM_78 recommendations replaced by LP_150 | +2,631 | +1,408 |
| LP_150's replacements | +1,104 | +611 |
| LP_175's replacements | +489 | +57 |
| LP_200's replacements | negative | negative |

- **No model produced a star-for-pile recommendation** on any surface.
- **A typical LP_150 swap:** it drops Higgins + Nick Herbig → Ashton Jeanty / CeeDee Lamb, and adds Josh Allen →
  Brock Bowers + Sonny Styles. The new recommendations give the user less of our board's edge than the ones they
  replace.
- **Deep packages never reach Finder recommendations.** The Finder allows a difference of at most one player, and
  Package Builder at most three assets. The deep-package question is therefore a Trade Calculator and Trade
  History question, not a Finder one.

**Read: on these inputs LP_150 makes more aggressive decisions, not better ones.**
- It fixes GEOM_78's filler case.
- It over-charges genuine-starter packages.
- It rewrites most Finder recommendations.
- It lowers the board edge it hands the user.

LP_175 and stronger only add cost. The useful part, discounting small pieces by their size, needs a shape that
leaves genuine starters near the incumbent. A homogeneous LP_p cannot do both: raising p to silence filler also
taxes every starter. Whether the market evidence (§6) supports something in between is for the box run to
decide.

## 9. Challenger status and the preregistered protocol: results

The protocol was frozen in `evidence/package_model_phase3_2026-10-20/PREREGISTRATION.md` before the run.

### 9.1 The run

- **Validity.** Aggregates only, and the guard refused 0 writes or processes.
- **Network.** 273 network refusals, all from the same `_resolve_league_context`. The function is byte-identical
  in the deployed `fd798c3e`, so the §1 parity audit applies.
- **Memory.** Peak 1,157 MB.
- **Ledger.** 29,638 groups, 18,690 graded trades, 11,565 leagues.
- **Reproduction.** On trades through 2026-10-19 (n 18,588, the ledger having grown slightly) the run reproduces
  the first production report to within 0.0006 in every bin: GEOM_78 −0.3006 / −0.1350 / −0.1270 against
  −0.3012 / −0.1349 / −0.1267.
- **Split.** Discovery 9,306 and confirmation 9,384, league-disjoint. There are no prospective trades yet: the
  freeze date is the last trade date.

### 9.2 Selections (discovery) and confirmation (held-out leagues)

| | S1 pooled: LP_250 | S2 elite-level: GP_078_150 |
|---|---|---|
| two-piece factor (GEOM_78: 1.78) | 1.32 | 1.47 |
| C1: calibration gain, clustered CI | J 0.018 vs 0.298, ΔJ [0.271, 0.284] ✓ | J 0.101 vs 0.298, ΔJ [0.196, 0.199] ✓ |
| C2: no bin materially worse | ✓ | ✓ |
| C3: dispersion | −0.090 [−0.092, −0.087] ✓ | −0.076 [−0.079, −0.075] ✓ |
| C4: both sources | ✓ (0.019 / 0.033) | ✓ (0.094 / 0.118) |
| C5: players and picks | ✓ | ✓ |
| **C6: elite over-credit** | **FLAGGED** (6,000–7,999: 1-for-N +0.086, ordinary +0.054) | not flagged |
| verdict | calibration replicated, **ineligible** (C6) | calibration replicated |

LP_150, shown but not independently tested (it was seen before the freeze), is −0.159 / −0.077 / −0.094 on
confirmation, unchanged from the full sample.

### 9.3 Interpretation rules (applied as frozen)

- **R1 applies.** On confirmation the decomposition's best has c = 2,000 > 0 and q = 0.85, which lies in
  [0.70, 0.85]. Its J is 0.006, below the better of S1 and S2 (0.018). Per the frozen rule, *a package-formula
  change is not supported*, and the level effect is routed to a separate follow-up.
- **R2 does not apply.** The best fit has c > 0 and q ≥ 0.70.
- **R3 is not corroborated.** c does not fall with league size (§6.2).
- **R4.** The elite-level estimate of the pure package premium is GP_078_150's two-piece factor, 1.47. But the
  decomposition at elite level still prefers q = 0.85 with c = 2,000. So the "stronger premium" read from
  homogeneous fits is the level effect again, not a stronger shape.

**GP_078_150** passes C1–C6, but R1 decides against a package change and the decision evidence goes the same way:
- in the local replay (§8) the GP family flags "superstar beats legitimate starters by a large margin" in 9 of 9
  cases;
- it needs 1.36× raw for two equal pieces against one star, and 3.86× for ten.

That breaks the rule that several legitimate starters keep significant value.

**No shadow challenger is implemented.** None qualified under the frozen rules, so adding a disabled-by-default
model path would add code without a candidate to put in it.

### 9.4 Prospective re-run (optional)

Trades after 2026-10-20 have not been seen by anyone. Re-running the same pinned command once there are at least
2,000 unequal post-freeze trades (about two weeks at October volume) would confirm on them. That re-run is now
confirmation of a KEEP, not a gate for a change. It is worth doing only if you want the strongest possible
record.

## 10. Owner report: the fifteen questions

1. **Did the 18,031-trade production dataset confirm Phase 2?**
   Yes, every conclusion, with intervals 3–5 times narrower:
   - all models under-credit consolidation;
   - depth-friendlier models are worse;
   - KTC and its blends are no better and fail monotonicity;
   - the value-level gradient is real.

   Phase 3 adds one thing: *why*. The gradient is a fixed value-level effect (§6).
2. **Is GEOM_78 mathematically correct and still defensible?**
   - **Correct:** yes. 0 failures on every mandatory property.
   - **Defensible:** yes. Once the level effect is separated, the market's own package shape is q ≈ 0.80–0.85.
     q = 0.78 sits beside it, with the incumbent's J at that level 0.015 against the best 0.006.
3. **Does the stronger consolidation preference in completed trades show a weakness in GEOM_78?**
   Not in its package shape. It shows something GEOM_78 does not model, and no package formula should: low-value
   assets count for far less as trade currency than their value-scale numbers say.

   The one visible symptom inside the calculator is real. A rank-only discount credits a sub-2,000 filler piece
   at 78% (§8.1).
4. **Is LP_150 a legitimate improvement or just more aggressive?**
   More aggressive. Its calibration gain is a partial imitation of the level effect:
   - it still leaves a level gradient (−0.21 at level 2,000–3,999 against −0.05 at 6,000–7,999);
   - on real players it rates 2-for-1s of genuine starters unfair (6 of 9 cases);
   - it rewrites most Finder top-10s with recommendations that hand the user less board edge.
5. **Does a better monotone hybrid exist?**
   Not as a homogeneous package formula. Each candidate either over-credits elite consolidation (LP_250,
   C6-flagged) or taxes genuine starters (GP_078_150, LP_175+).

   The structure that fits is *shape + level*: q ≈ 0.8 above a ~2,000 level. Its level half is not a package
   property and fails homogeneity by design.
6. **Best for 2-for-3?** (n 1,861)
   - GEOM_78 −0.11; LP_150 −0.06; GP_078_150 −0.02; LP_250 +0.01.
   - The level diagnostic VG: 0.00.
   - GEOM_78's error here is one of its smallest, after only the balanced 3-for-4+ and 3-for-5+ shapes. The level
     effect accounts for it.
7. **Best for 1-for-3?** (n 1,492)
   - GEOM_78 −0.33; LP_150 −0.17; GP_078_150 −0.09; LP_250 +0.01; VG −0.01.
   - The largest GEOM_78 shortfall is in 1-for-N trades, and nearly all of it is the level effect: the
     consolidating side's single asset is usually well above 2,000, and the extra pieces are often near it.
8. **Six-to-ten-asset packages?**
   - 1-for-5+ (n 201): GEOM_78 −0.33, LP_150 −0.20, VG −0.04.
   - 2-for-5+ (377): GEOM_78 −0.16.
   - 3+-for-5+ (698): GEOM_78 −0.05, LP_150 −0.05.
   - All-player deep packages (80): GEOM_78 −0.08, VG +0.02.

   Balanced deep packages are already handled well by GEOM_78. Lopsided star-for-many are not, again because of
   the level. LP_150 is more generous than GEOM_78 to very deep *even* packages (n = 10: 2.15× vs 2.40× needed)
   and harsher to uneven ones.
9. **Which best tells real depth from filler?**
   - The market draws the line by absolute value. A second piece below 2,000 earns 0.13 of its value; one of
     3,500–4,999 earns 0.32.
   - GEOM_78 cannot draw that line: it is rank-only and credits filler at 78%.
   - LP_150 draws it by relative size, which taxes genuine starters.
   - Only a level-aware layer draws it the way the market does. That is the follow-up (§11).
10. **How much of the discrepancy is picks or the value curve?**
    - **Picks:** not a separate cause. GEOM_78's shortfall grows with pick share (−0.25 → −0.33), but the level
      model is flat across pick share (+0.02 → −0.03). Picks behave like any asset of the same value.
    - **Value level:** essentially all of the systematic part. The level model leaves residuals within ±0.03 in
      every stratum, against GEOM_78's −0.10 to −0.35.
11. **Confidence for our IDP-heavy league?**
    - **Low.** 138 trades with IDP assets: DB 98, LB 41, DL 20, 12 of them deep. 276 trades from IDP-format
      leagues. The direction matches offense.
    - **The market evidence is about offense and picks.** Any IDP-specific package or level conclusion needs our
      own league's trades. There are 38 own-league graded trades in Phase 2, far too few.
12. **Would changing the formula improve Trade Finder and Trade Advisor?**
    Not to LP_150 or anything stronger. In the local replay they rewrite 45–95% of top-10s and hand the user less
    board edge (best offers +1,104 vs +2,631). No model produced a star-for-pile trade.

    A level-aware layer *might* improve filler handling. It is untested and would need its own replay with team
    context on.
13. **What would users notice if a new formula went live?** With LP_150:
    - about 25% of fairness labels would change on near-even trades;
    - 2-for-1s of two genuine starters for one star would flip from "fair" to "unfair";
    - most Finder top-10s would change;
    - filler sweeteners would stop rescuing lopsided trades;
    - Trade History grades would shift.
14. **Risks of changing the production model:**
    - fitting a market convention instead of value;
    - over-crediting elite consolidation (the C6 failure);
    - double-counting roster-spot costs that team context already charges;
    - re-grading Trade History;
    - JavaScript/Python parity work;
    - no IDP evidence;
    - a prospective population still unseen;
    - churn in user-visible verdicts with no demonstrated decision gain.
15. **What further evidence is needed?**
    - **For KEEP:** none required. The optional prospective re-run (§9.4) would strengthen the record.
    - **For the level question:**
      - a value-curve study of how canonical values below ~2,000 compare with trade-implied values (and with
        KTC's);
      - a team-context-on replay on the box;
      - own-league outcome evidence;
      - IDP-specific trades.

## 11. Recommendation

**KEEP GEOM_78. Retain `geom_q078_v1` with q = 0.78, unchanged.**

**The evidence:**
- 18,690 graded production trades.
- A preregistered, league-disjoint confirmation.
- Decision replays.

**Why it supports keeping GEOM_78:**
- **The package shape is not the problem.** Once a fixed value level is separated, the market's own package shape
  is q ≈ 0.80–0.85, beside the incumbent's 0.78.
- **LP_150's advantage is that level effect, imperfectly imitated.**
- **The two candidates that passed calibration both fail a decision test:**
  - LP_250 over-credits elite consolidation (C6);
  - GP_078_150 taxes genuine starters (9 of 9 local cases).
- **The local replay says the changes would make trade advice worse.**

**Follow-up for a separate owner decision (not authorized, not implemented): a trade-currency / value-level
study.** The market treats sub-~2,000 assets as near-worthless trade currency, uniformly across league sizes,
sources and both value scales. That is the one robust, systematic finding here. It explains GEOM_78's single
real weakness, filler sweeteners in near-even trades. The study would decide where, if anywhere, this belongs:

1. **Canonical value curve.** A valuation-owner question about the low end of the scale. It affects rankings, not
   only trades.
2. **Trade-currency layer in the trade engine.** For example, a labelled, reported adjustment for sub-level
   pieces. It must be designed so it does not double-count roster capacity / forced drops.
3. **Nowhere.** Shown to users as information only.

**Limitations of this recommendation:**
- Completed trades show where trades clear, not what is fair.
- The level reading cannot tell a value-curve cause from a convention cause.
- IDP evidence is thin.
- The decision replay is context-free.
- The prospective population is still unseen.

## 12. Verification and outstanding work

**Evidence** (`evidence/package_model_phase3_2026-10-20/`, all aggregate-only):

| file | content |
|---|---|
| `production_ledger_run_2026-10-20.json` | the first production report |
| `production_phase3_run_2026-10-20.json` | the preregistered Phase 3 run (sha256 `e42769a5…6598`) |
| `offline_parity_audit.json` | 0 / 136,558 values changed |
| `local.json` | properties, consolidation premium, real-player examples, decision replay |
| `PREREGISTRATION.md` | frozen before the run; no amendments |

**Commands.** The owner ran the pinned Phase 3 box command at `d7a881bc` (sha256-verified, read-only guard).
Locally:
- `python scripts/package_model_offline_parity_audit.py --out …`
- `python scripts/package_model_phase3_local.py`

**Tests:**
- `pytest tests/scripts/test_package_model_phase3_research.py tests/scripts/test_package_model_phase2_research.py tests/scripts/test_research_readonly_guard.py tests/scripts/test_package_model_hybrid_research.py tests/valuation_math tests/docs`;
- `bash scripts/format_python_changes.sh` green.

**Production is unchanged.** `geom_q078_v1` is active, with no code, config, value, weight or UI change.

**Outstanding:**
- (1) The optional prospective re-run.
- (2) A team-context-on replay (box-local).
- (3) The trade-currency / value-level study, which needs owner authorization.
- (4) IDP-specific evidence.
- (5) The owner decision on this recommendation.

UNRESOLVED: items (1)–(5). None of them blocks the KEEP recommendation.

## Addendum (2026-10-21): `fairness_bands_v2` re-measurement

The fairness levels in this memo were classified on the retired `fairness_bands_v1` denominator. They are
re-measured on `fairness_bands_v2` in `PACKAGE_MODEL_PHASES_1_3_V2_REMEASURE_2026-10-21.md` (§4.3). The
recorded v1 numbers reproduce exactly. **The KEEP recommendation does not change.** This memo and its evidence
are preserved as recorded.
