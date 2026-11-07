# W27-F005: TE retail-premium skew (methodology proposal, research only)

**Activation status: NOT ACTIVATED.** No production formula, weight, threshold, flag or
served field changes in this proposal. It is authorized as research and preparation only
(`docs/EXECUTION_PLAN.md`, MD-59; owner directive
`docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md` §3).

| | |
|---|---|
| Finding | W27-F005 (`docs/master-site-audit/evidence/registry/W27.jsonl`), re-adjudicated PARTIAL in `docs/audits/remediation_2026-11-06/CW40_P1_UNADJUDICATED.md` |
| Owner framing | 22 TEs carry a retail premium against 1 with a consensus premium. Is that a real market difference, TE-premium scoring, positional calibration, replacement level, market-source behaviour, a wrong transformation, or a methodology mismatch? |
| Research script | `scripts/research/w27_f005_te_skew.py` (offline and deterministic; the network is refused) |
| Test | `tests/scripts/test_w27_f005_te_skew_research.py` |
| Evidence | `docs/valuation/methodology_proposals/evidence/w27_f005_te_skew.json` |
| Base | `main` at `d7db52a43b` |

## 0. Answer

The skew is **mostly a methodology mismatch in the label, plus a smaller real market
difference.** It is not a wrong TE transformation, and it is not caused by league
scoring or replacement level.

1. **About 89% of the median TE gap is a value-curve spacing difference that every
   position shares.** The label compares our canonical value with KTC Market's
   normalized value. The two boards space value differently. Our board is above KTC
   Market at board ranks 2 to about 34, by up to 0.151 in log terms. The two cross
   near ranks 35 to 40. At every rank from 41 to 400, our board is below KTC Market, by
   0.002 to 0.194. 28 of the 30 top-250 tight ends sit at board ranks 25 to 238, so
   most of them read "retail premium" whatever anyone thinks of the player. The
   same term makes running backs 27 SELL / 5 BUY and wide receivers 27 / 15. Neither
   position has any TE transform.
2. **The rest is a real ordinal difference.** KTC ranks tight ends above our board:
   the median player-specific term is +0.031 log, and 70% of TEs are positive. On a
   scale where 0 means "prices TEs like KTC's base board" and 1 means "like KTC's TE++
   board", KTC Market scores 0.995 and our board 0.911. Every non-KTC board flagged as
   TE-premium scores below our board: IDPTC 0.50, DraftSharks 0.82, Dynasty Nerds
   SF-TEP 0.30, Fitzmaurice 0.28, Yahoo/Boone 0.10, and the held DLF Values SF-TEP
   0.30. **KTC TE++ prices tight ends higher than any other board in the source set.**
   That asymmetry is genuine, and nothing here should balance it away.
3. **The TE transformation is not defective.** On the pinned board, KTC's own
   base-to-TE++ uplift matches the production curve: the median log residual is
   −0.0098 and the mean is +0.0003. The flat 1.10 multiplier for TEP-native sources is
   unmeasured, so I tested the most aggressive fix: convert those sources with KTC's
   full curve. That makes our board's TE posture identical to KTC's (theta 1.002), and
   TEs are **still 16 SELL / 1 BUY**. At most, this hypothesis explains 6 of the 22
   labels, and only by calibrating the board to the benchmark it is measured against.
4. **Neither label has shown predictive skill.** I rebuilt 59 daily boards from
   2026-09-09 to 2026-11-07, each from its own pinned tree. The gap direction does not
   predict KTC Market's relative move over 7, 14 or 28 days. The mean information
   coefficient is −0.16 to −0.20 for both the incumbent and the candidate: KTC keeps
   moving the way it already deviates. The incumbent's TE labels persist 91% of the
   time at 14 days, which fits a structural offset. The candidate's persist 55%, close
   to other positions.

**Recommendation.** Do not change any value (reject C2, C3 and C4 below). Send **C1,
the scale-neutral gap**, to an owner-approved **shadow-only** evaluation. C1 is a
deterministic function of two fields the board already publishes, so the shadow can run
offline on the committed archives with this script. No served path, field or UI
changes. Its acceptance criteria would be fixed in advance (§13).

## 1. What is already closed, and what is not

The August finding measured the gap in RANK space. There it compared KTC's TE++
ordinals with base-TE ordinals and was basis-blind: 33 of 33 TEs came out SELL. That
version is **retired**. Since the owner directive of 2026-09-23, the gap is our
`rankDerivedValue` against KTC Market in value space. Both sides now sit on the same
TE++ basis: KTC Market natively, and the board through the ADR-015 conversion. The
basis mismatch the audit described therefore no longer exists by construction.

On the pinned board, the residual is TE 22 / 1, RB 27 / 5, WR 27 / 15 and QB 6 / 15.
These are top-250 rows with a ratio of at least 0.05, matching
`tests/api/test_audit_w27_f005_regression.py`.

## 2. Current formula and meaning

**Label (the quantity under test).**

* `src/sources/ktc_market.py:187-243` `build_market_blocks`: `normalizedValue = raw
  ktcCrowdTradesSfTep / max(raw over rankable rows) × 9999`. Pinned max: 9702.
* `src/sources/ktc_market.py:123-145` `compute_market_gap(model, market)`:
  `ratio = (market − model) / mean(market, model)`. A positive ratio is
  `retail_premium` (KTC above our model, a "sell" candidate). A negative ratio is
  `consensus_premium`. If either side is missing, the result is `("none", None)`.
* `src/api/data_contract.py:4764-4787` `_compute_market_gap` is a thin alias.
  `:4790-4835` `_stamp_ktc_market_benchmark` stamps `marketGapDirection` /
  `marketGapValueRatio` last, on the final published value (called at `:15295`).
* Display gates: `frontend/lib/thresholds.js:99` `MARKET_GAP_MIN_VALUE_RATIO = 0.05`
  (the /rankings Edge column and the trade page) and `:120`
  `PREMIUM_SUMMARY_VALUE_RATIO = 0.15` (the /edge panels).

*Meaning, as the owner defined it:* "KTC Market prices this asset above (or below) our
canonical value."

**Model side: TE alignment (ADR-015; verified exactly-once by W27-F009).**
`src/api/data_contract.py:13722-13750`, constants at `:9954-9955`, `:10002` and `:10007`:

* KTC Crowd and KTC Trades are exempt. They are already TE++.
* For non-TEP sources, `value ← soft_knee(convert_te_value(value, "base", "tepp"))`,
  where `convert_te_value` (`src/league_intel/te_premium.py:355`) multiplies by
  `tep_uplift(v) = min(2.0531, max(1.2092, 1 + 43.556·v^−0.6328))` (`:323`, constants in
  `config/weights/te_premium_curve.json`).
* For TEP-native sources (IDPTC, DLF Values SF-TEP, Dynasty Nerds SF-TEP, Fitzmaurice,
  Yahoo/Boone, DraftSharks), the value is multiplied by a flat
  `_TE_BLANKET_NATIVE_MULTIPLIER = 1.10`, a number nobody has measured.
* The target basis is the constant `"tepp"`. It is scoped to the scoring profile and
  shared by `dynasty_main` and `dynasty_new`.

**Market side.** KTC Market is KTC's published Crowd+Trades TE++ value. It gets no
transform, and it is never a vote.

## 3. Pinned inputs and reproduction

An archived payload does not pin a board on its own. `build_api_data_contract` reads
every non-KTC source CSV, `data/scrape_state` and `config/weights` from a repository
tree. This study materializes that tree at the commit that **added** the archive, using
the shared `scripts/research_pinned_board.py`. The network is refused during every
build, and the Sleeper league-context lookup gets its offline fallback. The board hash
is identical with and without that guard.

| input | value |
|---|---|
| archive | `exports/archive/dynasty_export_20261106_194518.zip`, sha256 `d4b196ea…7ced1` |
| payload | `dynasty_data_2026-11-06.json`, sha256 `18a3f2e2…07df1`, scrape 2026-11-06T19:45:17Z |
| tree revision | `2550b42abf36728731320bcfd78f762b7833402e`, content sha256 `9313c6e3…3a43` |
| incumbent board sha256 | `80700fff0b33407dcc551c6896f1fdb2e83360e04d9e25d59b2a35bb93abd621` |
| C2 board sha256 | `4f422e7e02eec747a3ec740938d1007a826fa5f995582559c54c2fa9e42d8816` |
| network attempts refused | 0 |

To reproduce: `python scripts/research/w27_f005_te_skew.py --out result.json`. It takes
about 4 seconds. Add `--history` for the 59-board evaluation, which takes about 80
seconds. Two independent runs gave byte-identical pinned output.

**Side finding (routed, not fixed here).** `tests/api/test_audit_w27_f005_regression.py`
builds the archive without pinning the tree (`csv_root=None`). Its counts therefore
depend on the working-tree CSVs, which refresh about every 2 hours. On `main` at
`d7db52a43b`, the unpinned build gives RB 28 / 4 and WR 28 / 13. The pinned build gives
27 / 5 and 27 / 15, and TE is 22 / 1 in both. The test's strict xfail can flip on a data
refresh alone. The fix is to route that build through `research_pinned_board.csv_tree`.
That belongs to CW-40, not this proposal.

## 4. Diagnosis: each hypothesis, measured

### 4.1 League scoring (the actual card, `dynasty_main`, pinned `sleeper.scoringSettings`)

`bonus_rec_te 0.0`. `bonus_fd_te 1.0` equals `bonus_fd_wr 1.0`. `rec 0.1`, plus
`bonus_rec_wr 0.02`, so a WR earns 0.02 more per catch than a TE. The lineup has 2
dedicated TE slots, 2 FLEX and 1 SUPER_FLEX. **The league pays no TE scoring premium**
(LI-7 / ADR-009), and on receptions it is marginally negative.

The label does not depend on the league. It is computed on the board scoped to the
scoring profile, so `dynasty_new` gets identical labels.

Direction: ADR-009's symmetric structural estimate of the 2-TE premium is about 1.12,
against KTC TE++'s 1.32. That means KTC's TE++ setting includes a scoring component
this league does not award. For `dynasty_main`, a TE priced below KTC TE++ is
*directionally consistent* with its card. Correcting for it is Axis B (the league
overlay). That axis is inactive and gated by the owner. **League scoring does not
produce the skew.** If anything, it argues against "fixing" it upward.

### 4.2 Wrong transformation

The independent oracle in §6 re-measures KTC's own uplift from the paired `ktc` and
`ktcSfTep` boards. These are byte-identical for all 71 QB, 128 RB and 186 WR rows and
differ on all 78 TE rows.

| TE band (by KTC base) | actual KTC uplift (median) | production curve (median) |
|---|---|---|
| TE1-12 | 1.2255 | 1.2092 |
| TE13-24 | 1.2716 | 1.2923 |
| TE25-40 | 1.3183 | 1.3449 |
| TE41+ | 1.4994 | 1.4981 |

The median log(actual / curve) is **−0.0098** and the mean is **+0.0003**. The curve
is current: its July constants still reproduce KTC on 2026-11-06. W27-F009 showed it is
applied exactly once.

**The base-to-TE++ conversion is not a defect.** The flat 1.10 native multiplier is
unmeasured. C2 (§5) tests it and finds it cannot explain the skew.

### 4.3 Market-source behaviour (TE posture, scale-free)

For each board I quantile-match its ordering against KTC's base board. I then take the
median TE lift in KTC-base value units and divide it by KTC TE++'s own lift (0.1908
log). This gives **theta**: 0 means the board prices TEs like KTC base, and 1 means
like KTC TE++. The measure is scale-free, so rank lists, 0-100 indices and 0-9999
values all compare directly.

| board | registry `is_tep_premium` | theta |
|---|---|---|
| KTC Crowd / Trades / Market | yes / yes / benchmark | 1.000 / 0.979 / 0.995 |
| **our board (`rankDerivedValue`)** | n/a | **0.911** |
| our board, leave-KTC-out | n/a | 0.865 |
| DraftSharks | yes | 0.818 |
| IDPTC | yes | 0.500 |
| Dynasty Nerds SF-TEP | yes | 0.304 |
| DLF Values SF-TEP (owner-held, not a vote) | yes | 0.296 |
| Fitzmaurice | yes | 0.277 |
| Yahoo / Boone | yes | 0.098 |
| PFK / FantasyPros SF / FantasyCalc / Dynasty Daddy | no | 0.255 / 0.128 / 0.091 / 0.059 |
| FantasyNavigator / Flock / DLF SF / OTC | no | 0.051 / 0.033 / −0.011 / −0.160 |

Every board other than KTC prices tight ends **below** our board. The board already
leans further toward KTC than any other vendor. Two things put it there: ADR-015 lifts
every base source onto KTC's full TE++ curve, and the two KTC voters pull it toward
the benchmark.

Signal independence: removing the KTC voters lowers theta to 0.865, and TEs become 23
SELL / 1 BUY.

**The positive TE ordinal term is real KTC behaviour.** KTC's TE++ setting prices tight
ends above every other provider. "TEP" means very different things across vendors: the
TEP-labelled boards span theta 0.10 to 0.82. Because the theta values are this spread
out, no single basis multiplier could make the sources agree.

### 4.4 Positional calibration and value-curve spacing (the methodology mismatch)

Over the 485 rows both boards price, `log(market / model)` splits exactly into two
terms:

* `tier = log(q / model)`, where `q` is KTC Market's own value at **our board's rank**.
  This is how differently the two value curves price that rank, and it is shared by
  every asset at that rank.
* `ordinal = log(market / q)`. This is whether KTC ranks the player above or below our
  board, expressed in KTC's value units.

The maximum decomposition error is 0.

| position (top-250) | n | total (median log) | tier | ordinal | ordinal > 0 | tier ÷ total |
|---|---|---|---|---|---|---|
| TE | 30 | +0.077 | +0.069 | +0.031 | 70% | 0.89 |
| RB | 47 | +0.073 | +0.070 | +0.019 | 55% | 0.96 |
| WR | 62 | +0.037 | +0.062 | −0.004 | 39% | 1.67 |
| QB | 33 | −0.035 | +0.013 | −0.023 | 18% | n/a |

The tier curve, by rank within the common universe:

| rank | 1 | 11 | 26 | 51 | 101 | 151 | 201 | 251 | 301 | 401 |
|---|---|---|---|---|---|---|---|---|---|---|
| our board | 9997 | 8653 | 6914 | 5431 | 3742 | 2853 | 2306 | 1889 | 1664 | 1238 |
| KTC Market | 9999 | 7707 | 6425 | 5517 | 3912 | 3091 | 2641 | 2256 | 1918 | 1364 |
| log(KTC / board) | 0.000 | −0.116 | −0.073 | +0.016 | +0.044 | +0.080 | +0.136 | +0.178 | +0.142 | +0.097 |

Across every rank: the curve is −0.151 to +0.019 over ranks 2 to 50, crosses near
ranks 35 to 40, and is +0.002 to +0.194 over ranks 41 to 400. The deep tail (ranks
401 to 485) is mixed, from −0.374 to +0.097.

Our board is the more top-heavy curve. It puts more value on elite assets and less on
the middle of the board than KTC does. The OFFENSE Hill master averages several
vendors' value spacings (`docs/valuation/HILL_SOURCE_ALIGNMENT_AUDIT_2026-09-24.md`
H3/H4), while KTC Market carries KTC's spacing alone.

A per-player label that includes this term turns a curve-level disagreement into a
per-player SELL. That disagreement is about how far apart a rank-50 asset and a
rank-250 asset are. Trading one mid-board asset for another cannot capture it, because
both carry the same tier term.

Concrete cases: T.J. Hockenson (+0.072) and Oronde Gadsden (+0.074) are SELL entirely
through the tier term, with ordinal 0.000. Travis Kelce is SELL (+0.056) even though
KTC ranks him *below* our board (ordinal −0.017).

**This is the dominant cause**, and it is not specific to TEs. TE is hit hardest for
two reasons: 26 of its 30 top-250 rows sit at board ranks 42 to 238, where the tier
term is positive, and it also carries the positive ordinal term from 4.3.

### 4.5 Replacement level

Neither side of the gap uses a replacement level. `rankDerivedValue` is a consensus
market value, not value over replacement, and KTC Market is a crowd and trade value.
Replacement-aware TE value belongs to the league overlay (Axis B, inactive). **This is
not a cause.**

### 4.6 Verdict

| hypothesis | verdict | share of the TE gap |
|---|---|---|
| methodology mismatch (value-curve spacing inside a per-player label) | **primary cause** | about 89% of the median TE gap (tier term) |
| market-source behaviour (KTC TE++ is the most TE-bullish board) | **genuine, keep visible** | the ordinal term: median +0.031, 70% positive |
| wrong transformation | not supported; the 1.10 native constant is unmeasured but cannot explain it | at most 6 of 22 labels, and only by calibrating to the benchmark |
| TE-premium scoring | not a cause; the card pays no TE premium | n/a |
| replacement level | not a cause; neither side uses it | n/a |

## 5. Candidates

All results below are from the pinned board: top-250 offense rows, not quarantined,
gate 0.05.

| candidate | formula | QB S/B | RB S/B | WR S/B | **TE S/B** | values change? |
|---|---|---|---|---|---|---|
| **C0** incumbent | `(m − v) / mean(m, v)` | 6 / 15 | 27 / 5 | 27 / 15 | **22 / 1** | n/a |
| **C1** scale-neutral | `(m − q) / mean(m, q)`, `q` = KTC's value at our board's rank | 1 / 13 | 11 / 3 | 8 / 13 | **9 / 1** | **no** (label only) |
| **C2** TEP-native sources on the KTC curve | C0 on a board where the 6 TEP-native sources take the measured curve instead of 1.10 | 6 / 15 | 27 / 5 | 27 / 15 | **16 / 1** | yes (TE + tethered picks) |
| C1 on the C2 board | | 1 / 13 | 12 / 3 | 8 / 9 | 7 / 2 | yes |
| **C3** position re-centring | `C0 − median(C0 of the position)` | 10 / 10 | 12 / 13 | 14 / 17 | 5 / 7 | no |
| **C4** suppress TE direction | TE → `none` | 6 / 15 | 27 / 5 | 27 / 15 | 0 / 0 | no |
| leave-KTC-out (diagnostic) | C0 against a board without the two KTC voters | 6 / 15 | 29 / 5 | 32 / 15 | 23 / 1 | n/a |

At the /edge panel gate of 0.15: C0 gives TE 4 / 0, RB 7 / 0, WR 3 / 1, QB 1 / 3. C1
gives TE 1 / 0, RB 1 / 0, WR 0 / 1, QB 0 / 1.

* **C1, scale-neutral (recommended for shadow).** It keeps the player-specific
  disagreement in KTC's own units and moves the curve-level term into a separately
  named diagnostic. **It does not force symmetry by position.** Tight ends stay mostly
  "KTC higher" (9 / 1), and quarterbacks become 13 BUY / 1 SELL because KTC's
  Superflex QB discount is real.

  It does carry one stated assumption. Because `q` is a permutation of `m`, the
  ordinal terms **sum to zero over the whole priced universe** (measured sum 0.0). So
  C1 assumes the two boards agree on how much value exists at each rank and disagree
  only about who occupies it. The tier term is not discarded: it is published beside
  the label under its own name.
* **C2 is rejected.** It raises TE values by a median of +2.6% (up to +25% for deep TEs)
  and moves the board's TE posture to exactly KTC's (theta 1.002). That is calibration
  to the benchmark. It contradicts every independent TEP vendor (theta 0.10 to 0.82),
  and it still leaves TE at 16 / 1. It would also deepen `dynasty_new`'s known Axis-B
  over-premium (ADR-015) and move `dynasty_main` further from its card.
* **C3 is rejected as forced symmetry.** It erases real positional facts: KTC's QB
  discount and its TE++ ordinal premium. It also depends on which rows happen to be in
  the population.
* **C4 is rejected.** It is the audit's cheap interim fix. It hides the genuine ordinal
  component, and a suppressed direction reads like an absent gap.

## 6. Independent oracles and expected results

* **KTC uplift oracle.** A separate binned-median computation over the paired raw KTC
  boards. The curve is evaluated from the pinned config JSON, not through
  `src.league_intel.te_premium`. Results are in §4.2. The test also checks that the
  restated curve equals the production `tep_uplift` to 1e-9.
* **Incumbent restatement.** `signed_gap` re-implements the label. It shows 0
  mismatches against the stamped `marketGapValueRatio` and `marketGapDirection` across
  every row, and it equals `compute_market_gap` on 500 random pairs.
* **C1 exactness.** The decomposition error is 0 and the ordinal sum is 0. On a
  synthetic board where KTC is 10% higher everywhere in the same order, C0 labels every
  row SELL and C1 labels none. Swapping two players' KTC prices produces opposite C1
  labels. All of this is pinned in the test.
* **C2 oracle.** This is a log-linear re-blend from the incumbent's own per-source
  stamps: un-correct each TEP-native contribution, re-lift it with the curve evaluated
  here, then take the applied-weight-weighted mean log change. It deliberately skips
  Hampel, trimming and the family cap. Against the production rebuild it gives a median
  absolute TE value error of **1.25%** (maximum 3.4%, signed +0.66%, n = 30). The
  oracle's census is TE 13 / 2 against the pipeline's 16 / 1, so both agree that the
  skew survives C2.

## 7. Before and after: player impacts

**C1 (label only).** Values, ranks, tiers and confidence are unchanged by construction.

* TE label flips: 14 SELL→HOLD (Sadiq, Pitts, Strange, T. Ferguson, Hockenson, Stowers,
  Kelce, J. Johnson, J. Ferguson, Okonkwo, Gadsden, Henry, Barner, Schultz) and 1
  HOLD→SELL (Colston Loveland, ordinal +0.076).
* TEs still SELL under C1: Loveland, Kraft, Fannin, Likely, Kittle, Raridon, Mayer,
  Freiermuth, M. Taylor. Still BUY: McBride.
* Other positions: RB 17 SELL→HOLD, 3 BUY→HOLD, 2 HOLD→BUY, 1 BUY→SELL. WR 19
  SELL→HOLD, 11 BUY→HOLD, 9 HOLD→BUY. QB 5 SELL→HOLD, 7 BUY→HOLD, 5 HOLD→BUY.
* Volume: C0 labels 118 of 172 eligible rows (68.6% non-HOLD, matching the 0.05 gate's
  calibration note). C1 labels 59 (34.3%). The gate was calibrated on C0's distribution.
  Do **not** re-tune it to restore volume: that would be calibration to a quota, not to
  evidence.

**C2 (rejected; shown for completeness).** 82 TE rows and 33 tethered current-year pick
rows change, and nothing else moves. TE values rise by a median of +2.56% (maximum
+24.96%: Lake McRee, 609 → 761). Rank displacement has a median of 1 and a maximum of
45. Top ranked movers: Justin Joly 346→308, Zach Ertz 429→384, Mason Taylor 238→219,
Pat Freiermuth 228→210 and Oronde Gadsden 172→154.

## 8. Position and league-format impacts

* C1 is a label computed on the board scoped to the scoring profile, so its effect is
  identical for every league on the profile. It preserves Superflex QB pricing (QB stays
  mostly "our model higher"), the TE++ basis, IDP (which C1 does not touch: IDP has no
  KTC Market and keeps W27-F001's explicit "none") and every canonical value.
* C2 would reprice TEs on the shared board for both leagues: wrong for `dynasty_new`
  (1 TE), and further from `dynasty_main`'s card.
* `dynasty_new` is not loaded in this container. Its labels are identical by
  construction, because the board is shared.

## 9. Historical predictive evaluation

Method: I rebuilt 59 daily boards (2026-09-09 to 2026-11-07, the last archive of each
day), each from **its own pinned tree**, with today's code and the network refused. The
2026-09-08 board predates the KTC Market capture and prices 0 rows. A label at t uses
only the board at t. The outcome is KTC Market's raw move to the first board at or after
t + h, minus that interval's median offense move. A "hit" means a SELL was followed by a
relative fall, or a BUY by a relative rise. The information coefficient (IC) is
−Spearman(signal, move) per date, so a positive IC means the signal was predictive.

| horizon | signal | label dates | obs (players) | hit rate | player-clustered | mean IC (sd) | TE hit | TE move after SELL | TE label persistence |
|---|---|---|---|---|---|---|---|---|---|
| 7 d | C0 | 52 | 5673 (183) | 0.466 | 0.517 | −0.161 (0.073) | 0.495 | +0.77% | 0.930 |
| 7 d | C1 | 52 | 3021 (165) | 0.379 | 0.482 | −0.204 (0.109) | 0.464 | +0.83% | 0.653 |
| 14 d | C0 | 45 | 4845 (179) | 0.454 | 0.518 | −0.157 (0.077) | 0.484 | +1.24% | 0.911 |
| 14 d | C1 | 45 | 2573 (162) | 0.405 | 0.511 | −0.174 (0.108) | 0.487 | +1.13% | 0.547 |
| 28 d | C0 | 31 | 3380 (167) | 0.454 | 0.513 | −0.176 (0.083) | 0.476 | +1.58% | 0.897 |
| 28 d | C1 | 31 | 1765 (146) | 0.406 | 0.465 | −0.154 (0.101) | 0.503 | +1.54% | 0.439 |

How to read this:

* **Neither signal forecasts KTC converging on our board.** Both have negative IC at
  every horizon: assets KTC already prices above us tend to keep rising on KTC. Over
  this window the label behaves as a lagging-consensus or momentum indicator, not a
  mean-reversion forecast. That holds for TEs too: SELL-labelled tight ends were
  followed by a +1.2% relative rise on KTC at 14 days.
* C1 is **not better** on IC. It is not justified on predictive grounds. Its case is
  semantic: a per-player BUY/SELL should describe the player, not the curve.
* Persistence separates the two quantities. C0's TE labels persist about 90 to 93%,
  the highest of any position, which fits a structural offset. C1's TE labels persist
  44 to 65%, in line with QB, RB and WR.
* Per-date TE census: C0 shows 20 to 29 SELL and 0 to 2 BUY on **every** date. C1
  shows 3 to 14 SELL and 0 to 5 BUY.

What this evaluation cannot show: whether our board or KTC is "right" about TE value.
The outcome here is KTC's own next price, which can only test convergence. A real test
needs an independent outcome: realized completed-trade prices from the Sharp
completed-trade ledger or own-league trades, or realized dynasty value over a season.
That data is the precondition named in §13. The samples are overlapping, in-season
windows that cover only two months, so they are not independent.

## 10. Confidence, calibration and uncertainty

* C1 leaves `confidenceBucket`, B11 axes, freshness and the blend untouched. It reads
  only published values. The 0.05 and 0.15 gates keep their meaning as a relative
  magnitude, now of the player-specific term. Their calibration note (label volume)
  would no longer describe the population.
* What C1 does disclose is its zero-sum assumption. The tier term stays visible under
  its own name, so no information is lost.
* Theta is measured on one snapshot per vendor and is not identifiable as "basis"
  versus "opinion". That is ADR-009's standing objection, and it is why no candidate
  here uses it to set a multiplier. The flat 1.10 native constant stays uncalibrated
  until a publisher's paired standard and TEP boards exist (the KTC-style natural
  experiment). DLF Values SF-TEP beside DLF SF is the closest candidate, but they are
  different products (values against rankings), not a clean pair.

## 11. Downstream consumers of `marketGapDirection` / `marketGapValueRatio`

* /rankings Edge column and filter: `frontend/lib/display-helpers.js`,
  `frontend/lib/player-filters.js`.
* /edge panels: `frontend/lib/edge-helpers.js`, `frontend/app/edge/page.jsx`,
  `edge-columns.jsx`.
* Player compare: `frontend/app/players/compare/page.jsx`.
* Trade page edge: `frontend/lib/trade-logic.js` (`getPlayerEdge`, same 0.05 gate).
* `src/trade/suggestions.py` (reads the same stamps).
* Board history: `src/snapshots/board_store.py` (stores the direction).
* MCP read surface: `src/api/chase_upside_mcp.py`.
* Public projection: `src/public_league/public_contract.py` (private fields, never
  public).

The recommended offline shadow changes none of these (the optional stamped variant in
§13 only adds fields). A later activation that
*replaces* the direction would change all of them at once, along with the strict xfail
in `tests/api/test_audit_w27_f005_regression.py`. Under C1, TE would sit at exactly
0.90, its limit. That is coincidence, not a target, and the test would need
re-adjudication rather than tuning.

## 12. Rollback

Nothing is activated, so there is nothing to roll back. The recommended shadow is
offline and touches no served path. If the optional stamped variant were chosen, its
fields would be additive, and removing them restores the incumbent byte for byte. Any
later activation would sit behind a default-off flag with
`RISKIT_FEATURE_<NAME>=0` plus a restart as its rollback, following the repo's flag
convention.

## 13. Recommendation and the owner decision requested

**Recommendation:**

1. Keep every value unchanged.
2. Reject C2, C3 and C4.
3. Keep KTC's TE asymmetry visible as a real market difference.
4. Send C1 to a shadow evaluation.

**Decision requested (one choice):** approve, reject or modify **an offline shadow
evaluation of C1**:

* Run `scripts/research/w27_f005_te_skew.py --history` over the committed daily archives
  for at least 8 more weeks. C1 is a pure function of `rankDerivedValue` and
  `ktcMarket.normalizedValue`, so every archived board can be re-scored on its own
  pinned tree.
* Score C0 and C1 against an **independent outcome**: realized completed-trade prices
  from the Sharp completed-trade ledger and own-league trades. KTC's own next price is
  not independent.
* No served path, contract field or UI changes.
* Optional variant, only if the owner wants it visible on the live contract and MCP
  surface: two additive, named diagnostic fields, `marketGapTierLog` and
  `marketGapOrdinalRatio`, stamped in `_stamp_ktc_market_benchmark`. No UI consumer,
  and `marketGapDirection` / `marketGapValueRatio` stay unchanged.

**Pre-registered acceptance criteria for any later activation request:**

* (a) C1 is non-inferior to C0 on the independent outcome above.
* (b) The curve-level term is never discarded. Any surface that shows the C1 label also
  states the curve-level difference.
* (c) No forced balance: positional asymmetries that survive (a), such as KTC's TE
  premium and its QB discount, are shown as they are.
* (d) The numbers are re-measured on a pinned board from the latest archive when the
  request is made.

If the owner rejects the shadow, the alternative with no methodology change is a
disclosure. The Edge copy would say that KTC Market's value curve sits above the board
between about ranks 40 and 400, so most mid-board assets read "KTC higher". That is a
product and UI decision, recorded here only as the fallback.

## 14. Limitations

* Historical boards are rebuilt with **today's code** on pinned past inputs (each
  board's own CSVs, scrape state and `config/weights`). That evaluates the current
  methodology on past data, not what production served on those dates.
* The outcome is KTC's own price path. There is no independent truth for dynasty value
  in the archive. Windows overlap, and the span is 2 months in-season.
* Theta uses KTC's base board as the coordinate. Any reference is a choice, and KTC base
  is chosen because KTC's natural experiment calibrates the 0-to-1 axis.
* C2 patches the registry in-process only, inside the research script. The oracle
  approximates the blend rather than replicating it.
* `dynasty_new` is not in the payload, and its labels are inferred to be identical
  because the board is shared.
