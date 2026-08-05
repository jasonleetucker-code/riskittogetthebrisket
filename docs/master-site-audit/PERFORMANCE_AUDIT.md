# Performance Audit

Deliverable section 12 of the master site audit. Sources: the W26 shard
(`evidence/registry/W26.jsonl`, 19 findings), `evidence/route-probe.json`,
`evidence/page-probe.json`, `evidence/W26/page-ux-probe.json`,
`evidence/W26/pending-requests.json`, `evidence/perf/api-data-payload-sizes.txt`,
plus payload findings from W00, W07, W10, W13, W15 and W25.

---

## Measurement caveats — read before quoting a number

| Evidence file | Runs per data point | What it is |
|---|---|---|
| `evidence/route-probe.json` | **1** (per route × per auth mode) | 66 GET routes, status / wall ms / bytes |
| `evidence/page-probe.json` | **1** (per page × per auth mode) | 41 Next pages in Chromium, nav timing + console |
| `evidence/W26/page-ux-probe.json` | **1** (per page × per viewport) | 14 pages × desktop/mobile, PerformanceResourceTiming totals |
| `evidence/W26/repeat-latency-auth.txt` | **5** | 9 routes, 5 sequential authenticated calls each |
| `evidence/perf/api-data-payload-sizes.txt`, `evidence/W26/data-view-sizes.txt` | 2 independent captures | `/api/data` byte sizes, agreeing to <1 part in 8,000 |

**Everything is single-run except the nine routes in `repeat-latency-auth.txt`.**
Single-run latency on a shared container is a coarse instrument: treat the <10 ms
band as "fast", not as a benchmark. The **payload sizes are exact** — they are byte
counts, not timings, and they reproduce.

Two structural cautions:

- `page-probe.json`'s `settleMs` is **not a page-load metric.** Values cluster at
  ~10.0–10.7 s and ~21.0–21.2 s across unrelated pages — a network-idle wait hitting
  a probe timeout. The 21 s tier is exactly the set of pages with unresolvable
  `sleepercdn.com` avatar requests (`/rankings`, `/rosters`, `/finder`, `/trades`,
  `/league/*`), which the audit protocol pre-declares as a container-egress artifact.
  Use `navMs`, `fcp` and `load` instead.
- All page numbers were taken through the protocol's request-interception topology.
  `page-probe-direct-next-INVALID.json` and `page-probe-via-proxy-INVALID.json` are
  retained but void.

Re-run the API sizes:

```bash
for v in '' '?view=app' '?view=array' '?view=compact' '?view=startup'; do
  printf '%-16s raw=%s\n' "${v:-full}" \
    $(curl -s -b /tmp/audit-cookies.txt -o /dev/null -w '%{size_download}' \
      "http://127.0.0.1:8000/api/data$v")
done
```

---

## Headline

**The page layer is fast and the API layer is mostly fast. The problem is bytes and
cold paths, not code speed.** Median authenticated route latency is **6 ms** across
66 GET routes; median page DOM-ready is **83 ms**; every Next bundle is under its own
CI budget. Against that, `/api/data` ships **11,953,535 bytes** raw / **1,176,182**
gzipped, the view routed to mobile devices is **13.0% larger** than the desktop view,
and two routes take **48 s** and **27 s** on a cold cache doing work their own callers
discard.

And one result that outranks all of the above: **the site's largest payload
optimisation is also the source of its worst value inconsistency.** The
`?view=delta` override POST is 67% smaller than the full contract and is
byte-faithful to it — but the frontend fires it with `tep_multiplier=1.15` on every
session, which makes the board it returns disagree with `GET /api/data` on 135 values
and 627 ranks (W07-F001, P0, verifier verdict *rescoped*, severity held). See
[Optimisations that serve a different answer](#optimisations-that-serve-a-different-answer).

---

## 1. Route latency and payload

66 GET probes (65 distinct paths — `/api/health` appears twice) run authenticated and
anonymous; 34 of the 100 live operations are non-GET and were not latency-probed.
Single run each.

### 1.1 Distribution (authenticated)

| Band | Routes |
|---|---|
| < 10 ms | 43 |
| 10–100 ms | 12 |
| 100 ms – 1 s | 4 |
| 1–10 s | 5 |
| > 10 s | 2 |

min 3 ms · median 6 ms · p90 1,515 ms · max 47,994 ms.

### 1.2 The slow tail — every route over 100 ms

| Route | auth ms | bytes | What is slow |
|---|---:|---:|---|
| `/api/bdvm/roster` | 47,994 | 310 | nflverse downloads discarded unread (W26-F004) |
| `/api/league-comparison` | 26,577 | 48,464 | cold 7-day disk cache miss; loads every nflverse season |
| `/api/draft-capital` (anon) | 13,188 | 15,989 | openpyxl + KTC scrape + up to 6 Sleeper calls (W10-F008, W00-F001) |
| `/api/valuation/league-adjusted` | 7,267 | 48,555 | cold league-scarcity build |
| `/api/player/{id}/realized` | 5,362 | 85 | re-parses a 61.7 MB JSON per request (W26-F006) |
| `/api/public/league/overview` | 1,569 | 15,229 | |
| `/api/sleeper/draft/picks` | 1,525 | 155 | outbound Sleeper call |
| `/api/public/league/overview.csv` | 1,515 | 192 | |
| `/api/data` | 574 | 11,953,535 | serialising 11.95 MB |
| `/api/ros/health` | 293 | 2,640 | |
| `/api/scaffold/identity` | 177 | 2,522,120 | |
| `/api/scaffold/raw` | 153 | 2,767,269 | |
| `/api/dynasty-data` | 95 | 11,953,535 | same payload, warm |
| `/api/public/league` | 94 | 2,081,957 | |

Anonymous-vs-authenticated latency differences worth naming: `/api/news` 1,236 ms anon
→ 10 ms auth, `/api/leagues` 934 ms anon → 5 ms auth, `/api/public/league/overview`
1,857 → 1,569 ms. These are first-call cache fills, not an auth cost — the anon probe
ran first.

### 1.3 The five largest responses

| Route | bytes | share of all 48 200-responses (32,012,380 b) |
|---|---:|---:|
| `/api/data` | 11,953,535 | 37.3% |
| `/api/dynasty-data` | 11,953,535 | 37.3% |
| `/api/scaffold/raw` | 2,767,269 | 8.6% |
| `/api/scaffold/identity` | 2,522,120 | 7.9% |
| `/api/public/league` | 2,081,957 | 6.5% |

Five routes are **97.7%** of all bytes the API can emit (31,278,416 of 32,012,380).
Everything else is noise.

### 1.4 Repeat-measured routes (5 runs each)

From `evidence/W26/repeat-latency-auth.txt` — the only repeats in the corpus.

| Route | run 1 | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|---:|
| `/api/bdvm/roster` | 4.4 ms | 4.1 | 4.5 | 4.0 | 5.0 |
| `/api/bdvm/values` | 4.3 ms | 4.0 | 3.9 | 3.9 | 3.9 |
| `/api/league-comparison` | 6.5 ms | 5.8 | 7.7 | 6.7 | 6.8 |
| `/api/draft-capital` | **2,735 ms** | 5.1 | 5.5 | 5.7 | 6.8 |
| `/api/valuation/league-adjusted` | 77 ms | 62 | 68 | 60 | 62 |
| `/api/player/4046/realized` | **5,179 ms** | **1,136** | **954** | **915** | **840** |
| `/api/terminal` | 133 ms | 138 | 158 | 25 | 31 |
| `/api/data?view=app` | 9.1 ms | 7.6 | 8.0 | 7.0 | 6.8 |
| `/api/public/league` | 6.0 ms | 5.5 | 4.6 | 4.7 | 4.8 |

Two readings matter:

- **Caching works where it exists.** `/api/bdvm/roster` goes 47,994 ms → 4 ms;
  `/api/league-comparison` 26,577 → 6 ms; `/api/draft-capital` 2,735 → 5 ms. These
  are one-time costs, not steady-state costs.
- **`/api/player/{id}/realized` never gets fast.** It settles at **~0.84 s**, not
  milliseconds, because nothing memoises the parse (W26-F006). This is the only
  route in the corpus with a slow *steady state*.

Re-run: `for i in 1 2 3 4 5; do curl -s -o /dev/null -b /tmp/audit-cookies.txt -w '%{time_total}\n' 'http://127.0.0.1:8000/api/player/4046/realized'; done`

---

## 2. Page timings

### 2.1 All 41 pages — navigation (single run, authenticated)

Median `navMs` **83 ms**, max **609 ms** (`/tools/source-health`), min 39 ms.
Anonymous: median 76 ms, max 168 ms. 41/41 pages return 200; 38 render an `<h1>`
(W00-F009, *Implemented and verified*). Three pages render no `<h1>`:
`/league/rivalry/[pair]`, `/league/franchise/[owner]`,
`/league/articles/[season]/[week]/[matchupId]/[mode]`.

Largest server-rendered HTML: `/trades` 857,729 b, `/rankings` 593,768 b,
`/finder` 583,490 b, `/rankings/[position]` 248,521 b.

### 2.2 14 pages × 2 viewports — resource timing

`fcp` / `load` in ms; `transfer` = compressed wire bytes; `decoded` = bytes parsed.

| Page | vp | nav | fcp | load | reqs | transfer | decoded | API calls |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `/draft` | mobile | 134 | 100 | 156 | 58 | **2,312,148** | **24,571,176** | 9 |
| `/draft` | desktop | 191 | 156 | 228 | 70 | **2,216,644** | **23,849,422** | 11 |
| `/` | mobile | 134 | 144 | 291 | 55 | 1,484,662 | 12,538,194 | 10 |
| `/` | desktop | 185 | 272 | 420 | 71 | 1,388,936 | 11,806,116 | 10 |
| `/rankings` | mobile | 127 | 208 | 326 | 65 | 1,135,662 | 12,553,077 | 9 |
| `/rankings` | desktop | 218 | 304 | 492 | 71 | 1,040,158 | 11,767,159 | 9 |
| `/trade` | mobile | 56 | 96 | 172 | 59 | 1,135,662 | 13,064,108 | 9 |
| `/trade` | desktop | 158 | 212 | 363 | 67 | 1,040,158 | 12,329,134 | 11 |
| `/news` | mobile | 60 | 112 | 152 | 57 | 1,135,662 | 12,533,315 | 7 |
| `/news` | desktop | 109 | 144 | 209 | 64 | 1,040,158 | 11,766,371 | 8 |
| `/settings` | mobile | 54 | 132 | 170 | 58 | 1,135,662 | 12,505,629 | 6 |
| `/bdvm` | mobile | 89 | 96 | 151 | 60 | 1,135,662 | 12,488,678 | 7 |
| `/waivers` | mobile | 120 | 116 | 190 | 59 | 1,135,662 | 12,578,490 | 7 |
| `/rosters` | mobile | 63 | 68 | 156 | 66 | 1,135,662 | 12,515,078 | 7 |
| `/finder` | mobile | 151 | 152 | 161 | 71 | 1,135,662 | 12,577,077 | 9 |
| `/league-comparison` | mobile | 46 | 76 | 119 | 59 | 1,135,662 | 12,560,784 | 8 |
| `/market/sharp-roster-percentage` | mobile | 58 | 92 | 124 | 55 | 1,135,662 | 12,481,120 | 8 |
| `/terminal` (**a Next 404**) | mobile | 134 | 132 | 178 | 58 | 1,135,662 | 12,481,320 | 7 |
| `/league` | desktop | 170 | 348 | 271 | 66 | **793** | 1,422,681 | 4 |
| `/league` | mobile | 195 | 152 | 276 | 60 | **793** | 1,359,375 | 4 |

Median FCP: desktop 150 ms, mobile 114 ms. Median `load`: desktop 222 ms,
mobile 165 ms.

Three facts fall straight out of this table:

1. **Every private page transfers the same ~1.04 MB / ~1.14 MB.** The wire cost is
   flat across `/rankings`, `/news`, `/settings`, `/bdvm`, `/waivers` and a **404
   page**, because `AppShell` fetches the player contract unconditionally
   (W26-F002).
2. **`/league` is the control.** It is exempt from the shell fetch — for a *security*
   reason, not a performance one — and transfers **793 bytes**. That is 0.07% of what
   every other page transfers. The exemption proves the fetch is optional.
3. **`/draft` costs ~2.1× every other page** in both transferred and decoded bytes
   (W26-F003).

Re-run: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers .venv/bin/python docs/master-site-audit/evidence/W26/w26_probe.py /tmp/out.json`

---

## 3. Payload sizes

### 3.1 `/api/data` by view

Measured 2026-08-04 (`evidence/W26/data-view-sizes.txt`; independently corroborated
by `evidence/perf/api-data-payload-sizes.txt`).

| View | raw bytes | gzipped | gzip ratio | vs full |
|---|---:|---:|---:|---:|
| (none / full) | **11,953,535** | **1,176,182** | 9.84% | — |
| `?view=compact` | **7,363,760** | 764,715 | 10.38% | −38.4% |
| `?view=array` | 6,514,536 | 669,214 | 10.27% | −45.5% |
| `?view=app` | **5,818,304** | 576,580 | 9.91% | −51.3% |
| `?view=startup` | 5,817,724 | 576,383 | 9.90% | −51.3% |
| `?view=delta` | 11,953,535 | — | — | **0%** — the parameter is silently ignored (W25-F007) |

Re-measured on today's stack (2026-08-05): full 11,954,874 · compact 7,365,099 ·
array 6,515,205 · app 5,818,973 · startup 5,818,393. The 1,339-byte drift is
timestamp churn; the ordering is identical.

### 3.2 `POST /api/rankings/overrides?view=delta`

| Body | raw bytes | gzipped |
|---|---:|---:|
| `{"tep_multiplier":1.15}` (what the app actually sends) | 3,739,098 | 349,679 |
| `{"sourceOverrides":{}}` | 3,918,195 | 372,690 |

Re-measured today: 3,918,187 raw / 372,694 gzipped for the second body — stable.

### 3.3 The compact-view inversion — **proven**

`?view=compact` is the view `frontend/lib/device-profile.js` routes phones and any
device reporting `navigator.deviceMemory <= 4` to. It is **849,224 bytes (+13.04%)
larger than `?view=array`**, the view desktop asks for, and 1,545,456 bytes (+26.6%)
larger than `?view=app`.

Byte-accounted mechanism (`evidence/W26/compact-vs-array-bytes.json`):

| | `playersArray` | legacy `players` dict | fields/row | total served |
|---|---:|---:|---:|---:|
| `array` | 6,132,969 | *(absent)* | 55 | 6,514,536 |
| `compact` | 3,659,280 | **3,336,826** | 41 | **7,363,760** |
| `app` | *(absent)* | 5,436,740 | — | 5,818,304 |

The per-row pruning is real and correct — 55 fields → 41, `playersArray` 6.13 MB →
3.66 MB. `compact` then also ships the legacy `players` dict, so the same 1,092 rows
are encoded twice, which more than cancels the saving. `array` deletes that dict;
`compact` does not.

Confirmed end-to-end in a browser: the same `/rankings` board, 230 rows, at 1500 px
transfers 1,040,158 b / decodes 11,767,159 b; at 390 px it transfers **1,135,662 b**
(+95,504) and decodes **12,553,077 b** (+785,918). **Mobile pays more than desktop
for identical output.**

**W26-F001, P1, verifier verdict `upheld` after an independent re-derivation.** The
verifier re-measured today's stack (compact 7,365,099 > array 6,515,205, +849,894 b,
within the finding's 1,024 b tolerance), re-derived the mechanism, and confirmed a
390 px browser genuinely issues `?view=compact`. The one correction the verifier made
is a category one: `playersAffected: 1092` means "rows double-encoded", **not**
"players whose value is wrong" — no value is affected by this finding.

Re-run: the `for v in ...` loop in §Measurement caveats, plus
`evidence/W26/compact-vs-array-shape.txt`.

### 3.4 Documented sizes are ~3× low, and the wrong figure is load-bearing

| Claim | Source | Measured | Ratio |
|---|---|---|---|
| full contract "~4 MB uncompressed" | `CLAUDE.md`, Rankings Override Payload Size Optimization | 11,953,535 b | **2.99×** |
| delta "~1.25 MB uncompressed" | same | 3,918,195 b | **3.13×** |
| delta "~100 KB over the wire" | same | 372,690 b | **3.73×** |
| compact "~90% byte reduction" | `server.py:3126-3128`, `frontend/app/api/dynasty-data/route.js:45`, `src/api/compact_view.py:3-5` | 38.4% | — |
| relative claim "delta ~70% smaller" | `CLAUDE.md` | 66.8% smaller | **holds** |

(W00-F003, W07-F005, W25-F002, W26-F019 — four workstreams independently measured the
same gap.)

The "~90%" figure is not harmless documentation drift: **it is the stated
justification for routing mobile devices to `?view=compact`.** A reader of the code
sees "~90% smaller", concludes the mobile path is optimal, and never checks. The
test that supposedly pins delta size (`tests/api/test_source_overrides.py:608-636`)
asserts `delta_bytes < 55_000` against a fixture ~71× smaller than production, so no
CI gate is coupled to the real number.

### 3.5 What is inside the 11.95 MB

`evidence/W26/full-contract-key-sizes.txt`:

| Key | approx bytes | share |
|---|---:|---:|
| `playersArray` | 6,672,883 | 55.8% |
| `players` (legacy dict — the same 1,092 rows again) | 5,913,738 | 49.5% |
| `sleeper` | 371,174 | 3.1% |
| `settings` | 11,081 | 0.09% |
| `methodology` | 9,041 | 0.08% |
| everything else (9 keys) | ~18,600 | 0.16% |

The full contract carries **two complete encodings of the same 1,092 players**.
`?view=array` already proves the dict-free shape renders.

Inside the delta, **2.20 MB of 3.74 MB (59%) is `sourceRankMeta`**, shipped for all
1,092 rows on every request and read only by the per-row source-audit panel, one row
at a time, on demand (W07-F005).

---

## 4. Caching inventory

Every cache the audit identified, with the four properties the brief asks for.
Code-read plus live header check; **no concurrency load test was run**, so the
stampede column is a code-structure claim, not a measured one.

| Cache | Key | Invalidation | Stampede protection | Last-known-good |
|---|---|---|---|---|
| `_OVERLAY_RESPONSE_CACHE` (`server.py:358`) | (kind, leagueKey, loadedLeague, view, sleeper_matches) + freshness stamp inside the value | contract regeneration | **per-key `asyncio.Lock`, re-check inside** | n/a |
| `_OVERRIDES_RESPONSE_CACHE` (`server.py:378`) | (body hash, view, leagueKey, sleeper_matches); refuses to cache the `leagueAdjusted` path at all | contract regeneration | **per-key `asyncio.Lock`, re-check inside** | n/a |
| `_DRAFT_CAPITAL_CACHE` (`server.py:6899`) | league key; TTL 300 s | TTL only | **per-league `asyncio.Lock` + post-wait re-check** | no |
| `_heavy_section_cache` (`server.py:8754`) | section key | TTL | **yes — waiters block on the loop, not in the threadpool** | n/a |
| public-league cache | league | TTL + background refresh | **yes, with stale-while-revalidate, a suppression flag and hit/miss/stale counters** | **yes** |
| `sleeper_overlay._BUILD_LOCKS` | per-key | — | **yes** (docstring: "before these locks concurrent expirees each launched their own storm") | — |
| `_ktc_cache` (`server.py:6893`) | none (single slot); 6 h TTL | TTL | none | **failures never memoised — W26-F008 / W10-F008** |
| openpyxl workbook cache | (path, mtime_ns, size) | file change | — | n/a |
| `bdvm_api._values_cache` | (id(contract), generatedAt, leagueKey, paramSetId, snapshotPath, surplusMode, currentWeek, day, eventsFingerprint); LRU max 4 | content + events-file fingerprint | **no** — lock released across `run_valuation` | n/a |
| `bdvm_api._context_cache` / `_schedule_cache` | season | process lifetime | **no** — `_aux_lock` released before the fetch | n/a |
| `bdvm_api` actuals | per UTC day | day rollover | — | **yes, inverted correctly: fetch failures are returned but never memoised** |
| `gameplan._BUNDLE_CACHE` | league_key + source stamp (not a clock) | source stamp change | **`_CACHE_LOCK` covers only the dict lookup**, not the ~1.35 s solve | n/a |
| `league_comparison` disk cache | league IDs + scoring hashes + seasons; 7-day TTL | TTL | **none at all** | no |
| `src/nfl_data/cache.py` (disk) | caller's argument list | hard TTL | none | **no — hard cliff to `[]`** |
| `_LEAGUE_CONTEXT_CACHE` (`data_contract.py:6143`) | **none — a single global slot**; 1 h TTL | TTL | none (read-before-write, fetch outside any lock) | **yes** — returns a fallback dict flagged `fetched_from_sleeper: False` |
| `useDynastyData` module cache (client) | request shape; 30 s TTL + in-flight dedupe | TTL | **yes — in-flight dedupe** | n/a |
| `PlayerPopup._realizedCache` (client) | sleeperId; 30 min TTL | TTL | — | **negative caching on failure** |
| `useTerminal` (client) | includes `valuationMode` | — | — | n/a |
| `src/sharp/*` | **none** — only two `lru_cache`d JSON config loaders | — | — | — |

### 4.1 HTTP cache headers — verified live today

```bash
for r in /api/data /api/terminal /api/news /api/draft-capital /api/league-comparison \
         /api/bdvm/values /api/valuation/league-adjusted /api/public/league; do
  echo "-- $r"; curl -s -D- -o /dev/null -b /tmp/audit-cookies.txt \
    "http://127.0.0.1:8000$r" | grep -i '^cache-control\|^etag'
done
```

| Route | `Cache-Control` | `ETag` |
|---|---|---|
| `/api/data` | `private, max-age=30, stale-while-revalidate=300` | **yes** |
| `/api/terminal` | `private, max-age=30, stale-while-revalidate=120` | no |
| `/api/news` | `public, max-age=60, stale-while-revalidate=180` | no |
| `/api/draft-capital` | `private, max-age=60, stale-while-revalidate=300` | no |
| `/api/league-comparison` | `private, max-age=300, stale-while-revalidate=3600` | no |
| `/api/public/league` | `public, max-age=60, stale-while-revalidate=300` | no |
| `/api/bdvm/values` | **none** | **none** |
| `/api/bdvm/roster` | **none** | **none** |
| `/api/bdvm/trades` | **none** | **none** |
| `/api/valuation/league-adjusted` | **none** | **none** |

`/api/data`'s conditional GET works and is free: re-verified today —
`If-None-Match` → **304 in 2.8 ms, 0 bytes**. The four routes with no policy include a
48,555-byte league-scoped payload that costs 7,267 ms to build cold (W26-F009).

---

## 5. Can any cache serve a value that disagrees with an uncached read?

This is the question the brief singles out, so it gets its own answer per cache.

| Cache | Can it disagree? | Evidence |
|---|---|---|
| `_LEAGUE_CONTEXT_CACHE` | **Yes — structurally.** One global slot, no league dimension; `_resolve_league_context()` takes no league argument and resolves the *default* league's id. Any second league reads the default league's `roster_count` and `bonus_rec_te`. | W26-F018 (P3, unverified) |
| `bdvm_api._values_cache` | **Theoretically.** `id(contract)` is a reusable CPython address, but `generatedAt` co-keys it, so a collision additionally requires an identical scrape. Risk much lower than a prior audit implied; the `id()` term does no work `generatedAt` isn't doing better. | W13-F017 (P3) |
| `src/nfl_data/cache.py` | **No — it fails the other way.** Hard TTL with no stale tier: at TTL+1 s it returns `None` and every ingest wrapper returns `[]`. Surfaces go from full data to *no* data in one step, with a `reason: "no_stats_available"` 200. Honest, but a cliff. | W26-F007 (P2) |
| `_ktc_cache` | **No** — it caches only successes, so it never serves a wrong value. It instead re-attempts a failing 15 s scrape forever. | W26-F008, W10-F008 |
| `_OVERRIDES_` / `_OVERLAY_RESPONSE_CACHE` | **No.** Both key on leagueKey *and* the loaded league *and* the sleeper-match flag; `_OVERRIDES_` explicitly refuses to cache the `leagueAdjusted` path rather than risk it. | W26-F018 `whatWorks` |
| `_DRAFT_CAPITAL_CACHE`, `gameplan._BUNDLE_CACHE` | **No.** Keyed on league key; gameplan additionally on a source stamp rather than a clock. | — |
| `useTerminal` (client) | **No** — it keys on `valuationMode`. A cache without that key would serve the stale market payload for the full TTL after a lens switch, which looks exactly like a broken toggle; the code gets this right. | `CLAUDE.md`, corroborated by W26 |

**On `_LEAGUE_CONTEXT_CACHE`, a cross-finding correction.** W26-F018 calls the impact
"latent today, because both live leagues share `scoring_profile
superflex_tep15_ppr1`". W18-F001 (P1) measured that the shared label is *itself* the
defect: the two leagues' host scoring disagrees on 35 of 48 shared keys, **including
`bonus_rec_te` 0.0 vs 0.5** — one of exactly two fields this cache holds. So the
premise for calling it latent does not hold; what makes it currently unobservable is
a *different* defect masking it. **Repairing W18-F001 without also keying this cache
would give `dynasty_new` its own board computed with `dynasty_main`'s TE bonus and
team count.** Sequence the two fixes together.

---

## 6. N+1s, waterfalls and blocking external calls

### 6.1 Work discarded unread — the 48-second no-op

`GET /api/bdvm/roster` computes `snapshot = latest_snapshot_path(season)` at
`bdvm_api.py:177`, gets `None`, and **then** calls `_context_for(season)` and
`_schedule_for(season)` before `run_valuation` — which returns
`no_projection_snapshot` at `service.py:305`, before it reads either value
(first used at lines 338/453 and 622). Every byte fetched is thrown away.

- Route probe: **47,994 ms for a 310-byte response** — the cold cost of downloading
  the nflverse id map (24.7 MB), six seasons of weekly stats (357.4 MB) and six
  seasons of snap counts (51.4 MB), 433 MB total.
- Re-run in a fresh process against an **already-warm** disk cache, the same two
  calls still cost **8.69 s** (schedule 1.27 s, context 7.41 s, 23,934 context
  players built and discarded) — `evidence/W26/bdvm-cold-path-timing.txt`.
- `schedule.py` retries a second URL with a 60 s timeout on failure, so the schedule
  leg alone can block **120 s**.
- Siblings `/api/bdvm/values` (6 ms) and `/api/bdvm/trades` (5 ms) look fast in the
  probe **only because `/api/bdvm/roster` sorts first alphabetically and had already
  paid**.

W26-F004, P1, confidence high, **not adversarially verified**. Repair is three lines:
if `snapshot is None`, pass `context={}` / `schedule_weeks=None` straight through.

Re-run: the one-liner in `W26-F004.reproduction.command`.

### 6.2 A linear scan of 19,421 rows, per request, forever

`GET /api/player/{id}/realized` calls `fetch_weekly_stats([2025, 2026])` per request.
That resolves to a **disk-only** TTL cache — `cache.get()` does
`json.loads(path.read_text())` with no in-process layer — so every call re-reads and
re-parses **61,706,838 bytes** and materialises 19,421 dict rows, which the handler
then filters with a Python list comprehension to find one GSIS id.

Measured in-process: first fetch 0.762 s, immediately-repeated fetch **0.745 s** —
no memoisation at any level. Route steady state ~0.84 s. A user opening 20 player
popups costs ~16 s of server CPU and ~1.2 GB of JSON parsing. (W26-F006, P2.)

This is the audit's only true **N+1 on the request path**: the index is rebuilt per
player instead of once per process.

### 6.3 `/draft` — a fetch waterfall and a near-duplicate

From `evidence/W26/pending-requests.json` (`/draft`, 73 requests):

| Request | start | end | dur |
|---|---:|---:|---:|
| `POST /api/rankings/overrides?view=delta` | 341 ms | 1,277 | 936 |
| `GET /api/dynasty-data?view=array` | 349 | 855 | 506 |
| `GET /api/data` | 632 | 1,173 | 541 |
| `GET /api/data?leagueKey=dynasty_main` | **1,404** | 1,751 | 347 |

The league-scoped contract fetch does not start until 1,404 ms — it waits on
`selectedLeagueKey` resolving. The bare `/api/data` is the same call site before the
key resolves; it is superseded and never lands.

Desktop `/draft` also issues **both** `/api/draft-capital` and
`/api/draft-capital?leagueKey=dynasty_main`. The probe's `apiDuplicates` field reports
zero duplicates across all 28 page/viewport combinations because it keys on the exact
URL — this pair is a near-duplicate it cannot see.

The mount-time `/api/data` call site (`draft/page.jsx:3932-3937`) passes
`cache: "no-store"` and consumes exactly one field: `data.sleeper.teams` — **46,792
of 11,953,535 bytes, 0.39%**, for 12 team names. The backend already serves
`etag` + `private, max-age=30` on that route, so `no-store` deliberately defeats a
working 304 path.

**W26-F003, P1, verifier verdict `rescoped`, severity held.** Three corrections to
the author's original claim, all reported here as the verified position:

- The author wrote "all three `/api/data` call sites consume only `sleeper.teams`".
  **Wrong.** Call site 2 (`fetchSyncPreview`, `page.jsx:4201-4224`) consumes
  `data.playersArray` — 6,673,553 bytes and the entire point of that fetch. Its waste
  is the duplicated legacy `players` dict (5,914,408 b), not 99.6% of the payload.
  **Two** of three call sites consume only teams.
- The author wrote "three separate call sites" *per page load*. Measured: **exactly
  one** completed `/api/data` response per load. Call site 2 is click-gated ("Sync
  rookies"); call site 3 is gated on post-sync state and uses `cache: "force-cache"`.
- `playersAffected: 1092` recounted to **0** — this is payload weight, not a value
  defect.

What survives and is why P1 held: **1.18 MB gzipped / ~11.95 MB parsed, on mount, on
the app's most time-critical page, to read 12 team names, with the backend's own ETag
deliberately bypassed.**

Measurement trap the verifier hit and documented: Chrome evicts response bodies over
its buffer, so `resp.body()` throws "Request content was evicted" and silently
under-reports by 11.9 MB. **Read `content-length` from the response headers.**

### 6.4 The unconditional shell fetch

`AppShell.jsx:33` declares exactly one exemption from the private data fetch —
`PUBLIC_ONLY_ROUTE_PREFIXES = ['/league']` — and it exists for a **data-leak** reason,
not a performance one. So every other private page, including a Next 404, fetches the
player contract.

**W26-F002, P2 (verifier lowered it from P1), verdict `rescoped`.** The core
mechanism is confirmed — a cold `/news` hard load does fetch `/api/dynasty-data`.
Three parts of the author's claim did not survive:

- "decode 11.7–13.1 MB" is the sum of `decodedBodySize` over **all** resource
  entries, not the contract. The contract is **6,515,205 b decoded / 671,811 b on the
  wire**. A further 3,897,831 b decoded / 369,861 b wire is the *second* request,
  `POST /api/rankings/overrides?view=delta`. The remaining ~1.3 MB is app JS/CSS any
  page must load. The numericProof's formula charged the Next bundle to this defect.
- "On mobile this is the dominant cost of every navigation" is **false.** AppShell
  lives in the root layout and does not remount on client-side navigation, and
  `dynasty-data.js:1413-1440` adds a module cache with a 30 s TTL plus in-flight
  dedupe. Measured: clicking from `/rankings` to `/news` produced **exactly one**
  `/api/dynasty-data` request in total. The probe's per-page cost is an artifact of
  a fresh `page.goto` per route.
- "A mistyped URL costs 1.0 MB" is true of a **cold context only**, ~0.67 MB of which
  is the contract.

Verified position: a real but ordinary inefficiency — a **cold entry** on a
board-less page pays ~672 KB wire and a 6.5 MB JSON parse it does not use, to keep
global search and the player popup working. The index those two need is
name + id + position + value, roughly **90 KB** for 1,092 rows — about 1.5% of the
current bytes.

### 6.5 Blocking external calls on the request path

| Call | Where | Timeout | Bounded? |
|---|---|---|---|
| KTC live scrape | `_get_ktc_rookies` → `_fetch_ktc_rookies_live` | 15 s `urlopen` | **No negative cache** — re-attempted on every 300 s miss, forever |
| Sleeper team-name mapping | draft-capital path | up to 5–6 calls | With 6 × 15 s timeouts the worst case is **~90 s of a threadpool worker** |
| nflverse id map / weekly stats / snap counts | `bdvm` context + schedule | 60 s ×2 on schedule | 433 MB cold; **discarded unread** (§6.1) |
| nflverse seasons | `/api/league-comparison` | — | 26,577 ms cold, 7-day disk cache, **no build lock** |
| `sleepercdn.com` avatars | `/rankings`, `/rosters`, `/finder` | — | **70 / 25 / 71** requests still pending at probe end — see below |

On the KTC path: `_parse_draft_data` logs *"KTC parse returned only 0 rookies, likely
blocked"* on **every single invocation**, and because only success is memoised, the
failing 15 s scrape recurs on every cache miss. Cost breakdown measured: openpyxl
cold 1.27 s / warm 0.64 s, five Sleeper calls 1.20 s, `_fetch_draft_capital`
end-to-end **2.5 s** per miss with everything warm and reachable (W10-F008).

Anonymous callers can force that rebuild: `/api/draft-capital` returns **200 with
real per-pick dollar values to an unauthenticated caller in 13,188 ms** (W00-F001,
P1) — every other value-bearing route correctly 401s. At a 300 s TTL that is
**288 forced rebuilds per day per league** from an unauthenticated client, ≈775
server-seconds/day at the 2.692 s figure (W26-F008). Redaction happens *after* the
build, so redaction does not bound the cost.

On the avatars: `/rankings` issues **142 total requests, 70 of them still pending at
probe end, all `sleepercdn.com`** — roughly half of all requests on the page are
third-party per-player thumbnails. The protocol pre-declares CDN unreachability as a
container artifact, and it is: **do not read the pending count as a production
defect.** The structural fact that survives is that the page opens ~70 concurrent
third-party image connections, and that this is what makes network-idle never fire in
this environment.

### 6.6 Repeated population rebuilds (no user-visible cost today)

`/api/sharp/market` and `/api/sharp/cohort` each call
`platform_records.build_manager_records` — a full `SELECT * FROM manager_seasons` plus
two GROUP BYs, then `score_managers` over the whole population — **twice per
request**. `/api/sharp/roster-percentage` calls it once. The only `lru_cache` in
`src/sharp` is on two small JSON config loaders. Cost is invisible today at 0 rows;
it is O(season_rows) SQL + O(N log N) scoring per request at the scale the discovery
crawl is designed to reach (W15-F017, P3).

### 6.7 Stampede exposure — code-structure claim, not load-tested

Four caches on the slowest measured routes hold their lock only across the dict
get/put, never across the build: `bdvm_api._context_for` / `_schedule_for`,
`bdvm_api.get_bdvm_values`, `league_comparison.build_comparison` (no lock at all),
and `gameplan.get_league_bundle` (whose own docstring says "only the ~1.35 s solve is
cached"). N concurrent cold `/api/bdvm/*` requests would each launch a full 433 MB
nflverse download; with 40 threadpool workers that saturates the pool for ~48 s.

**We did not run a concurrency test.** W26-F005 is P2 at `confidence: medium` and is
arithmetic over a code read. The repo demonstrably knows the pattern — four other
caches implement per-key single-flight with the reasoning written down — so this is a
consistency gap, not an unknown technique.

---

## 7. Optimisations that serve a different answer

The brief's rule: *a faster page serving stale or inconsistent values is not a
successful optimisation.* Three cases qualify.

### 7.1 The delta payload is 67% smaller and returns a different board — **P0**

`POST /api/rankings/overrides?view=delta` is the platform's headline payload
optimisation: 3.74 MB instead of 11.27 MB, 350 KB on the wire, and **byte-faithful**
— across 1,092 rows and the fields `rankDerivedValue`, `canonicalConsensusRank`,
`canonicalTierId`, `confidence`, the delta and the full contract agree on **every
single row, 0 mismatches**.

The optimisation is sound. The *call* is not. `SETTINGS_DEFAULTS.tepMultiplier = 1.15`
is a finite number and `tepMultiplierIsCustomized()` returns true for any finite
number, so `customized` is true **on a browser with empty localStorage**. The first
request `/rankings` makes is that POST with body `{"tep_multiplier": 1.15}`, which
sets `tep_multiplier_is_override=True`, which makes `data_contract.py:6939` skip the
ADR-015 TE-basis conversion entirely.

Result: the board the user reads differs from `GET /api/data` — which every
server-side engine prices from — on **135 values (82 TE, 50 PICK, 3 other), 627 ranks
and 654 tiers**. Brevin Jordan renders as **1,243** on `/rankings` while
`/api/waiver/faab-recommend` answers **1,519.0** for the same player in the same
session. Three TEs priced by `/api/data` fall out of the rendered board entirely and
display as **0**. The "Custom Mix" badge gates on `rankingsOverride.isCustomized`,
which the backend stamps **false** for a tep-only override — so the one warning that
exists is structurally suppressed on exactly this state.

**W07-F001, P0, verifier verdict `rescoped`, severity held.** The verifier reproduced
every leg on today's stack including the DOM numbers, and *widened* the blast radius:
`pagesAffected` 5 → ~30 (AppShell hydrates the 1.15 board app-wide, feeding the
player popup and global search everywhere), `routesAffected` 6 → 11. `/draft` was
reclassified — it reads `/api/data` directly, so it renders **both boards on one
page**.

This is the audit's cleanest example of the rule. The fast path is correct as a
transport; it is being asked the wrong question, and it is faster at being wrong.

### 7.2 `/draft`'s `cache: "no-store"` is the honest choice made for the wrong reason

Two of `/draft`'s three `/api/data` call sites pass `cache: "no-store"`, defeating a
working ETag/304. Removing `no-store` is the right fix for §6.3 — **but only
alongside 7.1.** `/draft` currently reads `/api/data` directly (the engine board)
while the popup on the same page reads the 1.15 board. Making the `/api/data` fetch
cacheable makes that page *faster at rendering two mutually inconsistent boards*.
Sequence: fix `SETTINGS_DEFAULTS.tepMultiplier` first, then the cache headers.

### 7.3 The Top Movers empty state reads as a market fact

`GET /api/movers` returns `{"window":0,"windowRequested":14,"historyDepthDays":0,
"asOf":null,"risers":[],"fallers":[]}`. `MoversPanel.jsx:154-164` reads only
`risers`/`fallers` and builds its subtitle from local state, so the home page prints
*"Rank deltas vs. 14d ago"* over two columns of *"No qualifying movers in this
window."* A 14-day rank delta was never computed.

**W26-F010, authored P1, verified `rescoped` to P2.** Four corrections to the
author's original claim, all reported here as the verified position:

- The `MarketTicker` half is **refuted.** `MarketTicker` never touches `/api/movers`;
  it reads the contract's per-row `rankChange`, which is populated (694 ints, 572
  nonzero). The "Market quiet" string appeared because no team was selected — a
  different defect.
- The alarming state is **container-conditional**: `data/rank_history.jsonl` does not
  exist here because the audit harness suppresses the scrape that writes it.
- The author's title said "vs. 30d ago"; the default is `useState(14)` and the page
  renders "14d". Self-inconsistent.
- `playersAffected: 1092` is unfounded; the panel shows at most 16 rows.

What is **durable and production-live**: whenever `window < windowRequested` — which
the backend docstring says is the normal case today — the subtitle labels an N-day
delta with the requested span. The backend is exemplary and not at fault: it
separates measured from requested window and publishes `historyDepthDays` and a null
`asOf`. The frontend reads none of the three. Display-only fix.

---

## 8. What works

A list of only defects is not an audit. These are measured positives.

| Result | Evidence |
|---|---|
| **41/41 Next pages return 200; 38 render an `<h1>`; median DOM-ready 83 ms, max 609 ms.** The only genuine client errors are a correct 401, a correct 403 (test user deliberately not allowlisted) and a correct 503 (`consensus_edge` flag off per ADR-023). | W00-F009, *Implemented and verified* |
| **Every Next page bundle is under its own CI budget**, `BUILD_EXIT=0`. Tightest headroom: `/draft` 125.6 / 128 KB, `/rankings` 62.0 / 65 KB. | `evidence/frontend-build.txt` |
| **GZipMiddleware does the heavy lifting**: 11.95 MB → 1.18 MB on the wire, a 9.84% ratio. | §3.1 |
| **`/api/data` conditional GET works and is free**: 304 in **2.8 ms, 0 bytes**, with `Vary: Accept-Encoding`. | re-verified today |
| **Six routes set a sensible, differentiated `Cache-Control`** — TTLs matched to volatility, all with `stale-while-revalidate`. | §4.1 |
| **Four caches implement per-key single-flight correctly**, with the reasoning written down: `_OVERLAY_RESPONSE_CACHE`, `_OVERRIDES_RESPONSE_CACHE`, `_DRAFT_CAPITAL_CACHE`, `_heavy_section_cache`. `_heavy_section_cache` goes further — waiters block on the event loop, not in the threadpool, so they do not hold worker tokens hostage. | W26-F005 `whatWorks` |
| **The public-league cache is the reference implementation**: stale-while-revalidate, a suppression flag on the background refresh thread, and hit/miss/stale counters. | W26-F005 |
| **Cache keys are league-aware nearly everywhere**: `_OVERRIDES_` keys on 4 dimensions and *refuses* to cache the `leagueAdjusted` path rather than risk it; `gameplan._BUNDLE_CACHE` keys on a source stamp rather than a clock. One cache misses (§5). | W26-F018 `whatWorks` |
| **The delta payload is byte-faithful**: 0 field mismatches vs `view=full` across 1,092 rows. | W07-F001, W07-F005 |
| **The per-row compaction in `compact_view.py` is correct and effective**: 55 fields → 41, `playersArray` 6.13 MB → 3.66 MB. It is cancelled by a separate mistake, not wrong itself. | W26-F001 |
| **Caching converts every cold path except one into a millisecond path**: 47,994 → 4 ms, 26,577 → 6 ms, 2,735 → 5 ms. | §1.4 |
| **Zero duplicate API URLs** across all 28 page/viewport combinations; the shell fetch is one request per page with ETag revalidation, gzip, a stream-through Next bridge and an idle-abort timeout. | `page-ux-probe.json` |
| **Client-side caching is real**: `useDynastyData` 30 s module cache + in-flight dedupe (a nav from `/rankings` to `/news` produced exactly one request); `PlayerPopup._realizedCache` 30 min with **negative caching**; `useTerminal` keys on `valuationMode`. | W26-F002 verification, W26-F006, W26-F009 |
| **The BDVM refusal is exemplary**: `no_projection_snapshot` with an actionable message and no fabricated projections. Its actuals layer returns fetch failures but **never memoises them** — a genuinely good cache-poisoning guard. | W26-F004 `whatWorks` |
| **`_fetch_draft_capital`'s per-league single-flight, threadpool offload and per-response redaction copy all work**: authenticated cache hits at 6 ms and 4 ms, event loop never blocked, no cross-viewer leak. | W10-F008, W26-F008 |
| **The movers backend tells the truth** — it separates measured from requested window and publishes `historyDepthDays` + a null `asOf`. Everything the UI needs to be honest is already in the payload. | W26-F010 |

---

## 9. Ranked fixes

Ranked by (user harm) × (bytes or seconds recovered) ÷ (size of change). Priorities
are the **verified** ones where a verifier ran; unverified findings are marked.

| # | Fix | Finding | Verified priority | Size | Recovers |
|---|---|---|---|---|---|
| **1** | `SETTINGS_DEFAULTS.tepMultiplier` → `null`; drop the migration that rewrites null to 1.15. Then re-verify a cleared-localStorage load fires no override POST. | W07-F001 | **P0** (`rescoped`, held) | S | Removes a 350 KB POST from every session's critical path **and** makes `/rankings` agree with all 11 engine routes. The only fix on this list that is a correctness fix and a perf fix at once. |
| **2** | Delete the legacy `players` dict from the `compact` payload — parity with what `array` already does. Then correct the four "~90%" comments. | W26-F001 | **P1** (`upheld`) | **XS** | compact 7.36 MB → ~4.03 MB. Mobile stops paying 95,504 more wire bytes than desktop. Highest bytes-per-line-changed on the list. |
| **3** | `if snapshot is None`, pass `context={}` / `schedule_weeks=None` instead of calling `_context_for` / `_schedule_for`. Separately cut `schedule.py`'s second 60 s retry. | W26-F004 | P1 (unverified) | **XS — 3 lines** | 48 s → ~0 on first `/bdvm` load after any restart; removes a 120 s worst case from a request path. |
| **4** | Point `/draft`'s mount-time call at `?view=startup` (or serve `sleeper.teams` from `/api/leagues`, which `/draft` already fetches at 840 b) and drop `cache: "no-store"`. **Do this after #1** (§7.2). | W26-F003 | **P1** (`rescoped`, held) | S | `/draft` transferred bytes ≈2.25 MB → ≈1.07 MB, matching `/rankings`. |
| **5** | Apply the auth gate every other value-bearing route uses to `/api/draft-capital`; memoise the KTC failure with a short backoff; move the KTC fetch off the request path. | W00-F001, W10-F008, W26-F008 | P1 / P2 (unverified) | S | Closes a data leak **and** removes ~775 server-seconds/day of unauthenticated forced rebuilds. |
| **6** | Add an in-process memo above `src/nfl_data/cache.py` keyed on (cache key, file `mtime_ns`), and build a GSIS-id index once instead of a 19,421-row scan per request. | W26-F006 | P2 (unverified) | S | ~0.84 s → ~0 per player popup; the only slow *steady-state* route in the corpus. |
| **7** | Split `useDynastyData` into a lightweight search-index fetch (name / playerId / position / value, ~90 KB) that AppShell always makes, and a full-board fetch board pages opt into. | W26-F002 | **P2** (`rescoped` down from P1) | M | ~672 KB wire + a 6.5 MB parse off every cold entry on a board-less page. First-paint cost only — the module cache already bounds repeats. |
| **8** | Drop `sourceRankMeta` from the delta; fetch it per-row when the audit panel expands. | W07-F005 | P2 (unverified) | S | 2.20 MB of 3.74 MB — 59% of the delta. |
| **9** | Port the existing per-key single-flight pattern to `bdvm_api._context_for`/`_schedule_for`, `get_bdvm_values`, `league_comparison.build_comparison` and `gameplan.get_league_bundle`. | W26-F005 | P2 (unverified, `confidence: medium`) | M | Caps concurrent cold cost at 1× instead of N×. Load-test first — this is the one entry not backed by a measurement. |
| **10** | Add `Cache-Control` + a content ETag to `/api/bdvm/*` and `/api/valuation/league-adjusted`; both payloads are already versioned (`paramSetId` / `configHash` / `asOf` / league factors stamp). | W26-F009 | P2 (unverified) | XS | 48,555 b re-sent per navigation → 0 on a 304. |
| **11** | Add `stale_ok` to `src/nfl_data/cache.py` (serve stale on refetch failure with a staleness stamp), a total-bytes budget with oldest-first eviction, and key weekly stats per season rather than per year-list. | W26-F007 | P2 (unverified) | M | Removes the full-data→no-data cliff; reclaims 123,413,676 duplicated bytes; stops unbounded disk growth. |
| **12** | Branch `MoversPanel` on `historyDepthDays === 0 \|\| asOf === null` first, and say so when `window < windowRequested`. Display-only; no backend change. | W26-F010 | **P2** (`rescoped` down from P1) | XS | Stops a data gap reading as a market fact. |
| **13** | Give `_resolve_league_context` a `league_key` parameter and key the cache on it. **Sequence with W18-F001** (§5). | W26-F018 | P3 (unverified) | XS | Prevents a per-league TE bonus / team count from being served from the default league. |
| **14** | Correct the payload figures in `CLAUDE.md`; fix `docs/ARCHITECTURE.md`'s `/api/data?view=delta`; make `/api/data` reject an unknown `view` with 400 instead of silently serving the default; add a production-scale size assertion. | W25-F002, W25-F007, W26-F019, W00-F003 | P2/P3 (unverified) | S | Stops a documentation defect from being the mechanism by which a performance defect ships (§3.4). |
| **15** | Partition the members already returned by `cohort_members` instead of calling it a second time; add a TTL memo keyed on the ledger's (`mtime_ns`, size). | W15-F017 | P3 (unverified) | S | Halves per-request population rebuilds. No user-visible cost today. |
| **16** | Drop the `id(contract)` term from the BDVM values cache key. | W13-F017 | P3 (unverified) | XS | Removes a theoretical key collision that `generatedAt` already guards better. |

---

## 10. What we could not test

These are results too. Not testing something is not the same as finding it sound.

| Not established | Why |
|---|---|
| **Behaviour under concurrency.** No load test, no parallel-request harness. The stampede exposure in §6.7 (W26-F005, `confidence: medium`) is arithmetic over a code read: `N × coldMs` is a structural claim about lock scope, not an observed pileup. | Read-only protocol; no load-generation tool sanctioned |
| **Production hardware and network.** Every latency here is a shared container over loopback. Real-network mobile behaviour — where the 95,504-byte compact penalty and the 350 KB delta POST actually cost time — is unmeasured. | No production access |
| **nginx-layer compression, caching and buffering.** All header observations are from FastAPI directly. `deploy/nginx/chaseupside-proxy.conf` was read, not exercised. | Container has no nginx |
| **Cold-cache first-entry mobile trace.** The verifier's own `whatWouldSettleIt` for W26-F002 asks for the contract fetch isolated from the bundle on a genuine first entry, plus a >30 s-TTL revalidation to confirm the per-navigation cost is ~0. Not captured. | Out of time; the module-cache result was measured on warm navigation only |
| **`/api/bdvm/*` at real payload size.** `/api/bdvm/values` measured 792 bytes because `data/bdvm/` does not exist in this container (pre-declared *Blocked by data*). Its size and latency **with** a projection snapshot is unknown — so fix #10's benefit is bounded below, not above. | No BDVM snapshot |
| **`/api/league-comparison` warm-vs-cold beyond one cold miss.** 26,577 ms was observed once; the 7-day disk TTL means the cold path is rare and was not re-triggered. | Single observation |
| **34 non-GET routes.** Only GET routes were latency-probed. POST computation endpoints (`/api/trade/*`, `/api/angle/*`, `/api/waiver/*`) have no latency or payload numbers in this document except `/api/rankings/overrides`. | Probe scope |
| **`sleepercdn.com` avatar cost in production.** 70 pending requests on `/rankings` is a container-egress artifact per the protocol. Whether ~70 concurrent third-party image connections is a real production cost is untested. | External CDN unreachable |
| **Sharp-route cost at scale.** W15-F017's O(N log N) rebuild is invisible at the current 0 rows. The scale at which it becomes the slowest surface on the site is a projection, not a measurement. | No populated platform ledger |
