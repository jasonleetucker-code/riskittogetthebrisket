# Lane C-market: cross-position market baseline (IDP vs offense), 2026-10-25

**Status:** research only, shadow only. Nothing here changes a served value, rank, source weight, vote, Hill curve,
bridge, IDP ceiling, package model (`geom_q078_v1`), fairness band (`fairness_bands_v2`), flag default, route or
public output. Every alternative below is an offline contract built in a separate interpreter and then thrown
away. Nothing in `src/` imports the research script, and a test pins that.

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §6C, §9 (Lane C, Deliverable C
baseline). That directive authorizes research and shadow work only.

**Evidence:** `docs/valuation/idp_accuracy/evidence/c_market_baseline_2026-10-25.json`. It holds aggregates and
public NFL player names only: no manager or team names, no user, owner or roster ids, and no per-team roster
listings (`assert_aggregate_only`).

**Reproduce:**

```bash
python scripts/idp_accuracy/market_baseline.py            # ~3 min; Sleeper public API, cached under data/
python scripts/idp_accuracy/market_baseline.py --offline  # re-run from the cache
python -m pytest tests/scripts/test_idp_accuracy_market_baseline.py -q
```

**Verdict on the shared-market anchor: NOT_JUSTIFIED.** Nothing independently justifies it for this league. The
cross-position level comes from two external dynasty markets. One is a generic Superflex/TE-premium calculator
that states no IDP scoring basis. The other is a vendor board synced to this league, but its IDP order does not
track this league's scoring better than a tackle-heavy reference card does. The two markets roughly agree on the
level, and agreement is consensus about **market price**. It is not evidence of **league utility**. This verdict
does **not** say the level is wrong. Whether it is wrong is UNRESOLVED and belongs to Lanes B and D (replacement
and lineup utility, and independent backtesting).

---

## 0. Pinned inputs

| input | value |
|---|---|
| code | branch `claude/idp-c-market-baseline`. The evidence was regenerated at commit `f9e8d41d8`, which adds research files only |
| repository tree read by the contract build (CSVs, scrape stamps, weights) | `bdbc83a1f` (main, 2026-10-25 16:55 UTC), content sha256 `80e5f8da…` |
| served artifact | `exports/archive/dynasty_export_20261025_120337.zip`, sha256 `50fb251a…`, scrape 2026-10-25 12:03 UTC. Fields read: `rankDerivedValue`, `canonicalConsensusRank`, `canonicalSiteValues`, `confidenceBucket`, `quarantined` and `sourceRankMeta`. No `_composite` field is read |
| league | `dynasty_main`. Live card fingerprint `sf1:9e51824690d091f9`, which matches the archived contract's card. 12 teams, 58 roster spots, 21 starters (QB 1, RB 2, WR 3, TE 2, FLEX 2, SUPER_FLEX 1, K 1, DL 3, LB 3, DB 3), best ball, roster-format sha256 `4d0914e7…` |
| production | Sleeper weekly stats, 2026 regular season weeks 1–6, all games final. Week 7 was in progress (8 of 14 games final) and is **excluded**. Scored with the canonical `compute_weekly_points` |
| scorer check | 3,299 of 3,299 player-weeks match Sleeper's own awarded points within 0.01 (max difference 0.0044). This reproduces Investigation B's check exactly |
| pre-season (point-in-time) board | `dynasty_export_20260909_211525.zip`, the latest archive strictly before the week-1 kickoff (NE @ SEA, 2026-09-10 00:20 UTC, from nflverse `games.csv`). It was scraped 21:15 UTC. Its source tree is `bd7eda605`, that scrape's data-refresh commit (21:17 UTC), also before kickoff. Both orderings are pinned by tests |
| control | The perturbation worker's baseline build is byte-identical to the in-process build (`controlBaselineMatchesInProcess: true`) |

The archive and the tree come from different scrapes, and this was deliberate. The archive is the 12:03 UTC
scrape. Tree `bdbc83a1f` carries the CSVs of the 16:50 UTC refresh. I used the tree the lane named. Rebuilding
from the archive's own `site_raw/` files would move some numbers slightly. Every `site_raw` hash in the archive
is recorded in `inputs.archiveSiteRawSha256`.

## 1. Baseline: where defenders sit on the served board

**Top 100 overall (served rank):** QB 20, RB 21, WR 30, TE 12, LB 9, DL 3, DB 0, PICK 5.
**Top 200 overall:** QB 29, RB 37, WR 52, TE 28, LB 24, DL 13, DB 6, PICK 11.

**Highest-ranked defenders:** Carson Schwesinger (LB, rank 34, value 6,287), Jack Campbell (LB, 50, 5,443), Arvell Reese
(DL, 63, 5,071), Sonny Styles (LB, 66, 5,023) and Aidan Hutchinson (DL, 75, 4,642). The first defender appears at rank
34. Ranks 1–25 hold no defender.

| family | #1 (overall rank / value) | #10 | #25 |
|---|---|---|---|
| DL | Arvell Reese 63 / 5,071 | 182 / 2,950 | 264 / 2,301 |
| LB | Carson Schwesinger 34 / 6,287 | 110 / 3,909 | 215 / 2,620 |
| DB | Nick Emmanwori 106 / 3,989 | 299 / 2,154 | 382 / 1,835 |

The full top 25 per family is in `baseline.top25ByPosition`.

**Rank bands** (share of players that are IDP, in `baseline.rankBands`):

| band | 1-25 | 26-50 | 51-100 | 101-150 | 151-200 | 201-300 | 301-400 | 401-500 | 501-800 |
|---|---|---|---|---|---|---|---|---|---|
| IDP share | 0.00 | 0.08 | 0.22 | 0.33 | 0.33 | 0.38 | 0.52 | 0.47 | 0.60 |

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
players have a median of 4,734 (p10 3,224, p90 8,035).

**Coverage and confidence** (`baseline.coverageByPosition`). The evidence behind IDP values is thin, and that is a
fact about the board, not a judgment:

- Every one of the **397 priced IDP rows** has `confidenceBucket = low`. That includes all 36 rows in each
  family's starter-depth pool (top 36).
- Offense starter pools are mostly `high`: QB 19 of 24, RB 21 of 24, WR 22 of 24, TE 17 of 24.
- The median IDP row has **3 voting sources** (range 1–3). The median offense row has 12–14.
- 51 IDP rows rest on a single voter (DL 20, LB 13, DB 18).

**Evidence census** (`baseline.evidenceCensus`):

- Of the IDP-capable markets, three vote:
  - `idpTradeCalc`: content last changed 14 days ago, freshness 46%.
  - `draftSharksIdp`: 1 day, 62%.
  - `fantasyProsIdp`: 51 days, 24%.
- Four do not vote:
  - `idpShowCombined`: stale for 66 days, freshness 0. It is excluded on 301 IDP rows.
  - `dlfIdp`: status `testing`.
  - `signalsIdp{Dl,Lb,Db}`: `data_issue`.
- Weight states: 359 of 397 IDP rows are `SEVERELY_DEGRADED` and the other 38 are `DEGRADED`.
- 9 IDP rows are quarantined. 32 IDP rows are unpriced; they stay missing, never 0.

## 2. Starters vs bench by price band (live rosters, weekly best ball)

Method:

- The rosters are the 12 live `dynasty_main` rosters (696 players).
- For each team and each week (1–6), the lineup is the exact optimum (`solve_optimal_assignment`) under that week's
  realized league-scored points.
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

## 4. How cross-position level enters consensus (code trace)

Each step below is traced to its live code path and checked against `sourceRankMeta` on the pinned board
(`bridgeTrace.votePoolCensus`).

1. **Every IDP vote is priced in the shared-market pool on the GLOBAL Hill master** (`c` 0.112, `s` 0.725). No IDP
   vote reaches the IDP master on this board. The pool is chosen by `src/canonical/rank_coordinates.py`:
   "a translation moves a rank into the pool of the ladder it was translated through". The four IDP voters reach
   that pool by different routes:
   - `idpTradeCalc` (377 rows) is **value-signal**: raw / site max × 9,999 (`value_direct`). Its offense and IDP
     values sit on one native 0–9,999 scale.
   - `draftSharksIdp` (321 rows) is **rank-signal**. `ds_combined_cross_market` merges the vendor's offense and IDP
     halves (one league-synced session) into one combined `3D Value +` order.
   - `idpShowCombined` (301 rows) is **rank-signal**, using the vendor's own combined rank. It is withheld on this
     board because it is stale.
   - `fantasyProsIdp` (271 rows) is **rank-signal and IDP-only**. It is crosswalked through the shared-market ladder
     (`needs_shared_market_translation`, `sharedMarketTranslated: true`).
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
4. **Which market sets the level** (`topIdpLevelAttribution`). Each vote's influence is attributed to the market
   its cross-position level came from, and a translated vote is attributed to the ladder seed. Over the top 108
   defenders this gives **Draft Sharks 0.51, IDPTC 0.49**. This is an influence share, not an exact derivative: the
   blend is a weighted mean-median.

**Answer to "where does a single external market decide cross-position level?"** On this board, no single market
decides it. Two cardinal bridges decide it about equally: IDPTC (a generic public calculator) and Draft Sharks (a
league-synced vendor board). IDPTC alone does fix the ladder that sets the level of IDP-only expert boards.

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
| IDPTC IDP values ×0.80 / ×1.25 | **0.931 / 1.085** | 40 / 29 | 9 / 16 | 42 / 47 |
| Draft Sharks IDP `3D Value +` ×0.80 / ×1.25 | **0.972 / 1.053** | 39 / 30 | 8 / 16 | 40 / 47 |

How to read it:

- **IDP placement responds to each bridge's IDP level, at less than full strength.**
  - Moving IDPTC's IDP values by ±20–25% moves the median defender by −6.9% / +8.5%, an elasticity of about 0.32–0.37.
  - Moving Draft Sharks' IDP values by the same amount moves it by −2.8% / +5.3%. That number counts the change in
    its combined ORDER, not a value, which is why it is smaller and asymmetric.
  - In both cases the top-100 IDP count swings between 8 and 16, and the top defender between rank 29 and 40.
- **Removing either bridge entirely leaves the median IDP level unchanged** (±0.2%). The two markets agree on the
  level, so neither one alone carries it. They disagree on identity, though, so removing one reshuffles which
  defenders are elite: without Draft Sharks the top-200 IDP count rises from 43 to 54.
- **The ladder seed matters little today** (±1.2%), because the only IDP-only voter (FantasyPros) sits in the 10% subgroup.
- The perturbation sizes were chosen for scale, and they do not estimate how wrong either market is. **No variant
  is a candidate methodology**, and none should be read as a recommended level.

## 6. Does the external shared-market anchor represent this league?

Stated assumptions compared with the verified card (`leagueFormatAlignment`):

| assumption | IDP Trade Calculator | Draft Sharks | `dynasty_main` (verified) |
|---|---|---|---|
| Superflex | ON (the scraper sets the site toggle) | TE-premium Superflex page | SUPER_FLEX 1: match |
| TE premium | ON (the scraper sets the site toggle) | TE-premium page | `bonus_rec_te` 0.0, `bonus_fd_te` 1.0, tiered reception (`rec` 0.1, `rec_0_4` 0.25 … `rec_40p` 2.0), 2 TE starters: **no conventional TE premium**. The canonical board's constant TE++ target basis shares this assumption (CLAUDE.md step 5a), so it is board-wide, not specific to IDPTC |
| IDP scoring | **UNAVAILABLE**: the ingested payload (name, value, position, team) states none | league-synced, scored client-side by the vendor; whether this card's custom keys are reproduced is **UNVERIFIED** | solo 1.33, assist 0.80, TFL 4.24, sack 2.92, QB hit 2.12, PD 5.30, INT 5.30, FF 4.24 |
| teams / roster / IDP starters | **UNAVAILABLE** | league-synced (presumably 12 teams; not observable in the CSV) | 12 teams, 58 spots, 9 IDP starters per team (108 league-wide, 45% of non-kicker starters) |

**Card alignment.** This measurement is descriptive and in-sample: these boards already know weeks 1–6. For each
market it compares two correlations:

- Spearman of the market's IDP values against 2026 weeks 1–6 **league-card** points per game;
- Spearman against points per game under Investigation B's **tackle-heavy reference card** (an illustrative card,
  not any provider's).

Both use the same players. The 95% CI comes from a paired bootstrap, and p-values are Holm-adjusted over the
12-cell family.

| market | IDP overall: league − reference [95% CI] (n) | DL | LB | DB |
|---|---|---|---|---|
| IDPTC | +0.014 [−0.023, +0.048] (333) | +0.002 | −0.006 | −0.045 |
| Draft Sharks IDP | −0.041 [−0.090, +0.005] (290) | −0.037 | −0.080 [−0.151, −0.013] | −0.039 |
| canonical | −0.015 [−0.050, +0.019] (352) | +0.001 | −0.023 | −0.059 |

After Holm adjustment, none of the 12 cells differs from zero; the smallest adjusted p-value is 0.28 (Draft Sharks
LB). So:

- **IDPTC's IDP order tracks league-card production and tackle-heavy production equally well.** There is no sign that
  it reflects this league's TFL- and PD-heavy card, which is what a generic calculator would be expected to show.
- **Draft Sharks' league sync is not visible in its IDP order either.** If anything it leans toward the
  tackle-heavy card, though not significantly. One plausible reason, unverified: its `3D Value +` is a multi-year
  value-over-replacement projection, so it should not track six weeks of production.
- The canonical board inherits both of these properties.

Placement in context: IDP is 26.5% of IDPTC's top 200 players, 23.5% of the canonical top 200, and 45% of this
league's non-kicker starting slots. A slot share is not a value share, because replacement depth differs by
position. It is shown only to give the level a frame of reference.

**Conclusion (verdict NOT_JUSTIFIED).** The cross-position anchor is a market-price anchor built from two external
dynasty markets:

- IDPTC: generic, TE premium switched on against this card, IDP scoring basis unstated, and 14 days without a
  content change;
- Draft Sharks: league-synced in name, with no measurable league-card signature in its IDP order.

Their agreement on level (§5) is consensus about market price, and the repository's own rule is that it is not
duplication. It still validates nothing about league utility. No non-market, league-specific evidence that would
justify this level exists in this lane. The single quantitative hint is suggestive but not conclusive:
defenders start in best ball about as often as offense players at half the price (§2). Turning that hint into a
claim needs replacement-adjusted, out-of-sample evidence, which belongs to Lanes B and D.

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
| same cohort: 2026-09-09 vs 2026-08-25 (players priced on both) | out-of-sample | 0.666 / 0.666 (293) | **0.412 / 0.403** (277) | 0.255 / 0.263 |

**Results:**

- **Reproduced exactly.** B's in-season 0.774 / 0.450 and pre-season 0.670 / 0.403 match to the third decimal, with
  the same n. The only differences are ±0.001 in two CI bounds, from rounding.
- **One discrepancy, and it is a cohort effect.** The latest pre-season board before kickoff, rebuilt point-in-time,
  shows IDP ρ 0.442 rather than 0.403. On the same 277 players it gives 0.412, against 0.403 for B's board. The extra
  66 defenders are priced because today's code prices players past the rank cap (#1101). Range restriction therefore
  explains most of the gap, as B's own §6 already argued (0.682 over all IDPs vs 0.413 over priced IDPs).
- **The offense − IDP gap is real out-of-sample:** 0.23–0.27, with every 95% CI above 0.12.

Limits of this reproduction:

- Six weeks of production measure realized short-horizon output, not dynasty value. Correlation with points per game
  is not a test of dynasty pricing accuracy.
- The point-in-time board uses today's methodology, so methodology drift since September is folded in.

## 8. Limitations and UNAVAILABLE items

- **IDPTC's IDP scoring basis, league size and IDP starter count are UNAVAILABLE.** The ingested payload does not
  state them. No other site was fetched, because the lane authorizes only Sleeper and nflverse.
- **Draft Sharks' reproduction of this card's custom keys is UNVERIFIED** (the vendor scores client-side).
- **Lane A's scoring manifest was not available on any branch when this ran,** so the card and its fingerprint were
  fetched here. Their fingerprint equals the archived contract's.
- **The perturbations are single-factor and do not interact.** The elasticities are local (±20–25%). The attribution
  shares in §4 are approximations of a weighted mean-median.
- **The starter/bench table replays today's rosters over weeks 1–6.** It is realized, not expected, production.
- **The card-alignment test is in-sample and descriptive.** The tackle-heavy card is illustrative.
- **Windows L1 caveat.** `tests/scripts` has pre-existing failures on this Windows host:
  - `test_probe_signals_native` (`os.getuid`);
  - five `verify_signals_onbox*` path-separator or file-mode assertions.

  None of them touch these files. Linux CI is authoritative.
- **Served values cannot move from this work.** The change adds a research script, its tests, this document and an
  evidence JSON, and touches no file under `src/`, `config/`, `frontend/`, `data/` or `CSVs/`. No served path can
  reach it (a test asserts that nothing in `src/` references it). `board_diff --expect-no-value-change` would compare
  two builds of byte-identical code and inputs. The in-process build is pinned equal to an independent worker build.

## 9. Next tasks this lane hands off

1. **Lanes B and D:** test the §2 hint with replacement-adjusted marginal lineup utility, out-of-sample. That means
   asking whether the 108th defender's marginal best-ball contribution justifies a value of 0.55× the 132nd
   offense player.
2. **Lane D:** the consensus compression of elite defenders (§3) is an estimator property on a three-voter panel.
   Any cross-position challenger should be evaluated against it explicitly.
3. **Owner decision, not research:** IDP evidence is thin. Every priced IDP row is low confidence, two of the three
   IDP voters are past their staleness budgets (IDPTC 14 days, FantasyPros 51 days), IDP Show has been stale for 66
   days, and DLF IDP is `testing`. Source restoration is the cheapest accuracy lever, and it changes source voting,
   which is owner-reserved.
