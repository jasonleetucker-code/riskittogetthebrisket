# Package Value Adjustment — Phase 3: the production market ledger, LP_150, and the value-level question (2026-10-20)

**Status: RESEARCH — interim.** Sections marked **[BOX RUN PENDING]** wait on the preregistered Phase 3
production run (`scripts/package_model_phase3_research.py --box`, pinned commit `d7a881bc`).

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
| the shortfall grows as value falls | single-side binning | to be re-measured with noise-balanced binning (§6) | **[BOX RUN PENDING]** |
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

**[LOCAL ANALYSIS — §8 adds the replay.]**

### 4.2 The family: how strong a consolidation premium do the trades "want"?

Exploratory, on the research container's own sample (1,078 trades; mostly Sharp Sleeper, overlapping the box
ledger). This is not production evidence:
- the pooled calibration loss J **keeps improving as consolidation strengthens**, all the way past LP_150 to
  LP_250 / LP_300 and GP_090_250 (J ≈ 0.02–0.03);
- for scale: LP_250 values two equal pieces at **1.32×** one piece, and ten 3,000-value starters at about 7,500,
  below a single 9,000 star.

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
- **Assets.** The report carries asset *kinds*, not positions. DL, LB and DB involvement, IDP-only trades and
  mixed offense/IDP trades are counted by the box run. In the container sample IDP assets appear in 27 of
  4,000+ asset slots.
- **Read:** the market evidence is overwhelmingly about offense and picks. **No package-model conclusion
  extends to IDP-heavy trades in our league without qualification.**

**B. Picks.**
- 14,474 graded trades include a pick (80.3%) and 3,557 are player-only. In the deep bin 1,187 of 1,233 include
  a pick, so only 46 deep trades are all players.
- GEOM_78 player-only: −0.247 / −0.098 / −0.087. With picks: −0.312 / −0.139 / −0.128.
- So picks deepen the shortfall, but do not create it.
- Pick-only, mixed, multi-future-pick, pick-dominated deep and all-player deep trades, plus the share of the
  deep side that is picks: **[BOX RUN PENDING]**.

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
- The production report's chronological split and source split both agree. Week-balanced means and a
  source × regime split are in the box run.

**E. League dependence.** 11,188 leagues and a league cap that changes nothing (§1 #8) argue against
dependence driving anything. League-clustered bootstrap intervals for every reported statistic are in the box
run.

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

**[BOX RUN PENDING]:** the same tables on 18,031+ trades with league-clustered CIs, by league size, source and
composition, and on KTC's value scale.

## 7. Mandatory properties

| candidate | add-asset monotone | raise-value monotone | order | swap | homogeneous | 1-for-1 raw | 1-point rule | `[7200]` vs `[6000, 1]` | eligible |
|---|---|---|---|---|---|---|---|---|---|
| GEOM_78 (incumbent) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **yes** |
| GEOM_q / LP_p / GP_q_g (every grid member) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes |
| EFD_78 / 115 / 130 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes (Phase 2) |
| KTC; KTC/GEOM blends | ✗ (Phase 1) | — | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ (B 676–2,031 worse) | **no**, whatever its fit |
| HYBRID_50, FGEOM_70_20 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | yes |
| VG_q_c / VOR_c (diagnostic) | ✓ (weak) | ✓ | ✓ | ✓ | **✗** | ✓ | ✓ | ✓ | **no**: a level effect, not a package formula |

The family rows are pinned by `tests/scripts/test_package_model_phase3_research.py`: 56 family members × 250
random trades, plus the mandatory case. **[LOCAL ANALYSIS — §8 adds the per-candidate audit counts.]**

## 8. Decision replay

**[LOCAL ANALYSIS PENDING — being completed.]**

## 9. Challenger status and the preregistered protocol

**No challenger is advanced, and no shadow pathway is added to application code.** Nothing yet meets your bar:
a specific advantage that survives independent validation.

The protocol is frozen in `evidence/package_model_phase3_2026-10-20/PREREGISTRATION.md` and implemented by
`scripts/package_model_phase3_research.py --box`:
- **Split.** League-disjoint discovery and confirmation halves, from a salted league hash.
- **Selections, on discovery only:**
  - S1, pooled calibration;
  - S2, elite-level calibration.
- **Tests, on confirmation:**
  - C1: calibration gain, league-clustered CI;
  - C2: no bin materially worse;
  - C3: dispersion not worse;
  - C4: both source families;
  - C5: players and picks;
  - C6: no elite over-credit.
- **Decomposition** (the R1–R4 rules) on every population.
- **Prospective.** Trades after 2026-10-20 form the only population nobody has seen. They are tested by
  re-running the same pinned commit once at least 2,000 unequal prospective trades exist (about two weeks at
  October volume).

## 10. Owner report: the fifteen questions

**[Completed after the box run and the replay; see §11 for the interim position.]**

## 11. Recommendation (interim)

**KEEP GEOM_78 — and CONTINUE CHALLENGER RESEARCH only through the frozen box protocol.**

**Why nothing changes today:**
- The production ledger confirms Phase 2 to high precision: every model under-credits consolidation, and
  depth-friendlier models are further off.
- The candidate that fits best on pooled data, LP_150, keeps "improving" as the premium is pushed to extremes.
  That is the signature of fitting a level effect with a shape formula.
- The container sample suggests the market behaves like *our* q = 0.78 above a fixed value level of about
  2,000. If confirmed, the improvement belongs in replacement-level and team-context modelling, not the
  package formula.

**What would change the recommendation:**
- R2 (§9): the decomposition finds no level effect, and an elite-level challenger passes C1–C6 on the held-out
  half;
- and later the prospective population confirms it.

## 12. Verification and outstanding work

**Done:**
- the report validated (§1);
- the full offline-parity audit;
- the period and source mechanism identified;
- the Phase 3 box protocol frozen, implemented, tested and rehearsed with the exact owner command
  (0 writes, 0 file changes, temp dir removed).

**Tests.** `pytest tests/scripts/test_package_model_phase3_research.py tests/scripts/test_package_model_phase2_research.py tests/scripts/test_research_readonly_guard.py tests/scripts/test_package_model_hybrid_research.py tests/valuation_math tests/docs`
→ 324 passed. `bash scripts/format_python_changes.sh` green.

**Outstanding:**
- (1) the Phase 3 box run (owner-run, pinned `d7a881bc`);
- (2) the prospective re-run after ≥ 2,000 unequal post-freeze trades;
- (3) the local decision replay (§8);
- (4) a team-context-on Trade Finder replay (box-local roster capacity);
- (5) the value-curve / replacement-level follow-up, which needs its own owner authorization.

UNRESOLVED: items (1)–(5).
