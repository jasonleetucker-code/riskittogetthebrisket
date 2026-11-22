# Forward validation scoreboard — 2026-11-22

Research measurement, schema `forward-scoreboard/v1`. Changes nothing served. Mode `archive`; panel 2026-07-14 to 2026-11-21 (130 dates); code `078e271d2c9c324601eb84a60480c28b1a12df93`.
Archive: 160 bundles, sha256 `cf409ba1c193b390d59d5016404579f8ba6f4956bb29dadbfeff6addef74c08f`.

Signal: the gap `log((x+1)/(market+1))` at origin D. Outcome: the cohort-excess market return D→D+H. Cell: mean per-origin Spearman, then usable origins with a positive rho over usable origins. Each origin is its own cross-section, with at least 30 pairs. No origins are pooled.

Reproduce: `python scripts/forward_validation_scoreboard.py` (about 90 seconds; the temporary ledger needs about 350 MB of disk).

## Reading (analyst notes, added by hand)

- **The headline question is not answered by this run.** The committed archive holds no served board value (`rankDerivedValue`), so the board-edge test is `unavailable` at every horizon. The tool measures the board once it is given a ledger that recorded it (`--ledger`, read-only copy). It was not run against any box-local ledger.
- **The market mostly stays put.** Log price at D explains 0.95–0.98 of log price at D+30 (0.92–0.94 at 60 days, 0.87 at 90). A typical offensive price moved 3–8% over 30 days, and a typical IDP price under 2%.
- **idpTradeCalc vs KTC: the raw sign is negative, and momentum explains part of it.**
  - Raw: at 30 days the mean rho is −0.097 over offense and picks, negative at all 4 origins (n = 416–514).
  - 2026-08-13: idpTradeCalc was stale at this origin. 99.8% of its values were unchanged since 07-14 (n = 518), and its gap tracked minus KTC's own prior 30-day return: rho −0.67 overall, and −0.88 to −0.93 for QB, RB, WR and TE.
  - 09-12 and 10-12: idpTradeCalc had updated (10.6% and 0.2% of values unchanged since the lookback date). The gap tracked the prior return less: −0.21 and −0.30 overall, and −0.16 to −0.54 by group.
  - Net of momentum: there are 3 origins with a lookback, because the first origin has none. The mean partial rho given KTC's prior return is −0.036 overall (2 of 3 negative), which is "no effect detected".
  - By group, a smaller negative partial remains at every origin for QB (−0.090), RB (−0.140) and TE (−0.102); WR is inconsistent (−0.058).
  - So momentum accounts for much of the raw sign, most clearly at 08-13 (QB: raw −0.106, partial −0.006), but not all of it. On three origins this supports only "the market did not move toward idpTradeCalc's disagreement". It does not support "idpTradeCalc is a contrary signal".
- **Size of the persistence increment.** Adding the gap to the log-price persistence regression raises R² by 0.0002–0.0013 per origin overall (mean 0.0008). The per-group means are 0.002–0.004. This is a different control from momentum.
- **Picks.**
  - Raw: when idpTradeCalc pick prices were above KTC's, later KTC pick moves were higher: rho +0.343, +0.592 and +0.048 (n = 82, 82, 35).
  - Only 08-13 has a momentum control (n = 82): partial +0.589, with the gap barely related to the prior return (rho −0.08). That origin's result is not momentum, but one origin gives no verdict.
  - Outcome attrition is 2–10% at 30 days and 8–14% at 60–90 days; pick names rolling over is part of it.
- **`ktc` is a TE-premium comparison here, not a source edge.** At 07-14 and 08-13, `ktc` equals `ktcSfTep` for every QB, RB and WR. Those cells are now unusable (0 distinct non-zero gaps). Its ALL cell still counts at those origins on 69 and 67 informative rows, nearly all TEs (zero-gap share 0.85 and 0.84).
- **KTC's own modes are underpowered.** KTC Crowd and KTC Trades against KTC Market exist only from 2026-09-09: two 30-day origins, no verdict. Their gaps are near mirror images, because Market is their blend. After the split, `ktcSfTep` equals `ktcCrowdSfTep` (`identicalSourceSeriesAtOrigin`).
- **Producer carry-forward.** The bundles for 2026-08-03 and 2026-08-06 did not freshly fetch idpTradeCalc, so those two (date, source) pairs are masked (`notFreshMasked`). Neither is a fold date, so no fold result changed.
- **IDP is unmeasured.** Its market is idpTradeCalc, and the archive has no other IDP value source and no board. (The archive's Draft Sharks CSVs are rank boards, and no bundle lists them as freshly fetched, so they are not ingested.) Realized points are unavailable (no committed offline data).
- **60 and 90 days have one or two origins**, so they carry no verdicts.

## Horizon 30 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-08-13 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.978 | 0.016 / 0.003 | 0.249 |
| 2026-08-13 → 2026-09-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.965 | 0.027 / 0.009 | 0.095 |
| 2026-09-12 → 2026-10-12 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 859 | 0.948 | 0.042 / 0.016 | 0.078 |
| 2026-10-12 → 2026-11-11 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 858 | 0.972 | 0.020 / 0.002 | 0.274 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

Gap vs outcome, mean per-origin Spearman (positive / usable origins):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.097 (0/4) | -0.160 (0/4) | -0.207 (0/4) | -0.146 (1/4) | -0.203 (0/4) | — | +0.328 (3/3) |
| ktc (keepTradeCut) | +0.005 (2/4) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | -0.100 (2/4) | — | -0.167 (0/1) |
| ktcCrowdSfTep (keepTradeCut) | +0.042 (1/2) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | +0.140 (1/2) | — | -0.167 (0/1) |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | +0.043 (1/2) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | +0.140 (1/2) | — | — |
| ktcTradesSfTep (keepTradeCut) | -0.042 (1/2) | +0.019 (2/2) | +0.023 (1/2) | -0.092 (0/2) | -0.140 (1/2) | — | +0.161 (1/1) |

— means no usable origin: no observation, the series is the market itself, too few pairs, or too few distinct non-zero gaps. The JSON gives the reason for each origin.

Net of momentum: mean partial Spearman of gap and outcome given the market's own prior-H log return (positive / origins with a momentum control):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.036 (1/3) | -0.090 (0/3) | -0.140 (0/3) | -0.058 (1/3) | -0.102 (0/3) | — | +0.589 (1/1) |
| ktc (keepTradeCut) | -0.027 (1/3) | -0.062 (1/2) | -0.062 (0/2) | +0.047 (2/2) | -0.058 (2/3) | — | — |
| ktcCrowdSfTep (keepTradeCut) | -0.004 (1/2) | -0.062 (1/2) | -0.062 (0/2) | +0.047 (2/2) | +0.111 (1/2) | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | -0.004 (1/2) | -0.062 (1/2) | -0.062 (0/2) | +0.047 (2/2) | +0.111 (1/2) | — | — |
| ktcTradesSfTep (keepTradeCut) | +0.004 (1/2) | +0.065 (1/2) | +0.062 (2/2) | -0.047 (0/2) | -0.111 (1/2) | — | — |


- `idpTradeCalc (idpTradeCalculator)` ALL: negative and consistent (mean rho -0.097 over 4 non-overlapping folds; 4/4 folds negative; beat market-value benchmark in 1/4). Mean zero-gap share 0.002; mean share unchanged since the lookback date 0.335. Momentum control: no effect detected net of momentum (mean partial rho -0.036 over 3 origins; 2/3 negative).
- `ktc (keepTradeCut)` ALL: no effect detected (mean rho +0.005 over 4 non-overlapping folds; 2/4 folds positive; beat market-value benchmark in 4/4). Mean zero-gap share 0.422; mean share unchanged since the lookback date 0.004. Momentum control: no effect detected net of momentum (mean partial rho -0.027 over 3 origins; 2/3 negative).
- `ktcCrowdSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho +0.042 is reported for completeness only. Mean zero-gap share 0.003; mean share unchanged since the lookback date 0.007. Momentum control: underpowered: mean partial rho -0.004 over 2 origins; 1/2 negative.
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho +0.043 is reported for completeness only. Mean zero-gap share 0.004; mean share unchanged since the lookback date 0.004. Momentum control: underpowered: mean partial rho -0.004 over 2 origins; 1/2 negative.
- `ktcTradesSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.042 is reported for completeness only. Mean zero-gap share 0.003; mean share unchanged since the lookback date 0.022. Momentum control: underpowered: mean partial rho +0.004 over 2 origins; 1/2 positive.

Predictor staleness: share of each series' values at D unchanged since its own value at the lookback date (D-H, snapped back):

| series | 2026-08-13 (vs 2026-07-14) | 2026-09-12 (vs 2026-08-13) | 2026-10-12 (vs 2026-09-12) |
|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | 0.998 (n 518) | 0.106 (n 473) | 0.002 (n 428) |
| ktc (keepTradeCut) | 0.002 (n 448) | 0.002 (n 478) | 0.007 (n 419) |
| ktcCrowdSfTep (keepTradeCut) | — | — | 0.007 (n 419) |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — |
| ktcSfTep (keepTradeCut) | — | 0.000 (n 394) | 0.008 (n 395) |
| ktcTradesSfTep (keepTradeCut) | — | — | 0.024 (n 419) |

## Horizon 60 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-09-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.943 | 0.038 / 0.014 | 0.062 |
| 2026-09-12 → 2026-11-11 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 859 | 0.917 | 0.056 / 0.022 | 0.076 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

Gap vs outcome, mean per-origin Spearman (positive / usable origins):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.102 (0/2) | -0.188 (0/2) | -0.217 (0/2) | -0.183 (0/2) | -0.234 (0/2) | — | +0.576 (1/1) |
| ktc (keepTradeCut) | -0.009 (0/2) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | -0.104 (1/2) | — | — |
| ktcCrowdSfTep (keepTradeCut) | -0.005 (0/1) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | +0.116 (1/1) | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | -0.010 (0/1) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | +0.116 (1/1) | — | — |
| ktcTradesSfTep (keepTradeCut) | +0.005 (1/1) | +0.085 (1/1) | +0.114 (1/1) | -0.092 (0/1) | -0.115 (0/1) | — | — |

— means no usable origin: no observation, the series is the market itself, too few pairs, or too few distinct non-zero gaps. The JSON gives the reason for each origin.

Net of momentum: mean partial Spearman of gap and outcome given the market's own prior-H log return (positive / origins with a momentum control):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.085 (0/1) | -0.134 (0/1) | -0.121 (0/1) | -0.064 (0/1) | -0.050 (0/1) | — | — |
| ktc (keepTradeCut) | -0.055 (0/1) | -0.125 (0/1) | -0.071 (0/1) | +0.010 (1/1) | +0.015 (1/1) | — | — |
| ktcCrowdSfTep (keepTradeCut) | -0.064 (0/1) | -0.125 (0/1) | -0.071 (0/1) | +0.010 (1/1) | -0.058 (0/1) | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | -0.071 (0/1) | -0.125 (0/1) | -0.071 (0/1) | +0.010 (1/1) | -0.058 (0/1) | — | — |
| ktcTradesSfTep (keepTradeCut) | +0.064 (1/1) | +0.125 (1/1) | +0.071 (1/1) | -0.008 (0/1) | +0.058 (1/1) | — | — |


- `idpTradeCalc (idpTradeCalculator)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.102 is reported for completeness only. Mean zero-gap share 0.002; mean share unchanged since the lookback date 0.002. Momentum control: no verdict: 1 origin(s) with a momentum control, fewer than 2.
- `ktc (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.009 is reported for completeness only. Mean zero-gap share 0.420; mean share unchanged since the lookback date 0.002. Momentum control: no verdict: 1 origin(s) with a momentum control, fewer than 2.
- `ktcCrowdSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2. Mean zero-gap share 0.005; mean share unchanged since the lookback date —. Momentum control: no verdict: 1 origin(s) with a momentum control, fewer than 2.
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2. Mean zero-gap share 0.005; mean share unchanged since the lookback date 0.003. Momentum control: no verdict: 1 origin(s) with a momentum control, fewer than 2.
- `ktcTradesSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2. Mean zero-gap share 0.005; mean share unchanged since the lookback date —. Momentum control: no verdict: 1 origin(s) with a momentum control, fewer than 2.

Predictor staleness: share of each series' values at D unchanged since its own value at the lookback date (D-H, snapped back):

| series | 2026-09-12 (vs 2026-07-14) |
|---|---|
| idpTradeCalc (idpTradeCalculator) | 0.104 (n 473) |
| ktc (keepTradeCut) | 0.002 (n 474) |
| ktcCrowdSfTep (keepTradeCut) | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — |
| ktcSfTep (keepTradeCut) | 0.003 (n 390) |
| ktcTradesSfTep (keepTradeCut) | — |

## Horizon 90 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-10-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.867 | 0.091 / 0.032 | 0.044 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

Gap vs outcome, mean per-origin Spearman (positive / usable origins):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.125 (0/1) | +0.037 (1/1) | -0.079 (0/1) | -0.221 (0/1) | -0.128 (0/1) | — | — |
| ktc (keepTradeCut) | -0.025 (0/1) | — | — | — | -0.141 (0/1) | — | — |
| ktcCrowdSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |

— means no usable origin: no observation, the series is the market itself, too few pairs, or too few distinct non-zero gaps. The JSON gives the reason for each origin.

Net of momentum: mean partial Spearman of gap and outcome given the market's own prior-H log return (positive / origins with a momentum control):

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | — | — | — | — | — | — | — |
| ktc (keepTradeCut) | — | — | — | — | — | — | — |
| ktcCrowdSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |


- `idpTradeCalc (idpTradeCalculator)` ALL: no verdict: 1 usable origin(s), fewer than 2. Mean zero-gap share 0.000; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktc (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2. Mean zero-gap share 0.836; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcCrowdSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.
- `ktcTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2. Mean zero-gap share —; mean share unchanged since the lookback date —. Momentum control: no verdict: 0 origin(s) with a momentum control, fewer than 2.

## Realized points

unavailable: No committed offline per-player realized fantasy points exist in the repository. src/nfl_data/realized_points scores nflverse weekly stat rows fetched over the network into a gitignored cache (src/nfl_data/cache.py); no tracked data/ file carries them, and this tool adds no network fetch.

## Independent validation (Hill registry)

Not registered; could not qualify as is:

- The offense and pick target is KTC (provider keepTradeCut), the training substrate of the OFFENSE Hill master. The registry's owner rule: KTC evidence alone is not independent for a KTC-trained curve.
- No preregistration was committed before this measurement. A registry target needs a committed, unedited preregistration that precedes its registry entry.
- This scores board and source gaps against later prices. A registry target is a pass/fail rule over champion and challenger Hill parameters.
- The IDP target, idpTradeCalc, also votes in the board.

## Caveats

- In-sample with the target: KTC Crowd and KTC Trades vote in the served board, KTC Market is their published blend, and idpTradeCalc votes too. The board's deviation from the market is still a fair test of whether the market moves toward the board, but agreement from shared lineage is not independent evidence.
- Per-source KTC rows (ktc, ktcSfTep, ktcCrowdSfTep, ktcTradesSfTep) are modes and calibration states of the target's own provider, not independent votes. KTC Market is the blend of Crowd and Trades, so a Crowd gap and a Trades gap against it are close to mirror images by construction.
- Market movement, not production: the outcome is the cohort-excess change in the market's own price. Realized points are reported separately (realizedPoints).
- Folds are non-overlapping and anchored at the panel's first date, so the fold count is small by construction. CE's verdict language needs 3 usable origins; below 2 no verdict is given.
- Survivorship: an asset that leaves the market's board before the horizon has no outcome. Each fold reports that attrition by reason.
- Day-granular: an observation dated D is 'as of D'. Archive scrape stamps are naive; the ledger records that rather than normalizing it.
- Momentum: a gap against a stale or slow source is close to minus the market's own past move, so short-term market momentum alone can make it look predictive. Read partialRhoGivenMomentum and unchangedSincePriorShare beside every rho. The momentum control is the market's raw prior-H log return; it is unavailable at the panel's first origin.
- Knowledge time: the as-of reads bound the observation date, not when a row was recorded. In --ledger mode a correction recorded after D would change D's predictor. A knowledge-cutoff read does not fit here: backfilled and migrated rows were recorded long after the dates they describe, so a cutoff at D would drop the whole archive history. The ledger's correction count is reported (inputs.ledgerCorrections in --ledger mode).
- Producer carry-forward: archive mode masks a source on a date whose bundle manifest does not list its CSV as freshly fetched (notFreshMasked). A --ledger run has no manifests, so no such mask applies there.
