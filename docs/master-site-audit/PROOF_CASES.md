# End-to-End Proof Results

Deliverable section 4. Twenty-four source-to-screen traces: a named asset or input,
walked stage by stage from the vendor row that entered the pipeline to the pixel the
user reads, with the actual number at every stage and the exact place the chain breaks
when it does.

- Audited HEAD `e96c06ef`; `findings.json` generated at `fb4a15a0`, 431 published
  findings + 1 refuted (9 P0 · 86 P1 · 180 P2 · 156 P3).
- **Every severity quoted here is the post-verification severity.** 45 findings went to
  independent refuters: 13 upheld, 31 rescoped, 1 overturned. `findings.json`
  `severityDriftUnderVerification` records 23 downward changes (5× P0→P1, 2× P0→P2,
  14× P1→P2, 2× P1→P3). Where a case rests on a rescoped finding, the authored severity
  is shown in parentheses and never used as the claim.
- Page-level observations come from Playwright request interception per
  `AUDIT_PROTOCOL.md`. Direct `:3000` and hand-rolled-proxy captures are void.

## Verdict vocabulary

| Verdict | Meaning |
|---|---|
| **TRACED — CLEAN** | Full chain walked with live numbers; every stage reproduces; no defect on this path. |
| **TRACED — BREAKS AT `<stage>`** | Full chain walked; a specific named stage emits a number the next stage should not have received. |
| **NOT RUN — BLOCKED BY DATA** | Chain cannot be executed in this container. The exact missing artifact is named. Not simulated. |
| **NOT RUN — FEATURE ABSENT** | There is no chain. Nothing exists to trace. |

`NOT RUN` is never softened into a partial result. Three cases (16, 17, 18) are blocked
by an empty ledger and one (21) has no implementation anywhere in the tree.

## Results at a glance

| # | Case | Asset / input | Verdict | Breaks at |
|---|---|---|---|---|
| 1 | Elite offensive player | Josh Allen (QB) | TRACED — CLEAN | — |
| 2 | Mid-tier offensive player | Travis Etienne (RB) | TRACED — BREAKS AT export | `exports/latest/dynasty_full.csv` |
| 3 | Low-confidence rookie | Eli Raridon (TE, R) · Avieon Terrell (DB, R) | TRACED — BREAKS AT label gate | `/edge` Sell panel |
| 4 | Elite IDP | Aidan Hutchinson (DL) | TRACED — CLEAN | — |
| 5 | Volatile IDP | Dallas Turner (DL) | TRACED — BREAKS AT Hampel + corridor clamp | blend stage 6/10 |
| 6 | **TE — premium + replacement** | **Tyler Conklin, Brock Bowers, Brevin Jordan, Grant Calcaterra (TE)** | **TRACED — BREAKS AT frontend override** | `useSettings.js:35` |
| 7 | Current rookie pick | 2026 Pick 1.01 | TRACED — CLEAN | — |
| 8 | Future projected pick | 2027 Early 1st · 2028 Late 1st · 2029 Early 1st | TRACED — BREAKS AT documentation | `CLAUDE.md` only |
| 9 | Offense-for-offense trade | Josh Allen ↔ Brock Bowers + Bo Nix | TRACED — BREAKS AT board identity | `/trade` client sum |
| 10 | Mixed offense–IDP trade | Carson Schwesinger (LB) → Patrick Mahomes (QB) | TRACED — BREAKS AT engine reachability | `include_idp` default |
| 11 | Multi-asset trade | 3-for-3 pick + offense + IDP package | TRACED — BREAKS AT value-adjustment monotonicity | `ktcAdjustPackage` |
| 12 | Real roster analysis | Jason's 57-player roster; Brent's direction label | TRACED — BREAKS AT asset-pool gate **and** ROS season sort | `BOARD_TOP_N_FILTER`, `_season_sort_key` |
| 13 | Trade Finder recommendation | Van Ginkel → Conner + McKinney | TRACED — BREAKS AT scoring normaliser | `board_gain_norm` |
| 14 | Central Buy/Sell recommendation | Brock Bowers | TRACED — no central tracker exists | 14 unreconciled emitters |
| 15 | Consensus Edge output | `/api/consensus-edge/*` | TRACED — CLEAN (honest 503) | — |
| 16 | Sharp Tracker transaction | — | **NOT RUN — BLOCKED BY DATA** | empty ledger |
| 17 | Insider Trading trend | — | **NOT RUN — BLOCKED BY DATA** | empty ledger + absent snapshot |
| 18 | Sharp roster-percentage player | — | **NOT RUN — BLOCKED BY DATA** | zero sharp rosters |
| 19 | Waiver candidate + FAAB | Brevin Jordan (TE) · Harold Landry (LB) | TRACED — BREAKS AT calibration | `_walk_waivers` |
| 20 | Perfect Draft result | Russini Panini, 31 picks / $685 | TRACED — BREAKS AT slot merge; optimizer absent | `mergeDraftCapitalTeams` |
| 21 | Schedule validation | — | **NOT RUN — FEATURE ABSENT** | no generator in repo |
| 22 | Public League historical claim | 2024 longest win streak | TRACED — BREAKS AT identity filter | `_RETIRED_OWNER_IDS` |
| 23 | Cached page + invalidation | `/draft` → `/api/draft-capital` | TRACED — BREAKS AT negative caching | `_get_ktc_rookies` |
| 24 | Failed / stale source | KTC live fetch failure | TRACED — BREAKS AT visibility | `/tools/source-health` |

**20 traced · 3 blocked by data · 1 feature absent.**

## What I re-ran live for this document

The stack was up (`:8000` API, `:3000` pages). These were re-executed today rather than
quoted from the workstream captures, and all reproduced to the digit:

| Command | Result |
|---|---|
| `GET /api/data` | 11,954,874 b, 1,092 `playersArray` rows |
| `POST /api/rankings/overrides?view=delta` body `{"tep_multiplier":1.15}` | 3,897,831 b; **135 value diffs (82 TE / 50 PICK / 3 other), 627 rank diffs, 654 tier diffs**; `isCustomized:false`, `tepMultiplierSource:"override"` |
| `GET /api/valuation/league-adjusted` | 709 factors, TE = 1.011595, `inactiveAxes:["tePremium","projectionCorroboration","receptionFit"]`, `replacementGap: null` on **8 of 8** positions |
| `POST /api/waiver/faab-recommend` `{"addPlayerName":"Brevin Jordan"}` | `resolvedAddValue: 1519.0`, standard bid $13 |
| Pick-tether check over all 72 current-year slot picks | **0 mismatches** |

---

# Cases 1–8 — asset valuation chains

## Case 1 — Elite offensive player: Josh Allen (QB, BUF)

**TRACED — CLEAN.** This is the chain working.

| Stage | Value | Where |
|---|---|---|
| Raw vendor rows | 18 source files carry him. `ktcSfTep` 9983 · `fantasyCalc` 10338 · `dynastyDaddySf` 10200 · `dynastyNerdsSfTep` 10256 · `otcffbSf` 92.7 (rank 3) · `yahooBoone` rank 1 · `dlfSf` rank 1 | `evidence/proof-cases/traces.json` |
| Identity | `identityMethod: canonical_id`, `identityConfidence: 1.0` | live `/api/data` |
| Normalization | 14 surviving source votes; `sourceRanks` 1–3 across every board | live |
| Blend | `blendedSourceRank` 1.5 → `_blendedValueUncapped` **9988** | live |
| Published | `rankDerivedValue` **9988**, `canonicalConsensusRank` 1, tier 1, `confidenceBucket` high, `sourceRankSpread` 2.0 | live |
| Page board (`tep=1.15` override) | **9988**, rank 1 — identical | re-run today |
| League-adjusted lens | factor 1.018366 → 10,171 rendered | `W07-F008` |
| Trade calculator | 9988, `adjA` 0 (no value adjustment) | `evidence/W08/symmetry.json` |
| Label surfaces | `/rankings` Edge = HOLD, Signal = "Consensus asset"; `signal-engine.js` HOLD; `terminal._evaluate_signal` HOLD | `evidence/W12/label-matrix.csv` row 1 |

**What works, plainly:** identity resolution, the 14-source blend, the rank stamp, the
tier, the confidence bucket, the page/API agreement, and the trade calculator all agree
on one number. Every label surface says the same thing.

**One real defect on this path, and it is small:** under the league-adjusted lens the
board exits its own declared 0–9999 scale — Josh Allen renders **10,171**
(9988 × 1.018366), Bijan Robinson 10,109 (`W07-F008`, P3, `evidence/W07/valuation-mode.json`).
`overlay.adjusted_rows` multiplies without renormalising.

---

## Case 2 — Mid-tier offensive player: Travis Etienne (RB)

**TRACED — BREAKS AT the downloadable export.**

| Stage | Value | Where |
|---|---|---|
| Raw vendor rows | 17 files. `ktcSfTep` 4367 · `idpTradeCalc` 4508 · `fantasyNavigatorSf` rank 67 · `fantasyProsSf` rank 74 · `draftSharksSf` rank 112 | `traces.json` |
| Normalized ranks | 14 votes, effective ranks 67–129 | live |
| Blend | `blendedSourceRank` 84.93 → **4081** | live |
| Published | `rankDerivedValue` 4081, rank 98, tier 17, confidence **medium** ("multi-source, moderate spread"), `sourceRankSpread` 62.0 | live |
| Page board | 4081, rank **95** (rank shifts 3 places because 82 TEs around him move — see Case 6) | re-run today |
| League-adjusted | factor 1.041554, rank 98 → 97 | live |
| **Export CSV** | `exports/latest/dynasty_full.csv` → **`Travis Etienne,4508,3,4367,4508`** | live file read |

**Where it breaks.** The `Composite` column of `dynasty_full.csv` is `_finalAdjusted`,
the raw pre-Hill scraper blend, not the board. Etienne exports at **4508** against a
board value of **4081** — 10.5% high. Josh Allen exports at 9983 against 9988.
`W29-F003` (P2) measured 805 name-matched rows, **exactly 1** identical, median ratio
1.0855 (p10 0.956, p90 1.260) — not a constant rescale, so no factor can correct it.
QBs and IDP read low (Lamar Jackson 7,631 vs 8,784; Carson Schwesinger 4,357 vs 5,908).
Evidence: `evidence/W29/export-vs-board.json`.

**What works:** every *in-app* export agrees with the screen — `/rankings` Export CSV and
Copy both go through `buildExportLines` using the identical expression as the render
(`rankings/page.jsx:764` vs `:1050`), and `dynasty_values.csv` is correctly labelled as
per-source raw vendor values (`W29-F003`, whatWorks).

---

## Case 3 — Low-confidence rookie: Eli Raridon (TE, R) and Avieon Terrell (DB, R)

**TRACED — BREAKS AT the label gate.** Two rookies, chosen to show both ends of the
confidence range: one priced and one the pipeline refuses to price.

### 3a. Eli Raridon — priced, low confidence, headline recommendation

| Stage | Value | Where |
|---|---|---|
| Sources | 16 vote | live |
| Blend | `rankDerivedValue` **2675**, rank 206, tier 33 | live |
| Confidence | bucket **low**; `sourceRankSpread` **332** — the widest of the ten rows the `/edge` Sell panel renders | live |
| Page board | 2372, rank 244 (−11.33%; he is a TE, so Case 6 applies) | re-run today |
| `/edge` Sell panel | **rank #1 of 10**, printed magnitude **±332** | `evidence/W27/te-rank-gap.json` |
| `/rankings` Edge column | SELL | `evidence/W12/label-matrix.csv` |

**Where it breaks — two independent defects on one row.**

1. **The printed number is not the described quantity.** `/edge` panels gate, sort and
   headline on `sourceRankSpread` (total dispersion across all 13 sources) under prose
   saying it is the KTC-vs-consensus gap. Raridon's actual `marketGapMagnitude` is
   **44.3**, not 332 — a 7.5× overstatement. Across the 20 rows the panels render, the
   spread/gap ratio runs 2.7× to 30.5×, median 5.6× (`W12-F004`, P1,
   `evidence/W12/edge-panel-vs-rankings.json`).
2. **Direction is never gated on confidence.** `marketAction`, `idpMarketAction` and
   `getPlayerEdge` read no confidence field at all — not `confidenceBucket`, not
   `sourceCount`, not `isSingleSource`, not `anomalyFlags`. On the live contract 356 rows
   carry BUY or SELL; **253 of them (71.1%)** sit on rows the same page badges low or no
   confidence, and 102 rest on a consensus of two sources or fewer (`W12-F007`, P1,
   `evidence/W12/label-matrix.csv`).

So the site's most confident-looking recommendation surface is headed by its
least-confident row, with a number 7.5× the gap it claims to show.

### 3b. Avieon Terrell — the pipeline correctly refuses

| Stage | Value | Where |
|---|---|---|
| Sources | 1 (`sourceCount: 1`, `isSingleSource: true`) | live |
| Anchor | `anchorValue` 1744 | live |
| Single-source haircut | `_blendedValueUncapped` = round(0.30 × 1744) = **523**, `singleSourceValuePenaltyApplied: true` | live |
| Published | **no `rankDerivedValue` key at all**; `values` = `{overall: null, finalAdjusted: null, displayValue: null, rawComposite: 497}`; `confidenceLabel: "None — unranked"` | live |

**This is correct behaviour and worth saying plainly.** 280 of 1,092 rows publish no
value rather than a floor value; 55 of those are rookies. `W02-F014` (P3) verified that
the only fabricated values anywhere on the board are the 12 synthetic 2029 picks, and
those are labelled in the payload and rendered as such.

**But the abstention is not respected downstream.** `W08-F006` (P2) measured **260 of
1,072** materialised rows addable to a `/trade` side at a silent value of 0 — once added,
the chip renders normally and contributes 0 to the side total, the gap, the verdict and
the CSV export with no warning. And `W11-F002` (P2, authored P0) showed unpriced free
agents drawing $22–$25 FAAB bids described as a "strong free-agent target" (Case 19).
`src/trade/finder.py` already solves this pattern with
`metadata.assetsUnpricedByBoard`; the client calculator has no equivalent.

---

## Case 4 — Elite IDP: Aidan Hutchinson (DL, DET)

**TRACED — CLEAN.**

| Stage | Value | Where |
|---|---|---|
| Raw vendor rows | 7 IDP files. `dlfIdp` rank 1 · `idpShow` rank 1 · `fantasyProsIdp` rank 1 · `draftSharksIdp` rank 41 · `idpTradeCalc` value-direct | `traces.json` |
| Ladder translation | original IDP ranks 1/1/1/41 → combined-pool effective ranks 34/34/34/345 | live `sourceRanks` |
| Scope routing | IDP Hill master | `CLAUDE.md` step 5 |
| Blend | 5 votes, `blendedSourceRank` 34.0 → **6362** | live |
| Corridor clamp | **not applied** (`marketCorridorClamp` absent) — pre-clamp blend sits inside the ±15% band | live |
| Published | 6362, rank 36, tier 6, confidence **high**, `sourceRankSpread` **0.0** | live |
| Page board | 6362, rank 36 — identical | re-run today |
| League-adjusted | DL factor 1.09776 → rank 36 → **31** | live |
| Edge label | `—` (no KTC rank exists for any IDP row) | `W27-F001` |

**What works:** the IDP ladder translation, the IDP-scope curve, the four-source
agreement, the clamp correctly declining to fire, and the DL scarcity factor moving him
up five places under the league lens.

**One documented gap on this path, not a defect in his number:** `/rankings` renders `—`
in the Edge column for **all 398 IDP rows**, because `_retail_source_keys()` returns
exactly `{'ktcSfTep'}` and KTC publishes no IDP. Meanwhile `/edge` runs a *second*
detector anchored on `idpTradeCalc` and labels 14 of the same players BUY/SELL
(`W27-F001`, P1, `evidence/W27/edge-rankings-dom.json`). The refusal is honest at the
field level; the two-surface contradiction is not.

---

## Case 5 — Volatile IDP: Dallas Turner (DL, MIN)

**TRACED — BREAKS AT the Hampel filter, then again at the corridor clamp.** This is the
clearest instance in the audit of a published number being a pure function of one source.

| Stage | Value | Where |
|---|---|---|
| Sources | 5 vote. Contributions: `idpTradeCalc` **4164** (anchor), then 2417, 1899, 1865, 673 | `evidence/W02/dallas-turner-sweep.json` |
| Hampel filter (K=2.75, floor 1000) | **ejects `idpTradeCalc` for being HIGH** | `W02-F002` |
| Blend after ejection | `_blendedValueUncapped` **1857** | live |
| Corridor clamp | drift = \|1856 − 4164\| / 4164 = 0.5543 > band 0.15 → clamped to 4164 × 0.85 = **3539** | live `marketCorridorClamp` |
| Published | `rankDerivedValue` **3539**, rank 124, tier 22, confidence **low**, `sourceRankSpread` 326.0 | live |
| Payload stamp | `{"applied":true,"originalValue":1856,"clampedValue":3539,"marketAnchor":4164,"marketSource":"idpTradeCalc","bandPct":0.15,"percentile":0.9,"cappedByMaxBand":true}` | live |
| Page board | 3539, rank 124 — identical | re-run today |

**Where it breaks — three ways, all measured.**

1. **The blend is not monotone in its own input.** Holding the other four contributions
   fixed and sweeping `idpTradeCalc`: the pre-clamp value rises smoothly to 2502.3 at a
   contribution of 3300, then **falls 25.8% to 1856.6 at 3400** — a 3.0% *increase* in one
   input. Above 3400 the blend is completely insensitive to the anchor (flat 1856.6 out
   to 5200). `W02-F004` (P2), sweep in `evidence/W02/dallas-turner-sweep.json`.
2. **The corridor clamp's per-bucket machinery is inert.** Live per-bucket P90 drifts are
   0.4805 / 0.5097 / 0.5228 — every one 3× the 0.15 asset-class cap — so
   `cappedByMaxBand` is true on **127 of 127** clamped rows. The percentile computation,
   the bucket split and `_MARKET_CORRIDOR_PERCENTILE` are dead weight; the live behaviour
   is a flat ±15% band around one source. `W02-F003` (P1).
3. **43.3% of ranked IDP rows are rewritten this way** — 127 of 293 eligible, mean move
   464.7 points (28.9% of pre-clamp), max 110.9%. On all 127, `rankDerivedValue` equals
   `round(marketAnchor × (1 ± 0.15))` to within 1: the other four sources contribute
   nothing. 126 of 127 anchor on `idpTradeCalc`.

**What works:** the clamp is correctly scoped — 0 offense rows and 0 pick rows clamped,
matching `CLAUDE.md`. The `marketCorridorClamp` stamp is complete and honest, which is
the only reason any of this was measurable from the payload.

---

## Case 6 — TIGHT END: premium and replacement (**the convergence case**)

**TRACED — BREAKS AT the frontend override, on every private page, for every tight end.**

Three of the nine surviving P0 findings converge here — `W07-F001`, `W08-F001`,
`W12-F002` — plus `W03-F001`, which is the same mechanism observed from the rankings
surface. All four reproduce today. Primary asset: **Tyler Conklin (TE)**, worst case on
the board. Supporting: Brock Bowers, Brevin Jordan, Grant Calcaterra.

### 6.1 The premium half — value stage, which is correct

Live per-source trace for Tyler Conklin from `GET /api/data`:

| Source | raw rank | eff rank | percentile | contribution | path | TE stamp |
|---|---|---|---|---|---|---|
| `ktcSfTep` | 445 | 445 | 0.88978 | 992 | `value_direct` | *(exempt — the anchor IS the TE++ board)* |
| `idpTradeCalc` | 802 | 802 | 1.00000 | 939 | `value_direct` | `tepNativeCorrectionApplied` |
| `fantasyProsSf` | 375 | 375 | 0.74950 | **1624** | `rank_hill` | `tepBoostApplied` |
| `fantasyNavigatorSf` | 399 | 399 | 0.79760 | **1548** | `rank_hill` | `tepBoostApplied` |
| `flockFantasySf` | 400 | 400 | 0.79960 | **1545** | `rank_hill` | `tepBoostApplied` |
| `pfkDynasty` | 435 | 435 | 0.86974 | **1448** | `rank_hill` | `tepBoostApplied` |
| `yahooBoone` | 344 | 344 | 0.68738 | 1273 | `rank_hill` | `tepNativeCorrectionApplied` |
| `draftSharks` | 408 | 646 | 1.00000 | 1868 | `rank_hill` | `tepNativeCorrectionApplied` |

Count-aware aggregation over those eight contributions (n=8 → trimmed mean-median) gives
`_blendedValueUncapped` **1451**, published as `rankDerivedValue` **1450**. The 1-point
drop is `derived = int(norm_val)` truncating where every neighbouring stamp rounds —
`W02-F010` (P3), 280 rows affected. Stamped alongside: `blendedSourceRank` 480.75,
`anchorValue` 1404, `values.rawComposite` 992.

This stage is **verified correct**. `W02-F013` (P3) recomputed
`_te_lift_under_ceiling(convert_te_value(percentile_to_value(p), 'base', 'tepp'))` from
the stamped percentile and reproduced the stamped contribution on **536 of 536**
converted TE votes. `W27-F009` (P3) audited all 85 TE rows × every source: **zero** rows
carry both `tepBoostApplied` and `tepNativeCorrectionApplied`; `ktcSfTep` carries neither
on all 73 of its TE rows. Measured multipliers: the eleven non-TEP sources take the real
curve (`dlfSf` 1.2091–1.4403, `fantasyProsSf` 1.2092–1.5915, `flockFantasySfRookies` up
to 1.6367); the TEP-native sources take exactly 1.1000 every time
(`evidence/W27/te-premium-once.json`).

Result: the TE board sits at median **0.943** of KTC's own TE++ values versus 0.920 for
non-TE offense — a 2.5-point residual, i.e. the alignment lands where ADR-015 says it
should (`W02-F013`).

### 6.2 The break — the page never asks for that board

`frontend/components/useSettings.js:35` sets `SETTINGS_DEFAULTS.tepMultiplier = 1.15`, a
finite number. `frontend/lib/dynasty-data.js:2020-2024` `tepMultiplierIsCustomized()`
returns true for **any** finite number. So `customized` is true with an **empty**
localStorage. The verifier confirmed in a real browser under the protocol's interception
topology: after `localStorage.clear()` + reload, the **only** POST the page makes is
`/api/rankings/overrides?view=delta` with body `{"tep_multiplier":1.15}`.

`src/api/data_contract.py:6939` gates the whole basis conversion on
`if not tep_multiplier_is_override:`. The flag is ON
(`src/api/feature_flags.py:141 te_basis_conversion=True`, `:367 LIVE`) and the curve is
loadable — it is simply never entered.

I re-ran that exact POST today. Response header fields:

```
isCustomized          = False
tepMultiplier         = 1.15
tepMultiplierDefault  = 1.15
tepMultiplierDerived  = 1.15
tepMultiplierSource   = override      ← the only field that changed
```

Diff against `GET /api/data`, 1,092 rows compared, today:

| Metric | Value |
|---|---|
| Rows with a different `rankDerivedValue` | **135** — 82 TE, 50 PICK, 3 other |
| Rows with a different `canonicalConsensusRank` | **627** |
| Rows with a different `canonicalTierId` | **654** |

Per-player, today:

| Player | `GET /api/data` | Page board (`tep=1.15`) | Understated |
|---|---|---|---|
| **Tyler Conklin (TE)** | **1450** (rank 469) | **1142** (rank 666) | **21.241%** |
| Brevin Jordan (TE) | 1519 (rank 451) | 1243 (rank 594) | 18.17% |
| Eli Raridon (TE, R) | 2675 (rank 206) | 2372 (rank 244) | 11.33% |
| George Kittle (TE) | 4088 (rank 97) | 3816 (rank 108) | 6.65% |
| Sam LaPorta (TE) | 5222 (rank 59) | 5021 (rank 65) | 3.85% |
| Brock Bowers (TE) | 9947 (rank 2) | 9876 (rank 2) | 0.71% |
| **Grant Calcaterra (TE)** | **1340** (rank 569) | **no value — drops out of the ranked set** | 100% |
| Josh Allen (QB, control) | 9988 (rank 1) | 9988 (rank 1) | 0.00% |

The direction is systematic and one-way: the flat 1.15 sits **below the entire measured
1.209–2.05 range**, so every tight end is under-priced on screen, deepest first.

Three TEs the canonical board prices (Grant Calcaterra 1340, Josh Oliver 1405, Thomas
Fidone 1392) fall out of the rendered board's ranked set entirely and display as 0
(`evidence/W07/te-divergence.json`, verified at ranks 924/973/1047).

### 6.3 What the user sees, and what everything else uses

The page shows **1,142** for Tyler Conklin. Every server-side engine reads
`latest_contract_data` — the un-overridden board — and uses **1,450**. I proved the
divergence live on the FAAB surface in the same session:

```
/rankings renders Brevin Jordan        1,243     (DOM-verified, W07-F001 verification (d))
POST /api/waiver/faab-recommend        1519.0    (resolvedAddValue, re-run today)
```

Same player, same session, two numbers, 22% apart, nothing on screen saying so.
`/trade` does it on one page: the client calculator sums the 1.15 board while
`POST /api/trade/simulate` on the same page answers from the canonical one — Sam LaPorta
renders **5,021** in the calculator and `5222` in the simulate response, 201 points apart
(`W08-F012`, P2, `evidence/W08/page_probe5.json`).

**No warning fires.** The "Custom Mix" badge (`frontend/app/rankings/page.jsx:170`) gates
on `rankingsOverride.isCustomized`, which the backend stamps **false** for a tep-only
override — the badge is structurally suppressed on exactly this state. `/settings`
positively asserts the opposite by labelling it "Default 1.15x".

**Blast radius, as corrected by verification** (`W07-F001` was rescoped upward on scope,
not downward on severity — it stays P0 and the verifier wrote "I tried to kill this and
could not"):

- **~30 pages, not 5.** `frontend/components/AppShell.jsx:61` calls `useDynastyData()` in
  `PrivateAppShell` — every private page hydrates the 1.15 board and feeds it to the
  app-wide PlayerPopup and global search.
- **11 routes, not 6.** Every league-scoped engine — `trade/suggestions`, `trade/finder`,
  `trade/simulate`, `angle/find`, `angle/packages`, `waiver/suggestions`,
  `waiver/faab-recommend`, `terminal`, `valuation/league-adjusted` — prices from
  `rankDerivedValue` on `/api/data` and therefore disagrees with the page.
- **`/draft` is a two-boards-on-one-page case**, not a 1.15 case:
  `frontend/app/draft/page.jsx:3930, 4201, 4484` fetch `/api/data` directly, so the
  RookieBoard shows the engine board while the popup on the same page shows the 1.15
  board.

### 6.4 The premium half breaks a second time — in rank space

The basis conversion operates on **values** (`data_contract.py:7674-7695`).
`marketGapDirection` is computed from **ordinal ranks** (`data_contract.py:3039-3056`)
and never sees it. `ktcSfTep` is the sole retail source and is a TE++ board; the
consensus it is differenced against is dominated by base-TE boards.

Live, `mean(consensusRank) − mean(retailRank)` by position
(`evidence/W27/te-rank-gap.json`):

| Position | n | mean diff | % retail_premium (⇒ SELL) |
|---|---|---|---|
| **TE** | 73 | **+41.60** | **94.5%** |
| PICK | 36 | +90.14 | 97.2% |
| WR | 193 | −6.83 | 35.8% |
| RB | 128 | −8.50 | 25.8% |
| QB | 66 | −24.69 | 6.1% |

Consequence on screen (`W12-F002`, **P0, upheld**): inside the top 250 the tight ends
split **32 SELL / 3 HOLD / 0 BUY**, and **all 32 SELL labels in the entire top 250 are
tight ends**. Whole board: 65 of 73 TEs with a verb are SELL, 4 are BUY. The `/edge` Sell
panel is 9 of its 10 rows TEs (Eli Raridon, Mason Taylor, Greg Dulcich, Hunter Henry, Pat
Freiermuth, Dalton Schultz, Max Klare, Travis Kelce, AJ Barner).
`evidence/W12/label-matrix.csv`.

So a user reading `/rankings` sees a tight end priced ~21% low **and** told to sell him.

### 6.5 The replacement half — measured, and it is not measured

This is the second half the case asks for, and the finding is that the replacement axis
is effectively absent. Live `GET /api/valuation/league-adjusted`:

| Position | `lineupScarcity` | `starterSeparation` | `eliteSeparation` | **`replacementGap`** |
|---|---|---|---|---|
| DL | 0.7672 | 6.035 | 18.81 | **null** |
| RB | 0.7078 | 14.825 | 20.48 | **null** |
| WR | 0.6340 | 6.215 | 15.75 | **null** |
| LB | 0.5985 | 6.655 | 18.89 | **null** |
| QB | 0.5918 | 10.880 | 20.73 | **null** |
| DB | 0.5737 | 4.200 | 6.75 | **null** |
| **TE** | **0.5580** | **2.040** | 12.025 | **null** |
| K | 0.4363 | 1.280 | 7.73 | **null** |

`replacementGap` is **null on 8 of 8 positions** — the replacement-level term is computed
by nothing. `waiverScarcity` is likewise null everywhere.

The only league adjustment a tight end receives is a **flat 1.011595 factor**, identical
for Brock Bowers (rank 2) and Tyler Conklin (rank 469) — confirmed live. And the
response's own `inactiveAxes` reads `["tePremium", "projectionCorroboration",
"receptionFit"]`: the TE axis is deliberately switched off in the overlay (correctly —
`W27-F009` proves this is the structural double-count guard). So:

- **replacement contributes +1.16%** to a TE's value, uniformly, from a scarcity index
  measured entirely in ROS log-rank units (`W29-F007`, P2);
- **the basis question moves the same TE by −21.24%**;
- and the two are never reconciled.

The one place the platform models replacement properly — BDVM's flex-aware dynamic
replacement — is dark: `data/bdvm/projections/` does not exist in this container, so all
four BDVM routes answer `status: "no_projection_snapshot"` with empty arrays
(`W13-F005`, P2, `evidence/W13/page-suppression.json`). When it *is* run offline it
under-scores TEs by **22.0%** because `src/nfl_data/realized_points.py` drops all six of
this league's per-reception yardage-band rules (`rec_0_4` 0.17 … `rec_40p` 1.92 against a
base `rec` of 0.08) — `W13-F001`, P1, `evidence/W13/reception-band-omission.txt`.

### 6.6 Case 6 summary

| Stage | Verdict |
|---|---|
| Vendor rows → identity → normalization | correct |
| TE basis conversion inside the blend | **correct and verified exactly once** on 536/536 votes, 85/85 rows |
| `GET /api/data` publication | correct — 1450 |
| **Frontend default → override POST** | **BREAKS** — 1142, −21.241% |
| Every server-side engine | still 1450 — the two never reconcile |
| Rank-space gap label | **BREAKS** — 32/32 top-250 SELL labels are TEs |
| League replacement adjustment | **not measured** — `replacementGap` null on 8/8 positions |
| User-visible warning | **none** — the badge that would fire is structurally suppressed |

Repair per `W07-F001`: set `SETTINGS_DEFAULTS.tepMultiplier` back to `null` (the
documented "derive from league" sentinel) and drop the `readSettings()` migration that
rewrites null to 1.15. The verifier's note: *"the repair the finding proposes is the only
one that makes the two agree without discarding ADR-015."*

---

## Case 7 — Current rookie pick: 2026 Pick 1.01

**TRACED — CLEAN.** The tether is exact.

| Stage | Value | Where |
|---|---|---|
| Raw vendor rows | one: `idpTradeCalc` **8013.0**. `ktcSfTep` does not price slot picks | `traces.json` |
| Blend | `_blendedValueUncapped` **8013**, `sourceCount` 1, `confidenceLabel: "Low — single pick source"` | live |
| Pick-year discount (Phase 3a) | **not applied** — year offset 0 → factor 1.0 | live (`pickYearDiscount` absent) |
| **Pick tethering (Phase 5.2b)** | overwritten with the merged rookie pool's #1 value: **7799** | live |
| Rookie pool #1 | **Jeremiyah Love (RB), `rankDerivedValue` 7799** | live |
| Published | `rankDerivedValue` **7799**, `canonicalConsensusRank` **null**, `canonicalTierId` **null** | live |
| League-adjusted overlay | **excluded** (anchor-slot-pick exclusion — `crossSurface.leagueAdjusted: null`) | `traces.json` |
| Page board | 7799 — identical | re-run today |
| `/draft` auction board | pick 1.01 `dollarValue` **$134.50**, `rookieName: "Jeremiyah Love"`, `currentOwner: "jstuedle"` | `evidence/W10/draft-capital-dynasty_main-auth.json` |

**I re-verified the tether across all 72 current-year slot picks today: 0 mismatches.**
Each `2026 Pick R.S` equals the `((R−1)×12 + S)`-th rookie's pool value exactly —
1.01 = 7799 (Love), 1.02 = 6160 (Carnell Tate), 1.03 = 5597 (Fernando Mendoza),
2.01 = 3544. The 72 priced picks' dollar values sum to exactly **$1200.00**.

**What works:** the tether, the discount correctly not firing, the overlay exclusion, the
honest single-source confidence label, and the $1200 normalisation.

**Known limitation on this path, honestly stamped:** only 2 of 21 sources cast any vote
on any pick, and all 72 slot picks are single-source — a fresh KTC pick value sits unread
in `canonicalSiteValues` while the anchor is `idpTradeCalc` alone (`W05-F006`, P1).
And rookie pick values are point estimates everywhere on the live path: no
mean/median/P10/P90/starter%/bust% distribution is served by any reachable route
(`W10-F012`, P2, Blocked by data).

---

## Case 8 — Future projected rookie pick: 2027 Early 1st, 2028 Late 1st, 2029 Early 1st

**TRACED — BREAKS AT documentation only.** The code is correct; `CLAUDE.md` describes
behaviour that was fixed.

| Pick | Sources | `_blendedValueUncapped` | `pickYearDiscount` | Published | Rank | Confidence |
|---|---|---|---|---|---|---|
| 2027 Early 1st | `ktcSfTep` 7047, `idpTradeCalc` 7052 | 7050 | **absent** | **7049** | 28 | High — picks agree within 15% |
| 2028 Late 1st | `ktcSfTep` 4026, `idpTradeCalc` 4132 | 4079 | **absent** | **4079** | 100 | High |
| **2029 Early 1st** | `idpTradeCalc` 5034 (a **clone** of the 2028 row) | 5034 | **0.53** | **2668** | 207 | Low — single pick source |

All three identical on the page board (re-run today).

**Where it breaks.** `CLAUDE.md`'s pipeline section (step 12) says the multiplicative
future-year discount lowers 2027/2028 picks. It does not.
`_apply_pick_year_discount_to_blend` gates on `_SYNTHETIC_FAR_FUTURE_PICK_NAMES`, so a
vendor-priced year is skipped. On the live board **exactly 12 rows carry
`pickYearDiscount`, all 2029, all 0.53** — I confirmed this today. The market's own term
structure is preserved instead: 2027 Early 1st (7049) sits **above** 2026 Pick 1.02
(6160). `W02-F007` (P3): the code fix shipped the same day as the audit that found it;
the doc was not updated.

**The one genuine fabrication on the whole board is here, and it is labelled.**
`_inject_far_future_pick_sources` clones the 12 2028 rows verbatim and multiplies by
0.53: 5034 × 0.53 = **2668**, matching the published value exactly. Those rows are ranked
and visible (2029 Early 1st at rank 207). They carry `confidenceLabel: "Low — single pick
source"`, `isSingleSource: true`, and `sourceAudit.allowlistReason` = *"synthetic
far-future tier: no vendor prices picks this far out; cloned from the nearest published
year and year-discounted"*, which `board-sections.jsx:233` renders (`W02-F014`, P3).

**Side effect worth knowing:** the clone loses `ktcSfTep` (present on 2028, absent on
2029), so the only surviving vote is `idpTradeCalc`. And all 18 2029 rows carry no
`_rawComposite`, so in the trade calculator's "Raw" value mode they contribute 0 while
showing a non-zero value in "Our Value" (`W08-F006`, P2).

---

# Cases 9–11 — trades

## Case 9 — Offense-for-offense trade

**TRACED — BREAKS AT board identity.**

Trade: **A = Josh Allen · B = Brock Bowers + Bo Nix.**

| Stage | Side A | Side B | Where |
|---|---|---|---|
| Board values (`/api/data`) | 9988 | 9947 + 6572 = 16519 | live |
| Value adjustment (`ktcAdjustPackage`) | 0 | 0 | `evidence/W08/symmetry.json` |
| Gap | **−6531** | | |
| Verdict | **"Major gap"** | | |
| Reversed (B↔A) | rawA 9988, rawB 16519, gap −6531 | | |
| Symmetry | **exact** | | |

**What works, and it was tested hard.** `W08-F009` (P3) verified A→B / B→A verdict
symmetry on 20 real trades **and 40,000 random ones** — exact. `W08-F010` (P3) verified
the KTC value-adjustment Python↔JS parity: **0 differences** over the 139-trade fixture,
identical RMS 26.59 against KTC's captured displays. `W08-F013` (P3) verified
duplicate-asset protection holds on both the manual and bulk-import paths.

**Where it breaks.** The calculator is not summing the canonical board. Brock Bowers is
**9947** on `/api/data` and **9876** on the page the calculator runs on. Two boards are
on screen simultaneously: the client sum uses the 1.15 board while
`POST /api/trade/simulate` — invoked from the same page — answers from
`latest_contract_data`. Sam LaPorta: **5,021** rendered, **5222** returned, 201 points
apart, both visible (`W08-F012`, P2; `W08-F001`, **P0, upheld**, 129 of 809 players
repriced by up to −21.2%).

Three further reachable defects on the offense-only path:

- **"Raw" value mode is not comparable across asset classes** — one dropdown click turns
  a FAIR trade into UNFAIR and flips which side wins: the same trade reads
  `5,021 vs 5,222 · Gap 201 · FAIR · Side B wins by 4%` in Our Value and
  `5,564 vs 4,180 · Gap 1,384 · UNFAIR · Side A wins by 25%` in Raw
  (`W08-F007`, P1, `evidence/W08/page_probe5.json`).
- **Current-year picks cannot be found in the only search box** — the exclusion is a
  hardcoded `/^2026\b/` regex rather than the contract's `currentDraftYear`
  (`W08-F004`, P1).
- **"Copy KTC URL" hardcodes `tep=0`**, sending a TE-premium league's trade to KTC's
  non-TE-premium board (`W08-F008`, P2).

---

## Case 10 — Mixed offense–IDP trade

**TRACED — BREAKS AT engine reachability.** The cross-market arithmetic is sound; the
route that can express it is unreachable from the UI.

Trade: **give Carson Schwesinger (LB, IDP) → receive Patrick Mahomes (QB, offense)**, via
`POST /api/angle/find`.

| Leg | Board value | Market value | Market source | Gain |
|---|---|---|---|---|
| Give — Carson Schwesinger (LB) | **5908** | 5667 | `idpTradeCalc` | — |
| Receive — Patrick Mahomes (QB) | **7461** | 6298 | `ktcSfTep` | +1553 board (+26.29%), +631 market (+11.13%) |
| | | | | `arb_score` 15.15 |

Evidence: `evidence/W27/angle-find-idp-crossmarket.json`. Alternatives returned on the
same call: Lamar Jackson (+2876 board, arb 15.08), Jalen Hurts (+1275), 2026 Pick 1.01
(+1891, market source `ktc`).

**Why the two markets are comparable at all — measured, not assumed.** Of `ktcSfTep`'s
501 rows, **475 (94.81%)** also appear on the 911-row `idpTradeCalc` board; pooled value
ratio median **0.997** (p10 0.8864, p90 1.0826); both boards top out at 9999
(`evidence/W27/cross-market-overlap.json`, `W27-F008` P3).

**Where it breaks — four ways.**

1. **`/angle` can never return an IDP player in a counter-package.** The engine defaults
   `include_idp=False` and the page never sends the flag (`W27-F003`, P1). The trace
   above is reachable only by calling the API directly.
2. **The Trade Finder produces zero mixed-market trades.** `metadata.mixedMarketTrades:
   **0**` on the live 40-trade run for Jason (`evidence/W27/finder-idp-coverage.json`).
3. **No defensive back can be proposed to anyone.** `build_asset_pool_from_contract`
   returns exactly 150 assets — WR 41, QB 28, RB 26, PICK 23, TE 18, DL 7, LB 7,
   **DB 0**. The first DB in the 812-row pool is Caleb Downs at board rank 167. IDP is
   9.33% of the asset pool against **42.86%** of the starting lineup (9 of 21 slots).
   `W27-F002` (P1, authored P0), `evidence/W27/trade-suggestions-12-teams.json`.
4. **The ±5% cross-market plausibility gate is narrower than the boards' own measured
   disagreement** (p10 0.886 – p90 1.083), and stamps no uncertainty band
   (`W27-F004`, P2).

**What works:** `W09-F014` and `W27-F010` (both P3) verified that the finder's per-market
gate is live and the prior audit's "finder is offense-only" claim does **not** reproduce
at HEAD — `positions_from_contract` fixes the gate, IDP assets trade, and the
IDP-blindness warning fires. `marketCoverage` on the live run is
`{ktcSfTep: 132, ktc: 18, idpTradeCalc: 150}`, 100%.

---

## Case 11 — Multi-asset trade (3-for-3, picks + offense + IDP)

**TRACED — BREAKS AT value-adjustment monotonicity.**

Trade, all values live board values:

| Side A | | Side B | |
|---|---|---|---|
| 2026 Pick 1.04 | 5320 | T.J. Hockenson (TE) | 3107 |
| Jadarian Price (RB) | 4286 | 2026 Pick 2.09 | 2846 |
| Dont'e Thornton (WR) | 1509 | Kaden Elliss (LB, IDP) | 1869 |
| **raw total** | **11115** | **raw total** | **7822** |
| value adjustment | **+1610** | value adjustment | 0 |
| **gap** | | | **+4903** |

**Where it breaks.** Add **Boye Mafe (1,235 board points)** to side A — a positive-value
asset, to the side already ahead:

```
before:  (11115 + 1610) − (7822 + 0) = +4903
after:   (12350 +    0) − (7822 + 0) = +4528     ← the gap FELL by 375
```

A's value adjustment collapses to 0 and A's position gets **worse** by adding a real
asset. Measured over 40,000 random 1-3 vs 1-3 trades from the live board: **772 (1.93%)**
got worse for A after adding a real asset; **27 of those crossed a meter-verdict label
boundary**. Restricting to multi-asset shapes only (2-3 per side, so the 1v1 suppression
rule cannot explain it): **687 of 60,000 (1.15%)** still violate.

Verdict-flipping example: A = Daiyan Henley (1923) vs B = 2028 Late 2nd (2785), gap −862
= **SLIGHT EDGE**; add Omar Speights (894) to A → gap −1219 = **UNFAIR**.

`W08-F003` (P1), `evidence/W08/monotonicity-full.json`.

**Root cause, stated precisely:** the value adjustment is folded into the side totals
(`adjusted = raw + adjustment`) and then differenced, but `ktcAdjustPackage` is a step
function of the piece multiset with three discontinuities (1v1 suppression, the
`|value|/(totalA+totalB) < 0.033` display floor, and the branch switch on `h` vs `y`).
KTC itself displays the value adjustment as an advisory "add this much to even it out"
badge, **not** as an addend to a side total.

**What works:** the gap is exactly A/B symmetric (`W08-F009`), so the non-monotonicity is
not an ordering artifact — it is real.

**Server-side counterpart, traced:** `POST /api/trade/simulate` for Brock Bowers →
Jonathan Taylor + Patrick Mahomes returns a coherent before/after/delta —
`totalValue` 171,279 → 175,283 (equity **+4004**), TE count −1 / value −9,950,
QB +7,482, RB +6,472, `verdict: "lean decline"`, `posture: "rebuilder"`
(`evidence/W09/simulate-bowers.json`). Note the simulate response prices Bowers at
**9950**, not the board's 9947 — that is `offense_only_value`, a second value concept
shipped under the same field name (`W29-F001`, P1: Travis Hunter renders **5,637** on
`/trade` and **4,401** on `/rankings`; 19 of 51 asset legs disagree with the board in
default market mode).

---

# Cases 12–14 — roster analysis and recommendations

## Case 12 — A real roster analysis: Jason's 57-player roster

**TRACED — BREAKS AT the asset-pool gate.**

| Stage | Value | Where |
|---|---|---|
| Input | 57 players + 62 picks, from Sleeper roster 1 (`ownerId 468418790212759552`) | `evidence/W09/suggestions-Jason.json` |
| `starterNeeds` derived from league | QB 2, RB 3, WR 4, TE 2, DL 3, LB 3, DB 3 (21 slots) | live payload — **correct** |
| Asset-pool gate | `BOARD_TOP_N_FILTER` 150 → `rosterMatched` **16 of 57** | live payload |
| `rosterAnalysis.rosterSize` reported to UI | **16** | live payload |
| `starterCounts` returned | QB 2, RB 1, WR 4, TE 1, DL 1, LB 3, **DB 0** | live payload |
| `needPositions` | RB, TE, DL, **DB** | live payload |
| Actual DB depth on the roster | **8** | `W27-F002` |
| Terminal `teamAggregates.totalValue` | **171,495** = exact sum of `rankDerivedValue` over rostered players | `evidence/W20/terminal-12teams-summary.json` |
| Portfolio panel legend | Starters 97,497 / Bench 73,998 / **Picks 143,067** | `W20-F004` |

**Where it breaks — four measured defects.**

1. **The engine analyses 28% of the roster and says nothing about it.** Across all 12
   teams `rosterMatched` runs 3–21 of 44–58 provided. Eight of 12 teams
   (Ed, Ty, Collin, Roy, Joey, Kich, jstuedle, Blaine) get `totalSuggestions: 0`, with no
   error, warning or "insufficient coverage" note in the payload. `positionalUpgrades` is
   0 for all 12. `W09-F001` (P1, authored P0), `evidence/W09/per-team-tabulation.json`.
2. **It reports a shortage at the one position nobody is short at.** All 12 teams are
   told to target DB; actual DB depth per team is 5–9 against 3 required starters.
   `starterCounts` only counts pool members, and no DB is ever in the pool
   (`W27-F002`, P1).
3. **"Roster strength" is a raw sum with no lineup solve.** `totalValue` is exactly
   `sum(rankDerivedValue)` over the roster's player names — no starter/depth weighting,
   no positional replacement level, and all 216 league picks excluded. A team with 28 IDP
   bench bodies and no startable RB scores identically to one with the same total
   concentrated in starters. `W20-F003` (P1). *`src/api/terminal.py:1206-1231` documents
   the pick exclusion honestly, including its measured 22.5% league-wide magnitude.*
4. **The panel's own numbers do not add up.** Total Value 171,495 sits above a legend
   summing to **314,562** — 1.83× the stated total — because the merge takes `totalValue`
   from the server (picks excluded) and `pickValue` from the client (picks included).
   `W20-F004` (P1), `evidence/W20/pick-join-divergence.txt`.

Additionally, `frontend/lib/portfolio-insights.js` prices **every** current-year pick at
zero — 15,626 per team, 187,512 league-wide, 39% of all pick capital — because it is the
one pick join in the tree that ignores `contract.pickAliases` (`W20-F005`, P1).

### The direction label the same roster analysis produces — two P0s

The `/league` → Trade Deadline board is the roster-analysis output a user acts on, and on
live data it inverts:

| Stage | Value | Where |
|---|---|---|
| `data/ros/team_strength/latest.json` | **Brent rank 1 of 12**, percentile **1.0** | `W20-F002` |
| Terminal cross-check | Brent `totalValue` **176,314** — highest of 12 | `evidence/W20/terminal-12teams-summary.json` |
| `data/ros/sims/latest_playoff.json` | **8 of 12 owners**. Brent, Kich, Blaine, jstuedle **absent** | `W20-F002` |
| `po = float((playoffs.get(owner) or {}).get('playoffOdds') or 0.0)` | absence → **0.0**, indistinguishable from a simulated 0% | `W20-F002` |
| Rendered | `STRENGTH 100.0%` in the column immediately left of **"Seller — sell aging win-now players. Prioritize 2026/2027 picks and 23-or-younger upside."** | `evidence/W20/ros-trade-deadline.json` |

`W20-F002`, **P0, upheld** (and `W17-F002`, **P0, upheld**, the same defect from the ROS
side).

**Why only 8 owners were in the sim at all:** `sorted(snapshot.seasons, key=luck._season_sort_key)`
passes `SeasonSnapshot` **objects** to a function typed `(_season_sort_key(season: str) -> int)`.
`int(season)` raises `TypeError`, which is swallowed by `except (TypeError, ValueError):
return 0`, so every season sorts equal, `sorted()` is a stable no-op, and `[-1]` returns
the **last** element of a newest-first list — the **oldest** season. On seasons
`["2026","2025","2024"]` the sims resolve `current_season = 2024`, status `complete`,
8 owners. The entire 2025 season is loaded and ignored. Proof: the sim's `expectedWins`
reproduce the 2024 **final records** exactly for all 8 owners — Ty 9.0/9-4,
MaKayla 8.0/8-5, Jason 7.0/7-6, Roy 7.0/7-6, Joey 6.0/6-7, Eric 5.0/5-8, Ed 5.0/5-8,
Collin 4.0/4-9. `W17-F001`, **P0, upheld**, `evidence/W17/season-sort-bug.txt`.
Every other module in the repo (`luck.py:193`, `power.py:79`, `weekly_recap.py:613`)
passes `s.season` correctly; only `src/ros/` does not.

**What works:** `starter_needs_for_league` correctly derives the per-league lineup from
`roster_positions`; `metadata.rosterMatched`/`rosterProvided` are honestly stamped, which
is the only reason the shortfall was measurable at all. And `src/api/gameplan.py` handles
the missing-owner case **correctly on the same data** — it stamps
`oddsSource: "owner_not_in_simulation"`, leaves `playoffOdds`/`championshipOdds` null, and
emits a note that the two competitiveness scales are not comparable (`W20-F002`,
whatWorks). The fix already exists in the codebase, one module over.

---

## Case 13 — A Trade Finder recommendation

**TRACED — BREAKS AT the scoring normaliser.** Live top-ranked result for Jason,
`POST /api/trade/finder`:

```
GIVE     Andrew Van Ginkel   DL MIN   board 1709   market 2011 (idpTradeCalc rank 74)
RECEIVE  Chamarri Conner     DB KC    board 1502   market 1329 (rank 129)
         Xavier McKinney     DB GB    board 1441   market 1334 (rank 128)

giveModelTotal 1709   receiveModelTotal 2943   boardDelta +1234 (+72%)
giveKtcTotal   2703   receiveKtcTotal   2663   ktcDelta      +40  (opponent +1.5%)
arbitrageScore 35.09  confidenceScore 0.2  confidenceTier "low"  edgeLabel "Strong Edge"
```

`metadata`: `valueSource: "rankDerivedValue"`, `assetPoolSize` 300,
`totalCandidatesEvaluated` 7045, `totalQualified` 6073, `returned` 40,
`marketCoveragePercent` 100.0, `assetsUnpricedByBoard` **186**.
`evidence/W09/finder-Jason.json`.

**What works, and it is the migration the prior audit asked for.** The finder now reads
the canonical board (`valueSource` stamped), assets the board declines to price leave the
universe and are **counted** rather than vanishing — the payload carries the warning
*"186 assets carry a scraper value above 800 but no canonical board value, so they are
not tradeable here. They are unpriced, not worthless."* The per-market IDP gate is live
(`W09-F014`, `W27-F010`, both P3, verified).

**Where it breaks — four defects, all on this one result.**

1. **Every returned trade is a 1-for-2.** All 480 trades across all 12 teams are 1-for-2;
   zero 1-for-1, zero 2-for-1. Running with `max_results=100000` for Jason yields 5,562
   qualified trades — 5,399 1-for-2, 163 1-for-1, **zero** 2-for-1 — and the first 1-for-1
   appears at rank **2,159**. Cause: `board_gain_norm = board_delta / give_model` divides
   by the give side only, so shrinking the give side inflates the dominant term
   (`f_board_edge = board_gain_norm × 50`) without bound, against a flat
   `f_simplicity = −3`. Best 1-for-2 score 35.09 vs best 1-for-1 21.38.
   `W09-F002` (P1).
2. **"Arbitrage score" is not arbitrage.** It is 80% own-side gain and 20% opponent
   appeal, so it ranks lopsidedness, not the market/board gap it is named for
   (`W09-F009`, P2). Visible above: `boardEdge` 36.1 vs `ktcAppeal` 0.45.
3. **"Strong Edge" and "low confidence" ship together, and the high tier is
   unreachable.** The confidence tier measures the scraper's 3-source site count against
   a 5-source baseline while the board blends up to 14 — so `confidenceTier: "high"` is
   structurally impossible (`W09-F008`, P2).
4. **No dominance pruning.** The 40 returned trades for Jason are built from only **4
   distinct give-side assets**, one of which appears in 20 of them (`W09-F012`, P2).

And structurally: **draft picks can never appear in a finder or suggestion result** —
both engines resolve rosters from `sleeper.teams[].players`, which contains zero picks
(`W09-F003`, P1). `metadata.myRosterSize` reports the post-filter count, understating a
57-man roster as **34** (`W09-F010`, P3) — visible in the payload above.

---

## Case 14 — A central Buy/Sell recommendation: Brock Bowers

**TRACED — and the trace establishes there is no central tracker.**

One player, one page load, three surfaces:

| Surface | Verdict shown | Threshold used |
|---|---|---|
| `/rankings` Edge column (`marketAction`) | **HOLD** — "Consensus asset" | `MARKET_GAP_MIN_DIFF` = 10 ranks |
| Popup opened *from that row* (`getPlayerEdge`) | **"Sell High — KTC ranks 5 spots higher than consensus — market overvalues"** | `MIN_EDGE_RANK_GAP` = 3 ranks |
| Backend stamp | `marketGapDirection: retail_premium`, `marketGapMagnitude: 5.36` | `> 0` |

Rendered DOM, verified in a real browser (`evidence/W12/popup-vs-row.json`,
`popup-Brock-Bowers.png`):

```
row:    2  Tier 1 | Brock Bowers | LV · 23 | TE | 1 | 9.9 | 9,876 | S+ | 14/15 High  HOLD  Consensus asset
popup:  Sell High — KTC ranks 5 spots higher than consensus — market overvalues
```

**83 of 1,072 rows** fall in the `[3,10)` band and therefore show HOLD in the table and a
full Buy Low / Sell High card in the popup opened from it — including 7 of the top 15
(Bowers #2, Bijan Robinson #3, Drake Maye #5, Jahmyr Gibbs #6, Trey McBride #8, Lamar
Jackson #11, Joe Burrow #13). `W12-F001` (P1, authored P0). Justin Herbert inverts:
row HOLD, popup **"Buy Low — Consensus ranks 4 spots higher than KTC"**.

**There is no arbiter.** `W12-F003` (P1) enumerated **16 independent directional
emitters, 14 reachable**, of which **five apply different cutoffs to the same
retail-vs-consensus quantity**: `>0` (backend stamp), `≥3` (popup + `/league` Edge Map),
`≥10` (`/rankings` Edge column), `sourceRankSpread≥20 AND rank≤250` (`/edge` panels + the
`/rankings` rail), and `≥10` on a different source set (`/edge` IDP tab). None shares
state, imports another, or reads another's output. Evidence:
`evidence/W12/label-families.json`, `evidence/W12/label-matrix.csv`.

Both candidate arbiters fail: `src/consensus_edge/*` 503s on every route (flag off — see
Case 15), and `src/news/unified_signal_engine.py` — 352 lines whose docstring calls it
*"the single entry point for every BUY/SELL/HOLD decision emitted to users"* — is
imported by nothing outside tests and one audit script (`W12-F012`, P2).

**Two further live facts about this surface:**

- **Every rule engine returns HOLD for every rostered player** — `signal-engine.js` and
  `terminal._evaluate_signal` both answer *"Stable — no movement, volatility, or news
  triggers"* for **665 of 665** rostered players, because `data/rank_history.jsonl` does
  not exist, and no surface says the evidence is missing (`W12-F011`, P2).
- **The terminal home page prescribes opposite actions from one input** — the Movers panel
  calls a riser a sell-high candidate while the Signals panel directly below calls the
  same rise a BUY (`W12-F009`, P2, authored P1).

**What works:** both `marketAction` and `getPlayerEdge` read the same
`effectiveSourceRanks`/`marketGapMagnitude`, so the **direction** never disagrees — only
the minimum magnitude does, which makes the repair small. `_compute_market_gap` correctly
excludes the retail source from the consensus mean, so there is no trivial
self-comparison, and stamps `none`/`null` honestly when either side is empty.

---

# Cases 15–18 — market intelligence

## Case 15 — A Consensus Edge output

**TRACED — CLEAN.** The chain terminates in an honest, deliberate refusal.

| Stage | Result | Where |
|---|---|---|
| Feature flag | `consensus_edge` default **False** | `src/api/feature_flags.py` |
| All five routes | **503** | `W25-F001`, `evidence/W14/health.json` |
| `/consensus-edge` page | explicit switched-off state, not a generic error | `evidence/W12/page-consensus-edge.png` |
| Reason recorded | its top-20 buy list did not beat a random draw | `docs/consensus-edge/DECISIONS.md` |

**This is the one label family in the audit that refuses rather than fakes.**
`W12-F015` (P3) verified it explicitly: `/consensus-edge` and `/bdvm` are the only two
surfaces with a documented, calibrated-or-honestly-uncalibrated score, and both degrade
to specific truthful empty states.

The engine itself was verified against its own arithmetic while off:

- `W14-F004` (P3) — the leave-one-out fair value is genuinely anchor-free: zero anchor
  votes survive, and the served `fairValue` reproduces a freshly built LOO board on every
  priced row (`evidence/W14/anchor-free-proof.txt`).
- `W14-F005` (P3) — every served number reproduces exactly from the payload, the page
  prints the API's numbers unmodified, and the board refuses on thin evidence rather than
  calling every positive gap a Buy.
- `W14-F006` (P3) — it is structurally separate from the sharp tracker: separate router,
  service, params, page and label vocabulary, no shared thresholds.

**Defects that would bite if the flag were flipped**, all measured against the off
engine: its "Sharp Flow" component can never score a row because the ledger keys
movements by Sleeper player id while the board looks them up by `displayName`
(`W14-F001`, P2, authored P1); Sharp Flow consults no sharp cohort at all and would count
every manager in every crawled league (`W14-F002`, P2); and **28 of 73 buy-side rows are
labelled Buy directly above their own text saying the fair value is BELOW the market**
(`W14-F003`, P2).

**Documentation defect on this path:** `server.py`'s comment says `consensus_edge`
defaults ON since 2026-08-04; the registry sets it `False` and the endpoints 503
(`W25-F001`, P2).

---

## Case 16 — A Sharp Tracker transaction

## **NOT RUN — BLOCKED BY DATA.**

There is no sharp transaction to trace. The platform ledger exists with a full schema and
**zero rows in every table**:

```
/home/user/riskittogetthebrisket/data/intel/ledger.sqlite3
  asset_movements 0   transactions 0   platform_managers 0   leagues 0
  manager_seasons 0   league_memberships 0   sharp_rosters 0   sharp_roster_assets 0
  sharp_roster_observations 0   sharp_roster_asset_spans 0   canonical_assets 0
  ingestion_runs 0    ...   (meta: 3 — the only non-empty table)
```

`evidence/W15/ledger-row-counts.json`.

`GET /api/sharp/market` answers `status: "cohort_building"` with `assets: []`,
`selectedManagers: 0`, and per-platform `status: "no_data"` for both sleeper and ffpc
(`evidence/W15/live-market.json`). **That is the correct behaviour** — `W15-F001` (P3)
verified that all five sharp routes and both pages say so explicitly rather than
presenting an empty cohort as an answer.

**Exact missing artifacts:** rows in `transactions` / `asset_movements` /
`platform_managers` / `manager_seasons` in `data/intel/ledger.sqlite3`.

**What would unblock it:** the three staggered sharp crawls, in order —
`scripts/discover_sharp_graph.py` (04:20 UTC, finds managers) →
`scripts/crawl_sharp_records.py` (04:50, finds results, which is what makes a manager
scoreable) → `scripts/crawl_sharp_rosters.py` (05:50, finds holdings). All three are
prohibited by `AUDIT_PROTOCOL.md`'s read-only rule and require outbound network the
container does not permit.

**Not simulated.** A synthetic-ledger probe exists (`evidence/W15/synthetic_ledger_probe.py`,
`evidence/W16/w16_ledger_probe.py`) and was used to exercise the counting code
(`W16-F002`, P3, verified the counting rules for multi-team trades, refetches, failed
transactions, window overlap and waiver-vs-trade separation). **That is a code-path proof,
not a source-to-screen proof, and it is not offered as one here.**

---

## Case 17 — An Insider Trading trend

## **NOT RUN — BLOCKED BY DATA.**

Same empty ledger. `W16-F012` (P3) established the precise shape of the block, which is
not what the protocol assumed: `data/intel/ledger.sqlite3` **exists** with a full schema
and zero rows; what is additionally absent is
`data/intel/snapshot_dynasty_main.json`.

**What the page does with that, traced in the DOM** (`evidence/W16/page-503-dom.txt`) —
this part *is* measurable and it is a real defect:

The 503 handler synthesizes `{assets: [], memberCount: 0, leagueCount: 0, staleHours:
null}` and hands it to the normal render path, producing three statements at once:

1. honest — *"No intel snapshot yet — the first crawl hasn't run"*;
2. misleading — *"Trades your league-mates made in their OTHER Sleeper leagues — 0
   managers, 0 leagues observed"*, which reads as a measured zero;
3. **fabricated negative** — *"No tracked activity yet / No buy/sell events in the rolling
   windows. Check back after the next crawl."* — an observation the server explicitly
   refused to make.

All window/sort/direction filter controls render as if operating over data.
`W16-F003` (P2).

**Exact missing artifacts:** `data/intel/snapshot_dynasty_main.json`, plus rows in
`asset_movements`.

**What would unblock it:** the intel refresh (`POST /api/intel/refresh`, or the daily
intel workflow) on a host with network access to Sleeper. Prohibited here — the protocol
bans `/api/*/refresh`.

---

## Case 18 — A Sharp roster-percentage player

## **NOT RUN — BLOCKED BY DATA.**

`GET /api/sharp/roster-percentage` live:

```
status "cohort_building"   players []   totalQualifyingPlayers 0
transparency: uniqueSharpManagers 0, eligibleRosters 0, sleeperRosters 0, ffpcRosters 0,
              cohortCoveragePct null, rostersPerManager null, lastRefreshedMs null
sample: eligibleRosters 0, minimumForRanking 8, rankable false,
        warning "Based on 0 eligible sharp rosters. That is below the 8-roster minimum,
                 so these percentages are not ranked as meaningful results."
```

`evidence/W15/live-roster-percentage.json`. The denominator is honest and the refusal is
explicit.

**Exact missing artifacts:** rows in `sharp_rosters` / `sharp_roster_assets` /
`sharp_roster_asset_spans` / `sharp_roster_observations` — all four confirmed at 0.

**What would unblock it:** `scripts/crawl_sharp_rosters.py`, which itself requires the
two upstream crawls to have populated managers and records first.

**What was established without the data, and is worth recording**, because it would be a
live defect the moment a real cohort exists: on a **synthetic** cohort of 2 managers / 6
rosters where one manager holds 5 of them, the API returned
`sharpRosterPct 0.833333` (`sharpRosters` 5, `eligibleRosters` 6) for a player rostered by
**exactly one human**. The manager-weighted figure is 0.5000. No row field, query
parameter or page column exposes the manager count; `sampleWarning` did not fire because
6 ≥ `MIN_PLAYER_DENOMINATOR` 5. The sibling board built from the *same* cohort
(`src/sharp/market.py`) publishes `uniqueManagers` per asset and feeds manager breadth
into `signalStrength` — the concentration hazard is guarded on one board and unguarded on
the other. `W15-F009` (P1), `evidence/W15/synthetic-cohort-and-board.json`.
**This is a synthetic-cohort result and is labelled as such; it is not a proof case.**

Also structurally verified while empty: deduplication is enforced by primary key — 5
rosters × 2 duplicate assets produced exactly 5 stored rows — and
`GET /api/sharp/roster-percentage/audit?assetId=…` does list `managerKey` for every
holding roster, so the information exists behind one extra API call.

---

# Cases 19–21 — waivers, draft, schedule

## Case 19 — A waiver candidate and its FAAB recommendation

**TRACED — BREAKS AT the league calibration.** Primary asset: **Brevin Jordan (TE)**,
run live today.

| Stage | Value | Where |
|---|---|---|
| Board value | `rankDerivedValue` **1519** (rank 451) | live |
| Free-agent pool anchor | top FA = Marlin Klein, **1908** | `evidence/W11/formula-numeric-proof.json` |
| Base formula | `aggressive_pct = 0.05 + 0.25 × (1519/1908) = 0.2490` → raw $24.90 | `src/trade/waiver.py:120-129` |
| Server response (live) | conservative **$9** · standard **$13** · aggressive **$18** · max $100 | re-run today |
| Factor breakdown | "Player value baseline: start at $17" (w 0.35) · "Trending bump: none" (0.15) · **"League historical calibration: $−4"** (0.20) · "Rival contention: missing" (0.15) | re-run today |
| `resolvedAddValue` | **1519.0** | re-run today |
| Explanation shown | *"Bid $13 — strong free-agent target. Cap at $18 if you want the priority claim."* | re-run today |
| What `/rankings` shows for the same player, same session | **1,243** | Case 6 |

**The base formula is exact.** `W11` re-derived it independently across the whole value
range — Josh Allen, Josh Jacobs, Jaylen Warren, J.K. Dobbins, Marlin Klein, Chamarri
Conner, Taron Johnson, Malachi Moore, the `MIN_WAIVER_VALUE` floor and an unpriced row —
**10 of 10 exact matches**, `allMatch: true` (`evidence/W11/formula-numeric-proof.json`).
`W11-F020` (P3) verified `computeFaabHint` and `_compute_faab_bid` now agree to the dollar
over an 800-point grid, 0 divergences.

**Where it breaks — five measured defects.**

1. **The league calibration blends three currencies.** `_walk_waivers()` flattens every
   season's transactions into one bid list with no budget normalization while
   `_league_budget()` returns only the current season's budget. The live snapshot covers
   2026 (budget **$100**), 2025 (**$200**) and 2024 (**$1000**). `positionBids['RB'].avg`
   is therefore **$43.00**, with a max of **$340** — physically impossible in a $100
   league. Budget-normalized it should be **$8.58**: a **5.0× inflation**, blended 50/50
   into every RB bid. `W11-F001`, **P0, upheld**, `evidence/W11/faab-analytics.json`.
2. **Unpriced players get real bids.** The zero guard fires correctly and the factor row
   honestly reads "Player value baseline: start at $0" — then step 4 blends that $0
   against the position average (`0.5 × 43.0 + 0.5 × 0 = $22`) and resurrects a bid from
   nothing, described as a "strong free-agent target". **125 of 283 free agents** are
   affected; Zach Wilson (value 0) additionally received "+$6 to clear top rival".
   `W11-F002` (P2, authored P0).
3. **Two different dollar figures for one player render at once.** The Best-add/drop table
   uses `computeFaabHint` (hardcoded $100 budget, filtered-batch denominator); the bid
   desk uses server `recommend_faab` (whole-pool denominator + position calibration +
   trending + contention). Harold Landry (LB, value 1684): hint **$12**, desk **$21** —
   a 75% disagreement on one screen. `W11-F007` (P1).
4. **The same player's hint changes with the position filter.** Charlie Kolar reads
   **$19** under "All positions" and **$21** under "TE", because the denominator is the
   filtered batch maximum. `W11-F005` (P1).
5. **The bid saturates.** `aggressive_pct` caps at 0.30 for every player at or above the
   free-agent pool top (1908) — Josh Allen (9988), Josh Jacobs (3859), Jaylen Warren
   (2937) and Marlin Klein (1908) all price identically at **$30/$21/$11**. 367 board rows
   price the same and no player anywhere justifies more than 40% of the budget.
   `W11-F003` (P1).

**Honest degradation observed live:** `staleInputs: ["intel"]` and
`contention.skipped: true` with the note *"teamOwnerId not provided — rival contention
skipped (we never guess which team is yours)"*. That is correct.

---

## Case 20 — A Perfect Draft result

**TRACED — BREAKS AT the slot merge. The optimizer itself does not exist.**

Input: the live `/api/draft-capital` board for `dynasty_main`, 72 picks, `totalBudget`
$1200, `numTeams` 12, `ktcSource: "csv"`, `rookieSource: "ours_filtered"`.

| Stage | Value | Where |
|---|---|---|
| Pick ownership from the feed | Russini Panini **31**, CollinFoz 7, jstuedle 6, Rage Against The Achane 6, Chargers Team Doctor 5, TyBWell 4, then 3/3/3/3/1 | live payload, verified |
| `auctionDollars` | Russini Panini **$685** of $1200 | live payload |
| `slotsByTeamFromPicks()` | returns the true 31 / 7 / 6 / … — **correct** | `W10-F002` |
| **`buildTeam()`** | `initialSlots = Math.min(feedSlots, DEFAULT_INITIAL_SLOTS=6)` — a hard **maximum** | `frontend/lib/draft-logic.js:1427-1431` |
| Total board slots | 72 → **46** | `W10-F002` |
| `mdv` ($/slot) | **$114.17** rendered; true value $685/31 = **$22.10** — 5.2× wrong | `W10-F002` |
| `slotPressure` | saturates at 1.0 after 6 picks (true 6/31 = 0.19) | `W10-F002` |
| `phaseMultiplier` | locks at its 1.5× maximum for the remaining 25 picks | `W10-F002` |
| `effectiveBudget` | reserves $5 instead of $30 | `W10-F002` |
| **Rendered DOM** | `Pick 0 of 46` · `PHASE 6 of 6 slots` · `MY REMAINING $685` · `BUDGET ADVANTAGE 14.63×` · `TOP RIVAL CEILING $175` | `evidence/W10/draft-page-rendered.txt` |

`W10-F002`, **P0, upheld**.

**The optimizer is absent.** `W10-F003` (P1): a grep for
`perfect.?draft|optimiz|knapsack|combinator` across all `.py/.js/.jsx` returns nothing but
a "Nomination optimizer" comment. `nextBestTargets` scores each player independently as
`ev = max(0, inflatedFair − myWinningBid) × tagWeight + scarcityBoost`, sorts, and slices
to `limit=5`. It never enumerates subsets, never checks budget feasibility, never
considers a second player, and is not even greedy value-per-dollar — `myWinningBid`
collapses to the constant `topCompetitorMax + 1` ($19 in the probe) for every player whose
ceiling clears the field, so a $60 asset and a $1 asset carry the same "price". The
surplus term is structurally **zero** whenever `budgetAdvantage ≥ 1`: measured **0 rows
returned at BA 1.0, 1.1, 1.5 and 3.0**, versus 3 rows at BA 0.33. The panel populates only
when the user is poorer than the field. `evidence/W10/probe-greedy-suboptimal.mjs`.

**And the bid ignores the user's money.** `theoreticalMaxBid`, `myMaxBid`, `myWinningBid`
and `enforceUpTo` read neither `myRemaining` nor `effectiveBudgetByIdx[myTeamIdx]` —
`effectiveBudgetFor()` is applied to rivals only. With **$4** remaining the board says
"Win at $69 / Max bid $80 / Push up to $48". `W10-F001` (P1, authored P0),
`evidence/W10/probe-bid-vs-budget.mjs`.

**What works:** `slotsByTeamFromPicks()` returns the correct counts (the corruption is
introduced one function later); the 72 priced picks sum to exactly **$1200.00**; and
`W10-F009` (P3) verified the Sleeper-derived fallback's unpriced-pick exclusion behaves
exactly as `CLAUDE.md` describes — 40 priced 2026 picks sum to exactly $1200 and 40
unpriced 2027 picks are excluded rather than diluting.

---

## Case 21 — A schedule validation

## **NOT RUN — FEATURE ABSENT.**

There is nothing to trace. `W28-F001` (P1, status **Missing**) grepped all **10,409
tracked files** for
`generate_schedule|build_schedule|schedule_generator|scheduleGenerator|makeSchedule|round.?robin|'no back-to-back'|'divisional opponent'`
— 14 files matched and every one is unrelated. The 100-operation live OpenAPI census
contains no schedule route. `frontend/app` has no schedule directory and no nav entry.
The three division names (The Pit / Sweet Pepper Bacon / Barbacoa) exist only as inert
strings inside Sleeper's league metadata blob in
`config/league_intel/sleeper_league_snapshot_2026-07-26.json`; no module reads them.

The two nearest-sounding artifacts are explicitly **not** this feature:

- `src/public_league/playoff_odds.py::_round_robin_schedule` — a synthetic pairing
  fallback used only to simulate *unposted* weeks for playoff odds. It copies observed
  Sleeper pair-sets by cycle residue and honours none of the stated constraints: no
  division model, no week-4 pin, no NFL input.
- `src/bdvm/schedule.py` — fetches the nflverse NFL slate purely to mark per-player bye
  weeks for BDVM ROS weighting.

Neither is user-reachable as a scheduler.

**What the audit could establish:** the constraint set is *satisfiable*. A feasibility
prover written for this audit (`evidence/W28/schedule_feasibility_proof.py`) found a
conforming 12-team / 3-division / 14-week schedule — 84 games = 12 × 14 / 2 = 14 weeks ×
6 matchups, each team playing its 3 divisional opponents twice and its 8 non-divisional
opponents once — printed in full at `evidence/W28/schedule-feasibility.txt`
(`solution found: True / ALL CONSTRAINTS SATISFIED`). **That proves the spec is
buildable; it is not a proof case, and it is not shipped code.**

**What would unblock a real trace:** the feature being written. `W28-F001` notes two
reusable building blocks already exist and would shorten the build —
`src/bdvm/schedule.py` already ingests the nflverse slate with byes marked (tested at
`tests/bdvm/test_schedule.py`), and `src/api/league_registry.py` +
`config/leagues/registry.json` already resolve the 12-team league.

---

# Cases 22–24 — public surface, caching, source failure

## Case 22 — A public League page historical claim

**TRACED — BREAKS AT the identity filter.** Claim under test: the all-time **longest win
streak** table on `/league?tab=records`.

| Stage | Value | Where |
|---|---|---|
| Sleeper 2024 league `1090320428817592320` | `total_rosters` **10** | `evidence/W19/numeric-proof.json` |
| Scored 2024 roster-weeks | **170** | `W19-F001` |
| `identity._RETIRED_OWNER_IDS` | 2 ids: `714976074907336704` (Bwalk903), `720849338183548928` (SheriffB) — rosters 9 and 10 | `src/public_league/identity.py:27-46` |
| `metrics.resolve_owner` for those ids | returns `''`; every section then does `if not owner_id: continue` | `W19-F001` |
| Roster-weeks erased | **34 of 170 (20%)** | `W19-F001` |
| Raw 2024 streak, roster 10 (computed) | longest win **6** | `evidence/W19/numeric-proof.json` |
| **Published rank 3** | **Jason, 4** | `evidence/W19/retired-owner-diff.json` |
| **Correct rank 3** | **SheriffB, 6** | same file, `withRetiredOwnersIncluded` |

Re-running the repo's **own** `records.build_section` with `_RETIRED_OWNER_IDS` emptied
changes **5 of 10 record categories** — `singleWeekLowest`, `narrowestVictory`,
`fewestPointsInWin`, `longestWinStreaks`, `longestLossStreaks` — **3 of them at rank #1**
(`evidence/W19/retired-owner-diff-full.json`):

| Category | Published #1 | True #1 |
|---|---|---|
| Lowest single-week score | **177.25** | **164.79** |
| Narrowest victory | **290.8** | **271.82** |
| Fewest points in a win | **241.23** | **236.61** |

`W19-F001` (P1, authored P0 — rescoped by verification).

Two further false claims on the same public page, both live:

- **The history payload self-contradicts on the same screen.** 2024 carries
  `numTeams: 10` and exactly **8** standings rows, and the History tab renders the 8-row
  table with no caveat (`W19-F002`, P1). Shipped standings-row counts are
  `{2026: 12, 2025: 10, 2024: 8}` against a true `{2026: 12, 2025: 10, 2024: 10}`
  (`evidence/W19/retired-owner-diff-full.json`).
- **Eight 2026 awards are manufactured from a season with zero scored games** — live
  payload: `points_king → Jason, pointsFor 0.0`; `regular_season_crown → Jason, record
  "0-0"`; `league_mvp → Jason / Justin Jefferson, vorp 0.0, starterPoints 0.0,
  gamesStarted 13` (`W19-F004`, P1, `evidence/W19/numeric-proof.json`).

**What works, and it is the important half:** *the values that are published verify
exactly against Sleeper.* `records.singleWeekHighest[0] = 489.2` matches
`/league/1180092661344120832/matchups/15` roster 9 **to 0.01** (`W19-F001`, whatWorks).
The defect is omission, not arithmetic. `W19-F010` (P3) additionally verified that the
week-level roster-ownership join the all-time claims require **does exist and is used** —
records, awards and the player-journey page all attribute points via per-week ownership.
`W19-F015` (P3) verified all 21 `/league` tabs and all 10 dynamic deep-link routes render
real, non-fabricated content in a real browser, and every not-found path degrades with a
specific message. `W19-F009` (P3) verified the public trade grader uses the canonical
formula and its served grades reproduce exactly.

**One related omission with a number:** public trade letter grades silently drop **224 of
1,708** traded asset slots (13.1%) that the board cannot price — including 20
first-round-pick slots — and still emit a confident "Robbery"/"Fleece" grade. 63 of 191
trades and 126 of 393 sides are affected (`W19-F003`, P1, `evidence/W19/numeric-proof.json`).

---

## Case 23 — A cached page and its invalidation path

**TRACED — BREAKS AT negative caching.** Subject: `/draft` → `GET /api/draft-capital`.

| Stage | Behaviour | Where |
|---|---|---|
| Page | `/draft` issues **three** `/api/draft-capital` fetches per load; two omit `leagueKey` | `W10-F007` (P2) |
| Single-flight | per-league `asyncio.Lock` with post-wait re-check — **correct**, prevents the triple-fetch fanning out | `server.py:8375-8394` |
| Response cache | `_DRAFT_CAPITAL_CACHE`, TTL **300 s** | `W26-F008` |
| Cold build | openpyxl workbook parse + KTC live fetch (15 s urlopen timeout) + up to six Sleeper calls | `W26-F008` |
| Measured, authenticated | **2.735 s** cold → 0.005 / 0.006 / 0.006 / 0.007 s warm | `evidence/W26/repeat-latency-auth.txt` |
| Measured, **anonymous, no cookie** | 2.692 s cold, then 0.003 s — the route serves 200 to anon | `W26-F008` |
| Genuinely cold first call in the route sweep | **13,188 ms** | `W00-F001`, `evidence/route-probe.json` |
| Invalidation | **time only** — no ETag, no event, no explicit invalidation hook | `W26-F008`, `W26-F009` |

**Where it breaks — two coupled defects.**

1. **Anonymous callers can force the rebuild.** Redaction happens per-response *after* the
   build (`rookieBoardRedacted: true`), so an anon client polling every 5 minutes forces
   the full workbook + KTC + Sleeper rebuild on every TTL expiry:
   86400 / 300 × 2.692 s = **775.3 server-seconds per day per league**, from an
   unauthenticated caller. `W26-F008` (P2).
2. **Failure is never remembered.** `_get_ktc_rookies()` (`server.py:7113`) returns the 6 h
   cache when fresh, else calls `_fetch_ktc_rookies_live()`. On failure it falls through
   to `_parse_csv_rookies()` and returns those rows **without writing
   `_ktc_cache["fetched_at"]`**. Every subsequent cache miss therefore re-attempts the
   failing live scrape — forever. That is the 2.692 s. **Live confirmation:** the payload
   I read today carries `"ktcSource": "csv"`, i.e. the live fetch is failing right now and
   the fallback is in use. `W26-F008` (P2), `W10-F008` (P2).

**Three neighbouring caches have no stampede protection at all** (`W26-F005`, P2): the
BDVM aux caches release `_aux_lock` before fetching, so N concurrent cold `/api/bdvm/*`
requests each launch a full nflverse download (**47,994 ms** measured);
`get_bdvm_values` releases `_lock` at :197 and re-acquires at :214;
`league_comparison.service.build_comparison` has a 7-day disk cache and **no lock at all**
(**26,577 ms** cold); `gameplan.get_league_bundle` holds `_CACHE_LOCK` only around the
dict lookup. With 40 threadpool workers, 40 concurrent cold BDVM requests saturate the
pool for ~48 s.

And `_LEAGUE_CONTEXT_CACHE` is a **single global slot with no league key**, so every
league's rookie-anchor roster count and TE bonus come from the default league
(`W26-F018`, P3) — a cache whose invalidation path is not merely time-based but
league-blind.

**What works, and the repo gets this right in more places than it gets it wrong.**
`W26-F005` names four caches that implement single-flight correctly with the reasoning
written down: `_OVERLAY_RESPONSE_CACHE` / `_OVERRIDES_RESPONSE_CACHE` (per-key
`asyncio.Lock`, re-check inside the lock, held locks preserved across eviction),
`_DRAFT_CAPITAL_CACHE`'s own per-league lock, `_heavy_section_cache` (waiters block on the
loop, not in the threadpool, so they do not hold worker tokens hostage), and
`sleeper_overlay._BUILD_LOCKS`. The public-league cache goes further with
stale-while-revalidate, a suppression flag on the background refresh thread, and
hit/miss/stale counters. Redacting on a per-response copy rather than mutating the cached
object is exactly right and avoids a cross-viewer leak. `ktcSource` is honestly stamped so
a consumer *can* tell the live fetch failed — which is how I detected it.

I also observed the overlay cache working live today: `GET /api/valuation/league-adjusted`
returned `"cacheHit": true`.

---

## Case 24 — A failed or stale source and the visible degradation behaviour

**TRACED — BREAKS AT visibility.** Three real failures were live during the audit. In
none of them does the user see the truth.

### 24a. KTC live fetch — failing right now, invisible

| Stage | Observed |
|---|---|
| `_fetch_ktc_rookies_live()` | fails (15 s timeout) |
| Fallback | `_parse_csv_rookies()` |
| Payload stamp | **`"ktcSource": "csv"`** — honest, read live today |
| User-visible signal | **none** on `/draft` |
| Cost | re-attempted on every 300 s cache miss forever (Case 23) |

### 24b. Source deletion — the contract calls it healthy

Stripping each source in turn from the live contract and re-running the validator
(`evidence/W05/source-drop-contract-health.json`):

| Source removed | Fields stripped | `status` | `errors` |
|---|---|---|---|
| `dlfSf` | 1,385 | **invalid** | `source_missing:dlfSf` |
| `yahooBoone` | 2,221 | **invalid** | `source_missing:yahooBoone` |
| **`ktcSfTep`** (the retail anchor, 501 rows) | 2,311 | **healthy** | `[]` |
| `fantasyCalc` | 2,327 | **healthy** | `[]` |
| `pfkDynasty` | 2,687 | **healthy** | `[]` |
| `fantasyNavigatorSf` | 2,552 | **healthy** | `[]` |
| `otcffbSf` | 2,055 | **healthy** | `[]` |
| `fantasyProsSf` | 2,232 | **healthy** | `[]` |

**Nine of 21 registry sources have no row-count floor**, including the retail anchor.
`W05-F004` (P1). *The floor mechanism itself is correct and load-bearing where it exists.*

Two failure modes a real fetcher actually produces return **silently**: a header-only CSV
(fetcher ran, scraped nothing) hits `if not csv_lookup: continue` with no error; and a
vendor column rename produces `schema_mismatch` only for the **4 of 22** sources
hard-coded in the probe (`dlfSf`, `dlfIdp`, `fantasyProsIdp`, `fantasyProsSf`) — the other
18, including `ktcSfTep` and `idpTradeCalc`, vanish with `parse_errors == []`.
`W05-F003` (P1), `evidence/W05/schema-probe-coverage.json`.

### 24c. The page built to show this — rendered DOM

`/tools/source-health`, captured through request interception
(`evidence/W05/source-health-page.txt`):

```
Source Health
Scraper status for every ranking source in the pipeline.

Sources · 4 · 3h ago · 2 issues
  IDPTradeCalc     —
  KTC              500 rows
  KTC_TradeDB      —   KTC trade DB skipped — no playerID→name mapping available
  KTC_WaiverDB     …
```

**4 of 21 registered sources listed**, and `IDPTradeCalc` renders **0 rows** (shown as an
em-dash) against **900** in the payload. The strip iterates
`source_health.source_runtime.enabled_sources` — a 4-item scraper-internal vocabulary —
instead of the registry keys, and the count lookup `counts[src] || counts[src.toLowerCase()]`
maps `'KTC'→'ktc'` (hits, 500) but `'IDPTradeCalc'→'idptradecalc'` (misses, 0). The
per-source freshness map `health.sources` — **22 correct camelCase entries** — is fetched
in the same payload and read with the same wrong keys, so `meta` is always `{}` and no
per-source age is ever rendered. `W05-F001` (P1).

Correspondingly, `/api/status` `source_health` describes **2 of 21** sources
(`total_sources: 2`, `source_counts` covering `ktc` + `idpTradeCalc` only,
`missing_sources` structurally always empty) — `W05-F002` (P2).

### 24d. Staleness is computed and shown to nobody

`dataFreshness.sourceTimestamps` ships **22 entries** in every `/api/data` response, each
carrying `ageHours`, `maxAgeHours` and `staleness ∈ {fresh, stale, missing}`. It is read
by exactly one module in the tree — `src/consensus_edge/service.py`, whose flag is **off**
(Case 15). The frontend touches `dataFreshness` in one place
(`rankings/page.jsx:835`) and reads only `generatedAt`. Two threshold tables disagree by
**4×**: `_SOURCE_MAX_AGE_HOURS` sets 6 h for twelve sources; `config/source_staleness.json`
sets 24 h for every source. The 6 h table stamps the payload; the 24 h table fires email.
Neither reaches a user, and staleness is purely descriptive — nothing downweights or
drops a stale source's vote. `W05-F009` (P2), `evidence/W05/source-chain.json`.

And the raw-ingest scaffold serves a **106-day-old** artifact
(`run_id 20260420T194828Z`, `created_at 2026-04-20`) while reporting
`mtime: 2026-08-03` — the git-checkout time — with `warnings: []`. No code in the tree can
produce a new one. `W05-F007` (P2). *Nothing in the frontend consumes it, so no user-facing
page is showing April data.*

### What works on this path

- **The file-missing path is honest**: it appends `{'error':'file_not_found'}`, logs a
  warning, and flips the contract to degraded.
- **The floor mechanism works where it exists** — `dlfSf` and `yahooBoone` both produce a
  hard error and flip the contract to invalid, and the config file allows tuning without
  a code change.
- **`W05-F010`** (P3) verified clean end to end: all 21 registered ranking sources have a
  live fetcher, a fresh CSV, and real votes on the served board.
- **`W05-F011`** (P3) verified the reported coverage gaps are explained and correct — KTC
  590/1074 and IDPTradeCalc 898/1074 are board depth and pick-anchor interpolation, not
  lost data.
- **The email alert path is real and per-source**: `_build_source_health_snapshot`'s
  `sources` block (22 correct entries) feeds `src/api/source_health_alerts.check_and_alert`
  from the daily sweep, with a documented soft/soft-escalate policy for `idpShow`. The CI
  freshness watchdog runs on the 2 h refresh and passes.

---

# What the 24 cases establish

**The arithmetic is largely sound. The plumbing between surfaces is not.**

Every stage that was independently reimplemented and diffed against the live payload
reproduced exactly: the blend on 800/800 rows (`W02-F012`), the TE basis conversion on
536/536 votes (`W02-F013`), the single-source haircut on 35/35 rows, the pick tether on
72/72 picks (re-verified today), the trade-verdict symmetry over 40,000 random trades
(`W08-F009`), the KTC value-adjustment Python↔JS parity at 0 differences
(`W08-F010`), the BDVM expected-positive-surplus closed form at 0.000e+00 max absolute
error over 4,893 path rows (`W13-F010`), the FAAB base formula on 10/10 cases
(`W11`), and the public records' single-week high against Sleeper to 0.01
(`W19-F001`).

What fails is agreement **between** components that each work:

| Failure shape | Cases | Representative measurement |
|---|---|---|
| Two boards for one number | 2, 6, 9, 11, 12, 19 | Brevin Jordan: 1,243 on screen, 1519.0 in the FAAB engine, same session |
| A label computed from a quantity other than the one it names | 3, 6, 13, 14 | 32 of 32 top-250 SELL labels are tight ends |
| A gate calibrated on one asset class applied to all | 5, 10, 12 | IDP is 9.33% of the trade asset pool against 42.86% of the starting lineup |
| Absence coerced into a measurement | 3, 12, 14, 17, 22 | `float(None or 0.0)` makes the #1 roster a "Seller" |
| A refusal that renders as a fact | 17, 23, 24 | `IDPTradeCalc —` on `/tools/source-health` against 900 rows in the payload |

And the honest ledger: **three cases could not be run at all** because the data does not
exist in this container (16, 17, 18 — an empty `data/intel/ledger.sqlite3`), and **one has
no implementation to trace** (21). Those four are recorded as blocked, with the exact
missing artifact and the exact unblocking step named, and none of them is presented as a
partial result.
