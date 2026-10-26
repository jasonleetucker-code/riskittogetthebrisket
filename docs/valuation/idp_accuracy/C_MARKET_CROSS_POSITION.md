# Lane C-market: cross-position market baseline (IDP vs offense), 2026-10-25

**Status:** research only, shadow only. Nothing here changes a served value, rank, source weight, vote, Hill curve,
bridge, IDP ceiling, package model (`geom_q078_v1`), fairness band (`fairness_bands_v2`), flag default, route or
public output. Every alternative below is an offline contract built in a separate interpreter and then thrown
away. Nothing in `src/` imports the research script, and a test pins that.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §6C, §9 (Lane C, Deliverable C
baseline). That directive authorizes research and shadow work only.

**Evidence:** `docs/valuation/idp_accuracy/evidence/c_market_baseline_2026-10-25.json`. It holds aggregates and
public NFL player names only: no manager or team names, no user, owner or roster ids, no raw Sleeper league id, and
no per-team roster listings (`assert_aggregate_only`, pinned by a test over the committed file).

**Reproduce:**

```bash
python scripts/idp_accuracy/market_baseline.py            # ~2 min; Sleeper + two public vendor pages, raw-cached
python scripts/idp_accuracy/market_baseline.py --offline  # re-run from the cache, byte-identical output
python -m pytest tests/idp_accuracy/test_market_baseline.py -q
```

The cache (`data/research_cache/idp_c_market_raw/`, gitignored) holds each response body byte for byte and the
evidence records its sha256 (`inputs.sleeperReceipts`, `leagueFormatAlignment.statedFormat`). A re-run reuses the
cache, so it reproduces the same inputs; `--refresh` refetches. Output does not depend on the Python hash seed
(checked under two seeds).

**Verdict on the shared-market anchor: NOT_JUSTIFIED.** Nothing independently shows that the anchor represents
this league. The cross-position level comes from two external dynasty markets. One is a generic public calculator
whose own page states a different basis from this league's card: Big 3 IDP scoring, 0.5 PPR, a TE premium, and no
statement of IDP starters or best ball. The other is a vendor board synced to this league, but the sync cannot be
verified from the data. The two markets agree on the median IDP level and disagree about who the elite defenders
are, and agreement between markets is consensus about **market price**. It is not evidence of **league utility**.
This verdict does **not** say the level is wrong. Whether it is wrong is UNRESOLVED and belongs to Lanes B and D
(replacement and lineup utility, and independent backtesting).

---

## 0. Pinned inputs and the cross-check against Lane A

| input | value |
|---|---|
| code | branch `claude/idp-c-market-baseline`. `inputs.scriptSha256` identifies the script that produced the evidence |
| repository tree read by the contract build (CSVs, scrape stamps, weights) | `bdbc83a1f` (main, 2026-10-25 16:55 UTC), content sha256 `80e5f8da…` |
| served artifact | `exports/archive/dynasty_export_20261025_120337.zip`, sha256 `50fb251a…`, scrape 2026-10-25 12:03 UTC. Fields read: `rankDerivedValue`, `canonicalConsensusRank`, `canonicalSiteValues`, `confidenceBucket`, `quarantined` and `sourceRankMeta`. No scraper `_composite` field is read, and a test pins that |
| league | `dynasty_main`. Scoring fingerprint `sf1:9e51824690d091f9` (live card equals the archived contract's card). Roster-format fingerprint `rf1:10f897578eea2fe4`. 12 teams, 58 roster spots, 21 starters (QB 1, RB 2, WR 3, TE 2, FLEX 2, SUPER_FLEX 1, K 1, DL 3, LB 3, DB 3), best ball |
| production | Sleeper weekly stats, 2026 regular season weeks 1–6, all games final. Week 7 was in progress and is **excluded** |
| pre-season (point-in-time) board | `dynasty_export_20260909_211525.zip`, the latest archive strictly before the week-1 kickoff (NE @ SEA, 2026-09-10 00:20 UTC, nflverse `games.csv`). Scraped 21:15 UTC. Its source tree is `bd7eda605`, that scrape's data-refresh commit (21:17 UTC), also before kickoff. Both orderings are pinned by tests |

**Cross-check against Lane A's manifest** (`MANIFEST.json`, sha256 `d0d9931d…`, PR #1931). The script compares its
own inputs with the manifest and records the result in `inputs.laneAManifestCrosscheck`:

| item | result |
|---|---|
| served-board hash (`servedBoardSha256`, `4e6ba1f5…`) | **match**. This lane's in-process build of the served board is the board Lane A pinned |
| archive sha256 | match |
| scoring fingerprint (live card and archived contract card) | match |
| roster-format fingerprint | match |
| Sleeper responses (league card, rosters, six matchup dumps, six weekly stat dumps) | **14 of 15 byte-identical** by sha256. The player directory (`/players/nfl`) differs, as expected for a daily-changing file; it supplies positions only |
| host-native scorer | Lane A's 3,710 of 3,710 and Investigation B's 3,299 of 3,299 are the **same scorer** with and without the `gp > 0` filter. Reproduced here: 3,299 of 3,299 and 3,710 of 3,710, max difference 0.0044, and 461 rostered player-weeks have no stat line and were awarded 0. This lane uses B's filter for points per game and the unfiltered line set for best-ball replay |

The archive and the tree come from different scrapes, and this was deliberate. The archive is the 12:03 UTC scrape.
Tree `bdbc83a1f` carries the CSVs of the 16:50 UTC refresh. I used the tree the lane named. Rebuilding from the
archive's own `site_raw/` files would move some numbers slightly. Every `site_raw` hash in the archive is recorded in
`inputs.archiveSiteRawSha256`. The perturbation worker's baseline build is byte-identical to the in-process build
(`controlBaselineMatchesInProcess: true`).

## 1. Baseline: where defenders sit on the served board

**Top 100 overall (served rank):** QB 20, RB 21, WR 30, TE 12, LB 9, DL 3, DB 0, PICK 5.
**Top 200 overall:** QB 29, RB 37, WR 52, TE 28, LB 24, DL 13, DB 6, PICK 11. The full lists are in
`baseline.top100` and `baseline.top200`.

**Highest-ranked defenders:** Carson Schwesinger (LB, rank 34, value 6,287), Jack Campbell (LB, 50, 5,443), Arvell Reese
(DL, 63, 5,071), Sonny Styles (LB, 66, 5,023) and Aidan Hutchinson (DL, 75, 4,642). The first defender appears at rank
34. Ranks 1–25 hold no defender.

**Top 10 per family** (the top 25 with confidence buckets is in `baseline.top25ByPosition`):

| # | DL | rank / value | LB | rank / value | DB | rank / value |
|---|---|---|---|---|---|---|
| 1 | Arvell Reese | 63 / 5,071 | Carson Schwesinger | 34 / 6,287 | Nick Emmanwori | 106 / 3,989 |
| 2 | Aidan Hutchinson | 75 / 4,642 | Jack Campbell | 50 / 5,443 | Dillon Thieneman | 122 / 3,688 |
| 3 | Will Anderson | 92 / 4,242 | Sonny Styles | 66 / 5,023 | Caleb Downs | 130 / 3,526 |
| 4 | Dallas Turner | 119 / 3,725 | Jacob Rodriguez | 78 / 4,624 | Kevin Winston | 157 / 3,237 |
| 5 | David Bailey | 131 / 3,500 | Cedric Gray | 84 / 4,444 | Cooper DeJean | 184 / 2,940 |
| 6 | Abdul Carter | 132 / 3,480 | Nick Bolton | 86 / 4,356 | Kyle Hamilton | 191 / 2,803 |
| 7 | Myles Garrett | 143 / 3,381 | Fred Warner | 88 / 4,313 | Brian Branch | 218 / 2,614 |
| 8 | Micah Parsons | 158 / 3,231 | Jihaad Campbell | 89 / 4,306 | Tykee Smith | 220 / 2,604 |
| 9 | Maxx Crosby | 175 / 3,006 | Edgerrin Cooper | 96 / 4,156 | Derwin James | 271 / 2,274 |
| 10 | Greg Rousseau | 182 / 2,950 | Ernest Jones | 110 / 3,909 | Antoine Winfield | 299 / 2,154 |

**Rank bands** (share of players that are IDP, in `baseline.rankBands`):

| band | 1-25 | 26-50 | 51-100 | 101-150 | 151-200 | 201-300 | 301-400 | 401-500 | 501-800 |
|---|---|---|---|---|---|---|---|---|---|
| IDP share | 0.00 | 0.08 | 0.22 | 0.33 | 0.33 | 0.38 | 0.52 | 0.47 | 0.60 |

**Value distributions** (priced rows, `baseline.valueQuantiles`): offense n 491, median 1,818, p90 5,416, max 9,983;
IDP n 397, median 1,488, p90 2,786, max 6,287.

**Value at equal depth.** The table compares the k-th best defender with the k-th best offense player. It
measures level only and says nothing about whether the level is correct.

| k | offense value | IDP value | IDP / offense |
|---|---|---|---|
| 1 | 9,983 | 6,287 | 0.63 |
| 10 | 8,959 | 4,306 | 0.48 |
| 25 | 6,975 | 3,480 | 0.50 |
| 50 | 5,416 | 2,614 | 0.48 |
| 108 (last league-wide IDP starter) | 3,400 | 1,882 | 0.55 |

**Starter pools.** The top 108 defenders have a median value of 2,545 (p10 1,921, p90 4,182). The top 132 offense
players have a median of 4,734 (p10 3,224, p90 8,035). Ratio of medians 0.54.

**Coverage and confidence** (`baseline.coverageByPosition`). The evidence behind IDP values is thin, and that is a
fact about the board, not a judgment:

- Every one of the **397 priced IDP rows** has `confidenceBucket = low`. That includes all 36 rows in each
  family's starter-depth pool (top 36).
- Offense starter pools are mostly `high`: QB 19 of 24, RB 21 of 24, WR 22 of 24, TE 17 of 24.
- The median IDP row has **3 voting sources** (range 1–3). The median offense row has 12–14.
- 51 IDP rows rest on a single voter (DL 20, LB 13, DB 18).

**Evidence census** (`baseline.evidenceCensus`):

- Of the IDP-capable markets, three vote:
  - `idpTradeCalc`: content last changed 14 days ago, freshness 46%. Its own page says "Updated: 10/10/2026".
  - `draftSharksIdp`: 1 day, 62%.
  - `fantasyProsIdp`: 51 days, 24%.
- Four do not vote:
  - `idpShowCombined`: stale for 66 days, freshness 0. It is withheld on all 301 IDP rows it covers.
  - `dlfIdp`: status `testing`.
  - `signalsIdp{Dl,Lb,Db}`: `data_issue`.
- Weight states: 359 of 397 IDP rows are `SEVERELY_DEGRADED` and the other 38 are `DEGRADED`.
- 9 IDP rows are quarantined (`no_valid_source_values`); 51 carry `suspicious_disagreement`. 32 IDP rows are unpriced;
  they stay missing, never 0. Offense: 11 unpriced, 0 quarantined.

## 2. Starters vs bench by price band (live rosters, weekly best ball)

Method:

- The rosters are the 12 live `dynasty_main` rosters (696 players), byte-identical to the rosters in Lane A's manifest.
- For each team and each week (1–6), the lineup is the exact optimum (`solve_optimal_assignment`) under that week's
  realized league-scored points. Lane A verified that this solver reproduces Sleeper's own best-ball totals exactly.
- A player with no stat line that week scored 0, which is a real realized zero in best ball.
- Classes by start share: `regular` started in at least half of the weeks, `spot` started at least once, `never`
  did not start.
- Counts are aggregated over all teams.

| band | offense players / regular share | IDP players / regular share |
|---|---|---|
| 1000-1500 | 58 / 0.19 | 79 / 0.25 |
| 1500-2000 | 82 / 0.26 | 94 / 0.39 |
| 2000-3000 | 87 / 0.46 | 52 / 0.52 |
| 3000-4500 | 57 / 0.47 | 30 / 0.70 |
| 4500+ | 74 / 0.77 | 6 / 0.83 |
| unvalued | 1 / 0.00 | 31 / 0.16 |

**Mean points of the player who filled each slot** (realized, weeks 1–6): DL 17.75, LB 17.62, DB 18.28, RB 18.39,
WR 19.12, TE 12.51, FLEX 12.13, SUPER_FLEX 16.53, QB 27.27.

**What this shows:**

- At every price band, defenders are regular best-ball starters at least as often as offense players. In the
  1,500–4,500 bands they start about 1.1–1.5x as often.
- The defenders who fill IDP slots score about what RB and WR starters score.
- Yet the defensive starter pool costs about half as much (§1).

**What it does not show:** that defenders are underpriced. Start share and starter points are not marginal value.
Replacement depth differs by position: Investigation B found DB waiver alternatives that come close to starter
production. Lanes B and D own that question.

**Caveats:**

- The rosters are today's, replayed over weeks 1–6. A player acquired mid-season is credited for weeks he spent
  elsewhere.
- This is realized production, not expected production.

## 3. The native IDP Trade Calculator distribution

`idpTradeCalcNative` is computed from `canonicalSiteValues.idpTradeCalc` and covers 432 offense, 377 IDP and 84
pick rows. On its own scale, the median offense value is 2,335 and the median IDP value is 1,247 (p90: 5,606 vs
3,188). Its top defender, Aidan Hutchinson (6,444), is the 24th player overall on IDPTC's own board, or 29th if
picks count.

The table compares where the k-th defender sits on each board. Ranks count players only.

| k | IDPTC's k-th defender: player rank | Draft Sharks combined: player rank | canonical: player rank | canonical value / IDPTC value |
|---|---|---|---|---|
| 1 | 24 | 18 | 34 | 0.98 |
| 3 | 45 | 32 | 62 | 0.90 |
| 10 | 59 | 69 | 86 | 0.80 |
| 25 | 126 | 122 | 126 | 0.97 |
| 50 | 194 | 275 | 206 | 0.87 |
| 108 | 374 | 424 | 341 | 0.97 |

**Control: the same comparison for offense.** At equal k, the canonical/IDPTC ratio is 1.00 (k = 1), 1.13 (k = 10),
1.08 (k = 25), 1.03 (k = 50) and 0.95 (k = 132).

**Finding: the canonical board places elite defenders lower than either bridge market does on its own.** The top
defender is the 34th player on the canonical board, the 24th on IDPTC's and the 18th on Draft Sharks'. At k = 10 the
canonical defender is worth 0.80 of IDPTC's k-th defender, while offense at k = 10 is worth 1.13.

The mechanism is identity disagreement. Every market gets one vote, and the bridges disagree about **who** the elite
defenders are:

- IDPTC's #1 defender (Hutchinson, effective rank 29) is rank 167 on Draft Sharks.
- Draft Sharks' #1 (Schwesinger, rank 18) is rank 54 on IDPTC.

Blending two or three disagreeing votes pulls each player toward the middle, so the top of the IDP population
compresses. Offense has 12–14 agreeing voters per row, so the same effect is far weaker there. The two orders still
broadly agree among IDPs: Spearman between IDPTC's rank and the canonical rank is 0.91 (n 377), and for Draft Sharks
it is 0.86 (n 295). This is a property of the consensus estimator on a thin, disagreeing panel. It is neither a
defect in a source nor evidence about league utility.

### 3b. IDP value as a share of offense value, on each market's own scale

`nativeLevelRatios` gives the k-th defender's value over the k-th offense player's value, each market on its own
scale:

| k | canonical | IDPTC | Draft Sharks `3D Value +` |
|---|---|---|---|
| 1 | 0.63 | 0.64 | 0.45 |
| 3 | 0.51 | 0.57 | 0.45 |
| 10 | 0.48 | 0.68 | 0.42 |
| 25 | 0.50 | 0.56 | 0.44 |
| 50 | 0.48 | 0.57 | 0.39 |
| 108 | 0.55 | 0.55 | 0.31 |
| top-108 IDP median / top-132 offense median | 0.54 | 0.61 | 0.48 |

Read it with two caveats:

- Draft Sharks' `3D Value +` is a vendor value-over-replacement number in whole units (its best offense player is
  100). Its ratios are not the same kind of quantity as the other two columns, and deep-k ratios are coarse. The
  2026-08-20 audit measured its best defender at 53% of its best offense player; today's file gives 45%.
- The pipeline uses Draft Sharks' combined **order** (rank-signal), not this cardinal ratio, so the DS column
  describes the vendor's statement, not an input to the board (§4).

The canonical level sits below IDPTC's own at most depths and above Draft Sharks'. That is what a blend of the two
looks like, and it is the only sense in which the board "agrees" with either.

## 4. How cross-position level enters consensus (code trace)

Each step below is traced to its live code path and checked against `sourceRankMeta` on the pinned board
(`bridgeTrace.votePoolCensus`).

1. **Every IDP vote is priced in the shared-market pool on the GLOBAL Hill master** (`c` 0.112, `s` 0.725). No IDP
   vote reaches the IDP master (`c` 0.083, `s` 1.11) on this board. The pool is chosen by
   `src/canonical/rank_coordinates.py`: "a translation moves a rank into the pool of the ladder it was translated
   through". The four IDP voters reach that pool by different routes:
   - `idpTradeCalc` (377 rows) is **value-signal**: raw / site max × 9,999 (`value_direct`). Its offense and IDP
     values sit on one native 0–9,999 scale.
   - `draftSharksIdp` (321 rows) is **rank-signal**. `ds_combined_cross_market` merges the vendor's offense and IDP
     halves (one league-synced session) into one combined `3D Value +` order.
   - `idpShowCombined` (301 rows) is **rank-signal**, using the vendor's own combined rank. It is withheld on this
     board because it is stale.
   - `fantasyProsIdp` (271 rows) is **rank-signal and IDP-only**. It is crosswalked through the shared-market ladder
     (`needs_shared_market_translation`, `sharedMarketTranslated: true`).

   On the offense side, most voters (KTC Crowd and Trades, DLF, Dynasty Daddy, FantasyCalc and others) are priced in
   the offense pool. Only IDPTC, Draft Sharks and IDP Show offense rows share the shared-market pool with the IDP
   rows. That shared pool is how an IDP value becomes comparable with an offense value at all.
2. **The shared-market ladder is seeded by one bridge: `idpTradeCalc`.** `config/bridges/bridges_v1.json` declares
   three bridges:
   - `idpTradeCalc`: QUALIFIED and capable. Its ladder starts at combined rank 29 with depth 377.
   - `draftSharks`: QUALIFIED and capable. Its ladder starts at 18 with depth 176.
   - `dynastyDealer`: PENDING.

   `src/bridges/ladder.py::build_bridge_ladder` admits only the first usable bridge in registry order, because
   `multi_bridge_ladder` defaults to OFF (`limit=1`). The ladder sets only the level of IDP-only rank sources, which
   today means only `fantasyProsIdp`.
3. **The hierarchical anchor decides about 90% of each IDP value.** On IDP and pick rows,
   `value = anchor + α·(subgroup − anchor)` with `α = 0.10`, where:
   - the anchor is the count-aware blend of the `is_cross_market` sources (`_anchor_key_sets`: `idpTradeCalc`,
     `draftSharks`, `draftSharksIdp`, `idpShowCombined`);
   - the subgroup is everything else, which on IDP rows today means only `fantasyProsIdp`.

   Offense rows use a flat count-aware blend.

   Among the top 108 defenders, the voting anchor sets are:
   - `{draftSharksIdp, idpTradeCalc}`: 101 rows;
   - `{idpTradeCalc}` alone: 6 rows;
   - `{draftSharksIdp}` alone: 1 row.

   The mean anchor weight is 0.903.
4. **What anchors the top defender.** Carson Schwesinger (served rank 34, value 6,287):

   | voter | pool / signal | effective rank | value contribution | applied weight |
   |---|---|---|---|---|
   | `draftSharksIdp` (anchor) | shared market, rank-signal | 18 | 7,032 | 0.624 |
   | `idpTradeCalc` (anchor) | shared market, value-signal | 54 | 5,637 | 0.424 |
   | `fantasyProsIdp` (subgroup) | shared market, translated | 68 | 4,671 | 0.241 |
   | `idpShowCombined` | shared market, rank-signal | 90 | 4,164 | 0 (withheld, stale) |

   Anchor value 6,468, subgroup value 4,671, and 0.9 × 6,468 + 0.1 × 4,671 = 6,288. Two anchors set the placement:
   Draft Sharks (updated a day ago) and IDPTC (14 days since a content change). Draft Sharks' contribution lifts him
   above IDPTC's, and the stale IDP Show vote is withheld.
5. **Which market sets the level** (`topIdpLevelAttribution`). Each vote's influence is attributed to the market
   its cross-position level came from, and a translated vote is attributed to the ladder seed. Over the top 108
   defenders this gives **Draft Sharks 0.51, IDPTC 0.49**. This is an influence share by weight, not an exact
   derivative: the blend is a weighted mean-median. §5 measures the response directly and it is **not** symmetric.

**Answer to "where does a single external market decide cross-position level?"** Today the two cardinal bridges agree
on the median IDP level, so removing either one leaves it unchanged (§5), and in that sense no single market decides
it. If they disagreed, the board would follow **IDPTC's cardinal level about two to three times more closely than
Draft Sharks'** (log-elasticity 0.43–0.46 against 0.13–0.23), because IDPTC alone passes an offense-relative
**value** through, while Draft Sharks enters as an order. IDPTC alone also seeds the ladder that sets the level of the
IDP-only boards (a ±1% lever today).

## 5. Perturbations (offline shadow builds, measurement only)

Each variant is a fresh build of the pinned inputs with one change. The comparison set is the baseline's top 108
defenders and top 132 offense players, matched by name. "IDP median ratio" is the median of variant/baseline
values, which is robust to the few rows that fall to the ×0.30 single-source haircut when a variant leaves them a
single voter. The geometric mean is also published; it is not robust to those rows. In every row of the table below
the offense median ratio stays between 0.999 and 1.0003, so these are IDP-relative moves.

| variant | IDP median ratio | top defender rank | IDP in top 100 | IDP in top 200 |
|---|---|---|---|---|
| baseline | 1.000 | 34 | 12 | 43 |
| remove `idpTradeCalc` (votes and ladder seed; Draft Sharks seeds instead) | 1.001 | 30 | 15 | 41 |
| remove Draft Sharks (both halves) | 1.000 | 34 (Hutchinson) | 12 | 54 |
| remove `idpShowCombined` | 1.000 | 34 | 12 | 44 |
| ladder seeded by Draft Sharks instead of IDPTC | 1.002 | 34 | 12 | 43 |
| ladder from every usable bridge (`multi_bridge_ladder` on, worker only) | 0.989 | 34 | 12 | 42 |
| ladder ranks ×0.80 / ×1.25 | 1.012 / 0.989 | 34 / 34 | 12 / 12 | 44 / 42 |
| IDPTC IDP values ×0.80 / ×1.25 | **0.909 / 1.108** | 40 / 26 | 8 / 17 | 37 / 52 |
| Draft Sharks IDP `3D Value +` ×0.80 / ×1.25 | **0.972 / 1.053** | 39 / 30 | 8 / 16 | 40 / 47 |

How to read it:

- **IDP placement responds to each bridge's IDP level, and much more to IDPTC's.**
  - Moving IDPTC's IDP values by ×0.80 / ×1.25 moves the median defender by −9.1% / +10.8%, a log-elasticity of
    0.43 / 0.46. The median defender's overall rank shifts by +23 / −21.5 places, and the top-100 IDP count swings
    between 8 and 17.
  - Moving Draft Sharks' IDP values by the same factors moves it by −2.8% / +5.3% (elasticity 0.13 / 0.23). That
    number counts the change in its combined ORDER, not a value, which is why it is smaller and asymmetric.
- **Removing either bridge entirely leaves the median IDP level unchanged** (±0.2%). The two markets agree on the
  level, so neither one alone carries it. They disagree on identity, though, so removing one reshuffles which
  defenders are elite: without Draft Sharks the top-200 IDP count rises from 43 to 54.
- **The ladder seed matters little today** (±1.2%), because the only IDP-only voter (FantasyPros) sits in the 10% subgroup.
- **The earlier single-source dependency is closed.** The 2026-08-20 audit
  (`docs/sources/CROSS_POSITION_SOURCE_AND_IDP_CEILING_AUDIT_2026-08-20.md`, §6) found that losing `idpTradeCalc`
  emptied the ladder and published IDP #1 at 9,999. With Draft Sharks now a qualified bridge, removing IDPTC leaves
  the median level at 1.001 and the top defender at rank 30.
- The perturbation sizes were chosen for scale, and they do not estimate how wrong either market is. **No variant
  is a candidate methodology**, and none should be read as a recommended level.
- **Coverage is checked, not assumed.** Each level perturbation records how many served IDP rows moved by the factor
  (`provenance.idpRowsMovedByTheFactor`) and the run refuses to continue below 99%. The IDPTC variant moves all 377 of
  its served defenders; Draft Sharks' moves all 295.

## 6. Does the external shared-market anchor represent this league?

### 6.1 What each bridge states about its own basis

**IDP Trade Calculator** (`idptradecalculator.com`, page title "The IDP Show Trade Calculator"). The raw home page
(13,544 bytes, sha256 in `statedFormat.idpTradeCalc.page`) states:

- a header of "12-Team/.5 PPR" and an update date of 10/10/2026, which matches the 14 days since its last content
  change in the source registry;
- in its meta description, that it is the official calculator of The IDP Show, built for IDP leagues using **Big 3
  scoring**;
- Superflex and TEP toggles. The scraper reads the DOM checkbox state back, and the pinned archive's capture evidence
  records both as **observed ON** (`basis: dom_checkbox_final_state`, 1,027 entries from the `value_sftep` column).

The page does not state a TE-premium magnitude, IDP starter counts, lineup or roster rules, or best ball (the page's
visible text is 193 characters and contains none of those words).

**"Big 3"** is defined by The IDP Show (`theidpshow.com/p/big-3-scoring`, dated 2021-09-23). It publishes the point
values (parsed into `statedFormat.theIdpShowBig3`), calls them its preferred IDP scoring, and says to assume them for
its player evaluations and mock drafts. Whether the calculator's numbers are actually computed under that card is the
vendor's claim, which this lane cannot verify.

**Draft Sharks** is driven with its league selector set to this league's synced copy (`scripts/fetch_draftsharks.py`,
a Draft Sharks league id, not the Sleeper id). The fetcher proves that the values **move** when the league is
activated; it does not prove that the vendor reproduces this card's custom keys (tiered reception, TFL and PD
prices). That is UNVERIFIED and cannot be observed from the CSV.

### 6.2 Measured mismatches

`leagueFormatAlignment.mismatches`. Points are 2026 weeks 1–6 league-scored (host-native) stat lines. Intervals are 95%
percentile bootstraps over players; "market starters" means the top 108 defenders (top 132 offense players) the
canonical board prices, so the pool is chosen by price and not by realized points.

| item | IDPTC states | league (verified card) | measured difference | result |
|---|---|---|---|---|
| teams | 12 | 12 | none | MATCH |
| Superflex | ON (observed) | 1 SUPER_FLEX slot | none | MATCH |
| reception scoring | ".5 PPR" | `rec` 0.10 + a catch-length tier (0.25 / 0.50 / 0.75 / 1.00 / 1.25 / 2.00) + 0.02 per WR catch | points attached to a catch: RB+WR+TE **0.72 [0.70, 0.74]** (n 379), WR 0.80, TE 0.68, RB 0.56, against 0.50 stated, so +44% per catch. Effect on points: offense market starters **×1.047 [1.038, 1.057]** (n 120); WR ×1.096, TE ×1.068, RB ×1.011, QB ×1.000 | MISMATCH, measured |
| other offense rules (first-down bonuses of 1.0 for RB/WR/TE and 0.4 for QB, 6-point passing TD, pass completion and incompletion rules) | not stated | present | not measured, because the header states nothing to compare against | UNAVAILABLE |
| TE premium | TEP toggle ON; magnitude not stated | `bonus_rec_te` 0.0, `bonus_fd_te` 1.0 (equal to WR and RB), 2 TE starter slots | direction only; the card pays a TE nothing extra per catch | MISMATCH (board-wide: the canonical TE++ target basis shares it) |
| IDP scoring | "Big 3" | solo 1.33, assist 0.80, TFL 4.24, sack 2.92, QB hit 2.12, PD 5.30, INT 5.30, FF 4.24, fumble recovery 3.19, TD 6.36, safety and blocked kick 5.30, return yards 0.111 | per-stat table below. Effect on points: defenders market starters **×1.077 [1.067, 1.087]** (n 100); all defenders ×1.088 [1.083, 1.093] (n 767); DL ×1.056, LB ×1.075, DB ×1.123 (each CI half-width under 0.01) | MISMATCH, measured |
| IDP starters, best ball, roster size | not stated | 9 per team (108), best ball, 58 spots | not measurable | UNAVAILABLE |

**Per-stat comparison** (`mismatches.idpScoring.perKey`), points per event, ratio = league card over Big 3:

| stat | Big 3 | league | league / Big 3 |
|---|---|---|---|
| solo tackle | 1.25 | 1.33 | 1.06 |
| assisted tackle | 0.75 | 0.80 | 1.07 |
| tackle for loss | 3 | 4.24 | **1.41** |
| sack | 5 | 2.92 | **0.58** |
| QB hit | 2 | 2.12 | 1.06 |
| pass defended | 4 | 5.30 | **1.33** |
| interception | 6 | 5.30 | 0.88 |
| forced fumble | 4 | 4.24 | 1.06 |
| fumble recovery | 3 | 3.19 | 1.06 |
| defensive TD | 6 | 6.36 | 1.06 |
| safety / blocked kick | 5 | 5.30 | 1.06 |
| sack yards and defensive return yards (per yard) | 0.1 | 0.111 | 1.11 |
| sack + QB hit + TFL (one sack play) | 10.0 | 9.28 | 0.93 |

The league card is close to Big 3 scaled up by about 6%, with four deliberate departures: sacks are worth much less,
and TFL, pass defended and (slightly) interceptions are priced differently. A full sack play (sack, QB hit and TFL)
pays almost the same under both cards (9.28 against 10.0), so the departures move **who** earns points (TFL and PD
plays without a sack) more than the total.

**How large is it?** Under the league card, a defender scores about 8% more than under Big 3 (market starters 7.7%).
The points-per-game orders under the two cards are nearly identical (Spearman 0.991 for market starters, 0.998 for all
defenders), and the shift favors DBs (+12.3%) over DL (+5.6%) by about 6.7 percentage points. Against the reception
mismatch (offense starters +4.7%), the card lifts defenders slightly more than offense: about 3% for the starter
pools, and about 1% for DL, 2.5% for LB and 7% for DB when each family's all-player ratio is set against the all-offense
ratio of 1.049 (ratios of two estimated ratios, intervals not propagated). Those are small next to the unmeasured items
in the table (IDP starter count, best ball, replacement depth) and next to the perturbations in §5. They say the
generic basis is **close** to this league's card for IDP and **off** for TE and reception. They do not say the level
is right.

### 6.3 Descriptive card alignment (in-sample)

For each market this compares two Spearman correlations on the same players: the market's IDP values against
league-card points per game, and against points per game under a reference card. The reference cards are
Investigation B's illustrative tackle-heavy card and the Big 3 card the calculator names. Intervals are paired
bootstraps on shared resamples; p-values are Holm-adjusted within each reference's 12-cell family. The boards
already know weeks 1–6, so this is descriptive.

`league − reference` Spearman (95% CI), IDP overall (n):

| market | vs Big 3 | vs tackle-heavy |
|---|---|---|
| IDPTC | −0.009 [−0.021, +0.002] (333) | +0.014 [−0.023, +0.048] |
| Draft Sharks IDP | −0.000 [−0.013, +0.013] (290) | −0.041 [−0.090, +0.005] |
| canonical | −0.004 [−0.015, +0.007] (352) | −0.015 [−0.050, +0.019] |

After Holm adjustment no cell differs from zero for Big 3 (smallest adjusted p 1.0) and none for the tackle-heavy card
(smallest adjusted p 0.28, Draft Sharks LB, raw difference −0.080 [−0.151, −0.013]). What that does and does not mean:

- **The test cannot separate Big 3 from the league card.** They rank the same players almost identically (Spearman
  0.99+), so a market built on either looks the same by order, and the confidence interval half-width is only about
  0.01. An IDPTC order consistent with its stated Big 3 basis is therefore also consistent with this league's card.
- **It has little power against the tackle-heavy card either** (half-width about 0.04 to 0.05). Absence of a
  significant difference is not evidence that a market's league sync works or fails.
- Draft Sharks' LB order correlates better with tackle-heavy points than with league points (raw), which fits a
  tackle-volume projection base, but it does not survive correction.
- The canonical board inherits the properties of both inputs.

### 6.4 Lineage context (recorded by the source registry, not re-measured here)

`config/sources/source_lineage.json` records, and this lane did not re-test:

- `idptc-idpshow-dependence`: the calculator's IDP order matches The IDP Show's IDP-only board (leave-pair-out
  residual +0.992 on n 243, raw Spearman 0.998 on n 347, refreshed 2026-10-01), with lead-lag at 3 of 5 publications.
  The page calls itself the official calculator of The IDP Show, and The IDP Show says Big 3 governs its evaluations.
  Ancestry stays **suspected**: no vendor statement says the calculator's IDP order is derived from The IDP Show's.
- `idptc-offense-ktc-value-identity`: at 2 of 4 broad offense batches its non-TE offense values equalled KTC's
  base superflex crowd values from days earlier. The batch voting since 2026-10-10 is close but not identical.
- Draft Sharks' basis is `model_projection`: a projection-driven value, not a market price.

The owner directive of 2026-10-19 says similarity is not lineage and agreement between providers is consensus, so this
report does not merge, cap or discount any vote on that basis. It records only that the **independence** of the IDP
bridge from The IDP Show, and of IDPTC's offense level from KTC, is unverified, which bears on whether the anchor can be
called independent evidence.

### 6.5 Conclusion (verdict NOT_JUSTIFIED)

1. The cardinal cross-position level comes from two external markets: the two anchors carry 0.90 of each top-108
   defender's value (§4).
2. Neither can be shown to represent this league. IDPTC states a basis that matches on teams and Superflex and
   differs on reception scoring (+44% per catch), TE premium and IDP scoring (a measured, mostly level-only
   difference), and says nothing about IDP starters, best ball or replacement. Draft Sharks' league sync cannot be
   verified.
3. The two agree on the median IDP level (removing either changes it by 0.2%) and disagree about who the elite
   defenders are. Agreement on level is consensus about price. It does not validate utility.
4. Both are stale or thin: IDPTC 14 days without a content change (weight 0.46), FantasyPros 51 days (0.24), IDP Show
   withheld at 66 days, every priced IDP row `low` confidence.
5. No non-market, league-specific evidence for the level exists in this lane. The one quantitative hint (§2:
   defenders start in best ball as often as offense at about half the price) is suggestive, not conclusive.

**What would change the verdict.** `JUSTIFIED` needs independent, league-scored evidence that supports the level out
of sample, for example replacement-adjusted marginal best-ball utility with a pre-registered backtest (Lanes B and D),
or a vendor-verifiable league-sync basis. A finding that the level is **wrong** needs the same evidence in the other
direction. Until then the correctness of the level stays UNRESOLVED.

## 7. Reproducing Investigation B's correlation claims

The outcome is 2026 weeks 1–6 league-card points per game for players with at least 3 games. Every priced player row
is joined by Sleeper id, and positions come from Sleeper's player directory. The estimator, bootstrap count (1,000)
and seed (20261020) are Investigation B's.

| board | sample type | offense ρ [95% CI] (n) | IDP ρ [95% CI] (n) | offense − IDP |
|---|---|---|---|---|
| B recorded, in-season (2026-10-20 board) | in-sample | 0.774 [0.727, 0.814] (344) | 0.450 [0.360, 0.541] (352) | 0.32 |
| **rebuild of B's 2026-10-20 archive** (today's code; main tree `21009b964` because B's `b8008c2a4` is unreachable) | in-sample | **0.774 [0.727, 0.814] (344)** | **0.450 [0.359, 0.541] (352)** | 0.324 [0.220, 0.426] |
| pinned 2026-10-25 board | in-sample, hindsight | 0.777 [0.732, 0.815] (344) | 0.447 [0.356, 0.535] (352) | 0.330 [0.231, 0.428] |
| B recorded, served pre-season (2026-08-25) | out-of-sample | 0.670 [0.602, 0.728] (296) | 0.403 [0.299, 0.495] (277) | 0.27 |
| **B's served 2026-08-25 board, re-scored** | out-of-sample | **0.670 [0.602, 0.728] (296)** | **0.403 [0.298, 0.495] (277)** | 0.267 [0.146, 0.380] |
| **point-in-time pre-season 2026-09-09** (today's code, that day's sources) | out-of-sample for the 2026 data; methodology is today's | 0.669 [0.601, 0.722] (324) | 0.442 [0.348, 0.521] (343) | 0.227 [0.120, 0.329] |
| same cohort, 2026-09-09 board (players priced on both) | out-of-sample | 0.666 [0.596, 0.726] (293) | 0.412 [0.303, 0.505] (277) | 0.255 [0.149, 0.374] |
| same cohort, B's 2026-08-25 board | out-of-sample | 0.666 [0.596, 0.726] (293) | 0.403 [0.288, 0.498] (277) | 0.263 [0.154, 0.383] |

**Results:**

- **Reproduced exactly.** B's in-season 0.774 / 0.450 and pre-season 0.670 / 0.403 match to the third decimal, with
  the same n. The only differences are ±0.001 in two CI bounds, from rounding.
- **One discrepancy, and it is a cohort effect.** The latest pre-season board before kickoff, rebuilt point-in-time,
  shows IDP ρ 0.442 rather than 0.403. On the same 277 players it gives 0.412, against 0.403 for B's board. The extra
  66 defenders are priced because today's code prices players past the rank cap (#1101). Range restriction therefore
  explains most of the gap, as B's own §6 already argued (its 2025 to 2026 points-per-game correlation is 0.682 over
  all IDPs but 0.413 over the priced ones).
- **The offense − IDP gap is real out-of-sample:** 0.23–0.27, with every 95% CI above 0.12.

Limits of this reproduction:

- Six weeks of production measure realized short-horizon output, not dynasty value. Correlation with points per game
  is not a test of dynasty pricing accuracy.
- The point-in-time board uses today's methodology, so methodology drift since September is folded in.
- The same-cohort intervals are deterministic only because the cohort is sorted before resampling; an earlier
  revision resampled in hash-seed order, which moved CI endpoints by up to 0.02 between identical runs.

## 8. Limitations and UNAVAILABLE items

- **IDPTC's IDP starter count, best-ball treatment, roster size and TE-premium magnitude are UNAVAILABLE.** The
  calculator's page does not state them. Its scoring basis ("Big 3") and header ("12-Team/.5 PPR") are stated, and
  are the vendor's claims about its own numbers.
- **The vendor pages were read once** (2026-10-26 UTC) and are receipted by sha256. A page can change later; the
  receipt shows whether it did. The Big 3 page is dated 2021, the calculator page 2026-10-10.
- **Draft Sharks' reproduction of this card's custom keys is UNVERIFIED** (the vendor scores client-side).
- **The offense-side mismatch is only partly measured.** Only the reception rules are isolated, against a 0.5 PPR
  counterfactual on the league's own stat lines. Other offense rules the header does not state are not compared.
- **The perturbations are single-factor and do not interact.** The elasticities are local (±20–25%). The attribution
  shares in §4 are approximations of a weighted mean-median.
- **The starter/bench table replays today's rosters over weeks 1–6.** It is realized, not expected, production.
- **The card-alignment test is in-sample, descriptive and low-powered** (§6.3).
- **Projections are UNAVAILABLE here.** `data/bdvm/projections/` is box-local, as Lane A recorded.
- **Served values cannot move from this work.** The change adds a research script, its tests, this document and an
  evidence JSON, and touches no file under `src/`, `config/`, `frontend/`, `data/` or `CSVs/`. No served path can
  reach it (a test asserts that nothing in `src/` references it).

## 9. Next tasks this lane hands off

1. **Lanes B and D:** test the §2 hint with replacement-adjusted marginal lineup utility, out-of-sample. That means
   asking whether the 108th defender's marginal best-ball contribution justifies a value of 0.55× the 132nd
   offense player. The measured scoring differences (§6.2) are small enough that they do not need to be the focus.
2. **Lane D:** the consensus compression of elite defenders (§3) is an estimator property on a thin, disagreeing
   panel. Any cross-position challenger should be evaluated against it explicitly.
3. **Owner decision, not research:** IDP evidence is thin. Every priced IDP row is low confidence, two of the three
   IDP voters are past their staleness budgets (IDPTC 14 days, FantasyPros 51 days), IDP Show has been stale for 66
   days, and DLF IDP is `testing`. Source restoration is the cheapest accuracy lever, and it changes source voting,
   which is owner-reserved.
4. **Owner question worth asking the vendors:** whether the IDP Trade Calculator's numbers are computed under Big 3, and
   at what starter counts. The answer would replace two UNAVAILABLE rows.
