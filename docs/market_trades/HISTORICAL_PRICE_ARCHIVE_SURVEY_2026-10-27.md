# Historical dynasty price archive survey, 2024 to mid-2026 (IDPM-3, 2026-10-27)

**Status: survey complete. Nothing was ingested.** No dataset was downloaded into the repo or `data/`. No
code, config, ledger, value, vote or flag changed. Every verdict below is a recommendation for the owner. None of
it authorizes ingestion.

Authority: owner directive IDPM-3 (`docs/OWNER_REQUESTED_TODO.md` on `main`, row IDPM-3).
The owner's answer was: "survey licensed or public historical archives of IDPTC, KTC and similar values, terms
honored, no paid data, nothing ingested until the owner approves a specific source". The work claim is in
`docs/WORK_CLAIMS.md` (IDPM-2 / IDPM-3). That claim row lists branch `claude/idp-market-census`; this survey is on
`claude/price-archive-survey`. That is intended: the one claim covers both deliverables.

Agent-OS-Receipt: 47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6

## 1. Summary

**The most important finding is in this repo, not on the web.** `HISTORY_FLOOR = 2026-07-14` was set because
`exports/archive/` starts on that day. But **git history already holds dated vendor snapshots back to 2026-03-09**,
which is about four months earlier. They are in `exports/latest/site_raw/*.csv` (from 2026-03-09) and
`CSVs/site_raw/*.csv` (from 2026-04-16). Since 2026-04-16 the two paths have been written in parallel, often in the
same commit, and the old path still updates. They are also in 112 dated `exports/latest/dynasty_data_YYYY-MM-DD.json`
files from 2026-03-25 to 2026-07-14: 111 before the floor, and one (2026-07-14) on it.

- **What this contradicts.** `docs/history/C1_U4_TEMPORAL_LEDGER.md` §6 calls the floor "permanent", and says
  "a pre-boundary row could only be fabricated". For 2026-03-09 to 2026-07-13 that is not true.
- **Scale.** KTC has 114 distinct content-change days before the floor. IDPTC has 19, including IDP players and
  36 pick rows from 2026-04-09.
- **Point-in-time quality.** These are real point-in-time observations: our own scrapes, committed at the time.
- **Effect on trades.** This is the one candidate that could give at-the-time prices to own-league trades from
  March to July 2026 without touching any third party again.

**Nothing found covers 2024, 2025 or January to early March 2026 for IDPTC.**
- IDPTC publishes no history feature.
- Its values load client-side from a Google Apps Script endpoint, so Wayback snapshots of the page carry no values.
- It was archived on only nine days in 2024 to 2026.
- **There is no free, terms-clean, point-in-time source of IDP trade values for that period.**

**For KTC and other offense or pick markets, daily history for 2024 to 2026 exists, but every copy is blocked by
terms.** Each of the following carries daily per-asset history:
- KTC's own player pages;
- Dynasty Daddy's undocumented per-asset endpoint, which relays KTC and other markets and covers picks;
- FantasyCalc's historical endpoint;
- Wayback snapshots of KTC's server-rendered rankings page, with 4 to 19 archived days a month.

Each one is blocked by the publisher's terms:
- KTC forbids "any form of automated data collection".
- FantasyCalc permits only `GET /values/current` programmatically "without separate written permission".
- Dynasty Daddy forbids "automated data scraping".
- The Internet Archive grants access "for scholarship and research purposes only".

None of these is usable without written permission.

**The only open public historical dataset found** is DynastyProcess `dynastyprocess/data`. It is GPL-3.0 licensed;
the upstream FantasyPros terms on republished ECR were not reviewed (UNKNOWN), so it is not shown to be terms-clean.
- It holds weekly offense and pick values plus weekly FantasyPros dynasty ECR ranks, including IDP, through 2024
  to 2026.
- Those are FantasyPros-expert-derived ranks and values, **not trade-market prices**.
- They share lineage with the `fantasyProsSf` / `fantasyProsIdp` sources the board already votes.
- They are PARTIAL at best.

## 2. Verdict table

| # | Candidate | Type | Covers 2024 – 2026-03? | Covers 2026-03 – 07-13? | IDP | Picks | Point-in-time | Terms position | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| R1 | Repo git history of vendor CSVs and dated JSON exports | repo history | no (repo starts 2026-03-09) | **yes** (KTC 114 d, IDPTC 19 d, FC 80 d, DD 89 d, DraftSharks IDP 79 d, ...) | **yes** (IDPTC, DLF IDP, DraftSharks IDP, IDP Show) | **yes** (KTC; IDPTC from 04-09) | **yes** | already collected under the same posture as live production (see §4) | **USABLE_PENDING_APPROVAL** |
| V1 | KTC player-page value history | vendor | yes (daily from 2020) | yes | no | not found | probably; needs validation (§3.2) | ToS forbids automated collection and reuse; robots disallows `/dynasty-rankings/histories` | **NOT_USABLE** without a KTC licence |
| V2 | KTC rankings page in the Wayback Machine | web archive | yes, sparse (4–19 days/month) | yes, sparse | no | yes (36 RDP rows) | yes | KTC ToS plus IA "scholarship and research purposes only" | **NOT_USABLE** for production; PARTIAL for private validation only, if the owner allows it (D6) |
| V3 | Dynasty Daddy per-asset history `/api/v1/player/{name_id}` | vendor (aggregator) | yes (picks from 2024-08-31, players from 2021) | yes | no | **yes** | probably | ToS forbids "automated data scraping"; the endpoint is undocumented (only `/values/dynasty` and `/values/redraft` are documented); the KTC columns relay KTC data | **NOT_USABLE** without written permission |
| V4 | FantasyCalc `/trades/historical/{id}` | vendor | **no**: the probe returned 2026-01-01 onward only | partly | no | unknown | the history ignores `numTeams` / `ppr`, so it is not our league's value | ToS: only `/values/current` without written permission; no "material substitute" for substantial portions of its content (for example its trade calculator) | **NOT_USABLE** without written permission |
| V5 | IDP Trade Calculator | vendor | no | no (outside repo history) | n/a | n/a | n/a | generic ToS, no data clause; robots allows all | **NOT_USABLE**: no history exists to retrieve |
| V6 | IDPTC in the Wayback Machine | web archive | 9 archived days in total, 2024-12 to 2026-02 | no | no values | no values | n/a | values are client-side, absent from snapshots | **NOT_USABLE** |
| V7 | DLF, DraftSharks, The IDP Show archives | vendor | behind paid subscription | (repo history: yes) | yes | DLF values only | n/a | paid | **NOT_USABLE** (paid); their pre-floor history is reachable only through R1 |
| O1 | DynastyProcess `values-players.csv` / `values-picks.csv` git history | open dataset | yes, weekly (52 / 50 / 36 commits in 2024 / 2025 / 2026) | yes, weekly | **no** | **yes** | yes (`scrape_date`) | GPL-3.0 licensed; upstream FantasyPros terms on republished ECR not reviewed (UNKNOWN) | **PARTIAL**: a different quantity (ECR-derived value), offense and picks only |
| O2 | DynastyProcess `db_fpecr` (FantasyPros dynasty ECR, includes `dynasty-idp/dl/lb/db`) | open dataset | yes, weekly | yes | **yes (ranks)** | no | yes (`scrape_date`) | as O1: GPL-3.0 licensed; upstream FantasyPros terms on republished ECR not reviewed (UNKNOWN) | **PARTIAL**: ranks, not prices; same lineage as `fantasyPros*` sources |
| O3 | DynastyProcess `db_playerids.csv` | open dataset | n/a | n/a | yes | n/a | n/a | GPL-3.0 | **USABLE_PENDING_APPROVAL** as an identity bridge only (has `ktc_id`, `fantasypros_id`, `sleeper_id`) |
| O4 | nflverse | open dataset | — | — | — | — | — | — | **NOT_USABLE**: no trade values; its ff tables are DynastyProcess mirrors (O2/O3) |
| O5 | Kaggle and GitHub "KTC archive" repos | open dataset | none found | — | — | — | — | GitHub hits were single-snapshot scrapers with no licence (`hassanjavedxoxo/keeptradecut-player-data`, `ees4/KeepTradeCut-Scraper`, `seh363/...`); Kaggle search was not verifiable without login | **NOT_USABLE / UNKNOWN**: no archive found |

## 3. Candidate detail

### 3.1 R1: this repo's own git history (the headline)

**Paths.** From 2026-03-09 the vendor CSVs are at `exports/latest/site_raw/<source>.csv`. From 2026-04-16 they are
also at `CSVs/site_raw/<source>.csv`. This is not a rename: the two paths have been written in parallel since
2026-04-16, often in the same commit, and the old path is still updated today. Query both paths to see the whole
series. The day counts below use the union of both paths, so the parallel writing does not change them.
Separately, `exports/latest/dynasty_data_YYYY-MM-DD.json` exists for **112 dates from 2026-03-25 to 2026-07-14**:
111 before the floor, and 2026-07-14 on it.
- Each file carries per-player, per-source values and the joined `_sleeperId`.
- Each carries the `sleeper` block, including `trades`.
- Top-level keys are `version`, `date`, `scrapeTimestamp`, `sites`, `pickAnchors`, `players`, `sleeper`, and others.

**Coverage before the floor.** Counts are distinct calendar days on which the file's content changed: a path
appears in `git log` only when its content changed. Commands: `git log --format=%ad --date=short -- <old path>
<new path>`, filtered to dates before 2026-07-14, with unique days counted.

| source CSV | content-change days before 2026-07-14 | first | last | notes |
|---|---|---|---|---|
| `ktc` (KTC SF, base) | **114** | 2026-03-09 | 2026-07-13 | includes pick rows (`2026 Early 1st`, ...) from the first snapshot |
| `ktcSfTep` (KTC SF TE++) | 78 | 2026-04-27 | 2026-07-13 | |
| `idpTradeCalc` | **19** | 2026-03-09 | 2026-07-12 | 385 rows and no picks in March; 813 to 901 rows **with 36 pick rows from 2026-04-09** |
| `fantasyCalc` | 80 | 2026-03-09 | 2026-07-13 | |
| `dynastyDaddySf` | 89 | 2026-04-16 | 2026-07-13 | relays other markets (lineage) |
| `dlfSf` / `dlfIdp` | 21 / 18 | 2026-03-09 | 2026-06 | |
| `draftSharksIdp` / `draftSharksSf` | 79 / 66 | 2026-03-22 / 04-19 | 2026-07 | |
| `flockFantasySf` | 88 | 2026-04-17 | | |
| `idpShow` | 5 | 2026-04-21 | 2026-06-16 | |
| `fantasyProsIdp` / `fantasyProsSf` / `yahooBoone` / `dynastyNerdsSfTep` | 6 / 2 / 6 / 3 | | | thin |

**About IDPTC's 19 days.** This is not a collection gap. IDPTC republishes rarely: the source-staleness record in
`CLAUDE.md` measures 6 content changes in 165 archives after the floor. So 19 change days probably *is* IDPTC's
true pre-floor history from March to July 2026. Between changes, the last observed board is the value then in
force, which is the `nearest-prior` fidelity.

**Point-in-time.**
- Yes. Each is our own observation, committed shortly after the scrape.
- The JSON files carry `scrapeTimestamp`.
- The commit timestamp is an upper bound on the observation time.
- The scrapes are not recomputed later.

**Identity.**
- The dated JSON exports already carry `_sleeperId`, joined at the time.
- Raw CSVs carry names only.
- They would resolve through `src/identity/resolution.py` under the served V1 policies, exactly like the
  existing archive backfill.

**Lineage.** Lineage is the same as for the live sources: KTC base and TE++ are one provider; Dynasty Daddy
relays others.

**R1's KTC rows already have a fixed role.** R1's `ktc` and `ktcSfTep` are the keys `src/sources/ktc_market.py`
names `KTC_HISTORICAL_MARKET_KEYS`. Its rule, quoted exactly: "Pre-2026-09-08 KTC boards. Both are Crowd-only
captures. Readable ONLY as the historical stand-in for the market on as-of replays that predate the three-mode
capture — never a live fallback, never a vote." So a backfill under D1 could carry them only in that role, and a
KTC-only comparison under D2(c) would be a comparison against that Crowd-only stand-in for KTC Market, named as such.

**What a backfill could and could not provide.**
- It could provide the `source_value` lane: vendor-published numbers.
- It could not provide `canonical_board` values. The pipeline never ran on those dates, and replaying today's
  pipeline would be a `reconstructed` value, which `src/history` defines but has no approved methodology to
  produce.
- So At-the-Time grades for these trades would need a separate owner-approved reconstruction methodology. The data
  is necessary for that, but not sufficient.

**Verdict:** USABLE_PENDING_APPROVAL. **Owner decisions needed: D1 and D2 in §5.**

### 3.2 V1: KTC player-page value history

- **URL:** `https://keeptradecut.com/dynasty-rankings/players/<slug>` (for example `rome-odunze-1587`).
- **Type:** vendor.
- **Cost:** free.

**What it is.**
- The page is server-rendered with embedded daily arrays `{"d":"YYMMDD","v":<value>}`.
- The arrays are `overallValue` (Crowd), `vftValueHistory` ("value from trades", that is KTC Trades) and
  `blendValueHistory` (the KTC Market blend), plus rank histories.
- There is one set for SF and one for 1QB, daily from 2020-05-26.
- TE-premium history was not present.
- A guessed pick slug returned 404, so per-pick history is unconfirmed.

**Spot check against R1.** Rome Odunze, SF, Crowd:

| date | KTC page history | repo `ktc.csv` | difference |
|---|---|---|---|
| 2026-04-16 | 5561 | 5509 | 0.9% |
| 2026-06-01 | 5460 | 5467 | 0.1% |
| 2026-07-13 | 5211 | 5223 | 0.2% |

Josh Allen was 9997 against 9994 on 2026-04-16, but 9987 against 9999 on 2026-07-13. The residual is plausibly
intraday or timezone, and is not proven. R1 itself holds several intraday versions per day (see D1).

**Lineage traps.**
- `blendValueHistory` is KTC Market: the quantity our registry carries as `ktcCrowdTradesSfTep` (that key is the
  TE++ board; the page arrays seen are base SF). Its one owner is `src/sources/ktc_market.py`, and it is a
  benchmark only, never a vote. A history of it is a history of the benchmark, not of a voting input.
- In the earlier part of the histories checked, `vftValueHistory` and `blendValueHistory` equal `overallValue`
  exactly, so KTC appears to have back-filled Trades history with Crowd values. Those points are not independent
  evidence and must never be counted as a second KTC vote. The date where the series diverge was not recorded in
  this survey. The only related date the repo records is our own three-mode capture start, 2026-09-08 (see
  `KTC_HISTORICAL_MARKET_KEYS` in §3.1).
- Both points bear directly on D1 and D2(c).

**Terms.** Quoted from `https://keeptradecut.com/terms-and-conditions`:
- "Prohibited Activities: ... Any form of automated data collection, including but not limited to: Web scraping
  Data mining ..."
- "You may not use our data, content, or materials on any other website or networked computer environment."
- "Limited License ... personal use of this website."

KTC's `robots.txt` disallows `/dynasty-rankings/histories`.

**Identity.** KTC ids appear in slugs. DynastyProcess `db_playerids.csv` maps `ktc_id` to `sleeper_id` (O3), and
the repo has `src/sources/ktc_identity.py`.

**Verdict:** NOT_USABLE without a licence from KTC.

### 3.3 V2: KTC in the Wayback Machine

**Snapshot counts.** These are CDX counts of distinct archived days with HTTP 200 status.

| URL | Months covered | Archived days per month |
|---|---|---|
| `keeptradecut.com/dynasty-rankings`, every query variant | every month 2024-01 to 2026-10 | 4 to 19 (2024: about 1 to 14; 2025: 4 to 19; 2026: 4 to 13) |
| bare URL `keeptradecut.com/dynasty-rankings` | — | 1 to 4 |
| `keeptradecut.com/trade-calculator` | — | 1 to 4 |
| one player page | — | 10 days in total (2024: 1, 2025: 7, 2026: 2) |

**Server-rendered.** One snapshot (2025-01-05) was checked. It embeds `playersArray`: 500 assets, including
**36 `RDP` pick rows**. Each carries `oneQBValues` and `superflexValues`, each with `tep` / `tepp` / `teppp`
variants. **So one snapshot is a complete multi-format board**, and it is genuinely point-in-time.

**Terms.**
- The KTC ToS (V1) applies to the data however it is obtained.
- Internet Archive terms: "Access to the Archive's Collections ... is granted for scholarship and research
  purposes only", and the user certifies use complies with intellectual-property law.

**Verdict:**
- NOT_USABLE for production values.
- At most PARTIAL as a private, never-served validation set, for example to measure how well a reconstruction
  matches, and only if the owner rules that this is research use (D6).

### 3.4 V3: Dynasty Daddy

**Documented API.** Per `https://dynasty-daddy.com/help/api-documentation`, the only documented endpoints are
`GET https://api.dynasty-daddy.com/api/v1/values/dynasty` and `/values/redraft`. The page says "Please cache
responses and don't hammer the servers." Both are current-only.

**The undocumented per-asset history endpoint.** `GET /api/v1/player/{name_id}` returns one row per day. A single
probe of `2027early1stpi` returned 788 daily rows from 2024-08-31 to 2026-10-26. Each row has these columns:
- KTC, as `trade_value` / `sf_trade_value`;
- DynastyProcess, as `dp_*`;
- DraftSharks, as `ds_*`;
- ADP, as `adp_*`;
- FantasyPros, as `fp_*`;
- DD's own `daddy_*` / `daddy_v2_*`;
- others.

The `fc_*` columns were null for picks. Positions are QB, RB, WR, TE and PI only, so there is **no IDP**.

**Spot check against R1** (`ktc.csv`, 2027 Early 1st):

| date | DD `sf_trade_value` | repo `ktc.csv` |
|---|---|---|
| 2026-04-16 | 6859 | 6877 |
| 2026-06-01 | 7114 | 7117 |
| 2026-07-13 | 7077 | 7099 |

DD is a faithful KTC SF relay.

**Terms.** `https://dynasty-daddy.com/help/terms-of-service`: "You may not use the platform for fraudulent
activities, automated data scraping, or any malicious intent."

**Lineage.** The KTC columns *are* KTC (V1), relayed. KTC's own terms forbid using KTC data "on any other website",
so relaying it does not clean it.

**Identity.** Easy: rows carry `sleeper_id`.

**Verdict:** NOT_USABLE without written permission. That means Dynasty Daddy's permission, plus KTC's for the KTC
columns.

### 3.5 V4: FantasyCalc

**Endpoint.** `GET https://api.fantasycalc.com/trades/historical/{fcId}?isDynasty=true&numQbs=2` returned daily
`{date, value}`. The probe was Rome Odunze, and it returned **only 2026-01-01 onward**.

**Spot check against R1.** The history does not match our contemporaneous `fantasyCalc.csv`:

| date | FantasyCalc history | repo `fantasyCalc.csv` |
|---|---|---|
| 2026-06-01 | 3418 | 3639 |
| 2026-07-13 | 3292 | 3330 |

An earlier draft of this survey said "a public client library" documents that trend and history requests ignore
`numTeams` / `ppr`. The library is not named in this survey's evidence, so that explanation is
**UNVERIFIED**. What is observed is the mismatch above: the history is not the league-parameterised value we
collect.

**Terms.** `https://fantasycalc.com/terms-of-usage` (effective 2026-10-10):
- "Only GET /values/current may be called programmatically without separate written permission. Website scraping
  is prohibited."
- Sites at or above 1,000 monthly active users need "express written permission".
- Attribution is required on every page displaying the data.
- The data may not be used to create a "material substitute" for substantial portions of FantasyCalc's content (for example its
  trade calculator). Only that phrase
  is quoted; the independent review of this survey confirmed the clause on the terms page.

**Identity.** Easy: rows carry `sleeperId`.

**Verdict:** NOT_USABLE without written permission. Even with permission it does not cover 2024 to 2025 on the
evidence seen.

### 3.6 V5 and V6: IDP Trade Calculator

- **No history feature.** The page (`https://idptradecalculator.com/`) loads a 10 KB `script.js`, which fetches
  current values from a Google Apps Script `exec` URL.
- **Not crawled for values.** Wayback captured the homepage on 9 days in total (2024-12 to 2026-02), and those
  captures contain no values.
- **Data endpoint not checked.** The Archive returned "Temporarily Offline" when queried for the Apps Script URL,
  so that check is UNKNOWN.
- **Terms.** `https://idptradecalculator.com/terms.html` (last updated 2025-04-08) is a generic generator
  template. It has no data-reuse or scraping clause. `robots.txt` allows all.
- **IDP and picks.** IDP yes. Picks only on the live board, and in R1 from 2026-04-09.

**Verdict:** NOT_USABLE: there is nothing historical to retrieve. **The only IDPTC history anywhere is R1**, from
2026-03-09.

### 3.7 V7: DLF, DraftSharks, The IDP Show

Their historical rankings and values sit behind paid subscriptions:
- DLF membership;
- the DraftSharks login the scraper already uses;
- The IDP Show's Substack tiers.

The directive excludes paid data, so they are NOT_USABLE as archives. Their pre-floor snapshots exist only in R1,
collected under the subscriptions the site already holds. Whether R1 may reuse those is part of D1.

### 3.8 O1 to O3: DynastyProcess open data

- **Repo.** `https://github.com/dynastyprocess/data`, licensed GPL-3.0, updated weekly by GitHub Actions.
- **O1 values.** `files/values-players.csv` has columns `ecr_1qb`, `ecr_2qb`, `value_1qb`, `value_2qb`,
  `scrape_date`, `fp_id`. Positions are QB, RB, WR and TE only. `files/values-picks.csv` holds pick ECR.
  - The file history is weekly and continuous: 52 commits in 2024, 50 in 2025, 36 in 2026 to date. There are 1 to
    8 commits a month, and only one in 2026-03/04.
  - Each `git` revision is a point-in-time weekly snapshot.
- **O2 ECR.** `files/db_fpecr.parquet` (39 MB, not downloaded) is FantasyPros ECR including
  `/nfl/rankings/dynasty-idp.php`, `dynasty-dl`, `dynasty-lb`, `dynasty-db`, `dynasty-superflex` and
  `dynasty-overall`, with `scrape_date`. Commits are weekly from 2024-09 (and earlier). The cumulative date range
  inside the parquet is stated by the README but **not verified here**.
- **O3 identity.** `files/db_playerids.csv` has columns including `fantasypros_id`, `ktc_id`, `sleeper_id`,
  `mfl_id` and `espn_id`.
- **Lineage.** Every DP value derives from FantasyPros expert consensus. It is the same evidence family as the
  board's `fantasyProsSf` / `fantasyProsIdp` sources, and it is not a trade market. Using it would add no
  independent vote. As an "at-the-time price" it would measure FantasyPros' experts, not the KTC or IDPTC market
  the trade was struck against.
- **Terms.** GPL-3.0 allows reuse, with copyleft obligations whose application to *data* the owner may wish to
  judge. The FantasyPros upstream terms on republished ECR were not reviewed (UNKNOWN).

**Verdicts:**
- O1: PARTIAL.
- O2: PARTIAL; this is the only free, dated IDP evidence for 2024 to early 2026, and it is ranks only.
- O3: USABLE_PENDING_APPROVAL, as an identity bridge.

## 4. Governance flag: the current posture already touches these terms

**Out of scope for IDPM-3, recorded so it is not lost.** The live pipeline already collects KTC by browser scrape,
and R1 is that same collection's history. KTC's terms read today forbid "any form of automated data collection".

FantasyCalc's terms (effective 2026-10-10) require:
- prominent attribution with a link on every page that displays FantasyCalc data or derivatives;
- 3-hour caching;
- written permission at or above 1,000 monthly active users;
- no use of the data to create a "material substitute" for substantial portions of FantasyCalc's content (for example
  its trade calculator; only that phrase is
  quoted here; the independent review confirmed the clause on the terms page). The site serves its own trade
  calculator, so this clause bears on the live posture, not only on history.

This survey takes no position on whether the live posture complies. It notes only that **approving R1 is not a new
category of exposure, but it is not a cleaner one either**. The owner may want D1 decided together with that
broader question.

## 5. Owner decisions needed

- **D1: approve R1 as a source.** May the repo's own git history of tracked vendor CSVs (from 2026-03-09) and the
  dated `dynasty_data_*.json` exports (from 2026-03-25), both up to 2026-07-13, be backfilled into `src/history` as
  `source_value` observations? If yes, this needs:
  - a change to the "permanent" `HISTORY_FLOOR` record, which a separate authorized unit would make;
  - a rule for what timestamp counts as observation time (`scrapeTimestamp` where present, else commit time).
    One calendar day can hold several intraday versions, so the rule must also choose a version, for example the
    last commit before a stated cutoff. Example: Rome Odunze in `ktc.csv` ranges 5509 to 5558 across the 10
    commits dated 2026-04-16 UTC. The review measured 5493 to 5558, because it also counted a commit at
    2026-04-17 03:59 UTC, which is still 2026-04-16 in US time zones. That gap is itself why the cutoff and its
    time zone must be fixed;
  - KTC rows only in the role `src/sources/ktc_market.py` already gives `KTC_HISTORICAL_MARKET_KEYS`: a Crowd-only
    historical stand-in for the market on as-of replays, never a vote (§3.1);
  - for each source family, a statement of whether reusing that history is within the posture the owner already
    accepts for live collection. KTC and the paid DLF, DraftSharks and IDP Show subscriptions are the sensitive
    ones.
- **D2: methodology for pre-floor At-the-Time grades.** Even with D1, the ledger would hold vendor numbers, not
  canonical board values. Choose one:
  - (a) keep At-the-Time `unavailable` before 2026-07-14 and use R1 only for diagnostics;
  - (b) authorize designing a labelled `reconstructed` lane under the existing champion-versus-challenger and
    backtest gates;
  - (c) allow a per-source at-the-time comparison, for example KTC-only, clearly named as such. This is not the
    canonical grade. Before 2026-09-08 a KTC-only figure is the Crowd-only historical stand-in for KTC Market,
    not KTC Market itself, and must be labelled that way (§3.1, §3.2).
- **D3: permission requests.** Should anyone ask KTC, FantasyCalc or Dynasty Daddy for written permission to use
  2024 to 2026 history (V1, V3, V4)? Without it, all three stay NOT_USABLE.
  - Default if the owner does not decide: no request is made.
  - If a request is made and the publisher asks for payment, that is a separate decision, because the directive
    excludes paid data.
- **D4: IDP before March 2026.** Accept that no IDP trade-value history exists for 2024 to early 2026, which
  leaves IDP legs of those trades permanently `unavailable`. Or authorize evaluating DynastyProcess's FantasyPros
  dynasty-IDP ECR ranks (O2) as an explicitly named, rank-only, non-market fallback.
- **D5: DynastyProcess identity bridge (O3).** Approve or decline use of `db_playerids.csv`, licensed GPL-3.0, for
  KTC-id or FantasyPros-id to Sleeper-id mapping, if any of the above is approved.
- **D6: Wayback snapshots as a private research set (V2).** May archived KTC snapshots from the Internet Archive be
  used as a private, never-served, research-only validation set, for example to measure a reconstruction under
  D2(b)? V2's PARTIAL verdict assumes a yes that no other decision here asks for. Default if the owner does not
  decide: not used.

## 6. Method and footprint

Every network read was an agent tool call making a single request, used only to judge feasibility.

| Read | Requests |
|---|---|
| `robots.txt` for 9 domains | 9 |
| terms pages for KTC, IDPTC, FantasyCalc, Dynasty Daddy and the Internet Archive | some read in the in-app browser because they render client-side |
| KTC player pages | 2 (plus one 404 pick slug) |
| archived KTC rankings snapshot | 1 |
| Dynasty Daddy `today` directory | 1 |
| Dynasty Daddy pick history | 1 |
| FantasyCalc `values/current` | 1 |
| FantasyCalc history (one player) | 1 |
| Wayback CDX queries | about 10 |
| GitHub API, DynastyProcess metadata and file headers | metadata and headers only |

- **Probes against terms that prohibit automated collection.** Agent tool calls are automated requests. These
  probes were made against publishers whose terms forbid automated collection, and they sit in the same tension
  as each other:

  | probe | requests | terms clause | terms read before or after the probe |
  |---|---|---|---|
  | KTC player pages | 2 (plus 1 that returned 404) | KTC: "any form of automated data collection" | not recorded |
  | archived KTC rankings snapshot (Wayback) | 1 | KTC, as above, applies to KTC data however obtained | not recorded |
  | Dynasty Daddy per-asset history `/api/v1/player/{name_id}` (undocumented) | 1 | Dynasty Daddy: "automated data scraping" | not recorded |
  | FantasyCalc `/trades/historical/{id}` | 1 | FantasyCalc: only `GET /values/current` programmatically without written permission | **after**: the terms page is client-rendered and was read later. No further FantasyCalc history calls were made after it was read |

  Each was a single feasibility request, but that does not take it outside the clause. The owner should treat all
  four the same way.
- **Probe files never reached the repo.** Fetched bodies went only to the session's scratchpad, never to the repo
  or `data/`. Nothing is committed but this document.
- **Not verified:**
  - KTC per-pick history pages;
  - the date range inside `db_fpecr.parquet`;
  - the FantasyPros terms;
  - Kaggle, which needs a login to search;
  - Wayback capture of the IDPTC Apps Script endpoint (the Archive was temporarily offline).
