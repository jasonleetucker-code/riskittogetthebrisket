# Forward validation scoreboard — 2026-11-22

Research measurement, schema `forward-scoreboard/v1`. Changes nothing served. Mode `archive`; panel 2026-07-14 to 2026-11-21 (130 dates); code `e982547cf354ed184be6e490df121bf532547736`.
Archive: 160 bundles, sha256 `cf409ba1c193b390d59d5016404579f8ba6f4956bb29dadbfeff6addef74c08f`.

Signal: the gap `log((x+1)/(market+1))` at origin D. Outcome: the cohort-excess market return D→D+H. Cell: mean per-origin Spearman, then usable origins with a positive rho over usable origins. Each origin is its own cross-section, with at least 30 pairs. No origins are pooled.

Reproduce: `python scripts/forward_validation_scoreboard.py` (about 90 seconds; the temporary ledger needs about 350 MB of disk).

## Reading (analyst notes, added by hand)

- **The headline question is not answered by this run.** The committed archive holds no served board value (`rankDerivedValue`), so the board-edge test is `unavailable` at every horizon. This is the main result: the archive alone cannot show whether our board beats the market. The tool measures the board as soon as it is given a ledger that recorded the served board (`--ledger`, read-only copy). It was not run against any box-local ledger here.
- **The market mostly stays put.** Log price at D explains 0.95–0.98 of log price at D+30 (0.92–0.94 at 60 days, 0.87 at 90). A typical offensive price moved 3–8% over 30 days, and a typical IDP price under 2%. Any edge has to show up in that small residual.
- **The one consistent per-source result is a negative one.** When idpTradeCalc prices an asset above KTC, KTC's later cohort-excess return is lower, not higher: mean rho −0.097 at 30 days over offense and picks together, negative at all 4 origins (n = 416–514 per origin). Offense drives it: QB (−0.160), RB (−0.207) and TE (−0.203) are negative at every origin, and WR (−0.146) at 3 of 4 (n = 63–177 per group and origin). Picks go the other way (next item). The market moved away from that disagreement, not toward it. The size is small: mean partial R −0.14, and ΔR² over persistence 0.001–0.004. An ad hoc check on the same temporary ledger (exact reads at the fold dates) found idpTradeCalc's offense prices almost frozen across two of the four folds (441 of 442 unchanged from 07-14 to 08-13, and 434 of 435 from 10-12 to 11-11). But the sign is also negative in the two folds where they moved, so staleness alone does not explain it.
- **Picks lean the other way, on thin data.** idpTradeCalc pick prices above KTC's went with later KTC pick gains: rho +0.343, +0.592 and +0.048 (n = 82, 82, 35). The 09-12 origin had too few matched picks to count. Outcome attrition (no market price at the horizon) is 2–10% at 30 days and 8–14% at 60–90 days; pick names rolling over is part of it.
- **KTC's own modes are underpowered.** KTC Crowd and KTC Trades against KTC Market exist only from 2026-09-09, so they have two 30-day origins: no verdict. Their gaps are near mirror images, because Market is their blend. After the split, `ktcSfTep` equals `ktcCrowdSfTep` (flagged per fold in `identicalSourceSeriesAtOrigin`).
- **IDP is unmeasured.** Its market is idpTradeCalc, and the archive has no other IDP value source and no board, so there is nothing to score. (The archive's Draft Sharks CSVs are rank boards, and no bundle lists them as freshly fetched, so they are not ingested.) Realized points are unavailable (no committed offline data).
- **60 and 90 days have one or two origins**, so they carry no verdicts.

## Horizon 30 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-08-13 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.978 | 0.016 / 0.003 | 0.249 |
| 2026-08-13 → 2026-09-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.965 | 0.027 / 0.009 | 0.095 |
| 2026-09-12 → 2026-10-12 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 859 | 0.948 | 0.042 / 0.016 | 0.078 |
| 2026-10-12 → 2026-11-11 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 858 | 0.972 | 0.020 / 0.002 | 0.274 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.097 (0/4) | -0.160 (0/4) | -0.207 (0/4) | -0.146 (1/4) | -0.203 (0/4) | — | +0.328 (3/3) |
| ktc (keepTradeCut) | +0.005 (2/4) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | -0.100 (2/4) | — | -0.167 (0/1) |
| ktcCrowdSfTep (keepTradeCut) | +0.042 (1/2) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | +0.140 (1/2) | — | -0.167 (0/1) |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | +0.043 (1/2) | -0.017 (0/2) | -0.023 (1/2) | +0.092 (2/2) | +0.140 (1/2) | — | — |
| ktcTradesSfTep (keepTradeCut) | -0.042 (1/2) | +0.019 (2/2) | +0.023 (1/2) | -0.092 (0/2) | -0.140 (1/2) | — | +0.161 (1/1) |

— means no usable origin: no observation, the series is the market itself, or too few pairs. The JSON gives the reason for each origin.

- `idpTradeCalc (idpTradeCalculator)` ALL: negative and consistent (mean rho -0.097 over 4 non-overlapping folds; 4/4 folds negative; beat market-value benchmark in 1/4)
- `ktc (keepTradeCut)` ALL: no effect detected (mean rho +0.005 over 4 non-overlapping folds; 2/4 folds positive; beat market-value benchmark in 4/4)
- `ktcCrowdSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho +0.042 is reported for completeness only.
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2
- `ktcSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho +0.043 is reported for completeness only.
- `ktcTradesSfTep (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.042 is reported for completeness only.

## Horizon 60 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-09-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.943 | 0.038 / 0.014 | 0.062 |
| 2026-09-12 → 2026-11-11 | ktcCrowdTradesSfTep | ktcCrowdTradesSfTep | idpTradeCalc | 859 | 0.917 | 0.056 / 0.022 | 0.076 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.102 (0/2) | -0.188 (0/2) | -0.217 (0/2) | -0.183 (0/2) | -0.234 (0/2) | — | +0.576 (1/1) |
| ktc (keepTradeCut) | -0.009 (0/2) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | -0.104 (1/2) | — | — |
| ktcCrowdSfTep (keepTradeCut) | -0.005 (0/1) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | +0.116 (1/1) | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | -0.010 (0/1) | -0.085 (0/1) | -0.114 (0/1) | +0.093 (1/1) | +0.116 (1/1) | — | — |
| ktcTradesSfTep (keepTradeCut) | +0.005 (1/1) | +0.085 (1/1) | +0.114 (1/1) | -0.092 (0/1) | -0.115 (0/1) | — | — |

— means no usable origin: no observation, the series is the market itself, or too few pairs. The JSON gives the reason for each origin.

- `idpTradeCalc (idpTradeCalculator)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.102 is reported for completeness only.
- `ktc (keepTradeCut)` ALL: underpowered: 2 usable fold(s). A direction cannot be called from this; mean rho -0.009 is reported for completeness only.
- `ktcCrowdSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2
- `ktcSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2
- `ktcTradesSfTep (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2

## Horizon 90 days

| origin → horizon | offense market | pick market | IDP market | universe | R² log level, ALL | median abs log return, ALL / IDP | IDP prices unchanged |
|---|---|---|---|---|---|---|---|
| 2026-07-14 → 2026-10-12 | ktcSfTep | ktc | idpTradeCalc | 959 | 0.867 | 0.091 / 0.032 | 0.044 |

**Board: unavailable.** the ledger holds no canonical_board observation on any fold origin. The committed archive carries the raw scraper payload, not the served board (no rankDerivedValue; audit W04-F009), so archive mode cannot measure the board. Run --ledger against a ledger that recorded the served board (origins live:server / migration:*).

| series | ALL | QB | RB | WR | TE | IDP | PICK |
|---|---|---|---|---|---|---|---|
| idpTradeCalc (idpTradeCalculator) | -0.125 (0/1) | +0.037 (1/1) | -0.079 (0/1) | -0.221 (0/1) | -0.128 (0/1) | — | — |
| ktc (keepTradeCut) | -0.025 (0/1) | — | — | — | -0.141 (0/1) | — | — |
| ktcCrowdSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcCrowdTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcSfTep (keepTradeCut) | — | — | — | — | — | — | — |
| ktcTradesSfTep (keepTradeCut) | — | — | — | — | — | — | — |

— means no usable origin: no observation, the series is the market itself, or too few pairs. The JSON gives the reason for each origin.

- `idpTradeCalc (idpTradeCalculator)` ALL: no verdict: 1 usable origin(s), fewer than 2
- `ktc (keepTradeCut)` ALL: no verdict: 1 usable origin(s), fewer than 2
- `ktcCrowdSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2
- `ktcCrowdTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2
- `ktcSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2
- `ktcTradesSfTep (keepTradeCut)` ALL: no verdict: 0 usable origin(s), fewer than 2

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
