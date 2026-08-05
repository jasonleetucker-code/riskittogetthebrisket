# Data & Source Audit

Deliverable §10 of the master site audit. Scope: every feed the platform ingests — the 21-source
ranking registry, the news providers, nflverse, the ROS source set, the BDVM projection
snapshots, and the two crawl ledgers (sharp, intel) — with status, access model, credentials,
coverage on the served board, freshness, failure behaviour, fallback behaviour, and whether a
historical snapshot exists.

Primary evidence: workstream **W05** (ingestion / sources / freshness), plus **W21** (news,
nfl_data), **W15**/**W16** (sharp and intel data), **W13** (BDVM projections). Supporting
findings from W03, W04, W06, W11, W17, W23, W26, W29 are cited by id where they bear on a source.

**Verification status.** No W05, W13, W15, W16 or W21 finding was selected for adversarial
re-verification (`docs/master-site-audit/evidence/verify/` contains verdicts for W02–W04, W06–W12,
W14, W17–W20, W22–W24, W26–W27, W29–W30 only). Those findings are authored, schema-validated and
merged, with the reproduction command in each record — but they were not independently attacked.
Where this document leans on a W23 or W04 finding that **was** verified, it reports the verifier's
position and says so.

Re-run any number below with the command printed beside it. Commands assume the audit cookie:

```bash
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
```

---

## Headline

**The ingestion pipeline is healthy and the reporting layer about it is not.**

All 21 registered ranking sources have a live fetcher, a present CSV, a fresh timestamp and real
votes on the served board — traced end to end and reproduced by the repo's own three watchdogs
(W05-F010). No registered source is dead. No fetched CSV is unread.

What is broken is everything that would *tell you* if that stopped being true. The one page
dedicated to source health renders 4 of 21 sources (W05-F001, W23-F007). `/api/status.source_health`
reports `total_sources: 2` and `missing_sources: []` for a board built from 21 (W05-F002,
W23-F008). Nine sources — including `ktcSfTep`, the retail anchor that sets the top of the value
scale — can vanish from the board entirely and leave `contractHealth: healthy` with zero errors
(W05-F004). Per-source staleness *is* computed on every payload and is read by no user-facing
surface at all (W05-F009). The single most common real-world source break — a vendor renaming a
column — is silently caught for 4 of 22 sources and silently ignored for the other 18 (W05-F003).

Separately, and independent of reporting: **only 2 of 21 sources cast any vote on any draft
pick**, and all 72 slot picks are single-source, even though the contract already holds a KTC
value for every one of them (W05-F006).

Three subsystems are **Blocked by data** in this container and must not be read as defects:
BDVM projections (`data/bdvm/` absent), the intel snapshot (`data/intel/snapshot_dynasty_main.json`
absent), and the sharp cohort (`data/intel/ledger.sqlite3` present, migrated, zero rows). All
three degrade honestly — see §10.

---

## 1. The ranking registry — all 21 sources

Registry: `src/api/data_contract.py::_RANKING_SOURCES`, mirrored in
`frontend/lib/dynasty-data.js::RANKING_SOURCES` and diffed by
`tests/api/test_source_registry_parity.py`. All 21 carry `weight: 1.0` by policy;
`config/weights/default_weights.json` is historical documentation and is loaded by nothing.

### 1a. Access model and credentials

| # | Registry key | Publisher / access path | Credentials needed | Signal | Scope |
|---|---|---|---|---|---|
| 1 | `ktcSfTep` | keeptradecut.com — Playwright scrape (`Dynasty Scraper.py`) | none | **value-direct** | offense |
| 2 | `idpTradeCalc` | IDP Trade Calculator — Playwright scrape (`Dynasty Scraper.py`) | none | **value-direct** | IDP + offense (cross-market backbone) |
| 3 | `dlfSf` | DLF — WordPress member auth behind Cloudflare | `DLF_USERNAME` + `DLF_PASSWORD`, cached `dlf_session.json` (~14d) | rank | offense |
| 4 | `dlfIdp` | DLF, same session | same | rank | IDP |
| 5 | `dlfRookieSf` | DLF, same session | same | rank (rookie translation) | offense |
| 6 | `dlfRookieIdp` | DLF, same session | same | rank (rookie translation) | IDP |
| 7 | `idpShow` | The IDP Show (Substack) | **manual cookie dump** `idpshow_session.json`; `connect.sid` expires ~90d; captcha blocks auto-login | rank | IDP |
| 8 | `draftSharks` | draftsharks.com — Playwright, in-browser login flow | `DRAFTSHARKS_EMAIL` + `DRAFTSHARKS_PASSWORD`, `draftsharks_session.json` (auto-refreshing) | rank (DS combined-rank pair) | offense |
| 9 | `draftSharksIdp` | same | same | rank (DS combined-rank pair) | IDP |
| 10 | `dynastyNerdsSfTep` | Dynasty Nerds — plain HTTP, no auth | none | rank | offense |
| 11 | `fantasyCalc` | FantasyCalc public JSON API | none | rank | offense |
| 12 | `otcffbSf` | OTC Fantasy Football public JSON API | none | rank | offense |
| 13 | `fantasyNavigatorSf` | Fantasy Navigator public REST API (Render) | none | rank | offense |
| 14 | `pfkDynasty` | Play For Keeps — Supabase PostgREST, site's own publishable anon key | none (public read path) | rank | offense |
| 15 | `dynastyDaddySf` | Dynasty Daddy public JSON API (`market=14`) | none | rank | offense |
| 16 | `fantasyProsSf` | FantasyPros — plain HTTP | none | rank | offense |
| 17 | `fantasyProsIdp` | FantasyPros combined IDP board — plain HTTP | none | rank | IDP |
| 18 | `fantasyProsFitzmaurice` | FantasyPros / Fitzmaurice monthly chart via Datawrapper TSV | none | rank | offense (TEP) |
| 19 | `flockFantasySf` | Flock Fantasy public JSON API | none | rank | offense |
| 20 | `flockFantasySfRookies` | Flock Fantasy public JSON API (`PROSPECTS_SF`) | none | rank (rookie translation) | offense |
| 21 | `yahooBoone` | Yahoo / Justin Boone monthly HTML charts | none | rank | offense (TEP) |

**Blocked by credentials or licensing: zero sources today.** Three sources need credentials
(DLF ×4 keys, DraftSharks ×2 keys, IDP Show cookie) and all three currently have valid data on
disk. `GET /api/health.session_cookies` reports the three session files as `present: false` in
this container — the fetchers are never run here — with `autoRefresh: true` for DLF and
DraftSharks and **`autoRefresh: false` for `idpshow_session.json`**. IDP Show is the one source
whose credential cannot self-heal; a lapsed cookie is exactly the failure mode
`config/source_staleness.json` was written for, and §7 shows that failure is invisible on every
surface.

`draftSharks` / `draftSharksIdp` are registered `is_rank_signal: false` but are **not** in
`_VALUE_BASED_SOURCES` (`frozenset({'ktcSfTep','idpTradeCalc'})`) — they vote through the
`ds_combined_rank_partner` path, not the `raw / site_max × 9999` value-direct path.

```bash
.venv/bin/python -c "import sys;sys.path.insert(0,'.');from src.api import data_contract as dc;print(len(dc._RANKING_SOURCES), dc._VALUE_BASED_SOURCES)"
grep -nE 'getenv|environ' scripts/fetch_dlf.py scripts/fetch_draftsharks.py scripts/fetch_idpshow.py
curl -s http://127.0.0.1:8000/api/health | .venv/bin/python -m json.tool | sed -n '/session_cookies/,/}/p'
```

### 1b. Coverage, freshness budget, and safety nets

`servedCoverage` = rows on the served **1,092-row** contract that carry this source in
`sourceRankMeta`, i.e. rows where it actually contributed to the blend
(`server.py::_compute_served_source_coverage`). It is the honest per-source coverage number and it
is already served on `/api/status`.

| Registry key | CSV rows | Board values | Votes | **Served coverage (of 1,092)** | Freshness budget | Row floor | Schema probe |
|---|---:|---:|---:|---:|---:|---:|:--:|
| `idpTradeCalc` | 900 | 911 | 903 | **770** | 6 h | 700 | no |
| `ktcSfTep` | 500 | 501 | 499 | **425** | 6 h | **none** | no |
| `fantasyProsSf` | 540 | 474 | 467 | **412** | 6 h (default) | **none** | **yes** |
| `pfkDynasty` | 496 | 476 | 470 | **395** | 6 h | **none** | no |
| `draftSharks` | 454 | 420 | 412 | **381** | 6 h | 190 | no |
| `flockFantasySf` | 439 | 415 | 411 | **378** | 168 h | 250 | no |
| `fantasyCalc` | 399 | 394 | 391 | **377** | 6 h | **none** | no |
| `fantasyNavigatorSf` | 758 | 455 | 448 | **371** | 6 h | **none** | no |
| `yahooBoone` | 410 | 377 | 374 | **364** | 720 h | 360 | no |
| `dynastyDaddySf` | 367 | 365 | 363 | **358** | 6 h | 250 | no |
| `otcffbSf` | 347 | 343 | 342 | **342** | 6 h | **none** | no |
| `fantasyProsFitzmaurice` | 299 | 299 | 299 | **298** | 720 h | 225 | no |
| `dynastyNerdsSfTep` | 294 | 293 | 293 | **293** | 6 h | 230 | no |
| `idpShow` | 350 | 349 | 347 | **279** | 720 h | 150 | no |
| `dlfSf` | 281 | 280 | 278 | **277** | 720 h | 240 | **yes** |
| `draftSharksIdp` | 410 | 319 | 318 | **273** | 6 h | 85 | no |
| `fantasyProsIdp` | 219 | 211 | 206 | **166** | 6 h | 75 | **yes** |
| `dlfIdp` | 171 | 171 | 169 | **137** | 720 h | 150 | **yes** |
| `flockFantasySfRookies` | 84 | 76 | 75 | **70** | 168 h | **none** | no |
| `dlfRookieSf` | 55 | 110 | 55 | **52** | 6 h (default) | **none** | no |
| `dlfRookieIdp` | 29 | 29 | 29 | **24** | 6 h (default) | **none** | no |

Source: `docs/master-site-audit/evidence/W05/source-chain.json` (CSV rows, board values, votes,
budget) and a live `/api/status` read (served coverage). Floors:
`src/api/data_contract.py::_DEFAULT_SOURCE_ROW_FLOORS` merged with
`config/weights/source_row_floors.json` (13 keys, one of which — `ktc` — is not a blend source).
Probe: the hardcoded list at `data_contract.py:3584`.

```bash
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/status \
  | .venv/bin/python -c "import json,sys;print(json.load(sys.stdin)['served_source_coverage'])"
.venv/bin/python -c "import sys;sys.path.insert(0,'.');from src.api import data_contract as dc;print(dc._DEFAULT_SOURCE_ROW_FLOORS)"
```

Three things to read off that table:

- **`ktcSfTep` — the retail anchor, one of two value-direct voters, 425 rows on the board — has
  no row floor and no schema probe.** It is the least protected source in the registry and the
  most load-bearing.
- **`fantasyNavigatorSf` publishes 758 rows and lands 371.** That is not an ingestion failure:
  W06-F014 measured its 60.0% name-join rate and confirmed the misses are players with no board
  row under any spelling — the enrichment cascade fills existing rows and never creates one. Same
  for `draftSharksIdp` (78.0%) and `fantasyProsSf` (87.8%). 17 of 21 sources join above 92%.
- **`dlfRookieSf` shows 110 board values against 55 CSV rows.** The extra 55 are synthetic
  `"2026 Pick R.SS"` stamps written into `canonicalSiteValues` that appear in `sourceRanks` on
  **zero** pick rows — see §6.

---

## 2. What "coverage" means, and why the two big numbers are not a shortfall

The health check reports `ktc 590 of 1074` and `idpTradeCalc 898 of 1074` against the raw player
universe. Both decompose exactly, with no lost rows (W05-F011, `Implemented and verified`):

| | matched player rows | pick-anchor rows | total |
|---|---:|---:|---:|
| `ktc` | 464 (of KTC's 500-row board minus its 36 generic pick tiers — **464/464 matched**) | 126 | **590** |
| `idpTradeCalc` | 814 (of 900 scraped) | 84 | **898** |

The 483 contract rows with no KTC value are 398 IDP (KTC publishes no defenders), 19 K, 50 deep
offense past KTC's top-500 cut, 16 unclassified. The 181 with no IDPTradeCalc value are 48 picks
(the 5th/6th-round tiers IDPTC does not price), 76 deep offense, 28 deep IDP, 19 K, 10
unclassified.

```bash
python3 - <<'EOF'
import json,collections
d=json.load(open('data/dynasty_data_2026-08-04.json')); pl=d['players']; pa=d['pickAnchors']
for k in ('ktc','idpTradeCalc'):
    print(k, sum(1 for n,p in pl.items() if p.get(k) is not None), 'pickAnchors', len(pa[k]))
EOF
```

---

## 3. Freshness: computed on every payload, shown to nobody

Per-source freshness exists in three places with **two disagreeing threshold tables** and **zero
user-facing renderers** (W05-F009, `Implemented but disconnected`, P2):

| Mechanism | Where | Thresholds | Consumer |
|---|---|---|---|
| `dataFreshness.sourceTimestamps` (22 entries: `ageHours`, `maxAgeHours`, `staleness`) | stamped into **every** `/api/data` response | `_SOURCE_MAX_AGE_HOURS` — 19 keys (6 h / 168 h / 720 h) + an implicit **6 h default** for the 3 unlisted | exactly one module: `src/consensus_edge/service.py`, whose flag is **off** by default (ADR-023) |
| `source_health.sources` (22 entries: `lastFetched`, `ageHours`) | `/api/status` | — | `src/api/source_health_alerts.check_and_alert`, from the daily signal-alerts sweep → **email only, if `ALERT_TO` is set** |
| `config/source_staleness.json` | file | **24 h flat**, every source | the email path above |

The frontend references `dataFreshness` in exactly one place (`rankings/page.jsx:835`) and reads
only `generatedAt` for a whole-board "updated Xm ago". `StaleDataBanner` polls `/api/health` and
shows one whole-board number.

**Live demonstration, taken while writing this document.** The container's snapshot is frozen (the
harness suppresses the scrape), so the CSVs have aged past their budgets. `/api/data` now reports
**13 of 22 sources `stale`** — and every surface still reads healthy:

```
ktc 6.082/6 stale · ktcSfTep 6.082/6 stale · idpTradeCalc 6.082/6 stale
dynastyNerdsSfTep, fantasyProsSf, fantasyProsIdp, fantasyCalc, otcffbSf,
dynastyDaddySf, draftSharks, draftSharksIdp, fantasyNavigatorSf, pfkDynasty — all stale
```

```bash
curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/data?view=app" \
 | .venv/bin/python -c "import json,sys;t=json.load(sys.stdin)['dataFreshness']['sourceTimestamps'];[print(k,v['ageHours'],v['maxAgeHours'],v['staleness']) for k,v in t.items()]"
curl -s http://127.0.0.1:8000/api/health   # data_age_hours: 0.7, data_stale: false
```

The aged CSVs are a **harness artifact** — do not read "13 stale" as a production defect. What is
*not* an artifact is the mechanism it exposes: 13 sources crossed their own declared threshold,
the contract said so on every response, and `/api/health` reported `data_age_hours: 0.7`,
`data_stale: false`. That gap is W23-F006 (verified, **rescoped** by the verifier): both
`/api/metrics.data_age_seconds` and `/api/health.data_age_hours` measure time since *this process
loaded the file*, not since the data was produced. The verifier upheld the mechanism and measured
the loaded snapshot at 6.25 h old — past the 6 h threshold — while `/api/health` reported 0.2 h
and `data_stale: false`; it rescoped the author's claim that the field is *permanently* identical
to uptime, leaving the residual defect as "a restart resets the staleness clock". The honest
per-source ages are three keys away in the same process.

Two further facts about freshness:

- **Staleness is purely descriptive.** Nothing in `_compute_unified_rankings` reads
  `sourceTimestamps.staleness`. A stale source's last-known values keep voting at full weight
  (W05-F009, confirming PRIOR-A25-F13). The prior audit's companion claim (PRIOR-A25-F04, "the
  contract calls 12 sources stale while the watchdog calls all 22 fresh") was **not reproducible
  at HEAD** — under a live snapshot both tables read fresh, because `_build_source_timestamps` now
  prefers the `data/scrape_state` stamp over CSV mtime. The two-table conflict is real and latent;
  the divergence it measured is not currently observable.
- **The refresh cadence is slower than the budgets assume.** The GitHub-Actions 2 h cron produced
  10 runs where 13–14 were scheduled over a 26.7 h window, with gaps of 4.00/4.00/3.75/3.50 h
  (W05-F012, P3, confidence *medium* — measured from the workflow's own commit stream, a proxy for
  the run stream). Over the same window the prod-side systemd fetch timers hit 14/14. The 6 h
  budgets were sized as "≈ three missed cycles"; at the observed cadence that is closer to 1.5.

---

## 4. Failure behaviour: what actually happens when a source breaks

Measured by mutating a copy of `CSVs/site_raw/` and re-running the real
`_enrich_from_source_csvs` + `validate_api_data_contract` (W05-F003, W05-F004).

| Failure mode | What the ingest does | What the contract validator does | Is it visible? |
|---|---|---|---|
| **CSV file deleted** | appends `{'error':'file_not_found'}`, logs a warning | flips contract to **degraded** | yes — honest |
| **Vendor renames a column** (the most common real break) | `schema_mismatch` for **4 of 22** sources only (`dlfSf`, `dlfIdp`, `fantasyProsIdp`, `fantasyProsSf`). The other 18 — including `ktcSfTep` and `idpTradeCalc` — fall through the alias lookup and vanish with `parse_errors == []` | nothing, unless a row floor exists | **no, for 18 sources** |
| **Header-only CSV** (fetcher ran, scraped nothing) | `if not csv_lookup: continue` — silent, no error | nothing | **no, for any source** |
| **Source's rows drop below its floor** | — | warning | yes, for the 12 floored sources |
| **Source's rows hit zero, floor exists** | — | `source_missing:{key}` → status **invalid** | yes |
| **Source's rows hit zero, no floor** (9 sources) | — | **nothing** | **no** |

Measured proof of the last row — stripping each source in turn from the live contract and
re-running the validator:

```
ktcSfTep           -> healthy, ok=true, errors=[]
otcffbSf           -> healthy, ok=true, errors=[]
fantasyCalc        -> healthy, ok=true, errors=[]
pfkDynasty         -> healthy, ok=true, errors=[]
fantasyNavigatorSf -> healthy, ok=true, errors=[]
fantasyProsSf      -> healthy, ok=true, errors=[]
dlfSf              -> invalid, ['source_missing:dlfSf']
yahooBoone         -> invalid, ['source_missing:yahooBoone']
```

Artifacts: `evidence/W05/schema-probe-coverage.json`, `evidence/W05/source-drop-contract-health.json`,
`evidence/W05/source-failure-modes.json`. Both reproduction scripts are in the finding records
(W05-F003, W05-F004) and run against a temp copy of `CSVs/`.

**The nine unfloored sources are:** `ktcSfTep`, `fantasyProsSf`, `fantasyCalc`, `otcffbSf`,
`fantasyNavigatorSf`, `pfkDynasty`, `dlfRookieSf`, `dlfRookieIdp`, `flockFantasySfRookies`. The
deferral is documented in-code (`data_contract.py:701-708`) as pending a live baseline; the live
baseline now exists — it is the table in §1b.

### The safety nets that do work, and where they run

| Gate | Runs where | Strictness | Verdict today |
|---|---|---|---|
| `scripts/watchdog_freshness.py` | 2 h refresh workflow, CI checkout | per-source, all 22 | `ok: 22 sources fresh, 0 hard-stale` |
| `scripts/watchdog_contract_coverage.py` | 2 h refresh workflow, CI checkout | per-source, all 21 registered | `ok: 21 registered source(s) covered, 0 fresh-but-absent` |
| `scripts/verify_live_source_coverage.py` | **`deploy/verify-deploy.sh:340` only** | strict, all 21 | `ok: live board carries 21 registered source(s)` |
| `.github/workflows/health-check.yml` (every 6 h, against prod) | GitHub Actions | **`MIN_SOURCES = 8`, `MIN_PER_SOURCE = 5`** | passes |

W05-F008 (`Partially implemented`, P2): `verify_live_source_coverage.py`'s docstring claims it runs
"every 6h against the public URL"; `grep` finds exactly one caller and it is the deploy script.
The 6 h workflow deliberately inlines a dependency-free check with `MIN_SOURCES = 8` so it needs no
checkout. **Between deploys, the board can lose up to 13 of 21 sources without any production
alert.** The CI watchdogs cover the CI checkout, so the specific exposure is "the running prod
process serves a different board than CI builds".

```bash
grep -rn 'verify_live_source_coverage' .github/workflows/ deploy/
.venv/bin/python scripts/watchdog_freshness.py && .venv/bin/python scripts/watchdog_contract_coverage.py
```

Related, and verified: the scraper's own partial-run guard is not a net either. W23-F003
(verified, **rescoped**) — `sites` is a 2-element list on the live snapshot, so
`site_count < total_sites/2` reduces to `site_count < 1.0`: the guard fires **only on total data
loss**. The verifier upheld the arithmetic and that the path is live, and **corrected the author's
mechanism**: `active_sites` is the config-enabled list fixed before any run outcome, so a skipped
source does *not* shrink the denominator with the numerator. And W23-F002 (verified, rescoped): a
run the guard **refuses to promote** is recorded as `outcome: 'success'` with `last_success_at`
stamped — the verifier confirmed every side effect and rescoped `playersAffected` to **0**, since
the guard correctly returns the previous snapshot and no player value is wrong.

---

## 5. Fallback behaviour

| Situation | Fallback | Honest? |
|---|---|---|
| A source CSV is missing | source drops out of the blend; remaining sources re-aggregate under the count-aware rule (n=1 passthrough → n≥5 trimmed mean-median) | contract flips degraded — **yes** |
| A source silently returns nothing (header-only / renamed header) | same drop, no marker | **no** — W05-F003 |
| A row rests on one post-Hampel source | 30% single-source haircut, `isSingleSource: true` stamped, UI presents it as speculative | yes — verified exact in W02-F013 |
| A blocked/partial scrape | previous snapshot is returned; disk file not overwritten | data handling **yes**, bookkeeping **no** — W23-F002 |
| The board carries no `ktcCrowd` block | FAAB recommender's crowd factor is simply **absent** from the factor list, `warnings: []` | **no** — W05-F005 / W11-F014 |
| The intel snapshot is missing | FAAB rival-intel factor defaults to 1.0 **with** an explicit note and `staleInputs: ['intel']` | **yes** — W11-F015, the model's best-behaved degradation path |
| `nfl_data_py` not importable | `nflverse_direct` fallback returns 19,421 weekly rows in 0.77 s | yes — the live path by design |
| nflverse cache entry ages past TTL | **no last-known-good**: `cache.get()` returns `None` the instant TTL expires and the wrapper returns `[]` — a usable 61.7 MB file on disk is ignored | **no** — W26-F007, P2 |

The FAAB contrast is the sharpest one in the audit: two optional inputs to the same endpoint, one
degrading with a named note and a `staleInputs` stamp, the other vanishing from the factor list
with no warning. W11-F015's own `requiredRepair` says every other optional input should follow it.

---

## 6. Draft picks: 2 of 21 sources vote, and all 72 slot picks are single-source

W05-F006 (`Implemented but defective`, **P1**). Counting non-null `sourceRanks` over the 144 pick
rows on the live board:

| | picks voted on |
|---|---:|
| `ktcSfTep` | 36 (the generic Early/Mid/Late 1st–4th tiers — the only picks in its CSV) |
| `idpTradeCalc` | 96 |
| every other source | **0** |

All 72 slot picks (`2026 Pick 1.01` … `6.12`) have `sourceCount == 1`, anchored on IDPTradeCalc
alone — while `canonicalSiteValues` carries a KTC value for **every one of them**
(`pickAnchors['ktc']` has 126 entries, interpolated by the scraper). Worked example:

```
2026 Pick 1.01
  canonicalSiteValues = {'ktc': 6726, 'idpTradeCalc': 8013, 'dlfRookieSf': 999880}
  sourceRanks         = {'idpTradeCalc': 12}
  anchorValue         = 8013        (a two-market peer average would be 7369.5)
  rankDerivedValue    = 7799
  isSingleSource      = true
```

Root cause: KTC's slot-pick values reach the contract only through `pickAnchors['ktc']`, stamped
under the **demoted, non-voting** `ktc` key. The 2026-04-28 demotion moved the blend vote to
`ktcSfTep` but not the pick anchors, and `ktcSfTep.csv` contains only the 36 generic tiers KTC
publishes. Separately, all 55 `dlfRookieSf` synthetic pick stamps land in `canonicalSiteValues` as
raw synthetic rank encodings (`999880`) and vote on nothing.

This contradicts CLAUDE.md directly — "Pick rows widen the anchor set to include ktcSfTep so the
two real pick markets (KTC + IDPTC) average as peers" — which is true only for the 36 generic
tiers where `ktcSfTep.csv` happens to carry the row (e.g. `2026 Early 1st` = 5605 / 5554, both
markets voting). Affected surfaces: `/rankings`, `/trade`, `/draft`, `/api/trade/simulate`,
`/api/draft-capital`. KTC prices the 1.01 **16% below** IDPTC.

```bash
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/data -o /tmp/full.json
python3 - <<'EOF'
import json,collections
pa=json.load(open('/tmp/full.json'))['playersArray']
picks=[r for r in pa if r.get('assetClass')=='pick']
v=collections.Counter()
for r in picks:
    for k,x in (r.get('sourceRanks') or {}).items():
        if x is not None: v[k]+=1
slot=[r for r in picks if ' Pick ' in r['displayName']]
print(len(picks), dict(v), len(slot), collections.Counter(r['sourceCount'] for r in slot))
EOF
```

Artifact: `evidence/W05/pick-vote-coverage.json`.

---

## 7. Source-health surfaces: do they tell the truth?

**No.** Four surfaces claim to answer "is any source dead?" and none of them can.

| Surface | What it claims | What it actually reports | Finding |
|---|---|---|---|
| `/tools/source-health` | *"Scraper status for every ranking source in the pipeline"* | header reads **"Sources · 4"** — `IDPTradeCalc`, `KTC`, `KTC_TradeDB`, `KTC_WaiverDB`. The 17 CSV-loaded sources are absent. `IDPTradeCalc` renders as **0 rows** (em-dash) because the count lookup is `counts[src] \|\| counts[src.toLowerCase()]` and `source_counts` is keyed `idpTradeCalc` — `'IDPTradeCalc'.toLowerCase()` misses. Per-source ages: none rendered, for the same key-casing reason | W05-F001 (P1), W23-F007 (P2, verified/rescoped — *"the observation is exactly right and I could not kill it"*; browser-confirmed) |
| `/api/status.source_health` | `total_sources`, `sources_with_data`, `source_counts`, `missing_sources` | `total_sources: 2`, `sources_with_data: 2`, `source_counts: {ktc:500, idpTradeCalc:900}`, `missing_sources: []` — for a board built from 21. `missing_sources` is empty **by construction**: the denominator is whatever the scraper ran, so it can never name a source that failed to run at all | W05-F002 (P2), W23-F008 (P2) |
| `/api/health` | `data_age_hours`, `data_stale` | measures time since the process loaded the file, not since the data was produced | W23-F006 (P2, verified/rescoped) |
| ops email alert on scrape success rate | fires below 50% | can never fire — the payload handed to `_check_scrape_rate` never carries the key, and `/api/status` carries it as a **dict** the `float()` cast rejects | W23-F001 (P2, verified/rescoped; the verifier noted PRIOR-A07-F03 had already named the `float(dict)` half) |

The one page dedicated to source health cannot show the one failure mode the platform has actually
suffered — CLAUDE.md records "IDP Show prod cookie expired and the source went silently stale for
two weeks" — because `idpShow` is not one of the four rows it renders.

**Every honest number is already in the same payload.** `/api/status.served_source_coverage`
carries all 21 sources with real per-source board counts (that is the §1b table), and
`source_health.sources` carries 22 correct per-source `lastFetched` / `ageHours` stamps.
`server.py:4347-4349`'s own comment concedes the point: *"`source_health` above is derived from
the 3-source legacy `sites` list and cannot detect a degraded board."* The fix is a renderer
change, not a data-collection project.

Two smaller truth gaps:

- The same raw file carries **three disagreeing KTC counts**: `sites.playerCount = 500`,
  `siteStats.ktc.count = 704`, rows actually carrying a `ktc` value = **590** (W05-F002).
- `source_failures` permanently reports `KTC_TradeDB` and `KTC_WaiverDB` as *"partial"* — a state
  the docs call a tolerable transient. It is not transient; see §9.

```bash
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/status | .venv/bin/python -c \
 "import json,sys;d=json.load(sys.stdin);sh=d['source_health'];print(sh['total_sources'],sh['source_counts'],sh['missing_sources'],sh['source_runtime']['enabled_sources'],len(d['served_source_coverage']))"
```

Artifacts: `evidence/W05/api-status.json`, `evidence/W05/source-health-page.txt`.

---

## 8. Historical snapshots: what is kept, and what is not

| Artifact | Present? | Contents | Verdict |
|---|---|---|---|
| `CSVs/site_raw/*.csv` | 22 files | current fetch only — **rewritten in place by every scrape** | no history |
| `exports/archive/*.zip` | **129** snapshots, 2026-07-14 → 08-04 | bundles `site_raw/` for **exactly 3 sources**: `ktc`, `ktcSfTep`, `idpTradeCalc`. Player rows carry `_composite` / `_finalAdjusted` / `_rawComposite` and **no** `rankDerivedValue`, `canonicalConsensusRank`, `confidenceBucket` or `sourceRanks` | **the served board is not recorded anywhere** |
| `data/raw/<vendor>/<year>/…` | 22 vendor dirs, 2,487 files | dated per-source snapshots — **frozen in April 2026** (2026-04-03 → 04-20 depending on vendor). No directory at all for `otcffb`, `pfkDynasty`, `fantasyNavigator`, `idpShow`, `fantasyProsFitzmaurice`, `flockFantasySfRookies`. Carries `footballguys_*` and `pff_idp`, neither in the registry | dead archive |
| `data/raw_sources/raw_source_snapshot_*.json` | 30 files, newest `20260420T194828Z` | the raw-ingest scaffold's artifact | **106 days old; no producer exists in the tree** |
| `data/scrape_state/*_last_success` | 31 files | per-source freshness stamps — this is what `_build_source_timestamps` now prefers over CSV mtime | works |
| `data/source_value_history.jsonl` | present, 91 KB | **one** snapshot (2026-08-04, 840 players) and **2 of 21** source keys (`ktcSfTep` 464, `idpTradeCalc` 814) | W03-F012, P2 |
| `data/rank_history.jsonl` | **absent** | — | W03-F011, **Blocked by data** |

Three consequences worth stating plainly:

1. **No backtest of the served board is reproducible.** W04-F009 (verified, **rescoped —
   strengthened**): every "historical" backtest calls `build_api_data_contract(old_payload)`, which
   reads the CSV-backed sources from `CSVs/site_raw/` **as they are today**. Replaying the
   2026-07-14 snapshot produces 1,092 rows voted on by 21 sources, 18 of which have no
   representation in that archive; `pfkDynasty.csv` and `fantasyNavigatorSf.csv` first entered the
   tree on 2026-08-03, three weeks after the snapshot date, and they vote in its replay. The
   verifier called this *"an airtight temporal leak"* and confirmed the archive's
   `_canonicalSiteValues` carries exactly three keys across all 1,074 players. The one honest
   exception is `src/model_registry/board_holdout.py`, whose docstring states outright that the
   forecast claim would need board snapshots this repo does not keep.
2. **The Hill-curve promotion criteria do not recompute.** W04-F006, P2: champion v2's recorded
   holdout criterion 787.84 recomputes to **753.05** today; the champion's drift alone (−34.79) is
   139% of the 25-point promotion margin.
3. **The raw-ingest scaffold is stale and unrefreshable.** W05-F007 (`Deprecated but still
   active`, P2, confirming PRIOR-A25-F10): `/api/scaffold/raw`, `/status` and `/identity` all serve
   `run_id 20260420T194828Z`, `created_at 2026-04-20` — 106 days old — while `/api/scaffold/status`
   reports `mtime: 2026-08-03T22:00:56` (the git-checkout time), so **the one field an operator
   would read as an age reads as "yesterday"**. `warnings: []`. Two of the nine snapshotted
   sources recorded `record_count: 0` with warnings still empty. It names `FOOTBALLGUYS_SF` (563)
   + `FOOTBALLGUYS_IDP` (525) as contributors — a vendor not in the registry, stamp frozen at
   2026-05-24. Grepping the tree for a **writer** of `data/raw_sources/raw_source_snapshot_*.json`
   finds only consumers and a retention pruner. Mitigating: nothing in the frontend consumes
   `/api/scaffold/*`.

```bash
ls exports/archive | wc -l
find data/raw -maxdepth 3 -mindepth 3 -type d -printf '%f\n' | grep -oE '[0-9]{8}T' | sort -u
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/scaffold/status
grep -rn 'raw_source_snapshot' --include='*.py' . | grep -v tests
```

One export-side inconsistency belongs here: `exports/latest/dynasty_full.csv` publishes
`_finalAdjusted` — the raw pre-Hill scraper composite — under the column name `Composite`.
Matching its 1,074 rows against the live contract, 805 match by name and **exactly 1** has an
identical value; median ratio 1.0855, p10 0.956, p90 1.260, and the disagreement is not a constant
rescale so no factor corrects it (W29-F003, P2). Every in-app export agrees with the screen; this
is the archive artifact only.

---

## 9. Non-ranking data feeds

### 9a. KTC crowd trade/waiver DB — ingested on the degraded path only

W05-F005 (`Implemented but disconnected`, P2). `scrape_ktc` has three extraction strategies;
`content = await page.content()` is assigned **only inside Strategy 3**, which is guarded by
`if not name_map:`. The ID-map builder then guards on `if "content" in dir() and content:`. So on
**every run where KTC actually works** (Strategy 1 API intercept or Strategy 2 DOM — which is what
produced today's 500 rows), `content` is unbound, `KTC_ID_TO_NAME` stays empty, and both crowd
endpoints are skipped. The condition is inverted: **the crowd DB can only run when the primary
scrape has failed.**

Downstream: `ktcCrowd` is absent from the contract → `crowd_bid_map_from_contract` returns `{}` →
the "KTC crowd-sourced calibration" factor never appears in a FAAB response, and **is not listed
as missing either** (4 factors, `warnings: []`), while the 15%-weight rival-contention factor *is*
marked missing. The whole downstream chain is built, unit-tested and correct; the failure is one
variable scope in the scraper.

```bash
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/status \
 | .venv/bin/python -c "import json,sys;print(json.load(sys.stdin)['source_health']['source_failures'])"
python3 -c "import json;print('ktcCrowd' in json.load(open('data/dynasty_data_2026-08-04.json')))"
```

### 9b. News providers — 6 registered, 4 producing

Live `/api/news`, re-measured while writing (matches `evidence/W21/api-news.json`):

| Provider | ok | items | Note |
|---|:--:|---:|---|
| `sleeper` | yes | 25 | |
| `espn` | yes | 20 | |
| `cbs` | yes | 25 | |
| `pfk` | yes | 25 | |
| `fantasypros` | **no** | 0 | `HTTPError: HTTP Error 404: Not Found` — has been 404ing on every aggregate for the whole audit window (W21-F005, P2) |
| `espn_player` | **yes** | 0 | permanently zero: it derives targets from `contract.sleeper.players`, a key the scraper never produces (W21-F004, P2) |

`providerRuns` has **zero frontend consumers** — the only occurrence under `frontend/` is the Next
bridge route emitting its own empty one. `/news` renders a "News unavailable" banner only on the
all-six-failed 503. **1 of 6 providers permanently dead renders as a slightly shorter list**, and
`espn_player` reports `ok: true` so it is invisible even to an operator reading the diagnostic.
Per-provider fault isolation itself is correct: one provider raising does not poison the aggregate,
and the all-failed case shortens the cache TTL to 15 s so a retry reaches a recovered upstream.

```bash
curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/news \
 | .venv/bin/python -c "import sys,json;[print(r) for r in json.load(sys.stdin)['providerRuns']]"
grep -rn providerRuns frontend/components frontend/app frontend/lib
```

### 9c. nflverse / nfl_data

`nfl_data_py` is deliberately excluded from `requirements.txt`; **`nflverse_direct` is the live
path and it works** — `fetch_weekly_stats([2025, 2026])` returns 19,421 rows in 0.77 s, and a
missing 2026 surfaces as an absent season rather than a zero (W21-F004 `whatWorks`). Three cache
defects sit on top of it (W26-F007, P2): no last-known-good on TTL expiry, no size bound (590 MB
across 7 entries, largest 357 MB), and three byte-identical copies of the same 61.7 MB file under
three keys. `/api/player/{id}/realized` re-reads and re-parses that 61.7 MB file on **every**
request (W26-F006, P2) — though the route currently returns `unmapped_player` for every player
anyway, per §9b.

### 9d. ROS source set — 5 sources, zero projections

`data/ros/sources/` — freshness is **fine and honestly reported**: `latest.json` was 4.9 h old
against the 2026-08-04 board, all 5 sources `ok`, and `/tools/ros-data-health` renders
"Last rebuilt: 4.9h ago · Overall freshness: fresh" (W17-F004, `Implemented and verified`).

The metadata is not. **Not one ROS source supplies a point projection**: all 1,285 rows across the
five live CSVs have an empty `projection` column (`draftSharksRosSf` 0/939, `fantasyProsRosOverall`
0/389, `fantasyProsRosSf` 0/538, `ffc2qbAdp` 0/200, `fantasyProsRosIdp` 0/219) — yet
`draftSharksRosSf` is registered `is_projection_source: True`, and two of the five are registered
`source_type: 'dynasty_proxy'` with `is_ros: False`, i.e. multi-year dynasty rankings feeding a
rest-of-season product (W17-F012, P2). Retention is also unimplemented:
`data/ros/aggregate/history` is 857 MB / 796 tracked files spanning 98 days against a documented
"rolling 30-day archive" with no prune code anywhere (W17-F013, P2).

### 9e. BDVM projection snapshots — **Blocked by data**

`data/bdvm/` does not exist in this container. See §10.

### 9f. Sharp and intel crawl ledgers — **Blocked by data**

See §10. One data-shape defect is independent of the emptiness and worth recording here: the
intel ledger models `trade` / `waiver` / `free_agent` correctly and indexes on `tx_type`, but the
only movement reader any **sharp** surface uses — `platform_ledger.query_movements` — hardcodes
`m.tx_type='trade'` with no parameter, so sharp adds/drops exist as data and are **Missing as a
surface** (W15-F013, P3). And `asset_movements.counterparty_user_id` is never populated by the
crawler, so "who traded with whom" is structurally unanswerable despite the column, the trigger and
the docs promising it (W16-F010, P3) — no reader today, so no wrong number, but multi-team-trade
pair analysis is impossible without a re-crawl.

---

## 10. Blocked by data vs genuinely broken

Per `AUDIT_PROTOCOL.md`: **Blocked by data** means the code exists, IS called, and returns
empty/degraded because a named input path is absent. It is not a defect. Every entry below was
checked for whether the degradation is *honest* — and every one of them is.

| Subsystem | Exact absent path | What the routes do | Honest? | Finding |
|---|---|---|---|---|
| **BDVM** (4 routes, 3 pages) | `data/bdvm/projections/` — `data/bdvm/` has no entry under `data/` at all | HTTP **200** with `status: "no_projection_snapshot"`, empty `players`/`picks`/`unpriced`, and a message naming the fix. In a real browser (protocol topology): `/rankings` rendered 965 players with **no "Fund gap" column**; `/draft` rendered its RookieBoard with no Fund gap; `/bdvm` rendered an explicit *"No projection snapshot yet"* panel, not a generic error | **yes** — nothing fabricated | W13-F005 |
| **Sharp cohort / Tracker / Roster %** (5 routes, 2 pages) | *no absent file* — `data/intel/ledger.sqlite3` **exists** (319 KB, migrated to platform-v2) with **every sharp table at 0 rows** | HTTP 200 with `status: "cohort_building"`; roster board returns `players: []`, `totalQualifyingPlayers: 0`, `cohortCoveragePct: null`, `sample.rankable: false` + an "insufficient" warning naming the 8-roster minimum. Browser: `SHARP MANAGERS 0 / ELIGIBLE ROSTERS 0 / COHORT REPRESENTED —`, "Sample too small" banner, **0 console errors** | **yes** — three distinct empty states separated end to end (`cohort_building`, `no_eligible_rosters`, "no players match these filters") | W15-F001 |
| **Insider Trading** (7 routes, 1 page) | `data/intel/snapshot_dynasty_main.json` | 5 routes **503** behind `snapshot_ready()`; `GET /api/intel/refresh/status` is deliberately snapshot-independent and 200s with `snapshotGeneratedAt: null`; `POST /api/intel/leads` returns 400 because body validation runs before the gate | **yes** — the 503 body names the league key and the exact remedy | W16-F012 |
| **Rank history / movers** | `data/rank_history.jsonl` | `/api/movers` → `window: 0, historyDepthDays: 0, asOf: null, risers: [], fallers: []`; no row carries `rankHistory`, so the sparkline self-suppresses | **yes** | W03-F011 |
| **FAAB rival intel** | `data/intel/snapshot_dynasty_main.json` | `intel_f` pinned at 1.0, `intelLevel: 'none'`, response note *"Intel snapshot missing — rival intel factor defaulted to 1.0."*, `staleInputs: ['intel']` | **yes** — the best-behaved degradation in the codebase | W11-F015 |
| **playerctx (depth chart / snap share)** | `data/playerctx/` | `/api/playerctx/player` → 404 `no_context` | yes | W21-F009 |

**Two protocol corrections.** `AUDIT_PROTOCOL.md`'s non-findings table says *"`data/intel/` and the
platform ledger DB do not exist in this container"*. Both halves are wrong: `data/intel/` exists and
contains `ledger.sqlite3`, a `.pre-platform-v2-auto.bak`, and an `ffpc/` directory; the ledger holds
all 19 tables and every one is empty except `meta` (3 rows). The 503s are gated on the **per-league
JSON snapshot**, not the DB — which is exactly why Sharp Tracker (reads the ledger directly, no
snapshot gate) answers `200 cohort_building` while Insider Trading (behind the gate) answers 503.
Recorded in W15-F001 and W16-F012.

### Things that are Blocked by data but would still be defective with data

Do not file these as blocked-and-therefore-fine. Each was proven at the function level or against a
locally rebuilt snapshot, out of process:

- **BDVM's "exact league scoring" drops all six reception yardage-band rules** — WR fundamentals
  understated 19.7%, TE 22.0% (W13-F001, **P1**).
- **BDVM roster capitals and the trade scan exclude every draft pick**, omitting 8–52% of a
  rebuilder's capital (W13-F002, **P1**).
- **The BDVM signal layer saturates at 81.5% `STRONG_SELL`** (W13-F003, **P1**).
- **Nothing has ever validated a BDVM number**: `params_v1.json` self-declares as un-backtested
  priors, `src/bdvm/backtest.py` (336 lines) is imported by exactly one file — its own test — and
  no script, route, workflow or timer runs it. The `/bdvm` page discloses the *proxy projection*
  flag well and never discloses that the parameter set is unvalidated (W13-F006, `Scaffolded only`,
  P2, confirming PRIOR-A15-F13).
- **The news→BDVM events writer keys on `currentDraftYear` while every reader keys on
  `nfl_projection_season()`** — they diverge for the whole Sept–Jan window, making the auto-ingest
  a silent no-op that still reports `ok: true` with a non-zero `added` count (W21-F006, P2; proven
  at the function level: reader 2026 / writer 2027 on all four probe dates).
- **`sigmaSource` is 0.0 for all 699 priced players** — but the snapshot is single-source by
  construction, so this run **cannot separate** "the parameter is never read" from "there was
  nothing to disagree with". W13-F016 is explicitly filed as *unresolved pending a two-source
  snapshot* (P3, confidence medium). That is the correct disposition, and it is the model for how
  a blocked-by-data question should be recorded.
- **`rosterQuality` is 22% of the Sharp Score and is structurally 0.0 for every manager**, with the
  weight not renormalized — the reachable ceiling is 78.0 on a number published as 0–100
  (W15-F002, P2, confirmed against PRIOR-A16-F00 with an exact decomposition: manual 68.1 == engine
  68.1).

---

## 11. What works

Stated plainly, because an audit that lists only defects is not an audit.

- **The full ingestion chain, all 21 sources.** Fetcher → CSV → freshness stamp → blend vote,
  traced end to end for every registered key. 19 have a dedicated `scripts/fetch_*.py`; `ktcSfTep`
  and `idpTradeCalc` come from `Dynasty Scraper.py`. Every `_SOURCE_CSV_PATHS` entry resolves to an
  existing file. Every key appears in `sourceRanks` with non-null ranks, from 29 rows
  (`dlfRookieIdp`) to 903 (`idpTradeCalc`). No registered source is dead and no fetched CSV is
  unread — the two `draftSharksRos*` files feed `src/ros/sources/draftsharks_ros.py`, and `ktc.csv`
  is the deliberately non-voting display/arbitrage source (W05-F010, `Implemented and verified`).

  ```bash
  .venv/bin/python scripts/verify_live_source_coverage.py http://127.0.0.1:8000 \
    && .venv/bin/python scripts/watchdog_freshness.py \
    && .venv/bin/python scripts/watchdog_contract_coverage.py
  ```

- **Coverage accounting is exact.** `ktc 590 = 464 + 126` and `idpTradeCalc 898 = 814 + 84`, with
  KTC name-matching at **464/464** on non-pick rows (W05-F011).
- **Identity joins are strong where it matters.** 17 of 21 sources join above 92%; the four low
  ones are pool-construction, not identity — 455 CSV keys have no board row under any spelling,
  confirmed by spot check (W06-F014, `Implemented and verified`). `POSITION_ALIASES` covers every
  position token any live source emits with no unmapped values.
- **The row-floor mechanism is correct where it exists.** Dropping `dlfSf` or `yahooBoone` produces
  a hard `source_missing` error and flips the contract to `invalid`. The config file allows tuning
  without a code change.
- **The file-missing ingest path is honest**: `{'error':'file_not_found'}`, a logged warning, and a
  degraded contract.
- **The per-source email alert path is real** and correctly per-source, fed by the 22-entry
  `source_health.sources` block through the daily sweep, with a documented soft/soft-escalate
  policy for `idpShow`.
- **The deploy-time gate genuinely works** and would fail a deploy that served a degraded board.
- **Registry lockstep is protected** — `tests/api/test_source_registry_parity.py` parses the
  frontend JS and diffs it against the Python registry. (The *second* documented mechanism,
  `GET /api/rankings/sources` as a "runtime check", has no runtime consumer — W01-F011, P3.)
- **Every Blocked-by-data subsystem degrades honestly.** Six subsystems, six honest empty states,
  zero fabricated numbers — see the §10 table.
- **The BDVM speculation clamp is real**, verified against the live news feed: 20 events mapped
  from 50 headlines, 13 with non-empty impact, and the **only** channel present across all 13 was
  `sigma_mult`, min 1.0376. A headline can widen uncertainty and can never move a mean or narrow σ
  (W21-F002, `Implemented and verified`).
- **BDVM market isolation is structurally real**: nothing in `src/bdvm/` reads a market value
  before the market layer, and only value-signal sources are read (W13-F008); the engine reproduces
  the frozen Appendix-C reference exactly (W13-F007).
- **`cohort_members` is genuinely the single sharp-membership definition** — the five documented
  qualification gates that *can* fire were verified against a synthetic ledger (W15-F015), and both
  imperatively registered sharp routes are present in the live app (W15-F014).
- **The intel ledger's counting rules are correct**: multi-team trades, refetches, failed
  transactions, window overlap and waiver-vs-trade separation all handled without double counting
  (W16-F002); Sharp Tracker and Insider Trading are genuinely separate products (W16-F001).
- **ROS aggregate freshness is fine and honestly surfaced** — 4.9 h old, all 5 sources ok,
  `/tools/ros-data-health` says so (W17-F004).

---

## 12. Repair order

Ranked by "how much wrong belief does this create, per unit of work".

| # | Repair | Findings | Size |
|---|---|---|---|
| 1 | **Drive `/tools/source-health` and `/api/status.source_health` from the registry.** `served_source_coverage` (21, correct) + `source_health.sources` (22, correct) are already in the same payload; keep `enabled_sources` as a scraper-stage overlay. Normalize casing through one helper. | W05-F001, W05-F002, W23-F007, W23-F008 | S |
| 2 | **Add row floors for the nine unfloored sources** at ~80% of the §1b counts, plus a registry-completeness test that fails when a registered source has no floor. `ktcSfTep` first. | W05-F004 | S |
| 3 | **Make the schema probe universal**: assert ≥1 name-alias column and ≥1 value-or-rank-alias column for every source; emit `source_empty:{key}` when a CSV parses cleanly to zero usable rows. | W05-F003 | M |
| 4 | **Stamp `pickAnchors` under `ktcSfTep`** (identical to `ktc` on all 36 shared rows) so slot picks get two markets. Then either wire the `dlfRookieSf` synthetic pick stamps into `sourceRanks` or stop writing them. Coordinate with pick tethering (Phase 5.2b overwrites current-year slots — measure 2027/2028 separately). | W05-F006 | M |
| 5 | **Collapse the two freshness threshold tables to one** (`config/source_staleness.json` via `resolve_threshold`) and render `sourceTimestamps` on the fixed source-health page. | W05-F009 | M |
| 6 | **Hoist `content = await page.content()`** out of the Strategy-3 block (or build `KTC_ID_TO_NAME` from the intercepted API payload, which carries `playerID` + `playerName`), and have the FAAB recommender emit the crowd factor with `missing: true` when the map is empty. | W05-F005, W11-F014 | M |
| 7 | **Fix the freshness/uptime conflation and the dead scrape-rate alert**: derive `data_age` from the snapshot's own scrape stamp, and pass `_scrape_success_rate_24h().get('rate')` (a float) to the ops sweep. | W23-F006, W23-F001 | S |
| 8 | **Bind `/news` to `providerRuns`** (`ok:false` OR `ok:true && count:0`) and repoint or disable the FantasyPros feed URL. | W21-F005 | XS |
| 9 | **Decide the raw-ingest scaffold**: restore a producer wired into `scheduled-refresh.yml`, or remove the three routes and the two scripts that depend on them. Either way, report `ageHours` from the snapshot's own `created_at`, never the file mtime. | W05-F007 | M |
| 10 | **Either run the strict coverage gate every 6 h** (add a checkout, or ship per-source expectations in `/api/status` so a dependency-free checker can be strict) **or correct the docstring** and raise `MIN_SOURCES` toward the registry count. | W05-F008 | S |
| 11 | **Persist board snapshots** (`playersArray` with `rankDerivedValue`) alongside the raw export, so a backtest can replay a board that was actually served instead of counterfactually re-blending today's CSVs into a weeks-old payload. | W04-F009, W04-F006, W03-F012 | L |

Items 1–3 and 7–8 are the reporting layer. Nothing on the board is wrong today because of them —
but nothing would tell you when it becomes wrong, which is the point of having them.
