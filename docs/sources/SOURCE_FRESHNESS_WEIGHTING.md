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
| root cause, re-checked 2026-09-24 | **Still upstream, confirmed by four independent checks.** (1) Substack's public archive: the two posts the fetcher reads are still IDP Show's newest *dynasty* boards (`combined-idp-offense-dynasty-rankings-fantasy-football`, `idp-dynasty-rankings`); every newer ranking post — "2026 Fantasy Football Rankings … 3.0" (08-29), "2026 Combined IDP Rankings 3.0", the weekly rankings — is a season/weekly board, which the dynasty lane must never ingest. (2) Datawrapper: chart `U8I37` serves v4, v5–v7 are 404 and the chart root redirects to v4 (last modified 2026-08-19). (3) Every 2-hourly production run is HEALTHY with the full 665 rows — not a paywall preview. (4) The CSV has not changed on `main` since acquisition (#1008). Four chart versions between 07-15 and 08-19 put the vendor's offseason cadence at ~9–12 days, consistent with the 168 h seed (bounds 72–336 h); no cadence change. The vendor moved to in-season redraft content; its dynasty board ages honestly and recovers automatically on republication. |

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

**Root cause, confirmed in production (2026-09-24, DLF-2026-09).** The first
DLF commit after the wrapper fix, `3793500e8` ("chore(dlf): automated refresh
2026-09-24T12:27:49Z", authored by the production fetch), wrote `dlfIdp` (172
rows), `dlfRookieIdp` (30) and `dlfRookieSf` (56) — every one with an **empty**
native Value column — and no `dlfSf`. So login, Cloudflare and the session all
work. DLF no longer serves its Value column on any board, and `dlfSf` alone
declared `require_native_value`, so its otherwise-valid ranking was refused
every run (native Value coverage 0 against a 240-row floor).

**Fix: rank health and native-Value health are separate questions.** The row
floor over parsed ranks decides whether a board is written (`_board_verdict`).
`dlfSf` now declares `expect_native_value`: when native Value coverage falls
below the floor, `fetch_dlf.py` prints `[DLF] WARNING dlfSf: native Value
coverage N/M — … writing rank with an empty value column` and writes
`name,rank,value` with the value **empty**. It never synthesizes Value from
Rank. Nothing in the dynasty blend reads DLF's native Value (DLF votes as a
rank signal), so an empty column changes no canonical number; it only means
the native Value is unavailable, and says so. Pinned by
`tests/adapters/test_dlf_scraper.py`.

The last valid DLF values keep their real age and decay by cadence until the
next successful run restores `dlfSf` to full authority.

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

### Family-capped voting (flag `source_family_cap`, default ON — owner directive 2026-09-24)

**Replaces "family head wins".** Before, only the registry-first member of a
correlation family voted and the rest were stamped `supersededBy`, so a fresh
Fantasy Navigator never voted beside KTC Crowd, nor Fitzmaurice beside the
FantasyPros consensus, nor a DLF rookie board beside the regular board.

Now every member votes with its own effective weight
(base × freshness × health × coverage), and the family's **total** is capped
at one provider's authority (`data_contract.cap_family_weights`, cap 1.0):

```
family_total = Σ effective_weight(member)
factor       = cap / family_total   if family_total > cap   else 1.0
member_vote  = effective_weight(member) × factor
```

* **Fresh members share one vote.** Two fully fresh DLF boards each carry
  0.5. A fresh Value (1.0) beside a stale Rank (0.25) carries 0.8 / 0.2.
* **A stale family is never scaled back up.** Members at 0.2 + 0.1 keep 0.3.
  The cap only ever lowers weight.
* **Missing is not zero.** An absent member contributes nothing, and its
  sibling keeps its own weight.
* **The families are the B10 correlation groups, unchanged.** KTC Crowd and
  KTC Trades are two families. Fantasy Navigator is inside the KTC Crowd
  family, so it can never become a hidden third full KTC vote. KTC Market is
  still benchmark-only and never an observation.

Four places change with it, so the cap cannot leak authority:

1. `retainedAuthority` caps its **denominator** the same way. Two fresh
   members of one family retain 1.0, not 0.5.
2. The **single-source haircut** counts families. A second member of the same
   family cannot lift a one-provider row out of the 30% haircut. With the cap
   off this is exactly the old rule, because selection leaves at most one
   value per family.
3. **B11 confidence** still sees ONE piece of evidence per family. It uses the
   member that carried the most weight on the row (ties go to registry order),
   and every field comes from that one real source, so no averaged number is
   invented.
4. The explainer and `sourceRankMeta` publish `familyAdjustment` and
   `preFamilyWeight`.

**Backtest** (`scripts/backtest_family_cap.py`). Each day 09-10…09-24 is
rebuilt from its own inputs, family-head selection vs cap, with freshness ON
in both:

* 352–525 rows change per day, median |Δ| 0.35–0.83%.
* By rank band on 09-24: 1–50 max 1.7% (max rank move 3); 51–150 max 3.5%
  (9); 151–300 max 4.9% (18); 301–500 max 5.9% (49); 501–800 max 10.5% (97).
* Newly voting: Fantasy Navigator (~365 rows from 09-21), Fitzmaurice (~280),
  Flock rookies (~45), DLF rookie IDP (~15).
* 6–14 rows per day move from the 3–4-voter blend rung to the trimmed 5+ rung,
  because family members count as observations.
* Mean retained authority 0.822 → 0.825. Degraded share unchanged.

**Known methodology effect, measured rather than hidden.** Fitzmaurice and
FantasyPros both vote rank → Hill, and they agree at every depth (median
ratio 0.95–1.03). Fantasy Navigator votes rank → Hill while KTC Crowd votes
its native value, and those two diverge by depth: median ratio 1.12 in the
top 50, 0.87–0.92 in ranks 151–500. That gap is the Hill curve against KTC's
own curve shape, not two opinions. Inside the cap, Navigator's roughly half
share of the KTC Crowd family carries part of it into the board (at most
1.7% in the top 50). The owner's decision keeps Navigator voting inside the
KTC family, so this is reported, not tuned. The Hill / live-source alignment
audit (sequenced next) is where the curve side is examined.

**Two corrections the cap required, found by the invariant tests:**

* **The cap follows the provider's base weight.** A fixed 1.0 cap silently
  undid a user's 2.0 weight override, which broke the end-to-end weight
  monotonicity test. The ceiling is now the largest base weight among the
  family's members. That is exactly 1.0 at default weights.
* **The n ≥ 5 trim removes weight MASS, not an observation.** The weight-blind
  trim was a step function. Under the cap's fractional weights, raising every
  source for Brock Bowers LOWERED his blend (9984.6 → 9983.7), because which
  observation sat at the 9999 ceiling decided whether 0.287 or 1.0 of weight
  was trimmed. `_trim_one_observation_mass` removes Σw / n from each end. With
  equal weights that is exactly the old trim, so the parity guarantee holds.
  Measured on today's board against production: trim alone changes 419 rows,
  median 0.14%, max 3.8%. The cap alone changes 522, median 0.85%. Together
  they change 535, median 0.72%, top-150 max 2.8%.

**Known and NOT fixed here:** the #1402 weighted median (midpoint-interpolated,
continuous in the WEIGHTS) is not monotone in the VALUES. When two
observations with different weights swap order, their cumulative positions
jump. On 20,000 random unequal-weight cases, production's blend lowers its
output when an input rises in 1,596 cases (worst −2.15%). The mass trim cuts
that to 237; the rest come from the median. It is a separate queued unit with
its own measurement.

**The DLF rookie boards** vote inside the DLF family cap until the rookie-board
audit decides whether they are distinct signals, mirrors, or seasonal.

**Rollback:** `RISKIT_FEATURE_SOURCE_FAMILY_CAP=0` and restart restores
family-head selection. The weights are still stamped either way.

## H. Current effective weights (board 2026-09-23T21:51Z, the PR's final head)

| source | subset | style | E | age | r | fresh | health | cov | base | **effective** | state |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ktcCrowdSfTep | players / picks | SNAPSHOT | 12 h | 3.1 h | 0.26 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| ktcTradesSfTep | players / picks | SNAPSHOT | 12 h | 3.1 h | 0.26 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| idpTradeCalc | players | BATCH | 127.8 h | 197 h | 1.54 | 0.878 | 1 | 1 | 1 | **0.878** | OVERDUE |
| idpTradeCalc | picks | UNKNOWN | 127.8 h | 645 h | 5.04 | 0.106 | 1 | 1 | 1 | **0.106** | SEVERELY_STALE |
| idpShowCombined | players | EXPLICIT | 168 h | 814 h | 4.85 | 0.120 | 1 | 1 | 1 | **0.120** | SEVERELY_STALE |
| dlfSf | players | BATCH | 52 h | 437 h | 8.41 | 0 | 1 | 1 | 1 | **quarantined** | — |
| dlfRookieSf | players | SNAPSHOT | 55 h | 411 h | 7.48 | 0.020 | 1 | 1 | 1 | **0.020** | SEVERELY_STALE |
| dlfIdp | players | SNAPSHOT | 168 h | 349 h | 2.08 | 0.678 | 1 | 1 | 1 | **0.678** | STALE |
| dlfRookieIdp | players | BATCH | 314.5 h | 349 h | 1.11 | 0.992 | 1 | 1 | 1 | **0.992** | ON_SCHEDULE |
| pfkDynasty | players | SNAPSHOT | 54.2 h | 113 h | 2.08 | 0.678 | 1 | 1 | 1 | **0.678** | STALE |
| flockFantasySfRookies | players | SNAPSHOT | 168.6 h | 441 h | 2.61 | 0.501 | 1 | 0.69 | 1 | **0.346** | STALE |
| all other voters | players | SNAPSHOT / BATCH / UNKNOWN | 12 h – 35 d | < E | ≤ 1 | 1.000 | 1 | 1 | 1 | **1.000** | ON_SCHEDULE |
| ktcCrowdTradesSfTep | players / picks | SNAPSHOT | 12 h | 3.1 h | — | 1.000 | — | — | — | **benchmark (no vote)** | ON_SCHEDULE |

Row states: NORMAL 610, DEGRADED 299, SEVERELY_DEGRADED 86. Most severely
degraded rows are 2026 picks priced only by stale IDPTC pick values.

The earlier draft of this table was taken at 18:41Z. Its numbers differ
only because the data aged three more hours.

## I. Real player examples (production `main` → this branch)

Examples come from the backtest's last day (2026-09-23 board, each variant
built from the same inputs). **Selection is mechanical**: the largest
September movers in KTC Market (since the key began, 09-09) and in IDPTC
(since 09-03), in both directions. They were not hand-picked.

**KTC Market risers** (market move → prod | KTC split only | split + freshness):

| player | KTC Market | prod | split | final |
|---|---|---|---|---|
| Dalton Kincaid | 4146 → 5158 | 4714 | 4757 | 4788 |
| Jalen Coker | 3146 → 4108 | 3080 | 3080 | 3220 |
| Bryce Young | 3849 → 4754 | 3730 | 3730 | 3830 |
| Parker Washington | 4382 → 5247 | 4030 | 4030 | 4082 |
| Isaiah Likely | 4272 → 4959 | 4241 | 4240 | 4321 |

**KTC Market fallers**:

| player | KTC Market | prod | split | final |
|---|---|---|---|---|
| Drake Maye | 8537 → 7668 | 9223 | 9132 | 9098 |
| Jayden Daniels | 7236 → 6505 | 8015 | 7963 | 7888 |
| Justin Herbert | 6854 → 6167 | 7157 | 7072 | 7018 |
| A.J. Brown | 5391 → 4788 | 4963 | 4982 | 4877 |
| Carnell Tate | 5551 → 4982 | 5446 | 5330 | 5403 |

**IDP** (IDPTC movers; IDP rows carry no KTC):

| player | IDPTC | prod | final | state |
|---|---|---|---|---|
| Jacob Rodriguez | 4173 → 5409 | 4389 | 4702 | DEGRADED |
| Greg Rousseau | 2141 → 3068 | 2499 | 2480 | DEGRADED |
| Jared Verse | 5399 → 3611 | 3447 | 3000 | DEGRADED |
| Jalon Walker | 2963 → 2141 | 2170 | 1999 | DEGRADED |
| Kevin Winston | 2940 → 2153 | 2694 | 2662 | DEGRADED |

**Where stale IDP evidence mattered most** (largest freshness moves on
09-23). All of them are IDP rows valued partly by a stale source (IDP Show
34 days old, DLF IDP 14 days old) that disagreed with the fresher boards:

| player | before | after | driver |
|---|---|---|---|
| Carson Schwesinger (LB) | 4910 (#65) | 5423 (#53) | fresh FP IDP / DS IDP outweigh the stale boards that ranked him lower |
| Myles Garrett (DL) | 4793 (#70) | 5218 (#61) | stale IDP Show rank 89 loses weight against fresh FP IDP / IDPTC |
| Laiatu Latu (DL) | 3306 (#155) | 2852 (#201) | the stale boards that ranked him higher lose weight |
| Christian Harris (LB) | 1495 (#583) | 1087 (off-cap) | IDPTC 0.88 vs IDP Show 0.12 |
| Jack Kiser (LB) | 1222 (#735) | 892 (off-cap) | IDPTC + IDP Show only; IDP Show now 12% of weight |

**Direction check, not a target.** Among the top-50 KTC Market risers,
freshness weighting moved the model *with* the market move for 33 players
and against it for 16. Among fallers it was 28 with and 19 against.

For IDPTC, the top-50 by absolute change is mostly sub-3% edits. Among
players whose IDPTC value moved ≥ 5%:

* **Fallers**: 6 with, 0 against.
* **Risers**: 1 with, 4 against. IDPTC's own weight is 0.88 today, so a
  rise it alone reports is diluted, as designed.

Nothing in this change targets KTC or any other single board.

## J. Model vs KTC Market (benchmark, not target)

| player | our model | KTC Market (raw / normalized) | difference (raw / normalized) | direction |
|---|---|---|---|---|
| Josh Allen | 9931 | 9589 / 9950 | +342 / −19 | retail_premium (normalized) |
| Ja'Marr Chase | 9513 | 9115 / 9458 | +398 / +55 | consensus_premium |
| Kaelon Black | 2590 | 3118 / 3236 | −528 / −646 | retail_premium |
| 2027 Early 1st | 6782 | 6412 / 6654 | +370 / +129 | consensus_premium |
| Jack Campbell (LB) | 5606 | — (no KTC coverage) | — | none |

`direction` is decided on the normalized difference, because KTC's raw
Crowd+Trades scale tops out below 9999.

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

| curve | rows changed | median \|Δ\| | p90 \|Δ\| | worst-day p90 | degraded share | mean retained authority |
|---|---|---|---|---|---|---|
| C1 exp after 1E (2^−(r−1)) | 868 | 1.50% | 8.78% | 15.5% | 34.0% | 0.775 |
| C2 logistic | 894 | 1.47% | 9.07% | 14.1% | 31.9% | 0.782 |
| C3 half-normal σ = 1.2 | 860 | 1.59% | 9.60% | 15.1% | 26.7% | 0.789 |
| **C4 eased exp (selected)** | **857** | **1.23%** | **7.26%** | **10.8%** | **17.6%** | **0.815** |

These numbers are measured with the **continuous** weighted median (below). A
first run under the old step median put C4 at 1.08% / 4.57%. That run was
flattered wherever the step snapped back to an unweighted answer, and elsewhere
it hid cliffs. The ranking of the four curves is the same under both.

Synthetic probes:

| probe | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| fast source (E = 12 h) dark for 24 h | 0.50 | 0.74 | 0.71 | 0.71 |
| fast source dark for 48 h | 0.13 | 0.05 | 0.04 | 0.21 |
| fast source dark for 96 h | 0.008 | 0 | 0 | quarantined |
| monthly source (E = 35 d) at 45 d | 0.82 | 0.93 | 0.97 | 0.96 |
| monthly source at 70 d | 0.50 | 0.74 | 0.71 | 0.71 |

**Why C4.** All four candidates hit the directive's target bands at r = 2
to 4. C4 is the most stable of them day to day: the lowest median, p90 and
worst-day movement (10.8% against 14–15.5%). It keeps the most authority
while still decaying a dark fast source to 0.21 at 4E, and it keeps a stale
source accountable longer before quarantine. C1 halves a source only one
hour past its normal interval. C2 and C3 collapse too steeply between 2E
and 4E.

**KTC split vs production**, per day: 522–581 rows changed, median |Δ| 0.74
– 0.97%, p90 2.2 – 3.3%. Offense and picks only. The baseline is current
`main` (`4e79d10ad`), so its Hill constants are the same as this branch's.

**Split + C4 vs production** (09-23):

* 940 rows changed.
* Median |Δ|: IDP 4.06%, offense 1.26%, picks 1.23%.
* The largest moves are IDP rows leaning on stale IDP Show / DLF IDP
  evidence.

### The weighted median is continuous in the weights

Merging `main` exposed a cliff that the freshness weights made reachable on
every board. The blend's weighted median was the textbook "first value whose
cumulative weight passes half", which is a **step function** of the weights.
Before this PR, only custom user weights reached it.

Kyle Hamilton's three-source IDP anchor was:

* IDPTC 3597 at weight 0.878;
* IDP Show 3554 at 0.120;
* Draft Sharks IDP 2269 at 1.0.

The median snapped to 2269 because 1.0 exceeded half of 1.998 by 0.001. That
dropped his value 20% (3315 → 2643). IDPTC at 0.881 would have snapped it
back to about 3554.

`_weighted_median_sorted` now works like this:

* each observation sits at the midpoint of its cumulative-weight interval;
* the median is the linear interpolation of the values at 0.5.

It is continuous in the weights and exactly the ordinary median under equal
weights. The equal-weight path, including flag-off and the default board
with no stale sources, still delegates to the unweighted blend before
reaching it, so those outputs are byte-identical.

Kyle Hamilton is now 3158 (−4.7% vs flag-off). Pinned by
`tests/api/test_weighted_blend.py`, which checks continuity across that exact
knife-edge and the equal-weight identity. The change also applies to custom
user weights, which now move values smoothly too.

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

## Post-deploy evidence

The weighting endpoints are auth-gated, so every deploy prints its own
evidence. `deploy/verify-deploy.sh` runs
`scripts/source_weighting_report.py --state-only` on the box. It builds no
contract and takes about 0.1 s. It assesses that box's own
`data/scrape_state` through the same freshness owner the blend uses, and
prints, per source and subset:

* last FETCH beside the DATA clock (data-as-of);
* E, age, r and freshness;
* health, coverage, base and effective weight;
* state.

It is **advisory**: a failure only warns
(`VERIFY_SOURCE_WEIGHTING_REPORT=0` disables it), so it can never fail or
skip a deploy.

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
| `tests/api/test_weighted_blend.py` | continuous weighted median (the Kyle Hamilton knife-edge) and the equal-weight identity |
| `tests/scripts/test_source_weighting_report_state_only.py` | the on-box report: reduced vs full weight, a re-fetch does not freshen, KTC Market is a benchmark, unmeasured ≠ zero, the deploy hook is advisory |

## Deferred / follow-ups (visible, not smuggled in)

* **DLF**: confirm the tripping board on the box (owner action above).
* **IDPTC picks**: verify the Sheet pick-sourcing path against the live site.
* The IDP-only "IDPTC vs IDP experts" edge (`idpMarketEdge`) is kept as an
  explicitly named alternate concept.
* KTC base weights of 1.0 each were the owner's decision. Revisit only with
  outcome evidence.
* Off-cap rows are valued but carry no per-source stamps, so the explainer
  reports `sourceBreakdownAvailable: false` for them.
