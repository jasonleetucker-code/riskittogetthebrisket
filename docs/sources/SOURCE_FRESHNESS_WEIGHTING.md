# Freshness-aware source weighting, KTC signal separation, IDP source health

**Owner directive 2026-09-23** ("DYNASTY VALUE SYSTEM OVERHAUL"), with the
owner's required revision of the same day (cadence-relative freshness, no
universal absolute floors, candidate curves compared before selection).
Recorded in `docs/EXECUTION_PLAN.md` §0 and `docs/OWNER_REQUESTED_TODO.md`.

Evidence for every number below:
`docs/sources/evidence/FRESHNESS_WEIGHTING_2026-09-23/` (source table, player
explanations, 14-day backtest). Board as of `2026-09-23T18:41:31Z`.

## 0. The architecture in one picture

```text
                 OUR MULTI-SOURCE MODEL                    KTC MARKET BENCHMARK
  KTC Crowd (ktcCrowdSfTep)          ─┐              KTC Crowd  ─┐
  KTC Trades (ktcTradesSfTep)        ─┤              KTC Trades ─┴→ KTC Market
  IDP Trade Calculator               ─┤                             (ktcCrowdTradesSfTep,
  IDP Show                           ─┤                              KTC's OWN published
  every other registered source      ─┘                              Crowd+Trades number)
            ↓
  effective = base × freshness × health × coverage     (per row, per source)
            ↓
  OUR MODEL VALUE  = rankDerivedValue  ────────── compared with ──────→ KTC Market
```

* **KTC Crowd and KTC Trades are two separate model inputs**: two registry
  entries, base weight **1.0 each** (owner answer), two B10 families
  (`ktcCrowd`, `ktcTrades`), each value-direct (`raw / site_max × 9999`),
  each with its own freshness, health and coverage.
* **KTC Market is the benchmark only.** It is never registered (import-time
  guard `_assert_non_voting_keys_unregistered`), never blended with a non-KTC
  input, and has one owner: `src/sources/ktc_market.py`. Every row carries a
  `ktcMarket` block; `marketGapDirection` / `marketGapValueRatio` compare
  `rankDerivedValue` against it. An IDP row has `ktcMarket.value = null` with
  a reason — never 0.
* **Fantasy Navigator** is KTC-derived. Measured on the live board, its mean
  absolute percentile deviation is 0.156 against KTC Crowd (base SF), 0.166
  against Crowd TE++ and 0.188 against Trades, so it joins the `ktcCrowd`
  family. It can never be a hidden third KTC vote.
* **One canonical model value.** Rankings, trade tools, the API and player
  pages all read `rankDerivedValue`, pinned by
  `tests/api/test_canonical_value_consumers.py`.

## A. Source inventory

| key | provider | signal | family | scope | model input | benchmark |
|---|---|---|---|---|---|---|
| ktcCrowdSfTep | KeepTradeCut Crowd SF TE++ | value | ktcCrowd | offense + picks | yes | component |
| ktcTradesSfTep | KeepTradeCut Trades SF TE++ | value | ktcTrades | offense + picks | yes | component |
| ktcCrowdTradesSfTep | KeepTradeCut published Crowd+Trades | value | — | offense + picks | **no** | **KTC Market** |
| idpTradeCalc | IDP Trade Calculator | value | idpTradeCalc | full roster + picks | yes | — |
| idpShowCombined | The IDP Show (Adamidp) Combined | rank | idpShow | IDP | yes | — |
| dlfSf / dlfRookieSf / dlfIdp / dlfRookieIdp | Dynasty League Football | rank | dlf | offense / IDP | yes | — |
| dynastyNerdsSfTep | Dynasty Nerds | rank | own | offense | yes | — |
| fantasyCalc | FantasyCalc | rank | own | offense | yes | — |
| otcffbSf | OTC Fantasy Football | rank | own | offense | yes | — |
| fantasyNavigatorSf | Fantasy Navigator (KTC-derived) | rank | **ktcCrowd** | offense | yes | — |
| pfkDynasty | Play for Keeps | rank | own | offense | yes | — |
| dynastyDaddySf | Dynasty Daddy | rank | own | offense | yes | — |
| fantasyProsSf / fantasyProsIdp / fantasyProsFitzmaurice | FantasyPros | rank | fantasyPros | offense / IDP | yes | — |
| flockFantasySf / flockFantasySfRookies | Flock Fantasy | rank | flockFantasy | offense | yes | — |
| yahooBoone | Yahoo / Justin Boone | rank | own | offense | yes | — |
| draftSharks / draftSharksIdp | Draft Sharks | rank | draftSharks | offense / IDP | yes | — |

`ktc` and `ktcSfTep` are historical market fallbacks for replaying old
payloads only. The declaration `_NON_VOTING_SOURCE_CSV_KEYS` enforces that
neither of them, nor the KTC Market, can be registered as a voter.

## B. KTC — how each enters the system

| signal | before (main `d9c6c7b1`) | after |
|---|---|---|
| KTC Crowd (`value`) | captured, non-voting diagnostic | **model input**, family `ktcCrowd`, weight 1.0 |
| KTC Trades (`vftValue`) | captured, non-voting diagnostic | **model input**, family `ktcTrades`, weight 1.0 |
| KTC Market (`blendValue`) | **the only KTC vote**, plus the market side of the gap averaged with KTC-derived Fantasy Navigator | **benchmark only**: `ktcMarket` block and market gap, KTC's own number alone |

Capture is unchanged. `src/sources/ktc_value_sources.py` was not edited
because it is claimed by #1391.

Consequences to know:

* KTC's share of an offensive row's blend roughly doubles. It was one of ~12
  families and is now two. Josh Allen's KTC share is 0.085 + 0.085.
* On pick rows, KTC now holds two of the three market votes against IDPTC.
* Rows priced **only** by KTC previously fell to the single-source haircut
  (30% of value). With two families present they no longer do. Examples:
  Malik Heath rose from 161 to 541 in the backtest, and Tylan Wallace from
  157 to 527. Both are off-cap rows. Two KTC families are two separate
  observations, so this is the rule working as written, not a defect. It is
  still the largest single-row effect of the split.

## C. IDP Trade Calculator

| | players | picks |
|---|---|---|
| last successful fetch | 2026-09-23T18:41Z | same fetch |
| last any meaningful change | 2026-09-23T08:04Z (≤ 2 rows) | 2026-08-28T01:13Z |
| last broad change (estimated data-as-of) | **2026-09-15T17:22Z** (184 rows) | **2026-08-28T01:13Z** |
| publication style | BATCH (large periodic batches plus small edits) | UNKNOWN (1 change event) |
| expected cadence | 127.8 h, learned from same-phase broad intervals | inherited from players (127.8 h) |
| current age | 193 h board level; row clock per row, e.g. Myles Garrett 165 h | 641 h |
| coverage / health | 1.00 / HEALTHY | 1.00 / HEALTHY |
| base → effective weight | 1.0 → **0.887** (OVERDUE) | 1.0 → **0.107** (SEVERELY_STALE) |
| root cause if stale | players: normal batch rhythm, slightly overdue | picks: the vendor has not changed pick values since 08-28. Sheet sourcing was not fully verified from here |

Players and picks are independent subsets, so a fresh player batch never
refreshes picks. Because the style is BATCH, a two-row edit refreshes only
those two rows (`rowChangedAt`). A broad batch refreshes the whole board.

## D. IDP Show

| | idpShowCombined |
|---|---|
| last successful fetch | 2026-09-23T18:32Z |
| last change / data-as-of | **2026-08-20T23:28Z**. The only content change was the acquisition itself |
| upstream timestamp | Datawrapper chart `lastModifiedAt 2026-08-19T17:46:59Z` (v5), now persisted as `idpShowCombined_upstream.json` |
| style | EXPLICIT_UPSTREAM_TIMESTAMP. Age uses `min(upstream, lastBroad)` |
| expected cadence | 168 h (seed; no interval history exists yet) |
| current age | 811 h (34 d), r = 4.83 |
| coverage / health | 1.00 / HEALTHY |
| base → effective weight | 1.0 → **0.122** (SEVERELY_STALE) |
| root cause | **Upstream.** The vendor has not republished. The public excerpt chart v5 matches our board on 247 of 249 rows, and our fetcher reads the latest chart version. There is nothing to fix on our side, so its authority decays until the vendor republishes and then recovers automatically. |

## E. Every other source

The full table, including the last-fetch column, is in
`evidence/.../source_weighting_report.txt`. Its shape:

| source | last fetch | data age | expected cadence | health | coverage | effective |
|---|---|---|---|---|---|---|
| ktcCrowdSfTep / ktcTradesSfTep | 09-23 18:41 | 4.7 h | 12 h | HEALTHY | 1.00 | 1.000 |
| fantasyCalc / dynastyDaddySf | 09-23 | 4.7 h | 12 h | HEALTHY | 1.00 | 1.000 |
| draftSharks / draftSharksIdp | 09-23 | 4.7 h | 19.5 / 14 h | HEALTHY | 1.00 | 1.000 |
| otcffbSf | 09-23 | 4.7 h | 24.6 h | HEALTHY | 1.00 | 1.000 |
| fantasyNavigatorSf | 09-23 | 25 h | 24 h | HEALTHY | 1.00 | 0.998 |
| fantasyProsSf / fantasyProsIdp | 09-23 | 25 h / 6 d | 48 h / 11.3 d | HEALTHY | 1.00 | 1.000 |
| flockFantasySf | 09-23 | 10.6 h | 48.7 h | HEALTHY | 1.00 | 1.000 |
| flockFantasySfRookies | 09-23 | 18.2 d | 7 d | HEALTHY | **0.69** | 0.348 |
| pfkDynasty | 09-23 | 4.6 d | 54 h | HEALTHY | 1.00 | 0.700 |
| dynastyNerdsSfTep | 09-23 | 12 d | 30 d | HEALTHY | 1.00 | 1.000 |
| fantasyProsFitzmaurice / yahooBoone | 09-23 | 22 d / 20 d | 30.7 d / 35 d | HEALTHY | 1.00 | 1.000 |
| **dlfSf** | **09-09 12:28** | 18.1 d | 52 h | HEALTHY (last valid) | 1.00 | **0 (quarantined)** |
| dlfRookieSf | 09-09 | 17 d | 56.5 h | HEALTHY | 1.00 | 0.024 |
| dlfIdp | 09-09 | 14.4 d | 7 d | HEALTHY | 1.00 | 0.685 |
| dlfRookieIdp | 09-09 | 14.4 d | 13.1 d | HEALTHY | 1.00 | 0.994 |

**DLF root cause.** DLF fetches have failed since 09-09. #1297 (09-09 13:40Z)
added a `require_native_value` guard. When any DLF board lacks the native
value column, `fetch_dlf.py` exits 2, and the production wrapper
`deploy/dlf_fetch_and_push.sh` then discarded **all four** boards.
`dlfSf.csv` still carries the pre-guard header. This could not be confirmed
from this environment (DLF returns Cloudflare 403 here).

Fixes made:

* The wrapper now pushes whatever boards were written, using
  `fetch_dlf.py --written-manifest`.
* The wrapper stamps only the boards actually written, and stamps
  `dlf_last_success` only on a full success.
* The wrapper still exits non-zero on a partial run, so the failure stays
  visible.

**Owner action:** `journalctl -u dynasty-dlf-fetch.service` on the box to
confirm which board trips the guard. Meanwhile the last valid DLF values
keep their real age and decay by cadence. DLF SF is quarantined, and the
IDP boards (longer cadence) retain partial authority.

## F. How production calculated values before this change

`_compute_unified_rankings` blended every registered source at weight 1.0.
The steps were value-direct voting for KTC Crowd+Trades and IDPTC; rank →
percentile → Hill for the rest; a Hampel filter; B10 family collapse; a
count-aware weighted mean-median; and a 30% single-source haircut. **Data
age had no effect on values.** The only freshness anywhere in the value
path was *fetch* age, used in the confidence gate (`maxAgeHours`). So a
source that was fetched on time but had not changed its content in 34 days
counted as fully fresh and kept its full vote.

## G. The freshness algorithm (implemented; flag `source_freshness_weighting`, default ON)

```text
effective(row, source) = base × freshness(age / E) × health × coverage

r = age / E
freshness(r) = 1                     if r ≤ 1
             = 2 ^ ( −(r − 1)² / r ) if r > 1          ("C4, eased exponential")
freshness < 0.02  ⇒ quarantined: the observation does not vote (dropped, never zero)
```

In plain words: a source keeps full authority for one normal publication
interval. After that its authority fades smoothly, with no cliff at r = 1,
and converges to one halving per further missed interval.

| r = age / E | 0.5 | 1 | 1.25 | 1.5 | 2 | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| freshness | 1.000 | 1.000 | 0.966 | 0.891 | 0.707 | 0.397 | 0.210 | 0.056 | quarantined (0.014) |

**Real-time translation** (age at which freshness reaches …):

| source | E | 0.9 | 0.7 | 0.4 | 0.2 | quarantine |
|---|---|---|---|---|---|---|
| KTC Crowd / Trades, FantasyCalc, Dynasty Daddy | 12 h | 18 h | 24 h | 36 h | 49 h | 3.8 d |
| DLF SF (learned) | 52 h | 3.2 d | 4.4 d | 6.5 d | 8.8 d | 16.3 d |
| IDPTC players (learned) | 5.3 d | 7.8 d | 10.8 d | 15.9 d | 21.7 d | 40.0 d |
| IDP Show (seed), DLF IDP | 7 d | 10.3 d | 14.1 d | 20.9 d | 28.5 d | 52.6 d |
| Fitzmaurice (learned) | 30.7 d | 45.2 d | 62.0 d | 91.7 d | 125 d | 231 d |
| Yahoo Boone | 35 d | 51.6 d | 70.7 d | 104.6 d | 143 d | 263 d |

The same 72 h is 0.06 for KTC and 1.00 for a weekly source. There is **no
universal absolute floor**.

### Three clocks (`src/sources/dataset_state.py`)

Fetch time is never data freshness:

| clock | moves when | used for |
|---|---|---|
| `lastFetchedAt` (`<key>_last_success`) | a fetch succeeded | infrastructure only; shown, never ages data |
| `lastAnyMeaningfulChangeAt` | ≥ 1 canonical (name → value/rank) changed | liveness, reported |
| `lastBroadDatasetChangeAt` | a change of ≥ max(5 rows, 2%) | the board-level freshness clock |

The fingerprint covers name plus value/rank columns only.

Clocks that do **not** move:

* An unchanged re-fetch.
* A markup-only change, a reordered board, a failed scrape, a CAPTCHA or
  challenge page, or a collapsed, duplicate-exploded or malformed board.

These change health only. The last valid content is kept.

### Publication style (derived from the last 20 change events, ≥ 5 required)

| style | rule | freshness clock |
|---|---|---|
| SNAPSHOT | ≥ 80% of events broad and median changed fraction ≥ 25% | `lastBroadDatasetChangeAt`, shared by every row |
| BATCH | otherwise | per row: max(`rowChangedAt[row]`, `lastBroad`) |
| INCREMENTAL | ≤ 20% of events broad | the same row clock. Any-change proves liveness but never refreshes untouched rows |
| UNKNOWN | < 5 events | BATCH clocks, flagged |
| EXPLICIT_UPSTREAM_TIMESTAMP | config-declared (IDP Show) | min(`upstreamPublishedAt`, `lastBroad`) |

### Expected cadence E

E is the **p75 of closed broad-change intervals**. The preference order is:

1. the same season phase (Sep–Jan in-season, else offseason), with ≥ 5
   intervals in the trailing 120 days;
2. any phase, with ≥ 5 intervals;
3. inherited from the players subset (picks);
4. the config seed.

E is clamped to per-source `[minHours, maxHours]` in
`config/sources/freshness_v1.json`. KTC's `minHours` is 12: its observed
p75 of about 6 h is our 2-hourly polling resolution, not KTC's publication
rhythm. The open gap is never in the history, and one closed outage is a
single sample in a p75 capped by `maxHours`, so **an outage cannot redefine
"normal"**. Recovery is automatic: the next genuine broad change resets the
clock.

### Health and coverage

* **Health** (data validity, not fetch age): HEALTHY 1.0, DEGRADED 0.5,
  FAILED 0.
* **Coverage** = min(1, rows / (0.8 × own rolling median)).
* **Row as-of**: `asOf` is the payload's `scrapeTimestamp`. A payload
  without one gets no weighting, which keeps the result deterministic.
* **Historical trees**: these rebuild the clocks from history at `asOf`,
  so no future change is ever visible.

### Degraded evidence stays visible

* **Per row**:
  * `sourceWeightState` (NORMAL / DEGRADED / SEVERELY_DEGRADED /
    INSUFFICIENT_DATA)
  * `retainedAuthority` = Σ effective / Σ base
  * `dominantSource` and `dominantSourceShare`
  * `freshnessExcludedSources`
  * `sourceRankMeta[k].freshness` / `freshnessAgeHours` /
    `dynamicWeightFactor`, stamped only when reduced
* **Board level**: the `sourceWeighting` block (sources × subsets, curve,
  formula, row-state census) and the `ktcMarket` summary.
* **Single-source haircut**: this counts freshness-excluded families, so
  crossing the quarantine line cannot drop a row off a cliff. A regression
  test pins this.
* **Confidence**: the B11 freshness axis now treats a source as fresh
  evidence only if it was fetched on time **and** its content freshness is
  ≥ `freshForConfidence` (0.5). Under the rollback flag it reverts to the
  fetch-only answer.

### Rollback

Set `RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING=0` and restart. Every
factor becomes 1.0 in valuation and confidence, while every diagnostic
keeps computing and reporting. The KTC split is not behind this flag.

## H. Current effective weights (2026-09-23T18:41Z)

| source | subset | style | E | age | r | fresh | health | cov | base | **effective** | state |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ktcCrowdSfTep | players / picks | SNAPSHOT | 12 h | 4.7 h | 0.39 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| ktcTradesSfTep | players / picks | SNAPSHOT | 12 h | 4.7 h | 0.39 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| idpTradeCalc | players | BATCH | 127.8 h | 193 h | 1.51 | 0.887 | 1 | 1 | 1 | **0.887** | OVERDUE |
| idpTradeCalc | picks | UNKNOWN | 127.8 h | 642 h | 5.02 | 0.107 | 1 | 1 | 1 | **0.107** | SEVERELY_STALE |
| idpShowCombined | players | EXPLICIT | 168 h | 811 h | 4.83 | 0.122 | 1 | 1 | 1 | **0.122** | SEVERELY_STALE |
| dlfSf | players | BATCH | 52 h | 434 h | 8.35 | 0 | 1 | 1 | 1 | **quarantined** | — |
| dlfRookieSf | players | SNAPSHOT | 56.5 h | 408 h | 7.23 | 0.024 | 1 | 1 | 1 | **0.024** | SEVERELY_STALE |
| dlfIdp | players | SNAPSHOT | 168 h | 346 h | 2.06 | 0.685 | 1 | 1 | 1 | **0.685** | STALE |
| dlfRookieIdp | players | BATCH | 314.5 h | 346 h | 1.10 | 0.994 | 1 | 1 | 1 | **0.994** | ON_SCHEDULE |
| pfkDynasty | players | SNAPSHOT | 54.2 h | 110 h | 2.02 | 0.700 | 1 | 1 | 1 | **0.700** | STALE |
| flockFantasySfRookies | players | SNAPSHOT | 168 h | 437 h | 2.60 | 0.504 | 1 | 0.69 | 1 | **0.348** | STALE |
| fantasyNavigatorSf | players | UNKNOWN | 24 h | 25 h | 1.05 | 0.998 | 1 | 1 | 1 | **0.998** | ON_SCHEDULE |
| all other voters | players | mostly SNAPSHOT | 12 h – 35 d | < E | ≤ 1 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| ktcCrowdTradesSfTep | players / picks | SNAPSHOT | 12 h | 4.7 h | — | 1.000 | — | — | — | **benchmark (no vote)** | ON_SCHEDULE |

Row states: NORMAL 685, DEGRADED 224, SEVERELY_DEGRADED 86. Sixty of the
severely degraded rows are 2026 picks priced only by stale IDPTC pick
values.

## I. Real player examples (production `main` → this branch)

Examples come from the backtest's last day (2026-09-23 board, each variant
built from the same inputs). **Selection is mechanical**: the largest
September movers in KTC Market (since the key began, 09-09) and in IDPTC
(since 09-03), in both directions. They were not hand-picked.

**KTC Market risers** (market move → prod | KTC split only | split + freshness):

| player | KTC Market | prod | split | final |
|---|---|---|---|---|
| Dalton Kincaid | 4146 → 5124 | 4605 | 4705 | 4756 |
| Jalen Coker | 3146 → 4090 | 3084 | 3084 | 3217 |
| Bryce Young | 3849 → 4730 | 3730 | 3730 | 3922 |
| Parker Washington | 4382 → 5222 | 4025 | 4025 | 4087 |
| Devaughn Vele | 1776 → 2443 | 1768 | 1848 | 1868 |

**KTC Market fallers**:

| player | KTC Market | prod | split | final |
|---|---|---|---|---|
| Drake Maye | 8537 → 7691 | 9254 | 9224 | 9213 |
| Jayden Daniels | 7236 → 6530 | 8044 | 7990 | 7862 |
| Justin Herbert | 6854 → 6193 | 7321 | 7254 | 7254 |
| A.J. Brown | 5391 → 4787 | 4987 | 4999 | 4898 |
| Carnell Tate | 5551 → 4995 | 5511 | 5369 | 5495 |

**IDP** (IDPTC movers; IDP rows carry no KTC):

| player | IDPTC | prod | final | state |
|---|---|---|---|---|
| Jacob Rodriguez | 4173 → 5409 | 3899 | 3976 | NORMAL |
| Greg Rousseau | 2141 → 3068 | 2502 | 2501 | DEGRADED |
| Jared Verse | 5399 → 4164 | 3636 | 3512 | DEGRADED |
| Jalon Walker | 2963 → 2141 | 2186 | 2087 | DEGRADED |
| Kevin Winston | 2940 → 2153 | 2508 | 2449 | DEGRADED |

**Where stale IDP evidence mattered most** (largest freshness moves on
09-23). All of them are deep IDP rows valued by a stale source (IDP Show 34
days old, DLF IDP 14 days old) that sat well above the fresher boards:

| player | before | after | driver |
|---|---|---|---|
| Christian Harris (LB) | 1495 (#589) | 1087 (off-cap) | IDPTC 0.887 vs IDP Show 0.122 |
| Jack Kiser (LB) | 1222 (#737) | 892 (off-cap) | IDPTC + IDP Show only; IDP Show now 12% of weight |
| Myles Garrett (DL) | 4793 | 5217 | stale IDP Show rank 89 loses weight against fresh FP IDP / IDPTC |

**Direction check, not a target.** Among the top-50 KTC Market risers,
freshness weighting moved the model *with* the market move for 33 players
and against it for 16. Among fallers it was 25 with and 22 against.

For IDPTC, the top-50 by absolute change is mostly sub-3% edits. Among
players whose IDPTC value moved ≥ 5%:

* **Fallers**: 5 with, 1 against.
* **Risers**: 1 with, 3 against. IDPTC's own weight is 0.887 today, so a
  rise it alone reports is diluted, as designed.

Nothing in this change targets KTC or any other single board.

## J. Model vs KTC Market (benchmark, not target)

| player | our model | KTC Market (raw / normalized) | difference | direction |
|---|---|---|---|---|
| Josh Allen | 9963 | 9588 / 9946 | +375 raw, +17 normalized | consensus_premium |
| Ja'Marr Chase | 9513 | 9123 / 9464 | +390 / +49 | consensus_premium |
| Kaelon Black | 2634 | 3118 / 3235 | −484 / −601 | retail_premium |
| 2027 Early 1st | 6773 | 6398 / 6637 | +375 / +136 | consensus_premium |
| Jack Campbell (LB) | 5182 | — (no KTC coverage) | — | none |

The explainer is available at `GET /api/players/{id}/value-explain` and
`scripts/source_weighting_report.py --player`. It lists each model source
with raw value, raw rank, normalized value, age, E, freshness, health,
base and effective weight, vote share, contribution and status. It then
shows KTC Crowd, KTC Trades, KTC Market and the model-vs-market
difference (absolute, percent and normalized).

## Backtest — curve choice and old vs new

Run with `scripts/backtest_source_freshness.py`. For each day
2026-09-10 … 09-23 it uses that day's own payload, its CSVs as committed,
and dataset state replayed from git history up to that moment. Values are
versus the `split` variant (KTC split, freshness off), averaged over 14
days:

| curve | rows changed | median \|Δ\| | p90 \|Δ\| | degraded share | mean retained authority |
|---|---|---|---|---|---|
| C1 exp after 1E (2^−(r−1)) | 869 | 1.39% | 7.96% | 33.7% | 0.776 |
| C2 logistic | 903 | 1.42% | 7.69% | 31.9% | 0.782 |
| C3 half-normal σ = 1.2 | 863 | 1.51% | 7.91% | 26.7% | 0.790 |
| **C4 eased exp (selected)** | **860** | **1.08%** | **4.57%** | **17.0%** | **0.815** |

Synthetic probes:

| probe | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| fast source (E = 12 h) dark for 24 h | 0.50 | 0.74 | 0.71 | 0.71 |
| fast source dark for 48 h | 0.13 | 0.05 | 0.04 | 0.21 |
| fast source dark for 96 h | 0.008 | 0 | 0 | quarantined |
| monthly source (E = 35 d) at 45 d | 0.82 | 0.93 | 0.97 | 0.96 |
| monthly source at 70 d | 0.50 | 0.74 | 0.71 | 0.71 |

**Why C4.** All four candidates hit the directive's target bands at r = 2
to 4. C4 is the most stable of them day to day: the lowest median and p90
movement, and none of the 14–17% p90 days that C1, C2 and C3 show on
09-11, 09-18 and 09-20–23. It keeps the most authority while still
decaying a dark fast source to 0.21 at 4E, and it keeps a stale source
accountable longer before quarantine. C1 halves a source only one hour
past its normal interval. C2 and C3 collapse too steeply between 2E and 4E.

**KTC split vs production**, per day: 522–581 rows changed, median |Δ| 0.74
– 0.94%, p90 2.2 – 3.2%. Offense and picks only.

**Split + C4 vs production** (09-23):

* 918 rows changed.
* IDP median |Δ| 2.19% and offense 0.94%.
* The largest moves are deep IDP rows leaning on stale IDP Show / DLF IDP
  evidence.
* On 09-11 the IDP median moved 9.75%. DLF IDP and IDP Show were both far
  past cadence while IDPTC had just batch-published.

## Storage contract

| file | written by |
|---|---|
| `data/scrape_state/<key>_dataset.json` | `scripts/record_source_datasets.py`. One writer per file: the GH 2-hourly refresh and the server's post-scrape pass record every board except `PROD_TIMER_OWNED_KEYS` (DLF ×4, IDP Show), which are recorded by `deploy/dlf_fetch_and_push.sh` (boards actually written) and `deploy/idpshow_fetch_and_push.sh`. A test pins the workflow's skip list to that constant |
| `data/scrape_state/<key>_upstream.json` | the fetcher, when the vendor states a publish time (IDP Show) |
| seeded history | `scripts/backfill_source_datasets.py --since 2026-04-01`. It replays the git history of `CSVs/site_raw/<key>.csv` deterministically. Git records a tracked CSV only when its content changes, so the history *is* the change archive |

Each state file holds, per subset: fingerprint, rowCount (plus history),
firstObservedAt, contentSince, both change clocks, `changeHistory` (bounded),
`rowHashes` / `rowChangedAt` (non-SNAPSHOT only), health, and upstream.
State is written only when something changed, so an unchanged re-fetch
leaves the file untouched.

## Alerts

`src/api/source_health_alerts.detect_content_alerts` covers:

* content far past cadence;
* a health failure;
* coverage collapse;
* a single remaining major voter.

These run in the existing sweep. `scripts/check_source_health.py` adds a
`contentFreshness` advisory (`::warning title=Stale source data::`).

## Relationship to `dynamic_source_weights`

The existing `dynamic_source_weights` flag gates an accuracy-based
**base**-weight fitter that is not wired to production. It answers "how good
is this source", while freshness answers "how current is this observation".
They compose multiplicatively into `base × freshness × …`, so this is not a
second owner.

## Tests

| file | covers |
|---|---|
| `tests/sources/test_ktc_signal_architecture.py` | KTC architecture, plus an AST guard that allows no second KTC Market literal |
| `tests/sources/test_dataset_state.py` | the three clocks, failures and CAPTCHAs, subsets, quiet persistence |
| `tests/sources/test_freshness.py` | the curve at the specified absolute ages for E = 12 h / 3 d / 7 d / 35 d, style, cadence learning, outage clamp, season phase, inheritance, as-of rebuild |
| `tests/api/test_freshness_weighted_blend.py` | exact weighted influence, recovery, quarantine without zero, no haircut cliff, missing ≠ zero, rollback, as-of determinism, confidence content freshness |
| `tests/api/test_canonical_value_consumers.py` | one canonical value, and every market display reads `ktcMarket` |

## Deferred / follow-ups (visible, not smuggled in)

* **DLF**: confirm the tripping board on the box (owner action above).
* **IDPTC picks**: verify the Sheet pick-sourcing path against the live site.
* The IDP-only "IDPTC vs IDP experts" edge (`idpMarketEdge`) is kept as an
  explicitly named alternate concept.
* KTC base weights of 1.0 each were the owner's decision. Revisit only with
  outcome evidence.
* Off-cap rows are valued but carry no per-source stamps, so the explainer
  reports `sourceBreakdownAvailable: false` for them.
