# W27-F001 methodology proposal: IDP edge consistency and the canonical IDP benchmark

**Activation status: NOT ACTIVATED.** This is research. No production formula, weight, threshold, flag,
served field or frontend component changed. Every number below comes from a pinned, tracked input, and
the harness that reproduces it is offline.

- **Authority:** owner directive 2026-11-07, §3 (`docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md`).
  Intake MD-59, `docs/EXECUTION_PLAN.md`: research and proposals only.
- **Finding:** W27-F001, P1, OPEN (`docs/master-site-audit/evidence/registry/W27.jsonl`). Re-adjudicated in
  `docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md`. The honest-disclosure half is merged
  (#2097, the "offense only" label on /rankings).
- **Not covered here:** BDVM's market signal. That is W13-F003, owned by another worker.
- **Agent-OS-Receipt:** 741230def70b1c94b9924192ee784bb7241b91a6

## 0. Summary

1. **The audit's suggested repair is the wrong repair on this board.** The audit proposed anchoring IDP
   rows on IDPTC "the way finder.py does", which means comparing our model value with IDPTC. On IDP rows,
   IDPTC carries a median **74.2%** of the blend's applied weight (offense comparison: the two KTC inputs
   carry 16.5%). It is also the α-shrinkage anchor on all 377 rows it prices, and it builds the
   shared-market ladder that 267 FantasyPros votes are translated through. So a model-vs-IDPTC gap is
   the model measuring itself:
   - It equals the source disagreement compressed by a slope of **0.265**, which is almost exactly
     1 − 0.742.
   - It reports a fabricated "aligned" on the 28 rows where IDPTC is the only voter.
   - It reports a fabricated SELL of about 108% on the 26 sole-voter rows that the single-source haircut
     cut to 30%.
2. **The live /edge IDP detector (`idpMarketAction`) is not a market edge at all.** It compares two
   sources with each other: IDPTC against the mean of the IDP experts. That is the same retail-vs-consensus
   construction the owner retired for offense on 2026-09-23. It also has four other problems:
   - **It ignores the blend's evidence weights.** All 323 of its BUY/SELL verdicts rest on expert evidence
     that the blend weights at a median **0.35** of one full-strength provider: FantasyPros at 0.13
     (64 days stale) plus Draft Sharks at 0.2173.
   - **It counts a zero-weight board as full evidence.** On 45 rows it uses The IDP Show combined
     board, which the blend weights at zero (79 days stale). The registry also records a measured
     dependence between IDPTC and The IDP Show (Spearman 0.998, IDP Show leads), but classifies common
     ancestry as **SUSPECTED**, not vendor-stated (`idptc-idpshow-suspected-ancestry`). A 2026-11-01
     source audit reports vendor statements and recommends an upgrade that has not been made.
   - **It has a curve-shape artifact.** It prices expert ranks on the GLOBAL Hill curve but IDPTC on its
     own published values. So when experts agree exactly with IDPTC, it still issues 232 BUY and 94 SELL
     verdicts (median baseline −14.1%).
   - **Its panels select on the benchmark's own rank** ("top 200 by IDPTC"). Selecting on one side of a
     two-sided comparison manufactures direction by itself: the same signal goes from 23 SELL / 13 BUY to
     7 SELL / 28 BUY when the selection side flips.
3. **Display defects on /edge (verified with the real module).**
   - `idpGapOf()` looks for "~N ordinal" in a title that now reads "~N%". Every IDP gap therefore parses
     as 0: the panels' "Gap desc" sort does nothing and the Gap column shows "—".
   - The panel note lists a "FootballGuys IDP" source that does not exist and omits DLF Rookie IDP.
   - Off /edge, four surfaces drop IDP rows without saying so: the player popup, the player page, the
     trade rows and the /rosters League Edge Map.
4. **Recommendation, IDP benchmark.** IDPTC is the only IDP *reference price* on the shared scale, and it
   is what IDP counterparties consult, so it is the right IDP benchmark. But it must never be compared
   with a value it dominates. Recommended contract:
   - The IDP gap is **C2**: anchor-free evidence vs IDPTC's price. The evidence excludes IDPTC, and each
     source's placement is priced on IDPTC's own curve. The zero point is exact by construction.
   - Whether C2 also excludes The IDP Show is **an owner decision (D1b), not a premise**. The registry
     classifies that ancestry as SUSPECTED, and the 2026-10-19 directive merges votes only on credible
     shared-data lineage. §4.2 reports C2 both ways.
   - C2 is gated on at least 2 independent provider families and at least 1.0 freshness-weighted
     provider-equivalents.
   - On the pinned board **no IDP row passes the weight gate**. The canonical IDP state today is therefore
     an explicit, reasoned "unavailable", never neutral, never a fabricated gap.
   - C2 should go to an owner-approved **shadow** evaluation.
5. **Historical evaluation finds no predictive value in any IDP edge definition.** The test asks whether
   the signal predicts IDPTC's subsequent move, using no look-ahead and tracked CSV history (11 weekly
   origins, 28-day horizon). Pooled hit rate is 0.494 for C2 and 0.501 for an incumbent-like replay;
   Spearman is −0.029 and −0.014. Results at 14 and 56 days are the same. No IDP BUY/SELL claim currently
   has evidence that it is actionable.

## 1. Current formulas and meaning (commit d7db52a43b)

| Surface | Formula | Benchmark | IDP outcome |
|---|---|---|---|
| Canonical gap: `src/api/data_contract.py:4764` `_compute_market_gap` → `src/sources/ktc_market.py:123` `compute_market_gap`, stamped by `_stamp_ktc_market_benchmark` (`data_contract.py:4790`) | `ratio = (KTC_norm − rankDerivedValue) / mean(both)`; `retail_premium` if > 0, `consensus_premium` if < 0; either side missing → `("none", None)` | KTC Market (`ktcCrowdTradesSfTep`), benchmark only, never a vote | KTC publishes no IDP, so every IDP row gets `ktcMarket: {available: false, reason: "no_ktc_coverage"}` and `marketGapDirection: "none"` |
| /rankings Edge column: `frontend/app/rankings/page.jsx:1300` `marketActionDisclosed` (`frontend/lib/display-helpers.js:322`) | reads the stamp; BUY/SELL/HOLD at `MARKET_GAP_MIN_VALUE_RATIO = 0.05` | KTC Market | "offense only" plus a tooltip pointing to /edge (#2097) |
| /rankings filter `edge=buy\|sell`: `frontend/lib/player-filters.js:176-185` | `marketGapDirection == consensus_premium / retail_premium` | KTC Market | matches 0 IDP rows, and does not say so |
| /edge IDP panels: `frontend/app/edge/page.jsx:173-198` → `idpMarketAction` (`display-helpers.js:501`) → `idpMarketEdge` (`:400`) | `ratio = (mean(IDPTC valueContribution) − mean(other keys' valueContribution)) / mean(both)`, unweighted, threshold 0.05; population = `isIdpInTopByIdptc(r, 200)` (`:547`) | IDPTC vs IDP experts (source vs source) | BUY/SELL on 323 rows |
| Popup / player page / trade rows: `frontend/lib/trade-logic.js:1321` `getPlayerEdge` → `components/PlayerPopup.jsx:904`, `app/players/[playerId]/page.jsx:151`, `app/trade/trade-sections.jsx:350,557` | reads the stamp | KTC Market | `signal: null`: no box, no disclosure |
| /rosters League Edge Map: `frontend/lib/league-analysis.js:1031` → `app/rosters/page.jsx:141,442` | Σ `edgePct` over a team's players with a signal | KTC Market | defenders silently absent from the team totals (the league starts 9 IDP of 21 slots) |
| Trade finder: `src/trade/finder.py:143` `IDP_MARKET_KEYS` | board value vs IDPTC value inside arbitrage scoring | IDPTC (model vs market, i.e. C1) | the third IDP "edge", backend-only |
| Consensus Edge (flag `consensus_edge` default OFF): `src/consensus_edge/fair_value.py:144-147` | leave-anchor-out board value vs anchor price | KTC Market / IDPTC | see C3 |

The owner's offense definition (2026-09-23): "difference from market" means **our model value vs canonical
KTC Market**. KTC Crowd and KTC Trades vote; KTC Market is derived from them and never votes. The offense
benchmark is therefore a descendant of two of about a dozen voting families. That correlation was
accepted at the owner level and is not reopened here (see §8).

## 2. Pinned inputs

- **Board:** `exports/archive/dynasty_export_20261107_063955.zip`.
  - Archive sha256 `f1ad8517…57fb60`; payload `dynasty_data_2026-11-07.json`, sha256 `7d35c88d…a4eade`.
  - Scrape `2026-11-07T06:39:55Z`.
  - Built with `build_api_data_contract(payload)` at commit `d7db52a43b8c96a7c44e2d62a24cb70c9114c37a`, the
    same path `tests/archive_fixtures.newest_complete_contract` uses. It reads the tracked `CSVs/site_raw`
    and `data/scrape_state`. The per-file sha256 of the six IDP CSVs and their dataset-state files are in
    the fixture's `provenance`.
  - Extraction is byte-deterministic: two runs gave the same fixture hash.
- **Fixture:** `tests/scripts/fixtures/w27_f001_idp_edge_rows.json` (430 IDP rows, 535 offense weight rows,
  the 899-value IDPTC price ladder, Hill parameters, per-source voting status, and the leave-IDPTC-out
  board summary).
- **History:** git objects for `CSVs/site_raw/{idpTradeCalc,dlfIdp,fantasyProsIdp,draftSharksIdp,idpShowCombined}.csv`,
  read with `git rev-list -1 --before=<date>`.
- **Never used:** the network, `exports/latest` or gitignored `data/`.

Source state on the pinned board (contract `sourceVotingStatus`):

| IDP source | family | applied weight | last genuine update | status |
|---|---|---|---|---|
| idpTradeCalc | idpTradeCalc | 1.0 | 2026-11-06 | active 100% |
| draftSharksIdp | draftSharks | 0.2173 | 2026-11-04 (cadence 14.3 h) | active |
| fantasyProsIdp | fantasyPros | 0.13 | 2026-09-04 (64 days) | active |
| idpShowCombined | idpShow | 0.0 | 2026-08-19 (79 days) | stale |
| dlfIdp, dlfRookieIdp | dlf | 0.0 | fresh | owner hold (CQ-65) |

## 3. Defect evidence

All counts are from `python scripts/research/w27_f001_idp_edge_benchmark.py analyze`; the full output is
in `evidence/w27_f001/analysis.json`.

### 3.1 The canonical edge has no IDP path, and four surfaces drop IDP silently

- 430 IDP rows (DL 165, LB 115, DB 150).
- `ktcMarket.reason == no_ktc_coverage` on 430/430, and `marketGapDirection == none` on 430/430.
- The /rankings cell reads "offense only" on 430/430: honest since #2097.
- The `edge=buy|sell` filter matches 0, with no notice.
- The popup, player page, trade rows and League Edge Map render nothing for a defender. They never say
  the comparison excludes IDP.

### 3.2 The second detector contradicts /rankings on 323 rows

- The real `frontend/lib/display-helpers.js`, run under node over the fixture
  (`scripts/research/w27_f001_frontend_crosscheck.mjs`), gives BUY 238 / SELL 85 / HOLD 15 / "—" 92.
- The Python transcription matches it row for row on all 430 rows (pinned by test).
- These are the same counts CW-40 measured on the earlier `20261106_194518` board.
- Every one of the 323 BUY/SELL rows reads "offense only" on /rankings.

### 3.3 It is source vs source, on evidence the blend does not trust

- **Concept.** `idpMarketEdge` compares IDPTC's `valueContribution` with the unweighted mean of every other
  key's `valueContribution`. Our model value never enters. This is the pre-2026-09-23 "retail vs consensus"
  construction the owner rejected for offense (see the `_compute_market_gap` docstring).
- **Evidence weight.** The expert side's applied weight is median 0.3473 (p10 0.13). All 323 verdicts sit
  below one full-strength provider.
- **Zero-weight evidence.** 45 verdicts count `idpShowCombined` at full strength, although the blend gives
  it zero weight (stale, 79 days). That is a defect whatever the lineage answer is.
- **Relation to IDPTC: unsettled, not proven lineage.**
  - `config/sources/source_lineage.json` records `idptc-idpshow-dependence` as a *measured dependence*
    (Spearman 0.998, IDP Show leads at 3 of 5 publications).
  - It records `idptc-idpshow-suspected-ancestry` as **SUSPECTED**: "no vendor statement says so".
  - `docs/sources/IDP_SHOW_LIBRARY_AUDIT_2026-11-01.md` §6 reports three vendor statements and recommends
    upgrading the relation. That upgrade has not been made.
  - Under the 2026-10-19 directive (`docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`), similarity
    alone never merges votes. That directive withdrew the IDPTC / IDP Show shared cap because its only
    basis was rank similarity.
  - So whether The IDP Show may serve as evidence against IDPTC is an owner question (D1b), not something
    this proposal treats as settled.

### 3.4 Curve-shape artifact

How the two sides are priced:

- **Expert votes.** Ranks are translated to the shared-market coordinate, then priced by the **GLOBAL**
  Hill curve: `V(p) = 9999 / (1 + (p/0.112)^0.725)`, with `p = (rank − 1) / 499`.
- **Check.** An independent implementation from the published `hillCurves.global` parameters reproduces
  **890 / 890** stamped rank-Hill votes within 1.
- **IDPTC.** Its vote is its own published value.
- **Consequence.** Put every expert at IDPTC's own rank and the incumbent still reports
  `(IDPTC value − GLOBAL_Hill(p_IDPTC)) / mean`.

| IDPTC rank bucket | rows | baseline median (zero disagreement) | incumbent | C2 (2 families) |
|---|---|---|---|---|
| 1–100 | 10 | +11.0% (SELL tilt) | SELL 9 / BUY 1 | SELL 8 / BUY 1 / HOLD 1 |
| 101–200 | 28 | +9.0% | SELL 16 / BUY 9 / HOLD 3 | SELL 15 / BUY 12 / HOLD 1 |
| 201–400 | 47 | +2.8% | SELL 29 / BUY 15 / HOLD 3 | SELL 20 / BUY 16 / HOLD 9 / n/a 2 |
| 401+ | 292 | −16.1% (BUY tilt) | BUY 213 / SELL 31 / HOLD 9 / — 39 | BUY 110 / SELL 24 / HOLD 22 / n/a 136 |

The baseline alone gives BUY 232 / SELL 94 / HOLD 51.

The like-for-like comparison is the artifact-free C2 with every weighted vote and a one-family gate. Under
it, 57 of the incumbent's 323 directional verdicts change:

- 24 BUY → HOLD
- 14 SELL → HOLD
- 4 BUY → SELL
- 15 BUY → unavailable

The rest keep their sign. So the direction mostly reflects genuine rank disagreement. The magnitude, the
HOLD band and the depth tilt are contaminated.

### 3.5 Selection on the benchmark's own rank manufactures direction

Same signal (C2, two families) over same-size populations (k = 38, the size of the incumbent's
top-200-by-IDPTC panel population), with only the selection rule changed:

| selected by | SELL | BUY | HOLD |
|---|---|---|---|
| IDPTC rank (incumbent /edge gate) | 23 | 13 | 2 |
| board value | 18 | 18 | 2 |
| mean of IDPTC price and evidence | 13 | 23 | 2 |
| evidence value | 7 | 28 | 3 |

This is regression toward the mean. Conditioning on one side being high selects that side's positive
errors. A panel gated on the benchmark's own ordering will over-report SELL. The offense panels gate on our
board rank (`edge-helpers.js:45`).

### 3.6 /edge display defects (real module, `evidence/w27_f001/frontend_crosscheck_summary.json`)

- **Gap parsing.** `idpGapOf()` (`edge/page.jsx:84`) parses `/~(\d+) ordinal/`. No title contains
  "ordinal" (0 of 430); titles read "~41% above…". As a result:
  - every `__idpGap` is 0;
  - the "Gap desc" sort is a no-op, so each panel shows the first 10 verdicts in board order. Example: the
    SELL panel lists Will Anderson (41%) first and Dallas Turner (91%) ninth;
  - the Gap column renders "—" under a header saying "Ordinal distance…" (`edge-columns.jsx:134-141`).
- **Panel copy.** The note names "FootballGuys IDP", which is not a registry key, and omits `dlfRookieIdp`.
  The subtitles say "ranks" for a value-space comparison.
- **Adjacent offense defect, not W27-F001.** `app/players/compare/page.jsx:175` colours on
  `marketGapDirection === "buy"`, a value the contract never emits. It prints the raw enum
  (`CONSENSUS_PREMIUM`) in red for both directions. The popup, player page and League Edge Map still
  describe the offense gap as "consensus vs KTC" rather than "our model vs KTC Market". Route both to the
  UI lane.

## 4. Candidates

All candidates are offline functions in `scripts/research/w27_f001_idp_edge_benchmark.py`; none is served.
"Market" means IDPTC's published value on the board scale (its value-direct vote).

| | Definition | Pinned-board result |
|---|---|---|
| **C0 (incumbent)** | §1 /edge row | BUY 238 / SELL 85 / HOLD 15 / — 92; contradicts /rankings on 323 |
| **C1: model vs IDPTC** (the audit's repair, the finder's arithmetic) | `(IDPTC − rankDerivedValue) / mean` | BUY 165 / SELL 68 / HOLD 144 / n/a 53. Regression on the leave-IDPTC-out gap has **slope 0.265** (= 1 − IDPTC share). 28 rows are "aligned" only because the model *is* IDPTC; 26 rows are SELL ≈ +108% only because of the single-source haircut. **Rejected:** double counting by construction |
| **C2: anchor-free evidence on the market's curve** | For each non-IDPTC source the blend counted on the row (applied weight > 0; holds and fully stale boards are already out; The IDP Show excluded by default, a D1b choice, see §4.2), read IDPTC's price at that source's shared-market rank. Evidence = applied-weight mean. Gap = `(IDPTC − evidence) / mean`. Gates: ≥ 2 independent families, total weight ≥ W | W = 0: 239 available, BUY 139 / SELL 67 / HOLD 33. **W = 0.5 or 1.0: 0 available.** Exactly 0 when every source agrees with IDPTC's placement |
| **C3: leave-IDPTC-out board** (the Consensus Edge construction) | rebuild with `idpTradeCalc` disabled; `(IDPTC − LOO value) / mean` | BUY 191 / SELL 115 / HOLD 17; agrees with C2 on 192 / 200 directional rows. Its shared-market ladder switches to the **Draft Sharks** bridge (FantasyPros goes `extrapolated` on 93 rows; values move median ×1.106, range 0.33–2.36). It still prices votes on the GLOBAL Hill, so 207 / 323 verdicts equal the zero-disagreement baseline's. **Not recommended** until the bridge-swap scale is validated |

Correction to an older record. The Consensus Edge refusal documented in `fair_value.py` (ADR-021/025,
"excluding IDPTC empties the ladder") **does not reproduce** on this board:

- `shared_market_crosswalk_failed` returns `{}`;
- `scale_integrity_lost(["idpTradeCalc"])` declares no asset-class loss;
- the cross-position bridge owner (Lane 8) now seeds the leave-out ladder from Draft Sharks.

So Consensus Edge (flag OFF) would currently emit IDP mispricing from C3. The docstring's premise is stale;
route that to the Consensus Edge owner.

### 4.1 Why C2's construction answers the double-counting question

IDPTC enters C2 only through its **price level**: the curve that turns a placement into dollars. It never
enters through its **opinion** of the player being evaluated. That is the IDP analogue of the offense
benchmark rule "KTC Market never votes": the benchmark sits on one side of the comparison only. C2 is
exactly zero when every independent source places the player where IDPTC does, so no curve-shape term can
create a verdict. The default additionally excludes The IDP Show (`BENCHMARK_LINEAGE_FAMILIES`), but
that is a parameter (`excluded_families`), and the alternative (`BENCHMARK_ONLY_FAMILIES`, IDPTC only) is
reported in §4.2. Applied weights reuse the blend's own freshness × health × coverage and owner holds,
with no new weighting.

### 4.2 Sensitivity: C2 with The IDP Show admitted as evidence

The IDP Show's exclusion rests on a SUSPECTED registry relation, so the result is shown both ways. The
only IDP Show key on the board is `idpShowCombined`. It places 301 IDP rows and has applied weight 0 on
every one of them (stale, 79 days).

| C2 variant | gate | available | BUY / SELL / HOLD | rows differing from the default |
|---|---|---|---|---|
| IDP Show excluded (default) | 2 families | 239 | 139 / 67 / 33 | n/a |
| IDP Show excluded (default) | 2 families, W ≥ 0.5 or 1.0 | **0** | n/a | n/a |
| IDP Show admitted, actual applied weights | any of the three gates | identical to the default | identical | **0** |
| IDP Show admitted at weight 1.0 (hypothetical: its board republished fresh) | 2 families | 290 | 220 / 38 / 32 | 144 |
| IDP Show admitted at weight 1.0 (hypothetical) | 2 families, W ≥ 0.5 or 1.0 | **273** | 204 / 38 / 31 | 301 |

What this means:

- **Today the choice changes nothing.** The board gives the IDP Show zero weight, so C2 is identical
  either way.
- **It becomes decisive the moment The IDP Show refreshes.** With the IDP Show admitted at full weight,
  273 rows would pass the W ≥ 1.0 gate (BUY-heavy, 204 vs 38), where the default passes none. With it
  excluded, they stay unavailable.
- **That is why it must be an explicit owner decision (D1b)** rather than a premise.

Historical replay with the IDP Show admitted (it exists in the tracked history from 2026-08-20, so it
enters origins from 2026-08-24, unweighted): hit rate 0.505 (14 d), 0.486 (28 d), 0.461 (56 d); Spearman
−0.013 / −0.008 / −0.000. Like every other variant, it shows no predictive value (§9).

## 5. Independently computed expected results (oracles)

| Oracle | What it checks | Result |
|---|---|---|
| Real frontend module under node (`w27_f001_frontend_crosscheck.mjs`) | the Python transcription of `idpMarketAction` / `marketActionDisclosed` / `isIdpInTopByIdptc` | 430 / 430 rows identical (test) |
| Hill formula from published parameters | expert votes are GLOBAL-Hill priced, which is the premise of the artifact | 890 / 890 within 1 |
| CSV-level recomputation of the FantasyPros half of C2 (`oracle` subcommand): own CSV parsing, own name join, own IDPTC IDP ladder | that `ladder(effectiveRank)` equals "IDPTC's k-th IDP price" for FantasyPros' k | 229 / 266 within 2%: **182 / 185** for the vendor's directly published ranks (`direct_combined`), 47 / 81 for vendor-derived family listings (`anchored_from_individual`), where the pipeline re-ranks before translating. Worked example: Micah Parsons, FantasyPros #39 IDP → stamped `effectiveRank` 204 = rank of IDPTC's 39th IDP (Blake Cashman, 3180) among all 899 IDPTC values |
| Synthetic C2 properties (tests) | zero point, refusals never 0, IDP Show exclusion as a parameter (both settings), direction | pass |

## 6. Before/after player impacts (named audit players, pinned board)

| Player | Pos | model | IDPTC | /rankings | C0 | C0 ratio | zero-disagreement baseline | C1 | C2 | C3 | C2 evidence weight |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Micah Parsons | DL | 4576 | 5409 | offense only | SELL | +79.6% | +13.5% | +16.7% | +77.1% | +94.7% | 0.347 |
| Abdul Carter | DL | 4620 | 5414 | offense only | SELL | +80.3% | +12.4% | +15.8% | +69.0% | +72.6% | 0.347 |
| Myles Garrett | DL | 3761 | 4173 | offense only | SELL | +39.5% | +11.5% | +10.4% | +39.7% | +62.6% | 0.347 |
| Aidan Hutchinson | DL | 5569 | 5963 | offense only | SELL | +21.9% | +6.2% | +6.8% | +24.4% | +45.7% | 0.347 |
| Nick Bolton | LB | 3931 | 3605 | offense only | BUY | −29.3% | +6.7% | −8.7% | −41.7% | −31.1% | 0.347 |
| Fred Warner | LB | 4298 | 4164 | offense only | BUY | −13.3% | +12.4% | −3.2% | −23.1% | −8.0% | 0.347 |
| Jared Verse | DL | 2205 | 2098 | offense only | BUY | −18.4% | +2.6% | −5.0% | −31.6% | −15.8% | 0.347 |

Under the recommended canonical state (C2 with W = 1.0), every one of these becomes
`unavailable / insufficient_evidence_weight`, because the independent evidence behind them is 0.347 of one
fresh provider. No player value, rank, tier or confidence changes under any candidate: the edge is a
comparison stamp, not a value.

## 7. Position and league-format impacts

| Pos | rows | C0 | C1 | C2 (2 fam.) | C3 |
|---|---|---|---|---|---|
| DL | 165 | BUY 68 / SELL 57 / HOLD 4 / — 36 | BUY 54 / SELL 46 / HOLD 46 | BUY 39 / SELL 44 / HOLD 14 / n/a 68 | BUY 51 / SELL 70 / HOLD 8 |
| LB | 115 | BUY 83 / SELL 10 / HOLD 4 / — 18 | BUY 48 / SELL 11 / HOLD 50 | BUY 54 / SELL 6 / HOLD 6 / n/a 49 | BUY 69 / SELL 17 / HOLD 2 |
| DB | 150 | BUY 87 / SELL 18 / HOLD 7 / — 38 | BUY 63 / SELL 11 / HOLD 48 | BUY 46 / SELL 17 / HOLD 13 / n/a 74 | BUY 71 / SELL 28 / HOLD 7 |

- **By position.** LB is the most one-sided population under every candidate: the independent boards
  place linebackers above IDPTC. DL is the only balanced one. Nothing here is forced toward symmetry; a
  one-sided market may warrant one-sided results.
- **League format.**
  - IDPTC is scraped Superflex + TE-premium (`value_sftep`). Its IDP values reflect the vendor's own IDP
    scoring, a format the repository does not record.
  - `dynasty_main`'s IDP scoring (TFL and PD paid heavily) is not known to match it. An IDP "market edge"
    against IDPTC is measured in the vendor's format, not this league's.
  - League scoring fit is a different concept. Consensus Edge applies it inside the value, never as edge
    evidence. This proposal adds no league-format adjustment and changes no Superflex, TEP or IDP rule.
  - The IDP edge depends on `leagueKey` only for visibility, so `dynasty_new` is unaffected.
- **Picks.** Out of scope. Picks keep the KTC Market comparison.

## 8. Signal-independence audit (owner framing)

- **IDPTC's roles on IDP rows (pinned board):**
  - voter: median applied-weight share 74.2%, p90 100%; the only voter on 54 rows;
  - α-shrinkage anchor (`isAnchor`) on 377 / 377 priced rows;
  - shared-market ladder: the only contributor (`crossPositionBridges.ladder.contributors == ["idpTradeCalc"]`),
    so all 267 FantasyPros votes are placed on its ladder;
  - rookie ladder reference for `dlfRookieIdp` (`rookie-ladder-borrows-reference-scale`).
- **Its ordering may not be independent either.** It tracks The IDP Show closely (measured dependence;
  ancestry classified SUSPECTED in the registry). If the vendor-stated derivation reported on 2026-11-01
  is accepted, "IDPTC vs the IDP Show board" is one publication compared with itself. If it is not, they
  are two providers in agreement, which is consensus under the 2026-10-19 directive.
- **Offense contrast (owner-accepted).** KTC Crowd + Trades carry a median 16.5% of offense rows' applied
  weight (p90 32.7%). The offense benchmark is a correlated descendant, but a minority one. On IDP the
  benchmark is the majority of the model. That is why the offense formula cannot be copied to IDP: C1's
  slope of 0.265 is the measured compression.
- **Agreement vs duplication** (owner directive 2026-10-19). Draft Sharks and FantasyPros agreeing with
  each other is consensus, and C2 counts both. Excluding The IDP Show is **proposed, not settled**:
  - the registry classifies its ancestry as SUSPECTED;
  - measured lead-lag and a 0.998 Spearman are similarity, which by themselves never merge votes;
  - the only basis that could qualify is the vendor statements reported on 2026-11-01, which the registry
    has not adopted.

  D1b asks the owner to choose. §4.2 shows both outcomes.

## 9. Historical predictive evaluation

- **Question.** Does the IDP signal at date t predict IDPTC's price move from t to t + h, relative to the
  IDP cohort's median move? This is the market converging to the evidence.
- **No look-ahead.** Every input is the last tracked CSV at or before t.
- **Outcome.** The IDPTC price at t + h.
- **Expected sign** if the signal works: hit rate > 0.5 and Spearman < 0.
- **Signals tested:** C2 at CSV level (within-IDP ranks priced on IDPTC's IDP ladder, The IDP Show
  excluded) and an incumbent-like replay (GLOBAL Hill vs IDPTC).

| horizon | origins | signal | observations | directional, moved | hit rate | Spearman |
|---|---|---|---|---|---|---|
| 14 d | 13 (07-27 … 10-19) | C2 | 2815 | 1397 | 0.511 | −0.031 |
| | | incumbent-like | 4306 | 2232 | 0.514 | −0.016 |
| 28 d | 11 (07-27 … 10-05) | C2 | 2327 | 1812 | 0.494 | −0.029 |
| | | incumbent-like | 3612 | 3005 | 0.501 | −0.014 |
| 56 d | 7 (07-27 … 09-07) | C2 | 1360 | 1138 | 0.464 | +0.002 |
| | | incumbent-like | 2238 | 2023 | 0.473 | −0.027 |

C2 with The IDP Show admitted (sensitivity, §4.2): 14 d 3244 / 1544 / 0.505 / −0.013; 28 d 2678 / 2036 /
0.486 / −0.008; 56 d 1556 / 1295 / 0.461 / −0.000.

- **Per origin** (28 d): hit rates run 0.43–0.60. The only negative-ρ stretch is the three origins of
  2026-08-24 … 09-07 (ρ −0.09 to −0.12), which bracket the 08-20 and 08-26 IDP Show republications.
- **The outcome is not degenerate.** IDPTC repriced 249–343 of about 370 IDP players inside every 28-day
  window.
- **Conclusion: the evidence is insufficient, and it points to no predictive value.** Overlapping horizons
  and the same players at every origin leave only about 3–4 independent 28-day windows. The naive binomial
  interval (0.494 ± 0.023) contains 0.5.
- **What it cannot do.** It cannot validate C2 or replay the incumbent exactly. The incumbent needs
  historical contracts, which would mean rebuilding with point-in-time dataset state and code.
- **What would enable a real evaluation:**
  1. a forward shadow log of the stamped C2 per board over several IDPTC repricing cycles;
  2. realized IDP **trade prices**, for example IDP trades in the completed-trade ledger with format
     evidence, as a revealed-price benchmark independent of every vendor;
  3. multi-season realized IDP production under the corrected scorer (#1938), for a value-level test.

Data caveats:

- IDPTC CSVs carry positions only from 2026-10-21. Earlier IDP membership comes from IDP-only expert
  boards or later IDPTC labels (identity, not price). Names IDPTC labels as offense are excluded.
- DLF IDP has no positions before 2026-10-22 and is treated as IDP-only.
- The fresh-only variant equals the all-experts variant here: every non-IDP-Show board changed within
  14 days of every origin.

## 10. Confidence, calibration and uncertainty

- **Dispersion swamps the threshold.** C2's absolute gap is median 0.25 (p90 0.61) against the 5% display
  threshold. Nearly every available row is directional, so on this evidence BUY/SELL says little more
  than "two boards disagree". If C2 reaches shadow, its threshold should be calibrated to cross-source
  dispersion, as Consensus Edge's cohort-robust z-score does, before any label is shown. The 5% (offense)
  and 15% (/edge summary) thresholds are unvalidated for IDP.
- **IDP confidence is already low.** B11 buckets every priced IDP row `low` on this board (398 `low`,
  32 unpriced `none`): few families and a stale majority.
  The proposed gates use B11's own unit, the provider family, and the freshness model's own unit, one
  full-strength provider. No new statistic.
- **Gate flicker.** Draft Sharks' weight cycles with its 14.3-hour cadence, between 1.0 just after a
  publish and about 0.2 two days later. FantasyPros stays at 0.13 until it republishes. A W = 1.0 gate
  would pass only during Draft Sharks' fresh window (1.0 + 0.13 = 1.13). Signals would flicker, so the
  shadow evaluation must measure the pass rate across cycles before any UI exposure.

## 11. Canonical contract proposal (not implemented)

**Rule:** ONE backend owner stamps the edge for every population. The frontend reads it and never
computes it. A missing benchmark, missing evidence or failed gate is an explicit state with a reason,
never neutral, never zero, never a fabricated gap.

### 11.1 Per-row block `marketEdge` (private: added to the public blocklist beside `marketGap*`)

```json
{
  "population": "offense | idp | pick",
  "comparison": "model_vs_benchmark | anchor_free_evidence_vs_benchmark",
  "benchmark": {
    "key": "ktcCrowdTradesSfTep | idpTradeCalc | null",
    "definition": "ktc_published_crowd_trades | idp_trade_calculator_reference_price",
    "isModelInput": false,
    "evidenceExcludedFamilies": ["idpTradeCalc", "idpShow (only if D1b = exclude)"],
    "value": 5409.0,
    "lastGenuineUpdate": "2026-11-06T02:56:01Z"
  },
  "state": "available | unavailable | withheld",
  "reason": null,
  "direction": "benchmark_premium | evidence_premium | aligned | null",
  "ratio": null,
  "evidence": {
    "value": null,
    "families": ["draftSharks", "fantasyPros"],
    "appliedWeight": 0.3473,
    "minFamilies": 2,
    "minAppliedWeight": 1.0,
    "sources": {"draftSharksIdp": {"appliedWeight": 0.2173, "lastGenuineUpdate": "…"}}
  },
  "methodVersion": "market_edge.v0-proposal",
  "boardAsOf": "2026-11-07T06:39:55Z"
}
```

**`reason` vocabulary**, kept closed and testable:

- `no_benchmark_coverage` (with `benchmarkReason` `no_ktc_coverage` / `no_idptc_price`)
- `no_model_value`
- `withheld_quarantined`
- `no_independent_evidence`
- `insufficient_independent_families`
- `insufficient_evidence_weight`
- `benchmark_lineage_only`
- `population_has_no_benchmark`

**Benchmark per population:**

- **offense.** KTC Market, `model_vs_benchmark`. Byte-identical to today's `marketGapDirection` /
  `marketGapValueRatio`, which stay as backward-compatible offense fields.
- **idp.** IDPTC, `anchor_free_evidence_vs_benchmark` (C2) with the gates above. `isModelInput: true` is
  stamped honestly, because IDPTC does vote, and `comparison` names why the model value is not the
  comparator.
- **pick.** Unchanged (KTC Market).

**Board-level `marketEdgeSummary`** per population carries:

- the counts by state and reason;
- the benchmark identity;
- the benchmark's median applied-weight share of the model on that population, so the double role is
  disclosed, not hidden.

### 11.2 Consumers (one reader each, no client-side math)

- **/rankings.** The Edge cell and the `edge=` filter read `marketEdge.state` / `direction`. An IDP row
  shows its reason instead of "offense only" once the stamp exists.
- **/edge.** `idpMarketEdge` / `idpMarketAction` / `isIdpInTopByIdptc` are **deleted**. The IDP panels
  read the stamp. Panel population is selected on a side-neutral quantity (board rank, or the mean of
  benchmark and evidence), never on the benchmark's own rank. Panels sort on the stamped ratio.
- **Popup, player page, trade rows, League Edge Map.** These read the stamp and show the per-row reason.
  The League Edge Map states which populations its totals cover.
- **MCP / public.** `marketEdge` joins `_PRIVATE_FIELD_BLOCKLIST` (§5 private decision intelligence).
- **Consensus Edge, finder, BDVM.** Untouched by this contract, and listed as separately named concepts:
  - the finder's IDP arbitrage keeps its own named arithmetic;
  - Consensus Edge's C3 premise is flagged stale (§4);
  - BDVM is W13-F003.

## 12. Downstream consumer effects of adopting the recommendation

| Consumer | Today | After D1a/D1b + D3(c) |
|---|---|---|
| /rankings Edge, IDP | "offense only" | "IDP edge unavailable: insufficient independent evidence (0.35 of 1.0)" or a stamped direction |
| /rankings filter | silently 0 IDP | includes IDP rows with `state == available` |
| /edge IDP panels | 10 SELL + 10 BUY, unsorted, from a second detector | stamped C2, or an explained empty state (today: empty, reason shown) |
| Popup / player page / trade rows | nothing for IDP | per-row reason |
| League Edge Map | IDP silently excluded | coverage disclosed; IDP included when available |
| Player values, ranks, tiers, confidence, trade/BDVM/FAAB math | — | **no change** (the edge is a stamp) |

## 13. Rollback

- **This PR.** Additive research files only: `scripts/research/`, one test, one fixture and this document
  with its evidence. Rollback means deleting them. No served path is touched.
- **For a future activation:** the `marketEdge` block would be additive and behind a feature flag (default
  OFF until the owner approves). Rollback would be flag off plus a restart. The stamp is then withheld and
  the frontend falls back to today's behavior. `marketGapDirection` / `marketGapValueRatio` keep their
  offense meaning throughout, so no consumer of the existing fields can break.

## 14. Recommendation

1. **Adopt IDPTC as the canonical IDP reference-price benchmark, with C2 as the IDP edge definition.**
   Never use C1 (model vs IDPTC) as a published edge. Gates: at least 2 independent families and at least
   1.0 applied-weight provider-equivalents.
   - Whether The IDP Show counts as evidence is the owner's D1b. Today it makes no difference (zero
     weight). After an IDP Show refresh it decides 273 rows (§4.2).
   - Either way, the sources lane should first settle the registry relation (SUSPECTED vs vendor-stated)
     under the 2026-10-19 rule.
2. **Send C2 to an owner-approved shadow evaluation.** Compute and record the stamp per board with no UI.
   Preregister these success criteria before any exposure:
   - the gate pass rate across Draft Sharks' publication cycle;
   - a hit rate of at least 0.55 whose interval excludes 0.5, over at least 8 non-overlapping horizons,
     against IDPTC repricing;
   - where available, agreement with realized IDP trade prices.
3. **Do not promote C3** until the leave-out bridge swap (Draft Sharks ladder, 93 extrapolations) is shown
   to keep the IDP scale.
4. **Retire the /edge second detector.** Interim choice: D3 below.

## 15. Owner decision requested

- **D1a. Canonical IDP edge definition.** Approve, reject or modify: "The IDP market benchmark is the IDP
  Trade Calculator's published price. The IDP edge compares that price with evidence that excludes IDPTC,
  with each source's placement priced on IDPTC's own curve (C2). It is published only with at least
  2 independent provider families and at least 1.0 freshness-weighted provider-equivalents; otherwise it
  is unavailable with a named reason." If modified, name the gate values.
- **D1b. The IDP Show as evidence against IDPTC.** Choose one:
  - **exclude** it, treating the vendor statements reported in
    `docs/sources/IDP_SHOW_LIBRARY_AUDIT_2026-11-01.md` §6 as credible shared-data lineage under the
    2026-10-19 rule. This would also require upgrading `idptc-idpshow-suspected-ancestry` from SUSPECTED;
  - **include** it as an independent provider, which is the default under the 2026-10-19 rule while the
    registry says SUSPECTED.

  Impact: 0 rows today; after an IDP Show refresh, 273 rows available vs 0 under the W ≥ 1.0 gate (§4.2).
  The proposal's default code path excludes it, but that default is not a recommendation to bypass the
  rule. If the owner makes no decision, the 2026-10-19 rule (include) governs.
- **D2. Shadow evaluation.** Authorize the backend to compute and record (not display) the C2 stamp per
  board behind a default-OFF flag, for at least 8 weeks, with the preregistered criteria in §14.2.
  Yes / no.
- **D3. Interim /edge IDP BUY/SELL panels** (presentation only; no methodology). Choose one:
  - (a) keep as is;
  - (b) relabel as "IDPTC vs IDP-expert disagreement — not a market signal", remove the BUY/SELL verbs,
    disclose the evidence weight and the IDP Show relation (registry: SUSPECTED ancestry), and fix the
    Gap parsing and source list;
  - (c) replace with the per-row unavailable reason until D1/D2 conclude.

  **Recommended:** (c). The fallback is (b). Either removes the contradiction with /rankings without
  inventing an IDP gap.

The display defects in §3.6 are independent of D1–D3 and can be routed to the UI lane as ordinary fixes:
the Gap parsing, the "FootballGuys IDP" note, the offense compare-page colour, and the silent IDP
exclusion on the popup, player page, trade rows and League Edge Map.

## 16. Reproduction

```bash
python scripts/research/w27_f001_idp_edge_benchmark.py extract --with-loo   # rebuild the fixture (pinned archive)
python scripts/research/w27_f001_idp_edge_benchmark.py analyze              # all §3–§8 numbers
python scripts/research/w27_f001_idp_edge_benchmark.py oracle               # §5 CSV oracle
python scripts/research/w27_f001_idp_edge_benchmark.py history --horizon-days 28   # §9 (needs full-depth git)
node scripts/research/w27_f001_frontend_crosscheck.mjs                       # real frontend module
python -m pytest tests/scripts/test_w27_f001_idp_edge_benchmark.py -q        # 20 tests
```

Evidence outputs: `docs/valuation/methodology_proposals/evidence/w27_f001/`.

## 17. Limitations

- **One board.** The share, gate and weight results describe the 2026-11-07 board. IDPTC's own freshness
  weight was 0.303 on 2026-10-28 (`docs/sources/IDP_SOURCE_AUTHORITY_2026-10-28.md`). So the IDPTC share
  and C2's gate pass rate move with publication cycles. The shadow evaluation exists to measure that.
- **The fixture reads HEAD's tracked CSVs.** It is built from the archive payload plus the tracked CSVs and
  dataset state at d7db52a43b, as the repository's archive fixtures are. The Draft Sharks CSV at that
  commit was committed 4 minutes after the scrape timestamp, and the archive's own copy carries the
  same ranks. Hashes are recorded.
- **The history replay is CSV-level.** It is exact for ladder-translated boards. For Draft Sharks it uses
  the vendor's published IDP rank, not the pipeline's combined-list placement.
- **No independent IDP price exists in the repository.** There is no realized trade price and no second
  crowd market. "No predictive value found" is a statement about IDPTC convergence, not about value
  accuracy.
- **IDPTC's IDP scoring format is a vendor property.** It is not reconciled with `dynasty_main`'s scoring;
  no data in the repository measures that gap.
